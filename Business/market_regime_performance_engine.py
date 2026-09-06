"""MarketRegimePerformanceEngine -- ACTIVATION 7 (performance per
market regime).

Aggregates ``Position.realized_pnl`` per market-regime label, over a
list of already-resolved closed-episode outcomes -- field-for-field
mirror of ``Business.strategy_performance_engine.
StrategyPerformanceEngine``, just grouped by regime instead of
strategy. No new formula: the win/loss/breakeven/gross/net/average
computation is byte-for-byte the same shape already established for
performance-per-strategy.

Never reads ``Position``, ``Trade``, ``Order``, any repository, or the
database -- every input is already resolved by the caller (see
``Business.market_regime_attribution_service.
MarketRegimeAttributionService``, the sole production caller, which is
also the one place the ``regime`` label itself is derived).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class EpisodeRegimeOutcome:
    """One closed position episode's market-regime label and P/L.

    Attributes:
        regime: ``"trending"``, ``"ranging"``, ``"volatile"``, or
            ``"insufficient_data"`` -- already resolved by the
            caller. ``"insufficient_data"`` is a real, honest label
            (not a fabricated regime) meaning real OHLCV history was
            not available/sufficient to classify this episode's
            opening moment -- it is counted and reported like any
            other group, never silently dropped.
        realized_pnl: The closed episode's ``Position.realized_pnl``,
            verbatim -- already resolved by the caller.
    """

    regime: str
    realized_pnl: float


@dataclass
class MarketRegimePerformanceStatistics:
    """Performance statistics for one ``regime`` label, aggregated
    over every closed episode carrying that label.

    Mirrors ``Business.strategy_performance_engine.
    StrategyPerformanceStatistics`` field-for-field (with ``regime``
    replacing ``strategy``) -- no additional metric beyond that.
    """

    regime: str
    closed_episodes: int
    winning_episodes: int
    losing_episodes: int
    breakeven_episodes: int
    gross_profit: float
    gross_loss: float
    net_profit: float
    average_win: float
    average_loss: float


class MarketRegimePerformanceEngine:
    """Computes one :class:`MarketRegimePerformanceStatistics` per
    distinct ``regime`` label from a ``List[EpisodeRegimeOutcome]``.

    Pure business object -- no dependency, no repository, no
    database. Performs no sorting/filtering/grouping across accounts
    or symbols -- a single plain loop over the list as given, grouped
    only by the already-resolved ``regime`` label each outcome
    carries. Structurally identical to
    ``Business.strategy_performance_engine.StrategyPerformanceEngine.
    calculate`` -- kept as a separate, small class rather than a
    shared/generic base, mirroring this codebase's existing
    convention of small, explicit, mirrored engines over premature
    abstraction (see e.g. ``PositionPerformanceEngine``/
    ``StrategyPerformanceEngine`` themselves).
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(
        self, outcomes: List[EpisodeRegimeOutcome]
    ) -> Dict[str, MarketRegimePerformanceStatistics]:
        """Aggregate ``outcomes`` into one
        :class:`MarketRegimePerformanceStatistics` per distinct
        ``regime`` label.

        Does not mutate ``outcomes`` or any element within it.

        Args:
            outcomes: One :class:`EpisodeRegimeOutcome` per closed
                position episode, in the order given -- this method
                performs no sorting/filtering.

        Returns:
            A ``dict`` mapping every distinct ``regime`` label
            observed in ``outcomes`` to its
            :class:`MarketRegimePerformanceStatistics`. Empty ``dict``
            for an empty ``outcomes`` list.
        """
        grouped: Dict[str, List[float]] = {}
        for outcome in outcomes:
            grouped.setdefault(outcome.regime, []).append(outcome.realized_pnl)

        result: Dict[str, MarketRegimePerformanceStatistics] = {}
        for regime, pnls in grouped.items():
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

            result[regime] = MarketRegimePerformanceStatistics(
                regime=regime,
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