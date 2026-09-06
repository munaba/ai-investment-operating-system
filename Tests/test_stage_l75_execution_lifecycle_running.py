"""
Phase 7 Sprint 75 proof suite -- ``ExecutionSession.start()`` (a
single new public method on the existing frozen value object) and
``Executor.start_session()`` (a single new public method on
``Executor`` that advances the currently stored session from
``ready`` to ``running`` using it). Execution remains completely
disabled: this sprint only introduces a second controlled
state-transition primitive -- no Skill is executed, no Tool is
executed, and ``execute()``/``has_pending_tasks()``/
``execute_plan()``/``prepare_session()``/the constructor are all
unchanged.

Scope: dedicated regression suite for the Sprint 75 addition only.
``SkillExecutionPlan`` (Sprint 71), the general shape of
``Executor.execute_plan`` (Sprint 72), ``ExecutionSession``'s
existing fields/validation/hash (Sprint 73), and ``with_state``/
``prepare_session`` (Sprint 74) are unchanged by this sprint -- this
suite does not re-verify their own internal behavior beyond
confirming Sprint 75 introduces no regression to them.

``ExecutionSession.start`` never executes a skill or a tool, is
never wired into ``Runtime``, ``Workflow``, ``Host``, or ``EventBus``,
and never inspects ``plan.skills``/``plan.tools`` (proven both by
direct behavioral tests -- using a plan whose fields raise on
access/iteration -- and by AST-level import inspection of both module
source files). ``Executor.start_session`` never inspects the
``ExecutionSession`` beyond calling ``start()`` on it.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l74_execution_session_lifecycle`` and
``Tests.test_stage_l73_execution_session`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 40+):
    V1  -- start: returns a new ExecutionSession instance (not
           ``self``).
    V2  -- start: the returned instance's state equals "running".
    V3  -- start: ready -> running transition works end to end.
    V4  -- start: plan is preserved by identity (``is``) on the
           returned instance.
    V5  -- start: metadata is preserved by identity (``is``) on the
           returned instance -- not rewrapped or re-copied.
    V6  -- start: the original instance's state is unchanged after
           the call.
    V7  -- start: the original instance's plan is unchanged
           (identity) after the call.
    V8  -- start: the original instance's metadata is unchanged
           (identity) after the call.
    V9  -- start: the original instance and the returned instance are
           distinct objects (``is not``).
    V10 -- start: a "pending" session cannot start -- raises
           ExecutionSessionError.
    V11 -- start: a "running" session cannot start again -- raises
           ExecutionSessionError (invalid transition).
    V12 -- start: an arbitrary/unknown state ("done") cannot start --
           raises ExecutionSessionError (invalid transition).
    V13 -- start: on an invalid current state, no new instance is
           returned (the call raises before returning).
    V14 -- start: full lifecycle chain (pending -> ready -> running)
           works end to end via with_state then start.
    V15 -- start: the returned instance still satisfies
           ExecutionSession's own validation (plan/state/metadata all
           still valid).
    V16 -- start: the returned instance's metadata is still a
           MappingProxyType (frozen), not a plain dict.
    V17 -- start: the returned instance's hash equals hash(id(plan))
           -- same as the original, since plan identity is preserved.
    V18 -- start: two independent start() calls on two distinct
           "ready" sessions each produce a distinct instance (no
           caching/interning).
    V19 -- executor: start_session() with no prior execute_plan()
           call raises ExecutorError.
    V20 -- executor: start_session() with no prior execute_plan()
           call never creates a _current_plan attribute as a side
           effect of the failed call.
    V21 -- executor: start_session() after execute_plan() +
           prepare_session() succeeds and returns None.
    V22 -- executor: start_session() advances self._current_plan from
           state "ready" to state "running".
    V23 -- executor: start_session() preserves plan identity on
           self._current_plan.
    V24 -- executor: start_session() preserves metadata identity on
           self._current_plan.
    V25 -- executor: start_session() replaces self._current_plan with
           a new ExecutionSession object (not the same object, and
           not a mutation of the old one).
    V26 -- executor: start_session() called directly after
           execute_plan() (skipping prepare_session()) raises
           ExecutionSessionError, since the session is still
           "pending" -- and the exception propagates unchanged out of
           start_session().
    V27 -- executor: a failed start_session() call (skipped
           prepare_session step) leaves self._current_plan completely
           unchanged (still "pending").
    V28 -- executor: a fresh execute_plan() call after start_session()
           overwrites the running session with a brand-new pending
           one.
    V29 -- executor: start_session() never touches self._task_manager.
    V30 -- executor: start_session() never touches self._host.
    V31 -- executor: start_session() never touches
           self._skill_resolver.
    V32 -- no execution: a plan whose skills raise on any attribute
           access/.execute()/call is never touched by start_session.
    V33 -- no iteration: a plan whose skills/tools tuples raise on
           __iter__ are never iterated by start/start_session.
    V34 -- no delegated calls: start_session never calls
           AutonomousHost.start/SkillResolver.resolve/any TaskManager
           method (guarded stubs raise on any call).
    V35 -- AST import verification: Orchestration.execution_session
           introduces no new imports for this sprint (import set is
           unchanged from Sprint 74).
    V36 -- AST import verification: Orchestration.executor introduces
           no new imports for this sprint (import set is unchanged
           from Sprint 74).
    V37 -- namespace verification: Orchestration.execution_session
           module does not expose Runtime/Workflow/Host/EventBus/
           Executor symbols.
    V38 -- namespace verification: Orchestration.executor module does
           not expose Runtime/Workflow/EventBus/ToolResolver/
           ToolManager/BaseSkill/BaseTool symbols.
    V39 -- public API verification: ExecutionSession exposes exactly
           {"with_state", "start"} as its public methods.
    V40 -- public API verification: Executor exposes exactly
           {"execute", "has_pending_tasks", "execute_plan",
           "prepare_session", "start_session"} as its public methods.
    V41 -- multi-instance independence: two Executor instances each
           advance their own session to running independently.
    V42 -- no singleton: two Executor() constructions with identical
           collaborators are distinct objects with independent
           _current_plan attributes after start_session.
    V43 -- no singleton: two start() calls on two value-equal-but-
           distinct "ready" ExecutionSession instances produce two
           distinct result objects.
    V44 -- exception type exactness: the only exception ever raised
           by start() for an invalid current state is
           ExecutionSessionError.
    V45 -- pre-existing Executor/ExecutionSession behavior (execute,
           has_pending_tasks, execute_plan, prepare_session,
           with_state, construction/validation, hash, equality) is
           completely unaffected by this addition.
    V46 -- execute() itself is not modified: calling
           Executor.execute() still never touches _current_plan.
"""

from __future__ import annotations

import ast
import sys
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
    raises on any ``start``/``stop`` call, proving ``start_session``
    never delegates to it."""

    def start(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("start_session must never call AutonomousHost.start()")

    def stop(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("start_session must never call AutonomousHost.stop()")


class _GuardedSkillResolver(SkillResolver):
    """A SkillResolver subclass (so ``isinstance`` checks pass) that
    raises on any ``resolve`` call, proving ``start_session`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip SkillResolver.__init__

    def resolve(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("start_session must never call SkillResolver.resolve()")


class _GuardedTaskManager(TaskManager):
    """A TaskManager subclass (so ``isinstance`` checks pass) that
    raises on any method call, proving ``start_session`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip TaskManager.__init__

    def has_tasks(self):  # type: ignore[override]
        raise AssertionError("start_session must never call TaskManager.has_tasks()")

    def next_task(self):  # type: ignore[override]
        raise AssertionError("start_session must never call TaskManager.next_task()")


class _RaisingTuple(tuple):
    """A tuple subclass that raises on iteration, proving a plan's
    skills/tools are never iterated by start/start_session."""

    def __iter__(self):
        raise AssertionError("must never iterate this tuple")


class _GuardedSkill:
    """A skill stand-in that raises on any attribute access, method
    call, or invocation -- proving start_session never touches a
    resolved skill object."""

    def __getattr__(self, item):
        raise AssertionError(f"must never access skill.{item}")

    def execute(self, *args, **kwargs):
        raise AssertionError("must never call skill.execute()")

    def __call__(self, *args, **kwargs):
        raise AssertionError("must never call a skill object")


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


def _ready_session(plan=None, metadata=None) -> ExecutionSession:
    plan = plan if plan is not None else SkillExecutionPlan(skills=(), tools=(), metadata={})
    metadata = metadata if metadata is not None else {}
    pending = ExecutionSession(plan=plan, state="pending", metadata=metadata)
    return pending.with_state("ready")


# ---------------------------------------------------------------------------
# V1-V3 -- start basic transition
# ---------------------------------------------------------------------------
def scenario_start_basic_transition() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = _ready_session(plan=plan)
    updated = original.start()

    check(isinstance(updated, ExecutionSession), "V1: start returns a new ExecutionSession instance")
    check(updated is not original, "V1: the returned instance is not self")
    check(updated.state == "running", "V2: the returned instance's state equals 'running'")
    check(original.state == "ready" and updated.state == "running", "V3: ready -> running transition works end to end")


# ---------------------------------------------------------------------------
# V4-V5 -- identity preservation on the returned instance
# ---------------------------------------------------------------------------
def scenario_start_identity_preservation() -> None:
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    original = _ready_session(plan=plan, metadata={"k": "v"})
    updated = original.start()

    check(updated.plan is original.plan, "V4: plan is preserved by identity on the returned instance")
    check(updated.plan is plan, "V4: plan is preserved by identity to the original argument")
    check(updated.metadata is original.metadata, "V5: metadata is preserved by identity, not rewrapped/re-copied")


# ---------------------------------------------------------------------------
# V6-V9 -- original instance left unchanged
# ---------------------------------------------------------------------------
def scenario_start_original_unchanged() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = _ready_session(plan=plan, metadata={"a": 1})
    original_plan_ref = original.plan
    original_metadata_ref = original.metadata

    updated = original.start()

    check(original.state == "ready", "V6: the original instance's state is unchanged after the call")
    check(original.plan is original_plan_ref, "V7: the original instance's plan is unchanged (identity)")
    check(
        original.metadata is original_metadata_ref,
        "V8: the original instance's metadata is unchanged (identity)",
    )
    check(updated is not original, "V9: the original and returned instances are distinct objects")


# ---------------------------------------------------------------------------
# V10-V13 -- invalid current state
# ---------------------------------------------------------------------------
def scenario_start_invalid_current_state() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})

    pending = ExecutionSession(plan=plan, state="pending", metadata={})
    raised = False
    result = "UNSET"
    try:
        result = pending.start()
    except ExecutionSessionError:
        raised = True
    check(raised, "V10: a 'pending' session cannot start -- raises ExecutionSessionError")
    check(result == "UNSET", "V13: start() never returns a new instance when current state is invalid (pending)")

    running = _ready_session(plan=plan).start()
    raised = False
    result = "UNSET"
    try:
        result = running.start()
    except ExecutionSessionError:
        raised = True
    check(raised, "V11: a 'running' session cannot start again -- raises ExecutionSessionError")
    check(result == "UNSET", "V13: start() never returns a new instance when current state is invalid (running)")

    done = ExecutionSession(plan=plan, state="done", metadata={})
    raised = False
    result = "UNSET"
    try:
        result = done.start()
    except ExecutionSessionError:
        raised = True
    check(raised, "V12: an arbitrary state ('done') cannot start -- raises ExecutionSessionError")
    check(result == "UNSET", "V13: start() never returns a new instance when current state is invalid (done)")


# ---------------------------------------------------------------------------
# V14 -- full lifecycle chain
# ---------------------------------------------------------------------------
def scenario_full_lifecycle_chain() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    pending = ExecutionSession(plan=plan, state="pending", metadata={})
    ready = pending.with_state("ready")
    running = ready.start()

    check(
        pending.state == "pending" and ready.state == "ready" and running.state == "running",
        "V14: full lifecycle chain (pending -> ready -> running) works end to end",
    )
    check(
        len({id(pending), id(ready), id(running)}) == 3,
        "V14: each transition in the chain produces a distinct instance",
    )
    check(pending.plan is ready.plan is running.plan is plan, "V14: plan identity survives the whole chain")


# ---------------------------------------------------------------------------
# V15-V17 -- returned instance validity, freezing, and hash
# ---------------------------------------------------------------------------
def scenario_start_returned_instance_valid() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={"k": 1})
    original = _ready_session(plan=plan, metadata={"k": 1})
    updated = original.start()

    check(
        isinstance(updated.plan, SkillExecutionPlan)
        and isinstance(updated.state, str)
        and updated.state,
        "V15: the returned instance still satisfies ExecutionSession's own validation",
    )
    check(
        type(updated.metadata).__name__ == "mappingproxy",
        "V16: the returned instance's metadata is still a MappingProxyType",
    )
    check(
        hash(updated) == hash(id(plan)),
        "V17: the returned instance's hash equals hash(id(plan))",
    )


# ---------------------------------------------------------------------------
# V18 -- no caching/interning across independent calls
# ---------------------------------------------------------------------------
def scenario_start_no_caching() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original_a = _ready_session(plan=plan)
    original_b = _ready_session(plan=plan)
    updated_a = original_a.start()
    updated_b = original_b.start()

    check(
        updated_a is not updated_b,
        "V18: two independent start() calls on distinct sessions produce two distinct instances (no caching)",
    )
    check(updated_a == updated_b, "V18: those distinct instances are still value-equal")


# ---------------------------------------------------------------------------
# V19-V20 -- start_session without a prior session
# ---------------------------------------------------------------------------
def scenario_start_session_without_plan() -> None:
    executor = _make_executor()

    raised = False
    try:
        executor.start_session()
    except ExecutorError:
        raised = True

    check(raised, "V19: start_session() with no prior execute_plan() call raises ExecutorError")
    check(
        not hasattr(executor, "_current_plan"),
        "V20: the failed call never creates a _current_plan attribute as a side effect",
    )


# ---------------------------------------------------------------------------
# V21-V25 -- start_session advances an existing ready session
# ---------------------------------------------------------------------------
def scenario_start_session_advances_existing() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    ready_session = executor._current_plan

    result = executor.start_session()

    check(result is None, "V21: start_session() succeeds and returns None")
    running_session = executor._current_plan
    check(running_session.state == "running", 'V22: self._current_plan advances from "ready" to "running"')
    check(running_session.plan is plan, "V23: start_session preserves plan identity")
    check(
        running_session.metadata is ready_session.metadata,
        "V24: start_session preserves metadata identity",
    )
    check(
        running_session is not ready_session,
        "V25: start_session replaces _current_plan with a new ExecutionSession object",
    )
    check(ready_session.state == "ready", "V25: the prior ready session object itself is unmutated")


# ---------------------------------------------------------------------------
# V26-V27 -- start_session skipping prepare_session
# ---------------------------------------------------------------------------
def scenario_start_session_skipping_prepare() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    pending_session = executor._current_plan

    raised = False
    try:
        executor.start_session()
    except ExecutionSessionError:
        raised = True

    check(
        raised,
        "V26: start_session() right after execute_plan() (skipping prepare_session) raises "
        "ExecutionSessionError, which propagates unchanged",
    )
    check(
        executor._current_plan is pending_session,
        "V27: a failed start_session() call leaves self._current_plan completely unchanged",
    )
    check(executor._current_plan.state == "pending", "V27: the unchanged session is still 'pending'")


# ---------------------------------------------------------------------------
# V28 -- fresh execute_plan overwrites a running session
# ---------------------------------------------------------------------------
def scenario_execute_plan_overwrites_running_session() -> None:
    executor = _make_executor()
    plan_a = SkillExecutionPlan(skills=(), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=(), tools=(), metadata={})

    executor.execute_plan(plan_a)
    executor.prepare_session()
    executor.start_session()
    check(executor._current_plan.state == "running", "V28: session is running before the second execute_plan call")

    executor.execute_plan(plan_b)
    check(executor._current_plan.state == "pending", "V28: a fresh execute_plan() resets state back to pending")
    check(executor._current_plan.plan is plan_b, "V28: a fresh execute_plan() wraps the new plan")


# ---------------------------------------------------------------------------
# V29-V31 -- start_session never touches other collaborators
# ---------------------------------------------------------------------------
def scenario_start_session_never_touches_collaborators() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()

    original_task_manager = executor._task_manager
    original_host = executor._host
    original_skill_resolver = executor._skill_resolver

    executor.start_session()

    check(executor._task_manager is original_task_manager, "V29: start_session never touches self._task_manager")
    check(executor._host is original_host, "V30: start_session never touches self._host")
    check(
        executor._skill_resolver is original_skill_resolver,
        "V31: start_session never touches self._skill_resolver",
    )


# ---------------------------------------------------------------------------
# V32 -- no skill execution
# ---------------------------------------------------------------------------
def scenario_no_skill_execution() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(_GuardedSkill(),), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    check(True, "V32: start_session with a guarded skill in the plan raises nothing (skill never touched)")


# ---------------------------------------------------------------------------
# V33 -- no iteration
# ---------------------------------------------------------------------------
def scenario_no_iteration() -> None:
    executor = _make_executor()
    raising_skills = _RaisingTuple(("s",))
    raising_tools = _RaisingTuple(("t",))
    plan = SkillExecutionPlan(skills=raising_skills, tools=raising_tools, metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    check(True, "V33: start_session never iterates plan.skills or plan.tools")


# ---------------------------------------------------------------------------
# V34 -- no delegated calls
# ---------------------------------------------------------------------------
def scenario_no_delegated_calls() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    check(True, "V34: start_session never calls AutonomousHost.start()")
    check(True, "V34: start_session never calls SkillResolver.resolve()")
    check(True, "V34: start_session never calls any TaskManager method")


# ---------------------------------------------------------------------------
# V35-V36 -- AST import verification (no new imports this sprint)
# ---------------------------------------------------------------------------
def _imports_of(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
    return imported_modules


def scenario_ast_import_verification_execution_session() -> None:
    imported_modules = _imports_of(ROOT / "Orchestration" / "execution_session.py")
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
        f"V35: Orchestration.execution_session's import set is unchanged from Sprint 74 (got {imported_modules})",
    )


def scenario_ast_import_verification_executor() -> None:
    imported_modules = _imports_of(ROOT / "Orchestration" / "executor.py")
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
        f"V36: Orchestration.executor's import set is unchanged from Sprint 74 (got {imported_modules})",
    )


# ---------------------------------------------------------------------------
# V37-V38 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_execution_session_namespace() -> None:
    import Orchestration.execution_session as session_module

    forbidden = ["Runtime", "Workflow", "Host", "EventBus", "Executor"]
    for name in forbidden:
        check(
            not hasattr(session_module, name),
            f"V37: Orchestration.execution_session module namespace does not expose '{name}'",
        )


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
            f"V38: Orchestration.executor module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V39-V40 -- public API verification
# ---------------------------------------------------------------------------
def scenario_execution_session_public_api_verification() -> None:
    expected_public_methods = {"with_state", "start"}
    actual_public_methods = {
        name
        for name in vars(ExecutionSession)
        if not name.startswith("_") and callable(getattr(ExecutionSession, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V39: ExecutionSession exposes exactly {expected_public_methods} as its public methods "
        f"(got {actual_public_methods})",
    )


def scenario_executor_public_api_verification() -> None:
    expected_public_methods = {
        "execute",
        "has_pending_tasks",
        "execute_plan",
        "prepare_session",
        "start_session",
    }
    actual_public_methods = {
        name
        for name in vars(Executor)
        if not name.startswith("_") and callable(getattr(Executor, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V40: Executor exposes exactly the expected public methods (got {actual_public_methods})",
    )


# ---------------------------------------------------------------------------
# V41 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    executor_a = _make_executor()
    executor_b = _make_executor()

    plan_a = SkillExecutionPlan(skills=("a",), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=("b",), tools=(), metadata={})

    executor_a.execute_plan(plan_a)
    executor_b.execute_plan(plan_b)

    executor_a.prepare_session()
    executor_b.prepare_session()

    executor_a.start_session()

    check(executor_a._current_plan.state == "running", "V41: executor_a's session advanced to running")
    check(executor_b._current_plan.state == "ready", "V41: executor_b's session is untouched, still ready")
    check(executor_a._current_plan.plan is plan_a, "V41: executor_a's session wraps only its own plan")
    check(executor_b._current_plan.plan is plan_b, "V41: executor_b's session wraps only its own plan")


# ---------------------------------------------------------------------------
# V42 -- no singleton: Executor
# ---------------------------------------------------------------------------
def scenario_no_executor_singleton() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor_a = Executor(task_manager=task_manager, host=host)
    executor_b = Executor(task_manager=task_manager, host=host)

    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor_a.execute_plan(plan)
    executor_a.prepare_session()
    executor_a.start_session()

    check(executor_a is not executor_b, "V42: two Executor() constructions are distinct objects")
    check(
        not hasattr(executor_b, "_current_plan"),
        "V42: executor_b's _current_plan is independent of executor_a's after start_session",
    )


# ---------------------------------------------------------------------------
# V43 -- no singleton: start results
# ---------------------------------------------------------------------------
def scenario_no_start_singleton() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session_a = _ready_session(plan=plan)
    session_b = _ready_session(plan=plan)

    updated_a = session_a.start()
    updated_b = session_b.start()

    check(
        updated_a is not updated_b,
        "V43: start() calls on two distinct-but-equal 'ready' sessions produce two distinct result objects",
    )
    check(updated_a == updated_b, "V43: those distinct result objects are still value-equal")


# ---------------------------------------------------------------------------
# V44 -- exception type exactness
# ---------------------------------------------------------------------------
def scenario_exception_type_exactness() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})

    for state in ["pending", "running", "done", "unknown"]:
        session = ExecutionSession(plan=plan, state=state, metadata={})
        raised_type = None
        try:
            session.start()
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is ExecutionSessionError,
            f"V44: start() on state {state!r} raises exactly ExecutionSessionError (got {raised_type})",
        )


# ---------------------------------------------------------------------------
# V45 -- pre-existing behavior unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_behavior_unaffected() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host)

    check(
        executor.has_pending_tasks() is False,
        "V45: has_pending_tasks() still works and reports no pending tasks on an empty queue",
    )

    raised = False
    try:
        executor.execute(context=None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V45: execute(context=None) still raises ExecutorError, unaffected by this sprint")

    executed_count = executor.execute(context="ctx", iterations=1)
    check(executed_count == 0, "V45: execute() on an empty queue still returns 0, unaffected by this sprint")

    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    check(
        executor._current_plan.state == "pending",
        "V45: execute_plan() still stores a pending session, unaffected by this sprint",
    )

    executor.prepare_session()
    check(
        executor._current_plan.state == "ready",
        "V45: prepare_session() still advances pending -> ready, unaffected by this sprint",
    )

    session_a = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    check(session_a == session_b, "V45: ExecutionSession equality is unaffected by this sprint")
    check(hash(session_a) == hash(id(plan)), "V45: ExecutionSession hash is unaffected by this sprint")

    with_state_result = session_a.with_state("ready")
    check(
        with_state_result.state == "ready",
        "V45: ExecutionSession.with_state() is unaffected by this sprint",
    )

    raised = False
    try:
        ExecutionSession(plan="not-a-plan", state="pending", metadata={})  # type: ignore[arg-type]
    except ExecutionSessionError:
        raised = True
    check(raised, "V45: ExecutionSession construction validation is unaffected by this sprint")


# ---------------------------------------------------------------------------
# V46 -- execute() unmodified
# ---------------------------------------------------------------------------
def scenario_execute_unmodified() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()

    session_before = executor._current_plan
    executed_count = executor.execute(context="ctx", iterations=1)

    check(executed_count == 0, "V46: execute() on an empty task queue still returns 0")
    check(
        executor._current_plan is session_before,
        "V46: execute() never touches self._current_plan",
    )


def main() -> int:
    scenarios = [
        scenario_start_basic_transition,
        scenario_start_identity_preservation,
        scenario_start_original_unchanged,
        scenario_start_invalid_current_state,
        scenario_full_lifecycle_chain,
        scenario_start_returned_instance_valid,
        scenario_start_no_caching,
        scenario_start_session_without_plan,
        scenario_start_session_advances_existing,
        scenario_start_session_skipping_prepare,
        scenario_execute_plan_overwrites_running_session,
        scenario_start_session_never_touches_collaborators,
        scenario_no_skill_execution,
        scenario_no_iteration,
        scenario_no_delegated_calls,
        scenario_ast_import_verification_execution_session,
        scenario_ast_import_verification_executor,
        scenario_execution_session_namespace,
        scenario_executor_namespace_verification,
        scenario_execution_session_public_api_verification,
        scenario_executor_public_api_verification,
        scenario_multi_instance_independence,
        scenario_no_executor_singleton,
        scenario_no_start_singleton,
        scenario_exception_type_exactness,
        scenario_pre_existing_behavior_unaffected,
        scenario_execute_unmodified,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 7 SPRINT 75 EXECUTION-LIFECYCLE-RUNNING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())