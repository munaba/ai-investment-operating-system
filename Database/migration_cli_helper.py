"""Shared implementation behind every standalone ``run_<domain>_migrations.py``
script (Activation 1.3).

Before Activation 1.3, each of the six ``run_*_migrations.py`` scripts
at the repository root duplicated the identical construction sequence
inline: ``DatabaseConfig.from_env()`` -> ``SQLiteDatabase(config)`` ->
``connect()`` -> ``MigrationRunner(database)`` -> ``apply(...)`` ->
``disconnect()`` (always, via ``try``/``finally``). That duplication
was pure boilerplate, not competing migration *logic* -- every script
already delegated the actual ordering/application/rollback work to the
single canonical ``Database.migrations.MigrationRunner``. Activation
1.3 unifies the boilerplate here so it is written once; the six
scripts become thin compatibility wrappers with byte-identical
external behavior (same construction order, same messages, same
return-code contract) to what they had before.

These scripts are kept, not removed or deprecated (Activation 1.3
Section 14 decision): they remain useful for an operator who wants to
apply a single domain's migration in isolation, independent of
``python main.py init`` applying every domain at once.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from Core.exceptions import DatabaseError
from Core.logger import get_logger
from .database_config import DatabaseConfig
from .migrations import Migration, MigrationRunner
from .sqlite_database import SQLiteDatabase

logger = get_logger(__name__)


def apply_domain_migrations(migrations: Sequence[Migration], label: str) -> int:
    """Apply ``migrations`` to the production database and report the result.

    Args:
        migrations: The domain's migration tuple (e.g.
            ``WATCHLIST_MIGRATIONS``), applied via ``MigrationRunner``
            unchanged.
        label: Lowercase singular domain word used in messages, e.g.
            ``"watchlist"``, ``"account"``, ``"position"``, ``"order"``,
            ``"trade"``, ``"snapshot"`` -- matches the wording each
            standalone script used before Activation 1.3.

    Returns:
        ``0`` on success (including "nothing pending"). ``1`` if
        applying the migrations raised a ``DatabaseError`` -- the error
        is logged and printed to stderr, never re-raised.
    """
    database: Optional[SQLiteDatabase] = None
    try:
        config = DatabaseConfig.from_env()
        database = SQLiteDatabase(config)
        database.connect()

        runner = MigrationRunner(database)
        applied = runner.apply(list(migrations))

        if applied:
            for record in applied:
                logger.info(f"Applied migration {record.version} '{record.name}'")
            print(f"Applied {len(applied)} migration(s).")
        else:
            print(f"No pending {label} migrations -- database already up to date.")

        return 0
    except DatabaseError as exc:
        logger.error(f"{label.capitalize()} migration failed: {exc}")
        print(f"{label.capitalize()} migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if database is not None:
            database.disconnect()
