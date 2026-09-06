"""``DecisionBriefService`` -- Phase B ("Decision Copilot").

Produces and persists a ``DecisionBrief`` for one symbol: a read-only
verdict on whether the symbol is actionable right now, and -- only
when ``SUCCESS`` -- the real risk-managed plan behind that call.

This service invents nothing. It reuses exactly three existing,
LOCKED components:

    * ``Database.models.RankingSnapshot`` (via ``SnapshotRepository``)
      -- the canonical analysis result. This service never runs
      ``RankingEngine``, never scans, never computes a recommendation.
    * ``Business.decision_brief_policy.DecisionBriefPolicy`` -- decides,
      from the snapshot alone, whether a plan may even be attempted.
    * ``Services.risk_management_service.RiskManagementService`` -- the
      one and only risk engine in this codebase. This service never
      computes a stop, target, position size, or risk amount itself;
      it only forwards caller-supplied risk parameters (mirroring
      ``Business.dry_run_order_service.DryRunOrderService``'s own
      "risk parameters are optional, caller-supplied, never invented"
      convention) into ``RiskManagementService.execute()`` and persists
      its verbatim output.

Every non-``SUCCESS`` status is a dead end by design: no plan is ever
attached to a ``NO_TRADE``/``DATA_STALE``/``DATA_ERROR``/
``INSUFFICIENT_DATA``/``ANALYSIS_FAILED``/``RISK_REJECTED``/
``POLICY_BLOCKED`` brief. Generating a brief -- of any status -- never
creates a paper order, a ``Trade``, or a ``Position``: this service
holds no reference to ``PaperTradingEngine``/``OrderLifecycleService``/
``ExecutionService`` and calls none of them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from Business.decision_brief_policy import DecisionBriefPolicy
from Database.models import DecisionBrief, RankingSnapshot
from Repository.persistence.decision_brief_repository import DecisionBriefRepository
from Repository.persistence.snapshot_repository import SnapshotRepository
from Services.metadata_keys import MetadataKeys
from Services.risk_management_service import RiskManagementService
from Services.service_context import ServiceContext

#: Every valid Phase-B brief status.
STATUS_SUCCESS = "SUCCESS"
STATUS_NO_TRADE = "NO_TRADE"
STATUS_DATA_STALE = "DATA_STALE"
STATUS_DATA_ERROR = "DATA_ERROR"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_ANALYSIS_FAILED = "ANALYSIS_FAILED"
STATUS_RISK_REJECTED = "RISK_REJECTED"
STATUS_POLICY_BLOCKED = "POLICY_BLOCKED"

ALL_STATUSES = frozenset(
    {
        STATUS_SUCCESS,
        STATUS_NO_TRADE,
        STATUS_DATA_STALE,
        STATUS_DATA_ERROR,
        STATUS_INSUFFICIENT_DATA,
        STATUS_ANALYSIS_FAILED,
        STATUS_RISK_REJECTED,
        STATUS_POLICY_BLOCKED,
    }
)


@dataclass(frozen=True)
class RiskInputs:
    """Caller-supplied risk parameters for a brief request.

    Every field must be a real, caller-supplied number -- this service
    never defaults, guesses, or fabricates any of them (mirroring
    ``DryRunOrderService``'s own convention: risk parameters are
    optional and, when absent, the risk stage is skipped rather than
    silently defaulted). ``entry_price`` is the real current price for
    the symbol; ``stop_loss_percent``/``take_profit_percent``/
    ``risk_per_trade_percent`` are the caller's own chosen risk
    tolerances; ``account_balance`` is the real account balance the
    position size should be sized against.
    """

    entry_price: float
    stop_loss_percent: float
    take_profit_percent: float
    risk_per_trade_percent: float
    account_balance: float


class DecisionBriefService:
    """Orchestrates one brief-generation request for one symbol.

    Constructor injection only, mirroring every other service/engine
    in this codebase: ``snapshot_repository`` (read the canonical
    analysis result), ``decision_brief_policy`` (gate), ``risk_service``
    (the one risk engine), ``brief_repository`` (persist the verdict).
    Stateless beyond these collaborators -- safe to reuse across calls.
    """

    def __init__(
        self,
        snapshot_repository: SnapshotRepository,
        decision_brief_policy: DecisionBriefPolicy,
        risk_service: RiskManagementService,
        brief_repository: DecisionBriefRepository,
    ) -> None:
        self._snapshot_repository = snapshot_repository
        self._decision_brief_policy = decision_brief_policy
        self._risk_service = risk_service
        self._brief_repository = brief_repository

    def generate_brief(
        self,
        symbol: str,
        *,
        risk_inputs: Optional[RiskInputs] = None,
    ) -> DecisionBrief:
        """Generate, persist, and return a ``DecisionBrief`` for ``symbol``.

        Never raises for business-level failures (missing snapshot,
        stale data, risk rejection, etc.) -- every such outcome is
        represented as a persisted brief with the matching status,
        exactly like every ``BaseService.execute()`` in this codebase
        represents business failure via ``ServiceResult.fail`` rather
        than an exception. Only genuinely unexpected errors
        (repository/database failure) propagate, since those are
        infrastructure failures this service has no business
        swallowing.

        Args:
            symbol: The symbol to brief. Case-insensitive; persisted
                upper-cased, matching ``RankingSnapshot.symbol``/CLI
                convention elsewhere (e.g. ``_latest_snapshot_for_symbol``).
            risk_inputs: Real, caller-supplied risk parameters. If
                ``None``, no attempt is made to price a plan and the
                brief resolves to ``POLICY_BLOCKED`` when the snapshot
                would otherwise be actionable -- this service never
                invents these values itself.

        Returns:
            The persisted :class:`Database.models.DecisionBrief`.
        """
        symbol = symbol.upper()
        generated_at = datetime.now(timezone.utc).isoformat()

        snapshot = self._latest_snapshot(symbol)
        gate = self._decision_brief_policy.evaluate(snapshot)

        if gate.blocked_status is not None:
            return self._persist(
                symbol=symbol,
                generated_at=generated_at,
                status=gate.blocked_status,
                source_snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
                reason=gate.reason,
            )

        # Gate passed: snapshot is fresh, status="success", and
        # recommendation == "BUY". A plan may be attempted, but only
        # with real, caller-supplied risk inputs.
        assert snapshot is not None  # gate.blocked_status is None implies a snapshot exists

        if risk_inputs is None:
            return self._persist(
                symbol=symbol,
                generated_at=generated_at,
                status=STATUS_POLICY_BLOCKED,
                source_snapshot_id=snapshot.snapshot_id,
                reason=(
                    "Snapshot is actionable (BUY, fresh data) but no risk parameters were "
                    "supplied -- entry/stop/target/position-size are never invented. Supply "
                    "--stop-loss-pct/--take-profit-pct/--risk-pct/--balance to price a plan."
                ),
            )

        risk_result = self._run_risk_service(risk_inputs)

        if not risk_result.success:
            return self._persist(
                symbol=symbol,
                generated_at=generated_at,
                status=STATUS_RISK_REJECTED,
                source_snapshot_id=snapshot.snapshot_id,
                reason=risk_result.message or "RiskManagementService rejected this trade.",
            )

        data = risk_result.data or {}
        return self._persist(
            symbol=symbol,
            generated_at=generated_at,
            status=STATUS_SUCCESS,
            source_snapshot_id=snapshot.snapshot_id,
            reason=None,
            entry_price=risk_inputs.entry_price,
            stop_loss_price=data.get(MetadataKeys.STOP_LOSS_PRICE),
            take_profit_price=data.get(MetadataKeys.TAKE_PROFIT_PRICE),
            risk_amount=data.get(MetadataKeys.RISK_AMOUNT),
            position_size=data.get(MetadataKeys.POSITION_SIZE),
            risk_reward_ratio=data.get(MetadataKeys.RISK_REWARD_RATIO),
        )

    def get_latest_brief(self, symbol: str) -> Optional[DecisionBrief]:
        """Read-only retrieval of the most recently persisted
        ``DecisionBrief`` for ``symbol``, or ``None`` if none exists.

        Pure pass-through to
        ``DecisionBriefRepository.get_latest_for_symbol`` -- never
        regenerates, reprices, or recomputes anything, and never
        writes a new row. Callers (e.g. the CLI's no-risk-argument
        ``brief SYMBOL`` path) use this to display the last persisted
        verdict verbatim instead of silently generating a new one.

        Args:
            symbol: Case-insensitive; matched upper-cased, exactly
                like ``generate_brief``.

        Returns:
            The stored :class:`Database.models.DecisionBrief`, or
            ``None`` if no brief has ever been persisted for this
            symbol.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        return self._brief_repository.get_latest_for_symbol(symbol.upper())

    def _latest_snapshot(self, symbol: str) -> Optional[RankingSnapshot]:
        """Read-only lookup of the most recent scan's snapshot for
        ``symbol``. Reuses ``SnapshotRepository.list_latest()`` exactly
        as-is, filtered in this layer -- same pattern as ``main.py``'s
        ``_latest_snapshot_for_symbol``, deliberately not reimplemented
        as a new repository query.
        """
        for row in self._snapshot_repository.list_latest():
            if row.symbol.upper() == symbol:
                return row
        return None

    def _run_risk_service(self, risk_inputs: RiskInputs):
        started_at = time.monotonic()
        context = ServiceContext(
            agent_name="decision_brief_service",
            provider_name="none",
            request_id=f"decision-brief-{started_at}",
            user_input="",
            metadata={
                MetadataKeys.ENTRY_PRICE: risk_inputs.entry_price,
                MetadataKeys.STOP_LOSS_PERCENT: risk_inputs.stop_loss_percent,
                MetadataKeys.TAKE_PROFIT_PERCENT: risk_inputs.take_profit_percent,
                MetadataKeys.RISK_PER_TRADE_PERCENT: risk_inputs.risk_per_trade_percent,
                MetadataKeys.ACCOUNT_BALANCE: risk_inputs.account_balance,
            },
        )
        try:
            return self._risk_service.execute(context)
        except Exception as exc:  # noqa: BLE001 - normalize any unexpected engine failure
            from Services.service_result import ServiceResult

            return ServiceResult.fail(
                error=exc,
                message=f"RiskManagementService raised an unexpected error: {exc}",
            )

    def _persist(
        self,
        *,
        symbol: str,
        generated_at: str,
        status: str,
        source_snapshot_id: Optional[int],
        reason: Optional[str],
        entry_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        risk_amount: Optional[float] = None,
        position_size: Optional[float] = None,
        risk_reward_ratio: Optional[float] = None,
    ) -> DecisionBrief:
        if status != STATUS_SUCCESS:
            # Hard invariant: only SUCCESS may carry a plan. Enforced
            # here, once, regardless of which caller above forgot to
            # scrub the fields -- never trust the caller alone.
            entry_price = None
            stop_loss_price = None
            take_profit_price = None
            risk_amount = None
            position_size = None
            risk_reward_ratio = None

        return self._brief_repository.create(
            symbol=symbol,
            generated_at=generated_at,
            status=status,
            source_snapshot_id=source_snapshot_id,
            reason=reason,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_amount=risk_amount,
            position_size=position_size,
            risk_reward_ratio=risk_reward_ratio,
        )