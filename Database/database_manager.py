from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

from Core.logger import get_logger
from .base_database import BaseDatabase, QueryResult
from .database_config import DatabaseConfig
from .session import Session, transaction

logger = get_logger(__name__)


class DatabaseManager:
    """Manages a single :class:`BaseDatabase`'s connection lifecycle.

    Responsible only for connection, closing, transactions, and health
    checks -- never business logic. The (future) Repository layer
    depends on ``DatabaseManager`` rather than on a concrete database
    backend directly, so the backend can change without Repositories
    changing.

    Attributes:
        config: The :class:`DatabaseConfig` in use, kept for reference
            (e.g. diagnostics/logging). Does not affect ``database``,
            which is already fully configured by the time it is injected
            here via the constructor.
    """

    def __init__(self, database: BaseDatabase, config: Optional[DatabaseConfig] = None) -> None:
        """Initialize with a database instance via constructor injection.

        Args:
            database: The concrete :class:`BaseDatabase` implementation to
                manage (e.g. a
                :class:`Database.sqlite_database.SQLiteDatabase`).
            config: Optional configuration snapshot associated with
                ``database``, kept for reference/diagnostics only.
        """
        self._database: BaseDatabase = database
        self.config: Optional[DatabaseConfig] = config

    @property
    def database(self) -> BaseDatabase:
        """The underlying :class:`BaseDatabase` this manager owns."""
        return self._database

    @property
    def is_connected(self) -> bool:
        """Whether the underlying database currently holds a live connection."""
        return self._database.is_connected

    def connect(self) -> None:
        """Open the underlying database connection.

        Raises:
            DatabaseError: If the connection could not be established.
        """
        self._database.connect()

    def disconnect(self) -> None:
        """Close the underlying database connection."""
        self._database.disconnect()

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> QueryResult:
        """Execute a single statement outside of an explicit transaction.

        Convenience passthrough to
        :meth:`Database.base_database.BaseDatabase.execute` for one-off
        reads/writes that don't need transactional grouping. This is
        plumbing, not business logic: it adds no interpretation of the
        SQL or its results.

        Args:
            sql: The SQL statement to execute.
            params: Optional positional parameters to bind.

        Returns:
            A normalized :class:`QueryResult`.
        """
        return self._database.execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> QueryResult:
        """Passthrough to
        :meth:`Database.base_database.BaseDatabase.executemany`.
        """
        return self._database.executemany(sql, seq_of_params)

    @contextmanager
    def session(self, *, exclusive: bool = False) -> Iterator[Session]:
        """Open a transactional session.

        Nests via a savepoint (rather than raising) if a transaction is
        already active on the underlying database -- see
        :meth:`Database.base_database.BaseDatabase.begin`.

        Args:
            exclusive: Request the backend's strongest available
                isolation for this transaction (serializes against other
                writers, including other processes). Only meaningful when
                not nested inside another active transaction. Most
                callers won't need this -- it exists primarily for
                one-off maintenance operations like schema migrations.

        Yields:
            A :class:`Database.session.Session` bound to a fresh
            transaction on the underlying database. Commits on clean
            exit, rolls back if the block raises.

        Example:
            >>> with database_manager.session() as session:
            ...     session.execute("INSERT INTO watchlist (...) VALUES (...)")
        """
        with transaction(self._database, exclusive=exclusive) as active_session:
            yield active_session

    def health_check(self) -> bool:
        """Check whether the underlying database is currently healthy.

        Never raises: any failure is caught, logged, and reported as
        ``False``, mirroring the ``health_check()`` contract shared by
        ``BaseProvider`` and ``BaseService``.

        Returns:
            ``True`` if the database responded successfully, ``False``
            otherwise.
        """
        try:
            return self._database.health_check()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"DatabaseManager.health_check failed: {exc}")
            return False