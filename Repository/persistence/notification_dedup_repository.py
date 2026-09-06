"""NotificationDedupRepository -- Phase D (Proactive IDX Scheduler Routine).

PERSISTENCE ONLY, mirroring ``SchedulerStateRepository``: stores and
retrieves exactly what ``Orchestration.idx_daily_scheduler.
IDXDailyScheduler`` supplies. Never decides SEND vs SUPPRESS itself --
that remains ``Business.notification_dedup_policy.
NotificationDedupPolicy``'s job. This repository only persists the
outcome of the last evaluation for one ``alert_type``, so a fresh
process restart sees the exact same "what was the last thing sent"
state a long-running process would have.

One row per ``alert_type`` (primary key -- see
``Database.migrations_scheduler.SCHEDULER_MIGRATIONS``, migration
version=23), updated in place -- same mutable-singleton-per-key shape
``RiskLimitsRepository`` already established for its one fixed row,
generalized here to one row per key instead of a single fixed key.
"""

from __future__ import annotations

from typing import List, Optional

from Business.notification_dedup_policy import DedupState
from Database.models import NotificationDedupState
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

#: ``last_status`` values a row may hold -- what actually happened the
#: last time this ``alert_type`` was evaluated, distinct from whether
#: it was ever *sent* (a row can be ``SUPPRESSED``/``FAILED`` and still
#: carry forward a ``last_signature``/``last_sent_at`` from an earlier
#: genuine send).
STATUS_SENT: str = "SENT"
STATUS_SUPPRESSED: str = "SUPPRESSED"
STATUS_FAILED: str = "FAILED"


class NotificationDedupRepository(BasePersistenceRepository):
    """Persists and queries ``notification_dedup_state`` rows."""

    def get(self, alert_type: str) -> Optional[NotificationDedupState]:
        """Return the current row for ``alert_type``, or ``None`` if
        this alert type has never been evaluated.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM notification_dedup_state WHERE alert_type = ?",
            (alert_type,),
        )
        return self._row_to_state(result.rows[0]) if result.rows else None

    def get_dedup_state(self, alert_type: str) -> Optional[DedupState]:
        """Return this ``alert_type``'s current row as the plain
        ``Business.notification_dedup_policy.DedupState`` value object
        ``NotificationDedupPolicy.evaluate()`` expects, or ``None``.

        Convenience conversion only -- performs no evaluation itself.
        """
        row = self.get(alert_type)
        if row is None:
            return None
        return DedupState(
            alert_type=row.alert_type,
            last_signature=row.last_signature,
            last_sent_at=row.last_sent_at,
        )

    def record(
        self,
        alert_type: str,
        *,
        last_status: str,
        updated_at: str,
        last_signature: Optional[str] = None,
        last_sent_at: Optional[str] = None,
    ) -> NotificationDedupState:
        """Create or overwrite the single row for ``alert_type``.

        Args:
            alert_type: Stable identifier for this alert channel.
            last_status: One of ``SENT``/``SUPPRESSED``/``FAILED`` --
                the outcome of the most recent evaluation, whatever it
                was.
            updated_at: ISO-8601 timestamp of this write. Required,
                caller-supplied.
            last_signature: The signature of the last alert actually
                *sent*. When ``last_status != SENT``, the caller is
                expected to pass through the previous row's
                ``last_signature``/``last_sent_at`` unchanged (this
                repository does not infer that itself) so a
                suppressed/failed evaluation never erases the record
                of the last genuine send.
            last_sent_at: ISO-8601 timestamp of the last actual send.

        Returns:
            The saved :class:`Database.models.NotificationDedupState`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        if self.get(alert_type) is None:
            self._execute(
                """
                INSERT INTO notification_dedup_state
                    (alert_type, last_signature, last_sent_at, last_status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (alert_type, last_signature, last_sent_at, last_status, updated_at),
            )
        else:
            self._execute(
                """
                UPDATE notification_dedup_state
                SET last_signature = ?, last_sent_at = ?, last_status = ?, updated_at = ?
                WHERE alert_type = ?
                """,
                (last_signature, last_sent_at, last_status, updated_at, alert_type),
            )
        return NotificationDedupState(
            alert_type=alert_type,
            last_signature=last_signature,
            last_sent_at=last_sent_at,
            last_status=last_status,
            updated_at=updated_at,
        )

    def list_all(self) -> List[NotificationDedupState]:
        """Return every dedup-state row, ordered by ``alert_type``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM notification_dedup_state ORDER BY alert_type ASC"
        )
        return [self._row_to_state(row) for row in result.rows]

    @staticmethod
    def _row_to_state(row) -> NotificationDedupState:
        return NotificationDedupState(
            alert_type=row["alert_type"],
            last_signature=row["last_signature"],
            last_sent_at=row["last_sent_at"],
            last_status=row["last_status"],
            updated_at=row["updated_at"],
        )