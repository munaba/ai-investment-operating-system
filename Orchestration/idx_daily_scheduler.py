"""IDXDailyScheduler -- Phase D ("Proactive IDX Scheduler Routine").

Orchestrates five fixed, named jobs over the course of one IDX trading
day, driven by repeated calls to :meth:`IDXDailyScheduler.tick`, each
supplied a caller-generated "now" (never generated internally, same
``generated_at``-is-caller-supplied convention every other
Orchestration/Business class in this codebase already follows --
``ManualScanService.run_scan``, ``DailyReportOrchestrator.
run_daily_report``, etc.):

    * ``pre_market_check``   -- once per trading day, during the IDX
      pre-market window. No fetch; a lightweight readiness check.
    * ``session_scan``       -- every tick while the regular session
      is open (gated by ``IDXMarketCalendar.is_market_open``). The
      only job that fetches real market data (via the existing,
      unmodified ``ManualScanService``). A material change in the
      resulting report triggers (at most) one deduplicated Telegram
      alert.
    * ``data_health_check``  -- every tick on a trading day. Performs
      NO fetch of its own; evaluates the freshness of the most recent
      successful ``session_scan`` observation (reconstructed from the
      append-only audit log, never from in-memory state) and raises a
      rate-limited alert on a FRESH<->STALE/MISSING transition.
    * ``market_close_recap`` -- once per trading day, at/after the IDX
      close. Reuses the existing, unmodified
      ``DailyReportOrchestrator`` (the same pipeline
      ``python main.py report daily`` already runs) -- this is the
      one job besides ``session_scan`` that performs its own fetch,
      by design (an end-of-day recap needs the day's final numbers).
    * ``daily_review``       -- once per trading day, after
      ``market_close_recap`` has succeeded. No fetch; summarizes the
      day's own persisted scheduler/audit state.

Restart-safety (Phase D "restart-safe scheduler state" requirement):
every decision this class makes -- "has job X already run today",
"what was the last freshness state", "what was the last alert sent"
-- is reconstructed fresh, on every ``tick()`` call, from
``SchedulerStateRepository``/``AuditEventRepository``/
``NotificationDedupRepository``. This class holds no mutable
in-process state of its own between calls; a brand new
``IDXDailyScheduler`` instance, constructed after a process restart,
observes exactly the same "has this already happened today" answers a
long-running instance would have.

Hard boundary (Phase D "no automatic paper order" requirement,
LOCKED): this module never imports ``PaperTradingEngine``,
``OrderLifecycleService``, ``ExecutionService``, or any broker
adapter, and calls none of them. Every job here is read-mostly
(``ManualScanService``/``DailyReportOrchestrator`` already persist
scan snapshots -- unchanged, pre-existing behavior) plus this
module's own Phase D audit/state bookkeeping. No job in this class
constructs an ``Order``, a ``Trade``, or mutates a ``Position``.

Explicitly reuses, never re-implements: ``IDXMarketCalendar`` (session
gating), ``DataFreshnessPolicy`` (FRESH/STALE/MISSING), and
``NotificationDedupPolicy`` (SEND/SUPPRESS_NO_CHANGE/
SUPPRESS_RATE_LIMITED) -- the three pure decision components Phase D
already built. This class is the thin sequencing layer over them, the
same "orchestrator adds no new business logic" convention
``ManualScanService``/``DailyReportOrchestrator`` already establish.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from Business.daily_report_orchestrator import DailyReportOrchestrator
from Business.data_freshness_policy import (
    FRESH,
    DataFreshnessPolicy,
    Observation,
)
from Business.idx_market_calendar import (
    SESSION_2_CLOSE,
    SESSION_PRE_MARKET,
    IDXMarketCalendar,
)
from Business.manual_scan_service import ManualScanService
from Business.notification_dedup_policy import NotificationDedupPolicy
from Business.notification_event import NotificationEvent, NotificationEventType
from Business.notification_manager import NotificationManager
from Repository.persistence.audit_event_repository import AuditEventRepository
from Repository.persistence.notification_dedup_repository import (
    STATUS_FAILED as DEDUP_STATUS_FAILED,
    STATUS_SENT as DEDUP_STATUS_SENT,
    STATUS_SUPPRESSED as DEDUP_STATUS_SUPPRESSED,
    NotificationDedupRepository,
)
from Repository.persistence.scheduler_state_repository import (
    STATUS_FAILED as JOB_STATUS_FAILED,
    SchedulerStateRepository,
)

#: Fixed Phase D job identifiers (LOCKED set -- mirrors
#: ``Database.models.SchedulerJobRun.job_type``'s own documented
#: examples exactly). No other job identifier is ever written to
#: ``scheduler_job_runs`` by this class.
JOB_PRE_MARKET_CHECK: str = "pre_market_check"
JOB_SESSION_SCAN: str = "session_scan"
JOB_DATA_HEALTH_CHECK: str = "data_health_check"
JOB_MARKET_CLOSE_RECAP: str = "market_close_recap"
JOB_DAILY_REVIEW: str = "daily_review"

ALL_JOB_TYPES: tuple = (
    JOB_PRE_MARKET_CHECK,
    JOB_SESSION_SCAN,
    JOB_DATA_HEALTH_CHECK,
    JOB_MARKET_CLOSE_RECAP,
    JOB_DAILY_REVIEW,
)

#: Fixed Phase D alert-channel identifiers, evaluated through
#: ``NotificationDedupPolicy``/``NotificationDedupRepository``.
ALERT_SESSION_SCAN_BRIEF: str = "session_scan_brief"
ALERT_DATA_FRESHNESS: str = "data_freshness"

#: Skip reasons a tick may report when no job was even attempted.
SKIP_NON_TRADING_DAY: str = "non_trading_day"

#: Default exponential-backoff parameters for a FAILED job's
#: ``next_retry_at`` (Phase D "retry/backoff works" requirement).
#: 60s doubling up to a 1-hour ceiling -- conservative enough that a
#: flapping provider cannot retry more than once a minute at first,
#: bounded enough that a genuine recovery is retried the same session.
DEFAULT_RETRY_BASE_SECONDS: float = 60.0
DEFAULT_RETRY_MAX_SECONDS: float = 3600.0


def _parse_iso8601(value: str) -> datetime:
    from datetime import timezone as _timezone

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone.utc)
    return parsed


@dataclass(frozen=True)
class JobOutcome:
    """The result of evaluating one job during one ``tick()`` call.

    Attributes:
        job_type: One of the ``JOB_*`` constants.
        attempted: Whether this tick actually attempted the job (an
            idempotency/session-gating check may have skipped it
            entirely -- ``attempted=False`` in that case, and
            ``outcome``/``detail`` describe why).
        outcome: One of ``"SUCCESS"``/``"FAILED"``/``"SKIPPED"``.
        detail: Free-text detail (a skip reason, or a short summary of
            what happened on success/failure).
    """

    job_type: str
    attempted: bool
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class TickResult:
    """The result of one :meth:`IDXDailyScheduler.tick` call.

    Attributes:
        now: The caller-supplied moment this tick evaluated, unchanged.
        trading_date: The IDX-local (Asia/Jakarta) trading date this
            tick's jobs are scoped to (``YYYY-MM-DD``).
        session: The IDX session ``now`` falls into (one of
            ``Business.idx_market_calendar``'s ``SESSION_*``
            constants).
        jobs: One :class:`JobOutcome` per job this tick evaluated
            (only jobs actually considered this tick -- a job whose
            gating condition was not even reached this tick is simply
            absent from this tuple, not present with ``SKIPPED``).
    """

    now: str
    trading_date: str
    session: str
    jobs: tuple = field(default_factory=tuple)


class IDXDailyScheduler:
    """Sequences Phase D's five daily jobs, gated by IDX session state
    and idempotent per ``(job_type, trading_date)``.

    Constructor injection only, mirroring every other
    Orchestration/Business class in this codebase. Every collaborator
    is stored by reference, never copied, never wrapped -- this class
    adds no new business logic of its own beyond sequencing and the
    bookkeeping (state/audit/dedup) that makes that sequencing
    restart-safe.
    """

    def __init__(
        self,
        idx_market_calendar: IDXMarketCalendar,
        scheduler_state_repository: SchedulerStateRepository,
        notification_dedup_repository: NotificationDedupRepository,
        notification_dedup_policy: NotificationDedupPolicy,
        data_freshness_policy: DataFreshnessPolicy,
        audit_event_repository: AuditEventRepository,
        manual_scan_service: ManualScanService,
        daily_report_orchestrator: DailyReportOrchestrator,
        notification_manager: NotificationManager,
        account_id: str,
        retry_base_seconds: float = DEFAULT_RETRY_BASE_SECONDS,
        retry_max_seconds: float = DEFAULT_RETRY_MAX_SECONDS,
    ) -> None:
        self._calendar = idx_market_calendar
        self._state_repo = scheduler_state_repository
        self._dedup_repo = notification_dedup_repository
        self._dedup_policy = notification_dedup_policy
        self._freshness_policy = data_freshness_policy
        self._audit = audit_event_repository
        self._manual_scan_service = manual_scan_service
        self._daily_report_orchestrator = daily_report_orchestrator
        self._notification_manager = notification_manager
        self._account_id = account_id
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(self, now: datetime) -> TickResult:
        """Evaluate every Phase D job for the moment ``now``.

        Args:
            now: Timezone-aware evaluation moment. Never generated by
                this method -- the caller (CLI command or simulation
                loop) is the sole source of "now", mirroring every
                other ``generated_at``-style contract in this
                codebase.

        Returns:
            A :class:`TickResult` describing what happened. On a
            non-trading day (weekend, or a caller-declared holiday),
            no job is even considered -- ``jobs`` is empty and the
            skip is implicit (no scheduler_job_runs row is written,
            no fetch of any kind happens).
        """
        local_date = self._calendar.local_date(now)
        trading_date = local_date.isoformat()
        session = self._calendar.session(now)
        local_time = self._calendar.to_local(now).time()

        if not self._calendar.is_trading_day(local_date):
            return TickResult(now=now.isoformat(), trading_date=trading_date, session=session, jobs=())

        outcomes = []

        # pre_market_check: exactly once, confined to the pre-market
        # window. No fetch of any kind.
        if session == SESSION_PRE_MARKET:
            outcomes.append(
                self._run_once(
                    JOB_PRE_MARKET_CHECK,
                    trading_date,
                    now,
                    lambda: self._job_pre_market_check(session),
                )
            )

        # session_scan: only while the regular session is genuinely
        # open (Phase D "session scan respects IDX session gating" /
        # "closed market performs no scan/fetch"). Repeatable per
        # tick -- not gated by has_succeeded, since a fresh scan every
        # open-session tick is the entire point of this job.
        if self._calendar.is_market_open(now):
            outcomes.append(self._run_session_scan(trading_date, now))

        # data_health_check: every tick on a trading day. Performs no
        # fetch of its own -- safe to run even while the market is
        # closed (pre-market/lunch/after-hours), since it only
        # evaluates the freshness of the last already-fetched
        # session_scan observation.
        outcomes.append(self._run_data_health_check(trading_date, now))

        # market_close_recap: once per day, at/after the IDX close.
        # Deliberately NOT gated to SESSION_AFTER_HOURS only (a coarse
        # tick interval could step over that narrow window) -- any
        # tick at/after SESSION_2_CLOSE on a trading day is eligible.
        if local_time >= SESSION_2_CLOSE:
            if self._may_attempt(JOB_MARKET_CLOSE_RECAP, trading_date, now):
                outcomes.append(
                    self._run_once(
                        JOB_MARKET_CLOSE_RECAP,
                        trading_date,
                        now,
                        lambda: self._job_market_close_recap(now),
                    )
                )

            # daily_review: once per day, only after market_close_recap
            # has actually succeeded -- it reviews that same day's
            # already-completed jobs.
            if self._state_repo.has_succeeded(JOB_MARKET_CLOSE_RECAP, trading_date) and self._may_attempt(
                JOB_DAILY_REVIEW, trading_date, now
            ):
                outcomes.append(
                    self._run_once(
                        JOB_DAILY_REVIEW,
                        trading_date,
                        now,
                        lambda: self._job_daily_review(trading_date, now),
                    )
                )

        return TickResult(
            now=now.isoformat(),
            trading_date=trading_date,
            session=session,
            jobs=tuple(outcomes),
        )

    # ------------------------------------------------------------------
    # Idempotency / retry-backoff gating
    # ------------------------------------------------------------------

    def _may_attempt(self, job_type: str, trading_date: str, now: datetime) -> bool:
        """Return whether ``job_type`` may be attempted now for
        ``trading_date``: not already ``SUCCESS``, and -- if the most
        recent attempt ``FAILED`` -- the backoff window
        (``next_retry_at``) has elapsed.

        A ``RUNNING`` row (a prior attempt that crashed mid-flight,
        never reaching ``mark_success``/``mark_failed``) is always
        eligible for a fresh attempt -- restart-safety requires this
        class to make forward progress after a crash, not wait
        forever on a row no process will ever complete.
        """
        if self._state_repo.has_succeeded(job_type, trading_date):
            return False
        row = self._state_repo.get(job_type, trading_date)
        if row is None:
            return True
        if row.status == JOB_STATUS_FAILED and row.next_retry_at:
            return now >= _parse_iso8601(row.next_retry_at)
        return True

    def _may_attempt_repeatable(self, job_type: str, trading_date: str, now: datetime) -> bool:
        """Same backoff check as :meth:`_may_attempt`, minus the
        ``has_succeeded`` short-circuit -- for a job meant to run on
        every eligible tick (``session_scan``), a prior success must
        never block the next attempt. Only a genuine, still-cooling-
        down failure (``FAILED`` with an unexpired ``next_retry_at``)
        holds this job back.
        """
        row = self._state_repo.get(job_type, trading_date)
        if row is None:
            return True
        if row.status == JOB_STATUS_FAILED and row.next_retry_at:
            return now >= _parse_iso8601(row.next_retry_at)
        return True

    def _run_once(self, job_type: str, trading_date: str, now: datetime, work_fn) -> JobOutcome:
        """Run a run-once-per-day job if its gate allows it this tick,
        recording start/success/failure state and audit events.

        Callers are expected to have already checked their own
        session-window gate (e.g. ``session == SESSION_PRE_MARKET``)
        before calling this -- this method itself only enforces the
        idempotency/backoff gate via :meth:`_may_attempt`.
        """
        if not self._may_attempt(job_type, trading_date, now):
            return JobOutcome(job_type=job_type, attempted=False, outcome="SKIPPED", detail="already succeeded or awaiting retry backoff")
        return self._attempt(job_type, trading_date, now, work_fn)

    def _attempt(self, job_type: str, trading_date: str, now: datetime, work_fn) -> JobOutcome:
        """Record start, run ``work_fn()``, and record success/failure
        -- the one place every job's state-transition + audit-event
        bookkeeping lives, so every job follows the exact same
        restart-safe recipe.

        Args:
            work_fn: A zero-argument callable returning an optional
                ``Dict[str, Any]`` detail payload on success, or
                raising on failure. Never called more than once here.
        """
        started_at = now.isoformat()
        self._state_repo.start(job_type, trading_date, started_at=started_at)
        self._audit.record(
            "job_started",
            created_at=started_at,
            payload={"job_type": job_type, "trading_date": trading_date},
        )
        try:
            detail = work_fn()
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # collaborator failure (fetch error, notification failure,
            # etc.) must be caught here so one job's failure never
            # aborts the rest of this tick's jobs.
            finished_at = now.isoformat()
            row = self._state_repo.get(job_type, trading_date)
            attempt = row.attempt if row is not None else 1
            backoff_seconds = min(
                self._retry_base_seconds * (2 ** max(attempt - 1, 0)),
                self._retry_max_seconds,
            )
            next_retry_at = (now + timedelta(seconds=backoff_seconds)).isoformat()
            error_text = str(exc)[:500]
            self._state_repo.mark_failed(
                job_type,
                trading_date,
                finished_at=finished_at,
                next_retry_at=next_retry_at,
                detail=error_text,
            )
            self._audit.record(
                "job_failed",
                created_at=finished_at,
                payload={
                    "job_type": job_type,
                    "trading_date": trading_date,
                    "error": error_text,
                    "next_retry_at": next_retry_at,
                },
            )
            return JobOutcome(job_type=job_type, attempted=True, outcome="FAILED", detail=error_text)

        finished_at = now.isoformat()
        detail_payload: Dict[str, Any] = dict(detail) if detail else {}
        detail_text = json.dumps(detail_payload) if detail_payload else None
        self._state_repo.mark_success(job_type, trading_date, finished_at=finished_at, detail=detail_text)
        self._audit.record(
            "job_succeeded",
            created_at=finished_at,
            payload={"job_type": job_type, "trading_date": trading_date, **detail_payload},
        )
        return JobOutcome(job_type=job_type, attempted=True, outcome="SUCCESS", detail=detail_text or "")

    # ------------------------------------------------------------------
    # Individual job bodies
    # ------------------------------------------------------------------

    def _job_pre_market_check(self, session: str) -> Dict[str, Any]:
        """No fetch. A lightweight readiness signal only: confirms the
        scheduler itself is running and the IDX session clock agrees
        this is the pre-market window.
        """
        return {"session": session, "message": "pre-market readiness check complete"}

    def _run_session_scan(self, trading_date: str, now: datetime) -> JobOutcome:
        """Run ``session_scan`` for this tick.

        Unlike the run-once jobs, this is NOT gated by
        :meth:`_may_attempt`/``has_succeeded`` -- it is meant to run
        on every open-session tick. Retry/backoff still applies on a
        genuine failure (a failed fetch this tick still respects its
        own ``next_retry_at`` before the *next* tick will attempt
        again), via the same :meth:`_may_attempt` check.
        """
        if not self._may_attempt_repeatable(JOB_SESSION_SCAN, trading_date, now):
            return JobOutcome(
                job_type=JOB_SESSION_SCAN,
                attempted=False,
                outcome="SKIPPED",
                detail="awaiting retry backoff from a prior failed attempt this session",
            )
        return self._attempt(JOB_SESSION_SCAN, trading_date, now, lambda: self._job_session_scan(now))

    def _job_session_scan(self, now: datetime) -> Dict[str, Any]:
        """Fetch a fresh scan via the existing ``ManualScanService``,
        then evaluate a deduplicated Telegram alert for it.

        Never touches ``PaperTradingEngine``/order/trade/position
        persistence -- ``ManualScanService.run_scan`` already only
        ever writes ``ranking_snapshots`` rows (unchanged, pre-existing
        behavior).
        """
        generated_at = now.isoformat()
        report = self._manual_scan_service.run_scan(generated_at)

        signature = _report_signature(report)
        state = self._dedup_repo.get_dedup_state(ALERT_SESSION_SCAN_BRIEF)
        decision = self._dedup_policy.evaluate(state=state, new_signature=signature, now=now)

        notification_outcome = self._apply_dedup_decision(
            alert_type=ALERT_SESSION_SCAN_BRIEF,
            decision=decision,
            new_signature=signature,
            now=now,
            build_event=lambda: NotificationEvent(
                event_type=NotificationEventType.NEW_SIGNAL,
                timestamp=generated_at,
                title="IDX Session Scan",
                message=(
                    f"Session scan at {generated_at}: {report.total_symbols} symbol(s) "
                    f"ranked. Signature changed since the last sent brief."
                ),
                metadata={"generated_at": generated_at, "total_symbols": report.total_symbols},
            ),
        )

        return {
            "generated_at": generated_at,
            "total_symbols": report.total_symbols,
            "notification": notification_outcome,
        }

    def _run_data_health_check(self, trading_date: str, now: datetime) -> JobOutcome:
        """``data_health_check`` runs every tick (never idempotency
        gated) -- it never fetches, so re-evaluating it every tick is
        cheap and is exactly what lets a genuine degradation be caught
        promptly, while ``NotificationDedupPolicy`` keeps the actual
        alert volume bounded.
        """
        return self._attempt_repeatable(
            JOB_DATA_HEALTH_CHECK, trading_date, now, lambda: self._job_data_health_check(now)
        )

    def _attempt_repeatable(self, job_type: str, trading_date: str, now: datetime, work_fn) -> JobOutcome:
        """Same recording contract as :meth:`_attempt`, for a job with
        no idempotency/backoff gate of its own (every tick is a fresh,
        unconditional attempt).
        """
        return self._attempt(job_type, trading_date, now, work_fn)

    def _job_data_health_check(self, now: datetime) -> Dict[str, Any]:
        """No fetch. Evaluates freshness of the most recent successful
        ``session_scan`` observation (reconstructed from the
        append-only audit log -- restart-safe by construction) and
        raises a rate-limited alert on a FRESH<->degraded transition.

        Phase D.1 fix: the last-known-good ``session_scan`` observation
        is the *candidate* being judged for freshness here (this job
        itself never fetches a newer one) -- passed as both
        ``candidate`` and ``last_good`` so ``DataFreshnessPolicy.
        evaluate()`` can actually reach ``FRESH`` when that observation
        is still within the freshness window, while a stale/absent
        observation still resolves to ``STALE``/``MISSING`` exactly as
        before. Never fabricates a value or timestamp -- both
        parameters are the same single observation reconstructed from
        the audit log, with its own original ``observed_at`` preserved
        unchanged either way.
        """
        last_good = self._load_last_good_session_scan_observation()
        result = self._freshness_policy.evaluate(candidate=last_good, now=now, last_good=last_good)

        new_signature = "FRESH" if result.status == FRESH else "DEGRADED"
        state = self._dedup_repo.get_dedup_state(ALERT_DATA_FRESHNESS)
        decision = self._dedup_policy.evaluate(state=state, new_signature=new_signature, now=now)

        recovered = new_signature == "FRESH" and state is not None and state.last_signature == "DEGRADED"
        message = (
            f"IDX data freshness recovered (status={result.status})"
            if recovered
            else f"IDX data freshness degraded (status={result.status}, age_seconds={result.age_seconds})"
        )

        notification_outcome = self._apply_dedup_decision(
            alert_type=ALERT_DATA_FRESHNESS,
            decision=decision,
            new_signature=new_signature,
            now=now,
            build_event=lambda: NotificationEvent(
                event_type=NotificationEventType.DATA_FETCH_FAILED,
                timestamp=now.isoformat(),
                title="IDX Data Freshness" + (" Recovered" if recovered else " Degraded"),
                message=message,
                metadata={"status": result.status, "age_seconds": result.age_seconds},
            ),
        )

        return {
            "status": result.status,
            "age_seconds": result.age_seconds,
            "notification": notification_outcome,
        }

    def _job_market_close_recap(self, now: datetime) -> Dict[str, Any]:
        """Reuse the existing, unmodified ``DailyReportOrchestrator``
        pipeline -- the same one ``python main.py report daily``
        already runs. This is the one Phase D job besides
        ``session_scan`` that performs its own fetch, by design.
        """
        generated_at = now.isoformat()
        event = self._daily_report_orchestrator.run_daily_report(self._account_id, generated_at)
        return {
            "generated_at": generated_at,
            "notification_event_type": event.event_type.value,
            "title": event.title,
        }

    def _job_daily_review(self, trading_date: str, now: datetime) -> Dict[str, Any]:
        """No fetch. Summarizes this trading date's already-persisted
        scheduler-job outcomes -- purely a read over
        ``SchedulerStateRepository``, never a recomputation of
        anything ``session_scan``/``market_close_recap`` already did.
        """
        runs = self._state_repo.list_for_date(trading_date)
        summary = {run.job_type: run.status for run in runs}
        return {
            "trading_date": trading_date,
            "job_summary": summary,
            "reviewed_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _apply_dedup_decision(self, *, alert_type: str, decision, new_signature: str, now: datetime, build_event) -> str:
        """Apply one ``NotificationDedupPolicy`` decision: send (and
        persist the outcome) or persist a suppression, carrying the
        prior ``last_signature``/``last_sent_at`` forward unchanged
        whenever this evaluation itself does not result in a genuine
        send (mirrors ``NotificationDedupRepository.record()``'s own
        documented contract).

        Returns:
            One of ``"SENT"``/``"SUPPRESS_NO_CHANGE"``/
            ``"SUPPRESS_RATE_LIMITED"``/``"FAILED"``.
        """
        previous = self._dedup_repo.get(alert_type)
        prior_signature = previous.last_signature if previous else None
        prior_sent_at = previous.last_sent_at if previous else None
        updated_at = now.isoformat()

        if not decision.should_send:
            self._dedup_repo.record(
                alert_type,
                last_status=DEDUP_STATUS_SUPPRESSED,
                updated_at=updated_at,
                last_signature=prior_signature,
                last_sent_at=prior_sent_at,
            )
            self._audit.record(
                "notification_suppressed",
                created_at=updated_at,
                payload={"alert_type": alert_type, "signature": new_signature, "reason": decision.reason},
            )
            return decision.action

        event = build_event()
        try:
            self._notification_manager.notify(event)
        except Exception as exc:  # noqa: BLE001 -- a Telegram/network
            # failure here must not abort the rest of this tick.
            self._dedup_repo.record(
                alert_type,
                last_status=DEDUP_STATUS_FAILED,
                updated_at=updated_at,
                last_signature=prior_signature,
                last_sent_at=prior_sent_at,
            )
            self._audit.record(
                "notification_failed",
                created_at=updated_at,
                payload={"alert_type": alert_type, "signature": new_signature, "error": str(exc)[:500]},
            )
            return "FAILED"

        self._dedup_repo.record(
            alert_type,
            last_status=DEDUP_STATUS_SENT,
            updated_at=updated_at,
            last_signature=new_signature,
            last_sent_at=updated_at,
        )
        self._audit.record(
            "notification_sent",
            created_at=updated_at,
            payload={"alert_type": alert_type, "signature": new_signature},
        )
        return "SENT"

    def _load_last_good_session_scan_observation(self) -> Optional[Observation]:
        """Reconstruct the most recent successful ``session_scan``
        observation from the append-only audit log -- restart-safe by
        construction (never from in-memory state).

        Best-effort, bounded lookback (the 200 most recent audit
        events): a known limitation, mirroring
        ``Business.idx_market_calendar.KNOWN_LIMITATIONS``'s own
        "report, don't work around" convention -- a session_scan
        success older than the 200 most recent audit events (very
        unlikely within one trading day's tick cadence) is treated the
        same as "never observed", i.e. ``MISSING``, never guessed.
        """
        for event in self._audit.list_recent(limit=200):
            if event.event_type != "job_succeeded":
                continue
            payload = json.loads(event.payload) if event.payload else {}
            if payload.get("job_type") != JOB_SESSION_SCAN:
                continue
            generated_at = payload.get("generated_at")
            if not generated_at:
                continue
            return Observation(value=payload, observed_at=generated_at, source=JOB_SESSION_SCAN)
        return None


def _report_signature(report) -> str:
    """Deterministic signature of "what a session-scan alert would say
    right now", used by ``NotificationDedupPolicy`` to detect a
    material change. Built only from the report's own already-computed
    ``Recommendation`` fields -- no new computation.
    """
    payload = [
        {
            "symbol": rec.symbol,
            "recommendation": rec.recommendation,
            "confidence": rec.confidence,
            "priority": rec.priority,
            "rank": rec.rank,
        }
        for rec in report.recommendations
    ]
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()