"""WatchlistScanner -- Sprint 5 STEP 1 (LOCKED DECISION, Revisi).

``WatchlistScanner`` has exactly two constructor dependencies:
``Repository.persistence.watchlist_repository.WatchlistRepository`` and
``Orchestration.market_analysis_agent.MarketAnalysisAgent`` (the
Phase 11 Sprint 119 three-Skill coordinator -- NOT
``Agents.market_analysis_agent.MarketAnalysisAgent``, an unrelated
abstract base class; see that module's docstring for why it cannot be
used here).

Per the LOCKED DECISION, this class does not construct, import, or
reference any of: ``ToolRegistry``, ``ToolResolver``,
``Orchestration.skill_context.SkillContext``,
``Services.service_context.ServiceContext``, or
``Core.analysis_pipeline.AnalysisPipeline``. It also does not import or
touch ``Orchestration.market_analysis_skill.MarketAnalysisSkill``,
``Orchestration.portfolio_analysis_skill.PortfolioAnalysisSkill``, or
``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``
directly -- those are ``MarketAnalysisAgent``'s own collaborators, out
of scope here.

``scan()`` (LOCKED shape): read every ticker from
``WatchlistRepository.list_all()``, and for each ticker call
``MarketAnalysisAgent.execute()`` exactly once, collecting each
ticker's result. No batching (all symbols in one call) -- one
``execute()`` call per symbol, per the LOCKED DECISION's "untuk setiap
simbol" wording.

``Orchestration.task.Task`` construction: ``MarketAnalysisAgent.execute()``
only ever reads ``task.metadata`` (a ``Mapping`` with a ``"symbols"``
list) -- it does not read ``task.name``/``task.description`` at all.
Those two fields are still required, non-empty-``str``-validated
fields on ``Task`` itself (unrelated to this scan), so a placeholder
value is supplied for each -- this is not a business-meaning value
comparable to ``ServiceContext.provider_name``/``user_input`` (which
would change what gets analyzed or which provider answers); it is
purely a required label on the value object. Flagged here rather than
assumed silently -- confirm or provide a different convention if this
is not acceptable.

Any exception ``WatchlistRepository.list_all()`` raises still
propagates unchanged (a ticker list this class cannot even read is a
caller-contract violation, not a per-ticker analysis failure -- there
is no per-ticker result to isolate it from).

Activation 2.7 (narrow, additive change to the paragraph above): an
exception from ``MarketAnalysisAgent.execute()`` for one ticker is now
caught and converted into a failed three-key result for that ticker
only (see ``_failure_result()``), so one ticker's fault no longer
aborts every ticker after it in the same ``scan()`` call. See
``_failure_result()``'s own docstring for the full rationale -- every
other line of ``scan()`` (ticker read, per-ticker ``Task``
construction, one ``execute()`` call per ticker, iteration order) is
unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List

from Orchestration.market_analysis_agent import MarketAnalysisAgent
from Orchestration.skill_result import SkillResult
from Orchestration.task import Task
from Repository.persistence.watchlist_repository import WatchlistRepository


class WatchlistScanner:
    """Runs ``MarketAnalysisAgent`` once per watchlist ticker.

    No state beyond the two constructor-injected collaborators, and no
    helper method beyond ``scan()`` itself -- the ticker read, the
    per-ticker ``Task`` construction, and the per-ticker ``execute()``
    call all live directly inline inside ``scan()``.
    """

    def __init__(
        self,
        watchlist_repository: WatchlistRepository,
        market_analysis_agent: MarketAnalysisAgent,
    ) -> None:
        """Store the two collaborators this scanner will call.

        Args:
            watchlist_repository: The already-constructed
                ``WatchlistRepository`` instance used to read the
                current ticker list. Stored by identity, never
                copied, never inspected, never wrapped.
            market_analysis_agent: The already-constructed
                ``Orchestration.market_analysis_agent.MarketAnalysisAgent``
                instance called once per ticker. Stored by identity,
                never copied, never inspected, never wrapped. Any
                wiring it needs (e.g. Tool resolution for its internal
                Skills) must already be in place before it is handed
                to this constructor -- this class injects nothing onto
                it.
        """
        self._watchlist_repository = watchlist_repository
        self._market_analysis_agent = market_analysis_agent

    def scan(self) -> Dict[str, Any]:
        """Read the watchlist and run ``MarketAnalysisAgent`` once per ticker.

        Reads the current ticker list via
        ``self._watchlist_repository.list_all()``. For each ticker, in
        list order, builds one ``Task`` carrying
        ``metadata={"symbols": [ticker]}`` -- the exact shape
        ``MarketAnalysisAgent.execute()`` already reads (see that
        class's own ``execute()`` docstring) -- and calls
        ``self._market_analysis_agent.execute(task)`` exactly once,
        collecting its result.

        Returns:
            A dict mapping each ticker to the exact ``dict``
            ``MarketAnalysisAgent.execute()`` returned for it (keys
            ``"market"``, ``"portfolio"``, ``"watchlist"``, each a
            ``SkillResult``), forwarded by identity, unchanged --
            nothing is merged, recomputed, or reshaped across tickers.

        Raises:
            Exception: any exception raised by
                ``WatchlistRepository.list_all()``, by ``Task``
                construction, or by
                ``MarketAnalysisAgent.execute()`` propagates unchanged
                -- never caught, never wrapped.
        """
        tickers: List[str] = self._watchlist_repository.list_all()

        results: Dict[str, Any] = {}
        for ticker in tickers:
            task = Task(
                name=f"watchlist_scan:{ticker}",
                description="",
                metadata={"symbols": [ticker]},
            )
            try:
                results[ticker] = self._market_analysis_agent.execute(task)
            except Exception as exc:  # noqa: BLE001 -- see Activation 2.7 note below
                results[ticker] = self._failure_result(str(exc))

        return results

    @staticmethod
    def _failure_result(error: str) -> Dict[str, SkillResult]:
        """Build the same three-key shape ``MarketAnalysisAgent.execute()``
        normally returns, with every ``SkillResult`` marked failed
        (Activation 2.7).

        Activation 2.7 supersedes, narrowly, this class's original
        "never catches anything itself" LOCKED DECISION -- but only
        for the one failure mode it never actually covered: an
        exception escaping ``MarketAnalysisAgent.execute()`` itself
        (every Skill it calls is already defensively coded to never
        raise on a per-symbol data problem; this only fires for a
        genuine infrastructure fault, e.g. a Tool call blowing up).
        Before this Activation, that single exception aborted the
        entire scan -- every ticker after the failing one was silently
        never scanned, and the failing ticker itself left no trace
        anywhere. Catching it here and converting it into a failed
        ``SkillResult`` per ticker keeps the failing ticker's failure
        visible (``RankingEngine.extract_failures()`` -> a persisted
        ``status="error"`` row) while every other ticker still scans
        normally -- the per-ticker Task construction and one-
        ``execute()``-call-per-ticker shape are otherwise byte-for-
        byte unchanged.
        """
        failed = SkillResult(success=False, output=None, error=error)
        return {"market": failed, "portfolio": failed, "watchlist": failed}