"""Activation 3.5 STEP 1 acceptance-gate proof.

Drives the real production pipeline
(``PaperTradingEngine.submit_order()`` ->
``OrderLifecycleService.create_order()`` ->
``ExecutionService.execute_order()`` ->
``AccountBalanceService.apply_trade()`` ->
``OrderIdempotencyRepository.create()``) against a real SQLite file on
disk (never ``:memory:``, never a mock/fake repository), and dumps raw
before/after ``accounts``/``trades`` row state so the evidence is not
filtered through the same code being proven.

Run directly: ``python Tests/activation_3_5_step1_proof.py``
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.execution_policy_config import ExecutionPolicy  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
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


# Non-zero fee/tax so the proof actually exercises the roadmap formula
# (a zero fee/tax fixture cannot distinguish the old formula from the
# new one). buy_fee_rate/sell_fee_rate/sell_tax_rate are the same flat
# per-trade ExecutionPolicy placeholder values ExecutionService already
# reads today -- not a new fee/tax computation, per the "jangan
# mengubah fee/tax calculation" ground rule.
_POLICY = ExecutionPolicy(
    lot_size=100,
    buy_fee_rate=1500.0,
    sell_fee_rate=1500.0,
    sell_tax_rate=2000.0,
)


def _raw_account_row(db_path: Path) -> dict:
    """Read the accounts row directly via sqlite3 -- bypassing every
    Repository/Service under test -- so the proof is not filtered
    through the same code it is proving."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM accounts WHERE account_id = 'paper-id'").fetchone()
    conn.close()
    return dict(row) if row else None


def _raw_trade_rows(db_path: Path) -> list:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades ORDER BY trade_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _build_stack(db_path: Path, *, cash: float):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idempotency_repo = OrderIdempotencyRepository(manager)

    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=cash,
        equity=cash,
        buying_power=cash,
    )

    order_lifecycle_service = OrderLifecycleService(order_repo)
    execution_service = ExecutionService(order_repo, trade_repo, _POLICY)
    account_balance_service = AccountBalanceService(account_repo)

    engine = PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=False,
        max_order_value=1_000_000_000_000.0,
        execution_policy=_POLICY,
        account_balance_service=account_balance_service,
    )
    return db, account_repo, engine


def scenario_success_buy():
    print("\n[Scenario 1] SUCCESS BUY -- real SQLite, full production pipeline")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "buy.db"
        db, account_repo, engine = _build_stack(db_path, cash=100_000_000.0)

        before = _raw_account_row(db_path)
        print(f"  Before: cash={before['cash']}")

        trade = engine.submit_order(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
            executed_at="2026-08-04T10:00:00+00:00",
            signal_evidence={"rsi": 28.0},
            user_approval=True,
            idempotency_key="proof-buy-001",
        )

        gross_value = trade.fill_price * trade.quantity
        expected_cash = before["cash"] - gross_value - trade.fee - trade.tax

        after = _raw_account_row(db_path)
        print(
            f"  Trade: fill_price={trade.fill_price} quantity={trade.quantity} "
            f"fee={trade.fee} tax={trade.tax} gross_value={gross_value}"
        )
        print(f"  After:  cash={after['cash']} (expected {expected_cash})")

        check(trade.fee == 1500.0, "BUY trade recorded the non-zero buy_fee_rate as fee")
        check(trade.tax == 0.0, "BUY trade recorded zero tax (no tax leg on a BUY, unchanged)")
        check(gross_value == 950_000.0, "gross_value == fill_price * quantity")
        check(
            after["cash"] == expected_cash,
            "after.cash == before.cash - gross_value - fee - tax (roadmap BUY formula)",
        )
        check(after["cash"] >= 0.0, "resulting cash is not negative")

        db.disconnect()


def scenario_success_sell():
    print("\n[Scenario 2] SUCCESS SELL -- real SQLite, full production pipeline")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sell.db"
        db, account_repo, engine = _build_stack(db_path, cash=100_000_000.0)

        # Seed an open BBCA position directly via PositionRepository.
        # This Activation's ground rules forbid touching Position (see
        # module docstring, "Jangan mengubah Position") -- Position
        # creation/update is a later Activation's job, not this one's.
        # A BUY through the engine today does not create a Position
        # row at all, so gate 9 ("available position untuk SELL")
        # would otherwise reject every SELL in this codebase's current
        # state. Seeding the fixture directly (test-only setup, not a
        # production code path) isolates this proof to what Activation
        # 3.5 STEP 1 actually changed: the cash formula.
        from Repository.persistence.position_repository import PositionRepository as _PR  # noqa: E402

        assert isinstance(engine._position_repository, _PR)
        engine._position_repository.create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=200.0,
            average_price=9000.0,
            realized_pnl=0.0,
            status="open",
        )

        before = _raw_account_row(db_path)
        print(f"  Before: cash={before['cash']}")

        trade = engine.submit_order(
            account_id="paper-id",
            symbol="BBCA",
            action="SELL",
            quantity=100.0,
            requested_price=9600.0,
            executed_at="2026-08-04T11:00:00+00:00",
            signal_evidence={"rsi": 70.0},
            user_approval=True,
            idempotency_key="proof-sell-001",
        )

        gross_value = trade.fill_price * trade.quantity
        expected_cash = before["cash"] + gross_value - trade.fee - trade.tax

        after = _raw_account_row(db_path)
        print(
            f"  Trade: fill_price={trade.fill_price} quantity={trade.quantity} "
            f"fee={trade.fee} tax={trade.tax} gross_value={gross_value}"
        )
        print(f"  After:  cash={after['cash']} (expected {expected_cash})")

        check(trade.fee == 1500.0, "SELL trade recorded the non-zero sell_fee_rate as fee")
        check(trade.tax == 2000.0, "SELL trade recorded the non-zero sell_tax_rate as tax")
        check(gross_value == 960_000.0, "gross_value == fill_price * quantity")
        check(
            after["cash"] == expected_cash,
            "after.cash == before.cash + gross_value - fee - tax (roadmap SELL formula)",
        )
        check(after["cash"] >= 0.0, "resulting cash is not negative")

        db.disconnect()


def scenario_insufficient_cash_buy_fails():
    print("\n[Scenario 3] FAILURE -- BUY exceeding cash raises, cash/Account untouched")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "insufficient.db"
        db, account_repo, engine = _build_stack(db_path, cash=1_000_000.0)

        before = _raw_account_row(db_path)
        print(f"  Before: cash={before['cash']}")

        raised = False
        try:
            engine.submit_order(
                account_id="paper-id",
                symbol="BBCA",
                action="BUY",
                # gross_value alone (9500 * 200 = 1,900,000) already
                # exceeds cash (1,000,000) -- this must fail at the
                # engine's own gate 8 pre-trade check.
                quantity=200.0,
                requested_price=9500.0,
                executed_at="2026-08-04T12:00:00+00:00",
                signal_evidence={"rsi": 20.0},
                user_approval=True,
                idempotency_key="proof-insufficient-001",
            )
        except ValidationError as exc:
            raised = True
            print(f"  Exception raised: {exc}")

        after = _raw_account_row(db_path)
        trades = _raw_trade_rows(db_path)
        print(f"  After:  cash={after['cash']}")

        check(raised, "submit_order() raises ValidationError for insufficient cash")
        check(after["cash"] == before["cash"], "cash is byte-for-byte unchanged after the failure")
        check(len(trades) == 0, "no Trade row was created")
        check(after["cash"] >= 0.0, "cash never went negative")

        db.disconnect()


def scenario_insufficient_cash_via_fee_tax_at_balance_service():
    print(
        "\n[Scenario 3b] FAILURE -- AccountBalanceService's own guard rejects a "
        "BUY whose gross_value alone fits but gross_value+fee+tax does not"
    )
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "fee_boundary.db"
        cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(cfg)
        db.connect()
        MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
        manager = DatabaseManager(db, cfg)
        account_repo = AccountRepository(manager)
        # cash covers gross_value (950,000) exactly, but not
        # gross_value + fee + tax -- proves the service's own guard
        # uses the roadmap's required_cash, not just gross_value.
        account_repo.create(
            account_id="paper-id",
            account_name="Paper Indonesia",
            mode="paper",
            currency="IDR",
            asset_class="stock_id",
            cash=950_000.0,
            equity=950_000.0,
            buying_power=950_000.0,
        )
        service = AccountBalanceService(account_repo)

        from Database.models import Trade

        trade = Trade(
            trade_id=1,
            order_id=1,
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            fill_price=9500.0,
            fee=1500.0,
            tax=0.0,
            executed_at="2026-08-04T12:00:00+00:00",
        )

        before = _raw_account_row(db_path)
        raised = False
        try:
            service.apply_trade(trade)
        except ValidationError as exc:
            raised = True
            print(f"  Exception raised: {exc}")
        after = _raw_account_row(db_path)

        check(raised, "apply_trade() raises when gross_value + fee + tax > cash even though gross_value alone fits")
        check(after["cash"] == before["cash"], "cash is untouched after this rejection too")

        db.disconnect()


def scenario_restart_proof():
    print("\n[Scenario 4] RESTART PROOF -- cash survives an application restart")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "restart.db"
        db, account_repo, engine = _build_stack(db_path, cash=100_000_000.0)

        engine.submit_order(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
            executed_at="2026-08-04T10:00:00+00:00",
            signal_evidence={"rsi": 28.0},
            user_approval=True,
            idempotency_key="proof-restart-001",
        )
        cash_before_restart = _raw_account_row(db_path)["cash"]
        print(f"  Cash before restart: {cash_before_restart}")

        # "Restart the application": disconnect and build a brand new
        # SQLiteDatabase/DatabaseManager/AccountRepository over the
        # same on-disk file -- nothing carried over in memory.
        db.disconnect()

        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg2)
        account_repo2 = AccountRepository(manager2)
        reread_account = account_repo2.get_by_id("paper-id")
        print(f"  Cash after restart:  {reread_account.cash}")

        check(
            reread_account.cash == cash_before_restart,
            "cash re-read after a full restart (new DB connection/objects) matches pre-restart value",
        )

        db2.disconnect()


def scenario_multiple_trades_cumulative():
    print("\n[Scenario 5] MULTIPLE TRADES -- cumulative cash is correct after each step")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "multiple.db"
        db, account_repo, engine = _build_stack(db_path, cash=100_000_000.0)

        # Seed an open BBCA position directly (same rationale as
        # Scenario 2 -- Position updates are out of this Activation's
        # scope, see module docstring), large enough that both SELL
        # steps below stay within it.
        engine._position_repository.create(
            account_id="paper-id",
            symbol="BBCA",
            quantity=1_000.0,
            average_price=9000.0,
            realized_pnl=0.0,
            status="open",
        )

        cash = 100_000_000.0
        # Quantities are all IDX-lot-size (100 shares) multiples --
        # gate 6 is unchanged by this Activation and still enforced.
        steps = [
            ("BUY", 100.0, 9500.0, "proof-multi-001"),
            ("BUY", 200.0, 9600.0, "proof-multi-002"),
            ("SELL", 300.0, 9700.0, "proof-multi-003"),
            ("SELL", 100.0, 9550.0, "proof-multi-004"),
        ]

        for action, quantity, price, key in steps:
            before = _raw_account_row(db_path)["cash"]
            trade = engine.submit_order(
                account_id="paper-id",
                symbol="BBCA",
                action=action,
                quantity=quantity,
                requested_price=price,
                executed_at="2026-08-04T13:00:00+00:00",
                signal_evidence={"rsi": 50.0},
                user_approval=True,
                idempotency_key=key,
            )
            gross_value = trade.fill_price * trade.quantity
            if action == "BUY":
                cash = cash - gross_value - trade.fee - trade.tax
            else:
                cash = cash + gross_value - trade.fee - trade.tax
            after = _raw_account_row(db_path)["cash"]
            print(
                f"  {action} qty={quantity} price={price} fee={trade.fee} "
                f"tax={trade.tax} -> before={before} after={after} expected={cash}"
            )
            check(after == cash, f"cumulative cash correct after {action} {quantity}@{price}")

        db.disconnect()


def main() -> int:
    scenario_success_buy()
    scenario_success_sell()
    scenario_insufficient_cash_buy_fails()
    scenario_insufficient_cash_via_fee_tax_at_balance_service()
    scenario_restart_proof()
    scenario_multiple_trades_cumulative()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 3.5 STEP 1 PROOF RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())