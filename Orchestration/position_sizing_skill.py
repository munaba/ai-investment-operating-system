"""PositionSizingSkill -- the project's first position-sizing layer
(Phase 10, Sprint 124).

Where ``Orchestration.trade_plan_skill.TradePlanSkill`` attaches a
``plan`` label to each already-risk-scored ``(action, risk)`` pair,
no existing Skill ever turned a trade plan into an actual executable
position size. This Skill closes that gap: it reads a list of
already-planned entries (each carrying the ``"action"``/``"risk"``/
``"plan"`` triple a prior ``TradePlanSkill.execute()`` call already
produced) and attaches a single, deterministic ``"position_size"``
label to every one of them.

This is not AI, not an LLM, not Ollama, not lot-size math, not
capital allocation math, and not a stop-loss/maximum-exposure
calculation of any kind: the entire mapping is one fixed, LOCKED
nine-row lookup table (plus one catch-all default), keyed on the
``(action, risk)`` pair and applied via a single ``dict.get(...)``
call per entry -- there is no numeric score, no probability, no
formula anywhere in this file.

Input shape (read from ``context.parameters["plans"]``, a ``list``):

    {
        "plans": [
            {"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "ACCUMULATE"},
            ...
        ]
    }

Only ``"symbol"``, ``"action"``, ``"risk"``, and ``"plan"`` are ever
read. Nothing else a ``plans`` entry may carry is inspected; this
Skill knows nothing about them and would behave identically if they
were absent entirely.

Decision table (LOCKED), read from the ``(action, risk)`` pair
straight to ``position_size`` with exactly one lookup:

    (BUY,  LOW)    -> FULL
    (BUY,  MEDIUM) -> HALF
    (BUY,  HIGH)   -> SMALL
    (WAIT, LOW)    -> WATCH
    (WAIT, MEDIUM) -> WATCH
    (WAIT, HIGH)   -> WATCH
    (SELL, LOW)    -> EXIT
    (SELL, MEDIUM) -> EXIT
    (SELL, HIGH)   -> EXIT
    anything else  -> UNKNOWN

"Anything else" covers every ``(action, risk)`` pair not one of the
nine rows above -- an unrecognized combination, a missing
``"action"`` or ``"risk"`` key, or a missing/non-``dict`` entry
itself. This Skill deliberately does NOT normalize ``action``,
``risk``, or ``plan`` at all -- there is no fallback category to
normalize into here, only a single ``"UNKNOWN"`` position size, so
all three raw values (including ``None`` for anything missing or
malformed) are read defensively and reported back on the output
entry, completely unchanged from whatever was actually present on
the input. ``plan`` in particular is never consulted by the lookup
itself -- only ``action``/``risk`` decide ``position_size`` -- it is
carried through purely for the caller's own use.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"positions": [
            {"symbol": "BBCA", "action": "BUY", "risk": "LOW", "plan": "ACCUMULATE", "position_size": "FULL"},
            ...
        ]},
        error=None,
        metadata={},
    )

Each position entry carries exactly ``"symbol"``, ``"action"``,
``"risk"``, ``"plan"``, and ``"position_size"`` -- nothing more.
``"action"``, ``"risk"``, and ``"plan"`` are always the exact raw
values read from the input (including ``None`` for anything missing
or malformed) -- never a normalized substitute. ``success`` is
unconditionally ``True`` and ``error`` is unconditionally ``None`` --
this Skill calls no Tool and has no failure mode of its own;
malformed input simply yields ``"UNKNOWN"`` position-size entries,
never a failure.

``context.parameters`` is read defensively: if it is not a
``Mapping`` at all, or its ``"plans"`` value is missing or not a
``list``, this method behaves as though ``"plans"`` were an empty
list -- never raising, and producing ``{"positions": []}``.

No new abstraction of any kind was introduced to build the mapping:
no ``PositionSizingEngine``, ``PositionCalculator``,
``RiskCalculator``, ``MoneyManagement``, ``Manager``, ``Planner``,
``Strategy``, ``Factory``, ``Registry``, ``Coordinator``,
``Workflow``, ``Service``, ``Repository``, ``Helper``, ``Utility``,
or ``Formatter`` module. The per-entry loop, the single fixed
nine-entry ``dict`` literal lookup table, and the ``dict.get(...)``
lookup all live directly inline inside ``execute()`` -- exactly the
same shape ``Orchestration.trade_plan_skill.TradePlanSkill`` already
uses one layer down.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private, nested or module-
level) beyond the three ``BaseSkill``-required members, and any
lot-size, capital-allocation, stop-loss, or maximum-exposure
calculation. No AI, no LLM calls (including Ollama), no provider
calls, no service calls, no repository calls, no database access, no
Tool calls of any kind (this Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` -- it
consumes an already-planned action, it does not produce one).

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import
``Orchestration.trade_plan_skill.TradePlanSkill``,
``Orchestration.position_risk_skill.PositionRiskSkill``,
``Orchestration.recommendation_skill.RecommendationSkill``,
``Orchestration.text_analysis_skill.TextAnalysisSkill``,
``Orchestration.market_analysis_skill.MarketAnalysisSkill``,
``Orchestration.portfolio_analysis_skill.PortfolioAnalysisSkill``,
``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``,
``Orchestration.market_analysis_agent.MarketAnalysisAgent``,
``Orchestration.trading_decision_agent.TradingDecisionAgent``, any
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


class PositionSizingSkill(BaseSkill):
    """The project's first position-sizing layer: turns each
    already-planned ``(action, risk)`` pair into a single, concrete
    ``position_size`` label via one fixed, deterministic lookup
    table.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``size``, ``allocate``, ``compute_stop_loss``, or ``exposure``
    anywhere on this class; the per-entry loop and the single lookup
    table both live entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"position_sizing"``.
        """
        return "position_sizing"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Attach a deterministic position size to each planned action."``.
        """
        return "Attach a deterministic position size to each planned action."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["plans"]`` and
        produce one position entry per entry via a single, fixed
        lookup table keyed on ``(action, risk)``.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-planned entries (each an
        already-produced ``TradePlanSkill``-shaped
        ``{"symbol": ..., "action": ..., "risk": ..., "plan": ...}``
        mapping) and attaches a position size to each one.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"plans"`` value is missing or
        not a ``list``, this method behaves as though ``"plans"``
        were an empty list -- never raising, and producing
        ``{"positions": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``TradePlanSkill``:

            * ``symbol`` is read from ``entry.get("symbol")`` if
              ``entry`` is a ``dict``, else ``None``.
            * ``action`` is read from ``entry.get("action")`` if
              ``entry`` is a ``dict``, else ``None``. This raw value
              is never normalized -- it is looked up exactly as
              read, and reported back unchanged on the output entry.
            * ``risk`` is read from ``entry.get("risk")`` if
              ``entry`` is a ``dict``, else ``None``. Also never
              normalized, also reported back unchanged.
            * ``plan`` is read from ``entry.get("plan")`` if
              ``entry`` is a ``dict``, else ``None``. Never consulted
              by the lookup itself, never normalized, reported back
              unchanged.

        The ``(action, risk)`` pair is looked up in one fixed,
        nine-entry ``dict`` literal mapping every LOCKED combination
        to its position size; any pair not present in that table (an
        unrecognized combination, including ``None``/``None`` from a
        missing or malformed entry) falls back to ``"UNKNOWN"`` via
        ``dict.get(...)``'s own default argument -- no separate
        branch, no ``if``/``elif`` chain of any kind.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"plans"`` list, in the shape documented
                above. Passed through defensively -- never copied,
                never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"positions": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        plan_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_plans = parameters.get("plans")
            if isinstance(raw_plans, list):
                plan_entries = raw_plans

        position_size_table = {
            ("BUY", "LOW"): "FULL",
            ("BUY", "MEDIUM"): "HALF",
            ("BUY", "HIGH"): "SMALL",
            ("WAIT", "LOW"): "WATCH",
            ("WAIT", "MEDIUM"): "WATCH",
            ("WAIT", "HIGH"): "WATCH",
            ("SELL", "LOW"): "EXIT",
            ("SELL", "MEDIUM"): "EXIT",
            ("SELL", "HIGH"): "EXIT",
        }

        positions = []
        for entry in plan_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            action = entry.get("action") if isinstance(entry, dict) else None
            risk = entry.get("risk") if isinstance(entry, dict) else None
            plan = entry.get("plan") if isinstance(entry, dict) else None

            position_size = position_size_table.get((action, risk), "UNKNOWN")

            positions.append({
                "symbol": symbol,
                "action": action,
                "risk": risk,
                "plan": plan,
                "position_size": position_size,
            })

        return SkillResult(
            success=True,
            output={"positions": positions},
            error=None,
            metadata={},
        )