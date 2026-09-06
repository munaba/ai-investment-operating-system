"""Standalone regression checks for
``Repository.persistence.daily_performance_repository.
DailyPerformanceRepository`` (Activation 5.3).

Covers:

* create() happy path returns a DailyPerformance with exact field
  values (not just a truthy/row-count check);
* daily_performance_id is repository-generated (autoincrement), never
  caller-supplied;
* starting_equity/ending_equity/number_of_signals default to None
  (NULL) when not supplied;
* list_by_account/list_all/get_latest_by_account/get_by_id;
* round-trip read after a real reconnect (restart persistence);
* DailyPerformanceRepository is append-only: no update/delete/
  replace/modify method exists at all.

Run directly with ``python Tests/test_daily_performance_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_daily_performance import DAILY_PERFORMANCE_MIGRATIONS  # noqa: E402
from Database.models import DailyPerformance  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.daily_performance_repository import DailyPerformanceRepository  # noqa: E402

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


def _build(tmp_dir: str, db_name: str = "daily_perf_repo.db"):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(DAILY_PERFORMANCE_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )
    return db, DailyPerformanceRepository(manager)


def scenario_create_returns_exact_values():
    print("\n[Scenario 1] create() happy path returns exact field values")
    with tempfile.TemporaryDirectory() as tmp:
        db, repo = _build(tmp)
        try:
            row = repo.create(
                account_id="paper-id",
                start_timestamp="2026-08-11T00:00:00+00:00",
                end_timestamp="2026-08-11T23:59:59+00:00",
                realized_result=150_000.0,
                unrealized_result=200_000.0,
                fees=5_000.0,
                tax=2_500.0,
                net_result=342_500.0,
                drawdown=0.05,
                number_of_executions=4,
                timestamp="2026-08-11T23:59:59+00:00",
                starting_equity=100_000_000.0,
                ending_equity=100_342_500.0,
                number_of_signals=None,
            )
            check(isinstance(row, DailyPerformance), "create() returns a DailyPerformance instance")
            check(row.daily_performance_id is not None, "created row has a repository-assigned daily_performance_id")
            check(row.account_id == "paper-id", "account_id persisted exactly as supplied")
            check(row.start_timestamp == "2026-08-11T00:00:00+00:00", "start_timestamp persisted exactly as supplied")
            check(row.end_timestamp == "2026-08-11T23:59:59+00:00", "end_timestamp persisted exactly as supplied")
            check(row.starting_equity == 100_000_000.0, "starting_equity persisted exactly as supplied")
            check(row.ending_equity == 100_342_500.0, "ending_equity persisted exactly as supplied")
            check(row.realized_result == 150_000.0, "realized_result persisted exactly as supplied")
            check(row.unrealized_result == 200_000.0, "unrealized_result persisted exactly as supplied")
            check(row.fees == 5_000.0, "fees persisted exactly as supplied")
            check(row.tax == 2_500.0, "tax persisted exactly as supplied")
            check(row.net_result == 342_500.0, "net_result persisted exactly as supplied")
            check(row.drawdown == 0.05, "drawdown persisted exactly as supplied")
            check(row.number_of_executions == 4, "number_of_executions persisted exactly as supplied")
            check(row.timestamp == "2026-08-11T23:59:59+00:00", "timestamp persisted exactly as supplied")
            check(row.number_of_signals is None, "number_of_signals persisted as None (GAP, not fabricated)")
        finally:
            db.disconnect()


def scenario_daily_performance_id_is_repository_generated():
    print("\n[Scenario 2] daily_performance_id is autoincrement, never caller-supplied")
    with tempfile.TemporaryDirectory() as tmp:
        db, repo = _build(tmp)
        try:
            r1 = repo.create(
                account_id="paper-id", start_timestamp="2026-08-11T00:00:00+00:00",
                end_timestamp="2026-08-11T23:59:59+00:00", realized_result=0.0,
                unrealized_result=0.0, fees=0.0, tax=0.0, net_result=0.0, drawdown=0.0,
                number_of_executions=0, timestamp="2026-08-11T23:59:59+00:00",
            )
            r2 = repo.create(
                account_id="paper-id", start_timestamp="2026-08-12T00:00:00+00:00",
                end_timestamp="2026-08-12T23:59:59+00:00", realized_result=0.0,
                unrealized_result=0.0, fees=0.0, tax=0.0, net_result=0.0, drawdown=0.0,
                number_of_executions=0, timestamp="2026-08-12T23:59:59+00:00",
            )
            check(r2.daily_performance_id == r1.daily_performance_id + 1, "second create() gets the next autoincrement id")
        finally:
            db.disconnect()


def scenario_nullable_fields_default_to_none():
    print("\n[Scenario 3] starting_equity/ending_equity/number_of_signals default to None")
    with tempfile.TemporaryDirectory() as tmp:
        db, repo = _build(tmp)
        try:
            row = repo.create(
                account_id="paper-id", start_timestamp="2026-08-11T00:00:00+00:00",
                end_timestamp="2026-08-11T23:59:59+00:00", realized_result=0.0,
                unrealized_result=0.0, fees=0.0, tax=0.0, net_result=0.0, drawdown=0.0,
                number_of_executions=0, timestamp="2026-08-11T23:59:59+00:00",
            )
            check(row.starting_equity is None, "starting_equity defaults to None when not supplied")
            check(row.ending_equity is None, "ending_equity defaults to None when not supplied")
            check(row.number_of_signals is None, "number_of_signals defaults to None when not supplied")

            fetched = repo.get_by_id(row.daily_performance_id)
            check(fetched.starting_equity is None, "starting_equity round-trips as None (NULL) from the database")
            check(fetched.ending_equity is None, "ending_equity round-trips as None (NULL) from the database")
            check(fetched.number_of_signals is None, "number_of_signals round-trips as None (NULL) from the database")
        finally:
            db.disconnect()


def scenario_list_and_get_methods():
    print("\n[Scenario 4] list_by_account / list_all / get_latest_by_account / get_by_id")
    with tempfile.TemporaryDirectory() as tmp:
        db, repo = _build(tmp)
        try:
            for i in range(3):
                repo.create(
                    account_id="paper-id",
                    start_timestamp=f"2026-08-1{i}T00:00:00+00:00",
                    end_timestamp=f"2026-08-1{i}T23:59:59+00:00",
                    realized_result=float(i), unrealized_result=0.0, fees=0.0, tax=0.0,
                    net_result=float(i), drawdown=0.0, number_of_executions=i,
                    timestamp=f"2026-08-1{i}T23:59:59+00:00",
                )
            by_account = repo.list_by_account("paper-id")
            check(len(by_account) == 3, "list_by_account returns all 3 rows for the account")
            check(
                [r.net_result for r in by_account] == [0.0, 1.0, 2.0],
                "list_by_account is ordered by daily_performance_id ascending",
            )

            all_rows = repo.list_all()
            check(len(all_rows) == 3, "list_all returns all rows")

            latest = repo.get_latest_by_account("paper-id")
            check(latest is not None and latest.net_result == 2.0, "get_latest_by_account returns the most recent row")

            fetched = repo.get_by_id(by_account[0].daily_performance_id)
            check(fetched is not None and fetched.net_result == 0.0, "get_by_id returns the correct row")

            none_for_other_account = repo.list_by_account("nonexistent")
            check(none_for_other_account == [], "list_by_account returns empty list for unknown account")

            none_for_missing_id = repo.get_by_id(999999)
            check(none_for_missing_id is None, "get_by_id returns None for a missing daily_performance_id")
        finally:
            db.disconnect()


def scenario_round_trip_after_restart():
    print("\n[Scenario 5] round-trip read survives a real reconnect (restart persistence)")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "daily_perf_restart.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
        MigrationRunner(db).apply(DAILY_PERFORMANCE_MIGRATIONS)
        manager = DatabaseManager(db, cfg)
        AccountRepository(manager).create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id",
            cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
        )
        repo = DailyPerformanceRepository(manager)
        created = repo.create(
            account_id="paper-id",
            start_timestamp="2026-08-11T00:00:00+00:00",
            end_timestamp="2026-08-11T23:59:59+00:00",
            realized_result=10.0, unrealized_result=5.0, fees=1.0, tax=0.5,
            net_result=13.5, drawdown=0.2, number_of_executions=7,
            timestamp="2026-08-11T23:59:59+00:00",
            starting_equity=100.0, ending_equity=113.5, number_of_signals=None,
        )
        db.disconnect()

        db2 = SQLiteDatabase(DatabaseConfig(db_path=cfg.db_path))
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg)
            repo2 = DailyPerformanceRepository(manager2)
            reread = repo2.get_by_id(created.daily_performance_id)
            check(reread is not None, "row readable from a brand-new process/connection")
            check(reread.start_timestamp == "2026-08-11T00:00:00+00:00", "start_timestamp survives restart")
            check(reread.end_timestamp == "2026-08-11T23:59:59+00:00", "end_timestamp survives restart")
            check(reread.starting_equity == 100.0, "starting_equity survives restart")
            check(reread.ending_equity == 113.5, "ending_equity survives restart")
            check(reread.realized_result == 10.0, "realized_result survives restart")
            check(reread.unrealized_result == 5.0, "unrealized_result survives restart")
            check(reread.fees == 1.0, "fees survives restart")
            check(reread.tax == 0.5, "tax survives restart")
            check(reread.net_result == 13.5, "net_result survives restart")
            check(reread.drawdown == 0.2, "drawdown survives restart")
            check(reread.number_of_executions == 7, "number_of_executions survives restart")
            check(reread.number_of_signals is None, "number_of_signals survives restart as None")
            check(reread.timestamp == "2026-08-11T23:59:59+00:00", "timestamp survives restart")
        finally:
            db2.disconnect()


def scenario_append_only_no_mutation_methods():
    print("\n[Scenario 6] DailyPerformanceRepository is append-only")
    forbidden = ("update", "delete", "replace", "modify", "remove")
    for name in forbidden:
        check(not hasattr(DailyPerformanceRepository, name), f"DailyPerformanceRepository has no '{name}' method")


def main() -> int:
    scenario_create_returns_exact_values()
    scenario_daily_performance_id_is_repository_generated()
    scenario_nullable_fields_default_to_none()
    scenario_list_and_get_methods()
    scenario_round_trip_after_restart()
    scenario_append_only_no_mutation_methods()

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
