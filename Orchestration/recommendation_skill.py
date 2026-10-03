"""RecommendationSkill -- the project's first real decision layer
(Phase 11, Sprint 120).

Where ``Orchestration.portfolio_analysis_skill.PortfolioAnalysisSkill``
and ``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``
only *reorder* already-analyzed stocks, and no existing Skill ever
turned an analysis into a concrete action, this Skill closes that
gap: it reads a list of already-analyzed stocks (each carrying the
``"recommendation"``/``"confidence"`` pair a prior
``TextAnalysisSkill.execute()`` call already produced, exactly the
same shape ``MarketAnalysisSkill.execute()`` collects them in) and
turns every one of them into a single, concrete action -- what to do
right now.

This is not AI, not an LLM, not Ollama, not a scoring engine, not an
optimization algorithm, and not portfolio mathematics of any kind:
the entire mapping is one fixed, LOCKED nine-row lookup table (plus
one catch-all default), applied via a single ``dict.get(...)`` call
per stock -- there is no numeric score, no probability, no weighting,
no averaging, no ranking, and no formula anywhere in this file.

Input shape (read from ``context.parameters["stocks"]``, a ``list``):

    {
        "stocks": [
            {
                "symbol": "BBCA",
                "analysis": {
                    "recommendation": "BUY",
                    "confidence": "HIGH",
                },
            },
            ...
        ]
    }

Only ``"symbol"`` and ``analysis["recommendation"]``/
``analysis["confidence"]`` are ever read. ``"price"``, ``"news"``,
``"fundamental"``, and ``analysis["reason"]``/``["strengths"]``/
``["risks"]``/``["summary"]`` -- everything else a
``TextAnalysisSkill`` result may carry -- is deliberately never
inspected; this Skill knows nothing about them and would behave
identically if they were absent entirely.

Decision table (LOCKED), read from ``(recommendation, confidence)``
straight to ``action`` with exactly one lookup:

    BUY  + HIGH   -> BUY
    BUY  + MEDIUM -> BUY
    BUY  + LOW    -> WATCH
    WAIT + HIGH   -> WATCH
    WAIT + MEDIUM -> WATCH
    WAIT + LOW    -> IGNORE
    SELL + HIGH   -> EXIT
    SELL + MEDIUM -> EXIT
    SELL + LOW    -> IGNORE
    anything else -> UNKNOWN

"Anything else" covers every case not one of the nine rows above --
an unrecognized ``recommendation`` value, an unrecognized
``confidence`` value, a missing ``"analysis"`` (or a non-``dict``
one), or a missing/non-``dict`` stock entry itself. Unlike
``PortfolioAnalysisSkill``/``WatchlistAnalysisSkill`` (which
normalize an unrecognized value to a fallback category before
ranking), this Skill deliberately does NOT normalize
``recommendation``/``confidence`` at all -- there is no fallback
category to rank into here, only a single ``"UNKNOWN"`` action, so
the raw ``recommendation``/``confidence`` values (including ``None``
for anything missing or malformed) are read defensively and then
looked up, and reported back on the output entry, completely
unchanged from whatever was actually present on the input.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"actions": [
            {"symbol": "BBCA", "action": "BUY",
             "recommendation": "BUY", "confidence": "HIGH"},
            ...
        ]},
        error=None,
        metadata={},
    )

Each action entry carries exactly ``"symbol"``, ``"action"``,
``"recommendation"``, and ``"confidence"`` -- nothing more (no
``"reason"``, no ``"strengths"``/``"risks"``/``"summary"``, and no
score of any kind). ``"recommendation"``/``"confidence"`` are always
the exact raw values read from the input (including ``None`` for
anything missing or malformed) -- never a normalized substitute.
``success`` is unconditionally ``True`` and ``error`` is
unconditionally ``None`` -- this Skill calls no Tool and has no
failure mode of its own; malformed input simply yields
``"UNKNOWN"`` actions, never a failure.

``context.parameters`` is read defensively: if it is not a
``Mapping`` at all, or its ``"stocks"`` value is missing or not a
``list``, this method behaves as though ``"stocks"`` were an empty
list -- never raising, and producing ``{"actions": []}``.

No new abstraction of any kind was introduced to build the mapping:
no ``DecisionEngine``, ``RecommendationEngine``, ``SignalEngine``,
``ActionPlanner``, ``PortfolioOptimizer``, ``Strategy``, ``Manager``,
``Coordinator``, ``Analyzer``, ``Pipeline``, ``Workflow``,
``Factory``, ``Helper``, or ``Utility`` module. The per-stock loop,
the single fixed nine-entry ``dict`` literal lookup table, and the
``dict.get(...)`` lookup all live directly inline inside
``execute()``.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private, nested or module-
level) beyond the three ``BaseSkill``-required members, and any of
``decide()``, ``recommend()``, ``plan()``, ``act()``, or
``score()``. No AI, no LLM calls (including Ollama), no provider
calls, no service calls, no repository calls, no Tool calls of any
kind (this Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` -- it
consumes already-computed analyses, it does not produce them), and
no scoring, probability, weighting, averaging, ranking,
optimization, portfolio balancing, or risk calculation anywhere in
this file.

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import ``Orchestration.text_analysis_skill.
TextAnalysisSkill``, ``Orchestration.market_analysis_skill.
MarketAnalysisSkill``, ``Orchestration.portfolio_analysis_skill.
PortfolioAnalysisSkill``, ``Orchestration.watchlist_analysis_skill.
WatchlistAnalysisSkill``, ``Orchestration.market_analysis_agent.
MarketAnalysisAgent``, any Tool, ``Orchestration.tool_resolver.
ToolResolver``, ``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_context.ToolContext``,
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


class RecommendationSkill(BaseSkill):
    """The project's first real decision layer: turns each
    already-analyzed stock's ``recommendation``/``confidence`` pair
    into a single, concrete ``action`` via one fixed, deterministic
    lookup table.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``decide``, ``recommend``, ``plan``, ``act``, or ``score``
    anywhere on this class; the per-stock loop and the single lookup
    table both live entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"recommendation"``.
        """
        return "recommendation"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Turn each analyzed stock's recommendation and confidence into a concrete action."``.
        """
        return "Turn each analyzed stock's recommendation and confidence into a concrete action."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["stocks"]`` and
        produce one action per stock via a single, fixed lookup
        table.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-analyzed stocks (each an
        already-produced ``TextAnalysisSkill``-shaped
        ``{"symbol": ..., "analysis": {"recommendation": ...,
        "confidence": ...}}`` mapping) and maps each one to an
        action.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"stocks"`` value is missing or
        not a ``list``, this method behaves as though ``"stocks"``
        were an empty list -- never raising, and producing
        ``{"actions": []}``.

        Each stock entry is read defensively, using the same
        never-raise ``isinstance()``/``.get()`` style already used
        throughout ``PortfolioAnalysisSkill``/
        ``WatchlistAnalysisSkill``:

            * ``symbol`` is read from ``stock.get("symbol")`` if
              ``stock`` is a ``dict``, else ``None``.
            * ``recommendation``/``confidence`` are read from
              ``stock["analysis"].get("recommendation")``/
              ``.get("confidence")`` only if both ``stock`` and
              ``stock["analysis"]`` are ``dict`` -- else both are
              ``None``. Unlike ``PortfolioAnalysisSkill``/
              ``WatchlistAnalysisSkill``, these raw values are never
              normalized to a fallback category -- they are looked
              up exactly as read, and reported back unchanged on the
              output entry.

        The ``(recommendation, confidence)`` pair is looked up in one
        fixed, nine-entry ``dict`` literal mapping every LOCKED
        combination to its action; any pair not present in that
        table (an unrecognized recommendation, an unrecognized
        confidence, or ``None`` from a missing/malformed analysis)
        falls back to ``"UNKNOWN"`` via ``dict.get(...)``'s own
        default argument -- no separate branch, no ``if``/``elif``
        chain of any kind.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"stocks"`` list, in the shape
                documented above. Passed through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"actions": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        stocks = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_stocks = parameters.get("stocks")
            if isinstance(raw_stocks, list):
                stocks = raw_stocks

        decision_table = {
            ("BUY", "HIGH"): "BUY",
            ("BUY", "MEDIUM"): "BUY",
            ("BUY", "LOW"): "WATCH",
            ("WAIT", "HIGH"): "WATCH",
            ("WAIT", "MEDIUM"): "WATCH",
            ("WAIT", "LOW"): "IGNORE",
            ("SELL", "HIGH"): "EXIT",
            ("SELL", "MEDIUM"): "EXIT",
            ("SELL", "LOW"): "IGNORE",
        }

        actions = []
        for stock in stocks:
            symbol = stock.get("symbol") if isinstance(stock, dict) else None
            analysis = stock.get("analysis") if isinstance(stock, dict) else None
            recommendation = analysis.get("recommendation") if isinstance(analysis, dict) else None
            confidence = analysis.get("confidence") if isinstance(analysis, dict) else None

            action = decision_table.get((recommendation, confidence), "UNKNOWN")

            actions.append({
                "symbol": symbol,
                "action": action,
                "recommendation": recommendation,
                "confidence": confidence,
            })

        return SkillResult(
            success=True,
            output={"actions": actions},
            error=None,
            metadata={},
        )