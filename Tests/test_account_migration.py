"""Standalone regression checks for ``Database.migrations_accounts.ACCOUNTS_MIGRATIONS``.

Covers Sprint 3 STEP 3 (Accounts):

* migration ``version=2`` applies idempotently and creates the
  ``accounts`` table with the expected columns/types;
* the ``mode`` and ``asset_class`` SQL ``CHECK`` constraints (generated
  from ``Database.account_constants``) reject out-of-domain values.

Run directly with ``python Tests/test_account_migration.py`` -- no
external test framework required, matching
``test_database_layer_smoke.py`` and ``test_news_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Database.database_config import DatabaseConfig  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def scenario_migration_applies_and_is_idempotent():
    print("\n[Scenario 1] version=2 applies and is idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "accounts_migration.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            runner = MigrationRunner(db)
            applied = runner.apply(ACCOUNTS_MIGRATIONS)
            check(len(applied) == 1, "exactly one migration applied on first run")
            check(applied[0].version == 2, "applied migration is version=2")
            check(applied[0].name == "create_accounts_table", "applied migration name matches")

            applied_again = runner.apply(ACCOUNTS_MIGRATIONS)
            check(applied_again == [], "second apply() is a no-op (idempotent)")

            versions = runner.applied_versions()
            check(2 in versions, "version 2 recorded in schema_migrations")
        finally:
            db.disconnect()


def scenario_table_shape():
    print("\n[Scenario 2] accounts table has expected columns")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "accounts_shape.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
            result = db.execute("PRAGMA table_info(accounts)")
            columns = {row["name"]: row["type"] for row in result.rows}
            expected = {
                "account_id": "TEXT",
                "account_name": "TEXT",
                "mode": "TEXT",
                "currency": "TEXT",
                "asset_class": "TEXT",
                "cash": "REAL",
                "equity": "REAL",
                "buying_power": "REAL",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            }
            for col_name, col_type in expected.items():
                check(col_name in columns, f"column '{col_name}' exists")
                check(columns.get(col_name) == col_type, f"column '{col_name}' is {col_type}")

            pk_columns = [row["name"] for row in db.execute("PRAGMA table_info(accounts)").rows if row["pk"] == 1]
            check(pk_columns == ["account_id"], "account_id is the sole PRIMARY KEY (TEXT, not autoincrement int)")
        finally:
            db.disconnect()


def scenario_mode_check_constraint():
    print("\n[Scenario 3] CHECK constraint rejects invalid mode")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "accounts_mode_check.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
            now = "2026-08-01T00:00:00+00:00"
            try:
                db.execute(
                    """
                    INSERT INTO accounts
                        (account_id, account_name, mode, currency, asset_class,
                         cash, equity, buying_power, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("bad-mode", "Bad Mode Account", "simulation", "USD", "crypto", 0, 0, 0, now, now),
                )
                check(False, "invalid mode 'simulation' rejected by CHECK constraint")
            except Exception:
                check(True, "invalid mode 'simulation' rejected by CHECK constraint")

            for valid_mode in ("paper", "live"):
                db.execute(
                    """
                    INSERT INTO accounts
                        (account_id, account_name, mode, currency, asset_class,
                         cash, equity, buying_power, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"ok-{valid_mode}", f"OK {valid_mode}", valid_mode, "USD", "crypto", 0, 0, 0, now, now),
                )
            check(True, "every value in ACCOUNT_MODES is accepted by CHECK constraint")
        finally:
            db.disconnect()


def scenario_asset_class_check_constraint():
    print("\n[Scenario 4] CHECK constraint rejects invalid asset_class")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "accounts_asset_class_check.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
            now = "2026-08-01T00:00:00+00:00"
            try:
                db.execute(
                    """
                    INSERT INTO accounts
                        (account_id, account_name, mode, currency, asset_class,
                         cash, equity, buying_power, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("bad-asset", "Bad Asset Account", "paper", "USD", "commodities", 0, 0, 0, now, now),
                )
                check(False, "invalid asset_class 'commodities' rejected by CHECK constraint")
            except Exception:
                check(True, "invalid asset_class 'commodities' rejected by CHECK constraint")

            for valid_asset_class in ("stock_id", "stock_us", "crypto", "forex"):
                db.execute(
                    """
                    INSERT INTO accounts
                        (account_id, account_name, mode, currency, asset_class,
                         cash, equity, buying_power, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"ok-{valid_asset_class}", f"OK {valid_asset_class}", "paper", "USD",
                     valid_asset_class, 0, 0, 0, now, now),
                )
            check(True, "every value in ACCOUNT_ASSET_CLASSES is accepted by CHECK constraint")
        finally:
            db.disconnect()


def main() -> int:
    scenario_migration_applies_and_is_idempotent()
    scenario_table_shape()
    scenario_mode_check_constraint()
    scenario_asset_class_check_constraint()

    print("\n" + "=" * 60)
    print(f"ACCOUNT MIGRATION TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
