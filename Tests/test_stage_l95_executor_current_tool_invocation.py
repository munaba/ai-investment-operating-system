"""Phase 8 Sprint 95 (REVISED): Executor.current_tool_invocation() now
builds a VALID ToolInvocation from skill._tool_names[0]. Boundary-only
-- no Tool resolved/executed, nothing cached. Reuses current_skill()
once, reads _tool_names once, raises ExecutorError if missing/empty.
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

# --- Fixtures ------------------------------------------------------------
class _Skill:
    """A skill stand-in that raises on any unexpected access, proving
    current_tool_invocation() never touches it beyond '_tool_names'."""

    def __init__(self, tool_names=None):
        if tool_names is not None:
            self._tool_names = tool_names

    def execute(self, *args, **kwargs):
        raise AssertionError("current_tool_invocation must never call skill.execute()")

    def __getattr__(self, item):
        if item in ("_tool_names", "_resolve_tool"):
            raise AttributeError(item)
        raise AssertionError(f"current_tool_invocation must never access skill.{item}")

class _GuardedToolResolver(ToolResolver):
    def __init__(self):
        pass  # deliberately skip ToolResolver.__init__

    def resolve(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("current_tool_invocation must never call ToolResolver.resolve()")

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

# --- V1-V8: valid construction, single tool name --------------------------
def scenario_single_tool_name() -> None:
    name = "price_tool"
    skill = _Skill(tool_names=(name,))
    executor = _running_executor(skill)

    result = executor.current_tool_invocation()
    check(isinstance(result, ToolInvocation), "V1: returns a real ToolInvocation instance")
    check(result.tool_name is name, "V2: tool_name preserved by identity")
    check(result.context is None, "V3: context == None")
    check(dict(result.metadata) == {}, "V4: metadata == {}")

    result2 = executor.current_tool_invocation()
    check(result2 is not result, "V5: a fresh ToolInvocation is constructed on each call")
    check(result2.tool_name is name, "V6: repeated calls preserve tool_name identity")
    check(hasattr(skill, "_tool_names"), "V7: _tool_names left untouched/present on the skill")
    check(skill._tool_names == (name,), "V8: _tool_names tuple itself is never mutated")

# --- V9-V12: multiple tool names -- first one wins ------------------------
def scenario_multiple_tool_names() -> None:
    first, second = "alpha_tool", "beta_tool"
    skill = _Skill(tool_names=(first, second))
    executor = _running_executor(skill)

    result = executor.current_tool_invocation()
    check(result.tool_name is first, "V9: first tool name used, not the second")
    check(result.tool_name is not second, "V10: second tool name never used")

    skill2 = _Skill(tool_names=[first, second])  # list instead of tuple
    executor2 = _running_executor(skill2)
    result2 = executor2.current_tool_invocation()
    check(result2.tool_name is first, "V11: works with a list of tool names too")
    check(len(skill2._tool_names) == 2, "V12: original tool_names collection length untouched")

# --- V13-V16: missing _tool_names raises ExecutorError --------------------
def scenario_missing_tool_names() -> None:
    skill = _Skill()  # no _tool_names set at all
    executor = _running_executor(skill)

    exc = _catch(lambda: executor.current_tool_invocation())
    check(isinstance(exc, ExecutorError), "V13: missing _tool_names raises ExecutorError")
    check(not isinstance(exc, ExecutionSessionError), "V14: not (mis-)raised as ExecutionSessionError")
    check(str(exc) != "", "V15: exception carries a non-empty message")
    check(not hasattr(skill, "_tool_names"), "V16: _tool_names still absent after the failed call")

# --- V17-V19: empty _tool_names raises ExecutorError ----------------------
def scenario_empty_tool_names() -> None:
    skill = _Skill(tool_names=())
    executor = _running_executor(skill)

    exc = _catch(lambda: executor.current_tool_invocation())
    check(isinstance(exc, ExecutorError), "V17: empty tuple _tool_names raises ExecutorError")

    skill2 = _Skill(tool_names=[])
    executor2 = _running_executor(skill2)
    exc2 = _catch(lambda: executor2.current_tool_invocation())
    check(isinstance(exc2, ExecutorError), "V18: empty list _tool_names raises ExecutorError")
    check(skill2._tool_names == [], "V19: empty _tool_names left untouched after failure")

# --- V20-V22: missing/wrong-state session propagation ---------------------
def scenario_session_propagation() -> None:
    executor = _make_executor()
    exc = _catch(lambda: executor.current_tool_invocation())
    check(isinstance(exc, ExecutorError), "V20: missing session raises ExecutorError")

    skill = _Skill(tool_names=("t",))
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor2 = _make_executor()
    executor2.execute_plan(plan)  # state == "pending", never started
    exc2 = _catch(lambda: executor2.current_tool_invocation())
    check(isinstance(exc2, ExecutionSessionError), "V21: non-running session raises ExecutionSessionError")
    check(not hasattr(executor2, "_tool_invocation"), "V22: no cache attribute created on failure")

# --- V23-V26: no cache / no mutation / no cursor movement -----------------
def scenario_no_cache_no_mutation() -> None:
    skill_a, skill_b = _Skill(tool_names=("a",)), _Skill(tool_names=("b",))
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()

    before = executor._current_plan
    executor.current_tool_invocation()
    check(executor._current_plan is before, "V23: self._current_plan is never replaced")
    check(executor._current_plan.current_skill_index == 0, "V24: skill cursor never advances")
    check(
        not hasattr(executor, "_tool_invocation") and not hasattr(executor, "_invocation"),
        "V25: no ToolInvocation cache attribute created on the Executor",
    )
    executor.current_tool_invocation()
    executor.current_tool_invocation()
    check(executor._current_plan.current_skill_index == 0, "V26: repeated calls still never advance the cursor")

# --- V27-V30: no tool resolution / no execution ---------------------------
def scenario_no_tool_resolution() -> None:
    skill = _Skill(tool_names=("t",))
    executor = _running_executor(skill, tool_resolver=_GuardedToolResolver())

    result = executor.current_tool_invocation()
    check(isinstance(result, ToolInvocation), "V27: succeeds even with a ToolResolver injected")
    check(not hasattr(skill, "_resolve_tool"), "V28: no _resolve_tool ever attached to the skill")
    check(result.tool_name == "t", "V29: tool_name is exactly _tool_names[0]")
    check(result.context is None, "V30: context still None with a ToolResolver present")

# --- V31-V36: AST verification of current_tool_invocation() ---------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.current_tool_invocation))
    tree = ast.parse(source)
    fn = tree.body[0]
    check(fn.name == "current_tool_invocation", "V31: method named 'current_tool_invocation'")
    params = [a.arg for a in fn.args.args]
    check(params == ["self"], f"V32: takes no arguments beyond self; got {params}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else (c.func.id if isinstance(c.func, ast.Name) else None))
        for c in calls
    }
    call_names.discard(None)
    check(
        call_names == {"current_skill", "hasattr", "len", "ExecutorError", "ToolInvocation"},
        f"V33: only sanctioned calls present; got {call_names}",
    )

    inv_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "ToolInvocation"]
    check(len(inv_calls) == 1, f"V34: exactly one ToolInvocation(...) call; got {len(inv_calls)}")
    kwargs = {kw.arg for kw in inv_calls[0].keywords}
    check(kwargs == {"tool_name", "context", "metadata"}, f"V35: kwargs exactly tool_name/context/metadata; got {kwargs}")

    forbidden = {
        "ToolResolver", "ToolRegistry", "ToolManager", "ToolContext",
        "Runtime", "Workflow", "Planner", "Registry", "Manager", "Service",
        "resolve", "execute", "cache", "_resolve_tool",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), f"V36: no forbidden name referenced (overlap {forbidden & referenced})")

def scenario_ast_reads_and_shape() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.current_tool_invocation))
    tree = ast.parse(source)
    fn = tree.body[0]
    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V37: no loop or try/except in the method body")

    tool_names_reads = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "_tool_names" and isinstance(n.ctx, ast.Load)
    ]
    check(len(tool_names_reads) == 1, f"V38: 'skill._tool_names' read exactly once; got {len(tool_names_reads)}")

    skill_call_count = sum(
        1 for c in ast.walk(tree)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "current_skill"
    )
    check(skill_call_count == 1, f"V39: current_skill() called exactly once; got {skill_call_count}")

    return_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    check(len(return_nodes) == 1, "V40: exactly one return statement")
    ret = return_nodes[0].value
    check(isinstance(ret, ast.Name) and ret.id == "invocation", "V41: return statement returns the local 'invocation' by name")
    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n is not fn]
    check(len(nested_funcs) == 0, "V42: no nested/local helper function defined")

# --- V43-V45: module-level import / namespace verification ----------------
def scenario_module_imports() -> None:
    module_tree = ast.parse((ROOT / "Orchestration" / "executor.py").read_text())
    from_modules = [n.module for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom)]
    check(
        from_modules.count("Orchestration.tool_invocation") == 1,
        f"V43: 'from Orchestration.tool_invocation import ...' appears exactly once; got {from_modules.count('Orchestration.tool_invocation')}",
    )
    tool_invocation_import = next(
        n for n in ast.walk(module_tree)
        if isinstance(n, ast.ImportFrom) and n.module == "Orchestration.tool_invocation"
    )
    imported_names = {a.name for a in tool_invocation_import.names}
    check(imported_names == {"ToolInvocation"}, f"V44: only 'ToolInvocation' imported; got {imported_names}")
    check("Orchestration.tool_resolver" in from_modules, "V45: pre-existing ToolResolver import untouched")
    forbidden_modules = {
        "Core.runtime", "Orchestration.workflow", "Orchestration.planner",
        "Orchestration.tool_registry", "Orchestration.tool_manager",
    }
    check(forbidden_modules.isdisjoint(set(from_modules)), f"V45b: no forbidden module imported (overlap {forbidden_modules & set(from_modules)})")

# --- V46-V47: public API surface ------------------------------------------
def scenario_public_surface() -> None:
    public_methods = {n for n in dir(Executor) if not n.startswith("_") and callable(getattr(Executor, n, None))}
    expected = {
        "execute", "has_pending_tasks", "execute_plan", "prepare_session",
        "start_session", "advance_skill", "current_skill",
        "invoke_current_skill", "current_tool_invocation",
    }
    check(public_methods == expected, f"V46: Executor's public callables exactly as expected; got {public_methods}")
    signature = inspect.signature(Executor.current_tool_invocation)
    params = [name for name in signature.parameters if name != "self"]
    check(params == [], "V47: current_tool_invocation() takes no arguments beyond self")

def main() -> int:
    for scenario in [
        scenario_single_tool_name,
        scenario_multiple_tool_names,
        scenario_missing_tool_names,
        scenario_empty_tool_names,
        scenario_session_propagation,
        scenario_no_cache_no_mutation,
        scenario_no_tool_resolution,
        scenario_ast_verification,
        scenario_ast_reads_and_shape,
        scenario_module_imports,
        scenario_public_surface,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 95 (REVISED) EXECUTOR-CURRENT-TOOL-INVOCATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())