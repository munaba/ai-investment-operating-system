"""Standalone, focused regression checks for Phase H Task 2 ONLY:
"Sustained-Use Evidence Review" --
``Services.sustained_use_review_service.SustainedUseReviewService``.

Every scenario drives the REAL ``SustainedUseReviewService`` against a
real on-disk SQLite database, seeding real rows directly through the
already-existing, unmodified persistence repositories (mirroring
``Tests/test_observation_window.py``'s and
``Tests/test_phase_g_task4_paper_review_service.py``'s own fixture
style) -- no mocked business logic.

Covers:

* an empty ACTIVE window returns an honest, all-zero/NOT_AVAILABLE
  result -- never an error, never a fabricated non-zero count;
* a populated window: scheduler success/failure evidence, freshness
  degraded/recovered evidence, alert SEND/SUPPRESS(_NO_CHANGE/
  _RATE_LIMITED)/FAILED evidence, Telegram command evidence,
  DecisionBrief + JournalEntry + BriefApproval->Order->Trade linkage
  (via the real PaperReviewService), reconciliation
  available/unavailable, drawdown available/unavailable,
  strategy/regime available/unavailable;
* exact start/end window filtering (a record exactly on the boundary
  is included; a record just outside is excluded);
* explicit EXTERNAL_BLOCKED evidence for the broker/live-investigation
  dimension, always present;
* restart-safety: a brand new service instance (fresh repositories,
  fresh DatabaseManager, same on-disk file) reproduces an identical
  review result;
* this service never mutates any trading state (no repository write
  method is ever called by ``SustainedUseReviewService`` -- verified
  both behaviorally, via before/after row counts, and structurally,
  via a source-grep for write-method calls);
* every evidence item traces back to a real source id/timestamp still
  independently readable from its own repository.

Run directly with
``python Tests/test_phase_h_task2_sustained_use_review.py`` -- no
external test framework required, matching every other standalone
test file in this repository.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.reconciliation_engine import ReconciliationEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_brief_approvals import BRIEF_APPROVALS_MIGRATIONS  # noqa: E402
from Database.migrations_daily_performance import DAILY_PERFORMANCE_MIGRATIONS  # noqa: E402
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS  # noqa: E402
from Database.migrations_observation_window import OBSERVATION_WINDOW_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshot_valuation_status import (  # noqa: E402
    PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS,
)
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS  # noqa: E402
from Database.migrations_scheduler import SCHEDULER_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_telegram_control import TELEGRAM_CONTROL_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.audit_event_repository import AuditEventRepository  # noqa: E402
from Repository.persistence.brief_approval_repository import BriefApprovalRepository  # noqa: E402
from Repository.persistence.daily_performance_repository import (  # noqa: E402
    DailyPerformanceRepository,
)
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
from Repository.persistence.journal_repository import JournalRepository  # noqa: E402
from Repository.persistence.notification_dedup_repository import (  # noqa: E402
    NotificationDedupRepository,
)
from Repository.persistence.observation_window_repository import (  # noqa: E402
    ObservationWindowRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import (  # noqa: E402
    PortfolioSnapshotRepository,
)
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.scheduler_state_repository import SchedulerStateRepository  # noqa: E402
from Repository.persistence.telegram_command_audit_repository import (  # noqa: E402
    TelegramCommandAuditRepository,
)
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402
from Services.paper_review_service import PaperReviewService  # noqa: E402
from Services.sustained_use_review_service import (  # noqa: E402
    OVERALL_COMPLETE_EVIDENCE,
    OVERALL_PARTIAL_EVIDENCE,
    STATUS_AVAILABLE,
    STATUS_EXTERNAL_BLOCKED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NOT_AVAILABLE,
    SustainedUseReviewService,
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
# Fixture bootstrap
# ---------------------------------------------------------------------------

_ALL_MIGRATIONS = (
    OBSERVATION_WINDOW_MIGRATIONS,
    SCHEDULER_MIGRATIONS,
    TELEGRAM_CONTROL_MIGRATIONS,
    ACCOUNTS_MIGRATIONS,
    SNAPSHOTS_MIGRATIONS,
    DECISION_BRIEFS_MIGRATIONS,
    RISK_LEDGER_MIGRATIONS,
    ORDERS_MIGRATIONS,
    TRADES_MIGRATIONS,
    POSITIONS_MIGRATIONS,
    BRIEF_APPROVALS_MIGRATIONS,
    PORTFOLIO_SNAPSHOTS_MIGRATIONS,
    PORTFOLIO_SNAPSHOT_VALUATION_STATUS_MIGRATIONS,
    DAILY_PERFORMANCE_MIGRATIONS,
)


class Fixture:
    """One in-memory bag of repositories over a single on-disk SQLite
    file, plus convenience seed helpers. Mirrors the repository-bag
    pattern already used by ``Tests/test_phase_g_task4_paper_review_service.py``.
    """

    def __init__(self, db_path: Path) -> None:
        cfg = DatabaseConfig(db_path=db_path)
        db = SQLiteDatabase(cfg)
        db.connect()
        runner = MigrationRunner(db)
        for migrations in _ALL_MIGRATIONS:
            runner.apply(list(migrations))
        self.manager = DatabaseManager(db, cfg)

        self.window_repo = ObservationWindowRepository(self.manager)
        self.scheduler_repo = SchedulerStateRepository(self.manager)
        self.audit_repo = AuditEventRepository(self.manager)
        self.dedup_repo = NotificationDedupRepository(self.manager)
        self.telegram_repo = TelegramCommandAuditRepository(self.manager)
        self.account_repo = AccountRepository(self.manager)
        self.brief_repo = DecisionBriefRepository(self.manager)
        self.journal_repo = JournalRepository(self.manager)
        self.approval_repo = BriefApprovalRepository(self.manager)
        self.order_repo = OrderRepository(self.manager)
        self.trade_repo = TradeRepository(self.manager)
        self.position_repo = PositionRepository(self.manager)
        self.snapshot_repo = PortfolioSnapshotRepository(self.manager)
        self.daily_perf_repo = DailyPerformanceRepository(self.manager)

    def build_service(
        self,
        *,
        with_optional: bool = True,
        with_paper_review: bool = True,
        with_reconciliation: bool = True,
        with_daily_performance: bool = True,
        with_portfolio_snapshots: bool = True,
    ) -> SustainedUseReviewService:
        paper_review_service = None
        if with_paper_review:
            paper_review_service = PaperReviewService(
                account_repository=self.account_repo,
                journal_repository=self.journal_repo,
                decision_brief_repository=self.brief_repo,
                brief_approval_repository=self.approval_repo,
                order_repository=self.order_repo,
                trade_repository=self.trade_repo,
                portfolio_snapshot_repository=self.snapshot_repo if with_portfolio_snapshots else None,
            )
        reconciliation_engine = None
        if with_reconciliation:
            reconciliation_engine = ReconciliationEngine(
                order_repository=self.order_repo,
                trade_repository=self.trade_repo,
                account_repository=self.account_repo,
                position_repository=self.position_repo,
            )
        return SustainedUseReviewService(
            observation_window_repository=self.window_repo,
            scheduler_state_repository=self.scheduler_repo,
            audit_event_repository=self.audit_repo,
            notification_dedup_repository=self.dedup_repo if with_optional else None,
            telegram_command_audit_repository=self.telegram_repo if with_optional else None,
            decision_brief_repository=self.brief_repo if with_optional else None,
            journal_repository=self.journal_repo if with_optional else None,
            paper_review_service=paper_review_service,
            reconciliation_engine=reconciliation_engine,
            daily_performance_repository=self.daily_perf_repo if with_daily_performance else None,
            portfolio_snapshot_repository=self.snapshot_repo if with_portfolio_snapshots else None,
        )

    def open_window(self, start_at: str, end_at: str) -> int:
        window = self.window_repo.create(
            start_at=start_at,
            end_at=end_at,
            timezone="Asia/Jakarta",
            created_at="2026-08-24T00:00:00+00:00",
        )
        return window.window_id

    def seed_account(self, account_id: str = "paper-id") -> None:
        self.account_repo.create(
            account_id=account_id,
            account_name="Paper Trading",
            mode="paper",
            currency="IDR",
            asset_class="stock_id",
            cash=100_000_000.0,
            equity=100_000_000.0,
            buying_power=100_000_000.0,
        )


def _fresh_fixture(tmp_dir: str) -> Fixture:
    return Fixture(Path(tmp_dir) / "aios.db")


# ---------------------------------------------------------------------------
# Scenario 1: empty ACTIVE window
# ---------------------------------------------------------------------------


def scenario_empty_active_window():
    print("\n[Scenario 1] empty ACTIVE window -> honest all-zero / NOT_AVAILABLE result")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        service = fx.build_service(with_optional=False, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)

        result = service.generate_review()

        check(result.window.start_at == "2026-08-24T00:00:00", "window metadata start_at preserved verbatim")
        check(result.window.end_at == "2026-09-23T23:59:59", "window metadata end_at preserved verbatim")
        check(result.window.timezone == "Asia/Jakarta", "window metadata timezone preserved verbatim")
        check(result.window.window_status == "ACTIVE", "window metadata status is ACTIVE")

        check(result.availability.status == STATUS_AVAILABLE, "availability is AVAILABLE (required collaborator) even when empty")
        check(result.availability.scheduled_job_count == 0, "availability scheduled_job_count is honestly 0")
        check(len(result.availability.job_runs) == 0, "availability job_runs is empty, not fabricated")

        check(result.data_freshness.valuation_snapshot_status == STATUS_NOT_AVAILABLE,
              "data_freshness valuation_snapshot_status is NOT_AVAILABLE with no portfolio_snapshot_repository/account_id")
        check(result.data_freshness.fresh_snapshot_count == 0, "data_freshness fresh count is 0, not fabricated")

        check(result.alert_usefulness.status == STATUS_AVAILABLE, "alert_usefulness top status is AVAILABLE (required audit repo)")
        check(result.alert_usefulness.telegram_status == STATUS_NOT_AVAILABLE,
              "alert_usefulness telegram_status is NOT_AVAILABLE with no telegram repo supplied")

        check(result.plan_journal_adherence.status == STATUS_NOT_AVAILABLE,
              "plan_journal_adherence is NOT_AVAILABLE with no brief/journal repos supplied")
        check(result.plan_journal_adherence.paper_review_status == STATUS_NOT_AVAILABLE,
              "plan_journal_adherence.paper_review_status is NOT_AVAILABLE with no PaperReviewService")

        check(result.paper_reconciliation.status == STATUS_NOT_AVAILABLE,
              "paper_reconciliation is NOT_AVAILABLE with no reconciliation_engine/account_id")
        check(result.drawdown_process.status == STATUS_NOT_AVAILABLE,
              "drawdown_process is NOT_AVAILABLE with no daily_performance_repository/account_id")
        check(result.strategy_regime.status == STATUS_NOT_AVAILABLE,
              "strategy_regime is NOT_AVAILABLE with no PaperReviewService/account_id")

        check(result.overall_evidence_status == OVERALL_PARTIAL_EVIDENCE,
              "overall_evidence_status is PARTIAL_EVIDENCE when several dimensions are NOT_AVAILABLE")

        blocked = [lim for lim in result.known_limitations if lim.status == STATUS_EXTERNAL_BLOCKED]
        check(len(blocked) == 1, "exactly one EXTERNAL_BLOCKED known-limitation entry is always present")
        check(blocked[0].dimension == "broker_live_market_investigation",
              "the EXTERNAL_BLOCKED entry names the broker/live-investigation dimension")

        not_avail = [lim for lim in result.known_limitations if lim.status == STATUS_NOT_AVAILABLE]
        check(len(not_avail) >= 5, "every NOT_AVAILABLE dimension gets its own known_limitations entry")


# ---------------------------------------------------------------------------
# Scenario 2: no ACTIVE window and no window_id -> explicit error, never a guess
# ---------------------------------------------------------------------------


def scenario_no_window_raises():
    print("\n[Scenario 2] no ACTIVE window and no window_id supplied -> ValidationError, never a guess")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        service = fx.build_service(with_optional=False, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        try:
            service.generate_review()
            check(False, "generate_review() raises when no window is ACTIVE and none is specified")
        except ValidationError:
            check(True, "generate_review() raises ValidationError when no window is ACTIVE and none is specified")

        try:
            service.generate_review(window_id=999)
            check(False, "generate_review(window_id=...) raises for a non-existent window_id")
        except ValidationError:
            check(True, "generate_review(window_id=...) raises ValidationError for a non-existent window_id")


# ---------------------------------------------------------------------------
# Scenario 3: scheduler availability evidence (success/failure) + exact date filtering
# ---------------------------------------------------------------------------


def scenario_scheduler_availability_evidence():
    print("\n[Scenario 3] scheduler job success/failure evidence, filtered to the window's trading-date range")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")

        # Inside the window.
        fx.scheduler_repo.start("pre_market_check", "2026-08-24", started_at="2026-08-24T01:00:00+00:00")
        fx.scheduler_repo.mark_success(
            "pre_market_check", "2026-08-24", finished_at="2026-08-24T01:00:05+00:00"
        )
        fx.scheduler_repo.start("session_scan", "2026-09-23", started_at="2026-09-23T02:00:00+00:00")
        fx.scheduler_repo.mark_failed(
            "session_scan", "2026-09-23", finished_at="2026-09-23T02:00:05+00:00", detail="provider timeout"
        )

        # Exactly on the boundary date (inclusive both ends).
        fx.scheduler_repo.start("data_health_check", "2026-08-24", started_at="2026-08-24T00:00:01+00:00")
        fx.scheduler_repo.mark_success(
            "data_health_check", "2026-08-24", finished_at="2026-08-24T00:00:02+00:00"
        )

        # Outside the window (before start).
        fx.scheduler_repo.start("pre_market_check", "2026-08-23", started_at="2026-08-23T01:00:00+00:00")
        fx.scheduler_repo.mark_success(
            "pre_market_check", "2026-08-23", finished_at="2026-08-23T01:00:05+00:00"
        )
        # Outside the window (after end).
        fx.scheduler_repo.start("market_close_recap", "2026-09-24", started_at="2026-09-24T09:00:00+00:00")
        fx.scheduler_repo.mark_success(
            "market_close_recap", "2026-09-24", finished_at="2026-09-24T09:00:05+00:00"
        )

        service = fx.build_service(with_optional=False, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        result = service.generate_review()

        check(result.availability.scheduled_job_count == 3, "3 job runs fall inside the window (2 outside excluded)")
        check(result.availability.success_count == 2, "2 SUCCESS runs counted inside the window")
        check(result.availability.failure_count == 1, "1 FAILED run counted inside the window")
        job_types = {run.job_type for run in result.availability.job_runs}
        check(job_types == {"pre_market_check", "session_scan", "data_health_check"},
              "in-window job_runs preserve their real job_type/trading_date identity")
        check(all(run.trading_date != "2026-08-23" and run.trading_date != "2026-09-24"
                   for run in result.availability.job_runs),
              "out-of-window trading dates are excluded")


# ---------------------------------------------------------------------------
# Scenario 4: data freshness degradation/recovery evidence
# ---------------------------------------------------------------------------


def scenario_freshness_evidence():
    print("\n[Scenario 4] freshness degradation/recovery audit evidence")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")

        fx.audit_repo.record(
            "freshness_degraded", created_at="2026-08-25T03:00:00+00:00",
            payload={"source": "market_price_tool", "reason": "provider stale"},
        )
        fx.audit_repo.record(
            "freshness_recovered", created_at="2026-08-25T04:00:00+00:00",
            payload={"source": "market_price_tool"},
        )
        # Outside the window.
        fx.audit_repo.record(
            "freshness_degraded", created_at="2026-10-01T03:00:00+00:00", payload={},
        )

        service = fx.build_service(with_optional=False, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        result = service.generate_review()

        check(len(result.data_freshness.freshness_degraded_events) == 1,
              "exactly 1 in-window freshness_degraded event captured")
        check(len(result.data_freshness.freshness_recovered_events) == 1,
              "exactly 1 in-window freshness_recovered event captured")
        degraded_event = result.data_freshness.freshness_degraded_events[0]
        check(degraded_event.id is not None, "freshness_degraded evidence preserves its real audit_events.id")
        check(degraded_event.created_at == "2026-08-25T03:00:00+00:00",
              "freshness_degraded evidence preserves its real created_at timestamp")


# ---------------------------------------------------------------------------
# Scenario 5: alert dedup evidence (SEND/SUPPRESS_NO_CHANGE/SUPPRESS_RATE_LIMITED/FAILED)
# ---------------------------------------------------------------------------


def scenario_alert_dedup_evidence():
    print("\n[Scenario 5] alert SEND/SUPPRESS(_NO_CHANGE/_RATE_LIMITED)/FAILED evidence")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")

        fx.audit_repo.record(
            "notification_sent", created_at="2026-08-25T05:00:00+00:00",
            payload={"alert_type": "session_scan_brief", "signature": "sig-1"},
        )
        fx.audit_repo.record(
            "notification_suppressed", created_at="2026-08-25T06:00:00+00:00",
            payload={
                "alert_type": "session_scan_brief",
                "signature": "sig-1",
                "reason": "signature unchanged since the last sent alert",
            },
        )
        fx.audit_repo.record(
            "notification_suppressed", created_at="2026-08-25T07:00:00+00:00",
            payload={
                "alert_type": "data_freshness",
                "signature": "sig-2",
                "reason": "signature changed but only 30s elapsed since the last send (< 1800s rate limit)",
            },
        )
        fx.audit_repo.record(
            "notification_failed", created_at="2026-08-25T08:00:00+00:00",
            payload={"alert_type": "session_scan_brief", "signature": "sig-3", "error": "network down"},
        )
        fx.dedup_repo.record(
            "session_scan_brief", last_status="SENT",
            updated_at="2026-08-25T05:00:00+00:00",
            last_signature="sig-1", last_sent_at="2026-08-25T05:00:00+00:00",
        )

        service = fx.build_service(with_optional=True, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        result = service.generate_review()

        check(result.alert_usefulness.sent_count == 1, "1 SENT event counted")
        check(result.alert_usefulness.suppress_no_change_count == 1,
              "1 event correctly classified SUPPRESS_NO_CHANGE from its real persisted reason text")
        check(result.alert_usefulness.suppress_rate_limited_count == 1,
              "1 event correctly classified SUPPRESS_RATE_LIMITED from its real persisted reason text")
        check(result.alert_usefulness.other_suppressed_count == 0, "no suppression events fall through to OTHER")
        check(result.alert_usefulness.failed_count == 1, "1 FAILED event counted")
        check(len(result.alert_usefulness.notification_events) == 4, "all 4 in-window notification events preserved")
        check(len(result.alert_usefulness.dedup_states) == 1,
              "current dedup state row is included (not window-scoped, documented)")


# ---------------------------------------------------------------------------
# Scenario 6: Telegram command audit evidence
# ---------------------------------------------------------------------------


def scenario_telegram_command_evidence():
    print("\n[Scenario 6] Telegram command audit evidence")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")

        fx.telegram_repo.record(
            "/status", status="EXECUTED", received_at="2026-08-26T10:00:00+00:00",
            update_id=1, chat_id="chat-1", raw_text="/status",
        )
        fx.telegram_repo.record(
            "/unknown", status="UNKNOWN_COMMAND", received_at="2026-08-27T11:00:00+00:00",
            update_id=2, chat_id="chat-1", raw_text="/unknown",
        )
        # Outside the window.
        fx.telegram_repo.record(
            "/status", status="EXECUTED", received_at="2026-10-05T10:00:00+00:00",
            update_id=3, chat_id="chat-1",
        )

        service = fx.build_service(with_optional=True, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        result = service.generate_review()

        check(result.alert_usefulness.telegram_status == STATUS_AVAILABLE,
              "telegram_status is AVAILABLE once a TelegramCommandAuditRepository is supplied")
        check(result.alert_usefulness.command_audit_count == 2, "2 in-window Telegram commands counted")
        commands = {c.command for c in result.alert_usefulness.command_audits}
        check(commands == {"/status", "/unknown"}, "in-window command identities preserved")


# ---------------------------------------------------------------------------
# Scenario 7: DecisionBrief + JournalEntry + paper linkage (via PaperReviewService)
# ---------------------------------------------------------------------------


def scenario_plan_journal_and_paper_linkage():
    print("\n[Scenario 7] DecisionBrief + JournalEntry + BriefApproval->Order->Trade linkage")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")

        brief = fx.brief_repo.create(
            "BBCA", "2026-08-26T02:00:00+00:00", "SUCCESS",
            entry_price=9000.0, stop_loss_price=8800.0, take_profit_price=9400.0,
            risk_amount=50000.0, position_size=25.0, risk_reward_ratio=2.0,
        )
        skip_brief = fx.brief_repo.create("TLKM", "2026-08-27T02:00:00+00:00", "NO_TRADE", reason="no setup")

        entry = fx.journal_repo.create(
            brief_id=brief.brief_id, symbol="BBCA", decision="TAKE",
            decided_at="2026-08-26T02:05:00+00:00", risk_policy_status="ACCEPTED",
            created_at="2026-08-26T02:05:00+00:00", planned_r=2.0,
        )
        fx.journal_repo.create(
            brief_id=skip_brief.brief_id, symbol="TLKM", decision="SKIP",
            decided_at="2026-08-27T02:05:00+00:00", risk_policy_status="ACCEPTED",
            created_at="2026-08-27T02:05:00+00:00",
        )

        order = fx.order_repo.create(
            account_id="paper-id", symbol="BBCA", action="BUY", quantity=25.0,
            requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="brief TAKE",
            filled_quantity=25.0,
        )
        trade = fx.trade_repo.create(
            order_id=order.order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=25.0, fill_price=9000.0, fee=1000.0, tax=0.0,
            executed_at="2026-08-26T02:06:00+00:00",
        )
        fx.approval_repo.create(brief.brief_id, order.order_id, trade.trade_id, approved_at="2026-08-26T02:06:00+00:00")

        service = fx.build_service(with_optional=True, with_paper_review=True,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=True)
        result = service.generate_review(account_id="paper-id")

        pja = result.plan_journal_adherence
        check(pja.status == STATUS_AVAILABLE, "plan_journal_adherence is AVAILABLE with brief/journal repos supplied")
        check(len(pja.briefs_in_window) == 2, "both real briefs in the window are captured")
        check(pja.brief_status_counts.get("SUCCESS") == 1, "brief_status_counts reflects the real SUCCESS brief")
        check(pja.brief_status_counts.get("NO_TRADE") == 1, "brief_status_counts reflects the real NO_TRADE brief")
        check(len(pja.journal_entries_in_window) == 2, "both real journal entries in the window are captured")
        check(pja.take_count == 1, "take_count matches the real TAKE entry")
        check(pja.skip_count == 1, "skip_count matches the real SKIP entry")
        check(pja.wait_count == 0, "wait_count is honestly 0")

        check(pja.paper_review_status == STATUS_AVAILABLE, "paper_review_status is AVAILABLE once PaperReviewService+account_id are supplied")
        check(pja.approved_paper_count == 1, "approved_paper_count is the real PaperReviewService output")
        check(pja.linked_order_count == 1, "linked_order_count is the real PaperReviewService output")
        check(pja.linked_trade_count == 1, "linked_trade_count is the real PaperReviewService output")
        check(pja.adherence_summary is not None and sum(pja.adherence_summary.values()) == 2,
              "adherence_summary is the real PaperReviewService output, covering both decisions")

        check(entry.entry_id in {e.entry_id for e in pja.journal_entries_in_window},
              "the real JournalEntry.entry_id is traceable inside the evidence tuple")


# ---------------------------------------------------------------------------
# Scenario 8: paper reconciliation available/unavailable
# ---------------------------------------------------------------------------


def scenario_reconciliation_available_and_unavailable():
    print("\n[Scenario 8] paper reconciliation available/unavailable")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")

        service_no_engine = fx.build_service(with_optional=False, with_paper_review=False,
                                              with_reconciliation=False, with_daily_performance=False,
                                              with_portfolio_snapshots=False)
        result_no_engine = service_no_engine.generate_review(account_id="paper-id")
        check(result_no_engine.paper_reconciliation.status == STATUS_NOT_AVAILABLE,
              "paper_reconciliation is NOT_AVAILABLE when no reconciliation_engine is supplied")

        service = fx.build_service(with_optional=False, with_paper_review=False,
                                    with_reconciliation=True, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        result = service.generate_review(account_id="paper-id", starting_cash=100_000_000.0)
        check(result.paper_reconciliation.status == STATUS_AVAILABLE,
              "paper_reconciliation is AVAILABLE once a reconciliation_engine + account_id are supplied")
        check(result.paper_reconciliation.consistent is True,
              "a freshly-created, untouched account reconciles as CONSISTENT")
        check(len(result.paper_reconciliation.violations) == 0, "no violations for an untouched account")

        result_no_account = service.generate_review()
        check(result_no_account.paper_reconciliation.status == STATUS_NOT_AVAILABLE,
              "paper_reconciliation is NOT_AVAILABLE when no account_id is supplied, even with an engine")


# ---------------------------------------------------------------------------
# Scenario 9: drawdown/process available/unavailable + insufficient data
# ---------------------------------------------------------------------------


def scenario_drawdown_available_and_unavailable():
    print("\n[Scenario 9] drawdown/process AVAILABLE / INSUFFICIENT_DATA / NOT_AVAILABLE")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")

        service_no_repo = fx.build_service(with_optional=False, with_paper_review=False,
                                            with_reconciliation=False, with_daily_performance=False,
                                            with_portfolio_snapshots=False)
        result_no_repo = service_no_repo.generate_review(account_id="paper-id")
        check(result_no_repo.drawdown_process.status == STATUS_NOT_AVAILABLE,
              "drawdown_process is NOT_AVAILABLE with no daily_performance_repository")

        service = fx.build_service(with_optional=False, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=True,
                                    with_portfolio_snapshots=False)
        result_empty = service.generate_review(account_id="paper-id")
        check(result_empty.drawdown_process.status == STATUS_INSUFFICIENT_DATA,
              "drawdown_process is INSUFFICIENT_DATA when the repository exists but has no in-window rows")

        fx.daily_perf_repo.create(
            account_id="paper-id",
            start_timestamp="2026-08-25T00:00:00+00:00",
            end_timestamp="2026-08-25T23:59:59+00:00",
            realized_result=10000.0, unrealized_result=0.0, fees=500.0, tax=0.0,
            net_result=9500.0, drawdown=0.02, number_of_executions=1,
            timestamp="2026-08-26T00:00:00+00:00",
        )
        result = service.generate_review(account_id="paper-id")
        check(result.drawdown_process.status == STATUS_AVAILABLE,
              "drawdown_process is AVAILABLE once a real in-window DailyPerformance row exists")
        check(len(result.drawdown_process.records) == 1, "the real DailyPerformance row is included")
        check(result.drawdown_process.records[0].drawdown == 0.02,
              "the real, persisted drawdown value is preserved verbatim, never recomputed")


# ---------------------------------------------------------------------------
# Scenario 10: strategy/regime available/unavailable
# ---------------------------------------------------------------------------


def scenario_strategy_regime_available_and_unavailable():
    print("\n[Scenario 10] strategy/regime AVAILABLE (pass-through) / NOT_AVAILABLE")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")

        service_no_review = fx.build_service(with_optional=False, with_paper_review=False,
                                              with_reconciliation=False, with_daily_performance=False,
                                              with_portfolio_snapshots=False)
        result_no_review = service_no_review.generate_review(account_id="paper-id")
        check(result_no_review.strategy_regime.status == STATUS_NOT_AVAILABLE,
              "strategy_regime is NOT_AVAILABLE with no PaperReviewService supplied")

        service = fx.build_service(with_optional=False, with_paper_review=True,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        result = service.generate_review(account_id="paper-id")
        check(result.strategy_regime.status == STATUS_AVAILABLE,
              "strategy_regime is AVAILABLE once PaperReviewService + account_id are supplied")
        # PaperReviewService itself was built with no strategy/market-regime
        # engine injected, so its own verbatim output is the NOT_AVAILABLE
        # sentinel string -- proving this is a true pass-through, not a
        # reinvented computation.
        check(result.strategy_regime.strategy_breakdown == "NOT_AVAILABLE",
              "strategy_breakdown is PaperReviewService's own verbatim NOT_AVAILABLE sentinel")
        check(result.strategy_regime.market_regime_breakdown == "NOT_AVAILABLE",
              "market_regime_breakdown is PaperReviewService's own verbatim NOT_AVAILABLE sentinel")

        result_no_account = service.generate_review()
        check(result_no_account.strategy_regime.status == STATUS_NOT_AVAILABLE,
              "strategy_regime is NOT_AVAILABLE when no account_id is supplied, even with PaperReviewService")


# ---------------------------------------------------------------------------
# Scenario 11: exact start/end boundary filtering
# ---------------------------------------------------------------------------


def scenario_exact_boundary_filtering():
    print("\n[Scenario 11] exact start/end boundary filtering (inclusive both ends)")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")

        fx.audit_repo.record("freshness_degraded", created_at="2026-08-24T00:00:00", payload={})
        fx.audit_repo.record("freshness_recovered", created_at="2026-09-23T23:59:59", payload={})
        fx.audit_repo.record("freshness_degraded", created_at="2026-08-23T23:59:59", payload={})
        fx.audit_repo.record("freshness_recovered", created_at="2026-09-24T00:00:00", payload={})

        service = fx.build_service(with_optional=False, with_paper_review=False,
                                    with_reconciliation=False, with_daily_performance=False,
                                    with_portfolio_snapshots=False)
        result = service.generate_review()

        check(len(result.data_freshness.freshness_degraded_events) == 1,
              "the degraded event exactly ON start_at is included; the one just before is excluded")
        check(result.data_freshness.freshness_degraded_events[0].created_at == "2026-08-24T00:00:00",
              "the included degraded event is the exact-boundary one")
        check(len(result.data_freshness.freshness_recovered_events) == 1,
              "the recovered event exactly ON end_at is included; the one just after is excluded")
        check(result.data_freshness.freshness_recovered_events[0].created_at == "2026-09-23T23:59:59",
              "the included recovered event is the exact-boundary one")


# ---------------------------------------------------------------------------
# Scenario 12: external-blocked evidence always present
# ---------------------------------------------------------------------------


def scenario_external_blocked_always_present():
    print("\n[Scenario 12] EXTERNAL_BLOCKED evidence is always present regardless of what else is wired")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")

        # Fully wired service -- every optional collaborator supplied.
        service = fx.build_service()
        result = service.generate_review(account_id="paper-id", starting_cash=100_000_000.0)

        blocked = [lim for lim in result.known_limitations if lim.status == STATUS_EXTERNAL_BLOCKED]
        check(len(blocked) == 1,
              "the EXTERNAL_BLOCKED broker/live-investigation entry is present even with everything else wired")
        check("future" in blocked[0].detail.lower() or "separate" in blocked[0].detail.lower(),
              "the EXTERNAL_BLOCKED entry documents that this is a deferred, separate, human decision")


# ---------------------------------------------------------------------------
# Scenario 13: restart-safety
# ---------------------------------------------------------------------------


def scenario_restart_safety():
    print("\n[Scenario 13] restart-safe: a brand-new service instance reproduces an identical review")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        fx = Fixture(db_path)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")
        fx.scheduler_repo.start("pre_market_check", "2026-08-24", started_at="2026-08-24T01:00:00+00:00")
        fx.scheduler_repo.mark_success("pre_market_check", "2026-08-24", finished_at="2026-08-24T01:00:05+00:00")
        fx.audit_repo.record("freshness_degraded", created_at="2026-08-25T00:00:00+00:00", payload={"x": 1})

        service_1 = fx.build_service(with_optional=False, with_paper_review=False,
                                      with_reconciliation=False, with_daily_performance=False,
                                      with_portfolio_snapshots=False)
        result_1 = service_1.generate_review()

        # Fresh connection/repositories/service over the SAME on-disk file --
        # simulates a process restart, never reusing the original in-memory
        # objects.
        fx2 = Fixture(db_path)
        service_2 = fx2.build_service(with_optional=False, with_paper_review=False,
                                       with_reconciliation=False, with_daily_performance=False,
                                       with_portfolio_snapshots=False)
        result_2 = service_2.generate_review()

        check(result_1.window.window_id == result_2.window.window_id, "restart reproduces the same window_id")
        check(result_1.availability.scheduled_job_count == result_2.availability.scheduled_job_count,
              "restart reproduces the same availability evidence")
        check(len(result_1.data_freshness.freshness_degraded_events) == len(result_2.data_freshness.freshness_degraded_events),
              "restart reproduces the same freshness evidence")


# ---------------------------------------------------------------------------
# Scenario 14: no trading-state mutation
# ---------------------------------------------------------------------------


def scenario_no_trading_state_mutation():
    print("\n[Scenario 14] SustainedUseReviewService never mutates any trading/audit state")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")

        order = fx.order_repo.create(
            account_id="paper-id", symbol="BBCA", action="BUY", quantity=10.0,
            requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="seed",
            filled_quantity=10.0,
        )
        fx.trade_repo.create(
            order_id=order.order_id, account_id="paper-id", symbol="BBCA", action="BUY",
            quantity=10.0, fill_price=9000.0, fee=100.0, tax=0.0,
            executed_at="2026-08-26T02:06:00+00:00",
        )
        fx.scheduler_repo.start("pre_market_check", "2026-08-24", started_at="2026-08-24T01:00:00+00:00")
        fx.audit_repo.record("freshness_degraded", created_at="2026-08-25T00:00:00+00:00", payload={})

        before_orders = len(fx.order_repo.list_all())
        before_trades = len(fx.trade_repo.list_all())
        before_jobs = len(fx.scheduler_repo.list_all())
        before_events = len(fx.audit_repo.list_all())
        before_windows = len(fx.window_repo.list_all())
        before_account = fx.account_repo.get_by_id("paper-id")

        service = fx.build_service()
        service.generate_review(account_id="paper-id", starting_cash=100_000_000.0)
        service.generate_review(account_id="paper-id", starting_cash=100_000_000.0)  # run twice

        check(len(fx.order_repo.list_all()) == before_orders, "no Order row was created/changed by review")
        check(len(fx.trade_repo.list_all()) == before_trades, "no Trade row was created/changed by review")
        check(len(fx.scheduler_repo.list_all()) == before_jobs, "no SchedulerJobRun row was created/changed by review")
        check(len(fx.audit_repo.list_all()) == before_events, "no AuditEvent row was created by review itself")
        check(len(fx.window_repo.list_all()) == before_windows, "no ObservationWindow row was created/changed by review")
        after_account = fx.account_repo.get_by_id("paper-id")
        check(after_account.cash == before_account.cash, "Account.cash is untouched by review")

        # Structural guarantee: grep the service source for any write-method
        # call against a repository/engine it holds.
        src = Path(_PROJECT_ROOT, "Services", "sustained_use_review_service.py").read_text()
        write_calls = [
            ".create(", ".update(", ".update_status(", ".update_balances(",
            ".record_fill(", ".close(", ".record(", "submit_order(",
        ]
        offenders = [call for call in write_calls if call in src]
        check(offenders == [], f"no write-method call appears anywhere in the service source (found: {offenders})")


# ---------------------------------------------------------------------------
# Scenario 15: overall_evidence_status reflects full vs partial evidence
# ---------------------------------------------------------------------------


def scenario_overall_status_complete_vs_partial():
    print("\n[Scenario 15] overall_evidence_status: COMPLETE_EVIDENCE only when every optional dimension is wired+populated")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        fx.open_window("2026-08-24T00:00:00", "2026-09-23T23:59:59")
        fx.seed_account("paper-id")

        fx.daily_perf_repo.create(
            account_id="paper-id",
            start_timestamp="2026-08-25T00:00:00+00:00",
            end_timestamp="2026-08-25T23:59:59+00:00",
            realized_result=0.0, unrealized_result=0.0, fees=0.0, tax=0.0,
            net_result=0.0, drawdown=0.0, number_of_executions=0,
            timestamp="2026-08-26T00:00:00+00:00",
        )
        fx.snapshot_repo.create(
            account_id="paper-id", cash=100_000_000.0, market_value=0.0, equity=100_000_000.0,
            realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
            timestamp="2026-08-26T00:00:00+00:00", valuation_status="FRESH",
        )

        service = fx.build_service()
        result = service.generate_review(account_id="paper-id", starting_cash=100_000_000.0)

        check(result.overall_evidence_status == OVERALL_COMPLETE_EVIDENCE,
              "overall_evidence_status is COMPLETE_EVIDENCE once every optional dimension is wired and populated")

        service_partial = fx.build_service(with_daily_performance=False)
        result_partial = service_partial.generate_review(account_id="paper-id", starting_cash=100_000_000.0)
        check(result_partial.overall_evidence_status == OVERALL_PARTIAL_EVIDENCE,
              "overall_evidence_status falls back to PARTIAL_EVIDENCE when even one dimension is unwired")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scenario_empty_active_window()
    scenario_no_window_raises()
    scenario_scheduler_availability_evidence()
    scenario_freshness_evidence()
    scenario_alert_dedup_evidence()
    scenario_telegram_command_evidence()
    scenario_plan_journal_and_paper_linkage()
    scenario_reconciliation_available_and_unavailable()
    scenario_drawdown_available_and_unavailable()
    scenario_strategy_regime_available_and_unavailable()
    scenario_exact_boundary_filtering()
    scenario_external_blocked_always_present()
    scenario_restart_safety()
    scenario_no_trading_state_mutation()
    scenario_overall_status_complete_vs_partial()

    print(f"\n{'=' * 70}")
    print(f"RESULTS: {_PASS} passed, {_FAIL} failed (of {_PASS + _FAIL} total)")
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    sys.exit(1 if _FAIL else 0)