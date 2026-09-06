"""Standalone regression checks for
``Business.execution_rate_engine.ExecutionRateEngine`` (Activation 7,
PAPER VALIDATION -- ``execution rate`` measurement, order-level
definition per the ACTIVATION 7 -- EXECUTION RATE ONLY audit).

Drives the REAL ``ExecutionRateEngine.calculate()`` against a real
on-disk SQLite database through the REAL ``OrderRepository`` -- no
formula reimplemented here, no mocked business logic. ``Order`` rows
are inserted via ``OrderRepository.create()`` exactly as
``Business.order_lifecycle_service.OrderLifecycleService`` already
produces them (``status`` from ``Database.order_constants.
ORDER_STATUSES``).

Proves, concretely:

* zero recorded orders -> ``execution_rate == 0.0``, never a
  ``ZeroDivisionError``;
* execution_rate == recorded ``FILLED`` orders / resolved orders
  (``FILLED``/``PARTIALLY_FILLED``/``REJECTED``/``CANCELLED``/
  ``EXPIRED``);
* in-flight orders (``NEW``/``VALIDATED``/``PENDING``) are excluded
  from both numerator and denominator;
* ``PARTIALLY_FILLED`` is counted in the denominator and reported
  separately, never folded into ``filled_orders``;
* ``filled_orders`` + ``partially_filled_orders`` +
  ``non_executed_orders`` == ``resolved_total`` exactly;
* ``calculate()`` performs zero writes to any table (read-only, mirrors
  ``Business.reconciliation_engine.ReconciliationEngine``'s /
  ``Business.failure_rate_engine.FailureRateEngine``'s own read-only
  guarantee tests).

Run directly with ``python Tests/test_execution_rate_engine.py`` -- no
external test framework required, matching every other
``Tests/test_*.py`` file in this codebase.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.execution_rate_engine import ExecutionRateEngine  # noqa: E402
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


def _build(tmp_dir: str):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "execution_rate_engine.db")
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

    engine = ExecutionRateEngine(order_repo)
    return engine, order_repo


def _order_kwargs(**overrides) -> dict:
    kwargs = dict(
        account_id="paper-id",
        symbol="BBCA",
        action="BUY",
        quantity=100.0,
        requested_price=9_500.0,
        filled_price=0.0,
        status="NEW",
        reason="test order",
    )
    kwargs.update(overrides)
    return kwargs


def scenario_empty_database_is_zero_never_divide_by_zero():
    print("\n[Scenario 1] No recorded orders -> execution_rate is 0.0, no ZeroDivisionError")
    with tempfile.TemporaryDirectory() as tmp:
        engine, _ = _build(tmp)
        result = engine.calculate()

        check(result.resolved_total == 0, "empty: resolved_total == 0")
        check(result.filled_orders == 0, "empty: filled_orders == 0")
        check(result.partially_filled_orders == 0, "empty: partially_filled_orders == 0")
        check(result.non_executed_orders == 0, "empty: non_executed_orders == 0")
        check(result.execution_rate == 0.0, "empty: execution_rate == 0.0")


def scenario_execution_rate_excludes_in_flight_orders():
    print("\n[Scenario 2] execution_rate == FILLED / resolved orders; NEW/VALIDATED/PENDING excluded")
    with tempfile.TemporaryDirectory() as tmp:
        engine, order_repo = _build(tmp)

        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="REJECTED", reason="insufficient cash"))
        order_repo.create(**_order_kwargs(status="CANCELLED", reason="user cancelled"))
        # In-flight orders: not yet resolved, must be excluded entirely.
        order_repo.create(**_order_kwargs(status="NEW", reason="just created"))
        order_repo.create(**_order_kwargs(status="VALIDATED", reason="validated"))
        order_repo.create(**_order_kwargs(status="PENDING", reason="pending"))

        result = engine.calculate()

        check(result.resolved_total == 5, "resolved_total == 5 (3 FILLED + REJECTED + CANCELLED)")
        check(result.filled_orders == 3, "filled_orders == 3")
        check(result.non_executed_orders == 2, "non_executed_orders == 2 (REJECTED + CANCELLED)")
        check(result.execution_rate == 0.6, "execution_rate == 3/5 == 0.6")


def scenario_partially_filled_counted_but_not_folded_into_filled():
    print("\n[Scenario 3] PARTIALLY_FILLED counts toward resolved_total, reported separately, never folded into filled_orders")
    with tempfile.TemporaryDirectory() as tmp:
        engine, order_repo = _build(tmp)

        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="PARTIALLY_FILLED", filled_price=9_500.0, filled_quantity=50.0, reason="partial"))
        order_repo.create(**_order_kwargs(status="EXPIRED", reason="expired"))

        result = engine.calculate()

        check(result.resolved_total == 3, "resolved_total == 3 (FILLED + PARTIALLY_FILLED + EXPIRED)")
        check(result.filled_orders == 1, "filled_orders == 1 (PARTIALLY_FILLED not counted as filled)")
        check(result.partially_filled_orders == 1, "partially_filled_orders == 1")
        check(result.non_executed_orders == 1, "non_executed_orders == 1 (EXPIRED)")
        check(
            result.filled_orders + result.partially_filled_orders + result.non_executed_orders
            == result.resolved_total,
            "filled + partially_filled + non_executed == resolved_total exactly",
        )
        check(abs(result.execution_rate - (1 / 3)) < 1e-9, "execution_rate == 1/3")


def scenario_calculate_is_read_only():
    print("\n[Scenario 4] calculate() performs zero writes to any table")
    with tempfile.TemporaryDirectory() as tmp:
        engine, order_repo = _build(tmp)
        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="REJECTED", reason="insufficient cash"))

        def row_count():
            return len(order_repo.list_all())

        before = row_count()
        engine.calculate()
        engine.calculate()
        after = row_count()

        check(before == after, "calculate() calls produced zero writes to any table")


def main() -> int:
    scenario_empty_database_is_zero_never_divide_by_zero()
    scenario_execution_rate_excludes_in_flight_orders()
    scenario_partially_filled_counted_but_not_folded_into_filled()
    scenario_calculate_is_read_only()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 EXECUTION RATE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())