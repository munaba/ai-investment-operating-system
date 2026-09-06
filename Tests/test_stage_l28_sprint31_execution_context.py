"""
Phase 3 Sprint 31 proof suite -- the ``ExecutionContext`` value-object
foundation.

Scope: dedicated regression suite for ``Orchestration.execution_context.
ExecutionContext``/``ExecutionContextError`` only. ``ExecutionContext``
is a brand-new module in this Sprint and is wired into nothing else --
``Executor``, ``WorkflowEngine``, ``WorkflowManager``, ``Workflow``,
``TaskManager``, ``TaskQueue``, ``Task``, ``AutonomousScheduler``,
``AutonomousHost``, ``AutonomousAgent``, ``RuntimeAnalysisPipeline``,
``EventBus``, and the Composition Root are all untouched by this
Sprint and are not exercised by this suite.

``ExecutionContext`` is a pure, frozen value object: no execution
method, no persistence, no serialization, and no eventing exist
anywhere in ``Orchestration/execution_context.py`` -- this suite
proves the *absence* of that surface area as much as it proves the
presence of the value-object behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-31 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    X1  -- constructing an ExecutionContext without an explicit
           execution_id auto-mints a uuid4-shaped string.
    X2  -- two ExecutionContexts constructed without an explicit
           execution_id never collide (independent ids), even when
           every other field is identical.
    X3  -- constructing an ExecutionContext without an explicit
           created_at auto-generates a timezone-aware UTC datetime,
           close to "now" at construction time.
    X4  -- an explicitly supplied execution_id/created_at is stored
           verbatim (not overwritten by the auto-generation defaults).
    X5  -- ExecutionContext instances are frozen: reassigning any
           field raises FrozenInstanceError, and the original value is
           unchanged.
    X6  -- ExecutionContext.metadata is immutable: item assignment on
           the returned mapping raises, and mutating the original
           dict passed to the constructor after construction has no
           effect on the already-built instance (eager snapshot),
           matching Orchestration.event_bus.Event.payload's and
           Orchestration.task.Task.metadata's own pattern.
    X7  -- default metadata (omitted entirely) is an empty mapping,
           and is only ever exposed as a MappingProxyType (never the
           original dict object).
    X8  -- equality: two ExecutionContexts are equal iff every field
           (including execution_id and created_at) matches; two
           independently-constructed contexts (different auto-minted
           execution_id) are never equal even with identical
           workflow_id/task_id/session_id/metadata.
    X9  -- ExecutionContext instances are hashable (usable as dict
           keys / set members), and equal contexts share the same
           hash.
    X10 -- repr() is a stable, informative string containing the
           class name and every field's value; two equal contexts
           have equal reprs.
    X11 -- invalid construction is rejected: empty/non-str
           workflow_id, non-str/non-None task_id, non-str/non-None
           session_id, non-Mapping metadata, empty/non-str
           execution_id, and non-datetime created_at all raise
           ExecutionContextError.
    X12 -- task_id and session_id are optional: omitting either (or
           both) defaults to None and construction succeeds; either
           accepts an explicit non-empty str.
    X13 -- metadata can hold arbitrary JSON-shaped values without
           complaint (nested dict/list/str/int/float/bool/None), and
           the returned mapping's contents match what was passed in.
    X14 -- two ExecutionContexts constructed with the exact same
           explicit execution_id (a "duplicate id" scenario) are
           independent objects that are only ``==`` if every other
           field also matches, and share a hash regardless (hash is
           execution_id-only) -- duplicate ids do not collapse
           instances or raise on their own.
    X15 -- ExecutionContextError is a subclass of Core.exceptions.
           AgentError.
    X16 -- ExecutionContext exposes no execution/scheduling/
           persistence/serialization surface (no run/start/stop/
           cancel/tick/schedule/save/load/to_dict/from_dict/serialize
           members), and defines no methods beyond __post_init__ and
           __hash__ (plus the dataclass-generated dunders).
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
from Orchestration.execution_context import (
    ExecutionContext,
    ExecutionContextError,
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


def _make_context(workflow_id: str = "wf-1", **kwargs) -> ExecutionContext:
    return ExecutionContext(workflow_id=workflow_id, **kwargs)


# ---------------------------------------------------------------------------
# X1 -- execution_id auto-minted, uuid4-shaped
# ---------------------------------------------------------------------------
def scenario_execution_id_auto_generated() -> None:
    context = _make_context()

    check(
        isinstance(context.execution_id, str),
        "X1: execution_id is a str",
    )

    valid_uuid = True
    try:
        UUID(context.execution_id)
    except ValueError:
        valid_uuid = False

    check(valid_uuid, "X1: auto-minted execution_id parses as a valid UUID")


# ---------------------------------------------------------------------------
# X2 -- independent auto-minted execution_ids never collide
# ---------------------------------------------------------------------------
def scenario_execution_ids_are_independent() -> None:
    first = _make_context()
    second = _make_context()

    check(
        first.execution_id != second.execution_id,
        "X2: two ExecutionContexts constructed without an explicit "
        "execution_id never collide",
    )


# ---------------------------------------------------------------------------
# X3 -- created_at auto-generated, UTC-aware, close to now
# ---------------------------------------------------------------------------
def scenario_created_at_auto_generated() -> None:
    before = datetime.now(timezone.utc)
    context = _make_context()
    after = datetime.now(timezone.utc)

    check(
        isinstance(context.created_at, datetime),
        "X3: created_at is a datetime",
    )
    check(
        context.created_at.tzinfo is not None
        and context.created_at.utcoffset() == timedelta(0),
        "X3: created_at is timezone-aware and in UTC",
    )
    check(
        before <= context.created_at <= after,
        "X3: auto-generated created_at falls between two 'now' "
        "timestamps bracketing construction",
    )


# ---------------------------------------------------------------------------
# X4 -- explicit execution_id/created_at are stored verbatim
# ---------------------------------------------------------------------------
def scenario_explicit_execution_id_and_created_at_preserved() -> None:
    explicit_id = "my-explicit-execution-id"
    explicit_time = datetime(2020, 1, 1, tzinfo=timezone.utc)

    context = _make_context(
        execution_id=explicit_id, created_at=explicit_time
    )

    check(
        context.execution_id == explicit_id,
        "X4: an explicitly supplied execution_id is stored verbatim, "
        "not overwritten by auto-generation",
    )
    check(
        context.created_at == explicit_time,
        "X4: an explicitly supplied created_at is stored verbatim, "
        "not overwritten by auto-generation",
    )


# ---------------------------------------------------------------------------
# X5 -- frozen: reassignment raises, original value unchanged
# ---------------------------------------------------------------------------
def scenario_frozen_instance() -> None:
    context = _make_context(task_id="task-1")

    for field_name, new_value in (
        ("workflow_id", "other-wf"),
        ("task_id", "other-task"),
        ("session_id", "other-session"),
        ("metadata", {"x": 1}),
        ("execution_id", "other-id"),
        ("created_at", datetime.now(timezone.utc)),
    ):
        raised = False
        try:
            setattr(context, field_name, new_value)
        except FrozenInstanceError:
            raised = True

        check(
            raised,
            f"X5: reassigning '{field_name}' on a frozen ExecutionContext "
            f"raises FrozenInstanceError",
        )

    check(
        context.workflow_id == "wf-1" and context.task_id == "task-1",
        "X5: the original field values are unchanged after rejected "
        "reassignment attempts",
    )


# ---------------------------------------------------------------------------
# X6 -- metadata immutability: proxy + eager snapshot
# ---------------------------------------------------------------------------
def scenario_metadata_immutable() -> None:
    original = {"a": 1}
    context = _make_context(metadata=original)

    check(
        isinstance(context.metadata, MappingProxyType),
        "X6: metadata is exposed as a MappingProxyType",
    )

    raised = False
    try:
        context.metadata["a"] = 2  # type: ignore[index]
    except TypeError:
        raised = True

    check(
        raised,
        "X6: item assignment on ExecutionContext.metadata raises TypeError",
    )

    original["a"] = 999
    original["b"] = "new"

    check(
        dict(context.metadata) == {"a": 1},
        "X6: mutating the original dict after construction has no "
        "effect on the already-built ExecutionContext (eager snapshot)",
    )


# ---------------------------------------------------------------------------
# X7 -- default metadata is an empty mapping, never the original dict
# ---------------------------------------------------------------------------
def scenario_default_metadata_is_empty_mapping() -> None:
    context = _make_context()

    check(
        dict(context.metadata) == {},
        "X7: omitted metadata defaults to an empty mapping",
    )
    check(
        isinstance(context.metadata, MappingProxyType),
        "X7: default metadata is exposed as a MappingProxyType, not a "
        "plain dict",
    )

    other_context = _make_context()
    check(
        context.metadata is not other_context.metadata,
        "X7: two independently-constructed default-metadata contexts "
        "do not share the same underlying mapping object",
    )


# ---------------------------------------------------------------------------
# X8 -- equality: every field must match
# ---------------------------------------------------------------------------
def scenario_equality_requires_every_field() -> None:
    shared_time = datetime(2021, 6, 1, tzinfo=timezone.utc)

    a = ExecutionContext(
        workflow_id="wf",
        task_id="t",
        session_id="s",
        metadata={"k": "v"},
        execution_id="same-id",
        created_at=shared_time,
    )
    b = ExecutionContext(
        workflow_id="wf",
        task_id="t",
        session_id="s",
        metadata={"k": "v"},
        execution_id="same-id",
        created_at=shared_time,
    )

    check(a == b, "X8: two contexts with identical fields are equal")

    c = ExecutionContext(
        workflow_id="wf",
        task_id="t",
        session_id="s",
        metadata={"k": "v"},
        execution_id="different-id",
        created_at=shared_time,
    )
    check(
        a != c,
        "X8: contexts differing only by execution_id are not equal",
    )

    independent_first = _make_context(workflow_id="wf")
    independent_second = _make_context(workflow_id="wf")
    check(
        independent_first != independent_second,
        "X8: two independently-constructed contexts (different "
        "auto-minted execution_id/created_at) are never equal, even "
        "with identical workflow_id",
    )


# ---------------------------------------------------------------------------
# X9 -- hashable, equal contexts share a hash
# ---------------------------------------------------------------------------
def scenario_hashing() -> None:
    shared_time = datetime(2021, 6, 1, tzinfo=timezone.utc)
    a = ExecutionContext(
        workflow_id="wf", execution_id="same-id", created_at=shared_time
    )
    b = ExecutionContext(
        workflow_id="wf", execution_id="same-id", created_at=shared_time
    )

    check(a == b, "X9: precondition -- a and b are equal")
    check(hash(a) == hash(b), "X9: equal ExecutionContexts share the same hash")

    holder = {a, b}
    check(
        len(holder) == 1,
        "X9: equal ExecutionContexts collapse to one entry in a set",
    )

    mapping = {a: "value"}
    check(
        mapping.get(b) == "value",
        "X9: an ExecutionContext can be used as a dict key, and an "
        "equal instance retrieves the same value",
    )


# ---------------------------------------------------------------------------
# X10 -- repr() is stable and informative
# ---------------------------------------------------------------------------
def scenario_repr_is_stable_and_informative() -> None:
    context = _make_context(
        workflow_id="wf-repr", task_id="t-repr", session_id="s-repr"
    )
    text = repr(context)

    check(
        "ExecutionContext" in text,
        "X10: repr() contains the class name",
    )
    for expected in ("wf-repr", "t-repr", "s-repr", context.execution_id):
        check(
            expected in text,
            f"X10: repr() contains {expected!r}",
        )

    shared_time = datetime(2022, 3, 3, tzinfo=timezone.utc)
    a = ExecutionContext(
        workflow_id="wf", execution_id="same-id", created_at=shared_time
    )
    b = ExecutionContext(
        workflow_id="wf", execution_id="same-id", created_at=shared_time
    )
    check(
        repr(a) == repr(b),
        "X10: two equal ExecutionContexts have equal reprs",
    )


# ---------------------------------------------------------------------------
# X11 -- invalid construction is rejected
# ---------------------------------------------------------------------------
def scenario_invalid_construction_rejected() -> None:
    for bad_workflow_id in ("", "   ", None, 123, [], {}):
        raised = False
        try:
            ExecutionContext(workflow_id=bad_workflow_id)  # type: ignore[arg-type]
        except ExecutionContextError:
            raised = True
        check(
            raised,
            f"X11: workflow_id={bad_workflow_id!r} raises "
            f"ExecutionContextError",
        )

    # "" is a str so it is technically permitted here (non-empty is
    # not required for the optional ids) -- only non-str, non-None
    # values are rejected for task_id/session_id below.
    for bad_task_id in (123, [], {}, object()):
        raised = False
        try:
            ExecutionContext(workflow_id="wf", task_id=bad_task_id)  # type: ignore[arg-type]
        except ExecutionContextError:
            raised = True
        check(
            raised,
            f"X11: task_id={bad_task_id!r} (non-str, non-None) raises "
            f"ExecutionContextError",
        )

    for bad_session_id in (123, [], {}, object()):
        raised = False
        try:
            ExecutionContext(workflow_id="wf", session_id=bad_session_id)  # type: ignore[arg-type]
        except ExecutionContextError:
            raised = True
        check(
            raised,
            f"X11: session_id={bad_session_id!r} (non-str, non-None) "
            f"raises ExecutionContextError",
        )

    for bad_metadata in ("not-a-mapping", 123, [1, 2], None):
        raised = False
        try:
            ExecutionContext(workflow_id="wf", metadata=bad_metadata)  # type: ignore[arg-type]
        except ExecutionContextError:
            raised = True
        check(
            raised,
            f"X11: metadata={bad_metadata!r} (non-Mapping) raises "
            f"ExecutionContextError",
        )

    for bad_execution_id in ("", "   ", 123, [], {}, None):
        raised = False
        try:
            ExecutionContext(workflow_id="wf", execution_id=bad_execution_id)  # type: ignore[arg-type]
        except ExecutionContextError:
            raised = True
        check(
            raised,
            f"X11: execution_id={bad_execution_id!r} raises "
            f"ExecutionContextError",
        )

    for bad_created_at in ("2020-01-01", 123, [], {}, None):
        raised = False
        try:
            ExecutionContext(workflow_id="wf", created_at=bad_created_at)  # type: ignore[arg-type]
        except ExecutionContextError:
            raised = True
        check(
            raised,
            f"X11: created_at={bad_created_at!r} (non-datetime) raises "
            f"ExecutionContextError",
        )


# ---------------------------------------------------------------------------
# X12 -- task_id/session_id are optional
# ---------------------------------------------------------------------------
def scenario_optional_fields() -> None:
    bare = _make_context()
    check(
        bare.task_id is None and bare.session_id is None,
        "X12: omitting task_id and session_id defaults both to None",
    )

    with_task_only = _make_context(task_id="t-only")
    check(
        with_task_only.task_id == "t-only"
        and with_task_only.session_id is None,
        "X12: task_id can be supplied while session_id stays None",
    )

    with_session_only = _make_context(session_id="s-only")
    check(
        with_session_only.session_id == "s-only"
        and with_session_only.task_id is None,
        "X12: session_id can be supplied while task_id stays None",
    )

    with_both = _make_context(task_id="t", session_id="s")
    check(
        with_both.task_id == "t" and with_both.session_id == "s",
        "X12: both task_id and session_id can be supplied together",
    )


# ---------------------------------------------------------------------------
# X13 -- metadata accepts arbitrary JSON-shaped values
# ---------------------------------------------------------------------------
def scenario_metadata_arbitrary_json_shaped_values() -> None:
    payload = {
        "string": "value",
        "int": 42,
        "float": 3.14,
        "bool": True,
        "none": None,
        "list": [1, "two", 3.0, {"nested": True}],
        "nested": {"a": {"b": [1, 2, 3]}},
    }
    context = _make_context(metadata=payload)

    check(
        dict(context.metadata) == payload,
        "X13: metadata holding arbitrary JSON-shaped values round-trips "
        "exactly as passed in",
    )
    check(
        isinstance(context.metadata, MappingProxyType),
        "X13: metadata is exposed only as a MappingProxyType, never the "
        "original dict object",
    )


# ---------------------------------------------------------------------------
# X14 -- duplicate explicit execution_id: independent objects
# ---------------------------------------------------------------------------
def scenario_duplicate_execution_ids() -> None:
    shared_id = "duplicate-id"

    first = ExecutionContext(workflow_id="wf-a", execution_id=shared_id)
    second = ExecutionContext(workflow_id="wf-b", execution_id=shared_id)

    check(
        first.execution_id == second.execution_id == shared_id,
        "X14: both contexts carry the same, duplicated execution_id "
        "without either construction raising",
    )
    check(
        first is not second,
        "X14: contexts sharing an execution_id remain distinct objects",
    )
    check(
        first != second,
        "X14: contexts sharing only execution_id (but differing "
        "workflow_id) are not equal",
    )
    check(
        hash(first) == hash(second),
        "X14: contexts sharing an execution_id share the same hash, "
        "regardless of other field differences (hash is "
        "execution_id-only)",
    )


# ---------------------------------------------------------------------------
# X15 -- ExecutionContextError is an AgentError subclass
# ---------------------------------------------------------------------------
def scenario_execution_context_error_is_agent_error_subclass() -> None:
    check(
        issubclass(ExecutionContextError, AgentError),
        "X15: ExecutionContextError is a subclass of Core.exceptions."
        "AgentError",
    )

    raised_as_agent_error = False
    try:
        ExecutionContext(workflow_id="")
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "X15: an ExecutionContextError from invalid construction can be "
        "caught as AgentError",
    )


# ---------------------------------------------------------------------------
# X16 -- no forbidden execution/persistence/serialization surface
# ---------------------------------------------------------------------------
def scenario_no_forbidden_surface() -> None:
    context = _make_context()

    forbidden_members = (
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
            not hasattr(context, member),
            f"X16: ExecutionContext exposes no {member!r} member",
        )

    import ast

    import Orchestration.execution_context as module

    tree = ast.parse(Path(module.__file__).read_text())
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionContext"
    )
    defined_methods = {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    check(
        defined_methods == {"__post_init__", "__hash__"},
        f"X16: ExecutionContext defines no methods beyond __post_init__ "
        f"and __hash__; found {sorted(defined_methods)!r}",
    )

    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)
            imported_names.extend(alias.name for alias in node.names)

    forbidden_symbols = (
        "Executor",
        "WorkflowEngine",
        "WorkflowManager",
        "Workflow",
        "TaskManager",
        "TaskQueue",
        "Task",
        "AutonomousScheduler",
        "AutonomousHost",
        "AutonomousAgent",
        "RuntimeAnalysisPipeline",
        "EventBus",
        "composition_root",
        "CompositionRoot",
    )
    for symbol in forbidden_symbols:
        check(
            not any(symbol in name for name in imported_names),
            f"X16: Orchestration/execution_context.py never imports "
            f"anything referencing {symbol!r}",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_execution_id_auto_generated,
        scenario_execution_ids_are_independent,
        scenario_created_at_auto_generated,
        scenario_explicit_execution_id_and_created_at_preserved,
        scenario_frozen_instance,
        scenario_metadata_immutable,
        scenario_default_metadata_is_empty_mapping,
        scenario_equality_requires_every_field,
        scenario_hashing,
        scenario_repr_is_stable_and_informative,
        scenario_invalid_construction_rejected,
        scenario_optional_fields,
        scenario_metadata_arbitrary_json_shaped_values,
        scenario_duplicate_execution_ids,
        scenario_execution_context_error_is_agent_error_subclass,
        scenario_no_forbidden_surface,
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
    print(f"PHASE 3 SPRINT 31 EXECUTION CONTEXT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())