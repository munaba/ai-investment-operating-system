from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class QueryResult:
    """Normalized outcome of a single :meth:`BaseDatabase.execute` call.

    Every concrete backend returns this same shape, mirroring the
    normalization pattern already used by ``Services.ServiceResult`` and
    ``Providers.ProviderResponse`` elsewhere in this framework -- callers
    never need to know which backend (SQLite today, PostgreSQL/
    TimescaleDB/Cloud SQL/DuckDB tomorrow) produced a result.

    Attributes:
        rows: Result rows as plain dicts (column name -> value), for
            ``SELECT``-style statements. Empty for statements that don't
            return rows.
        rowcount: Number of rows affected/returned, when the backend can
            report it (``-1`` when unknown, matching Python DB-API's
            ``cursor.rowcount`` convention).
        lastrowid: The row id of the last inserted row, if applicable and
            supported by the backend.
    """

    rows: List[Dict[str, Any]] = field(default_factory=list)
    rowcount: int = -1
    lastrowid: Optional[int] = None


class BaseDatabase(ABC):
    """Abstract interface every concrete database backend must implement.

    Mirrors the shape of ``Providers.BaseProvider`` and
    ``Services.BaseService`` in this framework: callers (principally the
    future Repository layer, via
    :class:`Database.database_manager.DatabaseManager`) depend only on
    this interface, never on a concrete backend, so SQLite can be
    replaced by PostgreSQL, TimescaleDB, Cloud SQL, or DuckDB without
    touching Repositories, Services, Orchestration, or Agents.

    What this interface abstracts (safe to rely on regardless of backend):
        * Connecting/disconnecting and reporting connection state.
        * Executing statements and getting back a normalized
          :class:`QueryResult` (rows as plain dicts, rowcount, lastrowid).
        * Transactions with arbitrary nesting: the *first* ``begin()`` on
          a connection starts a real transaction; any ``begin()`` called
          while one is already active opens a nested savepoint instead of
          raising. This makes Repository methods composable -- one
          Repository method can call another that also opens its own
          transaction, and only the outermost ``commit()``/``rollback()``
          actually commits/rolls back to the database.
        * A best-effort ``exclusive`` transaction mode for use cases (like
          schema migrations) that need to serialize against every other
          writer, including other OS processes talking to the same
          backend.
        * ``health_check()`` never raising.

    What this interface deliberately does NOT abstract (see
    ``Database/ARCHITECTURE.md`` for the full writeup):
        * SQL dialect/syntax. Callers write raw SQL; that SQL is NOT
          guaranteed to be portable across backends. There is no query
          builder here and none is planned at this stage.
        * Backend-specific tuning (SQLite pragmas, Postgres connection
          pool settings, etc.) -- ``DatabaseConfig.extra_pragmas`` is an
          escape hatch, not a portable abstraction.
        * Exact concurrency/locking semantics. "Exclusive transaction"
          means "serialize against other writers" on every backend, but
          *how* that's achieved (file locks for SQLite, advisory locks or
          ``SELECT ... FOR UPDATE`` for Postgres) is backend-specific and
          may have different blocking/timeout behavior.
        * Whether the backend is process-local (SQLite file) or networked
          (Postgres/Cloud SQL) -- this affects the ``:memory:`` caveat
          below and matters when reasoning about multi-process safety.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish the underlying connection.

        Implementations should be idempotent: calling ``connect()`` on an
        already-connected database should be a no-op.

        Raises:
            DatabaseError: If the connection could not be established.
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Release the underlying connection.

        Raises:
            DatabaseError: If disconnecting fails unexpectedly.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether this database currently holds a live connection."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> QueryResult:
        """Execute a single SQL statement.

        Args:
            sql: The SQL statement to execute.
            params: Optional positional parameters to bind.

        Returns:
            A normalized :class:`QueryResult`.

        Raises:
            DatabaseError: If the statement fails.
        """
        raise NotImplementedError

    @abstractmethod
    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> QueryResult:
        """Execute the same SQL statement against many parameter sets.

        Args:
            sql: The SQL statement to execute repeatedly.
            seq_of_params: A sequence of parameter sequences, one per
                execution.

        Returns:
            A normalized :class:`QueryResult` (``rows`` is always empty;
            ``rowcount`` reflects the total affected rows when the
            backend can report it).

        Raises:
            DatabaseError: If any execution fails.
        """
        raise NotImplementedError

    @abstractmethod
    def begin(self, *, exclusive: bool = False) -> None:
        """Start a transaction, nesting via a savepoint if one is already active.

        Repositories must be composable: calling ``begin()`` while a
        transaction is already active on this connection does NOT raise.
        Instead it opens a nested savepoint, so a Repository method that
        calls another Repository method (each wrapping its own logic in
        ``begin()``/``commit()``) works correctly whether it's the
        outermost call or nested inside a caller's own transaction. Only
        the outermost ``commit()``/``rollback()`` actually commits or
        rolls back against the database; nested calls release/roll back
        to their savepoint only.

        Args:
            exclusive: Only meaningful for the outermost ``begin()`` on a
                connection (i.e. when no transaction is currently active).
                When ``True``, requests the strongest available isolation
                for this backend -- enough to serialize against every
                other writer, including ones in other OS processes. Used
                by :class:`Database.migrations.MigrationRunner` so
                concurrent migration runs (e.g. from two processes
                started at the same time) can't race. Passing
                ``exclusive=True`` while a transaction is already active
                (i.e. this would be a nested savepoint, not a new
                top-level transaction) is a usage error.

        Raises:
            DatabaseError: If starting the transaction/savepoint fails,
                or if ``exclusive=True`` is passed for a nested call.
        """
        raise NotImplementedError

    @abstractmethod
    def commit(self) -> None:
        """Commit the innermost active transaction or savepoint.

        If this connection has nested transactions open (see ``begin()``),
        this releases only the innermost savepoint; the outer transaction
        remains open until its own ``commit()`` is called. If this is the
        outermost transaction, it is actually committed to the database.

        Raises:
            DatabaseError: If there is no active transaction, or the
                commit fails.
        """
        raise NotImplementedError

    @abstractmethod
    def rollback(self) -> None:
        """Roll back the innermost active transaction or savepoint, if any.

        Mirrors ``commit()``'s nesting behavior: rolling back a nested
        call undoes only that savepoint's work and leaves the outer
        transaction active (and still eligible to commit or roll back
        independently). Rolling back the outermost transaction rolls back
        everything since the matching ``begin()``.

        Implementations should tolerate being called with no active
        transaction (no-op) so cleanup/exception-handling code can call
        it unconditionally.
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        """Check whether this database is currently reachable and functional.

        Implementations should never raise -- any failure should be
        caught internally and reflected as a ``False`` return value,
        mirroring ``BaseProvider.health_check()`` and
        ``BaseService.health_check()``.

        Returns:
            ``True`` if the database is healthy, ``False`` otherwise.
        """
        raise NotImplementedError