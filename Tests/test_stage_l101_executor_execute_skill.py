"""Phase 9 Sprint 101: Executor.execute_current_skill() -- the first
end-to-end execution path. Reuses current_skill() exactly once, calls
skill.execute(None) exactly once, and returns the SkillResult
unchanged -- no inspection, no wrapping, no caching, no retry, no
logging, no state/cursor mutation. Table-driven, no pytest.
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
from Orchestration.execution_session import ExecutionSessionError
from Orchestration.executor import Executor, ExecutorError
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
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


class _Skill:
    def __init__(self, result=None, exc=None):
        self.calls: List[Any] = []
        self.result, self.exc = result, exc

    def execute(self, context):
        self.calls.append(context)
        if self.exc is not None:
            raise self.exc
        return self.result


class _AngryResolver(ToolResolver):
    def __init__(self):  # type: ignore[override]
        pass

    def resolve(self, tool_name):  # type: ignore[override]
        raise AssertionError("must never resolve a tool")


class _Angry:
    """Raises on any access -- proves the result is never inspected."""

    def __getattr__(self, name):
        raise AssertionError(f"must never inspect result.{name}")


def _executor(tool_resolver=None) -> Executor:
    kwargs = {"task_manager": TaskManager(TaskQueue()), "host": AutonomousHost()}
    if tool_resolver is not None:
        kwargs["tool_resolver"] = tool_resolver
    return Executor(**kwargs)


def _running(skill, tool_resolver=None) -> Executor:
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    ex = _executor(tool_resolver=tool_resolver)
    ex.execute_plan(plan)
    ex.prepare_session()
    ex.start_session()
    return ex


def _catch(fn):
    try:
        fn()
        return None
    except Exception as e:  # noqa: BLE001
        return e


# === GROUP A: behavior ======================================================
def scenario_successful_execution() -> None:
    sentinel = object()
    skill = _Skill(result=sentinel)
    ex = _running(skill)
    result = ex.execute_current_skill()
    check(result is sentinel, "V1: returns the SkillResult by identity")
    check(skill.calls == [None], "V2: skill.execute(None) called exactly once")
    check(ex._current_plan.state == "running", "V3: session state never mutated")
    check(ex._current_plan.current_skill_index == 0, "V4: skill cursor never advances")


def scenario_repeated_calls_no_caching() -> None:
    skill = _Skill(result="r")
    ex = _running(skill)
    ex.execute_current_skill()
    ex.execute_current_skill()
    check(skill.calls == [None, None], "V5: execute() called again -- no caching")
    check(not hasattr(ex, "_skill_result"), "V6: no result-cache attribute created")


def scenario_no_result_inspection() -> None:
    angry = _Angry()
    ex = _running(_Skill(result=angry))
    check(ex.execute_current_skill() is angry, "V7: angry result returned untouched")


def scenario_never_resolves_or_tags_tool() -> None:
    skill = _Skill(result="ok")
    ex = _running(skill, tool_resolver=_AngryResolver())
    ex.execute_current_skill()
    check(not hasattr(skill, "_tool_names"), "V8: skill._tool_names never set")
    check(not hasattr(skill, "_resolve_tool"), "V9: skill._resolve_tool never set")


def scenario_exception_propagates() -> None:
    boom = ValueError("skill exploded")
    skill = _Skill(exc=boom)
    ex = _running(skill)
    exc = _catch(lambda: ex.execute_current_skill())
    check(exc is boom, "V10: exception propagated unchanged, by identity")
    check(skill.calls == [None], "V11: execute() called exactly once before raising")
    check(not isinstance(exc, ExecutorError), "V12: not wrapped into ExecutorError")


def scenario_missing_session_raises() -> None:
    exc = _catch(lambda: _executor().execute_current_skill())
    check(isinstance(exc, ExecutorError), "V13: missing session raises ExecutorError")


def scenario_non_running_session_raises() -> None:
    skill = _Skill(result="unused")
    ex = _executor()
    ex.execute_plan(SkillExecutionPlan(skills=(skill,), tools=(), metadata={}))
    exc = _catch(lambda: ex.execute_current_skill())
    check(isinstance(exc, ExecutionSessionError), f"V14: non-running raises ExecutionSessionError; got {exc!r}")
    check(skill.calls == [], "V15: skill.execute() never called")


def scenario_current_skill_call_count() -> None:
    ex = _running(_Skill(result="unused"))
    calls = 0
    original = ex.current_skill

    def counting():
        nonlocal calls
        calls += 1
        return original()

    ex.current_skill = counting
    try:
        result = ex.execute_current_skill()
    finally:
        del ex.current_skill
    check(calls == 1, f"V16: current_skill() called exactly once; got {calls}")
    check(result == "unused", "V17: result still correct after instrumentation")


# === GROUP B: AST / namespace / import verification =========================
def scenario_ast_verification() -> None:
    src = textwrap.dedent(inspect.getsource(Executor.execute_current_skill))
    tree = ast.parse(src)
    fn = tree.body[0]
    check(fn.name == "execute_current_skill", "V18: method named correctly")
    check([a.arg for a in fn.args.args] == ["self"], "V19: takes no args beyond self")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", None))
        for c in calls
    }
    names.discard(None)
    check(names == {"current_skill", "execute"}, f"V20: only sanctioned calls; got {names}")
    check(sum(1 for c in calls if getattr(c.func, "attr", None) == "execute") == 1, "V21: exactly one .execute(...) call")
    check(sum(1 for c in calls if getattr(c.func, "attr", None) == "current_skill") == 1, "V22: exactly one .current_skill() call")

    forbidden = {
        "SkillContext", "ToolContext", "Runtime", "Workflow", "Planner",
        "invoke_current_skill", "current_tool_invocation", "resolve_current_tool",
        "logging", "logger", "cache", "retry",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), f"V23: no forbidden name (overlap {forbidden & referenced})")

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V24: no loop or try/except in the body")
    check(len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n is not fn]) == 0, "V25: no nested helper defined")

    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    check(len(returns) == 1, "V26: exactly one return statement")
    check(isinstance(returns[0].value, ast.Name) and returns[0].value.id == "result", "V27: returns local 'result' by name")

    exec_call = next(c for c in calls if getattr(c.func, "attr", None) == "execute")
    check(
        len(exec_call.args) == 1 and isinstance(exec_call.args[0], ast.Constant) and exec_call.args[0].value is None,
        "V28: skill.execute(None) called with the literal None",
    )


def scenario_module_imports_and_surface() -> None:
    module_tree = ast.parse((ROOT / "Orchestration" / "executor.py").read_text())
    from_modules = {n.module for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom)}
    forbidden_modules = {
        "Core.runtime", "Orchestration.workflow", "Orchestration.planner",
        "Orchestration.tool_registry", "Orchestration.tool_manager",
        "Orchestration.skill_registry", "Repository", "Core.composition_root",
    }
    check(forbidden_modules.isdisjoint(from_modules), f"V29: no forbidden module imported (overlap {forbidden_modules & from_modules})")

    public_methods = {n for n in dir(Executor) if not n.startswith("_") and callable(getattr(Executor, n, None))}
    expected = {
        "execute", "has_pending_tasks", "execute_plan", "prepare_session",
        "start_session", "advance_skill", "current_skill", "invoke_current_skill",
        "current_tool_invocation", "resolve_current_tool", "execute_current_tool",
        "execute_current_skill",
    }
    check(public_methods == expected, f"V30: public surface exactly as expected; got {public_methods}")
    check([p for p in inspect.signature(Executor.execute_current_skill).parameters if p != "self"] == [], "V31: no args beyond self")


def main() -> int:
    for scenario in [
        scenario_successful_execution,
        scenario_repeated_calls_no_caching,
        scenario_no_result_inspection,
        scenario_never_resolves_or_tags_tool,
        scenario_exception_propagates,
        scenario_missing_session_raises,
        scenario_non_running_session_raises,
        scenario_current_skill_call_count,
        scenario_ast_verification,
        scenario_module_imports_and_surface,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 9 SPRINT 101 EXECUTOR-EXECUTE-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())