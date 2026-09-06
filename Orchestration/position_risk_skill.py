"""PositionRiskSkill -- the project's first risk-level layer (Phase
10, Sprint 121).

Where ``Orchestration.recommendation_skill.RecommendationSkill``
turns an analyzed stock's ``recommendation``/``confidence`` pair into
a concrete ``action`` (``BUY``/``WATCH``/``IGNORE``/``EXIT``/
``UNKNOWN``), no existing Skill ever attached a risk level to that
action. This Skill closes that gap: it reads a list of already-
decided actions (each carrying the ``"action"`` value a prior
``RecommendationSkill.execute()`` call already produced) and attaches
a single, deterministic ``"risk"`` label to every one of them.

This is not AI, not an LLM, not Ollama, not ATR, not stop-loss math,
not position sizing, not capital allocation, and not a maximum-
exposure calculation of any kind: the entire mapping is one fixed,
LOCKED three-row lookup table (plus one catch-all default), applied
via a single ``dict.get(...)`` call per entry -- there is no numeric
score, no probability, no volatility measure, no formula anywhere in
this file.

Input shape (read from ``context.parameters["actions"]``, a
``list``):

    {
        "actions": [
            {"symbol": "BBCA", "action": "BUY"},
            ...
        ]
    }

Only ``"symbol"`` and ``"action"`` are ever read. Nothing else an
``actions`` entry may carry is inspected; this Skill knows nothing
about them and would behave identically if they were absent
entirely.

Decision table (LOCKED), read from ``action`` straight to ``risk``
with exactly one lookup:

    BUY  -> NORMAL
    WAIT -> LOW
    SELL -> NONE
    anything else -> UNKNOWN

"Anything else" covers every case not one of the three rows above --
an unrecognized ``action`` value (including ``UNKNOWN``, produced by
``RecommendationSkill`` for its own unrecognized cases), a missing
``"action"`` key, or a missing/non-``dict`` entry itself. This Skill
deliberately does NOT normalize ``action`` at all -- there is no
fallback category to normalize into here, only a single
``"UNKNOWN"`` risk level, so the raw ``action`` value (including
``None`` for anything missing or malformed) is read defensively,
looked up, and reported back on the output entry, completely
unchanged from whatever was actually present on the input.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"risk": [
            {"symbol": "BBCA", "action": "BUY", "risk": "NORMAL"},
            ...
        ]},
        error=None,
        metadata={},
    )

Each risk entry carries exactly ``"symbol"``, ``"action"``, and
``"risk"`` -- nothing more. ``"action"`` is always the exact raw
value read from the input (including ``None`` for anything missing
or malformed) -- never a normalized substitute. ``success`` is
unconditionally ``True`` and ``error`` is unconditionally ``None`` --
this Skill calls no Tool and has no failure mode of its own;
malformed input simply yields ``"UNKNOWN"`` risk entries, never a
failure.

``context.parameters`` is read defensively: if it is not a
``Mapping`` at all, or its ``"actions"`` value is missing or not a
``list``, this method behaves as though ``"actions"`` were an empty
list -- never raising, and producing ``{"risk": []}``.

No new abstraction of any kind was introduced to build the mapping:
no ``RuleEngine``, ``PositionSizer``, ``RiskEngine``, ``Strategy``,
``Manager``, ``Coordinator``, ``Planner``, ``Workflow``, ``Service``,
``Repository``, ``Provider``, ``Factory``, ``Helper``, or ``Utility``
module. The per-entry loop, the single fixed three-entry ``dict``
literal lookup table, and the ``dict.get(...)`` lookup all live
directly inline inside ``execute()`` -- exactly the same shape
``Orchestration.recommendation_skill.RecommendationSkill`` already
uses one layer up.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private, nested or module-
level) beyond the three ``BaseSkill``-required members, and any of
``size()``, ``allocate()``, ``compute_stop_loss()``, ``atr()``, or
``exposure()``. No AI, no LLM calls (including Ollama), no provider
calls, no service calls, no repository calls, no Tool calls of any
kind (this Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` -- it
consumes an already-decided action, it does not produce one), and no
ATR, stop-loss, position sizing, capital allocation, or maximum-
exposure calculation anywhere in this file.

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import ``Orchestration.recommendation_skill.
RecommendationSkill``, ``Orchestration.text_analysis_skill.
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


class PositionRiskSkill(BaseSkill):
    """The project's first risk-level layer: turns each already-
    decided action into a single, concrete ``risk`` label via one
    fixed, deterministic lookup table.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``size``, ``allocate``, ``compute_stop_loss``, ``atr``, or
    ``exposure`` anywhere on this class; the per-entry loop and the
    single lookup table both live entirely inline inside
    ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"position_risk"``.
        """
        return "position_risk"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Attach a deterministic risk level to each recommended action."``.
        """
        return "Attach a deterministic risk level to each recommended action."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["actions"]`` and
        produce one risk entry per action via a single, fixed lookup
        table.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-decided actions (each an
        already-produced ``RecommendationSkill``-shaped
        ``{"symbol": ..., "action": ...}`` mapping) and attaches a
        risk level to each one.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"actions"`` value is missing or
        not a ``list``, this method behaves as though ``"actions"``
        were an empty list -- never raising, and producing
        ``{"risk": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``RecommendationSkill``:

            * ``symbol`` is read from ``entry.get("symbol")`` if
              ``entry`` is a ``dict``, else ``None``.
            * ``action`` is read from ``entry.get("action")`` if
              ``entry`` is a ``dict``, else ``None``. This raw value
              is never normalized -- it is looked up exactly as
              read, and reported back unchanged on the output entry.

        ``action`` is looked up in one fixed, three-entry ``dict``
        literal mapping every LOCKED action to its risk level; any
        value not present in that table (an unrecognized action,
        including ``None`` from a missing/malformed entry) falls
        back to ``"UNKNOWN"`` via ``dict.get(...)``'s own default
        argument -- no separate branch, no ``if``/``elif`` chain of
        any kind.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing an ``"actions"`` list, in the shape
                documented above. Passed through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"risk": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        actions = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_actions = parameters.get("actions")
            if isinstance(raw_actions, list):
                actions = raw_actions

        risk_table = {
            "BUY": "NORMAL",
            "WAIT": "LOW",
            "SELL": "NONE",
        }

        risk = []
        for entry in actions:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            action = entry.get("action") if isinstance(entry, dict) else None

            risk_level = risk_table.get(action, "UNKNOWN")

            risk.append({
                "symbol": symbol,
                "action": action,
                "risk": risk_level,
            })

        return SkillResult(
            success=True,
            output={"risk": risk},
            error=None,
            metadata={},
        )