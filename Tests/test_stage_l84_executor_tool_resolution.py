"""
Phase 8 Sprint 84 proof suite -- Skill Tool Resolution Boundary.

``Executor`` gains an optional ``tool_resolver: ToolResolver | None``
constructor parameter. ``Executor`` never resolves, looks up, or
executes a Tool itself -- it only stores the injected ``ToolResolver``
and, immediately before ``skill.execute(context)`` in
``invoke_current_skill()``, hands the Skill a one-argument local
callable (``skill._resolve_tool``) that forwards to
``tool_resolver.resolve(name)``. The callable is never invoked by
``Executor`` -- only the Skill may call it, and only after receiving
``context``. Compact, table-driven, no-pytest style (~60 invariants).
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Orchestration.executor as executor_module
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.execution_session import ExecutionSessionError
from Orchestration.executor import Executor, ExecutorError
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
from Orchestration.tool_registry import ToolRegistry, ToolRegistryError
from Orchestration.tool_resolver import ToolResolver, ToolResolverError

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


# --- Fixtures ---------------------------------------------------------------
class _Skill:
    """Records ``self._resolve_tool``/``self._tool_names`` at execute()
    time; if ``call_with`` is set, calls the injected resolver too."""

    def __init__(self, call_with=None):
        self.calls = 0
        self.resolve_tool_at_execute = "UNSET"
        self.tool_names_at_execute = "UNSET"
        self._call_with = call_with
        self.resolved_value = "UNSET"
        self.raised = None

    def execute(self, context):
        self.calls += 1
        self.resolve_tool_at_execute = getattr(self, "_resolve_tool", "MISSING")
        self.tool_names_at_execute = getattr(self, "_tool_names", "MISSING")
        if self._call_with is not None:
            try:
                self.resolved_value = self.resolve_tool_at_execute(self._call_with)
            except Exception as exc:  # noqa: BLE001 -- captured for assertion
                self.raised = exc
        return context


class _PermissiveContext:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _patched_skill_context:
    def __enter__(self):
        self._original = executor_module.SkillContext
        executor_module.SkillContext = _PermissiveContext
        return self

    def __exit__(self, exc_type, exc, tb):
        executor_module.SkillContext = self._original
        return False


class _RecordingResolver(ToolResolver):
    def __init__(self, registry):
        super().__init__(registry)
        self.calls: List[str] = []

    def resolve(self, tool_name):
        self.calls.append(tool_name)
        return super().resolve(tool_name)


class _RaisingResolver(ToolResolver):
    def __init__(self, exc):
        super().__init__(ToolRegistry())
        self.exc = exc
        self.calls = 0

    def resolve(self, tool_name):
        self.calls += 1
        raise self.exc


class _CustomError(Exception):
    pass


def _registry_with(name, tool):
    reg = ToolRegistry()
    reg.register(name, tool)
    return reg


def _make_executor(tool_resolver=None) -> Executor:
    return Executor(
        task_manager=TaskManager(TaskQueue()),
        host=AutonomousHost(),
        tool_resolver=tool_resolver,
    )


def _running_executor(skill, tools=(), tool_resolver=None) -> Executor:
    plan = SkillExecutionPlan(skills=(skill,), tools=tools, metadata={})
    executor = _make_executor(tool_resolver=tool_resolver)
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor


# --- V1-V6: constructor validation -------------------------------------------
def scenario_constructor_validation() -> None:
    resolver = ToolResolver(ToolRegistry())
    check(_make_executor(resolver)._tool_resolver is resolver, "V1: valid ToolResolver stored by identity")
    check(_make_executor(None)._tool_resolver is None, "V2: None tool_resolver stored as None")
    default = Executor(task_manager=TaskManager(TaskQueue()), host=AutonomousHost())
    check(default._tool_resolver is None, "V3: omitted tool_resolver defaults to None")

    for label, bad in [("string", "x"), ("int", 5), ("registry_itself", ToolRegistry()), ("dict", {})]:
        raised = False
        try:
            _make_executor(bad)
        except ExecutorError:
            raised = True
        check(raised, f"V4[{label}]: invalid tool_resolver={bad!r} raises ExecutorError")

    for label, kwargs in [
        ("task_manager_none", dict(task_manager=None, host=AutonomousHost())),
        ("host_none", dict(task_manager=TaskManager(TaskQueue()), host=None)),
        ("bad_skill_resolver", dict(task_manager=TaskManager(TaskQueue()), host=AutonomousHost(), skill_resolver="bad")),
    ]:
        raised = False
        try:
            Executor(**kwargs)
        except ExecutorError:
            raised = True
        check(raised, f"V5[{label}]: pre-existing constructor validation unaffected")

    params = list(inspect.signature(Executor.__init__).parameters)
    check(
        params == ["self", "task_manager", "host", "skill_resolver", "tool_resolver"],
        f"V6: constructor parameter order (task_manager, host, skill_resolver, tool_resolver); got {params}",
    )


# --- V7-V15: lifecycle gating + Sprint 83 parity -----------------------------
def scenario_lifecycle_and_parity() -> None:
    resolver = ToolResolver(ToolRegistry())
    executor = _make_executor(resolver)
    raised = False
    try:
        executor.invoke_current_skill()
    except ExecutorError:
        raised = True
    check(raised, "V7: missing session still raises ExecutorError with resolver present")

    skill = _Skill()
    pending = _make_executor(resolver)
    pending.execute_plan(SkillExecutionPlan(skills=(skill,), tools=("x",), metadata={}))
    raised = False
    try:
        pending.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V8: 'pending' session still raises ExecutionSessionError")
    check(skill.calls == 0, "V9: skill.execute() never called while pending")
    check(not hasattr(skill, "_resolve_tool"), "V10: _resolve_tool not set while pending")

    pending.prepare_session()
    raised = False
    try:
        pending.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V11: 'ready' session still raises ExecutionSessionError")

    running_skill = _Skill()
    running = _running_executor(running_skill, tools=("a", "b"), tool_resolver=resolver)
    with _patched_skill_context():
        running.invoke_current_skill()
    check(running_skill.tool_names_at_execute == ("a", "b"), "V12: Sprint 83 _tool_names injection unaffected")
    check(callable(running_skill.resolve_tool_at_execute), "V13: _resolve_tool present/callable when resolver injected")

    for label, tools in [("empty", ()), ("some", ("p", "q"))]:
        s = _Skill()
        e = _running_executor(s, tools=tools, tool_resolver=None)
        with _patched_skill_context():
            e.invoke_current_skill()
        check(s.resolve_tool_at_execute == "MISSING", f"V14[{label}]: no _resolve_tool when tool_resolver is None")
    check(True, "V15: no-resolver / with-resolver parity block complete")


# --- V16-V21: identity + laziness --------------------------------------------
def scenario_identity_and_laziness() -> None:
    resolver = _RecordingResolver(_registry_with("price", object()))
    skill = _Skill()
    executor = _running_executor(skill, tools=("price",), tool_resolver=resolver)
    check(executor._tool_resolver is resolver, "V16: stored resolver is the injected object, by identity")

    with _patched_skill_context():
        executor.invoke_current_skill()
    check(callable(skill.resolve_tool_at_execute), "V17: injected _resolve_tool is callable")
    check(skill.resolve_tool_at_execute.__name__ == "resolve_tool", "V18: injected callable named 'resolve_tool'")
    check(resolver.calls == [], "V19: ToolResolver.resolve() never called by Executor when Skill doesn't call it")

    with _patched_skill_context():
        executor.invoke_current_skill()
        executor.invoke_current_skill()
    check(resolver.calls == [], "V20: still zero resolve() calls after repeated invoke_current_skill()")

    quiet_resolver = _RecordingResolver(_registry_with("x", object()))
    quiet_executor = _make_executor(quiet_resolver)
    quiet_executor.execute_plan(SkillExecutionPlan(skills=(_Skill(),), tools=("x",), metadata={}))
    quiet_executor.prepare_session()
    quiet_executor.start_session()
    check(quiet_resolver.calls == [], "V21: constructing/preparing an Executor never calls resolve()")


# --- V22-V29: call shape + return propagation --------------------------------
def scenario_call_shape_and_propagation() -> None:
    sentinel = object()
    resolver = _RecordingResolver(_registry_with("price", sentinel))
    skill = _Skill(call_with="price")
    executor = _running_executor(skill, tools=("price",), tool_resolver=resolver)
    with _patched_skill_context():
        executor.invoke_current_skill()
    check(resolver.calls == ["price"], f"V22: exactly one resolve('price') call; got {resolver.calls}")
    check(skill.resolved_value is sentinel, "V23: resolve() return value propagated unchanged, by identity")
    check(skill.raised is None, "V24: no exception for a valid, registered name")

    resolver2 = _RecordingResolver(_registry_with("news", "news-tool"))
    skill2 = _Skill(call_with="news")
    executor2 = _running_executor(skill2, tools=("news",), tool_resolver=resolver2)
    with _patched_skill_context():
        executor2.invoke_current_skill()
    check(resolver2.calls == ["news"], "V25: independent executor/resolver pair -- exactly one call, correct name")
    check(skill2.resolved_value == "news-tool", "V26: second resolver's return value propagated correctly")

    with _patched_skill_context():
        executor.invoke_current_skill()
    check(resolver.calls == ["price", "price"], "V27: second invoke_current_skill() adds one more resolve() call")
    check(skill.calls == 2, "V28: skill.execute() called twice total")
    check(list(inspect.signature(_Skill.execute).parameters) == ["self", "context"], "V29: fixture execute() sig unaffected")


# --- V30-V34: exception propagation, unwrapped --------------------------------
def scenario_exception_propagation() -> None:
    table = [
        ("tool_resolver_error", ToolResolverError("bad name")),
        ("value_error", ValueError("boom")),
        ("custom", _CustomError("custom failure")),
    ]
    for label, exc in table:
        raising_resolver = _RaisingResolver(exc)
        skill = _Skill(call_with="whatever")
        executor = _running_executor(skill, tools=("whatever",), tool_resolver=raising_resolver)
        with _patched_skill_context():
            executor.invoke_current_skill()
        check(skill.raised is exc, f"V30[{label}]: resolver exception propagated unchanged, by identity")
        check(raising_resolver.calls == 1, f"V31[{label}]: resolve() called exactly once despite raising")

    real_resolver = ToolResolver(ToolRegistry())
    skill_missing = _Skill(call_with="missing")
    executor_missing = _running_executor(skill_missing, tools=("missing",), tool_resolver=real_resolver)
    with _patched_skill_context():
        executor_missing.invoke_current_skill()
    check(
        isinstance(skill_missing.raised, ToolRegistryError),
        "V32: unregistered name -> ToolRegistryError propagated from a real ToolResolver, not wrapped",
    )


# --- V33-V36: session/state/cursor/metadata untouched -------------------------
def scenario_session_unchanged() -> None:
    resolver = ToolResolver(_registry_with("t", object()))
    skill_a, skill_b = _Skill(), _Skill()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=("t",), metadata={"k": "v"})
    executor = _make_executor(resolver)
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()

    session_before = executor._current_plan
    with _patched_skill_context():
        executor.invoke_current_skill()
    check(executor._current_plan is session_before, "V33: session object identity unchanged")
    check(executor._current_plan.state == "running", "V34: state unchanged ('running')")
    check(executor._current_plan.current_skill_index == 0, "V35: cursor unchanged by invoke_current_skill()")
    check(executor._current_plan.plan.metadata == {"k": "v"}, "V36: plan metadata untouched")


# --- V37-V46: AST verification of __init__ and invoke_current_skill() ---------
def scenario_ast_verification() -> None:
    init_tree = ast.parse(textwrap.dedent(inspect.getsource(Executor.__init__)))
    forbidden = {"Runtime", "Workflow", "EventBus", "ToolManager", "ToolRegistry", "BaseTool"}
    referenced_init = {n.id for n in ast.walk(init_tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(init_tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced_init), "V37: __init__ references no forbidden Runtime/Workflow/ToolManager/ToolRegistry")
    check("ToolResolver" in referenced_init, "V38: __init__ references ToolResolver (isinstance check)")

    method_tree = ast.parse(textwrap.dedent(inspect.getsource(Executor.invoke_current_skill)))
    calls = [n for n in ast.walk(method_tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else c.func.id)
        for c in calls if isinstance(c.func, (ast.Attribute, ast.Name))
    }
    check(
        call_names == {"current_skill", "SkillContext", "ToolContext", "execute", "setattr", "resolve"},
        f"V39: only sanctioned calls present (got {call_names})",
    )
    check("resolve_tool" not in call_names, "V40: resolve_tool() itself is never called inside invoke_current_skill()")

    function_def = method_tree.body[0]
    inner_names = {f.name for f in ast.walk(method_tree) if isinstance(f, ast.FunctionDef) and f is not function_def}
    check(inner_names == {"tool_context_factory", "resolve_tool"}, f"V41: exactly two local function defs (got {inner_names})")

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(method_tree)
    )
    check(has_loop_or_try is False, "V42: no loop or try/except of any kind")

    forbidden_method = forbidden | {"ToolResolver", "Planner", "Service", "Repository", "Provider"}
    referenced_method = {n.id for n in ast.walk(method_tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(method_tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden_method.isdisjoint(referenced_method), "V43: invoke_current_skill() never names ToolResolver/Runtime/Workflow/etc")

    setattr_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "setattr"]
    check(len(setattr_calls) == 2, "V44: exactly two setattr(...) calls (tool_names, resolve_tool)")
    resolve_setattr = [c for c in setattr_calls if isinstance(c.args[1], ast.Constant) and c.args[1].value == "_resolve_tool"]
    check(len(resolve_setattr) == 1, "V45: one setattr(skill, '_resolve_tool', resolve_tool) call present")
    sa = resolve_setattr[0]
    check(
        isinstance(sa.args[0], ast.Name) and sa.args[0].id == "skill"
        and isinstance(sa.args[2], ast.Name) and sa.args[2].id == "resolve_tool",
        "V46: setattr(skill, '_resolve_tool', resolve_tool) called with exact expected arguments",
    )


# --- V47-V50: import verification ---------------------------------------------
def scenario_import_verification() -> None:
    tree = ast.parse((ROOT / "Orchestration" / "executor.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    expected = {
        "Core.exceptions", "Orchestration.autonomous_host", "Orchestration.execution_session",
        "Orchestration.skill_context", "Orchestration.skill_execution_plan", "Orchestration.skill_resolver",
        "Orchestration.task_manager", "Orchestration.tool_context", "Orchestration.tool_resolver", "__future__",
    }
    check(imported == expected, f"V47: exactly one new import (Orchestration.tool_resolver) added; got {imported}")
    check("Orchestration.tool_manager" not in imported, "V48: no ToolManager import")
    check("Orchestration.tool_registry" not in imported, "V49: no ToolRegistry import")
    check("Orchestration.event_bus" not in imported, "V50: no EventBus import")


# --- V51-V54: signature & pre-existing behavior spot checks --------------------
def scenario_signature_and_regressions() -> None:
    params = [p for p in inspect.signature(Executor.invoke_current_skill).parameters if p != "self"]
    check(params == [], "V51: invoke_current_skill() still takes no arguments beyond self")

    resolver = ToolResolver(_registry_with("t", object()))
    skill_a, skill_b = _Skill(), _Skill()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=("t",), metadata={})
    executor = _make_executor(resolver)
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    check(executor.current_skill() is skill_a, "V52: current_skill() unaffected, still returns by identity")
    with _patched_skill_context():
        executor.invoke_current_skill()
    executor.advance_skill()
    check(executor.current_skill() is skill_b, "V53: advance_skill() still works, unaffected by this sprint")
    check(executor.execute(context="ctx") == 0, "V54: execute() unaffected, still returns 0 on empty queue")


def main() -> int:
    for scenario in [
        scenario_constructor_validation,
        scenario_lifecycle_and_parity,
        scenario_identity_and_laziness,
        scenario_call_shape_and_propagation,
        scenario_exception_propagation,
        scenario_session_unchanged,
        scenario_ast_verification,
        scenario_import_verification,
        scenario_signature_and_regressions,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 84 EXECUTOR-TOOL-RESOLUTION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())