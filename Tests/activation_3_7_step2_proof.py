"""Activation 3.7 STEP 2 -- standalone SQLite proof (not a unit test).

Proves that ``Business.position_manager.PositionManager`` now factors
``trade.fee``/``trade.tax`` into realized P/L on SELL, using a real
on-disk SQLite file (real ``PositionRepository`` + real migrations),
including a genuine connection close + reopen for the restart proof.

``PositionManager`` is called directly (never through
``PaperTradingEngine``), exactly as ``Tests/test_position_manager.py``
and ``Tests/activation_3_6_step3_proof.py`` already do -- this is the
one and only business owner for realized P/L, per the Activation 3.7
STEP 2 spec.

Run directly with ``python Tests/activation_3_7_step2_proof.py``.
"""
from __future__ import annotations

import sys
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.position_manager import PositionManager
from Core.exceptions import ValidationError
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migrations import MigrationRunner
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS
from Database.migrations_positions import POSITIONS_MIGRATIONS
from Database.models import Trade
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.position_repository import PositionRepository

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


def _build(tmp_dir: str, account_id: str = "paper-id"):
    db_path = Path(tmp_dir) / "activation_3_7_step2.db"
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id=account_id,
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )
    position_repo = PositionRepository(manager)
    service = PositionManager(position_repo)
    return db_path, db, service, position_repo


def _trade(trade_id, symbol="BBCA", account_id="paper-id", action="BUY",
           quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0, order_id=None):
    return Trade(
        trade_id=trade_id,
        order_id=order_id if order_id is not None else trade_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=fee,
        tax=tax,
        executed_at="2026-08-05T10:00:00+00:00",
    )


def _raw_position_row(db_path: Path, account_id: str, symbol: str):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM positions WHERE account_id=? AND symbol=?",
        (account_id, symbol),
    )
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# PROOF 1: BUY then SELL at a profit -- fee and tax reduce realized_pnl.
# ---------------------------------------------------------------------------
def proof_1_buy_sell_profit_with_fee_tax():
    print("\n[PROOF 1] BUY then SELL profit: realized_pnl accounts for fee and tax")
    with tempfile.TemporaryDirectory() as tmp:
        _, db, service, repo = _build(tmp)
        try:
            service.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))

            sell = service.apply_trade(
                _trade(2, action="SELL", quantity=100.0, fill_price=9800.0, fee=1500.0, tax=600.0)
            )

            gross = (9800.0 - 9500.0) * 100.0
            expected = gross - 1500.0 - 600.0
            check(expected == 27_900.0, "sanity: expected realized_pnl == 27,900.0 (gross 30,000 - 1,500 fee - 600 tax)")
            check(
                sell.realized_pnl == expected,
                f"realized_pnl == gross P/L - fee - tax (expected {expected}, got {sell.realized_pnl})",
            )
            check(sell.status == "closed", "position fully closed")
        finally:
            db.disconnect()


# ---------------------------------------------------------------------------
# PROOF 2: SELL at a loss -- realized_pnl still correctly reduced further
# by fee/tax (loss gets bigger, never smaller / never flips sign wrongly).
# ---------------------------------------------------------------------------
def proof_2_sell_loss_with_fee_tax():
    print("\n[PROOF 2] SELL rugi (loss): realized_pnl remains correct after fee and tax")
    with tempfile.TemporaryDirectory() as tmp:
        _, db, service, repo = _build(tmp)
        try:
            service.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))

            sell = service.apply_trade(
                _trade(2, action="SELL", quantity=100.0, fill_price=9300.0, fee=500.0, tax=200.0)
            )

            gross = (9300.0 - 9500.0) * 100.0  # -20,000.0 (a loss)
            expected = gross - 500.0 - 200.0  # -20,700.0 (loss widened by costs)
            check(gross == -20_000.0, "sanity: gross P/L is a loss of -20,000.0")
            check(expected == -20_700.0, "sanity: expected realized_pnl == -20,700.0")
            check(
                sell.realized_pnl == expected,
                f"realized_pnl on a losing SELL still == gross P/L - fee - tax (expected {expected}, got {sell.realized_pnl})",
            )
        finally:
            db.disconnect()


# ---------------------------------------------------------------------------
# PROOF 3: Partial SELL -- average_price stays put, realized_pnl
# accumulates across multiple SELLs, and each trade's fee/tax is only
# ever subtracted once (never re-applied on a later call).
# ---------------------------------------------------------------------------
def proof_3_partial_sell_accumulates_no_double_count():
    print("\n[PROOF 3] Partial SELL: average_price fixed, realized_pnl accumulates, fee/tax charged once per trade")
    with tempfile.TemporaryDirectory() as tmp:
        _, db, service, repo = _build(tmp)
        try:
            service.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))

            first = service.apply_trade(
                _trade(2, action="SELL", quantity=40.0, fill_price=9800.0, fee=200.0, tax=80.0)
            )
            expected_first = (9800.0 - 9500.0) * 40.0 - 200.0 - 80.0
            check(first.average_price == 9500.0, "average_price untouched after first partial SELL")
            check(first.quantity == 60.0, "quantity reduced by first partial SELL's quantity")
            check(
                first.realized_pnl == expected_first,
                f"realized_pnl after first partial SELL (expected {expected_first}, got {first.realized_pnl})",
            )

            second = service.apply_trade(
                _trade(3, action="SELL", quantity=20.0, fill_price=9400.0, fee=100.0, tax=40.0)
            )
            expected_second_delta = (9400.0 - 9500.0) * 20.0 - 100.0 - 40.0
            expected_total = expected_first + expected_second_delta
            check(second.average_price == 9500.0, "average_price still untouched after second partial SELL")
            check(second.quantity == 40.0, "quantity reduced correctly after second partial SELL")
            check(
                second.realized_pnl == expected_total,
                f"realized_pnl accumulates across SELLs (expected {expected_total}, got {second.realized_pnl})",
            )

            # No-double-count check: the FIRST trade's fee/tax
            # contributed exactly once to the running total, even
            # though the position has since been read/written again
            # by the second SELL. Reconstruct what the total *would*
            # be if trade #2's fee/tax had been (incorrectly) applied
            # a second time, and confirm the actual total is not that.
            wrongly_double_counted = expected_total - 200.0 - 80.0
            check(
                second.realized_pnl != wrongly_double_counted,
                "trade #2's fee/tax was not re-subtracted when trade #3 was applied (no double-count)",
            )
        finally:
            db.disconnect()


# ---------------------------------------------------------------------------
# PROOF 4: Full close -- quantity 0, status closed, final realized_pnl
# correct including fee/tax from both partial SELLs.
# ---------------------------------------------------------------------------
def proof_4_full_close():
    print("\n[PROOF 4] Full close: quantity == 0, status == 'closed', realized_pnl final value correct")
    with tempfile.TemporaryDirectory() as tmp:
        db_path, db, service, repo = _build(tmp)
        try:
            service.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
            service.apply_trade(
                _trade(2, action="SELL", quantity=60.0, fill_price=9800.0, fee=300.0, tax=120.0)
            )
            final = service.apply_trade(
                _trade(3, action="SELL", quantity=40.0, fill_price=9700.0, fee=200.0, tax=80.0)
            )

            expected = (
                (9800.0 - 9500.0) * 60.0 - 300.0 - 120.0
                + (9700.0 - 9500.0) * 40.0 - 200.0 - 80.0
            )
            check(final.quantity == 0.0, "quantity is exactly 0.0 after the full close")
            check(final.status == "closed", "status is 'closed'")
            check(
                final.realized_pnl == expected,
                f"final realized_pnl correct across both SELLs (expected {expected}, got {final.realized_pnl})",
            )

            still_open = repo.get_open_position("paper-id", "BBCA")
            check(still_open is None, "no OPEN position remains for this account+symbol")

            raw = _raw_position_row(db_path, "paper-id", "BBCA")
            check(raw is not None, "closed position row still exists in the raw positions table")
            check(raw["status"] == "closed", "raw row status column is 'closed'")
            check(raw["quantity"] == 0.0, "raw row quantity column is 0.0")
        finally:
            db.disconnect()


# ---------------------------------------------------------------------------
# PROOF 5: Restart -- close the connection, reopen the same DB file,
# realized_pnl is unchanged.
# ---------------------------------------------------------------------------
def proof_5_restart_preserves_realized_pnl():
    print("\n[PROOF 5] Restart: realized_pnl survives closing and reopening the SQLite connection")
    with tempfile.TemporaryDirectory() as tmp:
        db_path, db, service, repo = _build(tmp)
        service.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
        result = service.apply_trade(
            _trade(2, action="SELL", quantity=100.0, fill_price=9800.0, fee=1500.0, tax=600.0)
        )
        expected = (9800.0 - 9500.0) * 100.0 - 1500.0 - 600.0
        check(result.realized_pnl == expected, f"realized_pnl before restart == {expected}")

        db.disconnect()

        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg2)
            position_repo2 = PositionRepository(manager2)
            reread = position_repo2.get_by_id(result.position_id)
            check(reread is not None, "position row still exists after reconnect")
            check(
                reread.realized_pnl == expected,
                f"realized_pnl unchanged after close+reopen (expected {expected}, got {reread.realized_pnl})",
            )
            check(reread.status == "closed", "status unchanged after close+reopen")
            check(reread.quantity == 0.0, "quantity unchanged after close+reopen")

            raw = _raw_position_row(db_path, "paper-id", "BBCA")
            check(raw["realized_pnl"] == expected, "raw SQLite column realized_pnl matches expected after reconnect")
        finally:
            db2.disconnect()


# ---------------------------------------------------------------------------
# Sanity: locked behaviour untouched -- BUY flow / weighted average /
# oversell guard still behave exactly as before this Activation.
# ---------------------------------------------------------------------------
def sanity_locked_behaviour_untouched():
    print("\n[SANITY] Locked behaviour (BUY flow, weighted average, oversell guard) is unaffected")
    with tempfile.TemporaryDirectory() as tmp:
        _, db, service, repo = _build(tmp)
        try:
            first = service.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0, fee=500.0, tax=0.0))
            check(first.realized_pnl == 0.0, "fresh BUY still seeds realized_pnl at literal 0.0 (fee ignored on BUY)")

            merged = service.apply_trade(_trade(2, action="BUY", quantity=100.0, fill_price=9700.0, fee=500.0, tax=0.0))
            expected_avg = (100.0 * 9500.0 + 100.0 * 9700.0) / 200.0
            check(merged.average_price == expected_avg, "weighted average formula unchanged (fee ignored on BUY merge)")
            check(merged.realized_pnl == 0.0, "realized_pnl still just passed through on a BUY merge")

            raised = False
            try:
                service.apply_trade(_trade(3, action="SELL", quantity=1000.0, fill_price=9500.0))
            except ValidationError:
                raised = True
            check(raised, "oversell guard still raises ValidationError")

            unchanged = repo.get_open_position("paper-id", "BBCA")
            check(unchanged.quantity == 200.0, "position untouched after rejected oversell")
        finally:
            db.disconnect()


def main() -> int:
    proof_1_buy_sell_profit_with_fee_tax()
    proof_2_sell_loss_with_fee_tax()
    proof_3_partial_sell_accumulates_no_double_count()
    proof_4_full_close()
    proof_5_restart_preserves_realized_pnl()
    sanity_locked_behaviour_untouched()

    print("\n" + "=" * 70)
    print(f"ACTIVATION 3.7 STEP 2 PROOF RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())