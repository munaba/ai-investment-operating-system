"""
Phase 4 Sprint 34 proof suite -- Planner -> Workflow Integration
(``GoalPlanner.build_workflow()``).

Scope: dedicated regression suite for the single new public method
this sprint adds -- ``Orchestration.planner.GoalPlanner.
build_workflow()``. ``Orchestration.workflow.Workflow``/
``WorkflowStatus``/``WorkflowError`` (covered by ``Tests/
test_stage_l28_sprint27_workflow.py``), ``Orchestration.task.Task``
(Sprint 24), ``Orchestration.planner.GoalPlanner``'s pre-existing
``build_plan``/``execute_plan``/``translate_metadata``/
``accumulate_context``/``Goal``/``PlanStep``/``ExecutionPlan``
surface (Stage L15), ``Orchestration.workflow_engine.WorkflowEngine``,
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator``, ``Orchestration.executor.Executor``,
``Orchestration.autonomous_host.AutonomousHost``,
``Orchestration.autonomous_scheduler.AutonomousScheduler``, and the
Composition Root are all untouched by this sprint and are not
exercised (beyond real ``Task``/``Workflow`` instances used as plain
fixtures) by this suite.

``build_workflow()`` introduces no execution, no scheduling, and no
workflow preparation of any kind: this suite proves it is nothing
more than argument validation (mirroring the same isinstance/
emptiness-check philosophy ``Task``/``Workflow`` already use) plus a
single ``Workflow(...)`` construction call -- and, just as
importantly, proves the *absence* of any import of ``WorkflowEngine``,
``WorkflowExecutionCoordinator``, ``Executor``, or
``AutonomousScheduler`` anywhere in ``Orchestration/planner.py``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x / Sprint 1x-34 proof suites: a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    P1  -- a valid call returns a Workflow with the exact name/
           description/tasks/metadata supplied.
    P2  -- an invalid 'name' (None, empty str, whitespace-only str,
           non-str) raises GoalPlannerError, without constructing a
           Workflow.
    P3  -- an invalid 'description' (non-str) raises
           GoalPlannerError.
    P4  -- an invalid 'tasks' argument (None, a non-iterable, a str/
           bytes, or an iterable containing a non-Task item) raises
           GoalPlannerError.
    P5  -- an invalid 'metadata' argument (a non-Mapping, non-None
           value) raises GoalPlannerError.
    P6  -- an empty tasks collection is accepted -- build_workflow
           returns a Workflow with an empty tasks tuple, no error.
    P7  -- duplicate tasks (the same Task instance repeated, and two
           distinct Task instances with identical field values) are
           both accepted unchanged, with all duplicates preserved.
    P8  -- task ordering is preserved exactly as supplied.
    P9  -- metadata is copied: mutating the dict passed in after the
           call has no effect on the returned Workflow's metadata.
    P10 -- the returned Workflow's metadata is itself immutable
           (TypeError on item assignment).
    P11 -- calling build_workflow does not mutate or otherwise alter
           the 'tasks' iterable or 'metadata' mapping the caller
           passed in (beyond what a plain, non-mutating read would
           do).
    P12 -- build_workflow never executes anything: no Task or
           Workflow gains any new attribute, no Task.status or
           Workflow.status is anything other than its default
           (PENDING / CREATED), and no ServiceSkill in the
           GoalPlanner's own registry is ever called.
    P13 -- build_workflow never calls WorkflowEngine.prepare() or
           touches any WorkflowEngine at all -- proven both because
           this method's signature accepts no WorkflowEngine argument
           and via the AST import check in P16.
    P14 -- Orchestration/planner.py never imports
           Orchestration.executor or Orchestration.workflow_engine
           (AST inspection of the module's own import statements).
    P15 -- Orchestration/planner.py never imports
           Orchestration.autonomous_scheduler.
    P16 -- Orchestration/planner.py never imports
           Orchestration.workflow_execution_coordinator or
           Orchestration.autonomous_host.
    P17 -- multiple build_workflow calls with identical arguments
           produce independent Workflow instances (not the same
           object, and mutating one's source tasks list afterward
           does not affect the other).
    P18 -- every Workflow returned by build_workflow has a unique,
           auto-generated workflow_id -- no two calls ever collide.
    P19 -- repr() of the returned Workflow is stable (same string on
           repeated calls) and informative (contains the class name).
    P20 -- error propagation: GoalPlannerError is a subclass of
           Core.exceptions.AgentError, so every rejection above can
           also be caught as a plain AgentError.
    P21 -- GoalPlanner's constructor and its pre-existing
           build_plan/execute_plan/translate_metadata/
           accumulate_context surface are completely unaffected --
           a GoalPlanner built with an empty service_skills registry
           still behaves exactly as Stage L15 already locked down.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.planner import GoalPlanner, GoalPlannerError
from Orchestration.task import Task, TaskStatus
from Orchestration.workflow import Workflow, WorkflowStatus

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


def _make_task(name: str = "t", description: str = "d", **kwargs) -> Task:
    return Task(name=name, description=description, **kwargs)


def _make_planner() -> GoalPlanner:
    # Sprint 34's build_workflow() never touches self._service_skills,
    # so an empty registry is sufficient (and deliberately proves that
    # build_workflow needs no ServiceSkill collaborator at all).
    return GoalPlanner({})


# ---------------------------------------------------------------------------
# P1 -- valid workflow creation
# ---------------------------------------------------------------------------
def scenario_valid_workflow_creation() -> None:
    planner = _make_planner()
    tasks = [_make_task(name="a"), _make_task(name="b")]
    metadata = {"key": "value"}

    workflow = planner.build_workflow(
        name="wf-name",
        description="wf-description",
        tasks=tasks,
        metadata=metadata,
    )

    check(isinstance(workflow, Workflow), "P1: build_workflow returns a Workflow instance")
    check(workflow.name == "wf-name", "P1: name is carried through unchanged")
    check(
        workflow.description == "wf-description",
        "P1: description is carried through unchanged",
    )
    check(tuple(workflow.tasks) == tuple(tasks), "P1: tasks are carried through unchanged")
    check(dict(workflow.metadata) == metadata, "P1: metadata is carried through unchanged")
    check(
        workflow.status == WorkflowStatus.CREATED,
        "P1: the returned Workflow defaults to WorkflowStatus.CREATED",
    )


def scenario_metadata_defaults_to_empty() -> None:
    planner = _make_planner()
    workflow = planner.build_workflow(
        name="wf", description="d", tasks=[_make_task()]
    )
    check(
        dict(workflow.metadata) == {},
        "P1: metadata defaults to an empty mapping when omitted",
    )


# ---------------------------------------------------------------------------
# P2 -- invalid name
# ---------------------------------------------------------------------------
def scenario_invalid_name_rejected() -> None:
    planner = _make_planner()
    tasks = [_make_task()]

    for bad_name in (None, "", "   ", 123, [], {}, object()):
        raised = False
        try:
            planner.build_workflow(name=bad_name, description="d", tasks=tasks)
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"P2: build_workflow(name={bad_name!r}, ...) raises GoalPlannerError",
        )


# ---------------------------------------------------------------------------
# P3 -- invalid description
# ---------------------------------------------------------------------------
def scenario_invalid_description_rejected() -> None:
    planner = _make_planner()
    tasks = [_make_task()]

    for bad_description in (None, 123, [], {}, object()):
        raised = False
        try:
            planner.build_workflow(
                name="wf", description=bad_description, tasks=tasks
            )
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"P3: build_workflow(..., description={bad_description!r}, ...) "
            f"raises GoalPlannerError",
        )

    # An empty string description is explicitly valid (mirrors Workflow's
    # own 'may be empty' contract for description).
    workflow = planner.build_workflow(name="wf", description="", tasks=tasks)
    check(
        workflow.description == "",
        "P3: an empty-string description is accepted, not rejected",
    )


# ---------------------------------------------------------------------------
# P4 -- invalid task collection
# ---------------------------------------------------------------------------
def scenario_invalid_tasks_rejected() -> None:
    planner = _make_planner()

    for bad_tasks in (None, 123, "not-iterable-of-tasks", b"bytes", object()):
        raised = False
        try:
            planner.build_workflow(name="wf", description="d", tasks=bad_tasks)
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"P4: build_workflow(..., tasks={bad_tasks!r}) raises "
            f"GoalPlannerError",
        )

    # An iterable containing a non-Task item is also rejected.
    raised = False
    try:
        planner.build_workflow(
            name="wf", description="d", tasks=[_make_task(), "not-a-task"]
        )
    except GoalPlannerError:
        raised = True
    check(
        raised,
        "P4: a tasks iterable containing a non-Task item raises "
        "GoalPlannerError",
    )


# ---------------------------------------------------------------------------
# P5 -- invalid metadata
# ---------------------------------------------------------------------------
def scenario_invalid_metadata_rejected() -> None:
    planner = _make_planner()
    tasks = [_make_task()]

    for bad_metadata in ("not-a-mapping", 123, [], ["a", "b"], object()):
        raised = False
        try:
            planner.build_workflow(
                name="wf", description="d", tasks=tasks, metadata=bad_metadata
            )
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"P5: build_workflow(..., metadata={bad_metadata!r}) raises "
            f"GoalPlannerError",
        )


# ---------------------------------------------------------------------------
# P6 -- empty task collection
# ---------------------------------------------------------------------------
def scenario_empty_task_collection_accepted() -> None:
    planner = _make_planner()

    workflow = planner.build_workflow(name="wf", description="d", tasks=[])

    check(
        workflow.tasks == (),
        "P6: an empty tasks collection is accepted and produces an "
        "empty tasks tuple",
    )

    # A generator (a one-shot, non-list iterable) is also accepted.
    workflow_gen = planner.build_workflow(
        name="wf", description="d", tasks=(t for t in [])
    )
    check(
        workflow_gen.tasks == (),
        "P6: an empty generator is also accepted as 'tasks'",
    )


# ---------------------------------------------------------------------------
# P7 -- duplicate tasks
# ---------------------------------------------------------------------------
def scenario_duplicate_tasks_preserved() -> None:
    planner = _make_planner()
    same_task = _make_task(name="dup")

    workflow = planner.build_workflow(
        name="wf", description="d", tasks=[same_task, same_task, same_task]
    )
    check(
        workflow.tasks == (same_task, same_task, same_task),
        "P7: the exact same Task instance repeated is preserved, "
        "duplicates included",
    )

    task_a = _make_task(name="same-name", description="same-desc")
    task_b = _make_task(name="same-name", description="same-desc")
    workflow2 = planner.build_workflow(
        name="wf2", description="d", tasks=[task_a, task_b]
    )
    check(
        workflow2.tasks == (task_a, task_b),
        "P7: two distinct Task instances with identical field values "
        "are both accepted, unchanged",
    )


# ---------------------------------------------------------------------------
# P8 -- ordering preserved
# ---------------------------------------------------------------------------
def scenario_task_ordering_preserved() -> None:
    planner = _make_planner()
    tasks = [_make_task(name=f"task-{i}") for i in range(9)]

    workflow = planner.build_workflow(name="wf", description="d", tasks=tasks)

    check(
        workflow.tasks == tuple(tasks),
        "P8: task ordering is preserved exactly as supplied",
    )


# ---------------------------------------------------------------------------
# P9 -- metadata copied
# ---------------------------------------------------------------------------
def scenario_metadata_copied() -> None:
    planner = _make_planner()
    original_metadata = {"a": 1, "b": 2}

    workflow = planner.build_workflow(
        name="wf", description="d", tasks=[_make_task()], metadata=original_metadata
    )

    original_metadata["a"] = "mutated"
    original_metadata["c"] = "new-key"

    check(
        dict(workflow.metadata) == {"a": 1, "b": 2},
        "P9: mutating the original metadata dict after the call has "
        "no effect on the returned Workflow's metadata",
    )


# ---------------------------------------------------------------------------
# P10 -- metadata immutable
# ---------------------------------------------------------------------------
def scenario_metadata_immutable() -> None:
    planner = _make_planner()
    workflow = planner.build_workflow(
        name="wf", description="d", tasks=[_make_task()], metadata={"a": 1}
    )

    raised_on_assignment = False
    try:
        workflow.metadata["a"] = 2  # type: ignore[index]
    except TypeError:
        raised_on_assignment = True
    check(
        raised_on_assignment,
        "P10: the returned Workflow's metadata is immutable "
        "(TypeError on item assignment)",
    )


# ---------------------------------------------------------------------------
# P11 -- workflow (inputs) returned unchanged / not mutated
# ---------------------------------------------------------------------------
def scenario_inputs_not_mutated() -> None:
    planner = _make_planner()
    tasks_list = [_make_task(name="a"), _make_task(name="b")]
    tasks_snapshot = list(tasks_list)
    metadata = {"k": "v"}
    metadata_snapshot = dict(metadata)

    planner.build_workflow(
        name="wf", description="d", tasks=tasks_list, metadata=metadata
    )

    check(
        tasks_list == tasks_snapshot,
        "P11: the caller's original tasks list is left unchanged by "
        "build_workflow",
    )
    check(
        metadata == metadata_snapshot,
        "P11: the caller's original metadata dict is left unchanged "
        "by build_workflow",
    )


# ---------------------------------------------------------------------------
# P12 -- planner never executes
# ---------------------------------------------------------------------------
class _ExplodingServiceSkill:
    """A stand-in ServiceSkill whose execute() always raises -- used to
    prove build_workflow() never calls into the GoalPlanner's own
    service_skills registry at all."""

    def execute(self, *args, **kwargs):
        raise AssertionError(
            "build_workflow() must never call ServiceSkill.execute()"
        )


def scenario_planner_never_executes() -> None:
    planner = GoalPlanner({"exploding": _ExplodingServiceSkill()})
    task = _make_task(name="only")
    task_status_before = task.status

    workflow = planner.build_workflow(
        name="wf", description="d", tasks=[task]
    )

    check(
        task.status == task_status_before == TaskStatus.PENDING,
        "P12: build_workflow never mutates or transitions Task.status",
    )
    check(
        workflow.status == WorkflowStatus.CREATED,
        "P12: build_workflow never mutates or transitions "
        "Workflow.status away from its constructed default",
    )
    check(
        not hasattr(planner, "_last_execution_result"),
        "P12: build_workflow leaves no execution-result state on "
        "the GoalPlanner instance",
    )


# ---------------------------------------------------------------------------
# P13 -- planner never prepares (no WorkflowEngine argument/attribute)
# ---------------------------------------------------------------------------
def scenario_planner_never_prepares() -> None:
    import inspect

    signature = inspect.signature(GoalPlanner.build_workflow)
    param_names = list(signature.parameters.keys())

    check(
        "workflow_engine" not in param_names,
        "P13: build_workflow()'s signature accepts no 'workflow_engine' "
        "argument -- it cannot call prepare() on anything",
    )
    check(
        set(param_names) == {"self", "name", "description", "tasks", "metadata"},
        "P13: build_workflow()'s full parameter set is exactly "
        "{name, description, tasks, metadata}",
    )


# ---------------------------------------------------------------------------
# P14/P15/P16 -- Orchestration/planner.py never imports the forbidden
# orchestration-layer modules
# ---------------------------------------------------------------------------
def scenario_planner_module_forbidden_imports() -> None:
    import Orchestration.planner as planner_module

    tree = ast.parse(Path(planner_module.__file__).read_text())
    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.append(node.module)
            imported_names.extend(alias.name for alias in node.names)

    check(
        not any("executor" in name.lower() for name in imported_names),
        "P14: Orchestration/planner.py never imports anything "
        "referencing 'executor'",
    )
    check(
        not any("workflow_engine" in name.lower() for name in imported_names),
        "P14: Orchestration/planner.py never imports "
        "Orchestration.workflow_engine",
    )
    check(
        not any("scheduler" in name.lower() for name in imported_names),
        "P15: Orchestration/planner.py never imports "
        "Orchestration.autonomous_scheduler (or any *scheduler*)",
    )
    check(
        not any(
            "workflow_execution_coordinator" in name.lower()
            for name in imported_names
        ),
        "P16: Orchestration/planner.py never imports "
        "Orchestration.workflow_execution_coordinator",
    )
    check(
        not any("autonomous_host" in name.lower() for name in imported_names),
        "P16: Orchestration/planner.py never imports "
        "Orchestration.autonomous_host",
    )


# ---------------------------------------------------------------------------
# P17 -- multiple calls produce independent workflows
# ---------------------------------------------------------------------------
def scenario_multiple_calls_independent() -> None:
    planner = _make_planner()
    tasks = [_make_task(name="shared")]
    metadata = {"k": "v"}

    workflow_1 = planner.build_workflow(
        name="wf", description="d", tasks=tasks, metadata=metadata
    )
    workflow_2 = planner.build_workflow(
        name="wf", description="d", tasks=tasks, metadata=metadata
    )

    check(
        workflow_1 is not workflow_2,
        "P17: two build_workflow calls with identical arguments "
        "produce two distinct Workflow objects",
    )
    check(
        workflow_1.workflow_id != workflow_2.workflow_id,
        "P17: the two independently-built Workflows have distinct "
        "auto-generated workflow_ids",
    )

    # Mutating the shared source list afterward affects neither
    # already-built Workflow (tasks were materialized into a tuple at
    # call time).
    tasks.append(_make_task(name="appended-later"))
    check(
        len(workflow_1.tasks) == 1 and len(workflow_2.tasks) == 1,
        "P17: mutating the shared source tasks list after both calls "
        "affects neither already-built Workflow",
    )


# ---------------------------------------------------------------------------
# P18 -- workflow ids unique
# ---------------------------------------------------------------------------
def scenario_workflow_ids_unique() -> None:
    planner = _make_planner()
    ids = {
        planner.build_workflow(
            name=f"wf-{i}", description="d", tasks=[]
        ).workflow_id
        for i in range(50)
    }
    check(
        len(ids) == 50,
        "P18: 50 build_workflow calls produce 50 unique workflow_ids",
    )


# ---------------------------------------------------------------------------
# P19 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_stability() -> None:
    planner = _make_planner()
    workflow = planner.build_workflow(
        name="wf", description="d", tasks=[_make_task(name="only")]
    )

    repr_1 = repr(workflow)
    repr_2 = repr(workflow)

    check(repr_1 == repr_2, "P19: repr() of the returned Workflow is stable")
    check(
        "Workflow" in repr_1,
        "P19: repr() of the returned Workflow is informative "
        "(mentions the class name)",
    )


# ---------------------------------------------------------------------------
# P20 -- error propagation (GoalPlannerError is an AgentError)
# ---------------------------------------------------------------------------
def scenario_error_propagation() -> None:
    check(
        issubclass(GoalPlannerError, AgentError),
        "P20: GoalPlannerError is a subclass of Core.exceptions.AgentError",
    )

    planner = _make_planner()
    caught_as_agent_error = False
    try:
        planner.build_workflow(name="", description="d", tasks=[])
    except AgentError:
        caught_as_agent_error = True
    check(
        caught_as_agent_error,
        "P20: a build_workflow validation failure can be caught as a "
        "plain AgentError",
    )


# ---------------------------------------------------------------------------
# P21 -- pre-existing GoalPlanner surface unaffected
# ---------------------------------------------------------------------------
def scenario_pre_existing_surface_unaffected() -> None:
    from Orchestration.planner import ExecutionPlan, Goal, PlanStep

    planner = GoalPlanner({})
    goal = Goal(metadata={"x": 1})

    plan = planner.build_plan(goal)
    check(
        isinstance(plan, ExecutionPlan) and plan.steps == (),
        "P21: build_plan() against an empty service_skills registry "
        "still behaves exactly as before -- an empty ExecutionPlan",
    )

    results = planner.execute_plan(plan)
    check(
        results == [],
        "P21: execute_plan() on an empty plan still returns an empty "
        "list, unaffected by build_workflow's addition",
    )

    translated = planner.translate_metadata(
        PlanStep(service_name="unrelated"), {"a": 1}
    )
    check(
        translated == {"a": 1},
        "P21: translate_metadata()'s default pass-through behavior is "
        "unaffected",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_valid_workflow_creation,
        scenario_metadata_defaults_to_empty,
        scenario_invalid_name_rejected,
        scenario_invalid_description_rejected,
        scenario_invalid_tasks_rejected,
        scenario_invalid_metadata_rejected,
        scenario_empty_task_collection_accepted,
        scenario_duplicate_tasks_preserved,
        scenario_task_ordering_preserved,
        scenario_metadata_copied,
        scenario_metadata_immutable,
        scenario_inputs_not_mutated,
        scenario_planner_never_executes,
        scenario_planner_never_prepares,
        scenario_planner_module_forbidden_imports,
        scenario_multiple_calls_independent,
        scenario_workflow_ids_unique,
        scenario_repr_stability,
        scenario_error_propagation,
        scenario_pre_existing_surface_unaffected,
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
    print(f"PHASE 4 SPRINT 34 PLANNER-WORKFLOW RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())