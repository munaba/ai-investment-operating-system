"""ManualScanService -- Sprint 5 STEP 6 (LOCKED DECISION).

``ManualScanService`` is a pure orchestrator, nothing more: it wires
together the five already-completed Sprint 5 pipeline stages --
``Orchestration.watchlist_scanner.WatchlistScanner``,
``Business.ranking_engine.RankingEngine``,
``Business.recommendation_service.RecommendationService``,
``Business.report_service.ReportService``, and
``Repository.persistence.snapshot_repository.SnapshotRepository`` --
into one stable "manual scan" call.

    WatchlistRepository
            |
            v
    WatchlistScanner
            |
            v
    RankingEngine
            |
            v
    RecommendationService
            |
            v
    ReportService
            |
            v
        Report

Explicitly out of scope for this STEP (LOCKED DECISION): no CLI, no
scheduler, no export, no additional database write beyond
``SnapshotRepository.create()``, no snapshot beyond that same call, no
Telegram, no Discord, no PDF, no Excel, no new sorting/ranking/
filtering/scoring, no retry, no exception wrapping, no transaction, no
logging, and no direct call to any Repository other than
``SnapshotRepository`` (in particular, never
``Repository.persistence.watchlist_repository.WatchlistRepository``
directly -- ``WatchlistScanner`` already owns that).

Constructor (LOCKED): exactly five dependencies --
``WatchlistScanner``, ``RankingEngine``, ``RecommendationService``,
``ReportService``, ``SnapshotRepository`` -- no other dependency of
any kind.

Public API (LOCKED): exactly one public method, ``run_scan()``.

``generated_at`` is a required, caller-supplied value -- this service
does not generate a timestamp itself (no ``datetime.now()`` or
equivalent anywhere in this module), mirroring
``Business.report_service.ReportService.build_report()``'s own
``generated_at`` contract exactly.

Pipeline order (LOCKED DECISION 4): must run in exactly this order --
``WatchlistScanner.scan()`` -> ``RankingEngine.rank()`` ->
``RecommendationService.build_recommendations()`` ->
``ReportService.build_report()`` -> one
``SnapshotRepository.create()`` call per ``Recommendation`` -> return
the ``Report``. This order is never reshuffled, and no step is
skipped or repeated.

Snapshot persistence (LOCKED DECISION 5): for every ``Recommendation``
in the built report -- one at a time, no batching, no bulk insert --
``SnapshotRepository.create()`` is called with ``scan_time`` set to
this call's own ``generated_at`` (never a new timestamp), and
``symbol``/``recommendation``/``confidence``/``priority``/``rank``
copied verbatim from that ``Recommendation``. One ``Recommendation``
always yields exactly one snapshot row.

Return value (LOCKED DECISION 6): the exact ``Report``
``ReportService.build_report()`` returned -- the same object, never
rebuilt, re-copied, or wrapped.

Exception handling (LOCKED DECISION 7): no ``try``/``except``
anywhere in this module, and no new exception type is defined. Any
exception any of the five collaborators raises propagates unchanged.

Knowledge boundary: this module imports only ``typing``, plus
``Orchestration.watchlist_scanner.WatchlistScanner``,
``Business.ranking_engine.RankingEngine``,
``Business.recommendation_service.RecommendationService``,
``Business.report_service.{ReportService, Report}``, and
``Repository.persistence.snapshot_repository.SnapshotRepository`` for
the constructor's own type annotations. It does NOT import
``Repository.persistence.watchlist_repository.WatchlistRepository``,
``Orchestration.market_analysis_agent.MarketAnalysisAgent``, any other
Repository, any Tool, any Skill, any Pipeline, any scheduler, or any
export/notification module (PDF/Excel/HTML/JSON/Telegram/Discord).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, Optional

from Business.ranking_engine import RankingEngine
from Business.recommendation_service import RecommendationService
from Business.report_service import Report, ReportService
from Orchestration.watchlist_scanner import WatchlistScanner
from Repository.persistence.snapshot_repository import SnapshotRepository


class ManualScanService:
    """Orchestrates the already-completed Sprint 5 pipeline into one
    stable manual scan call.

    No business logic of its own -- no sorting, ranking, filtering,
    scoring, retry, or exception wrapping. The entire responsibility
    of this class is sequencing five already-existing collaborators in
    a fixed order and persisting one snapshot row per resulting
    ``Recommendation``.
    """

    def __init__(
        self,
        watchlist_scanner: WatchlistScanner,
        ranking_engine: RankingEngine,
        recommendation_service: RecommendationService,
        report_service: ReportService,
        snapshot_repository: SnapshotRepository,
    ) -> None:
        """Store the exactly five collaborators this service will call.

        Args:
            watchlist_scanner: The already-constructed
                ``WatchlistScanner`` used to run
                ``MarketAnalysisAgent`` once per watchlist ticker.
                Stored by identity, never copied, never inspected,
                never wrapped.
            ranking_engine: The already-constructed ``RankingEngine``
                used to normalize the scan result into
                ``RankedSymbol`` entries. Stored by identity.
            recommendation_service: The already-constructed
                ``RecommendationService`` used to turn ``RankedSymbol``
                entries into ``Recommendation`` entries. Stored by
                identity.
            report_service: The already-constructed ``ReportService``
                used to build the final ``Report``. Stored by
                identity.
            snapshot_repository: The already-constructed
                ``SnapshotRepository`` used to persist one row per
                ``Recommendation``. Stored by identity. Any wiring it
                needs (e.g. an already-connected ``DatabaseManager``)
                must already be in place before it is handed to this
                constructor -- this class injects nothing onto it.
        """
        self._watchlist_scanner = watchlist_scanner
        self._ranking_engine = ranking_engine
        self._recommendation_service = recommendation_service
        self._report_service = report_service
        self._snapshot_repository = snapshot_repository

    def run_scan(self, generated_at: str) -> Report:
        """Run the full manual scan pipeline and return the resulting
        ``Report``.

        Executes, in exactly this order (LOCKED DECISION 4):

            1. ``self._watchlist_scanner.scan()``
            2. ``self._ranking_engine.rank(scan_result)``
            3. ``self._recommendation_service.build_recommendations(ranked)``
            4. ``self._report_service.build_report(recommendations, generated_at)``
            5. ``self._snapshot_repository.create(...)`` once per
               ``Recommendation`` in the built report
            6. return the ``Report``

        No sorting, ranking, filtering, scoring, retry, or exception
        wrapping of any kind is performed here -- each step's output
        is handed to the next exactly as produced.

        Args:
            generated_at: Caller-supplied timestamp string, used
                unchanged both as the returned ``Report``'s
                ``generated_at`` and as every persisted snapshot row's
                ``scan_time``. This method never generates its own
                timestamp.

        Returns:
            The exact ``Report`` ``ReportService.build_report()``
            returned -- same object, never rebuilt or wrapped.

        Raises:
            Exception: any exception raised by
                ``WatchlistScanner.scan()``, ``RankingEngine.rank()``,
                ``RecommendationService.build_recommendations()``,
                ``ReportService.build_report()``, or
                ``SnapshotRepository.create()`` propagates unchanged
                -- never caught, never wrapped.
        """
        scan_result = self._watchlist_scanner.scan()
        ranked_symbols = self._ranking_engine.rank(scan_result)
        recommendations = self._recommendation_service.build_recommendations(ranked_symbols)
        report = self._report_service.build_report(recommendations, generated_at)

        # Activation 2.7 (supersedes, narrowly, this method's original
        # "one SnapshotRepository.create() call per Recommendation,
        # nothing else" LOCKED DECISION 5): every RankedSymbol already
        # carries the score/score_breakdown Sprint 5 STEP 4 discarded
        # when it copied only five fields into Recommendation. Rather
        # than re-deriving that score (which would risk drifting from
        # RankingEngine's own LOCKED formula) or changing
        # Recommendation's shape (LOCKED, out of scope), this method
        # looks the matching RankedSymbol back up by symbol -- read
        # only, RankingEngine.rank()'s own output is never mutated.
        ranked_by_symbol = {ranked.symbol: ranked for ranked in ranked_symbols}

        for recommendation in report.recommendations:
            ranked = ranked_by_symbol.get(recommendation.symbol)
            self._snapshot_repository.create(
                scan_time=generated_at,
                symbol=recommendation.symbol,
                recommendation=recommendation.recommendation,
                confidence=recommendation.confidence,
                priority=recommendation.priority,
                rank=recommendation.rank,
                status="success",
                score=ranked.score if ranked is not None else None,
                score_breakdown_json=self._breakdown_json(ranked),
                evidence_summary=self._evidence_summary(scan_result, recommendation.symbol),
            )

        # Activation 2.7: a symbol RankingEngine.rank() silently
        # excluded (see RankingEngine.extract_failures(), purely
        # additive -- rank()'s own filtering is untouched) is now
        # persisted too, as a status="error" row carrying why it was
        # excluded, instead of vanishing without a trace the moment
        # RecommendationService/ReportService never saw it.
        for symbol, reason in self._ranking_engine.extract_failures(scan_result):
            self._snapshot_repository.create(
                scan_time=generated_at,
                symbol=symbol,
                status="error",
                error_message=reason,
                evidence_summary=self._evidence_summary(scan_result, symbol),
            )

        return report

    @staticmethod
    def _breakdown_json(ranked_symbol) -> Optional[str]:
        """``json.dumps`` of ``ranked_symbol.score_breakdown``, or
        ``None`` if there is no matching ``RankedSymbol`` or it has no
        breakdown. Read-only: never computes or alters a breakdown,
        only serializes the one ``RankingEngine`` already produced.
        """
        if ranked_symbol is None or ranked_symbol.score_breakdown is None:
            return None
        return json.dumps(asdict(ranked_symbol.score_breakdown))

    @staticmethod
    def _evidence_summary(scan_result: Dict[str, Any], symbol: str) -> Optional[str]:
        """The real ``summary`` text ``WatchlistAnalysisSkill`` already
        produced for ``symbol``, read directly out of ``scan_result``
        -- the same ``"watchlist"`` ``SkillResult.output["watchlist"][0]
        ["summary"]`` shape ``RankingEngine`` itself reads
        ``recommendation``/``confidence``/``priority`` from, just one
        more field of the same, already-real entry. Never fabricated,
        never computed, never read from anywhere else -- ``None`` if
        that shape is absent or malformed, exactly like every other
        defensive read in this pipeline.
        """
        agent_result = scan_result.get(symbol)
        if not isinstance(agent_result, dict):
            return None
        watchlist_result = agent_result.get("watchlist")
        if watchlist_result is None or watchlist_result.success is not True:
            return None
        output = watchlist_result.output
        if not isinstance(output, dict):
            return None
        watchlist_list = output.get("watchlist")
        if not isinstance(watchlist_list, list) or not watchlist_list:
            return None
        entry = watchlist_list[0]
        if not isinstance(entry, dict):
            return None
        summary = entry.get("summary")
        return summary if isinstance(summary, str) else None