"""Independent behavior proof for Activation 3.2 -- written by the auditor,
NOT copied from the vendor's own Tests/test_paper_trading_engine.py.

Dumps real before/after SQLite state (raw SQL, not repository objects) so
the evidence is not filtered through the same code being audited.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "extracted"
sys.path.insert(0, str(_ROOT))

from Business.execution_service import ExecutionService
from Business.order_lifecycle_service import OrderLifecycleService
from Business.paper_trading_engine import PaperTradingEngine, PRETRADE_REASON_RISK_LIMIT_EXCEEDED
from Core.exceptions import ValidationError
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.migrations import MigrationRunner
from Database.migration_registry import all_migrations
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_idempotency_repository import OrderIdempotencyRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.trade_repository import TradeRepository


def dump(db_path: Path, label: str) -> dict:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    out = {}
    for table in ("accounts", "orders", "trades", "positions", "order_idempotency_keys", "schema_migrations"):
        try:
            rows = con.execute(f"SELECT * FROM {table}").fetchall()
            out[table] = [dict(r) for r in rows]
        except sqlite3.OperationalError as exc:
            out[table] = f"<error: {exc}>"
    con.close()
    print(f"\n----- RAW SQL STATE: {label} -----")
    for table, rows in out.items():
        print(f"  {table}: {rows}")
    return out


def build_graph(db_path: Path):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    for migration, _domain in all_migrations():
        MigrationRunner(db).apply([migration])
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idem_repo = OrderIdempotencyRepository(manager)
    ols = OrderLifecycleService(order_repo)
    execs = ExecutionService(order_repo, trade_repo)
    return db, manager, account_repo, position_repo, order_repo, trade_repo, idem_repo, ols, execs


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="a32_proof_"))
    db_path = tmp / "aios.db"
    print(f"Working DB: {db_path}")

    # ---------------------------------------------------------------
    # PROOF 1: fresh init via the canonical migration registry (proves
    # migration v12 is safe on a from-scratch init).
    # ---------------------------------------------------------------
    print("\n=== PROOF 1: migration v12 on fresh init ===")
    db, manager, account_repo, position_repo, order_repo, trade_repo, idem_repo, ols, execs = build_graph(db_path)
    applied = MigrationRunner(db).applied_versions()
    print(f"applied_versions() after fresh init: {sorted(applied)}")
    assert 12 in applied, "migration 12 missing after fresh init"
    dump(db_path, "after fresh init (before any account/order)")

    account_repo.create(
        account_id="acc-1", account_name="Proof Account", mode="paper",
        currency="IDR", asset_class="stock_id", cash=10_000_000.0,
        equity=10_000_000.0, buying_power=10_000_000.0,
    )

    engine = PaperTradingEngine(
        order_lifecycle_service=ols, execution_service=execs,
        account_repository=account_repo, position_repository=position_repo,
        order_idempotency_repository=idem_repo,
        kill_switch_engaged=False, max_order_value=1_000_000_000.0,
    )

    # ---------------------------------------------------------------
    # PROOF 2: failure path -- insufficient cash gate -- zero write,
    # verified via raw SQL (not repository objects).
    # ---------------------------------------------------------------
    print("\n=== PROOF 2: failure path (insufficient cash) -- zero write, verified via raw SQL ===")
    before = dump(db_path, "BEFORE cash-insufficient submit_order()")
    try:
        engine.submit_order(
            account_id="acc-1", symbol="BBCA", action="BUY", quantity=2000.0,
            requested_price=9500.0,  # 2000*9500 = 19,000,000 > 10,000,000 cash
            executed_at="2026-08-04T00:00:00+00:00",
            signal_evidence={"note": "test"}, user_approval=True,
            idempotency_key="proof-cash-1",
        )
        print("UNEXPECTED: no exception raised")
        return 1
    except ValidationError as exc:
        reason = exc.details.get("reason")
        print(f"Raised ValidationError as expected, reason={reason}")
        assert reason == "INSUFFICIENT_CASH", f"expected INSUFFICIENT_CASH, got {reason}"

    after = dump(db_path, "AFTER cash-insufficient submit_order()")
    assert before == after, "STATE CHANGED after a rejected pre-trade gate -- PARTIAL WRITE DETECTED"
    print("CONFIRMED: raw SQL state byte-identical before/after failed gate (zero write).")

    # Now trigger the actual risk-limit gate specifically (engine built with
    # a high default ceiling above; rebuild with a low one to hit gate 11
    # deliberately and prove *that* gate specifically zero-writes).
    engine_low_limit = PaperTradingEngine(
        order_lifecycle_service=ols, execution_service=execs,
        account_repository=account_repo, position_repository=position_repo,
        order_idempotency_repository=idem_repo,
        kill_switch_engaged=False, max_order_value=500_000.0,
    )
    before2 = dump(db_path, "BEFORE gate-11 (risk limit) specific breach")
    try:
        engine_low_limit.submit_order(
            account_id="acc-1", symbol="BBCA", action="BUY", quantity=100.0,
            requested_price=9500.0,  # 950,000 > 500,000 ceiling
            executed_at="2026-08-04T00:00:00+00:00",
            signal_evidence={"note": "test"}, user_approval=True,
            idempotency_key="proof-risk-2",
        )
        print("UNEXPECTED: no exception raised for gate 11")
        return 1
    except ValidationError as exc:
        reason = exc.details.get("reason")
        print(f"Gate 11 fired as expected, reason={reason}")
        assert reason == PRETRADE_REASON_RISK_LIMIT_EXCEEDED
    after2 = dump(db_path, "AFTER gate-11 (risk limit) specific breach")
    assert before2 == after2, "STATE CHANGED after risk-limit gate -- PARTIAL WRITE DETECTED"
    print("CONFIRMED: gate 11 (risk limit) is genuinely zero-write.")

    # ---------------------------------------------------------------
    # PROOF 3: success path -- before/after, and what DOES vs does NOT
    # change (Order+Trade written; Account.cash/Position NOT touched --
    # documented scope, verified independently here).
    # ---------------------------------------------------------------
    print("\n=== PROOF 3: success path -- before/after raw SQL ===")
    before3 = dump(db_path, "BEFORE successful submit_order()")
    trade = engine.submit_order(
        account_id="acc-1", symbol="BBCA", action="BUY", quantity=100.0,
        requested_price=9500.0,
        executed_at="2026-08-04T01:00:00+00:00",
        signal_evidence={"note": "test"}, user_approval=True,
        idempotency_key="proof-success-1",
    )
    after3 = dump(db_path, "AFTER successful submit_order()")
    print(f"\nTrade returned: order_id={trade.order_id} trade_id={trade.trade_id} fill_price={trade.fill_price}")

    orders_before, orders_after = before3["orders"], after3["orders"]
    trades_before, trades_after = before3["trades"], after3["trades"]
    accounts_before, accounts_after = before3["accounts"], after3["accounts"]
    idem_before, idem_after = before3["order_idempotency_keys"], after3["order_idempotency_keys"]

    assert len(orders_after) == len(orders_before) + 1, "expected exactly 1 new Order row"
    assert len(trades_after) == len(trades_before) + 1, "expected exactly 1 new Trade row"
    assert len(idem_after) == len(idem_before) + 1, "expected exactly 1 new idempotency-key row"
    assert orders_after[-1]["status"] == "FILLED", "Order should be FILLED after successful execution"
    assert trades_after[-1]["fill_price"] == 9500.0, "Trade.fill_price should equal requested_price (bug-fix verified)"
    print("CONFIRMED: exactly 1 Order (FILLED) + 1 Trade + 1 idempotency-key row written on success.")

    # Explicitly verify the documented (honest) gap: cash/position are NOT
    # touched by this Activation's success path.
    assert accounts_before == accounts_after, "Account.cash unexpectedly changed -- scope violation if true"
    print("CONFIRMED (documented gap, verified independently): Account.cash is UNCHANGED after a "
          "successful BUY -- Activation 3.2 does not call AccountBalanceService.apply_trade(). "
          "Cash/Position/Portfolio are still not updated by any production path.")

    # ---------------------------------------------------------------
    # PROOF 4: idempotency -- duplicate key rejected, zero additional
    # writes, exactly one Trade survives across two attempts.
    # ---------------------------------------------------------------
    print("\n=== PROOF 4: idempotency -- duplicate key ===")
    before4 = dump(db_path, "BEFORE duplicate submit_order() with same key")
    try:
        engine.submit_order(
            account_id="acc-1", symbol="BBCA", action="BUY", quantity=100.0,
            requested_price=9500.0,
            executed_at="2026-08-04T02:00:00+00:00",
            signal_evidence={"note": "test"}, user_approval=True,
            idempotency_key="proof-success-1",  # SAME key as Proof 3
        )
        print("UNEXPECTED: duplicate key was accepted")
        return 1
    except ValidationError as exc:
        print(f"Duplicate correctly rejected, reason={exc.details.get('reason')}")
    after4 = dump(db_path, "AFTER duplicate submit_order() attempt")
    assert before4 == after4, "duplicate request caused a write -- IDEMPOTENCY BROKEN"
    print("CONFIRMED: duplicate idempotency_key produces zero additional writes.")

    # ---------------------------------------------------------------
    # PROOF 5: restart -- close every connection, open a brand new one
    # against the same file, confirm state (independent of vendor test).
    # ---------------------------------------------------------------
    print("\n=== PROOF 5: restart persistence ===")
    db.disconnect()
    print("Connection closed (simulated process exit).")
    state_after_restart = dump(db_path, "AFTER simulated restart (new connection, same file)")
    assert len(state_after_restart["orders"]) == len(after4["orders"])
    assert len(state_after_restart["trades"]) == len(after4["trades"])
    assert state_after_restart["orders"][-1]["status"] == "FILLED"
    print("CONFIRMED: state intact after simulated restart (fresh connection, same DB file).")

    # ---------------------------------------------------------------
    # PROOF 6: migration re-run safety -- re-apply full migration set to
    # an ALREADY-migrated database; must be a no-op, no error, no dupes.
    # ---------------------------------------------------------------
    print("\n=== PROOF 6: migration re-run safety (idempotent re-apply) ===")
    db2 = SQLiteDatabase(DatabaseConfig(db_path=db_path))
    db2.connect()
    runner2 = MigrationRunner(db2)
    versions_before_rerun = sorted(runner2.applied_versions())
    records = runner2.apply([m for m, _d in all_migrations()])
    versions_after_rerun = sorted(runner2.applied_versions())
    print(f"versions before re-run: {versions_before_rerun}")
    print(f"newly-applied records on re-run: {records} (expect empty list)")
    print(f"versions after re-run:  {versions_after_rerun}")
    assert records == [], "re-running migrations against an already-migrated DB re-applied something"
    assert versions_before_rerun == versions_after_rerun, "version set changed on re-run"
    con = sqlite3.connect(str(db_path))
    dupe_check = con.execute(
        "SELECT version, COUNT(*) c FROM schema_migrations GROUP BY version HAVING c > 1"
    ).fetchall()
    con.close()
    assert dupe_check == [], f"duplicate schema_migrations rows found: {dupe_check}"
    print("CONFIRMED: re-running the full migration set against an already-migrated DB is a safe no-op.")
    db2.disconnect()

    print("\n" + "=" * 70)
    print("ALL INDEPENDENT PROOFS PASSED")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
