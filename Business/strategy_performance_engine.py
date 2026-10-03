"""StrategyPerformanceEngine -- ACTIVATION 7 (performance per strategy).

Aggregates ``Position.realized_pnl`` -- the single, already-existing
episode P/L field ("Gunakan Position.realized_pnl sebagai P/L episode
yang sudah existing") -- per strategy label, over a list of already-
resolved closed-episode outcomes.

This engine performs ONLY performance aggregation per strategy -- no
market regime, no other metric beyond the counts/gross/net/average
fields ``Business.position_performance_engine.PositionPerformanceEngine``
already establishes for the whole-account case (this engine mirrors
that exact set of fields, just grouped by strategy instead of summed
over every position).

Never reads ``Position``, ``Trade``, ``Order``, any repository, or the
database -- every input is already resolved by the caller (see
``Business.strategy_performance_service.StrategyPerformanceService``,
the sole production caller, which is also the one place the
``strategy`` label itself -- ``"recommendation_following"`` /
``"manual"`` / ``"mixed"`` -- is derived).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class EpisodeStrategyOutcome:
    """One closed position episode's strategy label and P/L.

    Plain data-in, no ``Trade``/``Order``/``Position`` reference of
    any kind -- keeps this engine a pure ``str``/``float`` aggregator,
    mirroring ``Business.profit_factor_engine.ProfitFactorEngine``'s
    own minimal-input style.

    Attributes:
        strategy: ``"recommendation_following"``, ``"manual"``, or
            ``"mixed"`` -- already resolved by the caller.
        realized_pnl: The closed episode's ``Position.realized_pnl``,
            verbatim -- already resolved by the caller.
    """

    strategy: str
    realized_pnl: float


@dataclass
class StrategyPerformanceStatistics:
    """Performance statistics for one ``strategy`` label, aggregated
    over every closed episode carrying that label.

    Mirrors ``Business.position_performance_engine.
    PositionPerformanceStatistics`` field-for-field, plus ``strategy``
    and ``closed_episodes`` for traceability back to the group this
    row describes -- no additional metric beyond that.
    """

    strategy: str
    closed_episodes: int
    winning_episodes: int
    losing_episodes: int
    breakeven_episodes: int
    gross_profit: float
    gross_loss: float
    net_profit: float
    average_win: float
    average_loss: float


class StrategyPerformanceEngine:
    """Computes one :class:`StrategyPerformanceStatistics` per
    distinct ``strategy`` label from a ``List[EpisodeStrategyOutcome]``.

    Pure business object -- no dependency, no repository, no
    database, no composition-root wiring beyond being constructed and
    handed to whatever caller assembles it (mirrors
    ``Business.position_performance_engine.PositionPerformanceEngine``).

    Performs no sorting, filtering, or grouping across accounts/
    symbols -- a single plain loop over the list as given, grouped
    only by the already-resolved ``strategy`` label each outcome
    carries.
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(
        self, outcomes: List[EpisodeStrategyOutcome]
    ) -> Dict[str, StrategyPerformanceStatistics]:
        """Aggregate ``outcomes`` into one
        :class:`StrategyPerformanceStatistics` per distinct
        ``strategy`` label.

        Does not mutate ``outcomes`` or any element within it.

        Args:
            outcomes: One :class:`EpisodeStrategyOutcome` per closed
                position episode, in the order given -- this method
                performs no sorting/filtering.

        Returns:
            A ``dict`` mapping every distinct ``strategy`` label
            observed in ``outcomes`` to its
            :class:`StrategyPerformanceStatistics`. Empty ``dict`` for
            an empty ``outcomes`` list.
        """
        grouped: Dict[str, List[float]] = {}
        for outcome in outcomes:
            grouped.setdefault(outcome.strategy, []).append(outcome.realized_pnl)

        result: Dict[str, StrategyPerformanceStatistics] = {}
        for strategy, pnls in grouped.items():
            winning_episodes = 0
            losing_episodes = 0
            breakeven_episodes = 0
            gross_profit = 0.0
            gross_loss = 0.0

            for realized_pnl in pnls:
                if realized_pnl > 0:
                    winning_episodes += 1
                    gross_profit += realized_pnl
                elif realized_pnl < 0:
                    losing_episodes += 1
                    gross_loss += abs(realized_pnl)
                else:
                    breakeven_episodes += 1

            net_profit = gross_profit - gross_loss
            average_win = gross_profit / winning_episodes if winning_episodes > 0 else 0.0
            average_loss = gross_loss / losing_episodes if losing_episodes > 0 else 0.0

            result[strategy] = StrategyPerformanceStatistics(
                strategy=strategy,
                closed_episodes=len(pnls),
                winning_episodes=winning_episodes,
                losing_episodes=losing_episodes,
                breakeven_episodes=breakeven_episodes,
                gross_profit=gross_profit,
                gross_loss=gross_loss,
                net_profit=net_profit,
                average_win=average_win,
                average_loss=average_loss,
            )

        return result