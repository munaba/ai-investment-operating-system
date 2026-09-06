"""Standalone regression checks for
``Repository.persistence.performance_repository.PerformanceRepository``.

Covers Sprint 6 STEP 1 (performance query layer):

* constructor -- same shape as every other persistence repository
  (only takes ``database_manager``);
* ``get_all_trades``/``get_all_positions``/``get_all_accounts``/
  ``get_all_snapshots`` happy paths;
* ``get_all_trades`` orders by ``executed_at`` ascending (not
  ``trade_id``, unlike ``TradeRepository.list_all``);
* every method returns an empty list, not an error, against an empty
  database;
* return types are the existing Sprint 4 / Sprint 5 STEP 3 models
  (``Trade``/``Position``/``Account``/``RankingSnapshot``) -- no new
  model is introduced;
* this repository exposes no create/insert/update/delete method of
  any kind (read-only).

Run directly with ``python Tests/test_performance_repository.py`` --
no external test framework required, matching
``test_snapshot_repository.py``/``test_trade_repository.py``.
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
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import Account, Position, RankingSnapshot, Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.performance_repository import PerformanceRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

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


def _build_manager(tmp_dir: str) -> DatabaseManager:
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "performance_repo.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    return DatabaseManager(db, cfg)


def _seed_account(manager: DatabaseManager, account_id: str = "paper-id") -> None:
    AccountRepository(manager).create(
        account_id=account_id,
        account_name=f"Account {account_id}",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )


def _seed_order(manager: DatabaseManager, account_id: str = "paper-id", symbol: str = "BBCA") -> int:
    order = OrderRepository(manager).create(
        account_id=account_id,
        symbol=symbol,
        action="BUY",
        quantity=100.0,
        requested_price=9500.0,
        filled_price=9500.0,
        status="FILLED",
        reason="test order",
        filled_quantity=100.0,
    )
    return order.order_id


def scenario_constructor():
    print("\n[Scenario 1] constructor -- only takes database_manager")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_manager(tmp)
        repo = PerformanceRepository(manager)
        check(isinstance(repo, PerformanceRepository), "constructs a PerformanceRepository instance")
        check(repo._database_manager is manager, "stores the exact database_manager instance supplied")


def scenario_get_all_trades_ordered_by_executed_at():
    print("\n[Scenario 2] get_all_trades() returns every trade, ordered by executed_at ascending")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_manager(tmp)
        _seed_account(manager)
        order_id = _seed_order(manager)
        trade_repo = TradeRepository(manager)
        # Insert out of executed_at order to prove sort is by executed_at,
        # not by insertion/trade_id order.
        later = trade_repo.create(
            order_id=order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=50.0, fill_price=9500.0, fee=0.0, tax=0.0,
            executed_at="2026-08-01T10:00:00+00:00",
        )
        earlier = trade_repo.create(
            order_id=order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=50.0, fill_price=9500.0, fee=0.0, tax=0.0,
            executed_at="2026-08-01T09:00:00+00:00",
        )

        repo = PerformanceRepository(manager)
        results = repo.get_all_trades()
        check(len(results) == 2, "get_all_trades returns every persisted trade")
        check(all(isinstance(t, Trade) for t in results), "every returned item is a Trade instance")
        check(
            [t.trade_id for t in results] == [earlier.trade_id, later.trade_id],
            "results are ordered by executed_at ascending (not trade_id/insertion order)",
        )


def scenario_get_all_positions():
    print("\n[Scenario 3] get_all_positions() returns every position")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_manager(tmp)
        _seed_account(manager)
        position_repo = PositionRepository(manager)
        first = position_repo.create(
            account_id="paper-id", symbol="BBCA", quantity=100.0,
            average_price=9500.0, realized_pnl=0.0, status="open",
        )
        second = position_repo.create(
            account_id="paper-id", symbol="TLKM", quantity=200.0,
            average_price=3000.0, realized_pnl=0.0, status="open",
        )

        repo = PerformanceRepository(manager)
        results = repo.get_all_positions()
        check(len(results) == 2, "get_all_positions returns every persisted position")
        check(all(isinstance(p, Position) for p in results), "every returned item is a Position instance")
        check(
            [p.position_id for p in results] == [first.position_id, second.position_id],
            "results are ordered by position_id ascending",
        )


def scenario_get_all_accounts():
    print("\n[Scenario 4] get_all_accounts() returns every account")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_manager(tmp)
        _seed_account(manager, account_id="paper-id")
        _seed_account(manager, account_id="crypto-main")

        repo = PerformanceRepository(manager)
        results = repo.get_all_accounts()
        check(len(results) == 2, "get_all_accounts returns every persisted account")
        check(all(isinstance(a, Account) for a in results), "every returned item is an Account instance")
        check(
            [a.account_id for a in results] == ["crypto-main", "paper-id"],
            "results are ordered by account_id ascending",
        )


def scenario_get_all_snapshots():
    print("\n[Scenario 5] get_all_snapshots() returns every RankingSnapshot")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_manager(tmp)
        snapshot_repo = SnapshotRepository(manager)
        first = snapshot_repo.create(
            scan_time="2026-08-01T09:00:00+00:00", symbol="BBCA",
            recommendation="SELL", confidence="LOW", priority=1, rank=1,
        )
        second = snapshot_repo.create(
            scan_time="2026-08-01T10:00:00+00:00", symbol="ASII",
            recommendation="BUY", confidence="HIGH", priority=1, rank=1,
        )

        repo = PerformanceRepository(manager)
        results = repo.get_all_snapshots()
        check(len(results) == 2, "get_all_snapshots returns every persisted snapshot")
        check(
            all(isinstance(s, RankingSnapshot) for s in results),
            "every returned item is a RankingSnapshot instance",
        )
        check(
            [s.snapshot_id for s in results] == [first.snapshot_id, second.snapshot_id],
            "results are ordered by snapshot_id ascending",
        )


def scenario_empty_database_returns_empty_lists():
    print("\n[Scenario 6] against an empty database, every method returns an empty list")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_manager(tmp)
        repo = PerformanceRepository(manager)
        check(repo.get_all_trades() == [], "get_all_trades() on empty database returns []")
        check(repo.get_all_positions() == [], "get_all_positions() on empty database returns []")
        check(repo.get_all_accounts() == [], "get_all_accounts() on empty database returns []")
        check(repo.get_all_snapshots() == [], "get_all_snapshots() on empty database returns []")


def scenario_read_only_no_mutation_methods_exist():
    print("\n[Scenario 7] PerformanceRepository is read-only -- no create/insert/update/delete method")
    repo_methods = {name for name in dir(PerformanceRepository) if not name.startswith("_")}
    check("create" not in repo_methods, "PerformanceRepository has no create() method")
    check("insert" not in repo_methods, "PerformanceRepository has no insert() method")
    check("update" not in repo_methods, "PerformanceRepository has no update() method")
    check("delete" not in repo_methods, "PerformanceRepository has no delete() method")
    expected_public_methods = {
        "get_all_trades", "get_all_positions", "get_all_accounts",
        "get_all_snapshots", "health_check",
    }
    check(
        repo_methods == expected_public_methods,
        f"PerformanceRepository's public API is exactly {sorted(expected_public_methods)}",
    )


def main() -> int:
    scenario_constructor()
    scenario_get_all_trades_ordered_by_executed_at()
    scenario_get_all_positions()
    scenario_get_all_accounts()
    scenario_get_all_snapshots()
    scenario_empty_database_returns_empty_lists()
    scenario_read_only_no_mutation_methods_exist()

    print("\n" + "=" * 60)
    print(f"PERFORMANCE REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())