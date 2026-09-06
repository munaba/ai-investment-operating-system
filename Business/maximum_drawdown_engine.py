"""MaximumDrawdownEngine -- Sprint 6 STEP 6 (LOCKED DECISION).

Computes Maximum Drawdown (MDD) -- the single most important risk
metric in trading strategy evaluation -- from an already-built equity
curve. This engine never reads ``Position``, ``Trade``, any
repository, or the database; it never computes an equity curve, P/L,
or return itself. All of that is another STEP's responsibility.

LOCKED DECISION formula:

    peak starts at the first equity value

    for each equity point:
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak

    maximum_drawdown = the largest drawdown ever observed

Public API (LOCKED): exactly one public method, ``calculate()``,
taking a single ``List[float]`` equity curve (equity after each trade
completes -- not P/L, not return, not ``Position``, not ``Trade``) --
no second parameter.

Constructor (LOCKED): ``MaximumDrawdownEngine()`` -- no dependency,
mirrors every other Sprint 6 engine
(``Business.position_performance_engine.PositionPerformanceEngine``,
``Business.win_rate_engine.WinRateEngine``,
``Business.expectancy_engine.ExpectancyEngine``,
``Business.profit_factor_engine.ProfitFactorEngine``).

Edge cases (LOCKED):
    * empty ``equity_curve`` -> ``0.0``
    * a single equity point -> ``0.0``
    * a strictly non-decreasing equity curve -> ``0.0``

No pandas, no numpy, no SQL, no scipy -- a single plain Python loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class MaximumDrawdownResult:
    """The single value this STEP produces.

    Exactly one field (LOCKED) -- no peak, no trough, no timestamp,
    no breakdown of any kind.

    Attributes:
        maximum_drawdown: The largest ``(peak - equity) / peak``
            observed across the equity curve, as a ``float`` in
            ``[0.0, 1.0]``. ``0.0`` when the curve is empty, has a
            single point, or never dips below its running peak.
    """

    maximum_drawdown: float


class MaximumDrawdownEngine:
    """Computes :class:`MaximumDrawdownResult` from an equity curve.

    Pure business object -- no dependency, no repository, no
    database, no composition-root wiring (mirrors every other Sprint
    6 engine): constructed directly by whatever future STEP needs it,
    never exposed on ``ApplicationGraph``.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(self, equity_curve: List[float]) -> MaximumDrawdownResult:
        """Compute the maximum drawdown across ``equity_curve``.

        Does not mutate ``equity_curve``. Reads only the ``float``
        values given -- never reads ``Position``, ``Trade``, any
        repository, or the database, and never computes an equity
        curve, P/L, or return itself.

        Args:
            equity_curve: Equity after each trade completes, in
                chronological order (e.g. ``[10000.0, 10500.0,
                11000.0, 10800.0]``). Not P/L, not return, not
                ``Position``, not ``Trade``.

        Returns:
            A :class:`MaximumDrawdownResult` whose
            ``maximum_drawdown`` is the largest ``(peak - equity) /
            peak`` observed, where ``peak`` is the running maximum of
            ``equity_curve`` starting from its first value. ``0.0``
            when ``equity_curve`` is empty, has fewer than two
            points, or never dips below its running peak.
        """
        if len(equity_curve) < 2:
            return MaximumDrawdownResult(maximum_drawdown=0.0)

        peak = equity_curve[0]
        maximum_drawdown = 0.0

        for equity in equity_curve:
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak
            maximum_drawdown = max(maximum_drawdown, drawdown)

        return MaximumDrawdownResult(maximum_drawdown=maximum_drawdown)