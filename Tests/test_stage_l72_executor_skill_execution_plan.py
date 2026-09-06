"""
Phase 6 Sprint 72 proof suite -- ``Executor`` gains a single new
public method, ``execute_plan(plan)``, which accepts a
``SkillExecutionPlan``, validates its type, and stores it by identity
as ``self._current_plan``. Execution remains completely disabled:
this sprint only connects ``Executor`` to the ``SkillExecutionPlan``
value object introduced in Sprint 71 -- no Skill is executed, no Tool
is executed, and the constructor is unchanged.

Scope: dedicated regression suite for the Sprint 72 addition only.
``Executor.__init__``/``execute``/``has_pending_tasks``/``__repr__``
are all unchanged by this sprint -- this suite does not re-verify
their own internal behavior beyond confirming Sprint 72 introduces no
regression to them.

``Executor.execute_plan`` never iterates ``plan.skills`` or
``plan.tools``, never reads or inspects ``plan.metadata``, never
calls ``AutonomousHost``, ``TaskManager``, ``SkillResolver``,
``ToolResolver``, ``Runtime``, ``Workflow``, or ``EventBus``, and
never mutates or clones ``plan`` (proven both by direct behavioral
tests -- using a plan whose fields raise on access/iteration -- and
by AST-level import inspection of the module's own source file).
``Orchestration.executor`` adds exactly one new import for this
sprint: ``Orchestration.skill_execution_plan.SkillExecutionPlan``.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l71_skill_execution_plan`` and
``Tests.test_stage_l70_planner_tool_discovery`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 35+):
    V1  -- valid plan: execute_plan(plan) with a real
           SkillExecutionPlan succeeds and returns None.
    V2  -- valid plan: after a successful call, self._current_plan is
           exactly the given plan (identity, not a copy).
    V3  -- invalid plan: None raises ExecutorError.
    V4  -- invalid plan: a plain dict raises ExecutorError.
    V5  -- invalid plan: a plain object() raises ExecutorError.
    V6  -- invalid plan: a str raises ExecutorError.
    V7  -- invalid plan: an ExecutionPlan (a different, unrelated
           value object from Orchestration.planner) raises
           ExecutorError.
    V8  -- invalid plan: a bare dict shaped like a plan
           ({"skills": (), "tools": (), "metadata": {}}) still raises
           ExecutorError (no duck typing).
    V9  -- identity preservation: the exact object passed in is the
           one stored -- not a copy, not a new instance built from its
           fields.
    V10 -- overwrite current plan: a second successful call replaces
           self._current_plan with the new plan.
    V11 -- current_plan unchanged on failure: after one successful
           call, a subsequent invalid call leaves self._current_plan
           untouched (still the prior plan).
    V12 -- current_plan unchanged on failure: an invalid call before
           any successful call leaves self._current_plan absent
           (never set to a partial/garbage value).
    V13 -- return value: execute_plan always returns None on success.
    V14 -- no execution: a plan whose skills raise on any attribute
           access/.execute()/call never triggers those, proving
           execute_plan never touches skill objects.
    V15 -- no iteration: a plan whose skills/tools tuples raise on
           __iter__ never triggers iteration.
    V16 -- no iteration: a plan whose tools tuple raises on __iter__
           never triggers iteration (checked independently of V15).
    V17 -- metadata untouched: a plan whose metadata raises on any
           read access is accepted without ever reading a key from it.
    V18 -- no Runtime: Orchestration.executor's module namespace does
           not expose a Runtime symbol.
    V19 -- no Host call: execute_plan never calls AutonomousHost.start
           (the bound host is a guard stub that raises on any call).
    V20 -- no Workflow: Orchestration.executor's module namespace does
           not expose a Workflow symbol.
    V21 -- no EventBus: Orchestration.executor's module namespace does
           not expose an EventBus symbol.
    V22 -- no SkillResolver call: execute_plan never calls
           SkillResolver.resolve (the bound skill_resolver is a guard
           stub that raises on any call).
    V23 -- no ToolResolver: Orchestration.executor's module namespace
           does not expose a ToolResolver symbol.
    V24 -- no TaskManager call: execute_plan never calls any
           TaskManager method (bound task_manager is a guard stub).
    V25 -- no mutation: plan.skills/plan.tools/plan.metadata are
           bit-for-bit identical (by value and, for skills/tools, by
           identity) before and after the execute_plan call.
    V26 -- no cloning: a second call with the same plan object stores
           the exact same object again (`is`), never a rebuilt
           SkillExecutionPlan.
    V27 -- constructor unchanged: Executor's constructor signature and
           validation behavior are identical to before this sprint.
    V28 -- AST import verification: Orchestration.executor imports
           Orchestration.skill_execution_plan and introduces no
           forbidden import.
    V29 -- namespace verification: Orchestration.executor module does
           not expose Runtime/Host-construction-helpers/Workflow/
           EventBus/ToolResolver/SkillResolver-execution symbols
           beyond what already existed.
    V30 -- public API verification: Executor exposes exactly the
           expected public methods (execute, has_pending_tasks,
           execute_plan) plus dunder __repr__.
    V31 -- multi-instance independence: two Executor instances each
           store their own plan independently -- no shared/singleton
           state.
    V32 -- no singleton: two Executor() constructions with identical
           collaborators are distinct objects with independent
           _current_plan attributes.
    V33 -- no hidden cache: calling execute_plan repeatedly with
           value-equal-but-distinct plan objects always reflects the
           most recently given object, never a cached earlier one.
    V34 -- exception type exactness: the only exception ever raised
           by execute_plan for bad input is ExecutorError -- never a
           bare TypeError/ValueError leaking through.
    V35 -- pre-existing Executor behavior (execute/has_pending_tasks)
           is completely unaffected by this addition.
    V36 -- execute_plan never touches self._task_manager or self._host
           attributes at all (only reads/writes self._current_plan).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_host import AutonomousHost
from Orchestration.executor import Executor, ExecutorError
from Orchestration.planner import ExecutionPlan, Goal
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.skill_resolver import SkillResolver
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _GuardedHost(AutonomousHost):
    """An AutonomousHost subclass (so ``isinstance`` checks pass) that
    raises on any ``start``/``stop`` call, proving ``execute_plan``
    never delegates to it."""

    def start(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("execute_plan must never call AutonomousHost.start()")

    def stop(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("execute_plan must never call AutonomousHost.stop()")


class _GuardedSkillResolver(SkillResolver):
    """A SkillResolver subclass (so ``isinstance`` checks pass) that
    raises on any ``resolve`` call, proving ``execute_plan`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip SkillResolver.__init__

    def resolve(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError(
            "execute_plan must never call SkillResolver.resolve()"
        )


class _GuardedTaskManager(TaskManager):
    """A TaskManager subclass (so ``isinstance`` checks pass) that
    raises on any method call, proving ``execute_plan`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip TaskManager.__init__

    def has_tasks(self):  # type: ignore[override]
        raise AssertionError(
            "execute_plan must never call TaskManager.has_tasks()"
        )

    def next_task(self):  # type: ignore[override]
        raise AssertionError(
            "execute_plan must never call TaskManager.next_task()"
        )


class _RaisingTuple(tuple):
    """A tuple subclass that raises on iteration, proving a plan's
    skills/tools are never iterated by execute_plan."""

    def __iter__(self):
        raise AssertionError("execute_plan must never iterate this tuple")


class _RaisingMapping(dict):
    """A dict subclass that raises on any read access, proving a
    plan's metadata is never read by execute_plan."""

    def __getitem__(self, key):
        raise AssertionError("execute_plan must never read metadata items")

    def get(self, *args, **kwargs):
        raise AssertionError("execute_plan must never call metadata.get()")

    def __iter__(self):
        raise AssertionError("execute_plan must never iterate metadata")

    def keys(self):
        raise AssertionError("execute_plan must never call metadata.keys()")

    def items(self):
        raise AssertionError("execute_plan must never call metadata.items()")


class _GuardedSkill:
    """A skill stand-in that raises on any attribute access, method
    call, or invocation -- proving execute_plan never touches a
    resolved skill object."""

    def __getattr__(self, item):
        raise AssertionError(
            f"execute_plan must never access skill.{item}"
        )

    def execute(self, *args, **kwargs):
        raise AssertionError("execute_plan must never call skill.execute()")

    def __call__(self, *args, **kwargs):
        raise AssertionError("execute_plan must never call a skill object")


def _make_executor(host=None, skill_resolver=None, task_manager=None) -> Executor:
    task_manager = task_manager if task_manager is not None else TaskManager(TaskQueue())
    host = host if host is not None else AutonomousHost()
    if skill_resolver is not None:
        return Executor(task_manager=task_manager, host=host, skill_resolver=skill_resolver)
    return Executor(task_manager=task_manager, host=host)


def _make_guarded_executor() -> Executor:
    return Executor(
        task_manager=_GuardedTaskManager(),
        host=_GuardedHost(),
        skill_resolver=_GuardedSkillResolver(),
    )


# ---------------------------------------------------------------------------
# V1/V2 -- valid plan accepted and stored
# ---------------------------------------------------------------------------
def scenario_valid_plan_accepted() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("s1",), tools=("t1",), metadata={})

    result = executor.execute_plan(plan)

    check(result is None, "V1: execute_plan(plan) returns None on success")
    check(
        executor._current_plan is plan,
        "V2: self._current_plan is exactly the given plan after a successful call",
    )


# ---------------------------------------------------------------------------
# V3-V8 -- invalid plan rejected
# ---------------------------------------------------------------------------
def scenario_invalid_plan_none() -> None:
    executor = _make_executor()
    raised = False
    try:
        executor.execute_plan(None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V3: execute_plan(None) raises ExecutorError")


def scenario_invalid_plan_dict() -> None:
    executor = _make_executor()
    raised = False
    try:
        executor.execute_plan({"skills": (), "tools": (), "metadata": {}})  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V4: execute_plan(dict) raises ExecutorError")


def scenario_invalid_plan_object() -> None:
    executor = _make_executor()
    raised = False
    try:
        executor.execute_plan(object())  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V5: execute_plan(object()) raises ExecutorError")


def scenario_invalid_plan_str() -> None:
    executor = _make_executor()
    raised = False
    try:
        executor.execute_plan("not-a-plan")  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V6: execute_plan(str) raises ExecutorError")


def scenario_invalid_plan_execution_plan() -> None:
    executor = _make_executor()
    unrelated_plan = ExecutionPlan(goal=Goal(metadata={}), steps=())
    raised = False
    try:
        executor.execute_plan(unrelated_plan)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(
        raised,
        "V7: execute_plan(ExecutionPlan(...)) raises ExecutorError (unrelated value object rejected)",
    )


def scenario_invalid_plan_no_duck_typing() -> None:
    executor = _make_executor()

    class _FakePlan:
        skills = ()
        tools = ()
        metadata = {}

    raised = False
    try:
        executor.execute_plan(_FakePlan())  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(
        raised,
        "V8: a duck-typed fake plan (matching attribute shape only) still raises ExecutorError -- no duck typing",
    )


# ---------------------------------------------------------------------------
# V9 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("a", "b"), tools=("t",), metadata={"k": 1})

    executor.execute_plan(plan)

    check(
        executor._current_plan is plan,
        "V9: the exact plan object passed in is stored -- not a copy or rebuilt instance",
    )
    check(
        executor._current_plan.skills is plan.skills,
        "V9: stored plan's skills tuple is the same object as the original plan's skills",
    )


# ---------------------------------------------------------------------------
# V10 -- overwrite current plan
# ---------------------------------------------------------------------------
def scenario_overwrite_current_plan() -> None:
    executor = _make_executor()
    plan_a = SkillExecutionPlan(skills=("a",), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=("b",), tools=(), metadata={})

    executor.execute_plan(plan_a)
    check(executor._current_plan is plan_a, "V10: first call stores plan_a")

    executor.execute_plan(plan_b)
    check(executor._current_plan is plan_b, "V10: second call overwrites with plan_b")


# ---------------------------------------------------------------------------
# V11 -- current_plan unchanged on failure (after a prior success)
# ---------------------------------------------------------------------------
def scenario_current_plan_unchanged_on_failure_after_success() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("keep",), tools=(), metadata={})
    executor.execute_plan(plan)

    raised = False
    try:
        executor.execute_plan("garbage")  # type: ignore[arg-type]
    except ExecutorError:
        raised = True

    check(raised, "V11: the invalid follow-up call itself raises ExecutorError")
    check(
        executor._current_plan is plan,
        "V11: self._current_plan is unchanged (still the prior valid plan) after a failed call",
    )


# ---------------------------------------------------------------------------
# V12 -- current_plan unchanged on failure (no prior success)
# ---------------------------------------------------------------------------
def scenario_current_plan_absent_on_first_failure() -> None:
    executor = _make_executor()
    raised = False
    try:
        executor.execute_plan(123)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True

    check(raised, "V12: an invalid first-ever call raises ExecutorError")
    check(
        not hasattr(executor, "_current_plan"),
        "V12: self._current_plan is never set to a partial/garbage value when the first call fails",
    )


# ---------------------------------------------------------------------------
# V13 -- return value always None on success
# ---------------------------------------------------------------------------
def scenario_return_value_always_none() -> None:
    executor = _make_executor()
    plan_a = SkillExecutionPlan(skills=(), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=("x",), tools=("y",), metadata={"z": 1})

    check(executor.execute_plan(plan_a) is None, "V13: first call returns None")
    check(executor.execute_plan(plan_b) is None, "V13: second call also returns None")


# ---------------------------------------------------------------------------
# V14 -- no execution of skill objects
# ---------------------------------------------------------------------------
def scenario_no_skill_execution() -> None:
    executor = _make_executor()
    guarded_skill = _GuardedSkill()
    plan = SkillExecutionPlan(skills=(guarded_skill,), tools=(), metadata={})

    # If execute_plan ever accessed an attribute on, called, or
    # invoked the guarded skill, this call itself would raise.
    executor.execute_plan(plan)
    check(
        executor._current_plan is plan,
        "V14: execute_plan completes without ever touching a resolved skill object",
    )


# ---------------------------------------------------------------------------
# V15 -- no iteration of skills
# ---------------------------------------------------------------------------
def scenario_no_skills_iteration() -> None:
    executor = _make_executor()
    raising_skills = _RaisingTuple(("s1", "s2"))
    plan = SkillExecutionPlan(skills=raising_skills, tools=(), metadata={})

    executor.execute_plan(plan)
    check(
        executor._current_plan is plan,
        "V15: execute_plan completes without ever iterating plan.skills",
    )


# ---------------------------------------------------------------------------
# V16 -- no iteration of tools
# ---------------------------------------------------------------------------
def scenario_no_tools_iteration() -> None:
    executor = _make_executor()
    raising_tools = _RaisingTuple(("t1", "t2"))
    plan = SkillExecutionPlan(skills=(), tools=raising_tools, metadata={})

    executor.execute_plan(plan)
    check(
        executor._current_plan is plan,
        "V16: execute_plan completes without ever iterating plan.tools",
    )


# ---------------------------------------------------------------------------
# V17 -- metadata untouched
# ---------------------------------------------------------------------------
def scenario_metadata_untouched() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={"a": 1})

    # SkillExecutionPlan.__post_init__ itself does `dict(self.metadata)`
    # and wraps it in MappingProxyType -- that happens once, at plan
    # construction time, before execute_plan is ever involved. To
    # prove execute_plan performs zero *additional* reads of its own,
    # swap the already-frozen metadata for a raising stand-in after
    # construction (via object.__setattr__, the same sanctioned
    # mechanism the dataclass itself uses) and confirm execute_plan
    # still completes without touching it.
    raising_metadata = _RaisingMapping({"a": 1})
    object.__setattr__(plan, "metadata", raising_metadata)

    executor.execute_plan(plan)
    check(
        executor._current_plan is plan,
        "V17: execute_plan completes without ever reading a key from plan.metadata itself",
    )


# ---------------------------------------------------------------------------
# V18 -- no Runtime symbol
# ---------------------------------------------------------------------------
def scenario_no_runtime_symbol() -> None:
    import Orchestration.executor as executor_module

    check(
        not hasattr(executor_module, "Runtime"),
        "V18: Orchestration.executor module namespace does not expose 'Runtime'",
    )
    check(
        not hasattr(executor_module, "WorkflowRuntime"),
        "V18: Orchestration.executor module namespace does not expose 'WorkflowRuntime'",
    )


# ---------------------------------------------------------------------------
# V19 -- no Host call
# ---------------------------------------------------------------------------
def scenario_no_host_call() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})

    # _GuardedHost.start/stop raise AssertionError if ever called --
    # if execute_plan reached them, this call itself would raise.
    executor.execute_plan(plan)
    check(
        executor._current_plan is plan,
        "V19: execute_plan never calls AutonomousHost.start() or .stop()",
    )


# ---------------------------------------------------------------------------
# V20 -- no Workflow symbol
# ---------------------------------------------------------------------------
def scenario_no_workflow_symbol() -> None:
    import Orchestration.executor as executor_module

    check(
        not hasattr(executor_module, "Workflow"),
        "V20: Orchestration.executor module namespace does not expose 'Workflow'",
    )
    check(
        not hasattr(executor_module, "WorkflowEngine"),
        "V20: Orchestration.executor module namespace does not expose 'WorkflowEngine'",
    )


# ---------------------------------------------------------------------------
# V21 -- no EventBus symbol
# ---------------------------------------------------------------------------
def scenario_no_event_bus_symbol() -> None:
    import Orchestration.executor as executor_module

    check(
        not hasattr(executor_module, "EventBus"),
        "V21: Orchestration.executor module namespace does not expose 'EventBus'",
    )


# ---------------------------------------------------------------------------
# V22 -- no SkillResolver call
# ---------------------------------------------------------------------------
def scenario_no_skill_resolver_call() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})

    # _GuardedSkillResolver.resolve raises AssertionError if ever
    # called -- if execute_plan reached it, this call itself raises.
    executor.execute_plan(plan)
    check(
        executor._current_plan is plan,
        "V22: execute_plan never calls SkillResolver.resolve()",
    )


# ---------------------------------------------------------------------------
# V23 -- no ToolResolver symbol
# ---------------------------------------------------------------------------
def scenario_no_tool_resolver_symbol() -> None:
    import Orchestration.executor as executor_module

    check(
        not hasattr(executor_module, "ToolResolver"),
        "V23: Orchestration.executor module namespace does not expose 'ToolResolver'",
    )
    check(
        not hasattr(executor_module, "ToolManager"),
        "V23: Orchestration.executor module namespace does not expose 'ToolManager'",
    )


# ---------------------------------------------------------------------------
# V24 -- no TaskManager call
# ---------------------------------------------------------------------------
def scenario_no_task_manager_call() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})

    # _GuardedTaskManager.has_tasks/next_task raise AssertionError if
    # ever called -- if execute_plan reached either, this call itself
    # would raise.
    executor.execute_plan(plan)
    check(
        executor._current_plan is plan,
        "V24: execute_plan never calls TaskManager.has_tasks() or .next_task()",
    )


# ---------------------------------------------------------------------------
# V25 -- no mutation
# ---------------------------------------------------------------------------
def scenario_no_mutation() -> None:
    executor = _make_executor()
    skills = ("s1", "s2")
    tools = ("t1",)
    metadata = {"k": "v"}
    plan = SkillExecutionPlan(skills=skills, tools=tools, metadata=metadata)

    skills_before, tools_before, metadata_before = plan.skills, plan.tools, dict(plan.metadata)

    executor.execute_plan(plan)

    check(plan.skills is skills_before, "V25: plan.skills object identity unchanged after execute_plan")
    check(plan.tools is tools_before, "V25: plan.tools object identity unchanged after execute_plan")
    check(dict(plan.metadata) == metadata_before, "V25: plan.metadata contents unchanged after execute_plan")


# ---------------------------------------------------------------------------
# V26 -- no cloning
# ---------------------------------------------------------------------------
def scenario_no_cloning() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=(), metadata={})

    executor.execute_plan(plan)
    first_stored = executor._current_plan
    executor.execute_plan(plan)
    second_stored = executor._current_plan

    check(first_stored is plan, "V26: first stored reference is the exact given plan")
    check(second_stored is plan, "V26: second stored reference is still the exact same given plan (no rebuild)")
    check(first_stored is second_stored, "V26: repeated calls with the same object never clone it")


# ---------------------------------------------------------------------------
# V27 -- constructor unchanged
# ---------------------------------------------------------------------------
def scenario_constructor_unchanged() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()

    executor = Executor(task_manager=task_manager, host=host)
    check(isinstance(executor, Executor), "V27: Executor(task_manager, host) still constructs successfully")

    raised = False
    try:
        Executor(task_manager=None, host=host)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V27: Executor(task_manager=None, ...) still raises ExecutorError")

    raised = False
    try:
        Executor(task_manager=task_manager, host=None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V27: Executor(host=None) still raises ExecutorError")

    raised = False
    try:
        Executor(task_manager=task_manager, host=host, skill_resolver="not-a-resolver")  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V27: Executor(skill_resolver=<invalid>) still raises ExecutorError")


# ---------------------------------------------------------------------------
# V28 -- AST import verification
# ---------------------------------------------------------------------------
def scenario_ast_import_verification() -> None:
    source_path = ROOT / "Orchestration" / "executor.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)

    check(
        "Orchestration.skill_execution_plan" in imported_modules,
        "V28: Orchestration.executor imports Orchestration.skill_execution_plan",
    )

    forbidden_modules = {
        "Orchestration.tool_resolver",
        "Orchestration.tool_manager",
        "Orchestration.runtime",
        "Orchestration.workflow",
        "Orchestration.workflow_engine",
        "Orchestration.workflow_execution_coordinator",
        "Orchestration.workflow_runtime",
        "Orchestration.event_bus",
        "Orchestration.base_skill",
        "Orchestration.base_tool",
    }
    intersection = imported_modules & forbidden_modules
    check(
        not intersection,
        f"V28: Orchestration.executor introduces no forbidden import (found: {intersection})",
    )

    expected_all_imports = {
        "__future__",
        "Core.exceptions",
        "Orchestration.autonomous_host",
        "Orchestration.skill_execution_plan",
        "Orchestration.skill_resolver",
        "Orchestration.task_manager",
    }
    check(
        imported_modules == expected_all_imports,
        f"V28: Orchestration.executor's full import set is exactly as expected (got {imported_modules})",
    )


# ---------------------------------------------------------------------------
# V29 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_namespace_verification() -> None:
    import Orchestration.executor as executor_module

    forbidden = [
        "Runtime",
        "WorkflowRuntime",
        "Workflow",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "EventBus",
        "ToolResolver",
        "ToolManager",
        "BaseSkill",
        "BaseTool",
    ]
    for name in forbidden:
        check(
            not hasattr(executor_module, name),
            f"V29: Orchestration.executor module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V30 -- public API verification
# ---------------------------------------------------------------------------
def scenario_public_api_verification() -> None:
    expected_public_methods = {"execute", "has_pending_tasks", "execute_plan"}
    actual_public_methods = {
        name
        for name in vars(Executor)
        if not name.startswith("_") and callable(getattr(Executor, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V30: Executor exposes exactly the expected public methods (got {actual_public_methods})",
    )


# ---------------------------------------------------------------------------
# V31 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    executor_a = _make_executor()
    executor_b = _make_executor()

    plan_a = SkillExecutionPlan(skills=("a",), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=("b",), tools=(), metadata={})

    executor_a.execute_plan(plan_a)
    executor_b.execute_plan(plan_b)

    check(executor_a._current_plan is plan_a, "V31: executor_a holds only its own plan")
    check(executor_b._current_plan is plan_b, "V31: executor_b holds only its own plan")
    check(
        executor_a._current_plan is not executor_b._current_plan,
        "V31: the two executors' stored plans are independent objects",
    )


# ---------------------------------------------------------------------------
# V32 -- no singleton
# ---------------------------------------------------------------------------
def scenario_no_singleton() -> None:
    executor_a = _make_executor()
    executor_b = _make_executor()

    check(executor_a is not executor_b, "V32: two Executor() constructions are distinct objects")

    plan = SkillExecutionPlan(skills=("only-a",), tools=(), metadata={})
    executor_a.execute_plan(plan)

    check(
        not hasattr(executor_b, "_current_plan"),
        "V32: executor_b's _current_plan is untouched by executor_a's call -- no shared singleton state",
    )


# ---------------------------------------------------------------------------
# V33 -- no hidden cache
# ---------------------------------------------------------------------------
def scenario_no_hidden_cache() -> None:
    executor = _make_executor()
    plan_v1 = SkillExecutionPlan(skills=("v1",), tools=(), metadata={})
    plan_v2 = SkillExecutionPlan(skills=("v2",), tools=(), metadata={})

    executor.execute_plan(plan_v1)
    check(executor._current_plan.skills == ("v1",), "V33: first call reflects plan_v1")

    executor.execute_plan(plan_v2)
    check(
        executor._current_plan.skills == ("v2",),
        "V33: second call reflects plan_v2 -- no stale cached earlier plan",
    )
    check(executor._current_plan is plan_v2, "V33: stored plan is exactly plan_v2 by identity")


# ---------------------------------------------------------------------------
# V34 -- exception type exactness
# ---------------------------------------------------------------------------
def scenario_exception_type_exactness() -> None:
    executor = _make_executor()
    invalid_values = [None, {}, [], "x", 1, 1.5, object()]
    for value in invalid_values:
        raised_type = None
        try:
            executor.execute_plan(value)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is ExecutorError,
            f"V34: execute_plan({value!r}) raises exactly ExecutorError (got {raised_type})",
        )


# ---------------------------------------------------------------------------
# V35 -- pre-existing Executor behavior unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_behavior_unaffected() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host)

    check(
        executor.has_pending_tasks() is False,
        "V35: has_pending_tasks() still works and reports no pending tasks on an empty queue",
    )

    raised = False
    try:
        executor.execute(context=None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V35: execute(context=None) still raises ExecutorError, unaffected by this sprint")

    executed_count = executor.execute(context="ctx", iterations=1)
    check(executed_count == 0, "V35: execute() on an empty queue still returns 0, unaffected by this sprint")


# ---------------------------------------------------------------------------
# V36 -- execute_plan never touches _task_manager/_host attributes
# ---------------------------------------------------------------------------
def scenario_never_touches_other_collaborators() -> None:
    executor = _make_guarded_executor()
    original_task_manager = executor._task_manager
    original_host = executor._host
    original_skill_resolver = executor._skill_resolver

    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)

    check(
        executor._task_manager is original_task_manager,
        "V36: self._task_manager reference is unchanged after execute_plan",
    )
    check(
        executor._host is original_host,
        "V36: self._host reference is unchanged after execute_plan",
    )
    check(
        executor._skill_resolver is original_skill_resolver,
        "V36: self._skill_resolver reference is unchanged after execute_plan",
    )


def main() -> int:
    scenarios = [
        scenario_valid_plan_accepted,
        scenario_invalid_plan_none,
        scenario_invalid_plan_dict,
        scenario_invalid_plan_object,
        scenario_invalid_plan_str,
        scenario_invalid_plan_execution_plan,
        scenario_invalid_plan_no_duck_typing,
        scenario_identity_preservation,
        scenario_overwrite_current_plan,
        scenario_current_plan_unchanged_on_failure_after_success,
        scenario_current_plan_absent_on_first_failure,
        scenario_return_value_always_none,
        scenario_no_skill_execution,
        scenario_no_skills_iteration,
        scenario_no_tools_iteration,
        scenario_metadata_untouched,
        scenario_no_runtime_symbol,
        scenario_no_host_call,
        scenario_no_workflow_symbol,
        scenario_no_event_bus_symbol,
        scenario_no_skill_resolver_call,
        scenario_no_tool_resolver_symbol,
        scenario_no_task_manager_call,
        scenario_no_mutation,
        scenario_no_cloning,
        scenario_constructor_unchanged,
        scenario_ast_import_verification,
        scenario_namespace_verification,
        scenario_public_api_verification,
        scenario_multi_instance_independence,
        scenario_no_singleton,
        scenario_no_hidden_cache,
        scenario_exception_type_exactness,
        scenario_pre_existing_behavior_unaffected,
        scenario_never_touches_other_collaborators,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 6 SPRINT 72 EXECUTOR-SKILL-EXECUTION-PLAN RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())