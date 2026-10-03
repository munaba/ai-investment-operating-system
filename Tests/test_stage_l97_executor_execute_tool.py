"""Phase 8 Sprint 97: Executor.execute_current_tool() completes the
Tool invocation pipeline. Reuses resolve_current_tool() once (never
duplicates its validation), constructs exactly one ToolContext
(task=None, parameters={}, metadata={}), calls tool.execute(context)
exactly once, and returns the ToolResult unchanged -- no inspection,
no wrapping, no copying, no caching, no logging, no retry, no state
mutation.

Important behavioral note (verified, not assumed): the real
``Orchestration.tool_context.ToolContext`` rejects ``task=None`` in
its own ``__post_init__`` (raises ``ToolContextError``). Since the
LOCKED implementation shape for this sprint fixes ``task=None``
verbatim, calling ``execute_current_tool()`` against the real
``ToolContext`` always raises ``ToolContextError`` before
``tool.execute()`` is ever reached -- it never reaches a "successful"
Tool run. That is exercised directly (Group A, real ``ToolContext``).

To additionally verify the resolve -> construct -> execute -> return
wiring itself (the part of the requirements checklist that assumes
construction succeeds -- successful passthrough, no caching, no
result inspection, and Tool.execute() exception propagation), Group B
patches ``executor_mod.ToolContext`` with a lenient stand-in that
skips the ``task is None`` check but is otherwise a faithful
passthrough object, restoring the real class immediately after each
scenario. This isolates "does the method wire things together
correctly" from "does the injected ToolContext dependency happen to
accept these particular arguments" -- both are needed for full
coverage of the pipeline.

Table-driven, no pytest, global counter + main().
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

import Orchestration.executor as executor_mod
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.execution_session import ExecutionSessionError
from Orchestration.executor import Executor, ExecutorError
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
from Orchestration.tool_context import ToolContext, ToolContextError
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
# --- Fixtures --------------------------------------------------------------
class _Skill:
    def __init__(self, tool_names=None):
        if tool_names is not None:
            self._tool_names = tool_names

    def execute(self, *args, **kwargs):
        raise AssertionError("execute_current_tool must never call skill.execute()")

class _RecordingTool:
    """A resolved-Tool stand-in that records execute() calls."""

    def __init__(self, result=None, exc=None):
        self.calls: List[Any] = []
        self.result = result
        self.exc = exc

    def execute(self, context):
        self.calls.append(context)
        if self.exc is not None:
            raise self.exc
        return self.result

class _RecordingResolver(ToolResolver):
    def __init__(self, tool=None):
        self.calls: List[Any] = []
        self.tool = tool

    def resolve(self, tool_name):  # type: ignore[override]
        self.calls.append(tool_name)
        return self.tool

class _LenientToolContext:
    """A patched stand-in for ToolContext used only in Group B: a
    faithful passthrough (records task/parameters/metadata by
    identity, no validation) that accepts ``task=None`` so the
    resolve -> construct -> execute -> return wiring can be verified
    in isolation from the real ToolContext's own 'task is not None'
    business rule."""

    def __init__(self, task=None, parameters=None, metadata=None):
        self.task = task
        self.parameters = parameters
        self.metadata = metadata

class _Sentinel:
    """Stand-in for a ToolResult -- returned by identity, never inspected."""

def _make_executor(tool_resolver=None) -> Executor:
    kwargs = {"task_manager": TaskManager(TaskQueue()), "host": AutonomousHost()}
    if tool_resolver is not None:
        kwargs["tool_resolver"] = tool_resolver
    return Executor(**kwargs)

def _running_executor(skill, tool_resolver=None) -> Executor:
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _make_executor(tool_resolver=tool_resolver)
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor

def _catch(fn):
    try:
        fn()
        return None
    except Exception as e:  # noqa: BLE001
        return e

class _patched_tool_context:
    """Context manager: temporarily replaces executor_mod.ToolContext
    with the lenient stand-in, restoring the real class afterward
    even if the body raises."""

    def __enter__(self):
        executor_mod.ToolContext = _LenientToolContext
        return self

    def __exit__(self, exc_type, exc, tb):
        executor_mod.ToolContext = ToolContext
        return False
# === GROUP A: real ToolContext -- always raises ToolContextError ===========
# --- V1-V6: ToolContext(task=None) rejects task, propagates unchanged ------
def scenario_real_context_construction_fails() -> None:
    tool = _RecordingTool(result="unused")
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("price_tool",))
    executor = _running_executor(skill, tool_resolver=resolver)

    exc = _catch(lambda: executor.execute_current_tool())
    check(isinstance(exc, ToolContextError), f"V1: real ToolContext(task=None) raises ToolContextError; got {exc!r}")
    check(not isinstance(exc, ExecutorError), "V2: not wrapped into ExecutorError")
    check(resolver.calls == ["price_tool"], "V3: resolver already resolved the correct tool before construction ran")
    check(len(resolver.calls) == 1, "V4: resolve() called exactly once")
    check(len(tool.calls) == 0, "V5: tool.execute() never reached -- ToolContext construction failed first")
    check(executor._current_plan.state == "running", "V6: session state never mutated by the failed attempt")
# --- V7-V9: repeated calls behave identically, no caching -------------------
def scenario_real_context_repeated_calls() -> None:
    tool = _RecordingTool(result="unused")
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=resolver)

    exc1 = _catch(lambda: executor.execute_current_tool())
    exc2 = _catch(lambda: executor.execute_current_tool())
    check(isinstance(exc1, ToolContextError) and isinstance(exc2, ToolContextError), "V7: both calls raise ToolContextError")
    check(resolver.calls == ["t", "t"], "V8: resolver called again each time -- no caching of the failure")
    check(not hasattr(executor, "_tool_result"), "V9: no result-cache attribute created on the Executor")
# --- V10-V14: delegated resolution failures propagate (before construction) -
def scenario_delegated_resolution_failures() -> None:
    tool = _RecordingTool(result="unused")
    resolver = _RecordingResolver(tool=tool)

    executor = _make_executor(tool_resolver=resolver)  # no execute_plan() call
    exc = _catch(lambda: executor.execute_current_tool())
    check(isinstance(exc, ExecutorError), "V10: missing session raises ExecutorError (via resolve_current_tool())")
    check(resolver.calls == [], "V11: resolver never called when the underlying session is missing")
    check(len(tool.calls) == 0, "V12: tool.execute() never called when resolution fails")

    skill = _Skill(tool_names=("t",))
    executor2 = _running_executor(skill)  # no tool_resolver injected
    exc2 = _catch(lambda: executor2.execute_current_tool())
    check(isinstance(exc2, ExecutorError), "V13: missing ToolResolver raises ExecutorError")
    check(len(tool.calls) == 0, "V14: tool.execute() still never called")
# --- V15-V17: resolve_current_tool() call count (real ToolContext path) ----
def scenario_resolve_call_count() -> None:
    tool = _RecordingTool(result="unused")
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=resolver)

    calls = 0
    original = executor.resolve_current_tool

    def counting():
        nonlocal calls
        calls += 1
        return original()

    executor.resolve_current_tool = counting
    try:
        exc = _catch(lambda: executor.execute_current_tool())
    finally:
        del executor.resolve_current_tool
    check(calls == 1, f"V15: resolve_current_tool() called exactly once; got {calls}")
    check(isinstance(exc, ToolContextError), "V16: failure still propagates as ToolContextError after instrumentation")
    check(len(tool.calls) == 0, "V17: tool.execute() never reached")
# === GROUP B: lenient patched ToolContext -- verifies the wiring ===========
# --- V18-V25: successful resolve -> construct -> execute -> return chain ---
def scenario_patched_successful_execution() -> None:
    sentinel = _Sentinel()
    tool = _RecordingTool(result=sentinel)
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("price_tool",))
    executor = _running_executor(skill, tool_resolver=resolver)

    with _patched_tool_context():
        result = executor.execute_current_tool()

    check(result is sentinel, "V18: returns the ToolResult by identity")
    check(len(tool.calls) == 1, "V19: tool.execute() called exactly once")
    ctx = tool.calls[0]
    check(isinstance(ctx, _LenientToolContext), "V20: a ToolContext(-like) instance is passed to execute()")
    check(ctx.task is None, "V21: ToolContext.task is None")
    check(ctx.parameters == {}, "V22: ToolContext.parameters is empty")
    check(ctx.metadata == {}, "V23: ToolContext.metadata is empty")
    check(resolver.calls == ["price_tool"], "V24: resolver.resolve() called with the correct tool_name")
    check(executor._current_plan.current_skill_index == 0, "V25: skill cursor never advances")
# --- V26-V28: no caching under the patched (successful) path ---------------
def scenario_patched_no_caching() -> None:
    tool = _RecordingTool(result="r")
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=resolver)

    with _patched_tool_context():
        executor.execute_current_tool()
        executor.execute_current_tool()
    check(len(tool.calls) == 2, "V26: tool.execute() called again on a second invocation -- no caching")
    check(resolver.calls == ["t", "t"], "V27: resolver.resolve() called again on a second invocation")
    check(not hasattr(executor, "_tool_result"), "V28: no result-cache attribute created on the Executor")
# --- V29-V32: Tool.execute() exception propagates unchanged ----------------
def scenario_patched_tool_execute_exception_propagation() -> None:
    boom = ValueError("tool exploded")
    tool = _RecordingTool(exc=boom)
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=resolver)

    with _patched_tool_context():
        exc = _catch(lambda: executor.execute_current_tool())
    check(exc is boom, "V29: tool.execute() exception propagated unchanged, by identity")
    check(len(tool.calls) == 1, "V30: tool.execute() was called exactly once before raising")
    check(not isinstance(exc, ExecutorError), "V31: not wrapped into ExecutorError")
    check(not hasattr(executor, "_tool_result"), "V32: no cache attribute created after a tool exception")
# --- V33: no ToolResult inspection ------------------------------------------
def scenario_patched_no_result_inspection() -> None:
    class _AngryResult:
        """Raises if any attribute is ever accessed -- proves the
        Executor never inspects the returned ToolResult."""

        def __getattr__(self, name):
            raise AssertionError(f"execute_current_tool must never inspect ToolResult.{name}")

        def __eq__(self, other):
            raise AssertionError("execute_current_tool must never compare ToolResult")

        def __bool__(self):
            raise AssertionError("execute_current_tool must never truth-test ToolResult")

    angry = _AngryResult()
    tool = _RecordingTool(result=angry)
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=resolver)

    with _patched_tool_context():
        result = executor.execute_current_tool()
    check(result is angry, "V33: the angry ToolResult stand-in is returned untouched by identity")
# --- V34-V41: AST verification of execute_current_tool() -------------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.execute_current_tool))
    tree = ast.parse(source)
    fn = tree.body[0]
    check(fn.name == "execute_current_tool", "V34: method named 'execute_current_tool'")
    params = [a.arg for a in fn.args.args]
    check(params == ["self"], f"V35: takes no arguments beyond self; got {params}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else (c.func.id if isinstance(c.func, ast.Name) else None))
        for c in calls
    }
    call_names.discard(None)
    check(
        call_names == {"resolve_current_tool", "ToolContext", "execute"},
        f"V36: only sanctioned calls present; got {call_names}",
    )

    execute_calls = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "execute"]
    check(len(execute_calls) == 1, f"V37: exactly one .execute(...) call; got {len(execute_calls)}")

    resolve_calls = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "resolve_current_tool"]
    check(len(resolve_calls) == 1, f"V38: exactly one .resolve_current_tool() call; got {len(resolve_calls)}")

    toolcontext_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "ToolContext"]
    check(len(toolcontext_calls) == 1, f"V39: exactly one ToolContext(...) construction; got {len(toolcontext_calls)}")

    forbidden = {
        "SkillContext", "Runtime", "Workflow", "Planner",
        "Registry", "Manager", "Repository", "Service",
        "current_skill", "current_tool_invocation", "logging", "logger", "cache",
        "retry", "success", "output", "error", "metadata",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), f"V40: no forbidden name referenced (overlap {forbidden & referenced})")

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V41: no loop or try/except in the method body")
# --- V42-V44: shape -- no nested helpers, single return, return identity ---
def scenario_ast_shape_and_order() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.execute_current_tool))
    tree = ast.parse(source)
    fn = tree.body[0]
    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n is not fn]
    check(len(nested_funcs) == 0, "V42: no nested/local helper function defined")

    return_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    check(len(return_nodes) == 1, "V43: exactly one return statement")
    ret = return_nodes[0].value
    check(isinstance(ret, ast.Name) and ret.id == "result", "V44: return statement returns the local 'result' by name")
# --- V45-V49: ToolContext argument shape ------------------------------------
def scenario_ast_context_construction_shape() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.execute_current_tool))
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    tc_call = next(c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "ToolContext")
    kwargs = {kw.arg: kw.value for kw in tc_call.keywords}
    check(set(kwargs.keys()) == {"task", "parameters", "metadata"}, f"V45: ToolContext called with exactly task/parameters/metadata; got {set(kwargs.keys())}")
    check(isinstance(kwargs.get("task"), ast.Constant) and kwargs["task"].value is None, "V46: task=None")
    check(isinstance(kwargs.get("parameters"), ast.Dict) and len(kwargs["parameters"].keys) == 0, "V47: parameters={}")
    check(isinstance(kwargs.get("metadata"), ast.Dict) and len(kwargs["metadata"].keys) == 0, "V48: metadata={}")

    execute_call = next(c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "execute")
    check(
        len(execute_call.args) == 1 and isinstance(execute_call.args[0], ast.Name) and execute_call.args[0].id == "context",
        "V49: tool.execute(context) is called with the local 'context'",
    )
# --- V50-V52: module imports / namespace / public surface ------------------
def scenario_module_imports_and_surface() -> None:
    module_tree = ast.parse((ROOT / "Orchestration" / "executor.py").read_text())
    from_modules = {n.module for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom)}
    forbidden_modules = {
        "Core.runtime", "Orchestration.workflow", "Orchestration.planner",
        "Orchestration.tool_registry", "Orchestration.tool_manager",
        "Orchestration.skill_registry", "Repository",
    }
    check(forbidden_modules.isdisjoint(from_modules), f"V50: no forbidden module imported (overlap {forbidden_modules & from_modules})")

    public_methods = {n for n in dir(Executor) if not n.startswith("_") and callable(getattr(Executor, n, None))}
    expected = {
        "execute", "has_pending_tasks", "execute_plan", "prepare_session",
        "start_session", "advance_skill", "current_skill",
        "invoke_current_skill", "current_tool_invocation", "resolve_current_tool",
        "execute_current_tool",
    }
    check(public_methods == expected, f"V51: Executor's public callables exactly as expected; got {public_methods}")

    signature = inspect.signature(Executor.execute_current_tool)
    params = [name for name in signature.parameters if name != "self"]
    check(params == [], "V52: execute_current_tool() takes no arguments beyond self")

def main() -> int:
    for scenario in [
        scenario_real_context_construction_fails,
        scenario_real_context_repeated_calls,
        scenario_delegated_resolution_failures,
        scenario_resolve_call_count,
        scenario_patched_successful_execution,
        scenario_patched_no_caching,
        scenario_patched_tool_execute_exception_propagation,
        scenario_patched_no_result_inspection,
        scenario_ast_verification,
        scenario_ast_shape_and_order,
        scenario_ast_context_construction_shape,
        scenario_module_imports_and_surface,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 97 EXECUTOR-EXECUTE-TOOL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())