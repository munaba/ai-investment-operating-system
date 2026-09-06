"""TradePlanSkill -- the project's first trade-plan layer (Phase 10,
Sprint 122).

Where ``Orchestration.position_risk_skill.PositionRiskSkill`` attaches
a ``risk`` label to each already-decided ``action``, no existing
Skill ever turned an ``action``/``risk`` pair into a concrete trade
plan. This Skill closes that gap: it reads a list of already-risk-
scored entries (each carrying the ``"action"``/``"risk"`` pair a
prior ``PositionRiskSkill.execute()`` call already produced) and
attaches a single, deterministic ``"plan"`` label to every one of
them.

This is not AI, not an LLM, not Ollama, not position sizing, not
capital allocation, and not an execution-priority calculation of any
kind: the entire mapping is one fixed, LOCKED three-row lookup table
(plus one catch-all default), keyed on the ``(action, risk)`` pair
and applied via a single ``dict.get(...)`` call per entry -- there is
no numeric score, no probability, no formula anywhere in this file.

Input shape (read from ``context.parameters["risk"]``, a ``list``):

    {
        "risk": [
            {"symbol": "BBCA", "action": "BUY", "risk": "NORMAL"},
            ...
        ]
    }

Only ``"symbol"``, ``"action"``, and ``"risk"`` are ever read.
Nothing else a ``risk`` entry may carry is inspected; this Skill
knows nothing about them and would behave identically if they were
absent entirely.

Decision table (LOCKED), read from the ``(action, risk)`` pair
straight to ``plan`` with exactly one lookup:

    (BUY, NORMAL)  -> ENTER
    (WAIT, LOW)    -> MONITOR
    (SELL, NONE)   -> EXIT
    anything else  -> UNKNOWN

"Anything else" covers every ``(action, risk)`` pair not one of the
three rows above -- an unrecognized combination, a missing
``"action"`` or ``"risk"`` key, or a missing/non-``dict`` entry
itself. This Skill deliberately does NOT normalize ``action`` or
``risk`` at all -- there is no fallback category to normalize into
here, only a single ``"UNKNOWN"`` plan, so both raw values (including
``None`` for anything missing or malformed) are read defensively,
looked up together, and reported back on the output entry, completely
unchanged from whatever was actually present on the input.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"plans": [
            {"symbol": "BBCA", "action": "BUY", "risk": "NORMAL", "plan": "ENTER"},
            ...
        ]},
        error=None,
        metadata={},
    )

Each plan entry carries exactly ``"symbol"``, ``"action"``,
``"risk"``, and ``"plan"`` -- nothing more. ``"action"`` and
``"risk"`` are always the exact raw values read from the input
(including ``None`` for anything missing or malformed) -- never a
normalized substitute. ``success`` is unconditionally ``True`` and
``error`` is unconditionally ``None`` -- this Skill calls no Tool and
has no failure mode of its own; malformed input simply yields
``"UNKNOWN"`` plan entries, never a failure.

``context.parameters`` is read defensively: if it is not a
``Mapping`` at all, or its ``"risk"`` value is missing or not a
``list``, this method behaves as though ``"risk"`` were an empty
list -- never raising, and producing ``{"plans": []}``.

No new abstraction of any kind was introduced to build the mapping:
no ``RuleEngine``, ``PositionSizer``, ``TradeEngine``, ``Strategy``,
``Manager``, ``Coordinator``, ``Planner``, ``Workflow``, ``Service``,
``Repository``, ``Provider``, ``Factory``, ``Helper``, or ``Utility``
module. The per-entry loop, the single fixed three-entry ``dict``
literal lookup table, and the ``dict.get(...)`` lookup all live
directly inline inside ``execute()`` -- exactly the same shape
``Orchestration.position_risk_skill.PositionRiskSkill`` already uses
one layer down.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private, nested or module-
level) beyond the three ``BaseSkill``-required members, and any
position-sizing, capital-allocation, or execution-priority
calculation. No AI, no LLM calls (including Ollama), no provider
calls, no service calls, no repository calls, no Tool calls of any
kind (this Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` -- it
consumes an already-risk-scored action, it does not produce one).

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import
``Orchestration.position_risk_skill.PositionRiskSkill``,
``Orchestration.recommendation_skill.RecommendationSkill``,
``Orchestration.text_analysis_skill.TextAnalysisSkill``,
``Orchestration.market_analysis_skill.MarketAnalysisSkill``,
``Orchestration.portfolio_analysis_skill.PortfolioAnalysisSkill``,
``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``,
``Orchestration.market_analysis_agent.MarketAnalysisAgent``, any
Tool, ``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_registry.ToolRegistry``,
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


class TradePlanSkill(BaseSkill):
    """The project's first trade-plan layer: turns each already-
    risk-scored ``(action, risk)`` pair into a single, concrete
    ``plan`` label via one fixed, deterministic lookup table.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``size``, ``allocate``, ``prioritize``, or ``sequence``
    anywhere on this class; the per-entry loop and the single lookup
    table both live entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"trade_plan"``.
        """
        return "trade_plan"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Attach a deterministic trade plan to each risk-scored action."``.
        """
        return "Attach a deterministic trade plan to each risk-scored action."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["risk"]`` and
        produce one plan entry per entry via a single, fixed lookup
        table keyed on ``(action, risk)``.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-risk-scored entries (each an
        already-produced ``PositionRiskSkill``-shaped
        ``{"symbol": ..., "action": ..., "risk": ...}`` mapping) and
        attaches a plan to each one.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"risk"`` value is missing or not
        a ``list``, this method behaves as though ``"risk"`` were an
        empty list -- never raising, and producing ``{"plans": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``PositionRiskSkill``:

            * ``symbol`` is read from ``entry.get("symbol")`` if
              ``entry`` is a ``dict``, else ``None``.
            * ``action`` is read from ``entry.get("action")`` if
              ``entry`` is a ``dict``, else ``None``. This raw value
              is never normalized -- it is looked up exactly as
              read, and reported back unchanged on the output entry.
            * ``risk`` is read from ``entry.get("risk")`` if
              ``entry`` is a ``dict``, else ``None``. Also never
              normalized, also reported back unchanged.

        The ``(action, risk)`` pair is looked up in one fixed,
        three-entry ``dict`` literal mapping every LOCKED combination
        to its plan; any pair not present in that table (an
        unrecognized combination, including ``None``/``None`` from a
        missing or malformed entry) falls back to ``"UNKNOWN"`` via
        ``dict.get(...)``'s own default argument -- no separate
        branch, no ``if``/``elif`` chain of any kind.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"risk"`` list, in the shape documented
                above. Passed through defensively -- never copied,
                never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"plans": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        risk_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_risk = parameters.get("risk")
            if isinstance(raw_risk, list):
                risk_entries = raw_risk

        plan_table = {
            ("BUY", "NORMAL"): "ENTER",
            ("WAIT", "LOW"): "MONITOR",
            ("SELL", "NONE"): "EXIT",
        }

        plans = []
        for entry in risk_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            action = entry.get("action") if isinstance(entry, dict) else None
            risk = entry.get("risk") if isinstance(entry, dict) else None

            plan = plan_table.get((action, risk), "UNKNOWN")

            plans.append({
                "symbol": symbol,
                "action": action,
                "risk": risk,
                "plan": plan,
            })

        return SkillResult(
            success=True,
            output={"plans": plans},
            error=None,
            metadata={},
        )