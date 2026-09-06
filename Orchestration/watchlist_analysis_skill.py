"""WatchlistAnalysisSkill -- the project's first watchlist-priority
Skill (Phase 11, Sprint 116).

Where ``Orchestration.portfolio_analysis_skill.PortfolioAnalysisSkill``
ranks *owned* positions (recommendation priority first, confidence
priority second, as two separate sort keys), this Skill answers a
different question -- given a watchlist of already-analyzed
candidates, which ones deserve attention first -- using one single,
combined, LOCKED nine-row (recommendation, confidence) priority
table, applied via exactly one ``sorted(...)`` call.

This is not AI, not an LLM, not Ollama, not a scoring engine, not an
optimization algorithm, and not portfolio mathematics of any kind:
the entire priority ordering is one fixed lookup table -- there is no
numeric score, no probability, no weighting, and no formula anywhere
in this file.

Input shape (read from ``context.parameters["stocks"]``, a ``list``):

    {
        "stocks": [
            {
                "symbol": "...",
                "analysis": {
                    "recommendation": "...",
                    "confidence": "...",
                    "summary": "...",
                },
            },
            ...
        ]
    }

Only ``"symbol"`` and ``analysis["recommendation"]``/
``analysis["confidence"]``/``analysis["summary"]`` are ever read.
``"price"``, ``"news"``, ``"fundamental"``, and
``analysis["reason"]``/``["strengths"]``/``["risks"]`` -- everything
else a ``TextAnalysisSkill`` result may carry -- is deliberately
never inspected; this Skill knows nothing about them and would
behave identically if they were absent entirely.

Priority table (LOCKED), highest attention first:

    BUY  + HIGH   -> 1st
    BUY  + MEDIUM -> 2nd
    BUY  + LOW    -> 3rd
    WAIT + HIGH   -> 4th
    WAIT + MEDIUM -> 5th
    WAIT + LOW    -> 6th
    SELL + HIGH   -> 7th
    SELL + MEDIUM -> 8th
    SELL + LOW    -> 9th (lowest)

This is written directly as one fixed, nine-entry ``dict`` literal
mapping the ``(recommendation, confidence)`` pair to its priority
integer, looked up by exactly one ``sorted(...)`` call -- there is no
separate recommendation-then-confidence two-key sort (unlike
``PortfolioAnalysisSkill``); the combined table already encodes both
in a single lookup, so the whole ordering is one sort with one key
per entry. Stable ordering for identical ``(recommendation,
confidence)`` pairs -- preserving the original input order -- comes
entirely from Python's ``sorted()`` being a guaranteed stable sort;
no manual swap, no insertion sort, no bubble sort, no second pass,
and no additional tie-breaker key of any kind was written.

Any unrecognized, missing, or malformed value is normalized before
the table above is applied, using the exact same never-raise
``isinstance()``/``.get()`` style already used throughout
``TextAnalysisSkill``/``PortfolioAnalysisSkill``:

    * a ``"recommendation"`` value that is not exactly one of
      ``"BUY"``/``"WAIT"``/``"SELL"`` (including ``None``, a missing
      key, or any other string) is treated as ``"SELL"``.
    * a ``"confidence"`` value that is not exactly one of
      ``"HIGH"``/``"MEDIUM"``/``"LOW"`` is treated as ``"LOW"``.
    * a stock entry with a missing, non-``dict`` ``"analysis"``, or a
      missing/non-``dict`` stock entry itself, is treated as though
      both ``"recommendation"`` and ``"confidence"`` were absent --
      i.e. ``"SELL"``/``"LOW"`` -- and never raises. This is exactly
      the same normalization ``PortfolioAnalysisSkill`` already uses.
    * ``"summary"`` is read from ``analysis.get("summary")`` if
      ``analysis`` is a ``dict``, else ``None`` -- it is never
      normalized, validated, or substituted; it is passed through by
      identity, whatever it is (including ``None``).

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"watchlist": [
            {"priority": 1, "symbol": "...", "recommendation": "...",
             "confidence": "...", "summary": "..."},
            ...
        ]},
        error=None,
        metadata={},
    )

Each watchlist entry carries exactly ``"priority"``, ``"symbol"``,
``"recommendation"``, ``"confidence"``, and ``"summary"`` -- nothing
more (no ``"reason"``, no ``"strengths"``/``"risks"``, and no score
of any kind). ``"priority"`` is always a 1-based position matching
this entry's index in the final, ordered ``"watchlist"`` list. The
``"recommendation"``/``"confidence"`` an entry carries are always the
already-normalized values used to prioritize it -- never the
original, raw value a malformed input happened to contain -- for the
same reason ``PortfolioAnalysisSkill`` does the same: an entry never
shows a value that contradicts the priority it was actually ordered
by. ``success`` is unconditionally ``True`` and ``error`` is
unconditionally ``None`` -- this Skill calls no Tool and has no
failure mode of its own; malformed input is normalized rather than
treated as a failure.

No new abstraction of any kind was introduced to build the
watchlist: no ``WatchlistManager``, ``PriorityEngine``,
``ScoreCalculator``, ``Analyzer``, ``Strategy``, ``Pipeline``,
``Factory``, ``Registry``, ``Builder``, ``Formatter``, or utility
module. The normalization loop, the single fixed priority lookup
``dict``, and the one ``sorted(...)`` call all live directly inline
inside ``execute()``.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private) beyond the three
``BaseSkill``-required members, any nested function or lambda beyond
the single sort-key lambda passed directly to ``sorted(...)``, and
any of ``prioritize()``, ``score()``, ``rank()``, ``watch()``, or
``sort_stocks()``. No AI, no LLM calls (including Ollama), no
provider calls, no service calls, no repository calls, no Tool calls
of any kind (this Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` -- it consumes
already-computed analyses, it does not produce them), and no
scoring, probability, or fuzzy logic anywhere in this file.

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import ``Orchestration.text_analysis_skill.
TextAnalysisSkill``, ``Orchestration.portfolio_analysis_skill.
PortfolioAnalysisSkill``, any Tool, ``Orchestration.tool_resolver.
ToolResolver``, ``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.executor.Executor``, ``Agents.planner.Planner``,
``Orchestration.memory``, ``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, ``Orchestration.event_bus.EventBus``,
``requests``, ``google.genai``, ``anthropic``, ``openai``,
``ollama``, ``sqlite3``, ``pandas``, ``numpy``, or ``yfinance``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class WatchlistAnalysisSkill(BaseSkill):
    """The project's first watchlist-priority Skill: orders multiple
    already-analyzed candidate stocks by one fixed, combined
    (recommendation, confidence) priority table.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``prioritize``, ``score``, ``rank``, ``watch``, or
    ``sort_stocks`` anywhere on this class; the normalization and
    ordering both live entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"watchlist_analysis"``.
        """
        return "watchlist_analysis"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Prioritize watchlist candidates by recommendation and confidence."``.
        """
        return "Prioritize watchlist candidates by recommendation and confidence."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["stocks"]`` and
        produce one deterministic, priority-ordered watchlist.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-analyzed candidate stocks
        (each an already-produced ``TextAnalysisSkill``-shaped
        ``{"symbol": ..., "analysis": {"recommendation": ...,
        "confidence": ..., "summary": ...}}`` mapping) and reorders
        them.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"stocks"`` value is missing or
        not a ``list``, this method behaves as though ``"stocks"``
        were an empty list -- never raising, and producing
        ``{"watchlist": []}``.

        Each stock entry is normalized independently, using the same
        never-raise ``isinstance()``/``.get()`` style already used
        throughout ``TextAnalysisSkill``/``PortfolioAnalysisSkill``:

            * ``symbol`` is read from ``stock.get("symbol")`` if
              ``stock`` is a ``dict``, else ``None``.
            * ``recommendation``/``confidence``/``summary`` are read
              from ``stock["analysis"].get("recommendation")``/
              ``.get("confidence")``/``.get("summary")`` only if both
              ``stock`` and ``stock["analysis"]`` are ``dict`` --
              else all three are treated as missing (``None``).
            * a ``recommendation`` that is not exactly one of
              ``"BUY"``/``"WAIT"``/``"SELL"`` is normalized to
              ``"SELL"``; a ``confidence`` that is not exactly one of
              ``"HIGH"``/``"MEDIUM"``/``"LOW"`` is normalized to
              ``"LOW"``. This single normalization step is what
              implements the LOCKED "unknown recommendation ->
              SELL", "unknown confidence -> LOW", and "missing
              analysis -> SELL/LOW" rules simultaneously -- a missing
              analysis simply yields ``None`` for both, which matches
              neither allowed set and so normalizes exactly the same
              way an explicitly unrecognized value would.
            * ``summary`` is never normalized or validated -- it is
              carried through by identity, whatever it is (including
              ``None`` for a missing/malformed analysis).

        The normalized entries are then ordered with exactly one
        ``sorted(...)`` call, keyed on a single fixed nine-entry
        ``dict`` literal mapping ``(recommendation, confidence)`` to
        its LOCKED priority integer (``BUY``+``HIGH`` highest,
        ``SELL``+``LOW`` lowest) -- relying on ``sorted()``'s
        guaranteed stability for the "preserve original input order"
        rule among identical pairs, with no additional tie-breaker
        key, no manual swap, no insertion sort, no bubble sort, and
        no second pass of any kind.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"stocks"`` list, in the shape
                documented above. Passed through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"watchlist": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        stocks = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_stocks = parameters.get("stocks")
            if isinstance(raw_stocks, list):
                stocks = raw_stocks

        normalized = []
        for stock in stocks:
            symbol = None
            recommendation = None
            confidence = None
            summary = None
            status = None
            analysis = None
            if isinstance(stock, dict):
                symbol = stock.get("symbol")
                status = stock.get("status")
                analysis = stock.get("analysis")
                if isinstance(analysis, dict):
                    recommendation = analysis.get("recommendation")
                    confidence = analysis.get("confidence")
                    summary = analysis.get("summary")

            if not isinstance(analysis, dict):
                # ONLY FIX -- failed data signal: a missing/None/non-dict
                # ``analysis`` means there is no real signal to prioritize,
                # so this must never be normalized into a live "SELL"/"LOW"
                # recommendation. Surface the already-existing upstream
                # failure status instead (MarketAnalysisSkill's
                # "DATA_ERROR"/"INSUFFICIENT_DATA"/"ANALYSIS_FAILED"), or
                # "SKIPPED" if even that is absent. Neither value is a
                # member of RankingEngine's recommendation-weight table,
                # so RankingEngine._extract_valid_entries() drops this
                # symbol before it can ever reach RecommendationService.
                if status in ("DATA_ERROR", "ANALYSIS_FAILED", "INSUFFICIENT_DATA", "SKIPPED"):
                    recommendation = status
                else:
                    recommendation = "SKIPPED"
                confidence = None
            elif recommendation not in ("BUY", "WAIT", "SELL"):
                # ONLY FIX -- analysis is a dict but carries an unrecognized
                # recommendation (e.g. "UNKNOWN"): this is not a real
                # BUY/WAIT/SELL signal either, so it must never be silently
                # normalized into a live "SELL". Surface the same existing
                # upstream failure status used for missing/non-dict analysis
                # above, or "SKIPPED" if that status is absent/unrecognized,
                # with confidence forced to None so this entry is not
                # treated as a scored recommendation downstream.
                if status in ("DATA_ERROR", "ANALYSIS_FAILED", "INSUFFICIENT_DATA", "SKIPPED"):
                    recommendation = status
                else:
                    recommendation = "SKIPPED"
                confidence = None
            # ONLY FIX -- only normalize confidence to "LOW" when this entry
            # still carries a real BUY/WAIT/SELL recommendation; entries
            # demoted above (missing analysis, or an unrecognized
            # recommendation) must keep confidence=None, not be re-promoted
            # to "LOW" here.
            if (
                recommendation in ("BUY", "WAIT", "SELL")
                and confidence not in ("HIGH", "MEDIUM", "LOW")
                and isinstance(analysis, dict)
            ):
                confidence = "LOW"

            normalized.append((symbol, recommendation, confidence, summary))

        priority_table = {
            ("BUY", "HIGH"): 1,
            ("BUY", "MEDIUM"): 2,
            ("BUY", "LOW"): 3,
            ("WAIT", "HIGH"): 4,
            ("WAIT", "MEDIUM"): 5,
            ("WAIT", "LOW"): 6,
            ("SELL", "HIGH"): 7,
            ("SELL", "MEDIUM"): 8,
            ("SELL", "LOW"): 9,
        }

        ordered = sorted(
            normalized,
            # ONLY FIX -- failed data signal: entries carrying a failure
            # status (e.g. "DATA_ERROR") are not in this fixed 9-row
            # table by design (they are not a real recommendation); fall
            # back to the lowest priority instead of raising, since this
            # Skill must never raise regardless of input shape.
            key=lambda entry: priority_table.get((entry[1], entry[2]), 99),
        )

        watchlist = []
        for position, (symbol, recommendation, confidence, summary) in enumerate(ordered, start=1):
            watchlist.append({
                "priority": position,
                "symbol": symbol,
                "recommendation": recommendation,
                "confidence": confidence,
                "summary": summary,
            })

        return SkillResult(
            success=True,
            output={"watchlist": watchlist},
            error=None,
            metadata={},
        )