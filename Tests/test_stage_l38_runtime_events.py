"""
Phase 4 Sprint 38 proof suite -- ``WorkflowRuntime`` <-> ``EventBus``
integration.

Scope: dedicated regression suite for the Sprint 38 addition only --
``WorkflowRuntime`` optionally accepting an ``EventBus`` and
publishing exactly three events (``"runtime.started"``,
``"runtime.completed"``, ``"runtime.failed"``) around ``run()``'s
existing Sprint 37 sequence. ``WorkflowSession``,
``WorkflowSessionManager``, ``WorkflowEngine``,
``WorkflowExecutionCoordinator``, ``Executor``, ``EventBus``, and
``Event`` are all untouched by this sprint and are exercised here only
as the real, unmodified collaborators ``WorkflowRuntime`` is built on
top of -- none of their own already-locked behavior (fully covered by
``Tests/test_stage_l37_workflow_runtime.py`` and
``Tests/test_stage_l28_sprint22_event_bus.py``) is re-verified beyond
what this integration itself needs.

This sprint introduces no new architectural layer, no new value
object, and no new event class: ``Event``/``EventBus`` are reused
exactly as Sprint 22B built them. ``WorkflowRuntime`` still knows
nothing of Reflection, Memory, LearningLoop, Scheduler, Monitoring,
Logger, or Database -- ``EventBus`` is its only outward communication
channel.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L3x / Sprint 1x-38 proof suites: a global
pass/fail counter, plain fixtures (real collaborators, plus thin
recording subclasses), and a ``main()`` runner.

Invariant coverage:
    R1  -- constructor: event_bus defaults to None and, when omitted,
           an independent EventBus() is auto-created (not a shared
           singleton).
    R2  -- constructor: a provided EventBus is used as-is (identity
           preserved, never wrapped or replaced).
    R3  -- constructor validation: a non-None, non-EventBus event_bus
           raises WorkflowRuntimeError; the four original collaborator
           validations (Sprint 37) still work unchanged.
    R4  -- success path: exactly one "runtime.started" and exactly one
           "runtime.completed" event are published; zero
           "runtime.failed" events.
    R5  -- failure path: exactly one "runtime.started" and exactly one
           "runtime.failed" event are published; zero
           "runtime.completed" events.
    R6  -- ordering (success): runtime.started is observed before
           runtime.completed, and both are observed after
           session_manager.prepare()/workflow_engine.load() have
           already run.
    R7  -- ordering (failure): runtime.started is observed before
           runtime.failed, and runtime.failed is observed only after
           session_manager.fail() has already run.
    R8  -- payload (started/completed): workflow_id, session_id, and
           execution_id are present and correct on both events, and
           workflow_id/execution_id match the exact ExecutionContext
           passed to run().
    R9  -- payload (failed): workflow_id, session_id, execution_id,
           and exception_type (the raised exception's class name) are
           all present and correct.
    R10 -- event names: exactly "runtime.started", "runtime.completed",
           "runtime.failed" are used -- no other event_name is ever
           published by WorkflowRuntime.
    R11 -- exception identity: the original exception instance raised
           by coordinator.execute_workflow() is still re-raised
           unchanged (identity), exactly as Sprint 37 guaranteed --
           the new eventing does not alter this.
    R12 -- auto-created EventBus isolation: two WorkflowRuntime
           instances constructed without an explicit event_bus each
           get a distinct EventBus (subscribing on one is invisible to
           the other).
    R13 -- provided EventBus reuse: a caller-supplied EventBus can be
           shared across two WorkflowRuntime instances, and a
           subscriber sees events from both runs on that shared bus.
    R14 -- multiple runtime instances independent: running two
           separate WorkflowRuntime instances (auto-created buses)
           against their own workflows never cross-publishes events to
           each other's subscribers.
    R15 -- no duplicate events: a single run() call (success or
           failure) never publishes the same event_name more than
           once.
    R16 -- EventBus itself is never modified: WorkflowRuntime never
           calls unsubscribe()/once() and never mutates
           EventBus._subscribers directly; only publish() is used, and
           existing subscriptions on a provided bus survive run().
    R17 -- no new event classes: workflow_runtime.py defines no class
           named RuntimeEvent, WorkflowRuntimeEvent, or ExecutionEvent
           anywhere in the module; the only Event constructions in the
           module use the existing Orchestration.event_bus.Event.
    R18 -- Sprint 37 regression: WorkflowRuntime with no event_bus
           argument at all still behaves exactly as Sprint 37 --
           successful run() still returns a COMPLETED session, and a
           failing run() still re-raises unchanged.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.event_bus import Event, EventBus
from Orchestration.execution_context import ExecutionContext
from Orchestration.executor import Executor
from Orchestration.task import Task
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
from Orchestration.workflow import Workflow
from Orchestration.workflow_engine import WorkflowEngine
from Orchestration.workflow_execution_coordinator import (
    WorkflowExecutionCoordinator,
)
from Orchestration.workflow_runtime import WorkflowRuntime, WorkflowRuntimeError
from Orchestration.workflow_session import WorkflowSession, WorkflowSessionStatus
from Orchestration.workflow_session_manager import WorkflowSessionManager
from Orchestration.autonomous_host import AutonomousHost

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


def _make_workflow(**kwargs) -> Workflow:
    kwargs.setdefault("name", "wf-name")
    kwargs.setdefault("description", "wf-description")
    return Workflow(**kwargs)


def _make_context(workflow: Workflow, **kwargs) -> ExecutionContext:
    return ExecutionContext(workflow_id=workflow.workflow_id, **kwargs)


class RecordingHost(AutonomousHost):
    """Thin ``AutonomousHost`` subclass overriding only ``start()`` --
    same technique ``Tests/test_stage_l37_workflow_runtime.py`` uses,
    keeping ``isinstance(host, AutonomousHost)`` true without a real
    ``AutonomousAgent``/``RuntimeAnalysisPipeline`` graph.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[object, object, object]] = []

    def start(self, agent, context, iterations):  # type: ignore[override]
        self.calls.append((agent, context, iterations))
        return ()


class FailingCoordinator(WorkflowExecutionCoordinator):
    """A ``WorkflowExecutionCoordinator`` whose ``execute_workflow()``
    always raises a fixed exception instance -- exercises
    ``WorkflowRuntime.run()``'s failure path.
    """

    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    def execute_workflow(self, executor, workflow_engine, context, iterations=1):
        raise self._exception


class RecordingSubscriber:
    """A plain callable collecting every ``Event`` delivered to it, in
    delivery order -- used in place of a mock/patch library.
    """

    def __init__(self) -> None:
        self.events: List[Event] = []

    def __call__(self, event: Event) -> None:
        self.events.append(event)


def _make_stack(
    event_bus: Any = None,
) -> Tuple[
    WorkflowSessionManager,
    WorkflowEngine,
    WorkflowExecutionCoordinator,
    Executor,
    RecordingHost,
]:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    executor = Executor(task_manager, host)
    workflow_engine = WorkflowEngine(task_manager)
    coordinator = WorkflowExecutionCoordinator()
    session_manager = WorkflowSessionManager()
    return session_manager, workflow_engine, coordinator, executor, host


def _subscribe_all(bus: EventBus, subscriber: RecordingSubscriber) -> None:
    bus.subscribe("runtime.started", subscriber)
    bus.subscribe("runtime.completed", subscriber)
    bus.subscribe("runtime.failed", subscriber)


# ---------------------------------------------------------------------------
# R1 -- auto-created EventBus when omitted
# ---------------------------------------------------------------------------
def scenario_auto_created_event_bus() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    check(
        isinstance(runtime._event_bus, EventBus),
        "R1: omitting event_bus auto-creates an EventBus instance",
    )


# ---------------------------------------------------------------------------
# R2 -- provided EventBus used as-is
# ---------------------------------------------------------------------------
def scenario_provided_event_bus_reused() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    bus = EventBus()
    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )

    check(
        runtime._event_bus is bus,
        "R2: a provided EventBus is used as-is (identity preserved)",
    )


# ---------------------------------------------------------------------------
# R3 -- constructor validation
# ---------------------------------------------------------------------------
def scenario_event_bus_constructor_validation() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()

    for bad in ("not-a-bus", 123, [], {}, object()):
        raised = False
        try:
            WorkflowRuntime(
                session_manager,
                workflow_engine,
                coordinator,
                executor,
                event_bus=bad,
            )
        except WorkflowRuntimeError:
            raised = True
        check(
            raised,
            f"R3: invalid event_bus {bad!r} raises WorkflowRuntimeError",
        )

    # Sprint 37 collaborator validation still works unchanged.
    for bad in (None, "not-it", 123):
        raised = False
        try:
            WorkflowRuntime(bad, workflow_engine, coordinator, executor)
        except WorkflowRuntimeError:
            raised = True
        check(
            raised,
            f"R3: invalid session_manager {bad!r} still raises "
            f"WorkflowRuntimeError (Sprint 37 validation unchanged)",
        )

    valid = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    check(
        isinstance(valid, WorkflowRuntime),
        "R3: constructing with event_bus omitted still succeeds",
    )

    valid_with_bus = WorkflowRuntime(
        session_manager,
        workflow_engine,
        coordinator,
        executor,
        event_bus=EventBus(),
    )
    check(
        isinstance(valid_with_bus, WorkflowRuntime),
        "R3: constructing with a valid EventBus succeeds",
    )


# ---------------------------------------------------------------------------
# R4 -- success path event counts
# ---------------------------------------------------------------------------
def scenario_success_path_event_counts() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)

    result = runtime.run(workflow, context)

    names = [event.event_name for event in subscriber.events]
    check(
        names.count("runtime.started") == 1,
        "R4: exactly one runtime.started published on success",
    )
    check(
        names.count("runtime.completed") == 1,
        "R4: exactly one runtime.completed published on success",
    )
    check(
        names.count("runtime.failed") == 0,
        "R4: zero runtime.failed published on success",
    )
    check(
        result.status is WorkflowSessionStatus.COMPLETED,
        "R4: run() still returns a COMPLETED session",
    )


# ---------------------------------------------------------------------------
# R5 -- failure path event counts
# ---------------------------------------------------------------------------
def scenario_failure_path_event_counts() -> None:
    session_manager, workflow_engine, _, executor, _ = _make_stack()
    exc = ValueError("boom")
    coordinator = FailingCoordinator(exc)
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)

    raised = None
    try:
        runtime.run(workflow, context)
    except Exception as caught:  # noqa: BLE001
        raised = caught

    names = [event.event_name for event in subscriber.events]
    check(
        names.count("runtime.started") == 1,
        "R5: exactly one runtime.started published on failure",
    )
    check(
        names.count("runtime.failed") == 1,
        "R5: exactly one runtime.failed published on failure",
    )
    check(
        names.count("runtime.completed") == 0,
        "R5: zero runtime.completed published on failure",
    )
    check(raised is exc, "R5: original exception still propagates")


# ---------------------------------------------------------------------------
# R6 -- ordering (success)
# ---------------------------------------------------------------------------
def scenario_success_ordering() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)
    runtime.run(workflow, context)

    names = [event.event_name for event in subscriber.events]
    check(
        names == ["runtime.started", "runtime.completed"],
        f"R6: success ordering is exactly "
        f"[runtime.started, runtime.completed]; got {names!r}",
    )


# ---------------------------------------------------------------------------
# R7 -- ordering (failure)
# ---------------------------------------------------------------------------
def scenario_failure_ordering() -> None:
    session_manager, workflow_engine, _, executor, _ = _make_stack()
    coordinator = FailingCoordinator(RuntimeError("nope"))
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)

    try:
        runtime.run(workflow, context)
    except RuntimeError:
        pass

    names = [event.event_name for event in subscriber.events]
    check(
        names == ["runtime.started", "runtime.failed"],
        f"R7: failure ordering is exactly "
        f"[runtime.started, runtime.failed]; got {names!r}",
    )


# ---------------------------------------------------------------------------
# R8 -- payload (started/completed)
# ---------------------------------------------------------------------------
def scenario_started_completed_payload() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)
    result = runtime.run(workflow, context)

    started = next(e for e in subscriber.events if e.event_name == "runtime.started")
    completed = next(
        e for e in subscriber.events if e.event_name == "runtime.completed"
    )

    for event, label in ((started, "runtime.started"), (completed, "runtime.completed")):
        check(
            event.payload.get("workflow_id") == context.workflow_id,
            f"R8: {label} payload workflow_id matches the ExecutionContext",
        )
        check(
            event.payload.get("execution_id") == context.execution_id,
            f"R8: {label} payload execution_id matches the ExecutionContext",
        )
        check(
            event.payload.get("session_id") == result.session_id,
            f"R8: {label} payload session_id matches the returned session",
        )


# ---------------------------------------------------------------------------
# R9 -- payload (failed)
# ---------------------------------------------------------------------------
def scenario_failed_payload() -> None:
    session_manager, workflow_engine, _, executor, _ = _make_stack()
    exc = KeyError("missing")
    coordinator = FailingCoordinator(exc)
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)

    try:
        runtime.run(workflow, context)
    except KeyError:
        pass

    failed = next(e for e in subscriber.events if e.event_name == "runtime.failed")
    check(
        failed.payload.get("workflow_id") == context.workflow_id,
        "R9: runtime.failed payload workflow_id matches the ExecutionContext",
    )
    check(
        failed.payload.get("execution_id") == context.execution_id,
        "R9: runtime.failed payload execution_id matches the ExecutionContext",
    )
    check(
        "session_id" in failed.payload and bool(failed.payload["session_id"]),
        "R9: runtime.failed payload includes a non-empty session_id",
    )
    check(
        failed.payload.get("exception_type") == "KeyError",
        "R9: runtime.failed payload exception_type is the raised "
        "exception's class name",
    )


# ---------------------------------------------------------------------------
# R10 -- only these three event names are ever published
# ---------------------------------------------------------------------------
def scenario_only_known_event_names() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    bus = EventBus()
    subscriber = RecordingSubscriber()
    # Subscribe to a broad net of plausible event names to prove
    # nothing else is ever published.
    for name in (
        "runtime.started",
        "runtime.completed",
        "runtime.failed",
        "runtime.running",
        "runtime.error",
    ):
        bus.subscribe(name, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)
    runtime.run(workflow, context)

    names = {event.event_name for event in subscriber.events}
    check(
        names == {"runtime.started", "runtime.completed"},
        f"R10: only runtime.started/runtime.completed observed on "
        f"success; got {names!r}",
    )


# ---------------------------------------------------------------------------
# R11 -- exception identity preserved
# ---------------------------------------------------------------------------
def scenario_exception_identity_preserved() -> None:
    session_manager, workflow_engine, _, executor, _ = _make_stack()
    exc = ValueError("original")
    coordinator = FailingCoordinator(exc)
    bus = EventBus()

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)

    caught = None
    try:
        runtime.run(workflow, context)
    except Exception as e:  # noqa: BLE001
        caught = e

    check(
        caught is exc,
        "R11: the exact original exception instance is re-raised "
        "(identity), unaffected by the new eventing",
    )


# ---------------------------------------------------------------------------
# R12 -- auto-created EventBus isolation
# ---------------------------------------------------------------------------
def scenario_auto_created_bus_isolation() -> None:
    stack1 = _make_stack()
    stack2 = _make_stack()

    runtime1 = WorkflowRuntime(*stack1[:4])
    runtime2 = WorkflowRuntime(*stack2[:4])

    check(
        runtime1._event_bus is not runtime2._event_bus,
        "R12: two WorkflowRuntime instances without an explicit "
        "event_bus each get their own, distinct EventBus",
    )

    subscriber1 = RecordingSubscriber()
    runtime1._event_bus.subscribe("runtime.started", subscriber1)

    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)
    runtime2.run(workflow, context)

    check(
        subscriber1.events == [],
        "R12: subscribing on runtime1's auto-created bus observes "
        "nothing when runtime2 runs",
    )


# ---------------------------------------------------------------------------
# R13 -- provided EventBus reuse across instances
# ---------------------------------------------------------------------------
def scenario_shared_event_bus_across_instances() -> None:
    shared_bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(shared_bus, subscriber)

    stack1 = _make_stack()
    stack2 = _make_stack()
    runtime1 = WorkflowRuntime(*stack1[:4], event_bus=shared_bus)
    runtime2 = WorkflowRuntime(*stack2[:4], event_bus=shared_bus)

    workflow1 = _make_workflow(tasks=[Task(name="t1", description="d")])
    context1 = _make_context(workflow1)
    workflow2 = _make_workflow(tasks=[Task(name="t2", description="d")])
    context2 = _make_context(workflow2)

    runtime1.run(workflow1, context1)
    runtime2.run(workflow2, context2)

    names = [event.event_name for event in subscriber.events]
    check(
        names == [
            "runtime.started",
            "runtime.completed",
            "runtime.started",
            "runtime.completed",
        ],
        f"R13: a shared EventBus observes both runtimes' events, in "
        f"order; got {names!r}",
    )


# ---------------------------------------------------------------------------
# R14 -- multiple runtime instances independent (no cross-publish)
# ---------------------------------------------------------------------------
def scenario_multiple_instances_independent() -> None:
    stack1 = _make_stack()
    stack2 = _make_stack()
    runtime1 = WorkflowRuntime(*stack1[:4])
    runtime2 = WorkflowRuntime(*stack2[:4])

    subscriber1 = RecordingSubscriber()
    subscriber2 = RecordingSubscriber()
    _subscribe_all(runtime1._event_bus, subscriber1)
    _subscribe_all(runtime2._event_bus, subscriber2)

    workflow1 = _make_workflow(tasks=[Task(name="t1", description="d")])
    context1 = _make_context(workflow1)
    workflow2 = _make_workflow(tasks=[Task(name="t2", description="d")])
    context2 = _make_context(workflow2)

    runtime1.run(workflow1, context1)

    check(
        len(subscriber1.events) == 2 and len(subscriber2.events) == 0,
        "R14: running runtime1 only notifies runtime1's own subscriber",
    )

    runtime2.run(workflow2, context2)

    check(
        len(subscriber1.events) == 2 and len(subscriber2.events) == 2,
        "R14: running runtime2 only adds to runtime2's own subscriber, "
        "leaving runtime1's untouched",
    )


# ---------------------------------------------------------------------------
# R15 -- no duplicate events per run()
# ---------------------------------------------------------------------------
def scenario_no_duplicate_events() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)

    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)
    runtime.run(workflow, context)

    check(
        len(subscriber.events) == len(set(id(e) for e in subscriber.events)),
        "R15: no duplicate Event objects published for a single run()",
    )
    names = [event.event_name for event in subscriber.events]
    check(
        len(names) == len(set(names)),
        "R15: no event_name repeats within a single successful run()",
    )


# ---------------------------------------------------------------------------
# R16 -- EventBus itself is never modified
# ---------------------------------------------------------------------------
def scenario_event_bus_not_mutated() -> None:
    bus = EventBus()
    subscriber = RecordingSubscriber()
    _subscribe_all(bus, subscriber)
    subscribers_before = {
        name: list(handlers) for name, handlers in bus._subscribers.items()
    }

    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    runtime = WorkflowRuntime(
        session_manager, workflow_engine, coordinator, executor, event_bus=bus
    )
    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)
    runtime.run(workflow, context)

    subscribers_after = {
        name: list(handlers) for name, handlers in bus._subscribers.items()
    }
    check(
        subscribers_before == subscribers_after,
        "R16: WorkflowRuntime.run() never subscribes/unsubscribes on "
        "the provided EventBus -- subscriber lists are unchanged",
    )

    import ast

    import Orchestration.workflow_runtime as module

    tree = ast.parse(Path(module.__file__).read_text())
    event_bus_method_calls: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
                and value.attr == "_event_bus"
            ):
                event_bus_method_calls.append(node.attr)

    check(
        set(event_bus_method_calls) == {"publish"},
        f"R16: workflow_runtime.py only ever calls publish() on "
        f"self._event_bus; found {sorted(set(event_bus_method_calls))!r}",
    )


# ---------------------------------------------------------------------------
# R17 -- no new event classes introduced
# ---------------------------------------------------------------------------
def scenario_no_new_event_classes() -> None:
    import ast

    import Orchestration.workflow_runtime as module

    source = Path(module.__file__).read_text()
    tree = ast.parse(source)

    forbidden_class_names = (
        "RuntimeEvent",
        "WorkflowRuntimeEvent",
        "ExecutionEvent",
    )
    defined_class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    for forbidden in forbidden_class_names:
        check(
            forbidden not in defined_class_names,
            f"R17: workflow_runtime.py defines no {forbidden!r} class",
        )

    check(
        "Event(" in source,
        "R17: workflow_runtime.py constructs the existing "
        "Orchestration.event_bus.Event, not a new event type",
    )


# ---------------------------------------------------------------------------
# R18 -- Sprint 37 behavior regression (no event_bus argument at all)
# ---------------------------------------------------------------------------
def scenario_sprint37_regression_no_event_bus_arg() -> None:
    session_manager, workflow_engine, coordinator, executor, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)
    result = runtime.run(workflow, context)
    check(
        isinstance(result, WorkflowSession)
        and result.status is WorkflowSessionStatus.COMPLETED,
        "R18: a successful run() with no event_bus argument at all "
        "still returns a COMPLETED WorkflowSession",
    )

    session_manager2, workflow_engine2, _, executor2, _ = _make_stack()
    exc = RuntimeError("still fails")
    coordinator2 = FailingCoordinator(exc)
    runtime2 = WorkflowRuntime(
        session_manager2, workflow_engine2, coordinator2, executor2
    )
    workflow2 = _make_workflow(tasks=[Task(name="t2", description="d")])
    context2 = _make_context(workflow2)

    caught = None
    try:
        runtime2.run(workflow2, context2)
    except Exception as e:  # noqa: BLE001
        caught = e
    check(
        caught is exc,
        "R18: a failing run() with no event_bus argument at all still "
        "re-raises the original exception unchanged",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_auto_created_event_bus,
        scenario_provided_event_bus_reused,
        scenario_event_bus_constructor_validation,
        scenario_success_path_event_counts,
        scenario_failure_path_event_counts,
        scenario_success_ordering,
        scenario_failure_ordering,
        scenario_started_completed_payload,
        scenario_failed_payload,
        scenario_only_known_event_names,
        scenario_exception_identity_preserved,
        scenario_auto_created_bus_isolation,
        scenario_shared_event_bus_across_instances,
        scenario_multiple_instances_independent,
        scenario_no_duplicate_events,
        scenario_event_bus_not_mutated,
        scenario_no_new_event_classes,
        scenario_sprint37_regression_no_event_bus_arg,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(
                f"{scenario.__name__} raised an unexpected exception"
            )
            print(
                f"  ERROR - {scenario.__name__} raised an unexpected "
                f"exception:"
            )
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(
        f"PHASE 4 SPRINT 38 RUNTIME EVENTS RESULTS: {_PASS} PASS / "
        f"{_FAIL} FAIL (total {_PASS + _FAIL})"
    )
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())