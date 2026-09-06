from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

from .base_database import BaseDatabase, QueryResult


class Session:
    """Thin handle to an in-progress transaction on a :class:`BaseDatabase`.

    Exists so code inside a ``with`` block has something natural to hold
    onto (``session.execute(...)``) instead of reaching back into a bare
    :class:`BaseDatabase` reference. Carries no state of its own beyond
    the wrapped database -- all the real work is still done by the
    database backend.
    """

    def __init__(self, database: BaseDatabase) -> None:
        """Wrap a database that already has an active transaction.

        Args:
            database: The database instance this session runs against.
        """
        self._database = database

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> QueryResult:
        """Execute a statement within this session's transaction.

        See :meth:`Database.base_database.BaseDatabase.execute`.
        """
        return self._database.execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> QueryResult:
        """Execute a statement many times within this session's transaction.

        See :meth:`Database.base_database.BaseDatabase.executemany`.
        """
        return self._database.executemany(sql, seq_of_params)


@contextmanager
def transaction(database: BaseDatabase, *, exclusive: bool = False) -> Iterator[Session]:
    """Run a block of statements as a single transaction.

    Begins a transaction on ``database``, yields a :class:`Session` bound
    to it, then commits on clean exit or rolls back if the block raises.
    If a transaction is already active on ``database`` (e.g. this call is
    nested inside a caller's own ``transaction(...)``/``session()``
    block), this opens a nested savepoint instead -- see
    :meth:`Database.base_database.BaseDatabase.begin`.

    Args:
        database: The database to run the transaction against.
        exclusive: Passed through to ``database.begin(exclusive=...)``.
            Only meaningful when this is not nested inside another active
            transaction -- see ``begin()`` for details.

    Yields:
        A :class:`Session` for issuing statements within the transaction.

    Raises:
        DatabaseError: If beginning, committing, or rolling back fails.
        Exception: Whatever the wrapped block raises, re-raised after the
            transaction has been rolled back.

    Example:
        >>> with transaction(database) as session:
        ...     session.execute("INSERT INTO watchlist (...) VALUES (...)")
    """
    database.begin(exclusive=exclusive)
    session = Session(database)
    try:
        yield session
    except Exception:
        database.rollback()
        raise
    else:
        database.commit()