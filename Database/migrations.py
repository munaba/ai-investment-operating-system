from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from Core.exceptions import DatabaseError
from Core.logger import get_logger
from Database.database import DatabaseManager, database_manager

logger = get_logger(__name__)


@dataclass(frozen=True)
class Migration:
    """A single versioned schema change.

    Attributes:
        version: Monotonically increasing migration version number.
        description: Short human-readable description of the migration.
        up: SQL statements that apply this migration.
        down: SQL statements that revert this migration.
    """

    version: int
    description: str
    up: List[str]
    down: List[str]

MIGRATIONS: List[Migration] = [
    Migration(
        version=1,
        description="Create core tables: chat_history, memory_records, tool_executions, audit_logs",
        up=[
            """
            CREATE TABLE IF NOT EXISTS chat_history (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS memory_records (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                collection TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding_id TEXT,
                metadata TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tool_executions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                input_data TEXT,
                output_data TEXT,
                status TEXT NOT NULL,
                error_message TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                details TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_chat_history_session_id ON chat_history (session_id)",
            "CREATE INDEX IF NOT EXISTS idx_memory_records_collection ON memory_records (collection)",
            "CREATE INDEX IF NOT EXISTS idx_tool_executions_tool_name ON tool_executions (tool_name)",
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs (resource)",
        ],
        down=[
            "DROP TABLE IF EXISTS chat_history",
            "DROP TABLE IF EXISTS memory_records",
            "DROP TABLE IF EXISTS tool_executions",
            "DROP TABLE IF EXISTS audit_logs",
        ],
    ),
]

_MANAGED_TABLES: List[str] = ["chat_history", "memory_records", "tool_executions", "audit_logs"]


class MigrationManager:
    """Applies and reverts versioned schema migrations for a SQLite database.

    Every migration step runs inside a single database transaction, so a
    failure partway through a migration leaves the schema unchanged rather
    than half-applied.

    Attributes:
        db: The :class:`DatabaseManager` used to run migration statements.
    """

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        """Initialize the migration manager.

        Args:
            db: The database manager to operate on. Defaults to the shared
                :data:`Database.database.database_manager` singleton.
        """
        self.db: DatabaseManager = db if db is not None else database_manager

    def database_version(self) -> int:
        """Get the current schema version of the database.

        Returns:
            The current schema version (``0`` if no migrations applied yet).

        Raises:
            DatabaseError: If the version could not be read.
        """
        row = self.db.fetchone("PRAGMA user_version")
        if row is None:
            return 0
        return int(row[0])

    def _set_database_version(self, version: int) -> None:
        """Set the schema version stored in the database.

        Args:
            version: The new schema version number.
        """
        
        self.db.execute(f"PRAGMA user_version = {int(version)}")

    def create_tables(self) -> None:
        """Create all managed tables by applying every migration from scratch.

        Equivalent to calling :meth:`upgrade` with no target (i.e. upgrade
        to the latest available version).

        Raises:
            DatabaseError: If table creation fails.
        """
        self.upgrade()

    def drop_tables(self) -> None:
        """Drop all managed tables and reset the schema version to 0.

        Raises:
            DatabaseError: If dropping tables fails.
        """
        try:
            with self.db.transaction() as conn:
                for table_name in _MANAGED_TABLES:
                    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            self._set_database_version(0)
            logger.info("All managed tables dropped; schema version reset to 0")
        except DatabaseError:
            raise
        except Exception as exc: 
            raise DatabaseError("Failed to drop tables", details={"error": str(exc)}) from exc

    def upgrade(self, target_version: Optional[int] = None) -> None:
        """Apply pending migrations up to ``target_version`` (or the latest).

        Args:
            target_version: Version to upgrade to. Defaults to the highest
                version defined in :data:`MIGRATIONS`.

        Raises:
            DatabaseError: If ``target_version`` is invalid, or a migration
                fails (in which case that migration step is rolled back).
        """
        current_version = self.database_version()
        latest_version = max((m.version for m in MIGRATIONS), default=0)
        target = target_version if target_version is not None else latest_version

        if target > latest_version:
            raise DatabaseError(f"Unknown target migration version: {target}")

        pending = sorted(
            (m for m in MIGRATIONS if current_version < m.version <= target),
            key=lambda m: m.version,
        )

        for migration in pending:
            try:
                with self.db.transaction() as conn:
                    for statement in migration.up:
                        conn.execute(statement)
                self._set_database_version(migration.version)
                logger.info(f"Applied migration v{migration.version}: {migration.description}")
            except DatabaseError:
                raise
            except Exception as exc:  
                raise DatabaseError(
                    f"Migration v{migration.version} failed", details={"error": str(exc)}
                ) from exc

    def downgrade(self, target_version: int) -> None:
        """Revert migrations down to (and excluding) ``target_version``.

        Args:
            target_version: Version to downgrade to. Must be less than the
                current database version and non-negative.

        Raises:
            DatabaseError: If ``target_version`` is invalid, or reverting a
                migration fails (in which case that step is rolled back).
        """
        if target_version < 0:
            raise DatabaseError(f"Invalid target migration version: {target_version}")

        current_version = self.database_version()
        if target_version >= current_version:
            logger.debug("downgrade() called with target >= current version; nothing to do")
            return

        to_revert = sorted(
            (m for m in MIGRATIONS if target_version < m.version <= current_version),
            key=lambda m: m.version,
            reverse=True,
        )

        for migration in to_revert:
            try:
                with self.db.transaction() as conn:
                    for statement in migration.down:
                        conn.execute(statement)
                self._set_database_version(migration.version - 1)
                logger.info(f"Reverted migration v{migration.version}: {migration.description}")
            except DatabaseError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise DatabaseError(
                    f"Reverting migration v{migration.version} failed", details={"error": str(exc)}
                ) from exc

migration_manager: MigrationManager = MigrationManager()