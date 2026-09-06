"""
Phase 7 Sprint 80 proof suite -- ``Executor.invoke_current_skill()``
propagating the exact, unexamined object returned by
``skill.execute(context)`` (SkillResult Propagation). No Runtime,
Tool execution, Workflow, or EventBus is introduced by this sprint.

Compact, table-driven, no-pytest style (55+ invariants in ~300 LOC).
Reuses the Sprint 78/79 stand-in conventions but consolidates
duplicated setup into a handful of helpers and data tables.
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
from Orchestration.execution_session import ExecutionSession, ExecutionSessionError
from Orchestration.executor import Executor, ExecutorError
from Orchestration.skill_context import SkillContextError
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.skill_result import SkillResult
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
class _ReturningSkill:
    """Returns a fixed object from execute(); records call count."""

    def __init__(self, value):
        self.value = value
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        return self.value


class _RaisingSkill:
    """Raises a fixed exception instance from execute()."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class _GuardedResult:
    """Stand-in result object whose success/output/error/metadata
    attributes raise if ever read -- proving invoke_current_skill()
    never inspects the object it propagates."""

    @property
    def success(self):
        raise AssertionError("must never read result.success")

    @property
    def output(self):
        raise AssertionError("must never read result.output")

    @property
    def error(self):
        raise AssertionError("must never read result.error")

    @property
    def metadata(self):
        raise AssertionError("must never read result.metadata")


class _RaisingMapping(dict):
    def __getitem__(self, item):
        raise AssertionError("must never read metadata")

    def get(self, *args, **kwargs):
        raise AssertionError("must never read metadata via get()")


class _RaisingTuple(tuple):
    def __iter__(self):
        raise AssertionError("must never iterate")

    def __len__(self):
        raise AssertionError("must never call len()")


class _PermissiveContext:
    """Non-validating stand-in for SkillContext -- the real
    SkillContext (Sprint 52, unchanged) rejects task=None, so reaching
    skill.execute() at all requires patching the module-level name
    invoke_current_skill() actually calls. Same technique already
    used in the Sprint 79 suite."""

    def __init__(self, **kwargs):
        pass


class _patched_skill_context:
    def __enter__(self):
        self._original = executor_module.SkillContext
        executor_module.SkillContext = _PermissiveContext
        return self

    def __exit__(self, exc_type, exc, tb):
        executor_module.SkillContext = self._original
        return False


def _make_executor(cls=Executor) -> Executor:
    return cls(task_manager=TaskManager(TaskQueue()), host=AutonomousHost())


def _running_executor(skill, tools=(), cls=Executor) -> Executor:
    plan = SkillExecutionPlan(skills=(skill,), tools=tools, metadata={})
    executor = _make_executor(cls=cls)
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor


class _CustomError(Exception):
    pass


class _ArbitraryObject:
    pass


# ---------------------------------------------------------------------------
# V1-V3 -- lifecycle gating unaffected (missing/pending/ready)
# ---------------------------------------------------------------------------
def scenario_lifecycle_gating() -> None:
    executor = _make_executor()
    raised = False
    try:
        executor.invoke_current_skill()
    except ExecutorError:
        raised = True
    check(raised, "V1: missing session raises ExecutorError")

    skill = _ReturningSkill("x")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    pending_executor = _make_executor()
    pending_executor.execute_plan(plan)
    raised = False
    try:
        pending_executor.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V2: 'pending' session raises ExecutionSessionError, no execute() call")
    check(skill.calls == 0, "V2b: skill.execute() never called while pending")

    pending_executor.prepare_session()
    raised = False
    try:
        pending_executor.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V3: 'ready' session raises ExecutionSessionError, no execute() call")


# ---------------------------------------------------------------------------
# V4-V15 -- identity-preserving propagation across result types
# ---------------------------------------------------------------------------
def scenario_value_propagation_table() -> None:
    sentinel = _ArbitraryObject()
    skill_result = SkillResult(success=True, output="done", error=None, metadata={"k": "v"})
    guarded = _GuardedResult()
    values = [
        ("None", None),
        ("int", 0),
        ("int_nonzero", 7),
        ("float", 3.14),
        ("str_empty", ""),
        ("str", "hello"),
        ("tuple", (1, 2)),
        ("dict", {"a": 1}),
        ("arbitrary_object", sentinel),
        ("SkillResult", skill_result),
        ("guarded_opaque_object", guarded),
    ]
    for label, value in values:
        skill = _ReturningSkill(value)
        executor = _running_executor(skill)
        with _patched_skill_context():
            result = executor.invoke_current_skill()
        check(result is value, f"V4-15 [{label}]: invoke_current_skill() returns the exact object by identity")
        check(skill.calls == 1, f"V4-15 [{label}]: execute() called exactly once")


# ---------------------------------------------------------------------------
# V16 -- opaque object survives untouched (no attribute access anywhere)
# ---------------------------------------------------------------------------
def scenario_opaque_result_untouched() -> None:
    guarded = _GuardedResult()
    skill = _ReturningSkill(guarded)
    executor = _running_executor(skill)
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result is guarded, "V16: guarded result propagated by identity without raising")
    for attr in ("success", "output", "error", "metadata"):
        raised = False
        try:
            getattr(result, attr)
        except AssertionError:
            raised = True
        check(raised, f"V16b: result.{attr} still raises when explicitly accessed (guard is real, proving invoke_current_skill() never touched it)")


# ---------------------------------------------------------------------------
# V17-V22 -- exception propagation, unwrapped and unaltered
# ---------------------------------------------------------------------------
def scenario_exception_propagation_table() -> None:
    exceptions = [
        RuntimeError("boom"),
        ValueError("bad value"),
        SkillContextError("context invalid"),
        _CustomError("custom"),
    ]
    for exc in exceptions:
        skill = _RaisingSkill(exc)
        executor = _running_executor(skill)
        caught = None
        try:
            with _patched_skill_context():
                executor.invoke_current_skill()
        except Exception as e:  # noqa: BLE001
            caught = e
        check(caught is exc, f"V17-22 [{type(exc).__name__}]: exact exception instance propagates unchanged")
        check(skill.calls == 1, f"V17-22 [{type(exc).__name__}]: execute() was actually called once before raising")


# ---------------------------------------------------------------------------
# V23-V28 -- no mutation of session/cursor/state/metadata/tools
# ---------------------------------------------------------------------------
def scenario_no_mutation() -> None:
    tools = _RaisingTuple(("t",))
    skill_a, skill_b = _ReturningSkill("A"), _ReturningSkill("B")
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=tools, metadata={})
    guarded_session = ExecutionSession(plan=plan, state="pending", metadata=_RaisingMapping())
    guarded_session = guarded_session.with_state("ready").start()
    executor = _make_executor()
    executor._current_plan = guarded_session

    session_before = executor._current_plan
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result == "A", "V23: invoke_current_skill() succeeds with guarded metadata/tools untouched")
    check(executor._current_plan is session_before, "V24: session object identity unchanged")
    check(executor._current_plan.state == "running", "V25: state unchanged ('running')")
    check(executor._current_plan.current_skill_index == 0, "V26: cursor unchanged after one call")

    with _patched_skill_context():
        for _ in range(3):
            executor.invoke_current_skill()
    check(executor._current_plan.current_skill_index == 0, "V27: cursor still unchanged after several calls")
    check(skill_a.calls == 4 and skill_b.calls == 0, "V28: same skill invoked every time; no advance, no caching of stale results")


# ---------------------------------------------------------------------------
# V29 -- no caching across distinct calls (freshly returned value each time)
# ---------------------------------------------------------------------------
def scenario_no_caching() -> None:
    counter = {"n": 0}

    class _CountingSkill:
        def execute(self, *args, **kwargs):
            counter["n"] += 1
            return counter["n"]

    executor = _running_executor(_CountingSkill())
    with _patched_skill_context():
        r1 = executor.invoke_current_skill()
        r2 = executor.invoke_current_skill()
    check(r1 == 1 and r2 == 2 and r1 != r2, "V29: each call returns the freshly computed value, no caching of a prior result")


# ---------------------------------------------------------------------------
# V30-V31 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    val_x, val_y = _ArbitraryObject(), _ArbitraryObject()
    exec_1 = _running_executor(_ReturningSkill(val_x))
    exec_2 = _running_executor(_ReturningSkill(val_y))
    with _patched_skill_context():
        r1, r2 = exec_1.invoke_current_skill(), exec_2.invoke_current_skill()
    check(r1 is val_x and r2 is val_y, "V30: two Executors propagate their own skill's result independently")
    check(exec_1 is not exec_2, "V31: distinct Executor instances, no singleton")


# ---------------------------------------------------------------------------
# V32-V37 -- AST verification
# ---------------------------------------------------------------------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.invoke_current_skill))
    tree = ast.parse(source)

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    isinstance_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "isinstance"]
    check(isinstance_calls == [], "V32: no isinstance(...) call in invoke_current_skill()")

    result_attr_access = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "result"
    ]
    check(result_attr_access == [], "V33: no attribute access on the local 'result' variable")

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V34: no loop or try/except of any kind")

    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else c.func.id)
        for c in calls
        if isinstance(c.func, (ast.Attribute, ast.Name))
    }
    check(call_names == {"current_skill", "SkillContext", "execute"}, f"V35: only sanctioned calls present (got {call_names})")

    forbidden = {"Runtime", "Workflow", "ToolContext", "ToolResolver", "Planner", "EventBus", "ToolManager"}
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    check(forbidden.isdisjoint(referenced), "V36: no reference to Runtime/Workflow/ToolContext/ToolResolver/Planner/EventBus/ToolManager")

    function_def = tree.body[0]
    check(isinstance(function_def.body[-1], ast.Return), "V37: body ends with a bare return statement")


# ---------------------------------------------------------------------------
# V38 -- namespace/import verification (no new imports this sprint)
# ---------------------------------------------------------------------------
def scenario_import_verification() -> None:
    tree = ast.parse((ROOT / "Orchestration" / "executor.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    expected = {
        "Core.exceptions",
        "Orchestration.autonomous_host",
        "Orchestration.execution_session",
        "Orchestration.skill_context",
        "Orchestration.skill_execution_plan",
        "Orchestration.skill_resolver",
        "Orchestration.task_manager",
        "__future__",
    }
    check(imported == expected, f"V38: no new top-level import introduced this sprint (got {imported})")


# ---------------------------------------------------------------------------
# V39-V40 -- signature & pre-existing behavior spot checks
# ---------------------------------------------------------------------------
def scenario_signature_and_regressions() -> None:
    params = [p for p in inspect.signature(Executor.invoke_current_skill).parameters if p != "self"]
    check(params == [], "V39: invoke_current_skill() takes no arguments beyond self")

    skill_a, skill_b = _ReturningSkill("A"), _ReturningSkill("B")
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    check(executor.current_skill() is skill_a, "V40a: current_skill() unaffected, still returns by identity")
    with _patched_skill_context():
        executor.invoke_current_skill()
    executor.advance_skill()
    check(executor.current_skill() is skill_b, "V40b: advance_skill() still works, unaffected by this sprint")
    check(executor.has_pending_tasks() is False, "V40c: has_pending_tasks() unaffected")
    check(executor.execute(context="ctx") == 0, "V40d: execute() unaffected, still returns 0 on empty queue")


def main() -> int:
    for scenario in [
        scenario_lifecycle_gating,
        scenario_value_propagation_table,
        scenario_opaque_result_untouched,
        scenario_exception_propagation_table,
        scenario_no_mutation,
        scenario_no_caching,
        scenario_multi_instance_independence,
        scenario_ast_verification,
        scenario_import_verification,
        scenario_signature_and_regressions,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 7 SPRINT 80 EXECUTOR-SKILL-RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())