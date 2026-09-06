"""RecommendationService -- Sprint 5 STEP 4 (LOCKED DECISION).

``RecommendationService`` is a pure adapter, nothing more: it turns
``RankingEngine.rank()``'s ``List[RankedSymbol]`` into a flat
``List[Recommendation]``, so a future Sprint can hand a
``Recommendation`` list to a display layer or the next STEP without
that consumer needing to know ``RankedSymbol``/``Business.ranking_engine``
exists at all.

Explicitly out of scope for this STEP (LOCKED DECISION): no sorting,
no filtering, no scoring, no re-ranking, no dedup, no grouping. Output
order is exactly input order -- whatever order ``RankingEngine.rank()``
already produced (itself exactly ``WatchlistScanner.scan()``'s
watchlist order). This service does not look at
``recommendation``/``confidence``/``priority``/``rank`` values to
decide anything; it only copies them across into a new
``Recommendation``.

Constructor (LOCKED): ``RecommendationService()`` -- no dependency
whatsoever. All data arrives through ``build_recommendations()``'s own
parameter.

Public API (LOCKED): exactly one public method,
``build_recommendations()``.

Knowledge boundary (LOCKED): this module imports only
``dataclasses.dataclass`` and ``typing``, plus
``Business.ranking_engine.RankedSymbol`` for the input type annotation
only (never constructed here). In particular it does NOT import
``Repository.persistence.watchlist_repository.WatchlistRepository``,
``Repository.persistence.snapshot_repository.SnapshotRepository``,
``Business.paper_trading_engine.PaperTradingEngine``,
``Orchestration.market_analysis_agent.MarketAnalysisAgent``, any
Skill, any Tool, any Pipeline, any ``Database.*`` module, or anything
portfolio-related. It never calls ``save()``/``load()``, never creates
or updates a snapshot, and never touches a portfolio.

Not wired to ``Core.composition_root`` (LOCKED DECISION): this STEP
adds no ``ApplicationGraph`` field and no ``_build_*`` function --
``RecommendationService`` is not a singleton and is not part of the
production object graph. A caller constructs
``RecommendationService()`` directly wherever it is needed.

Exception handling (LOCKED DECISION): no ``try``/``except`` anywhere
in this module, and no new exception type is defined. Malformed input
(e.g. a non-``RankedSymbol`` element) surfaces whatever ``AttributeError``/
``TypeError`` Python itself raises, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from Business.ranking_engine import RankedSymbol


@dataclass
class Recommendation:
    """One symbol's already-existing fields, copied out of a
    ``RankedSymbol`` into a plain value object.

    Exactly five fields (LOCKED) -- no score, no numeric confidence,
    no rating, no weighting field of any kind, mirroring
    ``RankedSymbol`` exactly.

    Attributes:
        symbol: The ticker this entry describes.
        recommendation: Copied verbatim from the source
            ``RankedSymbol.recommendation``.
        confidence: Copied verbatim from the source
            ``RankedSymbol.confidence``.
        priority: Copied verbatim from the source
            ``RankedSymbol.priority``.
        rank: Copied verbatim from the source ``RankedSymbol.rank``.
    """

    symbol: str
    recommendation: str
    confidence: str
    priority: int
    rank: int


class RecommendationService:
    """Normalizes a ``List[RankedSymbol]`` into a flat
    ``List[Recommendation]``.

    No state, no constructor argument, and no helper method beyond
    ``build_recommendations()`` itself -- the per-symbol read and the
    ``Recommendation`` construction both live directly inline inside
    ``build_recommendations()``, mirroring ``RankingEngine.rank()``'s
    own shape exactly.
    """

    def build_recommendations(
        self,
        ranked_symbols: List[RankedSymbol],
    ) -> List[Recommendation]:
        """Copy each ``RankedSymbol`` into a new ``Recommendation``.

        No sorting, filtering, scoring, re-ranking, dedup, or grouping
        of any kind is performed -- the returned list is in exactly
        ``ranked_symbols``'s own order. Each input ``RankedSymbol`` is
        read, never mutated; each output ``Recommendation`` is a
        distinct, newly constructed object.

        Args:
            ranked_symbols: The exact list
                ``RankingEngine.rank()`` returns (or any list of
                ``RankedSymbol``-shaped objects).

        Returns:
            A new ``list`` of newly constructed ``Recommendation``
            objects, one per element of ``ranked_symbols``, in the
            same order. Returns an empty list if ``ranked_symbols`` is
            empty.
        """
        return [
            Recommendation(
                symbol=ranked_symbol.symbol,
                recommendation=ranked_symbol.recommendation,
                confidence=ranked_symbol.confidence,
                priority=ranked_symbol.priority,
                rank=ranked_symbol.rank,
            )
            for ranked_symbol in ranked_symbols
        ]