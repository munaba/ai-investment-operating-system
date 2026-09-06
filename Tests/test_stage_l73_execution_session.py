"""
Phase 6 Sprint 73 proof suite -- ``ExecutionSession`` (a new,
standalone immutable value object) and ``Executor.execute_plan``'s
single change: instead of storing a raw ``SkillExecutionPlan`` as
``self._current_plan``, it now wraps that plan in a pending
``ExecutionSession`` and stores the session by identity. Execution
remains completely disabled: this sprint only introduces one more
boundary layer between ``Executor`` and the concrete
``SkillExecutionPlan`` shape -- no Skill is executed, no Tool is
executed, and ``execute()``/``has_pending_tasks()``/the constructor
are all unchanged.

Scope: dedicated regression suite for the Sprint 73 addition only.
``SkillExecutionPlan`` (Sprint 71) and the general shape of
``Executor.execute_plan`` (Sprint 72) are unchanged by this sprint --
this suite does not re-verify their own internal behavior beyond
confirming Sprint 73 introduces no regression to them.

``ExecutionSession`` never executes a skill or a tool, is never wired
into ``Runtime``, ``Workflow``, or ``EventBus``, and never inspects
``plan.skills``/``plan.tools``/``plan.metadata`` (proven both by
direct behavioral tests -- using a plan whose fields raise on
access/iteration -- and by AST-level import inspection of both module
source files). ``Executor.execute_plan`` never inspects the
``ExecutionSession`` it just built beyond passing it straight to
``self._current_plan``.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l72_executor_skill_execution_plan`` and
``Tests.test_stage_l71_skill_execution_plan`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 40+):
    V1  -- construction: valid plan/state/metadata succeeds.
    V2  -- construction: plan is stored by identity (not copied).
    V3  -- construction: state is stored exactly as given.
    V4  -- construction: metadata is frozen into a MappingProxyType.
    V5  -- construction: metadata content matches what was given.
    V6  -- invalid plan: None raises ExecutionSessionError.
    V7  -- invalid plan: a plain dict raises ExecutionSessionError.
    V8  -- invalid plan: a str raises ExecutionSessionError.
    V9  -- invalid plan: a plain object() raises ExecutionSessionError.
    V10 -- invalid state: None raises ExecutionSessionError.
    V11 -- invalid state: "" (empty string) raises
           ExecutionSessionError.
    V12 -- invalid state: a non-str (int) raises
           ExecutionSessionError.
    V13 -- invalid metadata: a non-Mapping (list) raises
           ExecutionSessionError.
    V14 -- metadata isolation: mutating the original dict passed in
           after construction does not affect session.metadata.
    V15 -- metadata immutability: session.metadata itself rejects
           item assignment (MappingProxyType semantics).
    V16 -- frozen dataclass: assigning session.plan after
           construction raises (FrozenInstanceError/AttributeError).
    V17 -- frozen dataclass: assigning session.state after
           construction raises.
    V18 -- frozen dataclass: assigning session.metadata after
           construction raises.
    V19 -- hash: hash(session) == hash(id(session.plan)).
    V20 -- hash: two sessions sharing the same plan object share a
           hash even when state differs.
    V21 -- equality: two sessions built from the same plan object,
           same state, and equal metadata content compare equal.
    V22 -- equality: differing state makes two sessions unequal.
    V23 -- identity preservation: session.plan is the exact object
           passed in, not a rebuilt/copied SkillExecutionPlan.
    V24 -- metadata default: an empty dict is accepted and stored as
           an empty, frozen mapping.
    V25 -- no mutation of the given plan: plan.skills/plan.tools are
           bit-for-bit identical (by identity) before and after
           wrapping in an ExecutionSession.
    V26 -- executor: execute_plan stores an ExecutionSession (not a
           raw SkillExecutionPlan) as self._current_plan.
    V27 -- executor: self._current_plan.plan is the exact plan object
           passed to execute_plan (identity).
    V28 -- executor: self._current_plan.state == "pending".
    V29 -- executor: self._current_plan.metadata == {} (empty).
    V30 -- executor: overwrite -- a second execute_plan call replaces
           self._current_plan with a new ExecutionSession wrapping
           the new plan.
    V31 -- executor: invalid plan input still raises ExecutorError,
           unchanged from Sprint 72.
    V32 -- executor: self._current_plan is left unchanged after a
           failed execute_plan call (previous session preserved).
    V33 -- executor: return value of execute_plan is always None.
    V34 -- no execution: a plan whose skills raise on any attribute
           access/.execute()/call never triggers those.
    V35 -- no iteration: a plan whose skills/tools tuples raise on
           __iter__ are never iterated by execute_plan.
    V36 -- no read: a plan whose metadata raises on any read access
           is accepted without ever reading a key from it.
    V37 -- no Host call: execute_plan never calls
           AutonomousHost.start (guarded stub raises on any call).
    V38 -- no SkillResolver call: execute_plan never calls
           SkillResolver.resolve (guarded stub raises on any call).
    V39 -- no TaskManager call: execute_plan never calls any
           TaskManager method (guarded stub raises on any call).
    V40 -- namespace: Orchestration.execution_session module does
           not expose Runtime/Workflow/EventBus/Executor symbols.
    V41 -- AST import verification: Orchestration.execution_session
           imports only the expected modules, no forbidden import.
    V42 -- AST import verification: Orchestration.executor imports
           Orchestration.execution_session and introduces no
           forbidden import.
    V43 -- namespace verification: Orchestration.executor module
           still does not expose Runtime/Workflow/EventBus/
           ToolResolver/ToolManager/BaseSkill/BaseTool symbols.
    V44 -- public API verification: Executor exposes exactly
           execute/has_pending_tasks/execute_plan plus dunder
           __repr__ -- unchanged by this sprint.
    V45 -- public API verification: ExecutionSession exposes no
           public methods beyond the dataclass-generated ones (only
           __post_init__/__hash__ defined, no other callables).
    V46 -- multi-instance independence: two Executor instances each
           store their own ExecutionSession independently.
    V47 -- no singleton: two Executor() constructions with identical
           collaborators are distinct objects with independent
           _current_plan attributes.
    V48 -- no singleton: two ExecutionSession() constructions with
           value-equal arguments are distinct objects (`is not`).
    V49 -- exception type exactness: the only exception ever raised
           by ExecutionSession construction for bad input is
           ExecutionSessionError -- never a bare TypeError/ValueError
           leaking through.
    V50 -- pre-existing Executor behavior (execute/has_pending_tasks/
           constructor validation) is completely unaffected by this
           addition.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_host import AutonomousHost
from Orchestration.execution_session import ExecutionSession, ExecutionSessionError
from Orchestration.executor import Executor, ExecutorError
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
        raise AssertionError("execute_plan must never call SkillResolver.resolve()")


class _GuardedTaskManager(TaskManager):
    """A TaskManager subclass (so ``isinstance`` checks pass) that
    raises on any method call, proving ``execute_plan`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip TaskManager.__init__

    def has_tasks(self):  # type: ignore[override]
        raise AssertionError("execute_plan must never call TaskManager.has_tasks()")

    def next_task(self):  # type: ignore[override]
        raise AssertionError("execute_plan must never call TaskManager.next_task()")


class _RaisingTuple(tuple):
    """A tuple subclass that raises on iteration, proving a plan's
    skills/tools are never iterated when wrapped in an
    ExecutionSession."""

    def __iter__(self):
        raise AssertionError("execute_plan must never iterate this tuple")


class _RaisingMapping(dict):
    """A dict subclass that raises on any read access, proving a
    plan's metadata is never read when wrapped in an
    ExecutionSession."""

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
        raise AssertionError(f"execute_plan must never access skill.{item}")

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
# V1-V5 -- valid construction
# ---------------------------------------------------------------------------
def scenario_valid_construction() -> None:
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    session = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})

    check(isinstance(session, ExecutionSession), "V1: valid construction succeeds")
    check(session.plan is plan, "V2: plan is stored by identity")
    check(session.state == "pending", "V3: state is stored exactly as given")
    check(
        type(session.metadata).__name__ == "mappingproxy",
        "V4: metadata is frozen into a MappingProxyType",
    )
    check(dict(session.metadata) == {"k": "v"}, "V5: metadata content matches what was given")


# ---------------------------------------------------------------------------
# V6-V9 -- invalid plan
# ---------------------------------------------------------------------------
def scenario_invalid_plan() -> None:
    for value, label in [
        (None, "None"),
        ({"skills": (), "tools": (), "metadata": {}}, "dict"),
        ("not-a-plan", "str"),
        (object(), "object()"),
    ]:
        raised = False
        try:
            ExecutionSession(plan=value, state="pending", metadata={})
        except ExecutionSessionError:
            raised = True
        check(raised, f"V6-V9: invalid plan ({label}) raises ExecutionSessionError")


# ---------------------------------------------------------------------------
# V10-V12 -- invalid state
# ---------------------------------------------------------------------------
def scenario_invalid_state() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    for value, label in [(None, "None"), ("", "empty string"), (5, "int")]:
        raised = False
        try:
            ExecutionSession(plan=plan, state=value, metadata={})
        except ExecutionSessionError:
            raised = True
        check(raised, f"V10-V12: invalid state ({label}) raises ExecutionSessionError")


# ---------------------------------------------------------------------------
# V13 -- invalid metadata
# ---------------------------------------------------------------------------
def scenario_invalid_metadata() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    raised = False
    try:
        ExecutionSession(plan=plan, state="pending", metadata=["not", "a", "mapping"])
    except ExecutionSessionError:
        raised = True
    check(raised, "V13: invalid metadata (list) raises ExecutionSessionError")


# ---------------------------------------------------------------------------
# V14 -- metadata isolation from the original dict
# ---------------------------------------------------------------------------
def scenario_metadata_isolation() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = {"a": 1}
    session = ExecutionSession(plan=plan, state="pending", metadata=original)
    original["a"] = 999
    original["b"] = 2

    check(
        dict(session.metadata) == {"a": 1},
        "V14: mutating the original dict after construction does not affect session.metadata",
    )


# ---------------------------------------------------------------------------
# V15 -- metadata immutability
# ---------------------------------------------------------------------------
def scenario_metadata_immutability() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session = ExecutionSession(plan=plan, state="pending", metadata={"a": 1})

    raised = False
    try:
        session.metadata["a"] = 2  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "V15: session.metadata rejects item assignment")


# ---------------------------------------------------------------------------
# V16-V18 -- frozen dataclass field reassignment
# ---------------------------------------------------------------------------
def scenario_frozen_fields() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session = ExecutionSession(plan=plan, state="pending", metadata={})

    for field, value in [("plan", plan), ("state", "running"), ("metadata", {})]:
        raised = False
        try:
            setattr(session, field, value)
        except (FrozenInstanceError, AttributeError):
            raised = True
        check(raised, f"V16-V18: reassigning session.{field} raises")


# ---------------------------------------------------------------------------
# V19-V20 -- hash
# ---------------------------------------------------------------------------
def scenario_hash() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session_a = ExecutionSession(plan=plan, state="pending", metadata={})
    session_b = ExecutionSession(plan=plan, state="running", metadata={"x": 1})

    check(
        hash(session_a) == hash(id(plan)),
        "V19: hash(session) == hash(id(session.plan))",
    )
    check(
        hash(session_a) == hash(session_b),
        "V20: two sessions sharing the same plan object share a hash even when state differs",
    )


# ---------------------------------------------------------------------------
# V21-V22 -- equality
# ---------------------------------------------------------------------------
def scenario_equality() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session_a = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    session_c = ExecutionSession(plan=plan, state="running", metadata={"k": "v"})

    check(
        session_a == session_b,
        "V21: two sessions with the same plan/state/equal metadata compare equal",
    )
    check(session_a != session_c, "V22: differing state makes two sessions unequal")


# ---------------------------------------------------------------------------
# V23 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    plan = SkillExecutionPlan(skills=("s1",), tools=("t1",), metadata={})
    session = ExecutionSession(plan=plan, state="pending", metadata={})

    check(session.plan is plan, "V23: session.plan is the exact object passed in")
    check(
        isinstance(session.plan, SkillExecutionPlan) and session.plan.skills is plan.skills,
        "V23: session.plan is not a rebuilt/copied SkillExecutionPlan",
    )


# ---------------------------------------------------------------------------
# V24 -- empty metadata default
# ---------------------------------------------------------------------------
def scenario_empty_metadata() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session = ExecutionSession(plan=plan, state="pending", metadata={})

    check(dict(session.metadata) == {}, "V24: an empty dict is accepted and stored as an empty mapping")
    check(
        type(session.metadata).__name__ == "mappingproxy",
        "V24: the empty mapping is still frozen into a MappingProxyType",
    )


# ---------------------------------------------------------------------------
# V25 -- plan not mutated by wrapping
# ---------------------------------------------------------------------------
def scenario_plan_not_mutated() -> None:
    skills = ("s1", "s2")
    tools = ("t1",)
    plan = SkillExecutionPlan(skills=skills, tools=tools, metadata={})
    ExecutionSession(plan=plan, state="pending", metadata={})

    check(plan.skills is skills, "V25: plan.skills identity is unchanged after wrapping")
    check(plan.tools is tools, "V25: plan.tools identity is unchanged after wrapping")


# ---------------------------------------------------------------------------
# V26-V29 -- executor stores a pending ExecutionSession
# ---------------------------------------------------------------------------
def scenario_executor_stores_pending_session() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={"m": 1})
    executor.execute_plan(plan)

    session = executor._current_plan
    check(
        isinstance(session, ExecutionSession),
        "V26: execute_plan stores an ExecutionSession, not a raw SkillExecutionPlan",
    )
    check(session.plan is plan, "V27: self._current_plan.plan is the exact plan object passed in")
    check(session.state == "pending", 'V28: self._current_plan.state == "pending"')
    check(dict(session.metadata) == {}, "V29: self._current_plan.metadata == {} (empty)")


# ---------------------------------------------------------------------------
# V30 -- overwrite
# ---------------------------------------------------------------------------
def scenario_overwrite_current_session() -> None:
    executor = _make_executor()
    plan_a = SkillExecutionPlan(skills=("a",), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=("b",), tools=(), metadata={})

    executor.execute_plan(plan_a)
    first_session = executor._current_plan
    executor.execute_plan(plan_b)
    second_session = executor._current_plan

    check(
        first_session is not second_session,
        "V30: a second execute_plan call replaces self._current_plan with a new ExecutionSession",
    )
    check(second_session.plan is plan_b, "V30: the replaced session wraps the new plan")


# ---------------------------------------------------------------------------
# V31 -- invalid plan still raises ExecutorError
# ---------------------------------------------------------------------------
def scenario_invalid_plan_still_raises_executor_error() -> None:
    executor = _make_executor()
    for value in [None, {"skills": (), "tools": (), "metadata": {}}, "not-a-plan", object()]:
        raised = False
        try:
            executor.execute_plan(value)  # type: ignore[arg-type]
        except ExecutorError:
            raised = True
        check(raised, f"V31: execute_plan({value!r}) still raises ExecutorError")


# ---------------------------------------------------------------------------
# V32 -- current session unchanged on failure
# ---------------------------------------------------------------------------
def scenario_current_session_unchanged_on_failure() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    original_session = executor._current_plan

    raised = False
    try:
        executor.execute_plan("not-a-plan")  # type: ignore[arg-type]
    except ExecutorError:
        raised = True

    check(raised, "V32: the failing call itself raises ExecutorError")
    check(
        executor._current_plan is original_session,
        "V32: self._current_plan is unchanged after a failed execute_plan call",
    )


# ---------------------------------------------------------------------------
# V33 -- return value always None
# ---------------------------------------------------------------------------
def scenario_return_value_always_none() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    result = executor.execute_plan(plan)
    check(result is None, "V33: execute_plan always returns None on success")


# ---------------------------------------------------------------------------
# V34 -- no skill execution
# ---------------------------------------------------------------------------
def scenario_no_skill_execution() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(_GuardedSkill(),), tools=(), metadata={})
    executor.execute_plan(plan)
    check(True, "V34: execute_plan with a guarded skill in the plan raises nothing (skill never touched)")


# ---------------------------------------------------------------------------
# V35 -- no iteration
# ---------------------------------------------------------------------------
def scenario_no_iteration() -> None:
    executor = _make_executor()
    raising_skills = _RaisingTuple(("s",))
    raising_tools = _RaisingTuple(("t",))
    plan = SkillExecutionPlan(skills=raising_skills, tools=raising_tools, metadata={})
    executor.execute_plan(plan)
    check(True, "V35: execute_plan never iterates plan.skills or plan.tools")


# ---------------------------------------------------------------------------
# V36 -- no metadata read
# ---------------------------------------------------------------------------
def scenario_no_metadata_read() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    # SkillExecutionPlan's own __post_init__ already copies metadata at
    # construction time, so the raising mapping is swapped in afterwards
    # (bypassing the frozen dataclass the same sanctioned way __post_init__
    # itself does) to prove execute_plan never reads it post-construction.
    object.__setattr__(plan, "metadata", _RaisingMapping())
    executor.execute_plan(plan)
    check(True, "V36: execute_plan never reads a key from plan.metadata")


# ---------------------------------------------------------------------------
# V37-V39 -- no delegated calls
# ---------------------------------------------------------------------------
def scenario_no_delegated_calls() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    check(True, "V37: execute_plan never calls AutonomousHost.start()")
    check(True, "V38: execute_plan never calls SkillResolver.resolve()")
    check(True, "V39: execute_plan never calls any TaskManager method")


# ---------------------------------------------------------------------------
# V40 -- namespace of execution_session module
# ---------------------------------------------------------------------------
def scenario_execution_session_namespace() -> None:
    import Orchestration.execution_session as session_module

    forbidden = ["Runtime", "Workflow", "EventBus", "Executor", "AutonomousHost", "TaskManager"]
    for name in forbidden:
        check(
            not hasattr(session_module, name),
            f"V40: Orchestration.execution_session module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V41 -- AST import verification: execution_session.py
# ---------------------------------------------------------------------------
def scenario_ast_import_verification_execution_session() -> None:
    source_path = ROOT / "Orchestration" / "execution_session.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)

    expected_all_imports = {
        "__future__",
        "dataclasses",
        "types",
        "typing",
        "Core.exceptions",
        "Orchestration.skill_execution_plan",
    }
    check(
        imported_modules == expected_all_imports,
        f"V41: Orchestration.execution_session's full import set is exactly as expected (got {imported_modules})",
    )

    forbidden_modules = {
        "Orchestration.executor",
        "Orchestration.runtime",
        "Orchestration.workflow",
        "Orchestration.workflow_engine",
        "Orchestration.event_bus",
        "Orchestration.autonomous_host",
        "Orchestration.task_manager",
        "Orchestration.skill_resolver",
    }
    intersection = imported_modules & forbidden_modules
    check(
        not intersection,
        f"V41: Orchestration.execution_session introduces no forbidden import (found: {intersection})",
    )


# ---------------------------------------------------------------------------
# V42 -- AST import verification: executor.py
# ---------------------------------------------------------------------------
def scenario_ast_import_verification_executor() -> None:
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
        "Orchestration.execution_session" in imported_modules,
        "V42: Orchestration.executor imports Orchestration.execution_session",
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
        f"V42: Orchestration.executor introduces no forbidden import (found: {intersection})",
    )

    expected_all_imports = {
        "__future__",
        "Core.exceptions",
        "Orchestration.autonomous_host",
        "Orchestration.execution_session",
        "Orchestration.skill_execution_plan",
        "Orchestration.skill_resolver",
        "Orchestration.task_manager",
    }
    check(
        imported_modules == expected_all_imports,
        f"V42: Orchestration.executor's full import set is exactly as expected (got {imported_modules})",
    )


# ---------------------------------------------------------------------------
# V43 -- namespace verification: executor module
# ---------------------------------------------------------------------------
def scenario_executor_namespace_verification() -> None:
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
            f"V43: Orchestration.executor module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V44 -- public API verification: Executor
# ---------------------------------------------------------------------------
def scenario_executor_public_api_verification() -> None:
    expected_public_methods = {"execute", "has_pending_tasks", "execute_plan"}
    actual_public_methods = {
        name
        for name in vars(Executor)
        if not name.startswith("_") and callable(getattr(Executor, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V44: Executor exposes exactly the expected public methods (got {actual_public_methods})",
    )


# ---------------------------------------------------------------------------
# V45 -- public API verification: ExecutionSession
# ---------------------------------------------------------------------------
def scenario_execution_session_public_api_verification() -> None:
    actual_public_methods = {
        name
        for name in vars(ExecutionSession)
        if not name.startswith("_") and callable(getattr(ExecutionSession, name))
    }
    check(
        actual_public_methods == set(),
        f"V45: ExecutionSession exposes no public methods beyond dataclass fields (got {actual_public_methods})",
    )


# ---------------------------------------------------------------------------
# V46 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    executor_a = _make_executor()
    executor_b = _make_executor()

    plan_a = SkillExecutionPlan(skills=("a",), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=("b",), tools=(), metadata={})

    executor_a.execute_plan(plan_a)
    executor_b.execute_plan(plan_b)

    check(
        executor_a._current_plan.plan is plan_a,
        "V46: executor_a's session wraps only its own plan",
    )
    check(
        executor_b._current_plan.plan is plan_b,
        "V46: executor_b's session wraps only its own plan",
    )
    check(
        executor_a._current_plan is not executor_b._current_plan,
        "V46: the two executors' sessions are independent objects",
    )


# ---------------------------------------------------------------------------
# V47 -- no singleton: Executor
# ---------------------------------------------------------------------------
def scenario_no_executor_singleton() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor_a = Executor(task_manager=task_manager, host=host)
    executor_b = Executor(task_manager=task_manager, host=host)

    check(executor_a is not executor_b, "V47: two Executor() constructions are distinct objects")

    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor_a.execute_plan(plan)
    check(
        not hasattr(executor_b, "_current_plan"),
        "V47: executor_b's _current_plan is independent of executor_a's",
    )


# ---------------------------------------------------------------------------
# V48 -- no singleton: ExecutionSession
# ---------------------------------------------------------------------------
def scenario_no_execution_session_singleton() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session_a = ExecutionSession(plan=plan, state="pending", metadata={})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={})

    check(
        session_a is not session_b,
        "V48: two ExecutionSession() constructions with value-equal arguments are distinct objects",
    )
    check(session_a == session_b, "V48: those distinct objects are still value-equal")


# ---------------------------------------------------------------------------
# V49 -- exception type exactness
# ---------------------------------------------------------------------------
def scenario_exception_type_exactness() -> None:
    for kwargs in [
        {"plan": None, "state": "pending", "metadata": {}},
        {"plan": SkillExecutionPlan(skills=(), tools=(), metadata={}), "state": "", "metadata": {}},
        {"plan": SkillExecutionPlan(skills=(), tools=(), metadata={}), "state": "pending", "metadata": []},
    ]:
        raised_type = None
        try:
            ExecutionSession(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is ExecutionSessionError,
            f"V49: ExecutionSession({kwargs!r}) raises exactly ExecutionSessionError (got {raised_type})",
        )


# ---------------------------------------------------------------------------
# V50 -- pre-existing Executor behavior unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_behavior_unaffected() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host)

    check(
        executor.has_pending_tasks() is False,
        "V50: has_pending_tasks() still works and reports no pending tasks on an empty queue",
    )

    raised = False
    try:
        executor.execute(context=None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V50: execute(context=None) still raises ExecutorError, unaffected by this sprint")

    executed_count = executor.execute(context="ctx", iterations=1)
    check(executed_count == 0, "V50: execute() on an empty queue still returns 0, unaffected by this sprint")

    raised = False
    try:
        Executor(task_manager=None, host=host)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V50: Executor(task_manager=None) still raises ExecutorError, unaffected by this sprint")


def main() -> int:
    scenarios = [
        scenario_valid_construction,
        scenario_invalid_plan,
        scenario_invalid_state,
        scenario_invalid_metadata,
        scenario_metadata_isolation,
        scenario_metadata_immutability,
        scenario_frozen_fields,
        scenario_hash,
        scenario_equality,
        scenario_identity_preservation,
        scenario_empty_metadata,
        scenario_plan_not_mutated,
        scenario_executor_stores_pending_session,
        scenario_overwrite_current_session,
        scenario_invalid_plan_still_raises_executor_error,
        scenario_current_session_unchanged_on_failure,
        scenario_return_value_always_none,
        scenario_no_skill_execution,
        scenario_no_iteration,
        scenario_no_metadata_read,
        scenario_no_delegated_calls,
        scenario_execution_session_namespace,
        scenario_ast_import_verification_execution_session,
        scenario_ast_import_verification_executor,
        scenario_executor_namespace_verification,
        scenario_executor_public_api_verification,
        scenario_execution_session_public_api_verification,
        scenario_multi_instance_independence,
        scenario_no_executor_singleton,
        scenario_no_execution_session_singleton,
        scenario_exception_type_exactness,
        scenario_pre_existing_behavior_unaffected,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 6 SPRINT 73 EXECUTION-SESSION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())