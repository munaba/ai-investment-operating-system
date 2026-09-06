"""Standalone regression checks for
``Business.failure_rate_engine.FailureRateEngine`` (Activation 7,
PAPER VALIDATION -- ``failure rate`` measurement).

Drives the REAL ``FailureRateEngine.calculate()`` against a real
on-disk SQLite database through the REAL ``SnapshotRepository``/
``OrderRepository`` -- no formula reimplemented here, no mocked
business logic. ``RankingSnapshot`` rows are inserted via
``SnapshotRepository.create()`` exactly as ``ManualScanService``/
``Orchestration.watchlist_scanner.WatchlistScanner`` already produce
them (``status="success"``/``"error"``); ``Order`` rows are inserted
via ``OrderRepository.create()`` exactly as
``Business.order_lifecycle_service.OrderLifecycleService`` already
produces them (``status`` from ``Database.order_constants.
ORDER_STATUSES``).

Proves, concretely:

* zero recorded outcomes -> every rate is ``0.0``, never a
  ``ZeroDivisionError``;
* scan failure rate == recorded ``status="error"`` snapshots /
  total recorded snapshots;
* order failure rate == recorded ``REJECTED`` orders / total
  *resolved* orders (``FILLED``/``PARTIALLY_FILLED``/``REJECTED``/
  ``CANCELLED``/``EXPIRED``) -- in-flight orders (``NEW``/
  ``VALIDATED``/``PENDING``) are excluded from both numerator and
  denominator;
* ``CANCELLED``/``EXPIRED`` orders count toward the resolved total but
  never toward failures (they are not treated as order failures);
* combined totals/failures/rate == scan + order;
* ``calculate()`` performs zero writes to any table (read-only, mirrors
  ``Business.reconciliation_engine.ReconciliationEngine``'s own
  read-only guarantee test).

Run directly with ``python Tests/test_failure_rate_engine.py`` -- no
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

from Business.failure_rate_engine import FailureRateEngine  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402

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
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "failure_rate_engine.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    order_repo = OrderRepository(manager)
    snapshot_repo = SnapshotRepository(manager)

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

    engine = FailureRateEngine(snapshot_repo, order_repo)
    return engine, snapshot_repo, order_repo


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
    print("\n[Scenario 1] No recorded outcomes -> every rate is 0.0, no ZeroDivisionError")
    with tempfile.TemporaryDirectory() as tmp:
        engine, _, _ = _build(tmp)
        result = engine.calculate()

        check(result.scan_total == 0, "empty: scan_total == 0")
        check(result.scan_failures == 0, "empty: scan_failures == 0")
        check(result.scan_failure_rate == 0.0, "empty: scan_failure_rate == 0.0")
        check(result.order_total == 0, "empty: order_total == 0")
        check(result.order_failures == 0, "empty: order_failures == 0")
        check(result.order_failure_rate == 0.0, "empty: order_failure_rate == 0.0")
        check(result.combined_total == 0, "empty: combined_total == 0")
        check(result.combined_failure_rate == 0.0, "empty: combined_failure_rate == 0.0")


def scenario_scan_failure_rate_from_recorded_snapshots():
    print("\n[Scenario 2] Scan failure rate == recorded error snapshots / total snapshots")
    with tempfile.TemporaryDirectory() as tmp:
        engine, snapshot_repo, _ = _build(tmp)

        snapshot_repo.create("2026-08-14T09:00:00+00:00", "BBCA", "BUY", "HIGH", 1, 1, status="success")
        snapshot_repo.create("2026-08-14T09:00:00+00:00", "BBRI", "HOLD", "MEDIUM", 2, 2, status="success")
        snapshot_repo.create("2026-08-14T09:00:00+00:00", "TLKM", status="error", error_message="data fetch failed")
        snapshot_repo.create("2026-08-14T09:00:00+00:00", "ASII", status="error", error_message="fundamental tool timeout")

        result = engine.calculate()

        check(result.scan_total == 4, "scan: total == 4 recorded snapshots")
        check(result.scan_failures == 2, "scan: failures == 2 error-status snapshots")
        check(result.scan_failure_rate == 0.5, "scan: failure_rate == 2/4 == 0.5")


def scenario_order_failure_rate_excludes_in_flight_and_non_rejection_lifecycle():
    print("\n[Scenario 3] Order failure rate == REJECTED / resolved orders; NEW/VALIDATED excluded; CANCELLED/EXPIRED count as resolved, not failures")
    with tempfile.TemporaryDirectory() as tmp:
        engine, _, order_repo = _build(tmp)

        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="REJECTED", reason="insufficient cash"))
        order_repo.create(**_order_kwargs(status="CANCELLED", reason="user cancelled"))
        order_repo.create(**_order_kwargs(status="EXPIRED", reason="expired"))
        # In-flight orders: not yet resolved, must be excluded entirely.
        order_repo.create(**_order_kwargs(status="NEW", reason="just created"))
        order_repo.create(**_order_kwargs(status="VALIDATED", reason="validated"))
        order_repo.create(**_order_kwargs(status="PENDING", reason="pending"))

        result = engine.calculate()

        check(result.order_total == 5, "order: total == 5 resolved orders (2 FILLED + REJECTED + CANCELLED + EXPIRED)")
        check(result.order_failures == 1, "order: failures == 1 REJECTED order")
        check(result.order_failure_rate == 0.2, "order: failure_rate == 1/5 == 0.2")


def scenario_combined_is_scan_plus_order():
    print("\n[Scenario 4] Combined totals/failures/rate == scan + order")
    with tempfile.TemporaryDirectory() as tmp:
        engine, snapshot_repo, order_repo = _build(tmp)

        snapshot_repo.create("2026-08-14T09:00:00+00:00", "BBCA", "BUY", "HIGH", 1, 1, status="success")
        snapshot_repo.create("2026-08-14T09:00:00+00:00", "TLKM", status="error", error_message="data fetch failed")

        order_repo.create(**_order_kwargs(status="FILLED", filled_price=9_500.0, filled_quantity=100.0, reason="filled"))
        order_repo.create(**_order_kwargs(status="REJECTED", reason="insufficient cash"))
        order_repo.create(**_order_kwargs(status="REJECTED", reason="kill switch engaged"))

        result = engine.calculate()

        check(result.scan_total == 2 and result.scan_failures == 1, "combined: scan side computed correctly (1/2)")
        check(result.order_total == 3 and result.order_failures == 2, "combined: order side computed correctly (2/3)")
        check(result.combined_total == 5, "combined: combined_total == 2 + 3 == 5")
        check(result.combined_failures == 3, "combined: combined_failures == 1 + 2 == 3")
        check(abs(result.combined_failure_rate - 0.6) < 1e-9, "combined: combined_failure_rate == 3/5 == 0.6")


def scenario_calculate_is_read_only():
    print("\n[Scenario 5] calculate() performs zero writes to any table")
    with tempfile.TemporaryDirectory() as tmp:
        engine, snapshot_repo, order_repo = _build(tmp)
        snapshot_repo.create("2026-08-14T09:00:00+00:00", "BBCA", "BUY", "HIGH", 1, 1, status="success")
        order_repo.create(**_order_kwargs(status="REJECTED", reason="insufficient cash"))

        def row_counts():
            return (len(snapshot_repo.list_all()), len(order_repo.list_all()))

        before = row_counts()
        engine.calculate()
        engine.calculate()
        after = row_counts()

        check(before == after, "calculate() calls produced zero writes to any table")


def main() -> int:
    scenario_empty_database_is_zero_never_divide_by_zero()
    scenario_scan_failure_rate_from_recorded_snapshots()
    scenario_order_failure_rate_excludes_in_flight_and_non_rejection_lifecycle()
    scenario_combined_is_scan_plus_order()
    scenario_calculate_is_read_only()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 FAILURE RATE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())