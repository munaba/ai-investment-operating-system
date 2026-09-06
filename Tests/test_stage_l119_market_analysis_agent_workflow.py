"""Phase 11 Sprint 119 proof suite -- MarketAnalysisAgent Workflow.

``MarketAnalysisAgent`` is no longer a single-Skill adapter (Sprint
118). It is now a simple, deterministic coordinator that calls three
Skills in a fixed, hardcoded order --

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

-- and returns ``{"market": ..., "portfolio": ..., "watchlist": ...}``,
each value the exact, unmodified ``SkillResult`` the corresponding
Skill produced.

Scope: dedicated proof suite for
``Orchestration.market_analysis_agent.MarketAnalysisAgent`` (Sprint
119 shape) only. Mirrors the compact, table-driven, no-pytest,
global-counter-plus-``main()`` style already used by
``Tests/test_stage_l118_market_analysis_agent.py``.

Two layers of coverage:

  1. Seam-level scenarios, using spy Skill stand-ins, that prove the
     Agent calls all three Skills exactly once each, in the correct
     order, forwards output/error by identity, wires ``"stocks"``
     from ``MarketAnalysisSkill``'s own output into both downstream
     Skills, never touches a Tool, and never raises on malformed
     input.
  2. Real integration: real ``MarketAnalysisSkill``/
     ``PortfolioAnalysisSkill``/``WatchlistAnalysisSkill`` instances
     (the first wired to a real ``TextAnalysisSkill``-driving chain
     via a real ``ToolResolver``/``ToolRegistry`` holding the three
     real Tools), proving the full documented flow actually works
     end-to-end.

Invariant coverage:
    O1  -- each of the three Skills is called exactly once.
    O2  -- the three Skills are called in the fixed order
           MarketAnalysisSkill -> PortfolioAnalysisSkill ->
           WatchlistAnalysisSkill.
    O3  -- the returned dict's three values are the exact SkillResult
           objects each Skill produced, forwarded by identity.
    O4  -- a failing SkillResult (success=False/error=<str>) from any
           of the three Skills is forwarded exactly as-is.
    C1  -- the SkillContext handed to MarketAnalysisSkill carries
           parameters == {"symbols": [...]} taken from
           task.metadata["symbols"].
    C2  -- the SkillContext handed to PortfolioAnalysisSkill carries
           parameters == {"stocks": [...]} taken from
           market_result.output["stocks"].
    C3  -- the SkillContext handed to WatchlistAnalysisSkill carries
           parameters == {"stocks": [...]} -- the *same* stocks list
           as PortfolioAnalysisSkill received, not anything derived
           from PortfolioAnalysisSkill's own output.
    C4  -- every SkillContext's own task field is the exact Task
           object MarketAnalysisAgent.execute() itself received
           (identity), for all three calls.
    N1  -- a Task whose metadata has no "symbols" key yields
           parameters == {"symbols": []}, never raising.
    N2  -- a Task whose metadata["symbols"] is not a list yields
           parameters == {"symbols": []}, never raising.
    N3  -- a task-like object with metadata=None never raises.
    N4  -- a MarketAnalysisSkill result whose output has no "stocks"
           key (or a non-list "stocks" value, or a non-Mapping
           output) yields parameters == {"stocks": []} for both
           downstream Skills, never raising.
    T1  -- MarketAnalysisAgent never calls execute_tool()/
           execute_tool_result() -- verified by construction (this
           class is not even a BaseSkill subclass) and by AST.
    T2  -- MarketAnalysisAgent never imports or references any Tool,
           ToolResolver, or ToolRegistry module, nor
           TextAnalysisSkill.
    A1  -- AST: no forbidden-name symbol (Planner, Graph, Engine,
           Workflow, Pipeline, Coordinator, Manager, Dispatcher,
           Router, Factory, Strategy, Registry, Service, Repository)
           anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           MarketAnalysisAgent, and it has no base class beyond
           `object` (no new inheritance).
    A3  -- AST: execute() defines no nested function/lambda, no
           `async`, and constructs exactly three SkillContext
           instances.
    A4  -- AST: execute() contains no `if`/`for`/`while`/`try` (no
           branching) beyond what SkillContext construction itself
           requires -- i.e. execute()'s own top-level flow is a
           straight-line sequence of statements.
    A5  -- class shape: __init__ stores exactly the three injected
           collaborators; no other instance state.
    I1  -- real integration: a real MarketAnalysisAgent, wired to
           real Skills (the first backed by a real Tool chain),
           executes a real Task with several symbols end-to-end and
           returns {"market": ..., "portfolio": ..., "watchlist": ...}
           each internally consistent with the others.
    I2  -- the same real chain, run twice with the same Task, is
           deterministic (field-equal SkillResults).
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.market_analysis_agent import MarketAnalysisAgent
from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.market_fundamental_tool import MarketFundamentalTool
from Orchestration.market_news_tool import MarketNewsTool
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.portfolio_analysis_skill import PortfolioAnalysisSkill
from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult
from Orchestration.task import Task
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver
from Orchestration.watchlist_analysis_skill import WatchlistAnalysisSkill

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
    print(f"  {'PASS' if condition else 'FAIL'} - {description}")


def _catch(fn):
    try:
        fn()
        return None
    except Exception as exc:  # noqa: BLE001
        return exc


# ---------------------------------------------------------------------------
# Fixtures -- seam-level: spy Skill stand-ins + a shared ordered call log
# ---------------------------------------------------------------------------
class CallLog:
    def __init__(self) -> None:
        self.events: List[str] = []

    def record(self, event: str) -> None:
        self.events.append(event)


class _SpyMarketAnalysisSkill:
    def __init__(self, log: CallLog, result: SkillResult):
        self._log = log
        self.result = result
        self.received_contexts: List[Any] = []

    def execute(self, context: Any) -> SkillResult:
        self._log.record("market")
        self.received_contexts.append(context)
        return self.result


class _SpyPortfolioAnalysisSkill:
    def __init__(self, log: CallLog, result: SkillResult):
        self._log = log
        self.result = result
        self.received_contexts: List[Any] = []

    def execute(self, context: Any) -> SkillResult:
        self._log.record("portfolio")
        self.received_contexts.append(context)
        return self.result


class _SpyWatchlistAnalysisSkill:
    def __init__(self, log: CallLog, result: SkillResult):
        self._log = log
        self.result = result
        self.received_contexts: List[Any] = []

    def execute(self, context: Any) -> SkillResult:
        self._log.record("watchlist")
        self.received_contexts.append(context)
        return self.result


class _FakeTask:
    """A minimal task-like object exposing only ``.metadata``, to
    prove MarketAnalysisAgent never touches any other Task attribute."""

    def __init__(self, metadata: Any):
        self.metadata = metadata


def _spies(
    market_output: Any = None,
    market_success: bool = True,
    market_error: Any = None,
):
    log = CallLog()
    market_result = SkillResult(
        success=market_success,
        output=market_output if market_output is not None else {"stocks": []},
        error=market_error,
        metadata={},
    )
    portfolio_result = SkillResult(success=True, output={"ranking": []}, error=None, metadata={})
    watchlist_result = SkillResult(success=True, output={"watchlist": []}, error=None, metadata={})

    market_spy = _SpyMarketAnalysisSkill(log, market_result)
    portfolio_spy = _SpyPortfolioAnalysisSkill(log, portfolio_result)
    watchlist_spy = _SpyWatchlistAnalysisSkill(log, watchlist_result)

    agent = MarketAnalysisAgent(market_spy, portfolio_spy, watchlist_spy)
    return agent, log, market_spy, portfolio_spy, watchlist_spy, market_result, portfolio_result, watchlist_result


# ---------------------------------------------------------------------------
# O1-O2 -- each Skill called exactly once, in the fixed order
# ---------------------------------------------------------------------------
def scenario_each_skill_called_exactly_once() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(len(market_spy.received_contexts) == 1, f"O1: MarketAnalysisSkill.execute() called exactly once; got {len(market_spy.received_contexts)}")
    check(len(portfolio_spy.received_contexts) == 1, f"O1: PortfolioAnalysisSkill.execute() called exactly once; got {len(portfolio_spy.received_contexts)}")
    check(len(watchlist_spy.received_contexts) == 1, f"O1: WatchlistAnalysisSkill.execute() called exactly once; got {len(watchlist_spy.received_contexts)}")


def scenario_skills_called_in_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(log.events == ["market", "portfolio", "watchlist"], f"O2: Skills called in order market -> portfolio -> watchlist; got {log.events!r}")


def scenario_repeated_execute_repeats_the_same_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    agent.execute(_FakeTask({"symbols": ["BBRI"]}))
    check(log.events == ["market", "portfolio", "watchlist", "market", "portfolio", "watchlist"], f"O2: each execute() call repeats the exact same fixed order; got {log.events!r}")


# ---------------------------------------------------------------------------
# O3-O4 -- results forwarded by identity, unmerged, unmodified
# ---------------------------------------------------------------------------
def scenario_results_forwarded_by_identity() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, market_result, portfolio_result, watchlist_result = _spies(
        market_output={"stocks": [{"symbol": "BBCA", "analysis": {"recommendation": "BUY"}}]}
    )
    result = agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(isinstance(result, dict), f"O3: execute() returns a dict; got {type(result)!r}")
    check(set(result.keys()) == {"market", "portfolio", "watchlist"}, f"O3: result has exactly the keys market/portfolio/watchlist; got {set(result.keys())!r}")
    check(result["market"] is market_result, "O3: result['market'] is the exact SkillResult MarketAnalysisSkill produced")
    check(result["portfolio"] is portfolio_result, "O3: result['portfolio'] is the exact SkillResult PortfolioAnalysisSkill produced")
    check(result["watchlist"] is watchlist_result, "O3: result['watchlist'] is the exact SkillResult WatchlistAnalysisSkill produced")


def scenario_failure_error_forwarded_unchanged() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, market_result, portfolio_result, watchlist_result = _spies(
        market_success=False, market_error="BBRI: market_price: boom"
    )
    result = agent.execute(_FakeTask({"symbols": ["BBRI"]}))
    check(result["market"].success is False, "O4: a failing MarketAnalysisSkill result's success=False is forwarded unchanged")
    check(result["market"].error == "BBRI: market_price: boom", f"O4: error string is forwarded unchanged; got {result['market'].error!r}")
    check(result["market"] is market_result, "O4: the failing SkillResult itself is still forwarded by identity")


# ---------------------------------------------------------------------------
# C1-C4 -- SkillContext construction and wiring between stages
# ---------------------------------------------------------------------------
def scenario_market_context_carries_symbols() -> None:
    agent, log, market_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA", "BBRI", "BMRI"]}))
    context = market_spy.received_contexts[0]
    check(dict(context.parameters) == {"symbols": ["BBCA", "BBRI", "BMRI"]}, f"C1: MarketAnalysisSkill context.parameters carries exactly {{'symbols': [...]}}; got {dict(context.parameters)!r}")


def scenario_portfolio_context_carries_stocks_from_market_output() -> None:
    stocks = [{"symbol": "BBCA", "analysis": {"recommendation": "BUY", "confidence": "HIGH"}}]
    agent, log, market_spy, portfolio_spy, *_ = _spies(market_output={"stocks": stocks})
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    context = portfolio_spy.received_contexts[0]
    check(dict(context.parameters) == {"stocks": stocks}, f"C2: PortfolioAnalysisSkill context.parameters carries {{'stocks': [...]}} taken from market_result.output['stocks']; got {dict(context.parameters)!r}")


def scenario_watchlist_context_carries_the_same_stocks_as_portfolio() -> None:
    stocks = [{"symbol": "BBCA", "analysis": {"recommendation": "BUY", "confidence": "HIGH"}}]
    agent, log, market_spy, portfolio_spy, watchlist_spy, *_ = _spies(market_output={"stocks": stocks})
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    portfolio_context = portfolio_spy.received_contexts[0]
    watchlist_context = watchlist_spy.received_contexts[0]
    check(dict(watchlist_context.parameters) == {"stocks": stocks}, f"C3: WatchlistAnalysisSkill context.parameters carries {{'stocks': [...]}}; got {dict(watchlist_context.parameters)!r}")
    check(dict(watchlist_context.parameters) == dict(portfolio_context.parameters), "C3: WatchlistAnalysisSkill receives the exact same stocks as PortfolioAnalysisSkill, not anything derived from PortfolioAnalysisSkill's own output")


def scenario_every_context_task_is_the_received_task_by_identity() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, *_ = _spies()
    task = _FakeTask({"symbols": ["BBCA"]})
    agent.execute(task)
    check(market_spy.received_contexts[0].task is task, "C4: MarketAnalysisSkill's SkillContext.task is the exact Task object received")
    check(portfolio_spy.received_contexts[0].task is task, "C4: PortfolioAnalysisSkill's SkillContext.task is the exact Task object received")
    check(watchlist_spy.received_contexts[0].task is task, "C4: WatchlistAnalysisSkill's SkillContext.task is the exact Task object received")


# ---------------------------------------------------------------------------
# N1-N4 -- malformed input never raises
# ---------------------------------------------------------------------------
def scenario_missing_symbols_key_yields_empty_list() -> None:
    agent, log, market_spy, *_ = _spies()
    exc = _catch(lambda: agent.execute(_FakeTask({})))
    check(exc is None, f"N1: missing 'symbols' key never raises; got {exc!r}")
    agent.execute(_FakeTask({}))
    context = market_spy.received_contexts[-1]
    check(dict(context.parameters) == {"symbols": []}, f"N1: missing 'symbols' key yields an empty list; got {dict(context.parameters)!r}")


def scenario_non_list_symbols_yields_empty_list() -> None:
    agent, log, market_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": "not a list"}))
    context = market_spy.received_contexts[-1]
    check(dict(context.parameters) == {"symbols": []}, f"N2: non-list 'symbols' value yields an empty list; got {dict(context.parameters)!r}")


def scenario_none_metadata_never_raises() -> None:
    agent, log, *_ = _spies()
    exc = _catch(lambda: agent.execute(_FakeTask(None)))
    check(exc is None, f"N3: metadata=None never raises; got {exc!r}")
    exc2 = _catch(lambda: agent.execute(object()))
    check(exc2 is None, f"N3: a task-like object with no .metadata attribute at all never raises; got {exc2!r}")


def scenario_missing_stocks_in_market_output_yields_empty_list() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, *_ = _spies(market_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N4: a market_result.output with no 'stocks' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(portfolio_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: missing 'stocks' key yields an empty list for PortfolioAnalysisSkill")
    check(dict(watchlist_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: missing 'stocks' key yields an empty list for WatchlistAnalysisSkill")


def scenario_non_mapping_market_output_never_raises() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, *_ = _spies(market_output="not a mapping")
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N4: a non-Mapping market_result.output never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(portfolio_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: non-Mapping output yields an empty stocks list for PortfolioAnalysisSkill")
    check(dict(watchlist_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: non-Mapping output yields an empty stocks list for WatchlistAnalysisSkill")


def scenario_non_list_stocks_never_raises() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, *_ = _spies(market_output={"stocks": "not a list"})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N4: a non-list 'stocks' value never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(portfolio_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: non-list 'stocks' yields an empty list for PortfolioAnalysisSkill")
    check(dict(watchlist_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: non-list 'stocks' yields an empty list for WatchlistAnalysisSkill")


# ---------------------------------------------------------------------------
# T1-T2 -- no Tool access of any kind
# ---------------------------------------------------------------------------
def scenario_agent_has_no_tool_related_methods() -> None:
    check(not hasattr(MarketAnalysisAgent, "execute_tool"), "T1: MarketAnalysisAgent has no execute_tool method")
    check(not hasattr(MarketAnalysisAgent, "execute_tool_result"), "T1: MarketAnalysisAgent has no execute_tool_result method")
    check(not hasattr(MarketAnalysisAgent, "_resolve_tool"), "T1: MarketAnalysisAgent has no _resolve_tool attribute on the class")


def scenario_module_never_imports_tool_or_text_analysis_machinery() -> None:
    import Orchestration.market_analysis_agent as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.add(node.module or "")
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)

    forbidden_imports = (
        "Orchestration.tool_resolver", "Orchestration.tool_registry",
        "Orchestration.tool_context", "Orchestration.market_price_tool",
        "Orchestration.market_news_tool", "Orchestration.market_fundamental_tool",
        "Orchestration.text_analysis_skill", "Orchestration.executor",
        "Orchestration.base_tool", "ToolResolver", "ToolRegistry", "ToolContext",
        "TextAnalysisSkill",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"T2: module never imports {forbidden!r}")


# ---------------------------------------------------------------------------
# A1-A5 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.market_analysis_agent as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"MarketAnalysisAgent"}, f"A2: module defines exactly one class; got {class_names!r}")

    for class_def in class_defs:
        base_names = [b.id for b in class_def.bases if isinstance(b, ast.Name)]
        check(base_names == [], f"A2: MarketAnalysisAgent has no base class (no new inheritance); got {base_names!r}")

    forbidden_fragments = (
        "Planner", "Graph", "Engine", "Workflow", "Pipeline",
        "Coordinator", "Manager", "Dispatcher", "Router", "Factory",
        "Strategy", "Registry", "Service", "Repository", "Helper",
        "Utility",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(MarketAnalysisAgent.execute)
    tree = ast.parse(textwrap.dedent(source))

    top_level_def = tree.body[0]
    check(isinstance(top_level_def, ast.FunctionDef), "A3: execute() is a plain (non-async) function")

    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A3: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")

    async_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.AsyncFunctionDef)]
    check(len(async_nodes) == 0, f"A3: execute() contains no async def; got {len(async_nodes)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    forbidden_tool_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in ("execute_tool", "execute_tool_result")
    ]
    check(len(forbidden_tool_calls) == 0, f"T1: execute() never calls execute_tool()/execute_tool_result(); got {len(forbidden_tool_calls)}")

    skill_context_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillContext"]
    check(len(skill_context_calls) == 3, f"A3: exactly three SkillContext(...) constructions; got {len(skill_context_calls)}")

    execute_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "execute"
        and isinstance(c.func.value, ast.Attribute)
        and isinstance(c.func.value.value, ast.Name) and c.func.value.value.id == "self"
    ]
    check(len(execute_calls) == 3, f"O1: exactly three self._*.execute(...) calls; got {len(execute_calls)}")


def scenario_execute_has_no_branching() -> None:
    source = inspect.getsource(MarketAnalysisAgent.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]

    for_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, (ast.For, ast.AsyncFor))]
    while_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.While)]
    try_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.Try)]
    check(len(for_nodes) == 0, f"A4: execute() contains no for-loop; got {len(for_nodes)}")
    check(len(while_nodes) == 0, f"A4: execute() contains no while-loop; got {len(while_nodes)}")
    check(len(try_nodes) == 0, f"A4: execute() contains no try/except (no error-swallowing); got {len(try_nodes)}")

    # if-statements are permitted only for the defensive isinstance()
    # style read of task.metadata / result.output (never for choosing
    # *which* Skill to call, or *whether* to call one).
    if_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.If)]
    for if_node in if_nodes:
        called_names = {
            c.func.id for c in ast.walk(if_node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }
        check(
            "SkillContext" not in called_names,
            "A4: no SkillContext(...) construction lives inside an if-branch (unconditional, hardcoded sequence)",
        )
        called_attrs = {
            c.func.attr for c in ast.walk(if_node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
        }
        check(
            "execute" not in called_attrs,
            "A4: no Skill.execute(...) call lives inside an if-branch (unconditional, hardcoded sequence)",
        )


def scenario_class_shape() -> None:
    agent, log, market_spy, portfolio_spy, watchlist_spy, *_ = _spies()
    check(
        agent.__dict__ == {
            "_market_analysis_skill": market_spy,
            "_portfolio_analysis_skill": portfolio_spy,
            "_watchlist_analysis_skill": watchlist_spy,
        },
        f"A5: __init__ stores exactly the three injected collaborators; got {agent.__dict__!r}",
    )
    check(agent._market_analysis_skill is market_spy, "A5: the stored MarketAnalysisSkill is the exact object passed in, by identity")
    check(agent._portfolio_analysis_skill is portfolio_spy, "A5: the stored PortfolioAnalysisSkill is the exact object passed in, by identity")
    check(agent._watchlist_analysis_skill is watchlist_spy, "A5: the stored WatchlistAnalysisSkill is the exact object passed in, by identity")


# ---------------------------------------------------------------------------
# I1-I2 -- real end-to-end integration
# ---------------------------------------------------------------------------
def _real_agent() -> MarketAnalysisAgent:
    tool_registry = ToolRegistry()
    tool_registry.register("market_price", MarketPriceTool())
    tool_registry.register("market_news", MarketNewsTool())
    tool_registry.register("market_fundamental", MarketFundamentalTool())
    tool_resolver = ToolResolver(tool_registry)

    market_analysis_skill = MarketAnalysisSkill()
    # This is exactly the shape Executor.invoke_current_skill() injects
    # onto a Skill instance in production -- performed here by the test
    # harness (standing in for an Executor), never by MarketAnalysisAgent
    # itself.
    market_analysis_skill._resolve_tool = tool_resolver.resolve

    portfolio_analysis_skill = PortfolioAnalysisSkill()
    watchlist_analysis_skill = WatchlistAnalysisSkill()

    return MarketAnalysisAgent(
        market_analysis_skill, portfolio_analysis_skill, watchlist_analysis_skill
    )


def scenario_real_end_to_end_chain() -> None:
    agent = _real_agent()
    task = Task(
        name="analyze-watchlist",
        description="Analyze several IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI", "BMRI"]},
    )

    result = agent.execute(task)

    check(isinstance(result, dict), f"I1: real chain returns a dict; got {type(result)!r}")
    check(set(result.keys()) == {"market", "portfolio", "watchlist"}, f"I1: result has exactly market/portfolio/watchlist; got {set(result.keys())!r}")

    market_result = result["market"]
    portfolio_result = result["portfolio"]
    watchlist_result = result["watchlist"]

    check(isinstance(market_result, SkillResult), f"I1: result['market'] is a SkillResult; got {type(market_result)!r}")
    check(isinstance(portfolio_result, SkillResult), f"I1: result['portfolio'] is a SkillResult; got {type(portfolio_result)!r}")
    check(isinstance(watchlist_result, SkillResult), f"I1: result['watchlist'] is a SkillResult; got {type(watchlist_result)!r}")

    stocks = market_result.output["stocks"]
    check(len(stocks) == 3, f"I1: one stock entry per symbol; got {len(stocks)}")
    symbols_in_order = [s["symbol"] for s in stocks]
    check(symbols_in_order == ["BBCA", "BBRI", "BMRI"], f"I1: original input order preserved in market output; got {symbols_in_order!r}")

    ranking = portfolio_result.output["ranking"]
    check(len(ranking) == 3, f"I1: PortfolioAnalysisSkill ranked all 3 stocks; got {len(ranking)}")
    ranking_symbols = {entry["symbol"] for entry in ranking}
    check(ranking_symbols == set(symbols_in_order), f"I1: PortfolioAnalysisSkill's ranking covers the exact same symbols as MarketAnalysisSkill produced; got {ranking_symbols!r}")

    watchlist = watchlist_result.output["watchlist"]
    check(len(watchlist) == 3, f"I1: WatchlistAnalysisSkill prioritized all 3 stocks; got {len(watchlist)}")
    watchlist_symbols = {entry["symbol"] for entry in watchlist}
    check(watchlist_symbols == set(symbols_in_order), f"I1: WatchlistAnalysisSkill's watchlist covers the exact same symbols as MarketAnalysisSkill produced; got {watchlist_symbols!r}")


def scenario_real_chain_is_deterministic() -> None:
    agent = _real_agent()
    task = Task(
        name="analyze-watchlist",
        description="Analyze several IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI"]},
    )

    result1 = agent.execute(task)
    result2 = agent.execute(task)
    check(result1["market"] == result2["market"], "I2: repeated real end-to-end runs produce field-equal 'market' SkillResults")
    check(result1["portfolio"] == result2["portfolio"], "I2: repeated real end-to-end runs produce field-equal 'portfolio' SkillResults")
    check(result1["watchlist"] == result2["watchlist"], "I2: repeated real end-to-end runs produce field-equal 'watchlist' SkillResults")


def scenario_real_chain_empty_symbols() -> None:
    agent = _real_agent()
    task = Task(name="analyze-nothing", description="No symbols given", metadata={})

    result = agent.execute(task)
    check(result["market"].output == {"stocks": []}, f"I1: an empty/missing symbols list flows through to an empty stocks list; got {result['market'].output!r}")
    check(result["portfolio"].output == {"ranking": []}, f"I1: an empty stocks list flows through to an empty ranking; got {result['portfolio'].output!r}")
    check(result["watchlist"].output == {"watchlist": []}, f"I1: an empty stocks list flows through to an empty watchlist; got {result['watchlist'].output!r}")
    check(result["market"].success is True, "I1: success is True for an empty symbols list (market)")
    check(result["portfolio"].success is True, "I1: success is True for an empty symbols list (portfolio)")
    check(result["watchlist"].success is True, "I1: success is True for an empty symbols list (watchlist)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_each_skill_called_exactly_once,
        scenario_skills_called_in_fixed_order,
        scenario_repeated_execute_repeats_the_same_fixed_order,
        scenario_results_forwarded_by_identity,
        scenario_failure_error_forwarded_unchanged,
        scenario_market_context_carries_symbols,
        scenario_portfolio_context_carries_stocks_from_market_output,
        scenario_watchlist_context_carries_the_same_stocks_as_portfolio,
        scenario_every_context_task_is_the_received_task_by_identity,
        scenario_missing_symbols_key_yields_empty_list,
        scenario_non_list_symbols_yields_empty_list,
        scenario_none_metadata_never_raises,
        scenario_missing_stocks_in_market_output_yields_empty_list,
        scenario_non_mapping_market_output_never_raises,
        scenario_non_list_stocks_never_raises,
        scenario_agent_has_no_tool_related_methods,
        scenario_module_never_imports_tool_or_text_analysis_machinery,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_execute_has_no_branching,
        scenario_class_shape,
        scenario_real_end_to_end_chain,
        scenario_real_chain_is_deterministic,
        scenario_real_chain_empty_symbols,
    ]

    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        scenario()

    print(f"\n{'=' * 70}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())