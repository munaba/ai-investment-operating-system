"""TelegramInboundStateRepository -- Phase E (Telegram Control Plane,
foundational task).

PERSISTENCE ONLY, mirroring ``Repository.persistence.
notification_dedup_repository.NotificationDedupRepository``: generic
key/value durable state, one row per ``state_key`` (primary key --
see ``Database.migrations_telegram_control.
TELEGRAM_CONTROL_MIGRATIONS``, migration version=26), updated in
place. Restart-safe: a fresh process reads back exactly the last
``last_update_id`` written, so an inbound Telegram long-poller can
resume without re-processing or dropping updates. Never decides
polling behavior itself -- purely storage.
"""

from __future__ import annotations

from typing import List, Optional

from Database.models import TelegramInboundState
from Repository.persistence.base_persistence_repository import BasePersistenceRepository

#: Default ``state_key`` for a single-bot deployment -- the caller may
#: pass any other key to track multiple independent polling identities
#: in the same table.
DEFAULT_STATE_KEY: str = "default"


class TelegramInboundStateRepository(BasePersistenceRepository):
    """Persists and queries ``telegram_inbound_state`` rows."""

    def get(self, state_key: str = DEFAULT_STATE_KEY) -> Optional[TelegramInboundState]:
        """Return the current row for ``state_key``, or ``None`` if
        this key has never been written.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM telegram_inbound_state WHERE state_key = ?",
            (state_key,),
        )
        return self._row_to_state(result.rows[0]) if result.rows else None

    def get_last_update_id(self, state_key: str = DEFAULT_STATE_KEY) -> Optional[int]:
        """Return the durable ``last_update_id`` for ``state_key``, or
        ``None`` if polling has never advanced (or this key has never
        been written).

        Convenience accessor only -- performs no polling itself.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        row = self.get(state_key)
        return row.last_update_id if row is not None else None

    def set_last_update_id(
        self,
        last_update_id: int,
        *,
        updated_at: str,
        state_key: str = DEFAULT_STATE_KEY,
    ) -> TelegramInboundState:
        """Create or overwrite the single row for ``state_key`` with a
        new ``last_update_id``.

        Args:
            last_update_id: The last Telegram ``update_id``
                successfully processed.
            updated_at: ISO-8601 timestamp of this write. Required,
                caller-supplied.
            state_key: Stable identifier for this polling identity.
                Defaults to ``DEFAULT_STATE_KEY`` for a single-bot
                deployment.

        Returns:
            The saved :class:`Database.models.TelegramInboundState`.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        if self.get(state_key) is None:
            self._execute(
                """
                INSERT INTO telegram_inbound_state (state_key, last_update_id, updated_at)
                VALUES (?, ?, ?)
                """,
                (state_key, last_update_id, updated_at),
            )
        else:
            self._execute(
                """
                UPDATE telegram_inbound_state
                SET last_update_id = ?, updated_at = ?
                WHERE state_key = ?
                """,
                (last_update_id, updated_at, state_key),
            )
        return TelegramInboundState(
            state_key=state_key,
            last_update_id=last_update_id,
            updated_at=updated_at,
        )

    def list_all(self) -> List[TelegramInboundState]:
        """Return every inbound-state row, ordered by ``state_key``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM telegram_inbound_state ORDER BY state_key ASC"
        )
        return [self._row_to_state(row) for row in result.rows]

    @staticmethod
    def _row_to_state(row) -> TelegramInboundState:
        return TelegramInboundState(
            state_key=row["state_key"],
            last_update_id=row["last_update_id"],
            updated_at=row["updated_at"],
        )