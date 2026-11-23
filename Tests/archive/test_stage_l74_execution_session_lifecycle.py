"""
Phase 6 Sprint 74 proof suite -- ``ExecutionSession.with_state()`` (a
single new public method on the existing frozen value object) and
``Executor.prepare_session()`` (a single new public method on
``Executor`` that advances the currently stored session from
``pending`` to ``ready`` using it). Execution remains completely
disabled: this sprint only introduces a controlled state-transition
primitive -- no Skill is executed, no Tool is executed, and
``execute()``/``has_pending_tasks()``/``execute_plan()``/the
constructor are all unchanged.

Scope: dedicated regression suite for the Sprint 74 addition only.
``SkillExecutionPlan`` (Sprint 71), the general shape of
``Executor.execute_plan`` (Sprint 72), and ``ExecutionSession``'s
existing fields/validation/hash (Sprint 73) are unchanged by this
sprint -- this suite does not re-verify their own internal behavior
beyond confirming Sprint 74 introduces no regression to them.

``ExecutionSession.with_state`` never executes a skill or a tool, is
never wired into ``Runtime``, ``Workflow``, ``Host``, or ``EventBus``,
and never inspects ``plan.skills``/``plan.tools`` (proven both by
direct behavioral tests -- using a plan whose fields raise on
access/iteration -- and by AST-level import inspection of both module
source files). ``Executor.prepare_session`` never inspects the
``ExecutionSession`` beyond calling ``with_state("ready")`` on it.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l73_execution_session`` and
``Tests.test_stage_l72_executor_skill_execution_plan`` in
particular): a global pass/fail counter, plain fixtures, and a
``main()`` runner.

Invariant coverage (target 40+):
    V1  -- with_state: returns a new ExecutionSession instance (not
           ``self``).
    V2  -- with_state: the returned instance's state equals the given
           argument.
    V3  -- with_state: pending -> ready transition works end to end.
    V4  -- with_state: plan is preserved by identity (``is``) on the
           returned instance.
    V5  -- with_state: metadata is preserved by identity (``is``) on
           the returned instance -- not rewrapped or re-copied.
    V6  -- with_state: the original instance's state is unchanged
           after the call.
    V7  -- with_state: the original instance's plan is unchanged
           (identity) after the call.
    V8  -- with_state: the original instance's metadata is unchanged
           (identity) after the call.
    V9  -- with_state: the original instance and the returned
           instance are distinct objects (``is not``).
    V10 -- with_state: invalid state None raises ExecutionSessionError.
    V11 -- with_state: invalid state "" (empty string) raises
           ExecutionSessionError.
    V12 -- with_state: invalid state non-str (int) raises
           ExecutionSessionError.
    V13 -- with_state: on invalid state, no new instance is returned
           (the call raises before returning).
    V14 -- with_state: repeated transitions chain correctly
           (pending -> ready -> done), each producing a distinct
           instance.
    V15 -- with_state: the returned instance still satisfies
           ExecutionSession's own validation (plan/state/metadata all
           still valid).
    V16 -- with_state: the returned instance's metadata is still a
           MappingProxyType (frozen), not a plain dict.
    V17 -- with_state: the returned instance's hash equals
           hash(id(plan)) -- same as the original, since plan
           identity is preserved.
    V18 -- with_state: two independent with_state() calls on the same
           original session (same target state) produce two distinct
           instances (no caching/interning).
    V19 -- executor: prepare_session() with no prior execute_plan()
           call raises ExecutorError.
    V20 -- executor: prepare_session() with no prior execute_plan()
           call never creates a _current_plan attribute as a side
           effect of the failed call.
    V21 -- executor: prepare_session() after execute_plan() succeeds
           and returns None.
    V22 -- executor: prepare_session() advances self._current_plan
           from state "pending" to state "ready".
    V23 -- executor: prepare_session() preserves plan identity on
           self._current_plan.
    V24 -- executor: prepare_session() preserves metadata identity on
           self._current_plan.
    V25 -- executor: prepare_session() replaces self._current_plan
           with a new ExecutionSession object (not the same object,
           and not a mutation of the old one).
    V26 -- executor: calling prepare_session() twice in a row raises
           ExecutionSessionError-driven ExecutorError-free behavior --
           i.e. the second call's with_state("ready") still succeeds
           (idempotent re-application of the same state is allowed by
           with_state's own contract) and again returns None.
    V27 -- executor: after a second prepare_session() call, the
           session's plan identity is still preserved.
    V28 -- executor: a fresh execute_plan() call after prepare_session
           overwrites the ready session with a brand-new pending one.
    V29 -- executor: prepare_session() never touches self._task_manager.
    V30 -- executor: prepare_session() never touches self._host.
    V31 -- executor: prepare_session() never touches
           self._skill_resolver.
    V32 -- no execution: a plan whose skills raise on any attribute
           access/.execute()/call is never touched by prepare_session.
    V33 -- no iteration: a plan whose skills/tools tuples raise on
           __iter__ are never iterated by with_state/prepare_session.
    V34 -- no delegated calls: prepare_session never calls
           AutonomousHost.start/SkillResolver.resolve/any TaskManager
           method (guarded stubs raise on any call).
    V35 -- AST import verification: Orchestration.execution_session
           introduces no new imports for this sprint (import set is
           unchanged from Sprint 73).
    V36 -- AST import verification: Orchestration.executor introduces
           no new imports for this sprint (import set is unchanged
           from Sprint 73).
    V37 -- namespace verification: Orchestration.execution_session
           module does not expose Runtime/Workflow/Host/EventBus/
           Executor symbols.
    V38 -- namespace verification: Orchestration.executor module does
           not expose Runtime/Workflow/EventBus/ToolResolver/
           ToolManager/BaseSkill/BaseTool symbols.
    V39 -- public API verification: ExecutionSession exposes exactly
           {"with_state"} as its public methods.
    V40 -- public API verification: Executor exposes exactly
           {"execute", "has_pending_tasks", "execute_plan",
           "prepare_session"} as its public methods.
    V41 -- multi-instance independence: two Executor instances each
           advance their own session independently.
    V42 -- no singleton: two Executor() constructions with identical
           collaborators are distinct objects with independent
           _current_plan attributes after prepare_session.
    V43 -- no singleton: two with_state("ready") calls on two
           value-equal-but-distinct ExecutionSession instances produce
           two distinct result objects.
    V44 -- exception type exactness: the only exception ever raised
           by with_state for bad input is ExecutionSessionError.
    V45 -- pre-existing Executor/ExecutionSession behavior (execute,
           has_pending_tasks, execute_plan, construction/validation,
           hash, equality) is completely unaffected by this addition.
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
    raises on any ``start``/``stop`` call, proving ``prepare_session``
    never delegates to it."""

    def start(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("prepare_session must never call AutonomousHost.start()")

    def stop(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("prepare_session must never call AutonomousHost.stop()")


class _GuardedSkillResolver(SkillResolver):
    """A SkillResolver subclass (so ``isinstance`` checks pass) that
    raises on any ``resolve`` call, proving ``prepare_session`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip SkillResolver.__init__

    def resolve(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("prepare_session must never call SkillResolver.resolve()")


class _GuardedTaskManager(TaskManager):
    """A TaskManager subclass (so ``isinstance`` checks pass) that
    raises on any method call, proving ``prepare_session`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip TaskManager.__init__

    def has_tasks(self):  # type: ignore[override]
        raise AssertionError("prepare_session must never call TaskManager.has_tasks()")

    def next_task(self):  # type: ignore[override]
        raise AssertionError("prepare_session must never call TaskManager.next_task()")


class _RaisingTuple(tuple):
    """A tuple subclass that raises on iteration, proving a plan's
    skills/tools are never iterated by with_state/prepare_session."""

    def __iter__(self):
        raise AssertionError("must never iterate this tuple")


class _GuardedSkill:
    """A skill stand-in that raises on any attribute access, method
    call, or invocation -- proving prepare_session never touches a
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


# ---------------------------------------------------------------------------
# V1-V3 -- with_state basic transition
# ---------------------------------------------------------------------------
def scenario_with_state_basic_transition() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = ExecutionSession(plan=plan, state="pending", metadata={})
    updated = original.with_state("ready")

    check(isinstance(updated, ExecutionSession), "V1: with_state returns a new ExecutionSession instance")
    check(updated is not original, "V1: the returned instance is not self")
    check(updated.state == "ready", "V2: the returned instance's state equals the given argument")
    check(original.state == "pending" and updated.state == "ready", "V3: pending -> ready transition works end to end")


# ---------------------------------------------------------------------------
# V4-V5 -- identity preservation on the returned instance
# ---------------------------------------------------------------------------
def scenario_with_state_identity_preservation() -> None:
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    original = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    updated = original.with_state("ready")

    check(updated.plan is original.plan, "V4: plan is preserved by identity on the returned instance")
    check(updated.plan is plan, "V4: plan is preserved by identity to the original argument")
    check(updated.metadata is original.metadata, "V5: metadata is preserved by identity, not rewrapped/re-copied")


# ---------------------------------------------------------------------------
# V6-V9 -- original instance left unchanged
# ---------------------------------------------------------------------------
def scenario_with_state_original_unchanged() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = ExecutionSession(plan=plan, state="pending", metadata={"a": 1})
    original_plan_ref = original.plan
    original_metadata_ref = original.metadata

    updated = original.with_state("ready")

    check(original.state == "pending", "V6: the original instance's state is unchanged after the call")
    check(original.plan is original_plan_ref, "V7: the original instance's plan is unchanged (identity)")
    check(
        original.metadata is original_metadata_ref,
        "V8: the original instance's metadata is unchanged (identity)",
    )
    check(updated is not original, "V9: the original and returned instances are distinct objects")


# ---------------------------------------------------------------------------
# V10-V13 -- invalid state
# ---------------------------------------------------------------------------
def scenario_with_state_invalid_state() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = ExecutionSession(plan=plan, state="pending", metadata={})

    for value, label in [(None, "None"), ("", "empty string"), (5, "int")]:
        raised = False
        result = "UNSET"
        try:
            result = original.with_state(value)  # type: ignore[arg-type]
        except ExecutionSessionError:
            raised = True
        check(raised, f"V10-V12: with_state({label}) raises ExecutionSessionError")
        check(result == "UNSET", f"V13: with_state({label}) never returns a new instance on failure")


# ---------------------------------------------------------------------------
# V14 -- chained transitions
# ---------------------------------------------------------------------------
def scenario_with_state_chained_transitions() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    pending = ExecutionSession(plan=plan, state="pending", metadata={})
    ready = pending.with_state("ready")
    done = ready.with_state("done")

    check(
        pending.state == "pending" and ready.state == "ready" and done.state == "done",
        "V14: repeated transitions chain correctly (pending -> ready -> done)",
    )
    check(
        len({id(pending), id(ready), id(done)}) == 3,
        "V14: each transition in the chain produces a distinct instance",
    )
    check(pending.plan is ready.plan is done.plan is plan, "V14: plan identity survives the whole chain")


# ---------------------------------------------------------------------------
# V15-V17 -- returned instance validity, freezing, and hash
# ---------------------------------------------------------------------------
def scenario_with_state_returned_instance_valid() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={"k": 1})
    original = ExecutionSession(plan=plan, state="pending", metadata={"k": 1})
    updated = original.with_state("ready")

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
def scenario_with_state_no_caching() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = ExecutionSession(plan=plan, state="pending", metadata={})
    updated_a = original.with_state("ready")
    updated_b = original.with_state("ready")

    check(
        updated_a is not updated_b,
        "V18: two independent with_state() calls produce two distinct instances (no caching)",
    )
    check(updated_a == updated_b, "V18: those distinct instances are still value-equal")


# ---------------------------------------------------------------------------
# V19-V20 -- prepare_session without a prior session
# ---------------------------------------------------------------------------
def scenario_prepare_session_without_plan() -> None:
    executor = _make_executor()

    raised = False
    try:
        executor.prepare_session()
    except ExecutorError:
        raised = True

    check(raised, "V19: prepare_session() with no prior execute_plan() call raises ExecutorError")
    check(
        not hasattr(executor, "_current_plan"),
        "V20: the failed call never creates a _current_plan attribute as a side effect",
    )


# ---------------------------------------------------------------------------
# V21-V25 -- prepare_session advances an existing session
# ---------------------------------------------------------------------------
def scenario_prepare_session_advances_existing() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    pending_session = executor._current_plan

    result = executor.prepare_session()

    check(result is None, "V21: prepare_session() succeeds and returns None")
    ready_session = executor._current_plan
    check(ready_session.state == "ready", 'V22: self._current_plan advances from "pending" to "ready"')
    check(ready_session.plan is plan, "V23: prepare_session preserves plan identity")
    check(
        ready_session.metadata is pending_session.metadata,
        "V24: prepare_session preserves metadata identity",
    )
    check(
        ready_session is not pending_session,
        "V25: prepare_session replaces _current_plan with a new ExecutionSession object",
    )
    check(pending_session.state == "pending", "V25: the prior pending session object itself is unmutated")


# ---------------------------------------------------------------------------
# V26-V27 -- calling prepare_session twice
# ---------------------------------------------------------------------------
def scenario_prepare_session_called_twice() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)

    executor.prepare_session()
    first_ready = executor._current_plan
    result = executor.prepare_session()
    second_ready = executor._current_plan

    check(result is None, "V26: calling prepare_session() a second time still succeeds and returns None")
    check(second_ready.state == "ready", "V26: the session remains in state 'ready' after the second call")
    check(second_ready.plan is plan, "V27: plan identity is still preserved after a second prepare_session call")
    check(second_ready is not first_ready, "V27: the second call still produces a new ExecutionSession object")


# ---------------------------------------------------------------------------
# V28 -- fresh execute_plan overwrites a ready session
# ---------------------------------------------------------------------------
def scenario_execute_plan_overwrites_ready_session() -> None:
    executor = _make_executor()
    plan_a = SkillExecutionPlan(skills=(), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=(), tools=(), metadata={})

    executor.execute_plan(plan_a)
    executor.prepare_session()
    check(executor._current_plan.state == "ready", "V28: session is ready before the second execute_plan call")

    executor.execute_plan(plan_b)
    check(executor._current_plan.state == "pending", "V28: a fresh execute_plan() resets state back to pending")
    check(executor._current_plan.plan is plan_b, "V28: a fresh execute_plan() wraps the new plan")


# ---------------------------------------------------------------------------
# V29-V31 -- prepare_session never touches other collaborators
# ---------------------------------------------------------------------------
def scenario_prepare_session_never_touches_collaborators() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)

    original_task_manager = executor._task_manager
    original_host = executor._host
    original_skill_resolver = executor._skill_resolver

    executor.prepare_session()

    check(executor._task_manager is original_task_manager, "V29: prepare_session never touches self._task_manager")
    check(executor._host is original_host, "V30: prepare_session never touches self._host")
    check(
        executor._skill_resolver is original_skill_resolver,
        "V31: prepare_session never touches self._skill_resolver",
    )


# ---------------------------------------------------------------------------
# V32 -- no skill execution
# ---------------------------------------------------------------------------
def scenario_no_skill_execution() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(_GuardedSkill(),), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    check(True, "V32: prepare_session with a guarded skill in the plan raises nothing (skill never touched)")


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
    check(True, "V33: prepare_session never iterates plan.skills or plan.tools")


# ---------------------------------------------------------------------------
# V34 -- no delegated calls
# ---------------------------------------------------------------------------
def scenario_no_delegated_calls() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    check(True, "V34: prepare_session never calls AutonomousHost.start()")
    check(True, "V34: prepare_session never calls SkillResolver.resolve()")
    check(True, "V34: prepare_session never calls any TaskManager method")


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
        f"V35: Orchestration.execution_session's import set is unchanged from Sprint 73 (got {imported_modules})",
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
        f"V36: Orchestration.executor's import set is unchanged from Sprint 73 (got {imported_modules})",
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
    actual_public_methods = {
        name
        for name in vars(ExecutionSession)
        if not name.startswith("_") and callable(getattr(ExecutionSession, name))
    }
    check(
        actual_public_methods == {"with_state"},
        f"V39: ExecutionSession exposes exactly {{'with_state'}} as its public methods (got {actual_public_methods})",
    )


def scenario_executor_public_api_verification() -> None:
    expected_public_methods = {"execute", "has_pending_tasks", "execute_plan", "prepare_session"}
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

    check(executor_a._current_plan.state == "ready", "V41: executor_a's session advanced to ready")
    check(executor_b._current_plan.state == "pending", "V41: executor_b's session is untouched, still pending")
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

    check(executor_a is not executor_b, "V42: two Executor() constructions are distinct objects")
    check(
        not hasattr(executor_b, "_current_plan"),
        "V42: executor_b's _current_plan is independent of executor_a's after prepare_session",
    )


# ---------------------------------------------------------------------------
# V43 -- no singleton: with_state results
# ---------------------------------------------------------------------------
def scenario_no_with_state_singleton() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session_a = ExecutionSession(plan=plan, state="pending", metadata={})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={})

    updated_a = session_a.with_state("ready")
    updated_b = session_b.with_state("ready")

    check(
        updated_a is not updated_b,
        "V43: with_state() calls on two distinct-but-equal sessions produce two distinct result objects",
    )
    check(updated_a == updated_b, "V43: those distinct result objects are still value-equal")


# ---------------------------------------------------------------------------
# V44 -- exception type exactness
# ---------------------------------------------------------------------------
def scenario_exception_type_exactness() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session = ExecutionSession(plan=plan, state="pending", metadata={})

    for value in [None, "", 5]:
        raised_type = None
        try:
            session.with_state(value)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is ExecutionSessionError,
            f"V44: with_state({value!r}) raises exactly ExecutionSessionError (got {raised_type})",
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

    session_a = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    check(session_a == session_b, "V45: ExecutionSession equality is unaffected by this sprint")
    check(hash(session_a) == hash(id(plan)), "V45: ExecutionSession hash is unaffected by this sprint")

    raised = False
    try:
        ExecutionSession(plan="not-a-plan", state="pending", metadata={})  # type: ignore[arg-type]
    except ExecutionSessionError:
        raised = True
    check(raised, "V45: ExecutionSession construction validation is unaffected by this sprint")


def main() -> int:
    scenarios = [
        scenario_with_state_basic_transition,
        scenario_with_state_identity_preservation,
        scenario_with_state_original_unchanged,
        scenario_with_state_invalid_state,
        scenario_with_state_chained_transitions,
        scenario_with_state_returned_instance_valid,
        scenario_with_state_no_caching,
        scenario_prepare_session_without_plan,
        scenario_prepare_session_advances_existing,
        scenario_prepare_session_called_twice,
        scenario_execute_plan_overwrites_ready_session,
        scenario_prepare_session_never_touches_collaborators,
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
        scenario_no_with_state_singleton,
        scenario_exception_type_exactness,
        scenario_pre_existing_behavior_unaffected,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 6 SPRINT 74 EXECUTION-SESSION-LIFECYCLE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())