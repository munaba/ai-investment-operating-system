"""Standalone regression checks for Activation 5.1 -- Decision Linkage.

Covers ONLY what Activation 5.1 STEP 2 actually implemented (per the
Activation 5.1 STEP 1 audit): ``Order.analysis_snapshot_id``, the one
of the roadmap's 13 linkage fields with a genuine, already-existing
production source (``RankingSnapshot.snapshot_id``, already flowing
through ``PaperTradingEngine.submit_order()`` as ``signal_evidence``).

This file proves:

* ``analysis_snapshot_id`` is actually persisted on the ``Order`` row
  created by ``OrderLifecycleService.create_order()`` (not just held
  in memory on the returned object);
* it survives a fresh ``OrderRepository.get_by_id()`` read -- i.e. it
  round-trips through SQLite, not just through the Python object the
  ``create()`` call happened to return;
* it is still correct after ``PaperTradingEngine.submit_order()``
  drives an order all the way through to a filled ``Trade`` (the
  linkage is not lost partway through the pipeline);
* ``PaperTradingEngine`` extracts it via a plain, non-raising
  ``getattr`` -- a ``signal_evidence`` object that does NOT carry a
  ``snapshot_id`` attribute (a plain ``dict``, exactly what every
  pre-existing test in ``test_paper_trading_engine.py`` already
  passes) still works unchanged and simply persists ``None``, never a
  fabricated value;
* ``Trade.order_id -> Order.order_id`` linkage is unchanged (Activation
  3.x behavior not touched by this STEP);
* ``timestamp`` fields (``Order.created_at``, ``Trade.executed_at``,
  ``Order.filled_at``) come from real, caller-supplied/repository-
  generated data, not something invented by this STEP;
* ``Position`` is NOT claimed to carry any order/trade linkage --
  this STEP does not add one, and this test asserts that absence
  explicitly rather than silently assuming it;
* none of the other 12 roadmap 5.1 fields were fabricated as new
  ``Order``/``Trade``/``Position`` attributes by this STEP.

Run directly with ``python Tests/test_activation5_1_decision_linkage.py``
-- no external test framework required, matching every other
standalone test in this suite.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_service import ExecutionService  # noqa: E402
from Business.order_lifecycle_service import OrderLifecycleService  # noqa: E402
from Business.paper_trading_engine import PaperTradingEngine  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.models import Order, Position, Trade  # noqa: E402
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


@dataclass
class _FakeRankingSnapshot:
    """Minimal stand-in for ``Database.models.RankingSnapshot``, shaped
    exactly like what ``main.py``'s production CLI path passes as
    ``signal_evidence`` (a real ``RankingSnapshot`` row). Only the one
    attribute this STEP actually reads (``snapshot_id``) is needed.
    """

    snapshot_id: int


def _build_engine(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "activation5_1.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(IDEMPOTENCY_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    position_repo = PositionRepository(manager)
    order_repo = OrderRepository(manager)
    trade_repo = TradeRepository(manager)
    idempotency_repo = OrderIdempotencyRepository(manager)
    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )
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
    repos = {
        "account": account_repo,
        "position": position_repo,
        "order": order_repo,
        "trade": trade_repo,
        "idempotency": idempotency_repo,
    }
    return db, engine, repos


def scenario_order_repository_persists_analysis_snapshot_id():
    print("\n[Scenario 1] OrderRepository.create() persists analysis_snapshot_id")
    with tempfile.TemporaryDirectory() as tmp:
        db, engine, repos = _build_engine(tmp)
        try:
            order_repo = repos["order"]

            order = order_repo.create(
                account_id="paper-id",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,
                requested_price=9500.0,
                filled_price=0.0,
                status="NEW",
                reason="",
                analysis_snapshot_id=42,
            )
            check(
                order.analysis_snapshot_id == 42,
                "create() returns Order with analysis_snapshot_id set",
            )

            # Round-trip through SQLite, not just the in-memory return value.
            reloaded = order_repo.get_by_id(order.order_id)
            check(reloaded is not None, "order round-trips via get_by_id()")
            check(
                reloaded.analysis_snapshot_id == 42,
                f"analysis_snapshot_id survives persistence round-trip (got {reloaded.analysis_snapshot_id!r})",
            )

            # Default (no snapshot supplied) is None, never fabricated.
            order_no_snapshot = order_repo.create(
                account_id="paper-id",
                symbol="TLKM",
                action="BUY",
                quantity=100.0,
                requested_price=3000.0,
                filled_price=0.0,
                status="NEW",
                reason="",
            )
            check(
                order_no_snapshot.analysis_snapshot_id is None,
                "analysis_snapshot_id defaults to None when caller supplies none",
            )
            reloaded_no_snapshot = order_repo.get_by_id(order_no_snapshot.order_id)
            check(
                reloaded_no_snapshot.analysis_snapshot_id is None,
                "None round-trips as NULL, not a fabricated value",
            )
        finally:
            db.disconnect()


def scenario_order_lifecycle_service_passes_through_unchanged_state_machine():
    print("\n[Scenario 2] OrderLifecycleService.create_order() threads analysis_snapshot_id "
          "through the UNCHANGED state machine")
    with tempfile.TemporaryDirectory() as tmp:
        db, engine, repos = _build_engine(tmp)
        try:
            order_repo = repos["order"]
            service = OrderLifecycleService(order_repo)

            order = service.create_order(
                account_id="paper-id",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,
                requested_price=9500.0,
                analysis_snapshot_id=7,
            )
            check(order.status == "PENDING", "structurally valid order still reaches PENDING")
            check(
                order.analysis_snapshot_id == 7,
                "analysis_snapshot_id survives NEW -> VALIDATED -> PENDING transitions",
            )
            reloaded = order_repo.get_by_id(order.order_id)
            check(
                reloaded.analysis_snapshot_id == 7,
                "analysis_snapshot_id persisted correctly across the transition sequence",
            )

            # Structurally invalid order: still REJECTED for the same
            # reason as before this STEP -- analysis_snapshot_id does
            # not change validation behavior.
            rejected = service.create_order(
                account_id="paper-id",
                symbol="",
                action="BUY",
                quantity=100.0,
                requested_price=9500.0,
                analysis_snapshot_id=99,
            )
            check(rejected.status == "REJECTED", "invalid order is still REJECTED (unchanged)")
            check(
                rejected.reason == "INVALID_SYMBOL",
                "REJECTED reason code is unchanged by this STEP",
            )
            check(
                rejected.analysis_snapshot_id == 99,
                "analysis_snapshot_id is still persisted even on a REJECTED order",
            )
        finally:
            db.disconnect()


def scenario_end_to_end_linkage_survives_submit_order():
    print("\n[Scenario 3] End-to-end: scan-snapshot -> submit_order() -> Order/Trade linkage intact")
    with tempfile.TemporaryDirectory() as tmp:
        db, engine, repos = _build_engine(tmp)
        try:
            snapshot = _FakeRankingSnapshot(snapshot_id=123)

            trade = engine.submit_order(
                account_id="paper-id",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,
                requested_price=9500.0,
                executed_at="2026-08-11T03:00:00+00:00",
                signal_evidence=snapshot,
                user_approval=True,
                idempotency_key="req-linkage-001",
            )

            order = repos["order"].get_by_id(trade.order_id)
            check(order is not None, "Order created by submit_order() is retrievable")
            check(
                order.analysis_snapshot_id == 123,
                f"analysis_snapshot_id extracted from signal_evidence.snapshot_id and persisted "
                f"(got {order.analysis_snapshot_id!r})",
            )

            # order_id -> trade_id linkage (Activation 3.x, unchanged).
            check(trade.order_id == order.order_id, "Trade.order_id matches the Order it came from")
            reloaded_trade = repos["trade"].get_by_id(trade.trade_id)
            check(reloaded_trade is not None, "Trade round-trips via get_by_id()")
            check(
                reloaded_trade.order_id == order.order_id,
                "persisted Trade.order_id still matches Order.order_id after reload",
            )

            # timestamp: real, caller-supplied/repository-generated data.
            check(
                order.filled_at == trade.executed_at,
                "Order.filled_at mirrors Trade.executed_at (Activation 3.4 contract, unchanged)",
            )
            check(
                trade.executed_at == "2026-08-11T03:00:00+00:00",
                "Trade.executed_at is exactly the caller-supplied executed_at -- nothing invented",
            )
            check(
                isinstance(order.created_at, str) and len(order.created_at) > 0,
                "Order.created_at is a real repository-generated timestamp",
            )

            # position: NOT claimed to carry any order/trade linkage --
            # this STEP does not add one. Assert the absence explicitly.
            positions = repos["position"].list_all()
            check(len(positions) == 1, "exactly one Position resulted from the BUY")
            position = positions[0]
            check(
                not hasattr(position, "order_id") and not hasattr(position, "trade_id"),
                "Position carries NO order_id/trade_id linkage -- not claimed, not fabricated by this STEP",
            )
            check(
                position.account_id == order.account_id and position.symbol == order.symbol,
                "Position is only traceable to the decision via (account_id, symbol) -- the "
                "pre-existing, weaker linkage this STEP leaves unchanged",
            )
        finally:
            db.disconnect()


def scenario_signal_evidence_without_snapshot_id_is_not_fabricated():
    print("\n[Scenario 4] signal_evidence without a snapshot_id attribute (e.g. a plain dict, "
          "exactly what every pre-existing PaperTradingEngine test already passes) "
          "persists None, never a guessed value")
    with tempfile.TemporaryDirectory() as tmp:
        db, engine, repos = _build_engine(tmp)
        try:
            trade = engine.submit_order(
                account_id="paper-id",
                symbol="BBCA",
                action="BUY",
                quantity=100.0,
                requested_price=9500.0,
                executed_at="2026-08-11T03:00:00+00:00",
                signal_evidence={"rsi": 28.0, "note": "oversold bounce"},
                user_approval=True,
                idempotency_key="req-linkage-002",
            )
            order = repos["order"].get_by_id(trade.order_id)
            check(
                order.analysis_snapshot_id is None,
                "plain-dict signal_evidence (no snapshot_id attribute) persists analysis_snapshot_id=None",
            )
        finally:
            db.disconnect()


def scenario_no_other_field_was_fabricated():
    print("\n[Scenario 5] None of the other 12 roadmap 5.1 fields were fabricated as new "
          "Order/Trade/Position attributes by this STEP")
    order_fields = set(Order.__dataclass_fields__.keys())
    trade_fields = set(Trade.__dataclass_fields__.keys())
    position_fields = set(Position.__dataclass_fields__.keys())

    check("analysis_snapshot_id" in order_fields, "Order gained exactly analysis_snapshot_id (this STEP's scope)")

    not_fabricated = (
        "signal_id",
        "recommendation_id",
        "strategy_name",
        "strategy_version",
        "entry_reason",
        "exit_reason",
        "risk_validation_id",
        "approval_id",
    )
    for field_name in not_fabricated:
        check(
            field_name not in order_fields
            and field_name not in trade_fields
            and field_name not in position_fields,
            f"'{field_name}' was NOT added anywhere -- still an honest GAP, not fabricated",
        )


def scenario_activation_3x_state_machine_and_gates_unchanged():
    print("\n[Scenario 6] Activation 3.x/4 behavior is unchanged by this STEP")
    with tempfile.TemporaryDirectory() as tmp:
        db, engine, repos = _build_engine(tmp)
        try:
            # A pre-trade gate failure still touches zero orders/trades,
            # exactly as Activation 3.2 established -- analysis_snapshot_id
            # plays no role in any of the 12 gates.
            try:
                engine.submit_order(
                    account_id="paper-id",
                    symbol="BBCA",
                    action="BUY",
                    quantity=100.0,
                    requested_price=9500.0,
                    executed_at="2026-08-11T03:00:00+00:00",
                    signal_evidence=None,  # gate 2: evidence missing
                    user_approval=True,
                    idempotency_key="req-linkage-003",
                )
                check(False, "gate 2 (evidence missing) should have raised ValidationError")
            except Exception as exc:  # noqa: BLE001 - broad on purpose for the proof
                check(
                    type(exc).__name__ == "ValidationError",
                    "gate 2 still rejects falsy signal_evidence with ValidationError (unchanged)",
                )
            check(len(repos["order"].list_all()) == 0, "no Order row created on a rejected pre-trade gate")
            check(len(repos["trade"].list_all()) == 0, "no Trade row created on a rejected pre-trade gate")

            # OrderLifecycleService still holds exactly one collaborator.
            service = OrderLifecycleService(repos["order"])
            check(
                list(vars(service).keys()) == ["_order_repository"],
                "OrderLifecycleService still holds exactly one collaborator (unchanged)",
            )
        finally:
            db.disconnect()


def main() -> int:
    scenario_order_repository_persists_analysis_snapshot_id()
    scenario_order_lifecycle_service_passes_through_unchanged_state_machine()
    scenario_end_to_end_linkage_survives_submit_order()
    scenario_signal_evidence_without_snapshot_id_is_not_fabricated()
    scenario_no_other_field_was_fabricated()
    scenario_activation_3x_state_machine_and_gates_unchanged()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"ACTIVATION 5.1 DECISION LINKAGE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for description in _FAILURES:
            print(f"  - {description}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())