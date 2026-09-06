from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Sequence

from Core.logger import get_logger
from .base_database import BaseDatabase
from .models import MigrationRecord
from .schema import BOOTSTRAP_STATEMENTS

logger = get_logger(__name__)


@dataclass
class Migration:
    """A single, isolated unit of schema evolution.

    Attributes:
        version: Sequential version number. Must be unique and
            monotonically increasing across all migrations ever applied.
        name: Short human-readable description (e.g.
            ``"create_watchlist_table"``).
        up_statements: SQL statements to run, in order, to apply this
            migration. Each should be idempotent-friendly
            (``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``)
            wherever practical.
    """

    version: int
    name: str
    up_statements: List[str] = field(default_factory=list)


class MigrationRunner:
    """Applies pending :class:`Migration` objects to a database, in
    order, tracking which versions have already run via the
    ``schema_migrations`` table (see :mod:`Database.schema`).

    Isolated from :mod:`Database.schema`: ``schema.py`` holds the
    bootstrap DDL for the tracking table itself; this class holds the
    logic that decides which migrations still need to run and applies
    them.
    """

    def __init__(self, database: BaseDatabase) -> None:
        """Initialize with the database to migrate.

        Args:
            database: The database to apply migrations against. Does not
                need to be connected yet -- backends connect lazily on
                first use.
        """
        self._database = database

    def ensure_bootstrap_schema(self) -> None:
        """Create the ``schema_migrations`` bookkeeping table if absent.

        Safe to call on every startup: every statement is
        ``CREATE TABLE IF NOT EXISTS``.

        Raises:
            DatabaseError: If a bootstrap statement fails.
        """
        for statement in BOOTSTRAP_STATEMENTS:
            self._database.execute(statement)

    def applied_versions(self) -> List[int]:
        """Return the version numbers already recorded as applied.

        Returns:
            A list of applied migration version numbers, in no
            particular order.

        Raises:
            DatabaseError: If the query fails.
        """
        result = self._database.execute("SELECT version FROM schema_migrations")
        return [int(row["version"]) for row in result.rows]

    def _pending(self, migrations: Sequence[Migration]) -> List[Migration]:
        """Return ``migrations`` not yet recorded in ``schema_migrations``,
        sorted by version."""
        already_applied = set(self.applied_versions())
        return sorted(
            (m for m in migrations if m.version not in already_applied),
            key=lambda m: m.version,
        )

    def apply(self, migrations: Sequence[Migration]) -> List[MigrationRecord]:
        """Apply every migration in ``migrations`` that has not run yet.

        Ensures the bootstrap schema exists first, then acquires an
        exclusive lock (see ``exclusive=True`` on
        :meth:`Database.base_database.BaseDatabase.begin`) before doing
        anything else. That lock serializes this call against *any other*
        migration run against the same database -- including one started
        by a different process at nearly the same time -- which is what
        makes this safe to call from multiple worker processes at startup
        without a separate coordination mechanism.

        Because the lock can only be acquired once, and the pending-list
        is (re-)computed only after acquiring it, a second caller that
        was blocked waiting for the lock will see whatever the first
        caller already applied and correctly skip those migrations,
        instead of re-running them.

        Each individual migration still runs in its own nested savepoint,
        so a failing migration's own partial statements are rolled back
        immediately and reported clearly. However, the entire batch
        (every migration applied during this one ``apply()`` call) is
        atomic: if any migration in the batch fails, every migration
        applied earlier *in this same call* is also rolled back, and the
        exclusive lock is released without anything having been persisted.
        This is a deliberate behavior change from leaving earlier
        migrations in the batch committed independently -- see
        ``Database/ARCHITECTURE.md`` for the rationale (a batch that can
        be left half-applied is exactly the kind of state the locking
        requirement was meant to prevent).

        Args:
            migrations: Candidate migrations, in any order. Only those
                whose ``version`` is not already recorded in
                ``schema_migrations`` are applied.

        Returns:
            The :class:`MigrationRecord` for each migration newly
            applied, in the order they were applied. Empty if there was
            nothing pending.

        Raises:
            DatabaseError: If any migration's statements fail. The whole
                batch (including any migrations already applied earlier
                in this call) is rolled back before the exception
                propagates.
        """
        self.ensure_bootstrap_schema()

        # Cheap check before paying for the exclusive lock: if nothing
        # looks pending, don't bother acquiring it at all.
        if not self._pending(migrations):
            return []

        applied_records: List[MigrationRecord] = []
        self._database.begin(exclusive=True)
        try:
            # Re-check now that we hold the exclusive lock: another
            # process/thread may have applied some or all of these
            # migrations while we were waiting for it.
            pending = self._pending(migrations)
            for migration in pending:
                applied_at = datetime.now(timezone.utc).isoformat()
                self._database.begin()  # nested -> SAVEPOINT
                try:
                    for statement in migration.up_statements:
                        self._database.execute(statement)
                    self._database.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                        (migration.version, migration.name, applied_at),
                    )
                    self._database.commit()  # RELEASE SAVEPOINT
                except Exception:
                    self._database.rollback()  # ROLLBACK TO SAVEPOINT
                    raise

                record = MigrationRecord(version=migration.version, name=migration.name, applied_at=applied_at)
                applied_records.append(record)
                logger.debug(f"Applied migration {migration.version} '{migration.name}'")

            self._database.commit()  # commits the exclusive outer transaction
        except Exception:
            self._database.rollback()  # rolls back the whole batch
            raise

        return applied_records