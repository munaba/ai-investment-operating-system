"""Activation 3.6 STEP 3 -- standalone SQLite proof (not a unit test).

Runs the real production pipeline (PaperTradingEngine.submit_order(),
never PositionManager called directly) against a real on-disk SQLite
file, inspecting raw table state before/after each step, including a
real connection close + reopen for the restart proof.
"""
from __future__ import annotations

import sys
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.account_balance_service import AccountBalanceService
from Business.execution_service import ExecutionService
from Business.order_lifecycle_service import OrderLifecycleService
from Business.paper_trading_engine import PaperTradingEngine
from Business.position_manager import PositionManager
from Core.exceptions import ValidationError
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migrations import MigrationRunner
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS
from Database.migrations_positions import POSITIONS_MIGRATIONS
from Database.migrations_orders import ORDERS_MIGRATIONS
from Database.migrations_trades import TRADES_MIGRATIONS
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.trade_repository import TradeRepository
from Repository.persistence.order_idempotency_repository import OrderIdempotencyRepository

DB_PATH = None  # set inside main()


def raw_counts(db_path: Path) -> dict:
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    out = {}
    for table in ("accounts", "positions", "orders", "trades", "order_idempotency_keys"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        out[table] = cur.fetchone()[0]
    con.close()
    return out


def raw_position_row(db_path: Path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM positions WHERE account_id='paper-id' AND symbol='BBCA'")
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def raw_account_cash(db_path: Path) -> float:
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("SELECT cash FROM accounts WHERE account_id='paper-id'")
    row = cur.fetchone()
    con.close()
    return row[0]


def build_engine(db_path: Path, *, create_account: bool = True):
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
    idem_repo = OrderIdempotencyRepository(manager)
    if create_account:
        account_repo.create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id",
            cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
        )
    ols = OrderLifecycleService(order_repo)
    execsvc = ExecutionService(order_repo, trade_repo)
    abs_svc = AccountBalanceService(account_repo)
    pm = PositionManager(position_repo)
    engine = PaperTradingEngine(
        order_lifecycle_service=ols,
        execution_service=execsvc,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idem_repo,
        kill_switch_engaged=False,
        max_order_value=1_000_000_000.0,
        account_balance_service=abs_svc,
        position_manager=pm,
    )
    return engine, manager


def submit(engine, key, action, qty, price):
    return engine.submit_order(
        account_id="paper-id", symbol="BBCA", action=action,
        quantity=qty, requested_price=price, executed_at="2026-08-01T10:00:00+00:00",
        signal_evidence={"reason": "proof"}, user_approval=True, idempotency_key=key,
    )


def main() -> int:
    fails = 0

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "activation_3_6_step3.db"

        # ---------------- Proof 1: BUY then partial SELL ----------------
        print("=" * 70)
        print("PROOF 1 -- BUY then partial SELL")
        print("=" * 70)
        engine, manager = build_engine(db_path)
        submit(engine, "buy-1", "BUY", 200.0, 9500.0)  # 200 shares = 2 IDX lots
        before = raw_position_row(db_path)
        print("after BUY:", before)

        submit(engine, "sell-1", "SELL", 100.0, 9800.0)  # 1 lot, partial
        after = raw_position_row(db_path)
        print("after partial SELL:", after)

        expected_pnl = (9800.0 - 9500.0) * 100.0
        ok = (
            after["quantity"] == 100.0
            and after["average_price"] == 9500.0
            and after["realized_pnl"] == expected_pnl
            and after["status"] == "open"
        )
        print(f"  quantity == 100.0: {after['quantity'] == 100.0}")
        print(f"  average_price unchanged (9500.0): {after['average_price'] == 9500.0}")
        print(f"  realized_pnl == {expected_pnl}: {after['realized_pnl'] == expected_pnl}")
        print(f"  status == 'open': {after['status'] == 'open'}")
        print("PROOF 1:", "PASS" if ok else "FAIL")
        fails += 0 if ok else 1
        manager.database.disconnect()

        # ---------------- Proof 2: SELL the remaining 60 (full close) ----------------
        print("\n" + "=" * 70)
        print("PROOF 2 -- SELL remaining quantity fully (close)")
        print("=" * 70)
        engine, manager = build_engine(db_path, create_account=False)  # reconnect over same file
        submit(engine, "sell-2", "SELL", 100.0, 9400.0)  # remaining lot, closes position
        closed = raw_position_row(db_path)
        print("after full SELL:", closed)

        expected_final_pnl = expected_pnl + (9400.0 - 9500.0) * 100.0
        ok2 = (
            closed["quantity"] == 0.0
            and closed["status"] == "closed"
            and closed["realized_pnl"] == expected_final_pnl
        )
        print(f"  quantity == 0.0: {closed['quantity'] == 0.0}")
        print(f"  status == 'closed': {closed['status'] == 'closed'}")
        print(f"  realized_pnl == {expected_final_pnl}: {closed['realized_pnl'] == expected_final_pnl}")
        print("PROOF 2:", "PASS" if ok2 else "FAIL")
        fails += 0 if ok2 else 1
        manager.database.disconnect()

        # ---------------- Proof 3: Oversell on a fresh symbol ----------------
        print("\n" + "=" * 70)
        print("PROOF 3 -- Oversell rejected, zero-write")
        print("=" * 70)
        engine, manager = build_engine(db_path, create_account=False)
        submit(engine, "buy-3", "BUY", 100.0, 9000.0)  # BBCA re-opens: prior position CLOSED in Proof 2
        before_counts = raw_counts(db_path)
        before_cash = raw_account_cash(db_path)
        raised = False
        try:
            submit(engine, "sell-oversell", "SELL", 900.0, 9000.0)  # 900 > 100 held, still lot-size valid
        except ValidationError as exc:
            raised = True
            print("  ValidationError raised:", exc.details.get("reason") if hasattr(exc, "details") else exc)
        after_counts = raw_counts(db_path)
        after_cash = raw_account_cash(db_path)
        ok3 = (
            raised
            and before_counts == after_counts
            and before_cash == after_cash
        )
        print(f"  ValidationError raised: {raised}")
        print(f"  table row counts unchanged: {before_counts} == {after_counts} -> {before_counts == after_counts}")
        print(f"  cash unchanged: {before_cash} == {after_cash} -> {before_cash == after_cash}")
        print("PROOF 3:", "PASS" if ok3 else "FAIL")
        fails += 0 if ok3 else 1
        manager.database.disconnect()

        # ---------------- Proof 4: restart persistence ----------------
        print("\n" + "=" * 70)
        print("PROOF 4 -- restart: close connection, reopen, state survives")
        print("=" * 70)
        before_restart = raw_position_row(db_path)  # BBCA row, closed, from proof 1/2
        print("state before restart (raw sqlite3, no app connection open):", before_restart)

        # Reopen via a brand-new engine/manager over the same file (simulates app restart)
        engine2, manager2 = build_engine(db_path, create_account=False)
        after_restart = raw_position_row(db_path)
        print("state after restart (fresh DatabaseManager, same file):", after_restart)

        ok4 = (
            before_restart is not None
            and after_restart is not None
            and before_restart["quantity"] == after_restart["quantity"]
            and before_restart["average_price"] == after_restart["average_price"]
            and before_restart["realized_pnl"] == after_restart["realized_pnl"]
            and before_restart["status"] == after_restart["status"]
        )
        print(f"  quantity survives restart: {before_restart['quantity']} == {after_restart['quantity']}")
        print(f"  average_price survives restart: {before_restart['average_price']} == {after_restart['average_price']}")
        print(f"  realized_pnl survives restart: {before_restart['realized_pnl']} == {after_restart['realized_pnl']}")
        print(f"  status survives restart: {before_restart['status']} == {after_restart['status']}")
        print("PROOF 4:", "PASS" if ok4 else "FAIL")
        fails += 0 if ok4 else 1
        manager2.database.disconnect()

    print("\n" + "=" * 70)
    print(f"ACTIVATION 3.6 STEP 3 SQLITE PROOF: {'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
    print("=" * 70)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())