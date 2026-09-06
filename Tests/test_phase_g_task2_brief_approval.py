"""Standalone, focused regression checks for Phase G Task 2 ONLY:
"Approved Brief -> Paper Link Contract" -- ``Database.
migrations_brief_approvals``, ``Repository.persistence.
brief_approval_repository.BriefApprovalRepository``, and
``Services.brief_approval_service.BriefApprovalService``.

Every scenario drives the REAL ``BriefApprovalService`` against a real
on-disk SQLite database and the REAL, unmodified
``PaperTradingEngine.submit_order()`` -- no mocked business logic.
Only ``_FailingBriefApprovalRepository`` (used in exactly one
scenario, to prove the linkage write is genuinely best-effort) is a
fake, and it fails on purpose.

Proves, concretely:

* Scenario 1: a non-SUCCESS brief (every one of the seven other
  statuses) is rejected before any order is ever submitted.
* Scenario 2: ``approved=False`` (and ``approved=None``) is rejected,
  even for a genuinely SUCCESS brief -- approval is never inferred.
* Scenario 3: a SUCCESS brief with explicit ``approved=True`` submits
  exactly one real paper order/trade, using the brief's own plan
  values.
* Scenario 4: the brief/order/trade linkage is persisted correctly.
* Scenario 5: one brief can be linked at most once -- a second
  ``approve_and_submit`` call for the same brief_id is rejected
  without submitting a second order (no duplicate submission on
  repeated approval).
* Scenario 6: the link row survives a full application restart.
* Scenario 7: if the post-commit linkage write fails, the already-
  committed trade is still returned unconditionally and is NOT rolled
  back -- the failure is surfaced explicitly on the result instead.

Run directly with
``python Tests/test_phase_g_task2_brief_approval.py`` -- no external
test framework required, matching every other standalone test file in
this repository.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Core.exceptions import RepositoryError, ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_brief_approvals import BRIEF_APPROVALS_MIGRATIONS  # noqa: E402
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.brief_approval_repository import (  # noqa: E402
    BriefApprovalRepository,
)
from Repository.persistence.decision_brief_repository import (  # noqa: E402
    DecisionBriefRepository,
)
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402
from Services.brief_approval_service import (  # noqa: E402
    REASON_ALREADY_LINKED,
    REASON_APPROVAL_NOT_EXPLICIT_TRUE,
    REASON_BRIEF_NOT_SUCCESS,
    BriefApprovalService,
)
from Services.decision_brief_service import (  # noqa: E402
    ALL_STATUSES,
    STATUS_SUCCESS,
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
# Test double -- I/O boundary only, used in exactly one scenario
# ---------------------------------------------------------------------------


class _FailingBriefApprovalRepository:
    """``BriefApprovalRepository``-shaped double whose ``create()``
    always raises -- exercises "the linkage write is best-effort,
    never rolls back the trade"."""

    def __init__(self, real: BriefApprovalRepository) -> None:
        self._real = real
        self.attempts = 0

    def create(self, **kwargs):
        self.attempts += 1
        raise RepositoryError("simulated brief_approvals write failure")

    def get_by_brief_id(self, brief_id: int):
        return self._real.get_by_brief_id(brief_id)

    def get_by_order_id(self, order_id: int):
        return self._real.get_by_order_id(order_id)

    def list_all(self):
        return self._real.list_all()


# ---------------------------------------------------------------------------
# Real-database test rig
# ---------------------------------------------------------------------------


def _build(tmp_dir: str, db_name: str, *, cash: float = 100_000_000.0, brief_approval_repository=None):
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
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="paper-id", account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=cash, equity=cash, buying_power=cash,
    )
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idempotency_repo = OrderIdempotencyRepository(manager)
    brief_repo = DecisionBriefRepository(manager)
    real_brief_approval_repo = BriefApprovalRepository(manager)

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

    active_brief_approval_repo = (
        brief_approval_repository if brief_approval_repository is not None else real_brief_approval_repo
    )
    service = BriefApprovalService(
        decision_brief_repository=brief_repo,
        brief_approval_repository=active_brief_approval_repo,
        paper_trading_engine=engine,
    )

    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
        "brief": brief_repo,
        "brief_approval": real_brief_approval_repo,
    }
    return cfg, service, repos


def _make_success_brief(brief_repo: DecisionBriefRepository, *, symbol: str = "BBCA") -> int:
    brief = brief_repo.create(
        symbol=symbol,
        generated_at="2026-08-23T09:00:00+00:00",
        status=STATUS_SUCCESS,
        source_snapshot_id=None,
        reason=None,
        entry_price=9500.0,
        stop_loss_price=9300.0,
        take_profit_price=9900.0,
        risk_amount=20000.0,
        position_size=100.0,
        risk_reward_ratio=2.0,
    )
    return brief.brief_id


def _make_non_success_brief(brief_repo: DecisionBriefRepository, status: str, *, symbol: str = "BBRI") -> int:
    brief = brief_repo.create(
        symbol=symbol,
        generated_at="2026-08-23T09:00:00+00:00",
        status=status,
        source_snapshot_id=None,
        reason="not actionable",
    )
    return brief.brief_id


# ---------------------------------------------------------------------------
# Scenario 1: non-SUCCESS brief rejected for every status
# ---------------------------------------------------------------------------


def scenario_non_success_rejected():
    print("\n[Scenario 1] every non-SUCCESS brief status is rejected before any order is submitted")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, service, repos = _build(tmp, "s1.db")

        non_success_statuses = sorted(ALL_STATUSES - {STATUS_SUCCESS})
        for status in non_success_statuses:
            brief_id = _make_non_success_brief(repos["brief"], status, symbol=f"SYM{status[:4]}")
            raised = None
            try:
                service.approve_and_submit(
                    brief_id,
                    approved=True,
                    account_id="paper-id",
                    executed_at="2026-08-23T10:00:00+00:00",
                )
            except ValidationError as exc:
                raised = exc
            check(raised is not None, f"status={status} raises ValidationError")
            check(
                raised is not None and raised.details.get("reason") == REASON_BRIEF_NOT_SUCCESS,
                f"status={status} raises with reason={REASON_BRIEF_NOT_SUCCESS!r}",
            )

        check(len(repos["order"].list_all()) == 0, "no Order row exists for any of the non-SUCCESS briefs")
        check(len(repos["brief_approval"].list_all()) == 0, "no brief_approvals row exists for any of them")


# ---------------------------------------------------------------------------
# Scenario 2: approved != True rejected, even for a SUCCESS brief
# ---------------------------------------------------------------------------


def scenario_approval_not_explicit_true_rejected():
    print("\n[Scenario 2] approved=False (and None) is rejected even for a genuinely SUCCESS brief")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, service, repos = _build(tmp, "s2.db")
        brief_id = _make_success_brief(repos["brief"])

        raised_false = None
        try:
            service.approve_and_submit(
                brief_id, approved=False, account_id="paper-id",
                executed_at="2026-08-23T10:00:00+00:00",
            )
        except ValidationError as exc:
            raised_false = exc
        check(raised_false is not None, "approved=False raises ValidationError")
        check(
            raised_false is not None and raised_false.details.get("reason") == REASON_APPROVAL_NOT_EXPLICIT_TRUE,
            f"approved=False raises with reason={REASON_APPROVAL_NOT_EXPLICIT_TRUE!r}",
        )

        raised_none = None
        try:
            service.approve_and_submit(
                brief_id, approved=None, account_id="paper-id",  # type: ignore[arg-type]
                executed_at="2026-08-23T10:00:00+00:00",
            )
        except ValidationError as exc:
            raised_none = exc
        check(raised_none is not None, "approved=None raises ValidationError (never inferred as True)")

        check(len(repos["order"].list_all()) == 0, "no Order row exists after either rejection")
        check(repos["brief_approval"].get_by_brief_id(brief_id) is None, "no brief_approvals row exists after either rejection")


# ---------------------------------------------------------------------------
# Scenario 3: SUCCESS + explicit approval submits exactly one paper order
# ---------------------------------------------------------------------------


def scenario_success_and_approved_submits_one_order():
    print("\n[Scenario 3] SUCCESS brief + explicit approved=True submits exactly one real paper order")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, service, repos = _build(tmp, "s3.db")
        brief_id = _make_success_brief(repos["brief"])

        result = service.approve_and_submit(
            brief_id, approved=True, account_id="paper-id",
            executed_at="2026-08-23T10:00:00+00:00",
        )

        check(result.trade is not None, "a real Trade was returned")
        check(len(repos["order"].list_all()) == 1, "exactly one Order row exists")
        check(len(repos["trade"].list_by_account("paper-id")) == 1, "exactly one Trade row exists")

        order = repos["order"].get_by_id(result.trade.order_id)
        check(order is not None and order.symbol == "BBCA", "order symbol matches the brief's symbol")
        check(order is not None and order.action == "BUY", "order action is BUY")
        check(order is not None and abs(order.quantity - 100.0) < 1e-9, "order quantity matches brief.position_size")
        check(order is not None and abs(order.requested_price - 9500.0) < 1e-9, "order requested_price matches brief.entry_price")


# ---------------------------------------------------------------------------
# Scenario 4: linkage persisted correctly
# ---------------------------------------------------------------------------


def scenario_linkage_persisted():
    print("\n[Scenario 4] brief/order/trade linkage is persisted correctly")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, service, repos = _build(tmp, "s4.db")
        brief_id = _make_success_brief(repos["brief"])

        result = service.approve_and_submit(
            brief_id, approved=True, account_id="paper-id",
            executed_at="2026-08-23T10:00:00+00:00",
        )

        check(result.link is not None, "link was persisted (link is not None)")
        check(result.link_error is None, "no link_error on the successful path")
        if result.link is not None:
            check(result.link.brief_id == brief_id, "link.brief_id matches the approved brief")
            check(result.link.order_id == result.trade.order_id, "link.order_id matches the real Order")
            check(result.link.trade_id == result.trade.trade_id, "link.trade_id matches the real Trade")
            check(bool(result.link.approved_at), "link.approved_at is non-empty")
            check(bool(result.link.recorded_at), "link.recorded_at is non-empty")

        fetched = repos["brief_approval"].get_by_brief_id(brief_id)
        check(fetched is not None, "link is retrievable via get_by_brief_id")
        fetched_by_order = repos["brief_approval"].get_by_order_id(result.trade.order_id)
        check(fetched_by_order is not None and fetched_by_order.brief_id == brief_id, "link is retrievable via get_by_order_id")


# ---------------------------------------------------------------------------
# Scenario 5: one brief, one link -- no duplicate submission on repeated approval
# ---------------------------------------------------------------------------


def scenario_one_brief_one_link_no_duplicate_submission():
    print("\n[Scenario 5] one brief can be linked at most once; repeated approval never submits a second order")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, service, repos = _build(tmp, "s5.db")
        brief_id = _make_success_brief(repos["brief"])

        first = service.approve_and_submit(
            brief_id, approved=True, account_id="paper-id",
            executed_at="2026-08-23T10:00:00+00:00",
        )
        check(first.trade is not None, "first approval submits a real trade")

        raised = None
        try:
            service.approve_and_submit(
                brief_id, approved=True, account_id="paper-id",
                executed_at="2026-08-23T10:05:00+00:00",
            )
        except ValidationError as exc:
            raised = exc
        check(raised is not None, "second approval for the same brief_id raises ValidationError")
        check(
            raised is not None and raised.details.get("reason") == REASON_ALREADY_LINKED,
            f"second approval raises with reason={REASON_ALREADY_LINKED!r}",
        )

        check(len(repos["order"].list_all()) == 1, "still exactly one Order row after the repeated approval attempt")
        check(len(repos["trade"].list_by_account("paper-id")) == 1, "still exactly one Trade row after the repeated approval attempt")
        check(len(repos["brief_approval"].list_all()) == 1, "still exactly one brief_approvals row after the repeated approval attempt")


# ---------------------------------------------------------------------------
# Scenario 6: link survives restart
# ---------------------------------------------------------------------------


def scenario_readable_after_restart():
    print("\n[Scenario 6] brief_approvals row survives a full application restart")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, service, repos = _build(tmp, "s6.db")
        brief_id = _make_success_brief(repos["brief"])
        result = service.approve_and_submit(
            brief_id, approved=True, account_id="paper-id",
            executed_at="2026-08-23T10:00:00+00:00",
        )

        # Simulate an application restart: brand new DatabaseManager/
        # connection over the SAME db file, nothing shared in memory.
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        brief_approval_repo2 = BriefApprovalRepository(manager2)

        after_restart = brief_approval_repo2.get_by_brief_id(brief_id)
        check(after_restart is not None, "link row is readable through a brand new connection after restart")
        if after_restart is not None:
            check(
                after_restart.brief_id == result.link.brief_id
                and after_restart.order_id == result.link.order_id
                and after_restart.trade_id == result.link.trade_id
                and after_restart.approved_at == result.link.approved_at
                and after_restart.recorded_at == result.link.recorded_at,
                "row read back after restart is identical to the row written before restart",
            )
        db2.disconnect()


# ---------------------------------------------------------------------------
# Scenario 7: post-commit linkage failure does not roll back the trade
# ---------------------------------------------------------------------------


def scenario_linkage_failure_does_not_roll_back_trade():
    print("\n[Scenario 7] a failing brief_approvals write is never propagated and never rolls back the committed trade")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, service, repos = _build(tmp, "s7.db")
        # Rebuild the service with a failing brief_approval_repository
        # wired in, reusing the same underlying repos/engine.
        failing_repo = _FailingBriefApprovalRepository(repos["brief_approval"])
        service_with_failing_repo = BriefApprovalService(
            decision_brief_repository=repos["brief"],
            brief_approval_repository=failing_repo,
            paper_trading_engine=service._paper_trading_engine,  # same real engine
        )
        brief_id = _make_success_brief(repos["brief"])

        result = service_with_failing_repo.approve_and_submit(
            brief_id, approved=True, account_id="paper-id",
            executed_at="2026-08-23T10:00:00+00:00",
        )

        check(result.trade is not None, "approve_and_submit still returns a real Trade despite the linkage-write failure")
        check(result.link is None, "result.link is None on linkage-write failure")
        check(result.link_error is not None and "brief_approvals" in result.link_error, "result.link_error explicitly identifies a brief_approvals failure")
        check(failing_repo.attempts == 1, "the failing repository's create() was actually attempted exactly once")

        order = repos["order"].get_by_id(result.trade.order_id)
        check(order is not None and order.status == "FILLED", "Order row exists and is FILLED despite the linkage-write failure")
        trades = repos["trade"].list_by_account("paper-id")
        check(len(trades) == 1 and trades[0].trade_id == result.trade.trade_id, "exactly one Trade row exists, matching the returned Trade")
        account = repos["account"].get_by_id("paper-id")
        expected_cash = 100_000_000.0 - (100.0 * 9500.0) - result.trade.fee - result.trade.tax
        check(abs(account.cash - expected_cash) < 1e-6, "Account.cash was really debited -- the linkage-write failure did not roll back the trade")
        check(repos["brief_approval"].get_by_brief_id(brief_id) is None, "no brief_approvals row exists via the real repository (the write genuinely failed, nothing was silently persisted elsewhere)")


def main() -> int:
    scenario_non_success_rejected()
    scenario_approval_not_explicit_true_rejected()
    scenario_success_and_approved_submits_one_order()
    scenario_linkage_persisted()
    scenario_one_brief_one_link_no_duplicate_submission()
    scenario_readable_after_restart()
    scenario_linkage_failure_does_not_roll_back_trade()

    print("\n" + "=" * 60)
    print(f"PHASE G TASK 2 (brief_approvals) TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())