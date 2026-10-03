"""PerformanceSummaryService -- Sprint 6 STEP 7 (LOCKED DECISION).

Closes out Sprint 6 by orchestrating the six engines built across
STEP 2-6 into a single :class:`PerformanceSummary`. This service
computes NO metric itself -- it only calls each engine, in the
LOCKED order below, and assembles their outputs verbatim.

LOCKED call order:

    1. TradeStatisticsEngine.calculate(trades)
       -> TradeExecutionStatistics
    2. PositionPerformanceEngine.calculate(positions)
       -> PositionPerformanceStatistics
    3. WinRateEngine.calculate(position_statistics)
       -> float
    4. ExpectancyEngine.calculate(position_statistics)
       -> ExpectancyResult
    5. ProfitFactorEngine.calculate(position_statistics)
       -> ProfitFactorResult
    6. MaximumDrawdownEngine.calculate(equity_curve)
       -> MaximumDrawdownResult

Every engine result is placed into :class:`PerformanceSummary`
exactly as returned -- no transformation, no normalization, no
additional calculation of any kind.

Not wired into ``composition_root.py``, ``ManualScanService``, any
Report, Dashboard, or AI component in this STEP -- wiring is deferred
to a future Sprint (LOCKED DECISION 12).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from Business.expectancy_engine import ExpectancyEngine, ExpectancyResult
from Business.maximum_drawdown_engine import (
    MaximumDrawdownEngine,
    MaximumDrawdownResult,
)
from Business.position_performance_engine import (
    PositionPerformanceEngine,
    PositionPerformanceStatistics,
)
from Business.profit_factor_engine import ProfitFactorEngine, ProfitFactorResult
from Business.trade_statistics_engine import (
    TradeExecutionStatistics,
    TradeStatisticsEngine,
)
from Business.win_rate_engine import WinRateEngine
from Database.models import Position, Trade


@dataclass
class PerformanceSummary:
    """The full Sprint 6 performance picture, assembled verbatim from
    the six engines' own results.

    Exactly six fields (LOCKED) -- no additional metric, no derived
    field, no re-computation of any kind.

    Attributes:
        trade_statistics: Exactly the ``TradeExecutionStatistics``
            returned by ``TradeStatisticsEngine.calculate(trades)``.
        position_statistics: Exactly the
            ``PositionPerformanceStatistics`` returned by
            ``PositionPerformanceEngine.calculate(positions)``.
        win_rate: Exactly the ``float`` returned by
            ``WinRateEngine.calculate(position_statistics)``.
        expectancy: Exactly the ``ExpectancyResult`` returned by
            ``ExpectancyEngine.calculate(position_statistics)``.
        profit_factor: Exactly the ``ProfitFactorResult`` returned by
            ``ProfitFactorEngine.calculate(position_statistics)``.
        maximum_drawdown: Exactly the ``MaximumDrawdownResult``
            returned by
            ``MaximumDrawdownEngine.calculate(equity_curve)``.
    """

    trade_statistics: TradeExecutionStatistics
    position_statistics: PositionPerformanceStatistics
    win_rate: float
    expectancy: ExpectancyResult
    profit_factor: ProfitFactorResult
    maximum_drawdown: MaximumDrawdownResult


class PerformanceSummaryService:
    """Orchestrates the six Sprint 6 engines into a
    :class:`PerformanceSummary`.

    Computes no metric itself -- ``win_rate``, ``expectancy``,
    ``profit_factor``, ``maximum_drawdown``, ``pnl``,
    ``trade_statistics``, and ``position_statistics`` all come from
    their respective engine. Reads no ``Repository``,
    ``PerformanceRepository``, or database of any kind -- all data
    arrives through ``build()``'s own parameters. No pandas, no
    numpy, no SQL, no mutation.

    Constructor (LOCKED): exactly six dependencies -- one instance of
    each of the six Sprint 6 engines. No other dependency.
    """

    def __init__(
        self,
        trade_statistics_engine: TradeStatisticsEngine,
        position_performance_engine: PositionPerformanceEngine,
        win_rate_engine: WinRateEngine,
        expectancy_engine: ExpectancyEngine,
        profit_factor_engine: ProfitFactorEngine,
        maximum_drawdown_engine: MaximumDrawdownEngine,
    ) -> None:
        """Stores the six injected engines. No other dependency."""
        self._trade_statistics_engine = trade_statistics_engine
        self._position_performance_engine = position_performance_engine
        self._win_rate_engine = win_rate_engine
        self._expectancy_engine = expectancy_engine
        self._profit_factor_engine = profit_factor_engine
        self._maximum_drawdown_engine = maximum_drawdown_engine

    def build(
        self,
        trades: List[Trade],
        positions: List[Position],
        equity_curve: List[float],
    ) -> PerformanceSummary:
        """Assemble a :class:`PerformanceSummary` by calling each of
        the six engines exactly once, in the LOCKED order.

        Does not mutate ``trades``, ``positions``, or
        ``equity_curve``. Performs no transformation, normalization,
        or additional calculation on any engine's output -- every
        field of the returned :class:`PerformanceSummary` is exactly
        the object each engine returned.

        Args:
            trades: Passed unchanged to
                ``TradeStatisticsEngine.calculate()``.
            positions: Passed unchanged to
                ``PositionPerformanceEngine.calculate()``.
            equity_curve: Passed unchanged to
                ``MaximumDrawdownEngine.calculate()``.

        Returns:
            A :class:`PerformanceSummary` whose six fields are
            exactly the six engines' own return values.
        """
        trade_statistics = self._trade_statistics_engine.calculate(trades)
        position_statistics = self._position_performance_engine.calculate(
            positions
        )
        win_rate = self._win_rate_engine.calculate(position_statistics)
        expectancy = self._expectancy_engine.calculate(position_statistics)
        profit_factor = self._profit_factor_engine.calculate(
            position_statistics
        )
        maximum_drawdown = self._maximum_drawdown_engine.calculate(
            equity_curve
        )

        return PerformanceSummary(
            trade_statistics=trade_statistics,
            position_statistics=position_statistics,
            win_rate=win_rate,
            expectancy=expectancy,
            profit_factor=profit_factor,
            maximum_drawdown=maximum_drawdown,
        )