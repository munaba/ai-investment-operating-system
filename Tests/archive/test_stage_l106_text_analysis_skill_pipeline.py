"""
Phase 9 Sprint 106 proof suite -- First Real Skill -> Tool Pipeline.

``TextAnalysisSkill.execute(context)`` no longer raises
``NotImplementedError``. Its entire body is now exactly one
statement: ``return self.execute_tool_result("market_price",
context)`` -- reusing ``BaseSkill.execute_tool_result()`` (Sprint
100), which itself reuses ``BaseSkill.execute_tool()`` (Sprint 85),
which resolves a Tool via the ``_resolve_tool`` callable an
``Executor`` injects (Sprint 84) and calls ``tool.execute(context)``
exactly once. No new abstraction is introduced anywhere in this
sprint -- ``Executor``, ``BaseSkill``, ``SkillContext``,
``ToolContext``, ``ToolResolver``, ``ToolRegistry``, ``ToolResult``,
``SkillResult``, and ``MarketPriceTool`` are all completely unchanged
and untouched by this sprint.

Scope: dedicated regression suite for the Sprint 106 change to
``Orchestration.text_analysis_skill.TextAnalysisSkill`` only. Mirrors
the compact, table-driven, no-pytest, global-counter-plus-main()
style already used throughout ``Tests/test_stage_l8*``/``l10*``.

Three layers of coverage:

  1. Seam-level scenarios that inject ``_resolve_tool`` directly on a
     ``TextAnalysisSkill`` instance -- exactly the same seam
     ``Executor.invoke_current_skill()`` uses in production -- to
     observe exactly what ``execute()`` does, without touching
     ``Executor`` itself.
  2. Instrumented-passthrough scenarios that wrap
     ``execute_tool_result`` on a single instance with a *counting*
     wrapper that still calls straight through to the real,
     unmodified ``BaseSkill.execute_tool_result`` -- used only to
     observe call count/arguments/identity; production behavior
     itself is never replaced, faked, or short-circuited.
  3. AST/namespace/import verification of the module's static shape.
  4. A real, fully-wired integration scenario -- genuine
     ``Executor``, ``ToolRegistry``, ``ToolResolver``, real
     ``TextAnalysisSkill``, real ``MarketPriceTool`` -- with **no
     monkeypatch, no stub, no test double anywhere in the chain**,
     proving the Sprint 105 pipeline
     (``Executor -> invoke_current_skill() -> TextAnalysisSkill ->
     MarketPriceTool -> ToolResult -> SkillResult``) is now a real,
     working production path.

Invariant coverage:
    T1  -- TextAnalysisSkill.execute() no longer raises
           NotImplementedError.
    T2  -- execute() delegates to execute_tool_result() with
           tool_name="market_price".
    T3  -- execute() passes context straight through, unexamined
           (identity-preserving).
    T4  -- execute_tool_result() is called exactly once per execute()
           call.
    T5  -- calling execute() twice invokes execute_tool_result()
           exactly twice total (once per call).
    T6  -- the resolved Tool's execute() receives exactly the context
           object passed to Skill.execute() (identity-preserving).
    T7  -- the SkillResult execute_tool_result() produces is returned
           by TextAnalysisSkill.execute() unchanged (identity,
           not a copy or wrapper).
    T8  -- a SkillResult's fields (success/output/error/metadata) are
           forwarded from the ToolResult unchanged.
    T9  -- no wrapping: the returned object's exact type is
           SkillResult, never a subclass or container.
    T10 -- exception propagation: if the resolved Tool's execute()
           raises, TextAnalysisSkill.execute() lets the exact
           exception instance propagate unchanged.
    T11 -- exception propagation: if no ToolResolver/_resolve_tool
           was ever injected, execute() raises BaseSkill's own
           SkillError (propagated unchanged from execute_tool()).
    T12 -- AST: execute()'s body is exactly one Return statement.
    T13 -- AST: that Return's value is a Call to
           self.execute_tool_result(...) with exactly two positional
           args and no keyword args.
    T14 -- AST: the first argument is the string literal
           "market_price".
    T15 -- AST: the second argument is the bare name "context".
    T16 -- AST: no other Call node appears anywhere in execute()'s
           body (no ToolResult(...), no SkillResult(...), no
           ToolResolver(...), no ToolRegistry(...), no
           ToolContext(...), no isinstance(...), no logging call, no
           len()/retry helper).
    T17 -- AST: execute()'s body contains no try/except, no for/while
           loop, and no comprehension.
    T18 -- AST: the module introduces no new top-level import --
           still only Orchestration.base_skill.BaseSkill plus stdlib
           __future__/typing.
    T19 -- namespace: the module does not expose
           Executor/ToolResolver/ToolRegistry/ToolContext/ToolResult/
           MarketPriceTool/SkillResult symbols directly.
    T20 -- namespace: module source contains no reference to
           Runtime/Workflow/Planner/EventBus/ToolManager/
           AutonomousHost/TaskManager/SkillResolver/Provider/Service/
           Repository/Database by name.
    T21 -- class shape: TextAnalysisSkill still defines no __init__
           of its own and carries no per-instance state beyond
           whatever an Executor injects.
    T22 -- name/description are unchanged ("text_analysis" /
           "Analyze textual information.").
    T23 -- real integration: Executor -> invoke_current_skill() ->
           TextAnalysisSkill -> MarketPriceTool -> ToolResult ->
           SkillResult succeeds end-to-end with zero test doubles.
    T24 -- real integration: the returned SkillResult has
           success=True, output={"symbol": "UNKNOWN", "price": None},
           error=None, metadata={} -- MarketPriceTool's own
           deterministic Sprint 99 result, forwarded unchanged.
    T25 -- real integration: calling invoke_current_skill() twice in
           a row against the same running session produces two
           independent, field-equal SkillResult objects (Tool is
           deterministic, Skill carries no state).
    T26 -- real integration: Executor's own session/cursor state
           (state, current_skill_index) is unaffected by
           invoke_current_skill() succeeding, exactly as already
           guaranteed by Sprint 78-101's own suites.
    T27 -- real integration: the plan's declared tool name
           ("market_price") matches exactly what execute() asks
           execute_tool_result() to resolve (T2), so no ToolRegistry
           lookup failure occurs anywhere in the chain.
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
from Orchestration.base_skill import SkillError
from Orchestration.executor import Executor
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
# Fixtures
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
    """Records every ``(name,)`` it was asked to resolve and returns
    a fixed Tool stand-in -- exactly the shape
    ``Executor.invoke_current_skill()`` injects as
    ``skill._resolve_tool``."""

    def __init__(self, tool):
        self.tool = tool
        self.requested_names: List[Any] = []

    def __call__(self, name):
        self.requested_names.append(name)
        return self.tool


def _wrap_execute_tool_result(skill: TextAnalysisSkill):
    """Wrap ``skill.execute_tool_result`` with a call-counting/arg-
    capturing passthrough that still calls straight through to the
    real, unmodified ``BaseSkill.execute_tool_result`` -- production
    behavior itself is never replaced, only observed."""
    calls: List[tuple] = []
    original = skill.execute_tool_result

    def _wrapper(tool_name, context):
        calls.append((tool_name, context))
        return original(tool_name, context)

    skill.execute_tool_result = _wrapper  # instance-level shadow only
    return calls


# ---------------------------------------------------------------------------
# T1-T3 -- basic delegation shape (seam-level: _resolve_tool injected
# directly, exactly like Executor.invoke_current_skill() does)
# ---------------------------------------------------------------------------
def scenario_basic_delegation() -> None:
    fixed_result = ToolResult(success=True, output="X", error=None, metadata={})
    tool = _RecordingTool(result=fixed_result)
    resolver = _RecordingResolver(tool)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver

    sentinel_context = object()
    exc = _catch(lambda: skill.execute(sentinel_context))
    check(exc is None, f"T1: execute() no longer raises NotImplementedError; got {exc!r}")

    check(resolver.requested_names == ["market_price"], "T2: execute_tool_result() resolved exactly 'market_price'")
    check(len(tool.calls) == 1, "T3a: the resolved Tool's execute() was called exactly once")
    check(tool.calls[0] is sentinel_context, "T3b: the Tool received the exact same context object by identity")


# ---------------------------------------------------------------------------
# T4-T5 -- call counts, via instrumented passthrough (still calls the
# real BaseSkill.execute_tool_result underneath)
# ---------------------------------------------------------------------------
def scenario_call_counts() -> None:
    fixed_result = ToolResult(success=True, output=1, error=None, metadata={})
    tool = _RecordingTool(result=fixed_result)
    resolver = _RecordingResolver(tool)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver
    calls = _wrap_execute_tool_result(skill)

    skill.execute(object())
    check(len(calls) == 1, "T4: execute_tool_result() is called exactly once per execute() call")

    skill.execute(object())
    check(len(calls) == 2, "T5: calling execute() twice invokes execute_tool_result() exactly twice total")
    check([c[0] for c in calls] == ["market_price", "market_price"], "T5b: both calls asked for 'market_price'")


# ---------------------------------------------------------------------------
# T6 -- context identity through the whole chain
# ---------------------------------------------------------------------------
def scenario_context_identity() -> None:
    fixed_result = ToolResult(success=True, output=None, error=None, metadata={})
    tool = _RecordingTool(result=fixed_result)
    resolver = _RecordingResolver(tool)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver

    ctx = {"marker": "unique-context-object"}
    skill.execute(ctx)
    check(tool.calls[0] is ctx, "T6: the resolved Tool's execute() receives the exact Skill.execute() context by identity")


# ---------------------------------------------------------------------------
# T7-T9 -- return value identity, field forwarding, exact type
# ---------------------------------------------------------------------------
def scenario_return_value_shape() -> None:
    fixed_result = ToolResult(success=True, output={"a": 1}, error=None, metadata={"m": 2})
    tool = _RecordingTool(result=fixed_result)
    resolver = _RecordingResolver(tool)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver
    calls = _wrap_execute_tool_result(skill)

    returned = skill.execute(object())
    check(len(calls) == 1, "T7 setup: execute_tool_result() called exactly once")

    check(type(returned) is SkillResult, "T9: the returned object's exact type is SkillResult, never a subclass or wrapper")
    check(returned.success is True, "T8a: SkillResult.success forwarded from ToolResult.success")
    check(returned.output == {"a": 1}, "T8b: SkillResult.output forwarded from ToolResult.output")
    check(returned.error is None, "T8c: SkillResult.error forwarded from ToolResult.error")
    check(dict(returned.metadata) == {"m": 2}, "T8d: SkillResult.metadata forwarded from ToolResult.metadata")


def scenario_return_by_identity() -> None:
    """T7: confirm execute() returns exactly what execute_tool_result()
    itself produced -- no re-wrapping -- by capturing the object the
    real (unwrapped) execute_tool_result() returns and comparing it,
    by identity, to what execute() ultimately returns."""
    fixed_result = ToolResult(success=False, output=None, error="boom", metadata={})
    tool = _RecordingTool(result=fixed_result)
    resolver = _RecordingResolver(tool)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver

    captured: List[SkillResult] = []
    original = skill.execute_tool_result

    def _capturing_wrapper(tool_name, context):
        produced = original(tool_name, context)
        captured.append(produced)
        return produced

    skill.execute_tool_result = _capturing_wrapper

    returned = skill.execute(object())
    check(len(captured) == 1, "T7 setup: execute_tool_result() called exactly once")
    check(returned is captured[0], "T7: execute() returns the exact SkillResult execute_tool_result() produced, by identity")


# ---------------------------------------------------------------------------
# T10-T11 -- exception propagation
# ---------------------------------------------------------------------------
def scenario_tool_exception_propagates() -> None:
    boom = ValueError("tool failed")
    tool = _RecordingTool(exc=boom)
    resolver = _RecordingResolver(tool)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver

    raised = None
    try:
        skill.execute(object())
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(raised is boom, "T10: the exact exception instance raised by the Tool propagates unchanged from execute()")


def scenario_missing_resolver_raises_skill_error() -> None:
    skill = TextAnalysisSkill()  # no _resolve_tool ever injected

    raised = None
    try:
        skill.execute(object())
    except SkillError as exc:
        raised = exc

    check(isinstance(raised, SkillError), "T11: with no ToolResolver injected, execute() raises BaseSkill's own SkillError")


# ---------------------------------------------------------------------------
# T12-T18 -- AST verification
# ---------------------------------------------------------------------------
def _execute_source() -> str:
    src = inspect.getsource(TextAnalysisSkill.execute)
    return textwrap.dedent(src)


def _execute_ast() -> ast.FunctionDef:
    tree = ast.parse(_execute_source())
    return tree.body[0]


def scenario_ast_verification() -> None:
    fn = _execute_ast()
    check(isinstance(fn, ast.FunctionDef) and fn.name == "execute", "AST setup: parsed execute()'s own FunctionDef")

    body = fn.body
    # Skip a leading docstring Expr(Constant) if present.
    stmts = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))]

    check(len(stmts) == 1, f"T12: execute()'s body is exactly one (non-docstring) statement; got {len(stmts)}")
    ret = stmts[0]
    check(isinstance(ret, ast.Return), "T12b: that one statement is a Return")

    call = ret.value
    check(isinstance(call, ast.Call), "T13: the Return's value is a Call")
    check(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute_tool_result"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self",
        "T13b: the Call is to self.execute_tool_result(...)",
    )
    check(len(call.args) == 2, "T13c: execute_tool_result(...) is called with exactly two positional args")
    check(len(call.keywords) == 0, "T13d: execute_tool_result(...) is called with no keyword args")

    arg0 = call.args[0] if call.args else None
    check(
        isinstance(arg0, ast.Constant) and arg0.value == "market_price",
        f"T14: the first argument is the string literal 'market_price'; got {ast.dump(arg0) if arg0 else None}",
    )

    arg1 = call.args[1] if len(call.args) > 1 else None
    check(
        isinstance(arg1, ast.Name) and arg1.id == "context",
        f"T15: the second argument is the bare name 'context'; got {ast.dump(arg1) if arg1 else None}",
    )

    # T16 -- no other Call node anywhere in execute()'s body.
    all_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    check(len(all_calls) == 1, f"T16: execute()'s body contains exactly one Call node total; got {len(all_calls)}")

    forbidden_names = {
        "ToolResult", "SkillResult", "ToolResolver", "ToolRegistry",
        "ToolContext", "isinstance", "len", "print", "open",
    }
    called_names = set()
    for n in all_calls:
        if isinstance(n.func, ast.Name):
            called_names.add(n.func.id)
        elif isinstance(n.func, ast.Attribute):
            called_names.add(n.func.attr)
    check(
        not (called_names & forbidden_names),
        f"T16b: no forbidden construction/inspection calls appear; got {called_names & forbidden_names}",
    )

    # T17 -- no try/except, no loops, no comprehensions.
    forbidden_node_types = (ast.Try, ast.For, ast.While, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
    found_forbidden = [n for n in ast.walk(fn) if isinstance(n, forbidden_node_types)]
    check(len(found_forbidden) == 0, f"T17: execute()'s body contains no try/except/loop/comprehension; got {[type(n).__name__ for n in found_forbidden]}")


def scenario_import_verification() -> None:
    module_path = ROOT / "Orchestration" / "text_analysis_skill.py"
    source = module_path.read_text()
    tree = ast.parse(source)

    imported_modules = set()
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module)
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                imported_names.add(alias.asname or alias.name)

    check(
        imported_modules == {"__future__", "typing", "Orchestration.base_skill"},
        f"T18: no new top-level import introduced; got {imported_modules}",
    )
    check(imported_names == {"annotations", "Any", "BaseSkill"}, f"T18b: imported names exactly as expected; got {imported_names}")


def scenario_namespace_verification() -> None:
    import Orchestration.text_analysis_skill as mod

    forbidden_symbols = [
        "Executor", "ToolResolver", "ToolRegistry", "ToolContext",
        "ToolResult", "MarketPriceTool", "SkillResult",
    ]
    for symbol in forbidden_symbols:
        check(not hasattr(mod, symbol), f"T19: module namespace does not expose '{symbol}'")

    module_path = ROOT / "Orchestration" / "text_analysis_skill.py"
    source = module_path.read_text()
    forbidden_words = [
        "Runtime", "Workflow", "Planner", "EventBus", "ToolManager",
        "AutonomousHost", "TaskManager", "SkillResolver", "Provider",
        "Service", "Repository", "Database",
    ]
    # Only scan actual code identifiers, not the module docstring/
    # comments, since the docstring legitimately documents what is
    # NOT imported (e.g. "does NOT import ... Runtime ...").
    tree = ast.parse(source)
    names_referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs_referenced = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for word in forbidden_words:
        check(word not in names_referenced and word not in attrs_referenced, f"T20: '{word}' is not referenced as a real name/attribute in the module's code")


# ---------------------------------------------------------------------------
# T21-T22 -- class shape unchanged
# ---------------------------------------------------------------------------
def scenario_class_shape_unchanged() -> None:
    check("__init__" not in TextAnalysisSkill.__dict__, "T21a: TextAnalysisSkill defines no __init__ of its own")
    skill = TextAnalysisSkill()
    check(skill.__dict__ == {}, "T21b: a freshly constructed instance has no instance __dict__ entries")
    check(skill.name == "text_analysis", "T22a: name is unchanged ('text_analysis')")
    check(skill.description == "Analyze textual information.", "T22b: description is unchanged")


# ---------------------------------------------------------------------------
# T23-T27 -- real, fully-wired integration (no test doubles anywhere)
# ---------------------------------------------------------------------------
def _real_running_executor():
    registry = ToolRegistry()
    tool = MarketPriceTool()
    registry.register(tool.name, tool)
    resolver = ToolResolver(registry)

    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host, tool_resolver=resolver)

    skill = TextAnalysisSkill()
    plan = SkillExecutionPlan(skills=(skill,), tools=(tool.name,), metadata={})

    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor


def scenario_real_integration() -> None:
    executor = _real_running_executor()

    exc = _catch(lambda: None)
    result = None
    error = None
    try:
        result = executor.invoke_current_skill()
    except Exception as e:  # noqa: BLE001
        error = e

    check(error is None, f"T23: the real Executor -> Skill -> Tool pipeline runs end-to-end without raising; got {error!r}")
    check(isinstance(result, SkillResult), "T23b: invoke_current_skill() returns a real SkillResult")

    check(result.success is True, "T24a: SkillResult.success is True")
    check(result.output == {"symbol": "UNKNOWN", "price": None}, f"T24b: SkillResult.output matches MarketPriceTool's deterministic output; got {result.output!r}")
    check(result.error is None, "T24c: SkillResult.error is None")
    check(dict(result.metadata) == {}, "T24d: SkillResult.metadata is empty")


def scenario_real_integration_repeat_call() -> None:
    executor = _real_running_executor()

    result1 = executor.invoke_current_skill()
    result2 = executor.invoke_current_skill()

    check(result1 is not result2, "T25a: two separate invoke_current_skill() calls produce two distinct SkillResult objects")
    check(
        (result1.success, result1.output, result1.error, dict(result1.metadata))
        == (result2.success, result2.output, result2.error, dict(result2.metadata)),
        "T25b: both results are field-equal (deterministic Tool, stateless Skill)",
    )


def scenario_real_integration_session_state_unaffected() -> None:
    executor = _real_running_executor()

    state_before = executor._current_plan.state
    index_before = executor._current_plan.current_skill_index

    executor.invoke_current_skill()

    check(executor._current_plan.state == state_before, "T26a: session state is unchanged after a successful invoke_current_skill()")
    check(executor._current_plan.current_skill_index == index_before, "T26b: the skill cursor is unchanged after a successful invoke_current_skill()")


def scenario_real_integration_tool_name_alignment() -> None:
    """T27: the plan declares tools=("market_price",) -- the exact
    same literal Sprint 106 hardcodes into TextAnalysisSkill.execute()
    -- so ToolRegistry lookup never fails for a name mismatch."""
    registry = ToolRegistry()
    tool = MarketPriceTool()
    check(tool.name == "market_price", "T27a: MarketPriceTool.name is 'market_price' -- what execute() asks for")
    registry.register(tool.name, tool)
    resolver = ToolResolver(registry)

    resolved = resolver.resolve("market_price")
    check(resolved is tool, "T27b: resolving 'market_price' returns the exact registered MarketPriceTool instance")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_basic_delegation,
        scenario_call_counts,
        scenario_context_identity,
        scenario_return_value_shape,
        scenario_return_by_identity,
        scenario_tool_exception_propagates,
        scenario_missing_resolver_raises_skill_error,
        scenario_ast_verification,
        scenario_import_verification,
        scenario_namespace_verification,
        scenario_class_shape_unchanged,
        scenario_real_integration,
        scenario_real_integration_repeat_call,
        scenario_real_integration_session_state_unaffected,
        scenario_real_integration_tool_name_alignment,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            import traceback
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"PHASE 9 SPRINT 106 TEXT ANALYSIS SKILL PIPELINE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())