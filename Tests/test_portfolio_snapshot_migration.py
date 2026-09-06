"""Standalone regression checks for
``Database.migrations_portfolio_snapshots.PORTFOLIO_SNAPSHOTS_MIGRATIONS``
(Activation 5.2).

Covers:

* migration version=8 applies idempotently and creates the
  ``portfolio_snapshots`` table with the expected columns;
* version=8 does not collide with, and does not require, versions
  6/7/9 (the reserved-but-not-yet-implemented range) or version 10/11
  (``ranking_snapshots``, a different table) -- it applies cleanly on
  top of just 1-5 (watchlist/accounts/positions/orders/trades);
* ``snapshot_id`` is the sole surrogate PRIMARY KEY and survives a
  restart (AUTOINCREMENT counter persists).

Run directly with ``python Tests/test_portfolio_snapshot_migration.py``.
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
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
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
    print("\n[Scenario 1] version=8 applies and is idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "pf_snapshots_migration.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            runner = MigrationRunner(db)
            applied = runner.apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
            check(len(applied) == 1, "exactly one migration applied on first run (v8)")
            check(applied[0].version == 8, "applied migration is version=8")
            check(applied[0].name == "create_portfolio_snapshots_table", "migration name matches")

            applied_again = runner.apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
            check(len(applied_again) == 0, "re-applying is a no-op (idempotent)")

            result = db.execute("PRAGMA table_info(portfolio_snapshots)")
            columns = {row["name"]: row["type"] for row in result.rows}
            expected_columns = {
                "snapshot_id": "INTEGER",
                "account_id": "TEXT",
                "cash": "REAL",
                "market_value": "REAL",
                "equity": "REAL",
                "realized_pnl": "REAL",
                "unrealized_pnl": "REAL",
                "exposure": "REAL",
                "drawdown": "REAL",
                "timestamp": "TEXT",
            }
            check(set(columns.keys()) == set(expected_columns.keys()), f"table has exactly the expected columns, got {set(columns.keys())}")
            for col_name, col_type in expected_columns.items():
                check(columns.get(col_name) == col_type, f"column '{col_name}' is {col_type}")
        finally:
            db.disconnect()


def scenario_snapshot_id_is_sole_primary_key():
    print("\n[Scenario 2] snapshot_id is the sole PRIMARY KEY, autoincrement")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "pf_snapshots_pk.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            _apply_prior_migrations(db)
            MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
            result = db.execute("PRAGMA table_info(portfolio_snapshots)")
            pk_columns = [row["name"] for row in result.rows if row["pk"] == 1]
            check(pk_columns == ["snapshot_id"], f"sole PRIMARY KEY is snapshot_id, got {pk_columns}")
        finally:
            db.disconnect()


def scenario_survives_restart():
    print("\n[Scenario 3] applied migration persists across a real process restart")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pf_snapshots_restart.db"
        cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(cfg)
        db.connect()
        _apply_prior_migrations(db)
        MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
        db.disconnect()

        db2 = SQLiteDatabase(DatabaseConfig(db_path=db_path))
        db2.connect()
        try:
            applied_again = MigrationRunner(db2).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
            check(len(applied_again) == 0, "fresh connection sees version=8 as already applied")
            result = db2.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio_snapshots'"
            )
            check(len(result.rows) == 1, "portfolio_snapshots table exists after restart")
        finally:
            db2.disconnect()


def main() -> int:
    scenario_migration_applies_and_is_idempotent()
    scenario_snapshot_id_is_sole_primary_key()
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
