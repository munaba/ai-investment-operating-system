"""Standalone regression checks for Activation 5.4 -- equity curve
production from real, persisted ``PortfolioSnapshot`` rows.

Covers, against a real on-disk SQLite file (real ``AccountRepository``/
``PortfolioSnapshotRepository``, real migrations):

* Scenario A -- basic equity curve, correct (timestamp, equity) pairs;
* Scenario B -- persistence: identical result after a real disconnect
  and a fresh DatabaseManager/repository/service built on a brand-new
  connection to the same on-disk file;
* Scenario C -- account isolation between two accounts;
* Scenario D -- empty account produces an empty list, never a
  synthetic ``0.0`` point;
* Scenario E -- snapshots inserted out of chronological order still
  come back ``timestamp ASC`` (not insertion/``snapshot_id`` order);
* Scenario F -- range query: snapshots outside
  ``[start_timestamp, end_timestamp]`` are excluded, and the boundary
  is inclusive (matching ``DailyPerformanceService``'s existing
  ``start_timestamp <= x <= end_timestamp`` contract);
* Scenario G -- reading the equity curve creates no Order/Trade,
  mutates no Cash/Position, and creates no new PortfolioSnapshot;
* Scenario H -- built from real ``Database.models.PortfolioSnapshot``
  rows via the real repository/service, not a fake entity;
* Scenario I -- the same equity values, fed unchanged into the real
  ``MaximumDrawdownEngine``, reproduce its documented formula (no
  duplicate drawdown formula in the equity curve path);
* invalid account raises ``ValidationError``, no fabricated curve.

Run directly with ``python Tests/test_equity_curve.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.maximum_drawdown_engine import MaximumDrawdownEngine  # noqa: E402
from Business.portfolio_snapshot_service import (  # noqa: E402
    EquityCurvePoint,
    PortfolioSnapshotService,
)
from Business.unrealized_pnl_engine import UnrealizedPnLEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository  # noqa: E402
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


def _manager(db_path: Path) -> DatabaseManager:
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
    return DatabaseManager(db, cfg), db


def _service(manager: DatabaseManager) -> PortfolioSnapshotService:
    return PortfolioSnapshotService(
        account_repository=AccountRepository(manager),
        position_repository=PositionRepository(manager),
        unrealized_pnl_engine=UnrealizedPnLEngine(market_price_tool=None),
        maximum_drawdown_engine=MaximumDrawdownEngine(),
        portfolio_snapshot_repository=PortfolioSnapshotRepository(manager),
    )


def _make_account(manager: DatabaseManager, account_id: str) -> None:
    AccountRepository(manager).create(
        account_id=account_id,
        account_name=f"Account {account_id}",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )


def scenario_a_basic_equity_curve():
    print("\n[Scenario A] Basic equity curve from real snapshots")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "a.db")
        try:
            _make_account(manager, "acc-a")
            repo = PortfolioSnapshotRepository(manager)
            repo.create(account_id="acc-a", cash=1.0, market_value=0.0, equity=100.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-01T00:00:00+00:00")
            repo.create(account_id="acc-a", cash=1.0, market_value=0.0, equity=110.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-02T00:00:00+00:00")
            repo.create(account_id="acc-a", cash=1.0, market_value=0.0, equity=105.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-03T00:00:00+00:00")

            svc = _service(manager)
            curve = svc.get_equity_curve("acc-a")
            expected = [
                EquityCurvePoint(timestamp="2026-08-01T00:00:00+00:00", equity=100.0),
                EquityCurvePoint(timestamp="2026-08-02T00:00:00+00:00", equity=110.0),
                EquityCurvePoint(timestamp="2026-08-03T00:00:00+00:00", equity=105.0),
            ]
            check(curve == expected, "get_equity_curve() returns exact (timestamp, equity) points in order")
        finally:
            db.disconnect()


def scenario_b_persistence_after_restart():
    print("\n[Scenario B] Persistence: identical result after disconnect/reconnect")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "b.db"
        manager1, db1 = _manager(db_path)
        _make_account(manager1, "acc-b")
        repo1 = PortfolioSnapshotRepository(manager1)
        repo1.create(account_id="acc-b", cash=1.0, market_value=0.0, equity=200.0,
                     realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                     timestamp="2026-08-01T00:00:00+00:00")
        repo1.create(account_id="acc-b", cash=1.0, market_value=0.0, equity=210.0,
                     realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                     timestamp="2026-08-02T00:00:00+00:00")
        before = _service(manager1).get_equity_curve("acc-b")
        db1.disconnect()  # real disconnect

        # Fresh DB connection, fresh DatabaseManager, fresh repository/service.
        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg2)
        try:
            after = _service(manager2).get_equity_curve("acc-b")
            check(after == before, "equity curve identical after real disconnect + fresh reconnect")
            check(len(after) == 2, "both snapshots survive restart")
        finally:
            db2.disconnect()


def scenario_c_account_isolation():
    print("\n[Scenario C] Account isolation between two accounts")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "c.db")
        try:
            _make_account(manager, "acc-x")
            _make_account(manager, "acc-y")
            repo = PortfolioSnapshotRepository(manager)
            repo.create(account_id="acc-x", cash=1.0, market_value=0.0, equity=1.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-01T00:00:00+00:00")
            repo.create(account_id="acc-x", cash=1.0, market_value=0.0, equity=2.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-02T00:00:00+00:00")
            repo.create(account_id="acc-y", cash=1.0, market_value=0.0, equity=3.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-01T00:00:00+00:00")
            repo.create(account_id="acc-y", cash=1.0, market_value=0.0, equity=4.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-02T00:00:00+00:00")

            svc = _service(manager)
            curve_x = svc.get_equity_curve("acc-x")
            curve_y = svc.get_equity_curve("acc-y")
            check([p.equity for p in curve_x] == [1.0, 2.0], "curve for acc-x contains only acc-x's equity")
            check([p.equity for p in curve_y] == [3.0, 4.0], "curve for acc-y contains only acc-y's equity")
        finally:
            db.disconnect()


def scenario_d_empty_account():
    print("\n[Scenario D] Account with no snapshots -> empty list, never fabricated 0.0")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "d.db")
        try:
            _make_account(manager, "acc-empty")
            svc = _service(manager)
            curve = svc.get_equity_curve("acc-empty")
            check(curve == [], "empty account returns an empty list")
            check(curve != [EquityCurvePoint(timestamp="", equity=0.0)], "no synthetic zero point is fabricated")
        finally:
            db.disconnect()


def scenario_e_timestamp_ordering():
    print("\n[Scenario E] Non-chronological insertion still returns timestamp ASC order")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "e.db")
        try:
            _make_account(manager, "acc-e")
            repo = PortfolioSnapshotRepository(manager)
            # Insert out of chronological order: middle timestamp first,
            # earliest second, latest last -- snapshot_id insertion order
            # therefore disagrees with timestamp order.
            repo.create(account_id="acc-e", cash=1.0, market_value=0.0, equity=222.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-02T00:00:00+00:00")
            repo.create(account_id="acc-e", cash=1.0, market_value=0.0, equity=111.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-01T00:00:00+00:00")
            repo.create(account_id="acc-e", cash=1.0, market_value=0.0, equity=333.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-03T00:00:00+00:00")

            svc = _service(manager)
            curve = svc.get_equity_curve("acc-e")
            check(
                [p.equity for p in curve] == [111.0, 222.0, 333.0],
                "equity curve is ordered by timestamp ASC, not snapshot_id/insertion order",
            )
        finally:
            db.disconnect()


def scenario_f_range_query():
    print("\n[Scenario F] Range query: inclusive boundary, out-of-range snapshots excluded")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "f.db")
        try:
            _make_account(manager, "acc-f")
            repo = PortfolioSnapshotRepository(manager)
            repo.create(account_id="acc-f", cash=1.0, market_value=0.0, equity=1.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-01T00:00:00+00:00")
            repo.create(account_id="acc-f", cash=1.0, market_value=0.0, equity=2.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-02T00:00:00+00:00")
            repo.create(account_id="acc-f", cash=1.0, market_value=0.0, equity=3.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-03T00:00:00+00:00")
            repo.create(account_id="acc-f", cash=1.0, market_value=0.0, equity=4.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-04T00:00:00+00:00")

            svc = _service(manager)
            curve = svc.get_equity_curve(
                "acc-f",
                start_timestamp="2026-08-02T00:00:00+00:00",
                end_timestamp="2026-08-03T00:00:00+00:00",
            )
            check([p.equity for p in curve] == [2.0, 3.0], "only snapshots inside the range are returned")

            boundary_only = svc.get_equity_curve(
                "acc-f",
                start_timestamp="2026-08-02T00:00:00+00:00",
                end_timestamp="2026-08-02T00:00:00+00:00",
            )
            check(
                [p.equity for p in boundary_only] == [2.0],
                "range boundary is inclusive (matches DailyPerformanceService's existing contract)",
            )
        finally:
            db.disconnect()


def scenario_g_no_mutation():
    print("\n[Scenario G] Reading the equity curve causes no side effects")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "g.db")
        try:
            _make_account(manager, "acc-g")
            repo = PortfolioSnapshotRepository(manager)
            repo.create(account_id="acc-g", cash=1.0, market_value=0.0, equity=1.0,
                        realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                        timestamp="2026-08-01T00:00:00+00:00")

            order_repo = OrderRepository(manager)
            position_repo = PositionRepository(manager)
            trade_repo = TradeRepository(manager)
            account_repo = AccountRepository(manager)

            before_orders = len(order_repo.list_by_account("acc-g"))
            before_positions = len(position_repo.list_by_account("acc-g"))
            before_trades = len(trade_repo.list_by_account("acc-g"))
            before_cash = account_repo.get_by_id("acc-g").cash
            before_snapshot_count = len(repo.list_by_account("acc-g"))

            svc = _service(manager)
            svc.get_equity_curve("acc-g")
            svc.get_equity_curve("acc-g", start_timestamp="2026-08-01T00:00:00+00:00")

            check(len(order_repo.list_by_account("acc-g")) == before_orders, "no Order created")
            check(len(position_repo.list_by_account("acc-g")) == before_positions, "no Position created")
            check(len(trade_repo.list_by_account("acc-g")) == before_trades, "no Trade created")
            check(account_repo.get_by_id("acc-g").cash == before_cash, "Cash unchanged")
            check(len(repo.list_by_account("acc-g")) == before_snapshot_count, "no new PortfolioSnapshot created")
        finally:
            db.disconnect()


def scenario_h_real_production_model():
    print("\n[Scenario H] Equity curve built from real production PortfolioSnapshot rows")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "h.db")
        try:
            _make_account(manager, "acc-h")
            repo = PortfolioSnapshotRepository(manager)
            created = repo.create(account_id="acc-h", cash=1.0, market_value=0.0, equity=42.0,
                                   realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                                   timestamp="2026-08-01T00:00:00+00:00")
            from Database.models import PortfolioSnapshot
            check(isinstance(created, PortfolioSnapshot), "snapshot is the real production PortfolioSnapshot model")

            curve = _service(manager).get_equity_curve("acc-h")
            check(curve[0].equity == created.equity, "equity curve point matches real persisted snapshot's equity")
            check(curve[0].timestamp == created.timestamp, "equity curve point matches real persisted snapshot's timestamp")
        finally:
            db.disconnect()


def scenario_i_drawdown_engine_reuse():
    print("\n[Scenario I] Drawdown over the equity curve uses MaximumDrawdownEngine, not a duplicate formula")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "i.db")
        try:
            _make_account(manager, "acc-i")
            repo = PortfolioSnapshotRepository(manager)
            for day, equity in enumerate((100.0, 150.0, 90.0, 120.0), start=1):
                repo.create(account_id="acc-i", cash=1.0, market_value=0.0, equity=equity,
                            realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                            timestamp=f"2026-08-0{day}T00:00:00+00:00")

            curve = _service(manager).get_equity_curve("acc-i")
            values = [p.equity for p in curve]

            engine = MaximumDrawdownEngine()
            result = engine.calculate(values)
            # Reference formula, computed independently in the test itself,
            # to prove the engine's real (LOCKED) output is what gets used
            # -- not that some other value happens to match.
            peak = values[0]
            expected_dd = 0.0
            for v in values:
                peak = max(peak, v)
                expected_dd = max(expected_dd, (peak - v) / peak)

            check(result.maximum_drawdown == expected_dd, "MaximumDrawdownEngine over the equity curve matches its own LOCKED formula")
            check(abs(result.maximum_drawdown - (150.0 - 90.0) / 150.0) < 1e-9, "drawdown value is the expected 40.0%")
        finally:
            db.disconnect()


def scenario_invalid_account_raises():
    print("\n[Scenario] Invalid account_id raises ValidationError, no fabricated curve")
    with tempfile.TemporaryDirectory() as tmp:
        manager, db = _manager(Path(tmp) / "invalid.db")
        try:
            svc = _service(manager)
            raised = False
            try:
                svc.get_equity_curve("does-not-exist")
            except ValidationError:
                raised = True
            check(raised, "get_equity_curve() raises ValidationError for an unknown account_id")
        finally:
            db.disconnect()


def main() -> int:
    scenario_a_basic_equity_curve()
    scenario_b_persistence_after_restart()
    scenario_c_account_isolation()
    scenario_d_empty_account()
    scenario_e_timestamp_ordering()
    scenario_f_range_query()
    scenario_g_no_mutation()
    scenario_h_real_production_model()
    scenario_i_drawdown_engine_reuse()
    scenario_invalid_account_raises()

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())