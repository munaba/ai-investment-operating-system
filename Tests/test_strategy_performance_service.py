"""Standalone regression checks for
``Business.strategy_performance_service.StrategyPerformanceService``.

Covers ACTIVATION 7 (performance per strategy) production
orchestration over REAL, temporary-SQLite-backed repositories
(``AccountRepository``/``TradeRepository``/``OrderRepository``/
``PositionRepository``) plus the real ``PositionManager`` (so every
``Trade``/``Position`` pair in these tests is produced exactly the
way the real trading flow produces it -- never hand-faked) and the
real Activation 7 engines (``PositionEpisodeReplayEngine``/
``StrategyPerformanceEngine``) -- no mocks of the domain objects
themselves, matching every other ``Tests/test_*_service.py`` file in
this project.

* ``get_performance_by_strategy`` on an unknown account_id raises
  ``ValidationError`` -- never a fabricated empty dict;
* an account with zero closed episodes returns an empty dict;
* a single-strategy episode (every trade in the episode shares the
  same ``Order.analysis_snapshot_id`` presence/absence) aggregates
  under that one strategy label;
* a mixed-strategy episode (opening BUY manual, a later BUY
  recommendation_following, before the closing SELL) aggregates under
  ``"mixed"``;
* multiple episodes across multiple symbols/strategies each land in
  the correct strategy group, with correct win/loss/net figures;
* an account with trades but zero CLOSED episodes (still-open
  position) returns an empty dict -- an open position is never
  reported as if it were a closed episode;
* ``Position.realized_pnl`` is used verbatim as the episode P/L --
  never recomputed by this service;
* deterministic: calling twice on the same data yields equal results;
* read-only: row counts across every touched table are unchanged
  after repeated calls (no DB writes).

Run directly with ``python Tests/test_strategy_performance_service.py``
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

from Business.position_episode_replay_engine import PositionEpisodeReplayEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.strategy_performance_engine import StrategyPerformanceEngine  # noqa: E402
from Business.strategy_performance_service import StrategyPerformanceService  # noqa: E402
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
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


def _build(db_path: Path):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repository = AccountRepository(manager)
    order_repository = OrderRepository(manager)
    trade_repository = TradeRepository(manager)
    position_repository = PositionRepository(manager)
    position_manager = PositionManager(position_repository)

    position_episode_replay_engine = PositionEpisodeReplayEngine(TradeHoldingPeriodEngine())
    strategy_performance_engine = StrategyPerformanceEngine()

    service = StrategyPerformanceService(
        account_repository=account_repository,
        trade_repository=trade_repository,
        order_repository=order_repository,
        position_repository=position_repository,
        position_episode_replay_engine=position_episode_replay_engine,
        strategy_performance_engine=strategy_performance_engine,
    )
    return {
        "service": service,
        "account_repository": account_repository,
        "order_repository": order_repository,
        "trade_repository": trade_repository,
        "position_repository": position_repository,
        "position_manager": position_manager,
        "db": db,
        "db_path": db_path,
    }


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


def _fill(ctx, account_id, symbol, action, quantity, fill_price, executed_at,
          analysis_snapshot_id=None, fee=0.0, tax=0.0):
    """Create a real Order + Trade, then apply it through the real
    PositionManager -- exactly the real trading flow, so ``Position.
    realized_pnl``/``status`` are always genuinely computed, never
    hand-faked by the test.
    """
    order = ctx["order_repository"].create(
        account_id=account_id, symbol=symbol, action=action, quantity=quantity,
        requested_price=fill_price, filled_price=fill_price, status="FILLED",
        reason="", analysis_snapshot_id=analysis_snapshot_id,
    )
    trade = ctx["trade_repository"].create(
        order_id=order.order_id, account_id=account_id, symbol=symbol, action=action,
        quantity=quantity, fill_price=fill_price, fee=fee, tax=tax, executed_at=executed_at,
    )
    ctx["position_manager"].apply_trade(trade)
    return order, trade


def _row_counts(db_path):
    con = sqlite3.connect(db_path)
    counts = {}
    for table in ("accounts", "orders", "trades", "positions"):
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    con.close()
    return counts


def scenario_unknown_account_raises_validation_error():
    print("\n[Scenario 1] get_performance_by_strategy() on an unknown account_id raises ValidationError")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s1.db")
        raised = False
        try:
            ctx["service"].get_performance_by_strategy("does-not-exist")
        except ValidationError:
            raised = True
        check(raised, "ValidationError raised, never a fabricated empty dict")


def scenario_zero_data_returns_empty_dict():
    print("\n[Scenario 2] zero/empty data: an account with no trades at all returns an empty dict")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s2.db")
        _make_account(ctx["account_repository"])
        result = ctx["service"].get_performance_by_strategy("paper")
        check(result == {}, "zero trades -> empty dict, not an error")


def scenario_single_strategy_episode():
    print("\n[Scenario 3] single-strategy episode: manual BUY -> manual SELL aggregates under 'manual'")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s3.db")
        _make_account(ctx["account_repository"])
        _fill(ctx, "paper", "BBCA", "BUY", 100.0, 9000.0, "2026-08-01T09:00:00+00:00")
        _fill(ctx, "paper", "BBCA", "SELL", 100.0, 9500.0, "2026-08-01T13:00:00+00:00")

        result = ctx["service"].get_performance_by_strategy("paper")
        check(list(result.keys()) == ["manual"], "only the 'manual' strategy group is present")
        stats = result["manual"]
        check(stats.closed_episodes == 1, "exactly one closed episode")
        check(stats.winning_episodes == 1, "the episode is a winner")
        expected_pnl = (9500.0 - 9000.0) * 100.0
        check(stats.gross_profit == expected_pnl, "gross_profit matches Position.realized_pnl verbatim")
        check(stats.net_profit == expected_pnl, "net_profit matches the same real realized_pnl")


def scenario_single_strategy_episode_recommendation_following():
    print("\n[Scenario 4] single-strategy episode: every trade carries analysis_snapshot_id -> 'recommendation_following'")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s4.db")
        _make_account(ctx["account_repository"])
        _fill(ctx, "paper", "ASII", "BUY", 50.0, 6000.0, "2026-08-01T09:00:00+00:00", analysis_snapshot_id=7)
        _fill(ctx, "paper", "ASII", "SELL", 50.0, 5800.0, "2026-08-01T11:00:00+00:00", analysis_snapshot_id=7)

        result = ctx["service"].get_performance_by_strategy("paper")
        check(
            list(result.keys()) == ["recommendation_following"],
            "only the 'recommendation_following' strategy group is present",
        )
        check(result["recommendation_following"].losing_episodes == 1, "the episode is a loser (sold below entry)")


def scenario_mixed_strategy_episode():
    print("\n[Scenario 5] mixed-strategy episode: manual opening BUY + recommendation_following add-on BUY -> 'mixed'")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s5.db")
        _make_account(ctx["account_repository"])
        _fill(ctx, "paper", "TLKM", "BUY", 60.0, 3000.0, "2026-08-01T09:00:00+00:00")  # manual (no snapshot)
        _fill(ctx, "paper", "TLKM", "BUY", 40.0, 3100.0, "2026-08-01T09:30:00+00:00", analysis_snapshot_id=11)  # recommendation_following
        _fill(ctx, "paper", "TLKM", "SELL", 100.0, 3200.0, "2026-08-01T13:00:00+00:00")  # manual close

        result = ctx["service"].get_performance_by_strategy("paper")
        check(list(result.keys()) == ["mixed"], "episode with more than one strategy among its trades -> 'mixed'")
        check(result["mixed"].closed_episodes == 1, "exactly one closed episode, correctly classified as mixed")


def scenario_multiple_episodes_multiple_symbols():
    print("\n[Scenario 6] multiple episodes across multiple symbols land in the correct strategy groups")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s6.db")
        _make_account(ctx["account_repository"])

        # BBCA: two manual episodes (one win, one loss).
        _fill(ctx, "paper", "BBCA", "BUY", 100.0, 9000.0, "2026-08-01T09:00:00+00:00")
        _fill(ctx, "paper", "BBCA", "SELL", 100.0, 9500.0, "2026-08-01T10:00:00+00:00")
        _fill(ctx, "paper", "BBCA", "BUY", 100.0, 9500.0, "2026-08-01T11:00:00+00:00")
        _fill(ctx, "paper", "BBCA", "SELL", 100.0, 9000.0, "2026-08-01T12:00:00+00:00")

        # ASII: one recommendation_following episode (win), still-open second episode.
        _fill(ctx, "paper", "ASII", "BUY", 50.0, 6000.0, "2026-08-01T09:00:00+00:00", analysis_snapshot_id=3)
        _fill(ctx, "paper", "ASII", "SELL", 50.0, 6200.0, "2026-08-01T10:00:00+00:00", analysis_snapshot_id=3)
        _fill(ctx, "paper", "ASII", "BUY", 20.0, 6100.0, "2026-08-01T11:00:00+00:00", analysis_snapshot_id=3)

        result = ctx["service"].get_performance_by_strategy("paper")
        check(set(result.keys()) == {"manual", "recommendation_following"}, "both strategy groups present, still-open episode excluded")
        check(result["manual"].closed_episodes == 2, "both BBCA episodes counted under manual")
        check(result["manual"].winning_episodes == 1, "one BBCA episode won")
        check(result["manual"].losing_episodes == 1, "one BBCA episode lost")
        check(
            result["recommendation_following"].closed_episodes == 1,
            "only the closed ASII episode counted -- the still-open one is excluded entirely",
        )
        check(result["recommendation_following"].winning_episodes == 1, "the closed ASII episode won")


def scenario_open_position_excluded():
    print("\n[Scenario 7] an account with trades but zero CLOSED episodes returns an empty dict")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s7.db")
        _make_account(ctx["account_repository"])
        _fill(ctx, "paper", "BBRI", "BUY", 100.0, 4000.0, "2026-08-01T09:00:00+00:00")

        result = ctx["service"].get_performance_by_strategy("paper")
        check(result == {}, "a still-open position is never reported as a closed episode")


def scenario_deterministic_and_read_only():
    print("\n[Scenario 8] deterministic replay + no DB writes across repeated calls")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s8.db")
        _make_account(ctx["account_repository"])
        _fill(ctx, "paper", "BBCA", "BUY", 100.0, 9000.0, "2026-08-01T09:00:00+00:00")
        _fill(ctx, "paper", "BBCA", "SELL", 100.0, 9500.0, "2026-08-01T13:00:00+00:00")

        before = _row_counts(ctx["db_path"])
        first = ctx["service"].get_performance_by_strategy("paper")
        second = ctx["service"].get_performance_by_strategy("paper")
        after = _row_counts(ctx["db_path"])

        check(first == second, "calling the service twice on the same data yields equal results")
        check(before == after, "row counts across every touched table are unchanged -- no DB writes")


def main() -> int:
    scenario_unknown_account_raises_validation_error()
    scenario_zero_data_returns_empty_dict()
    scenario_single_strategy_episode()
    scenario_single_strategy_episode_recommendation_following()
    scenario_mixed_strategy_episode()
    scenario_multiple_episodes_multiple_symbols()
    scenario_open_position_excluded()
    scenario_deterministic_and_read_only()

    print(f"\n{'=' * 70}\nRESULTS: {_PASS} passed, {_FAIL} failed\n{'=' * 70}")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())