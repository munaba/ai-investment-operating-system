"""Standalone regression checks for net-performance-after-fee --
``Database.models.Position.buy_fee_accumulated``.

Covers exactly what this Activation adds, no more:

* migration -- ``buy_fee_accumulated`` column exists after
  ``POSITIONS_MIGRATIONS`` (through ``version=17``), defaults to
  ``0.0`` for a freshly created row;
* repository round-trip -- ``PositionRepository.create``/``update``
  persist a caller-supplied ``buy_fee_accumulated`` exactly, and
  ``get_by_id``/``get_open_position``/``list_by_account`` read it
  back unchanged;
* ``PositionManager``:
    - a first BUY seeds ``buy_fee_accumulated`` with that trade's
      ``fee`` (never ``0.0``, never the whole-Trade cost);
    - a BUY merge ADDS the new trade's ``fee`` to the existing
      accumulator;
    - a partial SELL keeps the fraction of the accumulator
      proportional to the quantity REMAINING held, i.e. realizes the
      complementary, sold-proportional fraction off the position;
    - a full SELL always leaves ``buy_fee_accumulated == 0.0``
      exactly (float-exact, not just epsilon-close);
    - ``average_price``, ``realized_pnl`` (still only SELL
      ``fee``/``tax``, no ``buy_fee_accumulated`` term), and
      ``Account.cash`` behavior are all BYTE-FOR-BYTE unchanged by
      this Activation;
* ``ReconciliationEngine`` -- replays ``buy_fee_accumulated`` through
  the exact same trade history and reports the account CONSISTENT;
  a manufactured mismatch on just this one field is caught and
  reported as a violation (proving the invariant is actually wired
  in, not silently skipped).

Run directly with ``python Tests/test_position_net_performance_after_fee.py``
-- no external test framework required, matching every other
``Tests/test_*.py`` file in this codebase.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.position_manager import PositionManager  # noqa: E402
from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
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


def _build(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "net_performance_after_fee.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    position_repo = PositionRepository(manager)
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
    return db, manager, account_repo, position_repo, order_repo, trade_repo


def _trade(trade_id=1, order_id=1, account_id="paper-id", symbol="BBCA",
           action="BUY", quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0,
           executed_at="2026-08-01T10:00:00+00:00"):
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=fee,
        tax=tax,
        executed_at=executed_at,
    )


# -- migration -------------------------------------------------------


def scenario_migration_adds_column_default_zero():
    print("\n[Scenario 1] migration adds buy_fee_accumulated, default 0.0 on a fresh row")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)

        created = position_repo.create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9500.0,
            realized_pnl=0.0,
            status="open",
        )
        check(hasattr(created, "buy_fee_accumulated"), "Position has a buy_fee_accumulated attribute")
        check(created.buy_fee_accumulated == 0.0, "buy_fee_accumulated defaults to 0.0 when create() omits it")

        fetched = position_repo.get_by_id(created.position_id)
        check(fetched.buy_fee_accumulated == 0.0, "default 0.0 round-trips through the database")


# -- repository round-trip -------------------------------------------


def scenario_repository_persists_supplied_value():
    print("\n[Scenario 2] PositionRepository.create/update persist a caller-supplied buy_fee_accumulated exactly")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)

        created = position_repo.create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=100.0,
            average_price=9500.0,
            realized_pnl=0.0,
            status="open",
            buy_fee_accumulated=1_500.0,
        )
        check(created.buy_fee_accumulated == 1_500.0, "create() persists the supplied buy_fee_accumulated")

        position_repo.update(
            position_id=created.position_id,
            quantity=100.0,
            average_price=9500.0,
            realized_pnl=0.0,
            status="open",
            buy_fee_accumulated=2_750.0,
        )
        updated = position_repo.get_by_id(created.position_id)
        check(updated.buy_fee_accumulated == 2_750.0, "update() overwrites buy_fee_accumulated exactly")

        by_open = position_repo.get_open_position("paper-id", "BBCA")
        check(by_open.buy_fee_accumulated == 2_750.0, "get_open_position() reads it back unchanged")

        by_list = position_repo.list_by_account("paper-id")[0]
        check(by_list.buy_fee_accumulated == 2_750.0, "list_by_account() reads it back unchanged")


# -- PositionManager: BUY ---------------------------------------------


def scenario_first_buy_seeds_accumulator_with_trade_fee():
    print("\n[Scenario 3] first BUY seeds buy_fee_accumulated with that trade's fee")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)
        manager = PositionManager(position_repo)

        position = manager.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0, fee=1_500.0, tax=0.0))

        check(position.buy_fee_accumulated == 1_500.0, "buy_fee_accumulated == first BUY trade.fee")
        check(position.average_price == 9500.0, "average_price unaffected by fee tracking")
        check(position.realized_pnl == 0.0, "realized_pnl unaffected by fee tracking (still the 0.0 placeholder)")


def scenario_buy_merge_adds_fee_to_accumulator():
    print("\n[Scenario 4] a BUY merge ADDS the new trade's fee to the existing accumulator")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)
        manager = PositionManager(position_repo)

        manager.apply_trade(_trade(trade_id=1, action="BUY", quantity=100.0, fill_price=9500.0, fee=1_500.0))
        merged = manager.apply_trade(_trade(trade_id=2, action="BUY", quantity=100.0, fill_price=9700.0, fee=1_500.0))

        check(merged.buy_fee_accumulated == 3_000.0, "merged buy_fee_accumulated == sum of both BUY fees")
        check(merged.quantity == 200.0, "merge still sums quantity correctly (unchanged behavior)")
        check(
            merged.average_price == (100.0 * 9500.0 + 100.0 * 9700.0) / 200.0,
            "average_price formula is byte-for-byte unchanged",
        )


# -- PositionManager: SELL ---------------------------------------------


def scenario_partial_sell_realizes_proportional_fee():
    print("\n[Scenario 5] a partial SELL realizes the BUY fee proportionally to sold quantity")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)
        manager = PositionManager(position_repo)

        manager.apply_trade(_trade(trade_id=1, action="BUY", quantity=100.0, fill_price=9500.0, fee=1_000.0))
        result = manager.apply_trade(
            _trade(trade_id=2, action="SELL", quantity=40.0, fill_price=9800.0, fee=500.0, tax=200.0)
        )

        # 40 of 100 sold -> 60 remain held -> 60% of the accumulator
        # (proportional to what remains) stays with the still-OPEN
        # position; the complementary 40% was realized off it.
        expected_remaining = 1_000.0 * (60.0 / 100.0)
        check(
            abs(result.buy_fee_accumulated - expected_remaining) < 1e-9,
            "remaining buy_fee_accumulated == accumulator * (remaining_qty / qty_before_sell)",
        )
        check(result.quantity == 60.0, "quantity reduced by sell quantity (unchanged behavior)")
        check(result.status == "open", "status stays open on a partial SELL (unchanged behavior)")

        expected_realized_pnl = (9800.0 - 9500.0) * 40.0 - 500.0 - 200.0
        check(
            abs(result.realized_pnl - expected_realized_pnl) < 1e-9,
            "realized_pnl formula unchanged: still (fill-avg)*qty - trade.fee - trade.tax only, "
            "no buy_fee_accumulated term",
        )
        check(result.average_price == 9500.0, "average_price left untouched by SELL (unchanged behavior)")


def scenario_full_sell_leaves_accumulator_exactly_zero():
    print("\n[Scenario 6] a full SELL always leaves buy_fee_accumulated == 0.0 exactly")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)
        manager = PositionManager(position_repo)

        manager.apply_trade(_trade(trade_id=1, action="BUY", quantity=100.0, fill_price=9500.0, fee=1_234.5))
        result = manager.apply_trade(
            _trade(trade_id=2, action="SELL", quantity=100.0, fill_price=9900.0, fee=500.0, tax=200.0)
        )

        check(result.buy_fee_accumulated == 0.0, "buy_fee_accumulated is exactly 0.0 (float-exact) after full SELL")
        check(result.status == "closed", "status becomes closed on a full SELL (unchanged behavior)")


def scenario_sell_then_reopen_starts_accumulator_fresh():
    print("\n[Scenario 7] a fresh BUY reopening after a CLOSE starts buy_fee_accumulated at that trade's fee, "
          "never carries over from the closed position")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)
        manager = PositionManager(position_repo)

        manager.apply_trade(_trade(trade_id=1, action="BUY", quantity=100.0, fill_price=9500.0, fee=1_000.0))
        manager.apply_trade(_trade(trade_id=2, action="SELL", quantity=100.0, fill_price=9900.0, fee=500.0, tax=200.0))
        reopened = manager.apply_trade(
            _trade(trade_id=3, order_id=3, action="BUY", quantity=50.0, fill_price=10_000.0, fee=750.0)
        )

        check(reopened.buy_fee_accumulated == 750.0, "reopening BUY seeds a fresh accumulator (only this trade's fee)")
        check(reopened.status == "open", "reopening BUY is OPEN (unchanged behavior)")


def scenario_multiple_partial_sells_accumulate_correctly():
    print("\n[Scenario 8] two successive partial SELLs each realize their own proportional share")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)
        manager = PositionManager(position_repo)

        manager.apply_trade(_trade(trade_id=1, action="BUY", quantity=100.0, fill_price=9500.0, fee=1_000.0))
        after_first = manager.apply_trade(
            _trade(trade_id=2, action="SELL", quantity=50.0, fill_price=9800.0, fee=100.0, tax=50.0)
        )
        # 50 remain of 100 -> 50% of 1_000.0 == 500.0
        check(abs(after_first.buy_fee_accumulated - 500.0) < 1e-9, "first partial SELL leaves 50% of the accumulator")

        after_second = manager.apply_trade(
            _trade(trade_id=3, action="SELL", quantity=50.0, fill_price=9900.0, fee=100.0, tax=50.0)
        )
        check(after_second.buy_fee_accumulated == 0.0, "second (final) SELL leaves exactly 0.0")
        check(after_second.status == "closed", "position closes once quantity reaches zero")


def scenario_set_stop_loss_take_profit_preserves_accumulator():
    print("\n[Scenario 9] set_stop_loss_take_profit() passes buy_fee_accumulated through unchanged")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, _, _ = _build(tmp)
        manager = PositionManager(position_repo)

        position = manager.apply_trade(_trade(action="BUY", quantity=100.0, fill_price=9500.0, fee=1_500.0))
        updated = manager.set_stop_loss_take_profit(position.position_id, stop_loss=9000.0, take_profit=10000.0)

        check(updated.buy_fee_accumulated == 1_500.0, "buy_fee_accumulated untouched by set_stop_loss_take_profit()")


# -- ReconciliationEngine ---------------------------------------------


def scenario_reconciliation_replays_buy_fee_accumulator_consistent():
    print("\n[Scenario 10] ReconciliationEngine replays buy_fee_accumulated and reports CONSISTENT")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, order_repo, trade_repo = _build(tmp)
        manager = PositionManager(position_repo)
        reconciler = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)

        # Trades applied directly through PositionManager (this file's
        # own scope), while still exercising Order/TradeRepository so
        # the engine has real Order+Trade rows to replay against --
        # mirrors Tests/test_reconciliation_engine.py's own use of
        # real persisted rows for invariant 3.
        buy_order = order_repo.create(
            account_id="paper-id", symbol="BBCA", action="BUY", quantity=100.0,
            requested_price=9500.0, filled_price=0.0, status="NEW",
            reason="test",
        )
        buy = trade_repo.create(
            order_id=buy_order.order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=100.0, fill_price=9500.0, fee=1_500.0, tax=0.0,
            executed_at="2026-08-01T10:00:00+00:00",
        )
        order_repo.record_fill(
            order_id=buy_order.order_id, status="FILLED", filled_price=buy.fill_price,
            filled_quantity=buy.quantity, filled_at=buy.executed_at, reason="test",
        )
        manager.apply_trade(buy)

        sell_order = order_repo.create(
            account_id="paper-id", symbol="BBCA", action="SELL", quantity=40.0,
            requested_price=9800.0, filled_price=0.0, status="NEW",
            reason="test",
        )
        sell = trade_repo.create(
            order_id=sell_order.order_id, account_id="paper-id", symbol="BBCA", action="SELL",
            quantity=40.0, fill_price=9800.0, fee=500.0, tax=200.0,
            executed_at="2026-08-01T11:00:00+00:00",
        )
        order_repo.record_fill(
            order_id=sell_order.order_id, status="FILLED", filled_price=sell.fill_price,
            filled_quantity=sell.quantity, filled_at=sell.executed_at, reason="test",
        )
        manager.apply_trade(sell)

        result = reconciler.reconcile_account("paper-id")
        check(result.status == "CONSISTENT", "reconcile_account() reports CONSISTENT after replaying buy_fee_accumulated")
        check(result.violations == [], "zero violations")


def scenario_reconciliation_flags_buy_fee_accumulator_mismatch():
    print("\n[Scenario 11] ReconciliationEngine flags a manufactured buy_fee_accumulated mismatch")
    with tempfile.TemporaryDirectory() as tmp:
        _, _, account_repo, position_repo, order_repo, trade_repo = _build(tmp)
        manager = PositionManager(position_repo)
        reconciler = ReconciliationEngine(order_repo, trade_repo, account_repo, position_repo)

        buy_order = order_repo.create(
            account_id="paper-id", symbol="BBCA", action="BUY", quantity=100.0,
            requested_price=9500.0, filled_price=0.0, status="NEW",
            reason="test",
        )
        buy = trade_repo.create(
            order_id=buy_order.order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=100.0, fill_price=9500.0, fee=1_500.0, tax=0.0,
            executed_at="2026-08-01T10:00:00+00:00",
        )
        order_repo.record_fill(
            order_id=buy_order.order_id, status="FILLED", filled_price=buy.fill_price,
            filled_quantity=buy.quantity, filled_at=buy.executed_at, reason="test",
        )
        position = manager.apply_trade(buy)

        # Corrupt only buy_fee_accumulated -- quantity/average_price/
        # realized_pnl/status all stay correct, so this isolates the
        # new invariant from every pre-existing one.
        position_repo.update(
            position_id=position.position_id,
            quantity=position.quantity,
            average_price=position.average_price,
            realized_pnl=position.realized_pnl,
            status=position.status,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            buy_fee_accumulated=999_999.0,
        )

        result = reconciler.reconcile_account("paper-id")
        check(result.status == "INCONSISTENT", "a corrupted buy_fee_accumulated is reported INCONSISTENT")
        check(
            any("buy_fee_accumulated" in v for v in result.violations),
            "the violation message identifies buy_fee_accumulated specifically",
        )


def main() -> int:
    scenario_migration_adds_column_default_zero()
    scenario_repository_persists_supplied_value()
    scenario_first_buy_seeds_accumulator_with_trade_fee()
    scenario_buy_merge_adds_fee_to_accumulator()
    scenario_partial_sell_realizes_proportional_fee()
    scenario_full_sell_leaves_accumulator_exactly_zero()
    scenario_sell_then_reopen_starts_accumulator_fresh()
    scenario_multiple_partial_sells_accumulate_correctly()
    scenario_set_stop_loss_take_profit_preserves_accumulator()
    scenario_reconciliation_replays_buy_fee_accumulator_consistent()
    scenario_reconciliation_flags_buy_fee_accumulator_mismatch()

    print("\n" + "=" * 60)
    print(f"NET-PERFORMANCE-AFTER-FEE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())