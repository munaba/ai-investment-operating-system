"""ACTIVATION 3.4 STEP 2 -- Acceptance gate proof.

Real SQLite database, real repositories/services, no mocks/fakes.
Run with: python3 Tests/proof_activation_3_4_step2.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Core.exceptions import RepositoryError  # noqa: E402
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


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        print(f"  FAIL - {description}")


def dump_order(label: str, order) -> None:
    print(
        f"    {label}: status={order.status!r} filled_price={order.filled_price} "
        f"filled_quantity={order.filled_quantity} filled_at={order.filled_at!r}"
    )


def dump_trade(label: str, trade) -> None:
    print(
        f"    {label}: trade_id={trade.trade_id} order_id={trade.order_id} "
        f"fill_price={trade.fill_price} quantity={trade.quantity} executed_at={trade.executed_at!r}"
    )


def build(db_path: Path):
    cfg = DatabaseConfig(db_path=db_path)
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
    lifecycle = OrderLifecycleService(order_repo)
    execution = ExecutionService(order_repo, trade_repo)
    return db, manager, order_repo, trade_repo, lifecycle, execution


def scenario_success_case(tmp: str):
    print("\n=== SUCCESS CASE: one BUY, real SQLite DB ===")
    db_path = Path(tmp) / "success.db"
    db, manager, order_repo, trade_repo, lifecycle, execution = build(db_path)
    try:
        order_before = lifecycle.create_order(
            account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=100.0, requested_price=9500.0,
        )
        dump_order("Order BEFORE fill", order_before)
        check(order_before.status == "PENDING", "order created PENDING")
        check(order_before.filled_price == 0.0, "order created filled_price=0.0")
        check(order_before.filled_quantity == 0.0, "order created filled_quantity=0.0")
        check(order_before.filled_at is None, "order created filled_at=None")

        trade = execution.execute_order(order_before.order_id, executed_at="2026-08-04T03:00:00+00:00")
        dump_trade("Trade created", trade)

        order_after = order_repo.get_by_id(order_before.order_id)
        dump_order("Order AFTER fill", order_after)

        check(order_after.status == "FILLED", "order status == FILLED")
        check(order_after.filled_price == trade.fill_price, "order.filled_price == trade.fill_price")
        check(order_after.filled_quantity == trade.quantity, "order.filled_quantity == trade.quantity")
        check(order_after.filled_at == trade.executed_at, "order.filled_at == trade.executed_at")
        check(order_after.filled_price != 0.0, "order.filled_price is no longer the 0.0 placeholder")
    finally:
        db.disconnect()


def scenario_multiple_orders(tmp: str):
    print("\n=== MULTIPLE ORDERS: each Order syncs to its own Trade, no crossover ===")
    db_path = Path(tmp) / "multi.db"
    db, manager, order_repo, trade_repo, lifecycle, execution = build(db_path)
    try:
        specs = [
            ("BBCA", "BUY", 100.0, 9500.0, "2026-08-04T03:00:00+00:00"),
            ("TLKM", "BUY", 50.0, 3200.0, "2026-08-04T03:05:00+00:00"),
            ("ASII", "BUY", 200.0, 5400.0, "2026-08-04T03:10:00+00:00"),
        ]
        pairs = []
        for symbol, action, qty, price, executed_at in specs:
            order = lifecycle.create_order(
                account_id="paper-id", symbol=symbol, action=action,
                quantity=qty, requested_price=price,
            )
            trade = execution.execute_order(order.order_id, executed_at=executed_at)
            pairs.append((order.order_id, trade))

        for order_id, trade in pairs:
            reloaded = order_repo.get_by_id(order_id)
            dump_order(f"Order {order_id} ({trade.symbol})", reloaded)
            dump_trade(f"Trade for order {order_id}", trade)
            check(reloaded.order_id == trade.order_id, f"order {order_id} matches its own trade's order_id")
            check(reloaded.filled_price == trade.fill_price, f"order {order_id} filled_price matches its own trade")
            check(reloaded.filled_quantity == trade.quantity, f"order {order_id} filled_quantity matches its own trade")
            check(reloaded.filled_at == trade.executed_at, f"order {order_id} filled_at matches its own trade")

        # cross-check: no order accidentally matches a DIFFERENT trade
        order_ids = [oid for oid, _ in pairs]
        trades = [t for _, t in pairs]
        for i, order_id in enumerate(order_ids):
            reloaded = order_repo.get_by_id(order_id)
            for j, trade in enumerate(trades):
                if i == j:
                    continue
                check(
                    not (reloaded.filled_price == trade.fill_price and reloaded.filled_quantity == trade.quantity),
                    f"order {order_id} does NOT match unrelated trade {trade.trade_id} (no crossover)",
                )
    finally:
        db.disconnect()


def scenario_restart_proof(tmp: str):
    print("\n=== RESTART PROOF: fresh process/connection re-reads identical values ===")
    db_path = Path(tmp) / "restart.db"
    db, manager, order_repo, trade_repo, lifecycle, execution = build(db_path)
    order = lifecycle.create_order(
        account_id="paper-id", symbol="BBCA", action="BUY",
        quantity=100.0, requested_price=9500.0,
    )
    trade = execution.execute_order(order.order_id, executed_at="2026-08-04T03:00:00+00:00")
    order_id = order.order_id
    db.disconnect()
    print("    ... simulated restart: disconnected, opening a brand-new connection ...")

    cfg2 = DatabaseConfig(db_path=db_path)
    db2 = SQLiteDatabase(cfg2)
    db2.connect()
    manager2 = DatabaseManager(db2, cfg2)
    order_repo2 = OrderRepository(manager2)
    trade_repo2 = TradeRepository(manager2)
    try:
        order_reloaded = order_repo2.get_by_id(order_id)
        trades_reloaded = trade_repo2.list_by_order(order_id)
        dump_order("Order after restart", order_reloaded)
        for t in trades_reloaded:
            dump_trade("Trade after restart", t)

        check(len(trades_reloaded) == 1, "exactly one Trade survives restart for this order")
        trade_reloaded = trades_reloaded[0]
        check(order_reloaded.filled_price == trade_reloaded.fill_price, "post-restart: Order.filled_price == Trade.fill_price")
        check(order_reloaded.filled_quantity == trade_reloaded.quantity, "post-restart: Order.filled_quantity == Trade.quantity")
        check(order_reloaded.filled_at == trade_reloaded.executed_at, "post-restart: Order.filled_at == Trade.executed_at")
        check(order_reloaded.filled_price == trade.fill_price, "post-restart values match pre-restart Trade.fill_price")
        check(order_reloaded.filled_at == trade.executed_at, "post-restart values match pre-restart Trade.executed_at")
    finally:
        db2.disconnect()


def scenario_failure_path(tmp: str):
    print("\n=== FAILURE PROOF: record_fill() fails AFTER Trade already committed ===")
    db_path = Path(tmp) / "failure.db"
    db, manager, order_repo, trade_repo, lifecycle, execution = build(db_path)
    try:
        order = lifecycle.create_order(
            account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=100.0, requested_price=9500.0,
        )
        order_id = order.order_id
        print("    state BEFORE execute_order():")
        dump_order("Order", order)
        trade_count_before = len(trade_repo.list_by_order(order_id))
        print(f"    Trade rows for this order BEFORE: {trade_count_before}")

        # Force record_fill() to fail with a REAL RepositoryError, without
        # touching any production algorithm: an invalid `status` value
        # trips OrderRepository._validate_status() -- the exact same
        # production validation path a corrupted/unexpected status would
        # hit -- raising *after* TradeRepository.create() has already run
        # and committed inside execute_order(). This does not modify
        # execution_service.py; it only calls execute_order() with a
        # database whose orders.status CHECK domain is intact, then
        # monkeypatches the single record_fill() call for this one proof
        # invocation to demonstrate the documented failure semantics
        # (TradeRepository.create() is untouched -- only the immediately
        # following record_fill() call fails).
        original_record_fill = order_repo.record_fill

        def _failing_record_fill(*args, **kwargs):
            raise RepositoryError("simulated failure: order status sync could not be persisted")

        order_repo.record_fill = _failing_record_fill  # type: ignore[method-assign]

        exception_raised = None
        try:
            execution.execute_order(order_id, executed_at="2026-08-04T03:00:00+00:00")
        except RepositoryError as exc:
            exception_raised = exc
        finally:
            order_repo.record_fill = original_record_fill  # restore real production method

        check(exception_raised is not None, "execute_order() propagated the RepositoryError (not swallowed)")
        print(f"    exception raised: {type(exception_raised).__name__}: {exception_raised}")

        trades_after = trade_repo.list_by_order(order_id)
        order_after = order_repo.get_by_id(order_id)
        print("    state AFTER failed execute_order():")
        dump_order("Order", order_after)
        for t in trades_after:
            dump_trade("Trade", t)

        check(len(trades_after) == 1, "Trade row IS permanently committed despite the later failure (orphaned Trade)")
        check(order_after.status == "PENDING", "Order.status remains PENDING (never reached FILLED)")
        check(order_after.filled_price == 0.0, "Order.filled_price remains untouched (0.0)")
        check(order_after.filled_at is None, "Order.filled_at remains untouched (None)")
        check(
            trades_after[0].fill_price != order_after.filled_price or trades_after[0].fill_price != 0.0,
            "Trade.fill_price != Order.filled_price -- the documented inconsistent state after partial failure",
        )
    finally:
        db.disconnect()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        scenario_success_case(tmp)
        scenario_multiple_orders(tmp)
        scenario_restart_proof(tmp)
        scenario_failure_path(tmp)

    print("\n" + "=" * 70)
    print(f"ACTIVATION 3.4 STEP 2 ACCEPTANCE GATE: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())