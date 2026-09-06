"""TradingDecisionAgent -- final decision pipeline (Phase 10,
Sprint 126).

This module extends the ``TradingDecisionAgent`` introduced in
Sprint 123 (``MarketAnalysisSkill`` -> ``RecommendationSkill`` ->
``PositionRiskSkill`` -> ``TradePlanSkill``) so that it runs all the
way through the two Skills added since (``PositionSizingSkill`` in
Sprint 124, ``CapitalAllocationSkill`` in Sprint 125):

    Task
      |
      v
    MarketAnalysisSkill
      |
      v
    RecommendationSkill
      |
      v
    PositionRiskSkill
      |
      v
    TradePlanSkill
      |
      v
    PositionSizingSkill
      |
      v
    CapitalAllocationSkill

Sprint 154 extends this same chain, in the same inline,
never-branching style, through the eight remaining existing
production Skills, each fed from its immediate predecessor's own
output exactly as that Skill already documents:

    CapitalAllocationSkill
      |
      v
    OrderValidationSkill -> PaperTradingSkill -> TradeHistorySkill
      -> PortfolioUpdateSkill -> PortfolioMonitorSkill
      -> PortfolioPerformanceSkill -> PortfolioAlertSkill
      -> PortfolioReportSkill

No Skill's own logic, parameters, or output shape is changed by this
extension -- only the sequence in which the already-existing Skills
are called grows. ``execute()`` now returns fourteen ``SkillResult``
entries (the original six plus these eight), each still forwarded by
identity and unmodified; ``\"portfolio_report\"`` carries the final
``PortfolioReportSkill`` result.

This is not a planner, not a graph, not a workflow engine, and not
dynamic routing -- there is exactly one call sequence, written
directly inline inside ``execute()``, and it never branches: every
call to ``TradingDecisionAgent.execute()`` runs the exact same six
Skill calls, in the exact same order, every time. No Skill's own
behavior is touched by this change -- this module only orchestrates
already-shipped, already-tested Skills.

Construction (LOCKED): this Agent is handed exactly six
collaborators at construction time, already-constructed Skill
instances, in pipeline order --

    TradingDecisionAgent(
        market_analysis_skill,
        recommendation_skill,
        position_risk_skill,
        trade_plan_skill,
        position_sizing_skill,
        capital_allocation_skill,
    )

-- and stores each, unmodified, by identity. Nothing about *how* any
of them is able to resolve its own Tools (e.g. whether
``_resolve_tool`` was ever injected onto ``market_analysis_skill`` by
an ``Executor``) is this Agent's concern -- that wiring, if any,
happens entirely outside this module, before the Skill instance is
ever handed to ``TradingDecisionAgent.__init__``. Only
``MarketAnalysisSkill`` ever calls a Tool; the other five Skills call
no Tool at all, so no such wiring is ever needed for any of them.

``execute(task)`` (LOCKED): the entire method body is a straight-line
sequence, all inline, no helper method, no branching beyond the
defensive reads described below --

    1. Read a ``"symbols"`` list out of ``task.metadata`` (the only
       place a ``Task`` value object carries arbitrary
       caller-supplied data). Read defensively, using the same
       never-raise ``isinstance()``/``.get()`` style already used
       throughout every Skill in this chain: if ``task.metadata`` is
       not a ``Mapping``, or its ``"symbols"`` value is missing or
       not a ``list``, this step yields an empty list -- never
       raising. The same ``task.metadata`` is also read, the same
       defensive way, for a ``"capital"`` value: it is only ever
       treated as valid when it is an ``int``/``float`` and not a
       ``bool`` -- anything else (missing, wrong type, or a ``bool``)
       behaves exactly as though ``"capital"`` were ``0``, never
       raising.
    2. Build ``SkillContext(task=task, parameters={"symbols":
       symbols}, metadata={}, tool_context_factory=None)`` and call
       ``self._market_analysis_skill.execute(...)`` exactly once,
       producing ``market_result``.
    3. Read a ``"stocks"`` list out of ``market_result.output`` the
       same defensive way, build ``SkillContext(task=task,
       parameters={"stocks": stocks}, metadata={},
       tool_context_factory=None)``, and call
       ``self._recommendation_skill.execute(...)`` exactly once,
       producing ``recommendation_result``.
    4. Read an ``"actions"`` list out of ``recommendation_result
       .output`` the same defensive way, build
       ``SkillContext(task=task, parameters={"actions": actions},
       metadata={}, tool_context_factory=None)``, and call
       ``self._position_risk_skill.execute(...)`` exactly once,
       producing ``risk_result``.
    5. Read a ``"risk"`` list out of ``risk_result.output`` the same
       defensive way, build ``SkillContext(task=task,
       parameters={"risk": risk}, metadata={},
       tool_context_factory=None)``, and call
       ``self._trade_plan_skill.execute(...)`` exactly once,
       producing ``trade_plan_result``.
    6. Read a ``"plans"`` list out of ``trade_plan_result.output``
       the same defensive way, build ``SkillContext(task=task,
       parameters={"plans": plans}, metadata={},
       tool_context_factory=None)``, and call
       ``self._position_sizing_skill.execute(...)`` exactly once,
       producing ``position_size_result``.
    7. Read a ``"positions"`` list out of ``position_size_result
       .output`` the same defensive way -- ``"positions"`` is
       ``PositionSizingSkill``'s own output key (each entry now
       carrying a ``"position_size"`` label alongside the
       ``symbol``/``action``/``risk``/``plan`` it already carried).
       Build ``SkillContext(task=task, parameters={"capital":
       capital, "plans": positions}, metadata={},
       tool_context_factory=None)`` -- ``"plans"`` because that is
       ``CapitalAllocationSkill``'s own documented parameter key for
       this list (the same key name ``TradePlanSkill``/
       ``PositionSizingSkill`` already use one layer down, reused by
       ``CapitalAllocationSkill`` for its own already-sized input) --
       and call ``self._capital_allocation_skill.execute(...)``
       exactly once, producing ``capital_allocation_result``.

Each defensive read (steps 1, 3, 4, 5, 6, 7) is what makes the
pipeline never raise and never stop: if an upstream Skill's own
``success`` is ``False`` but its ``output`` still carries the
expected key as a (possibly empty) list -- which is how every Skill
in this chain behaves, since none of them ever raises or omits its
output key -- the pipeline simply continues with whatever list is
actually present, including an empty one. There is no
``if result.success`` check, no early return, and no exception
handling anywhere in this method; a genuinely malformed ``.output``
(not a ``Mapping``, or missing/non-``list`` key) is treated exactly
the same as a missing ``task.metadata`` -- it yields an empty list
for the next step, never a raise and never a stop. The same applies
to ``"capital"``: a missing or malformed ``task.metadata["capital"]``
never raises and never stops the pipeline -- ``CapitalAllocationSkill``
is still called, with a safe default of ``0``.

Overall success/error (documented behavior, not a separate return
field): the caller can compute an overall success as
``market_result.success and recommendation_result.success and
risk_result.success and trade_plan_result.success and
position_size_result.success and
capital_allocation_result.success``, and, when that is ``False``, an
aggregate error by joining every non-``None`` ``.error`` string, in
the same fixed order (market, recommendation, risk, trade_plan,
position_size, capital_allocation). This Agent does not itself
compute or return either value -- it forwards all six
``SkillResult`` objects unmodified, by identity, and it is exactly
from those six objects that both properties are always derivable.

Return value (LOCKED): a plain ``dict`` literal with exactly six
keys -- ``"market"``, ``"recommendation"``, ``"risk"``,
``"trade_plan"``, ``"position_size"``, ``"capital_allocation"`` --
each holding the exact ``SkillResult`` object the corresponding
Skill produced, forwarded by identity, completely unchanged. Nothing
is merged, recomputed, reshaped, or otherwise derived from them.

No new abstraction of any kind was introduced to build this
coordination: no ``AgentManager``, ``AgentEngine``,
``AgentCoordinator``, ``AgentRunner``, ``AgentExecutor``,
``AgentFactory``, ``Dispatcher``, ``Router``, ``Pipeline``,
``Workflow``, ``Graph``, ``Node``, ``Service``, ``Repository``,
``Planner``, ``Strategy``, ``Registry``, ``Analyzer``, ``Helper``, or
``Utility`` module. The symbol/capital extraction, the six
``SkillContext`` constructions, and the six delegated calls all live
directly inline inside ``execute()``.

Explicitly NOT part of this milestone: any attribute beyond the six
constructor-injected Skill references, any cache, any configuration,
any helper method (public or private) beyond ``execute()`` itself,
and any of ``run()``, ``chat()``, ``analyze()``, ``rank()``,
``recommend()``, or ``allocate()``. No AI, no LLM calls (including
Ollama), no provider calls, no service calls, no repository calls,
and no Tool calls of any kind, and no reasoning, ranking, scoring, or
allocation logic anywhere in this file -- all of that remains each
Skill's own responsibility, never this Agent's. No ``async``, no
``threading``, no ``queue``, no retry, and no caching anywhere in
this module.

Dependencies (LOCKED): this module imports
``Orchestration.market_analysis_skill.MarketAnalysisSkill``,
``Orchestration.recommendation_skill.RecommendationSkill``,
``Orchestration.position_risk_skill.PositionRiskSkill``,
``Orchestration.trade_plan_skill.TradePlanSkill``,
``Orchestration.position_sizing_skill.PositionSizingSkill``,
``Orchestration.capital_allocation_skill.CapitalAllocationSkill``
(each for its type annotation only -- never instantiated here),
``Orchestration.skill_context.SkillContext``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.capital_allocation_skill import CapitalAllocationSkill
from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.order_validation_skill import OrderValidationSkill
from Orchestration.paper_trading_skill import PaperTradingSkill
from Orchestration.portfolio_alert_skill import PortfolioAlertSkill
from Orchestration.portfolio_monitor_skill import PortfolioMonitorSkill
from Orchestration.portfolio_performance_skill import PortfolioPerformanceSkill
from Orchestration.portfolio_report_skill import PortfolioReportSkill
from Orchestration.portfolio_update_skill import PortfolioUpdateSkill
from Orchestration.position_risk_skill import PositionRiskSkill
from Orchestration.position_sizing_skill import PositionSizingSkill
from Orchestration.recommendation_skill import RecommendationSkill
from Orchestration.skill_context import SkillContext
from Orchestration.trade_history_skill import TradeHistorySkill
from Orchestration.trade_plan_skill import TradePlanSkill


class TradingDecisionAgent:
    """A simple, deterministic coordinator: runs
    ``MarketAnalysisSkill`` -> ``RecommendationSkill`` ->
    ``PositionRiskSkill`` -> ``TradePlanSkill`` ->
    ``PositionSizingSkill`` -> ``CapitalAllocationSkill``, in that
    fixed order, and collects all six results.

    No inheritance, no state beyond the six collaborators handed in
    at construction, and no helper methods beyond ``execute()``
    itself -- there is no ``run``, ``chat``, ``analyze``, ``rank``,
    ``recommend``, or ``allocate`` anywhere on this class; the
    symbol/capital extraction, the six ``SkillContext``
    constructions, and the six Skill calls all live entirely inline
    inside ``execute()`` itself.
    """

    def __init__(
        self,
        market_analysis_skill: MarketAnalysisSkill,
        recommendation_skill: RecommendationSkill,
        position_risk_skill: PositionRiskSkill,
        trade_plan_skill: TradePlanSkill,
        position_sizing_skill: PositionSizingSkill,
        capital_allocation_skill: CapitalAllocationSkill,
        order_validation_skill: OrderValidationSkill,
        paper_trading_skill: PaperTradingSkill,
        trade_history_skill: TradeHistorySkill,
        portfolio_update_skill: PortfolioUpdateSkill,
        portfolio_monitor_skill: PortfolioMonitorSkill,
        portfolio_performance_skill: PortfolioPerformanceSkill,
        portfolio_alert_skill: PortfolioAlertSkill,
        portfolio_report_skill: PortfolioReportSkill,
    ) -> None:
        """Store the six Skills this Agent will call, in order.

        Args:
            market_analysis_skill: The already-constructed
                ``MarketAnalysisSkill`` instance called first. Stored
                by identity, never copied, never inspected, never
                wrapped. Any wiring it needs to resolve its own Tools
                (e.g. an injected ``_resolve_tool``) must already be
                in place before it is handed to this constructor.
            recommendation_skill: The already-constructed
                ``RecommendationSkill`` instance called second.
                Stored by identity, never copied, never inspected,
                never wrapped.
            position_risk_skill: The already-constructed
                ``PositionRiskSkill`` instance called third. Stored
                by identity, never copied, never inspected, never
                wrapped.
            trade_plan_skill: The already-constructed
                ``TradePlanSkill`` instance called fourth. Stored by
                identity, never copied, never inspected, never
                wrapped.
            position_sizing_skill: The already-constructed
                ``PositionSizingSkill`` instance called fifth. Stored
                by identity, never copied, never inspected, never
                wrapped.
            capital_allocation_skill: The already-constructed
                ``CapitalAllocationSkill`` instance called sixth and
                last. Stored by identity, never copied, never
                inspected, never wrapped.
        """
        self._market_analysis_skill = market_analysis_skill
        self._recommendation_skill = recommendation_skill
        self._position_risk_skill = position_risk_skill
        self._trade_plan_skill = trade_plan_skill
        self._position_sizing_skill = position_sizing_skill
        self._capital_allocation_skill = capital_allocation_skill
        self._order_validation_skill = order_validation_skill
        self._paper_trading_skill = paper_trading_skill
        self._trade_history_skill = trade_history_skill
        self._portfolio_update_skill = portfolio_update_skill
        self._portfolio_monitor_skill = portfolio_monitor_skill
        self._portfolio_performance_skill = portfolio_performance_skill
        self._portfolio_alert_skill = portfolio_alert_skill
        self._portfolio_report_skill = portfolio_report_skill

    def execute(self, task: Any) -> Any:
        """Run this Agent: call ``MarketAnalysisSkill``, then
        ``RecommendationSkill``, then ``PositionRiskSkill``, then
        ``TradePlanSkill``, then ``PositionSizingSkill``, then
        ``CapitalAllocationSkill``, in that fixed order, and return
        all six results.

        ``task.metadata`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"symbols"`` value is missing or
        not a ``list``, this method behaves as though ``"symbols"``
        were an empty list -- never raising on account of a
        malformed ``task``. The same ``task.metadata`` is read
        defensively for ``"capital"``: only a non-``bool``
        ``int``/``float`` is accepted, anything else behaves as
        though ``"capital"`` were ``0``. Each downstream Skill's own
        ``.output`` is read the exact same defensive way to obtain
        the list its successor needs (``"stocks"`` from
        ``market_result.output``, ``"actions"`` from
        ``recommendation_result.output``, ``"risk"`` from
        ``risk_result.output``, ``"plans"`` from
        ``trade_plan_result.output``, ``"positions"`` from
        ``position_size_result.output``) -- so the pipeline never
        raises and never stops, regardless of whether an upstream
        Skill's own ``success`` was ``True`` or ``False``, as long as
        its ``.output`` still carries the expected key in the
        expected shape (which every Skill in this chain always
        does).

        Args:
            task: Whatever the caller is asking this Agent to run.
                Expected to expose a ``.metadata`` mapping containing
                a ``"symbols"`` list and a ``"capital"`` number, in
                the same shape ``Orchestration.task.Task`` provides,
                but never validated to actually be a ``Task``
                instance -- only ``.metadata`` is ever read from it,
                and it is passed through by identity, unexamined
                otherwise, as every ``SkillContext``'s own ``task``
                field.

        Returns:
            A freshly built ``dict`` with exactly six keys --
            ``"market"``, ``"recommendation"``, ``"risk"``,
            ``"trade_plan"``, ``"position_size"``,
            ``"capital_allocation"`` -- each holding the exact
            ``SkillResult`` object the corresponding Skill produced,
            forwarded by identity, completely unchanged, never
            merged, recomputed, or otherwise derived from.

        Raises:
            Exception: any exception raised while constructing a
                ``SkillContext`` (for example ``SkillContextError``)
                or by any of the six Skills' ``execute()`` calls
                propagates unchanged -- never caught, never wrapped.
        """
        symbols = []
        capital = 0
        task_metadata = getattr(task, "metadata", None)
        if isinstance(task_metadata, Mapping):
            raw_symbols = task_metadata.get("symbols")
            if isinstance(raw_symbols, list):
                symbols = raw_symbols

            raw_capital = task_metadata.get("capital")
            if isinstance(raw_capital, (int, float)) and not isinstance(raw_capital, bool):
                capital = raw_capital

        market_context = SkillContext(
            task=task,
            parameters={"symbols": symbols},
            metadata={},
            tool_context_factory=None,
        )
        market_result = self._market_analysis_skill.execute(market_context)

        stocks = []
        market_output = getattr(market_result, "output", None)
        if isinstance(market_output, Mapping):
            raw_stocks = market_output.get("stocks")
            if isinstance(raw_stocks, list):
                stocks = raw_stocks

        recommendation_context = SkillContext(
            task=task,
            parameters={"stocks": stocks},
            metadata={},
            tool_context_factory=None,
        )
        recommendation_result = self._recommendation_skill.execute(
            recommendation_context
        )

        actions = []
        recommendation_output = getattr(recommendation_result, "output", None)
        if isinstance(recommendation_output, Mapping):
            raw_actions = recommendation_output.get("actions")
            if isinstance(raw_actions, list):
                actions = raw_actions

        risk_context = SkillContext(
            task=task,
            parameters={"actions": actions},
            metadata={},
            tool_context_factory=None,
        )
        risk_result = self._position_risk_skill.execute(risk_context)

        risk = []
        risk_output = getattr(risk_result, "output", None)
        if isinstance(risk_output, Mapping):
            raw_risk = risk_output.get("risk")
            if isinstance(raw_risk, list):
                risk = raw_risk

        trade_plan_context = SkillContext(
            task=task,
            parameters={"risk": risk},
            metadata={},
            tool_context_factory=None,
        )
        trade_plan_result = self._trade_plan_skill.execute(trade_plan_context)

        plans = []
        trade_plan_output = getattr(trade_plan_result, "output", None)
        if isinstance(trade_plan_output, Mapping):
            raw_plans = trade_plan_output.get("plans")
            if isinstance(raw_plans, list):
                plans = raw_plans

        position_size_context = SkillContext(
            task=task,
            parameters={"plans": plans},
            metadata={},
            tool_context_factory=None,
        )
        position_size_result = self._position_sizing_skill.execute(
            position_size_context
        )

        positions = []
        position_size_output = getattr(position_size_result, "output", None)
        if isinstance(position_size_output, Mapping):
            raw_positions = position_size_output.get("positions")
            if isinstance(raw_positions, list):
                positions = raw_positions

        capital_allocation_context = SkillContext(
            task=task,
            parameters={"capital": capital, "plans": positions},
            metadata={},
            tool_context_factory=None,
        )
        capital_allocation_result = self._capital_allocation_skill.execute(
            capital_allocation_context
        )

        allocations = []
        capital_allocation_output = getattr(capital_allocation_result, "output", None)
        if isinstance(capital_allocation_output, Mapping):
            raw_allocations = capital_allocation_output.get("allocations")
            if isinstance(raw_allocations, list):
                allocations = raw_allocations

        order_validation_context = SkillContext(
            task=task,
            parameters={"allocations": allocations},
            metadata={},
            tool_context_factory=None,
        )
        order_validation_result = self._order_validation_skill.execute(
            order_validation_context
        )

        orders = []
        order_validation_output = getattr(order_validation_result, "output", None)
        if isinstance(order_validation_output, Mapping):
            raw_orders = order_validation_output.get("orders")
            if isinstance(raw_orders, list):
                orders = raw_orders

        paper_trading_context = SkillContext(
            task=task,
            parameters={"orders": orders},
            metadata={},
            tool_context_factory=None,
        )
        paper_trading_result = self._paper_trading_skill.execute(
            paper_trading_context
        )

        executions = []
        paper_trading_output = getattr(paper_trading_result, "output", None)
        if isinstance(paper_trading_output, Mapping):
            raw_executions = paper_trading_output.get("executions")
            if isinstance(raw_executions, list):
                executions = raw_executions

        trade_history_context = SkillContext(
            task=task,
            parameters={"executions": executions},
            metadata={},
            tool_context_factory=None,
        )
        trade_history_result = self._trade_history_skill.execute(
            trade_history_context
        )

        history = []
        trade_history_output = getattr(trade_history_result, "output", None)
        if isinstance(trade_history_output, Mapping):
            raw_history = trade_history_output.get("history")
            if isinstance(raw_history, list):
                history = raw_history

        portfolio_update_context = SkillContext(
            task=task,
            parameters={"history": history},
            metadata={},
            tool_context_factory=None,
        )
        portfolio_update_result = self._portfolio_update_skill.execute(
            portfolio_update_context
        )

        portfolio = []
        portfolio_update_output = getattr(portfolio_update_result, "output", None)
        if isinstance(portfolio_update_output, Mapping):
            raw_portfolio = portfolio_update_output.get("portfolio")
            if isinstance(raw_portfolio, list):
                portfolio = raw_portfolio

        portfolio_monitor_context = SkillContext(
            task=task,
            parameters={"portfolio": portfolio},
            metadata={},
            tool_context_factory=None,
        )
        portfolio_monitor_result = self._portfolio_monitor_skill.execute(
            portfolio_monitor_context
        )

        monitor = []
        portfolio_monitor_output = getattr(portfolio_monitor_result, "output", None)
        if isinstance(portfolio_monitor_output, Mapping):
            raw_monitor = portfolio_monitor_output.get("monitor")
            if isinstance(raw_monitor, list):
                monitor = raw_monitor

        portfolio_performance_context = SkillContext(
            task=task,
            parameters={"portfolio": monitor},
            metadata={},
            tool_context_factory=None,
        )
        portfolio_performance_result = self._portfolio_performance_skill.execute(
            portfolio_performance_context
        )

        performance = []
        portfolio_performance_output = getattr(
            portfolio_performance_result, "output", None
        )
        if isinstance(portfolio_performance_output, Mapping):
            raw_performance = portfolio_performance_output.get("performance")
            if isinstance(raw_performance, list):
                performance = raw_performance

        portfolio_alert_context = SkillContext(
            task=task,
            parameters={"performance": performance},
            metadata={},
            tool_context_factory=None,
        )
        portfolio_alert_result = self._portfolio_alert_skill.execute(
            portfolio_alert_context
        )

        alerts = []
        portfolio_alert_output = getattr(portfolio_alert_result, "output", None)
        if isinstance(portfolio_alert_output, Mapping):
            raw_alerts = portfolio_alert_output.get("alerts")
            if isinstance(raw_alerts, list):
                alerts = raw_alerts

        portfolio_report_context = SkillContext(
            task=task,
            parameters={"alerts": alerts},
            metadata={},
            tool_context_factory=None,
        )
        portfolio_report_result = self._portfolio_report_skill.execute(
            portfolio_report_context
        )

        return {
            "market": market_result,
            "recommendation": recommendation_result,
            "risk": risk_result,
            "trade_plan": trade_plan_result,
            "position_size": position_size_result,
            "capital_allocation": capital_allocation_result,
            "order_validation": order_validation_result,
            "paper_trading": paper_trading_result,
            "trade_history": trade_history_result,
            "portfolio_update": portfolio_update_result,
            "portfolio_monitor": portfolio_monitor_result,
            "portfolio_performance": portfolio_performance_result,
            "portfolio_alert": portfolio_alert_result,
            "portfolio_report": portfolio_report_result,
        }