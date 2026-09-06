"""MarketAnalysisAgent -- turning the Agent into a simple, hardcoded
multi-Skill coordinator (Phase 11, Sprint 119).

Sprint 118 built this Agent as a pure adapter over a single Skill:

    Task -> SkillContext -> MarketAnalysisSkill -> SkillResult

That flow never changed which Skill ran -- it only ever called
``MarketAnalysisSkill.execute()`` once and forwarded whatever it
returned. This sprint keeps that adapter shape (Task in, one
``SkillContext`` per Skill call, no reasoning, no Tool access) but
widens it to call three Skills, in a fixed, hardcoded order, and
collect all three results:

    Task
      |
      v
    MarketAnalysisSkill
      |
      v
    PortfolioAnalysisSkill
      |
      v
    WatchlistAnalysisSkill
      |
      v
    Combined Result

This is still not a planner, not a graph, not a workflow engine, and
not dynamic routing -- there is exactly one call sequence, written
directly inline inside ``execute()``, and it never branches: every
call to ``MarketAnalysisAgent.execute()`` runs the exact same three
Skill calls, in the exact same order, every time.

Construction (LOCKED): this Agent is handed exactly three
collaborators at construction time, already-constructed Skill
instances --

    MarketAnalysisAgent(
        market_analysis_skill,
        portfolio_analysis_skill,
        watchlist_analysis_skill,
    )

-- and stores each, unmodified, by identity. Nothing about *how*
``market_analysis_skill`` is able to resolve its own Tools (e.g.
whether ``_resolve_tool`` was ever injected onto it by an
``Executor``) is this Agent's concern -- that wiring, if any, happens
entirely outside this module, before the Skill instance is ever
handed to ``MarketAnalysisAgent.__init__``. ``PortfolioAnalysisSkill``
and ``WatchlistAnalysisSkill`` call no Tool at all, so no such wiring
is ever needed for either of them.

``execute(task)`` (LOCKED): the entire method body is exactly six
steps, all inline, no helper method, no branching --

    1. Read a ``"symbols"`` list out of ``task.metadata`` (the only
       place a ``Task`` value object -- ``Orchestration.task.Task``
       -- carries arbitrary caller-supplied data). Read defensively,
       using the same never-raise ``isinstance()``/``.get()`` style
       already used throughout every Skill in this chain: if
       ``task.metadata`` is not a ``Mapping``, or its ``"symbols"``
       value is missing or not a ``list``, this step yields an empty
       list -- never raising.
    2. Build ``SkillContext(task=task, parameters={"symbols":
       symbols}, metadata={}, tool_context_factory=None)`` and call
       ``self._market_analysis_skill.execute(...)`` exactly once,
       producing ``market_result``.
    3. Read a ``"stocks"`` list out of ``market_result.output`` the
       same defensive way -- if ``market_result.output`` is not a
       ``Mapping``, or its ``"stocks"`` value is missing or not a
       ``list``, this step yields an empty list, never raising.
    4. Build ``SkillContext(task=task, parameters={"stocks": stocks},
       metadata={}, tool_context_factory=None)`` and call
       ``self._portfolio_analysis_skill.execute(...)`` exactly once,
       producing ``portfolio_result``.
    5. Build a second, independent ``SkillContext(task=task,
       parameters={"stocks": stocks}, metadata={},
       tool_context_factory=None)`` -- carrying the exact same
       ``stocks`` list read in step 3, never
       ``portfolio_result.output`` -- and call
       ``self._watchlist_analysis_skill.execute(...)`` exactly once,
       producing ``watchlist_result``.
    6. Return ``{"market": market_result, "portfolio":
       portfolio_result, "watchlist": watchlist_result}`` -- a plain
       ``dict`` literal, freshly built by this method, but whose
       three values are exactly the three ``SkillResult`` objects
       each Skill produced, forwarded by identity, completely
       unchanged. Nothing is merged, recomputed, reshaped, or
       otherwise derived from them.

Each of the three Skills is called exactly once, in exactly this
order, every single time ``execute()`` runs -- there is no
conditional call, no retry, no skip, and no reordering of any kind.
Any exception any of the three ``.execute()`` calls raises propagates
unchanged; nothing in this module ever catches an exception.

No new abstraction of any kind was introduced to build this
coordination: no ``AgentManager``, ``AgentEngine``,
``AgentCoordinator``, ``AgentRunner``, ``AgentExecutor``,
``AgentFactory``, ``Dispatcher``, ``Router``, ``Pipeline``,
``Workflow``, ``Graph``, ``Node``, ``Service``, ``Repository``,
``Planner``, ``Strategy``, ``Registry``, helper module, or utility
module. The symbol-extraction, the three ``SkillContext``
constructions, and the three delegated calls all live directly
inline inside ``execute()``.

Architecture note -- why no new base class was introduced: same
reasoning as Sprint 118 -- ``Agents.base_agent.BaseAgent`` is the
abstract engine behind the project's *conversational* agents
(planner/memory/executor/``chat()``/``run()``), none of which applies
here. ``MarketAnalysisAgent`` remains a standalone class, not a
subclass of anything.

Explicitly NOT part of this milestone: any attribute beyond the
three constructor-injected Skill references, any cache, any
configuration, any helper method (public or private) beyond
``execute()`` itself, and any of ``run()``, ``chat()``, ``analyze()``,
``rank()``, or ``recommend()``. No AI, no LLM calls (including
Ollama), no provider calls, no service calls, no repository calls, no
Tool calls of any kind, and no reasoning, ranking, scoring, or
recommendation logic anywhere in this file -- all of that remains
each Skill's own responsibility, never this Agent's. No ``async``, no
``threading``, no ``queue``, no retry, and no caching anywhere in
this module.

Dependencies (LOCKED): this module imports
``Orchestration.market_analysis_skill.MarketAnalysisSkill``,
``Orchestration.portfolio_analysis_skill.PortfolioAnalysisSkill``,
``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill``
(each for its type annotation only -- never instantiated here),
``Orchestration.skill_context.SkillContext``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In particular
it does NOT import ``Orchestration.text_analysis_skill.
TextAnalysisSkill``, any Tool, ``Orchestration.tool_resolver.
ToolResolver``, ``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_context.ToolContext``,
``Orchestration.executor.Executor``,
``Orchestration.execution_session.ExecutionSession``,
``Agents.planner.Planner``, ``Agents.base_agent.BaseAgent``,
``Agents.executor.Executor``, ``Orchestration.workflow.Workflow``,
``Orchestration.memory``, ``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, ``Orchestration.event_bus.EventBus``,
``requests``, ``google.genai``, ``anthropic``, ``openai``,
``ollama``, ``sqlite3``, ``pandas``, ``numpy``, or ``yfinance``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.portfolio_analysis_skill import PortfolioAnalysisSkill
from Orchestration.skill_context import SkillContext
from Orchestration.watchlist_analysis_skill import WatchlistAnalysisSkill


class MarketAnalysisAgent:
    """A simple, deterministic coordinator: runs
    ``MarketAnalysisSkill`` -> ``PortfolioAnalysisSkill`` ->
    ``WatchlistAnalysisSkill``, in that fixed order, and collects all
    three results.

    No inheritance, no state beyond the three collaborators handed in
    at construction, and no helper methods beyond ``execute()``
    itself -- there is no ``run``, ``chat``, ``analyze``, ``rank``, or
    ``recommend`` anywhere on this class; the symbol extraction, the
    three ``SkillContext`` constructions, and the three Skill calls
    all live entirely inline inside ``execute()`` itself.
    """

    def __init__(
        self,
        market_analysis_skill: MarketAnalysisSkill,
        portfolio_analysis_skill: PortfolioAnalysisSkill,
        watchlist_analysis_skill: WatchlistAnalysisSkill,
    ) -> None:
        """Store the three Skills this Agent will call, in order.

        Args:
            market_analysis_skill: The already-constructed
                ``MarketAnalysisSkill`` instance called first. Stored
                by identity, never copied, never inspected, never
                wrapped. Any wiring it needs to resolve its own Tools
                (e.g. an injected ``_resolve_tool``) must already be
                in place before it is handed to this constructor.
            portfolio_analysis_skill: The already-constructed
                ``PortfolioAnalysisSkill`` instance called second.
                Stored by identity, never copied, never inspected,
                never wrapped.
            watchlist_analysis_skill: The already-constructed
                ``WatchlistAnalysisSkill`` instance called third.
                Stored by identity, never copied, never inspected,
                never wrapped.
        """
        self._market_analysis_skill = market_analysis_skill
        self._portfolio_analysis_skill = portfolio_analysis_skill
        self._watchlist_analysis_skill = watchlist_analysis_skill

    def execute(self, task: Any) -> Any:
        """Run this Agent: call ``MarketAnalysisSkill``, then
        ``PortfolioAnalysisSkill``, then ``WatchlistAnalysisSkill``,
        in that fixed order, and return all three results.

        ``task.metadata`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"symbols"`` value is missing or
        not a ``list``, this method behaves as though ``"symbols"``
        were an empty list -- never raising on account of a
        malformed ``task``. ``market_result.output`` is read the same
        defensive way to obtain the ``"stocks"`` list passed on to
        both ``PortfolioAnalysisSkill`` and ``WatchlistAnalysisSkill``.

        Args:
            task: Whatever the caller is asking this Agent to run.
                Expected to expose a ``.metadata`` mapping containing
                a ``"symbols"`` list, in the same shape
                ``Orchestration.task.Task`` provides, but never
                validated to actually be a ``Task`` instance -- only
                ``.metadata`` is ever read from it, and it is passed
                through by identity, unexamined otherwise, as every
                ``SkillContext``'s own ``task`` field.

        Returns:
            A freshly built ``dict`` with exactly three keys --
            ``"market"``, ``"portfolio"``, ``"watchlist"`` -- each
            holding the exact ``SkillResult`` object the
            corresponding Skill produced, forwarded by identity,
            completely unchanged, never merged, recomputed, or
            otherwise derived from.

        Raises:
            Exception: any exception raised while constructing a
                ``SkillContext`` (for example ``SkillContextError``)
                or by any of the three Skills' ``execute()`` calls
                propagates unchanged -- never caught, never wrapped.
        """
        symbols = []
        task_metadata = getattr(task, "metadata", None)
        if isinstance(task_metadata, Mapping):
            raw_symbols = task_metadata.get("symbols")
            if isinstance(raw_symbols, list):
                symbols = raw_symbols

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

        portfolio_context = SkillContext(
            task=task,
            parameters={"stocks": stocks},
            metadata={},
            tool_context_factory=None,
        )
        portfolio_result = self._portfolio_analysis_skill.execute(portfolio_context)

        watchlist_context = SkillContext(
            task=task,
            parameters={"stocks": stocks},
            metadata={},
            tool_context_factory=None,
        )
        watchlist_result = self._watchlist_analysis_skill.execute(watchlist_context)

        return {
            "market": market_result,
            "portfolio": portfolio_result,
            "watchlist": watchlist_result,
        }