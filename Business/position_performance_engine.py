from __future__ import annotations

from dataclasses import dataclass
from typing import List

from Database.models import Position


@dataclass
class PositionPerformanceStatistics:
    """Position-level profit/loss statistics computed over a
    ``List[Position]``.

    Sprint 6 STEP 3 scope: this is the ONE place in Sprint 6 that
    reads ``Position.realized_pnl``. Every downstream Sprint 6 engine
    (``WinRateEngine``, ``ExpectancyEngine``, ``ProfitFactorEngine``,
    ``DrawdownEngine``) must consume THIS dataclass -- never read
    ``Position`` (or ``Trade``) directly again.

    No field beyond the eight below may be added here.
    """

    winning_positions: int
    losing_positions: int
    breakeven_positions: int
    gross_profit: float
    gross_loss: float
    net_profit: float
    average_win: float
    average_loss: float


class PositionPerformanceEngine:
    """Computes :class:`PositionPerformanceStatistics` from a
    ``List[Position]``.

    Pure business object -- no dependency, no repository, no
    database, no composition-root wiring (mirrors
    ``Business.trade_statistics_engine.TradeStatisticsEngine``/
    ``Business.ranking_engine.RankingEngine``: constructed directly by
    whatever future STEP needs it, never exposed on
    ``ApplicationGraph``).

    Reads only ``Position.realized_pnl`` -- the single field already
    established by Sprint 4 (see ``Database.models.Position``). Never
    reads ``Trade``, ``Account``, ``RankingSnapshot``, any repository,
    or the database directly -- the caller is responsible for having
    already fetched the ``List[Position]`` (e.g. via
    ``Repository.persistence.performance_repository.
    PerformanceRepository.get_all_positions``).

    Performs no sorting, filtering by ``status``, grouping, SQL,
    pandas, numpy, formatting, or rounding -- a single plain loop over
    the list as given.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(self, positions: List[Position]) -> PositionPerformanceStatistics:
        """Compute position-level profit/loss statistics over
        ``positions``.

        Does not mutate ``positions`` or any element within it.

        Args:
            positions: The positions to summarize, in the order
                given -- this method performs no sorting/filtering/
                grouping.

        Returns:
            A :class:`PositionPerformanceStatistics`. On an empty
            list, every count is ``0`` and every monetary/average
            field is ``0.0``.
        """
        winning_positions = 0
        losing_positions = 0
        breakeven_positions = 0
        gross_profit = 0.0
        gross_loss = 0.0

        for position in positions:
            realized_pnl = position.realized_pnl
            if realized_pnl > 0:
                winning_positions += 1
                gross_profit += realized_pnl
            elif realized_pnl < 0:
                losing_positions += 1
                gross_loss += abs(realized_pnl)
            else:
                breakeven_positions += 1

        net_profit = gross_profit - gross_loss
        average_win = gross_profit / winning_positions if winning_positions > 0 else 0.0
        average_loss = gross_loss / losing_positions if losing_positions > 0 else 0.0

        return PositionPerformanceStatistics(
            winning_positions=winning_positions,
            losing_positions=losing_positions,
            breakeven_positions=breakeven_positions,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_profit=net_profit,
            average_win=average_win,
            average_loss=average_loss,
        )