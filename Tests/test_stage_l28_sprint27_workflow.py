"""
Phase 3 Sprint 27 proof suite -- the ``Workflow`` immutable value
object.

Scope: dedicated regression suite for
``Orchestration.workflow.Workflow``/``WorkflowStatus``/
``WorkflowError`` only. ``Orchestration.task.Task`` is unmodified and
already covered by its own dedicated suite
(``Tests/test_stage_l28_sprint24_task.py``) -- real ``Task``
instances are used throughout here, but ``Task``'s own value-object
behavior is not re-verified beyond what ``Workflow`` itself needs.
``TaskQueue``, ``TaskManager``, ``AutonomousScheduler``,
``AutonomousHost``, ``AutonomousAgent``, ``RuntimeAnalysisPipeline``,
``EventBus``, and the Composition Root are all untouched by this
Sprint and are not exercised by this suite.

``Workflow`` is a pure, frozen value object: no threading, no
asyncio, no timers, no execution, no scheduler/manager/queue
integration, no EventBus, no persistence, no serialization, and no
dependency-graph/traversal logic exist anywhere in
``Orchestration/workflow.py`` -- this suite proves the *absence* of
that surface area as much as it proves the presence of the value-
object behavior itself.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-2x proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    W1  -- WorkflowStatus declares exactly the five expected members
           (CREATED, READY, RUNNING, COMPLETED, FAILED).
    W2  -- workflow_id is auto-generated (a non-empty str uuid4) when
           not supplied, and two Workflows constructed without an
           explicit workflow_id never collide.
    W3  -- an explicitly supplied workflow_id is honored as-is.
    W4  -- status defaults to WorkflowStatus.CREATED when not
           supplied.
    W5  -- an explicitly supplied status is honored.
    W6  -- Workflow instances are frozen: reassigning any field after
           construction raises (dataclasses.FrozenInstanceError, a
           TypeError/AttributeError-family exception).
    W7  -- metadata is immutable: the stored metadata is an immutable
           mapping (TypeError on item assignment), and mutating the
           original dict passed in after construction has no effect
           on workflow.metadata.
    W8  -- tasks is stored as an immutable tuple: attempting to
           mutate it raises, and mutating a list passed in after
           construction has no effect on workflow.tasks.
    W9  -- duplicate tasks (the exact same Task object appearing more
           than once, and two distinct Task instances with identical
           field values) are both accepted without error.
    W10 -- insertion order is preserved exactly as supplied in
           workflow.tasks.
    W11 -- equality requires every field to match, workflow_id
           included; two Workflows built with identical arguments but
           auto-generated (thus differing) workflow_ids are unequal.
    W12 -- repr() is a stable, informative string.
    W13 -- Workflow instances are hashable, and equal Workflows share
           a hash.
    W14 -- invalid construction is rejected: empty/non-str name,
           non-str description, non-Task items in tasks, non-iterable
           tasks, non-WorkflowStatus status, and non-Mapping metadata
           all raise WorkflowError.
    W15 -- WorkflowError is a subclass of Core.exceptions.AgentError.
    W16 -- Workflow exposes no execution/scheduling/persistence/
           eventing/graph-traversal surface (no run/start/schedule/
           tick/save/load/to_dict/publish/subscribe/add_dependency/
           next_task members).
    W17 -- default tasks is an empty tuple and default metadata is an
           empty mapping when neither is supplied.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.task import Task
from Orchestration.workflow import Workflow, WorkflowError, WorkflowStatus

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


def _make_workflow(
    name: str = "wf", description: str = "d", **kwargs
) -> Workflow:
    return Workflow(name=name, description=description, **kwargs)


# ---------------------------------------------------------------------------
# W1 -- WorkflowStatus declares exactly the five expected members
# ---------------------------------------------------------------------------
def scenario_workflow_status_members() -> None:
    expected = {"CREATED", "READY", "RUNNING", "COMPLETED", "FAILED"}
    actual = {member.name for member in WorkflowStatus}

    check(
        actual == expected,
        f"W1: WorkflowStatus declares exactly {sorted(expected)}",
    )


# ---------------------------------------------------------------------------
# W2 -- workflow_id auto-generated
# ---------------------------------------------------------------------------
def scenario_workflow_id_auto_generated() -> None:
    workflow = _make_workflow()

    check(
        isinstance(workflow.workflow_id, str) and workflow.workflow_id.strip(),
        "W2: workflow_id is auto-generated as a non-empty str",
    )


def scenario_independent_workflow_ids() -> None:
    ids = {_make_workflow().workflow_id for _ in range(20)}

    check(
        len(ids) == 20,
        "W2: 20 Workflows constructed without an explicit workflow_id "
        "never collide",
    )


# ---------------------------------------------------------------------------
# W3 -- explicit workflow_id honored
# ---------------------------------------------------------------------------
def scenario_explicit_workflow_id_honored() -> None:
    workflow = _make_workflow(workflow_id="custom-id-123")

    check(
        workflow.workflow_id == "custom-id-123",
        "W3: an explicitly supplied workflow_id is honored as-is",
    )


# ---------------------------------------------------------------------------
# W4 -- default status is CREATED
# ---------------------------------------------------------------------------
def scenario_default_status_is_created() -> None:
    workflow = _make_workflow()

    check(
        workflow.status is WorkflowStatus.CREATED,
        "W4: status defaults to WorkflowStatus.CREATED",
    )


# ---------------------------------------------------------------------------
# W5 -- custom status honored
# ---------------------------------------------------------------------------
def scenario_custom_status_honored() -> None:
    for status in WorkflowStatus:
        workflow = _make_workflow(status=status)
        check(
            workflow.status is status,
            f"W5: an explicitly supplied status ({status.name}) is honored",
        )


# ---------------------------------------------------------------------------
# W6 -- frozen fields reject reassignment
# ---------------------------------------------------------------------------
def scenario_frozen_fields_reject_reassignment() -> None:
    workflow = _make_workflow()

    for field_name, value in (
        ("name", "new-name"),
        ("description", "new-desc"),
        ("tasks", ()),
        ("status", WorkflowStatus.RUNNING),
        ("metadata", {}),
        ("workflow_id", "new-id"),
    ):
        raised = False
        try:
            setattr(workflow, field_name, value)
        except (FrozenInstanceError, AttributeError, TypeError):
            raised = True

        check(
            raised,
            f"W6: reassigning frozen field '{field_name}' after "
            f"construction raises",
        )


# ---------------------------------------------------------------------------
# W7 -- metadata immutability
# ---------------------------------------------------------------------------
def scenario_metadata_is_immutable() -> None:
    original = {"key": "value"}
    workflow = _make_workflow(metadata=original)

    raised = False
    try:
        workflow.metadata["key"] = "changed"
    except TypeError:
        raised = True

    check(raised, "W7: workflow.metadata rejects item assignment (TypeError)")

    original["key"] = "mutated-after-construction"
    original["new_key"] = "added-after-construction"

    check(
        workflow.metadata["key"] == "value" and "new_key" not in workflow.metadata,
        "W7: mutating the original dict after construction has no effect "
        "on workflow.metadata",
    )


# ---------------------------------------------------------------------------
# W8 -- tasks stored as immutable tuple
# ---------------------------------------------------------------------------
def scenario_tasks_is_immutable_tuple() -> None:
    task_a = _make_task(name="a")
    task_b = _make_task(name="b")
    original_list = [task_a, task_b]
    workflow = _make_workflow(tasks=original_list)

    check(
        isinstance(workflow.tasks, tuple),
        "W8: workflow.tasks is stored as a tuple",
    )

    raised = False
    try:
        workflow.tasks[0] = task_b  # type: ignore[index]
    except TypeError:
        raised = True

    check(raised, "W8: workflow.tasks rejects item assignment (TypeError)")

    original_list.append(_make_task(name="c"))
    original_list[0] = task_b

    check(
        workflow.tasks == (task_a, task_b),
        "W8: mutating the original list after construction has no effect "
        "on workflow.tasks",
    )


# ---------------------------------------------------------------------------
# W9 -- duplicate tasks allowed
# ---------------------------------------------------------------------------
def scenario_duplicate_tasks_allowed() -> None:
    task = _make_task(name="dup")
    workflow = _make_workflow(tasks=(task, task))

    check(
        workflow.tasks == (task, task) and len(workflow.tasks) == 2,
        "W9: the exact same Task object appearing more than once is "
        "accepted without error",
    )

    twin_a = _make_task(name="twin")
    twin_b = _make_task(name="twin")
    workflow_twins = _make_workflow(tasks=(twin_a, twin_b))

    check(
        len(workflow_twins.tasks) == 2,
        "W9: two distinct Task instances with identical field values are "
        "both accepted without error",
    )


# ---------------------------------------------------------------------------
# W10 -- insertion order preserved
# ---------------------------------------------------------------------------
def scenario_insertion_order_preserved() -> None:
    tasks = [_make_task(name=f"task-{i}") for i in range(6)]
    workflow = _make_workflow(tasks=tasks)

    check(
        workflow.tasks == tuple(tasks),
        "W10: workflow.tasks preserves exactly the order supplied at "
        "construction",
    )


# ---------------------------------------------------------------------------
# W11 -- equality requires every field, including workflow_id
# ---------------------------------------------------------------------------
def scenario_equality_requires_every_field_including_id() -> None:
    shared_task = _make_task(name="shared")

    workflow_a = Workflow(
        name="n", description="d", tasks=(shared_task,), workflow_id="same-id"
    )
    workflow_b = Workflow(
        name="n", description="d", tasks=(shared_task,), workflow_id="same-id"
    )
    check(
        workflow_a == workflow_b,
        "W11: two Workflows with identical fields (including explicit, "
        "matching workflow_id) are equal",
    )

    workflow_c = _make_workflow(name="n", description="d")
    workflow_d = _make_workflow(name="n", description="d")
    check(
        workflow_c != workflow_d,
        "W11: two Workflows built identically but with auto-generated "
        "(thus differing) workflow_ids are unequal",
    )

    workflow_e = Workflow(
        name="n", description="different", tasks=(shared_task,),
        workflow_id="same-id",
    )
    check(
        workflow_a != workflow_e,
        "W11: Workflows differing in a single field (description) are "
        "unequal even with a matching workflow_id",
    )


# ---------------------------------------------------------------------------
# W12 -- repr() is stable and informative
# ---------------------------------------------------------------------------
def scenario_repr_is_stable_and_informative() -> None:
    workflow = _make_workflow(name="my-workflow", workflow_id="abc-123")

    representation = repr(workflow)

    check(
        "my-workflow" in representation and "abc-123" in representation,
        "W12: repr() includes the workflow's name and workflow_id",
    )
    check(
        repr(workflow) == representation,
        "W12: repr() is stable across repeated calls",
    )


# ---------------------------------------------------------------------------
# W13 -- hashability
# ---------------------------------------------------------------------------
def scenario_workflow_is_hashable() -> None:
    workflow_a = Workflow(name="n", description="d", workflow_id="same-id")
    workflow_b = Workflow(name="n", description="d", workflow_id="same-id")

    raised = False
    try:
        hashed = hash(workflow_a)
    except TypeError:
        raised = True
        hashed = None

    check(not raised, "W13: a Workflow instance is hashable")
    check(
        hash(workflow_a) == hash(workflow_b),
        "W13: two equal Workflows share the same hash",
    )

    workflow_set = {workflow_a, workflow_b, _make_workflow()}
    check(
        len(workflow_set) == 2,
        "W13: a set of Workflows collapses equal instances but keeps "
        "distinct ones",
    )


# ---------------------------------------------------------------------------
# W14 -- invalid construction rejected
# ---------------------------------------------------------------------------
def scenario_invalid_construction_rejected() -> None:
    for bad_name in ("", "   ", None, 123, []):
        raised = False
        try:
            Workflow(name=bad_name, description="d")
        except WorkflowError:
            raised = True
        check(raised, f"W14: Workflow(name={bad_name!r}, ...) raises WorkflowError")

    for bad_description in (None, 123, [], {}):
        raised = False
        try:
            Workflow(name="n", description=bad_description)
        except WorkflowError:
            raised = True
        check(
            raised,
            f"W14: Workflow(description={bad_description!r}, ...) raises "
            f"WorkflowError",
        )

    for bad_tasks in (
        (1, 2, 3),
        ["not-a-task"],
        (_make_task(), "not-a-task"),
        123,
        object(),
    ):
        raised = False
        try:
            Workflow(name="n", description="d", tasks=bad_tasks)
        except WorkflowError:
            raised = True
        check(
            raised,
            f"W14: Workflow(tasks={bad_tasks!r}, ...) raises WorkflowError",
        )

    for bad_status in ("CREATED", 1, None, "running"):
        raised = False
        try:
            Workflow(name="n", description="d", status=bad_status)
        except WorkflowError:
            raised = True
        check(
            raised,
            f"W14: Workflow(status={bad_status!r}, ...) raises WorkflowError",
        )

    for bad_metadata in ("not-a-mapping", 123, ["k", "v"], None):
        raised = False
        try:
            Workflow(name="n", description="d", metadata=bad_metadata)
        except WorkflowError:
            raised = True
        check(
            raised,
            f"W14: Workflow(metadata={bad_metadata!r}, ...) raises "
            f"WorkflowError",
        )

    for bad_workflow_id in ("", "   ", None, 123):
        raised = False
        try:
            Workflow(name="n", description="d", workflow_id=bad_workflow_id)
        except WorkflowError:
            raised = True
        check(
            raised,
            f"W14: Workflow(workflow_id={bad_workflow_id!r}, ...) raises "
            f"WorkflowError",
        )


# ---------------------------------------------------------------------------
# W15 -- WorkflowError is an AgentError
# ---------------------------------------------------------------------------
def scenario_workflow_error_is_agent_error_subclass() -> None:
    check(
        issubclass(WorkflowError, AgentError),
        "W15: WorkflowError is a subclass of Core.exceptions.AgentError",
    )

    raised_as_agent_error = False
    try:
        Workflow(name="", description="d")
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "W15: a WorkflowError from invalid construction can be caught as "
        "AgentError",
    )


# ---------------------------------------------------------------------------
# W16 -- no execution/scheduling/persistence/eventing/graph surface
# ---------------------------------------------------------------------------
def scenario_no_execution_or_persistence_surface() -> None:
    workflow = _make_workflow()

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
        "execute",
        "save",
        "load",
        "to_dict",
        "from_dict",
        "to_json",
        "from_json",
        "serialize",
        "deserialize",
        "publish",
        "subscribe",
        "unsubscribe",
        "event_bus",
        "add_dependency",
        "dependencies",
        "next_task",
        "add_task",
        "remove_task",
        "traverse",
        "graph",
    )

    none_present = all(
        not hasattr(workflow, member) for member in forbidden_members
    )
    check(
        none_present,
        "W16: Workflow exposes none of the forbidden execution/scheduling/"
        "persistence/eventing/graph-traversal members",
    )


# ---------------------------------------------------------------------------
# W17 -- default tasks / metadata
# ---------------------------------------------------------------------------
def scenario_defaults_are_empty() -> None:
    workflow = _make_workflow()

    check(
        workflow.tasks == (),
        "W17: default tasks is an empty tuple when not supplied",
    )
    check(
        dict(workflow.metadata) == {},
        "W17: default metadata is an empty mapping when not supplied",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_workflow_status_members,
        scenario_workflow_id_auto_generated,
        scenario_independent_workflow_ids,
        scenario_explicit_workflow_id_honored,
        scenario_default_status_is_created,
        scenario_custom_status_honored,
        scenario_frozen_fields_reject_reassignment,
        scenario_metadata_is_immutable,
        scenario_tasks_is_immutable_tuple,
        scenario_duplicate_tasks_allowed,
        scenario_insertion_order_preserved,
        scenario_equality_requires_every_field_including_id,
        scenario_repr_is_stable_and_informative,
        scenario_workflow_is_hashable,
        scenario_invalid_construction_rejected,
        scenario_workflow_error_is_agent_error_subclass,
        scenario_no_execution_or_persistence_surface,
        scenario_defaults_are_empty,
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
    print(f"PHASE 3 SPRINT 27 WORKFLOW RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())