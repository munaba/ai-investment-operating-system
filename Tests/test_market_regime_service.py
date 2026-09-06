"""Standalone regression checks for
``Business.market_regime_service.MarketRegimeService``.

Covers ACTIVATION 7 (performance per market regime) real-data
resolution: this service's only collaborators are the real
``Repository.external.stock_data_repository.StockDataRepository``
(with a fake ``yfinance``-compatible module injected through its own
existing ``yfinance_module`` constructor parameter -- never a
StockDataRepository/StockService/StockService method mock, and never
network access) and the real ``MarketRegimeEngine``.

* insufficient-data behavior: an empty history, a history that raises
  (``RepositoryError``), and a history with fewer than
  ``MarketRegimeEngine.MIN_BARS`` real bars at/before ``as_of``, all
  resolve to ``STATUS_INSUFFICIENT_DATA`` -- never a fabricated
  regime;
* no-lookahead ``as_of`` behavior: the central scenario in this file --
  a single fake history whose first half is a real choppy/"ranging"
  shape and whose second half is a real, strongly directional
  "trending" shape. Classifying with ``as_of`` bound to the end of the
  first half returns "ranging" (the correct, non-lookahead answer);
  classifying with no ``as_of`` bound (or one at/after the end of the
  full history) returns "trending" -- proving the earlier call never
  saw the later, real "future" bars;
* malformed/NaN ``"Close"`` values and non-numeric ``as_of`` strings
  are excluded/ignored defensively, never fabricated into a number;
* restart/determinism: calling ``classify_symbol_regime`` twice with
  the same ``(symbol, as_of)`` against the same real fake history
  returns an identical result -- this is what makes the "no schema
  migration, always deterministically recomputed" persistence
  decision documented in the module docstring restart-safe in
  production (real historical OHLCV for a past date does not change
  between runs, so the same recomputation always recovers the same
  regime).

Run directly with ``python Tests/test_market_regime_service.py`` -- no
external test framework required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402

from Business.market_regime_engine import (  # noqa: E402
    MarketRegimeEngine,
    REGIME_RANGING,
    REGIME_TRENDING,
    STATUS_CLASSIFIED,
    STATUS_INSUFFICIENT_DATA,
)
from Business.market_regime_service import MarketRegimeService  # noqa: E402
from Core.exceptions import RepositoryError  # noqa: E402
from Repository.external.stock_data_repository import StockDataRepository  # noqa: E402

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


def _choppy_then_trending_history() -> pd.DataFrame:
    """41 real daily bars, day0..day40 (2026-01-01 .. 2026-02-10):

    * day0..day20 (21 closes): a small alternating +2/-2 zig-zag --
      low volatility, ~zero efficiency_ratio -> "ranging" once
      classified over its own trailing 20-bar window.
    * day20..day40 (21 more diffs of +15): a strong, consistent
      uptrend -> "trending" once classified over ITS trailing
      20-bar window.

    Independently verified (outside this test, against the real
    ``MarketRegimeEngine``) that classifying the trailing 20 bars
    ending at day20 yields "ranging", and the trailing 20 bars ending
    at day40 (or later) yields "trending" -- this is the fixture the
    no-lookahead scenario below depends on.
    """
    dates = pd.date_range(start="2026-01-01", periods=41, freq="D")
    closes: List[float] = [5000.0]
    for i in range(20):
        closes.append(closes[-1] + (2 if i % 2 == 0 else -2))
    for _ in range(20):
        closes.append(closes[-1] + 15)

    rows = [{"Date": d, "Close": c} for d, c in zip(dates, closes)]
    return pd.DataFrame(rows).set_index("Date")


class _FakeTicker:
    def __init__(self, symbol: str, history_df: Optional[pd.DataFrame], raise_error: bool = False) -> None:
        self._symbol = symbol
        self._history_df = history_df
        self._raise_error = raise_error

    def history(self, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        if self._raise_error:
            raise RuntimeError(f"simulated provider failure for {self._symbol}")
        if self._history_df is None:
            return pd.DataFrame()
        return self._history_df


class FakeYFinanceModule:
    """Stand-in for the real ``yfinance`` module, injected through
    ``StockDataRepository``'s own existing ``yfinance_module``
    constructor parameter -- never a mock of ``StockDataRepository``
    or ``MarketRegimeService`` themselves.
    """

    def __init__(
        self,
        histories: Optional[Dict[str, pd.DataFrame]] = None,
        error_symbols: Optional[set] = None,
    ) -> None:
        self._histories = histories or {}
        self._error_symbols = error_symbols or set()

    def Ticker(self, symbol: str) -> _FakeTicker:
        return _FakeTicker(
            symbol,
            self._histories.get(symbol),
            raise_error=symbol in self._error_symbols,
        )


def _build_service(yf_module: FakeYFinanceModule) -> MarketRegimeService:
    stock_data_repository = StockDataRepository(yfinance_module=yf_module)
    return MarketRegimeService(
        stock_data_repository=stock_data_repository,
        market_regime_engine=MarketRegimeEngine(),
    )


def scenario_empty_history_is_insufficient_data():
    print("\n[Scenario 1] empty real history -> STATUS_INSUFFICIENT_DATA, never a fabricated regime")
    service = _build_service(FakeYFinanceModule(histories={"EMPTY": pd.DataFrame()}))
    result = service.classify_symbol_regime("EMPTY")
    check(result.status == STATUS_INSUFFICIENT_DATA, "empty history classifies as insufficient_data")
    check(result.regime is None, "regime is None, not guessed")


def scenario_repository_error_is_insufficient_data():
    print("\n[Scenario 2] a provider/RepositoryError -> STATUS_INSUFFICIENT_DATA, never raises out")
    service = _build_service(FakeYFinanceModule(error_symbols={"BROKEN"}))
    result = service.classify_symbol_regime("BROKEN")
    check(result.status == STATUS_INSUFFICIENT_DATA, "a fetch failure is reported as insufficient_data, not an exception")
    check(result.regime is None, "regime is None, not guessed")


def scenario_too_few_real_bars_before_as_of_is_insufficient_data():
    print("\n[Scenario 3] fewer than MIN_BARS real bars at/before as_of -> STATUS_INSUFFICIENT_DATA")
    history = _choppy_then_trending_history()
    service = _build_service(FakeYFinanceModule(histories={"THIN": history}))
    # as_of = day5: only 6 real bars (day0..day5) exist at/before this date,
    # far short of MarketRegimeEngine.MIN_BARS (15).
    result = service.classify_symbol_regime("THIN", as_of="2026-01-06T00:00:00+00:00")
    check(result.status == STATUS_INSUFFICIENT_DATA, "too few real bars before as_of classifies as insufficient_data")
    check(result.regime is None, "regime is None, not guessed from a short window")
    check(result.bar_count == 6, "bar_count reports exactly the real bars that were actually available")


def scenario_no_lookahead_as_of_excludes_future_bars():
    print("\n[Scenario 4] no-lookahead: as_of bound to day20 sees only the real 'ranging' half, not the later real 'trending' half")
    history = _choppy_then_trending_history()
    service = _build_service(FakeYFinanceModule(histories={"NOLOOK": history}))

    as_of_early = service.classify_symbol_regime("NOLOOK", as_of="2026-01-21T00:00:00+00:00")  # day20
    as_of_late = service.classify_symbol_regime("NOLOOK", as_of="2026-02-10T00:00:00+00:00")  # day40 (full history)
    as_of_none = service.classify_symbol_regime("NOLOOK")  # no bound -- also the full history

    check(as_of_early.status == STATUS_CLASSIFIED, "the early as_of has enough real bars to classify")
    check(as_of_early.regime == REGIME_RANGING, "bound to day20, only the real choppy half is visible -> 'ranging'")
    check(as_of_late.regime == REGIME_TRENDING, "bound to day40 (full history), the real trend half is now visible -> 'trending'")
    check(as_of_none.regime == REGIME_TRENDING, "no as_of bound behaves the same as 'as of now' (full real history) -> 'trending'")
    check(
        as_of_early.regime != as_of_late.regime,
        "the early classification is provably NOT peeking at the later real bars -- different, correct answers",
    )


def scenario_nan_and_malformed_closes_excluded():
    print("\n[Scenario 5] NaN/malformed 'Close' values are excluded defensively, never fabricated")
    dates = pd.date_range(start="2026-01-01", periods=25, freq="D")
    closes = [1000.0 + i for i in range(25)]
    df = pd.DataFrame({"Date": dates, "Close": closes}).set_index("Date")
    df.iloc[5, df.columns.get_loc("Close")] = float("nan")

    service = _build_service(FakeYFinanceModule(histories={"NANNY": df}))
    result = service.classify_symbol_regime("NANNY")
    # 25 real bars minus 1 NaN bar = 24 usable closes -- still classifiable.
    check(result.status == STATUS_CLASSIFIED, "a single NaN close does not poison the whole window -- it is excluded, and enough real bars remain")
    check(result.bar_count <= 24, "the NaN bar is excluded from bar_count, never counted as real data")


def scenario_malformed_as_of_string_is_ignored_not_fatal():
    print("\n[Scenario 6] a malformed as_of string is ignored (treated as no bound), never raises")
    history = _choppy_then_trending_history()
    service = _build_service(FakeYFinanceModule(histories={"BADASOF": history}))
    result = service.classify_symbol_regime("BADASOF", as_of="not-a-real-timestamp")
    check(result.status == STATUS_CLASSIFIED, "a malformed as_of does not crash the call")
    check(result.regime == REGIME_TRENDING, "a malformed as_of falls back to the full (unbounded) real history")


def scenario_deterministic_restart_safe():
    print("\n[Scenario 7] restart/determinism: identical (symbol, as_of) always recovers the identical classification")
    history = _choppy_then_trending_history()
    service_run_1 = _build_service(FakeYFinanceModule(histories={"NOLOOK": history}))
    # A brand-new MarketRegimeService instance (simulating a fresh
    # process/restart) built over the same real historical data.
    service_run_2 = _build_service(FakeYFinanceModule(histories={"NOLOOK": history}))

    first = service_run_1.classify_symbol_regime("NOLOOK", as_of="2026-01-21T00:00:00+00:00")
    second = service_run_2.classify_symbol_regime("NOLOOK", as_of="2026-01-21T00:00:00+00:00")
    third = service_run_1.classify_symbol_regime("NOLOOK", as_of="2026-01-21T00:00:00+00:00")

    check(first == second, "a fresh service instance ('restart') recovers an identical classification from the same real history")
    check(first == third, "calling the same instance twice also yields an identical result")


def main() -> int:
    scenario_empty_history_is_insufficient_data()
    scenario_repository_error_is_insufficient_data()
    scenario_too_few_real_bars_before_as_of_is_insufficient_data()
    scenario_no_lookahead_as_of_excludes_future_bars()
    scenario_nan_and_malformed_closes_excluded()
    scenario_malformed_as_of_string_is_ignored_not_fatal()
    scenario_deterministic_restart_safe()

    print(f"\n{'=' * 70}\nRESULTS: {_PASS} passed, {_FAIL} failed\n{'=' * 70}")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())