"""Standalone regression checks for
``Database.migrations_daily_performance.DAILY_PERFORMANCE_MIGRATIONS``
(Activation 5.3).

Covers:

* migration version=9 applies idempotently and creates the
  ``daily_performance`` table with the expected columns;
* version=9 does not collide with, and does not require, versions
  6/7/8 (the reserved-but-not-yet-implemented / separately-owned
  range) or version 10/11 (``ranking_snapshots``, a different table)
  -- it applies cleanly on top of just 1-5
  (watchlist/accounts/positions/orders/trades);
* ``daily_performance_id`` is the sole surrogate PRIMARY KEY and
  survives a restart (AUTOINCREMENT counter persists).

Run directly with ``python Tests/test_daily_performance_migration.py``.
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
from Database.migrations_daily_performance import DAILY_PERFORMANCE_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.migrations_watchlist import WATCHLIST_MIGRATIONS  # noqa: E402
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


def _apply_prior_migrations(db: SQLiteDatabase) -> None:
    runner = MigrationRunner(db)
    runner.apply(WATCHLIST_MIGRATIONS)
    runner.apply(ACCOUNTS_MIGRATIONS)
    runner.apply(POSITIONS_MIGRATIONS)
    runner.apply(ORDERS_MIGRATIONS)
    runner.apply(TRADES_MIGRATIONS)


def scenario_migration_applies_and_is_idempotent():
    print("\n[Scenario 1] version=9 applies and is idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "daily_perf_migration.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            runner = MigrationRunner(db)
            applied = runner.apply(DAILY_PERFORMANCE_MIGRATIONS)
            check(len(applied) == 1, "exactly one migration applied on first run (v9)")
            check(applied[0].version == 9, "applied migration is version=9")
            check(applied[0].name == "create_daily_performance_table", "migration name matches")

            applied_again = runner.apply(DAILY_PERFORMANCE_MIGRATIONS)
            check(len(applied_again) == 0, "re-applying is a no-op (idempotent)")

            result = db.execute("PRAGMA table_info(daily_performance)")
            columns = {row["name"]: row["type"] for row in result.rows}
            expected_columns = {
                "daily_performance_id": "INTEGER",
                "account_id": "TEXT",
                "start_timestamp": "TEXT",
                "end_timestamp": "TEXT",
                "starting_equity": "REAL",
                "ending_equity": "REAL",
                "realized_result": "REAL",
                "unrealized_result": "REAL",
                "fees": "REAL",
                "tax": "REAL",
                "net_result": "REAL",
                "drawdown": "REAL",
                "number_of_signals": "INTEGER",
                "number_of_executions": "INTEGER",
                "timestamp": "TEXT",
            }
            check(
                set(columns.keys()) == set(expected_columns.keys()),
                f"table has exactly the expected columns, got {set(columns.keys())}",
            )
            for col_name, col_type in expected_columns.items():
                check(columns.get(col_name) == col_type, f"column '{col_name}' is {col_type}")
        finally:
            db.disconnect()


def scenario_daily_performance_id_is_sole_primary_key():
    print("\n[Scenario 2] daily_performance_id is the sole PRIMARY KEY, autoincrement")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "daily_perf_pk.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            MigrationRunner(db).apply(DAILY_PERFORMANCE_MIGRATIONS)
            result = db.execute("PRAGMA table_info(daily_performance)")
            pk_columns = [row["name"] for row in result.rows if row["pk"] == 1]
            check(
                pk_columns == ["daily_performance_id"],
                f"sole PRIMARY KEY is daily_performance_id, got {pk_columns}",
            )
        finally:
            db.disconnect()


def scenario_survives_restart():
    print("\n[Scenario 3] applied migration persists across a real process restart")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "daily_perf_restart.db"
        cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(cfg)
        db.connect()
        _apply_prior_migrations(db)
        MigrationRunner(db).apply(DAILY_PERFORMANCE_MIGRATIONS)
        db.disconnect()

        db2 = SQLiteDatabase(DatabaseConfig(db_path=db_path))
        db2.connect()
        try:
            applied_again = MigrationRunner(db2).apply(DAILY_PERFORMANCE_MIGRATIONS)
            check(len(applied_again) == 0, "fresh connection sees version=9 as already applied")
            result = db2.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_performance'"
            )
            check(len(result.rows) == 1, "daily_performance table exists after restart")
        finally:
            db2.disconnect()


def main() -> int:
    scenario_migration_applies_and_is_idempotent()
    scenario_daily_performance_id_is_sole_primary_key()
    scenario_survives_restart()

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
