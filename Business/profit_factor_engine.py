"""ProfitFactorEngine -- Sprint 6 STEP 5 (LOCKED DECISION).

Computes a single ``profit_factor`` float from an already-computed
``Business.position_performance_engine.PositionPerformanceStatistics``
(STEP 3). Profit Factor is a standard trading-strategy evaluation
metric. This engine never reads ``Position``, ``Trade``, or any
repository/database directly, and never recomputes
``gross_profit``/``gross_loss`` (both already produced by STEP 3).

LOCKED DECISION formula:

    profit_factor = gross_profit / gross_loss

Public API (LOCKED): exactly one public method, ``calculate()``,
taking the single ``PositionPerformanceStatistics`` produced by STEP 3
-- no second parameter.

Constructor (LOCKED): ``ProfitFactorEngine()`` -- no dependency,
mirrors ``Business.position_performance_engine.PositionPerformanceEngine``,
``Business.win_rate_engine.WinRateEngine``, and
``Business.expectancy_engine.ExpectancyEngine``.

Zero-division guard: when ``gross_loss`` is ``0``, ``profit_factor``
is ``0.0`` -- never ``inf``, ``-inf``, ``NaN``, or ``None``.

Explicitly out of scope for this engine (LOCKED DECISION): it does
not compute expectancy, win rate, drawdown, pnl, average_win, or
average_loss -- each of those is another engine's responsibility. It
uses no pandas, no numpy, no SQL, no repository, and performs no
mutation -- pure calculation only.
"""

from __future__ import annotations

from dataclasses import dataclass

from Business.position_performance_engine import PositionPerformanceStatistics


@dataclass
class ProfitFactorResult:
    """The single value this STEP produces.

    Exactly one field (LOCKED) -- no ``gross_profit``, no
    ``gross_loss``, no breakdown of any kind.

    Attributes:
        profit_factor: ``gross_profit / gross_loss``, per the LOCKED
            DECISION formula above. ``0.0`` when ``gross_loss`` is
            ``0`` -- never ``inf``/``-inf``/``NaN``/``None``.
    """

    profit_factor: float


class ProfitFactorEngine:
    """Computes :class:`ProfitFactorResult` from a
    :class:`~Business.position_performance_engine.PositionPerformanceStatistics`.

    Pure business object -- no dependency, no repository, no
    database, no composition-root wiring (mirrors
    ``Business.position_performance_engine.PositionPerformanceEngine``,
    ``Business.win_rate_engine.WinRateEngine``, and
    ``Business.expectancy_engine.ExpectancyEngine``): constructed
    directly by whatever future STEP needs it, never exposed on
    ``ApplicationGraph``.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(
        self, statistics: PositionPerformanceStatistics
    ) -> ProfitFactorResult:
        """Compute the profit factor from already-computed position
        performance statistics.

        Does not mutate ``statistics``. Reads only ``gross_profit``
        and ``gross_loss`` -- never ``net_profit``, ``average_win``,
        ``average_loss``, ``winning_positions``, ``losing_positions``,
        or ``breakeven_positions``, and never reads ``Position`` or
        any repository.

        Args:
            statistics: The :class:`PositionPerformanceStatistics`
                produced by
                ``Business.position_performance_engine.PositionPerformanceEngine.calculate()``.
                Read only, never mutated.

        Returns:
            A :class:`ProfitFactorResult` whose ``profit_factor`` is
            ``statistics.gross_profit / statistics.gross_loss``.
            ``0.0`` when ``statistics.gross_loss`` is ``0`` --
            regardless of ``gross_profit`` -- never ``inf``,
            ``-inf``, ``NaN``, or ``None``.
        """
        if statistics.gross_loss == 0:
            return ProfitFactorResult(profit_factor=0.0)

        return ProfitFactorResult(
            profit_factor=statistics.gross_profit / statistics.gross_loss
        )