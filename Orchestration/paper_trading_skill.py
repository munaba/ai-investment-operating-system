"""PaperTradingSkill -- the project's first simulated-execution layer
(Phase 11, Sprint 128).

Where ``Orchestration.order_validation_skill.OrderValidationSkill``
attaches a ``status``/``reason`` verdict to each already-generated
order, no existing Skill ever turned that verdict into a simulated
execution outcome. This Skill closes that gap: it reads a list of
already-validated orders (each carrying the ``"status"`` value a
prior ``OrderValidationSkill.execute()`` call already produced) and
attaches a single, deterministic ``"execution_status"``/``"message"``
pair to every one of them.

This Skill simulates order execution. It does NOT connect to any
broker. It does NOT place real orders. It does NOT make an HTTP
request, open a websocket, or touch any network or persistence layer
of any kind. It simply converts an already-validated order into a
simulated execution outcome via one fixed, ordered rule chain -- the
exact same paper-trading boundary
``Orchestration.capital_allocation_skill.CapitalAllocationSkill`` and
``Orchestration.order_validation_skill.OrderValidationSkill`` already
established one layer down.

Input shape (read from ``context.parameters["orders"]``, a
``list``):

    {
        "orders": [
            {"symbol": "BBCA", "action": "BUY", "capital": 100000000,
             "status": "APPROVED", "reason": "ready for execution"},
            ...
        ]
    }

Only ``"symbol"``, ``"action"``, ``"capital"``, and ``"status"`` are
ever read from an order entry. ``"reason"`` (or anything else an
entry may carry) is never inspected; this Skill knows nothing about
it and would behave identically if it were absent entirely.

Execution rules (LOCKED), applied in this exact order, the first
matching rule wins:

    Rule 1: status == "APPROVED"
            -> execution_status = "EXECUTED",
               message = "paper trade executed"
    Rule 2: status == "HOLD"
            -> execution_status = "PENDING",
               message = "waiting for market confirmation"
    Rule 3: status == "EXIT"
            -> execution_status = "CLOSED",
               message = "paper position closed"
    Rule 4: everything else
            -> execution_status = "SKIPPED",
               message = "order not executed"

This Skill deliberately does NOT normalize ``status`` (or
``symbol``/``action``/``capital``) in any way (no case-folding, no
stripping) -- an unrecognized status, a missing ``"status"`` key, or
a missing/non-``dict`` entry itself all fall straight through to
Rule 4.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"executions": [
            {"symbol": "BBCA", "action": "BUY", "capital": 100000000,
             "execution_status": "EXECUTED",
             "message": "paper trade executed"},
            ...
        ]},
        error=None,
        metadata={},
    )

Each execution entry carries exactly ``"symbol"``, ``"action"``,
``"capital"``, ``"execution_status"``, and ``"message"`` -- nothing
more. ``"symbol"``, ``"action"``, and ``"capital"`` are always the
exact raw values read from the input (including ``None`` for
anything missing or malformed) -- never a normalized substitute.
``success`` is unconditionally ``True`` and ``error`` is
unconditionally ``None`` -- this Skill calls no Tool and has no
failure mode of its own; malformed input simply yields a
``"SKIPPED"`` execution, never a failure.

``context.parameters`` is read defensively: if it is not a
``Mapping`` at all, or its ``"orders"`` value is missing or not a
``list``, this method behaves as though ``"orders"`` were an empty
list -- never raising, and producing ``{"executions": []}``.

No new abstraction of any kind was introduced to build the
simulation. No ``TradeSimulator``, ``PaperBroker``, ``OrderEngine``,
``ExecutionManager``, ``Strategy``, ``Planner``, ``Workflow``,
``Factory``, ``Registry``, ``Helper``, or ``Provider`` module. The
per-entry loop and the single ``if``/``elif``/``elif``/``else`` rule
chain both live directly inline inside ``execute()`` -- exactly the
same shape ``OrderValidationSkill`` already uses one layer down.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private, nested or module-
level) beyond the three ``BaseSkill``-required members, and any
broker connection, order routing, HTTP request, websocket,
persistence, threading, or scheduling logic of any kind. No AI, no
LLM calls (including Ollama), no provider calls, no service calls, no
repository calls, no database access, no Tool calls of any kind (this
Skill never calls ``self.execute_tool()``/
``self.execute_tool_result()`` -- it consumes an already-validated
order, it does not produce or validate one, and it never touches a
real broker or market).

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import
``Orchestration.order_validation_skill.OrderValidationSkill``,
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
``ollama``, ``sqlite3``, ``pandas``, ``numpy``, ``yfinance``,
``websocket``, ``asyncio``, or ``threading``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class PaperTradingSkill(BaseSkill):
    """The project's first simulated-execution layer: turns each
    already-validated order into a single, deterministic
    ``execution_status``/``message`` outcome via one fixed, ordered
    rule chain.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill``-required members is deliberately absent --
    there is no ``execute_order``, ``simulate``, or ``fill`` anywhere
    on this class; the per-entry loop and the single rule chain both
    live entirely inline inside ``execute()`` itself. This Skill
    never connects to a broker, never places a real order, and never
    touches a network or persistence layer of any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"paper_trading"``.
        """
        return "paper_trading"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Convert each validated order into a simulated paper-trading execution outcome."``.
        """
        return "Convert each validated order into a simulated paper-trading execution outcome."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["orders"]`` and
        produce one simulated execution outcome per order entry via a
        single, fixed, ordered rule chain.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never connects to a broker, places a real order, or makes any
        network call. It consumes a ``list`` of already-validated
        entries (each an already-produced
        ``OrderValidationSkill``-shaped ``{"symbol": ..., "action":
        ..., "capital": ..., "status": ..., ...}`` mapping) and
        attaches an ``execution_status``/``message`` outcome to each
        one.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"orders"`` value is missing or
        not a ``list``, this method behaves as though ``"orders"``
        were an empty list -- never raising, and producing
        ``{"executions": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``OrderValidationSkill``:

            * ``symbol``/``action``/``capital``/``status`` are read
              from ``entry.get(...)`` if ``entry`` is a ``dict``,
              else ``None``. None of these are ever normalized --
              ``symbol``/``action``/``capital`` are reported back
              unchanged on the output entry.

        The four rules below are checked in this exact order -- the
        first one that matches wins, and only one
        execution_status/message pair is ever assigned per entry:

            Rule 1: ``status == "APPROVED"`` ->
                    ``execution_status="EXECUTED"``,
                    ``message="paper trade executed"``.
            Rule 2: ``status == "HOLD"`` ->
                    ``execution_status="PENDING"``,
                    ``message="waiting for market confirmation"``.
            Rule 3: ``status == "EXIT"`` ->
                    ``execution_status="CLOSED"``,
                    ``message="paper position closed"``.
            Rule 4: anything else (including an unrecognized status,
                    a missing status, or a malformed entry) ->
                    ``execution_status="SKIPPED"``,
                    ``message="order not executed"``.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing an ``"orders"`` list, in the shape
                documented above. Passed through defensively -- never
                copied, never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"executions": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        order_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_orders = parameters.get("orders")
            if isinstance(raw_orders, list):
                order_entries = raw_orders

        executions = []
        for entry in order_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            action = entry.get("action") if isinstance(entry, dict) else None
            capital = entry.get("capital") if isinstance(entry, dict) else None
            status = entry.get("status") if isinstance(entry, dict) else None

            if status == "APPROVED":
                execution_status = "EXECUTED"
                message = "paper trade executed"
            elif status == "HOLD":
                execution_status = "PENDING"
                message = "waiting for market confirmation"
            elif status == "EXIT":
                execution_status = "CLOSED"
                message = "paper position closed"
            else:
                execution_status = "SKIPPED"
                message = "order not executed"

            executions.append({
                "symbol": symbol,
                "action": action,
                "capital": capital,
                "execution_status": execution_status,
                "message": message,
            })

        return SkillResult(
            success=True,
            output={"executions": executions},
            error=None,
            metadata={},
        )