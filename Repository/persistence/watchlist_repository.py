from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class WatchlistRepository(BasePersistenceRepository):
    """Persists and queries the user's stock watchlist.

    Backed by the ``watchlist`` table (see
    ``Database.migrations_watchlist.WATCHLIST_MIGRATIONS``):
    ``ticker`` (TEXT PRIMARY KEY) and ``added_at`` (TEXT, ISO-8601 UTC).
    No surrogate id, no multi-user scoping, no notes/category, no other
    metadata -- deliberately minimal per the A2 scope decision. Extending
    the schema later is a new migration, not a change to this repository's
    shape.

    Exposes exactly four operations -- ``add``, ``remove``, ``exists``,
    ``list_all`` -- and no generic CRUD (``update``/``save``/``upsert``/
    ``get_by_id``/``search``), per the same A2 scope decision: none of
    that has a use-case yet.

    Takes only ``DatabaseManager`` via the inherited
    ``BasePersistenceRepository.__init__`` (constructor injection) --
    no constructor override needed here, since this repository has no
    behavior beyond what the base class already provides.
    """

    def add(self, ticker: str) -> None:
        """Add ``ticker`` to the watchlist.

        Idempotent: if ``ticker`` is already present, this is a no-op
        (``INSERT OR IGNORE``) -- ``added_at`` is not updated on a
        repeat ``add()`` of an already-present ticker.

        Args:
            ticker: The ticker symbol to add.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        added_at = datetime.now(timezone.utc).isoformat()
        self._execute(
            "INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?, ?)",
            (ticker, added_at),
        )

    def remove(self, ticker: str) -> None:
        """Remove ``ticker`` from the watchlist, if present.

        Idempotent: removing a ticker that isn't on the watchlist is a
        no-op, not an error.

        Args:
            ticker: The ticker symbol to remove.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        self._execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))

    def exists(self, ticker: str) -> bool:
        """Check whether ``ticker`` is currently on the watchlist.

        Args:
            ticker: The ticker symbol to check.

        Returns:
            ``True`` if ``ticker`` is on the watchlist, ``False``
            otherwise.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT 1 FROM watchlist WHERE ticker = ?", (ticker,))
        return len(result.rows) > 0

    def list_all(self) -> List[str]:
        """Return every ticker currently on the watchlist.

        Args:
            None.

        Returns:
            Ticker symbols, ordered by ``added_at`` ascending (oldest
            addition first).

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT ticker FROM watchlist ORDER BY added_at ASC")
        return [row["ticker"] for row in result.rows]