"""``SustainedUseReviewService`` -- Phase H Task 2 ("Sustained-Use

Evidence Review", evidence-collection/review layer only).

Reads the currently ACTIVE (or an explicitly selected) ``ObservationWindow``
and assembles real operating evidence from persisted AIOS records for a
human to eventually read and decide whether to continue, simplify, or
separately authorize a future market/broker investigation. This service
makes NO such decision itself -- it only collects and organizes evidence
that already exists in the database.

This service invents nothing. Every field on :class:`SustainedUseReviewResult`
is either:

    * a plain count/tuple derived directly from real, already-persisted
      rows (with the underlying dataclass -- ``SchedulerJobRun``,
      ``AuditEvent``, ``TelegramCommandAudit``, ``DecisionBrief``,
      ``JournalEntry``, ``DailyPerformance`` -- preserved verbatim so
      every item is traceable back to its own source id/timestamp), or
    * the verbatim output of an already-existing, LOCKED business
      component this service reuses read-only
      (``Services.paper_review_service.PaperReviewService``,
      ``Business.reconciliation_engine.ReconciliationEngine``), or
    * one of the explicit evidence-status sentinels below, when a
      dimension genuinely cannot be derived from what is currently
      wired/persisted -- never a fabricated number.

Evidence-status vocabulary (per dimension, see ``Database.models``-style
"never fabricate, always disclose" convention already established by
``Services.paper_review_service``):

    * :data:`STATUS_AVAILABLE` -- real evidence was found and returned.
    * :data:`STATUS_NOT_AVAILABLE` -- the collaborator needed to
      compute this dimension was never supplied to this service (e.g.
      no ``reconciliation_engine`` was injected, or no ``account_id``
      was supplied for an account-scoped dimension).
    * :data:`STATUS_INSUFFICIENT_DATA` -- the collaborator *was*
      supplied, but no real, persisted records exist in the window to
      compute this dimension from yet.
    * :data:`STATUS_EXTERNAL_BLOCKED` -- this dimension is explicitly,
      permanently out of this task's scope (a future
      market/broker investigation), never attempted here by design.

Reused, LOCKED, read-only collaborators (this service never writes to
any of them):

    * ``Repository.persistence.observation_window_repository.
      ObservationWindowRepository`` -- the window being reviewed.
    * ``Repository.persistence.scheduler_state_repository.
      SchedulerStateRepository`` -- availability/operations evidence.
    * ``Repository.persistence.audit_event_repository.
      AuditEventRepository`` -- freshness degradation/recovery and
      notification SEND/SUPPRESS/FAILED evidence.
    * ``Repository.persistence.notification_dedup_repository.
      NotificationDedupRepository`` (optional) -- current per-alert-type
      dedup state (NOT window-scoped -- see
      :class:`AlertUsefulnessEvidence`).
    * ``Repository.persistence.telegram_command_audit_repository.
      TelegramCommandAuditRepository`` (optional) -- command/alert
      audit evidence.
    * ``Repository.persistence.decision_brief_repository.
      DecisionBriefRepository`` / ``Repository.persistence.
      journal_repository.JournalRepository`` (optional) -- plan/journal
      evidence.
    * ``Services.paper_review_service.PaperReviewService`` (optional,
      requires ``account_id``) -- approved-paper/linked-order/
      linked-trade counts, adherence summary, strategy breakdown, and
      market-regime breakdown, all verbatim, never recomputed here.
    * ``Business.reconciliation_engine.ReconciliationEngine``
      (optional, requires ``account_id``) -- paper reconciliation
      evidence, verbatim.
    * ``Repository.persistence.daily_performance_repository.
      DailyPerformanceRepository`` (optional, requires ``account_id``)
      -- drawdown/process evidence, verbatim.
    * ``Repository.persistence.portfolio_snapshot_repository.
      PortfolioSnapshotRepository`` (optional, requires ``account_id``)
      -- FRESH/STALE/UNAVAILABLE valuation evidence, verbatim.

READ-ONLY GUARANTEE: every method on this class is built exclusively
from ``.get_*``/``.list_*`` repository calls and read-only service
calls (``PaperReviewService.review``,
``ReconciliationEngine.reconcile_account``). This service never calls
``.create``/``.update``/``.record``/``.close``/``submit_order`` or any
other write method on any collaborator, never sends a Telegram
message, never submits a paper order, and never touches a broker/live
execution path. Restart-safe by construction: every read goes through
a repository freshly queried on each call -- nothing is cached across
calls or across a process restart.

Window-bound filtering convention: every timestamp comparison in this
module is a plain ISO-8601 string comparison against the window's own
``start_at``/``end_at`` (inclusive on both ends) -- the same
string-prefix-comparison convention already established by
``Services.journal_service``/``Services.paper_review_service``. This
module performs no timezone-aware re-interpretation of ``start_at``/
``end_at`` against ``window.timezone``; see ``KNOWN_LIMITATIONS``.
``SchedulerJobRun.trading_date`` (a bare ``YYYY-MM-DD`` date) is
compared against the first 10 characters of ``start_at``/``end_at``
for the same reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union

from Business.reconciliation_engine import ReconciliationEngine
from Core.exceptions import ValidationError
from Database.models import (
    AuditEvent,
    DailyPerformance,
    DecisionBrief,
    JournalEntry,
    NotificationDedupState,
    ObservationWindow,
    SchedulerJobRun,
    TelegramCommandAudit,
)
from Repository.persistence.audit_event_repository import AuditEventRepository
from Repository.persistence.daily_performance_repository import DailyPerformanceRepository
from Repository.persistence.decision_brief_repository import DecisionBriefRepository
from Repository.persistence.journal_repository import JournalRepository
from Repository.persistence.notification_dedup_repository import NotificationDedupRepository
from Repository.persistence.observation_window_repository import ObservationWindowRepository
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository
from Repository.persistence.scheduler_state_repository import SchedulerStateRepository
from Repository.persistence.telegram_command_audit_repository import (
    TelegramCommandAuditRepository,
)
from Services.paper_review_service import PaperReviewService

#: Real evidence was found and returned for this dimension.
STATUS_AVAILABLE = "AVAILABLE"
#: The collaborator needed to compute this dimension was never
#: supplied to this service (or a required scoping value, such as
#: ``account_id``, was never supplied).
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
#: The collaborator *was* supplied, but no real, persisted records
#: exist in the window to compute this dimension from yet.
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
#: This dimension is explicitly, permanently out of scope for this
#: task -- a future, separately-authorized market/broker investigation
#: -- never attempted by this service by design.
STATUS_EXTERNAL_BLOCKED = "EXTERNAL_BLOCKED"

#: Overall result summary values -- descriptive only, never a
#: continue/simplify/authorize recommendation (that decision is
#: explicitly reserved for a human, outside this task's scope).
OVERALL_COMPLETE_EVIDENCE = "COMPLETE_EVIDENCE"
OVERALL_PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"

_SCHEDULER_STATUS_SUCCESS = "SUCCESS"
_SCHEDULER_STATUS_FAILED = "FAILED"
_SCHEDULER_STATUS_RUNNING = "RUNNING"

_EVENT_NOTIFICATION_SENT = "notification_sent"
_EVENT_NOTIFICATION_SUPPRESSED = "notification_suppressed"
_EVENT_NOTIFICATION_FAILED = "notification_failed"
_EVENT_FRESHNESS_DEGRADED = "freshness_degraded"
_EVENT_FRESHNESS_RECOVERED = "freshness_recovered"

#: The exact, LOCKED human-readable ``DedupDecision.reason`` text
#: fragments ``Business.notification_dedup_policy.NotificationDedupPolicy``
#: already writes (verbatim, unmodified) -- used only to classify an
#: already-real, already-persisted ``notification_suppressed`` audit
#: event's ``payload["reason"]`` back into the SUPPRESS_NO_CHANGE /
#: SUPPRESS_RATE_LIMITED vocabulary the roadmap asks for. This is a
#: deterministic read of real persisted text, not an invented metric:
#: if the text does not match either known fragment, the event is
#: counted under ``other_suppressed_count`` rather than guessed.
_REASON_FRAGMENT_NO_CHANGE = "signature unchanged"
_REASON_FRAGMENT_RATE_LIMITED = "rate limit"

#: Real ``PortfolioSnapshot.valuation_status`` values already written
#: by Phase G Task 3 -- reused verbatim, never redefined here (mirrors
#: ``Services.paper_review_service``).
_VALUATION_FRESH = "FRESH"
_VALUATION_STALE = "STALE"

KNOWN_LIMITATIONS: Tuple[str, ...] = (
    "Every timestamp filter in this service is a plain ISO-8601 string "
    "comparison against the window's own start_at/end_at (inclusive), "
    "the same convention already used by JournalService/PaperReviewService "
    "-- it does not re-interpret start_at/end_at against window.timezone "
    "before comparing them to UTC-stamped persisted records.",
    "Strategy/market-regime breakdowns reused from PaperReviewService "
    "(when available) reflect StrategyPerformanceService/"
    "MarketRegimeAttributionService's own account-wide history, not a "
    "computation scoped to this window -- neither engine accepts a date "
    "range today.",
)


@dataclass(frozen=True)
class WindowMetadata:
    """The exact, operator-selected window this review evidence is
    scoped to -- copied verbatim from the real, persisted
    ``ObservationWindow`` row, never inferred or recomputed."""

    window_id: int
    start_at: str
    end_at: str
    timezone: str
    window_status: str


@dataclass(frozen=True)
class AvailabilityEvidence:
    """Section 2 -- availability/operations, sourced verbatim from
    ``SchedulerStateRepository.list_all()`` filtered to this window's
    trading-date range."""

    status: str
    scheduled_job_count: int
    success_count: int
    failure_count: int
    running_count: int
    job_runs: Tuple[SchedulerJobRun, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DataFreshnessEvidence:
    """Section 3 -- data freshness. ``freshness_degraded_events``/
    ``freshness_recovered_events`` are always real (``AuditEventRepository``
    is a required collaborator); the FRESH/STALE/UNAVAILABLE snapshot
    counts require an optional ``PortfolioSnapshotRepository`` PLUS a
    real ``account_id`` -- see ``valuation_snapshot_status``."""

    status: str
    valuation_snapshot_status: str
    fresh_snapshot_count: int
    stale_snapshot_count: int
    unavailable_snapshot_count: int
    freshness_degraded_events: Tuple[AuditEvent, ...] = field(default_factory=tuple)
    freshness_recovered_events: Tuple[AuditEvent, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AlertUsefulnessEvidence:
    """Section 4 -- alert usefulness, sourced from
    ``AuditEventRepository`` (window-scoped) plus optional
    ``TelegramCommandAuditRepository`` (window-scoped) and
    ``NotificationDedupRepository`` (current per-alert-type state,
    NOT window-scoped -- mirrors ``HealthAuditService.dedup_states``,
    included for context only)."""

    status: str
    sent_count: int
    suppress_no_change_count: int
    suppress_rate_limited_count: int
    other_suppressed_count: int
    failed_count: int
    notification_events: Tuple[AuditEvent, ...] = field(default_factory=tuple)
    telegram_status: str = STATUS_NOT_AVAILABLE
    command_audit_count: int = 0
    command_audits: Tuple[TelegramCommandAudit, ...] = field(default_factory=tuple)
    dedup_states: Tuple[NotificationDedupState, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlanJournalAdherenceEvidence:
    """Section 5 -- plan/journal adherence. ``briefs_in_window``/
    ``journal_entries_in_window`` are always real when their
    respective optional repositories are supplied. ``approved_paper_count``/
    ``linked_order_count``/``linked_trade_count``/``adherence_summary``
    are the verbatim output of ``PaperReviewService.review`` -- never
    recomputed here -- and are ``None`` when that service (or an
    ``account_id``) was not supplied."""

    status: str
    briefs_in_window: Tuple[DecisionBrief, ...] = field(default_factory=tuple)
    brief_status_counts: Dict[str, int] = field(default_factory=dict)
    journal_entries_in_window: Tuple[JournalEntry, ...] = field(default_factory=tuple)
    take_count: int = 0
    skip_count: int = 0
    wait_count: int = 0
    paper_review_status: str = STATUS_NOT_AVAILABLE
    approved_paper_count: Optional[int] = None
    linked_order_count: Optional[int] = None
    linked_trade_count: Optional[int] = None
    adherence_summary: Optional[Dict[str, int]] = None


@dataclass(frozen=True)
class PaperReconciliationEvidence:
    """Section 6 -- paper reconciliation. Verbatim output of
    ``ReconciliationEngine.reconcile_account`` -- never recomputed
    here. Requires both a ``reconciliation_engine`` and an
    ``account_id``; ``starting_cash`` is passed through unchanged and,
    if omitted, ``ReconciliationEngine`` itself reports the
    Trade<->Cash invariant under ``not_verifiable`` (never fabricated)."""

    status: str
    account_id: Optional[str] = None
    consistent: Optional[bool] = None
    violations: Tuple[str, ...] = field(default_factory=tuple)
    not_verifiable: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DrawdownProcessEvidence:
    """Section 7 -- drawdown/process metrics. Sourced verbatim from
    already-persisted ``DailyPerformance`` rows (Activation 5.3) whose
    own ``[start_timestamp, end_timestamp]`` period is fully contained
    within this observation window -- no formula is recomputed here."""

    status: str
    account_id: Optional[str] = None
    records: Tuple[DailyPerformance, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StrategyRegimeEvidence:
    """Section 8 -- strategy/regime breakdown. Verbatim pass-through of
    ``PaperReviewService.review().strategy_breakdown`` /
    ``.market_regime_breakdown`` -- see ``KNOWN_LIMITATIONS`` for why
    these reflect account-wide history rather than this window alone."""

    status: str
    account_id: Optional[str] = None
    strategy_breakdown: Union[Dict[str, object], str, None] = None
    market_regime_breakdown: Union[Dict[str, object], str, None] = None


@dataclass(frozen=True)
class EvidenceLimitation:
    """One explicit, named gap in this review's evidence -- the
    roadmap's required AVAILABLE/NOT_AVAILABLE/INSUFFICIENT_DATA/
    EXTERNAL_BLOCKED distinction, itemized per dimension rather than
    left implicit."""

    dimension: str
    status: str
    detail: str


@dataclass(frozen=True)
class SustainedUseReviewResult:
    """Typed, frozen Phase H Task 2 sustained-use evidence review.

    This is evidence only -- it contains no continue/simplify/authorize
    recommendation. That deliberate human decision is explicitly out of
    scope for this task (see module docstring and the Phase H roadmap).
    """

    window: WindowMetadata
    generated_at: str
    availability: AvailabilityEvidence
    data_freshness: DataFreshnessEvidence
    alert_usefulness: AlertUsefulnessEvidence
    plan_journal_adherence: PlanJournalAdherenceEvidence
    paper_reconciliation: PaperReconciliationEvidence
    drawdown_process: DrawdownProcessEvidence
    strategy_regime: StrategyRegimeEvidence
    known_limitations: Tuple[EvidenceLimitation, ...]
    overall_evidence_status: str


class SustainedUseReviewService:
    """Builds one :class:`SustainedUseReviewResult` from real,
    already-persisted AIOS records for one ``ObservationWindow``.

    Constructor injection only, mirroring ``PaperReviewService``: every
    repository/service collaborator is supplied by the caller, never
    constructed here. Only ``observation_window_repository``/
    ``scheduler_state_repository``/``audit_event_repository`` are
    required -- every other collaborator is ``Optional``, so a caller
    that has not wired up every downstream component yet still gets a
    complete, honest result (with explicit ``STATUS_NOT_AVAILABLE``
    dimensions) rather than an exception. Stateless beyond these
    collaborators -- safe to reuse across calls, restart-safe since
    nothing is cached.
    """

    def __init__(
        self,
        observation_window_repository: ObservationWindowRepository,
        scheduler_state_repository: SchedulerStateRepository,
        audit_event_repository: AuditEventRepository,
        notification_dedup_repository: Optional[NotificationDedupRepository] = None,
        telegram_command_audit_repository: Optional[TelegramCommandAuditRepository] = None,
        decision_brief_repository: Optional[DecisionBriefRepository] = None,
        journal_repository: Optional[JournalRepository] = None,
        paper_review_service: Optional[PaperReviewService] = None,
        reconciliation_engine: Optional[ReconciliationEngine] = None,
        daily_performance_repository: Optional[DailyPerformanceRepository] = None,
        portfolio_snapshot_repository: Optional[PortfolioSnapshotRepository] = None,
    ) -> None:
        self._window_repository = observation_window_repository
        self._scheduler_state_repository = scheduler_state_repository
        self._audit_event_repository = audit_event_repository
        self._notification_dedup_repository = notification_dedup_repository
        self._telegram_command_audit_repository = telegram_command_audit_repository
        self._decision_brief_repository = decision_brief_repository
        self._journal_repository = journal_repository
        self._paper_review_service = paper_review_service
        self._reconciliation_engine = reconciliation_engine
        self._daily_performance_repository = daily_performance_repository
        self._portfolio_snapshot_repository = portfolio_snapshot_repository

    # -- public API --------------------------------------------------

    def generate_review(
        self,
        *,
        window_id: Optional[int] = None,
        account_id: Optional[str] = None,
        starting_cash: Optional[float] = None,
    ) -> SustainedUseReviewResult:
        """Build one evidence review for a real observation window.

        Purely observational: no repository or service is ever written
        to by this method.

        Args:
            window_id: The window to review. When omitted, the single
                currently ``ACTIVE`` window is used -- never inferred
                or selected automatically beyond that one explicit
                rule (mirrors ``ObservationWindowService.get_current``).
            account_id: Optional real account to scope every
                account-level dimension to (plan/journal adherence's
                paper-review portion, paper reconciliation, drawdown,
                strategy/regime). When omitted, those dimensions are
                honestly reported ``STATUS_NOT_AVAILABLE`` rather than
                guessed from an arbitrary account.
            starting_cash: Passed through unchanged to
                ``ReconciliationEngine.reconcile_account`` when both a
                ``reconciliation_engine`` and ``account_id`` are
                available. See ``PaperReconciliationEvidence``.

        Returns:
            A fully-populated, frozen :class:`SustainedUseReviewResult`.

        Raises:
            ValidationError: If ``window_id`` was supplied but no such
                window exists, or if ``window_id`` was omitted and no
                window is currently ``ACTIVE``.
            RepositoryError: If any underlying repository call fails.
        """
        window = self._resolve_window(window_id)

        availability = self._availability(window)
        data_freshness = self._data_freshness(window, account_id)
        alert_usefulness = self._alert_usefulness(window)

        paper_review = self._maybe_paper_review(window, account_id)
        plan_journal_adherence = self._plan_journal_adherence(window, paper_review)
        strategy_regime = self._strategy_regime(account_id, paper_review)

        paper_reconciliation = self._paper_reconciliation(account_id, starting_cash)
        drawdown_process = self._drawdown_process(window, account_id)

        sections = (
            ("availability", availability.status),
            ("data_freshness", data_freshness.valuation_snapshot_status),
            ("alert_usefulness", alert_usefulness.telegram_status),
            ("plan_journal_adherence", plan_journal_adherence.paper_review_status),
            ("paper_reconciliation", paper_reconciliation.status),
            ("drawdown_process", drawdown_process.status),
            ("strategy_regime", strategy_regime.status),
        )
        limitations = self._build_limitations(sections)

        overall_status = (
            OVERALL_COMPLETE_EVIDENCE
            if all(status == STATUS_AVAILABLE for _dim, status in sections)
            else OVERALL_PARTIAL_EVIDENCE
        )

        return SustainedUseReviewResult(
            window=WindowMetadata(
                window_id=window.window_id,
                start_at=window.start_at,
                end_at=window.end_at,
                timezone=window.timezone,
                window_status=window.status,
            ),
            generated_at=datetime.now(timezone.utc).isoformat(),
            availability=availability,
            data_freshness=data_freshness,
            alert_usefulness=alert_usefulness,
            plan_journal_adherence=plan_journal_adherence,
            paper_reconciliation=paper_reconciliation,
            drawdown_process=drawdown_process,
            strategy_regime=strategy_regime,
            known_limitations=limitations,
            overall_evidence_status=overall_status,
        )

    # -- window resolution ---------------------------------------------

    def _resolve_window(self, window_id: Optional[int]) -> ObservationWindow:
        if window_id is not None:
            window = self._window_repository.get_by_id(window_id)
            if window is None:
                raise ValidationError(
                    f"No observation window exists with window_id={window_id}.",
                    details={"window_id": window_id},
                )
            return window

        window = self._window_repository.get_active()
        if window is None:
            raise ValidationError(
                "No observation window is currently ACTIVE, and no window_id "
                "was supplied to review explicitly.",
                details={},
            )
        return window

    # -- filtering helpers -----------------------------------------------

    @staticmethod
    def _in_window(timestamp: Optional[str], window: ObservationWindow) -> bool:
        if timestamp is None:
            return False
        return window.start_at <= timestamp <= window.end_at

    @staticmethod
    def _trading_date_in_window(trading_date: str, window: ObservationWindow) -> bool:
        start_date = window.start_at[:10]
        end_date = window.end_at[:10]
        return start_date <= trading_date <= end_date

    # -- section 2: availability -----------------------------------------

    def _availability(self, window: ObservationWindow) -> AvailabilityEvidence:
        all_runs = self._scheduler_state_repository.list_all()
        runs = [r for r in all_runs if self._trading_date_in_window(r.trading_date, window)]
        runs.sort(key=lambda r: (r.trading_date, r.job_type))

        return AvailabilityEvidence(
            status=STATUS_AVAILABLE,
            scheduled_job_count=len(runs),
            success_count=sum(1 for r in runs if r.status == _SCHEDULER_STATUS_SUCCESS),
            failure_count=sum(1 for r in runs if r.status == _SCHEDULER_STATUS_FAILED),
            running_count=sum(1 for r in runs if r.status == _SCHEDULER_STATUS_RUNNING),
            job_runs=tuple(runs),
        )

    # -- section 3: data freshness ----------------------------------------

    def _events_in_window(
        self, window: ObservationWindow, event_types: frozenset
    ) -> List[AuditEvent]:
        all_events = self._audit_event_repository.list_all()
        events = [
            e
            for e in all_events
            if e.event_type in event_types and self._in_window(e.created_at, window)
        ]
        events.sort(key=lambda e: (e.created_at, e.id or 0))
        return events

    def _data_freshness(
        self, window: ObservationWindow, account_id: Optional[str]
    ) -> DataFreshnessEvidence:
        degraded = tuple(
            self._events_in_window(window, frozenset({_EVENT_FRESHNESS_DEGRADED}))
        )
        recovered = tuple(
            self._events_in_window(window, frozenset({_EVENT_FRESHNESS_RECOVERED}))
        )

        if self._portfolio_snapshot_repository is None or account_id is None:
            return DataFreshnessEvidence(
                status=STATUS_AVAILABLE,
                valuation_snapshot_status=STATUS_NOT_AVAILABLE,
                fresh_snapshot_count=0,
                stale_snapshot_count=0,
                unavailable_snapshot_count=0,
                freshness_degraded_events=degraded,
                freshness_recovered_events=recovered,
            )

        snapshots = self._portfolio_snapshot_repository.list_by_account(account_id)
        snapshots = [s for s in snapshots if self._in_window(s.timestamp, window)]

        return DataFreshnessEvidence(
            status=STATUS_AVAILABLE,
            valuation_snapshot_status=STATUS_AVAILABLE,
            fresh_snapshot_count=sum(1 for s in snapshots if s.valuation_status == _VALUATION_FRESH),
            stale_snapshot_count=sum(1 for s in snapshots if s.valuation_status == _VALUATION_STALE),
            unavailable_snapshot_count=sum(1 for s in snapshots if s.valuation_status is None),
            freshness_degraded_events=degraded,
            freshness_recovered_events=recovered,
        )

    # -- section 4: alert usefulness ---------------------------------------

    @staticmethod
    def _classify_suppression(event: AuditEvent) -> str:
        """Classify a real, persisted ``notification_suppressed`` event
        back into SUPPRESS_NO_CHANGE / SUPPRESS_RATE_LIMITED / "OTHER"
        by matching its own ``payload["reason"]`` text against the
        exact, LOCKED fragments ``NotificationDedupPolicy`` writes. See
        the ``_REASON_FRAGMENT_*`` module constants."""
        if not event.payload:
            return "OTHER"
        try:
            payload = json.loads(event.payload)
        except (TypeError, ValueError):
            return "OTHER"
        reason = (payload or {}).get("reason") or ""
        reason = reason.lower()
        if _REASON_FRAGMENT_NO_CHANGE in reason:
            return "SUPPRESS_NO_CHANGE"
        if _REASON_FRAGMENT_RATE_LIMITED in reason:
            return "SUPPRESS_RATE_LIMITED"
        return "OTHER"

    def _alert_usefulness(self, window: ObservationWindow) -> AlertUsefulnessEvidence:
        events = self._events_in_window(
            window,
            frozenset(
                {
                    _EVENT_NOTIFICATION_SENT,
                    _EVENT_NOTIFICATION_SUPPRESSED,
                    _EVENT_NOTIFICATION_FAILED,
                }
            ),
        )
        sent = sum(1 for e in events if e.event_type == _EVENT_NOTIFICATION_SENT)
        failed = sum(1 for e in events if e.event_type == _EVENT_NOTIFICATION_FAILED)

        suppressed = [e for e in events if e.event_type == _EVENT_NOTIFICATION_SUPPRESSED]
        no_change = sum(1 for e in suppressed if self._classify_suppression(e) == "SUPPRESS_NO_CHANGE")
        rate_limited = sum(
            1 for e in suppressed if self._classify_suppression(e) == "SUPPRESS_RATE_LIMITED"
        )
        other_suppressed = len(suppressed) - no_change - rate_limited

        if self._telegram_command_audit_repository is None:
            telegram_status = STATUS_NOT_AVAILABLE
            command_audits: Tuple[TelegramCommandAudit, ...] = tuple()
        else:
            all_commands = self._telegram_command_audit_repository.list_all()
            commands = [c for c in all_commands if self._in_window(c.received_at, window)]
            commands.sort(key=lambda c: (c.received_at, c.id or 0))
            telegram_status = STATUS_AVAILABLE
            command_audits = tuple(commands)

        dedup_states: Tuple[NotificationDedupState, ...] = (
            tuple(self._notification_dedup_repository.list_all())
            if self._notification_dedup_repository is not None
            else tuple()
        )

        return AlertUsefulnessEvidence(
            status=STATUS_AVAILABLE,
            sent_count=sent,
            suppress_no_change_count=no_change,
            suppress_rate_limited_count=rate_limited,
            other_suppressed_count=other_suppressed,
            failed_count=failed,
            notification_events=tuple(events),
            telegram_status=telegram_status,
            command_audit_count=len(command_audits),
            command_audits=command_audits,
            dedup_states=dedup_states,
        )

    # -- paper review (shared by sections 5 & 8) --------------------------

    def _maybe_paper_review(self, window: ObservationWindow, account_id: Optional[str]):
        if self._paper_review_service is None or account_id is None:
            return None
        return self._paper_review_service.review(
            account_id, since=window.start_at, until=window.end_at
        )

    # -- section 5: plan/journal adherence ---------------------------------

    def _plan_journal_adherence(
        self, window: ObservationWindow, paper_review
    ) -> PlanJournalAdherenceEvidence:
        briefs: Tuple[DecisionBrief, ...] = tuple()
        brief_status_counts: Dict[str, int] = {}
        if self._decision_brief_repository is not None:
            all_briefs = self._decision_brief_repository.list_all()
            in_window = [b for b in all_briefs if self._in_window(b.generated_at, window)]
            in_window.sort(key=lambda b: b.brief_id)
            briefs = tuple(in_window)
            for b in in_window:
                brief_status_counts[b.status] = brief_status_counts.get(b.status, 0) + 1

        entries: Tuple[JournalEntry, ...] = tuple()
        take_count = skip_count = wait_count = 0
        if self._journal_repository is not None:
            all_entries = self._journal_repository.list_all()
            in_window_entries = [e for e in all_entries if self._in_window(e.decided_at, window)]
            in_window_entries.sort(key=lambda e: e.entry_id)
            entries = tuple(in_window_entries)
            take_count = sum(1 for e in in_window_entries if e.decision == "TAKE")
            skip_count = sum(1 for e in in_window_entries if e.decision == "SKIP")
            wait_count = sum(1 for e in in_window_entries if e.decision == "WAIT")

        status = (
            STATUS_AVAILABLE
            if (self._decision_brief_repository is not None or self._journal_repository is not None)
            else STATUS_NOT_AVAILABLE
        )

        if paper_review is None:
            return PlanJournalAdherenceEvidence(
                status=status,
                briefs_in_window=briefs,
                brief_status_counts=brief_status_counts,
                journal_entries_in_window=entries,
                take_count=take_count,
                skip_count=skip_count,
                wait_count=wait_count,
                paper_review_status=STATUS_NOT_AVAILABLE,
            )

        return PlanJournalAdherenceEvidence(
            status=status,
            briefs_in_window=briefs,
            brief_status_counts=brief_status_counts,
            journal_entries_in_window=entries,
            take_count=take_count,
            skip_count=skip_count,
            wait_count=wait_count,
            paper_review_status=STATUS_AVAILABLE,
            approved_paper_count=paper_review.approved_paper_count,
            linked_order_count=paper_review.linked_order_count,
            linked_trade_count=paper_review.linked_trade_count,
            adherence_summary=dict(paper_review.adherence_summary),
        )

    # -- section 6: paper reconciliation -----------------------------------

    def _paper_reconciliation(
        self, account_id: Optional[str], starting_cash: Optional[float]
    ) -> PaperReconciliationEvidence:
        if self._reconciliation_engine is None or account_id is None:
            return PaperReconciliationEvidence(status=STATUS_NOT_AVAILABLE, account_id=account_id)

        result = self._reconciliation_engine.reconcile_account(
            account_id, starting_cash=starting_cash
        )
        return PaperReconciliationEvidence(
            status=STATUS_AVAILABLE,
            account_id=account_id,
            consistent=result.consistent,
            violations=tuple(result.violations),
            not_verifiable=tuple(result.not_verifiable),
        )

    # -- section 7: drawdown/process metrics --------------------------------

    def _drawdown_process(
        self, window: ObservationWindow, account_id: Optional[str]
    ) -> DrawdownProcessEvidence:
        if self._daily_performance_repository is None or account_id is None:
            return DrawdownProcessEvidence(status=STATUS_NOT_AVAILABLE, account_id=account_id)

        all_records = self._daily_performance_repository.list_by_account(account_id)
        in_window = [
            r
            for r in all_records
            if r.start_timestamp >= window.start_at and r.end_timestamp <= window.end_at
        ]
        in_window.sort(key=lambda r: r.daily_performance_id)

        status = STATUS_AVAILABLE if in_window else STATUS_INSUFFICIENT_DATA
        return DrawdownProcessEvidence(
            status=status, account_id=account_id, records=tuple(in_window)
        )

    # -- section 8: strategy/regime ------------------------------------------

    def _strategy_regime(self, account_id: Optional[str], paper_review) -> StrategyRegimeEvidence:
        if paper_review is None:
            return StrategyRegimeEvidence(status=STATUS_NOT_AVAILABLE, account_id=account_id)

        return StrategyRegimeEvidence(
            status=STATUS_AVAILABLE,
            account_id=account_id,
            strategy_breakdown=paper_review.strategy_breakdown,
            market_regime_breakdown=paper_review.market_regime_breakdown,
        )

    # -- section 9: known limitations ----------------------------------------

    def _build_limitations(
        self, sections: Tuple[Tuple[str, str], ...]
    ) -> Tuple[EvidenceLimitation, ...]:
        limitations: List[EvidenceLimitation] = []
        for dimension, status in sections:
            if status == STATUS_NOT_AVAILABLE:
                limitations.append(
                    EvidenceLimitation(
                        dimension=dimension,
                        status=STATUS_NOT_AVAILABLE,
                        detail=(
                            f"'{dimension}' evidence was not computed: the collaborator "
                            "and/or account_id needed for this dimension was not supplied "
                            "to SustainedUseReviewService."
                        ),
                    )
                )
            elif status == STATUS_INSUFFICIENT_DATA:
                limitations.append(
                    EvidenceLimitation(
                        dimension=dimension,
                        status=STATUS_INSUFFICIENT_DATA,
                        detail=(
                            f"'{dimension}' evidence was not computed: the required "
                            "collaborator is available, but no matching persisted "
                            "records exist within this observation window yet."
                        ),
                    )
                )

        limitations.append(
            EvidenceLimitation(
                dimension="broker_live_market_investigation",
                status=STATUS_EXTERNAL_BLOCKED,
                detail=(
                    "A real market/broker investigation is explicitly out of scope "
                    "for Phase H Task 2 by design -- it is a separate, future, "
                    "human-authorized decision, never attempted by this service."
                ),
            )
        )

        for detail in KNOWN_LIMITATIONS:
            limitations.append(
                EvidenceLimitation(dimension="methodology", status=STATUS_AVAILABLE, detail=detail)
            )

        return tuple(limitations)