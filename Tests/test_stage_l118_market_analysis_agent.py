"""Phase 10 Sprint 118 proof suite -- Market Analysis Agent.

``MarketAnalysisAgent`` is the project's first real Agent: it accepts
a ``Task``-shaped object, extracts a ``"symbols"`` list from its
``.metadata``, builds exactly one ``SkillContext``, and delegates
entirely to a single, constructor-injected
``Orchestration.market_analysis_skill.MarketAnalysisSkill`` instance
-- forwarding its ``SkillResult`` back unchanged. No reasoning, no
Tool access, and no new abstraction of any kind lives in this module.

Scope: dedicated proof suite for
``Orchestration.market_analysis_agent.MarketAnalysisAgent`` only.
Mirrors the compact, table-driven, no-pytest, global-counter-plus-
main() style already used by
``Tests/test_stage_l117_market_analysis_skill.py``, combined with a
real end-to-end integration layer (real ``MarketAnalysisSkill``, real
``TextAnalysisSkill``, real Tools, real ``ToolRegistry``/
``ToolResolver``) proving the full documented flow actually works.

Two layers of coverage:

  1. Seam-level scenarios, using a spy ``MarketAnalysisSkill``
     stand-in, that prove the Agent calls the Skill exactly once,
     forwards output/error by identity, never touches a Tool, and
     never raises on malformed input.
  2. Real integration: a real ``MarketAnalysisSkill`` wired to a real
     ``TextAnalysisSkill``-driving chain (via a real ``ToolResolver``
     over a real ``ToolRegistry`` holding the three real Tools),
     proving Task -> MarketAnalysisAgent -> MarketAnalysisSkill ->
     TextAnalysisSkill -> Tools -> final result works end-to-end.

Invariant coverage:
    O1  -- MarketAnalysisAgent.execute(task) calls
           MarketAnalysisSkill.execute() exactly once.
    O2  -- the SkillResult MarketAnalysisSkill.execute() returns is
           forwarded back by MarketAnalysisAgent.execute() unchanged
           (checked via `is`, not just `==`).
    O3  -- a SkillResult with success=False/error=<str> is forwarded
           exactly as-is (error never modified, reworded, or
           swallowed).
    C1  -- the SkillContext handed to MarketAnalysisSkill.execute()
           carries parameters == {"symbols": [...]} taken from
           task.metadata["symbols"].
    C2  -- the SkillContext's own task field is the exact Task object
           MarketAnalysisAgent.execute() itself received (identity).
    N1  -- a Task whose metadata has no "symbols" key yields
           parameters == {"symbols": []}, never raising.
    N2  -- a Task whose metadata["symbols"] is not a list yields
           parameters == {"symbols": []}, never raising.
    N3  -- a task-like object with metadata=None never raises.
    T1  -- MarketAnalysisAgent never calls execute_tool()/
           execute_tool_result() -- verified by construction (this
           class is not even a BaseSkill subclass, so those methods
           do not exist on it) and by AST (no such call anywhere in
           the module).
    T2  -- MarketAnalysisAgent never imports or references any Tool,
           ToolResolver, or ToolRegistry module.
    A1  -- AST: no forbidden-name symbol (AgentManager, AgentEngine,
           AgentCoordinator, AgentRunner, AgentExecutor, AgentFactory,
           Dispatcher, Router, Pipeline, Workflow, Graph, Node,
           Service, Repository) anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           MarketAnalysisAgent, and it has no base class beyond
           `object` (no new inheritance).
    A3  -- AST: execute() defines no nested function/lambda and
           constructs exactly one SkillContext.
    A4  -- class shape: __init__ stores exactly the one injected
           collaborator; no other instance state.
    I1  -- real integration: a real MarketAnalysisAgent, wired to a
           real MarketAnalysisSkill/TextAnalysisSkill/Tool chain via
           a real ToolRegistry/ToolResolver, executes a real Task
           with several symbols end-to-end and returns a SkillResult
           whose output["stocks"] has one entry per symbol, each
           carrying a real, Tool-derived "analysis" dict.
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
from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult
from Orchestration.task import Task
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver

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
# Fixtures -- seam-level: a spy MarketAnalysisSkill stand-in
# ---------------------------------------------------------------------------
class _SpyMarketAnalysisSkill:
    """A duck-typed ``MarketAnalysisSkill`` stand-in that records every
    ``execute(context)`` call and returns a fixed, pre-built
    ``SkillResult``."""

    def __init__(self, result: SkillResult):
        self.result = result
        self.received_contexts: List[Any] = []

    def execute(self, context: Any) -> SkillResult:
        self.received_contexts.append(context)
        return self.result


class _FakeTask:
    """A minimal task-like object exposing only ``.metadata``, to
    prove MarketAnalysisAgent never touches any other Task attribute."""

    def __init__(self, metadata: Any):
        self.metadata = metadata


# ---------------------------------------------------------------------------
# O1-O3 -- delegation and identity-forwarding
# ---------------------------------------------------------------------------
def scenario_calls_skill_exactly_once() -> None:
    fixed_result = SkillResult(success=True, output={"stocks": []}, error=None, metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(len(spy.received_contexts) == 1, f"O1: MarketAnalysisSkill.execute() called exactly once; got {len(spy.received_contexts)}")


def scenario_success_output_forwarded_by_identity() -> None:
    fixed_output = {"stocks": [{"symbol": "BBCA", "analysis": {"recommendation": "BUY"}}]}
    fixed_result = SkillResult(success=True, output=fixed_output, error=None, metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    result = agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(result is fixed_result, "O2: the SkillResult MarketAnalysisSkill.execute() returned is forwarded back by identity")
    check(result.output is fixed_output, "O2: the output dict is forwarded by identity, never copied")


def scenario_failure_error_forwarded_unchanged() -> None:
    fixed_result = SkillResult(success=False, output={"stocks": []}, error="BBRI: market_price: boom", metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    result = agent.execute(_FakeTask({"symbols": ["BBRI"]}))
    check(result is fixed_result, "O3: a failing SkillResult is forwarded back by identity")
    check(result.success is False, "O3: success=False is forwarded unchanged")
    check(result.error == "BBRI: market_price: boom", f"O3: error string is forwarded unchanged; got {result.error!r}")


# ---------------------------------------------------------------------------
# C1-C2 -- SkillContext construction
# ---------------------------------------------------------------------------
def scenario_context_parameters_carries_symbols() -> None:
    fixed_result = SkillResult(success=True, output={"stocks": []}, error=None, metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    agent.execute(_FakeTask({"symbols": ["BBCA", "BBRI", "BMRI"]}))
    context = spy.received_contexts[0]
    check(dict(context.parameters) == {"symbols": ["BBCA", "BBRI", "BMRI"]}, f"C1: context.parameters carries exactly {{'symbols': [...]}}; got {dict(context.parameters)!r}")


def scenario_context_task_is_the_received_task_by_identity() -> None:
    fixed_result = SkillResult(success=True, output={"stocks": []}, error=None, metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    task = _FakeTask({"symbols": ["BBCA"]})
    agent.execute(task)
    context = spy.received_contexts[0]
    check(context.task is task, "C2: SkillContext.task is the exact Task object this Agent received")


# ---------------------------------------------------------------------------
# N1-N3 -- malformed task metadata never raises
# ---------------------------------------------------------------------------
def scenario_missing_symbols_key_yields_empty_list() -> None:
    fixed_result = SkillResult(success=True, output={"stocks": []}, error=None, metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    exc = _catch(lambda: agent.execute(_FakeTask({})))
    check(exc is None, f"N1: missing 'symbols' key never raises; got {exc!r}")

    agent.execute(_FakeTask({}))
    context = spy.received_contexts[-1]
    check(dict(context.parameters) == {"symbols": []}, f"N1: missing 'symbols' key yields an empty list; got {dict(context.parameters)!r}")


def scenario_non_list_symbols_yields_empty_list() -> None:
    fixed_result = SkillResult(success=True, output={"stocks": []}, error=None, metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    agent.execute(_FakeTask({"symbols": "not a list"}))
    context = spy.received_contexts[-1]
    check(dict(context.parameters) == {"symbols": []}, f"N2: non-list 'symbols' value yields an empty list; got {dict(context.parameters)!r}")


def scenario_none_metadata_never_raises() -> None:
    fixed_result = SkillResult(success=True, output={"stocks": []}, error=None, metadata={})
    spy = _SpyMarketAnalysisSkill(fixed_result)
    agent = MarketAnalysisAgent(spy)

    exc = _catch(lambda: agent.execute(_FakeTask(None)))
    check(exc is None, f"N3: metadata=None never raises; got {exc!r}")

    exc2 = _catch(lambda: agent.execute(object()))
    check(exc2 is None, f"N3: a task-like object with no .metadata attribute at all never raises; got {exc2!r}")


# ---------------------------------------------------------------------------
# T1-T2 -- no Tool access of any kind
# ---------------------------------------------------------------------------
def scenario_agent_has_no_tool_related_methods() -> None:
    check(not hasattr(MarketAnalysisAgent, "execute_tool"), "T1: MarketAnalysisAgent has no execute_tool method")
    check(not hasattr(MarketAnalysisAgent, "execute_tool_result"), "T1: MarketAnalysisAgent has no execute_tool_result method")
    check(not hasattr(MarketAnalysisAgent, "_resolve_tool"), "T1: MarketAnalysisAgent has no _resolve_tool attribute on the class")


def scenario_module_never_imports_tool_machinery() -> None:
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
        "Orchestration.text_analysis_skill", "Orchestration.portfolio_analysis_skill",
        "Orchestration.watchlist_analysis_skill", "Orchestration.executor",
        "Orchestration.base_tool", "ToolResolver", "ToolRegistry", "ToolContext",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"T2: module never imports {forbidden!r}")


# ---------------------------------------------------------------------------
# A1-A4 -- AST / namespace verification
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
        "AgentManager", "AgentEngine", "AgentCoordinator", "AgentRunner",
        "AgentExecutor", "AgentFactory", "Dispatcher", "Router", "Pipeline",
        "Workflow", "Graph", "Node", "Service", "Repository", "Helper",
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
    nested_funcdefs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_funcdefs) == 0, f"A3: execute() defines no nested function/lambda; got {len(nested_funcdefs)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    forbidden_tool_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr in ("execute_tool", "execute_tool_result")
    ]
    check(len(forbidden_tool_calls) == 0, f"T1: execute() never calls execute_tool()/execute_tool_result(); got {len(forbidden_tool_calls)}")

    skill_context_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillContext"]
    check(len(skill_context_calls) == 1, f"A3: exactly one SkillContext(...) construction; got {len(skill_context_calls)}")


def scenario_class_shape() -> None:
    spy = _SpyMarketAnalysisSkill(SkillResult(success=True, output={"stocks": []}, error=None, metadata={}))
    agent = MarketAnalysisAgent(spy)
    check(agent.__dict__ == {"_market_analysis_skill": spy}, f"A4: __init__ stores exactly the one injected collaborator; got {agent.__dict__!r}")
    check(agent._market_analysis_skill is spy, "A4: the stored collaborator is the exact object passed in, by identity")


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

    return MarketAnalysisAgent(market_analysis_skill)


def scenario_real_end_to_end_chain() -> None:
    agent = _real_agent()
    task = Task(
        name="analyze-watchlist",
        description="Analyze several IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI", "BMRI"]},
    )

    result = agent.execute(task)

    check(isinstance(result, SkillResult), f"I1: real chain returns a SkillResult; got {type(result)!r}")
    stocks = result.output["stocks"]
    check(len(stocks) == 3, f"I1: one stock entry per symbol; got {len(stocks)}")
    symbols_in_order = [s["symbol"] for s in stocks]
    check(symbols_in_order == ["BBCA", "BBRI", "BMRI"], f"I1: original input order preserved through the full chain; got {symbols_in_order!r}")

    for entry in stocks:
        check(isinstance(entry["analysis"], dict), f"I1: {entry['symbol']} carries a real, Tool-derived analysis dict")
        check("recommendation" in entry["analysis"] and "confidence" in entry["analysis"], f"I1: {entry['symbol']}'s analysis has recommendation/confidence, produced by the real TextAnalysisSkill decision table")


def scenario_real_chain_is_deterministic() -> None:
    agent = _real_agent()
    task = Task(
        name="analyze-watchlist",
        description="Analyze several IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI"]},
    )

    result1 = agent.execute(task)
    result2 = agent.execute(task)
    check(result1 == result2, "I2: repeated real end-to-end runs with the same Task are field-equal (deterministic)")


def scenario_real_chain_empty_symbols() -> None:
    agent = _real_agent()
    task = Task(name="analyze-nothing", description="No symbols given", metadata={})

    result = agent.execute(task)
    check(result.output == {"stocks": []}, f"I1: an empty/missing symbols list flows all the way through to an empty stocks list; got {result.output!r}")
    check(result.success is True, "I1: success is True for an empty symbols list")


def main() -> int:
    scenarios = [
        scenario_calls_skill_exactly_once,
        scenario_success_output_forwarded_by_identity,
        scenario_failure_error_forwarded_unchanged,
        scenario_context_parameters_carries_symbols,
        scenario_context_task_is_the_received_task_by_identity,
        scenario_missing_symbols_key_yields_empty_list,
        scenario_non_list_symbols_yields_empty_list,
        scenario_none_metadata_never_raises,
        scenario_agent_has_no_tool_related_methods,
        scenario_module_never_imports_tool_machinery,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_class_shape,
        scenario_real_end_to_end_chain,
        scenario_real_chain_is_deterministic,
        scenario_real_chain_empty_symbols,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 10 SPRINT 118 MARKET-ANALYSIS-AGENT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())