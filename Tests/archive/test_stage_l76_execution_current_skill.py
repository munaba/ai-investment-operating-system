"""
Phase 7 Sprint 76 proof suite -- ``ExecutionSession.current_skill_index``
(a single new field, defaulting to ``0``) and ``ExecutionSession.
advance()`` (a single new public method that increments it by exactly
one), plus ``Executor.advance_skill()`` (a single new public method on
``Executor`` that advances the currently stored session's cursor using
it). Execution remains completely disabled: this sprint only
introduces an execution *cursor* -- no Skill is executed, no Tool is
inspected, ``plan.skills`` is never read, no bounds checking against
the plan's skill count is performed, and
``execute()``/``has_pending_tasks()``/``execute_plan()``/
``prepare_session()``/``start_session()``/the constructor are all
unchanged.

Scope: dedicated regression suite for the Sprint 76 addition only.
``SkillExecutionPlan`` (Sprint 71), the general shape of
``Executor.execute_plan`` (Sprint 72), ``ExecutionSession``'s existing
fields/validation/hash (Sprint 73), ``with_state``/``prepare_session``
(Sprint 74), and ``start``/``start_session`` (Sprint 75) are unchanged
by this sprint -- this suite does not re-verify their own internal
behavior beyond confirming Sprint 76 introduces no regression to them.

``ExecutionSession.advance`` never executes a skill or a tool, is
never wired into ``Runtime``, ``Workflow``, ``Host``, or ``EventBus``,
and never inspects ``plan.skills``/``plan.tools`` (proven both by
direct behavioral tests -- using a plan whose fields raise on
access/iteration -- and by AST-level import inspection of both module
source files). ``Executor.advance_skill`` never inspects the
``ExecutionSession`` beyond calling ``advance()`` on it, and performs
no bounds checking and introduces no loop.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l75_execution_lifecycle_running`` and
``Tests.test_stage_l74_execution_session_lifecycle`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 45+):
    V1  -- default: a freshly constructed ExecutionSession (no
           current_skill_index given) defaults to 0.
    V2  -- default: an explicitly given current_skill_index=0 is
           accepted.
    V3  -- validation: current_skill_index=None raises
           ExecutionSessionError.
    V4  -- validation: current_skill_index="0" (str) raises
           ExecutionSessionError.
    V5  -- validation: current_skill_index=-1 raises
           ExecutionSessionError.
    V6  -- validation: current_skill_index=True (bool) raises
           ExecutionSessionError (bool excluded despite being an int
           subclass).
    V7  -- validation: current_skill_index=3 (positive int) is
           accepted.
    V8  -- validation: existing plan/state/metadata validation is
           unchanged (still raises for bad plan/state/metadata).
    V9  -- advance: returns a new ExecutionSession instance (not
           ``self``).
    V10 -- advance: current_skill_index increments by exactly one.
    V11 -- advance: repeated advance() calls increment by one each
           time (0 -> 1 -> 2 -> 3).
    V12 -- advance: running is required -- a "pending" session raises
           ExecutionSessionError.
    V13 -- advance: running is required -- a "ready" session raises
           ExecutionSessionError.
    V14 -- advance: running is required -- an arbitrary state ("done")
           raises ExecutionSessionError.
    V15 -- advance: on an invalid current state, no new instance is
           returned (the call raises before returning).
    V16 -- advance: plan is preserved by identity on the returned
           instance.
    V17 -- advance: metadata is preserved by identity on the returned
           instance -- not rewrapped or re-copied.
    V18 -- advance: state is preserved (still "running") on the
           returned instance.
    V19 -- advance: the original instance's current_skill_index is
           unchanged after the call.
    V20 -- advance: the original instance's plan is unchanged
           (identity) after the call.
    V21 -- advance: the original instance's metadata is unchanged
           (identity) after the call.
    V22 -- advance: the original instance's state is unchanged after
           the call.
    V23 -- advance: the original and returned instances are distinct
           objects (``is not``).
    V24 -- advance: no mutation -- calling advance() twice on the same
           original instance produces two independent results, both
           equal to original_index + 1 (no shared/aliased state).
    V25 -- advance: the returned instance still satisfies
           ExecutionSession's own validation.
    V26 -- advance: the returned instance's metadata is still a
           MappingProxyType (frozen), not a plain dict.
    V27 -- advance: the returned instance's hash equals hash(id(plan))
           -- unaffected by the cursor.
    V28 -- with_state: preserves current_skill_index exactly across a
           state transition.
    V29 -- start: preserves current_skill_index exactly across a
           ready -> running transition.
    V30 -- full chain: pending(idx=0) -> ready -> running -> advance()
           -> advance() yields idx=2, with plan/metadata identity
           intact throughout.
    V31 -- executor: advance_skill() with no prior execute_plan() call
           raises ExecutorError.
    V32 -- executor: advance_skill() with no prior execute_plan() call
           never creates a _current_plan attribute as a side effect.
    V33 -- executor: advance_skill() after execute_plan() +
           prepare_session() + start_session() succeeds and returns
           None.
    V34 -- executor: advance_skill() increments
           self._current_plan.current_skill_index by one.
    V35 -- executor: advance_skill() preserves plan identity on
           self._current_plan.
    V36 -- executor: advance_skill() preserves metadata identity on
           self._current_plan.
    V37 -- executor: advance_skill() replaces self._current_plan with
           a new ExecutionSession object (not the same object, and
           not a mutation of the old one).
    V38 -- executor: advance_skill() called directly after
           execute_plan() (skipping prepare_session()/start_session())
           raises ExecutionSessionError, since the session is still
           "pending" -- and the exception propagates unchanged out of
           advance_skill().
    V39 -- executor: a failed advance_skill() call (session not
           running) leaves self._current_plan completely unchanged.
    V40 -- executor: calling advance_skill() repeatedly increments the
           cursor each time (0 -> 1 -> 2).
    V41 -- executor: advance_skill() never touches self._task_manager.
    V42 -- executor: advance_skill() never touches self._host.
    V43 -- executor: advance_skill() never touches
           self._skill_resolver.
    V44 -- no execution: a plan whose skills raise on any attribute
           access/.execute()/call is never touched by advance_skill.
    V45 -- no iteration: a plan whose skills/tools tuples raise on
           __iter__ are never iterated by advance/advance_skill.
    V46 -- no bounds checking: advance()/advance_skill() succeed even
           when current_skill_index already exceeds the length of
           plan.skills (no read of plan.skills at all, so no bound to
           violate).
    V47 -- no delegated calls: advance_skill never calls
           AutonomousHost.start/SkillResolver.resolve/any TaskManager
           method (guarded stubs raise on any call).
    V48 -- AST import verification: Orchestration.execution_session
           introduces no new imports for this sprint (import set is
           unchanged from Sprint 75).
    V49 -- AST import verification: Orchestration.executor introduces
           no new imports for this sprint (import set is unchanged
           from Sprint 75).
    V50 -- namespace verification: Orchestration.execution_session
           module does not expose Runtime/Workflow/Host/EventBus/
           Executor symbols.
    V51 -- namespace verification: Orchestration.executor module does
           not expose Runtime/Workflow/EventBus/ToolResolver/
           ToolManager/BaseSkill/BaseTool symbols.
    V52 -- public API verification: ExecutionSession exposes exactly
           {"with_state", "start", "advance"} as its public methods.
    V53 -- public API verification: Executor exposes exactly
           {"execute", "has_pending_tasks", "execute_plan",
           "prepare_session", "start_session", "advance_skill"} as its
           public methods.
    V54 -- multi-instance independence: two Executor instances each
           advance their own session's cursor independently.
    V55 -- no singleton: two Executor() constructions with identical
           collaborators are distinct objects with independent
           _current_plan attributes after advance_skill.
    V56 -- no singleton: two advance() calls on two value-equal-but-
           distinct "running" ExecutionSession instances produce two
           distinct result objects.
    V57 -- exception type exactness: the only exception ever raised by
           advance() for an invalid current state is
           ExecutionSessionError.
    V58 -- pre-existing Executor/ExecutionSession behavior (execute,
           has_pending_tasks, execute_plan, prepare_session,
           start_session, with_state, start, construction/validation,
           hash, equality) is completely unaffected by this addition.
    V59 -- execute() itself is not modified: calling Executor.execute()
           still never touches _current_plan.
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
    raises on any ``start``/``stop`` call, proving ``advance_skill``
    never delegates to it."""

    def start(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("advance_skill must never call AutonomousHost.start()")

    def stop(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("advance_skill must never call AutonomousHost.stop()")


class _GuardedSkillResolver(SkillResolver):
    """A SkillResolver subclass (so ``isinstance`` checks pass) that
    raises on any ``resolve`` call, proving ``advance_skill`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip SkillResolver.__init__

    def resolve(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("advance_skill must never call SkillResolver.resolve()")


class _GuardedTaskManager(TaskManager):
    """A TaskManager subclass (so ``isinstance`` checks pass) that
    raises on any method call, proving ``advance_skill`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip TaskManager.__init__

    def has_tasks(self):  # type: ignore[override]
        raise AssertionError("advance_skill must never call TaskManager.has_tasks()")

    def next_task(self):  # type: ignore[override]
        raise AssertionError("advance_skill must never call TaskManager.next_task()")


class _RaisingTuple(tuple):
    """A tuple subclass that raises on iteration, proving a plan's
    skills/tools are never iterated by advance/advance_skill."""

    def __iter__(self):
        raise AssertionError("must never iterate this tuple")


class _GuardedSkill:
    """A skill stand-in that raises on any attribute access, method
    call, or invocation -- proving advance_skill never touches a
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


def _running_session(plan=None, metadata=None, current_skill_index=0) -> ExecutionSession:
    plan = plan if plan is not None else SkillExecutionPlan(skills=(), tools=(), metadata={})
    metadata = metadata if metadata is not None else {}
    pending = ExecutionSession(
        plan=plan, state="pending", metadata=metadata, current_skill_index=current_skill_index
    )
    ready = pending.with_state("ready")
    return ready.start()


# ---------------------------------------------------------------------------
# V1-V2 -- default current_skill_index
# ---------------------------------------------------------------------------
def scenario_default_current_skill_index() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session = ExecutionSession(plan=plan, state="pending", metadata={})
    check(session.current_skill_index == 0, "V1: a freshly constructed ExecutionSession defaults current_skill_index to 0")

    session_explicit = ExecutionSession(plan=plan, state="pending", metadata={}, current_skill_index=0)
    check(session_explicit.current_skill_index == 0, "V2: an explicitly given current_skill_index=0 is accepted")


# ---------------------------------------------------------------------------
# V3-V7 -- current_skill_index validation
# ---------------------------------------------------------------------------
def scenario_current_skill_index_validation() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})

    for value, label in [(None, "None"), ("0", "str"), (-1, "negative int"), (True, "bool")]:
        raised = False
        try:
            ExecutionSession(plan=plan, state="pending", metadata={}, current_skill_index=value)  # type: ignore[arg-type]
        except ExecutionSessionError:
            raised = True
        check(raised, f"V3-V6: current_skill_index={label} raises ExecutionSessionError")

    valid_session = ExecutionSession(plan=plan, state="pending", metadata={}, current_skill_index=3)
    check(valid_session.current_skill_index == 3, "V7: current_skill_index=3 (positive int) is accepted")


# ---------------------------------------------------------------------------
# V8 -- existing validation unchanged
# ---------------------------------------------------------------------------
def scenario_existing_validation_unchanged() -> None:
    raised = False
    try:
        ExecutionSession(plan="not-a-plan", state="pending", metadata={})  # type: ignore[arg-type]
    except ExecutionSessionError:
        raised = True
    check(raised, "V8: plan validation is unchanged")

    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    raised = False
    try:
        ExecutionSession(plan=plan, state="", metadata={})
    except ExecutionSessionError:
        raised = True
    check(raised, "V8: state validation is unchanged")

    raised = False
    try:
        ExecutionSession(plan=plan, state="pending", metadata="not-a-mapping")  # type: ignore[arg-type]
    except ExecutionSessionError:
        raised = True
    check(raised, "V8: metadata validation is unchanged")


# ---------------------------------------------------------------------------
# V9-V11 -- advance basic behavior
# ---------------------------------------------------------------------------
def scenario_advance_basic_behavior() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = _running_session(plan=plan)
    updated = original.advance()

    check(isinstance(updated, ExecutionSession), "V9: advance returns a new ExecutionSession instance")
    check(updated is not original, "V9: the returned instance is not self")
    check(updated.current_skill_index == 1, "V10: current_skill_index increments by exactly one")

    second = updated.advance()
    third = second.advance()
    check(
        original.current_skill_index == 0
        and updated.current_skill_index == 1
        and second.current_skill_index == 2
        and third.current_skill_index == 3,
        "V11: repeated advance() calls increment by one each time (0 -> 1 -> 2 -> 3)",
    )


# ---------------------------------------------------------------------------
# V12-V15 -- running required
# ---------------------------------------------------------------------------
def scenario_advance_requires_running() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})

    pending = ExecutionSession(plan=plan, state="pending", metadata={})
    raised = False
    result = "UNSET"
    try:
        result = pending.advance()
    except ExecutionSessionError:
        raised = True
    check(raised, "V12: a 'pending' session cannot advance -- raises ExecutionSessionError")
    check(result == "UNSET", "V15: advance() never returns a new instance when current state is invalid (pending)")

    ready = pending.with_state("ready")
    raised = False
    result = "UNSET"
    try:
        result = ready.advance()
    except ExecutionSessionError:
        raised = True
    check(raised, "V13: a 'ready' session cannot advance -- raises ExecutionSessionError")
    check(result == "UNSET", "V15: advance() never returns a new instance when current state is invalid (ready)")

    done = ExecutionSession(plan=plan, state="done", metadata={})
    raised = False
    result = "UNSET"
    try:
        result = done.advance()
    except ExecutionSessionError:
        raised = True
    check(raised, "V14: an arbitrary state ('done') cannot advance -- raises ExecutionSessionError")
    check(result == "UNSET", "V15: advance() never returns a new instance when current state is invalid (done)")


# ---------------------------------------------------------------------------
# V16-V18 -- identity/value preservation on the returned instance
# ---------------------------------------------------------------------------
def scenario_advance_identity_preservation() -> None:
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    original = _running_session(plan=plan, metadata={"k": "v"})
    updated = original.advance()

    check(updated.plan is original.plan, "V16: plan is preserved by identity on the returned instance")
    check(updated.plan is plan, "V16: plan is preserved by identity to the original argument")
    check(updated.metadata is original.metadata, "V17: metadata is preserved by identity, not rewrapped/re-copied")
    check(updated.state == "running", 'V18: state is preserved (still "running") on the returned instance')


# ---------------------------------------------------------------------------
# V19-V23 -- original instance left unchanged
# ---------------------------------------------------------------------------
def scenario_advance_original_unchanged() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = _running_session(plan=plan, metadata={"a": 1})
    original_plan_ref = original.plan
    original_metadata_ref = original.metadata
    original_state = original.state

    updated = original.advance()

    check(original.current_skill_index == 0, "V19: the original instance's current_skill_index is unchanged")
    check(original.plan is original_plan_ref, "V20: the original instance's plan is unchanged (identity)")
    check(
        original.metadata is original_metadata_ref,
        "V21: the original instance's metadata is unchanged (identity)",
    )
    check(original.state == original_state, "V22: the original instance's state is unchanged after the call")
    check(updated is not original, "V23: the original and returned instances are distinct objects")


# ---------------------------------------------------------------------------
# V24 -- no mutation / no shared state across independent calls
# ---------------------------------------------------------------------------
def scenario_advance_no_mutation() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = _running_session(plan=plan, current_skill_index=5)

    first_call = original.advance()
    second_call = original.advance()

    check(
        first_call is not second_call,
        "V24: calling advance() twice on the same original instance produces two independent results",
    )
    check(
        first_call.current_skill_index == 6 and second_call.current_skill_index == 6,
        "V24: both independent results equal original_index + 1 (no shared/aliased state)",
    )
    check(original.current_skill_index == 5, "V24: the original instance itself is never mutated")


# ---------------------------------------------------------------------------
# V25-V27 -- returned instance validity, freezing, and hash
# ---------------------------------------------------------------------------
def scenario_advance_returned_instance_valid() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={"k": 1})
    original = _running_session(plan=plan, metadata={"k": 1})
    updated = original.advance()

    check(
        isinstance(updated.plan, SkillExecutionPlan)
        and isinstance(updated.state, str)
        and updated.state
        and isinstance(updated.current_skill_index, int),
        "V25: the returned instance still satisfies ExecutionSession's own validation",
    )
    check(
        type(updated.metadata).__name__ == "mappingproxy",
        "V26: the returned instance's metadata is still a MappingProxyType",
    )
    check(
        hash(updated) == hash(id(plan)),
        "V27: the returned instance's hash equals hash(id(plan)), unaffected by the cursor",
    )


# ---------------------------------------------------------------------------
# V28-V29 -- with_state and start preserve current_skill_index
# ---------------------------------------------------------------------------
def scenario_with_state_preserves_cursor() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    original = ExecutionSession(plan=plan, state="pending", metadata={}, current_skill_index=4)
    updated = original.with_state("ready")

    check(updated.current_skill_index == 4, "V28: with_state preserves current_skill_index exactly")
    check(updated.plan is plan, "V28: with_state still preserves plan identity")
    check(updated.metadata is original.metadata, "V28: with_state still preserves metadata identity")


def scenario_start_preserves_cursor() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    pending = ExecutionSession(plan=plan, state="pending", metadata={}, current_skill_index=7)
    ready = pending.with_state("ready")
    running = ready.start()

    check(running.current_skill_index == 7, "V29: start preserves current_skill_index exactly")
    check(running.plan is plan, "V29: start still preserves plan identity")
    check(running.metadata is pending.metadata, "V29: start still preserves metadata identity")


# ---------------------------------------------------------------------------
# V30 -- full lifecycle + cursor chain
# ---------------------------------------------------------------------------
def scenario_full_chain_with_cursor() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    pending = ExecutionSession(plan=plan, state="pending", metadata={})
    ready = pending.with_state("ready")
    running = ready.start()
    advanced_once = running.advance()
    advanced_twice = advanced_once.advance()

    check(
        pending.current_skill_index == 0
        and ready.current_skill_index == 0
        and running.current_skill_index == 0
        and advanced_once.current_skill_index == 1
        and advanced_twice.current_skill_index == 2,
        "V30: full chain pending -> ready -> running -> advance -> advance yields index=2",
    )
    check(
        pending.plan is ready.plan is running.plan is advanced_once.plan is advanced_twice.plan is plan,
        "V30: plan identity intact throughout the whole chain",
    )
    check(
        pending.metadata is ready.metadata is running.metadata is advanced_once.metadata is advanced_twice.metadata,
        "V30: metadata identity intact throughout the whole chain",
    )


# ---------------------------------------------------------------------------
# V31-V32 -- advance_skill without a prior session
# ---------------------------------------------------------------------------
def scenario_advance_skill_without_plan() -> None:
    executor = _make_executor()

    raised = False
    try:
        executor.advance_skill()
    except ExecutorError:
        raised = True

    check(raised, "V31: advance_skill() with no prior execute_plan() call raises ExecutorError")
    check(
        not hasattr(executor, "_current_plan"),
        "V32: the failed call never creates a _current_plan attribute as a side effect",
    )


# ---------------------------------------------------------------------------
# V33-V37 -- advance_skill advances an existing running session
# ---------------------------------------------------------------------------
def scenario_advance_skill_advances_existing() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    running_session = executor._current_plan

    result = executor.advance_skill()

    check(result is None, "V33: advance_skill() succeeds and returns None")
    advanced_session = executor._current_plan
    check(advanced_session.current_skill_index == 1, "V34: self._current_plan.current_skill_index increments by one")
    check(advanced_session.plan is plan, "V35: advance_skill preserves plan identity")
    check(
        advanced_session.metadata is running_session.metadata,
        "V36: advance_skill preserves metadata identity",
    )
    check(
        advanced_session is not running_session,
        "V37: advance_skill replaces _current_plan with a new ExecutionSession object",
    )
    check(running_session.current_skill_index == 0, "V37: the prior running session object itself is unmutated")


# ---------------------------------------------------------------------------
# V38-V39 -- advance_skill on a non-running session
# ---------------------------------------------------------------------------
def scenario_advance_skill_not_running() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    pending_session = executor._current_plan

    raised = False
    try:
        executor.advance_skill()
    except ExecutionSessionError:
        raised = True

    check(
        raised,
        "V38: advance_skill() right after execute_plan() (session still pending) raises "
        "ExecutionSessionError, which propagates unchanged",
    )
    check(
        executor._current_plan is pending_session,
        "V39: a failed advance_skill() call leaves self._current_plan completely unchanged",
    )
    check(executor._current_plan.state == "pending", "V39: the unchanged session is still 'pending'")


# ---------------------------------------------------------------------------
# V40 -- repeated advance_skill calls
# ---------------------------------------------------------------------------
def scenario_advance_skill_repeated() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()

    check(executor._current_plan.current_skill_index == 0, "V40: cursor starts at 0")
    executor.advance_skill()
    check(executor._current_plan.current_skill_index == 1, "V40: cursor is 1 after first advance_skill()")
    executor.advance_skill()
    check(executor._current_plan.current_skill_index == 2, "V40: cursor is 2 after second advance_skill()")


# ---------------------------------------------------------------------------
# V41-V43 -- advance_skill never touches other collaborators
# ---------------------------------------------------------------------------
def scenario_advance_skill_never_touches_collaborators() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()

    original_task_manager = executor._task_manager
    original_host = executor._host
    original_skill_resolver = executor._skill_resolver

    executor.advance_skill()

    check(executor._task_manager is original_task_manager, "V41: advance_skill never touches self._task_manager")
    check(executor._host is original_host, "V42: advance_skill never touches self._host")
    check(
        executor._skill_resolver is original_skill_resolver,
        "V43: advance_skill never touches self._skill_resolver",
    )


# ---------------------------------------------------------------------------
# V44 -- no skill execution
# ---------------------------------------------------------------------------
def scenario_no_skill_execution() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(_GuardedSkill(),), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    executor.advance_skill()
    check(True, "V44: advance_skill with a guarded skill in the plan raises nothing (skill never touched)")


# ---------------------------------------------------------------------------
# V45 -- no iteration
# ---------------------------------------------------------------------------
def scenario_no_iteration() -> None:
    executor = _make_executor()
    raising_skills = _RaisingTuple(("s",))
    raising_tools = _RaisingTuple(("t",))
    plan = SkillExecutionPlan(skills=raising_skills, tools=raising_tools, metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    executor.advance_skill()
    check(True, "V45: advance_skill never iterates plan.skills or plan.tools")


# ---------------------------------------------------------------------------
# V46 -- no bounds checking
# ---------------------------------------------------------------------------
def scenario_no_bounds_checking() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("only-one-skill",), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()

    for _ in range(10):
        executor.advance_skill()

    check(
        executor._current_plan.current_skill_index == 10,
        "V46: advance_skill() succeeds past the plan's actual skill count -- no bounds check against plan.skills",
    )


# ---------------------------------------------------------------------------
# V47 -- no delegated calls
# ---------------------------------------------------------------------------
def scenario_no_delegated_calls() -> None:
    executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("s",), tools=("t",), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    executor.advance_skill()
    check(True, "V47: advance_skill never calls AutonomousHost.start()")
    check(True, "V47: advance_skill never calls SkillResolver.resolve()")
    check(True, "V47: advance_skill never calls any TaskManager method")


# ---------------------------------------------------------------------------
# V48-V49 -- AST import verification (no new imports this sprint)
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
        f"V48: Orchestration.execution_session's import set is unchanged from Sprint 75 (got {imported_modules})",
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
        f"V49: Orchestration.executor's import set is unchanged from Sprint 75 (got {imported_modules})",
    )


# ---------------------------------------------------------------------------
# V50-V51 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_execution_session_namespace() -> None:
    import Orchestration.execution_session as session_module

    forbidden = ["Runtime", "Workflow", "Host", "EventBus", "Executor"]
    for name in forbidden:
        check(
            not hasattr(session_module, name),
            f"V50: Orchestration.execution_session module namespace does not expose '{name}'",
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
            f"V51: Orchestration.executor module namespace does not expose '{name}'",
        )


# ---------------------------------------------------------------------------
# V52-V53 -- public API verification
# ---------------------------------------------------------------------------
def scenario_execution_session_public_api_verification() -> None:
    expected_public_methods = {"with_state", "start", "advance"}
    actual_public_methods = {
        name
        for name in vars(ExecutionSession)
        if not name.startswith("_") and callable(getattr(ExecutionSession, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V52: ExecutionSession exposes exactly {expected_public_methods} as its public methods "
        f"(got {actual_public_methods})",
    )


def scenario_executor_public_api_verification() -> None:
    expected_public_methods = {
        "execute",
        "has_pending_tasks",
        "execute_plan",
        "prepare_session",
        "start_session",
        "advance_skill",
    }
    actual_public_methods = {
        name
        for name in vars(Executor)
        if not name.startswith("_") and callable(getattr(Executor, name))
    }
    check(
        actual_public_methods == expected_public_methods,
        f"V53: Executor exposes exactly the expected public methods (got {actual_public_methods})",
    )


# ---------------------------------------------------------------------------
# V54 -- multi-instance independence
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
    executor_b.start_session()

    executor_a.advance_skill()

    check(executor_a._current_plan.current_skill_index == 1, "V54: executor_a's cursor advanced to 1")
    check(executor_b._current_plan.current_skill_index == 0, "V54: executor_b's cursor is untouched, still 0")
    check(executor_a._current_plan.plan is plan_a, "V54: executor_a's session wraps only its own plan")
    check(executor_b._current_plan.plan is plan_b, "V54: executor_b's session wraps only its own plan")


# ---------------------------------------------------------------------------
# V55 -- no singleton: Executor
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
    executor_a.advance_skill()

    check(executor_a is not executor_b, "V55: two Executor() constructions are distinct objects")
    check(
        not hasattr(executor_b, "_current_plan"),
        "V55: executor_b's _current_plan is independent of executor_a's after advance_skill",
    )


# ---------------------------------------------------------------------------
# V56 -- no singleton: advance results
# ---------------------------------------------------------------------------
def scenario_no_advance_singleton() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    session_a = _running_session(plan=plan)
    session_b = _running_session(plan=plan)

    updated_a = session_a.advance()
    updated_b = session_b.advance()

    check(
        updated_a is not updated_b,
        "V56: advance() calls on two distinct-but-equal 'running' sessions produce two distinct result objects",
    )
    check(updated_a == updated_b, "V56: those distinct result objects are still value-equal")


# ---------------------------------------------------------------------------
# V57 -- exception type exactness
# ---------------------------------------------------------------------------
def scenario_exception_type_exactness() -> None:
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})

    for state in ["pending", "ready", "done", "unknown"]:
        session = ExecutionSession(plan=plan, state=state, metadata={})
        raised_type = None
        try:
            session.advance()
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is ExecutionSessionError,
            f"V57: advance() on state {state!r} raises exactly ExecutionSessionError (got {raised_type})",
        )


# ---------------------------------------------------------------------------
# V58 -- pre-existing behavior unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_behavior_unaffected() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host)

    check(
        executor.has_pending_tasks() is False,
        "V58: has_pending_tasks() still works and reports no pending tasks on an empty queue",
    )

    raised = False
    try:
        executor.execute(context=None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V58: execute(context=None) still raises ExecutorError, unaffected by this sprint")

    executed_count = executor.execute(context="ctx", iterations=1)
    check(executed_count == 0, "V58: execute() on an empty queue still returns 0, unaffected by this sprint")

    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    check(
        executor._current_plan.state == "pending",
        "V58: execute_plan() still stores a pending session, unaffected by this sprint",
    )

    executor.prepare_session()
    check(
        executor._current_plan.state == "ready",
        "V58: prepare_session() still advances pending -> ready, unaffected by this sprint",
    )

    executor.start_session()
    check(
        executor._current_plan.state == "running",
        "V58: start_session() still advances ready -> running, unaffected by this sprint",
    )

    session_a = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    check(session_a == session_b, "V58: ExecutionSession equality is unaffected by this sprint")
    check(hash(session_a) == hash(id(plan)), "V58: ExecutionSession hash is unaffected by this sprint")

    with_state_result = session_a.with_state("ready")
    check(
        with_state_result.state == "ready",
        "V58: ExecutionSession.with_state() is unaffected by this sprint",
    )

    start_result = with_state_result.start()
    check(
        start_result.state == "running",
        "V58: ExecutionSession.start() is unaffected by this sprint",
    )

    raised = False
    try:
        ExecutionSession(plan="not-a-plan", state="pending", metadata={})  # type: ignore[arg-type]
    except ExecutionSessionError:
        raised = True
    check(raised, "V58: ExecutionSession construction validation is unaffected by this sprint")


# ---------------------------------------------------------------------------
# V59 -- execute() unmodified
# ---------------------------------------------------------------------------
def scenario_execute_unmodified() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    executor.advance_skill()

    session_before = executor._current_plan
    executed_count = executor.execute(context="ctx", iterations=1)

    check(executed_count == 0, "V59: execute() on an empty task queue still returns 0")
    check(
        executor._current_plan is session_before,
        "V59: execute() never touches self._current_plan",
    )


def main() -> int:
    scenarios = [
        scenario_default_current_skill_index,
        scenario_current_skill_index_validation,
        scenario_existing_validation_unchanged,
        scenario_advance_basic_behavior,
        scenario_advance_requires_running,
        scenario_advance_identity_preservation,
        scenario_advance_original_unchanged,
        scenario_advance_no_mutation,
        scenario_advance_returned_instance_valid,
        scenario_with_state_preserves_cursor,
        scenario_start_preserves_cursor,
        scenario_full_chain_with_cursor,
        scenario_advance_skill_without_plan,
        scenario_advance_skill_advances_existing,
        scenario_advance_skill_not_running,
        scenario_advance_skill_repeated,
        scenario_advance_skill_never_touches_collaborators,
        scenario_no_skill_execution,
        scenario_no_iteration,
        scenario_no_bounds_checking,
        scenario_no_delegated_calls,
        scenario_ast_import_verification_execution_session,
        scenario_ast_import_verification_executor,
        scenario_execution_session_namespace,
        scenario_executor_namespace_verification,
        scenario_execution_session_public_api_verification,
        scenario_executor_public_api_verification,
        scenario_multi_instance_independence,
        scenario_no_executor_singleton,
        scenario_no_advance_singleton,
        scenario_exception_type_exactness,
        scenario_pre_existing_behavior_unaffected,
        scenario_execute_unmodified,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 7 SPRINT 76 EXECUTION-CURRENT-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())