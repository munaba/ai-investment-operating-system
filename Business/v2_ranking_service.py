"""Runs the v2 ranking for one market and stores it.

``python main.py v2 rank --market idx|us`` calls :meth:`V2RankingService.run`.
It fetches about five years of daily prices, keeps only sessions completed
before ``as_of`` (a bar dated ``as_of`` or later is a live quote), ranks the
universe with :func:`Business.factor_model.rank_universe`, and stores the
whole ranking.

Rebalance rule (pre-registered): the first stored ranking of a market is a
rebalance; afterwards a signal date is a rebalance when at least ``HOLD``
completed sessions have passed since the previous rebalance signal date.
Only rebalance dates produce picks (``picked = 1``) and a notification.
Re-running for a signal date that is already stored changes nothing and
sends nothing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from Business.factor_model import (
    HOLD,
    MIN_HISTORY,
    MODEL_VERSION,
    TOP_K,
    Market,
    history_window,
    rank_universe,
    yahoo_panel,
)
from Repository.persistence.v2_ranking_repository import V2RankingRepository

PanelFetcher = Callable[[Market, date, date], tuple[pd.DataFrame, pd.DataFrame]]
#: Refuse to rank when fewer stocks than this have a full year of history.
MIN_RANKED = 20


@dataclass(frozen=True)
class V2RunResult:
    market: str
    signal_date: str
    ranked: int
    is_rebalance: bool
    picks: list[str]
    top: list[tuple[str, float]]
    already_stored: bool
    sessions_since_rebalance: int | None


class V2RankingService:
    def __init__(self, repository: V2RankingRepository, fetch: PanelFetcher = yahoo_panel,
                 hold: int = HOLD, top_k: int = TOP_K) -> None:
        self._repo = repository
        self._fetch = fetch
        self._hold = hold
        self._top_k = top_k

    def run(self, market: Market, as_of: date, now: datetime) -> V2RunResult:
        start, end = history_window(as_of)
        close, volume = self._fetch(market, start, end)
        if close.empty:
            raise RuntimeError(f"no prices returned for market {market.name}")
        keep = close.index.date < as_of
        close, volume = close[keep], volume.reindex(close.index)[keep]
        if len(close.index) <= MIN_HISTORY:
            raise RuntimeError(f"only {len(close.index)} completed sessions; need more than {MIN_HISTORY}")

        ranking = rank_universe(market, close, volume, self._hold)
        if len(ranking.scores) < MIN_RANKED:
            raise RuntimeError(f"only {len(ranking.scores)} stocks have a full year of history")
        signal_date = ranking.signal_date.isoformat()
        top = [(s, float(v)) for s, v in ranking.scores.head(10).items()]

        existing = self._repo.get_ranking(market.name, signal_date)
        if existing:
            rebalance = existing[0].is_rebalance
            return V2RunResult(market.name, signal_date, len(existing), rebalance,
                               self._repo.picks_on(market.name, signal_date), top, True, None)

        previous = self._repo.last_rebalance_date(market.name, before=signal_date)
        if previous is None:
            sessions, rebalance = None, True
        else:
            sessions = int((close.index.date > date.fromisoformat(previous)).sum())
            rebalance = sessions >= self._hold
        picks = ranking.picks(self._top_k) if rebalance else []

        self._repo.save_ranking(
            market=market.name,
            signal_date=signal_date,
            scores=[(s, float(v)) for s, v in ranking.scores.items()],
            picks=picks,
            is_rebalance=rebalance,
            model_version=MODEL_VERSION,
            weights=ranking.weights,
            created_at=now.isoformat(),
        )
        return V2RunResult(market.name, signal_date, len(ranking.scores), rebalance, picks, top, False, sessions)
