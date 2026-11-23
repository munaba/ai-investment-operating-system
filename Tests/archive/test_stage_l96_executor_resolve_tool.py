"""Phase 8 Sprint 96: Executor.resolve_current_tool() connects
ToolInvocation to ToolResolver. Reuses current_tool_invocation() once
(never duplicates current_skill()/_tool_names checks), then -- if a
ToolResolver was injected -- calls self._tool_resolver.resolve(name)
once and returns the Tool unchanged. No execute(), no ToolContext/
SkillContext, nothing cached/mutated/wrapped/logged. Table-driven, no
pytest, global counter + main().
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
from Orchestration.tool_invocation import ToolInvocation
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
        raise AssertionError("resolve_current_tool must never call skill.execute()")

class _Tool:
    """A resolved-Tool stand-in that raises if ever executed/inspected."""

    def execute(self, *args, **kwargs):
        raise AssertionError("resolve_current_tool must never call tool.execute()")

class _RecordingResolver(ToolResolver):
    def __init__(self, tool=None, exc=None):
        self.calls: List[Any] = []
        self.tool = tool
        self.exc = exc

    def resolve(self, tool_name):  # type: ignore[override]
        self.calls.append(tool_name)
        if self.exc is not None:
            raise self.exc
        return self.tool

class _SpyInvocationRecorder:
    """Wraps Executor.current_tool_invocation to count calls without
    changing its behavior, restored via try/finally by the caller."""

    def __init__(self, executor):
        self.calls = 0
        self._executor = executor
        self._original = executor.current_tool_invocation

    def __enter__(self):
        outer = self

        def wrapped():
            outer.calls += 1
            return outer._original()

        self._executor.current_tool_invocation = wrapped
        return self

    def __exit__(self, exc_type, exc, tb):
        del self._executor.current_tool_invocation
        return False

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
# --- V1-V8: basic successful resolution -------------------------------------
def scenario_basic_resolution() -> None:
    tool = _Tool()
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("price_tool",))
    executor = _running_executor(skill, tool_resolver=resolver)

    result = executor.resolve_current_tool()
    check(result is tool, "V1: returns the resolved Tool by identity")
    check(resolver.calls == ["price_tool"], "V2: resolver.resolve() called with the correct tool_name")
    check(len(resolver.calls) == 1, "V3: resolve() called exactly once")

    result2 = executor.resolve_current_tool()
    check(result2 is tool, "V4: second call also returns the same Tool by identity")
    check(resolver.calls == ["price_tool", "price_tool"], "V5: no caching -- resolve() called again on a second invocation")
    check(not hasattr(executor, "_resolved_tool"), "V6: no cache attribute created on the Executor")
    check(not hasattr(skill, "_resolve_tool"), "V7: no _resolve_tool ever attached to the skill")
    check(not hasattr(skill, "_tool_names") or skill._tool_names == ("price_tool",), "V8: _tool_names left untouched")
    check(executor._current_plan.current_skill_index == 0, "V30: skill cursor never advances")
    check(executor._current_plan.state == "running", "V31: session state never mutated")
# --- V9-V11: current_tool_invocation()/current_skill() call counts ---------
def scenario_invocation_call_count() -> None:
    tool = _Tool()
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=resolver)

    with _SpyInvocationRecorder(executor) as spy:
        executor.resolve_current_tool()
        check(spy.calls == 1, f"V9: current_tool_invocation() called exactly once; got {spy.calls}")

    skill_calls = 0
    original_current_skill = executor.current_skill

    def counting_current_skill():
        nonlocal skill_calls
        skill_calls += 1
        return original_current_skill()

    executor.current_skill = counting_current_skill
    try:
        result = executor.resolve_current_tool()
    finally:
        del executor.current_skill
    check(skill_calls == 1, f"V10: current_skill() called exactly once overall (via current_tool_invocation()); got {skill_calls}")
    check(result is tool, "V11: resolution still succeeds after instrumentation")
# --- V14-V17: multiple tool names -- first one is forwarded ------------------
def scenario_multiple_tool_names_forwarded() -> None:
    tool = _Tool()
    resolver = _RecordingResolver(tool=tool)
    skill = _Skill(tool_names=("alpha", "beta"))
    executor = _running_executor(skill, tool_resolver=resolver)

    result = executor.resolve_current_tool()
    check(result is tool, "V14: resolution succeeds with multiple declared tool names")
    check(resolver.calls == ["alpha"], "V15: only the first tool name ('alpha') is forwarded")
    check("beta" not in resolver.calls, "V16: the second tool name is never forwarded")
    check(len(resolver.calls) == 1, "V17: resolve() still called exactly once")
# --- V18-V21: missing ToolResolver raises ExecutorError ----------------------
def scenario_missing_resolver() -> None:
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill)  # no tool_resolver injected

    exc = _catch(lambda: executor.resolve_current_tool())
    check(isinstance(exc, ExecutorError), "V18: missing ToolResolver raises ExecutorError")
    check(not isinstance(exc, ExecutionSessionError), "V19: not (mis-)raised as ExecutionSessionError")
    check(str(exc) != "", "V20: exception carries a non-empty message")
    check(not hasattr(executor, "_resolved_tool"), "V21: no cache attribute created on failure")
# --- V22-V25: underlying current_tool_invocation() failures propagate -------
def scenario_delegated_failures() -> None:
    resolver = _RecordingResolver(tool=_Tool())

    executor = _make_executor(tool_resolver=resolver)  # no execute_plan() call at all
    exc = _catch(lambda: executor.resolve_current_tool())
    check(isinstance(exc, ExecutorError), "V22: missing session raises ExecutorError (via current_tool_invocation())")
    check(resolver.calls == [], "V23: resolve() never called when the underlying session is missing")

    skill = _Skill()  # no _tool_names at all
    executor2 = _running_executor(skill, tool_resolver=resolver)
    exc2 = _catch(lambda: executor2.resolve_current_tool())
    check(isinstance(exc2, ExecutorError), "V24: missing _tool_names raises ExecutorError (via current_tool_invocation())")
    check(resolver.calls == [], "V25: resolve() never called when _tool_names is missing")
# --- V26-V29: resolver exception propagates unchanged ------------------------
def scenario_resolver_exception_propagation() -> None:
    boom = ValueError("resolver exploded")
    resolver = _RecordingResolver(exc=boom)
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=resolver)

    exc = _catch(lambda: executor.resolve_current_tool())
    check(exc is boom, "V26: resolver exception propagated unchanged, by identity")
    check(resolver.calls == ["t"], "V27: resolve() was called exactly once before raising")
    check(not isinstance(exc, ExecutorError), "V28: not wrapped into ExecutorError")
    check(not hasattr(executor, "_resolved_tool"), "V29: no cache attribute created after a resolver exception")
# --- V34-V39: AST verification of resolve_current_tool() --------------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.resolve_current_tool))
    tree = ast.parse(source)
    fn = tree.body[0]
    check(fn.name == "resolve_current_tool", "V34: method named 'resolve_current_tool'")
    params = [a.arg for a in fn.args.args]
    check(params == ["self"], f"V35: takes no arguments beyond self; got {params}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else (c.func.id if isinstance(c.func, ast.Name) else None))
        for c in calls
    }
    call_names.discard(None)
    check(
        call_names == {"current_tool_invocation", "ExecutorError", "resolve"},
        f"V36: only sanctioned calls present; got {call_names}",
    )

    resolve_calls = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "resolve"]
    check(len(resolve_calls) == 1, f"V37: exactly one .resolve(...) call; got {len(resolve_calls)}")

    forbidden = {
        "ToolContext", "SkillContext", "Runtime", "Workflow", "Planner",
        "Registry", "Manager", "Repository", "Service", "execute",
        "current_skill", "logging", "logger", "cache",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), f"V38: no forbidden name referenced (overlap {forbidden & referenced})")

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V39: no loop or try/except in the method body")

def scenario_ast_shape_and_order() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.resolve_current_tool))
    tree = ast.parse(source)
    fn = tree.body[0]
    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n is not fn]
    check(len(nested_funcs) == 0, "V40: no nested/local helper function defined")

    return_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    check(len(return_nodes) == 1, "V41: exactly one return statement")
    ret = return_nodes[0].value
    check(isinstance(ret, ast.Name) and ret.id == "tool", "V42: return statement returns the local 'tool' by name")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    inv_call = next(c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "current_tool_invocation")
    resolve_call = next(c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "resolve")
    check(inv_call.lineno <= resolve_call.lineno, "V43: current_tool_invocation() invoked at or before resolve(...)")

    resolve_arg = resolve_call.args[0] if resolve_call.args else None
    check(
        isinstance(resolve_arg, ast.Attribute) and resolve_arg.attr == "tool_name",
        "V44: resolve() is called with 'invocation.tool_name'",
    )
# --- V45-V47: module imports / namespace / public surface -------------------
def scenario_module_imports_and_surface() -> None:
    module_tree = ast.parse((ROOT / "Orchestration" / "executor.py").read_text())
    from_modules = {n.module for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom)}
    forbidden_modules = {
        "Core.runtime", "Orchestration.workflow", "Orchestration.planner",
        "Orchestration.tool_registry", "Orchestration.tool_manager",
        "Orchestration.skill_registry", "Repository",
    }
    check(forbidden_modules.isdisjoint(from_modules), f"V45: no forbidden module imported (overlap {forbidden_modules & from_modules})")

    public_methods = {n for n in dir(Executor) if not n.startswith("_") and callable(getattr(Executor, n, None))}
    expected = {
        "execute", "has_pending_tasks", "execute_plan", "prepare_session",
        "start_session", "advance_skill", "current_skill",
        "invoke_current_skill", "current_tool_invocation", "resolve_current_tool",
    }
    check(public_methods == expected, f"V46: Executor's public callables exactly as expected; got {public_methods}")

    signature = inspect.signature(Executor.resolve_current_tool)
    params = [name for name in signature.parameters if name != "self"]
    check(params == [], "V47: resolve_current_tool() takes no arguments beyond self")

def main() -> int:
    for scenario in [
        scenario_basic_resolution,
        scenario_invocation_call_count,
        scenario_multiple_tool_names_forwarded,
        scenario_missing_resolver,
        scenario_delegated_failures,
        scenario_resolver_exception_propagation,
        scenario_ast_verification,
        scenario_ast_shape_and_order,
        scenario_module_imports_and_surface,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 96 EXECUTOR-RESOLVE-TOOL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())