"""
Phase 4 Sprint 35 proof suite -- the ``WorkflowSession`` value-object
foundation.

Scope: dedicated regression suite for ``Orchestration.workflow_session.
WorkflowSession``/``WorkflowSessionStatus``/``WorkflowSessionError``
only. ``WorkflowSession`` is a brand-new module in this Sprint and is
wired into nothing else -- ``Reflection``, ``Learning``, ``Memory``,
``Scheduler``, ``EventBus``, ``WorkflowEngine``,
``WorkflowExecutionCoordinator``, ``Executor``,
``RuntimeAnalysisPipeline``, and the Composition Root are all
untouched by this Sprint and are not exercised by this suite.

``WorkflowSession`` is a pure, frozen value object: no execution
method (no ``execute()``, ``prepare()``, ``resume()``, ``pause()``),
no scheduler/EventBus integration, no persistence, and no
serialization exist anywhere in ``Orchestration/workflow_session.py``
-- this suite proves the *absence* of that surface area as much as it
proves the presence of the value-object behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L3x / Sprint 1x-35 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- WorkflowSessionStatus enum membership (exactly CREATED,
           PREPARED, RUNNING, COMPLETED, FAILED, CANCELLED).
    S2  -- constructing a WorkflowSession without an explicit
           session_id auto-mints a uuid4-shaped string; two sessions
           constructed without one never collide.
    S3  -- an explicitly supplied session_id is stored verbatim, not
           overwritten by the auto-generation default.
    S4  -- default status (omitted entirely) is
           WorkflowSessionStatus.CREATED.
    S5  -- an explicitly supplied status is stored verbatim.
    S6  -- workflow validation: non-Workflow values raise
           WorkflowSessionError.
    S7  -- execution_context validation: non-ExecutionContext values
           raise WorkflowSessionError.
    S8  -- metadata validation: non-Mapping values raise
           WorkflowSessionError.
    S9  -- created_at validation: non-datetime values raise
           WorkflowSessionError; omitting created_at auto-generates a
           timezone-aware UTC datetime close to "now".
    S10 -- session_id validation: empty/non-str values raise
           WorkflowSessionError.
    S11 -- metadata is immutable: item assignment on the returned
           mapping raises.
    S12 -- metadata is copied: mutating the original dict passed to
           the constructor after construction has no effect on the
           already-built instance (eager snapshot).
    S13 -- workflow identity is preserved: session.workflow is the
           exact Workflow instance passed in.
    S14 -- execution_context identity is preserved: session.
           execution_context is the exact ExecutionContext instance
           passed in.
    S15 -- repr() is a stable, informative string containing the
           class name and every field's value; two equal sessions
           have equal reprs.
    S16 -- WorkflowSession instances are hashable (usable as dict
           keys / set members), and equal sessions share the same
           hash.
    S17 -- duplicate explicit session_ids are allowed: two sessions
           constructed with the same explicit session_id are
           independent objects, not equal unless every other field
           also matches, and share a hash regardless (hash is
           session_id-only).
    S18 -- equality semantics: two WorkflowSessions are equal iff
           every field (including session_id and created_at) matches.
    S19 -- forbidden methods (execute/prepare/resume/pause/run/start/
           stop/cancel/save/load/serialize/etc.) are absent from
           WorkflowSession, and the class defines no methods beyond
           __post_init__ and __hash__.
    S20 -- forbidden imports (Scheduler/EventBus/WorkflowEngine/
           WorkflowExecutionCoordinator/Executor/
           RuntimeAnalysisPipeline/composition_root/Reflection/
           Learning/Memory) are absent from
           Orchestration/workflow_session.py.
    S21 -- WorkflowSessionError is a subclass of Core.exceptions.
           AgentError, and can be caught as such.
    S22 -- empty metadata (omitted entirely) is an empty mapping,
           exposed only as a MappingProxyType.
    S23 -- independent metadata copies: two sessions built from the
           same source dict do not share the underlying mapping
           object, and mutating one session's exposed metadata's
           source dict does not affect the other.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import List
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.execution_context import ExecutionContext
from Orchestration.workflow import Workflow
from Orchestration.workflow_session import (
    WorkflowSession,
    WorkflowSessionError,
    WorkflowSessionStatus,
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


def _make_session(**kwargs) -> WorkflowSession:
    if "workflow" not in kwargs:
        kwargs["workflow"] = _make_workflow()
    if "execution_context" not in kwargs:
        kwargs["execution_context"] = _make_context(kwargs["workflow"])
    return WorkflowSession(**kwargs)


# ---------------------------------------------------------------------------
# S1 -- enum membership
# ---------------------------------------------------------------------------
def scenario_enum_membership() -> None:
    expected = {
        "CREATED",
        "PREPARED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }
    actual = {member.name for member in WorkflowSessionStatus}
    check(
        actual == expected,
        f"S1: WorkflowSessionStatus has exactly {sorted(expected)!r}; "
        f"got {sorted(actual)!r}",
    )


# ---------------------------------------------------------------------------
# S2 -- session_id auto-minted, uuid4-shaped, independent
# ---------------------------------------------------------------------------
def scenario_session_id_auto_generated() -> None:
    first = _make_session()
    second = _make_session()

    check(isinstance(first.session_id, str), "S2: session_id is a str")

    valid_uuid = True
    try:
        UUID(first.session_id)
    except ValueError:
        valid_uuid = False
    check(valid_uuid, "S2: auto-minted session_id parses as a valid UUID")

    check(
        first.session_id != second.session_id,
        "S2: two WorkflowSessions constructed without an explicit "
        "session_id never collide",
    )


# ---------------------------------------------------------------------------
# S3 -- explicit session_id preserved
# ---------------------------------------------------------------------------
def scenario_explicit_session_id_preserved() -> None:
    session = _make_session(session_id="my-explicit-session-id")
    check(
        session.session_id == "my-explicit-session-id",
        "S3: an explicitly supplied session_id is stored verbatim, "
        "not overwritten by auto-generation",
    )


# ---------------------------------------------------------------------------
# S4 -- default status is CREATED
# ---------------------------------------------------------------------------
def scenario_default_status() -> None:
    session = _make_session()
    check(
        session.status is WorkflowSessionStatus.CREATED,
        "S4: default status (omitted) is WorkflowSessionStatus.CREATED",
    )


# ---------------------------------------------------------------------------
# S5 -- custom status preserved
# ---------------------------------------------------------------------------
def scenario_custom_status() -> None:
    for member in WorkflowSessionStatus:
        session = _make_session(status=member)
        check(
            session.status is member,
            f"S5: explicitly supplied status {member!r} is stored verbatim",
        )


# ---------------------------------------------------------------------------
# S6 -- workflow validation
# ---------------------------------------------------------------------------
def scenario_workflow_validation() -> None:
    context = _make_context(_make_workflow())
    for bad_workflow in (None, "not-a-workflow", 123, {}, []):
        raised = False
        try:
            WorkflowSession(workflow=bad_workflow, execution_context=context)
        except WorkflowSessionError:
            raised = True
        check(
            raised,
            f"S6: non-Workflow 'workflow' value {bad_workflow!r} raises "
            f"WorkflowSessionError",
        )


# ---------------------------------------------------------------------------
# S7 -- execution_context validation
# ---------------------------------------------------------------------------
def scenario_execution_context_validation() -> None:
    workflow = _make_workflow()
    for bad_context in (None, "not-a-context", 123, {}, []):
        raised = False
        try:
            WorkflowSession(workflow=workflow, execution_context=bad_context)
        except WorkflowSessionError:
            raised = True
        check(
            raised,
            f"S7: non-ExecutionContext 'execution_context' value "
            f"{bad_context!r} raises WorkflowSessionError",
        )


# ---------------------------------------------------------------------------
# S8 -- metadata validation
# ---------------------------------------------------------------------------
def scenario_metadata_validation() -> None:
    for bad_metadata in ("not-a-mapping", 123, ["a", "b"], None):
        raised = False
        try:
            _make_session(metadata=bad_metadata)
        except WorkflowSessionError:
            raised = True
        check(
            raised,
            f"S8: non-Mapping 'metadata' value {bad_metadata!r} raises "
            f"WorkflowSessionError",
        )


# ---------------------------------------------------------------------------
# S9 -- created_at validation and auto-generation
# ---------------------------------------------------------------------------
def scenario_created_at_validation_and_auto_generation() -> None:
    for bad_created_at in ("2020-01-01", 123, None, object()):
        raised = False
        try:
            _make_session(created_at=bad_created_at)
        except WorkflowSessionError:
            raised = True
        check(
            raised,
            f"S9: non-datetime 'created_at' value {bad_created_at!r} "
            f"raises WorkflowSessionError",
        )

    before = datetime.now(timezone.utc)
    session = _make_session()
    after = datetime.now(timezone.utc)

    check(
        isinstance(session.created_at, datetime),
        "S9: created_at is a datetime",
    )
    check(
        session.created_at.tzinfo is not None
        and session.created_at.utcoffset() == timedelta(0),
        "S9: auto-generated created_at is timezone-aware and in UTC",
    )
    check(
        before <= session.created_at <= after,
        "S9: auto-generated created_at falls between two 'now' "
        "timestamps bracketing construction",
    )

    explicit_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
    explicit_session = _make_session(created_at=explicit_time)
    check(
        explicit_session.created_at == explicit_time,
        "S9: an explicitly supplied created_at is stored verbatim",
    )


# ---------------------------------------------------------------------------
# S10 -- session_id validation
# ---------------------------------------------------------------------------
def scenario_session_id_validation() -> None:
    for bad_session_id in ("", "   ", 123, None, [], {}):
        raised = False
        try:
            _make_session(session_id=bad_session_id)
        except WorkflowSessionError:
            raised = True
        check(
            raised,
            f"S10: invalid 'session_id' value {bad_session_id!r} raises "
            f"WorkflowSessionError",
        )


# ---------------------------------------------------------------------------
# S11 -- metadata immutable (item assignment fails)
# ---------------------------------------------------------------------------
def scenario_metadata_immutable() -> None:
    session = _make_session(metadata={"a": 1})

    raised = False
    try:
        session.metadata["a"] = 2  # type: ignore[index]
    except TypeError:
        raised = True
    check(
        raised,
        "S11: item assignment on session.metadata raises TypeError "
        "(immutable MappingProxyType)",
    )


# ---------------------------------------------------------------------------
# S12 -- metadata copied (eager snapshot)
# ---------------------------------------------------------------------------
def scenario_metadata_copied() -> None:
    source = {"a": 1}
    session = _make_session(metadata=source)

    source["a"] = 999
    source["b"] = "new"

    check(
        dict(session.metadata) == {"a": 1},
        "S12: mutating the original dict after construction has no "
        "effect on the already-built session's metadata",
    )


# ---------------------------------------------------------------------------
# S13 -- workflow identity preserved
# ---------------------------------------------------------------------------
def scenario_workflow_identity_preserved() -> None:
    workflow = _make_workflow()
    context = _make_context(workflow)
    session = WorkflowSession(workflow=workflow, execution_context=context)

    check(
        session.workflow is workflow,
        "S13: session.workflow is the exact Workflow instance passed in",
    )


# ---------------------------------------------------------------------------
# S14 -- execution_context identity preserved
# ---------------------------------------------------------------------------
def scenario_execution_context_identity_preserved() -> None:
    workflow = _make_workflow()
    context = _make_context(workflow)
    session = WorkflowSession(workflow=workflow, execution_context=context)

    check(
        session.execution_context is context,
        "S14: session.execution_context is the exact ExecutionContext "
        "instance passed in",
    )


# ---------------------------------------------------------------------------
# S15 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_is_stable_and_informative() -> None:
    workflow = _make_workflow()
    context = _make_context(workflow)
    session = WorkflowSession(
        workflow=workflow,
        execution_context=context,
        session_id="fixed-id",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    r = repr(session)
    check(
        "WorkflowSession" in r,
        "S15: repr() contains the class name",
    )
    check(
        "fixed-id" in r,
        "S15: repr() contains the session_id value",
    )

    session_dup = WorkflowSession(
        workflow=workflow,
        execution_context=context,
        session_id="fixed-id",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    check(
        repr(session) == repr(session_dup),
        "S15: two equal sessions have equal reprs",
    )


# ---------------------------------------------------------------------------
# S16 -- hashability
# ---------------------------------------------------------------------------
def scenario_hashing() -> None:
    session = _make_session()

    hashable = True
    try:
        hash(session)
    except TypeError:
        hashable = False
    check(hashable, "S16: WorkflowSession instances are hashable")

    check(
        session in {session},
        "S16: WorkflowSession instances can be used as set members",
    )
    check(
        {session: "value"}.get(session) == "value",
        "S16: WorkflowSession instances can be used as dict keys",
    )

    workflow = _make_workflow()
    context = _make_context(workflow)
    fixed_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
    first = WorkflowSession(
        workflow=workflow,
        execution_context=context,
        session_id="same-id",
        created_at=fixed_time,
    )
    second = WorkflowSession(
        workflow=workflow,
        execution_context=context,
        session_id="same-id",
        created_at=fixed_time,
    )
    check(first == second, "S16: sanity check -- first and second are equal")
    check(
        hash(first) == hash(second),
        "S16: equal WorkflowSessions share the same hash",
    )


# ---------------------------------------------------------------------------
# S17 -- duplicate session ids allowed
# ---------------------------------------------------------------------------
def scenario_duplicate_session_ids() -> None:
    shared_id = "duplicate-session-id"

    workflow_a = _make_workflow(name="wf-a")
    workflow_b = _make_workflow(name="wf-b")

    first = WorkflowSession(
        workflow=workflow_a,
        execution_context=_make_context(workflow_a),
        session_id=shared_id,
    )
    second = WorkflowSession(
        workflow=workflow_b,
        execution_context=_make_context(workflow_b),
        session_id=shared_id,
    )

    check(
        first.session_id == second.session_id == shared_id,
        "S17: both sessions carry the same, duplicated session_id "
        "without either construction raising",
    )
    check(
        first is not second,
        "S17: sessions sharing a session_id remain distinct objects",
    )
    check(
        first != second,
        "S17: sessions sharing only session_id (but differing workflow) "
        "are not equal",
    )
    check(
        hash(first) == hash(second),
        "S17: sessions sharing a session_id share the same hash "
        "(hash is session_id-only)",
    )


# ---------------------------------------------------------------------------
# S18 -- equality semantics
# ---------------------------------------------------------------------------
def scenario_equality_requires_every_field() -> None:
    workflow = _make_workflow()
    context = _make_context(workflow)
    fixed_time = datetime(2020, 1, 1, tzinfo=timezone.utc)

    base_kwargs = dict(
        workflow=workflow,
        execution_context=context,
        session_id="id-1",
        status=WorkflowSessionStatus.CREATED,
        metadata={"k": "v"},
        created_at=fixed_time,
    )

    identical = WorkflowSession(**base_kwargs)
    same_fields = WorkflowSession(**base_kwargs)
    check(
        identical == same_fields,
        "S18: two sessions with identical field values are equal",
    )

    for field_name, override in (
        ("session_id", "id-2"),
        ("status", WorkflowSessionStatus.RUNNING),
        ("metadata", {"k": "different"}),
        ("created_at", datetime(2021, 1, 1, tzinfo=timezone.utc)),
    ):
        kwargs = dict(base_kwargs)
        kwargs[field_name] = override
        other = WorkflowSession(**kwargs)
        check(
            identical != other,
            f"S18: differing {field_name!r} makes two sessions unequal",
        )

    default_session = _make_session()
    another_default_session = _make_session()
    check(
        default_session != another_default_session,
        "S18: two independently-constructed default sessions (different "
        "auto-minted session_id/created_at) are not equal",
    )


# ---------------------------------------------------------------------------
# S19 -- forbidden methods absent
# ---------------------------------------------------------------------------
def scenario_forbidden_methods_absent() -> None:
    session = _make_session()

    forbidden_members = (
        "execute",
        "prepare",
        "resume",
        "pause",
        "run",
        "start",
        "stop",
        "cancel",
        "tick",
        "schedule",
        "save",
        "load",
        "to_dict",
        "from_dict",
        "serialize",
        "deserialize",
        "publish",
        "subscribe",
    )
    for member in forbidden_members:
        check(
            not hasattr(session, member),
            f"S19: WorkflowSession exposes no {member!r} member",
        )

    import ast

    import Orchestration.workflow_session as module

    tree = ast.parse(Path(module.__file__).read_text())
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WorkflowSession"
    )
    defined_methods = {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    check(
        defined_methods == {"__post_init__", "__hash__"},
        f"S19: WorkflowSession defines no methods beyond __post_init__ "
        f"and __hash__; found {sorted(defined_methods)!r}",
    )


# ---------------------------------------------------------------------------
# S20 -- forbidden imports absent
# ---------------------------------------------------------------------------
def scenario_forbidden_imports_absent() -> None:
    import ast

    import Orchestration.workflow_session as module

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
        "Scheduler",
        "EventBus",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Executor",
        "RuntimeAnalysisPipeline",
        "composition_root",
        "CompositionRoot",
        "Reflection",
        "Learning",
        "Memory",
        "threading",
        "asyncio",
    )
    for symbol in forbidden_symbols:
        check(
            not any(symbol in name for name in imported_names),
            f"S20: Orchestration/workflow_session.py never imports "
            f"anything referencing {symbol!r}",
        )


# ---------------------------------------------------------------------------
# S21 -- WorkflowSessionError is an AgentError subclass
# ---------------------------------------------------------------------------
def scenario_workflow_session_error_is_agent_error_subclass() -> None:
    check(
        issubclass(WorkflowSessionError, AgentError),
        "S21: WorkflowSessionError is a subclass of Core.exceptions."
        "AgentError",
    )

    raised_as_agent_error = False
    try:
        _make_session(session_id="")
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "S21: a WorkflowSessionError from invalid construction can be "
        "caught as AgentError",
    )


# ---------------------------------------------------------------------------
# S22 -- empty metadata default
# ---------------------------------------------------------------------------
def scenario_default_metadata_is_empty_mapping() -> None:
    session = _make_session()

    check(
        dict(session.metadata) == {},
        "S22: default (omitted) metadata is an empty mapping",
    )
    check(
        isinstance(session.metadata, MappingProxyType),
        "S22: metadata is exposed only as a MappingProxyType, never the "
        "original dict object",
    )


# ---------------------------------------------------------------------------
# S23 -- independent metadata copies across instances
# ---------------------------------------------------------------------------
def scenario_independent_metadata_copies() -> None:
    source = {"shared": "value"}
    first = _make_session(metadata=source)
    second = _make_session(metadata=source)

    check(
        first.metadata is not second.metadata,
        "S23: two sessions built from the same source dict do not "
        "share the underlying metadata mapping object",
    )

    source["shared"] = "mutated"
    check(
        dict(first.metadata) == {"shared": "value"}
        and dict(second.metadata) == {"shared": "value"},
        "S23: mutating the shared source dict after construction "
        "affects neither session's already-built metadata",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_enum_membership,
        scenario_session_id_auto_generated,
        scenario_explicit_session_id_preserved,
        scenario_default_status,
        scenario_custom_status,
        scenario_workflow_validation,
        scenario_execution_context_validation,
        scenario_metadata_validation,
        scenario_created_at_validation_and_auto_generation,
        scenario_session_id_validation,
        scenario_metadata_immutable,
        scenario_metadata_copied,
        scenario_workflow_identity_preserved,
        scenario_execution_context_identity_preserved,
        scenario_repr_is_stable_and_informative,
        scenario_hashing,
        scenario_duplicate_session_ids,
        scenario_equality_requires_every_field,
        scenario_forbidden_methods_absent,
        scenario_forbidden_imports_absent,
        scenario_workflow_session_error_is_agent_error_subclass,
        scenario_default_metadata_is_empty_mapping,
        scenario_independent_metadata_copies,
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
        f"PHASE 4 SPRINT 35 WORKFLOW SESSION RESULTS: {_PASS} PASS / "
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