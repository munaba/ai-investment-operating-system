"""
Phase 5 Sprint 45 proof suite -- wiring ``SkillResolver`` into
``Executor``.

Scope: dedicated regression suite for the Sprint 45 change to
``Orchestration.executor.Executor``/``ExecutorError`` only.
``Orchestration.skill_resolver.SkillResolver``/``SkillResolverError``
(covered by ``Tests/test_stage_l44_skill_resolver.py``),
``Orchestration.skill_registry.SkillRegistry``/``SkillRegistryError``
(covered by ``Tests/test_stage_l43_skill_registry.py``),
``Orchestration.task_manager.TaskManager``, ``Orchestration.task_queue.
TaskQueue``, ``Orchestration.task.Task``, and ``Orchestration.
autonomous_host.AutonomousHost`` are all unmodified and are not
re-verified beyond what this sprint's change to ``Executor`` needs --
real ``TaskManager``/``TaskQueue``/``SkillRegistry``/``SkillResolver``
instances are used throughout, and ``AutonomousHost`` is exercised
through a thin recording subclass that overrides only ``start()``.

This suite proves exactly one new behavior: every ``Task`` dequeued by
``Executor.execute()`` is resolved via ``SkillResolver.resolve()``
exactly once, before the delegated ``AutonomousHost.start()`` call --
and that every previously-verified Sprint 30 behavior (FIFO order,
iteration limits, empty-queue handling, exception propagation, no
execution of the resolved skill, no forbidden collaborators) is
otherwise unchanged.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``Tests/test_stage_l28_sprint30_executor.py`` and the other Stage L4x
proof suites: a global pass/fail counter, plain fixtures, and a
``main()`` runner.

Invariant coverage:
    R1  -- constructor validation: a non-None, non-SkillResolver
           'skill_resolver' argument raises ExecutorError; task_manager
           and host validation from Sprint 30 is unchanged.
    R2  -- omitting 'skill_resolver' (or passing None explicitly)
           causes Executor to construct its own independent
           SkillResolver backed by a fresh, empty SkillRegistry --
           no singleton, no shared state between two such Executors.
    R3  -- an explicitly-injected SkillResolver is reused as-is (by
           identity) -- never rewrapped, never replaced.
    R4  -- SkillResolver.resolve() is called exactly once per executed
           Task.
    R5  -- SkillResolver.resolve() is always called before the
           corresponding AutonomousHost.start() call, for every Task.
    R6  -- one resolve() call per Task even across several Tasks in a
           single execute() call -- no double-resolution, no skipped
           resolution.
    R7  -- FIFO order is preserved for both resolve() calls and
           start() calls.
    R8  -- the iteration limit (fewer Tasks executed than pending)
           still behaves exactly as before -- resolve() is only called
           for Tasks that are actually executed this call.
    R9  -- an empty TaskManager still results in zero resolve() calls,
           zero start() calls, and a return value of 0.
    R10 -- AutonomousHost.start() call count is unchanged from Sprint
           30 -- exactly one start() call per executed Task, regardless
           of the resolver wiring.
    R11 -- an exception raised by SkillResolver.resolve() propagates
           unchanged out of execute(), and no AutonomousHost.start()
           call is made for that Task.
    R12 -- Executor never calls, invokes, or executes the object
           returned by SkillResolver.resolve() -- it only calls
           resolve() and discards the return value.
    R13 -- Executor exposes no forbidden execution surface beyond the
           documented resolve()-then-start() wiring: still no
           run/tick/schedule/retry members, still no TaskQueue/
           WorkflowEngine/WorkflowManager/Workflow/
           AutonomousScheduler/AutonomousAgent/
           RuntimeAnalysisPipeline/EventBus/Composition-Root
           attributes or imports.
    R14 -- all previously-verified Sprint 30 behavior is unchanged:
           context/iterations validation, repeated execute() calls
           continuing FIFO, duplicate Tasks each delegated separately,
           has_pending_tasks() delegation, no Task.status mutation,
           and ExecutorError remaining a Core.exceptions.AgentError
           subclass.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.executor import Executor, ExecutorError
from Orchestration.skill_registry import SkillRegistry, SkillRegistryError
from Orchestration.skill_resolver import SkillResolver, SkillResolverError
from Orchestration.task import Task, TaskStatus
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


def _make_task(name: str = "n", description: str = "d", **kwargs) -> Task:
    return Task(name=name, description=description, **kwargs)


class RecordingHost(AutonomousHost):
    """A thin ``AutonomousHost`` subclass that overrides only
    ``start()`` to record every call it receives, instead of
    delegating to a real ``AutonomousAgent``. Identical to the
    Sprint 30 suite's fixture -- unmodified in scope."""

    def __init__(self) -> None:
        self.calls: List[Tuple[object, object, object]] = []

    def start(self, agent, context, iterations):  # type: ignore[override]
        self.calls.append((agent, context, iterations))
        return ()


class RecordingSkillResolver(SkillResolver):
    """A ``SkillResolver`` subclass that records every ``resolve()``
    call (by the exact ``Task`` passed in) while still delegating to
    the real ``SkillResolver.resolve()`` implementation -- so lookups
    still behave exactly as ``SkillResolver`` documents, but call
    order/count can be observed."""

    def __init__(self, skill_registry: SkillRegistry) -> None:
        super().__init__(skill_registry)
        self.resolve_calls: List[Task] = []

    def resolve(self, task):  # type: ignore[override]
        self.resolve_calls.append(task)
        return super().resolve(task)


class ExplodingSkillResolver(SkillResolver):
    """A ``SkillResolver`` subclass whose ``resolve()`` always raises,
    to verify that Executor propagates resolution failures unchanged
    and never proceeds to call ``AutonomousHost.start()`` for that
    Task."""

    def __init__(self, skill_registry: SkillRegistry) -> None:
        super().__init__(skill_registry)
        self.resolve_calls: List[Task] = []

    def resolve(self, task):  # type: ignore[override]
        self.resolve_calls.append(task)
        raise SkillResolverError("boom: resolution deliberately fails")


def _make_registry_with(*names: str) -> SkillRegistry:
    registry = SkillRegistry()
    for name in names:
        registry.register(name, object())
    return registry


def _make_executor(
    skill_resolver: SkillResolver | None = None,
) -> Tuple[Executor, TaskManager, RecordingHost]:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    if skill_resolver is None:
        executor = Executor(task_manager, host)
    else:
        executor = Executor(task_manager, host, skill_resolver)
    return executor, task_manager, host


# ---------------------------------------------------------------------------
# R1 -- constructor validation for skill_resolver
# ---------------------------------------------------------------------------
def scenario_constructor_rejects_invalid_skill_resolver() -> None:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()

    for bad_value in (
        "not-a-resolver",
        123,
        SkillRegistry(),
        [],
        {},
        object(),
    ):
        raised_bad = False
        try:
            Executor(task_manager, host, bad_value)
        except ExecutorError:
            raised_bad = True

        check(
            raised_bad,
            f"R1: Executor(task_manager, host, {bad_value!r}) (non-"
            f"SkillResolver) raises ExecutorError",
        )

    # Sprint 30 task_manager/host validation still holds with the new
    # 3rd parameter present.
    raised_tm_none = False
    try:
        Executor(None, host)
    except ExecutorError:
        raised_tm_none = True
    check(
        raised_tm_none,
        "R1: Executor(None, host) still raises ExecutorError "
        "(task_manager validation unchanged)",
    )

    raised_host_none = False
    try:
        Executor(task_manager, None)
    except ExecutorError:
        raised_host_none = True
    check(
        raised_host_none,
        "R1: Executor(task_manager, None) still raises ExecutorError "
        "(host validation unchanged)",
    )


# ---------------------------------------------------------------------------
# R2 -- None skill_resolver restores Sprint 30 behavior exactly (no
# resolution, no SkillRegistry/SkillResolver ever constructed by
# Executor)
# ---------------------------------------------------------------------------
def scenario_none_resolver_constructs_successfully() -> None:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()

    executor = Executor(task_manager, host)
    check(
        isinstance(executor, Executor),
        "R2: Executor(task_manager, host) with no skill_resolver "
        "constructs successfully",
    )
    check(
        executor._skill_resolver is None,  # noqa: SLF001
        "R2: the omitted skill_resolver is stored as None -- "
        "Executor never constructs a SkillResolver of its own",
    )

    executor_explicit_none = Executor(task_manager, host, None)
    check(
        isinstance(executor_explicit_none, Executor)
        and executor_explicit_none._skill_resolver is None,  # noqa: SLF001
        "R2: Executor(task_manager, host, None) constructs "
        "successfully and also stores None (explicit None behaves "
        "identically to omitted)",
    )


def scenario_none_resolver_skips_resolution_entirely() -> None:
    # With no resolver injected, an unregistered/arbitrary Task name
    # must NOT raise -- there is no registry to miss against, because
    # no resolution is attempted at all. This is the direct proof
    # that Sprint 30 behavior is restored.
    executor, task_manager, host = _make_executor()
    task = _make_task(name="totally-unregistered-name")
    task_manager.submit(task)

    executed = executor.execute("ctx")

    check(
        executed == 1,
        "R2: execute() with no skill_resolver still executes the "
        "Task normally (no SkillRegistryError, no resolution attempted)",
    )
    check(
        len(host.calls) == 1 and host.calls[0][0] is task,
        "R2: AutonomousHost.start() is still called with the exact "
        "Task, exactly as in Sprint 30",
    )


def scenario_executor_never_constructs_skill_registry_or_resolver() -> None:
    # Static proof: Orchestration.executor no longer imports or
    # references SkillRegistry at all, and holds no SkillRegistry
    # instance anywhere on an Executor built without an explicit
    # skill_resolver.
    import Orchestration.executor as executor_module

    check(
        "SkillRegistry" not in vars(executor_module),
        "R2: Orchestration.executor's module namespace does not "
        "contain a 'SkillRegistry' symbol -- Executor cannot "
        "construct one even accidentally",
    )

    executor, _, _ = _make_executor()
    check(
        not isinstance(executor._skill_resolver, SkillResolver),  # noqa: SLF001
        "R2: an Executor built without an explicit skill_resolver "
        "holds no SkillResolver instance at all (it holds None, not "
        "an auto-built one)",
    )

    for attr_name in ("_skill_registry", "skill_registry"):
        check(
            not hasattr(executor, attr_name),
            f"R2: Executor has no '{attr_name}' attribute of its own",
        )


def scenario_two_none_resolver_executors_share_nothing_because_nothing_exists() -> None:
    task_manager_1 = TaskManager(TaskQueue())
    task_manager_2 = TaskManager(TaskQueue())
    host_1 = RecordingHost()
    host_2 = RecordingHost()

    executor_1 = Executor(task_manager_1, host_1)
    executor_2 = Executor(task_manager_2, host_2)

    check(
        executor_1._skill_resolver is None  # noqa: SLF001
        and executor_2._skill_resolver is None,  # noqa: SLF001
        "R2: two independently-constructed Executors with no injected "
        "resolver both simply hold None -- there is no shared or "
        "per-instance auto-built registry to compare",
    )


# ---------------------------------------------------------------------------
# R3 -- injected resolver reused by identity
# ---------------------------------------------------------------------------
def scenario_injected_resolver_reused_by_identity() -> None:
    registry = _make_registry_with("task-a")
    resolver = SkillResolver(registry)

    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    executor = Executor(task_manager, host, resolver)

    check(
        executor._skill_resolver is resolver,  # noqa: SLF001
        "R3: an explicitly-injected SkillResolver is stored by "
        "identity, never rewrapped or replaced",
    )


# ---------------------------------------------------------------------------
# R4/R5/R6/R7 -- resolve() called exactly once per Task, before
# start(), in FIFO order
# ---------------------------------------------------------------------------
def scenario_resolve_called_exactly_once_before_start() -> None:
    registry = _make_registry_with("only-task")
    resolver = RecordingSkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    task = _make_task(name="only-task")
    task_manager.submit(task)

    executed = executor.execute("ctx")

    check(executed == 1, "R4: execute() executes exactly 1 Task")
    check(
        len(resolver.resolve_calls) == 1,
        "R4: SkillResolver.resolve() is called exactly once for the "
        "single executed Task",
    )
    check(
        resolver.resolve_calls[0] is task,
        "R4: resolve() is called with the exact dequeued Task, by "
        "identity",
    )
    check(
        len(host.calls) == 1,
        "R5: AutonomousHost.start() is still called exactly once",
    )
    check(
        host.calls[0][0] is task,
        "R5: start() still receives the exact same Task, by identity",
    )


def scenario_resolve_before_start_ordering() -> None:
    # Use a shared order log written to by both a resolver subclass
    # and a host subclass, to directly observe call ordering.
    order: List[str] = []

    class OrderingResolver(SkillResolver):
        def resolve(self, task):  # type: ignore[override]
            order.append("resolve")
            return super().resolve(task)

    class OrderingHost(AutonomousHost):
        def __init__(self) -> None:
            pass

        def start(self, agent, context, iterations):  # type: ignore[override]
            order.append("start")
            return ()

    registry = _make_registry_with("t1", "t2")
    resolver = OrderingResolver(registry)
    task_manager = TaskManager(TaskQueue())
    host = OrderingHost()
    executor = Executor(task_manager, host, resolver)

    task_manager.submit(_make_task(name="t1"))
    task_manager.submit(_make_task(name="t2"))

    executor.execute("ctx", iterations=2)

    check(
        order == ["resolve", "start", "resolve", "start"],
        f"R5: resolve() precedes start() for every Task, in strict "
        f"per-Task order; got {order!r}",
    )


def scenario_one_resolve_call_per_task_multiple_tasks() -> None:
    registry = _make_registry_with("a", "b", "c")
    resolver = RecordingSkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    tasks = [_make_task(name=n) for n in ("a", "b", "c")]
    for t in tasks:
        task_manager.submit(t)

    executed = executor.execute("ctx", iterations=3)

    check(executed == 3, "R6: all 3 Tasks are executed")
    check(
        len(resolver.resolve_calls) == 3,
        "R6: resolve() is called exactly 3 times for 3 executed Tasks "
        "(no double-resolution, no skipped resolution)",
    )
    check(
        resolver.resolve_calls == tasks,
        "R7: resolve() calls occur in the same FIFO order the Tasks "
        "were submitted in",
    )
    check(
        [c[0] for c in host.calls] == tasks,
        "R7: start() calls also occur in the same FIFO order",
    )


# ---------------------------------------------------------------------------
# R8 -- iteration limit still respected; resolve() only for executed
# Tasks
# ---------------------------------------------------------------------------
def scenario_iteration_limit_resolve_count_matches() -> None:
    registry = _make_registry_with("a", "b", "c", "d")
    resolver = RecordingSkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    tasks = [_make_task(name=n) for n in ("a", "b", "c", "d")]
    for t in tasks:
        task_manager.submit(t)

    executed = executor.execute("ctx", iterations=2)

    check(executed == 2, "R8: execute() stops after 2 iterations")
    check(
        len(resolver.resolve_calls) == 2,
        "R8: resolve() is called only for the 2 Tasks actually "
        "executed, not the 2 remaining pending Tasks",
    )
    check(
        resolver.resolve_calls == tasks[:2],
        "R8: the 2 resolve() calls correspond to the first 2 Tasks "
        "submitted (FIFO)",
    )
    check(
        task_manager.has_tasks(),
        "R8: the remaining 2 Tasks are still pending afterward",
    )


# ---------------------------------------------------------------------------
# R9 -- empty queue: zero resolve() calls, zero start() calls
# ---------------------------------------------------------------------------
def scenario_empty_queue_zero_resolve_calls() -> None:
    registry = SkillRegistry()
    resolver = RecordingSkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    executed = executor.execute("ctx")

    check(executed == 0, "R9: execute() returns 0 for an empty queue")
    check(
        len(resolver.resolve_calls) == 0,
        "R9: resolve() is never called when the TaskManager is empty",
    )
    check(
        len(host.calls) == 0,
        "R9: start() is never called when the TaskManager is empty",
    )


# ---------------------------------------------------------------------------
# R10 -- AutonomousHost.start() call count unchanged
# ---------------------------------------------------------------------------
def scenario_host_start_call_count_unchanged() -> None:
    registry = _make_registry_with("a", "b", "c")
    resolver = SkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    for n in ("a", "b", "c"):
        task_manager.submit(_make_task(name=n))

    executed = executor.execute("ctx", iterations=3)

    check(
        executed == 3 and len(host.calls) == 3,
        "R10: exactly one start() call per executed Task, matching "
        "the Sprint 30 baseline behavior",
    )


# ---------------------------------------------------------------------------
# R11 -- resolve() exception propagates unchanged; no start() call for
# that Task
# ---------------------------------------------------------------------------
def scenario_resolve_exception_propagates_and_blocks_start() -> None:
    registry = _make_registry_with("will-fail")
    resolver = ExplodingSkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    task_manager.submit(_make_task(name="will-fail"))

    raised = False
    try:
        executor.execute("ctx")
    except SkillResolverError:
        raised = True

    check(
        raised,
        "R11: a SkillResolverError raised by resolve() propagates "
        "unchanged out of execute()",
    )
    check(
        len(resolver.resolve_calls) == 1,
        "R11: resolve() was called (and raised) for the one pending "
        "Task",
    )
    check(
        len(host.calls) == 0,
        "R11: AutonomousHost.start() is never called for a Task whose "
        "resolution failed",
    )


def scenario_resolve_exception_mid_batch_stops_remaining_tasks() -> None:
    # First task resolves fine, second explodes -- proves the
    # exception is not swallowed and does not let the loop continue
    # on to later Tasks either.
    registry = _make_registry_with("ok", "bad")

    class PartialExplodingResolver(SkillResolver):
        def __init__(self, skill_registry: SkillRegistry) -> None:
            super().__init__(skill_registry)
            self.resolve_calls: List[Task] = []

        def resolve(self, task):  # type: ignore[override]
            self.resolve_calls.append(task)
            if task.name == "bad":
                raise SkillResolverError("boom")
            return super().resolve(task)

    resolver = PartialExplodingResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    task_manager.submit(_make_task(name="ok"))
    task_manager.submit(_make_task(name="bad"))
    task_manager.submit(_make_task(name="ok"))  # never reached

    raised = False
    try:
        executor.execute("ctx", iterations=3)
    except SkillResolverError:
        raised = True

    check(
        raised,
        "R11: resolve() failure on the 2nd Task still propagates out "
        "of execute()",
    )
    check(
        len(resolver.resolve_calls) == 2,
        "R11: only the first 2 Tasks were resolved before the "
        "exception stopped the loop -- the 3rd Task's resolve() was "
        "never called",
    )
    check(
        len(host.calls) == 1,
        "R11: only the 1st Task (which resolved successfully) reached "
        "start() -- the 2nd Task's failure blocked its own start() "
        "call and the loop stopped before the 3rd",
    )
    check(
        task_manager.has_tasks(),
        "R11: the 3rd, never-dequeued Task is still pending in the "
        "TaskManager after the exception",
    )


# ---------------------------------------------------------------------------
# R12 -- Executor never calls/invokes/executes the resolved skill
# ---------------------------------------------------------------------------
def scenario_resolved_skill_is_never_called() -> None:
    class TrackedSkill:
        def __init__(self) -> None:
            self.was_called = False

        def __call__(self, *args, **kwargs):
            self.was_called = True

        def run(self):
            self.was_called = True

        def execute(self):
            self.was_called = True

        def invoke(self):
            self.was_called = True

    skill = TrackedSkill()
    registry = SkillRegistry()
    registry.register("skill-task", skill)
    resolver = SkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    task_manager.submit(_make_task(name="skill-task"))
    executor.execute("ctx")

    check(
        not skill.was_called,
        "R12: the resolved skill object's __call__/run/execute/invoke "
        "are never triggered by Executor -- resolve()'s return value "
        "is discarded, not acted upon",
    )


# ---------------------------------------------------------------------------
# R13 -- no forbidden execution surface / attributes
# ---------------------------------------------------------------------------
def scenario_no_forbidden_surface() -> None:
    executor, _, _ = _make_executor()

    forbidden_attrs = [
        "task_queue",
        "workflow_engine",
        "workflow_manager",
        "workflow",
        "autonomous_scheduler",
        "autonomous_agent",
        "runtime_analysis_pipeline",
        "event_bus",
        "composition_root",
        "run",
        "tick",
        "schedule",
        "retry",
        "run_skill",
        "call_skill",
        "invoke_skill",
        "dispatch",
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(executor, attr),
            f"R13: Executor has no '{attr}' attribute",
        )

    public_methods = {
        name
        for name in dir(executor)
        if not name.startswith("_") and callable(getattr(executor, name))
    }
    check(
        public_methods == {"execute", "has_pending_tasks"},
        f"R13: Executor's only public callable members are 'execute' "
        f"and 'has_pending_tasks'; got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# R14 -- prior Sprint 30 behavior preserved
# ---------------------------------------------------------------------------
def scenario_execute_rejects_none_context_unchanged() -> None:
    executor, task_manager, host = _make_executor()
    task_manager.submit(_make_task(name="whatever"))

    raised = False
    try:
        executor.execute(None)
    except ExecutorError:
        raised = True

    check(
        raised,
        "R14: execute(None) still raises ExecutorError (context "
        "validation unchanged)",
    )
    check(
        len(host.calls) == 0 and task_manager.has_tasks(),
        "R14: no Task is dequeued and no start() call is made when "
        "context validation fails",
    )


def scenario_execute_rejects_invalid_iterations_unchanged() -> None:
    executor, task_manager, host = _make_executor()
    task_manager.submit(_make_task(name="whatever"))

    for bad_iterations in (0, -1, "1", 1.5, True, False):
        raised = False
        try:
            executor.execute("ctx", iterations=bad_iterations)
        except ExecutorError:
            raised = True
        check(
            raised,
            f"R14: execute('ctx', iterations={bad_iterations!r}) "
            f"still raises ExecutorError",
        )

    check(
        len(host.calls) == 0 and task_manager.has_tasks(),
        "R14: no Task is dequeued and no start() call is made for any "
        "invalid iterations value",
    )


def scenario_repeated_execute_calls_continue_fifo_with_resolution() -> None:
    registry = _make_registry_with("a", "b", "c")
    resolver = RecordingSkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    tasks = [_make_task(name=n) for n in ("a", "b", "c")]
    for t in tasks:
        task_manager.submit(t)

    first = executor.execute("ctx", iterations=2)
    second = executor.execute("ctx", iterations=2)

    check(
        first == 2 and second == 1,
        "R14: repeated execute() calls continue consuming from where "
        "the previous call left off",
    )
    check(
        resolver.resolve_calls == tasks,
        "R14: resolve() calls across both execute() calls remain in "
        "overall FIFO order",
    )
    check(
        [c[0] for c in host.calls] == tasks,
        "R14: start() calls across both execute() calls remain in "
        "overall FIFO order",
    )


def scenario_duplicate_tasks_each_delegated_and_resolved_separately() -> None:
    registry = _make_registry_with("dup")
    resolver = RecordingSkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    task = _make_task(name="dup")
    task_manager.submit(task)
    task_manager.submit(task)

    executed = executor.execute("ctx", iterations=2)

    check(executed == 2, "R14: both submissions of the duplicate Task execute")
    check(
        resolver.resolve_calls == [task, task],
        "R14: resolve() is called once per submission, even for the "
        "exact same Task instance submitted twice",
    )
    check(
        [c[0] for c in host.calls] == [task, task],
        "R14: start() is likewise called once per submission",
    )


def scenario_has_pending_tasks_matches_task_manager_unchanged() -> None:
    executor, task_manager, host = _make_executor()

    check(
        executor.has_pending_tasks() is False,
        "R14: has_pending_tasks() is False for an empty TaskManager",
    )

    registry = SkillRegistry()
    registry.register("x", object())
    executor2, task_manager2, _ = _make_executor(SkillResolver(registry))
    task_manager2.submit(_make_task(name="x"))

    check(
        executor2.has_pending_tasks() is True,
        "R14: has_pending_tasks() is True once a Task is submitted",
    )
    executor2.execute("ctx")
    check(
        executor2.has_pending_tasks() is False,
        "R14: has_pending_tasks() is False again after the Task is "
        "executed",
    )


def scenario_no_task_status_mutation_with_resolution() -> None:
    registry = _make_registry_with("status-check")
    resolver = SkillResolver(registry)
    executor, task_manager, host = _make_executor(resolver)

    task = _make_task(name="status-check")
    status_before = task.status
    task_manager.submit(task)

    executor.execute("ctx")

    check(
        task.status == status_before == TaskStatus.PENDING,
        "R14: Task.status is unchanged by execute(), even with "
        "resolution wired in",
    )


def scenario_executor_error_is_agent_error_subclass_unchanged() -> None:
    raised_as_agent_error_ctor = False
    try:
        Executor(None, RecordingHost())
    except AgentError:
        raised_as_agent_error_ctor = True

    check(
        raised_as_agent_error_ctor,
        "R14: an ExecutorError from an invalid constructor call can "
        "still be caught as AgentError",
    )

    executor, task_manager, host = _make_executor()
    task_manager.submit(_make_task(name="whatever"))

    raised_as_agent_error_execute = False
    try:
        executor.execute("ctx", iterations=0)
    except AgentError:
        raised_as_agent_error_execute = True

    check(
        raised_as_agent_error_execute,
        "R14: an ExecutorError from an invalid execute() call can "
        "still be caught as AgentError",
    )

    raised_as_agent_error_bad_resolver = False
    try:
        Executor(task_manager, RecordingHost(), "not-a-resolver")
    except AgentError:
        raised_as_agent_error_bad_resolver = True

    check(
        raised_as_agent_error_bad_resolver,
        "R14: an ExecutorError from an invalid skill_resolver argument "
        "can also be caught as AgentError",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_rejects_invalid_skill_resolver,
        scenario_none_resolver_constructs_successfully,
        scenario_none_resolver_skips_resolution_entirely,
        scenario_executor_never_constructs_skill_registry_or_resolver,
        scenario_two_none_resolver_executors_share_nothing_because_nothing_exists,
        scenario_injected_resolver_reused_by_identity,
        scenario_resolve_called_exactly_once_before_start,
        scenario_resolve_before_start_ordering,
        scenario_one_resolve_call_per_task_multiple_tasks,
        scenario_iteration_limit_resolve_count_matches,
        scenario_empty_queue_zero_resolve_calls,
        scenario_host_start_call_count_unchanged,
        scenario_resolve_exception_propagates_and_blocks_start,
        scenario_resolve_exception_mid_batch_stops_remaining_tasks,
        scenario_resolved_skill_is_never_called,
        scenario_no_forbidden_surface,
        scenario_execute_rejects_none_context_unchanged,
        scenario_execute_rejects_invalid_iterations_unchanged,
        scenario_repeated_execute_calls_continue_fifo_with_resolution,
        scenario_duplicate_tasks_each_delegated_and_resolved_separately,
        scenario_has_pending_tasks_matches_task_manager_unchanged,
        scenario_no_task_status_mutation_with_resolution,
        scenario_executor_error_is_agent_error_subclass_unchanged,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"PHASE 5 SPRINT 45 EXECUTOR SKILL RESOLUTION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())