"""TelegramCommandAuditRepository -- Phase E (Telegram Control Plane,
foundational task).

PERSISTENCE ONLY, mirroring ``Repository.persistence.
audit_event_repository.AuditEventRepository``: append-only log of
every inbound Telegram command received, regardless of outcome.
Never decides whether a command is authorized/executable itself --
that remains a future router/executor's job (explicitly out of scope
for this task, per the Phase E foundational-files constraint). This
repository only persists the outcome a caller already determined.
"""

from __future__ import annotations

from typing import List, Optional

from Database.models import TelegramCommandAudit
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

#: ``status`` values a row may hold -- the outcome of processing one
#: inbound Telegram command, exactly as determined by the caller
#: (a future router/executor). This repository does not interpret or
#: validate these values itself; they are simply the closed set every
#: caller is expected to choose from.
EXECUTED: str = "EXECUTED"
EXECUTED_REPLY_FAILED: str = "EXECUTED_REPLY_FAILED"
REJECTED_UNAUTHORIZED: str = "REJECTED_UNAUTHORIZED"
UNKNOWN_COMMAND: str = "UNKNOWN_COMMAND"
ERROR: str = "ERROR"


class TelegramCommandAuditRepository(BasePersistenceRepository):
    """Persists and queries ``telegram_command_audit`` rows.

    ``record()`` is the only write method -- append-only, exactly like
    ``AuditEventRepository.record()`` -- no update or delete method
    exists anywhere on this class.
    """

    def record(
        self,
        command: str,
        *,
        status: str,
        received_at: str,
        update_id: Optional[int] = None,
        chat_id: Optional[str] = None,
        raw_text: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> TelegramCommandAudit:
        """Append one command-audit row.

        Args:
            command: The parsed command identifier (e.g.
                ``"/status"``). Required, caller-supplied.
            status: One of the module-level outcome constants
                (``EXECUTED`` / ``EXECUTED_REPLY_FAILED`` /
                ``REJECTED_UNAUTHORIZED`` / ``UNKNOWN_COMMAND`` /
                ``ERROR``). Not validated against that set here --
                stored exactly as given.
            received_at: ISO-8601 timestamp of this command. Required,
                caller-supplied -- never generated here.
            update_id: The Telegram ``update_id`` this command came
                from, or ``None`` if not available.
            chat_id: Telegram chat identifier the command was received
                from, or ``None`` if not available.
            raw_text: The raw inbound message text, or ``None``.
            detail: Free-text detail (e.g. an error message), or
                ``None``.

        Returns:
            The newly created
            :class:`Database.models.TelegramCommandAudit`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            INSERT INTO telegram_command_audit
                (update_id, chat_id, command, raw_text, status, detail, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (update_id, chat_id, command, raw_text, status, detail, received_at),
        )
        return TelegramCommandAudit(
            id=result.lastrowid,
            update_id=update_id,
            chat_id=chat_id,
            command=command,
            raw_text=raw_text,
            status=status,
            detail=detail,
            received_at=received_at,
        )

    def list_recent(self, limit: int = 50) -> List[TelegramCommandAudit]:
        """Return the ``limit`` most recent command-audit rows, newest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM telegram_command_audit ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_audit(row) for row in result.rows]

    def list_by_chat(self, chat_id: str, limit: int = 50) -> List[TelegramCommandAudit]:
        """Return the ``limit`` most recent command-audit rows for one
        ``chat_id``, newest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            SELECT * FROM telegram_command_audit
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        return [self._row_to_audit(row) for row in result.rows]

    def list_all(self) -> List[TelegramCommandAudit]:
        """Return every command-audit row, oldest first.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM telegram_command_audit ORDER BY id ASC")
        return [self._row_to_audit(row) for row in result.rows]

    @staticmethod
    def _row_to_audit(row) -> TelegramCommandAudit:
        return TelegramCommandAudit(
            id=row["id"],
            update_id=row["update_id"],
            chat_id=row["chat_id"],
            command=row["command"],
            raw_text=row["raw_text"],
            status=row["status"],
            detail=row["detail"],
            received_at=row["received_at"],
        )