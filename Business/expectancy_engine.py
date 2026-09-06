"""ExpectancyEngine -- Sprint 6 STEP 5 (LOCKED DECISION).

Computes a single ``expectancy`` float from an already-computed
``Business.position_performance_engine.PositionPerformanceStatistics``
(STEP 3). This is the ONE place in Sprint 6 that computes
``win_rate``/``loss_rate``/``expectancy`` for this STEP -- it never
reads ``Position``, ``Trade``, or any repository/database directly,
and it never recomputes ``average_win``/``average_loss``/
``gross_profit``/``gross_loss`` (all already produced by STEP 3).

LOCKED DECISION formula:

    total_closed_positions = (
        statistics.winning_positions
        + statistics.losing_positions
        + statistics.breakeven_positions
    )

    win_rate = statistics.winning_positions / total_closed_positions
    loss_rate = statistics.losing_positions / total_closed_positions

    expectancy = (
        (win_rate * statistics.average_win)
        - (loss_rate * statistics.average_loss)
    )

Breakeven positions contribute no profit or loss themselves, but are
still counted in ``total_closed_positions`` and therefore dilute both
``win_rate`` and ``loss_rate``.

``total_closed_positions``, ``win_rate``, and ``loss_rate`` are local,
intermediate values computed inline inside ``calculate()`` -- none of
them is a dataclass field anywhere, persisted, or part of any public
contract. Only ``expectancy`` is returned, wrapped in
``ExpectancyResult``.

Public API (LOCKED): exactly one public method, ``calculate()``,
taking the single ``PositionPerformanceStatistics`` produced by STEP 3
-- no second parameter.

Constructor (LOCKED): ``ExpectancyEngine()`` -- no dependency, mirrors
``Business.position_performance_engine.PositionPerformanceEngine`` and
``Business.win_rate_engine.WinRateEngine``.

Zero-division guard: when ``total_closed_positions`` is ``0`` (i.e.
``statistics`` was built from an empty/degenerate position list),
``expectancy`` is ``0.0`` -- never a ``ZeroDivisionError``.
"""

from __future__ import annotations

from dataclasses import dataclass

from Business.position_performance_engine import PositionPerformanceStatistics


@dataclass
class ExpectancyResult:
    """The single value this STEP produces.

    Exactly one field (LOCKED) -- no ``win_rate``, no ``loss_rate``,
    no ``total_closed_positions``, no breakdown of any kind.

    Attributes:
        expectancy: The expected profit/loss per closed position, per
            the LOCKED DECISION formula above. ``0.0`` when there are
            no closed positions.
    """

    expectancy: float


class ExpectancyEngine:
    """Computes :class:`ExpectancyResult` from a
    :class:`~Business.position_performance_engine.PositionPerformanceStatistics`.

    Pure business object -- no dependency, no repository, no
    database, no composition-root wiring (mirrors
    ``Business.position_performance_engine.PositionPerformanceEngine``
    and ``Business.win_rate_engine.WinRateEngine``): constructed
    directly by whatever future STEP needs it, never exposed on
    ``ApplicationGraph``.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(
        self, statistics: PositionPerformanceStatistics
    ) -> ExpectancyResult:
        """Compute the expectancy from already-computed position
        performance statistics.

        Does not mutate ``statistics``. Reads only
        ``winning_positions``, ``losing_positions``,
        ``breakeven_positions``, ``average_win``, and
        ``average_loss`` -- never recomputes ``average_win``,
        ``average_loss``, ``gross_profit``, or ``gross_loss``, and
        never reads ``Position`` or any repository.

        Args:
            statistics: The :class:`PositionPerformanceStatistics`
                produced by
                ``Business.position_performance_engine.PositionPerformanceEngine.calculate()``.
                Read only, never mutated.

        Returns:
            An :class:`ExpectancyResult` whose ``expectancy`` is
            ``(win_rate * average_win) - (loss_rate * average_loss)``,
            where ``win_rate``/``loss_rate`` are computed locally
            against ``total_closed_positions`` (``winning_positions +
            losing_positions + breakeven_positions``). ``0.0`` when
            ``total_closed_positions`` is ``0``.
        """
        total_closed_positions = (
            statistics.winning_positions
            + statistics.losing_positions
            + statistics.breakeven_positions
        )

        if total_closed_positions == 0:
            return ExpectancyResult(expectancy=0.0)

        win_rate = statistics.winning_positions / total_closed_positions
        loss_rate = statistics.losing_positions / total_closed_positions

        expectancy = (win_rate * statistics.average_win) - (
            loss_rate * statistics.average_loss
        )

        return ExpectancyResult(expectancy=expectancy)