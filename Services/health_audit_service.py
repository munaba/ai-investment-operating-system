"""``HealthAuditService`` -- Phase D ("Proactive IDX Scheduler Routine").

Read-only aggregator over Phase D's three persistence tables --
``SchedulerStateRepository``/``NotificationDedupRepository``/
``AuditEventRepository`` -- built exclusively for the
``python main.py scheduler status`` CLI command (and any future
operator-facing health view). This service invents nothing and
computes nothing: every field on ``HealthSnapshot`` is copied verbatim
from a row one of the three repositories already returned.

This service never calls ``Orchestration.idx_daily_scheduler.
IDXDailyScheduler.tick`` itself, never writes any of the three tables
it reads, and never touches ``PaperTradingEngine``/
``OrderLifecycleService``/``ExecutionService``. It is purely a
read-side view over state ``IDXDailyScheduler`` already produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from Business.idx_market_calendar import IDXMarketCalendar
from Database.models import AuditEvent, NotificationDedupState, SchedulerJobRun
from Repository.persistence.audit_event_repository import AuditEventRepository
from Repository.persistence.notification_dedup_repository import NotificationDedupRepository
from Repository.persistence.scheduler_state_repository import SchedulerStateRepository

#: Default number of most-recent audit events a snapshot includes.
DEFAULT_RECENT_EVENTS_LIMIT: int = 20


@dataclass(frozen=True)
class HealthSnapshot:
    """A point-in-time, read-only view of Phase D's persisted state.

    Attributes:
        trading_date: The IDX-local trading date this snapshot's
            ``jobs`` are scoped to (``YYYY-MM-DD``).
        jobs: Every ``scheduler_job_runs`` row for ``trading_date``,
            ordered by ``job_type`` (verbatim from
            ``SchedulerStateRepository.list_for_date``).
        dedup_states: Every ``notification_dedup_state`` row, ordered
            by ``alert_type`` (verbatim from
            ``NotificationDedupRepository.list_all``) -- not scoped to
            ``trading_date`` (a dedup row's own ``last_sent_at`` may
            predate today; showing all of them is what lets an
            operator see "did today's degradation alert actually fire,
            or is that still yesterday's").
        recent_events: The ``limit`` most recent audit events across
            all job types/trading dates, newest first (verbatim from
            ``AuditEventRepository.list_recent``).
    """

    trading_date: str
    jobs: tuple = field(default_factory=tuple)
    dedup_states: tuple = field(default_factory=tuple)
    recent_events: tuple = field(default_factory=tuple)


class HealthAuditService:
    """Builds a :class:`HealthSnapshot` from Phase D's three
    persistence repositories.

    Constructor injection only, mirroring every other Service in this
    codebase. Stateless beyond its four collaborators -- safe to reuse
    across calls.
    """

    def __init__(
        self,
        scheduler_state_repository: SchedulerStateRepository,
        notification_dedup_repository: NotificationDedupRepository,
        audit_event_repository: AuditEventRepository,
        idx_market_calendar: IDXMarketCalendar,
    ) -> None:
        self._state_repo = scheduler_state_repository
        self._dedup_repo = notification_dedup_repository
        self._audit_repo = audit_event_repository
        self._calendar = idx_market_calendar

    def get_snapshot(
        self,
        *,
        trading_date: Optional[str] = None,
        now: Optional[datetime] = None,
        recent_events_limit: int = DEFAULT_RECENT_EVENTS_LIMIT,
    ) -> HealthSnapshot:
        """Build a :class:`HealthSnapshot` for ``trading_date``.

        Args:
            trading_date: IDX-local ``YYYY-MM-DD`` date to scope
                ``jobs`` to. When omitted, derived from ``now`` (or
                the real current UTC time when ``now`` is also
                omitted) via ``IDXMarketCalendar.local_date`` -- the
                exact same trading-date computation
                ``IDXDailyScheduler.tick`` itself uses, so
                ``scheduler status`` with no arguments always shows
                "today" in the same sense the scheduler itself means
                it.
            now: Only consulted when ``trading_date`` is omitted. When
                also omitted, ``datetime.now(timezone.utc)`` is used
                -- this is a read-only status view, not a scheduling
                decision, so a real wall-clock default here (unlike
                every ``IDXDailyScheduler`` job body) does not affect
                restart-safety.
            recent_events_limit: How many of the most recent audit
                events (across all dates/job types) to include.

        Returns:
            A :class:`HealthSnapshot`. Never raises for "nothing has
            happened yet on this date" -- every field is simply empty.
        """
        if trading_date is None:
            moment = now if now is not None else datetime.now(timezone.utc)
            trading_date = self._calendar.local_date(moment).isoformat()

        jobs: List[SchedulerJobRun] = self._state_repo.list_for_date(trading_date)
        dedup_states: List[NotificationDedupState] = self._dedup_repo.list_all()
        recent_events: List[AuditEvent] = self._audit_repo.list_recent(limit=recent_events_limit)

        return HealthSnapshot(
            trading_date=trading_date,
            jobs=tuple(jobs),
            dedup_states=tuple(dedup_states),
            recent_events=tuple(recent_events),
        )