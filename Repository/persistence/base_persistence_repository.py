from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

from Core.exceptions import DatabaseError, RepositoryError
from Database.base_database import QueryResult
from Database.database_manager import DatabaseManager
from Database.session import Session
from Repository.base_repository import BaseRepository


class BasePersistenceRepository(BaseRepository):
    """Contract shared by every repository backed by :class:`DatabaseManager`.

    Concrete persistence repositories (e.g. a future ``WatchlistRepository``)
    depend only on ``DatabaseManager`` -- never on a concrete backend such
    as ``Database.sqlite_database.SQLiteDatabase`` directly -- so the
    backend can change without repositories changing.

    Provides two protected helpers, ``_execute`` and ``_session``, which
    are thin passthroughs to ``DatabaseManager`` that additionally translate
    any ``DatabaseError`` into a ``RepositoryError`` (preserving the
    original exception via ``from exc``/``__cause__``). This is the only
    behavior added here; no generic CRUD (``get``/``save``/``delete``) is
    provided -- concrete repositories write their own SQL via these
    helpers.
    """

    def __init__(self, database_manager: DatabaseManager) -> None:
        """Initialize with the database manager to use, via constructor injection.

        Args:
            database_manager: The :class:`Database.database_manager.
                DatabaseManager` this repository issues statements
                through. Never a concrete backend directly.
        """
        self._database_manager = database_manager

    def health_check(self) -> bool:
        """Check whether the underlying database is currently reachable.

        Never raises: mirrors ``DatabaseManager.health_check()``, which
        already catches and logs any failure internally.

        Returns:
            ``True`` if the underlying database responded successfully,
            ``False`` otherwise.
        """
        return self._database_manager.health_check()

    def _execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> QueryResult:
        """Execute a single statement outside of an explicit transaction.

        Thin passthrough to ``DatabaseManager.execute`` for one-off
        reads/writes that don't need transactional grouping.

        Args:
            sql: The SQL statement to execute.
            params: Optional positional parameters to bind.

        Returns:
            A normalized :class:`Database.base_database.QueryResult`.

        Raises:
            RepositoryError: If the underlying statement fails. The
                original ``DatabaseError`` is preserved as ``__cause__``.
        """
        try:
            return self._database_manager.execute(sql, params)
        except DatabaseError as exc:
            raise RepositoryError(
                f"Repository statement failed: {sql}", details={"error": str(exc)}
            ) from exc

    @contextmanager
    def _session(self, *, exclusive: bool = False) -> Iterator[Session]:
        """Open a transactional session on the underlying database.

        Thin passthrough to ``DatabaseManager.session``; does not
        introduce any new transaction mechanism. Commits on clean exit,
        rolls back if the block raises -- see
        ``Database.database_manager.DatabaseManager.session``.

        Args:
            exclusive: Request the backend's strongest available
                isolation for this transaction. See
                ``DatabaseManager.session`` for details.

        Yields:
            A :class:`Database.session.Session` bound to a fresh
            transaction on the underlying database.

        Raises:
            RepositoryError: If beginning, committing, or rolling back the
                transaction fails, or if a statement executed inside the
                ``with`` block raises ``DatabaseError``. The original
                ``DatabaseError`` is preserved as ``__cause__``.
        """
        try:
            with self._database_manager.session(exclusive=exclusive) as session:
                yield session
        except DatabaseError as exc:
            raise RepositoryError(
                "Repository session failed", details={"error": str(exc)}
            ) from exc