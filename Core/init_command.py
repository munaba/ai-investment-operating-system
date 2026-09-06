from __future__ import annotations

"""Activation 1.3 -- ``python main.py init``.

The single official entry point for preparing the AIOS database on a
new environment, or one whose migrations are not yet complete.

Reuses, rather than reimplements, everything that already existed:

  * ``Database.database_config.DatabaseConfig.from_env()`` -- the same
    database path/pragma source ``doctor`` and every standalone
    ``run_*_migrations.py`` script already use. ``init`` never opens a
    second database path.
  * ``Database.sqlite_database.SQLiteDatabase`` -- its ``connect()``
    already creates the parent directory and the database file on
    first open (see its own docstring); ``init`` does not duplicate
    that logic.
  * ``Database.migrations.MigrationRunner`` -- the existing canonical
    migration abstraction (bootstrap schema, pending-detection,
    exclusive-lock + nested-savepoint transaction handling, batch
    rollback on failure). ``init`` does not re-implement any of this;
    it only orchestrates *calling* it and formatting the result.
  * ``Database.migration_registry.all_migrations()`` -- the canonical,
    version-ordered migration plan, shared with ``Core.doctor`` (see
    Activation 1.3 audit notes in that module).

Scope boundary through Activation 1.3: this module created the
database, the migration bookkeeping table, and ran schema migrations
only -- no paper account, no default currency/watchlist entry, no
other application bootstrap data, and no requirement on any
LLM/data-provider/Telegram credential or connectivity (see
``main.py``'s dispatch comment for why ``init`` must be reachable
before ``validate_runtime_environment()``).

Activation 1.4 extends this, *after* migrations succeed, with the
minimum application bootstrap from ``Core.bootstrap.run_bootstrap``:
a default paper account, a watchlist readability check, and a safe
``.env.example`` template. This still requires no provider credential
or network connectivity -- ``Core.bootstrap`` touches only the local
database and local filesystem. Migration and bootstrap remain
separate transactions/phases (Section 11): a migration failure never
reaches the bootstrap phase, and the two are reported as distinct
``Migration:``/``Bootstrap:``/``Overall:`` lines whenever bootstrap is
attempted, so a fresh reader can never mistake "schema is current" for
"application is fully initialized" (Section 12).
"""

import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from Core.bootstrap import run_bootstrap
from Core.exceptions import BootstrapError, DatabaseError
from Core.logger import get_logger
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migration_registry import all_migrations as _canonical_migrations
from Database.migrations import Migration, MigrationRunner
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.watchlist_repository import WatchlistRepository

logger = get_logger(__name__)

MigrationEntry = Tuple[Migration, str]

#: Default location for the safe config template this module ensures
#: exists -- the project root (two levels up from this file:
#: Core/init_command.py -> Core/ -> project root), not the process's
#: current working directory, so behavior does not depend on where
#: ``python main.py init`` happens to be invoked from.
_DEFAULT_CONFIG_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / ".env.example"


def run_init(
    db_config: Optional[DatabaseConfig] = None,
    migrations: Optional[Sequence[MigrationEntry]] = None,
    print_fn: Callable[[str], None] = print,
    config_template_path: Optional[Path] = None,
) -> int:
    """Create/open the database, apply every pending migration, then run
    the Activation 1.4 application bootstrap.

    Args:
        db_config: Database configuration to use. Defaults to
            ``DatabaseConfig.from_env()`` -- the same source ``doctor``
            and every standalone migration runner already use.
        migrations: ``(Migration, domain)`` pairs to apply, in the
            order they should be attempted. Defaults to
            ``Database.migration_registry.all_migrations()`` (the
            canonical, version-ordered plan). Overridable so tests can
            inject a forced-failure migration without touching real
            production schema/domain migrations.
        print_fn: Injection point for tests to capture output instead
            of writing to real stdout. Defaults to the builtin
            ``print``, mirroring ``Core.doctor.run_doctor_command``.
        config_template_path: Where ``Core.bootstrap.ensure_config_template``
            should create ``.env.example`` if absent. Defaults to the
            project root, independent of current working directory.
            Overridable so tests can point at a temporary directory
            instead of the real project root.

    Returns:
        ``0`` on success (including "nothing pending" for migrations
        and "already bootstrapped" for application data). Non-zero if
        the database could not be opened, the migration schema could
        not be created, a migration failed, or a bootstrap step failed.
    """
    config = db_config or DatabaseConfig.from_env()
    migration_entries: List[MigrationEntry] = list(migrations) if migrations is not None else _canonical_migrations()
    domain_by_version = {migration.version: domain for migration, domain in migration_entries}

    db_path = Path(config.db_path)
    # Snapshot existence *before* connecting -- SQLiteDatabase.connect()
    # creates the file (and parent directory) as a side effect of
    # opening it, so this is the only correct point to observe whether
    # this run is the one that created it.
    file_existed_before = db_path.is_file()

    lines: List[str] = ["AIOS INIT", "=" * len("AIOS INIT")]

    database = SQLiteDatabase(config)
    try:
        database.connect()
    except DatabaseError as exc:
        logger.error(f"init: failed to open database at '{db_path}': {exc}")
        lines += [
            "",
            "Database",
            f"  Path: {db_path}",
            f"  Error: {exc}",
            "",
            "Result",
            "  INIT FAILED",
        ]
        print_fn("\n".join(lines))
        return 1

    try:
        runner = MigrationRunner(database)

        try:
            runner.ensure_bootstrap_schema()
        except DatabaseError as exc:
            logger.error(f"init: failed to create schema_migrations bookkeeping table: {exc}")
            lines += [
                "",
                "Database",
                f"  Path: {db_path}",
                f"  Created: {'YES' if not file_existed_before else 'NO'}",
                "",
                "Bootstrap Failed",
                f"  Reason: {exc}",
                "",
                "Result",
                "  INIT FAILED",
            ]
            print_fn("\n".join(lines))
            return 1

        applied_before = set(runner.applied_versions())
        pending_this_run = [m for m, _domain in migration_entries if m.version not in applied_before]

        lines += [
            "",
            "Database",
            f"  Path: {db_path}",
            f"  Created: {'YES' if not file_existed_before else 'NO'}",
        ]

        try:
            newly_applied = runner.apply([m for m, _domain in migration_entries])
        except DatabaseError as exc:
            # MigrationRunner.apply() treats one apply() call as fully
            # atomic (see its own docstring): every migration it
            # considered "pending" for this call -- regardless of the
            # order we passed them in, since it internally sorts by
            # version -- is rolled back together if any one of them
            # fails. That means, on failure, "applied_after" is
            # guaranteed equal to "applied_before" *by construction*;
            # it cannot be used to work out *which* pending migration
            # was the one that actually failed (all of them look
            # equally "not applied" afterward). Identify the culprit
            # instead by matching the raised SQLiteDatabase error text
            # (which embeds the exact failing SQL statement, see
            # Database.sqlite_database.SQLiteDatabase.execute) against
            # each pending migration's own up_statements -- proof from
            # the actual error, not a guess from list position.
            applied_after = set(runner.applied_versions())
            rollback_success = applied_after == applied_before

            exc_text = str(exc)
            failed_migration = next(
                (m for m in pending_this_run if any(stmt in exc_text for stmt in m.up_statements)),
                None,
            )
            failed_domain = (
                domain_by_version.get(failed_migration.version, "unknown")
                if failed_migration is not None
                else None
            )

            logger.error(
                "init: migration failed "
                f"({failed_domain + ':v' + str(failed_migration.version) if failed_migration else 'unidentified'}): {exc}"
            )

            lines.append("")
            lines.append("Migration Failed")
            if failed_migration is not None:
                lines.append(f"  Migration: {failed_domain}:v{failed_migration.version}")
                lines.append(f"  Name: {failed_migration.name}")
            else:
                lines.append("  Migration: could not be identified from the error text below")
            lines.append(f"  Reason: {exc}")
            lines.append(f"  Rollback: {'SUCCESS' if rollback_success else 'BLOCKED'}")
            if not rollback_success:
                lines.append(
                    "  NOTE: database state could not be proven to match its "
                    "pre-init state -- do not treat this database as safe to "
                    "use until manually inspected."
                )
            lines.append("")
            lines.append("Result")
            lines.append("  INIT FAILED")
            print_fn("\n".join(lines))
            return 1

        if newly_applied:
            lines.append("")
            lines.append("Migration Plan")
            newly_applied_versions = {m.version for m in newly_applied}
            for index, (migration, domain) in enumerate(migration_entries, start=1):
                status = "APPLIED" if migration.version in newly_applied_versions else "already applied"
                label = f"{domain}:v{migration.version}"
                lines.append(f"  {index}. {label:<24} {status}")

        current_versions = set(runner.applied_versions())
        current_version = max(current_versions) if current_versions else None
        still_pending = [
            (migration, domain) for migration, domain in migration_entries if migration.version not in current_versions
        ]

        lines.append("")
        lines.append("Migration Status")
        lines.append(
            f"  Current version: v{current_version}" if current_version is not None else "  Current version: none"
        )
        if still_pending:
            lines.append("  Pending:")
            for migration, domain in still_pending:
                lines.append(f"    {domain}:v{migration.version}")
        else:
            lines.append("  Pending: 0")
            if not newly_applied:
                lines.append("  Nothing to apply")

        # Activation 1.4: migrations succeeded -- run application
        # bootstrap as a separate phase (Section 11: migration and
        # bootstrap are distinct transactions/phases, never claimed as
        # one atomic step). A bootstrap failure must never be reported
        # as "INIT SUCCESS" (Section 12), even though migrations
        # themselves are fully applied and current.
        database_manager = DatabaseManager(database, config)
        account_repository = AccountRepository(database_manager)
        watchlist_repository = WatchlistRepository(database_manager)
        resolved_config_template_path = config_template_path or _DEFAULT_CONFIG_TEMPLATE_PATH

        try:
            bootstrap_results = run_bootstrap(
                account_repository, watchlist_repository, resolved_config_template_path
            )
        except BootstrapError as exc:
            logger.error(f"init: bootstrap step '{exc.step}' failed: {exc.original}")
            lines.append("")
            lines.append("Bootstrap Failed")
            lines.append(f"  Step: {exc.step}")
            lines.append(f"  Reason: {exc.original}")
            lines.append("")
            lines.append("Migration: SUCCESS")
            lines.append("Bootstrap: FAILED")
            lines.append("Overall: FAILED")
            lines.append("")
            lines.append("Result")
            lines.append("  INIT FAILED")
            print_fn("\n".join(lines))
            return 1

        lines.append("")
        lines.append("Bootstrap")
        for step_result in bootstrap_results:
            lines.append(f"  {step_result.step:<22} {step_result.status:<14} {step_result.detail}")

        lines.append("")
        lines.append("Migration: SUCCESS")
        lines.append("Bootstrap: SUCCESS")
        lines.append("Overall: SUCCESS")
        lines.append("")
        lines.append("Result")
        lines.append("  INIT SUCCESS")
        print_fn("\n".join(lines))
        return 0
    finally:
        database.disconnect()


def main() -> int:
    return run_init()


if __name__ == "__main__":
    sys.exit(main())