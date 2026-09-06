"""Activation 3.7 STEP 4 -- standalone SQLite proof (not a unit test).

Proves ``Business.unrealized_pnl_engine.UnrealizedPnLEngine`` against a
real on-disk SQLite file (real ``PositionRepository`` + real
migrations, real ``PositionManager`` for BUY setup), including a
genuine connection close + reopen for the restart proof.

Market price is supplied via a small, duck-typed test double
(``_FixedPriceTool``) that implements the exact same contract as
``Orchestration.market_price_tool.MarketPriceTool``
(``execute(context) -> ToolResult`` reading ``context.parameters``) --
this mirrors the project's own existing pattern of injecting a fake
collaborator for determinism (e.g. ``StockService``'s
``yfinance_module``/``stock_repository`` injection seams). The real
``MarketPriceTool`` in production is never modified; this proof only
substitutes what price it reports, so results are deterministic
without a live network/yfinance call.

Run directly with ``python Tests/activation_3_7_step4_proof.py``.
"""
from __future__ import annotations

import sys
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.position_manager import PositionManager
from Business.unrealized_pnl_engine import UnrealizedPnLEngine, UnrealizedPnLResult
from Core.exceptions import ValidationError
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migrations import MigrationRunner
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS
from Database.migrations_positions import POSITIONS_MIGRATIONS
from Database.models import Trade
from Database.sqlite_database import SQLiteDatabase
from Orchestration.tool_result import ToolResult
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


class _FixedPriceTool:
    """Test double for ``MarketPriceTool``: same ``execute(context)``
    contract, but reports a fixed, caller-supplied price instead of
    making a real network/yfinance call. Never touched by production
    code -- ``UnrealizedPnLEngine`` only ever depends on the
    ``execute(context) -> ToolResult`` shape, never on the concrete
    ``MarketPriceTool`` class itself.
    """

    def __init__(self, price):
        self._price = price

    def execute(self, context):
        symbol = context.parameters.get("symbol")
        return ToolResult(
            success=True,
            output={"symbol": symbol, "price": self._price, "trend": "manual-fixture"},
            error=None,
            metadata={},
        )


def _build(tmp_dir: str, account_id: str = "paper-id"):
    db_path = Path(tmp_dir) / "activation_3_7_step4.db"
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
    position_manager = PositionManager(position_repo)
    return db_path, db, position_manager, position_repo, account_repo


def _trade(trade_id, symbol="BBCA", account_id="paper-id", action="BUY",
           quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0):
    return Trade(
        trade_id=trade_id,
        order_id=trade_id,
        account_id=account_id,
        symbol=symbol,
        action=action,
        quantity=quantity,
        fill_price=fill_price,
        fee=fee,
        tax=tax,
        executed_at="2026-08-05T10:00:00+00:00",
    )


def _raw_rows(db_path: Path, table: str):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(f"SELECT * FROM {table}")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


# ---------------------------------------------------------------------------
# PROOF 1: BUY, market naik -> unrealized positif.
# ---------------------------------------------------------------------------
def proof_1_market_up_positive_unrealized():
    print("\n[PROOF 1] BUY then market naik: unrealized_pnl positif")
    with tempfile.TemporaryDirectory() as tmp:
        _, db, position_manager, position_repo, _ = _build(tmp)
        try:
            position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
            position = position_repo.get_open_position("paper-id", "BBCA")

            engine = UnrealizedPnLEngine(_FixedPriceTool(9800.0))
            result = engine.calculate(position)

            expected = (9800.0 - 9500.0) * 100.0
            check(isinstance(result, UnrealizedPnLResult), "calculate() returns an UnrealizedPnLResult")
            check(result.market_price == 9800.0, "market_price reflects the current (higher) market price")
            check(result.average_price == 9500.0, "average_price read verbatim from Position")
            check(result.quantity == 100.0, "quantity read verbatim from Position")
            check(result.unrealized_pnl == expected, f"unrealized_pnl positive == {expected} (got {result.unrealized_pnl})")
            check(result.unrealized_pnl > 0, "unrealized_pnl is indeed positive")
            check(bool(result.market_timestamp), "market_timestamp is populated (non-empty)")
        finally:
            db.disconnect()


# ---------------------------------------------------------------------------
# PROOF 2: market turun -> unrealized negatif.
# ---------------------------------------------------------------------------
def proof_2_market_down_negative_unrealized():
    print("\n[PROOF 2] Market turun: unrealized_pnl negatif")
    with tempfile.TemporaryDirectory() as tmp:
        _, db, position_manager, position_repo, _ = _build(tmp)
        try:
            position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
            position = position_repo.get_open_position("paper-id", "BBCA")

            engine = UnrealizedPnLEngine(_FixedPriceTool(9100.0))
            result = engine.calculate(position)

            expected = (9100.0 - 9500.0) * 100.0
            check(expected == -40_000.0, "sanity: expected unrealized_pnl == -40,000.0")
            check(result.unrealized_pnl == expected, f"unrealized_pnl negative == {expected} (got {result.unrealized_pnl})")
            check(result.unrealized_pnl < 0, "unrealized_pnl is indeed negative")
        finally:
            db.disconnect()


# ---------------------------------------------------------------------------
# PROOF 3: restart -- Position state tetap, market di-fetch ulang,
# unrealized dihitung ulang (dengan harga baru, seolah harga sudah
# berubah lagi setelah restart).
# ---------------------------------------------------------------------------
def proof_3_restart_refetches_price_recomputes_unrealized():
    print("\n[PROOF 3] Restart: state Position tetap, market di-fetch ulang, unrealized dihitung ulang")
    with tempfile.TemporaryDirectory() as tmp:
        db_path, db, position_manager, position_repo, _ = _build(tmp)
        position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
        before_restart = position_repo.get_open_position("paper-id", "BBCA")

        engine_before = UnrealizedPnLEngine(_FixedPriceTool(9700.0))
        result_before = engine_before.calculate(before_restart)
        check(result_before.unrealized_pnl == (9700.0 - 9500.0) * 100.0, "unrealized_pnl before restart correct")

        db.disconnect()

        # Reopen a brand-new connection/DatabaseManager/PositionRepository,
        # exactly like a fresh process start would.
        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg2)
            position_repo2 = PositionRepository(manager2)

            after_restart = position_repo2.get_open_position("paper-id", "BBCA")
            check(after_restart is not None, "Position still exists after restart")
            check(after_restart.quantity == before_restart.quantity, "quantity unchanged after restart")
            check(after_restart.average_price == before_restart.average_price, "average_price unchanged after restart")
            check(after_restart.realized_pnl == before_restart.realized_pnl, "realized_pnl unchanged after restart")

            # Market has moved since the "restart" -- a brand-new engine
            # instance with a brand-new price-tool must be used (nothing
            # about market price is cached/persisted, per the STEP 3
            # audit), and the result must reflect the NEW price, proving
            # the price really was fetched again rather than reused from
            # anywhere.
            engine_after = UnrealizedPnLEngine(_FixedPriceTool(9200.0))
            result_after = engine_after.calculate(after_restart)
            expected_after = (9200.0 - 9500.0) * 100.0
            check(
                result_after.unrealized_pnl == expected_after,
                f"unrealized_pnl after restart reflects the freshly re-fetched price (expected {expected_after}, got {result_after.unrealized_pnl})",
            )
            check(
                result_after.unrealized_pnl != result_before.unrealized_pnl,
                "unrealized_pnl after restart differs from before restart (proves it was recomputed, not reused)",
            )
        finally:
            db2.disconnect()


# ---------------------------------------------------------------------------
# PROOF 4: menghitung unrealized tidak menyentuh database sama sekali --
# row Position/Trade/Account identik sebelum dan sesudah.
# ---------------------------------------------------------------------------
def proof_4_no_database_writes():
    print("\n[PROOF 4] Menghitung unrealized_pnl tidak menulis apa pun ke database")
    with tempfile.TemporaryDirectory() as tmp:
        db_path, db, position_manager, position_repo, account_repo = _build(tmp)
        try:
            position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
            position = position_repo.get_open_position("paper-id", "BBCA")
        finally:
            db.disconnect()

        # Note: 'trades' table isn't migrated in this proof's minimal
        # schema (ACCOUNTS_MIGRATIONS + POSITIONS_MIGRATIONS only,
        # exactly like Tests/test_position_manager.py) -- Trade rows
        # here are the standalone Trade objects fed directly into
        # PositionManager.apply_trade(), never persisted by a
        # TradeRepository in this scope. Positions and accounts ARE
        # persisted, so those are the two tables this proof checks
        # byte-for-byte before/after, matching what the roadmap asks
        # for ("row Position identik", "row Account identik").
        positions_before = _raw_rows(db_path, "positions")
        accounts_before = _raw_rows(db_path, "accounts")

        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg2)
            position_repo2 = PositionRepository(manager2)
            fresh_position = position_repo2.get_open_position("paper-id", "BBCA")

            engine = UnrealizedPnLEngine(_FixedPriceTool(9999.0))
            for _ in range(5):
                engine.calculate(fresh_position)
        finally:
            db2.disconnect()

        positions_after = _raw_rows(db_path, "positions")
        accounts_after = _raw_rows(db_path, "accounts")

        check(positions_before == positions_after, "positions table byte-for-byte identical before/after calculating unrealized_pnl (5x)")
        check(accounts_before == accounts_after, "accounts table byte-for-byte identical before/after calculating unrealized_pnl (5x)")
        check(len(positions_before) == 1, "sanity: exactly one position row exists")


# ---------------------------------------------------------------------------
# SANITY: no valid price -> ValidationError, never a fabricated result;
# and average_price/quantity are read verbatim, never recomputed.
# ---------------------------------------------------------------------------
def sanity_missing_price_rejected_and_average_price_untouched():
    print("\n[SANITY] Missing market price is rejected; average_price/quantity never recomputed")
    with tempfile.TemporaryDirectory() as tmp:
        _, db, position_manager, position_repo, _ = _build(tmp)
        try:
            position_manager.apply_trade(_trade(1, action="BUY", quantity=100.0, fill_price=9500.0))
            position_manager.apply_trade(_trade(2, action="BUY", quantity=100.0, fill_price=9700.0))
            position = position_repo.get_open_position("paper-id", "BBCA")
            expected_avg = (100.0 * 9500.0 + 100.0 * 9700.0) / 200.0
            check(position.average_price == expected_avg, "sanity: weighted average already correct going in")

            engine = UnrealizedPnLEngine(_FixedPriceTool(None))
            raised = False
            try:
                engine.calculate(position)
            except ValidationError:
                raised = True
            check(raised, "ValidationError raised when no valid market price is available")

            good_engine = UnrealizedPnLEngine(_FixedPriceTool(10_000.0))
            result = good_engine.calculate(position)
            check(result.average_price == expected_avg, "average_price used by the engine == Position's own weighted average, never recomputed")
        finally:
            db.disconnect()


def main() -> int:
    proof_1_market_up_positive_unrealized()
    proof_2_market_down_negative_unrealized()
    proof_3_restart_refetches_price_recomputes_unrealized()
    proof_4_no_database_writes()
    sanity_missing_price_rejected_and_average_price_untouched()

    print("\n" + "=" * 70)
    print(f"ACTIVATION 3.7 STEP 4 PROOF RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())