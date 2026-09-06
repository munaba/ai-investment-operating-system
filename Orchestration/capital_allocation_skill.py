"""CapitalAllocationSkill -- the project's first capital-allocation
layer (Phase 10, Sprint 125).

Where ``Orchestration.position_sizing_skill.PositionSizingSkill``
attaches a ``position_size`` label to each already-planned entry, no
existing Skill ever turned that label into an actual amount of
capital to deploy. This Skill closes that gap: it reads a list of
already-sized entries (each carrying the ``"position_size"`` value a
prior ``PositionSizingSkill.execute()`` call already produced) plus a
single total capital figure, and attaches a single, deterministic
``"allocated_capital"`` amount to every one of them.

This is not AI, not an LLM, not Ollama, not a Kelly-criterion
calculation, not a volatility-adjusted sizing formula, and not a
portfolio-optimization calculation of any kind: the entire mapping is
one fixed, LOCKED five-row percentage lookup table (plus one catch-
all default), applied via a single ``dict.get(...)`` call per entry,
multiplied straight through by the total capital -- there is no
probability, no volatility measure, no scoring, and no formula beyond
that one fixed percentage anywhere in this file.

Input shape (read from ``context.parameters["plans"]``, a ``list``,
and ``context.parameters["capital"]``, an ``int``/``float``):

    {
        "plans": [
            {"symbol": "BBCA", "action": "BUY", "risk": "LOW",
             "plan": "LONG_TERM", "position_size": "FULL"},
            ...
        ],
        "capital": 100000000
    }

Only ``"symbol"``, ``"action"``, ``"risk"``, ``"plan"``, and
``"position_size"`` are ever read from a plan entry. Nothing else a
``plans`` entry may carry is inspected; this Skill knows nothing
about them and would behave identically if they were absent
entirely.

Percentage table (LOCKED), read from ``position_size`` straight to a
fixed fraction of ``capital``:

    FULL    -> 100%
    HALF    -> 50%
    SMALL   -> 25%
    AVOID   -> 0%
    UNKNOWN -> 0%
    anything else -> 0%

"Anything else" covers every ``position_size`` value not one of the
five rows above -- an unrecognized value, a missing
``"position_size"`` key, or a missing/non-``dict`` entry itself. This
Skill deliberately does NOT normalize ``position_size`` (or
``action``/``risk``/``plan``) at all -- there is no fallback category
to normalize into here, only a single ``0%`` fraction, so the raw
``position_size`` value (including ``None`` for anything missing or
malformed) is read defensively, looked up, and reported back on the
output entry, completely unchanged from whatever was actually
present on the input.

``capital`` is read defensively and is only ever treated as valid
when it is an ``int`` or ``float`` and NOT a ``bool`` (``bool`` is a
``int`` subclass in Python, so it is explicitly excluded) and is
non-negative. Any other case -- ``None``, a ``str``, a ``bool``, or a
negative number -- behaves exactly as though ``capital`` were ``0``;
this never raises.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"allocations": [
            {"symbol": "BBCA", "action": "BUY", "risk": "LOW",
             "plan": "LONG_TERM", "position_size": "FULL",
             "allocated_capital": 100000000},
            ...
        ]},
        error=None,
        metadata={},
    )

Each allocation entry carries exactly ``"symbol"``, ``"action"``,
``"risk"``, ``"plan"``, ``"position_size"``, and
``"allocated_capital"`` -- nothing more. ``"action"``, ``"risk"``,
``"plan"``, and ``"position_size"`` are always the exact raw values
read from the input (including ``None`` for anything missing or
malformed) -- never a normalized substitute. ``success`` is
unconditionally ``True`` and ``error`` is unconditionally ``None`` --
this Skill calls no Tool and has no failure mode of its own;
malformed input simply yields ``0`` allocated-capital entries, never
a failure.

``context.parameters`` is read defensively: if it is not a
``Mapping`` at all, or its ``"plans"`` value is missing or not a
``list``, this method behaves as though ``"plans"`` were an empty
list -- never raising, and producing ``{"allocations": []}``. If its
``"capital"`` value is missing or invalid (per the rules above),
this method behaves as though ``"capital"`` were ``0`` -- never
raising.

No new abstraction of any kind was introduced to build the mapping:
no ``CapitalAllocator``, ``AllocationEngine``, ``MoneyManager``,
``PortfolioOptimizer``, ``Strategy``, ``Manager``, ``Coordinator``,
``Planner``, ``Workflow``, ``Service``, ``Repository``, ``Provider``,
``Factory``, ``Helper``, or ``Utility`` module. The per-entry loop,
the single fixed five-entry ``dict`` literal percentage table, and
the ``dict.get(...)`` lookup all live directly inline inside
``execute()`` -- exactly the same shape
``Orchestration.position_sizing_skill.PositionSizingSkill`` already
uses one layer down.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private, nested or module-
level) beyond the three ``BaseSkill``-required members, and any
Kelly-criterion, volatility-adjusted, stop-loss, or portfolio-
optimization calculation. No AI, no LLM calls (including Ollama), no
provider calls, no service calls, no repository calls, no database
access, no Tool calls of any kind (this Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` -- it
consumes an already-sized position, it does not produce one).

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import
``Orchestration.position_sizing_skill.PositionSizingSkill``,
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


class CapitalAllocationSkill(BaseSkill):
    """The project's first capital-allocation layer: turns each
    already-sized ``position_size`` label into a single, concrete
    ``allocated_capital`` amount via one fixed, deterministic
    percentage lookup table applied to a total ``capital`` figure.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``allocate``, ``size``, ``compute_stop_loss``, or ``exposure``
    anywhere on this class; the per-entry loop and the single lookup
    table both live entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"capital_allocation"``.
        """
        return "capital_allocation"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Turn each planned position size into an allocated amount of capital."``.
        """
        return "Turn each planned position size into an allocated amount of capital."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["plans"]`` and
        ``context.parameters["capital"]`` and produce one allocation
        entry per plan via a single, fixed percentage lookup table
        keyed on ``position_size``.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-sized entries (each an
        already-produced ``PositionSizingSkill``-shaped
        ``{"symbol": ..., "action": ..., "risk": ..., "plan": ...,
        "position_size": ...}`` mapping) and attaches an allocated
        capital amount to each one.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"plans"`` value is missing or
        not a ``list``, this method behaves as though ``"plans"``
        were an empty list -- never raising, and producing
        ``{"allocations": []}``. Its ``"capital"`` value is only
        treated as valid when it is an ``int`` or ``float`` (never a
        ``bool``) and non-negative -- any other case behaves exactly
        as though ``"capital"`` were ``0``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``PositionSizingSkill``:

            * ``symbol``/``action``/``risk``/``plan`` are read from
              ``entry.get(...)`` if ``entry`` is a ``dict``, else
              ``None``. None of these are ever normalized -- they are
              reported back unchanged on the output entry.
            * ``position_size`` is read from
              ``entry.get("position_size")`` if ``entry`` is a
              ``dict``, else ``None``. Never normalized -- looked up
              exactly as read, and reported back unchanged.

        ``position_size`` is looked up in one fixed, five-entry
        ``dict`` literal mapping every LOCKED value to its
        percentage of ``capital``; any value not present in that
        table (an unrecognized ``position_size``, including ``None``
        from a missing or malformed entry) falls back to ``0`` via
        ``dict.get(...)``'s own default argument -- no separate
        branch, no ``if``/``elif`` chain of any kind. The looked-up
        percentage is then multiplied straight through by the valid
        ``capital`` figure -- the only calculation this Skill ever
        performs.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"plans"`` list and a ``"capital"``
                value, in the shape documented above. Passed through
                defensively -- never copied, never mutated, and this
                method never raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"allocations": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        plan_entries = []
        capital = 0
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_plans = parameters.get("plans")
            if isinstance(raw_plans, list):
                plan_entries = raw_plans

            raw_capital = parameters.get("capital")
            if isinstance(raw_capital, (int, float)) and not isinstance(raw_capital, bool) and raw_capital >= 0:
                capital = raw_capital

        percentage_table = {
            "FULL": 1.0,
            "HALF": 0.5,
            "SMALL": 0.25,
            "AVOID": 0.0,
            "UNKNOWN": 0.0,
        }

        allocations = []
        for entry in plan_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            action = entry.get("action") if isinstance(entry, dict) else None
            risk = entry.get("risk") if isinstance(entry, dict) else None
            plan = entry.get("plan") if isinstance(entry, dict) else None
            position_size = entry.get("position_size") if isinstance(entry, dict) else None

            allocated_capital = capital * percentage_table.get(position_size, 0.0)
            if isinstance(allocated_capital, float) and allocated_capital.is_integer():
                allocated_capital = int(allocated_capital)

            allocations.append({
                "symbol": symbol,
                "action": action,
                "risk": risk,
                "plan": plan,
                "position_size": position_size,
                "allocated_capital": allocated_capital,
            })

        return SkillResult(
            success=True,
            output={"allocations": allocations},
            error=None,
            metadata={},
        )