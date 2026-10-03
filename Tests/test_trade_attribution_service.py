"""Standalone regression checks for
``Business.trade_attribution_service.TradeAttributionService``.

Covers Activation 5.6 (Strategy Attribution) production orchestration
over REAL, temporary-SQLite-backed repositories (``AccountRepository``/
``TradeRepository``/``OrderRepository``/``SnapshotRepository``) plus
the two real Activation 5.6 engines (``TradeAttributionEngine``/
``TradeHoldingPeriodEngine``) -- no mocks of the domain objects
themselves, matching every other ``Tests/test_*_service.py`` file in
this project.

* ``get_attribution`` on an unknown account_id raises
  ``ValidationError`` -- never a fabricated empty list;
* an account with zero trades returns an empty list;
* ``market`` resolves to the real ``Account.asset_class``;
* ``strategy`` resolves per-trade from the real
  ``Order.analysis_snapshot_id`` (manual vs recommendation_following);
* ``signal_snapshot_id`` resolves through a REAL
  ``SnapshotRepository.get_by_id()`` lookup -- an
  ``analysis_snapshot_id`` pointing at a real row resolves to that id,
  one pointing at a since-deleted/never-existing row resolves to
  ``None`` (never blindly echoed);
* ``holding_period_seconds`` is computed per (account, symbol) episode
  group across the account's real trade ledger (BUY -> partial SELL
  -> full SELL -> reopen);
* ``risk_category`` matches ``DecisionPolicy.risk_level`` for the
  trade's action;
* account isolation: a second account's trades/orders/snapshots never
  leak into the first account's attribution;
* ``get_attribution`` and ``get_attribution_grouped`` are read-only --
  row counts across every touched table are unchanged after repeated
  calls;
* ``group_trade_attributions`` groups correctly by all five LOCKED
  dimension names and rejects an unknown dimension with ``ValueError``.

Run directly with ``python Tests/test_trade_attribution_service.py``
-- no external test framework required.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.trade_attribution_engine import TradeAttributionEngine  # noqa: E402
from Business.trade_attribution_service import (  # noqa: E402
    GROUPING_DIMENSIONS,
    TradeAttributionService,
    group_trade_attributions,
)
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Orchestration.decision_policy import DecisionPolicy  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402
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


def _build_service(db_path: Path):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repository = AccountRepository(manager)
    order_repository = OrderRepository(manager)
    trade_repository = TradeRepository(manager)
    snapshot_repository = SnapshotRepository(manager)
    decision_policy = DecisionPolicy()
    trade_attribution_engine = TradeAttributionEngine(decision_policy)
    trade_holding_period_engine = TradeHoldingPeriodEngine()

    service = TradeAttributionService(
        account_repository=account_repository,
        trade_repository=trade_repository,
        order_repository=order_repository,
        snapshot_repository=snapshot_repository,
        trade_attribution_engine=trade_attribution_engine,
        trade_holding_period_engine=trade_holding_period_engine,
    )
    return service, account_repository, order_repository, trade_repository, snapshot_repository, db_path


def _make_account(account_repository, account_id="paper", asset_class="stock_id"):
    return account_repository.create(
        account_id=account_id,
        account_name=account_id,
        mode="paper",
        currency="IDR",
        asset_class=asset_class,
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )


def scenario_unknown_account_raises_validation_error():
    print("\n[Scenario 1] get_attribution() on an unknown account_id raises ValidationError")
    with tempfile.TemporaryDirectory() as tmp:
        service, *_ = _build_service(Path(tmp) / "s1.db")
        raised = False
        try:
            service.get_attribution("does-not-exist")
        except ValidationError:
            raised = True
        check(raised, "ValidationError raised, never a fabricated empty list")


def scenario_zero_trades_returns_empty_list():
    print("\n[Scenario 2] an account with zero trades returns an empty list")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, *_ = _build_service(Path(tmp) / "s2.db")
        _make_account(account_repo)
        result = service.get_attribution("paper")
        check(result == [], "zero trades -> empty list, not an error")


def scenario_market_resolves_to_account_asset_class():
    print("\n[Scenario 3] market resolves to the real Account.asset_class")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(Path(tmp) / "s3.db")
        _make_account(account_repo, asset_class="crypto")
        order = order_repo.create(account_id="paper", symbol="BTC", action="BUY", quantity=1.0,
                                   requested_price=500.0, filled_price=500.0, status="FILLED", reason="")
        trade_repo.create(order_id=order.order_id, account_id="paper", symbol="BTC", action="BUY",
                           quantity=1.0, fill_price=500.0, fee=0.0, tax=0.0,
                           executed_at="2026-08-01T09:00:00+00:00")
        result = service.get_attribution("paper")
        check(len(result) == 1, "exactly one attribution for one trade")
        check(result[0].market == "crypto", "market is the real, verbatim Account.asset_class")


def scenario_strategy_manual_vs_recommendation_following():
    print("\n[Scenario 4] strategy resolves per-trade from the real Order.analysis_snapshot_id")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(Path(tmp) / "s4.db")
        _make_account(account_repo)
        snapshot = snap_repo.create(scan_time="2026-08-01T08:00:00+00:00", symbol="BBCA",
                                     recommendation="BUY", confidence="HIGH", priority=1, rank=1)

        manual_order = order_repo.create(account_id="paper", symbol="BBCA", action="BUY", quantity=100.0,
                                          requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="")
        trade_repo.create(order_id=manual_order.order_id, account_id="paper", symbol="BBCA", action="BUY",
                           quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0,
                           executed_at="2026-08-01T09:00:00+00:00")

        following_order = order_repo.create(account_id="paper", symbol="ASII", action="BUY", quantity=50.0,
                                             requested_price=6000.0, filled_price=6000.0, status="FILLED",
                                             reason="", analysis_snapshot_id=snapshot.snapshot_id)
        trade_repo.create(order_id=following_order.order_id, account_id="paper", symbol="ASII", action="BUY",
                           quantity=50.0, fill_price=6000.0, fee=0.0, tax=0.0,
                           executed_at="2026-08-01T09:05:00+00:00")

        result = service.get_attribution("paper")
        by_symbol = {a.symbol: a for a in result}
        check(by_symbol["BBCA"].strategy == "manual", "trade with no analysis_snapshot_id resolves to 'manual'")
        check(by_symbol["ASII"].strategy == "recommendation_following", "trade with a real analysis_snapshot_id resolves to 'recommendation_following'")


def scenario_signal_resolves_real_snapshot_and_dangling_id_resolves_none():
    print("\n[Scenario 5] signal_snapshot_id: real snapshot resolves, dangling/never-existing id resolves to None")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(Path(tmp) / "s5.db")
        _make_account(account_repo)
        snapshot = snap_repo.create(scan_time="2026-08-01T08:00:00+00:00", symbol="BBCA",
                                     recommendation="BUY", confidence="HIGH", priority=1, rank=1)

        real_order = order_repo.create(account_id="paper", symbol="BBCA", action="BUY", quantity=100.0,
                                        requested_price=9000.0, filled_price=9000.0, status="FILLED",
                                        reason="", analysis_snapshot_id=snapshot.snapshot_id)
        trade_repo.create(order_id=real_order.order_id, account_id="paper", symbol="BBCA", action="BUY",
                           quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0,
                           executed_at="2026-08-01T09:00:00+00:00")

        dangling_order = order_repo.create(account_id="paper", symbol="ASII", action="BUY", quantity=50.0,
                                            requested_price=6000.0, filled_price=6000.0, status="FILLED",
                                            reason="", analysis_snapshot_id=99999)
        trade_repo.create(order_id=dangling_order.order_id, account_id="paper", symbol="ASII", action="BUY",
                           quantity=50.0, fill_price=6000.0, fee=0.0, tax=0.0,
                           executed_at="2026-08-01T09:05:00+00:00")

        result = service.get_attribution("paper")
        by_symbol = {a.symbol: a for a in result}
        check(by_symbol["BBCA"].signal_snapshot_id == snapshot.snapshot_id, "a real, still-existing snapshot resolves via a real SnapshotRepository.get_by_id() lookup")
        check(by_symbol["ASII"].signal_snapshot_id is None, "a dangling analysis_snapshot_id (no matching row) resolves to None -- never blindly echoed")


def scenario_holding_period_episode_across_full_lifecycle():
    print("\n[Scenario 6] holding_period_seconds: BUY -> partial SELL -> full SELL -> reopen")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(Path(tmp) / "s6.db")
        _make_account(account_repo)

        def _fill(action, quantity, executed_at):
            order = order_repo.create(account_id="paper", symbol="BBCA", action=action, quantity=quantity,
                                       requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="")
            return trade_repo.create(order_id=order.order_id, account_id="paper", symbol="BBCA", action=action,
                                      quantity=quantity, fill_price=9000.0, fee=0.0, tax=0.0, executed_at=executed_at)

        t_open_buy = _fill("BUY", 100.0, "2026-08-01T09:00:00+00:00")
        t_partial_sell = _fill("SELL", 40.0, "2026-08-01T10:00:00+00:00")
        t_close_sell = _fill("SELL", 60.0, "2026-08-01T13:00:00+00:00")
        t_reopen_buy = _fill("BUY", 30.0, "2026-08-01T15:00:00+00:00")

        result = service.get_attribution("paper")
        by_id = {a.trade_id: a for a in result}
        expected_first_episode = 4.0 * 3600
        check(by_id[t_open_buy.trade_id].holding_period_seconds == expected_first_episode, "opening BUY gets the closing-SELL-anchored holding period")
        check(by_id[t_partial_sell.trade_id].holding_period_seconds == expected_first_episode, "partial SELL shares the same closed-episode holding period")
        check(by_id[t_close_sell.trade_id].holding_period_seconds == expected_first_episode, "closing SELL gets the same holding period")
        check(by_id[t_reopen_buy.trade_id].holding_period_seconds is None, "reopened episode's still-open BUY is None -- never fabricated")


def scenario_risk_category_matches_decision_policy():
    print("\n[Scenario 7] risk_category matches DecisionPolicy.risk_level for the trade's action")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(Path(tmp) / "s7.db")
        _make_account(account_repo)
        buy_order = order_repo.create(account_id="paper", symbol="BBCA", action="BUY", quantity=100.0,
                                       requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="")
        trade_repo.create(order_id=buy_order.order_id, account_id="paper", symbol="BBCA", action="BUY",
                           quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0, executed_at="2026-08-01T09:00:00+00:00")
        sell_order = order_repo.create(account_id="paper", symbol="BBCA", action="SELL", quantity=100.0,
                                        requested_price=9500.0, filled_price=9500.0, status="FILLED", reason="")
        trade_repo.create(order_id=sell_order.order_id, account_id="paper", symbol="BBCA", action="SELL",
                           quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0, executed_at="2026-08-01T10:00:00+00:00")

        result = service.get_attribution("paper")
        by_action = {a.action: a for a in result}
        check(by_action["BUY"].risk_category == "NORMAL", "BUY trade risk_category is 'NORMAL'")
        check(by_action["SELL"].risk_category == "HIGH", "SELL trade risk_category is 'HIGH'")


def scenario_account_isolation():
    print("\n[Scenario 8] account isolation -- a second account's data never leaks in")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(Path(tmp) / "s8.db")
        _make_account(account_repo, account_id="paper-1")
        _make_account(account_repo, account_id="paper-2")

        order1 = order_repo.create(account_id="paper-1", symbol="BBCA", action="BUY", quantity=100.0,
                                    requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="")
        trade_repo.create(order_id=order1.order_id, account_id="paper-1", symbol="BBCA", action="BUY",
                           quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0, executed_at="2026-08-01T09:00:00+00:00")

        result_1 = service.get_attribution("paper-1")
        result_2 = service.get_attribution("paper-2")
        check(len(result_1) == 1, "account paper-1 sees its own real trade")
        check(len(result_2) == 0, "account paper-2 sees ZERO trades -- paper-1's trade never leaks across account_id")


def scenario_read_only_row_counts_unchanged():
    print("\n[Scenario 9] read-only proof -- row counts unchanged across every touched table")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "s9.db"
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(db_path)
        _make_account(account_repo)
        snapshot = snap_repo.create(scan_time="2026-08-01T08:00:00+00:00", symbol="BBCA",
                                     recommendation="BUY", confidence="HIGH", priority=1, rank=1)
        order = order_repo.create(account_id="paper", symbol="BBCA", action="BUY", quantity=100.0,
                                   requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="",
                                   analysis_snapshot_id=snapshot.snapshot_id)
        trade_repo.create(order_id=order.order_id, account_id="paper", symbol="BBCA", action="BUY",
                           quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0, executed_at="2026-08-01T09:00:00+00:00")

        con = sqlite3.connect(db_path)
        tables = ("accounts", "orders", "trades", "ranking_snapshots")
        counts_before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        con.close()

        for _ in range(3):
            service.get_attribution("paper")
            service.get_attribution_grouped("paper", "strategy")

        con = sqlite3.connect(db_path)
        counts_after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        con.close()
        check(counts_before == counts_after, f"row counts unchanged after repeated read calls: {counts_before} == {counts_after}")


def scenario_grouping_by_all_five_dimensions():
    print("\n[Scenario 10] group_trade_attributions groups correctly by all five LOCKED dimensions")
    with tempfile.TemporaryDirectory() as tmp:
        service, account_repo, order_repo, trade_repo, snap_repo, _ = _build_service(Path(tmp) / "s10.db")
        _make_account(account_repo)
        buy_order = order_repo.create(account_id="paper", symbol="BBCA", action="BUY", quantity=100.0,
                                       requested_price=9000.0, filled_price=9000.0, status="FILLED", reason="")
        trade_repo.create(order_id=buy_order.order_id, account_id="paper", symbol="BBCA", action="BUY",
                           quantity=100.0, fill_price=9000.0, fee=0.0, tax=0.0, executed_at="2026-08-01T09:00:00+00:00")
        sell_order = order_repo.create(account_id="paper", symbol="BBCA", action="SELL", quantity=100.0,
                                        requested_price=9500.0, filled_price=9500.0, status="FILLED", reason="")
        trade_repo.create(order_id=sell_order.order_id, account_id="paper", symbol="BBCA", action="SELL",
                           quantity=100.0, fill_price=9500.0, fee=0.0, tax=0.0, executed_at="2026-08-01T10:00:00+00:00")

        check(set(GROUPING_DIMENSIONS) == {"strategy", "market", "signal", "holding_period", "risk_category"}, "GROUPING_DIMENSIONS covers exactly the five LOCKED roadmap dimension names")

        for dimension in GROUPING_DIMENSIONS:
            grouped = service.get_attribution_grouped("paper", dimension)
            total = sum(len(v) for v in grouped.values())
            check(total == 2, f"grouping by '{dimension}' preserves every attribution row (2 trades)")

        risk_grouped = service.get_attribution_grouped("paper", "risk_category")
        check(set(risk_grouped.keys()) == {"NORMAL", "HIGH"}, "grouping by risk_category produces the real NORMAL/HIGH keys")

        raised = False
        try:
            group_trade_attributions([], "not_a_real_dimension")
        except ValueError:
            raised = True
        check(raised, "an unknown dimension name raises ValueError")


def main() -> int:
    scenario_unknown_account_raises_validation_error()
    scenario_zero_trades_returns_empty_list()
    scenario_market_resolves_to_account_asset_class()
    scenario_strategy_manual_vs_recommendation_following()
    scenario_signal_resolves_real_snapshot_and_dangling_id_resolves_none()
    scenario_holding_period_episode_across_full_lifecycle()
    scenario_risk_category_matches_decision_policy()
    scenario_account_isolation()
    scenario_read_only_row_counts_unchanged()
    scenario_grouping_by_all_five_dimensions()

    print("\n" + "=" * 60)
    print(f"TRADE ATTRIBUTION SERVICE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())