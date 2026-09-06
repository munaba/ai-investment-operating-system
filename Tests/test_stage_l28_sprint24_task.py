"""
Phase 3 Sprint 24 proof suite -- the ``Task`` value-object foundation.

Scope: dedicated regression suite for
``Orchestration.task.Task``/``TaskStatus``/``TaskError`` only.
``Task`` is a brand-new module in this Sprint and is wired into
nothing else -- ``AutonomousScheduler``, ``AutonomousHost``,
``AutonomousAgent``, ``RuntimeAnalysisPipeline``, ``GoalPlanner``,
``EventBus``, and the Composition Root are all untouched by this
Sprint and are not exercised by this suite.

``Task`` is a pure, frozen value object: no execution method, no
scheduler/queue integration, no workflow, no callbacks, no retry, no
timeout, no persistence, and no serialization exist anywhere in
``Orchestration/task.py`` -- this suite proves the *absence* of that
surface area as much as it proves the presence of the value-object
behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-2x proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    T1  -- TaskStatus has exactly the five required members, with the
           exact required names.
    T2  -- constructing a Task without an explicit task_id auto-mints
           a uuid4-shaped string.
    T3  -- two Tasks constructed without an explicit task_id never
           collide (independent ids).
    T4  -- a Task constructed without an explicit status defaults to
           TaskStatus.PENDING.
    T5  -- a Task constructed with an explicit status stores exactly
           that status (every member accepted).
    T6  -- Task instances are frozen: reassigning any field raises
           FrozenInstanceError, and the original value is unchanged.
    T7  -- Task.metadata is immutable: item assignment/mutation on the
           returned mapping raises, and mutating the original dict
           passed to the constructor after construction has no effect
           on the already-built Task (eager snapshot), matching
           Orchestration.event_bus.Event.payload's own pattern.
    T8  -- equality: two Tasks are equal iff every field (including
           task_id) matches; two independently-constructed Tasks
           (different auto-minted task_id) are never equal even with
           identical name/description/status/metadata.
    T9  -- repr() is a stable, informative string containing the
           class name and every field's value; two equal Tasks have
           equal reprs.
    T10 -- Task instances are hashable (usable as dict keys / set
           members), and equal Tasks share the same hash.
    T11 -- invalid construction is rejected: empty/non-str name,
           non-str description, non-TaskStatus status, non-Mapping
           metadata, and empty/non-str task_id all raise TaskError.
    T12 -- TaskError is a subclass of Core.exceptions.AgentError.
    T13 -- Task exposes no execution/scheduling/persistence surface
           (no run/start/stop/cancel/tick/schedule/save/load/
           to_dict/from_dict/serialize members).
    T14 -- default metadata (omitted entirely) is an empty mapping.
    T15 -- a Task's metadata can hold arbitrary JSON-shaped values
           without complaint, and is only ever exposed as a
           MappingProxyType (never the original dict object).
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType
from typing import List
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.task import Task, TaskError, TaskStatus

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


# ---------------------------------------------------------------------------
# T1 -- TaskStatus has exactly the five required members
# ---------------------------------------------------------------------------
def scenario_task_status_members() -> None:
    names = {member.name for member in TaskStatus}
    check(
        names == {"PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"},
        "T1: TaskStatus has exactly PENDING/RUNNING/COMPLETED/FAILED/"
        "CANCELLED, nothing more, nothing less",
    )
    check(
        len(TaskStatus) == 5,
        "T1: TaskStatus has exactly 5 members",
    )


# ---------------------------------------------------------------------------
# T2 -- auto-minted task_id is uuid4-shaped
# ---------------------------------------------------------------------------
def scenario_task_id_auto_generated() -> None:
    task = Task(name="n", description="d")

    check(
        isinstance(task.task_id, str),
        "T2: task_id is a str",
    )

    valid_uuid = True
    try:
        UUID(task.task_id, version=4)
    except ValueError:
        valid_uuid = False

    check(valid_uuid, "T2: auto-minted task_id parses as a valid uuid4")


# ---------------------------------------------------------------------------
# T3 -- independent ids across instances
# ---------------------------------------------------------------------------
def scenario_independent_task_ids() -> None:
    tasks = [Task(name="n", description="d") for _ in range(25)]
    ids = {t.task_id for t in tasks}

    check(
        len(ids) == 25,
        "T3: 25 independently-constructed Tasks all get distinct task_ids",
    )


# ---------------------------------------------------------------------------
# T4 -- default status is PENDING
# ---------------------------------------------------------------------------
def scenario_default_status_is_pending() -> None:
    task = Task(name="n", description="d")

    check(
        task.status is TaskStatus.PENDING,
        "T4: a Task constructed without an explicit status defaults to "
        "TaskStatus.PENDING",
    )


# ---------------------------------------------------------------------------
# T5 -- explicit status is honored for every member
# ---------------------------------------------------------------------------
def scenario_custom_status_honored() -> None:
    all_stored_correctly = True
    for member in TaskStatus:
        task = Task(name="n", description="d", status=member)
        if task.status is not member:
            all_stored_correctly = False

    check(
        all_stored_correctly,
        "T5: every TaskStatus member is accepted and stored exactly as given",
    )


# ---------------------------------------------------------------------------
# T6 -- frozen: reassigning any field raises
# ---------------------------------------------------------------------------
def scenario_frozen_fields_reject_reassignment() -> None:
    task = Task(name="n", description="d")

    for field_name, new_value in (
        ("name", "changed"),
        ("description", "changed"),
        ("status", TaskStatus.RUNNING),
        ("metadata", {}),
        ("task_id", "changed"),
    ):
        raised = False
        try:
            setattr(task, field_name, new_value)
        except FrozenInstanceError:
            raised = True

        check(
            raised,
            f"T6: reassigning Task.{field_name} raises FrozenInstanceError",
        )

    check(
        task.name == "n" and task.description == "d"
        and task.status is TaskStatus.PENDING,
        "T6: the original field values are unchanged after rejected "
        "reassignment attempts",
    )


# ---------------------------------------------------------------------------
# T7 -- metadata immutability (snapshot + read-only view)
# ---------------------------------------------------------------------------
def scenario_metadata_is_immutable() -> None:
    original = {"key": "value"}
    task = Task(name="n", description="d", metadata=original)

    check(
        isinstance(task.metadata, MappingProxyType),
        "T7: Task.metadata is exposed as a MappingProxyType",
    )

    raised = False
    try:
        task.metadata["key"] = "mutated"
    except TypeError:
        raised = True

    check(raised, "T7: mutating Task.metadata directly raises TypeError")

    original["key"] = "mutated-original"
    original["new_key"] = "added-after-construction"

    check(
        dict(task.metadata) == {"key": "value"},
        "T7: mutating the original dict after construction never affects "
        "the already-built Task (eager snapshot)",
    )


# ---------------------------------------------------------------------------
# T8 -- equality: every field must match, including task_id
# ---------------------------------------------------------------------------
def scenario_equality_requires_every_field_including_id() -> None:
    task_a = Task(
        name="n", description="d", task_id="shared-id", metadata={"k": "v"}
    )
    task_b = Task(
        name="n", description="d", task_id="shared-id", metadata={"k": "v"}
    )
    task_c = Task(name="n", description="d")  # different auto-minted id
    task_d = Task(name="n", description="d")  # yet another auto-minted id

    check(
        task_a == task_b,
        "T8: two Tasks with identical fields (including task_id) are equal",
    )
    check(
        task_c != task_d,
        "T8: two independently-constructed Tasks (differing task_id) are "
        "never equal, even with identical name/description/status/metadata",
    )
    check(
        Task(name="n", description="d", task_id="shared-id")
        != Task(name="different", description="d", task_id="shared-id"),
        "T8: same task_id but a differing field still compares unequal",
    )


# ---------------------------------------------------------------------------
# T9 -- repr is stable and informative
# ---------------------------------------------------------------------------
def scenario_repr_is_stable_and_informative() -> None:
    task = Task(name="n", description="d", task_id="fixed-id")
    r = repr(task)

    check(
        "Task(" in r and "fixed-id" in r and "n" in r and "d" in r,
        "T9: repr() contains the class name and every field's value",
    )

    task_twin = Task(name="n", description="d", task_id="fixed-id")
    check(
        repr(task) == repr(task_twin),
        "T9: two equal Tasks produce identical reprs",
    )


# ---------------------------------------------------------------------------
# T10 -- hashability
# ---------------------------------------------------------------------------
def scenario_task_is_hashable() -> None:
    task_a = Task(name="n", description="d", task_id="fixed-id")
    task_b = Task(name="n", description="d", task_id="fixed-id")

    hashable = True
    try:
        hash(task_a)
    except TypeError:
        hashable = False

    check(hashable, "T10: hash(task) succeeds (Task is hashable)")

    check(
        hash(task_a) == hash(task_b),
        "T10: two equal Tasks share the same hash",
    )

    seen = {task_a, task_b, Task(name="other", description="d")}
    check(
        len(seen) == 2,
        "T10: Task instances can be used as set members / dict keys",
    )


# ---------------------------------------------------------------------------
# T11 -- invalid construction is rejected
# ---------------------------------------------------------------------------
def scenario_invalid_construction_rejected() -> None:
    invalid_cases = {
        "empty name": dict(name="", description="d"),
        "whitespace-only name": dict(name="   ", description="d"),
        "non-str name": dict(name=123, description="d"),
        "None name": dict(name=None, description="d"),
        "non-str description": dict(name="n", description=123),
        "None description": dict(name="n", description=None),
        "invalid status (wrong type)": dict(
            name="n", description="d", status="PENDING"
        ),
        "invalid status (wrong enum)": dict(
            name="n", description="d", status=object()
        ),
        "non-Mapping metadata (list)": dict(
            name="n", description="d", metadata=["not", "a", "mapping"]
        ),
        "non-Mapping metadata (str)": dict(
            name="n", description="d", metadata="not-a-mapping"
        ),
        "empty task_id": dict(name="n", description="d", task_id=""),
        "non-str task_id": dict(name="n", description="d", task_id=123),
        "None task_id": dict(name="n", description="d", task_id=None),
    }

    all_raised = True
    for label, kwargs in invalid_cases.items():
        try:
            Task(**kwargs)
            all_raised = False
            print(f"    (did not raise for: {label})")
        except TaskError:
            pass

    check(
        all_raised,
        "T11: every invalid-construction case raises TaskError",
    )

    check(
        Task(name="n", description="") is not None,
        "T11: an empty (but present) description is valid",
    )


# ---------------------------------------------------------------------------
# T12 -- TaskError is an AgentError
# ---------------------------------------------------------------------------
def scenario_task_error_is_agent_error_subclass() -> None:
    check(
        issubclass(TaskError, AgentError),
        "T12: TaskError is a subclass of Core.exceptions.AgentError",
    )

    raised_as_agent_error = False
    try:
        Task(name="", description="d")
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "T12: a TaskError from invalid construction can be caught as "
        "AgentError",
    )


# ---------------------------------------------------------------------------
# T13 -- no execution/scheduling/persistence surface
# ---------------------------------------------------------------------------
def scenario_no_execution_or_persistence_surface() -> None:
    task = Task(name="n", description="d")

    forbidden_members = (
        "run",
        "start",
        "stop",
        "cancel",
        "tick",
        "schedule",
        "pause",
        "resume",
        "retry",
        "timeout",
        "save",
        "load",
        "to_dict",
        "from_dict",
        "to_json",
        "from_json",
        "serialize",
        "deserialize",
        "callback",
        "on_complete",
    )

    none_present = all(not hasattr(task, member) for member in forbidden_members)
    check(
        none_present,
        "T13: Task exposes none of the forbidden execution/scheduling/"
        "persistence members",
    )


# ---------------------------------------------------------------------------
# T14 -- default metadata is an empty mapping
# ---------------------------------------------------------------------------
def scenario_default_metadata_is_empty() -> None:
    task = Task(name="n", description="d")

    check(
        dict(task.metadata) == {},
        "T14: metadata defaults to an empty mapping when omitted",
    )
    check(
        isinstance(task.metadata, MappingProxyType),
        "T14: even the default empty metadata is a MappingProxyType",
    )


# ---------------------------------------------------------------------------
# T15 -- metadata holds arbitrary values, always via a proxy, never the
# original dict object
# ---------------------------------------------------------------------------
def scenario_metadata_arbitrary_values_and_never_original_object() -> None:
    original = {
        "int": 1,
        "float": 1.5,
        "str": "value",
        "bool": True,
        "none": None,
        "list": [1, 2, 3],
        "nested": {"a": {"b": 2}},
    }
    task = Task(name="n", description="d", metadata=original)

    check(
        dict(task.metadata) == original,
        "T15: arbitrary JSON-shaped metadata values are stored faithfully",
    )
    check(
        task.metadata is not original,
        "T15: Task.metadata is never the exact same object the caller "
        "passed in",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_task_status_members,
        scenario_task_id_auto_generated,
        scenario_independent_task_ids,
        scenario_default_status_is_pending,
        scenario_custom_status_honored,
        scenario_frozen_fields_reject_reassignment,
        scenario_metadata_is_immutable,
        scenario_equality_requires_every_field_including_id,
        scenario_repr_is_stable_and_informative,
        scenario_task_is_hashable,
        scenario_invalid_construction_rejected,
        scenario_task_error_is_agent_error_subclass,
        scenario_no_execution_or_persistence_surface,
        scenario_default_metadata_is_empty,
        scenario_metadata_arbitrary_values_and_never_original_object,
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
    print(f"PHASE 3 SPRINT 24 TASK RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())