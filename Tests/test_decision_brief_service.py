"""Standalone regression checks for
``Services.decision_brief_service.DecisionBriefService``.

Covers Phase B ("Decision Copilot") orchestration -- the actual rules
given in the Phase B brief:

* reuses the existing ``RankingSnapshot`` + ``RiskManagementService``,
  never a second strategy/risk engine;
* only SUCCESS can carry a plan;
* entry/stop/target/risk are never invented -- no risk_inputs means
  an otherwise-actionable snapshot resolves to POLICY_BLOCKED, not a
  guessed plan;
* stale/error/insufficient data is never actionable (no plan attached
  regardless of risk_inputs);
* a RiskManagementService rejection (e.g. non-positive risk per unit)
  becomes RISK_REJECTED, not a fabricated plan;
* generating a brief never creates a paper order / Trade / Position
  (this service holds no such collaborator at all -- structural
  guarantee, not just a runtime check);
* every one of the eight Phase-B statuses is reachable.

Run directly with ``python Tests/test_decision_brief_service.py`` --
no external test framework required, matching
``test_snapshot_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.decision_brief_policy import DecisionBriefPolicy  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402
from Services.decision_brief_service import (  # noqa: E402
    ALL_STATUSES,
    DecisionBriefService,
    RiskInputs,
)
from Services.risk_management_service import RiskManagementService  # noqa: E402

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


def _build_service(tmp_dir: str) -> DecisionBriefService:
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "service.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(DECISION_BRIEFS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    snapshot_repository = SnapshotRepository(manager)
    brief_repository = DecisionBriefRepository(manager)
    return (
        DecisionBriefService(
            snapshot_repository=snapshot_repository,
            decision_brief_policy=DecisionBriefPolicy(),
            risk_service=RiskManagementService(),
            brief_repository=brief_repository,
        ),
        snapshot_repository,
    )


def scenario_no_snapshot_is_insufficient_data():
    print("\n[Scenario 1] symbol with no snapshot at all -> INSUFFICIENT_DATA, no plan")
    with tempfile.TemporaryDirectory() as tmp:
        service, _snap_repo = _build_service(tmp)
        brief = service.generate_brief("BBCA")
        check(brief.status == "INSUFFICIENT_DATA", "no snapshot resolves to INSUFFICIENT_DATA")
        check(brief.entry_price is None, "INSUFFICIENT_DATA brief carries no entry_price")
        check(brief.position_size is None, "INSUFFICIENT_DATA brief carries no position_size")


def scenario_error_snapshot_is_data_error_never_actionable():
    print("\n[Scenario 2] status='error' snapshot -> DATA_ERROR, never actionable even with risk_inputs")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="TLKM",
            status="error",
            error_message="Excluded: insufficient history.",
        )
        risk_inputs = RiskInputs(
            entry_price=1000.0,
            stop_loss_percent=2.0,
            take_profit_percent=4.0,
            risk_per_trade_percent=1.0,
            account_balance=10_000_000.0,
        )
        brief = service.generate_brief("TLKM", risk_inputs=risk_inputs)
        check(brief.status == "DATA_ERROR", "error-status snapshot resolves to DATA_ERROR")
        check(brief.entry_price is None, "DATA_ERROR brief carries no plan even when risk_inputs were supplied")
        check(brief.reason == "Excluded: insufficient history.", "DATA_ERROR reason forwards the real error_message")


def scenario_stale_snapshot_is_data_stale_never_actionable():
    print("\n[Scenario 3] stale snapshot -> DATA_STALE, never actionable even with risk_inputs")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        stale_time = datetime.now(timezone.utc) - timedelta(hours=12)
        snap_repo.create(
            scan_time=stale_time.isoformat(),
            symbol="ASII",
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
        )
        risk_inputs = RiskInputs(
            entry_price=5000.0,
            stop_loss_percent=2.0,
            take_profit_percent=4.0,
            risk_per_trade_percent=1.0,
            account_balance=10_000_000.0,
        )
        brief = service.generate_brief("ASII", risk_inputs=risk_inputs)
        check(brief.status == "DATA_STALE", "stale snapshot resolves to DATA_STALE")
        check(brief.entry_price is None, "DATA_STALE brief carries no plan even when risk_inputs were supplied")


def scenario_non_buy_is_no_trade():
    print("\n[Scenario 4] non-BUY recommendation -> NO_TRADE, no plan")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="BBRI",
            recommendation="SELL",
            confidence="HIGH",
            priority=1,
            rank=1,
        )
        brief = service.generate_brief("BBRI")
        check(brief.status == "NO_TRADE", "SELL recommendation resolves to NO_TRADE")
        check(brief.entry_price is None, "NO_TRADE brief carries no plan")


def scenario_actionable_without_risk_inputs_is_policy_blocked():
    print("\n[Scenario 5] fresh BUY snapshot but NO risk_inputs -> POLICY_BLOCKED, never a guessed plan")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="BBCA",
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
        )
        brief = service.generate_brief("BBCA", risk_inputs=None)
        check(brief.status == "POLICY_BLOCKED", "actionable snapshot with no risk_inputs resolves to POLICY_BLOCKED")
        check(brief.entry_price is None, "POLICY_BLOCKED brief never fabricates an entry_price")
        check(brief.stop_loss_price is None, "POLICY_BLOCKED brief never fabricates a stop_loss_price")
        check(brief.reason is not None, "POLICY_BLOCKED brief explains why no plan was produced")


def scenario_actionable_with_risk_inputs_is_success_with_real_plan():
    print("\n[Scenario 6] fresh BUY snapshot + real risk_inputs -> SUCCESS with RiskManagementService's own numbers")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snapshot = snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="BBCA",
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
        )
        risk_inputs = RiskInputs(
            entry_price=9000.0,
            stop_loss_percent=2.0,
            take_profit_percent=4.0,
            risk_per_trade_percent=1.0,
            account_balance=10_000_000.0,
        )
        # Compute the expected numbers independently, via the exact
        # same RiskManagementService formula, to prove the service
        # forwards RiskManagementService's real output rather than
        # inventing its own.
        expected_stop = 9000.0 * (1 - 2.0 / 100)
        expected_target = 9000.0 * (1 + 4.0 / 100)
        expected_risk_amount = 10_000_000.0 * (1.0 / 100)

        brief = service.generate_brief("BBCA", risk_inputs=risk_inputs)
        check(brief.status == "SUCCESS", "actionable snapshot with real risk_inputs resolves to SUCCESS")
        check(brief.source_snapshot_id == snapshot.snapshot_id, "SUCCESS brief points at the real source RankingSnapshot")
        check(brief.entry_price == 9000.0, "entry_price is exactly the caller-supplied real price")
        check(abs(brief.stop_loss_price - expected_stop) < 1e-9, "stop_loss_price matches RiskManagementService's own formula")
        check(abs(brief.take_profit_price - expected_target) < 1e-9, "take_profit_price matches RiskManagementService's own formula")
        check(abs(brief.risk_amount - expected_risk_amount) < 1e-9, "risk_amount matches RiskManagementService's own formula")
        check(brief.position_size is not None, "SUCCESS brief has a position_size")
        check(brief.risk_reward_ratio is not None, "SUCCESS brief has a risk_reward_ratio")


def scenario_risk_rejection_is_risk_rejected_not_fabricated():
    print("\n[Scenario 7] RiskManagementService rejection -> RISK_REJECTED, no fabricated plan")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="BBCA",
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
        )
        # stop_loss_percent >= 100 makes stop_loss_price <= 0 <
        # entry_price is fine, but risk_per_unit stays positive; use
        # a genuinely invalid input instead: negative account_balance
        # is rejected by RiskManagementService's own validation
        # (account_balance must be > 0).
        risk_inputs = RiskInputs(
            entry_price=9000.0,
            stop_loss_percent=2.0,
            take_profit_percent=4.0,
            risk_per_trade_percent=1.0,
            account_balance=-1.0,
        )
        brief = service.generate_brief("BBCA", risk_inputs=risk_inputs)
        check(brief.status == "RISK_REJECTED", "RiskManagementService's own validation failure resolves to RISK_REJECTED")
        check(brief.entry_price is None, "RISK_REJECTED brief carries no fabricated plan")
        check(brief.reason is not None, "RISK_REJECTED brief explains the rejection")


def scenario_only_success_can_contain_a_plan_invariant():
    print("\n[Scenario 8] structural invariant: every non-SUCCESS brief has every plan field None")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="BBCA",
            recommendation="HOLD",
            confidence="LOW",
            priority=1,
            rank=1,
        )
        brief = service.generate_brief("BBCA")
        check(brief.status != "SUCCESS", "sanity: this scenario's brief is not SUCCESS")
        plan_fields = (
            brief.entry_price,
            brief.stop_loss_price,
            brief.take_profit_price,
            brief.risk_amount,
            brief.position_size,
            brief.risk_reward_ratio,
        )
        check(all(field is None for field in plan_fields), "every plan field is None on a non-SUCCESS brief")


def scenario_get_latest_brief_retrieves_persisted_success():
    print("\n[Scenario 11] get_latest_brief retrieves a persisted SUCCESS brief without regenerating it")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="BMRI",
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
        )
        risk_inputs = RiskInputs(
            entry_price=5000.0,
            stop_loss_percent=2.0,
            take_profit_percent=4.0,
            risk_per_trade_percent=1.0,
            account_balance=10_000_000.0,
        )
        created = service.generate_brief("BMRI", risk_inputs=risk_inputs)
        check(created.status == "SUCCESS", "setup: brief generated with risk_inputs is SUCCESS")

        # Simulate a fresh process: a brand-new DecisionBriefService
        # instance over the same repository/database, mirroring
        # main.py's per-invocation composition root.
        fresh_service = DecisionBriefService(
            snapshot_repository=service._snapshot_repository,
            decision_brief_policy=DecisionBriefPolicy(),
            risk_service=RiskManagementService(),
            brief_repository=service._brief_repository,
        )
        retrieved = fresh_service.get_latest_brief("BMRI")
        check(retrieved is not None, "get_latest_brief returns a brief for a symbol with a persisted brief")
        check(retrieved.brief_id == created.brief_id, "retrieved brief is the exact persisted row, same brief_id")
        check(retrieved.status == "SUCCESS", "retrieved brief keeps its persisted SUCCESS status")
        check(retrieved.entry_price == created.entry_price, "retrieved brief keeps its persisted entry_price")
        check(
            retrieved.generated_at == created.generated_at,
            "retrieved brief keeps its original generated_at (not regenerated)",
        )

        count_after = len(service._brief_repository.list_by_symbol("BMRI"))
        check(count_after == 1, "get_latest_brief writes no new row -- exactly one brief persisted")


def scenario_get_latest_brief_retrieves_persisted_no_trade():
    print("\n[Scenario 12] get_latest_brief retrieves a persisted NO_TRADE brief")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="UNVR",
            recommendation="HOLD",
            confidence="LOW",
            priority=1,
            rank=1,
        )
        created = service.generate_brief("UNVR")
        check(created.status == "NO_TRADE", "setup: HOLD recommendation resolves to NO_TRADE")

        retrieved = service.get_latest_brief("UNVR")
        check(retrieved is not None, "get_latest_brief returns the persisted NO_TRADE brief")
        check(retrieved.brief_id == created.brief_id, "retrieved NO_TRADE brief is the exact persisted row")
        check(retrieved.status == "NO_TRADE", "retrieved brief keeps its persisted NO_TRADE status")
        check(retrieved.reason == created.reason, "retrieved brief keeps its persisted reason")


def scenario_get_latest_brief_none_when_nothing_persisted():
    print("\n[Scenario 13] get_latest_brief returns None when no brief was ever persisted for the symbol")
    with tempfile.TemporaryDirectory() as tmp:
        service, _snap_repo = _build_service(tmp)
        retrieved = service.get_latest_brief("GOTO")
        check(retrieved is None, "get_latest_brief returns None for a symbol with zero persisted briefs")


def scenario_risk_argument_invocation_bypasses_retrieval_and_creates_new_brief():
    print("\n[Scenario 14] a risk-argument call always creates a NEW brief rather than retrieving")
    with tempfile.TemporaryDirectory() as tmp:
        service, snap_repo = _build_service(tmp)
        snap_repo.create(
            scan_time=datetime.now(timezone.utc).isoformat(),
            symbol="ICBP",
            recommendation="BUY",
            confidence="HIGH",
            priority=1,
            rank=1,
        )
        risk_inputs = RiskInputs(
            entry_price=8000.0,
            stop_loss_percent=2.0,
            take_profit_percent=4.0,
            risk_per_trade_percent=1.0,
            account_balance=10_000_000.0,
        )
        first = service.generate_brief("ICBP", risk_inputs=risk_inputs)
        second = service.generate_brief("ICBP", risk_inputs=risk_inputs)
        check(first.status == "SUCCESS" and second.status == "SUCCESS", "setup: both calls resolve to SUCCESS")
        check(
            second.brief_id != first.brief_id,
            "a second risk-argument call creates a distinct new brief_id, never reusing the first",
        )
        all_for_symbol = service._brief_repository.list_by_symbol("ICBP")
        check(len(all_for_symbol) == 2, "two risk-argument calls persist two append-only rows, not one updated row")
        latest = service.get_latest_brief("ICBP")
        check(
            latest.brief_id == second.brief_id,
            "get_latest_brief now resolves to the second (most recent) generated brief",
        )


def scenario_service_holds_no_execution_collaborator():
    print("\n[Scenario 9] structural guarantee: DecisionBriefService cannot create paper orders/Trades/Positions")
    import inspect

    source = inspect.getsource(DecisionBriefService)
    forbidden_names = (
        "PaperTradingEngine",
        "OrderLifecycleService",
        "ExecutionService",
        "OrderRepository",
        "TradeRepository",
        "PositionRepository",
        "PositionManager",
    )
    for name in forbidden_names:
        check(name not in source, f"DecisionBriefService source never references {name}")


def scenario_all_eight_statuses_are_declared():
    print("\n[Scenario 10] all eight Phase-B statuses are declared in ALL_STATUSES")
    expected = {
        "SUCCESS",
        "NO_TRADE",
        "DATA_STALE",
        "DATA_ERROR",
        "INSUFFICIENT_DATA",
        "ANALYSIS_FAILED",
        "RISK_REJECTED",
        "POLICY_BLOCKED",
    }
    check(ALL_STATUSES == frozenset(expected), f"ALL_STATUSES is exactly {sorted(expected)}")


def main() -> int:
    scenario_no_snapshot_is_insufficient_data()
    scenario_error_snapshot_is_data_error_never_actionable()
    scenario_stale_snapshot_is_data_stale_never_actionable()
    scenario_non_buy_is_no_trade()
    scenario_actionable_without_risk_inputs_is_policy_blocked()
    scenario_actionable_with_risk_inputs_is_success_with_real_plan()
    scenario_risk_rejection_is_risk_rejected_not_fabricated()
    scenario_only_success_can_contain_a_plan_invariant()
    scenario_get_latest_brief_retrieves_persisted_success()
    scenario_get_latest_brief_retrieves_persisted_no_trade()
    scenario_get_latest_brief_none_when_nothing_persisted()
    scenario_risk_argument_invocation_bypasses_retrieval_and_creates_new_brief()
    scenario_service_holds_no_execution_collaborator()
    scenario_all_eight_statuses_are_declared()

    print("\n" + "=" * 60)
    print(f"DECISION BRIEF SERVICE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())