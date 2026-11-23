"""The canonical migration registry must cover every migrations module.

Regression: Database/migration_registry.py listed only 10 of the 20
``Database/migrations_*.py`` domains, so ``python main.py init`` created
an incomplete schema (no scheduler, risk ledger, decision brief ... tables)
and ``python main.py doctor`` reported READY without checking them.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from Database.migration_registry import MIGRATION_MODULES, all_migrations
from Database.migrations import Migration

_DATABASE_DIR = Path(__file__).resolve().parent.parent / "Database"


def _module_paths_on_disk() -> set[str]:
    return {f"Database.{p.stem}" for p in _DATABASE_DIR.glob("migrations_*.py")}


def test_every_migrations_module_is_registered() -> None:
    registered = {module_path for _domain, module_path, _attr in MIGRATION_MODULES}
    assert _module_paths_on_disk() - registered == set()


def test_registered_tuples_hold_every_migration_in_their_module() -> None:
    for _domain, module_path, attr in MIGRATION_MODULES:
        module = importlib.import_module(module_path)
        declared = {
            m.version
            for name, value in vars(module).items()
            if name.endswith("_MIGRATIONS") and isinstance(value, (tuple, list))
            for m in value
            if isinstance(m, Migration)
        }
        assert {m.version for m in getattr(module, attr)} == declared, module_path


def test_all_migrations_versions_are_unique_and_sorted() -> None:
    versions = [m.version for m, _domain in all_migrations()]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))


def test_init_applies_every_registered_migration(tmp_path) -> None:
    from Database.database_config import DatabaseConfig
    from Database.migrations import MigrationRunner
    from Database.sqlite_database import SQLiteDatabase

    config = DatabaseConfig.from_env()
    config.db_path = tmp_path / "fresh.db"
    db = SQLiteDatabase(config)
    db.connect()
    try:
        runner = MigrationRunner(db)
        runner.apply([m for m, _domain in all_migrations()])
        applied = {row["version"] for row in db.execute("SELECT version FROM schema_migrations").rows}
    finally:
        db.disconnect()
    assert applied == {m.version for m, _domain in all_migrations()}
