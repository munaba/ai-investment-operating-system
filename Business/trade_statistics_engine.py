from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from Database.models import Trade


@dataclass
class TradeExecutionStatistics:
    """Pure execution statistics computed over a ``List[Trade]``.

    Sprint 6 STEP 2 scope: EXECUTION STATISTICS ONLY -- volume, fee,
    tax, and timing facts that are directly readable off ``Trade``
    itself. Deliberately excludes anything derived from profit/loss
    (``realized_pnl`` does not exist on ``Trade`` -- see Sprint 6
    STEP 2 STOP-rule discussion), such as win rate, expectancy,
    average win/loss, profit factor, or drawdown. Those are reserved
    for a later STEP once a genuine realized-P/L source is available.

    No field beyond the ten below may be added here.
    """

    total_trades: int
    buy_trades: int
    sell_trades: int
    total_volume: float
    total_fees: float
    total_tax: float
    first_trade_time: Optional[str]
    last_trade_time: Optional[str]


class TradeStatisticsEngine:
    """Computes :class:`TradeExecutionStatistics` from a ``List[Trade]``.

    Pure business object -- no dependency, no repository, no database,
    no composition-root wiring (mirrors ``Business.ranking_engine.
    RankingEngine``/``Business.recommendation_service.
    RecommendationService``/``Business.report_service.ReportService``:
    constructed directly by whatever future STEP needs it, never
    exposed on ``ApplicationGraph``).

    Reads only ``Trade`` fields that already exist as of Sprint 4
    STEP 4 (``action``, ``quantity``, ``fee``, ``tax``,
    ``executed_at``). Never reads ``Position``, ``Account``,
    ``RankingSnapshot``, any repository, or the database directly --
    the caller is responsible for having already fetched the
    ``List[Trade]`` (e.g. via ``Repository.persistence.
    performance_repository.PerformanceRepository.get_all_trades``).

    Performs no sorting, filtering, grouping, SQL, pandas, or numpy --
    a single plain loop over the list as given. ``first_trade_time``/
    ``last_trade_time`` are therefore the first/last element's
    ``executed_at`` *in the order the list was received*, not
    chronologically sorted -- ordering, if any is required, is the
    caller's responsibility (e.g. ``PerformanceRepository.
    get_all_trades`` already returns trades ordered by
    ``executed_at`` ascending).
    """

    def __init__(self) -> None:
        """No dependency of any kind."""

    def calculate(self, trades: List[Trade]) -> TradeExecutionStatistics:
        """Compute execution statistics over ``trades``.

        Does not mutate ``trades`` or any element within it.

        Args:
            trades: The trades to summarize, in the order the caller
                wants ``first_trade_time``/``last_trade_time`` derived
                from (this method does not sort them).

        Returns:
            A :class:`TradeExecutionStatistics` with every numeric
            field ``0`` and both timestamp fields ``None`` if
            ``trades`` is empty.
        """
        total_trades = 0
        buy_trades = 0
        sell_trades = 0
        total_volume = 0.0
        total_fees = 0.0
        total_tax = 0.0
        first_trade_time: Optional[str] = None
        last_trade_time: Optional[str] = None

        for trade in trades:
            total_trades += 1
            if trade.action == "BUY":
                buy_trades += 1
            elif trade.action == "SELL":
                sell_trades += 1
            total_volume += trade.quantity
            total_fees += trade.fee
            total_tax += trade.tax
            if first_trade_time is None:
                first_trade_time = trade.executed_at
            last_trade_time = trade.executed_at

        return TradeExecutionStatistics(
            total_trades=total_trades,
            buy_trades=buy_trades,
            sell_trades=sell_trades,
            total_volume=total_volume,
            total_fees=total_fees,
            total_tax=total_tax,
            first_trade_time=first_trade_time,
            last_trade_time=last_trade_time,
        )