"""Standalone regression checks for
``Business.order_lifecycle_service.OrderLifecycleService``.

Covers Sprint 4 STEP 5 (Order lifecycle / business layer):

* NEW -> VALIDATED -> PENDING happy path (structural validation
  passes);
* NEW -> REJECTED with each LOCKED structural reason code;
* ``transition_status()`` persists status/reason via
  ``OrderRepository.update_status`` and re-reads current status from
  the repository rather than trusting a caller-supplied value;
* illegal transitions (out of PENDING, or skipping a state) raise
  ``ValidationError`` and never call ``OrderRepository.update_status``;
* this service never creates a Trade, never touches a Position, and
  never touches Account cash/equity -- there is no code path in this
  service that could, since it depends on ``OrderRepository`` only.

Run directly with ``python Tests/test_order_lifecycle_service.py`` --
no external test framework required, matching
``test_order_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.order_lifecycle_service import (  # noqa: E402
    REASON_INVALID_ACTION,
    REASON_INVALID_PRICE,
    REASON_INVALID_QUANTITY,
    REASON_INVALID_SYMBOL,
    OrderLifecycleService,
)
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402

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


def _build_service(tmp_dir: str) -> tuple[OrderLifecycleService, OrderRepository]:
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "order_lifecycle.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    order_repo = OrderRepository(manager)
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
    return OrderLifecycleService(order_repo), order_repo


def scenario_new_to_validated_to_pending_happy_path():
    print("\n[Scenario 1] NEW -> VALIDATED -> PENDING happy path")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo = _build_service(tmp)
        order = service.create_order(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
        )
        check(order.status == "PENDING", "create_order() ends at PENDING on valid input")
        check(order.reason == "queued after validation", "final PENDING reason is recorded")

        persisted = order_repo.get_by_id(order.order_id)
        check(persisted.status == "PENDING", "repository reflects the final PENDING status")
        check(persisted.reason == "queued after validation", "repository persisted the final reason")


def scenario_new_to_rejected_each_reason_code():
    print("\n[Scenario 2] NEW -> REJECTED for each structural rule")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo = _build_service(tmp)

        cases = [
            (dict(symbol="", action="BUY", quantity=100.0, requested_price=9500.0), REASON_INVALID_SYMBOL),
            (dict(symbol="   ", action="BUY", quantity=100.0, requested_price=9500.0), REASON_INVALID_SYMBOL),
            (dict(symbol="BBCA", action="HOLD", quantity=100.0, requested_price=9500.0), REASON_INVALID_ACTION),
            (dict(symbol="BBCA", action="BUY", quantity=0.0, requested_price=9500.0), REASON_INVALID_QUANTITY),
            (dict(symbol="BBCA", action="BUY", quantity=-5.0, requested_price=9500.0), REASON_INVALID_QUANTITY),
            (dict(symbol="BBCA", action="BUY", quantity=True, requested_price=9500.0), REASON_INVALID_QUANTITY),
            (dict(symbol="BBCA", action="BUY", quantity=100.0, requested_price=0.0), REASON_INVALID_PRICE),
            (dict(symbol="BBCA", action="BUY", quantity=100.0, requested_price=-1.0), REASON_INVALID_PRICE),
        ]
        for kwargs, expected_reason in cases:
            order = service.create_order(account_id="paper-id", **kwargs)
            check(
                order.status == "REJECTED",
                f"create_order({kwargs}) ends at REJECTED",
            )
            check(
                order.reason == expected_reason,
                f"create_order({kwargs}) records reason {expected_reason!r} (got {order.reason!r})",
            )
            persisted = order_repo.get_by_id(order.order_id)
            check(
                persisted.status == "REJECTED" and persisted.reason == expected_reason,
                "repository reflects the same REJECTED status/reason",
            )


def scenario_first_matching_rule_wins():
    print("\n[Scenario 3] first matching structural rule wins")
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _build_service(tmp)
        # Both symbol AND action are invalid -- INVALID_SYMBOL must win
        # (checked first in the LOCKED rule order).
        order = service.create_order(
            account_id="paper-id",
            symbol="",
            action="HOLD",
            quantity=-1.0,
            requested_price=-1.0,
        )
        check(
            order.reason == REASON_INVALID_SYMBOL,
            "the first failing rule (symbol) wins over later failing rules",
        )


def scenario_illegal_transition_rejected():
    print("\n[Scenario 4] illegal transitions are rejected")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo = _build_service(tmp)
        order = service.create_order(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
        )
        check(order.status == "PENDING", "setup: order reached PENDING")

        raised = False
        try:
            service.transition_status(order.order_id, "FILLED", "attempted illegal jump")
        except ValidationError:
            raised = True
        check(raised, "PENDING -> FILLED raises ValidationError (no transition defined yet)")

        unchanged = order_repo.get_by_id(order.order_id)
        check(
            unchanged.status == "PENDING" and unchanged.reason == "queued after validation",
            "illegal transition attempt left the persisted order untouched",
        )

        raised_missing = False
        try:
            service.transition_status(999999, "VALIDATED", "no such order")
        except ValidationError:
            raised_missing = True
        check(raised_missing, "transition_status() on a non-existent order_id raises ValidationError")


def scenario_skip_state_rejected():
    print("\n[Scenario 5] skipping a state (NEW -> PENDING directly) is illegal")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo = _build_service(tmp)
        order = service._order_repository.create(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
            filled_price=0.0,
            status="NEW",
            reason="",
        )
        raised = False
        try:
            service.transition_status(order.order_id, "PENDING", "skip VALIDATED")
        except ValidationError:
            raised = True
        check(raised, "NEW -> PENDING directly raises ValidationError (must pass through VALIDATED)")


def scenario_repository_called_correctly():
    print("\n[Scenario 6] repository is called with the right arguments")
    with tempfile.TemporaryDirectory() as tmp:
        service, order_repo = _build_service(tmp)

        calls = []
        original_update_status = order_repo.update_status

        def _spy_update_status(order_id, status, reason):
            calls.append((order_id, status, reason))
            return original_update_status(order_id, status, reason)

        order_repo.update_status = _spy_update_status  # type: ignore[method-assign]

        order = service.create_order(
            account_id="paper-id",
            symbol="BBCA",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
        )

        check(len(calls) == 2, "happy path calls update_status() exactly twice (VALIDATED, PENDING)")
        check(
            calls[0] == (order.order_id, "VALIDATED", "structural validation passed"),
            "first update_status() call moves NEW -> VALIDATED with the right reason",
        )
        check(
            calls[1] == (order.order_id, "PENDING", "queued after validation"),
            "second update_status() call moves VALIDATED -> PENDING with the right reason",
        )

        calls.clear()
        rejected = service.create_order(
            account_id="paper-id",
            symbol="",
            action="BUY",
            quantity=100.0,
            requested_price=9500.0,
        )
        check(len(calls) == 1, "rejected path calls update_status() exactly once")
        check(
            calls[0] == (rejected.order_id, "REJECTED", REASON_INVALID_SYMBOL),
            "rejected path calls update_status() with REJECTED + the right reason code",
        )


def scenario_no_trade_position_or_cash_side_effects():
    print("\n[Scenario 7] no Trade/Position/Cash side effects are possible")
    # Structural guarantee, not a runtime probe: OrderLifecycleService's
    # __init__ only ever accepts/stores an OrderRepository, so there is
    # no attribute through which it could reach a TradeRepository,
    # PositionRepository, or AccountRepository.
    with tempfile.TemporaryDirectory() as tmp:
        service, _ = _build_service(tmp)
        attrs = vars(service)
        check(
            list(attrs.keys()) == ["_order_repository"],
            "OrderLifecycleService holds exactly one collaborator: _order_repository",
        )


def main() -> int:
    scenario_new_to_validated_to_pending_happy_path()
    scenario_new_to_rejected_each_reason_code()
    scenario_first_matching_rule_wins()
    scenario_illegal_transition_rejected()
    scenario_skip_state_rejected()
    scenario_repository_called_correctly()
    scenario_no_trade_position_or_cash_side_effects()

    print("\n" + "=" * 60)
    print(f"SPRINT 4 STEP 5 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())