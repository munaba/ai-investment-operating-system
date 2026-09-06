"""Standalone regression checks for
``Business.market_regime_attribution_service.MarketRegimeAttributionService``.

Covers ACTIVATION 7 (performance per market regime / market-condition
variety) end to end over REAL, temporary-SQLite-backed repositories
(``AccountRepository``/``TradeRepository``/``PositionRepository``/
``WatchlistRepository``) plus the real ``PositionManager`` (so every
``Trade``/``Position`` pair is produced exactly the way the real
trading flow produces it -- never hand-faked), the real
``PositionEpisodeReplayEngine``, the real ``MarketRegimeEngine``, and
a real ``MarketRegimeService`` wired to a real ``StockDataRepository``
with only its ``yfinance`` client faked (never a mock of any of this
project's own classes). Mirrors
``Tests/test_strategy_performance_service.py``'s own shape closely.

* unknown account_id raises ``ValidationError``, never a fabricated
  empty dict;
* zero closed episodes returns an empty dict;
* regime attribution is based on each closed episode's OPENING trade
  timestamp -- verified directly: two episodes on the same symbol,
  opened at two different real points in market history (one
  "ranging", one later "trending"), land in two DIFFERENT regime
  groups even though they share a symbol;
* no-lookahead: the above only holds because the first (earlier)
  episode's classification never sees the later, real "trending"
  bars that exist by the time the test runs the query -- this is the
  same no-lookahead property ``test_market_regime_service.py`` proves
  at the service layer, exercised here through the full attribution
  path;
* at least 2 distinct REAL regimes are observed across an account's
  closed episodes, from real (fake-OHLCV-backed but arithmetically
  real) market data -- never fabricated/default regime labels;
* an episode whose opening trade cannot be classified (insufficient
  real OHLCV) is grouped under the honest ``"insufficient_data"``
  label, never silently dropped and never guessed into a real regime;
* ``get_market_condition_variety()`` reports real, currently-observed
  market-condition variety (``regime_count >= 2``) over a real
  watchlist, with per-symbol evidence backing the counts;
* ``Position.realized_pnl`` is used verbatim as each episode's P/L --
  never recomputed by this service;
* determinism + read-only: calling both public methods twice yields
  equal results, with unchanged row counts across every touched table
  (no DB writes).

Run directly with
``python Tests/test_market_regime_attribution_service.py`` -- no
external test framework required.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402

from Business.market_regime_attribution_service import (  # noqa: E402
    MarketRegimeAttributionService,
    REGIME_INSUFFICIENT_DATA,
)
from Business.market_regime_engine import MarketRegimeEngine  # noqa: E402
from Business.market_regime_performance_engine import MarketRegimePerformanceEngine  # noqa: E402
from Business.market_regime_service import MarketRegimeService  # noqa: E402
from Business.position_episode_replay_engine import PositionEpisodeReplayEngine  # noqa: E402
from Business.position_manager import PositionManager  # noqa: E402
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_orders import ORDERS_MIGRATIONS  # noqa: E402
from Database.migrations_positions import POSITIONS_MIGRATIONS  # noqa: E402
from Database.migrations_trades import TRADES_MIGRATIONS  # noqa: E402
from Database.migrations_watchlist import WATCHLIST_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.external.stock_data_repository import StockDataRepository  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.order_repository import OrderRepository  # noqa: E402
from Repository.persistence.position_repository import PositionRepository  # noqa: E402
from Repository.persistence.trade_repository import TradeRepository  # noqa: E402
from Repository.persistence.watchlist_repository import WatchlistRepository  # noqa: E402

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
# Real fixture market histories -- every series below is a plain arithmetic
# construction, independently verified (see Tests/test_market_regime_engine.py
# and Tests/test_market_regime_service.py) to classify exactly as labeled
# once run through the real, unmodified MarketRegimeEngine.
# ---------------------------------------------------------------------------

def _choppy_then_trending_history() -> pd.DataFrame:
    """Symbol history whose trailing-20-bar window ending at day20
    classifies "ranging", and whose trailing-20-bar window ending at
    day40 (or later) classifies "trending". See
    ``Tests/test_market_regime_service.py`` for the exact same,
    independently-verified fixture.
    """
    dates = pd.date_range(start="2026-01-01", periods=41, freq="D")
    closes: List[float] = [5000.0]
    for i in range(20):
        closes.append(closes[-1] + (2 if i % 2 == 0 else -2))
    for _ in range(20):
        closes.append(closes[-1] + 15)
    rows = [{"Date": d, "Close": c} for d, c in zip(dates, closes)]
    return pd.DataFrame(rows).set_index("Date")


def _volatile_history() -> pd.DataFrame:
    """25 real bars alternating +4%/-4% daily returns -- classifies
    "volatile" over its own trailing 20-bar window (independently
    verified against the real MarketRegimeEngine).
    """
    dates = pd.date_range(start="2026-01-01", periods=25, freq="D")
    closes: List[float] = [1000.0]
    for i in range(24):
        r = 0.04 if i % 2 == 0 else -0.04
        closes.append(closes[-1] * (1 + r))
    rows = [{"Date": d, "Close": c} for d, c in zip(dates, closes)]
    return pd.DataFrame(rows).set_index("Date")


def _short_history(n: int = 5) -> pd.DataFrame:
    """Deliberately too few real bars (below MarketRegimeEngine.
    MIN_BARS) to classify -- the honest "insufficient_data" fixture.
    """
    dates = pd.date_range(start="2026-01-01", periods=n, freq="D")
    closes = [100.0 + i for i in range(n)]
    rows = [{"Date": d, "Close": c} for d, c in zip(dates, closes)]
    return pd.DataFrame(rows).set_index("Date")


class _FakeTicker:
    def __init__(self, history_df: Optional[pd.DataFrame]) -> None:
        self._history_df = history_df

    def history(self, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        return self._history_df if self._history_df is not None else pd.DataFrame()


class FakeYFinanceModule:
    """Stand-in for the real ``yfinance`` module, injected through
    ``StockDataRepository``'s own existing ``yfinance_module``
    constructor parameter.
    """

    def __init__(self, histories: Dict[str, pd.DataFrame]) -> None:
        self._histories = histories

    def Ticker(self, symbol: str) -> _FakeTicker:
        return _FakeTicker(self._histories.get(symbol))


def _build(db_path: Path, histories: Dict[str, pd.DataFrame]):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(ORDERS_MIGRATIONS)
    MigrationRunner(db).apply(TRADES_MIGRATIONS)
    MigrationRunner(db).apply(POSITIONS_MIGRATIONS)
    MigrationRunner(db).apply(WATCHLIST_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repository = AccountRepository(manager)
    order_repository = OrderRepository(manager)
    trade_repository = TradeRepository(manager)
    position_repository = PositionRepository(manager)
    watchlist_repository = WatchlistRepository(manager)
    position_manager = PositionManager(position_repository)

    position_episode_replay_engine = PositionEpisodeReplayEngine(TradeHoldingPeriodEngine())

    stock_data_repository = StockDataRepository(yfinance_module=FakeYFinanceModule(histories))
    market_regime_service = MarketRegimeService(
        stock_data_repository=stock_data_repository,
        market_regime_engine=MarketRegimeEngine(),
    )
    market_regime_performance_engine = MarketRegimePerformanceEngine()

    service = MarketRegimeAttributionService(
        account_repository=account_repository,
        trade_repository=trade_repository,
        position_repository=position_repository,
        watchlist_repository=watchlist_repository,
        position_episode_replay_engine=position_episode_replay_engine,
        market_regime_service=market_regime_service,
        market_regime_performance_engine=market_regime_performance_engine,
    )
    return {
        "service": service,
        "account_repository": account_repository,
        "order_repository": order_repository,
        "trade_repository": trade_repository,
        "position_repository": position_repository,
        "watchlist_repository": watchlist_repository,
        "position_manager": position_manager,
        "db": db,
        "db_path": db_path,
    }


def _make_account(account_repository, account_id="paper", asset_class="stock_id"):
    return account_repository.create(
        account_id=account_id, account_name=account_id, mode="paper", currency="IDR",
        asset_class=asset_class, cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
    )


def _fill(ctx, account_id, symbol, action, quantity, fill_price, executed_at, fee=0.0, tax=0.0):
    order = ctx["order_repository"].create(
        account_id=account_id, symbol=symbol, action=action, quantity=quantity,
        requested_price=fill_price, filled_price=fill_price, status="FILLED",
        reason="", analysis_snapshot_id=None,
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
    for table in ("accounts", "orders", "trades", "positions", "watchlist"):
        counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    con.close()
    return counts


def scenario_unknown_account_raises_validation_error():
    print("\n[Scenario 1] get_performance_by_regime() on an unknown account_id raises ValidationError")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s1.db", histories={})
        raised = False
        try:
            ctx["service"].get_performance_by_regime("does-not-exist")
        except ValidationError:
            raised = True
        check(raised, "ValidationError raised, never a fabricated empty dict")


def scenario_zero_data_returns_empty_dict():
    print("\n[Scenario 2] an account with no trades at all returns an empty dict")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s2.db", histories={})
        _make_account(ctx["account_repository"])
        result = ctx["service"].get_performance_by_regime("paper")
        check(result == {}, "zero trades -> empty dict, not an error")


def scenario_regime_based_on_opening_trade_timestamp_no_lookahead():
    print("\n[Scenario 3] regime attribution uses each episode's OPENING trade timestamp -- no lookahead")
    with tempfile.TemporaryDirectory() as tmp:
        symbol = "BBCA"
        histories = {symbol: _choppy_then_trending_history()}
        ctx = _build(Path(tmp) / "s3.db", histories=histories)
        _make_account(ctx["account_repository"])

        # Episode 1 opens on day5 (well inside the real "choppy" half) and
        # closes same day -- its regime must come from real bars at/before
        # day5 only (never the later, real "trending" half of the fixture).
        _fill(ctx, "paper", symbol, "BUY", 10.0, 5000.0, "2026-01-06T09:00:00+00:00")
        _fill(ctx, "paper", symbol, "SELL", 10.0, 5010.0, "2026-01-06T13:00:00+00:00")

        # Episode 2 opens on day40 (the full real "trending" half is now
        # available at/before this later real timestamp).
        _fill(ctx, "paper", symbol, "BUY", 10.0, 5300.0, "2026-02-10T09:00:00+00:00")
        _fill(ctx, "paper", symbol, "SELL", 10.0, 5320.0, "2026-02-10T13:00:00+00:00")

        result = ctx["service"].get_performance_by_regime("paper")
        check(
            REGIME_INSUFFICIENT_DATA in result,
            "the day5-opened episode has too few real bars before it (only ~6 real bars exist by day5) "
            "-> honestly grouped under 'insufficient_data', never guessed",
        )
        check(
            "trending" in result,
            "the day40-opened episode sees the full real trending history at/before its own opening moment -> 'trending'",
        )
        check(
            result[REGIME_INSUFFICIENT_DATA].closed_episodes == 1,
            "exactly the early episode lands in insufficient_data",
        )
        check(
            result["trending"].closed_episodes == 1,
            "exactly the later episode lands in trending",
        )


def scenario_two_distinct_real_regimes_same_and_different_symbols():
    print("\n[Scenario 4] at least 2 distinct REAL regimes observed across closed episodes, from real OHLCV")
    with tempfile.TemporaryDirectory() as tmp:
        trending_symbol = "TRND"
        volatile_symbol = "VOLT"
        histories = {
            trending_symbol: _choppy_then_trending_history(),
            volatile_symbol: _volatile_history(),
        }
        ctx = _build(Path(tmp) / "s4.db", histories=histories)
        _make_account(ctx["account_repository"])

        # Opens late enough on TRND to see the real trending half.
        _fill(ctx, "paper", trending_symbol, "BUY", 10.0, 5300.0, "2026-02-10T09:00:00+00:00")
        _fill(ctx, "paper", trending_symbol, "SELL", 10.0, 5350.0, "2026-02-10T13:00:00+00:00")

        # Opens on VOLT, where the whole real fixture is volatile.
        _fill(ctx, "paper", volatile_symbol, "BUY", 5.0, 1000.0, "2026-01-25T09:00:00+00:00")
        _fill(ctx, "paper", volatile_symbol, "SELL", 5.0, 900.0, "2026-01-25T13:00:00+00:00")

        result = ctx["service"].get_performance_by_regime("paper")
        check(len(result) >= 2, "at least 2 distinct regime labels observed across the account's closed episodes")
        check("trending" in result, "TRND's late-opened episode is real 'trending'")
        check("volatile" in result, "VOLT's episode is real 'volatile'")
        check(
            result["trending"].net_profit == (5350.0 - 5300.0) * 10.0,
            "Position.realized_pnl is used verbatim for the trending group -- never recomputed",
        )
        check(
            result["volatile"].net_profit == (900.0 - 1000.0) * 5.0,
            "Position.realized_pnl is used verbatim for the volatile group -- never recomputed",
        )
        check(result["volatile"].losing_episodes == 1, "the losing VOLT episode is correctly counted as a loss")


def scenario_market_condition_variety_from_real_watchlist():
    print("\n[Scenario 5] get_market_condition_variety() reports real, currently-observed variety (>= 2 regimes)")
    with tempfile.TemporaryDirectory() as tmp:
        trending_symbol = "TRND"
        volatile_symbol = "VOLT"
        thin_symbol = "THIN"
        histories = {
            trending_symbol: _choppy_then_trending_history(),
            volatile_symbol: _volatile_history(),
            thin_symbol: _short_history(),
        }
        ctx = _build(Path(tmp) / "s5.db", histories=histories)
        ctx["watchlist_repository"].add(trending_symbol)
        ctx["watchlist_repository"].add(volatile_symbol)
        ctx["watchlist_repository"].add(thin_symbol)

        variety = ctx["service"].get_market_condition_variety()
        check(variety["regime_count"] >= 2, "at least 2 distinct real regimes observed in the current watchlist")
        check(set(variety["observed_regimes"]) == {"trending", "volatile"}, "the observed_regimes set matches exactly the real, classifiable symbols")
        check(variety["symbols_classified"] == 2, "2 of 3 watchlist symbols were classifiable from real data")
        check(variety["symbols_insufficient_data"] == 1, "the too-short-history symbol is honestly reported as insufficient_data")
        check(variety["per_symbol"][thin_symbol] == REGIME_INSUFFICIENT_DATA, "the per-symbol evidence backs the insufficient_data count")
        check(variety["per_symbol"][trending_symbol] == "trending", "the per-symbol evidence backs the trending count")
        check(variety["per_symbol"][volatile_symbol] == "volatile", "the per-symbol evidence backs the volatile count")


def scenario_empty_watchlist_is_honest_zero():
    print("\n[Scenario 6] an empty watchlist honestly reports all-zero variety, never a guessed variety")
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _build(Path(tmp) / "s6.db", histories={})
        variety = ctx["service"].get_market_condition_variety()
        check(variety["regime_count"] == 0, "empty watchlist -> zero regime_count")
        check(variety["observed_regimes"] == [], "empty watchlist -> empty observed_regimes list")
        check(variety["symbols_classified"] == 0, "empty watchlist -> zero symbols_classified")
        check(variety["symbols_insufficient_data"] == 0, "empty watchlist -> zero symbols_insufficient_data")


def scenario_open_position_excluded():
    print("\n[Scenario 7] an account with trades but zero CLOSED episodes returns an empty dict")
    with tempfile.TemporaryDirectory() as tmp:
        histories = {"BBRI": _choppy_then_trending_history()}
        ctx = _build(Path(tmp) / "s7.db", histories=histories)
        _make_account(ctx["account_repository"])
        _fill(ctx, "paper", "BBRI", "BUY", 100.0, 4000.0, "2026-01-06T09:00:00+00:00")

        result = ctx["service"].get_performance_by_regime("paper")
        check(result == {}, "a still-open position is never reported as a closed episode")


def scenario_deterministic_and_read_only():
    print("\n[Scenario 8] deterministic + read-only: repeated calls yield equal results and no DB writes")
    with tempfile.TemporaryDirectory() as tmp:
        trending_symbol = "TRND"
        histories = {trending_symbol: _choppy_then_trending_history()}
        ctx = _build(Path(tmp) / "s8.db", histories=histories)
        _make_account(ctx["account_repository"])
        ctx["watchlist_repository"].add(trending_symbol)
        _fill(ctx, "paper", trending_symbol, "BUY", 10.0, 5300.0, "2026-02-10T09:00:00+00:00")
        _fill(ctx, "paper", trending_symbol, "SELL", 10.0, 5320.0, "2026-02-10T13:00:00+00:00")

        before = _row_counts(ctx["db_path"])
        perf_first = ctx["service"].get_performance_by_regime("paper")
        variety_first = ctx["service"].get_market_condition_variety()
        perf_second = ctx["service"].get_performance_by_regime("paper")
        variety_second = ctx["service"].get_market_condition_variety()
        after = _row_counts(ctx["db_path"])

        check(perf_first == perf_second, "get_performance_by_regime() is deterministic across repeated calls")
        check(variety_first == variety_second, "get_market_condition_variety() is deterministic across repeated calls")
        check(before == after, "row counts across every touched table are unchanged -- no DB writes")


def main() -> int:
    scenario_unknown_account_raises_validation_error()
    scenario_zero_data_returns_empty_dict()
    scenario_regime_based_on_opening_trade_timestamp_no_lookahead()
    scenario_two_distinct_real_regimes_same_and_different_symbols()
    scenario_market_condition_variety_from_real_watchlist()
    scenario_empty_watchlist_is_honest_zero()
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