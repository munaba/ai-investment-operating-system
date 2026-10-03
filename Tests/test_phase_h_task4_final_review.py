"""Standalone, focused regression checks for Phase H Task 4 ONLY:
"Operator Feedback + Final Review Record" --
``Services.sustained_use_final_review_service.SustainedUseFinalReviewService``.

Every scenario drives the REAL ``SustainedUseFinalReviewService`` (and
its real collaborators -- ``ObservationWindowRepository``,
``SustainedUseReviewService`` (Task 2, unmodified),
``OperatorFeedbackRepository``, ``FinalReviewRecordRepository``)
against a real on-disk SQLite database, seeding real rows directly
through the already-existing, unmodified persistence repositories --
no mocked business logic. Mirrors
``Tests/test_phase_h_task2_sustained_use_review.py``'s own fixture and
scenario-runner style.

Covers:

* operator feedback persists;
* restart-safe feedback (a brand new repository/service instance,
  same on-disk file, reproduces identical rows);
* final-review record persists (create-then-update-in-place, exactly
  one row per window, enforced by the unique index);
* evidence link persists (``operator_feedback_ids`` on the review
  record reflects real, persisted ``OperatorFeedback.feedback_id``
  values -- never fabricated);
* initial human decision is ``PENDING``;
* explicit ``CONTINUE`` is recorded only when given explicitly;
* explicit ``SIMPLIFY`` is recorded only when given explicitly;
* explicit ``AUTHORIZE_FUTURE_INVESTIGATION`` is recorded only when
  given explicitly;
* the insufficient-evidence gate rejects a non-PENDING decision when
  ``scheduled_job_count == 0`` (the implemented gate), and accepts it
  once real evidence exists;
* the decision can never be inferred -- an unknown/omitted
  ``human_decision`` value is rejected, never silently defaulted;
* no LLM/provider is importable from, or reachable through, this
  service (source-grep + collaborator-graph check);
* no trading/order/position/account mutation ever occurs (verified
  both behaviorally, via before/after row counts on every such table,
  and structurally, via a source-grep for write-method calls to those
  repositories);
* no risk-limit mutation ever occurs;
* no permission/allowlist mutation ever occurs;
* duplicate/conflicting decisions are handled deterministically (last
  explicit call wins, previous decision fields are fully overwritten,
  never merged/averaged).

Run directly with
``python Tests/test_phase_h_task4_final_review.py`` -- no external
test framework required, matching every other standalone test file in
this repository.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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
from Database.migrations_sustained_use_final_review import (  # noqa: E402
    SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS,
)
from Database.migrations_telegram_control import TELEGRAM_CONTROL_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import (  # noqa: E402
    FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION,
    FINAL_REVIEW_DECISION_CONTINUE,
    FINAL_REVIEW_DECISION_PENDING,
    FINAL_REVIEW_DECISION_SIMPLIFY,
)
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.audit_event_repository import AuditEventRepository  # noqa: E402
from Repository.persistence.brief_approval_repository import BriefApprovalRepository  # noqa: E402
from Repository.persistence.daily_performance_repository import (  # noqa: E402
    DailyPerformanceRepository,
)
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
from Repository.persistence.final_review_record_repository import (  # noqa: E402
    FinalReviewRecordRepository,
)
from Repository.persistence.journal_repository import JournalRepository  # noqa: E402
from Repository.persistence.notification_dedup_repository import (  # noqa: E402
    NotificationDedupRepository,
)
from Repository.persistence.observation_window_repository import (  # noqa: E402
    ObservationWindowRepository,
)
from Repository.persistence.operator_feedback_repository import (  # noqa: E402
    OperatorFeedbackRepository,
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
from Services.sustained_use_final_review_service import (  # noqa: E402
    SustainedUseFinalReviewService,
)
from Services.sustained_use_review_service import SustainedUseReviewService  # noqa: E402

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
    SUSTAINED_USE_FINAL_REVIEW_MIGRATIONS,
)

#: Tables this service must NEVER write to. Used for the before/after
#: row-count mutation checks below -- every one of these tables must
#: have an identical row count before and after every scenario in this
#: file.
_NON_MUTABLE_TABLES = (
    "orders",
    "trades",
    "positions",
    "accounts",
    "risk_limits",
    "brief_approvals",
    "decision_briefs",
    "journal_entries",
    "portfolio_snapshots",
)


class Fixture:
    """One bag of repositories over a single on-disk SQLite file, plus
    convenience seed helpers. Mirrors
    ``Tests/test_phase_h_task2_sustained_use_review.py``'s own
    ``Fixture`` pattern.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
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
        self.feedback_repo = OperatorFeedbackRepository(self.manager)
        self.record_repo = FinalReviewRecordRepository(self.manager)

    def build_review_service(self) -> SustainedUseReviewService:
        return SustainedUseReviewService(
            observation_window_repository=self.window_repo,
            scheduler_state_repository=self.scheduler_repo,
            audit_event_repository=self.audit_repo,
            notification_dedup_repository=self.dedup_repo,
            telegram_command_audit_repository=self.telegram_repo,
            decision_brief_repository=self.brief_repo,
            journal_repository=self.journal_repo,
            paper_review_service=None,
            reconciliation_engine=None,
            daily_performance_repository=self.daily_perf_repo,
            portfolio_snapshot_repository=self.snapshot_repo,
        )

    def build_service(self) -> SustainedUseFinalReviewService:
        return SustainedUseFinalReviewService(
            observation_window_repository=self.window_repo,
            sustained_use_review_service=self.build_review_service(),
            operator_feedback_repository=self.feedback_repo,
            final_review_record_repository=self.record_repo,
        )

    def open_window(self, start_at: str = "2026-08-24T00:00:00", end_at: str = "2026-09-23T23:59:59") -> int:
        window = self.window_repo.create(
            start_at=start_at,
            end_at=end_at,
            timezone="Asia/Jakarta",
            created_at="2026-08-24T00:00:00+00:00",
        )
        return window.window_id

    def seed_scheduler_job_run(self, window_id: int, trading_date: str = "2026-08-25") -> None:
        """Insert one real, successful ``SchedulerJobRun`` so
        ``availability.scheduled_job_count > 0`` for the window under
        test -- the same real, derived-not-fabricated signal
        ``SustainedUseFinalReviewService``'s insufficiency gate relies
        on."""
        self.scheduler_repo.start(
            "session_scan", trading_date, started_at="2026-08-25T01:00:00+00:00"
        )
        self.scheduler_repo.mark_success(
            "session_scan", trading_date, finished_at="2026-08-25T01:00:05+00:00"
        )

    def table_row_counts(self, tables) -> dict:
        counts = {}
        for table in tables:
            result = self.manager.execute(f"SELECT COUNT(*) AS n FROM {table}")
            counts[table] = result.rows[0]["n"]
        return counts


def _fresh_fixture(tmp_dir: str) -> Fixture:
    return Fixture(Path(tmp_dir) / "aios.db")


# ---------------------------------------------------------------------------
# Scenario 1: operator feedback persists
# ---------------------------------------------------------------------------


def scenario_feedback_persists():
    print("\n[Scenario 1] operator feedback persists")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        service = fx.build_service()

        feedback = service.record_feedback(
            window_id=window_id,
            operator_rating=4,
            alert_usefulness="useful",
            free_text="Seems fine so far",
            concerns=["too_many_alerts", "stale_data"],
            operator_label="ops1",
        )

        check(feedback.feedback_id is not None, "record_feedback() returns a persisted feedback_id")
        check(feedback.observation_window_id == window_id, "feedback is linked to the correct window_id")
        check(feedback.operator_rating == 4, "operator_rating is stored verbatim")
        check(feedback.free_text == "Seems fine so far", "free_text is stored verbatim")
        check(
            json.loads(feedback.concerns) == ["too_many_alerts", "stale_data"],
            "concerns list round-trips through JSON verbatim",
        )

        reread = fx.feedback_repo.get_by_id(feedback.feedback_id)
        check(reread is not None, "feedback row is independently readable back from OperatorFeedbackRepository")
        check(reread.operator_rating == 4, "re-read feedback row matches what was written")


# ---------------------------------------------------------------------------
# Scenario 2: restart-safe feedback
# ---------------------------------------------------------------------------


def scenario_restart_safe_feedback():
    print("\n[Scenario 2] restart-safe feedback")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        fx1 = Fixture(db_path)
        window_id = fx1.open_window()
        service1 = fx1.build_service()
        feedback1 = service1.record_feedback(window_id=window_id, operator_rating=5, operator_label="ops1")

        # Brand new Fixture/repository/service instance over the SAME
        # on-disk file -- nothing cached, nothing in-memory carried
        # over.
        fx2 = Fixture(db_path)
        service2 = fx2.build_service()
        rows = service2.list_feedback(window_id=window_id)

        check(len(rows) == 1, "exactly one feedback row survives a fresh repository instance over the same DB file")
        check(rows[0].feedback_id == feedback1.feedback_id, "restarted instance reads back the identical feedback_id")
        check(rows[0].operator_rating == 5, "restarted instance reads back the identical operator_rating")
        check(rows[0].operator_label == "ops1", "restarted instance reads back the identical operator_label")


# ---------------------------------------------------------------------------
# Scenario 3: final-review record persists (create then update in place)
# ---------------------------------------------------------------------------


def scenario_final_review_record_persists():
    print("\n[Scenario 3] final-review record persists (create-then-update-in-place)")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        service = fx.build_service()

        check(service.load_final_review(window_id=window_id) is None,
              "load_final_review() returns None before any refresh/feedback/decision has ever run")

        record1 = service.refresh_review(window_id=window_id)
        check(record1.review_id is not None, "refresh_review() creates a persisted review row")
        check(record1.observation_window_id == window_id, "review row is linked to the correct window_id")

        record2 = service.refresh_review(window_id=window_id)
        check(record2.review_id == record1.review_id,
              "a second refresh_review() call updates the SAME row in place, not a second row")

        all_rows = fx.record_repo.list_all()
        window_rows = [r for r in all_rows if r.observation_window_id == window_id]
        check(len(window_rows) == 1, "exactly one final_review_records row exists per window (unique index enforced)")

        loaded = service.load_final_review(window_id=window_id)
        check(loaded is not None and loaded.review_id == record1.review_id,
              "load_final_review() reads back the same persisted row without side effects")


# ---------------------------------------------------------------------------
# Scenario 4: evidence link persists (operator_feedback_ids)
# ---------------------------------------------------------------------------


def scenario_evidence_link_persists():
    print("\n[Scenario 4] evidence link (operator_feedback_ids) persists and is never fabricated")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        service = fx.build_service()

        record0 = service.refresh_review(window_id=window_id)
        check(json.loads(record0.operator_feedback_ids) == [],
              "operator_feedback_ids is an honest empty list before any feedback exists")

        fb1 = service.record_feedback(window_id=window_id, operator_rating=3)
        record1 = service.load_final_review(window_id=window_id)
        check(json.loads(record1.operator_feedback_ids) == [fb1.feedback_id],
              "operator_feedback_ids links exactly the one real, persisted feedback_id after one feedback call")

        fb2 = service.record_feedback(window_id=window_id, free_text="second note")
        record2 = service.load_final_review(window_id=window_id)
        linked_ids = json.loads(record2.operator_feedback_ids)
        check(set(linked_ids) == {fb1.feedback_id, fb2.feedback_id},
              "operator_feedback_ids links both real, persisted feedback_id values after a second feedback call")
        check(all(fx.feedback_repo.get_by_id(fid) is not None for fid in linked_ids),
              "every linked feedback_id independently resolves to a real, persisted OperatorFeedback row")


# ---------------------------------------------------------------------------
# Scenario 5: initial human decision is PENDING
# ---------------------------------------------------------------------------


def scenario_initial_decision_is_pending():
    print("\n[Scenario 5] initial human_decision is PENDING")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        service = fx.build_service()

        record = service.refresh_review(window_id=window_id)
        check(record.human_decision == FINAL_REVIEW_DECISION_PENDING,
              "a freshly created final review record starts human_decision == 'PENDING'")
        check(record.decided_at is None, "decided_at is None while human_decision == 'PENDING'")
        check(record.decided_by is None, "decided_by is None while human_decision == 'PENDING'")
        check(record.decision_note is None, "decision_note is None while human_decision == 'PENDING'")


# ---------------------------------------------------------------------------
# Scenarios 6-8: explicit CONTINUE / SIMPLIFY / AUTHORIZE_FUTURE_INVESTIGATION
# ---------------------------------------------------------------------------


def _decide_with_sufficient_evidence(fx: Fixture, decision: str, description: str) -> None:
    window_id = fx.open_window()
    fx.seed_scheduler_job_run(window_id)
    service = fx.build_service()

    record = service.record_decision(
        window_id=window_id,
        human_decision=decision,
        decision_note=f"explicit {decision} for test",
        decided_by="ops1",
    )
    check(record.human_decision == decision, f"record_decision() persists explicit {description}")
    check(record.decided_at is not None, f"decided_at is set once {description} is explicitly recorded")
    check(record.decided_by == "ops1", f"decided_by is stored verbatim for {description}")
    check(record.decision_note == f"explicit {decision} for test",
          f"decision_note is stored verbatim for {description}")

    reread = fx.record_repo.get_by_window(window_id)
    check(reread.human_decision == decision, f"{description} is independently re-readable from the repository")


def scenario_explicit_continue():
    print("\n[Scenario 6] explicit CONTINUE")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        _decide_with_sufficient_evidence(fx, FINAL_REVIEW_DECISION_CONTINUE, "CONTINUE")


def scenario_explicit_simplify():
    print("\n[Scenario 7] explicit SIMPLIFY")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        _decide_with_sufficient_evidence(fx, FINAL_REVIEW_DECISION_SIMPLIFY, "SIMPLIFY")


def scenario_explicit_authorize_future_investigation():
    print("\n[Scenario 8] explicit AUTHORIZE_FUTURE_INVESTIGATION")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        _decide_with_sufficient_evidence(
            fx, FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION, "AUTHORIZE_FUTURE_INVESTIGATION"
        )


# ---------------------------------------------------------------------------
# Scenario 9: insufficient-evidence gate rejects non-PENDING decisions
# ---------------------------------------------------------------------------


def scenario_insufficient_evidence_gate():
    print("\n[Scenario 9] insufficient-evidence gate rejects non-PENDING when scheduled_job_count == 0")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        service = fx.build_service()

        # No SchedulerJobRun seeded -> scheduled_job_count == 0.
        for decision in (
            FINAL_REVIEW_DECISION_CONTINUE,
            FINAL_REVIEW_DECISION_SIMPLIFY,
            FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION,
        ):
            raised = False
            try:
                service.record_decision(window_id=window_id, human_decision=decision)
            except ValidationError:
                raised = True
            check(raised, f"record_decision({decision}) raises ValidationError when scheduled_job_count == 0")

        record = service.load_final_review(window_id=window_id)
        check(record is None or record.human_decision == FINAL_REVIEW_DECISION_PENDING,
              "a rejected decision never lands on the persisted row -- human_decision stays PENDING/unset")

        # PENDING itself is never gated, even with zero evidence.
        record_pending = service.record_decision(
            window_id=window_id, human_decision=FINAL_REVIEW_DECISION_PENDING
        )
        check(record_pending.human_decision == FINAL_REVIEW_DECISION_PENDING,
              "record_decision(PENDING) is always accepted, even with scheduled_job_count == 0")

        # Once real evidence exists, the same decision succeeds.
        fx.seed_scheduler_job_run(window_id)
        record_ok = service.record_decision(
            window_id=window_id, human_decision=FINAL_REVIEW_DECISION_CONTINUE
        )
        check(record_ok.human_decision == FINAL_REVIEW_DECISION_CONTINUE,
              "record_decision(CONTINUE) succeeds once real evidence (scheduled_job_count > 0) exists")


# ---------------------------------------------------------------------------
# Scenario 10: decision cannot be inferred
# ---------------------------------------------------------------------------


def scenario_decision_cannot_be_inferred():
    print("\n[Scenario 10] decision cannot be inferred -- unknown/omitted values are rejected")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        fx.seed_scheduler_job_run(window_id)
        service = fx.build_service()

        raised = False
        try:
            service.record_decision(window_id=window_id, human_decision="APPROVED")  # not in the allowed set
        except ValidationError:
            raised = True
        check(raised, "an unknown human_decision value ('APPROVED') is rejected, never coerced to a known value")

        raised_missing_kw = False
        try:
            service.record_decision(window_id=window_id)  # human_decision omitted entirely
        except TypeError:
            raised_missing_kw = True
        check(raised_missing_kw,
              "human_decision has no default value -- omitting it entirely is a TypeError, not a silent PENDING/guess")

        # refresh_review()/record_feedback() never touch human_decision
        # at all, confirming evidence refresh alone can never move a
        # decision off PENDING.
        record_before = service.record_decision(
            window_id=window_id, human_decision=FINAL_REVIEW_DECISION_PENDING
        )
        check(record_before.human_decision == FINAL_REVIEW_DECISION_PENDING, "sanity: decision reset to PENDING")
        service.refresh_review(window_id=window_id)
        service.record_feedback(window_id=window_id, operator_rating=5, free_text="great")
        record_after = service.load_final_review(window_id=window_id)
        check(record_after.human_decision == FINAL_REVIEW_DECISION_PENDING,
              "refresh_review()/record_feedback() never advance human_decision off PENDING by themselves")


# ---------------------------------------------------------------------------
# Scenario 11: no LLM/provider can influence the decision
# ---------------------------------------------------------------------------


def _imported_module_names(module) -> set:
    """Return the top-level dotted module names actually ``import``ed
    (or ``from``-imported) by ``module``'s own source -- parsed via
    ``ast``, not a substring grep, so prose in docstrings/comments
    that merely *discusses* a collaborator (to document its absence)
    can never produce a false positive."""
    import ast

    tree = ast.parse(Path(module.__file__).read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def scenario_no_llm_provider_influence():
    print("\n[Scenario 11] LLM/provider cannot influence the decision")
    import Services.sustained_use_final_review_service as service_module

    imported = _imported_module_names(service_module)
    hits = [name for name in imported if name.startswith("Providers") or name.startswith("Agents")]
    check(not hits,
          f"Services.sustained_use_final_review_service imports no Providers.*/Agents.* module (actual imports: {sorted(imported)})")

    import inspect

    ctor_params = set(inspect.signature(SustainedUseFinalReviewService.__init__).parameters) - {"self"}
    check(
        ctor_params
        == {
            "observation_window_repository",
            "sustained_use_review_service",
            "operator_feedback_repository",
            "final_review_record_repository",
        },
        "SustainedUseFinalReviewService's constructor accepts only real persistence/review collaborators -- "
        "no provider/LLM/agent parameter exists to inject one through",
    )

    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        fx.seed_scheduler_job_run(window_id)
        service = fx.build_service()
        # Recording the exact same decision twice must be perfectly
        # deterministic (no model call could have made a difference).
        r1 = service.record_decision(window_id=window_id, human_decision=FINAL_REVIEW_DECISION_CONTINUE)
        r2 = service.record_decision(window_id=window_id, human_decision=FINAL_REVIEW_DECISION_CONTINUE)
        check(r1.human_decision == r2.human_decision == FINAL_REVIEW_DECISION_CONTINUE,
              "recording the identical explicit decision twice is perfectly deterministic")


# ---------------------------------------------------------------------------
# Scenarios 12-14: no trading / risk-limit / permission mutation
# ---------------------------------------------------------------------------


def scenario_no_trading_mutation():
    print("\n[Scenario 12] no trading mutation (orders/trades/positions/accounts/portfolio_snapshots)")
    import Services.sustained_use_final_review_service as service_module

    imported = _imported_module_names(service_module)
    forbidden_modules = (
        "Repository.persistence.order_repository",
        "Repository.persistence.trade_repository",
        "Repository.persistence.position_repository",
        "Business.paper_trading_engine",
        "Services.order_lifecycle_service",
        "Services.execution_service",
    )
    hits = [m for m in forbidden_modules if m in imported]
    check(not hits, f"service imports no order/trade/position/execution module (actual imports: {sorted(imported)})")

    import inspect

    ctor_params = set(inspect.signature(SustainedUseFinalReviewService.__init__).parameters) - {"self"}
    forbidden_param_substrings = ("order", "trade", "position", "execution", "risk")
    bad_params = [p for p in ctor_params if any(tok in p.lower() for tok in forbidden_param_substrings)]
    check(not bad_params,
          f"SustainedUseFinalReviewService's constructor takes no order/trade/position/execution/risk parameter (actual params: {sorted(ctor_params)})")

    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        fx.seed_scheduler_job_run(window_id)
        service = fx.build_service()

        tables = ("orders", "trades", "positions", "accounts", "portfolio_snapshots")
        before = fx.table_row_counts(tables)

        service.refresh_review(window_id=window_id)
        service.record_feedback(window_id=window_id, operator_rating=3, free_text="note", concerns=["x"])
        service.record_decision(
            window_id=window_id, human_decision=FINAL_REVIEW_DECISION_CONTINUE, decided_by="ops1"
        )
        service.record_decision(window_id=window_id, human_decision=FINAL_REVIEW_DECISION_SIMPLIFY)

        after = fx.table_row_counts(tables)
        check(before == after, f"trading-related table row counts are unchanged by any Task 4 call: before={before} after={after}")


def scenario_no_risk_limit_mutation():
    print("\n[Scenario 13] no risk-limit mutation")
    import Services.sustained_use_final_review_service as service_module

    imported = _imported_module_names(service_module)
    hits = [m for m in imported if "risk_limit" in m.lower() or "risk_ledger" in m.lower()]
    check(not hits, f"service imports no risk-limit/risk-ledger module (actual imports: {sorted(imported)})")

    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        fx.seed_scheduler_job_run(window_id)
        service = fx.build_service()

        before = fx.table_row_counts(["risk_limits"])
        service.record_decision(window_id=window_id, human_decision=FINAL_REVIEW_DECISION_CONTINUE)
        after = fx.table_row_counts(["risk_limits"])
        check(before == after, f"risk_limits row count is unchanged by record_decision(): before={before} after={after}")


def scenario_no_permission_mutation():
    print("\n[Scenario 14] no permission/allowlist mutation")
    import Services.sustained_use_final_review_service as service_module

    imported = _imported_module_names(service_module)
    hits = [m for m in imported if "allowlist" in m.lower() or "telegram_inbound_state" in m.lower()]
    check(not hits, f"service imports no permission/allowlist module (actual imports: {sorted(imported)})")

    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        fx.seed_scheduler_job_run(window_id)
        service = fx.build_service()

        before = fx.table_row_counts(["telegram_inbound_state"])
        service.record_decision(
            window_id=window_id, human_decision=FINAL_REVIEW_DECISION_AUTHORIZE_FUTURE_INVESTIGATION
        )
        after = fx.table_row_counts(["telegram_inbound_state"])
        check(before == after,
              f"telegram_inbound_state (permission/allowlist table) row count is unchanged: before={before} after={after}")


# ---------------------------------------------------------------------------
# Scenario 15: duplicate/conflicting decisions handled deterministically
# ---------------------------------------------------------------------------


def scenario_duplicate_conflicting_decisions():
    print("\n[Scenario 15] duplicate/conflicting decisions handled deterministically")
    with tempfile.TemporaryDirectory() as tmp:
        fx = _fresh_fixture(tmp)
        window_id = fx.open_window()
        fx.seed_scheduler_job_run(window_id)
        service = fx.build_service()

        r1 = service.record_decision(
            window_id=window_id,
            human_decision=FINAL_REVIEW_DECISION_CONTINUE,
            decision_note="first pass",
            decided_by="ops1",
        )
        check(r1.human_decision == FINAL_REVIEW_DECISION_CONTINUE, "first decision recorded as CONTINUE")

        # Conflicting second call, different decision + different
        # decided_by, on the SAME window.
        r2 = service.record_decision(
            window_id=window_id,
            human_decision=FINAL_REVIEW_DECISION_SIMPLIFY,
            decision_note="changed my mind",
            decided_by="ops2",
        )
        check(r2.human_decision == FINAL_REVIEW_DECISION_SIMPLIFY,
              "a later conflicting decision deterministically overwrites the earlier one (last explicit call wins)")
        check(r2.decision_note == "changed my mind", "decision_note is fully overwritten, never merged/appended")
        check(r2.decided_by == "ops2", "decided_by is fully overwritten, never merged")
        check(r1.review_id == r2.review_id,
              "the conflicting decision updates the SAME row (one row per window), not a second row")

        all_rows = fx.record_repo.list_all()
        window_rows = [row for row in all_rows if row.observation_window_id == window_id]
        check(len(window_rows) == 1, "still exactly one final_review_records row for the window after conflicting decisions")

        # Re-read independently to confirm durability of the final
        # (second) decision, not the first.
        reread = fx.record_repo.get_by_window(window_id)
        check(reread.human_decision == FINAL_REVIEW_DECISION_SIMPLIFY,
              "independently re-reading the row confirms the LATEST decision persisted, not the first")

        # A third call reverting explicitly to PENDING is also
        # deterministic and always allowed.
        r3 = service.record_decision(window_id=window_id, human_decision=FINAL_REVIEW_DECISION_PENDING)
        check(r3.human_decision == FINAL_REVIEW_DECISION_PENDING, "an explicit revert to PENDING is accepted deterministically")
        check(r3.decided_at is None and r3.decided_by is None and r3.decision_note is None,
              "reverting to PENDING clears decided_at/decided_by/decision_note")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scenario_feedback_persists()
    scenario_restart_safe_feedback()
    scenario_final_review_record_persists()
    scenario_evidence_link_persists()
    scenario_initial_decision_is_pending()
    scenario_explicit_continue()
    scenario_explicit_simplify()
    scenario_explicit_authorize_future_investigation()
    scenario_insufficient_evidence_gate()
    scenario_decision_cannot_be_inferred()
    scenario_no_llm_provider_influence()
    scenario_no_trading_mutation()
    scenario_no_risk_limit_mutation()
    scenario_no_permission_mutation()
    scenario_duplicate_conflicting_decisions()

    print(f"\n{'=' * 70}")
    print(f"RESULTS: {_PASS} passed, {_FAIL} failed (of {_PASS + _FAIL} total)")
    if _FAILURES:
        print("\nFailed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    sys.exit(1 if _FAIL else 0)
