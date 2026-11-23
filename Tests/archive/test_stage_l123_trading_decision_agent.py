"""Phase 10 Sprint 123 proof suite -- TradingDecisionAgent.

``TradingDecisionAgent`` is a second, independent Agent -- separate
from ``Orchestration.market_analysis_agent.MarketAnalysisAgent`` --
that coordinates the *decision* pipeline: four Skills called in a
fixed, hardcoded order --

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

-- returning ``{"market": ..., "recommendation": ..., "risk": ...,
"trade_plan": ...}``, each value the exact, unmodified ``SkillResult``
the corresponding Skill produced.

Scope: dedicated proof suite for
``Orchestration.trading_decision_agent.TradingDecisionAgent`` only.
Mirrors the compact, table-driven, no-pytest,
global-counter-plus-``main()`` style already used by
``Tests/test_stage_l119_market_analysis_agent_workflow.py``.

Two layers of coverage:

  1. Seam-level scenarios, using spy Skill stand-ins, that prove the
     Agent calls all four Skills exactly once each, in the correct
     order, forwards output/error by identity, wires ``"stocks"`` ->
     ``"actions"`` -> ``"risk"`` from each stage's own output into the
     next, never touches a Tool, and never raises on malformed input
     or on a downstream failure.
  2. Real integration: real ``MarketAnalysisSkill``/
     ``RecommendationSkill``/``PositionRiskSkill``/``TradePlanSkill``
     instances (the first wired to a real Tool chain via a real
     ``ToolResolver``/``ToolRegistry``), proving the full documented
     flow actually works end-to-end.

Invariant coverage:
    O1  -- each of the four Skills is called exactly once.
    O2  -- the four Skills are called in the fixed order
           MarketAnalysisSkill -> RecommendationSkill ->
           PositionRiskSkill -> TradePlanSkill.
    O3  -- the returned dict's four values are the exact SkillResult
           objects each Skill produced, forwarded by identity.
    O4  -- a failing SkillResult (success=False/error=<str>) from any
           of the four Skills is forwarded exactly as-is, and the
           pipeline continues to completion regardless (never raises,
           never stops).
    C1  -- the SkillContext handed to MarketAnalysisSkill carries
           parameters == {"symbols": [...]} taken from
           task.metadata["symbols"].
    C2  -- the SkillContext handed to RecommendationSkill carries
           parameters == {"stocks": [...]} taken from
           market_result.output["stocks"].
    C3  -- the SkillContext handed to PositionRiskSkill carries
           parameters == {"actions": [...]} taken from
           recommendation_result.output["actions"].
    C4  -- the SkillContext handed to TradePlanSkill carries
           parameters == {"risk": [...]} taken from
           risk_result.output["risk"].
    C5  -- every SkillContext's own task field is the exact Task
           object TradingDecisionAgent.execute() itself received
           (identity), for all four calls.
    N1  -- a Task whose metadata has no "symbols" key yields
           parameters == {"symbols": []}, never raising.
    N2  -- a Task whose metadata["symbols"] is not a list yields
           parameters == {"symbols": []}, never raising.
    N3  -- a task-like object with metadata=None never raises.
    N4  -- a MarketAnalysisSkill result whose output has no "stocks"
           key (or a non-list "stocks" value, or a non-Mapping
           output) yields parameters == {"stocks": []} for
           RecommendationSkill, never raising.
    N5  -- the same defensive-read behavior for "actions" between
           RecommendationSkill and PositionRiskSkill.
    N6  -- the same defensive-read behavior for "risk" between
           PositionRiskSkill and TradePlanSkill.
    T1  -- TradingDecisionAgent never calls execute_tool()/
           execute_tool_result() -- verified by construction (this
           class is not a BaseSkill subclass) and by AST.
    T2  -- TradingDecisionAgent never imports or references any Tool,
           ToolResolver, or ToolRegistry module.
    A1  -- AST: no forbidden-name symbol (Planner, Graph, Engine,
           Workflow, Pipeline, Coordinator, Manager, Dispatcher,
           Router, Factory, Strategy, Registry, Service, Repository,
           Adapter) anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           TradingDecisionAgent, and it has no base class beyond
           `object` (no new inheritance).
    A3  -- AST: execute() defines no nested function/lambda, no
           `async`, and constructs exactly four SkillContext
           instances and exactly four self._*.execute(...) calls.
    A4  -- AST: execute() contains no `for`/`while`/`try` (no
           branching) beyond the defensive `if` reads --
           execute()'s own top-level flow is a straight-line
           sequence of statements.
    A5  -- class shape: __init__ stores exactly the four injected
           collaborators; no other instance state; no helper method
           beyond __init__/execute.
    I1  -- real integration: a real TradingDecisionAgent, wired to
           real Skills (the first backed by a real Tool chain),
           executes a real Task with several symbols end-to-end and
           returns {"market": ..., "recommendation": ..., "risk": ...,
           "trade_plan": ...} each internally consistent with the
           others.
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

from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.market_fundamental_tool import MarketFundamentalTool
from Orchestration.market_news_tool import MarketNewsTool
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.position_risk_skill import PositionRiskSkill
from Orchestration.recommendation_skill import RecommendationSkill
from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult
from Orchestration.task import Task
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver
from Orchestration.trade_plan_skill import TradePlanSkill
from Orchestration.trading_decision_agent import TradingDecisionAgent

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


class _SpyRecommendationSkill:
    def __init__(self, log: CallLog, result: SkillResult):
        self._log = log
        self.result = result
        self.received_contexts: List[Any] = []

    def execute(self, context: Any) -> SkillResult:
        self._log.record("recommendation")
        self.received_contexts.append(context)
        return self.result


class _SpyPositionRiskSkill:
    def __init__(self, log: CallLog, result: SkillResult):
        self._log = log
        self.result = result
        self.received_contexts: List[Any] = []

    def execute(self, context: Any) -> SkillResult:
        self._log.record("risk")
        self.received_contexts.append(context)
        return self.result


class _SpyTradePlanSkill:
    def __init__(self, log: CallLog, result: SkillResult):
        self._log = log
        self.result = result
        self.received_contexts: List[Any] = []

    def execute(self, context: Any) -> SkillResult:
        self._log.record("trade_plan")
        self.received_contexts.append(context)
        return self.result


class _FakeTask:
    """A minimal task-like object exposing only ``.metadata``, to
    prove TradingDecisionAgent never touches any other Task
    attribute."""

    def __init__(self, metadata: Any):
        self.metadata = metadata


def _spies(
    market_output: Any = None,
    market_success: bool = True,
    market_error: Any = None,
    recommendation_output: Any = None,
    recommendation_success: bool = True,
    risk_output: Any = None,
    risk_success: bool = True,
):
    log = CallLog()
    market_result = SkillResult(
        success=market_success,
        output=market_output if market_output is not None else {"stocks": []},
        error=market_error,
        metadata={},
    )
    recommendation_result = SkillResult(
        success=recommendation_success,
        output=recommendation_output if recommendation_output is not None else {"actions": []},
        error=None,
        metadata={},
    )
    risk_result = SkillResult(
        success=risk_success,
        output=risk_output if risk_output is not None else {"risk": []},
        error=None,
        metadata={},
    )
    trade_plan_result = SkillResult(success=True, output={"plans": []}, error=None, metadata={})

    market_spy = _SpyMarketAnalysisSkill(log, market_result)
    recommendation_spy = _SpyRecommendationSkill(log, recommendation_result)
    risk_spy = _SpyPositionRiskSkill(log, risk_result)
    trade_plan_spy = _SpyTradePlanSkill(log, trade_plan_result)

    agent = TradingDecisionAgent(market_spy, recommendation_spy, risk_spy, trade_plan_spy)
    return (
        agent, log,
        market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        market_result, recommendation_result, risk_result, trade_plan_result,
    )


# ---------------------------------------------------------------------------
# O1-O2 -- each Skill called exactly once, in the fixed order
# ---------------------------------------------------------------------------
def scenario_each_skill_called_exactly_once() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(len(market_spy.received_contexts) == 1, f"O1: MarketAnalysisSkill.execute() called exactly once; got {len(market_spy.received_contexts)}")
    check(len(recommendation_spy.received_contexts) == 1, f"O1: RecommendationSkill.execute() called exactly once; got {len(recommendation_spy.received_contexts)}")
    check(len(risk_spy.received_contexts) == 1, f"O1: PositionRiskSkill.execute() called exactly once; got {len(risk_spy.received_contexts)}")
    check(len(trade_plan_spy.received_contexts) == 1, f"O1: TradePlanSkill.execute() called exactly once; got {len(trade_plan_spy.received_contexts)}")


def scenario_skills_called_in_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(log.events == ["market", "recommendation", "risk", "trade_plan"], f"O2: Skills called in order market -> recommendation -> risk -> trade_plan; got {log.events!r}")


def scenario_repeated_execute_repeats_the_same_fixed_order() -> None:
    agent, log, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    agent.execute(_FakeTask({"symbols": ["BBRI"]}))
    check(
        log.events == ["market", "recommendation", "risk", "trade_plan"] * 2,
        f"O2: each execute() call repeats the exact same fixed order; got {log.events!r}",
    )


# ---------------------------------------------------------------------------
# O3-O4 -- results forwarded by identity, unmerged, unmodified
# ---------------------------------------------------------------------------
def scenario_results_forwarded_by_identity() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        market_result, recommendation_result, risk_result, trade_plan_result,
    ) = _spies(market_output={"stocks": [{"symbol": "BBCA"}]})
    result = agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(isinstance(result, dict), f"O3: execute() returns a dict; got {type(result)!r}")
    check(set(result.keys()) == {"market", "recommendation", "risk", "trade_plan"}, f"O3: result has exactly the keys market/recommendation/risk/trade_plan; got {set(result.keys())!r}")
    check(result["market"] is market_result, "O3: result['market'] is the exact SkillResult MarketAnalysisSkill produced")
    check(result["recommendation"] is recommendation_result, "O3: result['recommendation'] is the exact SkillResult RecommendationSkill produced")
    check(result["risk"] is risk_result, "O3: result['risk'] is the exact SkillResult PositionRiskSkill produced")
    check(result["trade_plan"] is trade_plan_result, "O3: result['trade_plan'] is the exact SkillResult TradePlanSkill produced")


def scenario_failure_error_forwarded_and_pipeline_continues() -> None:
    (
        agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy,
        market_result, recommendation_result, risk_result, trade_plan_result,
    ) = _spies(market_success=False, market_error="BBRI: market_price: boom")
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBRI"]})))
    check(exc is None, f"O4: a failing upstream Skill never raises; pipeline continues; got {exc!r}")

    result = agent.execute(_FakeTask({"symbols": ["BBRI"]}))
    check(result["market"].success is False, "O4: a failing MarketAnalysisSkill result's success=False is forwarded unchanged")
    check(result["market"].error == "BBRI: market_price: boom", f"O4: error string is forwarded unchanged; got {result['market'].error!r}")
    check(result["market"] is market_result, "O4: the failing SkillResult itself is still forwarded by identity")
    check(len(recommendation_spy.received_contexts) == 2, "O4: RecommendationSkill still ran despite MarketAnalysisSkill's failure")
    check(len(risk_spy.received_contexts) == 2, "O4: PositionRiskSkill still ran despite the upstream failure")
    check(len(trade_plan_spy.received_contexts) == 2, "O4: TradePlanSkill still ran despite the upstream failure")


# ---------------------------------------------------------------------------
# C1-C5 -- SkillContext construction and wiring between stages
# ---------------------------------------------------------------------------
def scenario_market_context_carries_symbols() -> None:
    agent, log, market_spy, *_ = _spies()
    agent.execute(_FakeTask({"symbols": ["BBCA", "BBRI", "BMRI"]}))
    context = market_spy.received_contexts[0]
    check(dict(context.parameters) == {"symbols": ["BBCA", "BBRI", "BMRI"]}, f"C1: MarketAnalysisSkill context.parameters carries exactly {{'symbols': [...]}}; got {dict(context.parameters)!r}")


def scenario_recommendation_context_carries_stocks_from_market_output() -> None:
    stocks = [{"symbol": "BBCA", "analysis": {"recommendation": "BUY"}}]
    agent, log, market_spy, recommendation_spy, *_ = _spies(market_output={"stocks": stocks})
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    context = recommendation_spy.received_contexts[0]
    check(dict(context.parameters) == {"stocks": stocks}, f"C2: RecommendationSkill context.parameters carries {{'stocks': [...]}} taken from market_result.output['stocks']; got {dict(context.parameters)!r}")


def scenario_risk_context_carries_actions_from_recommendation_output() -> None:
    actions = [{"symbol": "BBCA", "action": "BUY"}]
    agent, log, market_spy, recommendation_spy, risk_spy, *_ = _spies(recommendation_output={"actions": actions})
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    context = risk_spy.received_contexts[0]
    check(dict(context.parameters) == {"actions": actions}, f"C3: PositionRiskSkill context.parameters carries {{'actions': [...]}} taken from recommendation_result.output['actions']; got {dict(context.parameters)!r}")


def scenario_trade_plan_context_carries_risk_from_risk_output() -> None:
    risk_entries = [{"symbol": "BBCA", "action": "BUY", "risk": "NORMAL"}]
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies(risk_output={"risk": risk_entries})
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    context = trade_plan_spy.received_contexts[0]
    check(dict(context.parameters) == {"risk": risk_entries}, f"C4: TradePlanSkill context.parameters carries {{'risk': [...]}} taken from risk_result.output['risk']; got {dict(context.parameters)!r}")


def scenario_every_context_task_is_the_received_task_by_identity() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies()
    task = _FakeTask({"symbols": ["BBCA"]})
    agent.execute(task)
    check(market_spy.received_contexts[0].task is task, "C5: MarketAnalysisSkill's SkillContext.task is the exact Task object received")
    check(recommendation_spy.received_contexts[0].task is task, "C5: RecommendationSkill's SkillContext.task is the exact Task object received")
    check(risk_spy.received_contexts[0].task is task, "C5: PositionRiskSkill's SkillContext.task is the exact Task object received")
    check(trade_plan_spy.received_contexts[0].task is task, "C5: TradePlanSkill's SkillContext.task is the exact Task object received")


# ---------------------------------------------------------------------------
# N1-N6 -- malformed input never raises
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
    agent, log, market_spy, recommendation_spy, *_ = _spies(market_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N4: a market_result.output with no 'stocks' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(recommendation_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: missing 'stocks' key yields an empty list for RecommendationSkill")


def scenario_non_mapping_market_output_never_raises() -> None:
    agent, log, market_spy, recommendation_spy, *_ = _spies(market_output="not a mapping")
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N4: a non-Mapping market_result.output never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(recommendation_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: non-Mapping output yields an empty stocks list for RecommendationSkill")


def scenario_non_list_stocks_never_raises() -> None:
    agent, log, market_spy, recommendation_spy, *_ = _spies(market_output={"stocks": "not a list"})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N4: a non-list 'stocks' value never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(recommendation_spy.received_contexts[-1].parameters) == {"stocks": []}, "N4: non-list 'stocks' yields an empty list for RecommendationSkill")


def scenario_missing_actions_in_recommendation_output_yields_empty_list() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, *_ = _spies(recommendation_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N5: a recommendation_result.output with no 'actions' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(risk_spy.received_contexts[-1].parameters) == {"actions": []}, "N5: missing 'actions' key yields an empty list for PositionRiskSkill")


def scenario_non_mapping_recommendation_output_never_raises() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, *_ = _spies(recommendation_output="not a mapping")
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N5: a non-Mapping recommendation_result.output never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(risk_spy.received_contexts[-1].parameters) == {"actions": []}, "N5: non-Mapping output yields an empty actions list for PositionRiskSkill")


def scenario_missing_risk_in_risk_output_yields_empty_list() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies(risk_output={})
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N6: a risk_result.output with no 'risk' key never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(trade_plan_spy.received_contexts[-1].parameters) == {"risk": []}, "N6: missing 'risk' key yields an empty list for TradePlanSkill")


def scenario_non_mapping_risk_output_never_raises() -> None:
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies(risk_output="not a mapping")
    exc = _catch(lambda: agent.execute(_FakeTask({"symbols": ["BBCA"]})))
    check(exc is None, f"N6: a non-Mapping risk_result.output never raises; got {exc!r}")
    agent.execute(_FakeTask({"symbols": ["BBCA"]}))
    check(dict(trade_plan_spy.received_contexts[-1].parameters) == {"risk": []}, "N6: non-Mapping output yields an empty risk list for TradePlanSkill")


# ---------------------------------------------------------------------------
# T1-T2 -- no Tool access of any kind
# ---------------------------------------------------------------------------
def scenario_agent_has_no_tool_related_methods() -> None:
    check(not hasattr(TradingDecisionAgent, "execute_tool"), "T1: TradingDecisionAgent has no execute_tool method")
    check(not hasattr(TradingDecisionAgent, "execute_tool_result"), "T1: TradingDecisionAgent has no execute_tool_result method")
    check(not hasattr(TradingDecisionAgent, "_resolve_tool"), "T1: TradingDecisionAgent has no _resolve_tool attribute on the class")


def scenario_module_never_imports_tool_machinery() -> None:
    import Orchestration.trading_decision_agent as module

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
        "Orchestration.base_tool", "Orchestration.market_analysis_agent",
        "Orchestration.portfolio_analysis_skill", "Orchestration.watchlist_analysis_skill",
        "ToolResolver", "ToolRegistry", "ToolContext", "TextAnalysisSkill",
        "MarketAnalysisAgent",
    )
    for forbidden in forbidden_imports:
        check(forbidden not in imported_names, f"T2: module never imports {forbidden!r}")


# ---------------------------------------------------------------------------
# A1-A5 -- AST / namespace verification
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.trading_decision_agent as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_defs = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    class_names = {n.name for n in class_defs}
    check(class_names == {"TradingDecisionAgent"}, f"A2: module defines exactly one class; got {class_names!r}")

    for class_def in class_defs:
        base_names = [b.id for b in class_def.bases if isinstance(b, ast.Name)]
        check(base_names == [], f"A2: TradingDecisionAgent has no base class (no new inheritance); got {base_names!r}")

    forbidden_fragments = (
        "Planner", "Graph", "Engine", "Workflow", "Pipeline",
        "Coordinator", "Manager", "Dispatcher", "Router", "Factory",
        "Strategy", "Registry", "Service", "Repository", "Helper",
        "Utility", "Adapter",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(TradingDecisionAgent.execute)
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
    check(len(skill_context_calls) == 4, f"A3: exactly four SkillContext(...) constructions; got {len(skill_context_calls)}")

    execute_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "execute"
        and isinstance(c.func.value, ast.Attribute)
        and isinstance(c.func.value.value, ast.Name) and c.func.value.value.id == "self"
    ]
    check(len(execute_calls) == 4, f"O1: exactly four self._*.execute(...) calls; got {len(execute_calls)}")


def scenario_execute_has_no_branching() -> None:
    source = inspect.getsource(TradingDecisionAgent.execute)
    tree = ast.parse(textwrap.dedent(source))
    top_level_def = tree.body[0]

    for_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, (ast.For, ast.AsyncFor))]
    while_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.While)]
    try_nodes = [n for n in ast.walk(top_level_def) if isinstance(n, ast.Try)]
    check(len(for_nodes) == 0, f"A4: execute() contains no for-loop; got {len(for_nodes)}")
    check(len(while_nodes) == 0, f"A4: execute() contains no while-loop; got {len(while_nodes)}")
    check(len(try_nodes) == 0, f"A4: execute() contains no try/except (no error-swallowing); got {len(try_nodes)}")

    # if-statements are permitted only for the defensive isinstance()
    # style read of task.metadata / each Skill's own result.output
    # (never for choosing *which* Skill to call, or *whether* to call
    # one, or for skipping a stage based on a prior success flag).
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
    agent, log, market_spy, recommendation_spy, risk_spy, trade_plan_spy, *_ = _spies()
    check(
        agent.__dict__ == {
            "_market_analysis_skill": market_spy,
            "_recommendation_skill": recommendation_spy,
            "_position_risk_skill": risk_spy,
            "_trade_plan_skill": trade_plan_spy,
        },
        f"A5: __init__ stores exactly the four injected collaborators; got {agent.__dict__!r}",
    )
    check(agent._market_analysis_skill is market_spy, "A5: the stored MarketAnalysisSkill is the exact object passed in, by identity")
    check(agent._recommendation_skill is recommendation_spy, "A5: the stored RecommendationSkill is the exact object passed in, by identity")
    check(agent._position_risk_skill is risk_spy, "A5: the stored PositionRiskSkill is the exact object passed in, by identity")
    check(agent._trade_plan_skill is trade_plan_spy, "A5: the stored TradePlanSkill is the exact object passed in, by identity")


def scenario_no_extra_methods_beyond_init_and_execute() -> None:
    required_members = {"__init__", "execute"}
    for attr_name, attr_value in TradingDecisionAgent.__dict__.items():
        if attr_name in required_members:
            continue
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        is_callable_attr = callable(attr_value) or isinstance(attr_value, (staticmethod, classmethod, property))
        check(
            not is_callable_attr,
            f"A5: no additional method/property defined on TradingDecisionAgent beyond __init__/execute; found {attr_name!r}",
        )


# ---------------------------------------------------------------------------
# I1-I2 -- real end-to-end integration
# ---------------------------------------------------------------------------
def _real_agent() -> TradingDecisionAgent:
    tool_registry = ToolRegistry()
    tool_registry.register("market_price", MarketPriceTool())
    tool_registry.register("market_news", MarketNewsTool())
    tool_registry.register("market_fundamental", MarketFundamentalTool())
    tool_resolver = ToolResolver(tool_registry)

    market_analysis_skill = MarketAnalysisSkill()
    # This is exactly the shape Executor.invoke_current_skill() injects
    # onto a Skill instance in production -- performed here by the test
    # harness (standing in for an Executor), never by
    # TradingDecisionAgent itself.
    market_analysis_skill._resolve_tool = tool_resolver.resolve

    recommendation_skill = RecommendationSkill()
    position_risk_skill = PositionRiskSkill()
    trade_plan_skill = TradePlanSkill()

    return TradingDecisionAgent(
        market_analysis_skill, recommendation_skill, position_risk_skill, trade_plan_skill
    )


def scenario_real_end_to_end_chain() -> None:
    agent = _real_agent()
    task = Task(
        name="trading-decision",
        description="Produce a full trade decision for several IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI", "BMRI"]},
    )

    result = agent.execute(task)

    check(isinstance(result, dict), f"I1: real chain returns a dict; got {type(result)!r}")
    check(set(result.keys()) == {"market", "recommendation", "risk", "trade_plan"}, f"I1: result has exactly market/recommendation/risk/trade_plan; got {set(result.keys())!r}")

    market_result = result["market"]
    recommendation_result = result["recommendation"]
    risk_result = result["risk"]
    trade_plan_result = result["trade_plan"]

    check(isinstance(market_result, SkillResult), f"I1: result['market'] is a SkillResult; got {type(market_result)!r}")
    check(isinstance(recommendation_result, SkillResult), f"I1: result['recommendation'] is a SkillResult; got {type(recommendation_result)!r}")
    check(isinstance(risk_result, SkillResult), f"I1: result['risk'] is a SkillResult; got {type(risk_result)!r}")
    check(isinstance(trade_plan_result, SkillResult), f"I1: result['trade_plan'] is a SkillResult; got {type(trade_plan_result)!r}")

    stocks = market_result.output["stocks"]
    check(len(stocks) == 3, f"I1: one stock entry per symbol; got {len(stocks)}")
    symbols_in_order = [s["symbol"] for s in stocks]
    check(symbols_in_order == ["BBCA", "BBRI", "BMRI"], f"I1: original input order preserved in market output; got {symbols_in_order!r}")

    actions = recommendation_result.output["actions"]
    check(len(actions) == 3, f"I1: RecommendationSkill produced one action per stock; got {len(actions)}")
    action_symbols = [entry["symbol"] for entry in actions]
    check(action_symbols == symbols_in_order, f"I1: RecommendationSkill's actions cover the exact same symbols in the exact same order; got {action_symbols!r}")

    risk_entries = risk_result.output["risk"]
    check(len(risk_entries) == 3, f"I1: PositionRiskSkill produced one risk entry per action; got {len(risk_entries)}")
    risk_symbols = [entry["symbol"] for entry in risk_entries]
    check(risk_symbols == symbols_in_order, f"I1: PositionRiskSkill's risk entries cover the exact same symbols in the exact same order; got {risk_symbols!r}")

    plans = trade_plan_result.output["plans"]
    check(len(plans) == 3, f"I1: TradePlanSkill produced one plan per risk entry; got {len(plans)}")
    plan_symbols = [entry["symbol"] for entry in plans]
    check(plan_symbols == symbols_in_order, f"I1: TradePlanSkill's plans cover the exact same symbols in the exact same order; got {plan_symbols!r}")
    for plan_entry, action_entry, risk_entry in zip(plans, actions, risk_entries):
        check(plan_entry["action"] == action_entry["action"], f"I1: TradePlanSkill's action matches RecommendationSkill's own action for {plan_entry['symbol']!r}")
        check(plan_entry["risk"] == risk_entry["risk"], f"I1: TradePlanSkill's risk matches PositionRiskSkill's own risk for {plan_entry['symbol']!r}")


def scenario_real_chain_is_deterministic() -> None:
    agent = _real_agent()
    task = Task(
        name="trading-decision",
        description="Produce a full trade decision for a couple of IDX symbols end-to-end",
        metadata={"symbols": ["BBCA", "BBRI"]},
    )

    result1 = agent.execute(task)
    result2 = agent.execute(task)
    check(result1["market"] == result2["market"], "I2: repeated real end-to-end runs produce field-equal 'market' SkillResults")
    check(result1["recommendation"] == result2["recommendation"], "I2: repeated real end-to-end runs produce field-equal 'recommendation' SkillResults")
    check(result1["risk"] == result2["risk"], "I2: repeated real end-to-end runs produce field-equal 'risk' SkillResults")
    check(result1["trade_plan"] == result2["trade_plan"], "I2: repeated real end-to-end runs produce field-equal 'trade_plan' SkillResults")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_each_skill_called_exactly_once,
        scenario_skills_called_in_fixed_order,
        scenario_repeated_execute_repeats_the_same_fixed_order,
        scenario_results_forwarded_by_identity,
        scenario_failure_error_forwarded_and_pipeline_continues,
        scenario_market_context_carries_symbols,
        scenario_recommendation_context_carries_stocks_from_market_output,
        scenario_risk_context_carries_actions_from_recommendation_output,
        scenario_trade_plan_context_carries_risk_from_risk_output,
        scenario_every_context_task_is_the_received_task_by_identity,
        scenario_missing_symbols_key_yields_empty_list,
        scenario_non_list_symbols_yields_empty_list,
        scenario_none_metadata_never_raises,
        scenario_missing_stocks_in_market_output_yields_empty_list,
        scenario_non_mapping_market_output_never_raises,
        scenario_non_list_stocks_never_raises,
        scenario_missing_actions_in_recommendation_output_yields_empty_list,
        scenario_non_mapping_recommendation_output_never_raises,
        scenario_missing_risk_in_risk_output_yields_empty_list,
        scenario_non_mapping_risk_output_never_raises,
        scenario_agent_has_no_tool_related_methods,
        scenario_module_never_imports_tool_machinery,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_execute_has_no_branching,
        scenario_class_shape,
        scenario_no_extra_methods_beyond_init_and_execute,
        scenario_real_end_to_end_chain,
        scenario_real_chain_is_deterministic,
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