"""Activation 11 final deterministic Forex paper E2E acceptance probe."""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import Orchestration.market_price_tool as market_price_tool_module
import main as cli
from Business.account_balance_service import AccountBalanceService
from Business.execution_policy_config import load_execution_policy
from Business.execution_service import ExecutionService
from Business.manual_scan_service import ManualScanService
from Business.order_lifecycle_service import OrderLifecycleService
from Business.paper_trading_engine import PaperTradingEngine
from Business.performance_summary_production_service import PerformanceSummaryProductionService
from Business.performance_summary_service import PerformanceSummaryService
from Business.expectancy_engine import ExpectancyEngine
from Business.maximum_drawdown_engine import MaximumDrawdownEngine
from Business.notification_builder import NotificationBuilder
from Business.notification_dispatcher import NotificationDispatcher
from Business.notification_manager import NotificationManager
from Business.position_manager import PositionManager
from Business.position_performance_engine import PositionPerformanceEngine
from Business.portfolio_snapshot_service import PortfolioSnapshotService
from Business.profit_factor_engine import ProfitFactorEngine
from Business.ranking_engine import RankingEngine
from Business.reconciliation_engine import ReconciliationEngine
from Business.recommendation_service import RecommendationService
from Business.report_service import ReportService
from Business.trade_statistics_engine import TradeStatisticsEngine
from Business.unrealized_pnl_engine import UnrealizedPnLEngine
from Business.win_rate_engine import WinRateEngine
from Core.bootstrap import DEFAULT_FOREX_ACCOUNT_ID, DEFAULT_PAPER_ACCOUNT_ID
from Core.init_command import run_init
from Core.init_forex_command import run_init_forex
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.sqlite_database import SQLiteDatabase
from Orchestration.skill_result import SkillResult
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_approval_repository import OrderApprovalRepository
from Repository.persistence.order_idempotency_repository import OrderIdempotencyRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.performance_repository import PerformanceRepository
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.snapshot_repository import SnapshotRepository
from Repository.persistence.trade_repository import TradeRepository
from Repository.persistence.watchlist_repository import WatchlistRepository

PASS = 0
FAIL = 0


def check(ok: bool, msg: str) -> None:
    global PASS, FAIL
    print(("PASS" if ok else "FAIL") + " - " + msg)
    if ok:
        PASS += 1
    else:
        FAIL += 1


PAIR = "EUR/USD"
PRICE = 1.10
PREVIOUS = 1.09
BUY_STOP = 1.095
SELL_STOP_FOR_LONG = 1.095
EXECUTED_AT = "2026-01-06T15:00:00+00:00"


class FakeWatchlistScanner:
    def scan(self) -> Dict[str, Any]:
        return {
            PAIR: {
                "watchlist": SkillResult(
                    success=True,
                    output={
                        "watchlist": [
                            {
                                "priority": 1,
                                "symbol": PAIR,
                                "recommendation": "BUY",
                                "confidence": "HIGH",
                                "summary": "Deterministic Forex BUY evidence for E2E acceptance.",
                            }
                        ]
                    },
                )
            }
        }


def fake_fetch(symbol: str):
    normalized = symbol.upper()
    if normalized in {"EURUSD=X", "EUR/USD", "EURUSD"}:
        return PRICE, PREVIOUS
    return None, None


class App:
    def __init__(self, manager: DatabaseManager) -> None:
        self.account_repository = AccountRepository(manager)
        self.watchlist_repository = WatchlistRepository(manager)
        self.position_repository = PositionRepository(manager)
        self.order_repository = OrderRepository(manager)
        self.trade_repository = TradeRepository(manager)
        self.snapshot_repository = SnapshotRepository(manager)
        self.performance_repository = PerformanceRepository(manager)
        self.portfolio_snapshot_repository = PortfolioSnapshotRepository(manager)

        idem = OrderIdempotencyRepository(manager)
        approvals = OrderApprovalRepository(manager)
        execution_policy = load_execution_policy()

        self.market_price_tool = market_price_tool_module.MarketPriceTool()
        unrealized = UnrealizedPnLEngine(self.market_price_tool)

        self.manual_scan_service = ManualScanService(
            FakeWatchlistScanner(),
            RankingEngine(),
            RecommendationService(),
            ReportService(),
            self.snapshot_repository,
        )

        self.paper_trading_engine = PaperTradingEngine(
            order_lifecycle_service=OrderLifecycleService(self.order_repository),
            execution_service=ExecutionService(self.order_repository, self.trade_repository, execution_policy),
            account_repository=self.account_repository,
            position_repository=self.position_repository,
            order_idempotency_repository=idem,
            kill_switch_engaged=False,
            max_order_value=1_000_000_000.0,
            execution_policy=execution_policy,
            account_balance_service=AccountBalanceService(self.account_repository),
            position_manager=PositionManager(self.position_repository, self.account_repository),
            notification_manager=NotificationManager(NotificationDispatcher(channels=[])),
            notification_builder=NotificationBuilder(),
            order_approval_repository=approvals,
            halted_markets=frozenset(),
            halted_symbols=frozenset(),
            max_daily_loss=None,
            max_position_value=None,
        )

        max_dd = MaximumDrawdownEngine()
        self.portfolio_snapshot_service = PortfolioSnapshotService(
            account_repository=self.account_repository,
            position_repository=self.position_repository,
            unrealized_pnl_engine=unrealized,
            maximum_drawdown_engine=max_dd,
            portfolio_snapshot_repository=self.portfolio_snapshot_repository,
        )
        self.reconciliation_engine = ReconciliationEngine(
            order_repository=self.order_repository,
            trade_repository=self.trade_repository,
            account_repository=self.account_repository,
            position_repository=self.position_repository,
        )
        perf_service = PerformanceSummaryService(
            trade_statistics_engine=TradeStatisticsEngine(),
            position_performance_engine=PositionPerformanceEngine(),
            win_rate_engine=WinRateEngine(),
            expectancy_engine=ExpectancyEngine(),
            profit_factor_engine=ProfitFactorEngine(),
            maximum_drawdown_engine=max_dd,
        )
        self.performance_summary_production_service = PerformanceSummaryProductionService(
            account_repository=self.account_repository,
            trade_repository=self.trade_repository,
            position_repository=self.position_repository,
            portfolio_snapshot_service=self.portfolio_snapshot_service,
            performance_summary_service=perf_service,
        )


def build_app(cfg: DatabaseConfig) -> App:
    db = SQLiteDatabase(cfg)
    db.connect()
    manager = DatabaseManager(db, cfg)
    return App(manager)


def main() -> int:
    global PASS, FAIL
    tmp = Path(tempfile.mkdtemp(prefix="activation11_forex_e2e_"))
    cfg = DatabaseConfig(db_path=tmp / "forex_e2e.db")
    original_fetch = market_price_tool_module._fetch_real_prices
    previous_market = os.environ.get("AIOS_MARKET")

    try:
        check(run_init(db_config=cfg, print_fn=lambda _: None) == 0, "canonical init succeeds")
        check(run_init_forex(db_config=cfg, print_fn=lambda _: None) == 0, "init-forex succeeds")
        app = build_app(cfg)

        forex = app.account_repository.get_by_id(DEFAULT_FOREX_ACCOUNT_ID)
        idx = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
        check(forex is not None and forex.asset_class == "forex" and forex.currency == "USD", "forex-usd account is present and correct")
        idx_cash_before = idx.cash if idx else None

        market_price_tool_module._fetch_real_prices = fake_fetch
        app.watchlist_repository.add(PAIR)

        observed = []
        original_scan = app.manual_scan_service.run_scan
        def scan_spy(ts: str):
            observed.append(os.environ.get("AIOS_MARKET"))
            return original_scan(ts)
        app.manual_scan_service.run_scan = scan_spy

        try:
            rc = cli._run_scan_command(app, ["--market", "forex"])
        finally:
            app.manual_scan_service.run_scan = original_scan
        check(rc == 0, "scan --market forex succeeds through real ManualScanService")
        check(observed == ["forex"], "AIOS_MARKET=forex during scan")
        check(os.environ.get("AIOS_MARKET") == previous_market, "AIOS_MARKET restored after scan")

        snap = cli._latest_snapshot_for_symbol(app, PAIR)
        check(snap is not None and snap.status == "success", "Forex RankingSnapshot persisted")
        check(snap is not None and snap.recommendation == "BUY", "Forex snapshot recommendation is BUY")
        check(cli._run_recommendation_command(app, [PAIR]) == 0, "Forex recommendation command succeeds")
        check(cli._latest_snapshot_for_symbol(app, PAIR) is not None, "recommendation reads persisted Forex snapshot")

        buy_rc = cli._run_paper_buy_command(
            app,
            [PAIR, "--allocation", "0.05", "--market", "forex", "--stop-loss", str(BUY_STOP), "--executed-at", EXECUTED_AT],
        )
        check(buy_rc == 0, "Forex BUY succeeds through production paper path")
        pos = app.position_repository.get_open_position(DEFAULT_FOREX_ACCOUNT_ID, PAIR)
        trades = app.trade_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        orders = app.order_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        check(pos is not None and pos.direction == "LONG", "Forex BUY creates LONG position")
        check(pos is not None and pos.stop_loss == BUY_STOP, "Forex BUY persists stop-loss")
        check(len(orders) == 1 and len(trades) == 1, "Forex BUY creates Order + Trade")

        snapshots = app.portfolio_snapshot_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)
        check(len(snapshots) >= 1, "post-trade PortfolioSnapshot persisted")

        perf_rc = cli._run_report_command(app, ["performance", DEFAULT_FOREX_ACCOUNT_ID])
        check(perf_rc == 0, "report performance forex-usd succeeds")
        perf = app.performance_summary_production_service.get_performance_summary(DEFAULT_FOREX_ACCOUNT_ID)
        check(perf.trade_statistics.total_trades >= 1, "performance contains Forex BUY trade")
        check(perf.position_statistics is not None, "performance computes Forex position statistics")

        sell_rc = cli._run_paper_sell_command(
            app,
            [PAIR, "--quantity", str(int(pos.quantity if pos else 0)), "--market", "forex", "--stop-loss", str(SELL_STOP_FOR_LONG), "--executed-at", EXECUTED_AT],
        )
        check(sell_rc == 0, "Forex SELL closes LONG through production paper path")
        check(app.position_repository.get_open_position(DEFAULT_FOREX_ACCOUNT_ID, PAIR) is None, "Forex position closes after SELL")
        check(len(app.trade_repository.list_by_account(DEFAULT_FOREX_ACCOUNT_ID)) == 2, "Forex trade count is BUY + SELL")

        rec = app.reconciliation_engine.reconcile_account(DEFAULT_FOREX_ACCOUNT_ID)
        check(rec.consistent is True, "Forex reconciliation is CONSISTENT")
        check(rec.violations == [], "Forex reconciliation has no violations")

        idx_after = app.account_repository.get_by_id(DEFAULT_PAPER_ACCOUNT_ID)
        check(idx_after is not None and idx_after.cash == idx_cash_before, "IDX cash remains unchanged")
        check(len(app.order_repository.list_by_account(DEFAULT_PAPER_ACCOUNT_ID)) == 0, "IDX receives no Forex orders")
        check(os.environ.get("AIOS_MARKET") == previous_market, "AIOS_MARKET restored after full Forex flow")

        print(f"\nACTIVATION 11 FINAL E2E: {PASS} PASS / {FAIL} FAIL (total {PASS+FAIL})")
        return 0 if FAIL == 0 else 1
    finally:
        market_price_tool_module._fetch_real_prices = original_fetch
        if previous_market is None:
            os.environ.pop("AIOS_MARKET", None)
        else:
            os.environ["AIOS_MARKET"] = previous_market

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
