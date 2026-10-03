"""SchedulerStateRepository -- Phase D (Proactive IDX Scheduler Routine).

PERSISTENCE ONLY, mirroring ``RiskLimitsRepository``/``DecisionBriefRepository``:
stores and retrieves exactly what ``Orchestration.idx_daily_scheduler.
IDXDailyScheduler`` supplies. Never decides *whether* a job may run
(that is the scheduler's own gating logic, built from
``Business.idx_market_calendar.IDXMarketCalendar`` and this
repository's own read methods) -- this repository only records what
already happened.

One row per ``(job_type, trading_date)`` pair (the table's own composite
primary key -- see ``Database.migrations_scheduler.SCHEDULER_MIGRATIONS``,
migration version=22). This is the *sole* mechanism restart-safety
depends on: re-reading this table after a fresh process start yields
the exact same "has job X already succeeded for trading date Y"
answer a long-running process would have given.
"""

from __future__ import annotations

from typing import List, Optional

from Database.models import SchedulerJobRun
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

#: Statuses a ``scheduler_job_runs`` row may hold. Not a Python ``Enum``
#: -- this module's other Phase D siblings (``DataFreshnessPolicy``,
#: ``NotificationDedupPolicy``) already use plain string constants, so
#: this repository follows the same convention.
STATUS_RUNNING: str = "RUNNING"
STATUS_SUCCESS: str = "SUCCESS"
STATUS_FAILED: str = "FAILED"


class SchedulerStateRepository(BasePersistenceRepository):
    """Persists and queries ``scheduler_job_runs`` rows.

    ``start()`` is the one upsert-shaped write: it creates the row on
    first attempt for a ``(job_type, trading_date)`` pair, or updates
    the same row in place on a retry (incrementing ``attempt``) --
    exactly the "one row, updated in place" convention
    ``RiskLimitsRepository.save()`` already established for a mutable
    row, generalized here to a composite key.
    """

    def get(self, job_type: str, trading_date: str) -> Optional[SchedulerJobRun]:
        """Return the current row for ``(job_type, trading_date)``, or
        ``None`` if this job has never been attempted for that date.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM scheduler_job_runs WHERE job_type = ? AND trading_date = ?",
            (job_type, trading_date),
        )
        return self._row_to_run(result.rows[0]) if result.rows else None

    def has_succeeded(self, job_type: str, trading_date: str) -> bool:
        """Return whether ``job_type`` already has a ``SUCCESS`` row for
        ``trading_date`` -- the single idempotency check every
        run-once-per-day Phase D job (pre-market check, market-close
        recap, daily review) consults before executing.
        """
        row = self.get(job_type, trading_date)
        return row is not None and row.status == STATUS_SUCCESS

    def start(
        self,
        job_type: str,
        trading_date: str,
        *,
        started_at: str,
    ) -> SchedulerJobRun:
        """Record the start of one attempt at ``job_type`` for
        ``trading_date``.

        First attempt for this ``(job_type, trading_date)`` pair ->
        insert a new row, ``attempt=1``. Any subsequent call (a retry
        after a prior ``FAILED`` attempt, or a fresh attempt for a
        repeatable job such as ``session_scan``) -> update the same
        row in place, ``attempt`` incremented by one, ``status`` reset
        to ``RUNNING``, ``finished_at``/``next_retry_at`` cleared.

        Args:
            job_type: Fixed Phase D job identifier.
            trading_date: IDX-local (``YYYY-MM-DD``) trading date this
                run belongs to.
            started_at: ISO-8601 timestamp of this attempt's start.
                Required, caller-supplied -- never generated here.

        Returns:
            The newly written :class:`Database.models.SchedulerJobRun`.
        """
        existing = self.get(job_type, trading_date)
        if existing is None:
            self._execute(
                """
                INSERT INTO scheduler_job_runs
                    (job_type, trading_date, status, attempt, started_at,
                     finished_at, next_retry_at, detail)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (job_type, trading_date, STATUS_RUNNING, 1, started_at),
            )
            attempt = 1
        else:
            attempt = existing.attempt + 1
            self._execute(
                """
                UPDATE scheduler_job_runs
                SET status = ?, attempt = ?, started_at = ?,
                    finished_at = NULL, next_retry_at = NULL, detail = NULL
                WHERE job_type = ? AND trading_date = ?
                """,
                (STATUS_RUNNING, attempt, started_at, job_type, trading_date),
            )
        return SchedulerJobRun(
            job_type=job_type,
            trading_date=trading_date,
            status=STATUS_RUNNING,
            attempt=attempt,
            started_at=started_at,
            finished_at=None,
            next_retry_at=None,
            detail=None,
        )

    def mark_success(
        self,
        job_type: str,
        trading_date: str,
        *,
        finished_at: str,
        detail: Optional[str] = None,
    ) -> Optional[SchedulerJobRun]:
        """Mark the current row ``SUCCESS``. Returns ``None`` if no
        row exists yet for ``(job_type, trading_date)`` (``start()``
        was never called) -- callers are expected to always call
        ``start()`` first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        if self.get(job_type, trading_date) is None:
            return None
        self._execute(
            """
            UPDATE scheduler_job_runs
            SET status = ?, finished_at = ?, next_retry_at = NULL, detail = ?
            WHERE job_type = ? AND trading_date = ?
            """,
            (STATUS_SUCCESS, finished_at, detail, job_type, trading_date),
        )
        return self.get(job_type, trading_date)

    def mark_failed(
        self,
        job_type: str,
        trading_date: str,
        *,
        finished_at: str,
        next_retry_at: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> Optional[SchedulerJobRun]:
        """Mark the current row ``FAILED``, optionally scheduling a
        retry (``next_retry_at``) -- the backoff timestamp
        ``IDXDailyScheduler`` computes and consults before attempting
        another ``start()`` for the same ``(job_type, trading_date)``.

        Returns ``None`` if no row exists yet (mirrors ``mark_success``).

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        if self.get(job_type, trading_date) is None:
            return None
        self._execute(
            """
            UPDATE scheduler_job_runs
            SET status = ?, finished_at = ?, next_retry_at = ?, detail = ?
            WHERE job_type = ? AND trading_date = ?
            """,
            (STATUS_FAILED, finished_at, next_retry_at, detail, job_type, trading_date),
        )
        return self.get(job_type, trading_date)

    def list_for_date(self, trading_date: str) -> List[SchedulerJobRun]:
        """Return every job row recorded for ``trading_date``, ordered
        by ``job_type`` -- used by ``Services.health_audit_service.
        HealthAuditService`` / ``python main.py scheduler status``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM scheduler_job_runs WHERE trading_date = ? ORDER BY job_type ASC",
            (trading_date,),
        )
        return [self._row_to_run(row) for row in result.rows]

    def list_all(self) -> List[SchedulerJobRun]:
        """Return every job row ever recorded, ordered by
        ``trading_date`` then ``job_type``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM scheduler_job_runs ORDER BY trading_date ASC, job_type ASC"
        )
        return [self._row_to_run(row) for row in result.rows]

    @staticmethod
    def _row_to_run(row) -> SchedulerJobRun:
        return SchedulerJobRun(
            job_type=row["job_type"],
            trading_date=row["trading_date"],
            status=row["status"],
            attempt=row["attempt"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            next_retry_at=row["next_retry_at"],
            detail=row["detail"],
        )