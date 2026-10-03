from __future__ import annotations

import sqlite3
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from Core.exceptions import DatabaseError
from Core.logger import get_logger
from .base_database import BaseDatabase, QueryResult
from .database_config import DatabaseConfig

logger = get_logger(__name__)

_BARE_MEMORY_PATH = ":memory:"
_ROOT_TRANSACTION = "__root__"


class SQLiteDatabase(BaseDatabase):
    """SQLite-backed implementation of :class:`BaseDatabase`.

    Holds one ``sqlite3.Connection`` per thread (SQLite connections are
    not safe to share across threads), so a single ``SQLiteDatabase``
    instance can be shared by multiple threads without callers needing to
    manage connections themselves. No business logic lives here -- only
    the mechanics of talking to SQLite.

    Connection lifecycle:
        Each thread lazily opens its own connection on first use and owns
        it until that thread calls ``disconnect()`` -- or, if it never
        does (e.g. a thread-pool worker that dies without cleaning up),
        the connection is closed automatically as a last resort once the
        thread object itself is garbage collected. This instance also
        tracks every connection it has opened (across all threads) so
        that :meth:`close_all` can shut everything down cleanly, e.g. at
        application exit.

    Nested transactions:
        ``begin()``/``commit()``/``rollback()`` nest via ``SAVEPOINT``
        when called while a transaction is already active on the calling
        thread's connection -- see :class:`Database.base_database.BaseDatabase`
        for the full contract.

    The ``:memory:`` trap:
        A bare ``":memory:"`` database path is rejected at construction
        time. Because each thread gets its *own* connection, a bare
        ``:memory:`` database is a different, empty database per thread --
        data written by one thread would silently be invisible to
        another, with no error. If you genuinely want an in-memory
        database usable from multiple threads, use SQLite's shared-cache
        URI form with ``uri_mode=True``, e.g.::

            DatabaseConfig(db_path="file::memory:?cache=shared", uri_mode=True)

        This is still subject to SQLite's own shared-cache caveat: the
        in-memory database is destroyed once its last connection closes,
        so at least one connection must stay open for the data to
        persist across a thread reconnecting later. Prefer a real file
        path (or single-threaded, single-connection use) unless you
        specifically need this. See ``Database/ARCHITECTURE.md``.

    Attributes:
        config: The :class:`DatabaseConfig` this instance was built from.
    """

    def __init__(self, config: Optional[DatabaseConfig] = None) -> None:
        """Initialize the backend without opening a connection yet.

        Args:
            config: Connection/pragma configuration. Defaults to
                :meth:`DatabaseConfig.from_env`.

        Raises:
            DatabaseError: If ``config`` uses a bare ``":memory:"`` path
                without ``uri_mode=True`` -- see the class docstring.
        """
        self.config: DatabaseConfig = config or DatabaseConfig.from_env()
        self._local: threading.local = threading.local()
        self._registry_lock: threading.Lock = threading.Lock()
        # thread ident -> live sqlite3.Connection, for close_all()/introspection.
        self._connections: Dict[int, sqlite3.Connection] = {}
        # thread ident -> that connection's leak-detection finalizer, so
        # close_all() can detach() them (a connection this method closes
        # should never also be closed again later by a finalizer running
        # on an arbitrary GC thread).
        self._finalizers: Dict[int, "weakref.finalize"] = {}
        self._reject_unsafe_bare_memory_path()

    def _reject_unsafe_bare_memory_path(self) -> None:
        """Raise early if configured with the unsafe bare ``:memory:`` path."""
        if str(self.config.db_path) == _BARE_MEMORY_PATH and not self.config.uri_mode:
            raise DatabaseError(
                "Refusing to use a bare ':memory:' database path: "
                "SQLiteDatabase gives each thread its own connection, so "
                "every thread would silently get its own separate, empty "
                "in-memory database. Use a shared-cache URI instead, e.g. "
                "DatabaseConfig(db_path='file::memory:?cache=shared', "
                "uri_mode=True), or use a real file path.",
                details={"db_path": _BARE_MEMORY_PATH},
            )

    @property
    def is_connected(self) -> bool:
        """Whether the calling thread currently holds a live connection."""
        return getattr(self._local, "connection", None) is not None

    @property
    def in_transaction(self) -> bool:
        """Whether the calling thread's connection has an open transaction
        (top-level or nested savepoint)."""
        return bool(getattr(self._local, "savepoint_stack", None))

    @property
    def active_connection_count(self) -> int:
        """Number of live connections this instance currently tracks,
        across all threads. Diagnostic use (e.g. shutdown/health checks)."""
        with self._registry_lock:
            return len(self._connections)

    def connect(self) -> None:
        """Open a connection for the calling thread and apply pragmas.

        Idempotent per thread: does nothing if the calling thread already
        holds a connection. Creates the parent directory of ``db_path``
        if it does not exist yet (skipped in ``uri_mode``, since the path
        may not be a plain filesystem path).

        Registers this connection for lifecycle tracking, and arranges
        for it to be closed automatically if the owning thread is
        garbage-collected without an explicit :meth:`disconnect` call.

        Raises:
            DatabaseError: If the connection cannot be opened.
        """
        if self.is_connected:
            return
        path_str = str(self.config.db_path)
        try:
            if not self.config.uri_mode:
                Path(path_str).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                path_str,
                timeout=self.config.timeout,
                isolation_level=None,  # manual transaction control via begin/commit/rollback
                # check_same_thread=False is required, not just a relaxation.
                # Per-thread isolation here is enforced structurally by
                # threading.local storage: no thread ever executes SQL
                # against another thread's connection. The ONLY place a
                # connection is ever touched by a thread that didn't open
                # it is shutdown (close_all() / the leak-reclaim
                # finalizer), where the sole intent is to close() it, not
                # to run queries concurrently. With check_same_thread=True,
                # that legitimate cross-thread close() call raises
                # sqlite3.ProgrammingError, which close_all() previously
                # caught and logged as a harmless warning -- but the
                # connection was NOT actually closed, and by that point
                # close_all() had already detached its finalizer safety
                # net, so the OS-level file handle leaked with no
                # remaining path to close it deterministically. See
                # Database/ARCHITECTURE.md and close_all() below.
                check_same_thread=False,
                uri=self.config.uri_mode,
            )
            connection.row_factory = sqlite3.Row
            self._apply_pragmas(connection)
            self._local.connection = connection
            self._local.savepoint_stack = []
            ident = threading.get_ident()
            # Last-resort safety net: if this thread is garbage collected
            # (e.g. a pool worker exits) without ever calling disconnect(),
            # make sure the underlying OS-level connection still gets
            # closed rather than leaking until the process exits. Kept on
            # _local (and in the registry) so disconnect()/close_all() can
            # detach() it -- otherwise, once this thread object is later
            # collected, the finalizer would still fire and try to close a
            # connection that isn't safe to touch from whatever thread
            # happens to be running GC.
            finalizer = weakref.finalize(
                threading.current_thread(),
                self._reclaim_leaked_connection,
                connection,
                ident,
            )
            self._local.finalizer = finalizer
            with self._registry_lock:
                self._connections[ident] = connection
                self._finalizers[ident] = finalizer
            logger.debug(f"SQLiteDatabase connected at '{path_str}' (thread={ident})")
        except sqlite3.Error as exc:
            raise DatabaseError(
                f"Failed to connect to SQLite database at '{path_str}'",
                details={"error": str(exc)},
            ) from exc

    def _reclaim_leaked_connection(self, connection: sqlite3.Connection, ident: int) -> None:
        """Finalizer callback: close a connection whose owning thread is gone
        without ever calling :meth:`disconnect`.

        This is the last-resort safety net described in the class
        docstring -- it should rarely fire, since :meth:`disconnect` and
        :meth:`close_all` are both expected to close every connection
        deterministically during normal operation. When it does fire, it
        calls ``connection.close()`` directly and immediately. This is
        safe even though the finalizer runs on whatever thread happens to
        trigger garbage collection (essentially never the original,
        now-dead owning thread) because connections are opened with
        ``check_same_thread=False`` -- see :meth:`connect`.

        Explicit, immediate ``close()`` here is important, not cosmetic:
        this callback firing at all means bookkeeping already lost track
        of the connection, so from this point on nothing else will ever
        close it. Waiting instead for CPython's refcounting/GC to
        deallocate the ``sqlite3.Connection`` object would make the
        actual closing of the OS-level file handle depend on nothing
        else still referencing it (e.g. an exception traceback, a
        reference cycle needing a full GC pass) -- non-deterministic
        timing that is invisible on POSIX (which allows deleting/
        replacing files that still have open handles) but surfaces as a
        hard file-lock error on Windows, which does not.

        Never raises -- this runs during garbage collection/interpreter
        teardown, where exceptions are easy to lose and hard to act on.
        """
        with self._registry_lock:
            self._connections.pop(ident, None)
            self._finalizers.pop(ident, None)
        try:
            connection.close()
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.warning(f"Error closing leaked connection for thread {ident}: {exc}")
        logger.debug(f"Reclaimed and closed leaked connection for thread {ident}")

    def _apply_pragmas(self, connection: sqlite3.Connection) -> None:
        """Apply configured pragmas to a freshly-opened connection.

        Args:
            connection: The connection to configure.
        """
        cursor = connection.cursor()
        try:
            cursor.execute(f"PRAGMA journal_mode = {self.config.journal_mode}")
            cursor.execute(f"PRAGMA synchronous = {self.config.synchronous}")
            cursor.execute(f"PRAGMA foreign_keys = {'ON' if self.config.foreign_keys else 'OFF'}")
            for pragma_name, pragma_value in self.config.extra_pragmas.items():
                cursor.execute(f"PRAGMA {pragma_name} = {pragma_value}")
        finally:
            cursor.close()

    def disconnect(self) -> None:
        """Close the calling thread's connection, if any. Never raises."""
        connection = getattr(self._local, "connection", None)
        if connection is None:
            return
        ident = threading.get_ident()
        finalizer = getattr(self._local, "finalizer", None)
        if finalizer is not None:
            finalizer.detach()  # we're closing it properly ourselves now
        try:
            connection.close()
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.warning(f"Error while closing SQLite connection: {exc}")
        finally:
            self._local.connection = None
            self._local.savepoint_stack = []
            self._local.finalizer = None
            with self._registry_lock:
                self._connections.pop(ident, None)
                self._finalizers.pop(ident, None)
            logger.debug(f"SQLiteDatabase disconnected (thread={ident})")

    def close_all(self) -> None:
        """Close every connection this instance currently tracks, across
        all threads that have ever called :meth:`connect`.

        Intended for graceful application shutdown -- callable from any
        thread. Connections are opened with ``check_same_thread=False``
        (see :meth:`connect`) specifically so this cross-thread
        ``close()`` is a real, deterministic close and not merely a
        best-effort attempt -- it does not rely on garbage collection to
        actually release the OS-level file handle.

        Bookkeeping (the connection registry entry and its leak-detection
        finalizer) for a given connection is only dropped *after* that
        connection's ``close()`` call actually succeeds. If closing a
        connection unexpectedly fails, its finalizer is deliberately left
        attached, so the leak-detection safety net still applies to it --
        this method never leaves a connection with neither a confirmed
        close nor a finalizer able to catch it later.

        Does not clear other threads' thread-local bookkeeping beyond
        that; those threads will simply reconnect lazily the next time
        they call :meth:`connect` (or any method that connects
        implicitly).

        Never raises: failures closing individual connections are logged
        and skipped so one bad connection can't block shutdown of the
        rest.
        """
        with self._registry_lock:
            connections = list(self._connections.items())

        calling_ident = threading.get_ident()
        closed_count = 0
        for ident, connection in connections:
            try:
                connection.close()
            except sqlite3.Error as exc:  # noqa: BLE001
                logger.warning(
                    f"Error closing connection for thread {ident} during "
                    f"close_all(): {exc}. Leaving its leak-detection "
                    f"finalizer attached as a safety net."
                )
                continue  # bookkeeping intentionally left in place

            closed_count += 1
            with self._registry_lock:
                self._connections.pop(ident, None)
                finalizer = self._finalizers.pop(ident, None)
            if finalizer is not None:
                finalizer.detach()  # closed successfully -- safety net no longer needed

            if ident == calling_ident:
                # We're the thread that owns this one, and we just closed it
                # ourselves above (or tried to) -- clear our own thread-local
                # state too, so is_connected() / _ensure_connected() don't
                # keep pointing at a closed connection. Other threads' own
                # _local state is left alone; they'll notice on next use.
                self._local.connection = None
                self._local.savepoint_stack = []
                self._local.finalizer = None
        logger.debug(
            f"SQLiteDatabase.close_all() closed {closed_count}/{len(connections)} "
            f"tracked connection(s)"
        )

    def _ensure_connected(self) -> sqlite3.Connection:
        """Return the calling thread's connection, connecting lazily if needed."""
        if not self.is_connected:
            self.connect()
        return self._local.connection

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a ``sqlite3.Row`` into a plain ``dict``."""
        return dict(row)

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> QueryResult:
        """Execute a single SQL statement against the calling thread's connection.

        Args:
            sql: The SQL statement to execute.
            params: Optional positional parameters to bind.

        Returns:
            A normalized :class:`QueryResult`.

        Raises:
            DatabaseError: If the statement fails.
        """
        connection = self._ensure_connected()
        try:
            cursor = connection.cursor()
            cursor.execute(sql, params or [])
            rows: List[Dict[str, Any]] = (
                [self._row_to_dict(row) for row in cursor.fetchall()]
                if cursor.description is not None
                else []
            )
            result = QueryResult(rows=rows, rowcount=cursor.rowcount, lastrowid=cursor.lastrowid)
            cursor.close()
            return result
        except sqlite3.Error as exc:
            raise DatabaseError(f"SQLite execute failed: {sql}", details={"error": str(exc)}) from exc

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> QueryResult:
        """Execute the same statement against many parameter sets.

        Args:
            sql: The SQL statement to execute repeatedly.
            seq_of_params: A sequence of parameter sequences.

        Returns:
            A normalized :class:`QueryResult` with empty ``rows``.

        Raises:
            DatabaseError: If any execution fails.
        """
        connection = self._ensure_connected()
        try:
            cursor = connection.cursor()
            cursor.executemany(sql, seq_of_params)
            result = QueryResult(rows=[], rowcount=cursor.rowcount, lastrowid=cursor.lastrowid)
            cursor.close()
            return result
        except sqlite3.Error as exc:
            raise DatabaseError(f"SQLite executemany failed: {sql}", details={"error": str(exc)}) from exc

    def begin(self, *, exclusive: bool = False) -> None:
        """Start a transaction, or a nested savepoint if one is already active.

        See :meth:`Database.base_database.BaseDatabase.begin` for the
        full nesting contract. On SQLite specifically, ``exclusive=True``
        issues ``BEGIN EXCLUSIVE``, which takes an exclusive lock on the
        database file immediately (rather than waiting for the first
        write) -- this is what lets :class:`Database.migrations.MigrationRunner`
        serialize against another process running migrations against the
        same file at the same time.

        Raises:
            DatabaseError: If ``exclusive=True`` is passed while a
                transaction is already active on this connection, or if
                the underlying ``BEGIN``/``SAVEPOINT`` statement fails.
        """
        connection = self._ensure_connected()
        stack: List[str] = self._local.savepoint_stack
        try:
            if not stack:
                connection.execute("BEGIN EXCLUSIVE" if exclusive else "BEGIN")
                stack.append(_ROOT_TRANSACTION)
            else:
                if exclusive:
                    raise DatabaseError(
                        "exclusive=True is only valid for a new top-level "
                        "transaction, not a nested savepoint (a transaction "
                        "is already active on this connection)."
                    )
                savepoint_name = f"sp_{len(stack)}"
                connection.execute(f"SAVEPOINT {savepoint_name}")
                stack.append(savepoint_name)
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to begin transaction", details={"error": str(exc)}) from exc

    def commit(self) -> None:
        """Commit the innermost active transaction or savepoint.

        Raises:
            DatabaseError: If there is no active transaction, or the
                commit/release fails.
        """
        connection = self._ensure_connected()
        stack: List[str] = self._local.savepoint_stack
        if not stack:
            raise DatabaseError("No active transaction to commit")
        try:
            name = stack.pop()
            if name == _ROOT_TRANSACTION:
                connection.commit()
            else:
                connection.execute(f"RELEASE SAVEPOINT {name}")
        except sqlite3.Error as exc:
            raise DatabaseError("Failed to commit transaction", details={"error": str(exc)}) from exc

    def rollback(self) -> None:
        """Roll back the innermost active transaction or savepoint, if any.

        Tolerates being called with no active transaction (silently
        returns) so cleanup code can call it unconditionally. Never
        raises -- any failure is caught and logged.
        """
        connection = getattr(self._local, "connection", None)
        stack: Optional[List[str]] = getattr(self._local, "savepoint_stack", None)
        if connection is None or not stack:
            return
        try:
            name = stack.pop()
            if name == _ROOT_TRANSACTION:
                connection.rollback()
            else:
                connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
                connection.execute(f"RELEASE SAVEPOINT {name}")
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.warning(f"Error while rolling back transaction: {exc}")

    def health_check(self) -> bool:
        """Check reachability by running ``SELECT 1``.

        Never raises: any failure is caught, logged, and reported as
        ``False``.

        Returns:
            ``True`` if the check succeeded, ``False`` otherwise.
        """
        try:
            result = self.execute("SELECT 1")
            return len(result.rows) == 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"SQLiteDatabase health_check failed: {exc}")
            return False