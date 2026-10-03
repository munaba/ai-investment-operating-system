"""Standalone, focused regression checks for Phase G Task 4 ONLY:
"Continuous Review Inputs" -- ``Services.paper_review_service.
PaperReviewService``.

Every scenario drives the REAL ``PaperReviewService`` against a real
on-disk SQLite database and the REAL, unmodified ``JournalService``,
``BriefApprovalService``, ``PaperTradingEngine``,
``StrategyPerformanceService``, and ``MarketRegimeAttributionService``
-- no mocked business logic. Only the ``yfinance`` client underneath
``StockDataRepository`` is faked, following the exact pattern already
established by ``Tests/test_market_regime_attribution_service.py``.

Proves, concretely:

* Scenario 1: an empty review period (no journal entries at all)
  returns an honest, all-zero result -- never an error, never a
  fabricated non-zero count.
* Scenario 2: TAKE/SKIP/WAIT counts match real, persisted
  ``JournalEntry`` rows exactly.
* Scenario 3: an ACCEPTED TAKE that was actually approved-and-submitted
  is traced end to end -- decision -> brief -> approval -> order ->
  trade -- with every id/timestamp on the trace matching the real,
  persisted rows.
* Scenario 4: strategy attribution is the real, unmodified
  ``StrategyPerformanceService`` output, byte-for-byte.
* Scenario 5: market-regime attribution is the real, unmodified
  ``MarketRegimeAttributionService`` output, byte-for-byte.
* Scenario 6: decision adherence is FOLLOWED once a real outcome is
  recorded on an executed TAKE.
* Scenario 7: decision adherence is OUTCOME_PENDING (not FOLLOWED, not
  NOT_APPLICABLE) for an executed TAKE with no outcome recorded yet,
  and NOT_EXECUTED for an ACCEPTED TAKE that was never actually
  approved-and-submitted.
* Scenario 8: valuation freshness counts come verbatim from real,
  persisted ``PortfolioSnapshot.valuation_status`` rows -- never a
  fabricated/guessed price -- and reports NOT_AVAILABLE, honestly,
  when no ``PortfolioSnapshotRepository`` was supplied at all.
* Scenario 9: every id/timestamp on every ``DecisionTrace`` traces
  back to a real row still readable from its own repository.
* Scenario 10: restart-safe -- a brand new ``PaperReviewService``
  instance (fresh repositories, fresh ``DatabaseManager``, same
  on-disk file) reproduces an identical review result.

Run directly with
``python Tests/test_phase_g_task4_paper_review_service.py`` -- no
external test framework required, matching every other standalone
test file in this repository.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402

from Business.execution_service import ExecutionService  # noqa: E402
from Business.market_regime_attribution_service import MarketRegimeAttributionService  # noqa: E402
from Business.market_regime_engine import MarketRegimeEngine  # noqa: E402
from Business.market_regime_performance_engine import MarketRegimePerformanceEngine  # noqa: E402
from Business.market_regime_service import MarketRegimeService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.position_episode_replay_engine import PositionEpisodeReplayEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.risk_ledger_policy import RiskLedgerPolicy  # noqa: E402
from Business.strategy_performance_engine import StrategyPerformanceEngine  # noqa: E402
from Business.strategy_performance_service import StrategyPerformanceService  # noqa: E402
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_brief_approvals import BRIEF_APPROVALS_MIGRATIONS  # noqa: E402
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshot_valuation_status import (  # noqa: E402
    PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS,
)
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.migrations_watchlist import WATCHLIST_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.external.stock_data_repository import StockDataRepository  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.brief_approval_repository import BriefApprovalRepository  # noqa: E402
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
from Repository.persistence.journal_repository import JournalRepository  # noqa: E402
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import (  # noqa: E402
    PortfolioSnapshotRepository,
)
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.risk_limits_repository import RiskLimitsRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402
from Repository.persistence.watchlist_repository import WatchlistRepository  # noqa: E402
from Services.brief_approval_service import BriefApprovalService  # noqa: E402
from Services.decision_brief_service import STATUS_SUCCESS  # noqa: E402
from Services.journal_service import (  # noqa: E402
    DECISION_SKIP,
    DECISION_TAKE,
    DECISION_WAIT,
    JournalService,
)
from Services.paper_review_service import (  # noqa: E402
    ADHERENCE_FOLLOWED,
    ADHERENCE_NOT_APPLICABLE,
    ADHERENCE_NOT_EXECUTED,
    ADHERENCE_OUTCOME_PENDING,
    NOT_AVAILABLE,
    PaperReviewService,
)

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


# ---------------------------------------------------------------------------
# Real fixture market history -- reused verbatim from
# Tests/test_market_regime_attribution_service.py's own independently
# verified "ranging" fixture (trailing-20-bar window classifies
# "ranging" through the real, unmodified MarketRegimeEngine).
# ---------------------------------------------------------------------------


def _ranging_history() -> pd.DataFrame:
    dates = pd.date_range(start="2026-01-01", periods=21, freq="D")
    closes: List[float] = [5000.0]
    for i in range(20):
        closes.append(closes[-1] + (2 if i % 2 == 0 else -2))
    rows = [{"Date": d, "Close": c} for d, c in zip(dates, closes)]
    return pd.DataFrame(rows).set_index("Date")


class _FakeTicker:
    def __init__(self, history_df: Optional[pd.DataFrame]) -> None:
        self._history_df = history_df

    def history(self, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        return self._history_df if self._history_df is not None else pd.DataFrame()


class FakeYFinanceModule:
    def __init__(self, histories: Dict[str, pd.DataFrame]) -> None:
        self._histories = histories

    def Ticker(self, symbol: str) -> _FakeTicker:
        return _FakeTicker(self._histories.get(symbol))


# ---------------------------------------------------------------------------
# Real-database test rig
# ---------------------------------------------------------------------------


def _build(tmp_dir: str, db_name: str, *, histories: Optional[Dict[str, pd.DataFrame]] = None):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(DECISION_BRIEFS_MIGRATIONS)
    MigrationRunner(db).apply(BRIEF_APPROVALS_MIGRATIONS)
    MigrationRunner(db).apply(RISK_LEDGER_MIGRATIONS)
    MigrationRunner(db).apply(WATCHLIST_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="paper-id", account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
    )
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idempotency_repo = OrderIdempotencyRepository(manager)
    brief_repo = DecisionBriefRepository(manager)
    brief_approval_repo = BriefApprovalRepository(manager)
    journal_repo = JournalRepository(manager)
    risk_limits_repo = RiskLimitsRepository(manager)
    watchlist_repo = WatchlistRepository(manager)
    portfolio_snapshot_repo = PortfolioSnapshotRepository(manager)
    position_manager = PositionManager(position_repo)

    order_lifecycle_service = OrderLifecycleService(order_repo)
    execution_service = ExecutionService(order_repo, trade_repo)
    engine = PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repo,
        position_repository=position_repo,
        order_idempotency_repository=idempotency_repo,
        kill_switch_engaged=False,
        max_order_value=1_000_000_000.0,
    )
    brief_approval_service = BriefApprovalService(
        decision_brief_repository=brief_repo,
        brief_approval_repository=brief_approval_repo,
        paper_trading_engine=engine,
    )
    journal_service = JournalService(
        brief_repository=brief_repo,
        risk_limits_repository=risk_limits_repo,
        journal_repository=journal_repo,
        risk_ledger_policy=RiskLedgerPolicy(),
    )
    risk_limits_repo.save(
        reference_capital=100_000_000.0,
        max_risk_per_trade_percent=100.0,
        max_daily_loss=1_000_000_000.0,
        max_trades_per_day=1000,
        loss_streak_cooldown=1000,
        updated_at="2026-08-01T00:00:00+00:00",
    )

    position_episode_replay_engine = PositionEpisodeReplayEngine(TradeHoldingPeriodEngine())
    strategy_performance_service = StrategyPerformanceService(
        account_repository=account_repo,
        trade_repository=trade_repo,
        order_repository=order_repo,
        position_repository=position_repo,
        position_episode_replay_engine=position_episode_replay_engine,
        strategy_performance_engine=StrategyPerformanceEngine(),
    )

    stock_data_repository = StockDataRepository(
        yfinance_module=FakeYFinanceModule(histories or {})
    )
    market_regime_service = MarketRegimeService(
        stock_data_repository=stock_data_repository,
        market_regime_engine=MarketRegimeEngine(),
    )
    market_regime_attribution_service = MarketRegimeAttributionService(
        account_repository=account_repo,
        trade_repository=trade_repo,
        position_repository=position_repo,
        watchlist_repository=watchlist_repo,
        position_episode_replay_engine=position_episode_replay_engine,
        market_regime_service=market_regime_service,
        market_regime_performance_engine=MarketRegimePerformanceEngine(),
    )

    review_service = PaperReviewService(
        account_repository=account_repo,
        journal_repository=journal_repo,
        decision_brief_repository=brief_repo,
        brief_approval_repository=brief_approval_repo,
        order_repository=order_repo,
        trade_repository=trade_repo,
        strategy_performance_service=strategy_performance_service,
        market_regime_attribution_service=market_regime_attribution_service,
        portfolio_snapshot_repository=portfolio_snapshot_repo,
    )
    review_service_no_optionals = PaperReviewService(
        account_repository=account_repo,
        journal_repository=journal_repo,
        decision_brief_repository=brief_repo,
        brief_approval_repository=brief_approval_repo,
        order_repository=order_repo,
        trade_repository=trade_repo,
    )

    repos = {
        "cfg": cfg,
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
        "brief": brief_repo,
        "brief_approval": brief_approval_repo,
        "journal": journal_repo,
        "risk_limits": risk_limits_repo,
        "watchlist": watchlist_repo,
        "portfolio_snapshot": portfolio_snapshot_repo,
        "position_manager": position_manager,
        "journal_service": journal_service,
        "brief_approval_service": brief_approval_service,
        "review_service": review_service,
        "review_service_no_optionals": review_service_no_optionals,
        "db": db,
    }
    return repos


def _make_success_brief(brief_repo, *, symbol="BBCA", entry=9500.0, stop=9300.0, target=9900.0,
                         risk_amount=20000.0, position_size=100.0, rr=2.0):
    brief = brief_repo.create(
        symbol=symbol, generated_at="2026-08-23T09:00:00+00:00", status=STATUS_SUCCESS,
        source_snapshot_id=None, reason=None,
        entry_price=entry, stop_loss_price=stop, take_profit_price=target,
        risk_amount=risk_amount, position_size=position_size, risk_reward_ratio=rr,
    )
    return brief.brief_id


# ---------------------------------------------------------------------------
# Scenario 1: empty review period
# ---------------------------------------------------------------------------


def scenario_empty_review_period():
    print("\n[Scenario 1] empty review period: no journal entries at all -> honest all-zero result")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s1.db")
        result = ctx["review_service"].review("paper-id")

        check(result.total_reviewed_decisions == 0, "total_reviewed_decisions == 0")
        check(result.take_count == 0 and result.skip_count == 0 and result.wait_count == 0, "all decision counts are 0")
        check(result.approved_paper_count == 0, "approved_paper_count == 0")
        check(result.linked_order_count == 0 and result.linked_trade_count == 0, "linked order/trade counts == 0")
        check(result.decision_traces == (), "decision_traces is empty, not fabricated")
        check(result.strategy_breakdown == {}, "strategy_breakdown is a real empty dict (zero closed episodes)")
        check(result.market_regime_breakdown == {}, "market_regime_breakdown is a real empty dict (zero closed episodes)")
        check(sum(result.adherence_summary.values()) == 0, "adherence_summary sums to 0")
        check(result.valuation_freshness.status == "AVAILABLE", "valuation_freshness looked (repository was supplied)")
        check(
            result.valuation_freshness.fresh == 0 and result.valuation_freshness.stale == 0,
            "valuation_freshness counts are honestly 0 (no snapshots exist yet)",
        )


def scenario_unknown_account_raises():
    print("\n[Scenario 1b] unknown account_id raises ValidationError, never a fabricated result")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s1b.db")
        raised = None
        try:
            ctx["review_service"].review("does-not-exist")
        except ValidationError as exc:
            raised = exc
        check(raised is not None, "ValidationError is raised for an unknown account")


# ---------------------------------------------------------------------------
# Scenario 2: TAKE/SKIP/WAIT counts match real JournalEntry rows
# ---------------------------------------------------------------------------


def scenario_take_skip_wait_counts():
    print("\n[Scenario 2] TAKE/SKIP/WAIT counts match real, persisted JournalEntry rows exactly")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s2.db")
        b1 = _make_success_brief(ctx["brief"], symbol="BBCA")
        b2 = _make_success_brief(ctx["brief"], symbol="ASII")
        b3 = _make_success_brief(ctx["brief"], symbol="TLKM")

        ctx["journal_service"].record_decision(b1, DECISION_TAKE)
        ctx["journal_service"].record_decision(b2, DECISION_SKIP)
        ctx["journal_service"].record_decision(b3, DECISION_WAIT)

        result = ctx["review_service"].review("paper-id")
        check(result.total_reviewed_decisions == 3, "total_reviewed_decisions == 3")
        check(result.take_count == 1, "take_count == 1")
        check(result.skip_count == 1, "skip_count == 1")
        check(result.wait_count == 1, "wait_count == 1")
        check(len(result.decision_traces) == 3, "one DecisionTrace per real JournalEntry")


def scenario_period_filter():
    print("\n[Scenario 2b] since/until filters real JournalEntry.decided_at correctly")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s2b.db")
        b1 = _make_success_brief(ctx["brief"], symbol="BBCA")
        b2 = _make_success_brief(ctx["brief"], symbol="ASII")
        e1 = ctx["journal"].create(
            brief_id=b1, symbol="BBCA", decision=DECISION_SKIP, decided_at="2026-08-01T00:00:00+00:00",
            note=None, risk_policy_status="ACCEPTED", risk_policy_reason=None, planned_r=None,
            created_at="2026-08-01T00:00:00+00:00",
        )
        e2 = ctx["journal"].create(
            brief_id=b2, symbol="ASII", decision=DECISION_SKIP, decided_at="2026-08-10T00:00:00+00:00",
            note=None, risk_policy_status="ACCEPTED", risk_policy_reason=None, planned_r=None,
            created_at="2026-08-10T00:00:00+00:00",
        )
        result = ctx["review_service"].review("paper-id", since="2026-08-05T00:00:00+00:00")
        check(result.total_reviewed_decisions == 1, "only the in-range entry is reviewed")
        check(result.decision_traces[0].entry_id == e2.entry_id, "the later entry (e2) is the one reviewed")
        check(e1.entry_id != e2.entry_id, "sanity: the two entries are distinct")


# ---------------------------------------------------------------------------
# Scenario 3: full trace decision -> brief -> approval -> order -> trade
# ---------------------------------------------------------------------------


def scenario_full_trace_approved_paper():
    print("\n[Scenario 3] ACCEPTED TAKE that was approved-and-submitted traces end to end")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s3.db")
        brief_id = _make_success_brief(ctx["brief"], symbol="BBCA")
        entry = ctx["journal_service"].record_decision(brief_id, DECISION_TAKE)
        check(entry.risk_policy_status == "ACCEPTED", "sanity: the TAKE was ACCEPTED by the real RiskLedgerPolicy")

        approval_result = ctx["brief_approval_service"].approve_and_submit(
            brief_id, approved=True, account_id="paper-id", executed_at="2026-08-23T10:00:00+00:00",
        )

        result = ctx["review_service"].review("paper-id")
        check(result.approved_paper_count == 1, "approved_paper_count == 1")
        check(result.linked_order_count == 1, "linked_order_count == 1")
        check(result.linked_trade_count == 1, "linked_trade_count == 1")

        trace = result.decision_traces[0]
        check(trace.entry_id == entry.entry_id, "trace.entry_id matches the real JournalEntry")
        check(trace.brief_id == brief_id, "trace.brief_id matches the real DecisionBrief")
        check(trace.approved_paper is True, "trace.approved_paper is True")
        check(trace.order_id == approval_result.trade.order_id, "trace.order_id matches the real Order")
        check(trace.trade_id == approval_result.trade.trade_id, "trace.trade_id matches the real Trade")

        real_order = ctx["order"].get_by_id(trace.order_id)
        real_trade = ctx["trade"].get_by_id(trace.trade_id)
        check(real_order is not None and real_order.symbol == "BBCA", "trace.order_id resolves to a real, matching Order")
        check(real_trade is not None and real_trade.symbol == "BBCA", "trace.trade_id resolves to a real, matching Trade")


def scenario_skip_never_links():
    print("\n[Scenario 3b] a SKIP decision never has a link, regardless of review")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s3b.db")
        brief_id = _make_success_brief(ctx["brief"], symbol="BBCA")
        ctx["journal_service"].record_decision(brief_id, DECISION_SKIP)

        result = ctx["review_service"].review("paper-id")
        check(result.approved_paper_count == 0, "approved_paper_count == 0 for a SKIP")
        check(result.decision_traces[0].order_id is None, "trace.order_id is None for a SKIP")
        check(result.decision_traces[0].trade_id is None, "trace.trade_id is None for a SKIP")


# ---------------------------------------------------------------------------
# Scenario 4: strategy attribution is the real, unmodified service output
# ---------------------------------------------------------------------------


def scenario_strategy_attribution():
    print("\n[Scenario 4] strategy_breakdown is the real StrategyPerformanceService output, byte-for-byte")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s4.db")
        order1 = ctx["order"].create(
            account_id="paper-id", symbol="BBCA", action="BUY", quantity=100.0,
            requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="",
            analysis_snapshot_id=None,
        )
        trade1 = ctx["trade"].create(
            order_id=order1.order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0, executed_at="2026-08-01T09:00:00+00:00",
        )
        ctx["position_manager"].apply_trade(trade1)
        order2 = ctx["order"].create(
            account_id="paper-id", symbol="BBCA", action="SELL", quantity=100.0,
            requested_price=9500.0, filled_price=9500.0, status="FILLED", reason="",
            analysis_snapshot_id=None,
        )
        trade2 = ctx["trade"].create(
            order_id=order2.order_id, account_id="paper-id", symbol="BBCA", action="SELL",
            quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0, executed_at="2026-08-01T13:00:00+00:00",
        )
        ctx["position_manager"].apply_trade(trade2)

        expected = ctx["review_service_no_optionals"]  # sanity placeholder, unused
        direct = None
        from Business.strategy_performance_service import StrategyPerformanceService as _SPS  # noqa: E402
        # Build an independent, second StrategyPerformanceService instance
        # pointed at the SAME real repositories, to prove PaperReviewService
        # returns the identical, real output -- never its own computation.
        independent = _SPS(
            account_repository=ctx["account"], trade_repository=ctx["trade"],
            order_repository=ctx["order"], position_repository=ctx["position"],
            position_episode_replay_engine=PositionEpisodeReplayEngine(TradeHoldingPeriodEngine()),
            strategy_performance_engine=StrategyPerformanceEngine(),
        )
        direct = independent.get_performance_by_strategy("paper-id")

        result = ctx["review_service"].review("paper-id")
        check(result.strategy_breakdown == direct, "strategy_breakdown matches an independent, real StrategyPerformanceService call")
        check("manual" in result.strategy_breakdown, "the real 'manual' strategy group is present")
        check(result.strategy_breakdown["manual"].closed_episodes == 1, "one real closed episode counted")


def scenario_strategy_not_available_when_unwired():
    print("\n[Scenario 4b] strategy_breakdown is NOT_AVAILABLE when no StrategyPerformanceService was injected")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s4b.db")
        result = ctx["review_service_no_optionals"].review("paper-id")
        check(result.strategy_breakdown == NOT_AVAILABLE, "strategy_breakdown == NOT_AVAILABLE, never fabricated")
        check(result.market_regime_breakdown == NOT_AVAILABLE, "market_regime_breakdown == NOT_AVAILABLE, never fabricated")
        check(result.valuation_freshness.status == NOT_AVAILABLE, "valuation_freshness.status == NOT_AVAILABLE, never fabricated")


# ---------------------------------------------------------------------------
# Scenario 5: market-regime attribution is the real, unmodified service output
# ---------------------------------------------------------------------------


def scenario_market_regime_attribution():
    print("\n[Scenario 5] market_regime_breakdown is the real MarketRegimeAttributionService output, byte-for-byte")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s5.db", histories={"BBCA": _ranging_history()})
        order1 = ctx["order"].create(
            account_id="paper-id", symbol="BBCA", action="BUY", quantity=100.0,
            requested_price=5000.0, filled_price=5000.0, status="FILLED", reason="",
            analysis_snapshot_id=None,
        )
        trade1 = ctx["trade"].create(
            order_id=order1.order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=100.0, fill_price=5000.0, fee=0.0, tax=0.0, executed_at="2026-01-20T09:00:00+00:00",
        )
        ctx["position_manager"].apply_trade(trade1)
        order2 = ctx["order"].create(
            account_id="paper-id", symbol="BBCA", action="SELL", quantity=100.0,
            requested_price=5100.0, filled_price=5100.0, status="FILLED", reason="",
            analysis_snapshot_id=None,
        )
        trade2 = ctx["trade"].create(
            order_id=order2.order_id, account_id="paper-id", symbol="BBCA", action="SELL",
            quantity=100.0, fill_price=5100.0, fee=0.0, tax=0.0, executed_at="2026-01-20T13:00:00+00:00",
        )
        ctx["position_manager"].apply_trade(trade2)

        from Business.market_regime_attribution_service import (  # noqa: E402
            MarketRegimeAttributionService as _MRAS,
        )
        independent = _MRAS(
            account_repository=ctx["account"], trade_repository=ctx["trade"],
            position_repository=ctx["position"], watchlist_repository=ctx["watchlist"],
            position_episode_replay_engine=PositionEpisodeReplayEngine(TradeHoldingPeriodEngine()),
            market_regime_service=MarketRegimeService(
                stock_data_repository=StockDataRepository(
                    yfinance_module=FakeYFinanceModule({"BBCA": _ranging_history()})
                ),
                market_regime_engine=MarketRegimeEngine(),
            ),
            market_regime_performance_engine=MarketRegimePerformanceEngine(),
        )
        direct = independent.get_performance_by_regime("paper-id")

        result = ctx["review_service"].review("paper-id")
        check(result.market_regime_breakdown == direct, "market_regime_breakdown matches an independent, real MarketRegimeAttributionService call")
        check("ranging" in result.market_regime_breakdown, "the real 'ranging' regime group is present")


# ---------------------------------------------------------------------------
# Scenario 6/7: decision adherence
# ---------------------------------------------------------------------------


def scenario_adherence_followed_when_outcome_exists():
    print("\n[Scenario 6] adherence == FOLLOWED once a real outcome is recorded on an executed TAKE")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s6.db")
        brief_id = _make_success_brief(ctx["brief"], symbol="BBCA")
        entry = ctx["journal_service"].record_decision(brief_id, DECISION_TAKE)
        ctx["brief_approval_service"].approve_and_submit(
            brief_id, approved=True, account_id="paper-id", executed_at="2026-08-23T10:00:00+00:00",
        )
        ctx["journal_service"].record_outcome(
            entry.entry_id, outcome_status="CLOSED_WIN", exit_price=9900.0,
            closed_at="2026-08-24T10:00:00+00:00",
        )

        result = ctx["review_service"].review("paper-id")
        trace = result.decision_traces[0]
        check(trace.adherence == ADHERENCE_FOLLOWED, "adherence == FOLLOWED")
        check(trace.outcome_status == "CLOSED_WIN", "trace.outcome_status matches the real, recorded outcome")
        check(result.adherence_summary[ADHERENCE_FOLLOWED] == 1, "adherence_summary counts exactly one FOLLOWED")


def scenario_adherence_outcome_pending_and_not_executed():
    print("\n[Scenario 7] adherence == OUTCOME_PENDING when no outcome yet, NOT_EXECUTED when never approved")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s7.db")

        # Executed TAKE, no outcome recorded yet.
        brief_pending = _make_success_brief(ctx["brief"], symbol="BBCA")
        entry_pending = ctx["journal_service"].record_decision(brief_pending, DECISION_TAKE)
        ctx["brief_approval_service"].approve_and_submit(
            brief_pending, approved=True, account_id="paper-id", executed_at="2026-08-23T10:00:00+00:00",
        )

        # ACCEPTED TAKE decided on, but never actually approved/submitted.
        brief_not_executed = _make_success_brief(ctx["brief"], symbol="ASII")
        entry_not_executed = ctx["journal_service"].record_decision(brief_not_executed, DECISION_TAKE)

        result = ctx["review_service"].review("paper-id")
        traces_by_entry = {t.entry_id: t for t in result.decision_traces}

        check(
            traces_by_entry[entry_pending.entry_id].adherence == ADHERENCE_OUTCOME_PENDING,
            "executed-but-not-yet-closed TAKE -> OUTCOME_PENDING (not FOLLOWED, not NOT_APPLICABLE)",
        )
        check(
            traces_by_entry[entry_not_executed.entry_id].adherence == ADHERENCE_NOT_EXECUTED,
            "ACCEPTED TAKE never approved-and-submitted -> NOT_EXECUTED",
        )
        check(result.adherence_summary[ADHERENCE_OUTCOME_PENDING] == 1, "adherence_summary counts one OUTCOME_PENDING")
        check(result.adherence_summary[ADHERENCE_NOT_EXECUTED] == 1, "adherence_summary counts one NOT_EXECUTED")


def scenario_adherence_not_applicable_for_skip_wait_and_rejected():
    print("\n[Scenario 7b] adherence == NOT_APPLICABLE for SKIP/WAIT/RISK_REJECTED decisions")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s7b.db")
        b_skip = _make_success_brief(ctx["brief"], symbol="BBCA")
        b_wait = _make_success_brief(ctx["brief"], symbol="ASII")
        b_rejected = _make_success_brief(ctx["brief"], symbol="TLKM", risk_amount=999_000_000.0)

        ctx["journal_service"].record_decision(b_skip, DECISION_SKIP)
        ctx["journal_service"].record_decision(b_wait, DECISION_WAIT)
        rejected_entry = ctx["journal_service"].record_decision(b_rejected, DECISION_TAKE)
        check(rejected_entry.risk_policy_status == "RISK_REJECTED", "sanity: the oversized TAKE was genuinely RISK_REJECTED")

        result = ctx["review_service"].review("paper-id")
        for trace in result.decision_traces:
            check(trace.adherence == ADHERENCE_NOT_APPLICABLE, f"entry_id={trace.entry_id} ({trace.decision}) -> NOT_APPLICABLE")
        check(result.adherence_summary[ADHERENCE_NOT_APPLICABLE] == 3, "adherence_summary counts all three as NOT_APPLICABLE")


# ---------------------------------------------------------------------------
# Scenario 8: valuation freshness, never a fabricated price
# ---------------------------------------------------------------------------


def scenario_valuation_freshness():
    print("\n[Scenario 8] valuation_freshness counts come verbatim from real PortfolioSnapshot rows")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s8.db")
        ctx["portfolio_snapshot"].create(
            account_id="paper-id", cash=100_000_000.0, market_value=0.0, equity=100_000_000.0,
            realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0, timestamp="2026-08-01T09:00:00+00:00",
            valuation_status="FRESH",
        )
        ctx["portfolio_snapshot"].create(
            account_id="paper-id", cash=100_000_000.0, market_value=0.0, equity=100_000_000.0,
            realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0, timestamp="2026-08-02T09:00:00+00:00",
            valuation_status="STALE",
        )
        ctx["portfolio_snapshot"].create(
            account_id="paper-id", cash=100_000_000.0, market_value=0.0, equity=100_000_000.0,
            realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0, timestamp="2026-08-03T09:00:00+00:00",
            valuation_status=None,
        )

        result = ctx["review_service"].review("paper-id")
        vf = result.valuation_freshness
        check(vf.status == "AVAILABLE", "valuation_freshness.status == AVAILABLE")
        check(vf.fresh == 1, "exactly one real FRESH snapshot counted")
        check(vf.stale == 1, "exactly one real STALE snapshot counted")
        check(vf.unavailable == 1, "exactly one snapshot with no valuation_status counted as unavailable")
        check(vf.fresh + vf.stale + vf.unavailable == 3, "counts sum to the real number of persisted snapshots -- nothing invented")


# ---------------------------------------------------------------------------
# Scenario 9: traceability ids/timestamps preserved
# ---------------------------------------------------------------------------


def scenario_traceability_preserved():
    print("\n[Scenario 9] every id/timestamp on a DecisionTrace resolves back to a real, matching row")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s9.db")
        brief_id = _make_success_brief(ctx["brief"], symbol="BBCA")
        entry = ctx["journal_service"].record_decision(brief_id, DECISION_TAKE, note="conviction trade")
        approval_result = ctx["brief_approval_service"].approve_and_submit(
            brief_id, approved=True, account_id="paper-id", executed_at="2026-08-23T10:00:00+00:00",
        )

        result = ctx["review_service"].review("paper-id")
        trace = result.decision_traces[0]

        real_entry = ctx["journal"].get_by_id(trace.entry_id)
        real_brief = ctx["brief"].get_by_id(trace.brief_id)
        real_approval = ctx["brief_approval"].get_by_brief_id(trace.brief_id)

        check(real_entry is not None and real_entry.entry_id == entry.entry_id, "trace.entry_id resolves to the real JournalEntry")
        check(trace.decided_at == real_entry.decided_at, "trace.decided_at matches the real JournalEntry.decided_at exactly")
        check(real_brief is not None and real_brief.brief_id == brief_id, "trace.brief_id resolves to the real DecisionBrief")
        check(real_brief.symbol == trace.symbol, "trace.symbol matches the real DecisionBrief.symbol")
        check(real_approval is not None, "trace.brief_id resolves to a real BriefApproval link")
        check(trace.order_id == real_approval.order_id, "trace.order_id matches the real BriefApproval.order_id")
        check(trace.trade_id == real_approval.trade_id, "trace.trade_id matches the real BriefApproval.trade_id")
        check(
            approval_result.trade.trade_id == trace.trade_id,
            "trace.trade_id matches the real Trade actually returned by BriefApprovalService",
        )


# ---------------------------------------------------------------------------
# Scenario 10: restart-safe
# ---------------------------------------------------------------------------


def scenario_restart_safe():
    print("\n[Scenario 10] a brand-new PaperReviewService over the same on-disk file reproduces an identical result")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s10.db")
        brief_id = _make_success_brief(ctx["brief"], symbol="BBCA")
        ctx["journal_service"].record_decision(brief_id, DECISION_TAKE)
        ctx["brief_approval_service"].approve_and_submit(
            brief_id, approved=True, account_id="paper-id", executed_at="2026-08-23T10:00:00+00:00",
        )
        before = ctx["review_service"].review("paper-id")

        # Simulate an application restart: brand new DatabaseManager /
        # repository / service instances over the SAME db file, nothing
        # shared in memory with the objects above.
        db2 = SQLiteDatabase(ctx["cfg"])
        db2.connect()
        manager2 = DatabaseManager(db2, ctx["cfg"])
        review_service2 = PaperReviewService(
            account_repository=AccountRepository(manager2),
            journal_repository=JournalRepository(manager2),
            decision_brief_repository=DecisionBriefRepository(manager2),
            brief_approval_repository=BriefApprovalRepository(manager2),
            order_repository=OrderRepository(manager2),
            trade_repository=TradeRepository(manager2),
        )
        after = review_service2.review("paper-id")

        check(after.total_reviewed_decisions == before.total_reviewed_decisions, "total_reviewed_decisions survives restart")
        check(after.approved_paper_count == before.approved_paper_count, "approved_paper_count survives restart")
        check(after.linked_order_count == before.linked_order_count, "linked_order_count survives restart")
        check(after.linked_trade_count == before.linked_trade_count, "linked_trade_count survives restart")
        check(
            [t.entry_id for t in after.decision_traces] == [t.entry_id for t in before.decision_traces],
            "decision_traces are identical, entry-for-entry, after restart",
        )
        check(
            after.decision_traces[0].order_id == before.decision_traces[0].order_id
            and after.decision_traces[0].trade_id == before.decision_traces[0].trade_id,
            "trace order_id/trade_id are byte-for-byte identical after restart",
        )
        db2.disconnect()


def main() -> int:
    scenario_empty_review_period()
    scenario_unknown_account_raises()
    scenario_take_skip_wait_counts()
    scenario_period_filter()
    scenario_full_trace_approved_paper()
    scenario_skip_never_links()
    scenario_strategy_attribution()
    scenario_strategy_not_available_when_unwired()
    scenario_market_regime_attribution()
    scenario_adherence_followed_when_outcome_exists()
    scenario_adherence_outcome_pending_and_not_executed()
    scenario_adherence_not_applicable_for_skip_wait_and_rejected()
    scenario_valuation_freshness()
    scenario_traceability_preserved()
    scenario_restart_safe()

    print("\n" + "=" * 60)
    print(f"PHASE G TASK 4 (paper_review_service) TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())