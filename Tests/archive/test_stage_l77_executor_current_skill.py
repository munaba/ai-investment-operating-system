"""
Phase 7 Sprint 77 proof suite -- ``Executor.current_skill()`` (a single
new public method that reads the currently selected Skill out of the
currently stored ``ExecutionSession``, based on
``ExecutionSession.current_skill_index``). Execution remains
completely disabled: this sprint only allows *reading* the selected
Skill -- no Skill is executed, no Tool is executed or inspected, no
metadata is inspected, and
``execute()``/``has_pending_tasks()``/``execute_plan()``/
``prepare_session()``/``start_session()``/``advance_skill()``/the
constructor are all unchanged.

Scope: dedicated regression suite for the Sprint 77 addition only.
``SkillExecutionPlan`` (Sprint 71), the general shape of
``Executor.execute_plan`` (Sprint 72), ``ExecutionSession``'s
existing fields/validation/hash (Sprint 73), ``with_state``/
``prepare_session`` (Sprint 74), ``start``/``start_session``
(Sprint 75), and ``current_skill_index``/``advance``/
``advance_skill()`` (Sprint 76) are unchanged by this sprint -- this
suite does not re-verify their own internal behavior beyond
confirming Sprint 77 introduces no regression to them.

``Executor.current_skill()`` never executes a skill or a tool, is
never wired into ``Runtime``, ``Workflow``, ``Host``, ``EventBus``, or
``Planner``, and never iterates ``plan.skills``/``plan.tools`` or
inspects ``plan.metadata`` (proven both by direct behavioral tests --
using a plan whose fields raise on iteration, and skill stand-ins
that raise on any attribute access/call -- and by AST-level import
inspection of the module source file). ``current_skill()`` performs
no bounds checking, no normalization, no fallback, and introduces no
loop of any kind.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L4x/L5x/L6x/L7x proof suites (mirroring
``Tests.test_stage_l76_execution_current_skill`` in particular): a
global pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage (target 45+):
    V1  -- running success: current_skill() on a running session with
           a non-empty skills tuple returns the skill at index 0.
    V2  -- running success: the returned object is the exact same
           object (``is``) as ``plan.skills[0]`` -- no copy, no
           wrapper.
    V3  -- index respected: after one advance_skill() call,
           current_skill() returns ``plan.skills[1]``.
    V4  -- index respected: after two advance_skill() calls,
           current_skill() returns ``plan.skills[2]``.
    V5  -- index respected: current_skill() reads whatever
           current_skill_index the stored session currently holds,
           not always index 0.
    V6  -- identity preservation: repeated current_skill() calls (no
           advance in between) return the exact same object each
           time.
    V7  -- duplicate skill handling: a plan whose skills tuple
           contains the same object at two different indices returns
           that same object at both indices (identity-based lookup,
           not a search).
    V8  -- duplicate skill handling: a plan whose skills tuple
           contains two distinct-but-equal objects returns the
           specific object at the requested index, not merely an
           equal one.
    V9  -- pending rejection: current_skill() on a "pending" session
           raises ExecutionSessionError.
    V10 -- pending rejection: the ExecutionSessionError message
           mentions the actual current state ("pending").
    V11 -- ready rejection: current_skill() on a "ready" session
           raises ExecutionSessionError.
    V12 -- ready rejection: the ExecutionSessionError message
           mentions the actual current state ("ready").
    V13 -- arbitrary-state rejection: current_skill() on an
           arbitrary non-running state ("done") raises
           ExecutionSessionError.
    V14 -- missing session: current_skill() with no prior
           execute_plan() call raises ExecutorError.
    V15 -- missing session: the ExecutorError message references
           execute_plan().
    V16 -- missing session: calling current_skill() with no prior
           execute_plan() call never creates a _current_plan
           attribute as a side effect.
    V17 -- no execution: a plan whose skills are guarded stand-ins
           that raise on any attribute access/call is never touched
           beyond being returned -- current_skill() itself does not
           trigger any of those guards.
    V18 -- no execution: the returned guarded skill's guard is only
           triggered if the caller of this test explicitly pokes it
           (proving current_skill() itself performs zero access).
    V19 -- no iteration: a plan whose skills/tools tuples raise on
           __iter__ are never iterated by current_skill().
    V20 -- no iteration: current_skill() succeeds even when
           plan.tools is a tuple subclass that raises on __iter__.
    V21 -- metadata untouched: a plan/session whose metadata is a
           mapping subclass that raises on any read access is never
           touched by current_skill().
    V22 -- tools untouched: current_skill() never reads plan.tools at
           all (a tools tuple that raises on __len__/__getitem__ is
           never touched).
    V23 -- returned object exact identity: current_skill() returns
           plan.skills[current_skill_index] itself, verified via
           id() equality, not just ``==``.
    V24 -- no bounds checking: current_skill_index equal to
           len(plan.skills) raises the natural IndexError from tuple
           indexing (no ExecutorError/ExecutionSessionError swallowing
           or translating it).
    V25 -- no bounds checking: current_skill_index far beyond
           len(plan.skills) still raises a plain IndexError, not any
           custom exception type.
    V26 -- no bounds checking: current_skill() performs no length
           check against plan.skills before indexing (proven by the
           IndexError itself surfacing unchanged, and by AST
           inspection showing no len() call in the method body).
    V27 -- single-skill plan: a plan with exactly one skill returns
           that skill at index 0.
    V28 -- empty-skills plan at index 0 raises IndexError (natural
           tuple indexing failure), not swallowed by current_skill().
    V29 -- multi-instance independence: two Executor instances each
           expose their own session's current skill independently.
    V30 -- multi-instance independence: advancing one Executor's
           cursor does not affect the other Executor's current_skill()
           result.
    V31 -- no singleton: two Executor() constructions with identical
           collaborators are distinct objects, each with its own
           independent _current_plan/current_skill() result.
    V32 -- exception propagation: exception type exactness --
           current_skill() on a non-running session raises exactly
           ExecutionSessionError (not a subclass masquerading, not
           ExecutorError).
    V33 -- exception propagation: current_skill() on a missing
           session raises exactly ExecutorError (not
           ExecutionSessionError).
    V34 -- exception propagation: a failed current_skill() call
           (missing session) leaves no _current_plan attribute
           behind.
    V35 -- exception propagation: a failed current_skill() call
           (wrong state) leaves self._current_plan completely
           unchanged (same object, by identity).
    V36 -- AST verification: Orchestration.executor's current_skill()
           method body contains no call to any of execute/start/
           resolve/append/sorted/list/iter/len.
    V37 -- AST verification: current_skill() method body contains no
           for-loop, while-loop, comprehension, or try/except of any
           kind.
    V38 -- AST verification: current_skill() method body references
           only ``self._current_plan``, ``self._current_plan.state``,
           ``self._current_plan.plan``,
           ``self._current_plan.plan.skills``, and
           ``self._current_plan.current_skill_index`` as its data
           reads (plus the two raised exception types).
    V39 -- namespace verification: Orchestration.executor module does
           not expose Runtime/Workflow/EventBus/ToolResolver/
           ToolManager/BaseSkill/BaseTool/Planner symbols.
    V40 -- public API verification: Executor exposes exactly
           {"execute", "has_pending_tasks", "execute_plan",
           "prepare_session", "start_session", "advance_skill",
           "current_skill"} as its public methods.
    V41 -- no delegated calls: current_skill() never calls
           AutonomousHost.start/SkillResolver.resolve/any TaskManager
           method (guarded stubs raise on any call).
    V42 -- pre-existing behavior unaffected: execute(),
           has_pending_tasks(), execute_plan(), prepare_session(),
           start_session(), advance_skill() all still behave exactly
           as before this sprint.
    V43 -- pre-existing behavior unaffected: ExecutionSession's own
           validation/hash/equality/with_state/start/advance are all
           unaffected by this sprint.
    V44 -- execute() unmodified: calling Executor.execute() still
           never touches self._current_plan.
    V45 -- full chain: pending -> ready -> running -> current_skill()
           -> advance_skill() -> current_skill() returns the correct
           skill at each step, with plan/metadata identity intact
           throughout.
    V46 -- current_skill() called twice in a row (no state change in
           between) returns the exact same object both times.
    V47 -- current_skill() does not require ``context`` or any
           argument at all -- it takes no positional/keyword
           arguments beyond ``self``.
    V48 -- current_skill() returns None correctly when the plan
           contains ``None`` as a skill entry (identity, not falsy-
           value special-casing).
"""

from __future__ import annotations

import ast
import inspect
import textwrap
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
    raises on any ``start``/``stop`` call, proving ``current_skill``
    never delegates to it."""

    def start(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("current_skill must never call AutonomousHost.start()")

    def stop(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("current_skill must never call AutonomousHost.stop()")


class _GuardedSkillResolver(SkillResolver):
    """A SkillResolver subclass (so ``isinstance`` checks pass) that
    raises on any ``resolve`` call, proving ``current_skill`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip SkillResolver.__init__

    def resolve(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("current_skill must never call SkillResolver.resolve()")


class _GuardedTaskManager(TaskManager):
    """A TaskManager subclass (so ``isinstance`` checks pass) that
    raises on any method call, proving ``current_skill`` never
    delegates to it."""

    def __init__(self):
        pass  # deliberately skip TaskManager.__init__

    def has_tasks(self):  # type: ignore[override]
        raise AssertionError("current_skill must never call TaskManager.has_tasks()")

    def next_task(self):  # type: ignore[override]
        raise AssertionError("current_skill must never call TaskManager.next_task()")


class _RaisingTuple(tuple):
    """A tuple subclass that raises on iteration, proving a plan's
    skills/tools are never iterated by current_skill()."""

    def __iter__(self):
        raise AssertionError("must never iterate this tuple")


class _RaisingLenTuple(tuple):
    """A tuple subclass that raises on __len__, proving current_skill()
    never checks the length of plan.tools/plan.skills."""

    def __len__(self):
        raise AssertionError("must never call len() on this tuple")


class _GuardedSkill:
    """A skill stand-in that raises on any attribute access, method
    call, or invocation -- proving current_skill() never touches a
    resolved skill object beyond returning it by identity."""

    def __getattr__(self, item):
        raise AssertionError(f"must never access skill.{item}")

    def execute(self, *args, **kwargs):
        raise AssertionError("must never call skill.execute()")

    def __call__(self, *args, **kwargs):
        raise AssertionError("must never call a skill object")


class _RaisingMapping(dict):
    """A mapping subclass that raises on any read access, proving
    current_skill() never inspects plan/session metadata."""

    def __getitem__(self, item):
        raise AssertionError("must never read metadata")

    def get(self, *args, **kwargs):
        raise AssertionError("must never read metadata via get()")

    def __iter__(self):
        raise AssertionError("must never iterate metadata")


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


def _running_executor(plan) -> Executor:
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor


# ---------------------------------------------------------------------------
# V1-V2 -- running success, exact identity
# ---------------------------------------------------------------------------
def scenario_running_success_basic() -> None:
    skill_a, skill_b, skill_c = object(), object(), object()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b, skill_c), tools=(), metadata={})
    executor = _running_executor(plan)

    result = executor.current_skill()
    check(result is skill_a, "V1: current_skill() on a running session returns the skill at index 0")
    check(id(result) == id(plan.skills[0]), "V2: the returned object is the exact same object as plan.skills[0]")


# ---------------------------------------------------------------------------
# V3-V5 -- index respected
# ---------------------------------------------------------------------------
def scenario_index_respected() -> None:
    skill_a, skill_b, skill_c = object(), object(), object()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b, skill_c), tools=(), metadata={})
    executor = _running_executor(plan)

    executor.advance_skill()
    check(executor.current_skill() is skill_b, "V3: after one advance_skill(), current_skill() returns plan.skills[1]")

    executor.advance_skill()
    check(executor.current_skill() is skill_c, "V4: after two advance_skill() calls, current_skill() returns plan.skills[2]")

    check(
        executor._current_plan.current_skill_index == 2
        and executor.current_skill() is plan.skills[executor._current_plan.current_skill_index],
        "V5: current_skill() reads whatever current_skill_index the stored session currently holds",
    )


# ---------------------------------------------------------------------------
# V6 -- identity preservation across repeated calls
# ---------------------------------------------------------------------------
def scenario_repeated_calls_identity() -> None:
    skill_a = object()
    plan = SkillExecutionPlan(skills=(skill_a,), tools=(), metadata={})
    executor = _running_executor(plan)

    first = executor.current_skill()
    second = executor.current_skill()
    check(first is second, "V6: repeated current_skill() calls return the exact same object each time")
    check(first is skill_a, "V6: that object is the exact skill given in the plan")


# ---------------------------------------------------------------------------
# V7-V8 -- duplicate skill handling
# ---------------------------------------------------------------------------
def scenario_duplicate_skill_handling() -> None:
    shared_skill = object()
    plan = SkillExecutionPlan(skills=(shared_skill, shared_skill), tools=(), metadata={})
    executor = _running_executor(plan)

    at_zero = executor.current_skill()
    executor.advance_skill()
    at_one = executor.current_skill()
    check(at_zero is shared_skill and at_one is shared_skill, "V7: a plan whose skills tuple contains the same object at two indices returns that object at both")

    class _Equal:
        def __eq__(self, other):
            return isinstance(other, _Equal)

        def __hash__(self):
            return 1

    equal_a, equal_b = _Equal(), _Equal()
    check(equal_a == equal_b and equal_a is not equal_b, "V8 setup: two distinct-but-equal objects")
    plan2 = SkillExecutionPlan(skills=(equal_a, equal_b), tools=(), metadata={})
    executor2 = _running_executor(plan2)
    result0 = executor2.current_skill()
    executor2.advance_skill()
    result1 = executor2.current_skill()
    check(
        result0 is equal_a and result0 is not equal_b,
        "V8: current_skill() returns the specific object at index 0, not merely an equal one",
    )
    check(
        result1 is equal_b and result1 is not equal_a,
        "V8: current_skill() returns the specific object at index 1, not merely an equal one",
    )


# ---------------------------------------------------------------------------
# V9-V10 -- pending rejection
# ---------------------------------------------------------------------------
def scenario_pending_rejection() -> None:
    plan = SkillExecutionPlan(skills=("S0",), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)

    raised = False
    message = ""
    try:
        executor.current_skill()
    except ExecutionSessionError as exc:
        raised = True
        message = str(exc)
    check(raised, "V9: current_skill() on a 'pending' session raises ExecutionSessionError")
    check("pending" in message, "V10: the ExecutionSessionError message mentions the actual current state ('pending')")


# ---------------------------------------------------------------------------
# V11-V12 -- ready rejection
# ---------------------------------------------------------------------------
def scenario_ready_rejection() -> None:
    plan = SkillExecutionPlan(skills=("S0",), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()

    raised = False
    message = ""
    try:
        executor.current_skill()
    except ExecutionSessionError as exc:
        raised = True
        message = str(exc)
    check(raised, "V11: current_skill() on a 'ready' session raises ExecutionSessionError")
    check("ready" in message, "V12: the ExecutionSessionError message mentions the actual current state ('ready')")


# ---------------------------------------------------------------------------
# V13 -- arbitrary-state rejection
# ---------------------------------------------------------------------------
def scenario_arbitrary_state_rejection() -> None:
    plan = SkillExecutionPlan(skills=("S0",), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor._current_plan = executor._current_plan.with_state("done")

    raised = False
    try:
        executor.current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V13: current_skill() on an arbitrary non-running state ('done') raises ExecutionSessionError")


# ---------------------------------------------------------------------------
# V14-V16 -- missing session
# ---------------------------------------------------------------------------
def scenario_missing_session() -> None:
    executor = _make_executor()

    raised = False
    message = ""
    try:
        executor.current_skill()
    except ExecutorError as exc:
        raised = True
        message = str(exc)
    check(raised, "V14: current_skill() with no prior execute_plan() call raises ExecutorError")
    check("execute_plan" in message, "V15: the ExecutorError message references execute_plan()")
    check(not hasattr(executor, "_current_plan"), "V16: no _current_plan attribute is created as a side effect")


# ---------------------------------------------------------------------------
# V17-V18 -- no execution
# ---------------------------------------------------------------------------
def scenario_no_skill_execution() -> None:
    guarded_skill = _GuardedSkill()
    plan = SkillExecutionPlan(skills=(guarded_skill,), tools=(), metadata={})
    executor = _running_executor(plan)

    result = executor.current_skill()
    check(result is guarded_skill, "V17: current_skill() returns the guarded skill stand-in without touching it")

    poked = False
    try:
        result.execute()
    except AssertionError:
        poked = True
    check(poked, "V18: the returned guarded skill's guard only triggers when explicitly poked, proving current_skill() itself performed zero access")


# ---------------------------------------------------------------------------
# V19-V20 -- no iteration
# ---------------------------------------------------------------------------
def scenario_no_iteration() -> None:
    skills = _RaisingTuple((object(), object()))
    tools = _RaisingTuple(("tool_a",))
    plan = SkillExecutionPlan(skills=skills, tools=tools, metadata={})
    executor = _running_executor(plan)

    result = executor.current_skill()
    check(result is skills[0], "V19: current_skill() never iterates plan.skills (a raising-__iter__ tuple works fine)")
    check(True, "V20: current_skill() succeeds even when plan.tools raises on __iter__ (never touched)")


# ---------------------------------------------------------------------------
# V21 -- metadata untouched
# ---------------------------------------------------------------------------
def scenario_metadata_untouched() -> None:
    skill_a = object()
    plan = SkillExecutionPlan(skills=(skill_a,), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()

    # Swap in a raising-metadata session by identity, preserving state/plan/index.
    guarded_session = ExecutionSession(
        plan=plan, state="pending", metadata=_RaisingMapping()
    )
    guarded_session = guarded_session.with_state("ready")
    guarded_session = guarded_session.start()
    executor._current_plan = guarded_session

    result = executor.current_skill()
    check(result is skill_a, "V21: current_skill() never touches a metadata mapping that raises on any read access")


# ---------------------------------------------------------------------------
# V22 -- tools untouched
# ---------------------------------------------------------------------------
def scenario_tools_untouched() -> None:
    class _RaisingLenGetitemTuple(tuple):
        def __len__(self):
            raise AssertionError("must never call len() on plan.tools")

        def __getitem__(self, item):
            raise AssertionError("must never index plan.tools")

    skill_a = object()
    tools = _RaisingLenGetitemTuple(("tool_a", "tool_b"))
    plan = SkillExecutionPlan(skills=(skill_a,), tools=tools, metadata={})
    executor = _running_executor(plan)

    result = executor.current_skill()
    check(result is skill_a, "V22: current_skill() never reads plan.tools at all")


# ---------------------------------------------------------------------------
# V23 -- returned object exact identity via id()
# ---------------------------------------------------------------------------
def scenario_exact_identity_via_id() -> None:
    skill_a = object()
    plan = SkillExecutionPlan(skills=(skill_a,), tools=(), metadata={})
    executor = _running_executor(plan)

    result = executor.current_skill()
    check(id(result) == id(plan.skills[0]), "V23: current_skill() returns plan.skills[current_skill_index] itself, verified via id()")


# ---------------------------------------------------------------------------
# V24-V26 -- no bounds checking
# ---------------------------------------------------------------------------
def scenario_no_bounds_checking() -> None:
    plan = SkillExecutionPlan(skills=("S0", "S1"), tools=(), metadata={})
    executor = _running_executor(plan)

    executor.advance_skill()
    executor.advance_skill()  # current_skill_index now == len(plan.skills) == 2

    raised_type = None
    try:
        executor.current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(raised_type is IndexError, "V24: current_skill_index == len(plan.skills) raises a plain IndexError")

    executor2 = _running_executor(plan)
    for _ in range(10):
        executor2.advance_skill()  # current_skill_index far beyond len(plan.skills)

    raised_type_2 = None
    try:
        executor2.current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type_2 = type(exc)
    check(raised_type_2 is IndexError, "V25: current_skill_index far beyond len(plan.skills) still raises a plain IndexError")

    source = textwrap.dedent(inspect.getsource(Executor.current_skill))
    tree = ast.parse(source)
    len_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
    ]
    check(len_calls == [], "V26: current_skill() performs no len() call anywhere in its body")


# ---------------------------------------------------------------------------
# V27-V28 -- single-skill and empty-skills plans
# ---------------------------------------------------------------------------
def scenario_single_and_empty_skill_plans() -> None:
    only_skill = object()
    plan = SkillExecutionPlan(skills=(only_skill,), tools=(), metadata={})
    executor = _running_executor(plan)
    check(executor.current_skill() is only_skill, "V27: a plan with exactly one skill returns that skill at index 0")

    empty_plan = SkillExecutionPlan(skills=(), tools=(), metadata={})
    empty_executor = _running_executor(empty_plan)
    raised_type = None
    try:
        empty_executor.current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(raised_type is IndexError, "V28: an empty-skills plan at index 0 raises a plain IndexError, not swallowed")


# ---------------------------------------------------------------------------
# V29-V31 -- multi-instance independence / no singleton
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    skill_x, skill_y = object(), object()
    plan_1 = SkillExecutionPlan(skills=(skill_x,), tools=(), metadata={})
    plan_2 = SkillExecutionPlan(skills=(skill_y,), tools=(), metadata={})

    executor_1 = _running_executor(plan_1)
    executor_2 = _running_executor(plan_2)

    check(
        executor_1.current_skill() is skill_x and executor_2.current_skill() is skill_y,
        "V29: two Executor instances each expose their own session's current skill independently",
    )

    plan_multi = SkillExecutionPlan(skills=(skill_x, skill_y), tools=(), metadata={})
    executor_a = _running_executor(plan_multi)
    executor_b = _running_executor(plan_multi)
    executor_a.advance_skill()

    check(
        executor_a.current_skill() is skill_y and executor_b.current_skill() is skill_x,
        "V30: advancing one Executor's cursor does not affect the other Executor's current_skill() result",
    )

    executor_c = _make_executor()
    executor_d = _make_executor()
    check(executor_c is not executor_d, "V31: two Executor() constructions with identical collaborators are distinct objects")
    executor_c.execute_plan(plan_multi)
    executor_c.prepare_session()
    executor_c.start_session()
    check(
        not hasattr(executor_d, "_current_plan"),
        "V31: executor_d has no _current_plan while executor_c does -- independent state, no singleton",
    )


# ---------------------------------------------------------------------------
# V32-V35 -- exception propagation
# ---------------------------------------------------------------------------
def scenario_exception_propagation() -> None:
    plan = SkillExecutionPlan(skills=("S0",), tools=(), metadata={})

    executor = _make_executor()
    executor.execute_plan(plan)
    raised_type = None
    try:
        executor.current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(raised_type is ExecutionSessionError, "V32: current_skill() on a non-running session raises exactly ExecutionSessionError")

    executor_missing = _make_executor()
    raised_type_missing = None
    try:
        executor_missing.current_skill()
    except Exception as exc:  # noqa: BLE001
        raised_type_missing = type(exc)
    check(raised_type_missing is ExecutorError, "V33: current_skill() on a missing session raises exactly ExecutorError")
    check(not hasattr(executor_missing, "_current_plan"), "V34: a failed current_skill() call (missing session) leaves no _current_plan attribute behind")

    session_before = executor._current_plan
    try:
        executor.current_skill()
    except ExecutionSessionError:
        pass
    check(executor._current_plan is session_before, "V35: a failed current_skill() call (wrong state) leaves self._current_plan completely unchanged")


# ---------------------------------------------------------------------------
# V36-V38 -- AST verification
# ---------------------------------------------------------------------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.current_skill))
    tree = ast.parse(source)

    forbidden_call_names = {"execute", "start", "resolve", "append", "sorted", "list", "iter", "len"}
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attrs = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    check(
        forbidden_call_names.isdisjoint(called_names) and forbidden_call_names.isdisjoint(called_attrs),
        "V36: current_skill()'s body contains no call to execute/start/resolve/append/sorted/list/iter/len",
    )

    has_loop_or_try = any(
        isinstance(node, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for node in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V37: current_skill()'s body contains no for/while/try/comprehension of any kind")

    attribute_chains = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                attribute_chains.add(".".join(reversed(parts)))

    allowed_chains = {
        "self._current_plan",
        "self._current_plan.state",
        "self._current_plan.plan",
        "self._current_plan.plan.skills",
        "self._current_plan.current_skill_index",
    }
    check(
        attribute_chains <= allowed_chains,
        f"V38: current_skill()'s body references only the sanctioned attribute chains (got {attribute_chains})",
    )


# ---------------------------------------------------------------------------
# V39 -- namespace verification
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
        check(not hasattr(executor_module, name), f"V39: Orchestration.executor module does not expose {name}")


# ---------------------------------------------------------------------------
# V40 -- public API verification
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
    }
    check(public_methods == expected, f"V40: Executor exposes exactly {expected} as its public methods (got {public_methods})")


# ---------------------------------------------------------------------------
# V41 -- no delegated calls
# ---------------------------------------------------------------------------
def scenario_no_delegated_calls() -> None:
    guarded_executor = _make_guarded_executor()
    plan = SkillExecutionPlan(skills=("S0", "S1"), tools=(), metadata={})
    guarded_executor.execute_plan(plan)
    guarded_executor.prepare_session()
    guarded_executor.start_session()

    result = guarded_executor.current_skill()
    check(result == "S0", "V41: current_skill() succeeds against guarded collaborators without ever calling AutonomousHost.start/SkillResolver.resolve/any TaskManager method")

    guarded_executor.advance_skill()
    result_2 = guarded_executor.current_skill()
    check(result_2 == "S1", "V41: current_skill() still works correctly across advance_skill() with guarded collaborators untouched")


# ---------------------------------------------------------------------------
# V42-V43 -- pre-existing behavior unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_behavior_unaffected() -> None:
    task_manager = TaskManager(TaskQueue())
    host = AutonomousHost()
    executor = Executor(task_manager=task_manager, host=host)

    check(executor.has_pending_tasks() is False, "V42: has_pending_tasks() still works and reports no pending tasks on an empty queue")

    raised = False
    try:
        executor.execute(context=None)  # type: ignore[arg-type]
    except ExecutorError:
        raised = True
    check(raised, "V42: execute(context=None) still raises ExecutorError, unaffected by this sprint")

    executed_count = executor.execute(context="ctx", iterations=1)
    check(executed_count == 0, "V42: execute() on an empty queue still returns 0, unaffected by this sprint")

    plan = SkillExecutionPlan(skills=("S0",), tools=(), metadata={})
    executor.execute_plan(plan)
    check(executor._current_plan.state == "pending", "V42: execute_plan() still stores a pending session, unaffected by this sprint")

    executor.prepare_session()
    check(executor._current_plan.state == "ready", "V42: prepare_session() still advances pending -> ready, unaffected by this sprint")

    executor.start_session()
    check(executor._current_plan.state == "running", "V42: start_session() still advances ready -> running, unaffected by this sprint")

    executor.advance_skill()
    check(executor._current_plan.current_skill_index == 1, "V42: advance_skill() still increments the cursor, unaffected by this sprint")

    session_a = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    session_b = ExecutionSession(plan=plan, state="pending", metadata={"k": "v"})
    check(session_a == session_b, "V43: ExecutionSession equality is unaffected by this sprint")
    check(hash(session_a) == hash(id(plan)), "V43: ExecutionSession hash is unaffected by this sprint")

    with_state_result = session_a.with_state("ready")
    check(with_state_result.state == "ready", "V43: ExecutionSession.with_state() is unaffected by this sprint")

    start_result = with_state_result.start()
    check(start_result.state == "running", "V43: ExecutionSession.start() is unaffected by this sprint")

    advance_result = start_result.advance()
    check(advance_result.current_skill_index == 1, "V43: ExecutionSession.advance() is unaffected by this sprint")

    raised = False
    try:
        ExecutionSession(plan="not-a-plan", state="pending", metadata={})  # type: ignore[arg-type]
    except ExecutionSessionError:
        raised = True
    check(raised, "V43: ExecutionSession construction validation is unaffected by this sprint")


# ---------------------------------------------------------------------------
# V44 -- execute() unmodified
# ---------------------------------------------------------------------------
def scenario_execute_unmodified() -> None:
    executor = _make_executor()
    plan = SkillExecutionPlan(skills=("S0",), tools=(), metadata={})
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    executor.current_skill()

    session_before = executor._current_plan
    executed_count = executor.execute(context="ctx", iterations=1)

    check(executed_count == 0, "V44: execute() on an empty task queue still returns 0")
    check(executor._current_plan is session_before, "V44: execute() never touches self._current_plan")


# ---------------------------------------------------------------------------
# V45 -- full chain
# ---------------------------------------------------------------------------
def scenario_full_chain() -> None:
    skill_a, skill_b = object(), object()
    metadata = {"k": "v"}
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata=metadata)

    executor = _make_executor()
    executor.execute_plan(plan)
    check(executor._current_plan.plan is plan, "V45: plan identity intact after execute_plan()")

    executor.prepare_session()
    check(executor._current_plan.state == "ready", "V45: prepare_session() advances to 'ready'")

    executor.start_session()
    check(executor._current_plan.state == "running", "V45: start_session() advances to 'running'")

    first = executor.current_skill()
    check(first is skill_a, "V45: current_skill() returns skill_a while at index 0")

    executor.advance_skill()
    second = executor.current_skill()
    check(second is skill_b, "V45: current_skill() returns skill_b after advance_skill()")

    check(
        executor._current_plan.plan is plan and executor._current_plan.plan.metadata == metadata,
        "V45: plan/metadata identity intact throughout the full chain",
    )


# ---------------------------------------------------------------------------
# V46 -- back-to-back identical calls
# ---------------------------------------------------------------------------
def scenario_back_to_back_identical_calls() -> None:
    skill_a = object()
    plan = SkillExecutionPlan(skills=(skill_a,), tools=(), metadata={})
    executor = _running_executor(plan)

    first_call = executor.current_skill()
    second_call = executor.current_skill()
    check(first_call is second_call is skill_a, "V46: current_skill() called twice in a row returns the exact same object both times")


# ---------------------------------------------------------------------------
# V47 -- no arguments required
# ---------------------------------------------------------------------------
def scenario_no_arguments_required() -> None:
    signature = inspect.signature(Executor.current_skill)
    params = [name for name in signature.parameters if name != "self"]
    check(params == [], "V47: current_skill() takes no positional/keyword arguments beyond self")


# ---------------------------------------------------------------------------
# V48 -- None as a skill entry
# ---------------------------------------------------------------------------
def scenario_none_skill_entry() -> None:
    plan = SkillExecutionPlan(skills=(None, "S1"), tools=(), metadata={})
    executor = _running_executor(plan)

    result = executor.current_skill()
    check(result is None, "V48: current_skill() returns None correctly when the plan contains None as a skill entry (identity, not falsy special-casing)")

    executor.advance_skill()
    result_2 = executor.current_skill()
    check(result_2 == "S1", "V48: current_skill() correctly moves past a None entry to the next skill")


def main() -> int:
    scenarios = [
        scenario_running_success_basic,
        scenario_index_respected,
        scenario_repeated_calls_identity,
        scenario_duplicate_skill_handling,
        scenario_pending_rejection,
        scenario_ready_rejection,
        scenario_arbitrary_state_rejection,
        scenario_missing_session,
        scenario_no_skill_execution,
        scenario_no_iteration,
        scenario_metadata_untouched,
        scenario_tools_untouched,
        scenario_exact_identity_via_id,
        scenario_no_bounds_checking,
        scenario_single_and_empty_skill_plans,
        scenario_multi_instance_independence,
        scenario_exception_propagation,
        scenario_ast_verification,
        scenario_namespace_verification,
        scenario_public_api_verification,
        scenario_no_delegated_calls,
        scenario_pre_existing_behavior_unaffected,
        scenario_execute_unmodified,
        scenario_full_chain,
        scenario_back_to_back_identical_calls,
        scenario_no_arguments_required,
        scenario_none_skill_entry,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 7 SPRINT 77 EXECUTOR-CURRENT-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)

    if _FAILURES:
        print("\nFailures:")
        for failure in _FAILURES:
            print(f"  - {failure}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())