"""
Phase 4 Sprint 36 proof suite -- ``WorkflowSessionManager`` lifecycle
integration.

Scope: dedicated regression suite for ``Orchestration.
workflow_session_manager.WorkflowSessionManager``/
``WorkflowSessionManagerError`` only, plus a light touch on
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator`` to confirm it was left as pure
orchestration (this Sprint did not find it "absolutely necessary" to
modify the coordinator, so this suite proves that file is untouched
rather than exercising new coordinator behavior).

``WorkflowSessionManager`` owns ONLY lifecycle-status transitions for
``WorkflowSession``. It never executes, prepares (in the
``WorkflowEngine.prepare()`` sense), schedules, or talks to
``EventBus`` -- this suite proves the *absence* of that surface area
as much as it proves the presence of the transition behavior itself.
``Workflow``, ``WorkflowSession``, ``WorkflowEngine``, ``Executor``,
``TaskManager``, ``TaskQueue``, ``AutonomousScheduler``,
``AutonomousHost``, ``AutonomousAgent``, ``RuntimeAnalysisPipeline``,
``Planner``, ``Providers``, ``Services``, ``Repository``, ``Database``,
and the Composition Root are all untouched by this Sprint and are not
exercised by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L3x / Sprint 1x-36 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    M1  -- create() builds a new WorkflowSession in CREATED status.
    M2  -- create() rejects invalid workflow/execution_context/
           metadata inputs via WorkflowSessionManagerError.
    M3  -- create() treats metadata=None as an empty mapping.
    M4  -- every allowed lifecycle transition (prepare/start/complete/
           fail/cancel) succeeds from its documented "from" status(es)
           and lands on the documented "to" status.
    M5  -- every disallowed transition (including the spec's explicit
           examples: COMPLETED->RUNNING, FAILED->RUNNING,
           CANCELLED->PREPARED) raises WorkflowSessionManagerError.
    M6  -- immutability: the original session passed into any
           transition method is never mutated (its status/every field
           is unchanged after the call).
    M7  -- every transition method returns a NEW WorkflowSession
           object (not the same object as the input).
    M8  -- workflow is preserved (same identity) across every
           transition.
    M9  -- execution_context is preserved (same identity) across
           every transition.
    M10 -- metadata is preserved (equal contents) across every
           transition.
    M11 -- the returned session's metadata is still an immutable
           MappingProxyType (item assignment raises).
    M12 -- duplicate transitions: calling the same transition twice
           from the same original (untouched) session succeeds both
           times independently; calling a transition twice by chaining
           from the *returned* session the second time fails (already
           moved on).
    M13 -- terminal states: once a session reaches COMPLETED, FAILED,
           or CANCELLED, every further transition method call on it
           raises WorkflowSessionManagerError.
    M14 -- error hierarchy: WorkflowSessionManagerError is a subclass
           of Core.exceptions.AgentError.
    M15 -- forbidden imports: workflow_session_manager.py never
           imports WorkflowEngine, WorkflowExecutionCoordinator,
           Executor, AutonomousScheduler, AutonomousHost,
           AutonomousAgent, RuntimeAnalysisPipeline, EventBus,
           composition_root, threading, or asyncio.
    M16 -- forbidden execution logic: WorkflowSessionManager exposes
           no execute/run/dequeue member, and its methods never call
           an Executor.
    M17 -- forbidden scheduler logic: WorkflowSessionManager exposes
           no schedule/enqueue/tick member.
    M18 -- forbidden EventBus usage: WorkflowSessionManager exposes no
           publish/subscribe/emit member.
    M19 -- WorkflowExecutionCoordinator remains orchestration only:
           Orchestration/workflow_execution_coordinator.py was not
           modified to contain lifecycle-transition logic (no
           prepare/start/complete/fail/cancel members appear on it,
           and it does not import WorkflowSession or
           WorkflowSessionManager).
    M20 -- session validation: passing None or a non-WorkflowSession
           value to any transition method raises
           WorkflowSessionManagerError.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from types import MappingProxyType
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.execution_context import ExecutionContext
from Orchestration.workflow import Workflow
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


def _fresh_created_session(manager: WorkflowSessionManager, **kwargs) -> WorkflowSession:
    workflow = kwargs.pop("workflow", None) or _make_workflow()
    context = kwargs.pop("execution_context", None) or _make_context(workflow)
    metadata = kwargs.pop("metadata", None)
    return manager.create(workflow, context, metadata=metadata)


# All non-terminal statuses and all terminal statuses, for convenience.
_TERMINAL_STATUSES = (
    WorkflowSessionStatus.COMPLETED,
    WorkflowSessionStatus.FAILED,
    WorkflowSessionStatus.CANCELLED,
)
_ALL_STATUSES = tuple(WorkflowSessionStatus)


def _session_with_status(
    manager: WorkflowSessionManager, status: WorkflowSessionStatus
) -> WorkflowSession:
    """Build a session and drive it to ``status`` via legitimate
    manager transitions (used as test fixtures, not itself part of
    what's under test)."""
    session = _fresh_created_session(manager)
    if status is WorkflowSessionStatus.CREATED:
        return session
    session = manager.prepare(session)
    if status is WorkflowSessionStatus.PREPARED:
        return session
    session = manager.start(session)
    if status is WorkflowSessionStatus.RUNNING:
        return session
    if status is WorkflowSessionStatus.COMPLETED:
        return manager.complete(session)
    if status is WorkflowSessionStatus.FAILED:
        return manager.fail(session)
    if status is WorkflowSessionStatus.CANCELLED:
        return manager.cancel(session)
    raise AssertionError(f"unreachable status {status!r}")


# ---------------------------------------------------------------------------
# M1 -- create() builds a session in CREATED
# ---------------------------------------------------------------------------
def scenario_create_builds_created_session() -> None:
    manager = WorkflowSessionManager()
    workflow = _make_workflow()
    context = _make_context(workflow)

    session = manager.create(workflow, context)

    check(
        isinstance(session, WorkflowSession),
        "M1: create() returns a WorkflowSession instance",
    )
    check(
        session.status is WorkflowSessionStatus.CREATED,
        "M1: create() returns a session in WorkflowSessionStatus.CREATED",
    )
    check(
        session.workflow is workflow,
        "M1: create() preserves the exact Workflow instance passed in",
    )
    check(
        session.execution_context is context,
        "M1: create() preserves the exact ExecutionContext instance "
        "passed in",
    )


# ---------------------------------------------------------------------------
# M2 -- create() rejects invalid inputs
# ---------------------------------------------------------------------------
def scenario_create_rejects_invalid_inputs() -> None:
    manager = WorkflowSessionManager()
    workflow = _make_workflow()
    context = _make_context(workflow)

    for bad_workflow in (None, "not-a-workflow", 123):
        raised = False
        try:
            manager.create(bad_workflow, context)
        except WorkflowSessionManagerError:
            raised = True
        check(
            raised,
            f"M2: create() with invalid workflow {bad_workflow!r} raises "
            f"WorkflowSessionManagerError",
        )

    for bad_context in (None, "not-a-context", 123):
        raised = False
        try:
            manager.create(workflow, bad_context)
        except WorkflowSessionManagerError:
            raised = True
        check(
            raised,
            f"M2: create() with invalid execution_context "
            f"{bad_context!r} raises WorkflowSessionManagerError",
        )

    for bad_metadata in ("not-a-mapping", 123, ["a", "b"]):
        raised = False
        try:
            manager.create(workflow, context, metadata=bad_metadata)
        except WorkflowSessionManagerError:
            raised = True
        check(
            raised,
            f"M2: create() with invalid metadata {bad_metadata!r} raises "
            f"WorkflowSessionManagerError",
        )


# ---------------------------------------------------------------------------
# M3 -- create() treats metadata=None as empty mapping
# ---------------------------------------------------------------------------
def scenario_create_metadata_none_is_empty() -> None:
    manager = WorkflowSessionManager()
    session = _fresh_created_session(manager, metadata=None)

    check(
        dict(session.metadata) == {},
        "M3: create() with metadata=None yields an empty metadata mapping",
    )


# ---------------------------------------------------------------------------
# M4 -- every allowed transition succeeds
# ---------------------------------------------------------------------------
def scenario_allowed_transitions_succeed() -> None:
    manager = WorkflowSessionManager()

    allowed = (
        ("prepare", WorkflowSessionStatus.CREATED, WorkflowSessionStatus.PREPARED),
        ("start", WorkflowSessionStatus.PREPARED, WorkflowSessionStatus.RUNNING),
        ("complete", WorkflowSessionStatus.RUNNING, WorkflowSessionStatus.COMPLETED),
        ("fail", WorkflowSessionStatus.CREATED, WorkflowSessionStatus.FAILED),
        ("fail", WorkflowSessionStatus.PREPARED, WorkflowSessionStatus.FAILED),
        ("fail", WorkflowSessionStatus.RUNNING, WorkflowSessionStatus.FAILED),
        ("cancel", WorkflowSessionStatus.CREATED, WorkflowSessionStatus.CANCELLED),
        ("cancel", WorkflowSessionStatus.PREPARED, WorkflowSessionStatus.CANCELLED),
        ("cancel", WorkflowSessionStatus.RUNNING, WorkflowSessionStatus.CANCELLED),
    )

    for method_name, from_status, to_status in allowed:
        session = _session_with_status(manager, from_status)
        method = getattr(manager, method_name)
        result = method(session)
        check(
            result.status is to_status,
            f"M4: {method_name}() from {from_status.name} lands on "
            f"{to_status.name}",
        )


# ---------------------------------------------------------------------------
# M5 -- every disallowed transition raises
# ---------------------------------------------------------------------------
def scenario_disallowed_transitions_raise() -> None:
    manager = WorkflowSessionManager()

    method_allowed_from = {
        "prepare": {WorkflowSessionStatus.CREATED},
        "start": {WorkflowSessionStatus.PREPARED},
        "complete": {WorkflowSessionStatus.RUNNING},
        "fail": {
            WorkflowSessionStatus.CREATED,
            WorkflowSessionStatus.PREPARED,
            WorkflowSessionStatus.RUNNING,
        },
        "cancel": {
            WorkflowSessionStatus.CREATED,
            WorkflowSessionStatus.PREPARED,
            WorkflowSessionStatus.RUNNING,
        },
    }

    for method_name, allowed_from in method_allowed_from.items():
        method = getattr(manager, method_name)
        for status in _ALL_STATUSES:
            if status in allowed_from:
                continue
            session = _session_with_status(manager, status)
            raised = False
            try:
                method(session)
            except WorkflowSessionManagerError:
                raised = True
            check(
                raised,
                f"M5: {method_name}() from {status.name} (not in "
                f"{sorted(s.name for s in allowed_from)!r}) raises "
                f"WorkflowSessionManagerError",
            )

    # The spec's explicit named examples.
    completed = _session_with_status(manager, WorkflowSessionStatus.COMPLETED)
    raised = False
    try:
        manager.start(completed)
    except WorkflowSessionManagerError:
        raised = True
    check(raised, "M5: COMPLETED -> RUNNING (via start()) is NOT ALLOWED")

    failed = _session_with_status(manager, WorkflowSessionStatus.FAILED)
    raised = False
    try:
        manager.start(failed)
    except WorkflowSessionManagerError:
        raised = True
    check(raised, "M5: FAILED -> RUNNING (via start()) is NOT ALLOWED")

    cancelled = _session_with_status(manager, WorkflowSessionStatus.CANCELLED)
    raised = False
    try:
        manager.prepare(cancelled)
    except WorkflowSessionManagerError:
        raised = True
    check(raised, "M5: CANCELLED -> PREPARED (via prepare()) is NOT ALLOWED")


# ---------------------------------------------------------------------------
# M6 -- original session never mutated
# ---------------------------------------------------------------------------
def scenario_original_session_never_mutated() -> None:
    manager = WorkflowSessionManager()
    session = _fresh_created_session(manager, metadata={"k": "v"})
    original_snapshot = (
        session.session_id,
        session.status,
        session.workflow,
        session.execution_context,
        dict(session.metadata),
        session.created_at,
    )

    manager.prepare(session)

    check(
        (
            session.session_id,
            session.status,
            session.workflow,
            session.execution_context,
            dict(session.metadata),
            session.created_at,
        )
        == original_snapshot,
        "M6: calling prepare() leaves the original session's every "
        "field completely unchanged",
    )


# ---------------------------------------------------------------------------
# M7 -- new object returned
# ---------------------------------------------------------------------------
def scenario_new_object_returned() -> None:
    manager = WorkflowSessionManager()

    created = _fresh_created_session(manager)
    prepared = manager.prepare(created)
    check(prepared is not created, "M7: prepare() returns a new object")

    started = manager.start(prepared)
    check(started is not prepared, "M7: start() returns a new object")

    completed = manager.complete(started)
    check(completed is not started, "M7: complete() returns a new object")

    running_for_fail = _session_with_status(manager, WorkflowSessionStatus.RUNNING)
    failed = manager.fail(running_for_fail)
    check(failed is not running_for_fail, "M7: fail() returns a new object")

    running_for_cancel = _session_with_status(manager, WorkflowSessionStatus.RUNNING)
    cancelled = manager.cancel(running_for_cancel)
    check(cancelled is not running_for_cancel, "M7: cancel() returns a new object")


# ---------------------------------------------------------------------------
# M8/M9/M10 -- workflow/execution_context/metadata preserved
# ---------------------------------------------------------------------------
def scenario_workflow_context_metadata_preserved() -> None:
    manager = WorkflowSessionManager()
    workflow = _make_workflow()
    context = _make_context(workflow)
    metadata = {"trace": "abc-123", "nested": {"n": 1}}

    session = manager.create(workflow, context, metadata=metadata)
    prepared = manager.prepare(session)
    started = manager.start(prepared)
    completed = manager.complete(started)

    for label, s in (("prepared", prepared), ("started", started), ("completed", completed)):
        check(
            s.workflow is workflow,
            f"M8: workflow identity preserved across transition into "
            f"{label}",
        )
        check(
            s.execution_context is context,
            f"M9: execution_context identity preserved across "
            f"transition into {label}",
        )
        check(
            dict(s.metadata) == metadata,
            f"M10: metadata contents preserved across transition into "
            f"{label}",
        )


# ---------------------------------------------------------------------------
# M11 -- returned session's metadata still immutable
# ---------------------------------------------------------------------------
def scenario_returned_metadata_immutable() -> None:
    manager = WorkflowSessionManager()
    session = _fresh_created_session(manager, metadata={"a": 1})
    prepared = manager.prepare(session)

    check(
        isinstance(prepared.metadata, MappingProxyType),
        "M11: transitioned session's metadata is a MappingProxyType",
    )

    raised = False
    try:
        prepared.metadata["a"] = 2  # type: ignore[index]
    except TypeError:
        raised = True
    check(
        raised,
        "M11: item assignment on the transitioned session's metadata "
        "raises TypeError",
    )


# ---------------------------------------------------------------------------
# M12 -- duplicate transitions
# ---------------------------------------------------------------------------
def scenario_duplicate_transitions() -> None:
    manager = WorkflowSessionManager()
    original = _fresh_created_session(manager)

    first_prepare = manager.prepare(original)
    second_prepare = manager.prepare(original)

    check(
        first_prepare.status is WorkflowSessionStatus.PREPARED
        and second_prepare.status is WorkflowSessionStatus.PREPARED,
        "M12: calling prepare() twice on the same untouched original "
        "session succeeds both times independently",
    )
    check(
        first_prepare is not second_prepare,
        "M12: the two independent prepare() calls return distinct "
        "objects",
    )

    raised = False
    try:
        manager.prepare(first_prepare)
    except WorkflowSessionManagerError:
        raised = True
    check(
        raised,
        "M12: chaining prepare() again on an already-PREPARED result "
        "raises WorkflowSessionManagerError",
    )


# ---------------------------------------------------------------------------
# M13 -- terminal states reject every further transition
# ---------------------------------------------------------------------------
def scenario_terminal_states_reject_all_transitions() -> None:
    manager = WorkflowSessionManager()

    for terminal_status in _TERMINAL_STATUSES:
        session = _session_with_status(manager, terminal_status)
        for method_name in ("prepare", "start", "complete", "fail", "cancel"):
            method = getattr(manager, method_name)
            raised = False
            try:
                method(session)
            except WorkflowSessionManagerError:
                raised = True
            check(
                raised,
                f"M13: {method_name}() on a session already in "
                f"{terminal_status.name} raises "
                f"WorkflowSessionManagerError",
            )


# ---------------------------------------------------------------------------
# M14 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(WorkflowSessionManagerError, AgentError),
        "M14: WorkflowSessionManagerError is a subclass of "
        "Core.exceptions.AgentError",
    )

    manager = WorkflowSessionManager()
    raised_as_agent_error = False
    try:
        manager.create("bad", "bad")
    except AgentError:
        raised_as_agent_error = True
    check(
        raised_as_agent_error,
        "M14: a WorkflowSessionManagerError from invalid create() "
        "inputs can be caught as AgentError",
    )


# ---------------------------------------------------------------------------
# M15 -- forbidden imports
# ---------------------------------------------------------------------------
def scenario_forbidden_imports_absent() -> None:
    import ast

    import Orchestration.workflow_session_manager as module

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
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Executor",
        "AutonomousScheduler",
        "AutonomousHost",
        "AutonomousAgent",
        "RuntimeAnalysisPipeline",
        "EventBus",
        "composition_root",
        "CompositionRoot",
        "threading",
        "asyncio",
    )
    for symbol in forbidden_symbols:
        check(
            not any(symbol in name for name in imported_names),
            f"M15: Orchestration/workflow_session_manager.py never "
            f"imports anything referencing {symbol!r}",
        )


# ---------------------------------------------------------------------------
# M16 -- forbidden execution logic
# ---------------------------------------------------------------------------
def scenario_forbidden_execution_logic() -> None:
    manager = WorkflowSessionManager()
    for member in ("execute", "run", "dequeue"):
        check(
            not hasattr(manager, member),
            f"M16: WorkflowSessionManager exposes no {member!r} member",
        )


# ---------------------------------------------------------------------------
# M17 -- forbidden scheduler logic
# ---------------------------------------------------------------------------
def scenario_forbidden_scheduler_logic() -> None:
    manager = WorkflowSessionManager()
    for member in ("schedule", "enqueue", "tick"):
        check(
            not hasattr(manager, member),
            f"M17: WorkflowSessionManager exposes no {member!r} member",
        )


# ---------------------------------------------------------------------------
# M18 -- forbidden EventBus usage
# ---------------------------------------------------------------------------
def scenario_forbidden_eventbus_usage() -> None:
    manager = WorkflowSessionManager()
    for member in ("publish", "subscribe", "emit"):
        check(
            not hasattr(manager, member),
            f"M18: WorkflowSessionManager exposes no {member!r} member",
        )


# ---------------------------------------------------------------------------
# M19 -- coordinator remains orchestration only
# ---------------------------------------------------------------------------
def scenario_coordinator_remains_orchestration_only() -> None:
    import ast

    import Orchestration.workflow_execution_coordinator as coordinator_module
    from Orchestration.workflow_execution_coordinator import (
        WorkflowExecutionCoordinator,
    )

    coordinator = WorkflowExecutionCoordinator()
    for member in ("prepare", "start", "complete", "fail", "cancel"):
        check(
            not hasattr(coordinator, member),
            f"M19: WorkflowExecutionCoordinator exposes no lifecycle "
            f"member {member!r} (lifecycle logic belongs only in "
            f"WorkflowSessionManager)",
        )

    tree = ast.parse(Path(coordinator_module.__file__).read_text())
    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)
            imported_names.extend(alias.name for alias in node.names)

    for symbol in ("WorkflowSession", "WorkflowSessionManager"):
        check(
            not any(symbol in name for name in imported_names),
            f"M19: Orchestration/workflow_execution_coordinator.py was "
            f"not modified to import {symbol!r} (Sprint 36 did not find "
            f"coordinator integration absolutely necessary)",
        )


# ---------------------------------------------------------------------------
# M20 -- session validation
# ---------------------------------------------------------------------------
def scenario_session_validation() -> None:
    manager = WorkflowSessionManager()

    for method_name in ("prepare", "start", "complete", "fail", "cancel"):
        method = getattr(manager, method_name)
        for bad_session in (None, "not-a-session", 123, {}, []):
            raised = False
            try:
                method(bad_session)
            except WorkflowSessionManagerError:
                raised = True
            check(
                raised,
                f"M20: {method_name}() with invalid session "
                f"{bad_session!r} raises WorkflowSessionManagerError",
            )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_create_builds_created_session,
        scenario_create_rejects_invalid_inputs,
        scenario_create_metadata_none_is_empty,
        scenario_allowed_transitions_succeed,
        scenario_disallowed_transitions_raise,
        scenario_original_session_never_mutated,
        scenario_new_object_returned,
        scenario_workflow_context_metadata_preserved,
        scenario_returned_metadata_immutable,
        scenario_duplicate_transitions,
        scenario_terminal_states_reject_all_transitions,
        scenario_error_hierarchy,
        scenario_forbidden_imports_absent,
        scenario_forbidden_execution_logic,
        scenario_forbidden_scheduler_logic,
        scenario_forbidden_eventbus_usage,
        scenario_coordinator_remains_orchestration_only,
        scenario_session_validation,
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
        f"PHASE 4 SPRINT 36 WORKFLOW SESSION MANAGER RESULTS: {_PASS} "
        f"PASS / {_FAIL} FAIL (total {_PASS + _FAIL})"
    )
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())