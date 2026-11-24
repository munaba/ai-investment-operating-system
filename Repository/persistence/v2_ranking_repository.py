"""Persists v2 rankings (``v2_rankings``, migration version 35)."""
from __future__ import annotations

import json
from dataclasses import dataclass

from Repository.persistence.base_persistence_repository import BasePersistenceRepository


@dataclass(frozen=True)
class V2RankingRow:
    market: str
    signal_date: str
    symbol: str
    rank: int
    score: float
    is_rebalance: bool
    picked: bool
    model_version: str


class V2RankingRepository(BasePersistenceRepository):
    """One ranking per (market, signal date); a rerun for the same date
    replaces it atomically."""

    def save_ranking(
        self,
        *,
        market: str,
        signal_date: str,
        scores: list[tuple[str, float]],
        picks: list[str],
        is_rebalance: bool,
        model_version: str,
        weights: dict[str, float],
        created_at: str,
    ) -> None:
        weights_json = json.dumps(weights, sort_keys=True)
        picked = set(picks)
        rows = [
            (market, signal_date, symbol, rank, float(score), int(is_rebalance), int(symbol in picked),
             model_version, weights_json, created_at)
            for rank, (symbol, score) in enumerate(scores, start=1)
        ]
        with self._session() as session:
            session.execute("DELETE FROM v2_rankings WHERE market = ? AND signal_date = ?", (market, signal_date))
            session.executemany(
                """
                INSERT INTO v2_rankings
                    (market, signal_date, symbol, rank, score, is_rebalance, picked,
                     model_version, weights_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_ranking(self, market: str, signal_date: str) -> list[V2RankingRow]:
        result = self._execute(
            "SELECT * FROM v2_rankings WHERE market = ? AND signal_date = ? ORDER BY rank",
            (market, signal_date),
        )
        return [self._row(r) for r in result.rows]

    def last_rebalance_date(self, market: str, before: str | None = None) -> str | None:
        """Latest rebalance signal date, optionally strictly before ``before``."""
        sql = "SELECT MAX(signal_date) AS d FROM v2_rankings WHERE market = ? AND is_rebalance = 1"
        params: tuple = (market,)
        if before is not None:
            sql += " AND signal_date < ?"
            params = (market, before)
        result = self._execute(sql, params)
        return result.rows[0]["d"] if result.rows else None

    def picks_on(self, market: str, signal_date: str) -> list[str]:
        result = self._execute(
            "SELECT symbol FROM v2_rankings WHERE market = ? AND signal_date = ? AND picked = 1 ORDER BY rank",
            (market, signal_date),
        )
        return [r["symbol"] for r in result.rows]

    @staticmethod
    def _row(r) -> V2RankingRow:
        return V2RankingRow(
            market=r["market"], signal_date=r["signal_date"], symbol=r["symbol"], rank=int(r["rank"]),
            score=float(r["score"]), is_rebalance=bool(r["is_rebalance"]), picked=bool(r["picked"]),
            model_version=r["model_version"],
        )
