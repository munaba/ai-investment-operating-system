"""Activation 5.6 -- acceptance-gate proof script.

Proves the full mandated flow end-to-end against a REAL, temporary
SQLite database, through the REAL ``Core.composition_root.
build_application()`` object graph:

    real DB -> real repositories -> TradeAttributionService
    -> real per-trade TradeAttribution rows

Same substitution boundary Activation 5.5's own
``activation5_5_acceptance_proof.py`` already established as the
project's accepted "production proof" pattern (this sandbox has no
real network access to Yahoo Finance):
``Orchestration.market_price_tool.MarketPriceTool.execute`` is patched
at the class level to return a caller-controlled price. Everything
downstream -- ``PaperTradingEngine``, ``PositionManager``,
``OrderLifecycleService``, ``TradeHoldingPeriodEngine``,
``TradeAttributionEngine``, ``TradeAttributionService``, and every
repository they call -- is the real, unmodified production code.

Run directly:
``python Tests/activation5_6_acceptance_proof.py``
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
    tmp_dir = tempfile.mkdtemp(prefix="aios_activation5_6_")
    db_path = Path(tmp_dir) / "acceptance.db"
    os.environ["DB_PATH"] = str(db_path)
    for var in ("EXECUTION_BUY_FEE_RATE", "EXECUTION_SELL_FEE_RATE", "EXECUTION_SELL_TAX_RATE"):
        os.environ.pop(var, None)

    from Core.composition_root import build_application
    from Core.init_command import run_init
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
    print("[1] init")
    print("=" * 70)
    rc = run_init()
    check(rc == 0, "run_init() exited 0 on a brand-new database")
    check(db_path.is_file(), f"database file created at {db_path}")

    with patch.object(MarketPriceTool, "execute", fake_execute):
        app = build_application()
        check(app is not None, "build_application() succeeded")
        check(hasattr(app, "trade_attribution_service"), "ApplicationGraph exposes trade_attribution_service")
        check(hasattr(app, "trade_attribution_engine"), "ApplicationGraph exposes trade_attribution_engine")
        check(hasattr(app, "trade_holding_period_engine"), "ApplicationGraph exposes trade_holding_period_engine")

        print("\n" + "=" * 70)
        print("[2] empty-account path (account exists, zero trades)")
        print("=" * 70)
        empty_attribution = app.trade_attribution_service.get_attribution("paper")
        check(empty_attribution == [], "zero real trades produces an empty attribution list, never fabricated rows")

        print("\n" + "=" * 70)
        print("[3] watchlist add BBCA + scan (real pipeline, scanner boundary faked -- no network)")
        print("=" * 70)
        rc = cli._run_watchlist_command(app, ["add", "BBCA"])
        check(rc == 0, "watchlist add exited 0")
        app.manual_scan_service._watchlist_scanner = FakeWatchlistScanner()
        rc = cli._run_scan_command(app, ["--market", "idx"])
        check(rc == 0, "scan exited 0")
        real_snapshot = app.snapshot_repository.list_latest()[0]
        check(real_snapshot is not None, "scan produced a real, persisted RankingSnapshot row")

        print("\n" + "=" * 70)
        print("[4] recommendation_following episode: BUY -> partial SELL -> full SELL -> reopen BUY")
        print("=" * 70)
        price_box["value"] = 9000.0
        rc = cli._run_paper_command(app, ["buy", "BBCA", "--allocation", "0.05"])
        check(rc == 0, "paper buy #1 (opening BUY) exited 0")
        position = app.position_repository.get_open_position("paper", "BBCA")
        opened_quantity = position.quantity
        check(position is not None, "a real open Position exists after the opening BUY")

        price_box["value"] = 9100.0
        # Lot-size compliant partial (IDX lot size = 100 shares) -- leaves a
        # non-zero, non-fabricated remainder open.
        partial_qty = (opened_quantity / 2 // 100) * 100
        rc = cli._run_paper_command(app, ["sell", "BBCA", "--quantity", str(partial_qty)])
        check(rc == 0, "paper sell (partial SELL) exited 0")
        position_after_partial = app.position_repository.get_by_id(position.position_id)
        check(position_after_partial.status == "open", "position remains OPEN after a partial SELL -- episode not closed")

        price_box["value"] = 9200.0
        remaining_qty = position_after_partial.quantity
        rc = cli._run_paper_command(app, ["sell", "BBCA", "--quantity", str(remaining_qty)])
        check(rc == 0, "paper sell (closing SELL) exited 0")
        position_after_close = app.position_repository.get_by_id(position.position_id)
        check(position_after_close.status == "closed", "position is CLOSED after the full SELL -- episode complete")

        price_box["value"] = 9300.0
        rc = cli._run_paper_command(app, ["buy", "BBCA", "--allocation", "0.03"])
        check(rc == 0, "paper buy #2 (reopen BUY, a fresh episode) exited 0")
        reopened_position = app.position_repository.get_open_position("paper", "BBCA")
        check(reopened_position is not None and reopened_position.position_id != position.position_id, "reopening BUY creates a real, NEW, distinct open Position row")

        print("\n" + "=" * 70)
        print("[5] manual (no-signal) order path -- submit_order() directly with signal_evidence carrying no snapshot_id")
        print("=" * 70)
        from datetime import datetime, timezone
        import uuid as _uuid

        class _NoSnapshotEvidence:
            """Deliberately carries no snapshot_id attribute -- the real,
            documented 'manual' path (PaperTradingEngine's own getattr(...,
            None) contract)."""

        price_box["value"] = 500.0
        manual_trade = app.paper_trading_engine.submit_order(
            account_id="paper",
            symbol="MANUALX",
            action="BUY",
            quantity=100.0,
            requested_price=500.0,
            executed_at=datetime.now(timezone.utc).isoformat(),
            signal_evidence=_NoSnapshotEvidence(),
            user_approval=True,
            idempotency_key=f"manual-{_uuid.uuid4()}",
        )
        check(manual_trade is not None, "a real manual order (no signal) was submitted and filled")
        manual_order = app.order_repository.get_by_id(manual_trade.order_id)
        check(manual_order.analysis_snapshot_id is None, "the manual order's real, persisted analysis_snapshot_id is None")

        print("\n" + "=" * 70)
        print("[6] real trade attribution: real DB -> real repositories -> TradeAttributionService")
        print("=" * 70)
        attributions = app.trade_attribution_service.get_attribution("paper")
        real_trades = app.trade_repository.list_by_account("paper")
        check(len(attributions) == len(real_trades), f"one TradeAttribution per real Trade row ({len(real_trades)} trades)")

        by_symbol = {}
        for a in attributions:
            by_symbol.setdefault(a.symbol, []).append(a)

        print("\n  -- strategy: recommendation_following / manual --")
        bbca_attrs = by_symbol["BBCA"]
        check(all(a.strategy == "recommendation_following" for a in bbca_attrs), "every BBCA trade's strategy is 'recommendation_following' (real Order.analysis_snapshot_id was set)")
        manual_attrs = by_symbol["MANUALX"]
        check(all(a.strategy == "manual" for a in manual_attrs), "the no-signal trade's strategy is 'manual'")
        check(all(a.strategy_version == "1" for a in attributions), "every attribution's strategy_version is the literal '1'")

        print("\n  -- market: Account.asset_class --")
        real_account = app.account_repository.get_by_id("paper")
        check(all(a.market == real_account.asset_class for a in attributions), f"every attribution's market is the real, verbatim Account.asset_class ({real_account.asset_class!r})")

        print("\n  -- signal: RankingSnapshot.snapshot_id --")
        check(all(a.signal_snapshot_id == real_snapshot.snapshot_id for a in bbca_attrs), "every BBCA attribution's signal_snapshot_id is the REAL, resolved RankingSnapshot.snapshot_id")
        check(all(a.signal_snapshot_id is None for a in manual_attrs), "the manual trade's signal_snapshot_id is None -- never fabricated")

        print("\n  -- holding period: BUY -> partial SELL -> full SELL -> reopen episode boundaries --")
        bbca_by_action_order = sorted(bbca_attrs, key=lambda a: a.trade_id)
        opening_buy_attr, partial_sell_attr, closing_sell_attr, reopen_buy_attr = bbca_by_action_order
        check(
            opening_buy_attr.holding_period_seconds == partial_sell_attr.holding_period_seconds == closing_sell_attr.holding_period_seconds,
            "opening BUY, partial SELL, and closing SELL ALL share the identical real holding_period_seconds (one closed episode)",
        )
        check(opening_buy_attr.holding_period_seconds is not None and opening_buy_attr.holding_period_seconds > 0.0, "the closed episode's real holding_period_seconds is a positive, non-fabricated number")
        check(reopen_buy_attr.holding_period_seconds is None, "the reopened, still-open second episode's holding_period_seconds is None -- never fabricated")

        print("\n  -- risk category: DecisionPolicy.risk_level --")
        buy_attrs = [a for a in attributions if a.action == "BUY"]
        sell_attrs = [a for a in attributions if a.action == "SELL"]
        check(len(buy_attrs) > 0 and all(a.risk_category == "NORMAL" for a in buy_attrs), "every BUY attribution's risk_category is 'NORMAL', straight off the real, LOCKED DecisionPolicy")
        check(len(sell_attrs) > 0 and all(a.risk_category == "HIGH" for a in sell_attrs), "every SELL attribution's risk_category is 'HIGH', straight off the real, LOCKED DecisionPolicy")

        print("\n  -- traceability: Trade -> Order -> Position --")
        for a in attributions:
            real_trade = next(t for t in real_trades if t.trade_id == a.trade_id)
            real_order = app.order_repository.get_by_id(a.order_id)
            check(real_trade.order_id == a.order_id, f"attribution.order_id ({a.order_id}) matches the real Trade.order_id for trade {a.trade_id}")
            check(real_order is not None, f"attribution.order_id ({a.order_id}) resolves to a real, existing Order row")
        real_positions = app.position_repository.list_by_account("paper")
        bbca_positions = [p for p in real_positions if p.symbol == "BBCA"]
        check(len(bbca_positions) == 2, "the real Position ledger shows exactly 2 BBCA positions (one closed episode + one reopened) -- attribution's episode boundaries trace straight back to real Position rows")

        print("\n" + "=" * 70)
        print("[7] account isolation -- a second, independent account")
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
        attributions_other = app.trade_attribution_service.get_attribution("paper-2")
        check(attributions_other == [], "second account's attribution is ZERO rows -- 'paper' account's trades never leak across account_id")

        print("\n" + "=" * 70)
        print("[8] error path -- unknown account_id")
        print("=" * 70)
        from Core.exceptions import ValidationError
        raised = False
        try:
            app.trade_attribution_service.get_attribution("does-not-exist")
        except ValidationError:
            raised = True
        check(raised, "ValidationError propagates unchanged for an unknown account_id -- never a fabricated empty list")

        print("\n" + "=" * 70)
        print("[9] read-only proof -- Order/Trade/Position/Account/RankingSnapshot row counts unchanged")
        print("=" * 70)
        con = sqlite3.connect(db_path)
        watched_tables = ("orders", "trades", "positions", "accounts", "ranking_snapshots")
        counts_before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in watched_tables}
        # Also snapshot full row content (not just counts) for orders/trades/
        # positions/accounts/ranking_snapshots to prove no in-place UPDATE
        # slipped past a naive COUNT(*) check either.
        content_before = {t: con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in watched_tables}
        con.close()

        for _ in range(3):
            app.trade_attribution_service.get_attribution("paper")
            app.trade_attribution_service.get_attribution_grouped("paper", "strategy")
            app.trade_attribution_service.get_attribution_grouped("paper", "holding_period")

        con = sqlite3.connect(db_path)
        counts_after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in watched_tables}
        content_after = {t: con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in watched_tables}
        con.close()
        check(counts_before == counts_after, f"row counts unchanged after 3 repeated attribution calls: {counts_before} == {counts_after}")
        check(content_before == content_after, "row CONTENT (every column, every table) is byte-for-byte unchanged after repeated attribution calls -- no in-place mutation of Order/Trade/Position/Account/RankingSnapshot")

    print("\n" + "=" * 70)
    print("[10] restart persistence -- brand-new OS process, brand-new build_application(), same DB file")
    print("=" * 70)
    proof_snippet = (
        "import sys\n"
        "sys.path.insert(0, '.')\n"
        "from Core.composition_root import build_application\n"
        "app2 = build_application()\n"
        "attributions = app2.trade_attribution_service.get_attribution('paper')\n"
        "bbca = [a for a in attributions if a.symbol == 'BBCA']\n"
        "manual = [a for a in attributions if a.symbol == 'MANUALX']\n"
        "print('RESTART_TOTAL_ATTRIBUTIONS=' + str(len(attributions)))\n"
        "print('RESTART_BBCA_STRATEGY=' + bbca[0].strategy)\n"
        "print('RESTART_MANUAL_STRATEGY=' + manual[0].strategy)\n"
        "closed = sorted(bbca, key=lambda a: a.trade_id)[:3]\n"
        "print('RESTART_HOLDING_PERIOD_CONSISTENT=' + str(len({a.holding_period_seconds for a in closed}) == 1))\n"
        "print('RESTART_HOLDING_PERIOD_VALUE=' + str(closed[0].holding_period_seconds))\n"
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
    check("RESTART_TOTAL_ATTRIBUTIONS=" in result.stdout, "a brand-new process, brand-new build_application(), successfully computes attribution after restart")
    check("RESTART_BBCA_STRATEGY=recommendation_following" in result.stdout, "the same real 'recommendation_following' strategy survives a real restart, read straight from SQLite")
    check("RESTART_MANUAL_STRATEGY=manual" in result.stdout, "the same real 'manual' strategy survives a real restart")
    check("RESTART_HOLDING_PERIOD_CONSISTENT=True" in result.stdout, "the closed episode's holding period is still consistent across all its trades after restart")

    print("\n" + "=" * 70)
    print(f"ACTIVATION 5.6 ACCEPTANCE-GATE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())