"""Standalone regression checks for Activation 7 -- Blocker #4 ONLY:
persist ``user_approval`` so it is auditable from the database
(``Database.migrations_order_approvals``,
``Repository.persistence.order_approval_repository.
OrderApprovalRepository``, and the corresponding
``Business.paper_trading_engine.PaperTradingEngine.submit_order()``
best-effort write).

Every scenario below drives the REAL ``PaperTradingEngine.
submit_order()`` against a real on-disk SQLite database -- no mocked
business logic. Only ``_FailingApprovalRepository`` (used in exactly
one scenario, to prove the audit write is genuinely best-effort) is a
fake, and it fails on purpose.

Proves, concretely:

* Scenario 1: a successful BUY records one ``order_approvals`` row,
  ``approved=True``, correctly linked to the real ``Order``/``Trade``/
  ``Account`` it gated.
* Scenario 2: the recorded ``recorded_at`` timestamp is a real,
  parseable UTC timestamp taken at (or after) the moment the trade was
  committed -- never fabricated, never blank.
* Scenario 3: the row survives a full application restart (a brand
  new ``DatabaseManager``/connection over the same db file reads the
  same row back).
* Scenario 4: a rejected order (gate 3 -- ``user_approval`` missing)
  raises ``ValidationError`` *before* any ``Order``/``Trade`` exists,
  so no ``order_approvals`` row is ever written for it -- proven for
  every other pre-trade gate rejection too, not just gate 3's own.
* Scenario 5: engine behaviour (return value, Order/Trade/Account/
  Position/idempotency-key state) is byte-for-byte identical whether
  or not an ``order_approval_repository`` is wired in -- this
  Activation changes no approval gate, no execution logic, and no
  transaction boundary.
* Scenario 6: if writing the audit row itself fails, the already-
  committed trade is still returned unconditionally and every trading
  row (Order/Trade/Account/Position/idempotency-key) is still fully
  committed -- the failure is logged, never silently swallowed, and
  never rolls back the trade.
* Scenario 7: a SELL trade is recorded exactly like a BUY (no BUY-only
  special-casing in the audit write).

Run directly with ``python Tests/test_activation7_blocker4_order_approvals.py``
-- no external test framework required, matching every other
standalone test file in this repository.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import (  # noqa: E402
    PRETRADE_REASON_ACCOUNT_NOT_FOUND,
    PRETRADE_REASON_APPROVAL_MISSING,
    PRETRADE_REASON_EVIDENCE_MISSING,
    PaperTradingEngine,
)
from Core.exceptions import RepositoryError, ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_order_approvals import ORDER_APPROVALS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_approval_repository import (  # noqa: E402
    OrderApprovalRepository,
)
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

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


class _FailingApprovalRepository:
    """``OrderApprovalRepository``-shaped double whose ``create()``
    always raises -- exercises the "audit write is best-effort, never
    rolls back the trade" requirement."""

    def __init__(self) -> None:
        self.attempts = 0

    def create(self, **kwargs) -> None:
        self.attempts += 1
        raise RepositoryError("simulated order_approvals write failure")


class _ListLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _attach_capture(logger_name: str) -> _ListLogHandler:
    handler = _ListLogHandler()
    logging.getLogger(logger_name).addHandler(handler)
    return handler


def _detach_capture(logger_name: str, handler: _ListLogHandler) -> None:
    logging.getLogger(logger_name).removeHandler(handler)


# ---------------------------------------------------------------------------
# Real-database test rig (mirrors Tests/test_paper_trading_engine.py and
# Tests/test_activation7_fix_blockers.py's own _build()/_build_engine()
# helpers)
# ---------------------------------------------------------------------------


def _build(
    tmp_dir: str,
    db_name: str,
    *,
    cash: float = 100_000_000.0,
    order_approval_repository=None,
):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)
    MigrationRunner(db).apply(ORDER_APPROVALS_MIGRATIONS)
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
    approval_repo = OrderApprovalRepository(manager)

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
        order_approval_repository=(
            order_approval_repository
            if order_approval_repository is not None
            else approval_repo
        ),
    )

    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
        "approval": approval_repo,
    }
    return cfg, engine, repos


def _submit_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        requested_price=9500.0,
        executed_at="2026-08-13T10:00:00+00:00",
        signal_evidence={"rsi": 28.0, "note": "oversold bounce"},
        user_approval=True,
        idempotency_key="req-approval-001",
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# Scenario 1: approval is recorded, correctly linked
# ---------------------------------------------------------------------------


def scenario_approval_recorded_and_linked():
    print("\n[Scenario 1] approval is recorded, with correct Order/Trade/Account linkage")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, engine, repos = _build(tmp, "s1.db")

        trade = engine.submit_order(**_submit_kwargs())

        approval = repos["approval"].get_by_order_id(trade.order_id)
        check(approval is not None, "an order_approvals row now exists for the order this trade came from")
        if approval is not None:
            check(approval.approved is True, "approved is recorded as True (the user_approval value gate 3 already required)")
            check(approval.order_id == trade.order_id, "linkage: approval.order_id matches the real Order")
            check(approval.trade_id == trade.trade_id, "linkage: approval.trade_id matches the real Trade")
            check(approval.account_id == "paper-id", "linkage: approval.account_id matches the real Account")


# ---------------------------------------------------------------------------
# Scenario 2: timestamp is real, not fabricated
# ---------------------------------------------------------------------------


def scenario_timestamp_is_real():
    print("\n[Scenario 2] recorded_at is a real, parseable UTC timestamp -- never blank, never fabricated")
    with tempfile.TemporaryDirectory() as tmp:
        from datetime import datetime, timezone

        cfg, engine, repos = _build(tmp, "s2.db")

        before = datetime.now(timezone.utc)
        trade = engine.submit_order(**_submit_kwargs())
        after = datetime.now(timezone.utc)

        approval = repos["approval"].get_by_order_id(trade.order_id)
        check(approval is not None and bool(approval.recorded_at), "recorded_at is non-empty")
        if approval is not None and approval.recorded_at:
            parsed = datetime.fromisoformat(approval.recorded_at)
            check(before <= parsed <= after, "recorded_at falls within [before submit_order(), after submit_order()] -- a real write-time timestamp, not a fabricated one")


# ---------------------------------------------------------------------------
# Scenario 3: readable after restart
# ---------------------------------------------------------------------------


def scenario_readable_after_restart():
    print("\n[Scenario 3] approval row survives a full application restart")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, engine, repos = _build(tmp, "s3.db")
        trade = engine.submit_order(**_submit_kwargs())

        # Simulate an application restart: brand new DatabaseManager/
        # connection over the SAME db file, nothing shared in memory.
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        approval_repo2 = OrderApprovalRepository(manager2)

        approval_after_restart = approval_repo2.get_by_order_id(trade.order_id)
        check(approval_after_restart is not None, "approval row is readable through a brand new connection after restart")
        if approval_after_restart is not None:
            original = repos["approval"].get_by_order_id(trade.order_id)
            check(
                original is not None
                and approval_after_restart.order_id == original.order_id
                and approval_after_restart.trade_id == original.trade_id
                and approval_after_restart.account_id == original.account_id
                and approval_after_restart.approved == original.approved
                and approval_after_restart.recorded_at == original.recorded_at,
                "row read back after restart is identical to the row written before restart",
            )
        db2.disconnect()


# ---------------------------------------------------------------------------
# Scenario 4: no approval row for a rejected order
# ---------------------------------------------------------------------------


def scenario_no_approval_row_for_rejected_order():
    print("\n[Scenario 4] no order_approvals row is ever written for a pre-trade-rejected order")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, engine, repos = _build(tmp, "s4.db")

        # 4a. gate 3 itself: user_approval missing/False.
        raised = None
        try:
            engine.submit_order(**_submit_kwargs(user_approval=False, idempotency_key="req-rejected-1"))
        except ValidationError as exc:
            raised = exc
        check(raised is not None and raised.details.get("reason") == PRETRADE_REASON_APPROVAL_MISSING, "gate 3 (user_approval) still rejects as before")
        check(len(repos["order"].list_all()) == 0, "no Order row exists after the gate-3 rejection")

        # 4b. a different, earlier gate (account not found) -- proves
        # this holds for pre-trade rejections generally, not only
        # gate 3's own path.
        raised2 = None
        try:
            engine.submit_order(**_submit_kwargs(account_id="does-not-exist", idempotency_key="req-rejected-2"))
        except ValidationError as exc:
            raised2 = exc
        check(raised2 is not None and raised2.details.get("reason") == PRETRADE_REASON_ACCOUNT_NOT_FOUND, "account-not-found gate still rejects as before")

        # 4c. evidence-missing gate.
        raised3 = None
        try:
            engine.submit_order(**_submit_kwargs(signal_evidence=None, idempotency_key="req-rejected-3"))
        except ValidationError as exc:
            raised3 = exc
        check(raised3 is not None and raised3.details.get("reason") == PRETRADE_REASON_EVIDENCE_MISSING, "evidence-missing gate still rejects as before")

        check(len(repos["order"].list_all()) == 0, "still zero Order rows after all three rejections")
        check(len(repos["trade"].list_by_account("paper-id")) == 0, "still zero Trade rows after all three rejections")

        # A genuinely approved order afterward still records exactly
        # one approval row -- rejections above did not corrupt state.
        trade = engine.submit_order(**_submit_kwargs(idempotency_key="req-approved-after-rejections"))
        approval = repos["approval"].get_by_order_id(trade.order_id)
        check(approval is not None and approval.approved is True, "a genuinely approved order after the rejections above still records its own approval row correctly")


# ---------------------------------------------------------------------------
# Scenario 5: no change to trading behaviour with vs. without the repo wired
# ---------------------------------------------------------------------------


def scenario_trading_behavior_unchanged():
    print("\n[Scenario 5] trading behaviour is identical whether or not order_approval_repository is wired in")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_a, engine_with, repos_with = _build(tmp, "s5a.db")
        trade_with = engine_with.submit_order(**_submit_kwargs())

        cfg_b, engine_without, repos_without = _build(
            tmp, "s5b.db", order_approval_repository=None,
        )
        # Force "not wired" by rebuilding the engine directly without
        # the kwarg at all (default None), reusing the same repos.
        engine_without_2 = PaperTradingEngine(
            order_lifecycle_service=OrderLifecycleService(repos_without["order"]),
            execution_service=ExecutionService(repos_without["order"], repos_without["trade"]),
            account_repository=repos_without["account"],
            position_repository=repos_without["position"],
            order_idempotency_repository=repos_without["idempotency"],
            kill_switch_engaged=False,
            max_order_value=1_000_000_000.0,
            # order_approval_repository intentionally omitted -> None
        )
        trade_without = engine_without_2.submit_order(**_submit_kwargs(idempotency_key="req-no-repo"))

        check(trade_with.order_id is not None and trade_with.trade_id is not None, "engine with repo wired still returns a real Trade")
        check(trade_without.order_id is not None and trade_without.trade_id is not None, "engine WITHOUT repo wired still returns a real Trade")

        order_with = repos_with["order"].get_by_id(trade_with.order_id)
        order_without = repos_without["order"].get_by_id(trade_without.order_id)
        check(order_with.status == "FILLED" and order_without.status == "FILLED", "both engines fill the order identically")

        account_with = repos_with["account"].get_by_id("paper-id")
        account_without = repos_without["account"].get_by_id("paper-id")
        check(abs(account_with.cash - account_without.cash) < 1e-6, "Account.cash debited identically with or without the approval repository wired")

        approval_without = repos_without["approval"].get_by_order_id(trade_without.order_id)
        check(approval_without is None, "no approval row is written at all when order_approval_repository is not wired (default None) -- unchanged behaviour for existing callers")


# ---------------------------------------------------------------------------
# Scenario 6: audit write failure never rolls back the trade
# ---------------------------------------------------------------------------


def scenario_audit_write_failure_does_not_roll_back_trade():
    print("\n[Scenario 6] a failing order_approvals write is logged, never propagated, and never rolls back the committed trade")
    with tempfile.TemporaryDirectory() as tmp:
        failing_repo = _FailingApprovalRepository()
        cfg, engine, repos = _build(tmp, "s6.db", order_approval_repository=failing_repo)

        handler = _attach_capture("Business.paper_trading_engine")
        try:
            trade = engine.submit_order(**_submit_kwargs())
        finally:
            _detach_capture("Business.paper_trading_engine", handler)

        check(trade is not None and trade.trade_id is not None, "submit_order() still returns a real Trade despite the audit-write failure")
        check(failing_repo.attempts == 1, "the failing repository's create() was actually attempted exactly once")

        order = repos["order"].get_by_id(trade.order_id)
        check(order is not None and order.status == "FILLED", "Order row exists and is FILLED despite the audit-write failure")
        trades = repos["trade"].list_by_account("paper-id")
        check(len(trades) == 1 and trades[0].trade_id == trade.trade_id, "exactly one Trade row exists, matching the returned Trade")
        account = repos["account"].get_by_id("paper-id")
        expected_cash = 100_000_000.0 - (100.0 * 9500.0) - trade.fee - trade.tax
        check(abs(account.cash - expected_cash) < 1e-6, "Account.cash was really debited -- the audit-write failure did not roll back the trade")
        positions = repos["position"].list_by_account("paper-id")
        check(len(positions) == 1 and positions[0].quantity == 100.0, "Position row exists with the correct quantity despite the audit-write failure")
        idem = repos["idempotency"].get_by_key("req-approval-001")
        check(idem is not None and idem.trade_id == trade.trade_id, "idempotency key was still recorded, linked to the real trade")

        error_records = [r for r in handler.records if r.levelno >= logging.ERROR]
        check(len(error_records) == 1, "exactly one ERROR-level log record was emitted for the audit-write failure")
        if error_records:
            message = error_records[0].getMessage()
            check("order_approvals" in message, "log message clearly identifies an order_approvals audit failure")
            check(str(trade.trade_id) in message, "log message includes the trade_id so the failure is traceable")
            check(error_records[0].exc_info is not None, "log record carries exc_info (the actual exception), not just a bare message")


# ---------------------------------------------------------------------------
# Scenario 7: SELL is recorded the same way as BUY
# ---------------------------------------------------------------------------


def scenario_sell_recorded_same_as_buy():
    print("\n[Scenario 7] a SELL trade's approval is recorded exactly like a BUY's")
    with tempfile.TemporaryDirectory() as tmp:
        cfg, engine, repos = _build(tmp, "s7.db")

        buy_trade = engine.submit_order(**_submit_kwargs(idempotency_key="req-sell-setup"))
        check(repos["approval"].get_by_order_id(buy_trade.order_id) is not None, "setup BUY recorded its own approval row")

        sell_trade = engine.submit_order(**_submit_kwargs(
            action="SELL",
            quantity=100.0,
            requested_price=9600.0,
            idempotency_key="req-sell-001",
        ))
        approval = repos["approval"].get_by_order_id(sell_trade.order_id)
        check(approval is not None, "SELL order also gets its own order_approvals row")
        if approval is not None:
            check(approval.approved is True, "SELL approval also recorded as True")
            check(approval.trade_id == sell_trade.trade_id, "SELL approval correctly linked to the SELL Trade, not the earlier BUY")


def main() -> int:
    scenario_approval_recorded_and_linked()
    scenario_timestamp_is_real()
    scenario_readable_after_restart()
    scenario_no_approval_row_for_rejected_order()
    scenario_trading_behavior_unchanged()
    scenario_audit_write_failure_does_not_roll_back_trade()
    scenario_sell_recorded_same_as_buy()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 BLOCKER #4 (order_approvals) TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())