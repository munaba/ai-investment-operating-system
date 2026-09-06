"""
Phase 7 Sprint 78 proof suite -- ``Executor.invoke_current_skill()`` (a
single new public method that invokes exactly one Skill --
``current_skill().execute(None)`` -- and returns its result verbatim).
This is the first sprint in which a Skill is actually executed: no
Tool, ``Runtime``, ``Workflow``, ``Planner``, ``SkillResolver``, or
``ToolResolver`` is ever invoked, no session/cursor state is mutated,
and no metadata/tools are inspected.

Scope: dedicated regression suite for the Sprint 78 addition only.
``SkillExecutionPlan`` (Sprint 71), the general shape of
``Executor.execute_plan`` (Sprint 72), ``ExecutionSession``'s
existing fields/validation/hash (Sprint 73), ``with_state``/
``prepare_session`` (Sprint 74), ``start``/``start_session``
(Sprint 75), ``current_skill_index``/``advance``/``advance_skill()``
(Sprint 76), and ``current_skill()`` (Sprint 77) are unchanged by
this sprint -- this suite does not re-verify their own internal
behavior beyond confirming Sprint 78 introduces no regression to
them.

``Executor.invoke_current_skill()`` calls ``self.current_skill()``
exactly once (reusing its existing-session/running-state checks
rather than duplicating them) and ``skill.execute(None)`` exactly
once, returning the result unchanged. It never calls
``advance_skill()``, never mutates ``self._current_plan`` or any of
its fields, never reads ``plan.tools``/``plan.metadata``, never
iterates ``plan.skills``, and is never wired into ``Runtime``,
``Workflow``, ``Host``, ``EventBus``, ``Planner``, ``SkillResolver``,
or ``ToolResolver`` (proven both by direct behavioral tests -- using
guarded stand-ins that raise on any touch -- and by AST-level
inspection of the method's own source).

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l77_executor_current_skill`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 50+):
    V1  -- missing session: invoke_current_skill() with no prior
           execute_plan() call raises ExecutorError.
    V2  -- missing session: the ExecutorError message references
           execute_plan() (propagated from current_skill()).
    V3  -- missing session: no _current_plan attribute is created as
           a side effect of a failed call.
    V4  -- pending state: invoke_current_skill() on a "pending"
           session raises ExecutionSessionError.
    V5  -- pending state: the ExecutionSessionError message mentions
           the actual current state ("pending").
    V6  -- ready state: invoke_current_skill() on a "ready" session
           raises ExecutionSessionError.
    V7  -- ready state: the ExecutionSessionError message mentions
           the actual current state ("ready").
    V8  -- arbitrary non-running state ("done") raises
           ExecutionSessionError.
    V9  -- running state: invoke_current_skill() on a running session
           with a real skill succeeds and returns the skill's result.
    V10 -- running state: the skill's execute() method is actually
           invoked (observable side effect recorded).
    V11 -- current_skill called exactly once: a skill/plan
           instrumented to count current_skill() invocations shows
           exactly one call per invoke_current_skill() call.
    V12 -- execute called exactly once: the invoked skill's execute()
           is called exactly once per invoke_current_skill() call.
    V13 -- execute called exactly once: calling
           invoke_current_skill() twice in a row invokes execute()
           exactly twice total (once per call), not zero, not more.
    V14 -- execute(None): the skill's execute() receives exactly one
           positional argument, and that argument is None.
    V15 -- execute(None): no keyword arguments are passed to
           execute().
    V16 -- return propagated: invoke_current_skill() returns exactly
           what execute() returned (identity-preserving for a
           non-trivial object).
    V17 -- return propagated: a None return value from execute() is
           propagated as None (not swallowed or replaced).
    V18 -- return propagated: a falsy-but-not-None return value
           (e.g. 0, "", []) is propagated unchanged.
    V19 -- exception propagated: if execute() raises a custom
           exception, invoke_current_skill() lets it propagate
           unchanged (no try/except swallows or wraps it).
    V20 -- exception propagated: the exact exception instance raised
           by execute() is the one that escapes invoke_current_skill()
           (identity-preserving, not re-raised as a new object).
    V21 -- exception propagated: an exception from current_skill()
           itself (missing session) is not caught or altered by
           invoke_current_skill().
    V22 -- exception propagated: an exception from current_skill()
           itself (wrong state) is not caught or altered by
           invoke_current_skill().
    V23 -- no wrapper: the returned value is not wrapped in any
           Executor-defined type, list, tuple, or dict -- it is the
           exact object execute() returned.
    V24 -- no wrapper: invoke_current_skill() does not attach any
           extra attribute or metadata to the returned value.
    V25 -- no state mutation: self._current_plan.state is unchanged
           (still "running") after a successful invoke_current_skill()
           call.
    V26 -- no state mutation: self._current_plan itself (the whole
           object, by identity) is unchanged after a successful
           invoke_current_skill() call.
    V27 -- no cursor mutation: self._current_plan.current_skill_index
           is unchanged after invoke_current_skill().
    V28 -- no cursor mutation: calling invoke_current_skill() several
           times in a row never changes current_skill_index (always
           invokes the same skill).
    V29 -- no advance: invoke_current_skill() never calls
           advance_skill() -- proven via an Executor subclass whose
           advance_skill() raises if called.
    V30 -- no metadata access: a plan/session whose metadata is a
           mapping subclass that raises on any read access is never
           touched by invoke_current_skill().
    V31 -- no tool access: invoke_current_skill() never reads
           plan.tools at all (a tools tuple that raises on
           __len__/__getitem__/__iter__ is never touched).
    V32 -- no iteration: a plan whose skills/tools tuples raise on
           __iter__ are never iterated by invoke_current_skill().
    V33 -- no delegated calls: invoke_current_skill() never calls
           AutonomousHost.start/SkillResolver.resolve/any TaskManager
           method (guarded stubs raise on any call).
    V34 -- no delegated calls: invoke_current_skill() succeeds against
           fully guarded collaborators (task_manager/host/
           skill_resolver all raise on any call) as long as the skill
           itself is well-behaved.
    V35 -- AST verification: invoke_current_skill()'s body contains
           no call to len().
    V36 -- AST verification: invoke_current_skill()'s body contains
           no subscript/indexing expression.
    V37 -- AST verification: invoke_current_skill()'s body contains
           no for-loop, while-loop, comprehension, or try/except of
           any kind.
    V38 -- AST verification: invoke_current_skill()'s body calls only
           self.current_skill() and skill.execute(None), and ends
           with a bare return of that result -- no other Call nodes
           appear.
    V39 -- AST verification: invoke_current_skill()'s body contains
           no reference to Runtime/Workflow/Planner/EventBus/
           ToolResolver/ToolManager/AutonomousHost/TaskManager/
           SkillResolver by name.
    V40 -- AST verification: the module source for
           Orchestration.executor introduces no new top-level import
           for this sprint (import set unchanged from Sprint 77).
    V41 -- namespace verification: Orchestration.executor module does
           not expose Runtime/Workflow/EventBus/ToolResolver/
           ToolManager/BaseSkill/BaseTool/Planner symbols.
    V42 -- public API verification: Executor exposes exactly
           {"execute", "has_pending_tasks", "execute_plan",
           "prepare_session", "start_session", "advance_skill",
           "current_skill", "invoke_current_skill"} as its public
           methods.
    V43 -- multi-instance independence: two Executor instances each
           invoke their own session's current skill independently.
    V44 -- multi-instance independence: invoking one Executor's skill
           does not affect the other Executor's stored session/
           cursor.
    V45 -- no singleton: two Executor() constructions with identical
           collaborators are distinct objects, each with its own
           independent _current_plan and invocation result.
    V46 -- no singleton: two invoke_current_skill() calls on two
           value-equal-but-distinct running sessions with equal but
           distinct skill objects produce independent results.
    V47 -- pre-existing behavior unaffected: execute(),
           has_pending_tasks(), execute_plan(), prepare_session(),
           start_session(), advance_skill(), current_skill() all
           still behave exactly as before this sprint.
    V48 -- pre-existing behavior unaffected: ExecutionSession's own
           validation/hash/equality/with_state/start/advance are all
           unaffected by this sprint.
    V49 -- execute() unmodified: calling Executor.execute() still
           never touches self._current_plan.
    V50 -- current_skill() unmodified: calling Executor.current_skill()
           directly still behaves exactly as in Sprint 77 (no bounds
           check, no iteration, returns by identity).
    V51 -- full chain: pending -> ready -> running ->
           invoke_current_skill() -> advance_skill() ->
           invoke_current_skill() invokes the correct skill at each
           step, with plan/metadata identity intact throughout.
    V52 -- signature: invoke_current_skill() takes no
           positional/keyword arguments beyond self.
    V53 -- skill returning itself: invoke_current_skill() correctly
           returns a skill's own execute() result even when that
           result happens to be the skill object itself (identity
           check, not special-cased).
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
    raises on any ``start``/``stop`` call, proving
    ``invoke_current_skill`` never delegates to it."""

    def start(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("invoke_current_skill must never call AutonomousHost.start()")

    def stop(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("invoke_current_skill must never call AutonomousHost.stop()")


class _GuardedSkillResolver(SkillResolver):
    """A SkillResolver subclass (so ``isinstance`` checks pass) that
    raises on any ``resolve`` call, proving ``invoke_current_skill``
    never delegates to it."""

    def __init__(self):
        pass  # deliberately skip SkillResolver.__init__

    def resolve(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("invoke_current_skill must never call SkillResolver.resolve()")


class _GuardedTaskManager(TaskManager):
    """A TaskManager subclass (so ``isinstance`` checks pass) that
    raises on any method call, proving ``invoke_current_skill`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip TaskManager.__init__

    def has_tasks(self):  # type: ignore[override]
        raise AssertionError("invoke_current_skill must never call TaskManager.has_tasks()")

    def next_task(self):  # type: ignore[override]
        raise AssertionError("invoke_current_skill must never call TaskManager.next_task()")


class _RaisingTuple(tuple):
    """A tuple subclass that raises on iteration, proving a plan's
    skills/tools are never iterated by invoke_current_skill()."""

    def __iter__(self):
        raise AssertionError("must never iterate this tuple")


class _RaisingToolsTuple(tuple):
    """A tuple subclass that raises on len/getitem/iter, proving
    plan.tools is never touched by invoke_current_skill()."""

    def __len__(self):
        raise AssertionError("must never call len() on plan.tools")

    def __getitem__(self, item):
        raise AssertionError("must never index plan.tools")

    def __iter__(self):
        raise AssertionError("must never iterate plan.tools")


class _RaisingMapping(dict):
    """A mapping subclass that raises on any read access, proving
    invoke_current_skill() never inspects plan/session metadata."""

    def __getitem__(self, item):
        raise AssertionError("must never read metadata")

    def get(self, *args, **kwargs):
        raise AssertionError("must never read metadata via get()")

    def __iter__(self):
        raise AssertionError("must never iterate metadata")


class _RecordingSkill:
    """A skill stand-in that records every execute() call (args,
    kwargs, and call count) and returns a fixed, observable result."""

    def __init__(self, result=None):
        self._result = result
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._result


class _RaisingExecuteSkill:
    """A skill stand-in whose execute() raises a specific exception
    instance, proving invoke_current_skill() propagates it unchanged."""

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        raise self._exc


class _SelfReturningSkill:
    """A skill stand-in whose execute() returns the skill object
    itself, proving invoke_current_skill() does not special-case
    falsy/self-referential results."""

    def execute(self, *args, **kwargs):
        return self


class _CustomError(Exception):
    pass


class _CountingCurrentSkillExecutor(Executor):
    """An Executor subclass that counts how many times its own
    ``current_skill()`` is invoked, proving
    ``invoke_current_skill()`` calls it exactly once per call and
    never duplicates its logic."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_skill_call_count = 0

    def current_skill(self):  # type: ignore[override]
        self.current_skill_call_count += 1
        return super().current_skill()


class _NoAdvanceExecutor(Executor):
    """An Executor subclass whose advance_skill() raises if called,
    proving invoke_current_skill() never calls it."""

    def advance_skill(self):  # type: ignore[override]
        raise AssertionError("invoke_current_skill must never call advance_skill()")


def _make_executor(host=None, skill_resolver=None, task_manager=None, cls=Executor) -> Executor:
    task_manager = task_manager if task_manager is not None else TaskManager(TaskQueue())
    host = host if host is not None else AutonomousHost()
    if skill_resolver is not None:
        return cls(task_manager=task_manager, host=host, skill_resolver=skill_resolver)
    return cls(task_manager=task_manager, host=host)


def _make_guarded_executor(cls=Executor) -> Executor:
    return cls(
        task_manager=_GuardedTaskManager(),
        host=_GuardedHost(),
        skill_resolver=_GuardedSkillResolver(),
    )


def _running_executor(plan, cls=Executor) -> Executor:
    executor = _make_executor(cls=cls)
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor


# ---------------------------------------------------------------------------
# V1-V3 -- missing session
# ---------------------------------------------------------------------------
def scenario_missing_session() -> None:
    executor = _make_executor()

    raised = False
    message = ""
    try:
        executor.invoke_current_skill()
    except ExecutorError as exc:
        raised = True
        message = str(exc)
    check(raised, "V1: invoke_current_skill() with no prior execute_plan() call raises ExecutorError")
    check("execute_plan" in message, "V2: the ExecutorError message references execute_plan()")
    check(not hasattr(executor, "_current_plan"), "V3: no _current_plan attribute is created as a side effect")


# ---------------------------------------------------------------------------
# V4-V5 -- pending state
# ---------------------------------------------------------------------------
def scenario_pending_state() -> None:
    plan = SkillExecutionPlan(skills=(_RecordingSkill("R"),), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)

    raised = False
    message = ""
    try:
        executor.invoke_current_skill()
    except ExecutionSessionError as exc:
        raised = True
        message = str(exc)
    check(raised, "V4: invoke_current_skill() on a 'pending' session raises ExecutionSessionError")
    check("pending" in message, "V5: the ExecutionSessionError message mentions the actual current state ('pending')")


# ---------------------------------------------------------------------------
# V6-V7 -- ready state
# ---------------------------------------------------------------------------
def scenario_ready_state() -> None:
    plan = SkillExecutionPlan(skills=(_RecordingSkill("R"),), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()

    raised = False
    message = ""
    try:
        executor.invoke_current_skill()
    except ExecutionSessionError as exc:
        raised = True
        message = str(exc)
    check(raised, "V6: invoke_current_skill() on a 'ready' session raises ExecutionSessionError")
    check("ready" in message, "V7: the ExecutionSessionError message mentions the actual current state ('ready')")


# ---------------------------------------------------------------------------
# V8 -- arbitrary non-running state
# ---------------------------------------------------------------------------
def scenario_arbitrary_state() -> None:
    plan = SkillExecutionPlan(skills=(_RecordingSkill("R"),), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor._current_plan = executor._current_plan.with_state("done")

    raised = False
    try:
        executor.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V8: invoke_current_skill() on an arbitrary non-running state ('done') raises ExecutionSessionError")


# ---------------------------------------------------------------------------
# V9-V10 -- running state success
# ---------------------------------------------------------------------------
def scenario_running_state_success() -> None:
    skill = _RecordingSkill("HELLO")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    result = executor.invoke_current_skill()
    check(result == "HELLO", "V9: invoke_current_skill() on a running session with a real skill succeeds and returns the skill's result")
    check(len(skill.calls) == 1, "V10: the skill's execute() method is actually invoked (observable side effect recorded)")


# ---------------------------------------------------------------------------
# V11 -- current_skill called exactly once
# ---------------------------------------------------------------------------
def scenario_current_skill_called_once() -> None:
    skill = _RecordingSkill("X")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan, cls=_CountingCurrentSkillExecutor)

    executor.invoke_current_skill()
    check(executor.current_skill_call_count == 1, "V11: current_skill() is called exactly once per invoke_current_skill() call")

    executor.invoke_current_skill()
    check(executor.current_skill_call_count == 2, "V11: a second invoke_current_skill() call brings the current_skill() count to exactly two")


# ---------------------------------------------------------------------------
# V12-V13 -- execute called exactly once (per call)
# ---------------------------------------------------------------------------
def scenario_execute_called_exactly_once() -> None:
    skill = _RecordingSkill("Y")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    executor.invoke_current_skill()
    check(len(skill.calls) == 1, "V12: execute() is called exactly once after a single invoke_current_skill() call")

    executor.invoke_current_skill()
    check(len(skill.calls) == 2, "V13: calling invoke_current_skill() twice in a row invokes execute() exactly twice total")


# ---------------------------------------------------------------------------
# V14-V15 -- execute(None) argument shape
# ---------------------------------------------------------------------------
def scenario_execute_none_argument() -> None:
    skill = _RecordingSkill("Z")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    executor.invoke_current_skill()
    args, kwargs = skill.calls[0]
    check(args == (None,), "V14: the skill's execute() receives exactly one positional argument, and that argument is None")
    check(kwargs == {}, "V15: no keyword arguments are passed to execute()")


# ---------------------------------------------------------------------------
# V16-V18 -- return propagated
# ---------------------------------------------------------------------------
def scenario_return_propagated() -> None:
    sentinel = object()
    skill = _RecordingSkill(sentinel)
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)
    result = executor.invoke_current_skill()
    check(result is sentinel, "V16: invoke_current_skill() returns exactly what execute() returned (identity-preserving)")

    none_skill = _RecordingSkill(None)
    plan_none = SkillExecutionPlan(skills=(none_skill,), tools=(), metadata={})
    executor_none = _running_executor(plan_none)
    result_none = executor_none.invoke_current_skill()
    check(result_none is None, "V17: a None return value from execute() is propagated as None")

    for falsy_value in [0, "", []]:
        falsy_skill = _RecordingSkill(falsy_value)
        plan_falsy = SkillExecutionPlan(skills=(falsy_skill,), tools=(), metadata={})
        executor_falsy = _running_executor(plan_falsy)
        result_falsy = executor_falsy.invoke_current_skill()
        check(
            result_falsy == falsy_value and type(result_falsy) is type(falsy_value),
            f"V18: a falsy-but-not-None return value ({falsy_value!r}) is propagated unchanged",
        )


# ---------------------------------------------------------------------------
# V19-V20 -- exception propagated from execute()
# ---------------------------------------------------------------------------
def scenario_exception_propagated_from_execute() -> None:
    custom_exc = _CustomError("boom")
    skill = _RaisingExecuteSkill(custom_exc)
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    raised_exc = None
    try:
        executor.invoke_current_skill()
    except _CustomError as exc:
        raised_exc = exc
    check(raised_exc is not None, "V19: if execute() raises a custom exception, invoke_current_skill() lets it propagate unchanged")
    check(raised_exc is custom_exc, "V20: the exact exception instance raised by execute() is the one that escapes invoke_current_skill()")
    check(skill.calls == 1, "V19: execute() was actually called once before raising")


# ---------------------------------------------------------------------------
# V21-V22 -- exception propagated from current_skill()
# ---------------------------------------------------------------------------
def scenario_exception_propagated_from_current_skill() -> None:
    executor_missing = _make_executor()
    raised_type = None
    try:
        executor_missing.invoke_current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(raised_type is ExecutorError, "V21: an exception from current_skill() itself (missing session) is not caught or altered by invoke_current_skill()")

    plan = SkillExecutionPlan(skills=(_RecordingSkill("R"),), tools=(), metadata={})
    executor_wrong_state = _make_executor()
    executor_wrong_state.execute_plan(plan)
    raised_type_2 = None
    try:
        executor_wrong_state.invoke_current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type_2 = type(exc)
    check(raised_type_2 is ExecutionSessionError, "V22: an exception from current_skill() itself (wrong state) is not caught or altered by invoke_current_skill()")


# ---------------------------------------------------------------------------
# V23-V24 -- no wrapper
# ---------------------------------------------------------------------------
def scenario_no_wrapper() -> None:
    sentinel = object()
    skill = _RecordingSkill(sentinel)
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    result = executor.invoke_current_skill()
    check(
        not isinstance(result, (list, tuple, dict))
        and type(result) is object
        and result is sentinel,
        "V23: the returned value is not wrapped in any Executor-defined type, list, tuple, or dict",
    )
    check(not hasattr(result, "_executor_metadata"), "V24: invoke_current_skill() does not attach any extra attribute or metadata to the returned value")


# ---------------------------------------------------------------------------
# V25-V26 -- no state mutation
# ---------------------------------------------------------------------------
def scenario_no_state_mutation() -> None:
    skill = _RecordingSkill("R")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    session_before = executor._current_plan
    executor.invoke_current_skill()
    check(executor._current_plan.state == "running", "V25: self._current_plan.state is unchanged (still 'running') after a successful invoke_current_skill() call")
    check(executor._current_plan is session_before, "V26: self._current_plan itself (the whole object, by identity) is unchanged after a successful invoke_current_skill() call")


# ---------------------------------------------------------------------------
# V27-V28 -- no cursor mutation
# ---------------------------------------------------------------------------
def scenario_no_cursor_mutation() -> None:
    skill_a, skill_b = _RecordingSkill("A"), _RecordingSkill("B")
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata={})
    executor = _running_executor(plan)

    executor.invoke_current_skill()
    check(executor._current_plan.current_skill_index == 0, "V27: self._current_plan.current_skill_index is unchanged after invoke_current_skill()")

    for _ in range(5):
        executor.invoke_current_skill()
    check(
        executor._current_plan.current_skill_index == 0 and len(skill_a.calls) == 6 and len(skill_b.calls) == 0,
        "V28: calling invoke_current_skill() several times in a row never changes current_skill_index (always invokes the same skill)",
    )


# ---------------------------------------------------------------------------
# V29 -- no advance
# ---------------------------------------------------------------------------
def scenario_no_advance() -> None:
    skill = _RecordingSkill("R")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan, cls=_NoAdvanceExecutor)

    result = executor.invoke_current_skill()
    check(result == "R", "V29: invoke_current_skill() never calls advance_skill() (proven via a subclass whose advance_skill() raises if called)")


# ---------------------------------------------------------------------------
# V30 -- no metadata access
# ---------------------------------------------------------------------------
def scenario_no_metadata_access() -> None:
    skill = _RecordingSkill("R")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    guarded_session = ExecutionSession(plan=plan, state="pending", metadata=_RaisingMapping())
    guarded_session = guarded_session.with_state("ready")
    guarded_session = guarded_session.start()

    executor = _make_executor()
    executor._current_plan = guarded_session

    result = executor.invoke_current_skill()
    check(result == "R", "V30: a plan/session whose metadata is a mapping subclass that raises on any read access is never touched by invoke_current_skill()")


# ---------------------------------------------------------------------------
# V31 -- no tool access
# ---------------------------------------------------------------------------
def scenario_no_tool_access() -> None:
    skill = _RecordingSkill("R")
    tools = _RaisingToolsTuple(("tool_a",))
    plan = SkillExecutionPlan(skills=(skill,), tools=tools, metadata={})
    executor = _running_executor(plan)

    result = executor.invoke_current_skill()
    check(result == "R", "V31: invoke_current_skill() never reads plan.tools at all")


# ---------------------------------------------------------------------------
# V32 -- no iteration
# ---------------------------------------------------------------------------
def scenario_no_iteration() -> None:
    skill = _RecordingSkill("R")
    skills = _RaisingTuple((skill,))
    tools = _RaisingTuple(("tool_a",))
    plan = SkillExecutionPlan(skills=skills, tools=tools, metadata={})
    executor = _running_executor(plan)

    result = executor.invoke_current_skill()
    check(result == "R", "V32: a plan whose skills/tools tuples raise on __iter__ are never iterated by invoke_current_skill()")


# ---------------------------------------------------------------------------
# V33-V34 -- no delegated calls
# ---------------------------------------------------------------------------
def scenario_no_delegated_calls() -> None:
    guarded_executor = _make_guarded_executor()
    skill = _RecordingSkill("OK")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    guarded_executor.execute_plan(plan)
    guarded_executor.prepare_session()
    guarded_executor.start_session()

    result = guarded_executor.invoke_current_skill()
    check(result == "OK", "V33: invoke_current_skill() never calls AutonomousHost.start/SkillResolver.resolve/any TaskManager method")
    check(len(skill.calls) == 1, "V34: invoke_current_skill() succeeds against fully guarded collaborators as long as the skill itself is well-behaved")


# ---------------------------------------------------------------------------
# V35-V39 -- AST verification of invoke_current_skill()'s own body
# ---------------------------------------------------------------------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.invoke_current_skill))
    tree = ast.parse(source)

    len_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len"
    ]
    check(len_calls == [], "V35: invoke_current_skill()'s body contains no call to len()")

    subscripts = [node for node in ast.walk(tree) if isinstance(node, ast.Subscript)]
    check(subscripts == [], "V36: invoke_current_skill()'s body contains no subscript/indexing expression")

    has_loop_or_try = any(
        isinstance(node, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for node in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V37: invoke_current_skill()'s body contains no for/while/try/comprehension of any kind")

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    call_descriptions = set()
    for call in calls:
        if isinstance(call.func, ast.Attribute):
            call_descriptions.add(call.func.attr)
        elif isinstance(call.func, ast.Name):
            call_descriptions.add(call.func.id)
    check(
        call_descriptions == {"current_skill", "execute"},
        f"V38: invoke_current_skill()'s body calls only self.current_skill() and skill.execute(None) (got {call_descriptions})",
    )

    function_def = tree.body[0]
    check(
        isinstance(function_def, ast.FunctionDef) and isinstance(function_def.body[-1], ast.Return),
        "V38: invoke_current_skill()'s body ends with a bare return statement",
    )

    forbidden_names = {
        "Runtime",
        "Workflow",
        "Planner",
        "EventBus",
        "ToolResolver",
        "ToolManager",
        "AutonomousHost",
        "TaskManager",
        "SkillResolver",
    }
    referenced_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced_attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    check(
        forbidden_names.isdisjoint(referenced_names) and forbidden_names.isdisjoint(referenced_attrs),
        "V39: invoke_current_skill()'s body contains no reference to Runtime/Workflow/Planner/EventBus/ToolResolver/ToolManager/AutonomousHost/TaskManager/SkillResolver by name",
    )


# ---------------------------------------------------------------------------
# V40 -- module-level import verification
# ---------------------------------------------------------------------------
def scenario_module_import_verification() -> None:
    executor_source_path = ROOT / "Orchestration" / "executor.py"
    tree = ast.parse(executor_source_path.read_text())

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)

    expected_modules = {
        "Core.exceptions",
        "Orchestration.autonomous_host",
        "Orchestration.execution_session",
        "Orchestration.skill_execution_plan",
        "Orchestration.skill_resolver",
        "Orchestration.task_manager",
        "__future__",
    }
    check(
        imported_modules == expected_modules,
        f"V40: Orchestration.executor introduces no new top-level import for this sprint (got {imported_modules})",
    )


# ---------------------------------------------------------------------------
# V41 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_namespace_verification() -> None:
    import Orchestration.executor as executor_module

    forbidden_names = [
        "Runtime",
        "Workflow",
        "EventBus",
        "ToolResolver",
        "ToolManager",
        "BaseSkill",
        "BaseTool",
        "Planner",
    ]
    for name in forbidden_names:
        check(not hasattr(executor_module, name), f"V41: Orchestration.executor module does not expose {name}")


# ---------------------------------------------------------------------------
# V42 -- public API verification
# ---------------------------------------------------------------------------
def scenario_public_api_verification() -> None:
    public_methods = {
        name
        for name, value in vars(Executor).items()
        if not name.startswith("_") and callable(value)
    }
    expected = {
        "execute",
        "has_pending_tasks",
        "execute_plan",
        "prepare_session",
        "start_session",
        "advance_skill",
        "current_skill",
        "invoke_current_skill",
    }
    check(public_methods == expected, f"V42: Executor exposes exactly {expected} as its public methods (got {public_methods})")


# ---------------------------------------------------------------------------
# V43-V44 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    skill_x, skill_y = _RecordingSkill("X"), _RecordingSkill("Y")
    plan_1 = SkillExecutionPlan(skills=(skill_x,), tools=(), metadata={})
    plan_2 = SkillExecutionPlan(skills=(skill_y,), tools=(), metadata={})

    executor_1 = _running_executor(plan_1)
    executor_2 = _running_executor(plan_2)

    result_1 = executor_1.invoke_current_skill()
    result_2 = executor_2.invoke_current_skill()
    check(result_1 == "X" and result_2 == "Y", "V43: two Executor instances each invoke their own session's current skill independently")

    check(
        len(skill_x.calls) == 1 and len(skill_y.calls) == 1,
        "V44: invoking one Executor's skill does not affect the other Executor's stored session/cursor",
    )


# ---------------------------------------------------------------------------
# V45-V46 -- no singleton
# ---------------------------------------------------------------------------
def scenario_no_singleton() -> None:
    skill_a = _RecordingSkill("A")
    plan = SkillExecutionPlan(skills=(skill_a,), tools=(), metadata={})

    executor_c = _make_executor()
    executor_d = _make_executor()
    check(executor_c is not executor_d, "V45: two Executor() constructions with identical collaborators are distinct objects")

    executor_c.execute_plan(plan)
    executor_c.prepare_session()
    executor_c.start_session()
    check(not hasattr(executor_d, "_current_plan"), "V45: executor_d has no _current_plan while executor_c does -- independent state, no singleton")

    class _Equal:
        def __eq__(self, other):
            return isinstance(other, _Equal)

        def __hash__(self):
            return 1

        def execute(self, *args, **kwargs):
            return "EQUAL_RESULT"

    equal_a, equal_b = _Equal(), _Equal()
    check(equal_a == equal_b and equal_a is not equal_b, "V46 setup: two distinct-but-equal skill objects")

    plan_a = SkillExecutionPlan(skills=(equal_a,), tools=(), metadata={})
    plan_b = SkillExecutionPlan(skills=(equal_b,), tools=(), metadata={})
    exec_a = _running_executor(plan_a)
    exec_b = _running_executor(plan_b)

    result_a = exec_a.invoke_current_skill()
    result_b = exec_b.invoke_current_skill()
    check(
        result_a == "EQUAL_RESULT" and result_b == "EQUAL_RESULT" and exec_a is not exec_b,
        "V46: two invoke_current_skill() calls on two value-equal-but-distinct running sessions with equal but distinct skill objects produce independent results",
    )


# ---------------------------------------------------------------------------
# V47-V48 -- pre-existing behavior unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_behavior_unaffected() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host)

    check(executor.has_pending_tasks() is False, "V47: has_pending_tasks() still works and reports no pending tasks on an empty queue")

    raised = False
    try:
        executor.execute(context=None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V47: execute(context=None) still raises ExecutorError, unaffected by this sprint")

    executed_count = executor.execute(context="ctx", iterations=1)
    check(executed_count == 0, "V47: execute() on an empty queue still returns 0, unaffected by this sprint")

    skill_0, skill_1 = _RecordingSkill("S0"), _RecordingSkill("S1")
    plan = SkillExecutionPlan(skills=(skill_0, skill_1), tools=(), metadata={})
    executor.execute_plan(plan)
    check(executor._current_plan.state == "pending", "V47: execute_plan() still stores a pending session, unaffected by this sprint")

    executor.prepare_session()
    check(executor._current_plan.state == "ready", "V47: prepare_session() still advances pending -> ready, unaffected by this sprint")

    executor.start_session()
    check(executor._current_plan.state == "running", "V47: start_session() still advances ready -> running, unaffected by this sprint")

    check(executor.current_skill() is skill_0, "V47: current_skill() still returns the skill at the current index, unaffected by this sprint")

    executor.advance_skill()
    check(executor._current_plan.current_skill_index == 1, "V47: advance_skill() still increments the cursor, unaffected by this sprint")
    check(executor.current_skill() is skill_1, "V47: current_skill() reflects the new cursor after advance_skill(), unaffected by this sprint")

    session_a = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    check(session_a == session_b, "V48: ExecutionSession equality is unaffected by this sprint")
    check(hash(session_a) == hash(id(plan)), "V48: ExecutionSession hash is unaffected by this sprint")

    with_state_result = session_a.with_state("ready")
    check(with_state_result.state == "ready", "V48: ExecutionSession.with_state() is unaffected by this sprint")

    start_result = with_state_result.start()
    check(start_result.state == "running", "V48: ExecutionSession.start() is unaffected by this sprint")

    advance_result = start_result.advance()
    check(advance_result.current_skill_index == 1, "V48: ExecutionSession.advance() is unaffected by this sprint")

    raised = False
    try:
        ExecutionSession(plan="not-a-plan", state="pending", metadata={})  # type: ignore[arg-type]
    except ExecutionSessionError:
        raised = True
    check(raised, "V48: ExecutionSession construction validation is unaffected by this sprint")


# ---------------------------------------------------------------------------
# V49 -- execute() unmodified
# ---------------------------------------------------------------------------
def scenario_execute_unmodified() -> None:
    skill = _RecordingSkill("S0")
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)
    executor.invoke_current_skill()

    session_before = executor._current_plan
    executed_count = executor.execute(context="ctx", iterations=1)

    check(executed_count == 0, "V49: execute() on an empty task queue still returns 0")
    check(executor._current_plan is session_before, "V49: execute() never touches self._current_plan")


# ---------------------------------------------------------------------------
# V50 -- current_skill() unmodified
# ---------------------------------------------------------------------------
def scenario_current_skill_unmodified() -> None:
    skill_a, skill_b = _RecordingSkill("A"), _RecordingSkill("B")
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata={})
    executor = _running_executor(plan)

    check(executor.current_skill() is skill_a, "V50: current_skill() directly still returns by identity, unaffected by this sprint")
    check(len(skill_a.calls) == 0, "V50: current_skill() still does not invoke execute() on the skill")

    executor.advance_skill()
    executor.advance_skill()
    raised_type = None
    try:
        executor.current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(raised_type is IndexError, "V50: current_skill() still performs no bounds check (a plain IndexError surfaces unchanged)")


# ---------------------------------------------------------------------------
# V51 -- full chain
# ---------------------------------------------------------------------------
def scenario_full_chain() -> None:
    skill_a, skill_b = _RecordingSkill("A_RESULT"), _RecordingSkill("B_RESULT")
    metadata = {"k": "v"}
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata=metadata)

    executor = _make_executor()
    executor.execute_plan(plan)
    check(executor._current_plan.plan is plan, "V51: plan identity intact after execute_plan()")

    executor.prepare_session()
    check(executor._current_plan.state == "ready", "V51: prepare_session() advances to 'ready'")

    executor.start_session()
    check(executor._current_plan.state == "running", "V51: start_session() advances to 'running'")

    first_result = executor.invoke_current_skill()
    check(first_result == "A_RESULT", "V51: invoke_current_skill() invokes skill_a while at index 0")

    executor.advance_skill()
    second_result = executor.invoke_current_skill()
    check(second_result == "B_RESULT", "V51: invoke_current_skill() invokes skill_b after advance_skill()")

    check(len(skill_a.calls) == 1 and len(skill_b.calls) == 1, "V51: each skill was invoked exactly once at its own step")
    check(
        executor._current_plan.plan is plan and executor._current_plan.plan.metadata == metadata,
        "V51: plan/metadata identity intact throughout the full chain",
    )


# ---------------------------------------------------------------------------
# V52 -- signature
# ---------------------------------------------------------------------------
def scenario_signature() -> None:
    signature = inspect.signature(Executor.invoke_current_skill)
    params = [name for name in signature.parameters if name != "self"]
    check(params == [], "V52: invoke_current_skill() takes no positional/keyword arguments beyond self")


# ---------------------------------------------------------------------------
# V53 -- skill returning itself
# ---------------------------------------------------------------------------
def scenario_skill_returning_itself() -> None:
    skill = _SelfReturningSkill()
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    result = executor.invoke_current_skill()
    check(result is skill, "V53: invoke_current_skill() correctly returns a skill's own execute() result even when that result is the skill object itself")


def main() -> int:
    scenarios = [
        scenario_missing_session,
        scenario_pending_state,
        scenario_ready_state,
        scenario_arbitrary_state,
        scenario_running_state_success,
        scenario_current_skill_called_once,
        scenario_execute_called_exactly_once,
        scenario_execute_none_argument,
        scenario_return_propagated,
        scenario_exception_propagated_from_execute,
        scenario_exception_propagated_from_current_skill,
        scenario_no_wrapper,
        scenario_no_state_mutation,
        scenario_no_cursor_mutation,
        scenario_no_advance,
        scenario_no_metadata_access,
        scenario_no_tool_access,
        scenario_no_iteration,
        scenario_no_delegated_calls,
        scenario_ast_verification,
        scenario_module_import_verification,
        scenario_namespace_verification,
        scenario_public_api_verification,
        scenario_multi_instance_independence,
        scenario_no_singleton,
        scenario_pre_existing_behavior_unaffected,
        scenario_execute_unmodified,
        scenario_current_skill_unmodified,
        scenario_full_chain,
        scenario_signature,
        scenario_skill_returning_itself,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 7 SPRINT 78 EXECUTOR-INVOKE-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())