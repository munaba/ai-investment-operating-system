"""Phase 10 Sprint 114 proof suite -- Executive Summary.

``TextAnalysisSkill.execute(context)`` still calls the same three
Tools (``"market_price"``, ``"market_news"``, ``"market_fundamental"``)
through the same, already-frozen ``BaseSkill.execute_tool_result()``
API Sprint 106/108/112 already used, and still combines/derives the
Sprint 112 recommendation table and the Sprint 113 investment thesis
unchanged. Sprint 114 adds exactly one new key inside the existing
``"analysis"`` dict -- ``"summary"`` -- a single deterministic
``str`` built with plain f-strings and ``"\\n".join(...)`` over a
fixed line list, directly inline inside ``execute()``. No new class
(``SummaryGenerator``, ``Formatter``, ``Builder``, ``TemplateEngine``,
``Renderer``, ``Manager``, ``Pipeline``, ``Strategy``, ``Helper``, or
utility module) was introduced anywhere in this project to add it.

Scope: dedicated proof suite for the Sprint 114 change to
``Orchestration.text_analysis_skill.TextAnalysisSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-main()
style already used by
``Tests/test_stage_l113_text_analysis_investment_thesis.py``.

Three layers of coverage:

  1. Seam-level scenarios that inject ``_resolve_tool`` directly on a
     ``TextAnalysisSkill`` instance -- exactly the same seam
     ``Executor.invoke_current_skill()`` uses in production -- using
     local, duck-typed Tool stand-ins that return fixed
     ``ToolResult`` outputs, to prove the summary's exact locked
     layout across the BUY/HIGH example, a fallback/UNKNOWN case, a
     multi-strength/multi-risk case, and malformed Tool outputs.
  2. AST/namespace verification proving the summary logic lives
     entirely inline inside ``execute()`` and that no forbidden
     abstraction was introduced.
  3. A real, fully-wired integration scenario -- genuine ``Executor``,
     ``ToolRegistry``, ``ToolResolver``, real ``TextAnalysisSkill``,
     real ``MarketPriceTool``, real ``MarketNewsTool``, and real
     ``MarketFundamentalTool`` -- proving that, with today's real
     Tools, ``"summary"`` is present, a ``str``, and deterministic.

Invariant coverage:
    E1  -- the canonical BUY/HIGH example from the sprint brief
           reproduces the LOCKED template byte-for-byte.
    E2  -- Line 1 is always exactly ``"Recommendation: <recommendation>"``.
    E3  -- Line 2 is always exactly ``"Confidence: <confidence>"``.
    E4  -- a blank line separates the confidence line from
           ``"Strengths:"``.
    E5  -- every entry of ``strengths`` appears on its own
           ``"- <entry>"`` line, in the same order as the list.
    E6  -- a blank line separates the strengths block from
           ``"Risks:"``.
    E7  -- every entry of ``risks`` appears on its own ``"- <entry>"``
           line, in the same order as the list.
    E8  -- a blank line separates the risks block from the final
           ``"Reason: <reason>"`` line, which is always the last
           line.
    E9  -- the fallback single-item lists (``["No major strength
           detected"]`` / ``["No major risk detected"]``) render as
           a single ``"- No major .../detected"`` bullet, same as any
           other entry -- no special-casing.
    E10 -- multiple strengths/risks each render as their own bullet
           line, in fixed order, none dropped or merged.
    U1  -- malformed/non-dict Tool outputs never raise, and
           ``"summary"`` still renders the UNKNOWN/LOW/insufficient
           data + both fallback bullet lists cleanly.
    S1  -- ``"analysis"`` now has exactly six keys: recommendation,
           confidence, reason, strengths, risks, summary.
    S2  -- recommendation/confidence/reason/strengths/risks values
           themselves are byte-for-byte unchanged from Sprint 112/113.
    T1  -- ``"summary"`` is always a plain ``str``.
    A1  -- AST: no forbidden-name symbol (SummaryGenerator, Formatter,
           Builder, TemplateEngine, Renderer, Manager, Pipeline,
           Strategy, Helper, Utility, Engine, Adapter) anywhere in the
           module namespace.
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
           with "summary" present in "analysis" as a non-empty str
           that starts with "Recommendation: " and ends with the
           literal "Reason: " + reason.
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
# E1 -- the canonical example from the sprint brief, byte-for-byte
# ---------------------------------------------------------------------------
def scenario_canonical_buy_example() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "positive"},
        {"valuation": "undervalued", "quality": "strong"},
    )
    analysis = result.output["analysis"]
    expected = (
        "Recommendation: BUY\n"
        "Confidence: HIGH\n"
        "\n"
        "Strengths:\n"
        "- bullish price trend\n"
        "- positive market sentiment\n"
        "- undervalued fundamentals\n"
        "- strong company quality\n"
        "\n"
        "Risks:\n"
        "- No major risk detected\n"
        "\n"
        "Reason: bullish price, positive news, undervalued fundamental"
    )
    check(analysis["summary"] == expected, f"E1: canonical BUY/HIGH example matches LOCKED template byte-for-byte; got {analysis['summary']!r}")


# ---------------------------------------------------------------------------
# E2-E8 -- line-by-line structure checks
# ---------------------------------------------------------------------------
def scenario_line_structure() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "positive"},
        {"valuation": "undervalued", "quality": "strong"},
    )
    analysis = result.output["analysis"]
    lines = analysis["summary"].split("\n")

    check(lines[0] == f"Recommendation: {analysis['recommendation']}", f"E2: line 1 is 'Recommendation: <recommendation>'; got {lines[0]!r}")
    check(lines[1] == f"Confidence: {analysis['confidence']}", f"E3: line 2 is 'Confidence: <confidence>'; got {lines[1]!r}")
    check(lines[2] == "", "E4: blank line separates confidence from Strengths:")
    check(lines[3] == "Strengths:", f"E4: line 4 is 'Strengths:'; got {lines[3]!r}")

    strengths = analysis["strengths"]
    strength_lines = lines[4:4 + len(strengths)]
    check(strength_lines == [f"- {s}" for s in strengths], f"E5: each strength on its own '- <entry>' line, in order; got {strength_lines!r}")

    idx = 4 + len(strengths)
    check(lines[idx] == "", "E6: blank line separates strengths from Risks:")
    check(lines[idx + 1] == "Risks:", f"E6: 'Risks:' line present; got {lines[idx + 1]!r}")

    risks = analysis["risks"]
    risk_lines = lines[idx + 2: idx + 2 + len(risks)]
    check(risk_lines == [f"- {r}" for r in risks], f"E7: each risk on its own '- <entry>' line, in order; got {risk_lines!r}")

    idx2 = idx + 2 + len(risks)
    check(lines[idx2] == "", "E8: blank line separates risks from Reason:")
    check(lines[idx2 + 1] == f"Reason: {analysis['reason']}", f"E8: final line is 'Reason: <reason>'; got {lines[idx2 + 1]!r}")
    check(idx2 + 1 == len(lines) - 1, "E8: 'Reason: ...' is the very last line")


# ---------------------------------------------------------------------------
# E9 -- fallback single-item lists render as a plain bullet, no special-casing
# ---------------------------------------------------------------------------
def scenario_fallback_lists_render_as_bullets() -> None:
    result = _run(
        {"trend": "neutral"},
        {"overall_sentiment": "neutral"},
        {"valuation": "fair", "quality": "unknown"},
    )
    analysis = result.output["analysis"]
    check(analysis["strengths"] == ["No major strength detected"], "E9 precondition: strengths is the fallback list")
    check(analysis["risks"] == ["No major risk detected"], "E9 precondition: risks is the fallback list")
    check("- No major strength detected" in analysis["summary"], "E9: fallback strength renders as its own bullet line")
    check("- No major risk detected" in analysis["summary"], "E9: fallback risk renders as its own bullet line")
    check(analysis["summary"].count("- No major strength detected") == 1, "E9: fallback strength bullet appears exactly once")
    check(analysis["summary"].count("- No major risk detected") == 1, "E9: fallback risk bullet appears exactly once")


# ---------------------------------------------------------------------------
# E10 -- multiple strengths/risks each render, fixed order, none dropped
# ---------------------------------------------------------------------------
def scenario_multiple_strengths_and_risks_all_render() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "negative"},
        {"valuation": "undervalued", "quality": "weak"},
    )
    analysis = result.output["analysis"]
    check(
        analysis["strengths"] == ["bullish price trend", "undervalued fundamentals"],
        f"E10 precondition: two strengths present in fixed order; got {analysis['strengths']!r}",
    )
    check(
        analysis["risks"] == ["negative market sentiment", "weak company quality"],
        f"E10 precondition: two risks present in fixed order; got {analysis['risks']!r}",
    )
    summary = analysis["summary"]
    strengths_block = summary.split("Strengths:\n", 1)[1].split("\n\nRisks:")[0]
    check(
        strengths_block == "- bullish price trend\n- undervalued fundamentals",
        f"E10: both strengths render, in fixed order, none dropped/merged; got {strengths_block!r}",
    )
    risks_block = summary.split("Risks:\n", 1)[1].split("\n\nReason:")[0]
    check(
        risks_block == "- negative market sentiment\n- weak company quality",
        f"E10: both risks render, in fixed order, none dropped/merged; got {risks_block!r}",
    )


# ---------------------------------------------------------------------------
# U1 -- malformed / non-dict Tool outputs never raise; summary still renders
# ---------------------------------------------------------------------------
def scenario_non_dict_outputs_never_raise() -> None:
    exc = _catch(lambda: _run(None, "some string", 42))
    check(exc is None, f"U1: non-dict Tool outputs never raise while building summary; got {exc!r}")

    result = _run(None, "some string", 42)
    analysis = result.output["analysis"]
    expected = (
        "Recommendation: UNKNOWN\n"
        "Confidence: LOW\n"
        "\n"
        "Strengths:\n"
        "- No major strength detected\n"
        "\n"
        "Risks:\n"
        "- No major risk detected\n"
        "\n"
        "Reason: insufficient data"
    )
    check(analysis["summary"] == expected, f"U1: fallback UNKNOWN/LOW summary renders cleanly; got {analysis['summary']!r}")


# ---------------------------------------------------------------------------
# S1-S2, T1 -- analysis shape, unchanged prior fields, summary type
# ---------------------------------------------------------------------------
def scenario_analysis_shape() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "positive"},
        {"valuation": "undervalued", "quality": "strong"},
    )
    analysis = result.output["analysis"]
    check(
        set(analysis.keys()) == {"recommendation", "confidence", "reason", "strengths", "risks", "summary"},
        f"S1: analysis has exactly six keys; got {set(analysis.keys())!r}",
    )


def scenario_prior_fields_unchanged() -> None:
    result = _run(
        {"trend": "bullish"},
        {"overall_sentiment": "positive"},
        {"valuation": "undervalued", "quality": "strong"},
    )
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "BUY", "S2: recommendation unchanged (BUY)")
    check(analysis["confidence"] == "HIGH", "S2: confidence unchanged (HIGH)")
    check(analysis["reason"] == "bullish price, positive news, undervalued fundamental", "S2: reason unchanged")
    check(
        analysis["strengths"] == [
            "bullish price trend",
            "positive market sentiment",
            "undervalued fundamentals",
            "strong company quality",
        ],
        "S2: strengths unchanged from Sprint 113",
    )
    check(analysis["risks"] == ["No major risk detected"], "S2: risks unchanged from Sprint 113")


def scenario_summary_is_plain_str() -> None:
    result = _run({"trend": "bullish"}, {}, {})
    check(isinstance(result.output["analysis"]["summary"], str), "T1: 'summary' is always a plain str")


# ---------------------------------------------------------------------------
# A1-A6 -- AST / namespace verification: summary logic stays inline, no new
# abstraction of any kind
# ---------------------------------------------------------------------------
def scenario_no_forbidden_abstractions() -> None:
    import Orchestration.text_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"TextAnalysisSkill"}, f"A2: module defines exactly one class; got {class_names!r}")

    forbidden_fragments = (
        "SummaryGenerator", "Formatter", "Builder", "TemplateEngine",
        "Renderer", "Manager", "Pipeline", "Strategy", "Helper",
        "Utility", "Engine", "Adapter", "Aggregator", "InvestmentThesis",
        "Analyzer", "DecisionEngine", "RuleEngine", "Factory", "Registry",
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

    forbidden_call_names = {"ToolResult", "ToolResolver", "ToolRegistry", "ToolContext", "Ollama", "SummaryGenerator", "TemplateEngine"}
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
    check("summary" in analysis, "I1: 'summary' present in analysis with real Tools")
    summary = analysis["summary"]
    check(isinstance(summary, str) and len(summary) > 0, "I1: summary is a non-empty str")
    check(summary.startswith("Recommendation: "), "I1: summary starts with 'Recommendation: '")
    check(summary.endswith(f"Reason: {analysis['reason']}"), "I1: summary ends with 'Reason: <reason>'")


def scenario_real_integration_repeat_call_deterministic() -> None:
    executor = _real_running_executor()
    result1 = executor.invoke_current_skill()
    result2 = executor.invoke_current_skill()

    check(result1 is not result2, "I2a: two separate invoke_current_skill() calls produce two distinct SkillResult objects")
    check(result1 == result2, "I2b: the two SkillResults are field-equal (fully deterministic, no randomness/timestamps)")
    check(
        result1.output["analysis"]["summary"] == result2.output["analysis"]["summary"],
        "I2c: repeated calls produce byte-identical summaries",
    )


def main() -> int:
    scenarios = [
        scenario_canonical_buy_example,
        scenario_line_structure,
        scenario_fallback_lists_render_as_bullets,
        scenario_multiple_strengths_and_risks_all_render,
        scenario_non_dict_outputs_never_raise,
        scenario_analysis_shape,
        scenario_prior_fields_unchanged,
        scenario_summary_is_plain_str,
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
    print(f"PHASE 10 SPRINT 114 TEXT-ANALYSIS-SUMMARY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())