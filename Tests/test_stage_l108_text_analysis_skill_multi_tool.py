"""Phase 10 Sprint 108 proof suite -- Multi-Tool Skill Orchestration.

``TextAnalysisSkill.execute(context)`` now calls TWO Tools --
``"market_price"`` and ``"market_news"`` -- through the same,
already-frozen ``BaseSkill.execute_tool_result()`` API Sprint 106
already used for a single Tool, and combines the two resulting
``SkillResult`` values into exactly one ``SkillResult``. No new
abstraction is introduced anywhere in this sprint -- ``Executor``,
``BaseSkill``, ``SkillContext``, ``ToolContext``, ``ToolResolver``,
``ToolRegistry``, ``ToolResult``, ``SkillResult``, ``MarketPriceTool``,
and ``MarketNewsTool`` are all completely unchanged and untouched.

Scope: dedicated regression suite for the Sprint 108 change to
``Orchestration.text_analysis_skill.TextAnalysisSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-main()
style already used by ``Tests/test_stage_l106_text_analysis_skill_pipeline.py``.

Three layers of coverage:

  1. Seam-level scenarios that inject ``_resolve_tool`` directly on a
     ``TextAnalysisSkill`` instance -- exactly the same seam
     ``Executor.invoke_current_skill()`` uses in production -- using
     local, duck-typed Tool stand-ins to observe precisely what
     ``execute()`` does (call order, arguments, combination logic),
     without touching ``Executor`` itself.
  2. AST/namespace/import verification of the module's static shape,
     including proof that no forbidden abstraction (Manager,
     Registry, Adapter, Factory, Context, Pipeline, MultiToolExecutor,
     Aggregator) was introduced.
  3. A real, fully-wired integration scenario -- genuine ``Executor``,
     ``ToolRegistry``, ``ToolResolver``, real ``TextAnalysisSkill``,
     real ``MarketPriceTool`` AND real ``MarketNewsTool`` -- with
     **no monkeypatch, no stub, no test double anywhere in the
     chain**, proving the Sprint 108 pipeline (``Executor ->
     invoke_current_skill() -> TextAnalysisSkill -> {MarketPriceTool,
     MarketNewsTool} -> ToolResult -> SkillResult``) is a real,
     working, multi-Tool production path.

Invariant coverage:
    T1  -- execute() calls execute_tool_result() with
           tool_name="market_price" AND tool_name="market_news", in
           that order.
    T2  -- both Tool calls receive the exact same context object
           (identity-preserving), never a copy or a reshaped context.
    T3  -- the combined output is exactly
           {"price": <market_price output>, "news": <market_news
           output>}, each value forwarded by identity.
    T4  -- combined success is True only when both sub-results
           succeeded (logical AND).
    T5  -- combined success is False when either sub-result failed,
           and combined error is a non-empty str (never a dict, never
           None) that mentions the failing tool(s).
    T6  -- combined error is exactly None when both sub-results
           succeeded.
    T7  -- combined metadata is always {}.
    T8  -- the returned object's exact type is SkillResult, never a
           subclass, container, or plain dict.
    T9  -- exception propagation: if the market_price call raises,
           the market_news call is never made, and the exact
           exception instance propagates unchanged.
    T10 -- exception propagation: if no ToolResolver/_resolve_tool was
           ever injected, execute() raises BaseSkill's own SkillError.
    T11 -- AST: execute()'s body calls self.execute_tool_result(...)
           exactly twice, with tool_name literals "market_price" and
           "market_news" (in that order) and "context" as the second
           positional argument each time.
    T12 -- AST: execute()'s body constructs exactly one SkillResult.
    T13 -- AST: no other Tool/Resolver/Registry/Context construction
           call appears anywhere in execute()'s body (no
           ToolResult(...), no ToolResolver(...), no ToolRegistry(...),
           no ToolContext(...), no Ollama/AI call).
    T14 -- AST: the module defines exactly one class,
           TextAnalysisSkill -- no Manager/Registry/Adapter/Factory/
           Aggregator/Pipeline/MultiToolExecutor class anywhere.
    T15 -- namespace: module source contains no reference to
           Runtime/Workflow/Planner/EventBus/ToolManager/
           AutonomousHost/TaskManager/SkillResolver/Provider/Service/
           Repository/Database/Ollama by name (as real code, not
           docstring prose).
    T16 -- class shape: TextAnalysisSkill still defines no __init__
           of its own and carries no per-instance state beyond
           whatever an Executor injects; name/description unchanged.
    T17 -- real integration: Executor -> invoke_current_skill() ->
           TextAnalysisSkill -> {MarketPriceTool, MarketNewsTool} ->
           ToolResult -> SkillResult succeeds end-to-end with zero
           test doubles.
    T18 -- real integration: the returned SkillResult has
           success=True, output == {"price": {"symbol": "UNKNOWN",
           "price": None}, "news": {<MarketNewsTool's real empty-
           headlines output>}}, error=None, metadata={}.
    T19 -- real integration: calling invoke_current_skill() twice in
           a row against the same running session produces two
           distinct, field-equal SkillResult objects (both Tools are
           deterministic, Skill carries no state).
    T20 -- real integration: Executor's own session/cursor state is
           unaffected by invoke_current_skill() succeeding.
    T21 -- real integration with real, non-trivial parameters:
           a ToolContext-shaped context carrying a symbol and real
           headlines flows through to both Tools and the combined
           output reflects both Tools' real processing of that input.
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
# Fixtures (seam-level test doubles -- duck-typed Tools, not framework mocks)
# ---------------------------------------------------------------------------
class _RecordingTool:
    """A duck-typed Tool stand-in (not a BaseTool subclass -- the
    ``_resolve_tool`` seam never requires one) that records every
    ``execute()`` call's argument and returns a fixed ``ToolResult``
    (or raises a fixed exception)."""

    def __init__(self, result: Any = None, exc: Exception = None):
        self.calls: List[Any] = []
        self.result = result
        self.exc = exc

    def execute(self, context):
        self.calls.append(context)
        if self.exc is not None:
            raise self.exc
        return self.result


class _RecordingResolver:
    """Records every name it was asked to resolve, in order, and
    dispatches to whichever fixed Tool stand-in was registered under
    that name -- exactly the shape ``Executor.invoke_current_skill()``
    injects as ``skill._resolve_tool``."""

    def __init__(self, tools: dict):
        self.tools = tools
        self.requested_names: List[Any] = []

    def __call__(self, name):
        self.requested_names.append(name)
        return self.tools[name]


def _two_tool_skill(price_result=None, news_result=None, price_exc=None, news_exc=None):
    price_tool = _RecordingTool(result=price_result, exc=price_exc)
    news_tool = _RecordingTool(result=news_result, exc=news_exc)
    resolver = _RecordingResolver({"market_price": price_tool, "market_news": news_tool})

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver
    return skill, resolver, price_tool, news_tool


# ---------------------------------------------------------------------------
# T1-T2 -- call order, names, and context identity
# ---------------------------------------------------------------------------
def scenario_call_order_and_names() -> None:
    price_result = ToolResult(success=True, output={"symbol": "UNKNOWN", "price": None}, error=None, metadata={})
    news_result = ToolResult(success=True, output={"symbol": "UNKNOWN", "headline_count": 0}, error=None, metadata={})
    skill, resolver, price_tool, news_tool = _two_tool_skill(price_result, news_result)

    sentinel_context = object()
    exc = _catch(lambda: skill.execute(sentinel_context))
    check(exc is None, f"T1: execute() runs without raising; got {exc!r}")

    check(resolver.requested_names == ["market_price", "market_news"], "T1: both tools resolved in order market_price then market_news")
    check(len(price_tool.calls) == 1 and len(news_tool.calls) == 1, "T1: each Tool's execute() called exactly once")

    check(price_tool.calls[0] is sentinel_context, "T2: market_price Tool received the exact same context object by identity")
    check(news_tool.calls[0] is sentinel_context, "T2: market_news Tool received the exact same context object by identity")


# ---------------------------------------------------------------------------
# T3 -- combined output shape
# ---------------------------------------------------------------------------
def scenario_combined_output_shape() -> None:
    price_result = ToolResult(success=True, output={"symbol": "AAPL", "price": 123.45}, error=None, metadata={})
    news_result = ToolResult(success=True, output={"symbol": "AAPL", "overall_sentiment": "positive"}, error=None, metadata={})
    skill, *_ = _two_tool_skill(price_result, news_result)

    result = skill.execute(object())
    check(
        result.output == {"price": {"symbol": "AAPL", "price": 123.45}, "news": {"symbol": "AAPL", "overall_sentiment": "positive"}},
        f"T3: combined output is exactly {{'price': ..., 'news': ...}}; got {result.output!r}",
    )
    check(result.output["price"] is price_result.output, "T3: 'price' value forwarded by identity from market_price's ToolResult.output")
    check(result.output["news"] is news_result.output, "T3: 'news' value forwarded by identity from market_news's ToolResult.output")


# ---------------------------------------------------------------------------
# T4-T6 -- success/error combination logic
# ---------------------------------------------------------------------------
def scenario_both_succeed() -> None:
    price_result = ToolResult(success=True, output="p", error=None, metadata={})
    news_result = ToolResult(success=True, output="n", error=None, metadata={})
    skill, *_ = _two_tool_skill(price_result, news_result)

    result = skill.execute(object())
    check(result.success is True, "T4: combined success is True when both sub-results succeed")
    check(result.error is None, "T6: combined error is exactly None when both succeeded")


def scenario_price_fails() -> None:
    price_result = ToolResult(success=False, output=None, error="price failure", metadata={})
    news_result = ToolResult(success=True, output="n", error=None, metadata={})
    skill, *_ = _two_tool_skill(price_result, news_result)

    result = skill.execute(object())
    check(result.success is False, "T5: combined success is False when market_price fails")
    check(isinstance(result.error, str) and result.error != "", "T5: combined error is a non-empty str")
    check("market_price" in result.error, "T5: combined error mentions the failing tool ('market_price')")
    check("market_news" not in result.error, "T5: combined error does not mention the tool that succeeded")


def scenario_news_fails() -> None:
    price_result = ToolResult(success=True, output="p", error=None, metadata={})
    news_result = ToolResult(success=False, output=None, error="news failure", metadata={})
    skill, *_ = _two_tool_skill(price_result, news_result)

    result = skill.execute(object())
    check(result.success is False, "T5: combined success is False when market_news fails")
    check("market_news" in result.error, "T5: combined error mentions the failing tool ('market_news')")


def scenario_both_fail() -> None:
    price_result = ToolResult(success=False, output=None, error="p-fail", metadata={})
    news_result = ToolResult(success=False, output=None, error="n-fail", metadata={})
    skill, *_ = _two_tool_skill(price_result, news_result)

    result = skill.execute(object())
    check(result.success is False, "T5: combined success is False when both fail")
    check("market_price" in result.error and "market_news" in result.error, "T5: combined error mentions both failing tools")


# ---------------------------------------------------------------------------
# T7-T8 -- metadata and exact type
# ---------------------------------------------------------------------------
def scenario_metadata_and_type() -> None:
    price_result = ToolResult(success=True, output="p", error=None, metadata={"ignored": 1})
    news_result = ToolResult(success=True, output="n", error=None, metadata={"ignored": 2})
    skill, *_ = _two_tool_skill(price_result, news_result)

    result = skill.execute(object())
    check(dict(result.metadata) == {}, "T7: combined metadata is always {}")
    check(type(result) is SkillResult, "T8: returned object's exact type is SkillResult")


# ---------------------------------------------------------------------------
# T9 -- short-circuit exception propagation
# ---------------------------------------------------------------------------
def scenario_price_raises_short_circuits() -> None:
    boom = RuntimeError("market_price exploded")
    skill, resolver, price_tool, news_tool = _two_tool_skill(price_exc=boom)

    caught = _catch(lambda: skill.execute(object()))
    check(caught is boom, "T9: the exact exception instance from market_price propagates unchanged")
    check(resolver.requested_names == ["market_price"], "T9: market_news is never resolved once market_price raises")
    check(len(news_tool.calls) == 0, "T9: market_news Tool's execute() is never called once market_price raises")


def scenario_news_raises_propagates() -> None:
    boom = ValueError("market_news exploded")
    price_result = ToolResult(success=True, output="p", error=None, metadata={})
    skill, resolver, price_tool, news_tool = _two_tool_skill(price_result=price_result, news_exc=boom)

    caught = _catch(lambda: skill.execute(object()))
    check(caught is boom, "T9: the exact exception instance from market_news propagates unchanged")
    check(len(price_tool.calls) == 1, "T9: market_price still ran once before market_news raised")


# ---------------------------------------------------------------------------
# T10 -- no resolver injected raises SkillError
# ---------------------------------------------------------------------------
def scenario_no_resolver_injected() -> None:
    skill = TextAnalysisSkill()  # no _resolve_tool ever injected
    caught = _catch(lambda: skill.execute(object()))
    check(caught is not None, "T10: execute() raises when no ToolResolver/_resolve_tool was ever injected")
    check(type(caught).__name__ == "SkillError", f"T10: the raised exception is BaseSkill's own SkillError; got {type(caught).__name__!r}")


# ---------------------------------------------------------------------------
# T11-T13 -- AST verification of execute()'s body
# ---------------------------------------------------------------------------
def scenario_ast_execute_body() -> None:
    source = inspect.getsource(TextAnalysisSkill.execute)
    tree = ast.parse(_dedent(source))

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    execute_tool_result_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "execute_tool_result"
    ]
    check(len(execute_tool_result_calls) == 2, f"T11: execute_tool_result() is called exactly twice; got {len(execute_tool_result_calls)}")

    tool_names_in_order = []
    for c in execute_tool_result_calls:
        check(len(c.args) == 2 and not c.keywords, "T11: each execute_tool_result() call has exactly two positional args, no keywords")
        first_arg = c.args[0]
        check(isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str), "T11: first argument is a string literal")
        tool_names_in_order.append(first_arg.value)
        second_arg = c.args[1]
        check(isinstance(second_arg, ast.Name) and second_arg.id == "context", "T11: second argument is the bare name 'context'")

    check(tool_names_in_order == ["market_price", "market_news"], f"T11: tool names requested in order ['market_price', 'market_news']; got {tool_names_in_order!r}")

    skill_result_calls = [
        c for c in calls
        if (isinstance(c.func, ast.Name) and c.func.id == "SkillResult")
    ]
    check(len(skill_result_calls) == 1, f"T12: exactly one SkillResult(...) construction; got {len(skill_result_calls)}")

    forbidden_call_names = {"ToolResult", "ToolResolver", "ToolRegistry", "ToolContext", "Ollama"}
    called_names = {
        (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
        for c in calls
        if isinstance(c.func, (ast.Name, ast.Attribute))
    }
    check(forbidden_call_names.isdisjoint(called_names), f"T13: no forbidden construction call present; got overlap {forbidden_call_names & called_names}")


def _dedent(source: str) -> str:
    import textwrap
    return textwrap.dedent(source)


# ---------------------------------------------------------------------------
# T14 -- exactly one class in the module; no forbidden abstraction classes
# ---------------------------------------------------------------------------
def scenario_no_new_abstraction_classes() -> None:
    import Orchestration.text_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    check(class_names == {"TextAnalysisSkill"}, f"T14: module defines exactly one class; got {class_names!r}")

    forbidden_name_fragments = ("Manager", "Registry", "Adapter", "Factory", "Aggregator", "Pipeline", "MultiToolExecutor")
    module_public_names = {n for n in dir(module) if not n.startswith("_")}
    for fragment in forbidden_name_fragments:
        check(
            not any(fragment in name for name in module_public_names),
            f"T14: no module-level symbol containing {fragment!r} (forbidden abstraction)",
        )


# ---------------------------------------------------------------------------
# T15 -- namespace/reference verification (real code, not docstring prose)
# ---------------------------------------------------------------------------
def scenario_no_forbidden_references() -> None:
    import Orchestration.text_analysis_skill as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names_referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs_referenced = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_words = (
        "Runtime", "Workflow", "Planner", "EventBus", "ToolManager",
        "AutonomousHost", "TaskManager", "SkillResolver", "Provider",
        "Service", "Repository", "Database", "Ollama",
    )
    all_referenced = names_referenced | attrs_referenced | imported
    for word in forbidden_words:
        check(word not in all_referenced, f"T15: '{word}' is not referenced as real code (import/Name/Attribute)")


# ---------------------------------------------------------------------------
# T16 -- class shape unchanged
# ---------------------------------------------------------------------------
def scenario_class_shape_unchanged() -> None:
    check("__init__" not in TextAnalysisSkill.__dict__, "T16a: TextAnalysisSkill defines no __init__ of its own")
    skill = TextAnalysisSkill()
    check(skill.__dict__ == {}, "T16b: a freshly constructed instance has no instance __dict__ entries")
    check(skill.name == "text_analysis", "T16c: name is unchanged ('text_analysis')")
    check(skill.description == "Analyze textual information.", "T16d: description is unchanged")


# ---------------------------------------------------------------------------
# T17-T20 -- real, fully-wired multi-Tool integration (no test doubles)
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

    check(error is None, f"T17: the real Executor -> Skill -> {{MarketPriceTool, MarketNewsTool}} pipeline runs end-to-end without raising; got {error!r}")
    check(isinstance(result, SkillResult), "T17: invoke_current_skill() returns a real SkillResult")

    check(result.success is True, "T18a: SkillResult.success is True")
    expected_output = {
        "price": {"symbol": "UNKNOWN", "price": None},
        "news": {
            "symbol": "UNKNOWN",
            "headline_count": 0,
            "headlines": (),
            "overall_sentiment": "neutral",
            "sentiment_score": 0,
        },
    }
    check(result.output == expected_output, f"T18b: SkillResult.output matches both Tools' real deterministic output; got {result.output!r}")
    check(result.error is None, "T18c: SkillResult.error is None")
    check(dict(result.metadata) == {}, "T18d: SkillResult.metadata is empty")


def scenario_real_integration_repeat_call() -> None:
    executor = _real_running_executor()
    result1 = executor.invoke_current_skill()
    result2 = executor.invoke_current_skill()

    check(result1 is not result2, "T19a: two separate invoke_current_skill() calls produce two distinct SkillResult objects")
    check(result1 == result2, "T19b: the two SkillResults are field-equal (both Tools are deterministic, Skill carries no state)")


def scenario_real_integration_session_state_unaffected() -> None:
    executor = _real_running_executor()
    state_before = executor._current_plan.state
    index_before = executor._current_plan.current_skill_index

    executor.invoke_current_skill()

    check(executor._current_plan.state == state_before, "T20a: session state is unchanged after a successful invoke_current_skill()")
    check(executor._current_plan.current_skill_index == index_before, "T20b: the skill cursor is unchanged after a successful invoke_current_skill()")


# ---------------------------------------------------------------------------
# T21 -- real integration with non-trivial, real parameters flowing to
# both Tools through a genuine ToolContext-shaped context
# ---------------------------------------------------------------------------
def scenario_real_integration_with_parameters() -> None:
    registry = ToolRegistry()
    price_tool = MarketPriceTool()
    news_tool = MarketNewsTool()
    registry.register(price_tool.name, price_tool)
    registry.register(news_tool.name, news_tool)
    resolver = ToolResolver(registry)

    skill = TextAnalysisSkill()
    # Same seam Executor.invoke_current_skill() itself uses
    # (setattr(skill, "_resolve_tool", ...)) -- a real ToolResolver
    # over a real ToolRegistry holding the real MarketPriceTool/
    # MarketNewsTool instances, just attached directly so this
    # scenario can supply a richer context than the Executor's own
    # fixed tool_context_factory (task=None/parameters={}/metadata={})
    # currently builds.
    skill._resolve_tool = resolver.resolve

    rich_context = ToolContext(
        task=None,
        parameters={"symbol": "BBCA", "headlines": ["Profits surge to a record high", "Shares plunge after profit warning"]},
        metadata={},
    )
    result = skill.execute(rich_context)

    check(result.success is True, "T21: combined success True with real, non-trivial parameters")
    check(result.output["price"]["symbol"] == "UNKNOWN", "T21: MarketPriceTool's own Sprint 99 output is symbol-agnostic (still 'UNKNOWN')")
    check(result.output["news"]["symbol"] == "BBCA", "T21: MarketNewsTool really read 'symbol' from the shared context")
    check(result.output["news"]["headline_count"] == 2, "T21: MarketNewsTool really read both headlines from the shared context")
    check(result.output["news"]["sentiment_score"] == 0, "T21: MarketNewsTool's real sentiment classification computed a tie (1 positive, 1 negative)")


def main() -> int:
    scenarios = [
        scenario_call_order_and_names,
        scenario_combined_output_shape,
        scenario_both_succeed,
        scenario_price_fails,
        scenario_news_fails,
        scenario_both_fail,
        scenario_metadata_and_type,
        scenario_price_raises_short_circuits,
        scenario_news_raises_propagates,
        scenario_no_resolver_injected,
        scenario_ast_execute_body,
        scenario_no_new_abstraction_classes,
        scenario_no_forbidden_references,
        scenario_class_shape_unchanged,
        scenario_real_integration,
        scenario_real_integration_repeat_call,
        scenario_real_integration_session_state_unaffected,
        scenario_real_integration_with_parameters,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 10 SPRINT 108 TEXT-ANALYSIS-SKILL-MULTI-TOOL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())