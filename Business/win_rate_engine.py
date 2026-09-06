"""WinRateEngine -- Sprint 6 STEP 4 (LOCKED DECISION).

Computes a single ``win_rate`` float from an already-computed
``Business.position_performance_engine.PositionPerformanceStatistics``
(STEP 3). This is the ONE place in Sprint 6 that computes
``total_closed_positions`` and ``win_rate`` -- it never reads
``Position``, ``Trade``, or any repository/database directly.

LOCKED DECISION 5 STEP 4 formula:

    win_rate = winning_positions / total_closed_positions

``total_closed_positions`` is not a field on
``PositionPerformanceStatistics`` (LOCKED DECISION 2 STEP 3 froze that
dataclass at exactly eight fields -- see position_performance_engine.py).
Per the confirmed Option A, ``total_closed_positions`` is a local,
intermediate value computed inline inside ``calculate()`` from the
three already-existing count fields:

    total_closed_positions = (
        statistics.winning_positions
        + statistics.losing_positions
        + statistics.breakeven_positions
    )

It is not a dataclass field anywhere, not persisted, and not part of
any public contract -- purely a local variable used once to compute
``win_rate``.

Public API (LOCKED): exactly one public method, ``calculate()``,
taking the single ``PositionPerformanceStatistics`` produced by STEP 3
-- no second parameter for ``total_closed_positions`` or any other
value (that would reopen LOCKED DECISION 4's single-argument
``calculate(statistics: PositionPerformanceStatistics)`` contract).

Constructor (LOCKED): ``WinRateEngine()`` -- no dependency, mirrors
``Business.position_performance_engine.PositionPerformanceEngine``.

Zero-division guard: when ``total_closed_positions`` is ``0`` (i.e.
``statistics`` was built from an empty/degenerate position list),
``win_rate`` is ``0.0`` -- never a ``ZeroDivisionError``.
"""

from __future__ import annotations

from Business.position_performance_engine import PositionPerformanceStatistics


class WinRateEngine:
    """Computes ``win_rate`` from a
    :class:`~Business.position_performance_engine.PositionPerformanceStatistics`.

    Pure business object -- no dependency, no repository, no
    database, no composition-root wiring (mirrors
    ``Business.position_performance_engine.PositionPerformanceEngine``):
    constructed directly by whatever future STEP needs it, never
    exposed on ``ApplicationGraph``.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(self, statistics: PositionPerformanceStatistics) -> float:
        """Compute the win rate from already-computed position
        performance statistics.

        Args:
            statistics: The :class:`PositionPerformanceStatistics`
                produced by
                ``Business.position_performance_engine.PositionPerformanceEngine.calculate()``.
                Read only, never mutated.

        Returns:
            ``winning_positions / total_closed_positions`` as a
            ``float``, where ``total_closed_positions`` is
            ``winning_positions + losing_positions +
            breakeven_positions`` computed locally. ``0.0`` when
            ``total_closed_positions`` is ``0``.
        """
        total_closed_positions = (
            statistics.winning_positions
            + statistics.losing_positions
            + statistics.breakeven_positions
        )

        if total_closed_positions == 0:
            return 0.0

        return statistics.winning_positions / total_closed_positions