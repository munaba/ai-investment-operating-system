"""Phase 10 Sprint 109 proof suite -- First Deterministic Reasoning.

``TextAnalysisSkill.execute(context)`` still calls the same two Tools
(``"market_price"`` then ``"market_news"``) through the same,
already-frozen ``BaseSkill.execute_tool_result()`` API Sprint 108
already used, and still combines their two ``SkillResult`` values the
same way (``success`` = AND, ``error`` = joined failures,
``metadata`` = ``{}``). Sprint 109 adds exactly one new thing: a
third ``"analysis"`` entry in ``output``, derived from the price
Tool's ``"trend"`` value and the news Tool's ``"overall_sentiment"``
value via the LOCKED four-row decision table, entirely inline inside
``execute()``. No new class, Manager, Registry, Adapter, Factory,
Analyzer, Engine, Strategy, DecisionEngine, Pipeline, Utility, or
Helper module was introduced anywhere in this project to add it.

Scope: dedicated proof suite for the Sprint 109 change to
``Orchestration.text_analysis_skill.TextAnalysisSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-main()
style already used by
``Tests/test_stage_l108_text_analysis_skill_multi_tool.py``.

Three layers of coverage:

  1. Seam-level scenarios that inject ``_resolve_tool`` directly on a
     ``TextAnalysisSkill`` instance -- exactly the same seam
     ``Executor.invoke_current_skill()`` uses in production -- using
     local, duck-typed Tool stand-ins that return fixed
     ``ToolResult`` outputs, to drive every row of the LOCKED
     decision table plus every "insufficient data" case.
  2. AST/namespace verification proving the reasoning lives entirely
     inline inside ``execute()`` and that no forbidden abstraction
     (Manager, Engine, Analyzer, Strategy, DecisionEngine, Pipeline,
     Registry, Factory, Adapter, Utility, Helper) was introduced.
  3. A real, fully-wired integration scenario -- genuine ``Executor``,
     ``ToolRegistry``, ``ToolResolver``, real ``TextAnalysisSkill``,
     real ``MarketPriceTool`` AND real ``MarketNewsTool`` -- proving
     that, with today's real Tools (``MarketPriceTool`` has no
     ``"trend"`` output at all), the reasoning deterministically and
     correctly falls back to "insufficient data" rather than
     guessing.

Invariant coverage:
    R1  -- bullish + positive -> recommendation=BUY, confidence=HIGH,
           reason="bullish price and positive news".
    R2  -- bullish + negative -> recommendation=WAIT,
           confidence=MEDIUM, reason="bullish price and negative
           news".
    R3  -- bearish + positive -> recommendation=WAIT,
           confidence=MEDIUM, reason="bearish price and positive
           news".
    R4  -- bearish + negative -> recommendation=SELL,
           confidence=HIGH, reason="bearish price and negative
           news".
    R5  -- no other (trend, sentiment) combination ever produces
           BUY/WAIT/SELL -- only the four exact pairs above do.
    U1  -- missing "trend" key -> UNKNOWN/LOW/"insufficient data".
    U2  -- missing "overall_sentiment" key -> UNKNOWN/LOW/
           "insufficient data".
    U3  -- both missing -> UNKNOWN/LOW/"insufficient data".
    U4  -- unrecognized trend value (e.g. "sideways") ->
           UNKNOWN/LOW/"insufficient data".
    U5  -- unrecognized sentiment value (e.g. "neutral") ->
           UNKNOWN/LOW/"insufficient data".
    U6  -- non-dict price/news output (``None``, a plain string) ->
           UNKNOWN/LOW/"insufficient data", no exception raised.
    U7  -- a failed sub-call (``success=False``, ``output=None``)
           still yields UNKNOWN/LOW/"insufficient data" for
           "analysis", without disturbing the existing Sprint 108
           combined success/error logic.
    S1  -- ``output`` has exactly the three keys "price", "news",
           "analysis".
    S2  -- ``output["analysis"]`` has exactly the three keys
           "recommendation", "confidence", "reason".
    S3  -- ``output["price"]``/``output["news"]`` are still forwarded
           by identity, unchanged from Sprint 108.
    C1  -- combined success/error logic (AND / joined failure
           strings) is unchanged from Sprint 108, independent of the
           new "analysis" entry.
    A1  -- AST: no forbidden-name symbol (Manager, Registry, Adapter,
           Factory, Aggregator, Pipeline, MultiToolExecutor, Engine,
           Analyzer, Strategy, DecisionEngine, Utility, Helper)
           anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           TextAnalysisSkill.
    A3  -- AST: execute() defines no nested function/lambda -- the
           decision table is plain, flat if/elif/else inside
           execute() itself, not a helper closure.
    A4  -- AST: execute_tool_result() is still called exactly twice,
           with tool_name literals "market_price" and "market_news"
           in that order (Sprint 108 invariant, still true).
    A5  -- AST: exactly one SkillResult(...) construction.
    A6  -- class shape: still no __init__ of its own, no per-instance
           state; name/description unchanged.
    I1  -- real integration: Executor -> invoke_current_skill() ->
           TextAnalysisSkill -> {MarketPriceTool, MarketNewsTool} ->
           SkillResult succeeds end-to-end.
    I2  -- real integration: with today's real Tools (no "trend" in
           MarketPriceTool's output), "analysis" is deterministically
           {"recommendation": "UNKNOWN", "confidence": "LOW",
           "reason": "insufficient data"}.
    I3  -- real integration: repeated calls are field-equal
           (deterministic, no randomness, no timestamps).
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
# Fixtures (seam-level test doubles -- duck-typed Tools, not framework mocks)
# ---------------------------------------------------------------------------
class _FixedTool:
    """A duck-typed Tool stand-in that always returns a fixed
    ``ToolResult``, regardless of context."""

    def __init__(self, result: ToolResult):
        self.result = result

    def execute(self, context):
        return self.result


class _FixedResolver:
    """Dispatches to whichever fixed Tool stand-in was registered
    under the requested name -- exactly the shape
    ``Executor.invoke_current_skill()`` injects as
    ``skill._resolve_tool``."""

    def __init__(self, tools: dict):
        self.tools = tools

    def __call__(self, name):
        return self.tools[name]


def _skill_with(price_output: Any, news_output: Any, price_success: bool = True, news_success: bool = True):
    price_tool = _FixedTool(ToolResult(success=price_success, output=price_output, error=None if price_success else "boom", metadata={}))
    news_tool = _FixedTool(ToolResult(success=news_success, output=news_output, error=None if news_success else "boom", metadata={}))
    resolver = _FixedResolver({"market_price": price_tool, "market_news": news_tool})

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver
    return skill


def _run(price_output: Any, news_output: Any, price_success: bool = True, news_success: bool = True) -> SkillResult:
    skill = _skill_with(price_output, news_output, price_success, news_success)
    return skill.execute(object())


# ---------------------------------------------------------------------------
# R1-R4 -- the four LOCKED decision-table rows
# ---------------------------------------------------------------------------
def scenario_bullish_positive_buy_high() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "BUY", "R1: bullish+positive -> recommendation=BUY")
    check(analysis["confidence"] == "HIGH", "R1: bullish+positive -> confidence=HIGH")
    check(analysis["reason"] == "bullish price and positive news", "R1: bullish+positive -> exact reason string")


def scenario_bullish_negative_wait_medium() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "negative"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "WAIT", "R2: bullish+negative -> recommendation=WAIT")
    check(analysis["confidence"] == "MEDIUM", "R2: bullish+negative -> confidence=MEDIUM")
    check(analysis["reason"] == "bullish price and negative news", "R2: bullish+negative -> exact reason string")


def scenario_bearish_positive_wait_medium() -> None:
    result = _run({"trend": "bearish"}, {"overall_sentiment": "positive"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "WAIT", "R3: bearish+positive -> recommendation=WAIT")
    check(analysis["confidence"] == "MEDIUM", "R3: bearish+positive -> confidence=MEDIUM")
    check(analysis["reason"] == "bearish price and positive news", "R3: bearish+positive -> exact reason string")


def scenario_bearish_negative_sell_high() -> None:
    result = _run({"trend": "bearish"}, {"overall_sentiment": "negative"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "SELL", "R4: bearish+negative -> recommendation=SELL")
    check(analysis["confidence"] == "HIGH", "R4: bearish+negative -> confidence=HIGH")
    check(analysis["reason"] == "bearish price and negative news", "R4: bearish+negative -> exact reason string")


# ---------------------------------------------------------------------------
# U1-U7 -- missing / unknown / malformed data always -> insufficient data
# ---------------------------------------------------------------------------
def _check_insufficient_data(result: SkillResult, label: str) -> None:
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "UNKNOWN", f"{label}: recommendation=UNKNOWN")
    check(analysis["confidence"] == "LOW", f"{label}: confidence=LOW")
    check(analysis["reason"] == "insufficient data", f"{label}: reason='insufficient data'")


def scenario_missing_trend() -> None:
    result = _run({"symbol": "AAPL"}, {"overall_sentiment": "positive"})
    _check_insufficient_data(result, "U1")


def scenario_missing_sentiment() -> None:
    result = _run({"trend": "bullish"}, {"symbol": "AAPL"})
    _check_insufficient_data(result, "U2")


def scenario_both_missing() -> None:
    result = _run({"symbol": "AAPL"}, {"symbol": "AAPL"})
    _check_insufficient_data(result, "U3")


def scenario_unrecognized_trend() -> None:
    result = _run({"trend": "sideways"}, {"overall_sentiment": "positive"})
    _check_insufficient_data(result, "U4")


def scenario_unrecognized_sentiment() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "neutral"})
    _check_insufficient_data(result, "U5")


def scenario_non_dict_outputs() -> None:
    exc = _catch(lambda: _run(None, "some string"))
    check(exc is None, f"U6: non-dict outputs never raise; got {exc!r}")
    result = _run(None, "some string")
    _check_insufficient_data(result, "U6")


def scenario_failed_subcall_still_insufficient_data() -> None:
    result = _run({"trend": "bullish"}, None, news_success=False)
    _check_insufficient_data(result, "U7")
    check(result.success is False, "U7: combined success still False when a sub-call failed")
    check(isinstance(result.error, str) and "market_news" in result.error, "U7: combined error still mentions the failing tool")


# ---------------------------------------------------------------------------
# R5 -- exhaustive sweep: only the four exact pairs ever produce a
# non-UNKNOWN recommendation
# ---------------------------------------------------------------------------
def scenario_exhaustive_sweep() -> None:
    trends = ["bullish", "bearish", "sideways", None, "", "BULLISH"]
    sentiments = ["positive", "negative", "neutral", None, "", "POSITIVE"]

    locked_pairs = {
        ("bullish", "positive"): ("BUY", "HIGH"),
        ("bullish", "negative"): ("WAIT", "MEDIUM"),
        ("bearish", "positive"): ("WAIT", "MEDIUM"),
        ("bearish", "negative"): ("SELL", "HIGH"),
    }

    all_correct = True
    for trend in trends:
        for sentiment in sentiments:
            price_output = {} if trend is None else {"trend": trend}
            news_output = {} if sentiment is None else {"overall_sentiment": sentiment}
            result = _run(price_output, news_output)
            analysis = result.output["analysis"]
            expected = locked_pairs.get((trend, sentiment))
            if expected is None:
                if not (analysis["recommendation"] == "UNKNOWN" and analysis["confidence"] == "LOW"):
                    all_correct = False
            else:
                expected_rec, expected_conf = expected
                if not (analysis["recommendation"] == expected_rec and analysis["confidence"] == expected_conf):
                    all_correct = False

    check(all_correct, "R5: exhaustive sweep -- only the four LOCKED pairs ever produce BUY/WAIT/SELL; every other combination is UNKNOWN/LOW")


# ---------------------------------------------------------------------------
# S1-S3 -- output shape
# ---------------------------------------------------------------------------
def scenario_output_shape() -> None:
    result = _run({"trend": "bullish", "price": 100}, {"overall_sentiment": "positive", "sentiment_score": 3})
    check(set(result.output.keys()) == {"price", "news", "analysis"}, f"S1: output has exactly keys price/news/analysis; got {set(result.output.keys())!r}")
    check(set(result.output["analysis"].keys()) == {"recommendation", "confidence", "reason"}, f"S2: analysis has exactly keys recommendation/confidence/reason; got {set(result.output['analysis'].keys())!r}")


def scenario_price_news_still_forwarded_by_identity() -> None:
    price_output = {"trend": "bearish", "price": 55.5}
    news_output = {"overall_sentiment": "negative"}
    skill = _skill_with(price_output, news_output)
    result = skill.execute(object())
    check(result.output["price"] is price_output, "S3: 'price' still forwarded by identity, unchanged from Sprint 108")
    check(result.output["news"] is news_output, "S3: 'news' still forwarded by identity, unchanged from Sprint 108")


# ---------------------------------------------------------------------------
# C1 -- Sprint 108 success/error combination logic unchanged
# ---------------------------------------------------------------------------
def scenario_combination_logic_unchanged() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"})
    check(result.success is True, "C1: combined success True when both sub-calls succeed")
    check(result.error is None, "C1: combined error None when both sub-calls succeed")

    result2 = _run({"trend": "bullish"}, None, price_success=False, news_success=False)
    check(result2.success is False, "C1: combined success False when both sub-calls fail")
    check("market_price" in result2.error and "market_news" in result2.error, "C1: combined error mentions both failing tools")


# ---------------------------------------------------------------------------
# A1-A6 -- AST / namespace verification: reasoning stays inline, no new
# abstraction of any kind
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.text_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"TextAnalysisSkill"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "Manager", "Registry", "Adapter", "Factory", "Aggregator",
        "Pipeline", "MultiToolExecutor", "Engine", "Analyzer",
        "Strategy", "DecisionEngine", "Utility", "Helper",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def scenario_execute_body_shape() -> None:
    source = inspect.getsource(TextAnalysisSkill.execute)
    tree = ast.parse(_dedent(source))

    top_level_def = tree.body[0]
    nested_defs = [
        n for n in ast.walk(top_level_def)
        if n is not top_level_def and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    check(len(nested_defs) == 0, f"A3: execute() defines no nested function/lambda; got {len(nested_defs)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    execute_tool_result_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "execute_tool_result"
    ]
    check(len(execute_tool_result_calls) == 2, f"A4: execute_tool_result() still called exactly twice; got {len(execute_tool_result_calls)}")
    tool_names_in_order = [c.args[0].value for c in execute_tool_result_calls if isinstance(c.args[0], ast.Constant)]
    check(tool_names_in_order == ["market_price", "market_news"], f"A4: tool names still requested in order ['market_price', 'market_news']; got {tool_names_in_order!r}")

    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A5: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    forbidden_call_names = {"ToolResult", "ToolResolver", "ToolRegistry", "ToolContext", "Ollama"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"A5: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")


def _dedent(source: str) -> str:
    import textwrap
    return textwrap.dedent(source)


def scenario_class_shape_unchanged() -> None:
    check("__init__" not in TextAnalysisSkill.__dict__, "A6a: TextAnalysisSkill still defines no __init__ of its own")
    skill = TextAnalysisSkill()
    check(skill.__dict__ == {}, "A6b: a freshly constructed instance still has no instance __dict__ entries")
    check(skill.name == "text_analysis", "A6c: name is unchanged ('text_analysis')")
    check(skill.description == "Analyze textual information.", "A6d: description is unchanged")


# ---------------------------------------------------------------------------
# I1-I3 -- real, fully-wired integration (no test doubles)
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
    return executor


def scenario_real_integration() -> None:
    executor = _real_running_executor()

    result = None
    error = None
    try:
        result = executor.invoke_current_skill()
    except Exception as e:  # noqa: BLE001
        error = e

    check(error is None, f"I1: real Executor -> Skill -> {{MarketPriceTool, MarketNewsTool}} pipeline runs end-to-end without raising; got {error!r}")
    check(isinstance(result, SkillResult), "I1: invoke_current_skill() returns a real SkillResult")
    check(result.success is True, "I1: SkillResult.success is True")

    check(
        result.output["analysis"] == {"recommendation": "UNKNOWN", "confidence": "LOW", "reason": "insufficient data"},
        f"I2: with today's real MarketPriceTool (no 'trend' output), analysis deterministically falls back to insufficient data; got {result.output['analysis']!r}",
    )


def scenario_real_integration_repeat_call_deterministic() -> None:
    executor = _real_running_executor()
    result1 = executor.invoke_current_skill()
    result2 = executor.invoke_current_skill()

    check(result1 is not result2, "I3a: two separate invoke_current_skill() calls produce two distinct SkillResult objects")
    check(result1 == result2, "I3b: the two SkillResults are field-equal (fully deterministic, no randomness/timestamps)")


def main() -> int:
    scenarios = [
        scenario_bullish_positive_buy_high,
        scenario_bullish_negative_wait_medium,
        scenario_bearish_positive_wait_medium,
        scenario_bearish_negative_sell_high,
        scenario_missing_trend,
        scenario_missing_sentiment,
        scenario_both_missing,
        scenario_unrecognized_trend,
        scenario_unrecognized_sentiment,
        scenario_non_dict_outputs,
        scenario_failed_subcall_still_insufficient_data,
        scenario_exhaustive_sweep,
        scenario_output_shape,
        scenario_price_news_still_forwarded_by_identity,
        scenario_combination_logic_unchanged,
        scenario_no_forbidden_abstractions,
        scenario_execute_body_shape,
        scenario_class_shape_unchanged,
        scenario_real_integration,
        scenario_real_integration_repeat_call_deterministic,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 10 SPRINT 109 TEXT-ANALYSIS-REASONING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())