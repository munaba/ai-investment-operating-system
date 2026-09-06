"""MarketRegimeEngine -- ACTIVATION 7 (performance per market regime).

Resolves the ONE conflict the roadmap re-audit identified: the
higher-level ``Master Prompt (Roadmap).md`` ACTIVATION 7 -- PAPER
VALIDATION gate explicitly lists ``performance per market regime`` and
``variasi kondisi pasar`` (market-condition variety) as minimum
validation dimensions, while a prior session had LOCKED "no market
regime" as out of scope (see
``Business.strategy_performance_service`` module docstring, and
``Docs/ACTIVATION 7/AIOS_Activation7_Final_Closeout_Report.md``,
"Market-condition evidence -- OPEN GAP"). Per this session's explicit
instruction, that narrower LOCKED decision is superseded ONLY for
market-regime classification -- nothing else about
``StrategyPerformanceService``/``StrategyPerformanceEngine`` (fee
formula, trading flow, decision table, schema) is touched.

This module is a pure, deterministic, dependency-free classifier over
already-fetched OHLCV bars. It does not import ``yfinance``, does not
know about ``StockDataRepository``, does not read any repository or
the database, and performs no I/O of any kind -- mirrors the existing
``Business.profit_factor_engine.ProfitFactorEngine``/
``Business.strategy_performance_engine.StrategyPerformanceEngine``
minimal-input, no-dependency style exactly.

LOCKED classification method (documented here, not tuned per-call, no
ML, no external service):

    Given a chronological window of closing prices
    ``close[0..n-1]`` (``n >= MIN_BARS``):

    1. Daily returns ``r[i] = (close[i] - close[i-1]) / close[i-1]``
       for ``i in 1..n-1``.
    2. ``volatility`` = population standard deviation of ``r``.
    3. ``efficiency_ratio`` = ``abs(close[n-1] - close[0]) /
       sum(abs(close[i] - close[i-1]) for i in 1..n-1)`` -- a
       Kaufman-style "efficiency ratio": how much of the window's
       total price movement (the denominator, the sum of every
       single day's absolute move) actually contributed to the net
       directional move (the numerator). Range ``[0, 1]``; ``1`` means
       every day moved the same direction (a pure trend), ``0`` means
       the window round-tripped back to where it started (pure
       chop/range).
    4. Classify, checked in this fixed order:

           volatility >= VOLATILITY_THRESHOLD        -> "volatile"
           efficiency_ratio >= TREND_EFFICIENCY_THRESHOLD -> "trending"
           otherwise                                  -> "ranging"

       Volatility is checked first (LOCKED, documented choice): a
       window can be both choppy AND wide-swinging (e.g. a volatile
       range), and "volatile" is the more decision-relevant label for
       risk/position-sizing purposes than "ranging" would be in that
       case.

    Fewer than ``MIN_BARS`` closes (or any close <= 0, which would
    make a return undefined) -> ``status="insufficient_data"``,
    ``regime=None``. This is never guessed or defaulted to a regime
    label -- an explicit, honest "not enough real data" status,
    per this session's instruction.

No fabrication: every number this engine reports is a plain
arithmetic function of the real ``close`` values it was given. If the
caller's data source could not supply enough real bars, this engine
says so explicitly rather than picking a plausible-looking label.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

#: Regime labels this engine ever returns (besides ``None``) -- LOCKED,
#: per the ACTIVATION 7 instruction: "trending", "ranging", "volatile".
REGIME_TRENDING = "trending"
REGIME_RANGING = "ranging"
REGIME_VOLATILE = "volatile"

#: Status returned when there is not enough real history to classify.
#: Never a fabricated/default regime label.
STATUS_INSUFFICIENT_DATA = "insufficient_data"
#: Status returned when classification succeeded.
STATUS_CLASSIFIED = "classified"

#: Minimum number of real closing prices required to classify a
#: window at all. Below this, a standard deviation / efficiency ratio
#: would be statistically meaningless (e.g. a 2-bar "window" always
#: has efficiency_ratio == 1.0, which is not a real trend signal).
#: Chosen as roughly one trading month of daily bars -- documented,
#: fixed, not tuned per call.
MIN_BARS: int = 15

#: Daily-return population-stdev threshold above which a window is
#: classified "volatile" regardless of its efficiency ratio. 0.025
#: (2.5% daily stdev) is a documented, fixed threshold -- not fit to
#: any dataset, not learned, not adjustable per call.
VOLATILITY_THRESHOLD: float = 0.025

#: Efficiency-ratio threshold at/above which a (non-volatile) window
#: is classified "trending" rather than "ranging". 0.4 is a
#: documented, fixed threshold.
TREND_EFFICIENCY_THRESHOLD: float = 0.4


@dataclass
class MarketRegimeClassification:
    """The deterministic result of classifying one window of closes.

    Attributes:
        status: ``STATUS_CLASSIFIED`` or ``STATUS_INSUFFICIENT_DATA``.
        regime: One of ``REGIME_TRENDING``/``REGIME_RANGING``/
            ``REGIME_VOLATILE`` when ``status == STATUS_CLASSIFIED``,
            else ``None`` -- never a fabricated/guessed label.
        volatility: The computed population stdev of daily returns,
            or ``None`` when ``status == STATUS_INSUFFICIENT_DATA``.
        efficiency_ratio: The computed Kaufman-style efficiency
            ratio, or ``None`` when
            ``status == STATUS_INSUFFICIENT_DATA``.
        bar_count: The number of closes actually supplied (always
            recorded, even on ``STATUS_INSUFFICIENT_DATA``, so a
            caller can report exactly how much real data was
            available).
    """

    status: str
    regime: Optional[str]
    volatility: Optional[float]
    efficiency_ratio: Optional[float]
    bar_count: int


class MarketRegimeEngine:
    """Deterministic trending/ranging/volatile classifier over a
    chronological window of real closing prices.

    Pure business object -- no dependency, no repository, no
    database, no I/O, no randomness, no ML. Calling ``classify()``
    twice with the same ``closes`` always returns the identical
    result -- this is what makes regime attribution restart-safe
    without persisting anything: the same real historical closes
    (see ``Business.market_regime_service.MarketRegimeService``)
    always deterministically recover the same regime.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def classify(self, closes: Sequence[float]) -> MarketRegimeClassification:
        """Classify a chronological window of closing prices.

        Args:
            closes: Real closing prices, oldest first, newest last.
                Not mutated.

        Returns:
            A :class:`MarketRegimeClassification`. Never raises for a
            too-short or degenerate window -- reports
            ``STATUS_INSUFFICIENT_DATA`` instead.
        """
        bar_count = len(closes)

        if bar_count < MIN_BARS:
            return MarketRegimeClassification(
                status=STATUS_INSUFFICIENT_DATA,
                regime=None,
                volatility=None,
                efficiency_ratio=None,
                bar_count=bar_count,
            )

        # A non-positive close makes a percentage return undefined --
        # this is bad/unusable real data, not a reason to guess.
        if any(close <= 0 for close in closes):
            return MarketRegimeClassification(
                status=STATUS_INSUFFICIENT_DATA,
                regime=None,
                volatility=None,
                efficiency_ratio=None,
                bar_count=bar_count,
            )

        returns: List[float] = [
            (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, bar_count)
        ]

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        volatility = math.sqrt(variance)

        total_absolute_move = sum(
            abs(closes[i] - closes[i - 1]) for i in range(1, bar_count)
        )
        net_move = abs(closes[-1] - closes[0])
        efficiency_ratio = (
            net_move / total_absolute_move if total_absolute_move > 0 else 0.0
        )

        if volatility >= VOLATILITY_THRESHOLD:
            regime = REGIME_VOLATILE
        elif efficiency_ratio >= TREND_EFFICIENCY_THRESHOLD:
            regime = REGIME_TRENDING
        else:
            regime = REGIME_RANGING

        return MarketRegimeClassification(
            status=STATUS_CLASSIFIED,
            regime=regime,
            volatility=volatility,
            efficiency_ratio=efficiency_ratio,
            bar_count=bar_count,
        )