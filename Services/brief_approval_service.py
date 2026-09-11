"""``BriefApprovalService`` -- Phase G (Task 2, "Approved Brief ->
Paper Link Contract").

Implements exactly the linkage identified as missing by the Phase G
Task 1 audit: ``DecisionBrief -> explicit human approval -> existing
paper buy/sell``. Nothing else.

This service invents no execution logic. It reuses exactly two
existing, LOCKED components:

    * ``Repository.persistence.decision_brief_repository.
      DecisionBriefRepository`` -- read the already-persisted,
      already-priced ``DecisionBrief`` verbatim. This service never
      calls ``DecisionBriefService``, never regenerates a brief, never
      reprices a plan.
    * ``Business.paper_trading_engine.PaperTradingEngine.submit_order``
      -- the one and only paper execution engine in this codebase.
      Called unchanged, with the brief's own verbatim plan values
      (``entry_price``/``position_size``) as ``requested_price``/
      ``quantity``. This service never submits an order itself,
      never talks to the database for orders/trades directly, and
      never touches ``OrderLifecycleService``/``ExecutionService``.

Approval semantics (LOCKED for this task):

    * Only a brief whose ``status == "SUCCESS"`` is eligible -- every
      other status (``NO_TRADE``/``DATA_STALE``/``DATA_ERROR``/
      ``INSUFFICIENT_DATA``/``ANALYSIS_FAILED``/``RISK_REJECTED``/
      ``POLICY_BLOCKED``) is rejected outright, before anything else
      is checked. A ``SUCCESS`` brief is the only status that ever
      carries a real, risk-managed plan (see
      ``Services.decision_brief_service``) -- there is nothing to
      submit for any other status.
    * ``approved`` must be passed explicitly, and must be exactly
      ``True`` -- this service never infers approval from a brief's
      mere existence, its ``SUCCESS`` status, or any other implicit
      signal. A brief being actionable is not the same fact as a
      human having approved it; conflating the two would silently
      reintroduce automatic paper submission, which this task
      explicitly forbids.
    * A brief already linked (a ``brief_approvals`` row already
      exists for it) is rejected before ``PaperTradingEngine`` is
      ever called again -- one brief, one link, enforced here AND by
      the ``brief_approvals.brief_id`` ``PRIMARY KEY`` (defense in
      depth: even if two concurrent calls both pass this in-service
      check, the database-level constraint is the final authority).
      This also means calling ``approve_and_submit`` twice for the
      same brief never submits a second paper order.

Post-commit linkage write (LOCKED, mirrors
``PaperTradingEngine.submit_order()``'s own ``OrderApprovalRepository``
write exactly): once ``submit_order()`` has returned a real, fully
committed ``Trade``, this service makes exactly one best-effort
attempt to persist the ``brief_approvals`` link row. If that write
fails, the already-committed trade is NOT rolled back -- there is
nothing to roll back to, and a paper trade is real money-shaped state
this service has no business discarding because an audit row failed
to write. The failure is instead surfaced explicitly on the returned
``BriefApprovalResult`` (``link is None``, ``link_error`` populated)
so the caller can see and act on it, rather than being silently
swallowed.

Explicitly out of scope for this task (per the Phase G Task 2 brief):
no change to ``PaperTradingEngine``, ``DecisionBriefService``, the
``decision_briefs``/``order_approvals`` schemas, Telegram, the Phase F
copilot, or risk policy. No broker/live execution. No second
execution engine -- this service is a thin caller of the existing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from Business.paper_trading_engine import PaperTradingEngine
from Core.exceptions import RepositoryError, ValidationError
from Database.models import BriefApproval, Trade
from Repository.persistence.brief_approval_repository import BriefApprovalRepository
from Repository.persistence.decision_brief_repository import DecisionBriefRepository
from Services.decision_brief_service import STATUS_SUCCESS

#: Reason codes for ValidationError.details["reason"] -- mirrors
#: PaperTradingEngine's own PRETRADE_REASON_* convention so callers
#: can branch on a stable string rather than parsing message text.
REASON_BRIEF_NOT_FOUND = "brief_not_found"
REASON_BRIEF_NOT_SUCCESS = "brief_not_success"
REASON_APPROVAL_NOT_EXPLICIT_TRUE = "approval_not_explicit_true"
REASON_ALREADY_LINKED = "brief_already_linked"


@dataclass(frozen=True)
class BriefApprovalResult:
    """Outcome of one ``approve_and_submit`` call.

    ``trade`` is always the real, fully committed ``Trade`` returned
    by ``PaperTradingEngine.submit_order()`` -- present whenever this
    dataclass is returned at all (a rejection before submission raises
    instead, it never returns a result with ``trade=None``).

    ``link`` is the persisted ``BriefApproval`` row on success, or
    ``None`` if the post-commit linkage write itself failed --
    distinguished from a submission failure specifically because the
    trade already exists and committed either way. ``link_error`` is
    the failure's ``str(exc)`` when ``link is None``, ``None``
    otherwise.
    """

    trade: Trade
    link: Optional[BriefApproval]
    link_error: Optional[str] = None


class BriefApprovalService:
    """Orchestrates one "approve this brief, submit its paper order"
    request.

    Constructor injection only, mirroring every other service/engine
    in this codebase: ``decision_brief_repository`` (read the brief),
    ``brief_approval_repository`` (persist the link),
    ``paper_trading_engine`` (the one execution engine). Stateless
    beyond these collaborators -- safe to reuse across calls.
    """

    def __init__(
        self,
        decision_brief_repository: DecisionBriefRepository,
        brief_approval_repository: BriefApprovalRepository,
        paper_trading_engine: PaperTradingEngine,
    ) -> None:
        self._decision_brief_repository = decision_brief_repository
        self._brief_approval_repository = brief_approval_repository
        self._paper_trading_engine = paper_trading_engine

    def approve_and_submit(
        self,
        brief_id: int,
        *,
        approved: bool,
        account_id: str,
        executed_at: str,
    ) -> BriefApprovalResult:
        """Link an explicitly-approved ``SUCCESS`` brief to a new
        paper order, then persist the linkage.

        Args:
            brief_id: The ``DecisionBrief.brief_id`` to approve and
                submit. Must reference an existing, ``SUCCESS``
                brief that has not already been linked.
            approved: Must be exactly ``True`` -- the caller's
                explicit human-approval decision. Never defaulted,
                never inferred.
            account_id: The paper account this order is submitted
                against. Passed through to
                ``PaperTradingEngine.submit_order()`` unchanged.
            executed_at: ISO-8601 timestamp passed through to
                ``PaperTradingEngine.submit_order()`` unchanged --
                this service generates no execution timestamp of its
                own.

        Returns:
            A ``BriefApprovalResult`` carrying the real, committed
            ``Trade`` and (best-effort) the persisted link row.

        Raises:
            ValidationError: If ``brief_id`` does not exist
                (``REASON_BRIEF_NOT_FOUND``), the brief's
                ``status != "SUCCESS"`` (``REASON_BRIEF_NOT_SUCCESS``),
                ``approved is not True``
                (``REASON_APPROVAL_NOT_EXPLICIT_TRUE``), or the brief
                is already linked (``REASON_ALREADY_LINKED``). None of
                these submits or touches ``PaperTradingEngine`` in any
                way -- every rejection here happens before that call.
            ValidationError: Also propagates unchanged from
                ``PaperTradingEngine.submit_order()`` itself if any of
                its own 19 pre-trade gates reject the order (e.g. a
                second call reusing the same deterministic
                idempotency key -- see below).
        """
        if approved is not True:
            # Checked first and unconditionally, regardless of
            # whether brief_id even exists: "never infer approval
            # from brief existence" means this gate does not need to
            # look at the brief at all to reject a non-True approval.
            raise ValidationError(
                "Explicit approval (approved=True) is required to link a "
                "DecisionBrief to a paper order.",
                details={"reason": REASON_APPROVAL_NOT_EXPLICIT_TRUE, "brief_id": brief_id},
            )

        brief = self._decision_brief_repository.get_by_id(brief_id)
        if brief is None:
            raise ValidationError(
                f"No DecisionBrief exists for brief_id={brief_id}.",
                details={"reason": REASON_BRIEF_NOT_FOUND, "brief_id": brief_id},
            )

        if brief.status != STATUS_SUCCESS:
            raise ValidationError(
                f"DecisionBrief {brief_id} has status={brief.status!r}; only a "
                f"{STATUS_SUCCESS!r} brief carries a plan and may be linked to a "
                "paper order.",
                details={
                    "reason": REASON_BRIEF_NOT_SUCCESS,
                    "brief_id": brief_id,
                    "status": brief.status,
                },
            )

        if self._brief_approval_repository.get_by_brief_id(brief_id) is not None:
            raise ValidationError(
                f"DecisionBrief {brief_id} is already linked to a paper order; "
                "one brief may be linked at most once.",
                details={"reason": REASON_ALREADY_LINKED, "brief_id": brief_id},
            )

        approved_at = datetime.now(timezone.utc).isoformat()

        # Deterministic per-brief idempotency key: a second attempt to
        # submit for the SAME brief_id (e.g. a caller retrying after
        # the pre-check above raced, or after a link-write failure
        # below) hits PaperTradingEngine's own existing idempotency
        # gate 10 and is rejected there -- never a second real order.
        idempotency_key = f"decision-brief-{brief_id}"

        trade = self._paper_trading_engine.submit_order(
            account_id=account_id,
            symbol=brief.symbol,
            action="BUY",
            quantity=brief.position_size,
            requested_price=brief.entry_price,
            executed_at=executed_at,
            signal_evidence={
                "decision_brief_id": brief_id,
                "source_snapshot_id": brief.source_snapshot_id,
            },
            user_approval=True,
            idempotency_key=idempotency_key,
        )

        # Best-effort, post-commit linkage write -- mirrors
        # PaperTradingEngine's own OrderApprovalRepository write
        # exactly. The trade above is already fully committed; a
        # failure here is surfaced on the result, never raised, and
        # never rolls back the trade.
        try:
            link = self._brief_approval_repository.create(
                brief_id=brief_id,
                order_id=trade.order_id,
                trade_id=trade.trade_id,
                approved_at=approved_at,
            )
            return BriefApprovalResult(trade=trade, link=link, link_error=None)
        except RepositoryError as exc:
            return BriefApprovalResult(trade=trade, link=None, link_error=str(exc))