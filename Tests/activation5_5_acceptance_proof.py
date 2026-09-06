"""Activation 5.5 -- acceptance-gate proof script.

Proves the full mandated flow end-to-end against a REAL, temporary
SQLite database, through the REAL ``Core.composition_root.
build_application()`` object graph:

    real DB -> real repositories -> PerformanceSummaryService
    -> real performance summary

Same substitution boundary Activation 4 Session 2's
``activation4_session2_acceptance_proof.py`` already established as
the project's accepted "production proof" pattern (this sandbox has
no real network access to Yahoo Finance):
``Orchestration.market_price_tool.MarketPriceTool.execute`` is
patched at the class level to return a caller-controlled price.
Everything downstream -- ``PaperTradingEngine``, ``PositionManager``,
``AccountBalanceService``, ``UnrealizedPnLEngine``,
``PortfolioSnapshotService``, ``PerformanceSummaryService``,
``PerformanceSummaryProductionService``, and every repository they
call -- is the real, unmodified production code.

Run directly:
``python Tests/activation5_5_acceptance_proof.py``
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
    tmp_dir = tempfile.mkdtemp(prefix="aios_activation5_5_")
    db_path = Path(tmp_dir) / "acceptance.db"
    os.environ["DB_PATH"] = str(db_path)
    for var in ("EXECUTION_BUY_FEE_RATE", "EXECUTION_SELL_FEE_RATE", "EXECUTION_SELL_TAX_RATE"):
        os.environ.pop(var, None)

    from Core.composition_root import build_application
    from Core.init_command import run_init
    from Database.migration_cli_helper import apply_domain_migrations
    from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS
    from Orchestration.market_price_tool import MarketPriceTool
    from Orchestration.skill_result import SkillResult
    import main as cli

    class FakeWatchlistScanner:
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

    price_box = {"value": None}

    def fake_execute(self, context):
        from Orchestration.tool_result import ToolResult

        symbol = context.parameters.get("symbol") if hasattr(context, "parameters") else None
        price = price_box["value"]
        return ToolResult(success=price is not None, output={"symbol": symbol, "price": price, "trend": "unknown"}, error=None, metadata={})

    print("=" * 70)
    print("[1] init (+ portfolio_snapshots migration -- separate, manual, LOCKED-documented step)")
    print("=" * 70)
    rc = run_init()
    check(rc == 0, "run_init() exited 0 on a brand-new database")
    check(db_path.is_file(), f"database file created at {db_path}")
    rc2 = apply_domain_migrations(PORTFOLIO_SNAPSHOTS_MIGRATIONS, "portfolio snapshot")
    check(rc2 == 0, "portfolio_snapshots migration applied (not part of main.py init's canonical registry)")

    with patch.object(MarketPriceTool, "execute", fake_execute):
        app = build_application()
        check(app is not None, "build_application() succeeded")
        check(hasattr(app, "performance_summary_production_service"), "ApplicationGraph exposes performance_summary_production_service")
        check(hasattr(app, "portfolio_snapshot_service"), "ApplicationGraph exposes portfolio_snapshot_service")
        check(hasattr(app, "performance_summary_service"), "ApplicationGraph exposes performance_summary_service")

        print("\n" + "=" * 70)
        print("[2] empty-account path (account exists, zero trades/positions/snapshots)")
        print("=" * 70)
        summary_empty = app.performance_summary_production_service.get_performance_summary("paper")
        check(summary_empty.trade_statistics.total_trades == 0, "trade_statistics.total_trades is 0 for a real, empty account (never fabricated)")
        check(summary_empty.maximum_drawdown.maximum_drawdown == 0.0, "maximum_drawdown is 0.0 for an empty equity curve, straight off MaximumDrawdownEngine's own documented contract")

        print("\n" + "=" * 70)
        print("[3] watchlist add BBCA + scan (real pipeline, scanner boundary faked -- no network)")
        print("=" * 70)
        rc = cli._run_watchlist_command(app, ["add", "BBCA"])
        check(rc == 0, "watchlist add exited 0")
        app.manual_scan_service._watchlist_scanner = FakeWatchlistScanner()
        rc = cli._run_scan_command(app, ["--market", "idx"])
        check(rc == 0, "scan exited 0")

        print("\n" + "=" * 70)
        print("[4] snapshot #1 (pre-trade equity)")
        print("=" * 70)
        price_box["value"] = 9000.0
        snap1 = app.portfolio_snapshot_service.take_snapshot("paper")
        check(snap1.equity == 100_000_000.0, "pre-trade snapshot equity is the real, untouched starting cash")

        print("\n" + "=" * 70)
        print("[5] paper buy BBCA --allocation 0.05")
        print("=" * 70)
        rc = cli._run_paper_command(app, ["buy", "BBCA", "--allocation", "0.05"])
        check(rc == 0, "paper buy exited 0")
        position = app.position_repository.get_open_position("paper", "BBCA")
        expected_quantity = 500.0
        check(position is not None and position.quantity == expected_quantity, f"BUY quantity is the real, lot-adjusted {expected_quantity} shares")
        check(position is not None and position.average_price == 9000.0, "average_price is the real fill price")

        print("\n" + "=" * 70)
        print("[6] snapshot #2 (post-buy, price moved to 9200)")
        print("=" * 70)
        price_box["value"] = 9200.0
        snap2 = app.portfolio_snapshot_service.take_snapshot("paper")
        check(snap2.unrealized_pnl == (9200.0 - 9000.0) * 500.0, "post-buy snapshot unrealized_pnl comes from the real, LOCKED UnrealizedPnLEngine")

        print("\n" + "=" * 70)
        print("[7] paper sell BBCA --quantity 500 (performance harus berubah)")
        print("=" * 70)
        price_box["value"] = 9500.0
        rc = cli._run_paper_command(app, ["sell", "BBCA", "--quantity", "500"])
        check(rc == 0, "paper sell exited 0")
        position_after_sell = app.position_repository.get_by_id(position.position_id)
        expected_realized_pnl = (9500.0 - 9000.0) * 500.0
        check(position_after_sell is not None and position_after_sell.realized_pnl == expected_realized_pnl, f"real realized_pnl is {expected_realized_pnl} via PositionManager's own LOCKED formula")
        check(position_after_sell is not None and position_after_sell.status == "closed", "position status is now 'closed'")

        print("\n" + "=" * 70)
        print("[8] snapshot #3 (post-sell)")
        print("=" * 70)
        snap3 = app.portfolio_snapshot_service.take_snapshot("paper")
        check(snap3.realized_pnl == expected_realized_pnl, "post-sell snapshot realized_pnl matches the real Position.realized_pnl")

        print("\n" + "=" * 70)
        print("[9] real performance summary: real DB -> real repositories -> PerformanceSummaryService")
        print("=" * 70)
        summary = app.performance_summary_production_service.get_performance_summary("paper")

        trades = app.trade_repository.list_by_account("paper")
        positions = app.position_repository.list_by_account("paper")
        equity_curve_points = app.portfolio_snapshot_service.get_equity_curve("paper")
        check(len(trades) == 2, "real ledger has exactly BUY + SELL")
        check(len(positions) == 1, "real ledger has exactly one Position row")
        check(
            len(equity_curve_points) == 5,
            "equity curve carries the 3 manually-taken snapshots plus 2 automatic "
            "snapshots now captured by Activation 7 FIX's post-trade CLI wiring "
            "(blocker 2: PortfolioSnapshotService.take_snapshot() now also runs "
            "right after 'paper buy'/'paper sell' commit, in addition to this "
            "test's own manual snapshots)",
        )
        check(
            [p.equity for p in equity_curve_points] == [snap1.equity, snap1.equity, snap2.equity, snap3.equity, snap3.equity],
            "equity curve is verbatim, chronological PortfolioSnapshot.equity -- never fabricated "
            "(the 2 new automatic snapshots equal the adjacent manual snapshot's equity exactly, "
            "since no price change or further trade occurs between them)",
        )

        # Cross-check: call the same LOCKED engines directly on the same
        # real data and confirm PerformanceSummaryProductionService's
        # result is bit-for-bit identical -- proves no transformation,
        # no second formula, no drift from the production path.
        from Business.trade_statistics_engine import TradeStatisticsEngine
        from Business.position_performance_engine import PositionPerformanceEngine
        from Business.win_rate_engine import WinRateEngine
        from Business.expectancy_engine import ExpectancyEngine
        from Business.profit_factor_engine import ProfitFactorEngine
        from Business.maximum_drawdown_engine import MaximumDrawdownEngine

        expected_trade_stats = TradeStatisticsEngine().calculate(trades)
        expected_position_stats = PositionPerformanceEngine().calculate(positions)
        expected_win_rate = WinRateEngine().calculate(expected_position_stats)
        expected_expectancy = ExpectancyEngine().calculate(expected_position_stats)
        expected_profit_factor = ProfitFactorEngine().calculate(expected_position_stats)
        expected_drawdown = MaximumDrawdownEngine().calculate([p.equity for p in equity_curve_points])

        check(summary.trade_statistics == expected_trade_stats, "trade_statistics is bit-for-bit identical to a fresh, independent TradeStatisticsEngine.calculate(trades) call")
        check(summary.position_statistics == expected_position_stats, "position_statistics is bit-for-bit identical to a fresh, independent PositionPerformanceEngine.calculate(positions) call")
        check(summary.win_rate == expected_win_rate, "win_rate is bit-for-bit identical to a fresh WinRateEngine call")
        check(summary.expectancy == expected_expectancy, "expectancy is bit-for-bit identical to a fresh ExpectancyEngine call")
        check(summary.profit_factor == expected_profit_factor, "profit_factor is bit-for-bit identical to a fresh ProfitFactorEngine call")
        check(summary.maximum_drawdown == expected_drawdown, "maximum_drawdown is bit-for-bit identical to a fresh MaximumDrawdownEngine call over the real equity curve")
        check(summary.trade_statistics.total_trades == 2, "real trade_statistics.total_trades is 2 (BUY + SELL)")
        check(
            summary.position_statistics.winning_positions
            + summary.position_statistics.losing_positions
            + summary.position_statistics.breakeven_positions
            == 1,
            "real position_statistics covers exactly 1 closed position (won since realized_pnl=250000.0 > 0)",
        )
        check(summary.position_statistics.winning_positions == 1, "the one real closed position is correctly classified winning (realized_pnl=250000.0)")

        print("\n" + "=" * 70)
        print("[10] account isolation -- a second, independent account")
        print("=" * 70)
        app.account_repository.create(
            account_id="paper-2",
            account_name="paper-2",
            mode="paper",
            currency="IDR",
            asset_class="stock_id",
            cash=100_000_000.0,
            equity=100_000_000.0,
            buying_power=100_000_000.0,
        )
        summary_other = app.performance_summary_production_service.get_performance_summary("paper-2")
        check(summary_other.trade_statistics.total_trades == 0, "second account's summary shows ZERO trades -- 'paper' account's BUY/SELL never leak across account_id")
        check(
            summary_other.position_statistics.winning_positions
            + summary_other.position_statistics.losing_positions
            + summary_other.position_statistics.breakeven_positions
            == 0,
            "second account's summary shows ZERO positions -- 'paper' account's closed position never leaks across account_id",
        )

        print("\n" + "=" * 70)
        print("[11] error path -- unknown account_id")
        print("=" * 70)
        from Core.exceptions import ValidationError
        raised = False
        try:
            app.performance_summary_production_service.get_performance_summary("does-not-exist")
        except ValidationError:
            raised = True
        check(raised, "ValidationError propagates unchanged for an unknown account_id -- never a fabricated empty summary")

        print("\n" + "=" * 70)
        print("[12] read-only proof -- row counts unchanged by get_performance_summary()")
        print("=" * 70)
        con = sqlite3.connect(db_path)
        counts_before = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("trades", "positions", "orders", "portfolio_snapshots", "accounts")
        }
        con.close()
        for _ in range(3):
            app.performance_summary_production_service.get_performance_summary("paper")
        con = sqlite3.connect(db_path)
        counts_after = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("trades", "positions", "orders", "portfolio_snapshots", "accounts")
        }
        con.close()
        check(counts_before == counts_after, f"row counts unchanged after 3 repeated calls: {counts_before} == {counts_after}")

    print("\n" + "=" * 70)
    print("[13] restart persistence -- brand-new OS process, brand-new build_application(), same DB file")
    print("=" * 70)
    proof_snippet = (
        "import sys\n"
        "sys.path.insert(0, '.')\n"
        "from unittest.mock import patch\n"
        "from Orchestration.market_price_tool import MarketPriceTool\n"
        "from Orchestration.tool_result import ToolResult\n"
        "def fake_execute(self, context):\n"
        "    return ToolResult(success=True, output={'symbol': 'BBCA', 'price': 9500.0, 'trend': 'unknown'}, error=None, metadata={})\n"
        "patcher = patch.object(MarketPriceTool, 'execute', fake_execute)\n"
        "patcher.start()\n"
        "from Core.composition_root import build_application\n"
        "app2 = build_application()\n"
        "s = app2.performance_summary_production_service.get_performance_summary('paper')\n"
        "print('RESTART_TOTAL_TRADES=' + str(s.trade_statistics.total_trades))\n"
        "print('RESTART_NET_PROFIT=' + str(s.position_statistics.net_profit))\n"
    )
    restart_script_path = Path(tmp_dir) / "restart_probe.py"
    restart_script_path.write_text(proof_snippet)
    result = subprocess.run(
        [sys.executable, str(restart_script_path)],
        cwd=str(_PROJECT_ROOT),
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout)
    print(result.stderr[-2000:] if result.stderr else "")
    check("RESTART_TOTAL_TRADES=2" in result.stdout, "a brand-new process, brand-new build_application(), sees the same 2 real trades after restart")
    check("RESTART_NET_PROFIT=250000.0" in result.stdout, "the same real net_profit (250000.0) survives a real restart, read straight from SQLite")

    print("\n" + "=" * 70)
    print(f"ACTIVATION 5.5 ACCEPTANCE-GATE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())