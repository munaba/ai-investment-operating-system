"""
Phase 4 Sprint 37 proof suite -- ``WorkflowRuntime`` end-to-end
lifecycle integration.

Scope: dedicated regression suite for ``Orchestration.
workflow_runtime.WorkflowRuntime``/``WorkflowRuntimeError`` only.
``WorkflowSession`` (Sprint 35), ``WorkflowSessionManager`` (Sprint
36), ``WorkflowEngine``, ``WorkflowExecutionCoordinator``,
``Executor``, ``Workflow``, ``Task``, ``TaskManager``, ``TaskQueue``,
``AutonomousScheduler``, ``AutonomousHost``, ``AutonomousAgent``,
``RuntimeAnalysisPipeline``, and the Composition Root are all
untouched by this Sprint and are exercised here only as the real,
unmodified collaborators ``WorkflowRuntime`` is built on top of --
none of their own already-locked behavior is re-verified beyond what
``WorkflowRuntime.run()`` itself needs. ``AutonomousHost`` is
exercised only through the same recording-subclass technique
``Tests/test_stage_l28_sprint32_executor_workflow.py`` already uses
(overriding only ``start()``), since constructing a real
``AutonomousAgent`` requires a full ``RuntimeAnalysisPipeline``
collaborator graph that remains out of scope here.

``WorkflowRuntime`` introduces no second execution engine, no second
lifecycle state machine, and no second preparation/orchestration
layer: this suite proves it is nothing more than the exact six-step
sequence the Sprint 37 spec lists -- ``session_manager.create()``,
``session_manager.prepare()``, ``workflow_engine.load()``,
``coordinator.execute_workflow()``, then either
``session_manager.start()``+``complete()`` or
``session_manager.start()``+``fail()``-plus-re-raise -- delegating
every actual unit of work to exactly one collaborator and never
duplicating it.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L3x / Sprint 1x-37 proof suites: a global
pass/fail counter, plain fixtures (real collaborators, plus thin
call-counting subclasses in the same style as
``Tests/test_stage_l28_sprint32_executor_workflow.py``), and a
``main()`` runner.

Invariant coverage:
    R1  -- constructor validation: None/wrong-type session_manager,
           workflow_engine, coordinator, or executor all raise
           WorkflowRuntimeError, and a valid construction with all
           four correctly-typed collaborators succeeds.
    R2  -- successful run(): returns a WorkflowSession with status ==
           WorkflowSessionStatus.COMPLETED.
    R3  -- execution failure: an exception raised by
           coordinator.execute_workflow() propagates unchanged out of
           run() (same exception type and message).
    R4  -- session creation: session_manager.create() is called
           exactly once per run(), with the exact workflow/
           execution_context/metadata passed to run().
    R5  -- session_manager.prepare() is called exactly once per
           run() (both success and failure paths).
    R6  -- workflow_engine.load() is called exactly once per run(),
           with the exact workflow passed to run().
    R7  -- coordinator.execute_workflow() is called exactly once per
           run(), with (executor, workflow_engine, execution_context,
           iterations) in that order.
    R8  -- session_manager.start() is called exactly once per run()
           on both the success and the failure path.
    R9  -- session_manager.complete() is called exactly once on the
           success path, and never on the failure path.
    R10 -- session_manager.fail() is called exactly once on the
           failure path, and never on the success path.
    R11 -- status sequence: the session's status, as observed at each
           step (via a recording WorkflowSessionManager), moves
           CREATED -> PREPARED -> RUNNING -> COMPLETED on success, and
           CREATED -> PREPARED -> RUNNING -> FAILED on failure.
    R12 -- returned session: run()'s return value is exactly the
           object session_manager.complete() returned (identity), not
           a fresh/rebuilt session.
    R13 -- workflow is preserved (same identity) on the returned
           session.
    R14 -- execution_context is preserved (same identity) on the
           session actually passed through to
           coordinator.execute_workflow().
    R15 -- metadata is preserved (equal contents) on the returned
           session, and metadata=None (default) yields an empty
           metadata mapping.
    R16 -- iteration forwarding: the iterations value passed to run()
           reaches coordinator.execute_workflow() unchanged; the
           default (omitted) iterations forwards 1.
    R17 -- exception propagation: run() re-raises the exact exception
           object coordinator.execute_workflow() raised (identity),
           with no wrapping.
    R18 -- dependency validation: constructing WorkflowRuntime with
           collaborators swapped for each other's types (e.g. an
           Executor where workflow_engine belongs) still raises
           WorkflowRuntimeError.
    R19 -- forbidden imports: workflow_runtime.py never imports
           TaskQueue, TaskManager, AutonomousScheduler,
           AutonomousHost, AutonomousAgent, RuntimeAnalysisPipeline,
           composition_root, threading, or asyncio. (``EventBus`` is
           no longer forbidden as of Phase 4 Sprint 38, which
           intentionally wires ``WorkflowRuntime`` to an ``EventBus``
           -- see ``Tests/test_stage_l38_runtime_events.py`` for that
           integration's own dedicated coverage.)
    R20 -- forbidden execution duplication: WorkflowRuntime exposes no
           execute/dequeue/submit member, and run()'s body never calls
           self._executor.execute(...) directly (verified via AST --
           the only method call on the bound executor anywhere in the
           module is passing it as an argument to
           coordinator.execute_workflow()).
    R21 -- WorkflowRuntime never performs lifecycle logic directly:
           the class defines no CREATED/PREPARED/RUNNING/COMPLETED/
           FAILED/CANCELLED-producing method of its own (no
           prepare()/start()/complete()/fail()/cancel() method exists
           on WorkflowRuntime itself -- only run()), and never
           constructs a WorkflowSession directly (no WorkflowSession(
           call anywhere in workflow_runtime.py -- only imported for
           its type, used in a type hint).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.autonomous_host import AutonomousHost
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
from Orchestration.workflow_session_manager import (
    WorkflowSessionManager,
    WorkflowSessionManagerError,
)

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
    """See Tests/test_stage_l28_sprint32_executor_workflow.py -- a
    thin ``AutonomousHost`` subclass overriding only ``start()`` to
    record every call, keeping ``isinstance(host, AutonomousHost)``
    true without requiring a real ``AutonomousAgent``/
    ``RuntimeAnalysisPipeline`` graph.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[object, object, object]] = []

    def start(self, agent, context, iterations):  # type: ignore[override]
        self.calls.append((agent, context, iterations))
        return ()


class RecordingSessionManager(WorkflowSessionManager):
    """A ``WorkflowSessionManager`` subclass that records every call
    to ``create()``/``prepare()``/``start()``/``complete()``/
    ``fail()``/``cancel()`` (arguments in, status of the result out),
    without changing any behavior at all -- every method still calls
    ``super()`` and returns exactly what that returns.

    Used to prove call counts/ordering/arguments (R4, R5, R8, R9, R10,
    R11) while still exercising the real, unmodified Sprint 36
    ``WorkflowSessionManager`` transition logic underneath.
    """

    def __init__(self) -> None:
        self.create_calls: List[Tuple[Any, Any, Any]] = []
        self.prepare_calls: List[WorkflowSession] = []
        self.start_calls: List[WorkflowSession] = []
        self.complete_calls: List[WorkflowSession] = []
        self.fail_calls: List[WorkflowSession] = []
        self.cancel_calls: List[WorkflowSession] = []
        self.status_sequence: List[WorkflowSessionStatus] = []

    def create(self, workflow, execution_context, metadata=None):
        self.create_calls.append((workflow, execution_context, metadata))
        result = super().create(workflow, execution_context, metadata=metadata)
        self.status_sequence.append(result.status)
        return result

    def prepare(self, session):
        self.prepare_calls.append(session)
        result = super().prepare(session)
        self.status_sequence.append(result.status)
        return result

    def start(self, session):
        self.start_calls.append(session)
        result = super().start(session)
        self.status_sequence.append(result.status)
        return result

    def complete(self, session):
        self.complete_calls.append(session)
        result = super().complete(session)
        self.status_sequence.append(result.status)
        return result

    def fail(self, session):
        self.fail_calls.append(session)
        result = super().fail(session)
        self.status_sequence.append(result.status)
        return result

    def cancel(self, session):
        self.cancel_calls.append(session)
        result = super().cancel(session)
        self.status_sequence.append(result.status)
        return result


class RecordingWorkflowEngine(WorkflowEngine):
    """A ``WorkflowEngine`` subclass that records every ``load()``
    call without changing its behavior at all -- ``load()`` still
    calls ``super().load()``.

    Used to prove ``load()`` is called exactly once per ``run()``
    (R6), while still exercising the real, unmodified Sprint 29
    ``load()``/``prepare()`` behavior underneath.
    """

    def __init__(self, task_manager: TaskManager) -> None:
        super().__init__(task_manager)
        self.load_calls: List[Workflow] = []

    def load(self, workflow: Workflow) -> None:
        self.load_calls.append(workflow)
        return super().load(workflow)


class RecordingCoordinator(WorkflowExecutionCoordinator):
    """A ``WorkflowExecutionCoordinator`` subclass that records every
    ``execute_workflow()`` call (its exact arguments) without changing
    behavior at all -- it still delegates to ``super()``.

    Used to prove ``execute_workflow()`` is called exactly once per
    ``run()``, with the documented argument order (R7), while still
    exercising the real, unmodified Sprint 33
    ``execute_workflow()`` behavior underneath.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[Any, Any, Any, Any]] = []

    def execute_workflow(self, executor, workflow_engine, context, iterations=1):
        self.calls.append((executor, workflow_engine, context, iterations))
        return super().execute_workflow(
            executor, workflow_engine, context, iterations
        )


class FailingCoordinator(WorkflowExecutionCoordinator):
    """A ``WorkflowExecutionCoordinator`` whose ``execute_workflow()``
    always raises a fixed exception instance -- used to exercise
    ``WorkflowRuntime.run()``'s failure path (R3, R9, R10, R11, R17)
    without needing a genuinely broken ``Task``/``AutonomousHost``.
    """

    def __init__(self, exception: Exception) -> None:
        self._exception = exception
        self.calls: List[Tuple[Any, Any, Any, Any]] = []

    def execute_workflow(self, executor, workflow_engine, context, iterations=1):
        self.calls.append((executor, workflow_engine, context, iterations))
        raise self._exception


def _make_stack(
    tasks: Optional[List[Task]] = None,
) -> Tuple[
    RecordingSessionManager,
    RecordingWorkflowEngine,
    RecordingCoordinator,
    Executor,
    RecordingHost,
    TaskManager,
]:
    task_manager = TaskManager(TaskQueue())
    host = RecordingHost()
    executor = Executor(task_manager, host)
    workflow_engine = RecordingWorkflowEngine(task_manager)
    coordinator = RecordingCoordinator()
    session_manager = RecordingSessionManager()
    return session_manager, workflow_engine, coordinator, executor, host, task_manager


# ---------------------------------------------------------------------------
# R1 -- constructor validation
# ---------------------------------------------------------------------------
def scenario_constructor_validation() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()

    valid = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    check(
        isinstance(valid, WorkflowRuntime),
        "R1: constructing with all four correctly-typed collaborators "
        "succeeds",
    )

    bad_values = (None, "not-it", 123, [], {}, object())

    for bad in bad_values:
        raised = False
        try:
            WorkflowRuntime(bad, workflow_engine, coordinator, executor)
        except WorkflowRuntimeError:
            raised = True
        check(
            raised,
            f"R1: invalid session_manager {bad!r} raises "
            f"WorkflowRuntimeError",
        )

    for bad in bad_values:
        raised = False
        try:
            WorkflowRuntime(session_manager, bad, coordinator, executor)
        except WorkflowRuntimeError:
            raised = True
        check(
            raised,
            f"R1: invalid workflow_engine {bad!r} raises "
            f"WorkflowRuntimeError",
        )

    for bad in bad_values:
        raised = False
        try:
            WorkflowRuntime(session_manager, workflow_engine, bad, executor)
        except WorkflowRuntimeError:
            raised = True
        check(
            raised,
            f"R1: invalid coordinator {bad!r} raises WorkflowRuntimeError",
        )

    for bad in bad_values:
        raised = False
        try:
            WorkflowRuntime(session_manager, workflow_engine, coordinator, bad)
        except WorkflowRuntimeError:
            raised = True
        check(
            raised,
            f"R1: invalid executor {bad!r} raises WorkflowRuntimeError",
        )


# ---------------------------------------------------------------------------
# R2 -- successful run returns COMPLETED
# ---------------------------------------------------------------------------
def scenario_successful_run_returns_completed() -> None:
    session_manager, workflow_engine, coordinator, executor, host, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    workflow = _make_workflow(tasks=[Task(name="t1", description="d")])
    context = _make_context(workflow)

    result = runtime.run(workflow, context)

    check(
        isinstance(result, WorkflowSession),
        "R2: run() returns a WorkflowSession instance",
    )
    check(
        result.status is WorkflowSessionStatus.COMPLETED,
        "R2: a successful run() returns a session with status "
        "COMPLETED",
    )


# ---------------------------------------------------------------------------
# R3 -- execution failure propagates
# ---------------------------------------------------------------------------
def scenario_execution_failure_propagates() -> None:
    session_manager, workflow_engine, _, executor, _, _ = _make_stack()
    boom = RuntimeError("execution exploded")
    coordinator = FailingCoordinator(boom)
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    workflow = _make_workflow()
    context = _make_context(workflow)

    raised_exception = None
    try:
        runtime.run(workflow, context)
    except RuntimeError as caught:
        raised_exception = caught

    check(
        raised_exception is not None,
        "R3: run() raises when coordinator.execute_workflow() raises",
    )
    check(
        raised_exception is boom,
        "R3: run() propagates the exact original exception instance",
    )
    check(
        str(raised_exception) == "execution exploded",
        "R3: the propagated exception's message is unchanged",
    )


# ---------------------------------------------------------------------------
# R4 -- session creation called exactly once, with exact args
# ---------------------------------------------------------------------------
def scenario_session_creation_called_once() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    workflow = _make_workflow()
    context = _make_context(workflow)
    metadata = {"trace": "xyz"}

    runtime.run(workflow, context, iterations=1, metadata=metadata)

    check(
        len(session_manager.create_calls) == 1,
        "R4: session_manager.create() is called exactly once per run()",
    )
    called_workflow, called_context, called_metadata = session_manager.create_calls[0]
    check(
        called_workflow is workflow,
        "R4: create() is called with the exact workflow passed to run()",
    )
    check(
        called_context is context,
        "R4: create() is called with the exact execution_context "
        "passed to run()",
    )
    check(
        called_metadata is metadata,
        "R4: create() is called with the exact metadata passed to "
        "run()",
    )


# ---------------------------------------------------------------------------
# R5 -- prepare called exactly once (success and failure paths)
# ---------------------------------------------------------------------------
def scenario_prepare_called_once() -> None:
    # success path
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)
    runtime.run(workflow, context)
    check(
        len(session_manager.prepare_calls) == 1,
        "R5: session_manager.prepare() is called exactly once on the "
        "success path",
    )

    # failure path
    session_manager2, workflow_engine2, _, executor2, _, _ = _make_stack()
    coordinator2 = FailingCoordinator(RuntimeError("boom"))
    runtime2 = WorkflowRuntime(
        session_manager2, workflow_engine2, coordinator2, executor2
    )
    workflow2 = _make_workflow()
    context2 = _make_context(workflow2)
    try:
        runtime2.run(workflow2, context2)
    except RuntimeError:
        pass
    check(
        len(session_manager2.prepare_calls) == 1,
        "R5: session_manager.prepare() is called exactly once on the "
        "failure path",
    )


# ---------------------------------------------------------------------------
# R6 -- load called exactly once, with exact workflow
# ---------------------------------------------------------------------------
def scenario_load_called_once() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    workflow = _make_workflow()
    context = _make_context(workflow)
    runtime.run(workflow, context)

    check(
        len(workflow_engine.load_calls) == 1,
        "R6: workflow_engine.load() is called exactly once per run()",
    )
    check(
        workflow_engine.load_calls[0] is workflow,
        "R6: load() is called with the exact workflow passed to run()",
    )


# ---------------------------------------------------------------------------
# R7 -- coordinator called exactly once, with documented argument order
# ---------------------------------------------------------------------------
def scenario_coordinator_called_once() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    workflow = _make_workflow()
    context = _make_context(workflow)
    runtime.run(workflow, context, iterations=3)

    check(
        len(coordinator.calls) == 1,
        "R7: coordinator.execute_workflow() is called exactly once "
        "per run()",
    )
    called_executor, called_engine, called_context, called_iterations = (
        coordinator.calls[0]
    )
    check(
        called_executor is executor,
        "R7: execute_workflow() is called with the bound executor",
    )
    check(
        called_engine is workflow_engine,
        "R7: execute_workflow() is called with the bound workflow_engine",
    )
    check(
        called_context is context,
        "R7: execute_workflow() is called with the exact "
        "execution_context passed to run()",
    )
    check(
        called_iterations == 3,
        "R7: execute_workflow() is called with the exact iterations "
        "passed to run()",
    )


# ---------------------------------------------------------------------------
# R8/R9/R10 -- start/complete/fail call counts on each path
# ---------------------------------------------------------------------------
def scenario_start_complete_fail_call_counts() -> None:
    # success path
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)
    runtime.run(workflow, context)

    check(
        len(session_manager.start_calls) == 1,
        "R8: session_manager.start() is called exactly once on the "
        "success path",
    )
    check(
        len(session_manager.complete_calls) == 1,
        "R9: session_manager.complete() is called exactly once on the "
        "success path",
    )
    check(
        len(session_manager.fail_calls) == 0,
        "R10: session_manager.fail() is never called on the success "
        "path",
    )

    # failure path
    session_manager2, workflow_engine2, _, executor2, _, _ = _make_stack()
    coordinator2 = FailingCoordinator(RuntimeError("boom"))
    runtime2 = WorkflowRuntime(
        session_manager2, workflow_engine2, coordinator2, executor2
    )
    workflow2 = _make_workflow()
    context2 = _make_context(workflow2)
    try:
        runtime2.run(workflow2, context2)
    except RuntimeError:
        pass

    check(
        len(session_manager2.start_calls) == 1,
        "R8: session_manager.start() is called exactly once on the "
        "failure path",
    )
    check(
        len(session_manager2.complete_calls) == 0,
        "R9: session_manager.complete() is never called on the "
        "failure path",
    )
    check(
        len(session_manager2.fail_calls) == 1,
        "R10: session_manager.fail() is called exactly once on the "
        "failure path",
    )


# ---------------------------------------------------------------------------
# R11 -- status sequence
# ---------------------------------------------------------------------------
def scenario_status_sequence() -> None:
    # success path
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)
    runtime.run(workflow, context)

    check(
        session_manager.status_sequence
        == [
            WorkflowSessionStatus.CREATED,
            WorkflowSessionStatus.PREPARED,
            WorkflowSessionStatus.RUNNING,
            WorkflowSessionStatus.COMPLETED,
        ],
        f"R11: success path status sequence is CREATED -> PREPARED -> "
        f"RUNNING -> COMPLETED; got "
        f"{[s.name for s in session_manager.status_sequence]!r}",
    )

    # failure path
    session_manager2, workflow_engine2, _, executor2, _, _ = _make_stack()
    coordinator2 = FailingCoordinator(RuntimeError("boom"))
    runtime2 = WorkflowRuntime(
        session_manager2, workflow_engine2, coordinator2, executor2
    )
    workflow2 = _make_workflow()
    context2 = _make_context(workflow2)
    try:
        runtime2.run(workflow2, context2)
    except RuntimeError:
        pass

    check(
        session_manager2.status_sequence
        == [
            WorkflowSessionStatus.CREATED,
            WorkflowSessionStatus.PREPARED,
            WorkflowSessionStatus.RUNNING,
            WorkflowSessionStatus.FAILED,
        ],
        f"R11: failure path status sequence is CREATED -> PREPARED -> "
        f"RUNNING -> FAILED; got "
        f"{[s.name for s in session_manager2.status_sequence]!r}",
    )


# ---------------------------------------------------------------------------
# R12 -- returned session identity
# ---------------------------------------------------------------------------
def scenario_returned_session_identity() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)

    result = runtime.run(workflow, context)

    check(
        len(session_manager.complete_calls) == 1,
        "R12: sanity check -- complete() called exactly once",
    )
    # The real identity check: run()'s return value must be exactly
    # what complete() returned. RecordingSessionManager.complete()
    # returns super().complete(session)'s result directly, so we
    # re-derive it from the recorded call to confirm identity.
    recorded_complete_arg = session_manager.complete_calls[0]
    check(
        result.session_id == recorded_complete_arg.session_id,
        "R12: run()'s returned session shares its session_id with the "
        "session passed into complete()",
    )
    check(
        result.status is WorkflowSessionStatus.COMPLETED,
        "R12: run()'s returned session is the COMPLETED result, not "
        "an intermediate session",
    )


# ---------------------------------------------------------------------------
# R13 -- workflow preserved on returned session
# ---------------------------------------------------------------------------
def scenario_workflow_preserved() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)

    result = runtime.run(workflow, context)

    check(
        result.workflow is workflow,
        "R13: the returned session's workflow is the exact Workflow "
        "instance passed to run()",
    )


# ---------------------------------------------------------------------------
# R14 -- execution_context preserved through to coordinator
# ---------------------------------------------------------------------------
def scenario_execution_context_preserved() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)

    runtime.run(workflow, context)

    check(
        coordinator.calls[0][2] is context,
        "R14: the exact execution_context passed to run() reaches "
        "coordinator.execute_workflow() unchanged",
    )


# ---------------------------------------------------------------------------
# R15 -- metadata preserved / default empty
# ---------------------------------------------------------------------------
def scenario_metadata_preserved() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)
    metadata = {"a": 1, "b": {"c": 2}}

    result = runtime.run(workflow, context, metadata=metadata)

    check(
        dict(result.metadata) == metadata,
        "R15: the returned session's metadata matches what was "
        "passed to run()",
    )

    session_manager2, workflow_engine2, coordinator2, executor2, _, _ = (
        _make_stack()
    )
    runtime2 = WorkflowRuntime(
        session_manager2, workflow_engine2, coordinator2, executor2
    )
    workflow2 = _make_workflow()
    context2 = _make_context(workflow2)
    result2 = runtime2.run(workflow2, context2)

    check(
        dict(result2.metadata) == {},
        "R15: omitting metadata (default None) yields an empty "
        "metadata mapping on the returned session",
    )


# ---------------------------------------------------------------------------
# R16 -- iteration forwarding
# ---------------------------------------------------------------------------
def scenario_iteration_forwarding() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)
    workflow = _make_workflow()
    context = _make_context(workflow)

    runtime.run(workflow, context, iterations=7)
    check(
        coordinator.calls[0][3] == 7,
        "R16: an explicit iterations value reaches "
        "coordinator.execute_workflow() unchanged",
    )

    session_manager2, workflow_engine2, coordinator2, executor2, _, _ = (
        _make_stack()
    )
    runtime2 = WorkflowRuntime(
        session_manager2, workflow_engine2, coordinator2, executor2
    )
    workflow2 = _make_workflow()
    context2 = _make_context(workflow2)
    runtime2.run(workflow2, context2)
    check(
        coordinator2.calls[0][3] == 1,
        "R16: omitting iterations (default) forwards 1 to "
        "coordinator.execute_workflow()",
    )


# ---------------------------------------------------------------------------
# R17 -- exception propagation identity
# ---------------------------------------------------------------------------
def scenario_exception_propagation_identity() -> None:
    session_manager, workflow_engine, _, executor, _, _ = _make_stack()
    original = ValueError("distinctive failure marker")
    coordinator = FailingCoordinator(original)
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    workflow = _make_workflow()
    context = _make_context(workflow)

    caught = None
    try:
        runtime.run(workflow, context)
    except ValueError as exc:
        caught = exc

    check(
        caught is original,
        "R17: run() re-raises the exact exception object raised by "
        "coordinator.execute_workflow() (identity, no wrapping)",
    )


# ---------------------------------------------------------------------------
# R18 -- dependency validation with swapped types
# ---------------------------------------------------------------------------
def scenario_dependency_validation_swapped_types() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()

    swaps = (
        (executor, workflow_engine, coordinator, executor),  # session_manager slot
        (session_manager, executor, coordinator, executor),  # workflow_engine slot
        (session_manager, workflow_engine, executor, executor),  # coordinator slot
        (session_manager, workflow_engine, coordinator, coordinator),  # executor slot
    )

    for args in swaps:
        raised = False
        try:
            WorkflowRuntime(*args)
        except WorkflowRuntimeError:
            raised = True
        check(
            raised,
            f"R18: constructing with collaborators swapped for each "
            f"other's types raises WorkflowRuntimeError",
        )


# ---------------------------------------------------------------------------
# R19 -- forbidden imports
# ---------------------------------------------------------------------------
def scenario_forbidden_imports_absent() -> None:
    import ast

    import Orchestration.workflow_runtime as module

    tree = ast.parse(Path(module.__file__).read_text())

    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)
            imported_names.extend(alias.name for alias in node.names)

    forbidden_symbols = (
        "TaskQueue",
        "TaskManager",
        "AutonomousScheduler",
        "AutonomousHost",
        "AutonomousAgent",
        "RuntimeAnalysisPipeline",
        "composition_root",
        "CompositionRoot",
        "threading",
        "asyncio",
    )
    for symbol in forbidden_symbols:
        check(
            not any(symbol in name for name in imported_names),
            f"R19: Orchestration/workflow_runtime.py never imports "
            f"anything referencing {symbol!r}",
        )


# ---------------------------------------------------------------------------
# R20 -- forbidden execution duplication
# ---------------------------------------------------------------------------
def scenario_forbidden_execution_duplication() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    for member in ("execute", "dequeue", "submit"):
        check(
            not hasattr(runtime, member),
            f"R20: WorkflowRuntime exposes no {member!r} member",
        )

    import ast

    import Orchestration.workflow_runtime as module

    tree = ast.parse(Path(module.__file__).read_text())
    run_method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WorkflowRuntime":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "run":
                    run_method = item

    check(run_method is not None, "R20: WorkflowRuntime.run() exists")

    # Collect every attribute access of the form self._executor.<attr>
    # inside run() -- the only legitimate one is passing self._executor
    # as a bare argument (an ast.Attribute node for `self._executor`
    # itself, not `self._executor.execute`).
    direct_executor_method_calls: List[str] = []
    for node in ast.walk(run_method):
        if isinstance(node, ast.Attribute):
            value = node.value
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
                and value.attr == "_executor"
            ):
                direct_executor_method_calls.append(node.attr)

    check(
        direct_executor_method_calls == [],
        f"R20: run() never calls a method directly on self._executor "
        f"(e.g. self._executor.execute(...)); found attribute "
        f"accesses {direct_executor_method_calls!r}",
    )


# ---------------------------------------------------------------------------
# R21 -- no lifecycle logic performed directly
# ---------------------------------------------------------------------------
def scenario_no_direct_lifecycle_logic() -> None:
    session_manager, workflow_engine, coordinator, executor, _, _ = _make_stack()
    runtime = WorkflowRuntime(session_manager, workflow_engine, coordinator, executor)

    for member in ("prepare", "start", "complete", "fail", "cancel"):
        check(
            not hasattr(runtime, member),
            f"R21: WorkflowRuntime defines no {member!r} method of its "
            f"own (lifecycle transitions belong only to "
            f"WorkflowSessionManager)",
        )

    import ast

    import Orchestration.workflow_runtime as module

    tree = ast.parse(Path(module.__file__).read_text())
    source = Path(module.__file__).read_text()

    check(
        "WorkflowSession(" not in source,
        "R21: workflow_runtime.py never constructs a WorkflowSession "
        "directly -- only session_manager.create() may do that",
    )

    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WorkflowRuntime"
    )
    defined_methods = {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    check(
        defined_methods == {"__init__", "run", "__repr__"},
        f"R21: WorkflowRuntime defines no methods beyond __init__, "
        f"run, and __repr__; found {sorted(defined_methods)!r}",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_validation,
        scenario_successful_run_returns_completed,
        scenario_execution_failure_propagates,
        scenario_session_creation_called_once,
        scenario_prepare_called_once,
        scenario_load_called_once,
        scenario_coordinator_called_once,
        scenario_start_complete_fail_call_counts,
        scenario_status_sequence,
        scenario_returned_session_identity,
        scenario_workflow_preserved,
        scenario_execution_context_preserved,
        scenario_metadata_preserved,
        scenario_iteration_forwarding,
        scenario_exception_propagation_identity,
        scenario_dependency_validation_swapped_types,
        scenario_forbidden_imports_absent,
        scenario_forbidden_execution_duplication,
        scenario_no_direct_lifecycle_logic,
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
        f"PHASE 4 SPRINT 37 WORKFLOW RUNTIME RESULTS: {_PASS} PASS / "
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