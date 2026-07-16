from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence

from Core.exceptions import DatabaseError
from Core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DB_PATH: str = "data_saham.db"


class DatabaseManager:
    """Thread-safe singleton wrapper around a SQLite database.

    SQLite connections are not safe to share across threads, so each thread
    that calls :meth:`connect` receives its own ``sqlite3.Connection``
    stored in thread-local storage. A shared lock serializes write-heavy
    operations (transactions, backup, vacuum) to avoid ``database is
    locked`` errors when multiple threads write concurrently.

    Can be used as a context manager to automatically connect/disconnect::

        with DatabaseManager() as db:
            db.execute("SELECT 1")

    Attributes:
        db_path: Filesystem path to the SQLite database file.
    """

    _instance: Optional["DatabaseManager"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls, db_path: str = DEFAULT_DB_PATH) -> "DatabaseManager":
        """Create or return the existing singleton instance.

        Args:
            db_path: Path to the SQLite database file. Only used the first
                time the singleton is created.

        Returns:
            The single shared ``DatabaseManager`` instance.
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """Initialize the singleton exactly once.

        Args:
            db_path: Path to the SQLite database file.
        """
        if self._initialized:
            return
        self.db_path: Path = Path(db_path)
        self._local: threading.local = threading.local()
        self._write_lock: threading.Lock = threading.Lock()
        self._initialized = True
        logger.debug(f"DatabaseManager initialized with db_path={self.db_path}")

    def connect(self) -> sqlite3.Connection:
        """Return the current thread's SQLite connection, opening it if needed.

        Returns:
            An open ``sqlite3.Connection`` bound to the calling thread.

        Raises:
            DatabaseError: If the connection could not be opened.
        """
        connection: Optional[sqlite3.Connection] = getattr(self._local, "connection", None)
        if connection is not None:
            return connection

        try:
            connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                isolation_level=None,  
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._local.connection = connection
            logger.debug(
                f"Opened SQLite connection to '{self.db_path}' "
                f"on thread '{threading.current_thread().name}'"
            )
            return connection
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"Failed to connect to database at '{self.db_path}'",
                details={"error": str(exc)},
            ) from exc

    def disconnect(self) -> None:
        """Close the current thread's SQLite connection, if open.

        Raises:
            DatabaseError: If closing the connection fails.
        """
        connection: Optional[sqlite3.Connection] = getattr(self._local, "connection", None)
        if connection is None:
            return
        try:
            connection.close()
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to close database connection", details={"error": str(exc)}) from exc
        finally:
            self._local.connection = None
            logger.debug("Closed SQLite connection")

    def __enter__(self) -> "DatabaseManager":
        """Enter the context manager, opening a connection for this thread."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the context manager, closing this thread's connection."""
        self.disconnect()

    def execute(self, query: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        """Execute a single parameterized SQL statement.

        Args:
            query: SQL statement containing ``?`` placeholders.
            params: Values to bind to the placeholders in ``query``.

        Returns:
            The resulting ``sqlite3.Cursor``.

        Raises:
            DatabaseError: If execution fails.
        """
        connection = self.connect()
        try:
            return connection.execute(query, params)
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Query execution failed", details={"query": query, "error": str(exc)}
            ) from exc

    def executemany(self, query: str, seq_of_params: Sequence[Sequence[Any]]) -> sqlite3.Cursor:
        """Execute a parameterized SQL statement against a sequence of parameter sets.

        Args:
            query: SQL statement containing ``?`` placeholders.
            seq_of_params: Sequence of parameter tuples/lists, one per row.

        Returns:
            The resulting ``sqlite3.Cursor``.

        Raises:
            DatabaseError: If execution fails.
        """
        connection = self.connect()
        try:
            return connection.executemany(query, seq_of_params)
        except sqlite3.Error as exc:
            raise DatabaseError(
                "Batch query execution failed", details={"query": query, "error": str(exc)}
            ) from exc

    def fetchone(self, query: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        """Execute a query and fetch a single row.

        Args:
            query: SQL statement containing ``?`` placeholders.
            params: Values to bind to the placeholders in ``query``.

        Returns:
            The first matching row, or ``None`` if no row matched.
        """
        cursor = self.execute(query, params)
        return cursor.fetchone()

    def fetchall(self, query: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        """Execute a query and fetch all matching rows.

        Args:
            query: SQL statement containing ``?`` placeholders.
            params: Values to bind to the placeholders in ``query``.

        Returns:
            A list of all matching rows (possibly empty).
        """
        cursor = self.execute(query, params)
        return cursor.fetchall()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager providing an atomic, all-or-nothing SQL transaction.

        Begins a transaction on entry; commits on successful exit; rolls
        back automatically if any exception is raised inside the ``with``
        block. A write lock is held for the duration of the transaction to
        keep concurrent writes from different threads serialized.

        Yields:
            The active ``sqlite3.Connection`` to run statements against.

        Raises:
            DatabaseError: If the transaction fails and is rolled back.

        Example:
            >>> with database_manager.transaction() as conn:
            ...     conn.execute("INSERT INTO chat_history (id) VALUES (?)", ("1",))
            ...     conn.execute("INSERT INTO audit_logs (id) VALUES (?)", ("2",))
        """
        connection = self.connect()
        with self._write_lock:
            try:
                connection.execute("BEGIN")
                yield connection
                connection.execute("COMMIT")
            except Exception as exc:
                connection.execute("ROLLBACK")
                logger.warning(f"Transaction rolled back due to: {exc}")
                if isinstance(exc, DatabaseError):
                    raise
                raise DatabaseError(
                    "Transaction failed and was rolled back", details={"error": str(exc)}
                ) from exc

    def backup(self, destination_path: str) -> None:
        """Create a full backup copy of the database using SQLite's backup API.

        Args:
            destination_path: Filesystem path where the backup file will be
                written.

        Raises:
            DatabaseError: If the backup operation fails.
        """
        source = self.connect()
        destination: Optional[sqlite3.Connection] = None
        try:
            destination = sqlite3.connect(destination_path)
            with self._write_lock:
                source.backup(destination)
            logger.info(f"Database backed up to '{destination_path}'")
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"Failed to backup database to '{destination_path}'", details={"error": str(exc)}
            ) from exc
        finally:
            if destination is not None:
                destination.close()

    def vacuum(self) -> None:
        """Rebuild the database file to reclaim unused space and defragment it.

        Raises:
            DatabaseError: If the VACUUM operation fails.
        """
        connection = self.connect()
        try:
            with self._write_lock:
                connection.execute("VACUUM")
            logger.info("Database vacuumed successfully")
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to vacuum database", details={"error": str(exc)}) from exc

    def table_exists(self, table_name: str) -> bool:
        """Check whether a table exists in the database.

        Args:
            table_name: Name of the table to check.

        Returns:
            ``True`` if the table exists, ``False`` otherwise.
        """
        row = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return row is not None

database_manager: DatabaseManager = DatabaseManager()