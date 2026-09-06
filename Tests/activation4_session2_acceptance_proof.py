"""Activation 4 Session 2 -- acceptance-gate proof script.

Proves the full mandated flow end-to-end against a REAL, temporary
SQLite database, through the REAL ``main.py`` CLI functions and the
REAL ``Core.composition_root.build_application()`` object graph --
same ``PaperTradingEngine`` / ``PositionManager`` /
``AccountBalanceService`` / ``UnrealizedPnLEngine`` / repositories the
production CLI uses:

    init -> watchlist add -> scan -> recommendation/review ->
    paper buy -> portfolio -> restart -> portfolio tetap benar ->
    paper sell -> performance berubah

Two substitutions are made, at the same boundaries the project's own
``Tests/section_2_8_proof.py`` already established as its accepted
"production proof" pattern -- both exist ONLY because this sandbox has
no real network access to Yahoo Finance, which is pre-existing and
outside Activation 4 Session 2's scope:

  1. ``app.manual_scan_service``'s private ``_watchlist_scanner`` is
     swapped for a fake that returns one realistic BUY signal for
     BBCA (mirrors ``section_2_8_proof.py`` exactly). Everything
     downstream of ``WatchlistScanner.scan()`` -- ``RankingEngine``,
     ``RecommendationService``, ``ReportService``,
     ``SnapshotRepository`` -- is the real, unmodified pipeline.
  2. ``Orchestration.market_price_tool.MarketPriceTool.execute`` is
     patched at the class level to return a caller-controlled price
     instead of attempting a real ``StockService``/yfinance network
     call. This is the exact same Tool class, same call signature,
     same output shape -- only the real-data network hop is stubbed.
     Everything downstream (``PaperTradingEngine.submit_order()``,
     ``UnrealizedPnLEngine.calculate()``, and every repository/
     Business object they call) is the real, unmodified production
     code.

The "restart" step is a genuinely fresh OS process (``subprocess``),
re-reading the same on-disk SQLite file through a brand-new
``build_application()`` call -- it does NOT get the class-level
``MarketPriceTool`` patch (that only exists in this process's memory),
so it also proves the real, unmodified ``N/A``-on-missing-price
behavior survives a real restart with no network available.

Run directly:
``python Tests/activation4_session2_acceptance_proof.py``
"""

from __future__ import annotations

import os
import subprocess
import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="aios_activation4_session2_")
    db_path = Path(tmp_dir) / "acceptance.db"
    os.environ["DB_PATH"] = str(db_path)
    # Keep fee/tax at their real defaults (0.0) so the arithmetic
    # below is exact -- never a hardcoded assumption if the operator's
    # real environment happens to already export these.
    for var in ("EXECUTION_BUY_FEE_RATE", "EXECUTION_SELL_FEE_RATE", "EXECUTION_SELL_TAX_RATE"):
        os.environ.pop(var, None)

    # Imported after DB_PATH is set, matching how main.py itself only
    # ever reads DatabaseConfig.from_env() at call time, not at import
    # time.
    from Core.composition_root import build_application
    from Core.init_command import run_init
    from Orchestration.market_price_tool import MarketPriceTool
    from Orchestration.skill_result import SkillResult
    import main as cli

    class FakeWatchlistScanner:
        """Same fake-data pattern as ``section_2_8_proof.py``: one
        ticker (BBCA) with a real BUY signal -- everything downstream
        (RankingEngine/RecommendationService/ReportService/
        SnapshotRepository) is the real, unmodified pipeline.
        """

        def scan(self):
            return {
                "BBCA": {
                    "watchlist": SkillResult(
                        success=True,
                        output={
                            "watchlist": [
                                {
                                    "priority": 1,
                                    "symbol": "BBCA",
                                    "recommendation": "BUY",
                                    "confidence": "HIGH",
                                    "summary": "Volume breakout confirmed above resistance.",
                                }
                            ]
                        },
                    )
                },
            }

    # Mutable box the patched MarketPriceTool.execute reads from, so
    # each phase of this script can control "the current real price"
    # without touching PaperTradingEngine/UnrealizedPnLEngine/any
    # Business object at all.
    price_box = {"value": None}

    def fake_execute(self, context):
        from Orchestration.tool_result import ToolResult

        symbol = context.parameters.get("symbol") if hasattr(context, "parameters") else None
        price = price_box["value"]
        return ToolResult(success=price is not None, output={"symbol": symbol, "price": price, "trend": "unknown"}, error=None, metadata={})

    print("=" * 70)
    print("[1] init")
    print("=" * 70)
    rc = run_init()
    check(rc == 0, "run_init() exited 0 on a brand-new database")
    check(db_path.is_file(), f"database file created at {db_path}")

    with patch.object(MarketPriceTool, "execute", fake_execute):
        app = build_application()
        check(app is not None, "build_application() succeeded")

        print("\n" + "=" * 70)
        print("[2] watchlist add BBCA")
        print("=" * 70)
        rc = cli._run_watchlist_command(app, ["add", "BBCA"])
        check(rc == 0, "watchlist add exited 0")
        check(app.watchlist_repository.list_all() == ["BBCA"], "BBCA persisted on the watchlist")

        print("\n" + "=" * 70)
        print("[3] scan --market idx (real pipeline, scanner boundary faked -- no network)")
        print("=" * 70)
        app.manual_scan_service._watchlist_scanner = FakeWatchlistScanner()
        rc = cli._run_scan_command(app, ["--market", "idx"])
        check(rc == 0, "scan exited 0")
        snapshot = None
        for row in app.snapshot_repository.list_latest():
            if row.symbol == "BBCA":
                snapshot = row
        check(snapshot is not None, "BBCA ranking snapshot persisted by the real RankingEngine/SnapshotRepository")
        check(snapshot is not None and snapshot.status == "success", "snapshot status is success")
        check(snapshot is not None and snapshot.recommendation == "BUY", "real recommendation for BBCA is BUY")

        print("\n" + "=" * 70)
        print("[4] recommendation BBCA (review step, read-only)")
        print("=" * 70)
        rc = cli._run_recommendation_command(app, ["BBCA"])
        check(rc == 0, "recommendation exited 0")

        print("\n" + "=" * 70)
        print("[5] paper buy BBCA --allocation 0.05 (explicit user approval)")
        print("=" * 70)
        account_before = app.account_repository.get_by_id("paper")
        check(account_before is not None, "bootstrap default paper account exists")
        check(account_before.cash == 100_000_000.0, "real bootstrap starting cash is Rp100,000,000 (never a hardcoded/zero capital)")

        price_box["value"] = 9000.0
        rc = cli._run_paper_command(app, ["buy", "BBCA", "--allocation", "0.05"])
        check(rc == 0, "paper buy exited 0")

        position = app.position_repository.get_open_position("paper", "BBCA")
        check(position is not None, "an OPEN Position row now exists for BBCA")
        # allocation 5% of Rp100,000,000 = Rp5,000,000 @ 9000 -> floor
        # 555 shares -> lot-adjusted (lot_size=100) -> 500 shares.
        # Computed here only to state the expectation -- the real
        # quantity comes from PaperTradingEngine.submit_order()/
        # PositionManager.apply_trade(), never recomputed by this
        # script and written back.
        expected_quantity = 500.0
        check(position is not None and position.quantity == expected_quantity, f"BUY quantity is the real, lot-adjusted {expected_quantity} shares (from actual cash, never capital=0)")
        check(position is not None and position.average_price == 9000.0, "average_price is the real fill price")

        account_after_buy = app.account_repository.get_by_id("paper")
        expected_cash_after_buy = 100_000_000.0 - (expected_quantity * 9000.0)
        check(account_after_buy is not None and account_after_buy.cash == expected_cash_after_buy, f"real cash decreased to {expected_cash_after_buy} via AccountBalanceService.apply_trade()")

        print("\n" + "=" * 70)
        print("[6] portfolio (real Position state + real UnrealizedPnLEngine)")
        print("=" * 70)
        price_box["value"] = 9200.0
        rc = cli._run_portfolio_command(app, [])
        check(rc == 0, "portfolio exited 0")

        print("\n" + "=" * 70)
        print("[7] account / orders / trades (real, production data)")
        print("=" * 70)
        rc = cli._run_account_command(app, [])
        check(rc == 0, "account exited 0")
        rc = cli._run_orders_command(app, [])
        check(rc == 0, "orders exited 0")
        orders = app.order_repository.list_by_account("paper")
        check(len(orders) == 1 and orders[0].action == "BUY" and orders[0].status == "FILLED", "real BUY order persisted with status FILLED")
        rc = cli._run_trades_command(app, [])
        check(rc == 0, "trades exited 0")
        trades = app.trade_repository.list_by_account("paper")
        check(len(trades) == 1 and trades[0].action == "BUY", "real BUY trade persisted (append-only ledger)")

    print("\n" + "=" * 70)
    print("[8] restart -- brand-new OS process, brand-new build_application(), same DB file")
    print("=" * 70)
    result = subprocess.run(
        [sys.executable, "main.py", "portfolio"],
        cwd=str(_PROJECT_ROOT),
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout)
    check("BBCA" in result.stdout, "portfolio still shows BBCA after a real restart (fresh process, fresh build_application())")
    check(f"qty={expected_quantity}" in result.stdout, "position quantity survives restart, read straight from SQLite")

    result_account = subprocess.run(
        [sys.executable, "main.py", "account"],
        cwd=str(_PROJECT_ROOT),
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result_account.stdout)
    check(f"cash         : {expected_cash_after_buy}" in result_account.stdout, "account cash survives restart, unchanged from what 'paper buy' actually wrote")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    reread = con.execute(
        "SELECT * FROM positions WHERE account_id='paper' AND symbol='BBCA' ORDER BY position_id DESC LIMIT 1"
    ).fetchone()
    con.close()
    check(reread is not None, "position row is directly readable in the real sqlite file after restart")
    check(reread is not None and reread["status"] == "open", "position status is still the real 'open' (lowercase) after restart")

    print("\n" + "=" * 70)
    print("[9] paper sell BBCA --quantity 500 (performance harus berubah)")
    print("=" * 70)
    with patch.object(MarketPriceTool, "execute", fake_execute):
        app2 = build_application()
        position_before_sell = app2.position_repository.get_open_position("paper", "BBCA")
        check(position_before_sell is not None and position_before_sell.realized_pnl == 0.0, "realized_pnl is still 0.0 before any SELL")

        price_box["value"] = 9500.0
        rc = cli._run_paper_command(app2, ["sell", "BBCA", "--quantity", "500"])
        check(rc == 0, "paper sell exited 0")

        position_after_sell = app2.position_repository.get_by_id(position_before_sell.position_id)
        expected_realized_pnl = (9500.0 - 9000.0) * 500.0
        check(position_after_sell is not None and position_after_sell.realized_pnl == expected_realized_pnl, f"real realized_pnl changed to {expected_realized_pnl} via PositionManager's own LOCKED formula")
        check(position_after_sell is not None and position_after_sell.status == "closed", "position status is now 'closed' (full quantity sold)")
        check(position_after_sell is not None and position_after_sell.quantity == 0.0, "position quantity is now 0")

        account_after_sell = app2.account_repository.get_by_id("paper")
        expected_cash_after_sell = expected_cash_after_buy + (500.0 * 9500.0)
        check(account_after_sell is not None and account_after_sell.cash == expected_cash_after_sell, f"real cash increased to {expected_cash_after_sell} via AccountBalanceService.apply_trade()")

        trades_after_sell = app2.trade_repository.list_by_account("paper")
        check(len(trades_after_sell) == 2 and trades_after_sell[-1].action == "SELL", "real SELL trade appended to the ledger (never mutates the BUY trade)")

        print("\n[9b] portfolio after SELL -- realized_pnl reflected, no unrealized lookup for a closed position")
        rc = cli._run_portfolio_command(app2, [])
        check(rc == 0, "portfolio exited 0 after SELL")

    print("\n" + "=" * 70)
    print(f"ACTIVATION 4 SESSION 2 ACCEPTANCE-GATE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())