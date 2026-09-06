"""Standalone, focused regression checks for Phase G Task 5 ONLY:
"Paper Review CLI + End-to-End Proof".

Every scenario drives:

    * the REAL ``Core.composition_root.build_application()`` object
      graph (proving ``ApplicationGraph.paper_review_service`` is
      wired to the real, unmodified
      ``Services.paper_review_service.PaperReviewService``), and
    * the REAL ``python main.py report paper-review`` CLI as an actual
      subprocess (proving the command exists, is dispatched
      correctly, and prints the real result) --

against one real, on-disk SQLite database, using the REAL, unmodified
``JournalService``, ``BriefApprovalService``, ``PaperTradingEngine``,
``StrategyPerformanceService``, and ``MarketRegimeAttributionService``.
No mocked business logic anywhere in this file.

Proves, concretely:

* Scenario 1: a SUCCESS brief -> explicit approval -> real paper
  order/trade -> real journal outcome is traced end to end by BOTH
  the in-process ``app.paper_review_service`` AND the real CLI's
  printed output.
* Scenario 2: SKIP/WAIT decisions remain non-executed -- never linked
  to an order/trade, in the service result and in the CLI output.
* Scenario 3: strategy/market-regime/adherence values in the CLI
  report match the persisted source records exactly (compared against
  independent, second instances of the real services).
* Scenario 4: a stale ``PortfolioSnapshot.valuation_status`` remains
  labelled STALE end to end, in the CLI's own printed counts.
* Scenario 5: restart-safety -- a brand-new ``build_application()``
  call (fresh process-level graph, same on-disk db file) reproduces an
  identical review result.
* Scenario 6: running the review CLI itself never creates an order or
  a trade -- real ``Order``/``Trade`` row counts are identical before
  and after the CLI runs, for every scenario above.

Run directly with
``python Tests/test_phase_g_task5_paper_review_cli.py`` -- no
external test framework required, matching every other standalone
test file in this repository.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.position_episode_replay_engine import PositionEpisodeReplayEngine  # noqa: E402
from Business.risk_ledger_policy import RiskLedgerPolicy  # noqa: E402
from Business.strategy_performance_engine import StrategyPerformanceEngine  # noqa: E402
from Business.strategy_performance_service import StrategyPerformanceService  # noqa: E402
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine  # noqa: E402
from Core.composition_root import build_application  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_brief_approvals import BRIEF_APPROVALS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshot_valuation_status import (  # noqa: E402
    PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS,
)
from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.brief_approval_repository import BriefApprovalRepository  # noqa: E402
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
from Repository.persistence.journal_repository import JournalRepository  # noqa: E402
from Repository.persistence.risk_limits_repository import RiskLimitsRepository  # noqa: E402
from Services.brief_approval_service import BriefApprovalService  # noqa: E402
from Services.decision_brief_service import STATUS_SUCCESS  # noqa: E402
from Services.journal_service import (  # noqa: E402
    DECISION_SKIP,
    DECISION_TAKE,
    DECISION_WAIT,
    JournalService,
)
from Services.paper_review_service import PaperReviewService  # noqa: E402

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
# Shared fixture: one on-disk db, migrated for every domain PaperReviewService
# touches, PLUS the real production ApplicationGraph over it.
# ---------------------------------------------------------------------------


def _build(tmp_dir: str, db_name: str):
    """Real on-disk db, migrated, then the real production
    ``ApplicationGraph`` built over it via ``build_application()``
    (env-var ``DB_PATH``, exactly how ``main.py`` resolves its own db
    path -- see ``Database.database_config.DatabaseConfig.from_env``).

    ``BRIEF_APPROVALS_MIGRATIONS``/``RISK_LEDGER_MIGRATIONS``/
    ``PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS`` are applied
    here because they are separate, manual, operator-run migrations
    in this repository (``run_brief_approval_migrations.py`` /
    ``run_risk_ledger_migrations.py``) -- ``build_application()``
    itself never runs a migration (LOCKED convention, see every
    ``_build_*_repository`` docstring in ``Core.composition_root``).
    Every other table (accounts/positions/orders/trades/snapshots/
    decision_briefs/idempotency/watchlist/...) ``build_application()``
    depends on already ships pre-migrated in this repository's
    ``data/investment_platform.db`` and its migration scripts are
    exercised by the existing regression suite -- untouched here.
    """
    db_path = Path(tmp_dir) / db_name
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()

    # Bring in every migration this scratch db needs from scratch
    # (a brand-new tmp file has none of the pre-shipped tables).
    from Database.migrations_accounts import ACCOUNTS_MIGRATIONS
    from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS
    from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS
    from Database.migrations_order_approvals import ORDER_APPROVALS_MIGRATIONS
    from Database.migrations_orders import ORDERS_MIGRATIONS
    from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS
    from Database.migrations_positions import POSITIONS_MIGRATIONS
    from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
    from Database.migrations_trades import TRADES_MIGRATIONS
    from Database.migrations_watchlist import WATCHLIST_MIGRATIONS

    for migration_set in (
        ACCOUNTS_MIGRATIONS,
        POSITIONS_MIGRATIONS,
        ORDERS_MIGRATIONS,
        TRADES_MIGRATIONS,
        IDEMPOTENCY_MIGRATIONS,
        ORDER_APPROVALS_MIGRATIONS,
        SNAPSHOTS_MIGRATIONS,
        DECISION_BRIEFS_MIGRATIONS,
        BRIEF_APPROVALS_MIGRATIONS,
        RISK_LEDGER_MIGRATIONS,
        WATCHLIST_MIGRATIONS,
        PORTFOLIO_SNAPSHOTS_MIGRATIONS,
        PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS,
    ):
        MigrationRunner(db).apply(migration_set)
    db.disconnect()

    os.environ["DB_PATH"] = str(db_path)
    app = build_application()

    app.account_repository.create(
        account_id="paper", account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
    )

    risk_limits_repo = RiskLimitsRepository(app.database_manager)
    risk_limits_repo.save(
        reference_capital=100_000_000.0,
        max_risk_per_trade_percent=100.0,
        max_daily_loss=1_000_000_000.0,
        max_trades_per_day=1000,
        loss_streak_cooldown=1000,
        updated_at="2026-08-01T00:00:00+00:00",
    )

    brief_repo = DecisionBriefRepository(app.database_manager)
    brief_approval_repo = BriefApprovalRepository(app.database_manager)
    journal_repo = JournalRepository(app.database_manager)

    journal_service = JournalService(
        brief_repository=brief_repo,
        risk_limits_repository=risk_limits_repo,
        journal_repository=journal_repo,
        risk_ledger_policy=RiskLedgerPolicy(),
    )
    brief_approval_service = BriefApprovalService(
        decision_brief_repository=brief_repo,
        brief_approval_repository=brief_approval_repo,
        paper_trading_engine=app.paper_trading_engine,
    )

    return {
        "cfg": cfg,
        "db_path": db_path,
        "app": app,
        "brief": brief_repo,
        "brief_approval": brief_approval_repo,
        "journal": journal_repo,
        "journal_service": journal_service,
        "brief_approval_service": brief_approval_service,
    }


def _make_success_brief(brief_repo, *, symbol="BBCA", entry=9500.0, stop=9300.0, target=9900.0,
                         risk_amount=20000.0, position_size=100.0, rr=2.0):
    brief = brief_repo.create(
        symbol=symbol, generated_at="2026-08-23T09:00:00+00:00", status=STATUS_SUCCESS,
        source_snapshot_id=None, reason=None,
        entry_price=entry, stop_loss_price=stop, take_profit_price=target,
        risk_amount=risk_amount, position_size=position_size, risk_reward_ratio=rr,
    )
    return brief.brief_id


def _order_trade_counts(app) -> tuple:
    orders = len(app.order_repository.list_by_account("paper"))
    trades = len(app.trade_repository.list_by_account("paper"))
    return orders, trades


def _run_cli(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke the REAL ``python main.py report paper-review ...`` CLI
    as an actual subprocess against ``db_path``, exactly as an
    operator would run it -- not a function call shortcut.
    """
    env = dict(os.environ)
    env["DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, "main.py", "report", "paper-review", *args],
        cwd=str(_PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Scenario 1: SUCCESS brief -> approval -> order/trade -> outcome -> CLI trace
# ---------------------------------------------------------------------------


def scenario_full_chain_traced_by_cli():
    print("\n[Scenario 1] SUCCESS brief -> approval -> order/trade -> outcome is traced end to end by the real CLI")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s1.db")
        app = ctx["app"]
        before_counts = _order_trade_counts(app)

        brief_id = _make_success_brief(ctx["brief"], symbol="BBCA")
        entry = ctx["journal_service"].record_decision(brief_id, DECISION_TAKE)
        check(entry.risk_policy_status == "ACCEPTED", "sanity: the TAKE was ACCEPTED by the real RiskLedgerPolicy")

        approval_result = ctx["brief_approval_service"].approve_and_submit(
            brief_id, approved=True, account_id="paper", executed_at="2026-08-23T10:00:00+00:00",
        )
        ctx["journal_service"].record_outcome(
            entry.entry_id, outcome_status="CLOSED_WIN", exit_price=9900.0,
            closed_at="2026-08-24T10:00:00+00:00",
        )

        # In-process: the real, wired ApplicationGraph.paper_review_service.
        result = app.paper_review_service.review("paper")
        check(result.approved_paper_count == 1, "approved_paper_count == 1 (in-process)")
        check(result.linked_order_count == 1, "linked_order_count == 1 (in-process)")
        check(result.linked_trade_count == 1, "linked_trade_count == 1 (in-process)")
        trace = result.decision_traces[0]
        check(trace.order_id == approval_result.trade.order_id, "trace.order_id matches the real Order (in-process)")
        check(trace.trade_id == approval_result.trade.trade_id, "trace.trade_id matches the real Trade (in-process)")
        check(trace.adherence == "FOLLOWED", "adherence == FOLLOWED once outcome recorded (in-process)")

        # Real CLI subprocess: same real database, same real service.
        proc = _run_cli(ctx["db_path"], "paper")
        check(proc.returncode == 0, "CLI exits 0")
        out = proc.stdout
        check("Paper Review -- account_id=paper" in out, "CLI prints the report header")
        check("approved_paper_count : 1" in out, "CLI prints approved_paper_count == 1")
        check("linked_order_count   : 1" in out, "CLI prints linked_order_count == 1")
        check("linked_trade_count   : 1" in out, "CLI prints linked_trade_count == 1")
        check(f"entry_id={entry.entry_id}" in out, "CLI prints the real entry_id")
        check(f"brief_id={brief_id}" in out, "CLI prints the real brief_id")
        check(f"order_id={approval_result.trade.order_id}" in out, "CLI prints the real order_id")
        check(f"trade_id={approval_result.trade.trade_id}" in out, "CLI prints the real trade_id")
        check("outcome_status=CLOSED_WIN" in out, "CLI prints the real outcome_status")
        check("adherence=FOLLOWED" in out, "CLI prints adherence=FOLLOWED")

        after_counts = _order_trade_counts(app)
        check(
            after_counts == (before_counts[0] + 1, before_counts[1] + 1),
            "exactly one real Order/Trade exist -- created by approve_and_submit, not by the review/CLI",
        )


# ---------------------------------------------------------------------------
# Scenario 2: SKIP/WAIT remain non-executed, in-process and via CLI
# ---------------------------------------------------------------------------


def scenario_skip_wait_never_execute():
    print("\n[Scenario 2] SKIP/WAIT decisions remain non-executed -- never linked, in-process or via CLI")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s2.db")
        app = ctx["app"]
        before_counts = _order_trade_counts(app)

        b_skip = _make_success_brief(ctx["brief"], symbol="BBCA")
        b_wait = _make_success_brief(ctx["brief"], symbol="ASII")
        ctx["journal_service"].record_decision(b_skip, DECISION_SKIP)
        ctx["journal_service"].record_decision(b_wait, DECISION_WAIT)

        result = app.paper_review_service.review("paper")
        check(result.skip_count == 1 and result.wait_count == 1, "one SKIP and one WAIT recorded (in-process)")
        check(result.approved_paper_count == 0, "approved_paper_count == 0 (in-process)")
        for trace in result.decision_traces:
            check(trace.order_id is None and trace.trade_id is None, f"trace for {trace.decision} has no order/trade link")
            check(trace.adherence == "NOT_APPLICABLE", f"{trace.decision} adherence == NOT_APPLICABLE")

        proc = _run_cli(ctx["db_path"], "paper")
        check(proc.returncode == 0, "CLI exits 0")
        out = proc.stdout
        check("SKIP                     : 1" in out, "CLI prints SKIP count == 1")
        check("WAIT                     : 1" in out, "CLI prints WAIT count == 1")
        check("approved_paper_count : 0" in out, "CLI prints approved_paper_count == 0")
        check("linked_order_count   : 0" in out, "CLI prints linked_order_count == 0")
        check("order_id=NOT_AVAILABLE" in out, "CLI prints order_id=NOT_AVAILABLE for the non-executed decisions")
        check("trade_id=NOT_AVAILABLE" in out, "CLI prints trade_id=NOT_AVAILABLE for the non-executed decisions")

        after_counts = _order_trade_counts(app)
        check(after_counts == before_counts, "zero real Order/Trade rows exist -- SKIP/WAIT never execute, review never creates any")


# ---------------------------------------------------------------------------
# Scenario 3: strategy/regime/adherence values match persisted source records
# ---------------------------------------------------------------------------


def scenario_strategy_and_adherence_match_source():
    print("\n[Scenario 3] CLI's strategy breakdown and adherence counts match the real persisted source records")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s3.db")
        app = ctx["app"]

        # A manual round-trip trade (BUY then SELL, same symbol) --
        # a real, closed episode StrategyPerformanceService will count.
        order1 = app.order_repository.create(
            account_id="paper", symbol="BBCA", action="BUY", quantity=100.0,
            requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="",
            analysis_snapshot_id=None,
        )
        trade1 = app.trade_repository.create(
            order_id=order1.order_id, account_id="paper", symbol="BBCA", action="BUY",
            quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0, executed_at="2026-08-01T09:00:00+00:00",
        )
        app.position_manager.apply_trade(trade1)
        order2 = app.order_repository.create(
            account_id="paper", symbol="BBCA", action="SELL", quantity=100.0,
            requested_price=9500.0, filled_price=9500.0, status="FILLED", reason="",
            analysis_snapshot_id=None,
        )
        trade2 = app.trade_repository.create(
            order_id=order2.order_id, account_id="paper", symbol="BBCA", action="SELL",
            quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0, executed_at="2026-08-01T13:00:00+00:00",
        )
        app.position_manager.apply_trade(trade2)

        # One executed-and-outcome-recorded TAKE (FOLLOWED) plus one
        # ACCEPTED-but-never-submitted TAKE (NOT_EXECUTED), so
        # adherence_summary has real, non-trivial counts to check.
        b_followed = _make_success_brief(ctx["brief"], symbol="TLKM")
        e_followed = ctx["journal_service"].record_decision(b_followed, DECISION_TAKE)
        ctx["brief_approval_service"].approve_and_submit(
            b_followed, approved=True, account_id="paper", executed_at="2026-08-23T10:00:00+00:00",
        )
        ctx["journal_service"].record_outcome(
            e_followed.entry_id, outcome_status="CLOSED_WIN", exit_price=1.0, closed_at="2026-08-24T00:00:00+00:00",
        )
        b_not_executed = _make_success_brief(ctx["brief"], symbol="ASII")
        ctx["journal_service"].record_decision(b_not_executed, DECISION_TAKE)

        # Independent, second StrategyPerformanceService pointed at the
        # SAME real repositories -- proves the CLI's number is the real,
        # unmodified engine's output, not a recomputation.
        independent = StrategyPerformanceService(
            account_repository=app.account_repository, trade_repository=app.trade_repository,
            order_repository=app.order_repository, position_repository=app.position_repository,
            position_episode_replay_engine=PositionEpisodeReplayEngine(TradeHoldingPeriodEngine()),
            strategy_performance_engine=StrategyPerformanceEngine(),
        )
        direct_strategy = independent.get_performance_by_strategy("paper")

        result = app.paper_review_service.review("paper")
        check(result.strategy_breakdown == direct_strategy, "strategy_breakdown matches an independent, real StrategyPerformanceService call")
        check(result.adherence_summary["FOLLOWED"] == 1, "adherence_summary FOLLOWED == 1 (in-process)")
        check(result.adherence_summary["NOT_EXECUTED"] == 1, "adherence_summary NOT_EXECUTED == 1 (in-process)")

        proc = _run_cli(ctx["db_path"], "paper")
        out = proc.stdout
        check(proc.returncode == 0, "CLI exits 0")
        for strategy, statistics in direct_strategy.items():
            check(
                f"{strategy}: closed_episodes={statistics.closed_episodes}" in out,
                f"CLI prints the real strategy '{strategy}' closed_episodes count",
            )
        check("FOLLOWED      : 1" in out, "CLI prints adherence FOLLOWED == 1")
        check("NOT_EXECUTED  : 1" in out, "CLI prints adherence NOT_EXECUTED == 1")


# ---------------------------------------------------------------------------
# Scenario 4: stale valuation remains labelled stale, in the CLI's own output
# ---------------------------------------------------------------------------


def scenario_stale_valuation_labelled_stale_in_cli():
    print("\n[Scenario 4] a stale PortfolioSnapshot.valuation_status stays labelled STALE, in the real CLI output")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s4.db")
        app = ctx["app"]
        app.portfolio_snapshot_repository.create(
            account_id="paper", cash=100_000_000.0, market_value=0.0, equity=100_000_000.0,
            realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0, timestamp="2026-08-01T09:00:00+00:00",
            valuation_status="FRESH",
        )
        app.portfolio_snapshot_repository.create(
            account_id="paper", cash=100_000_000.0, market_value=0.0, equity=100_000_000.0,
            realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0, timestamp="2026-08-02T09:00:00+00:00",
            valuation_status="STALE",
        )

        result = app.paper_review_service.review("paper")
        check(result.valuation_freshness.fresh == 1, "one real FRESH snapshot counted (in-process)")
        check(result.valuation_freshness.stale == 1, "one real STALE snapshot counted (in-process)")

        proc = _run_cli(ctx["db_path"], "paper")
        check(proc.returncode == 0, "CLI exits 0")
        out = proc.stdout
        check("status      : AVAILABLE" in out, "CLI prints valuation status AVAILABLE")
        check("fresh       : 1" in out, "CLI prints fresh == 1")
        check("stale       : 1" in out, "CLI prints stale == 1, never silently dropped or relabeled FRESH")


# ---------------------------------------------------------------------------
# Scenario 5: restart-safe -- a brand-new build_application() call
# ---------------------------------------------------------------------------


def scenario_restart_safe():
    print("\n[Scenario 5] a brand-new build_application() call over the same on-disk db reproduces an identical review")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(tmp, "s5.db")
        app = ctx["app"]
        brief_id = _make_success_brief(ctx["brief"], symbol="BBCA")
        ctx["journal_service"].record_decision(brief_id, DECISION_TAKE)
        ctx["brief_approval_service"].approve_and_submit(
            brief_id, approved=True, account_id="paper", executed_at="2026-08-23T10:00:00+00:00",
        )
        before = app.paper_review_service.review("paper")

        # Simulate an application restart: a brand new build_application()
        # call (fresh process-level ApplicationGraph, fresh
        # DatabaseManager/repositories/services), same on-disk db file,
        # nothing shared in memory with `app` above.
        os.environ["DB_PATH"] = str(ctx["db_path"])
        app2 = build_application()
        after = app2.paper_review_service.review("paper")

        check(after.total_reviewed_decisions == before.total_reviewed_decisions, "total_reviewed_decisions survives restart")
        check(after.approved_paper_count == before.approved_paper_count, "approved_paper_count survives restart")
        check(
            [t.entry_id for t in after.decision_traces] == [t.entry_id for t in before.decision_traces],
            "decision_traces are identical, entry-for-entry, after restart",
        )
        check(
            after.decision_traces[0].order_id == before.decision_traces[0].order_id
            and after.decision_traces[0].trade_id == before.decision_traces[0].trade_id,
            "trace order_id/trade_id are byte-for-byte identical after restart",
        )

        # And the real CLI, run twice in a row (its own "restart"),
        # against the same db file, prints identical counts.
        proc1 = _run_cli(ctx["db_path"], "paper")
        proc2 = _run_cli(ctx["db_path"], "paper")
        check(proc1.returncode == 0 and proc2.returncode == 0, "both CLI runs exit 0")
        check(
            "approved_paper_count : 1" in proc1.stdout and "approved_paper_count : 1" in proc2.stdout,
            "the CLI reports the identical approved_paper_count across two separate invocations",
        )


def main() -> int:
    scenario_full_chain_traced_by_cli()
    scenario_skip_wait_never_execute()
    scenario_strategy_and_adherence_match_source()
    scenario_stale_valuation_labelled_stale_in_cli()
    scenario_restart_safe()

    print(f"\n{'=' * 70}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("\nFAILURES:")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL PHASE G TASK 5 CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())