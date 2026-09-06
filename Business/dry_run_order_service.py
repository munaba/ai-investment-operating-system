"""DryRunOrderService -- Activation 8.2 (broker-agnostic dry-run flow).

Purpose
-------
Given an order *request* (never persisted, never executed), produce a
deterministic preview of what would happen if that request were
submitted for real -- without ever calling a broker, opening a
network connection, or assuming any particular broker's endpoint
shape. This is groundwork for a *future* live-order path: today it
only answers "what would this order look like", it never places one.

Pipeline (LOCKED order, matches the Activation 8.2 brief exactly):

    request -> validation -> estimated value -> fee -> risk ->
    approval -> dry-run result

Each stage is produced by *reusing* an already-existing component --
this module defines no new validation rule, no new fee formula, no
new risk formula, and no new approval rule of its own:

    * validation  -- ``Business.order_lifecycle_service.
      OrderLifecycleService._validate`` (the exact same structural
      rule chain Sprint 4 uses before persisting a real ``Order``),
      called directly as a ``staticmethod`` so this service never
      needs an ``OrderRepository`` and never writes a row.
    * fee/tax     -- ``Business.execution_policy_config.
      ExecutionPolicy`` (the same policy object ``ExecutionService``
      reads from), selected by ``action`` with the exact same
      by-side rule ``ExecutionService.execute_order`` already uses
      (BUY -> ``buy_fee_rate``/no tax, SELL -> ``sell_fee_rate``/
      ``sell_tax_rate``). No multiplication/formula is invented here
      -- exactly like ``ExecutionService``, this is still a
      placeholder rate until a dedicated fee/tax formula Activation
      exists.
    * risk        -- ``Services.risk_management_service.
      RiskManagementService`` (unmodified), invoked through its
      normal ``ServiceContext``/``ServiceResult`` contract. Optional:
      a dry-run request that does not supply risk parameters simply
      skips this stage (``risk_status="SKIPPED"``) rather than
      failing the whole dry run.
    * approval    -- ``Orchestration.order_validation_skill.
      OrderValidationSkill`` (unmodified), fed the request's
      ``action``/estimated value as an already-allocated entry, the
      exact shape it already consumes. Its four-rule verdict
      (APPROVED/HOLD/EXIT/REJECTED) becomes this dry run's approval
      verdict.

No broker API, no network call, no real ``Order``/``Trade`` row, and
no endpoint/broker-specific assumption appears anywhere in this
module -- every field on ``DryRunResult`` is derived purely from the
caller-supplied request plus the four reused components above, all
of which are pure/in-memory (``OrderLifecycleService._validate`` and
``OrderValidationSkill.execute`` never touch I/O; ``ExecutionPolicy``
is a frozen value object; ``RiskManagementService.execute`` is a pure
calculation over its input metadata). ``DryRunResult`` additionally
carries three explicit witness flags -- ``broker_called``,
``network_called``, ``order_persisted`` -- all permanently ``False``,
so a caller (or a test) can assert the dry-run contract without
having to inspect this module's internals.

Paper trading (``Business.paper_trading_engine.PaperTradingEngine``)
is untouched: this module does not import it, does not subclass it,
and does not change its behavior in any way. A dry run and a paper
trade are two independent flows that happen to reuse the same
lower-level components.

Activation 8.3 update ("HUMAN APPROVAL ONLY")
----------------------------------------------
The approval stage above (``OrderValidationSkill``) is, and remains,
a fully *automatic* rule chain -- see
``Core.human_approval_port`` for the audit establishing that neither
it nor any existing ``Core.approval`` port ever consults an actual
human. Activation 8.3 adds exactly the missing piece: a
``Core.human_approval_port.HumanApprovalPort`` gate, consulted as an
additional pipeline stage after the automatic approval stage. Its
outcome is reported on ``DryRunResult`` as
``human_approval_status``/``human_approval_reviewer``/
``human_approval_note``, alongside (not instead of) the unchanged
automatic ``approval_status``/``approval_reason`` fields -- the
automatic verdict is kept as a recommendation; the human gate is the
decision. ``DryRunResult.would_submit`` now requires *both*: the
automatic recommendation must be ``"APPROVED"`` *and* a human must
have explicitly recorded ``approved=True`` for this same request
(``human_approval_status == "APPROVED"``). By default -- i.e. for
any request no human has looked at yet -- ``human_approval_status``
is ``"PENDING"`` and ``would_submit`` is ``False``, even when the
automatic recommendation is ``"APPROVED"``. This is the entire
Activation 8.3 contract: nothing is ever ready to submit on an
automatic verdict alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from Business.execution_policy_config import ExecutionPolicy, load_execution_policy
from Business.order_lifecycle_service import OrderLifecycleService
from Core.human_approval_port import ApprovalOutcome, HumanApprovalPort
from Orchestration.order_validation_skill import OrderValidationSkill
from Services.metadata_keys import MetadataKeys
from Services.risk_management_service import RiskManagementService
from Services.service_context import ServiceContext

#: Action this service treats as "BUY" when selecting which
#: ``ExecutionPolicy`` fee rate applies and which ``ExecutionService``
#: tax rule applies. Mirrors ``Business.execution_service._BUY`` --
#: re-declared here rather than imported, same reasoning that module
#: already gives for not importing another LOCKED module's private
#: attribute.
_BUY = "BUY"

#: Reason text for a request that clears structural validation.
#: Mirrors ``Business.order_lifecycle_service._REASON_VALIDATED``.
_REASON_VALIDATED = "structural validation passed"

#: Reason text for a request that never reaches the approval stage
#: because it failed structural validation first.
_REASON_APPROVAL_SKIPPED = "approval not evaluated: order failed structural validation"

#: risk_status values.
RISK_STATUS_COMPUTED = "COMPUTED"
RISK_STATUS_SKIPPED = "SKIPPED"
RISK_STATUS_FAILED = "FAILED"

#: human_approval_status values. The first three are the exact string
#: values of ``Core.runtime.ApprovalOutcome`` (reused, not
#: reinvented); ``"SKIPPED"`` is added only for the case validation
#: already failed and the human gate was never consulted, mirroring
#: ``RISK_STATUS_SKIPPED`` above.
HUMAN_APPROVAL_PENDING = ApprovalOutcome.PENDING.value
HUMAN_APPROVAL_APPROVED = ApprovalOutcome.APPROVED.value
HUMAN_APPROVAL_DENIED = ApprovalOutcome.DENIED.value
HUMAN_APPROVAL_SKIPPED = "SKIPPED"

#: The four ``ServiceContext.metadata`` keys ``RiskManagementService``
#: requires, expressed as the caller-facing dry-run parameter names.
#: All four (plus ``requested_price`` as ``entry_price``) must be
#: supplied for the risk stage to run; any missing one skips the
#: stage entirely rather than failing the dry run.
_RISK_PARAM_KEYS = (
    "stop_loss_percent",
    "take_profit_percent",
    "risk_per_trade_percent",
    "account_balance",
)


@dataclass(frozen=True)
class DryRunResult:
    """Everything a dry run produced, one field per pipeline stage.

    Attributes:
        request: Echo of the caller's input, unchanged.
        validation_status: ``"PASSED"`` or ``"REJECTED"``.
        validation_reason: Human-readable reason, or one of
            ``Business.order_lifecycle_service.REJECTION_REASONS`` if
            ``validation_status == "REJECTED"``.
        estimated_value: ``quantity * requested_price``, or ``None``
            if validation failed (no downstream stage runs).
        fee: The fee this order would carry, sourced from
            ``ExecutionPolicy`` exactly as ``ExecutionService`` reads
            it. ``None`` if validation failed.
        tax: The tax this order would carry, same sourcing as
            ``fee``. ``None`` if validation failed.
        estimated_net_amount: For a BUY, the cash that would be
            required (``estimated_value + fee + tax``); for a SELL,
            the proceeds that would be received
            (``estimated_value - fee - tax``). ``None`` if validation
            failed.
        risk_status: ``"COMPUTED"``, ``"SKIPPED"`` (risk parameters
            not supplied), or ``"FAILED"`` (``RiskManagementService``
            rejected the supplied risk parameters).
        risk: ``RiskManagementService``'s computed
            ``stop_loss_price``/``take_profit_price``/``risk_amount``/
            ``position_size``/``risk_reward_ratio`` dict when
            ``risk_status == "COMPUTED"``; the service's failure
            message when ``risk_status == "FAILED"``; ``None`` when
            ``"SKIPPED"``.
        approval_status: ``OrderValidationSkill``'s *automatic*
            recommendation -- ``"APPROVED"``/``"HOLD"``/``"EXIT"``/
            ``"REJECTED"`` -- or ``None`` if validation failed first
            (approval never runs). Unchanged since Activation 8.2;
            never itself sufficient to submit as of Activation 8.3
            (see ``would_submit``).
        approval_reason: The matching reason text from
            ``OrderValidationSkill``, or the skip reason when
            validation failed first.
        human_approval_status: The Activation 8.3 human decision gate
            -- ``"PENDING"`` (no human has decided yet, the default),
            ``"APPROVED"``, ``"DENIED"``, or ``"SKIPPED"`` (validation
            failed first, the gate was never consulted). Sourced from
            ``Core.human_approval_port.HumanApprovalPort.check()``.
        human_approval_reviewer: The reviewer identity recorded with
            the human decision, if any and if one was recorded.
        human_approval_note: The free-text note recorded with the
            human decision, if any and if one was recorded.
        status: The overall dry-run verdict. Equal to
            ``validation_status`` (``"REJECTED"``) when structural
            validation failed; otherwise equal to ``approval_status``
            (the automatic recommendation) -- ``status`` reports the
            *recommendation*, ``would_submit`` reports whether it is
            actually authorized to proceed.
        would_submit: ``True`` iff *both* ``approval_status ==
            "APPROVED"`` (automatic recommendation) *and*
            ``human_approval_status == "APPROVED"`` (explicit human
            decision) -- the Activation 8.3 contract: an automatic
            recommendation alone is never enough. Always ``False`` in
            this Activation since nothing is ever actually submitted
            regardless of this flag's value.
        broker_called: Always ``False``. No broker API is invoked
            anywhere in this module.
        network_called: Always ``False``. No network call is made
            anywhere in this module.
        order_persisted: Always ``False``. No ``Order``/``Trade`` row
            is ever created by this module.
        dry_run: Always ``True``.
    """

    request: dict[str, Any]
    validation_status: str
    validation_reason: str
    estimated_value: Optional[float]
    fee: Optional[float]
    tax: Optional[float]
    estimated_net_amount: Optional[float]
    risk_status: str
    risk: Optional[dict[str, Any]]
    approval_status: Optional[str]
    approval_reason: str
    human_approval_status: str
    human_approval_reviewer: Optional[str]
    human_approval_note: Optional[str]
    status: str
    would_submit: bool
    broker_called: bool = field(default=False)
    network_called: bool = field(default=False)
    order_persisted: bool = field(default=False)
    dry_run: bool = field(default=True)


class DryRunOrderService:
    """Runs the Activation 8.2 dry-run pipeline for a single order
    request, entirely in-memory.

    Depends only on already-existing, already-LOCKED components,
    each reused unmodified:

        * ``Business.order_lifecycle_service.OrderLifecycleService``
          (its ``_validate`` staticmethod only -- no repository, no
          instance, no persistence);
        * ``Business.execution_policy_config.ExecutionPolicy``;
        * ``Services.risk_management_service.RiskManagementService``;
        * ``Orchestration.order_validation_skill.OrderValidationSkill``;
        * ``Core.human_approval_port.HumanApprovalPort`` (Activation
          8.3).

    This service opens no database connection, no network socket,
    and calls no broker of any kind -- it has no attribute through
    which it could reach one.
    """

    def __init__(
        self,
        execution_policy: ExecutionPolicy | None = None,
        order_validation_skill: OrderValidationSkill | None = None,
        risk_management_service: RiskManagementService | None = None,
        human_approval_port: HumanApprovalPort | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            execution_policy: Canonical ``ExecutionPolicy`` this
                service reads its ``fee``/``tax`` placeholder values
                from. Defaults to
                ``Business.execution_policy_config.
                load_execution_policy()``, mirroring
                ``ExecutionService``'s own default.
            order_validation_skill: The reused approval-verdict
                component. Defaults to a fresh
                ``OrderValidationSkill()`` (it is stateless).
            risk_management_service: The reused risk-computation
                component. Defaults to a fresh
                ``RiskManagementService()`` (it is stateless).
            human_approval_port: The Activation 8.3 human-decision
                gate. Defaults to a fresh ``HumanApprovalPort()`` --
                unlike the other three collaborators this one is
                stateful (it holds recorded decisions), so a caller
                that wants to record a decision for a request before
                calling ``dry_run()`` should construct one explicitly
                and pass it in here, or use the
                ``human_approval_port`` property to reach the
                instance this service is already using.
        """
        self._execution_policy = execution_policy if execution_policy is not None else load_execution_policy()
        self._order_validation_skill = (
            order_validation_skill if order_validation_skill is not None else OrderValidationSkill()
        )
        self._risk_management_service = (
            risk_management_service if risk_management_service is not None else RiskManagementService()
        )
        self._human_approval_port = (
            human_approval_port if human_approval_port is not None else HumanApprovalPort()
        )

    @property
    def human_approval_port(self) -> HumanApprovalPort:
        """The ``HumanApprovalPort`` instance this service consults.

        Exposed so a caller can record a human decision
        (``human_approval_port.record_decision(decision_key, ...)``)
        for the same ``decision_key`` it will later pass to
        ``dry_run()`` -- without this service needing to expose a
        ``record_decision()``-shaped method of its own.
        """
        return self._human_approval_port

    def dry_run(
        self,
        account_id: str,
        symbol: str,
        action: str,
        quantity: float,
        requested_price: float,
        analysis_snapshot_id: Optional[int] = None,
        stop_loss_percent: Optional[float] = None,
        take_profit_percent: Optional[float] = None,
        risk_per_trade_percent: Optional[float] = None,
        account_balance: Optional[float] = None,
        request_id: str = "dry-run",
        human_decision_key: Optional[str] = None,
    ) -> DryRunResult:
        """Run the full dry-run pipeline for one order request.

        Never raises for a bad/rejectable request -- every business
        outcome (structural rejection, risk-parameter rejection,
        approval rejection) is reported on the returned
        ``DryRunResult`` instead, mirroring the never-raise style
        already used by ``OrderValidationSkill``/
        ``RiskManagementService``.

        Args:
            account_id: Owning account's ``account_id``. Echoed back
                on ``request`` only -- not itself validated (matches
                ``OrderLifecycleService.create_order``).
            symbol: Traded symbol/ticker.
            action: Requested action. Must be ``"BUY"`` or ``"SELL"``
                to pass structural validation.
            quantity: Requested quantity. Must be a positive
                ``int``/``float`` to pass structural validation.
            requested_price: Requested price. Must be a positive
                ``int``/``float`` to pass structural validation. Also
                used as ``entry_price`` for the risk stage.
            analysis_snapshot_id: Optional, echoed back on ``request``
                only, same treatment as
                ``OrderLifecycleService.create_order``.
            stop_loss_percent: Optional risk input. The risk stage
                only runs when this and the next two args, together
                with ``account_balance``, are all supplied.
            take_profit_percent: Optional risk input, see above.
            risk_per_trade_percent: Optional risk input, see above.
            account_balance: Optional risk input, see above.
            request_id: Correlation id passed through to the
                ``ServiceContext`` built for the risk stage. Purely
                for traceability; never inspected by this method.
                Also used as the default human-approval
                ``decision_key`` when ``human_decision_key`` is not
                supplied.
            human_decision_key: The key this call looks up on
                ``human_approval_port`` for the Activation 8.3 human
                decision gate. Defaults to ``request_id`` when not
                supplied, so the common case (one id per dry-run
                request) needs only one argument. A caller that wants
                the risk-stage correlation id and the human-decision
                key to differ can pass both explicitly.

        Returns:
            A fully populated ``DryRunResult``. No I/O of any kind
            occurs while producing it.
        """
        request_snapshot: dict[str, Any] = {
            "account_id": account_id,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "requested_price": requested_price,
            "analysis_snapshot_id": analysis_snapshot_id,
        }

        # --- Stage: validation (reused, structural, no persistence) ---
        rejection_reason = OrderLifecycleService._validate(symbol, action, quantity, requested_price)

        if rejection_reason is not None:
            return DryRunResult(
                request=request_snapshot,
                validation_status="REJECTED",
                validation_reason=rejection_reason,
                estimated_value=None,
                fee=None,
                tax=None,
                estimated_net_amount=None,
                risk_status=RISK_STATUS_SKIPPED,
                risk=None,
                approval_status=None,
                approval_reason=_REASON_APPROVAL_SKIPPED,
                human_approval_status=HUMAN_APPROVAL_SKIPPED,
                human_approval_reviewer=None,
                human_approval_note=None,
                status="REJECTED",
                would_submit=False,
            )

        # --- Stage: estimated value ---
        estimated_value = float(quantity) * float(requested_price)

        # --- Stage: fee (reused ExecutionPolicy, same selection rule
        # as Business.execution_service.ExecutionService) ---
        fee = self._execution_policy.buy_fee_rate if action == _BUY else self._execution_policy.sell_fee_rate
        tax = 0.0 if action == _BUY else self._execution_policy.sell_tax_rate
        estimated_net_amount = (
            estimated_value + fee + tax if action == _BUY else estimated_value - fee - tax
        )

        # --- Stage: risk (reused RiskManagementService, optional) ---
        risk_status, risk = self._run_risk_stage(
            entry_price=requested_price,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
            risk_per_trade_percent=risk_per_trade_percent,
            account_balance=account_balance,
            request_id=request_id,
        )

        # --- Stage: approval (reused OrderValidationSkill, automatic
        # recommendation only -- not itself a submit authorization as
        # of Activation 8.3) ---
        approval_status, approval_reason = self._run_approval_stage(
            symbol=symbol,
            action=action,
            estimated_value=estimated_value,
        )

        # --- Stage: human approval (Activation 8.3, the actual
        # submit-authorization gate) ---
        decision_key = human_decision_key if human_decision_key is not None else request_id
        human_status, human_reviewer, human_note = self._run_human_approval_stage(decision_key)

        return DryRunResult(
            request=request_snapshot,
            validation_status="PASSED",
            validation_reason=_REASON_VALIDATED,
            estimated_value=estimated_value,
            fee=fee,
            tax=tax,
            estimated_net_amount=estimated_net_amount,
            risk_status=risk_status,
            risk=risk,
            approval_status=approval_status,
            approval_reason=approval_reason,
            human_approval_status=human_status,
            human_approval_reviewer=human_reviewer,
            human_approval_note=human_note,
            status=approval_status,
            would_submit=(approval_status == "APPROVED") and (human_status == HUMAN_APPROVAL_APPROVED),
        )

    def _run_risk_stage(
        self,
        entry_price: float,
        stop_loss_percent: Optional[float],
        take_profit_percent: Optional[float],
        risk_per_trade_percent: Optional[float],
        account_balance: Optional[float],
        request_id: str,
    ) -> tuple[str, Optional[dict[str, Any]]]:
        """Run the reused ``RiskManagementService`` if enough input is
        present; otherwise skip the stage without failing the dry run.

        Returns:
            A ``(risk_status, risk)`` pair -- see ``DryRunResult``'s
            ``risk_status``/``risk`` fields for the exact contract.
        """
        supplied = {
            "stop_loss_percent": stop_loss_percent,
            "take_profit_percent": take_profit_percent,
            "risk_per_trade_percent": risk_per_trade_percent,
            "account_balance": account_balance,
        }
        if any(supplied[key] is None for key in _RISK_PARAM_KEYS):
            return RISK_STATUS_SKIPPED, None

        context = ServiceContext(
            agent_name="dry_run_order_service",
            provider_name="dry_run",
            request_id=request_id,
            user_input="",
            metadata={
                MetadataKeys.ENTRY_PRICE: entry_price,
                MetadataKeys.STOP_LOSS_PERCENT: stop_loss_percent,
                MetadataKeys.TAKE_PROFIT_PERCENT: take_profit_percent,
                MetadataKeys.RISK_PER_TRADE_PERCENT: risk_per_trade_percent,
                MetadataKeys.ACCOUNT_BALANCE: account_balance,
            },
        )
        result = self._risk_management_service.execute(context)

        if not result.success:
            return RISK_STATUS_FAILED, {"error": result.message}

        return RISK_STATUS_COMPUTED, dict(result.data)

    def _run_approval_stage(
        self,
        symbol: str,
        action: str,
        estimated_value: float,
    ) -> tuple[str, str]:
        """Run the reused ``OrderValidationSkill`` and extract this
        request's single verdict from its ``"orders"`` output list.

        Returns:
            A ``(approval_status, approval_reason)`` pair, taken
            verbatim from the skill's single output entry.
        """
        context = _ApprovalContext(
            {
                "allocations": [
                    {"symbol": symbol, "action": action, "capital": estimated_value},
                ],
            }
        )
        result = self._order_validation_skill.execute(context)
        verdict = result.output["orders"][0]
        return verdict["status"], verdict["reason"]

    def _run_human_approval_stage(
        self, decision_key: str
    ) -> tuple[str, Optional[str], Optional[str]]:
        """Run the reused ``HumanApprovalPort`` (Activation 8.3) and
        translate its ``ApprovalOutcome`` plus any recorded
        ``HumanDecision`` into this stage's ``DryRunResult`` fields.

        Never raises: an unrecognized/undecided ``decision_key``
        simply yields ``"PENDING"`` with no reviewer/note, exactly
        like ``HumanApprovalPort.check()`` itself.

        Returns:
            A ``(human_approval_status, reviewer, note)`` triple.
        """
        outcome = self._human_approval_port.check(decision_key)
        decision = self._human_approval_port.get_decision(decision_key)

        if decision is None:
            return outcome.value, None, None

        return outcome.value, decision.reviewer, decision.note


class _ApprovalContext:
    """A minimal context-like object exposing only ``.parameters``,
    the exact shape ``OrderValidationSkill.execute`` reads (see that
    module's own ``_FakeContext`` test double). Kept private to this
    module -- not a new shared abstraction, just the smallest object
    that satisfies the one attribute the reused Skill needs.
    """

    def __init__(self, parameters: dict[str, Any]) -> None:
        self.parameters = parameters