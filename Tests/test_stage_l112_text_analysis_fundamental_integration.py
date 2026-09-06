"""Phase 10 Sprint 112 proof suite -- Fundamental Integration.

``TextAnalysisSkill.execute(context)`` now calls THREE Tools --
``"market_price"``, ``"market_news"``, and ``"market_fundamental"``
-- through the same, already-frozen ``BaseSkill.execute_tool_result()``
API Sprint 106/108 already used, combines their three ``SkillResult``
values the same way (``success`` = AND of all three, ``error`` =
joined failures, ``metadata`` = ``{}``), and extends the Sprint 109
deterministic decision table with a third input: the fundamental
Tool's ``"valuation"`` value. No new class, Manager, Registry,
Adapter, Factory, Analyzer, Engine, Strategy, DecisionEngine,
RuleEngine, Pipeline, Utility, or Helper module was introduced
anywhere in this project to add it.

Scope: dedicated proof suite for the Sprint 112 change to
``Orchestration.text_analysis_skill.TextAnalysisSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-main()
style already used by
``Tests/test_stage_l109_text_analysis_reasoning.py``.

Three layers of coverage:

  1. Seam-level scenarios that inject ``_resolve_tool`` directly on a
     ``TextAnalysisSkill`` instance -- exactly the same seam
     ``Executor.invoke_current_skill()`` uses in production -- using
     local, duck-typed Tool stand-ins that return fixed
     ``ToolResult`` outputs, to drive every row of the LOCKED
     three-input decision table plus every "insufficient data" case.
  2. AST/namespace verification proving the reasoning lives entirely
     inline inside ``execute()``, that all three Tools are called by
     name exactly once each via ``execute_tool_result()``, and that
     no forbidden abstraction (Manager, Engine, Analyzer, Strategy,
     DecisionEngine, RuleEngine, Pipeline, Registry, Factory,
     Adapter, Utility, Helper) was introduced.
  3. A real, fully-wired integration scenario -- genuine ``Executor``,
     ``ToolRegistry``, ``ToolResolver``, real ``TextAnalysisSkill``,
     real ``MarketPriceTool``, real ``MarketNewsTool``, AND real
     ``MarketFundamentalTool`` -- proving that, with today's real
     Tools (``MarketPriceTool`` has no ``"trend"`` output at all),
     the reasoning deterministically and correctly falls back to
     "insufficient data" rather than guessing, and that the
     ``"fundamental"`` key is present and forwarded by identity.

Invariant coverage:
    R1  -- bullish + positive + undervalued -> BUY / HIGH.
    R2  -- bearish + negative + overvalued  -> SELL / HIGH.
    R3  -- bullish + negative + fair        -> WAIT / MEDIUM.
    R4  -- bearish + positive + fair        -> WAIT / MEDIUM.
    R5  -- no other (trend, sentiment, valuation) triple ever
           produces BUY/WAIT/SELL -- only the four exact triples
           above do.
    U1  -- missing "valuation" key -> UNKNOWN/LOW/"insufficient data".
    U2  -- all three missing -> UNKNOWN/LOW/"insufficient data".
    U3  -- unrecognized valuation value -> UNKNOWN/LOW/"insufficient
           data".
    U4  -- non-dict fundamental output (``None``, a plain string) ->
           UNKNOWN/LOW/"insufficient data", no exception raised.
    U5  -- a failed sub-call (``success=False``, ``output=None``)
           still yields UNKNOWN/LOW/"insufficient data" for
           "analysis", without disturbing the combined success/error
           logic.
    S1  -- ``output`` has exactly the four keys "price", "news",
           "fundamental", "analysis".
    S2  -- ``output["analysis"]`` has exactly the three keys
           "recommendation", "confidence", "reason".
    S3  -- ``output["price"]``/``["news"]``/``["fundamental"]`` are
           forwarded by identity, unchanged.
    C1  -- combined success/error logic (AND of three / joined
           failure strings) is correct, independent of the "analysis"
           entry.
    A1  -- AST: no forbidden-name symbol (Manager, Registry, Adapter,
           Factory, Aggregator, Pipeline, MultiToolExecutor, Engine,
           Analyzer, Strategy, DecisionEngine, RuleEngine, Utility,
           Helper) anywhere in the module namespace.
    A2  -- AST: the module defines exactly one class,
           TextAnalysisSkill.
    A3  -- AST: execute() defines no nested function/lambda -- the
           decision table is plain, flat if/elif/else inside
           execute() itself, not a helper closure.
    A4  -- AST: execute_tool_result() is called exactly three times,
           with tool_name literals "market_price", "market_news",
           "market_fundamental" in that order.
    A5  -- AST: exactly one SkillResult(...) construction.
    A6  -- class shape: still no __init__ of its own, no per-instance
           state; name/description unchanged.
    I1  -- real integration: Executor -> invoke_current_skill() ->
           TextAnalysisSkill -> {MarketPriceTool, MarketNewsTool,
           MarketFundamentalTool} -> SkillResult succeeds end-to-end.
    I2  -- real integration: with today's real Tools (no "trend" in
           MarketPriceTool's output), "analysis" is deterministically
           {"recommendation": "UNKNOWN", "confidence": "LOW",
           "reason": "insufficient data"}.
    I3  -- real integration: "fundamental" key is present in output
           and repeated calls are field-equal (deterministic, no
           randomness, no timestamps).
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

from Orchestration.autonomous_host import AutonomousHost
from Orchestration.executor import Executor
from Orchestration.market_fundamental_tool import MarketFundamentalTool
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


def _skill_with(
    price_output: Any,
    news_output: Any,
    fundamental_output: Any,
    price_success: bool = True,
    news_success: bool = True,
    fundamental_success: bool = True,
):
    price_tool = _FixedTool(ToolResult(success=price_success, output=price_output, error=None if price_success else "boom", metadata={}))
    news_tool = _FixedTool(ToolResult(success=news_success, output=news_output, error=None if news_success else "boom", metadata={}))
    fundamental_tool = _FixedTool(ToolResult(success=fundamental_success, output=fundamental_output, error=None if fundamental_success else "boom", metadata={}))
    resolver = _FixedResolver({
        "market_price": price_tool,
        "market_news": news_tool,
        "market_fundamental": fundamental_tool,
    })

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver
    return skill


def _run(
    price_output: Any,
    news_output: Any,
    fundamental_output: Any,
    price_success: bool = True,
    news_success: bool = True,
    fundamental_success: bool = True,
) -> SkillResult:
    skill = _skill_with(price_output, news_output, fundamental_output, price_success, news_success, fundamental_success)
    return skill.execute(object())


# ---------------------------------------------------------------------------
# R1-R4 -- the four LOCKED decision-table rows
# ---------------------------------------------------------------------------
def scenario_bullish_positive_undervalued_buy_high() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"}, {"valuation": "undervalued"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "BUY", "R1: bullish+positive+undervalued -> recommendation=BUY")
    check(analysis["confidence"] == "HIGH", "R1: bullish+positive+undervalued -> confidence=HIGH")
    check(analysis["reason"] == "bullish price, positive news, undervalued fundamental", "R1: exact reason string")


def scenario_bearish_negative_overvalued_sell_high() -> None:
    result = _run({"trend": "bearish"}, {"overall_sentiment": "negative"}, {"valuation": "overvalued"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "SELL", "R2: bearish+negative+overvalued -> recommendation=SELL")
    check(analysis["confidence"] == "HIGH", "R2: bearish+negative+overvalued -> confidence=HIGH")
    check(analysis["reason"] == "bearish price, negative news, overvalued fundamental", "R2: exact reason string")


def scenario_bullish_negative_fair_wait_medium() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "negative"}, {"valuation": "fair"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "WAIT", "R3: bullish+negative+fair -> recommendation=WAIT")
    check(analysis["confidence"] == "MEDIUM", "R3: bullish+negative+fair -> confidence=MEDIUM")
    check(analysis["reason"] == "bullish price, negative news, fair fundamental", "R3: exact reason string")


def scenario_bearish_positive_fair_wait_medium() -> None:
    result = _run({"trend": "bearish"}, {"overall_sentiment": "positive"}, {"valuation": "fair"})
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "WAIT", "R4: bearish+positive+fair -> recommendation=WAIT")
    check(analysis["confidence"] == "MEDIUM", "R4: bearish+positive+fair -> confidence=MEDIUM")
    check(analysis["reason"] == "bearish price, positive news, fair fundamental", "R4: exact reason string")


# ---------------------------------------------------------------------------
# U1-U5 -- missing / unknown / malformed data always -> insufficient data
# ---------------------------------------------------------------------------
def _check_insufficient_data(result: SkillResult, label: str) -> None:
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "UNKNOWN", f"{label}: recommendation=UNKNOWN")
    check(analysis["confidence"] == "LOW", f"{label}: confidence=LOW")
    check(analysis["reason"] == "insufficient data", f"{label}: reason='insufficient data'")


def scenario_missing_valuation() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"}, {"symbol": "AAPL"})
    _check_insufficient_data(result, "U1")


def scenario_all_missing() -> None:
    result = _run({"symbol": "AAPL"}, {"symbol": "AAPL"}, {"symbol": "AAPL"})
    _check_insufficient_data(result, "U2")


def scenario_unrecognized_valuation() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"}, {"valuation": "unknown"})
    _check_insufficient_data(result, "U3")


def scenario_non_dict_fundamental_output() -> None:
    exc = _catch(lambda: _run({"trend": "bullish"}, {"overall_sentiment": "positive"}, None))
    check(exc is None, f"U4: non-dict fundamental output never raises; got {exc!r}")
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"}, "some string")
    _check_insufficient_data(result, "U4")


def scenario_failed_subcall_still_insufficient_data() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"}, None, fundamental_success=False)
    _check_insufficient_data(result, "U5")
    check(result.success is False, "U5: combined success still False when a sub-call failed")
    check(isinstance(result.error, str) and "market_fundamental" in result.error, "U5: combined error still mentions the failing tool")


# ---------------------------------------------------------------------------
# R5 -- exhaustive sweep: only the four exact triples ever produce a
# non-UNKNOWN recommendation
# ---------------------------------------------------------------------------
def scenario_exhaustive_sweep() -> None:
    trends = ["bullish", "bearish", "neutral", None]
    sentiments = ["positive", "negative", "neutral", None]
    valuations = ["undervalued", "fair", "overvalued", None]

    locked_triples = {
        ("bullish", "positive", "undervalued"): ("BUY", "HIGH"),
        ("bearish", "negative", "overvalued"): ("SELL", "HIGH"),
        ("bullish", "negative", "fair"): ("WAIT", "MEDIUM"),
        ("bearish", "positive", "fair"): ("WAIT", "MEDIUM"),
    }

    all_correct = True
    for trend in trends:
        for sentiment in sentiments:
            for valuation in valuations:
                price_output = {} if trend is None else {"trend": trend}
                news_output = {} if sentiment is None else {"overall_sentiment": sentiment}
                fundamental_output = {} if valuation is None else {"valuation": valuation}
                result = _run(price_output, news_output, fundamental_output)
                analysis = result.output["analysis"]
                expected = locked_triples.get((trend, sentiment, valuation))
                if expected is None:
                    if not (analysis["recommendation"] == "UNKNOWN" and analysis["confidence"] == "LOW"):
                        all_correct = False
                else:
                    expected_rec, expected_conf = expected
                    if not (analysis["recommendation"] == expected_rec and analysis["confidence"] == expected_conf):
                        all_correct = False

    check(all_correct, "R5: exhaustive sweep -- only the four LOCKED triples ever produce BUY/WAIT/SELL; every other combination is UNKNOWN/LOW")


# ---------------------------------------------------------------------------
# S1-S3 -- output shape
# ---------------------------------------------------------------------------
def scenario_output_shape() -> None:
    result = _run(
        {"trend": "bullish", "price": 100},
        {"overall_sentiment": "positive", "sentiment_score": 3},
        {"valuation": "undervalued", "quality": "strong"},
    )
    check(set(result.output.keys()) == {"price", "news", "fundamental", "analysis"}, f"S1: output has exactly keys price/news/fundamental/analysis; got {set(result.output.keys())!r}")
    check(set(result.output["analysis"].keys()) == {"recommendation", "confidence", "reason"}, f"S2: analysis has exactly keys recommendation/confidence/reason; got {set(result.output['analysis'].keys())!r}")


def scenario_all_outputs_forwarded_by_identity() -> None:
    price_output = {"trend": "bearish", "price": 55.5}
    news_output = {"overall_sentiment": "negative"}
    fundamental_output = {"valuation": "overvalued", "quality": "weak"}
    skill = _skill_with(price_output, news_output, fundamental_output)
    result = skill.execute(object())
    check(result.output["price"] is price_output, "S3: 'price' forwarded by identity")
    check(result.output["news"] is news_output, "S3: 'news' forwarded by identity")
    check(result.output["fundamental"] is fundamental_output, "S3: 'fundamental' forwarded by identity")


# ---------------------------------------------------------------------------
# C1 -- success/error combination logic across three sub-calls
# ---------------------------------------------------------------------------
def scenario_combination_logic() -> None:
    result = _run({"trend": "bullish"}, {"overall_sentiment": "positive"}, {"valuation": "undervalued"})
    check(result.success is True, "C1: combined success True when all three sub-calls succeed")
    check(result.error is None, "C1: combined error None when all three sub-calls succeed")

    result2 = _run(
        {"trend": "bullish"}, None, None,
        price_success=False, news_success=False, fundamental_success=False,
    )
    check(result2.success is False, "C1: combined success False when all three sub-calls fail")
    check(
        "market_price" in result2.error and "market_news" in result2.error and "market_fundamental" in result2.error,
        "C1: combined error mentions all three failing tools",
    )


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
        "Strategy", "DecisionEngine", "RuleEngine", "Utility", "Helper",
    )
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"A1: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


def _dedent(source: str) -> str:
    return textwrap.dedent(source)


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
    check(len(execute_tool_result_calls) == 3, f"A4: execute_tool_result() called exactly three times; got {len(execute_tool_result_calls)}")
    tool_names_in_order = [c.args[0].value for c in execute_tool_result_calls if isinstance(c.args[0], ast.Constant)]
    check(
        tool_names_in_order == ["market_price", "market_news", "market_fundamental"],
        f"A4: tool names requested in order ['market_price', 'market_news', 'market_fundamental']; got {tool_names_in_order!r}",
    )

    skill_result_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "SkillResult"]
    check(len(skill_result_calls) == 1, f"A5: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    forbidden_call_names = {"ToolResult", "ToolResolver", "ToolRegistry", "ToolContext", "Ollama"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"A5: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")


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
    fundamental_tool = MarketFundamentalTool()
    registry.register(price_tool.name, price_tool)
    registry.register(news_tool.name, news_tool)
    registry.register(fundamental_tool.name, fundamental_tool)
    resolver = ToolResolver(registry)

    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host, tool_resolver=resolver)

    skill = TextAnalysisSkill()
    plan = SkillExecutionPlan(
        skills=(skill,),
        tools=(price_tool.name, news_tool.name, fundamental_tool.name),
        metadata={},
    )

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

    check(error is None, f"I1: real Executor -> Skill -> {{MarketPriceTool, MarketNewsTool, MarketFundamentalTool}} pipeline runs end-to-end without raising; got {error!r}")
    check(isinstance(result, SkillResult), "I1: invoke_current_skill() returns a real SkillResult")
    check(result.success is True, "I1: SkillResult.success is True")

    check(
        result.output["analysis"] == {"recommendation": "UNKNOWN", "confidence": "LOW", "reason": "insufficient data"},
        f"I2: with today's real Tools (no 'trend' in MarketPriceTool's output), analysis deterministically falls back to insufficient data; got {result.output['analysis']!r}",
    )
    check("fundamental" in result.output, "I3a: 'fundamental' key present in output with real Tools")


def scenario_real_integration_repeat_call_deterministic() -> None:
    executor = _real_running_executor()
    result1 = executor.invoke_current_skill()
    result2 = executor.invoke_current_skill()

    check(result1 is not result2, "I3b: two separate invoke_current_skill() calls produce two distinct SkillResult objects")
    check(result1 == result2, "I3c: the two SkillResults are field-equal (fully deterministic, no randomness/timestamps)")


def main() -> int:
    scenarios = [
        scenario_bullish_positive_undervalued_buy_high,
        scenario_bearish_negative_overvalued_sell_high,
        scenario_bullish_negative_fair_wait_medium,
        scenario_bearish_positive_fair_wait_medium,
        scenario_missing_valuation,
        scenario_all_missing,
        scenario_unrecognized_valuation,
        scenario_non_dict_fundamental_output,
        scenario_failed_subcall_still_insufficient_data,
        scenario_exhaustive_sweep,
        scenario_output_shape,
        scenario_all_outputs_forwarded_by_identity,
        scenario_combination_logic,
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
    print(f"PHASE 10 SPRINT 112 TEXT-ANALYSIS-FUNDAMENTAL-INTEGRATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())