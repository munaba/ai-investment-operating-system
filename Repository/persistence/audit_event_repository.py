"""AuditEventRepository -- Phase D (Proactive IDX Scheduler Routine).

PERSISTENCE ONLY, mirroring ``JournalRepository``/``DecisionBriefRepository``:
append-only log of every scheduler job start/success/failure,
notification sent/suppressed/failed, and freshness degradation/
recovery transition ``Orchestration.idx_daily_scheduler.
IDXDailyScheduler`` produces. Never interprets ``payload`` -- it is
stored and returned exactly as given (a JSON string the caller already
serialized), never parsed by this repository.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from Database.models import AuditEvent
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class AuditEventRepository(BasePersistenceRepository):
    """Persists and queries ``audit_events`` rows.

    ``record()`` is the only write method -- append-only, exactly like
    ``DecisionBriefRepository.create()``/``SnapshotRepository`` -- no
    update or delete method exists anywhere on this class.
    """

    def record(
        self,
        event_type: str,
        *,
        created_at: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Append one audit event row.

        Args:
            event_type: Short machine-readable event name (e.g.
                ``"job_started"``, ``"job_succeeded"``, ``"job_failed"``,
                ``"notification_sent"``, ``"notification_suppressed"``,
                ``"notification_failed"``, ``"freshness_degraded"``,
                ``"freshness_recovered"``).
            created_at: ISO-8601 timestamp of this event. Required,
                caller-supplied -- never generated here.
            payload: Optional free-form event-specific detail dict.
                Serialized to a JSON string by this repository
                (``json.dumps``) -- the caller supplies a plain dict,
                never a pre-serialized string.

        Returns:
            The newly created :class:`Database.models.AuditEvent`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        payload_text = json.dumps(payload) if payload is not None else None
        result = self._execute(
            "INSERT INTO audit_events (event_type, payload, created_at) VALUES (?, ?, ?)",
            (event_type, payload_text, created_at),
        )
        return AuditEvent(
            id=result.lastrowid,
            event_type=event_type,
            payload=payload_text,
            created_at=created_at,
        )

    def list_recent(self, limit: int = 50) -> List[AuditEvent]:
        """Return the ``limit`` most recent audit events, newest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_event(row) for row in result.rows]

    def list_all(self) -> List[AuditEvent]:
        """Return every audit event, oldest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM audit_events ORDER BY id ASC")
        return [self._row_to_event(row) for row in result.rows]

    @staticmethod
    def _row_to_event(row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            event_type=row["event_type"],
            payload=row["payload"],
            created_at=row["created_at"],
        )