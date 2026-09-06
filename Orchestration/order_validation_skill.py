"""OrderValidationSkill -- the project's first order-validation layer
(Phase 11, Sprint 127).

Where ``Orchestration.capital_allocation_skill.CapitalAllocationSkill``
attaches an ``allocated_capital`` amount to each already-planned
entry, no existing Skill ever checked whether an already-allocated
entry is actually safe to hand off for execution. This Skill closes
that gap: it reads a list of already-allocated entries (each carrying
the ``"action"`` and ``"capital"`` values a prior
``CapitalAllocationSkill.execute()`` call already produced) and
attaches a single, deterministic ``"status"``/``"reason"`` pair to
every one of them.

This Skill does not execute orders. It only validates them. There is
no broker call, no order routing, no queueing, no scheduling, and no
retry anywhere in this file -- ``execute()`` produces a validation
verdict and nothing more.

Input shape (read from ``context.parameters["allocations"]``, a
``list``):

    {
        "allocations": [
            {"symbol": "BBCA", "action": "BUY", "risk": "LOW",
             "plan": "LONG_TERM", "position_size": "FULL",
             "capital": 100000000},
            ...
        ]
    }

Only ``"symbol"``, ``"action"``, and ``"capital"`` are ever read from
an allocation entry. ``"risk"``, ``"plan"``, and ``"position_size"``
(or anything else an entry may carry) are never inspected; this Skill
knows nothing about them and would behave identically if they were
absent entirely.

Validation rules (LOCKED), applied in this exact order, the first
matching rule wins:

    Rule 1: action == "BUY" AND capital > 0
            -> status = "APPROVED", reason = "ready for execution"
    Rule 2: action == "WAIT"
            -> status = "HOLD",     reason = "waiting for better opportunity"
    Rule 3: action == "SELL"
            -> status = "EXIT",     reason = "exit position"
    Rule 4: everything else
            -> status = "REJECTED", reason = "invalid order"

Rule 4 is the catch-all: a ``"BUY"`` action paired with a
non-positive/invalid ``capital`` falls through Rule 1 and, since it is
neither ``"WAIT"`` nor ``"SELL"``, lands on Rule 4 -- exactly as
written in the sprint spec. This Skill deliberately does NOT
normalize ``action`` in any way (no case-folding, no stripping) -- an
unrecognized action, a missing ``"action"`` key, or a missing/non-
``dict`` entry itself all fall straight through to Rule 4.

``capital`` is read defensively and is only ever treated as
satisfying "capital > 0" when it is an ``int`` or ``float`` and NOT a
``bool`` (``bool`` is a ``int`` subclass in Python, so it is
explicitly excluded) and is strictly greater than zero. Any other
case -- ``None``, a ``str``, a ``bool``, zero, or a negative number --
behaves exactly as though the capital check failed; this never
raises. The raw ``capital`` value is still reported back on the
output entry, completely unchanged from whatever was actually present
on the input.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"orders": [
            {"symbol": "BBCA", "action": "BUY", "capital": 100000000,
             "status": "APPROVED", "reason": "ready for execution"},
            ...
        ]},
        error=None,
        metadata={},
    )

Each order entry carries exactly ``"symbol"``, ``"action"``,
``"capital"``, ``"status"``, and ``"reason"`` -- nothing more.
``"symbol"``, ``"action"``, and ``"capital"`` are always the exact
raw values read from the input (including ``None`` for anything
missing or malformed) -- never a normalized substitute. ``success``
is unconditionally ``True`` and ``error`` is unconditionally
``None`` -- this Skill calls no Tool and has no failure mode of its
own; malformed input simply yields a ``"REJECTED"`` order, never a
failure.

``context.parameters`` is read defensively: if it is not a
``Mapping`` at all, or its ``"allocations"`` value is missing or not
a ``list``, this method behaves as though ``"allocations"`` were an
empty list -- never raising, and producing ``{"orders": []}``.

No new abstraction of any kind was introduced to build the
validation. No ``OrderValidator``, ``ExecutionEngine``,
``TradeManager``, ``RiskCoordinator``, ``Strategy``, ``Planner``,
``Workflow``, ``Factory``, ``Registry``, ``Helper``, or ``Provider``
module. The per-entry loop and the single ``if``/``elif``/``elif``/
``else`` rule chain both live directly inline inside ``execute()`` --
exactly the same shape ``CapitalAllocationSkill`` already uses one
layer down.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private, nested or module-
level) beyond the three ``BaseSkill``-required members, and any
broker call, order routing, execution, or scheduling logic of any
kind. No AI, no LLM calls (including Ollama), no provider calls, no
service calls, no repository calls, no database access, no Tool
calls of any kind (this Skill never calls ``self.execute_tool()``/
``self.execute_tool_result()`` -- it consumes an already-allocated
trade, it does not produce or execute one).

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import
``Orchestration.capital_allocation_skill.CapitalAllocationSkill``,
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


class OrderValidationSkill(BaseSkill):
    """The project's first order-validation layer: turns each
    already-allocated trade entry into a single, deterministic
    ``status``/``reason`` verdict via one fixed, ordered rule chain.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill``-required members is deliberately absent --
    there is no ``validate``, ``check``, or ``verify`` anywhere on
    this class; the per-entry loop and the single rule chain both
    live entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"order_validation"``.
        """
        return "order_validation"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Validate whether each generated trade allocation is safe to submit for execution."``.
        """
        return "Validate whether each generated trade allocation is safe to submit for execution."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["allocations"]``
        and produce one order-validation verdict per allocation entry
        via a single, fixed, ordered rule chain.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-allocated entries (each an
        already-produced ``CapitalAllocationSkill``-shaped
        ``{"symbol": ..., "action": ..., "capital": ..., ...}``
        mapping) and attaches a ``status``/``reason`` verdict to each
        one.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"allocations"`` value is missing
        or not a ``list``, this method behaves as though
        ``"allocations"`` were an empty list -- never raising, and
        producing ``{"orders": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``CapitalAllocationSkill``:

            * ``symbol``/``action``/``capital`` are read from
              ``entry.get(...)`` if ``entry`` is a ``dict``, else
              ``None``. None of these are ever normalized -- they are
              reported back unchanged on the output entry.

        The four rules below are checked in this exact order -- the
        first one that matches wins, and only one status/reason pair
        is ever assigned per entry:

            Rule 1: ``action == "BUY"`` and ``capital`` is a
                    non-``bool`` ``int``/``float`` strictly greater
                    than zero -> ``status="APPROVED"``,
                    ``reason="ready for execution"``.
            Rule 2: ``action == "WAIT"`` -> ``status="HOLD"``,
                    ``reason="waiting for better opportunity"``.
            Rule 3: ``action == "SELL"`` -> ``status="EXIT"``,
                    ``reason="exit position"``.
            Rule 4: anything else (including a ``"BUY"`` paired with
                    invalid/non-positive capital, an unrecognized
                    action, a missing action, or a malformed entry)
                    -> ``status="REJECTED"``, ``reason="invalid order"``.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing an ``"allocations"`` list, in the shape
                documented above. Passed through defensively -- never
                copied, never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"orders": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        allocation_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_allocations = parameters.get("allocations")
            if isinstance(raw_allocations, list):
                allocation_entries = raw_allocations

        orders = []
        for entry in allocation_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            action = entry.get("action") if isinstance(entry, dict) else None
            capital = entry.get("capital") if isinstance(entry, dict) else None

            capital_is_positive_number = (
                isinstance(capital, (int, float))
                and not isinstance(capital, bool)
                and capital > 0
            )

            if action == "BUY" and capital_is_positive_number:
                status = "APPROVED"
                reason = "ready for execution"
            elif action == "WAIT":
                status = "HOLD"
                reason = "waiting for better opportunity"
            elif action == "SELL":
                status = "EXIT"
                reason = "exit position"
            else:
                status = "REJECTED"
                reason = "invalid order"

            orders.append({
                "symbol": symbol,
                "action": action,
                "capital": capital,
                "status": status,
                "reason": reason,
            })

        return SkillResult(
            success=True,
            output={"orders": orders},
            error=None,
            metadata={},
        )