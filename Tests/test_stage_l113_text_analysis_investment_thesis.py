"""Phase 10 Sprint 113 proof suite -- Investment Thesis.

``TextAnalysisSkill.execute(context)`` still calls the same three
Tools (``"market_price"``, ``"market_news"``, ``"market_fundamental"``)
through the same, already-frozen ``BaseSkill.execute_tool_result()``
API Sprint 106/108/112 already used, and still combines/derives the
Sprint 112 recommendation table unchanged. Sprint 113 adds exactly
two new keys inside the existing ``"analysis"`` dict --
``"strengths"`` and ``"risks"`` -- each a plain ``list`` of fixed
strings built from eight independent ``if`` statements (four for
strengths, four for risks) directly inside ``execute()``. No new
class (``InvestmentThesis``, ``Analyzer``, ``DecisionEngine``,
``Strategy``, ``RuleEngine``, ``Manager``, ``Pipeline``, ``Factory``,
``Registry``, ``Helper``, or utility module) was introduced anywhere
in this project to add it.

Scope: dedicated proof suite for the Sprint 113 change to
``Orchestration.text_analysis_skill.TextAnalysisSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-main()
style already used by
``Tests/test_stage_l112_text_analysis_fundamental_integration.py``.

Three layers of coverage:

  1. Seam-level scenarios that inject ``_resolve_tool`` directly on a
     ``TextAnalysisSkill`` instance -- exactly the same seam
     ``Executor.invoke_current_skill()`` uses in production -- using
     local, duck-typed Tool stand-ins that return fixed
     ``ToolResult`` outputs, to drive every strength/risk condition
     independently, in combination, and the "no major .../detected"
     fallbacks.
  2. AST/namespace verification proving the thesis logic lives
     entirely inline inside ``execute()`` and that no forbidden
     abstraction was introduced.
  3. A real, fully-wired integration scenario -- genuine ``Executor``,
     ``ToolRegistry``, ``ToolResolver``, real ``TextAnalysisSkill``,
     real ``MarketPriceTool``, real ``MarketNewsTool``, and real
     ``MarketFundamentalTool`` -- proving that, with today's real
     Tools, ``"strengths"``/``"risks"`` are present and deterministic.

Invariant coverage:
    T1  -- price.trend == "bullish" -> "bullish price trend" in
           strengths.
    T2  -- news.overall_sentiment == "positive" -> "positive market
           sentiment" in strengths.
    T3  -- fundamental.valuation == "undervalued" -> "undervalued
           fundamentals" in strengths.
    T4  -- fundamental.quality == "strong" -> "strong company
           quality" in strengths.
    T5  -- no strength condition matches -> strengths ==
           ["No major strength detected"].
    K1  -- price.trend == "bearish" -> "bearish price trend" in
           risks.
    K2  -- news.overall_sentiment == "negative" -> "negative market
           sentiment" in risks.
    K3  -- fundamental.valuation == "overvalued" -> "overvalued
           valuation" in risks.
    K4  -- fundamental.quality == "weak" -> "weak company quality"
           in risks.
    K5  -- no risk condition matches -> risks == ["No major risk
           detected"].
    M1  -- all four strength conditions true simultaneously ->
           strengths has exactly all four strings, in fixed order.
    M2  -- all four risk conditions true simultaneously -> risks has
           exactly all four strings, in fixed order.
    M3  -- strengths and risks are independent of each other -- a
           bullish trend contributing a strength does not prevent a
           simultaneously negative sentiment from contributing a
           risk (mixed signals both recorded).
    U1  -- missing/non-dict Tool outputs -> no exception, and both
           lists fall back to their "No major .../detected" default.
    S1  -- "analysis" now has exactly five keys: recommendation,
           confidence, reason, strengths, risks.
    S2  -- recommendation/confidence/reason values themselves are
           byte-for-byte unchanged from the Sprint 112 rules.
    O1  -- order within strengths/risks is always exactly the fixed
           order (trend, sentiment, valuation, quality) regardless of
           which subset is present -- never reordered/sorted.
    A1  -- AST: no forbidden-name symbol (InvestmentThesis, Analyzer,
           DecisionEngine, Strategy, RuleEngine, Manager, Pipeline,
           Factory, Registry, Helper, Utility) anywhere in the module
           namespace.
    A2  -- AST: the module defines exactly one class,
           TextAnalysisSkill.
    A3  -- AST: execute() defines no nested function/lambda.
    A4  -- AST: execute_tool_result() is still called exactly three
           times, in the same order.
    A5  -- AST: exactly one SkillResult(...) construction.
    A6  -- class shape: still no __init__ of its own, no per-instance
           state; name/description unchanged.
    I1  -- real integration: Executor -> invoke_current_skill() ->
           TextAnalysisSkill -> {MarketPriceTool, MarketNewsTool,
           MarketFundamentalTool} -> SkillResult succeeds end-to-end,
           with "strengths"/"risks" present in "analysis".
    I2  -- real integration: repeated calls are field-equal
           (deterministic, no randomness, no timestamps).
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
# T1-T5 -- strengths, one condition at a time
# ---------------------------------------------------------------------------
def scenario_bullish_trend_strength() -> None:
    result = _run({"trend": "bullish"}, {}, {})
    strengths = result.output["analysis"]["strengths"]
    check("bullish price trend" in strengths, "T1: bullish trend -> 'bullish price trend' in strengths")


def scenario_positive_sentiment_strength() -> None:
    result = _run({}, {"overall_sentiment": "positive"}, {})
    strengths = result.output["analysis"]["strengths"]
    check("positive market sentiment" in strengths, "T2: positive sentiment -> 'positive market sentiment' in strengths")


def scenario_undervalued_strength() -> None:
    result = _run({}, {}, {"valuation": "undervalued"})
    strengths = result.output["analysis"]["strengths"]
    check("undervalued fundamentals" in strengths, "T3: undervalued valuation -> 'undervalued fundamentals' in strengths")


def scenario_strong_quality_strength() -> None:
    result = _run({}, {}, {"quality": "strong"})
    strengths = result.output["analysis"]["strengths"]
    check("strong company quality" in strengths, "T4: strong quality -> 'strong company quality' in strengths")


def scenario_no_strengths_fallback() -> None:
    result = _run({"trend": "neutral"}, {"overall_sentiment": "neutral"}, {"valuation": "fair", "quality": "unknown"})
    strengths = result.output["analysis"]["strengths"]
    check(strengths == ["No major strength detected"], f"T5: no strength condition matches -> exact fallback list; got {strengths!r}")


# ---------------------------------------------------------------------------
# K1-K5 -- risks, one condition at a time
# ---------------------------------------------------------------------------
def scenario_bearish_trend_risk() -> None:
    result = _run({"trend": "bearish"}, {}, {})
    risks = result.output["analysis"]["risks"]
    check("bearish price trend" in risks, "K1: bearish trend -> 'bearish price trend' in risks")


def scenario_negative_sentiment_risk() -> None:
    result = _run({}, {"overall_sentiment": "negative"}, {})
    risks = result.output["analysis"]["risks"]
    check("negative market sentiment" in risks, "K2: negative sentiment -> 'negative market sentiment' in risks")


def scenario_overvalued_risk() -> None:
    result = _run({}, {}, {"valuation": "overvalued"})
    risks = result.output["analysis"]["risks"]
    check("overvalued valuation" in risks, "K3: overvalued valuation -> 'overvalued valuation' in risks")


def scenario_weak_quality_risk() -> None:
    result = _run({}, {}, {"quality": "weak"})
    risks = result.output["analysis"]["risks"]
    check("weak company quality" in risks, "K4: weak quality -> 'weak company quality' in risks")


def scenario_no_risks_fallback() -> None:
    result = _run({"trend": "neutral"}, {"overall_sentiment": "neutral"}, {"valuation": "fair", "quality": "unknown"})
    risks = result.output["analysis"]["risks"]
    check(risks == ["No major risk detected"], f"K5: no risk condition matches -> exact fallback list; got {risks!r}")


# ---------------------------------------------------------------------------
# M1-M3 -- all-true combinations and independence
# ---------------------------------------------------------------------------
def scenario_all_strengths_present_fixed_order() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "positive"},
        {"valuation": "undervalued", "quality": "strong"},
    )
    strengths = result.output["analysis"]["strengths"]
    check(
        strengths == [
            "bullish price trend",
            "positive market sentiment",
            "undervalued fundamentals",
            "strong company quality",
        ],
        f"M1: all four strength conditions true -> exact four strings in fixed order; got {strengths!r}",
    )


def scenario_all_risks_present_fixed_order() -> None:
    result = _run(
        {"trend": "bearish"},
        {"overall_sentiment": "negative"},
        {"valuation": "overvalued", "quality": "weak"},
    )
    risks = result.output["analysis"]["risks"]
    check(
        risks == [
            "bearish price trend",
            "negative market sentiment",
            "overvalued valuation",
            "weak company quality",
        ],
        f"M2: all four risk conditions true -> exact four strings in fixed order; got {risks!r}",
    )


def scenario_mixed_signals_independent() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "negative"},
        {"valuation": "fair"},
    )
    analysis = result.output["analysis"]
    check("bullish price trend" in analysis["strengths"], "M3: bullish trend still contributes a strength despite negative sentiment")
    check("negative market sentiment" in analysis["risks"], "M3: negative sentiment still contributes a risk despite bullish trend")
    check("bearish price trend" not in analysis["risks"], "M3: bullish trend never appears as a risk")
    check("positive market sentiment" not in analysis["strengths"], "M3: negative sentiment never appears as a strength")


# ---------------------------------------------------------------------------
# U1 -- malformed / non-dict Tool outputs never raise
# ---------------------------------------------------------------------------
def scenario_non_dict_outputs_never_raise() -> None:
    exc = _catch(lambda: _run(None, "some string", 42))
    check(exc is None, f"U1: non-dict Tool outputs never raise; got {exc!r}")

    result = _run(None, "some string", 42)
    analysis = result.output["analysis"]
    check(analysis["strengths"] == ["No major strength detected"], f"U1: strengths falls back cleanly; got {analysis['strengths']!r}")
    check(analysis["risks"] == ["No major risk detected"], f"U1: risks falls back cleanly; got {analysis['risks']!r}")


# ---------------------------------------------------------------------------
# S1-S2 -- analysis shape and unchanged recommendation fields
# ---------------------------------------------------------------------------
def scenario_analysis_shape() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "positive"},
        {"valuation": "undervalued", "quality": "strong"},
    )
    analysis = result.output["analysis"]
    check(
        set(analysis.keys()) == {"recommendation", "confidence", "reason", "strengths", "risks"},
        f"S1: analysis has exactly five keys; got {set(analysis.keys())!r}",
    )


def scenario_recommendation_fields_unchanged() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "positive"},
        {"valuation": "undervalued", "quality": "strong"},
    )
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "BUY", "S2: recommendation unchanged (BUY)")
    check(analysis["confidence"] == "HIGH", "S2: confidence unchanged (HIGH)")
    check(analysis["reason"] == "bullish price, positive news, undervalued fundamental", "S2: reason unchanged")

    result2 = _run({"trend": "neutral"}, {"overall_sentiment": "neutral"}, {"valuation": "fair"})
    analysis2 = result2.output["analysis"]
    check(analysis2["recommendation"] == "UNKNOWN", "S2: recommendation unchanged (UNKNOWN fallback)")
    check(analysis2["confidence"] == "LOW", "S2: confidence unchanged (LOW fallback)")
    check(analysis2["reason"] == "insufficient data", "S2: reason unchanged (insufficient data fallback)")


# ---------------------------------------------------------------------------
# O1 -- fixed ordering regardless of subset present
# ---------------------------------------------------------------------------
def scenario_partial_subset_preserves_fixed_order() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "neutral"},
        {"valuation": "undervalued", "quality": "unknown"},
    )
    strengths = result.output["analysis"]["strengths"]
    check(strengths == ["bullish price trend", "undervalued fundamentals"], f"O1: partial strengths preserve fixed relative order; got {strengths!r}")

    result2 = _run(
        {"trend": "neutral"},
        {"overall_sentiment": "negative"},
        {"valuation": "unknown", "quality": "weak"},
    )
    risks = result2.output["analysis"]["risks"]
    check(risks == ["negative market sentiment", "weak company quality"], f"O1: partial risks preserve fixed relative order; got {risks!r}")


# ---------------------------------------------------------------------------
# A1-A6 -- AST / namespace verification: thesis logic stays inline, no new
# abstraction of any kind
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.text_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"TextAnalysisSkill"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "InvestmentThesis", "Analyzer", "DecisionEngine", "Strategy",
        "RuleEngine", "Manager", "Pipeline", "Factory", "Registry",
        "Helper", "Utility", "Engine", "Adapter", "Aggregator",
        "MultiToolExecutor",
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

    forbidden_call_names = {"ToolResult", "ToolResolver", "ToolRegistry", "ToolContext", "Ollama", "InvestmentThesis"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"A5: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")

    func_defs = [n for n in tree.body[0].body if isinstance(n, ast.FunctionDef)]
    check(len(func_defs) == 0, "A3b: no nested def statements directly in execute()'s body")


def scenario_class_shape_unchanged() -> None:
    check("__init__" not in TextAnalysisSkill.__dict__, "A6a: TextAnalysisSkill still defines no __init__ of its own")
    skill = TextAnalysisSkill()
    check(skill.__dict__ == {}, "A6b: a freshly constructed instance still has no instance __dict__ entries")
    check(skill.name == "text_analysis", "A6c: name is unchanged ('text_analysis')")
    check(skill.description == "Analyze textual information.", "A6d: description is unchanged")


# ---------------------------------------------------------------------------
# I1-I2 -- real, fully-wired integration (no test doubles)
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

    analysis = result.output["analysis"]
    check("strengths" in analysis and "risks" in analysis, "I1: 'strengths'/'risks' present in analysis with real Tools")
    check(isinstance(analysis["strengths"], list) and len(analysis["strengths"]) >= 1, "I1: strengths is a non-empty list")
    check(isinstance(analysis["risks"], list) and len(analysis["risks"]) >= 1, "I1: risks is a non-empty list")


def scenario_real_integration_repeat_call_deterministic() -> None:
    executor = _real_running_executor()
    result1 = executor.invoke_current_skill()
    result2 = executor.invoke_current_skill()

    check(result1 is not result2, "I2a: two separate invoke_current_skill() calls produce two distinct SkillResult objects")
    check(result1 == result2, "I2b: the two SkillResults are field-equal (fully deterministic, no randomness/timestamps)")


def main() -> int:
    scenarios = [
        scenario_bullish_trend_strength,
        scenario_positive_sentiment_strength,
        scenario_undervalued_strength,
        scenario_strong_quality_strength,
        scenario_no_strengths_fallback,
        scenario_bearish_trend_risk,
        scenario_negative_sentiment_risk,
        scenario_overvalued_risk,
        scenario_weak_quality_risk,
        scenario_no_risks_fallback,
        scenario_all_strengths_present_fixed_order,
        scenario_all_risks_present_fixed_order,
        scenario_mixed_signals_independent,
        scenario_non_dict_outputs_never_raise,
        scenario_analysis_shape,
        scenario_recommendation_fields_unchanged,
        scenario_partial_subset_preserves_fixed_order,
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
    print(f"PHASE 10 SPRINT 113 TEXT-ANALYSIS-INVESTMENT-THESIS RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())