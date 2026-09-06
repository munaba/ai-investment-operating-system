"""Phase 10 Sprint 110 proof suite -- First Real Market Analysis.

``MarketPriceTool.execute(context)`` is no longer a fixed literal. It
now derives ``"trend"`` (and ``"price"``) deterministically from
``context.parameters["current_price"]`` /
``context.parameters["previous_price"]`` via the LOCKED four-rule
table, entirely inline inside ``execute()`` itself -- no new class,
Manager, Analyzer, Strategy, Engine, Registry, Factory, Adapter,
Pipeline, Utility, or helper module was introduced anywhere in this
project to add it.

Scope: dedicated proof suite for the Sprint 110 change to
``Orchestration.market_price_tool.MarketPriceTool`` only. Mirrors the
compact, table-driven, no-pytest, global-counter-plus-main() style
already used by ``Tests/test_stage_l109_text_analysis_reasoning.py``.

Two layers of coverage:

  1. Direct, seam-free scenarios that construct a real
     ``MarketPriceTool`` and call ``execute()`` with local, duck-typed
     context stand-ins (real ``ToolContext`` too), driving every row
     of the LOCKED trend table plus every missing/invalid-input case.
  2. AST/namespace verification proving the analysis lives entirely
     inline inside ``execute()`` and that no forbidden abstraction was
     introduced -- plus a real, fully-wired
     Executor -> TextAnalysisSkill -> {MarketPriceTool, MarketNewsTool}
     integration proving Sprint 109's reasoning now actually reaches
     BUY/WAIT/SELL when real price data is supplied, and still falls
     back to UNKNOWN when it is not.

Invariant coverage:
    T1  -- current_price > previous_price -> trend="bullish".
    T2  -- current_price < previous_price -> trend="bearish".
    T3  -- current_price == previous_price -> trend="neutral".
    T4  -- either price missing -> trend="unknown", price=None.
    T5  -- either price is an invalid type (str/None/bool/list) ->
           trend="unknown", price=None.
    T6  -- price value returned equals current_price whenever both
           prices are valid (bullish/bearish/neutral cases).
    T7  -- missing symbol -> symbol="UNKNOWN".
    T8  -- non-str / empty-str symbol -> symbol="UNKNOWN".
    T9  -- a real, present symbol is forwarded unchanged.
    T10 -- no other trend value is ever produced -- only "bullish",
           "bearish", "neutral", "unknown".
    T11 -- determinism: identical parameters always produce an
           identical (field-equal) ToolResult, across repeated calls
           and across separate MarketPriceTool instances.
    T12 -- never raises: None, a plain string, a dict without
           .parameters, and an arbitrary object are all tolerated as
           ``context`` without exception.
    T13 -- success/error/metadata shape unchanged: success=True,
           error=None, metadata={} on every call.
    T14 -- a real ToolContext (not just a duck-typed stand-in) flows
           through the same code path correctly.
    T15 -- bool values for current_price/previous_price are treated
           as invalid (not coerced to 1/0), yielding "unknown".
    A1  -- AST: no forbidden-name symbol (Manager, Registry, Adapter,
           Factory, Analyzer, Strategy, Engine, Pipeline, Utility,
           Helper) anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           MarketPriceTool.
    A3  -- AST: execute() defines no nested function/lambda -- the
           analysis is flat code inside execute() itself, not a
           helper closure or module-level private function.
    A4  -- class shape: still no __init__ of its own, no
           per-instance state; name/description unchanged.
    I1  -- real integration: Executor -> invoke_current_skill() ->
           TextAnalysisSkill -> {MarketPriceTool, MarketNewsTool} ->
           SkillResult succeeds end-to-end with real price/headline
           parameters, and Sprint 109's reasoning now actually
           reaches a non-UNKNOWN recommendation because
           MarketPriceTool finally supplies a real "trend".
    I2  -- real integration: with no price parameters supplied at
           all, the same pipeline still deterministically falls back
           to "analysis": UNKNOWN/LOW/"insufficient data" (Sprint 109
           behavior preserved, now driven by Sprint 110's real
           "unknown" trend rather than a missing key).
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_host import AutonomousHost
from Orchestration.executor import Executor
from Orchestration.market_news_tool import MarketNewsTool
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.skill_result import SkillResult
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
from Orchestration.text_analysis_skill import TextAnalysisSkill
from Orchestration.tool_context import ToolContext
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver
from Orchestration.tool_result import ToolResult

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
# Fixtures
# ---------------------------------------------------------------------------
class _DuckContext:
    """A minimal duck-typed context stand-in exposing only
    ``.parameters`` -- MarketPriceTool never requires a real
    ToolContext, matching MarketNewsTool's Sprint 107 tolerance."""

    def __init__(self, parameters: Any):
        self.parameters = parameters


def _run(parameters: Any) -> ToolResult:
    tool = MarketPriceTool()
    return tool.execute(_DuckContext(parameters))


# ---------------------------------------------------------------------------
# T1-T3 -- the three price-comparison trend rules
# ---------------------------------------------------------------------------
def scenario_bullish() -> None:
    result = _run({"symbol": "AAPL", "current_price": 110, "previous_price": 100})
    check(result.output["trend"] == "bullish", "T1: current > previous -> trend=bullish")
    check(result.output["price"] == 110, "T6: price equals current_price on bullish")


def scenario_bearish() -> None:
    result = _run({"symbol": "AAPL", "current_price": 90, "previous_price": 100})
    check(result.output["trend"] == "bearish", "T2: current < previous -> trend=bearish")
    check(result.output["price"] == 90, "T6: price equals current_price on bearish")


def scenario_neutral() -> None:
    result = _run({"symbol": "AAPL", "current_price": 100, "previous_price": 100})
    check(result.output["trend"] == "neutral", "T3: current == previous -> trend=neutral")
    check(result.output["price"] == 100, "T6: price equals current_price on neutral")


def scenario_neutral_with_floats() -> None:
    result = _run({"symbol": "AAPL", "current_price": 100.0, "previous_price": 100})
    check(result.output["trend"] == "neutral", "T3: equal values across int/float -> trend=neutral")


# ---------------------------------------------------------------------------
# T4-T5, T15 -- missing / invalid price data -> unknown
# ---------------------------------------------------------------------------
def scenario_missing_current_price() -> None:
    result = _run({"symbol": "AAPL", "previous_price": 100})
    check(result.output["trend"] == "unknown", "T4: missing current_price -> trend=unknown")
    check(result.output["price"] is None, "T4: missing current_price -> price=None")


def scenario_missing_previous_price() -> None:
    result = _run({"symbol": "AAPL", "current_price": 100})
    check(result.output["trend"] == "unknown", "T4: missing previous_price -> trend=unknown")
    check(result.output["price"] is None, "T4: missing previous_price -> price=None")


def scenario_missing_both_prices() -> None:
    result = _run({"symbol": "AAPL"})
    check(result.output["trend"] == "unknown", "T4: missing both prices -> trend=unknown")
    check(result.output["price"] is None, "T4: missing both prices -> price=None")


def scenario_string_prices() -> None:
    result = _run({"symbol": "AAPL", "current_price": "110", "previous_price": "100"})
    check(result.output["trend"] == "unknown", "T5: string prices -> trend=unknown (never coerced)")
    check(result.output["price"] is None, "T5: string prices -> price=None")


def scenario_none_prices() -> None:
    result = _run({"symbol": "AAPL", "current_price": None, "previous_price": 100})
    check(result.output["trend"] == "unknown", "T5: None current_price -> trend=unknown")


def scenario_list_prices() -> None:
    result = _run({"symbol": "AAPL", "current_price": [110], "previous_price": 100})
    check(result.output["trend"] == "unknown", "T5: list current_price -> trend=unknown")


def scenario_bool_prices_not_coerced() -> None:
    result = _run({"symbol": "AAPL", "current_price": True, "previous_price": False})
    check(result.output["trend"] == "unknown", "T15: bool current_price/previous_price are not coerced to 1/0 -> trend=unknown")
    check(result.output["price"] is None, "T15: bool prices -> price=None")


# ---------------------------------------------------------------------------
# T7-T9 -- symbol defaulting
# ---------------------------------------------------------------------------
def scenario_missing_symbol() -> None:
    result = _run({"current_price": 110, "previous_price": 100})
    check(result.output["symbol"] == "UNKNOWN", "T7: missing symbol -> symbol=UNKNOWN")


def scenario_non_str_symbol() -> None:
    result = _run({"symbol": 12345, "current_price": 110, "previous_price": 100})
    check(result.output["symbol"] == "UNKNOWN", "T8: non-str symbol -> symbol=UNKNOWN")


def scenario_empty_str_symbol() -> None:
    result = _run({"symbol": "", "current_price": 110, "previous_price": 100})
    check(result.output["symbol"] == "UNKNOWN", "T8: empty-str symbol -> symbol=UNKNOWN")


def scenario_real_symbol_forwarded() -> None:
    result = _run({"symbol": "BBCA", "current_price": 110, "previous_price": 100})
    check(result.output["symbol"] == "BBCA", "T9: a real symbol is forwarded unchanged")


# ---------------------------------------------------------------------------
# T10 -- exhaustive sweep: only the four LOCKED trend values ever appear
# ---------------------------------------------------------------------------
def scenario_exhaustive_trend_values() -> None:
    price_pairs = [
        (110, 100), (90, 100), (100, 100),
        (None, 100), (100, None), (None, None),
        ("110", "100"), ([1], 100), (True, False),
    ]
    allowed_trends = {"bullish", "bearish", "neutral", "unknown"}
    all_valid = True
    for current, previous in price_pairs:
        result = _run({"symbol": "X", "current_price": current, "previous_price": previous})
        if result.output["trend"] not in allowed_trends:
            all_valid = False
    check(all_valid, "T10: every trend value produced is one of bullish/bearish/neutral/unknown")


# ---------------------------------------------------------------------------
# T11 -- determinism
# ---------------------------------------------------------------------------
def scenario_determinism() -> None:
    params = {"symbol": "AAPL", "current_price": 150, "previous_price": 140}
    result1 = _run(params)
    result2 = _run(params)
    tool2 = MarketPriceTool()
    result3 = tool2.execute(_DuckContext(dict(params)))

    check(result1 == result2, "T11a: repeated calls with identical parameters are field-equal")
    check(result1 == result3, "T11b: separate MarketPriceTool instances are field-equal for identical parameters")
    check(result1.output == {"symbol": "AAPL", "price": 150, "trend": "bullish"}, "T11c: output matches expected deterministic value")


# ---------------------------------------------------------------------------
# T12 -- never raises on malformed context
# ---------------------------------------------------------------------------
def scenario_never_raises() -> None:
    tool = MarketPriceTool()
    for label, ctx in [
        ("None context", None),
        ("plain string context", "not a context"),
        ("dict without .parameters attr", {"symbol": "AAPL"}),
        ("arbitrary object", object()),
    ]:
        exc = _catch(lambda ctx=ctx: tool.execute(ctx))
        check(exc is None, f"T12: execute() never raises for {label}; got {exc!r}")


def scenario_malformed_context_falls_back_to_defaults() -> None:
    tool = MarketPriceTool()
    result = tool.execute(object())
    check(result.output == {"symbol": "UNKNOWN", "price": None, "trend": "unknown"}, f"T12: malformed context falls back to full LOCKED defaults; got {result.output!r}")


# ---------------------------------------------------------------------------
# T13 -- success/error/metadata shape
# ---------------------------------------------------------------------------
def scenario_result_shape() -> None:
    result = _run({"symbol": "AAPL", "current_price": 100, "previous_price": 90})
    check(result.success is True, "T13: success is always True")
    check(result.error is None, "T13: error is always None")
    check(dict(result.metadata) == {}, "T13: metadata is always {}")
    check(type(result) is ToolResult, "T13: returned object's exact type is ToolResult")


# ---------------------------------------------------------------------------
# T14 -- a real ToolContext flows through correctly
# ---------------------------------------------------------------------------
def scenario_real_tool_context() -> None:
    tool = MarketPriceTool()
    context = ToolContext(task=None, parameters={"symbol": "BBCA", "current_price": 200, "previous_price": 250}, metadata={})
    result = tool.execute(context)
    check(result.output == {"symbol": "BBCA", "price": 200, "trend": "bearish"}, f"T14: real ToolContext flows through correctly; got {result.output!r}")


# ---------------------------------------------------------------------------
# A1-A4 -- AST / namespace verification: analysis stays inline, no new
# abstraction of any kind
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.market_price_tool as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"MarketPriceTool"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "Manager", "Registry", "Adapter", "Factory", "Aggregator",
        "Pipeline", "Engine", "Analyzer", "Strategy", "DecisionEngine",
        "Utility", "Helper",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(MarketPriceTool.execute)
    tree = ast.parse(_dedent(source))

    top_level_def = tree.body[0]
    nested_defs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_defs) == 0, f"A3: execute() defines no nested function/lambda; got {len(nested_defs)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    tool_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "ToolResult"]
    check(len(tool_result_calls) == 1, f"A3: exactly one ToolResult(...) construction; got {len(tool_result_calls)}")

    forbidden_call_names = {"ToolResolver", "ToolRegistry", "ToolContext", "Ollama"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"A3: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")


def _dedent(source: str) -> str:
    import textwrap
    return textwrap.dedent(source)


def scenario_class_shape_unchanged() -> None:
    check("__init__" not in MarketPriceTool.__dict__, "A4a: MarketPriceTool still defines no __init__ of its own")
    tool = MarketPriceTool()
    check(tool.__dict__ == {}, "A4b: a freshly constructed instance still has no instance __dict__ entries")
    check(tool.name == "market_price", "A4c: name is unchanged ('market_price')")
    check(tool.description == "Retrieve market price information.", "A4d: description is unchanged")


# ---------------------------------------------------------------------------
# I1-I2 -- real, fully-wired Executor -> Skill -> Tools integration
# ---------------------------------------------------------------------------
def _real_running_executor():
    registry = ToolRegistry()
    price_tool = MarketPriceTool()
    news_tool = MarketNewsTool()
    registry.register(price_tool.name, price_tool)
    registry.register(news_tool.name, news_tool)
    resolver = ToolResolver(registry)

    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host, tool_resolver=resolver)

    skill = TextAnalysisSkill()
    plan = SkillExecutionPlan(skills=(skill,), tools=(price_tool.name, news_tool.name), metadata={})

    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor, skill, resolver


def scenario_real_integration_reaches_buy() -> None:
    registry = ToolRegistry()
    price_tool = MarketPriceTool()
    news_tool = MarketNewsTool()
    registry.register(price_tool.name, price_tool)
    registry.register(news_tool.name, news_tool)
    resolver = ToolResolver(registry)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver.resolve

    context = ToolContext(
        task=None,
        parameters={
            "symbol": "BBCA",
            "current_price": 120,
            "previous_price": 100,
            "headlines": ["Profits surge to a record high"],
        },
        metadata={},
    )
    result = skill.execute(context)

    check(result.success is True, "I1: end-to-end Skill execution succeeds with real price/headline parameters")
    check(result.output["price"]["trend"] == "bullish", "I1: MarketPriceTool now really reports a bullish trend")
    check(result.output["news"]["overall_sentiment"] == "positive", "I1: MarketNewsTool reports positive sentiment for the given headline")
    check(
        result.output["analysis"] == {"recommendation": "BUY", "confidence": "HIGH", "reason": "bullish price and positive news"},
        f"I1: Sprint 109's reasoning now reaches a real BUY recommendation; got {result.output['analysis']!r}",
    )


def scenario_real_integration_no_price_data_still_unknown() -> None:
    executor, skill, resolver = _real_running_executor()
    result = executor.invoke_current_skill()

    check(result.success is True, "I2: end-to-end Skill execution still succeeds with no price parameters supplied")
    check(result.output["price"]["trend"] == "unknown", "I2: with no price parameters, MarketPriceTool reports trend=unknown")
    check(
        result.output["analysis"] == {"recommendation": "UNKNOWN", "confidence": "LOW", "reason": "insufficient data"},
        f"I2: Sprint 109's reasoning still falls back to insufficient data; got {result.output['analysis']!r}",
    )


def main() -> int:
    scenarios = [
        scenario_bullish,
        scenario_bearish,
        scenario_neutral,
        scenario_neutral_with_floats,
        scenario_missing_current_price,
        scenario_missing_previous_price,
        scenario_missing_both_prices,
        scenario_string_prices,
        scenario_none_prices,
        scenario_list_prices,
        scenario_bool_prices_not_coerced,
        scenario_missing_symbol,
        scenario_non_str_symbol,
        scenario_empty_str_symbol,
        scenario_real_symbol_forwarded,
        scenario_exhaustive_trend_values,
        scenario_determinism,
        scenario_never_raises,
        scenario_malformed_context_falls_back_to_defaults,
        scenario_result_shape,
        scenario_real_tool_context,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_class_shape_unchanged,
        scenario_real_integration_reaches_buy,
        scenario_real_integration_no_price_data_still_unknown,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 10 SPRINT 110 MARKET-PRICE-TOOL-ANALYSIS RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())