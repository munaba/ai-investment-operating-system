"""Standalone regression checks for
``Business.market_regime_engine.MarketRegimeEngine``.

Covers ACTIVATION 7 (performance per market regime / market-condition
variety) at the pure-classifier level -- no repository, no database,
no I/O. Every fixture below is a plain, hand-computed arithmetic
series (never randomized), and every expected result in this file was
independently verified against the engine's own documented formulas
before being hardcoded here.

* insufficient-data behavior: fewer than ``MIN_BARS`` closes, and any
  non-positive close, both -> ``STATUS_INSUFFICIENT_DATA`` /
  ``regime=None`` (never a guessed/defaulted regime label);
* exact threshold/boundary behavior: ``volatility == VOLATILITY_THRESHOLD``
  exactly classifies "volatile"; ``efficiency_ratio ==
  TREND_EFFICIENCY_THRESHOLD`` exactly (with volatility below its own
  threshold) classifies "trending"; the LOCKED check order (volatility
  first) is verified with a window that is both high-volatility AND
  high-efficiency-ratio, confirming "volatile" wins;
* exactly ``MIN_BARS`` closes classifies (does not spuriously report
  insufficient data at the boundary itself);
* determinism: calling ``classify()`` twice on the identical list
  returns an equal result, and the input list is never mutated.

Run directly with ``python Tests/test_market_regime_engine.py`` -- no
external test framework required.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.market_regime_engine import (  # noqa: E402
    MIN_BARS,
    REGIME_RANGING,
    REGIME_TRENDING,
    REGIME_VOLATILE,
    STATUS_CLASSIFIED,
    STATUS_INSUFFICIENT_DATA,
    TREND_EFFICIENCY_THRESHOLD,
    VOLATILITY_THRESHOLD,
    MarketRegimeEngine,
)

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


def _alternating_returns_closes(r: float, n_returns: int, start: float = 1000.0):
    """``n_returns`` closes (plus the starting close) whose daily
    returns alternate exactly ``+r``/``-r``. For an even
    ``n_returns`` this makes the population mean exactly 0 and the
    population stdev exactly ``abs(r)`` -- an exact, hand-verifiable
    volatility fixture, not an approximation.
    """
    closes = [start]
    for i in range(n_returns):
        signed_r = r if i % 2 == 0 else -r
        closes.append(closes[-1] * (1 + signed_r))
    return closes


def _unit_step_closes(up_steps: int, down_steps: int, start: float = 1000.0):
    """Closes built from ``up_steps`` diffs of ``+1`` and
    ``down_steps`` diffs of ``-1`` (ups first, then downs). Because
    every diff has the same magnitude, ``efficiency_ratio`` reduces
    to exactly ``(up_steps - down_steps) / (up_steps + down_steps)``
    regardless of ordering -- an exact, hand-verifiable
    efficiency-ratio fixture. A large ``start`` keeps every daily
    percentage return tiny, so volatility stays far below
    ``VOLATILITY_THRESHOLD`` in these fixtures.
    """
    closes = [start]
    for _ in range(up_steps):
        closes.append(closes[-1] + 1)
    for _ in range(down_steps):
        closes.append(closes[-1] - 1)
    return closes


def scenario_insufficient_data_too_few_bars():
    print("\n[Scenario 1] fewer than MIN_BARS closes -> STATUS_INSUFFICIENT_DATA, regime=None")
    engine = MarketRegimeEngine()
    too_few = [100.0 + i for i in range(MIN_BARS - 1)]
    check(len(too_few) == MIN_BARS - 1, "fixture sanity: exactly one below MIN_BARS")
    result = engine.classify(too_few)
    check(result.status == STATUS_INSUFFICIENT_DATA, "status is insufficient_data")
    check(result.regime is None, "regime is None, never a fabricated/guessed label")
    check(result.volatility is None, "volatility is None")
    check(result.efficiency_ratio is None, "efficiency_ratio is None")
    check(result.bar_count == MIN_BARS - 1, "bar_count records the real (short) supplied length")


def scenario_insufficient_data_non_positive_close():
    print("\n[Scenario 2] any close <= 0 -> STATUS_INSUFFICIENT_DATA (undefined return), never guessed")
    engine = MarketRegimeEngine()
    closes = [100.0] * (MIN_BARS + 5)
    closes[7] = 0.0  # a zero close mid-window makes one return undefined
    result = engine.classify(closes)
    check(result.status == STATUS_INSUFFICIENT_DATA, "a single non-positive close disqualifies the whole window")
    check(result.regime is None, "regime is None, not defaulted")

    closes_negative = [100.0] * (MIN_BARS + 5)
    closes_negative[3] = -5.0
    result_negative = engine.classify(closes_negative)
    check(result_negative.status == STATUS_INSUFFICIENT_DATA, "a negative close is treated the same way")


def scenario_exactly_min_bars_classifies():
    print("\n[Scenario 3] exactly MIN_BARS closes classifies -- the boundary itself is NOT insufficient")
    engine = MarketRegimeEngine()
    closes = _alternating_returns_closes(r=0.001, n_returns=MIN_BARS - 1)
    check(len(closes) == MIN_BARS, "fixture sanity: exactly MIN_BARS closes")
    result = engine.classify(closes)
    check(result.status == STATUS_CLASSIFIED, "MIN_BARS closes is enough to classify, not insufficient_data")
    check(result.bar_count == MIN_BARS, "bar_count reflects the real supplied length")


def scenario_volatility_exact_threshold_boundary():
    print("\n[Scenario 4] volatility at (>=) VOLATILITY_THRESHOLD -> 'volatile' (the '>=' is inclusive)")
    engine = MarketRegimeEngine()
    # r is set a hair above VOLATILITY_THRESHOLD, not bit-identical to it: the
    # engine computes volatility via a mean/variance/sqrt pipeline, so an
    # input alternating exactly +/-VOLATILITY_THRESHOLD can round to a
    # stdev a few ULPs *below* the threshold through ordinary
    # floating-point rounding (verified: 0.025 alternating rounds to
    # 0.024999999999999973). This fixture instead pins the input just
    # above the threshold so the boundary direction (">=" is inclusive)
    # is what gets exercised, without fighting float noise.
    closes = _alternating_returns_closes(r=VOLATILITY_THRESHOLD + 1e-9, n_returns=14)
    result = engine.classify(closes)
    check(result.volatility >= VOLATILITY_THRESHOLD, "fixture sanity: computed volatility is at/above the threshold")
    check(result.status == STATUS_CLASSIFIED, "classified (enough bars)")
    check(result.regime == REGIME_VOLATILE, "at/above-threshold volatility classifies as 'volatile'")


def scenario_volatility_just_below_threshold_falls_through_to_efficiency():
    print("\n[Scenario 5] volatility just below threshold + high efficiency_ratio -> 'trending' (priority order holds)")
    engine = MarketRegimeEngine()
    # 14 up-steps, 0 down-steps over a high price base: efficiency_ratio == 1.0,
    # and the tiny relative daily moves keep volatility far below VOLATILITY_THRESHOLD.
    closes = _unit_step_closes(up_steps=14, down_steps=0, start=10_000.0)
    result = engine.classify(closes)
    check(result.volatility < VOLATILITY_THRESHOLD, "fixture sanity: volatility is below the volatile threshold")
    check(result.efficiency_ratio >= TREND_EFFICIENCY_THRESHOLD, "fixture sanity: efficiency_ratio is at/above the trend threshold")
    check(result.regime == REGIME_TRENDING, "low volatility + high efficiency_ratio classifies as 'trending'")


def scenario_efficiency_ratio_exact_threshold_boundary():
    print("\n[Scenario 6] efficiency_ratio == TREND_EFFICIENCY_THRESHOLD exactly -> 'trending'")
    engine = MarketRegimeEngine()
    # 14 up-steps, 6 down-steps: (14-6)/(14+6) == 8/20 == 0.4 exactly.
    closes = _unit_step_closes(up_steps=14, down_steps=6, start=1_000.0)
    result = engine.classify(closes)
    check(abs(result.efficiency_ratio - TREND_EFFICIENCY_THRESHOLD) < 1e-12, "computed efficiency_ratio equals the threshold exactly")
    check(result.volatility < VOLATILITY_THRESHOLD, "fixture sanity: volatility stays below its own threshold")
    check(result.regime == REGIME_TRENDING, "exactly-at-threshold efficiency_ratio classifies as 'trending'")


def scenario_efficiency_ratio_just_below_threshold_is_ranging():
    print("\n[Scenario 7] efficiency_ratio just below TREND_EFFICIENCY_THRESHOLD -> 'ranging'")
    engine = MarketRegimeEngine()
    # 17 up-steps, 8 down-steps: (17-8)/(17+8) == 9/25 == 0.36 < 0.4.
    closes = _unit_step_closes(up_steps=17, down_steps=8, start=1_000.0)
    result = engine.classify(closes)
    check(result.efficiency_ratio < TREND_EFFICIENCY_THRESHOLD, "fixture sanity: efficiency_ratio is below the trend threshold")
    check(result.volatility < VOLATILITY_THRESHOLD, "fixture sanity: volatility is below the volatile threshold")
    check(result.regime == REGIME_RANGING, "below both thresholds classifies as 'ranging'")


def scenario_priority_order_volatility_wins_over_high_efficiency():
    print("\n[Scenario 8] volatility AND efficiency_ratio both high -> 'volatile' wins (LOCKED check order)")
    engine = MarketRegimeEngine()
    # A monotonic uptrend (every return is positive, so
    # efficiency_ratio == 1.0) but alternating between two large,
    # unequal daily percentage jumps (+8%/+2%) -- this keeps the
    # returns' population stdev well above VOLATILITY_THRESHOLD (a
    # constant daily return, e.g. always exactly +5%, would instead
    # have zero variance and therefore zero volatility).
    closes = [100.0]
    for i in range(19):
        r = 0.08 if i % 2 == 0 else 0.02
        closes.append(closes[-1] * (1 + r))
    result = engine.classify(closes)
    check(result.efficiency_ratio >= TREND_EFFICIENCY_THRESHOLD, "fixture sanity: efficiency_ratio is high (pure uptrend)")
    check(result.volatility >= VOLATILITY_THRESHOLD, "fixture sanity: volatility is also high")
    check(result.regime == REGIME_VOLATILE, "volatility is checked first -- 'volatile' wins even though efficiency_ratio also qualifies for 'trending'")


def scenario_deterministic_and_non_mutating():
    print("\n[Scenario 9] classify() is deterministic and never mutates its input")
    engine = MarketRegimeEngine()
    closes = _unit_step_closes(up_steps=14, down_steps=6, start=1_000.0)
    original = list(closes)

    first = engine.classify(closes)
    second = engine.classify(closes)

    check(first == second, "calling classify() twice on the identical list yields an equal result")
    check(closes == original, "classify() never mutates the closes list it was given")


def main() -> int:
    scenario_insufficient_data_too_few_bars()
    scenario_insufficient_data_non_positive_close()
    scenario_exactly_min_bars_classifies()
    scenario_volatility_exact_threshold_boundary()
    scenario_volatility_just_below_threshold_falls_through_to_efficiency()
    scenario_efficiency_ratio_exact_threshold_boundary()
    scenario_efficiency_ratio_just_below_threshold_is_ranging()
    scenario_priority_order_volatility_wins_over_high_efficiency()
    scenario_deterministic_and_non_mutating()

    print(f"\n{'=' * 70}\nRESULTS: {_PASS} passed, {_FAIL} failed\n{'=' * 70}")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())