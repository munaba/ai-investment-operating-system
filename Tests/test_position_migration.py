from __future__ import annotations

import sys

from Core.exceptions import DatabaseError
from Core.logger import get_logger
from Database.database_config import DatabaseConfig
from Database.migrations import MigrationRunner
from Database.migrations_positions import POSITIONS_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase

logger = get_logger(__name__)


def run_position_migrations() -> int:
    """Apply ``POSITIONS_MIGRATIONS`` to the production database.

    Manual, standalone operation (same scope decision as
    ``run_account_migrations.py``/``run_watchlist_migrations.py``):
    this function is never called by ``main.py``,
    ``Core.composition_root``, ``Core.startup_validation``, or any
    ``Repository.*`` module. An operator runs this file directly
    (``python run_position_migrations.py``) when the positions schema
    needs to be applied to a real database.

    Construction order (fixed, mirrors ``run_account_migrations.py``):
    ``DatabaseConfig.from_env()`` -> ``SQLiteDatabase(config)`` ->
    ``connect()`` -> ``MigrationRunner(database)`` ->
    ``apply(POSITIONS_MIGRATIONS)`` -> ``disconnect()`` (always, via
    ``try``/``finally``, even on failure).

    Idempotent: safe to run any number of times. Migrations already
    recorded in ``schema_migrations`` are skipped.

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migrations raised a ``DatabaseError`` -- the error
        is logged and printed to stderr, never re-raised.
    """
    database: SQLiteDatabase | None = None
    try:
        config = DatabaseConfig.from_env()
        database = SQLiteDatabase(config)
        database.connect()

        runner = MigrationRunner(database)
        applied = runner.apply(POSITIONS_MIGRATIONS)

        if applied:
            for record in applied:
                logger.info(f"Applied migration {record.version} '{record.name}'")
            print(f"Applied {len(applied)} migration(s).")
        else:
            print("No pending position migrations -- database already up to date.")

        return 0
    except DatabaseError as exc:
        logger.error(f"Position migration failed: {exc}")
        print(f"Position migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.disconnect()


def main() -> int:
    return run_position_migrations()


if __name__ == "__main__":
    sys.exit(main())