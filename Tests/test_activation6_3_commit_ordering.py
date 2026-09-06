"""
Activation 6.3 proof suite -- commit ordering (VERIFY ONLY).

Roadmap target (``Master Prompt (Roadmap).md`` -> ACTIVATION 6 -> 6.3
"Commit ordering"):

    Event ``ORDER_EXECUTED`` hanya dikirim setelah database transaction
    berhasil commit. Jangan mengirim notifikasi sukses sebelum state
    berhasil disimpan.

This suite does not change ``Business.paper_trading_engine.
PaperTradingEngine`` or ``Core.composition_root`` -- it only proves the
already-implemented ``submit_order()`` sequence (pre-trade gates ->
``OrderLifecycleService.create_order()`` -> ``ExecutionService.
execute_order()`` -> ``AccountBalanceService.apply_trade()`` ->
``PositionManager.apply_trade()`` -> ``OrderIdempotencyRepository.
create()`` -> best-effort ``ORDER_EXECUTED`` notify, wrapped in its own
``try/except Exception: pass``) already satisfies every acceptance
point asked for:

    1. successful order -> DB commit -> ``ORDER_EXECUTED`` is sent;
    2. the final write (``OrderIdempotencyRepository.create()``) fails
       -> no ``ORDER_EXECUTED`` is ever sent;
    3. notification fails after commit -> Order/Trade/Account/Position
       remain committed (unaffected by the notification failure);
    4. restart (fresh ``DatabaseManager``/connection over the same
       SQLite file) still shows the correct, already-committed state;
    5. no duplicate ``ORDER_EXECUTED`` is ever sent for one order.

Uses a real, temporary SQLite database and the real production
``PaperTradingEngine``/``OrderLifecycleService``/``ExecutionService``/
``AccountBalanceService``/``PositionManager``/``OrderIdempotencyRepository``
-- the same construction helper ``Tests/test_paper_trading_engine.py``
already established. Only ``notification_manager``/
``order_idempotency_repository.create`` are ever swapped for a
recording spy or a fault-injecting wrapper, never any trading
component.

Run directly:
``python Tests/test_activation6_3_commit_ordering.py``
-- no external test framework required.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.account_balance_service import AccountBalanceService  # noqa: E402
from Business.execution_service import ExecutionService  # noqa: E402
from Business.notification_builder import NotificationBuilder  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Core.exceptions import RepositoryError, ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import Trade  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_idempotency_repository import (  # noqa: E402
    OrderIdempotencyRepository,
)
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


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
# Recording notification double -- never touches Repository/Database, only
# records that it was called (and with which event), mirroring the real
# NotificationManager's LOCKED single-method contract (notify(event) -> None).
# ---------------------------------------------------------------------------
class _RecordingNotificationManager:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: List[Any] = []

    def notify(self, event: Any) -> None:
        self.calls.append(event)
        if self.fail:
            raise RuntimeError("simulated notification failure (e.g. Telegram down)")


def _make_db_path(tmp_dir: str) -> Path:
    return Path(tmp_dir) / "activation6_3.db"


def _open_manager(db_path: Path) -> DatabaseManager:
    """Open a fresh connection over ``db_path`` -- used both for the
    initial build and to simulate a process restart (Scenario 4)."""
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    return DatabaseManager(db, cfg)


def _apply_migrations(manager: DatabaseManager) -> None:
    db = manager.database
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)


def _repos(manager: DatabaseManager) -> Dict[str, Any]:
    return {
        "account": AccountRepository(manager),
        "position": PositionRepository(manager),
        "order": OrderRepository(manager),
        "trade": TradeRepository(manager),
        "idempotency": OrderIdempotencyRepository(manager),
    }


def _build_engine(
    manager: DatabaseManager,
    repos: Dict[str, Any],
    *,
    notification_manager: Any = None,
    max_order_value: float = 1_000_000_000.0,
) -> PaperTradingEngine:
    order_lifecycle_service = OrderLifecycleService(repos["order"])
    execution_service = ExecutionService(repos["order"], repos["trade"])
    return PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=repos["account"],
        position_repository=repos["position"],
        order_idempotency_repository=repos["idempotency"],
        kill_switch_engaged=False,
        max_order_value=max_order_value,
        account_balance_service=AccountBalanceService(repos["account"]),
        position_manager=PositionManager(repos["position"]),
        notification_builder=NotificationBuilder(),
        notification_manager=notification_manager if notification_manager is not None else _RecordingNotificationManager(),
    )


def _default_order_kwargs(**overrides: Any) -> dict:
    kwargs = dict(
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        requested_price=9500.0,
        executed_at="2026-08-13T10:00:00+00:00",
        signal_evidence={"rsi": 28.0, "note": "oversold bounce"},
        user_approval=True,
        idempotency_key="6.3-req-001",
    )
    kwargs.update(overrides)
    return kwargs


def _committed_state(repos: Dict[str, Any], account_id: str = "paper-id") -> Dict[str, Any]:
    account = repos["account"].get_by_id(account_id)
    return {
        "cash": account.cash if account else None,
        "equity": account.equity if account else None,
        "orders": [o.order_id for o in repos["order"].list_all()],
        "trades": [t.trade_id for t in repos["trade"].list_all()],
        "positions": [(p.position_id, p.status, p.quantity) for p in repos["position"].list_all()],
        "idempotency_keys": sorted(
            row.idempotency_key for row in ([repos["idempotency"].get_by_key("6.3-req-001")] if repos["idempotency"].get_by_key("6.3-req-001") else [])
        ),
    }


# ---------------------------------------------------------------------------
# Scenario 1 -- successful order -> DB commit -> ORDER_EXECUTED sent
# ---------------------------------------------------------------------------
def scenario_success_commits_then_notifies() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_db_path(tmp)
        manager = _open_manager(db_path)
        _apply_migrations(manager)
        repos = _repos(manager)
        repos["account"].create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id", cash=100_000_000.0,
            equity=100_000_000.0, buying_power=100_000_000.0,
        )
        notifier = _RecordingNotificationManager()
        engine = _build_engine(manager, repos, notification_manager=notifier)

        trade = engine.submit_order(**_default_order_kwargs())

        check(isinstance(trade, Trade), "S1: submit_order() returns a real Trade on success")

        order = repos["order"].get_by_id(trade.order_id)
        check(order is not None and order.status == "FILLED", "S1: Order row committed with status FILLED")
        trades = repos["trade"].list_by_order(trade.order_id)
        check(len(trades) == 1, "S1: exactly one Trade row committed")
        account = repos["account"].get_by_id("paper-id")
        check(account.cash < 100_000_000.0, "S1: Account cash was debited (committed)")
        positions = repos["position"].list_all()
        check(len(positions) == 1 and positions[0].quantity == 100.0, "S1: Position row committed")
        idem = repos["idempotency"].get_by_key("6.3-req-001")
        check(idem is not None, "S1: idempotency key committed")

        check(len(notifier.calls) == 1, "S1: ORDER_EXECUTED notification was sent exactly once")
        if notifier.calls:
            from Business.notification_event import NotificationEventType
            event = notifier.calls[0]
            check(
                event.event_type == NotificationEventType.ORDER_EXECUTED,
                "S1: the sent event's type is ORDER_EXECUTED",
            )
            check(
                event.metadata.get("trade_id") == trade.trade_id,
                "S1: the sent event carries this exact Trade's trade_id",
            )


# ---------------------------------------------------------------------------
# Scenario 2 -- final idempotency write fails -> no ORDER_EXECUTED sent
# ---------------------------------------------------------------------------
def scenario_final_write_failure_blocks_notification() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_db_path(tmp)
        manager = _open_manager(db_path)
        _apply_migrations(manager)
        repos = _repos(manager)
        repos["account"].create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id", cash=100_000_000.0,
            equity=100_000_000.0, buying_power=100_000_000.0,
        )
        notifier = _RecordingNotificationManager()
        engine = _build_engine(manager, repos, notification_manager=notifier)

        # Fault-inject the LAST write in submit_order()'s sequence --
        # OrderIdempotencyRepository.create() -- while leaving every
        # earlier write (Order/Trade/Account/Position) untouched, real
        # production code.
        real_create = repos["idempotency"].create

        def _failing_create(*args: Any, **kwargs: Any) -> Any:
            raise RepositoryError("simulated idempotency-key write failure")

        repos["idempotency"].create = _failing_create  # type: ignore[assignment]

        raised: Exception | None = None
        try:
            engine.submit_order(**_default_order_kwargs(idempotency_key="6.3-req-fail"))
        except Exception as exc:  # noqa: BLE001
            raised = exc

        repos["idempotency"].create = real_create  # restore for later checks

        check(raised is not None, "S2: submit_order() raises when the final idempotency write fails")
        check(
            isinstance(raised, RepositoryError),
            "S2: the raised exception is the RepositoryError the write actually failed with "
            "(not swallowed/re-wrapped)",
        )
        check(len(notifier.calls) == 0, "S2: ORDER_EXECUTED was never sent when the final write failed")

        idem = repos["idempotency"].get_by_key("6.3-req-fail")
        check(idem is None, "S2: no idempotency-key row exists after the failed write")

        # Order/Trade/Account/Position from THIS attempt were still
        # written by the earlier, real steps (documented, pre-existing
        # trade-off in the module's own LOCKED DECISION on write
        # timing) -- confirms the failure is isolated to the
        # notification decision, not fabricated data hiding elsewhere.
        orders = repos["order"].list_all()
        check(len(orders) == 1, "S2: the Order from this attempt is still the real, committed one (unchanged pre-existing behavior)")


# ---------------------------------------------------------------------------
# Scenario 3 -- notification fails AFTER commit -> trading state unaffected
# ---------------------------------------------------------------------------
def scenario_notification_failure_does_not_roll_back_trade() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_db_path(tmp)
        manager = _open_manager(db_path)
        _apply_migrations(manager)
        repos = _repos(manager)
        repos["account"].create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id", cash=100_000_000.0,
            equity=100_000_000.0, buying_power=100_000_000.0,
        )
        failing_notifier = _RecordingNotificationManager(fail=True)
        engine = _build_engine(manager, repos, notification_manager=failing_notifier)

        raised: Exception | None = None
        trade = None
        try:
            trade = engine.submit_order(**_default_order_kwargs(idempotency_key="6.3-req-notify-fail"))
        except Exception as exc:  # noqa: BLE001
            raised = exc

        check(raised is None, "S3: submit_order() does NOT raise even though the notification send failed")
        check(isinstance(trade, Trade), "S3: submit_order() still returns the real Trade despite the notification failure")
        check(len(failing_notifier.calls) == 1, "S3: the notification attempt did happen (and failed) -- not skipped")

        order = repos["order"].get_by_id(trade.order_id)
        check(order is not None and order.status == "FILLED", "S3: Order remains committed as FILLED")
        check(len(repos["trade"].list_by_order(trade.order_id)) == 1, "S3: Trade remains committed")
        account = repos["account"].get_by_id("paper-id")
        check(account.cash < 100_000_000.0, "S3: Account cash debit remains committed")
        check(len(repos["position"].list_all()) == 1, "S3: Position remains committed")
        idem = repos["idempotency"].get_by_key("6.3-req-notify-fail")
        check(idem is not None, "S3: idempotency key remains committed")


# ---------------------------------------------------------------------------
# Scenario 4 -- restart (fresh connection) still shows correct state
# ---------------------------------------------------------------------------
def scenario_restart_preserves_correct_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_db_path(tmp)
        manager = _open_manager(db_path)
        _apply_migrations(manager)
        repos = _repos(manager)
        repos["account"].create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id", cash=100_000_000.0,
            equity=100_000_000.0, buying_power=100_000_000.0,
        )
        engine = _build_engine(manager, repos)
        trade = engine.submit_order(**_default_order_kwargs(idempotency_key="6.3-req-restart"))
        before_restart = _committed_state(repos)

        manager.disconnect()

        # "Restart": brand-new SQLiteDatabase/DatabaseManager/Repository
        # instances over the SAME on-disk file -- nothing in-memory is
        # reused, mirroring a real process restart.
        manager2 = _open_manager(db_path)
        repos2 = _repos(manager2)
        after_restart = _committed_state(repos2)

        check(before_restart == after_restart, "S4: committed state is byte-for-byte identical across a simulated restart")

        order_after = repos2["order"].get_by_id(trade.order_id)
        check(order_after is not None and order_after.status == "FILLED", "S4: Order survives restart as FILLED")
        idem_after = repos2["idempotency"].get_by_key("6.3-req-restart")
        check(idem_after is not None, "S4: idempotency key survives restart")

        # Re-submitting the SAME idempotency_key after restart must still
        # be rejected by gate 10 -- proves duplicate protection survives
        # a restart too (ties into Scenario 5's no-duplicate guarantee).
        engine2 = _build_engine(manager2, repos2)
        dup_raised = None
        try:
            engine2.submit_order(**_default_order_kwargs(idempotency_key="6.3-req-restart"))
        except ValidationError as exc:
            dup_raised = exc
        check(
            dup_raised is not None and dup_raised.details.get("reason") == "DUPLICATE_REQUEST",
            "S4: after restart, resubmitting the same idempotency_key is still rejected as a duplicate",
        )

        manager2.disconnect()


# ---------------------------------------------------------------------------
# Scenario 5 -- no duplicate ORDER_EXECUTED
# ---------------------------------------------------------------------------
def scenario_no_duplicate_order_executed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = _make_db_path(tmp)
        manager = _open_manager(db_path)
        _apply_migrations(manager)
        repos = _repos(manager)
        repos["account"].create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id", cash=100_000_000.0,
            equity=100_000_000.0, buying_power=100_000_000.0,
        )
        notifier = _RecordingNotificationManager()
        engine = _build_engine(manager, repos, notification_manager=notifier)

        trade1 = engine.submit_order(**_default_order_kwargs(idempotency_key="6.3-req-dup"))
        check(len(notifier.calls) == 1, "S5: first submission sends exactly one ORDER_EXECUTED")

        # Same idempotency_key again -> gate 10 rejects before any
        # create_order()/execute_order() call, so no second Trade and
        # no second notification are even attempted.
        dup_raised = None
        try:
            engine.submit_order(**_default_order_kwargs(idempotency_key="6.3-req-dup"))
        except ValidationError as exc:
            dup_raised = exc

        check(dup_raised is not None and dup_raised.details.get("reason") == "DUPLICATE_REQUEST", "S5: resubmitting the same idempotency_key is rejected")
        check(len(notifier.calls) == 1, "S5: still exactly one ORDER_EXECUTED after the rejected duplicate resubmission")

        trades_for_order = repos["trade"].list_by_order(trade1.order_id)
        check(len(trades_for_order) == 1, "S5: still exactly one Trade row for the original order -- no duplicate Trade created")

        # A genuinely different order (different key) legitimately
        # produces its own, separate ORDER_EXECUTED -- proves the
        # single-notify guarantee is per-order, not a global lockout.
        trade2 = engine.submit_order(**_default_order_kwargs(idempotency_key="6.3-req-dup-2", symbol="TLKM"))
        check(len(notifier.calls) == 2, "S5: a second, genuinely distinct order still gets its own single ORDER_EXECUTED")
        check(trade2.trade_id != trade1.trade_id, "S5: the second order produced a different Trade")


# ---------------------------------------------------------------------------
# Regression -- 6.1, 6.2, PaperTradingEngine, notification, Activation 5.x
# ---------------------------------------------------------------------------
def scenario_regression_suites_still_pass() -> None:
    suite_files = [
        "test_paper_trading_engine.py",
        "test_stage_sprint4_step9_paper_trading_engine_wiring.py",
        "test_notification_event.py",
        "test_notification_builder.py",
        "test_notification_dispatcher.py",
        "test_notification_manager.py",
        "test_telegram_notification_channel.py",
        "test_stage_sprint7_step7_notification_wiring.py",
        "test_activation6_1_telegram_credential_wiring.py",
        "test_activation6_2_notification_failure_propagation.py",
        "test_activation5_1_decision_linkage.py",
        "test_activation5_6_wiring.py",
        "activation5_5_acceptance_proof.py",
        "activation5_6_acceptance_proof.py",
    ]
    for suite_file in suite_files:
        suite_path = _PROJECT_ROOT / "Tests" / suite_file
        check(suite_path.is_file(), f"{suite_file} still exists")
        result = subprocess.run(
            [sys.executable, str(suite_path)],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        check(
            result.returncode == 0,
            f"REGRESSION: {suite_file} still exits 0 "
            f"[stderr tail: {result.stderr[-400:] if result.returncode != 0 else ''}]",
        )


def main() -> int:
    scenarios = [
        scenario_success_commits_then_notifies,
        scenario_final_write_failure_blocks_notification,
        scenario_notification_failure_does_not_roll_back_trade,
        scenario_restart_preserves_correct_state,
        scenario_no_duplicate_order_executed,
        scenario_regression_suites_still_pass,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(
        f"ACTIVATION 6.3 COMMIT ORDERING VERIFICATION RESULTS: "
        f"{_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})"
    )
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())