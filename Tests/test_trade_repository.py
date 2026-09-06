"""Standalone regression checks for
``Repository.persistence.trade_repository.TradeRepository``.

Covers Sprint 4 STEP 4 (Trade persistence):

* create/get_by_id/list_by_account/list_by_order/list_all happy
  paths;
* ``trade_id`` is repository-generated (autoincrement), never
  caller-supplied;
* this repository performs no fill/average/fee/tax/merge/portfolio
  computation -- ``create`` persists exactly the values the caller
  supplies;
* TradeRepository is append-only: no update/delete/replace/modify
  method exists at all.

Run directly with ``python Tests/test_trade_repository.py`` -- no
external test framework required, matching ``test_order_repository.py``.
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
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
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


def _build_repository(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "trades_repo.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
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
    return trade_repo, order_repo


def _seed_order(order_repo: OrderRepository, account_id: str = "paper-id", symbol: str = "BBCA") -> int:
    order = order_repo.create(
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


def scenario_create_and_get():
    print("\n[Scenario 1] create / get_by_id happy path")
    with tempfile.TemporaryDirectory() as tmp:
        trade_repo, order_repo = _build_repository(tmp)
        order_id = _seed_order(order_repo)

        trade = trade_repo.create(
            order_id=order_id,
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            fill_price=9500.0,
            fee=15000.0,
            tax=1425.0,
            executed_at="2026-08-01T09:00:00+00:00",
        )
        check(trade.trade_id is not None, "create() returns a trade_id (repository-generated)")
        check(trade.symbol == "BBCA", "create() returns trade with correct symbol")
        check(trade.fee == 15000.0, "create() stores caller-supplied fee as-is")
        check(trade.tax == 1425.0, "create() stores caller-supplied tax as-is")
        check(trade.executed_at == "2026-08-01T09:00:00+00:00", "create() stores caller-supplied executed_at as-is")

        fetched = trade_repo.get_by_id(trade.trade_id)
        check(fetched is not None, "get_by_id() finds the created trade")
        check(fetched.quantity == 100.0, "get_by_id() returns correct quantity")
        check(fetched.order_id == order_id, "get_by_id() returns correct order_id")

        missing = trade_repo.get_by_id(999999)
        check(missing is None, "get_by_id() returns None for missing trade")


def scenario_list_by_account_and_list_all():
    print("\n[Scenario 2] list_by_account() / list_all()")
    with tempfile.TemporaryDirectory() as tmp:
        trade_repo, order_repo = _build_repository(tmp)
        order_id_1 = _seed_order(order_repo, symbol="BBCA")
        order_id_2 = _seed_order(order_repo, symbol="TLKM")

        trade_repo.create(order_id_1, "paper-id", "BBCA", "BUY", 100.0, 9500.0, 15000.0, 1425.0, "2026-08-01T09:00:00+00:00")
        trade_repo.create(order_id_2, "paper-id", "TLKM", "SELL", 50.0, 3200.0, 8000.0, 480.0, "2026-08-01T09:05:00+00:00")

        by_account = trade_repo.list_by_account("paper-id")
        check(len(by_account) == 2, "list_by_account() returns all trades for the account")
        ids = [t.trade_id for t in by_account]
        check(ids == sorted(ids), "list_by_account() ordered by trade_id ascending")

        by_account_missing = trade_repo.list_by_account("does-not-exist")
        check(by_account_missing == [], "list_by_account() returns empty list for unknown account")

        all_trades = trade_repo.list_all()
        check(len(all_trades) == 2, "list_all() returns every trade")


def scenario_list_by_order_supports_partial_fills():
    print("\n[Scenario 3] list_by_order() returns multiple trades for one order (partial fills)")
    with tempfile.TemporaryDirectory() as tmp:
        trade_repo, order_repo = _build_repository(tmp)
        order_id = _seed_order(order_repo, symbol="BBCA")

        trade_repo.create(order_id, "paper-id", "BBCA", "BUY", 40.0, 9500.0, 6000.0, 570.0, "2026-08-01T09:00:00+00:00")
        trade_repo.create(order_id, "paper-id", "BBCA", "BUY", 60.0, 9510.0, 9000.0, 855.0, "2026-08-01T09:01:00+00:00")

        by_order = trade_repo.list_by_order(order_id)
        check(len(by_order) == 2, "list_by_order() returns both partial-fill trades for the order")
        ids = [t.trade_id for t in by_order]
        check(ids == sorted(ids), "list_by_order() ordered by trade_id ascending")
        check(sum(t.quantity for t in by_order) == 100.0, "sum of partial-fill quantities matches order quantity")

        by_order_missing = trade_repo.list_by_order(999999)
        check(by_order_missing == [], "list_by_order() returns empty list for unknown order")


def scenario_no_business_logic_or_mutation_methods_exist():
    print("\n[Scenario 4] TradeRepository is append-only: no update/delete/execute/business-logic methods")
    forbidden_names = (
        "update", "delete", "replace", "modify", "execute_trade",
        "validate", "fill", "buy", "sell", "merge", "calculate_pnl",
        "calculate", "average_price",
    )
    for name in forbidden_names:
        check(not hasattr(TradeRepository, name), f"TradeRepository has no '{name}' method")


def scenario_foreign_key_violations_raise_repository_error():
    print("\n[Scenario 5] invalid order_id/account_id raise RepositoryError (existing exception, no new class)")
    from Core.exceptions import RepositoryError  # noqa: E402

    with tempfile.TemporaryDirectory() as tmp:
        trade_repo, order_repo = _build_repository(tmp)
        order_id = _seed_order(order_repo)

        try:
            trade_repo.create(order_id, "does-not-exist", "BBCA", "BUY", 100.0, 9500.0, 15000.0, 1425.0, "2026-08-01T09:00:00+00:00")
            check(False, "create() with a non-existent account_id raises RepositoryError")
        except RepositoryError:
            check(True, "create() with a non-existent account_id raises RepositoryError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"create() with a non-existent account_id raised wrong exception type: {type(exc).__name__}")

        try:
            trade_repo.create(999999, "paper-id", "BBCA", "BUY", 100.0, 9500.0, 15000.0, 1425.0, "2026-08-01T09:00:00+00:00")
            check(False, "create() with a non-existent order_id raises RepositoryError")
        except RepositoryError:
            check(True, "create() with a non-existent order_id raises RepositoryError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"create() with a non-existent order_id raised wrong exception type: {type(exc).__name__}")


def main() -> int:
    scenario_create_and_get()
    scenario_list_by_account_and_list_all()
    scenario_list_by_order_supports_partial_fills()
    scenario_no_business_logic_or_mutation_methods_exist()
    scenario_foreign_key_violations_raise_repository_error()

    print("\n" + "=" * 60)
    print(f"TRADE REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())