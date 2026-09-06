"""
Phase 4 Sprint 42 proof suite -- ``GoalPlanner`` <- ``Memory``
integration (Closed Learning Loop).

Scope: dedicated regression suite for the Sprint 42 addition only --
``GoalPlanner.__init__(memory=...)`` accepting an optional, duck-typed
memory collaborator, and the new ``GoalPlanner.recall(goal)`` method
reading (never writing) relevant past experience from it. This is
integration only: no new architectural layer, no new value object, no
manager, no singleton, no global state, and no duplicated planning or
memory logic. ``GoalPlanner``'s existing four-plus-one-method contract
(``build_plan``/``execute_plan``/``translate_metadata``/
``accumulate_context``/``build_workflow``, Stage L15 + Sprint 34,
exercised in full by ``Tests/test_stage_l15_plaanner.py`` and
``Tests/test_stage_l34_planner_workflow.py``) is unchanged; ``Memory``'s
existing ``MemoryStore``/``MemoryRecorder`` contract (Stage L17,
exercised in full by ``Tests/test_stage_l17_memory.py``) is unchanged.
Neither of those suites is re-verified here beyond confirming Sprint 42
introduces no regression to them.

GoalPlanner never imports, constructs, or references MemoryStore,
MemoryRecorder, Observation, Reflector, LearningLoop, WorkflowRuntime,
Executor, AutonomousScheduler, AutonomousHost, EventBus, or
Core.composition_root (proven by module-namespace inspection, mirroring
test_stage_l40_reflection_learning.py's S9/S12-S14 and
test_stage_l41_learning_memory.py's M8/M12-M14). GoalPlanner remains
the only caller of the memory collaborator it is given -- the memory
collaborator is never handed a reference back to the planner, and
never called by anything other than ``recall``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L4x / Sprint 1x-41 proof suites: a global pass/fail
counter, plain fixtures (a thin recording/duck-typed stand-in for a
memory collaborator, plus the real ``ServiceSkill``/``Observation``/
``MemoryStore`` types where useful), and a ``main()`` runner.

Invariant coverage:
    L1  -- planner works without memory: GoalPlanner(service_skills)
           (memory omitted, defaults to None) builds and executes
           plans exactly as before.
    L2  -- planner accepts memory when given: GoalPlanner(service_skills,
           memory=stub) constructs successfully.
    L3  -- invalid memory attachment rejected: GoalPlanner(sk, memory=X)
           raises GoalPlannerError when X has no callable list
           attribute.
    L4  -- recall with no memory: recall(goal) returns () when no
           memory was supplied at construction time.
    L5  -- recall reads memory exactly once per call: one recall() call
           invokes stub.list() exactly once.
    L6  -- recall returns relevant past experience: a goal whose
           metadata overlaps a stored record's goal_metadata gets that
           record's aggregated_outputs back.
    L7  -- recall excludes irrelevant experience: a stored record whose
           goal_metadata shares no (key, value) pair with goal.metadata
           is excluded from the result.
    L8  -- recall never mutates memory: after any number of recall()
           calls, the memory collaborator's own stored state is
           byte-for-byte identical to before.
    L9  -- recall never writes to memory: the stub's write-tracking
           method (add) is never called by recall(), regardless of
           how many times recall() runs.
    L10 -- recall returns fresh copies: mutating a dict returned by
           recall() never affects the memory collaborator's own stored
           data.
    L11 -- recall works against a real MemoryStore: exercised through
           MemoryStore/MemoryRecorder/Observation exactly as Stage
           L17/L16 locked them, with GoalPlanner.recall() layered on
           top read-only.
    L12 -- planner remains Reflection independent: Orchestration.
           planner's module namespace contains no Reflector/
           ReflectionRecord symbol.
    L13 -- planner remains LearningLoop independent: Orchestration.
           planner's module namespace contains no LearningLoop symbol.
    L14 -- planner remains Runtime independent: Orchestration.planner's
           module namespace contains no WorkflowRuntime/WorkflowEngine
           symbol.
    L15 -- planner remains Executor independent: Orchestration.
           planner's module namespace contains no Executor symbol.
    L16 -- planner never publishes/subscribes to events: a GoalPlanner
           instance exposes no publish/subscribe/attach-shaped method;
           Orchestration.planner's module namespace contains no
           EventBus/Event symbol.
    L17 -- planner never starts a scheduler: Orchestration.planner's
           module namespace contains no Scheduler/AutonomousScheduler/
           AutonomousHost symbol.
    L18 -- planner never imports Memory or Composition Root
           implementation symbols: Orchestration.planner's module
           namespace contains no MemoryStore/MemoryRecorder/
           CompositionRoot symbol -- memory is accepted purely by duck
           typing.
    L19 -- planner still builds Workflow: build_workflow() is
           completely unaffected by the memory/recall addition.
    L20 -- no regression: build_plan/execute_plan/translate_metadata/
           accumulate_context all behave identically whether or not a
           memory collaborator is attached.
    L21 -- multiple planner instances: two GoalPlanner instances, each
           constructed with their own distinct memory stub, recall only
           from their own stub -- no cross-talk.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.memory import MemoryRecorder, MemoryStore
from Orchestration.observation import Observation
from Orchestration.planner import ExecutionPlan, Goal, GoalPlanner, GoalPlannerError, PlanStep
from Orchestration.service_skill import ServiceSkill
from Services.metadata_keys import MetadataKeys
from Services.service_result import ServiceResult

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
# Fixtures
# ---------------------------------------------------------------------------
class _StubSkillMetadata:
    def __init__(self, service_name, required_inputs=(), produced_outputs=()):
        self.service_name = service_name
        self.required_inputs = tuple(required_inputs)
        self.produced_outputs = tuple(produced_outputs)


class _StubServiceSkill:
    """Minimal ServiceSkill-shaped stub -- built and executed exactly
    like Stage L15's own fixtures, kept local so this suite does not
    depend on any particular production Service."""

    def __init__(self, service_name, required_inputs=(), produced_outputs=(),
                 output_data=None):
        self.metadata = _StubSkillMetadata(service_name, required_inputs, produced_outputs)
        self._output_data = output_data or {}

    def execute(self, user_input, metadata, agent_name, provider_name, request_id):
        return ServiceResult(
            success=True,
            message="ok",
            data=dict(self._output_data),
            metadata=dict(metadata),
        )


class RecordingMemory:
    """A minimal duck-typed memory stand-in exposing both ``list()``
    (read) and ``add()`` (write-tracking, used only to prove ``recall``
    never calls it) without doing anything else.

    Deliberately NOT a ``MemoryStore`` subclass -- Sprint 42's
    ``recall()`` is proven here to work against anything shaped like a
    memory collaborator (has a callable ``list``), exactly as
    ``GoalPlanner.__init__()``'s duck-typing validation requires. The
    real ``MemoryStore``/``MemoryRecorder``/``Observation`` are
    exercised separately (L11) to confirm their own Stage L17/L16
    behavior is untouched.
    """

    def __init__(self, records=()):
        self._records = tuple(records)
        self.list_calls = 0
        self.add_calls: List[Any] = []

    def list(self):
        self.list_calls += 1
        return self._records

    def add(self, record):
        # Never expected to be called by GoalPlanner.recall() -- kept
        # only so L9 can assert it stays untouched.
        self.add_calls.append(record)


class _FakeObservation:
    """Duck-typed observation-shaped stand-in -- deliberately NOT an
    ``Orchestration.observation.Observation`` instance, proving
    ``recall()`` only ever uses ``getattr``, never ``isinstance``
    against the real ``Observation`` type."""

    def __init__(self, goal_metadata, aggregated_outputs):
        self.goal_metadata = goal_metadata
        self.aggregated_outputs = aggregated_outputs


class _FakeRecord:
    def __init__(self, observation):
        self.observation = observation


def _plain_skills() -> Dict[str, ServiceSkill]:
    return {
        "a": _StubServiceSkill("a", required_inputs=(), produced_outputs=("X",)),
        "b": _StubServiceSkill("b", required_inputs=("X",), produced_outputs=("Y",)),
    }


# ---------------------------------------------------------------------------
# L1 -- planner works without memory
# ---------------------------------------------------------------------------
def scenario_planner_works_without_memory() -> None:
    planner = GoalPlanner(_plain_skills())
    plan = planner.build_plan(Goal(metadata={}))
    results = planner.execute_plan(plan)

    check(
        [step.service_name for step in plan.steps] == ["a", "b"],
        "L1: build_plan still produces the same deterministic plan "
        "when memory is omitted",
    )
    check(
        len(results) == 2 and all(r.success for r in results),
        "L1: execute_plan still runs every step successfully when "
        "memory is omitted",
    )
    check(
        planner.recall(Goal(metadata={})) == (),
        "L1: recall() returns an empty tuple when no memory was given",
    )


# ---------------------------------------------------------------------------
# L2 -- planner accepts memory when given
# ---------------------------------------------------------------------------
def scenario_planner_accepts_memory() -> None:
    stub = RecordingMemory()
    planner = GoalPlanner(_plain_skills(), memory=stub)
    check(
        isinstance(planner, GoalPlanner),
        "L2: GoalPlanner(service_skills, memory=stub) constructs successfully",
    )

    planner2 = GoalPlanner(_plain_skills(), memory=MemoryStore())
    check(
        isinstance(planner2, GoalPlanner),
        "L2: GoalPlanner() also accepts a real MemoryStore instance as memory",
    )


# ---------------------------------------------------------------------------
# L3 -- invalid memory attachment rejected
# ---------------------------------------------------------------------------
def scenario_invalid_memory_rejected() -> None:
    for bad in ("not-a-memory", 123, object(), [], {}):
        raised = False
        try:
            GoalPlanner(_plain_skills(), memory=bad)  # type: ignore[arg-type]
        except GoalPlannerError:
            raised = True
        check(
            raised,
            f"L3: GoalPlanner(memory={bad!r}) raises GoalPlannerError "
            f"when memory has no callable list attribute",
        )

    class NoListMethod:
        list = "not callable"

    raised = False
    try:
        GoalPlanner(_plain_skills(), memory=NoListMethod())
    except GoalPlannerError:
        raised = True
    check(
        raised,
        "L3: GoalPlanner() rejects an object whose 'list' attribute "
        "exists but is not callable",
    )


# ---------------------------------------------------------------------------
# L4 -- recall with no memory
# ---------------------------------------------------------------------------
def scenario_recall_no_memory() -> None:
    planner = GoalPlanner(_plain_skills())
    check(
        planner.recall(Goal(metadata={"TICKER": "BBCA"})) == (),
        "L4: recall(goal) returns () when no memory was supplied at "
        "construction time",
    )


# ---------------------------------------------------------------------------
# L5 -- recall reads memory exactly once per call
# ---------------------------------------------------------------------------
def scenario_recall_reads_once() -> None:
    stub = RecordingMemory(records=())
    planner = GoalPlanner(_plain_skills(), memory=stub)
    planner.recall(Goal(metadata={"TICKER": "BBCA"}))
    check(
        stub.list_calls == 1,
        "L5: one recall() call invokes memory.list() exactly once",
    )
    planner.recall(Goal(metadata={"TICKER": "BBCA"}))
    check(
        stub.list_calls == 2,
        "L5: a second recall() call invokes memory.list() exactly once more",
    )


# ---------------------------------------------------------------------------
# L6 -- recall returns relevant past experience
# ---------------------------------------------------------------------------
def scenario_recall_returns_relevant() -> None:
    matching = _FakeRecord(
        _FakeObservation(
            goal_metadata={"TICKER": "BBCA"},
            aggregated_outputs={"SCORE": 0.9},
        )
    )
    stub = RecordingMemory(records=(matching,))
    planner = GoalPlanner(_plain_skills(), memory=stub)

    result = planner.recall(Goal(metadata={"TICKER": "BBCA", "PERIOD": "1D"}))
    check(
        result == ({"SCORE": 0.9},),
        "L6: recall() returns the aggregated_outputs of a record whose "
        "goal_metadata overlaps the given goal's metadata",
    )


# ---------------------------------------------------------------------------
# L7 -- recall excludes irrelevant experience
# ---------------------------------------------------------------------------
def scenario_recall_excludes_irrelevant() -> None:
    unrelated = _FakeRecord(
        _FakeObservation(
            goal_metadata={"TICKER": "TLKM"},
            aggregated_outputs={"SCORE": 0.1},
        )
    )
    stub = RecordingMemory(records=(unrelated,))
    planner = GoalPlanner(_plain_skills(), memory=stub)

    result = planner.recall(Goal(metadata={"TICKER": "BBCA"}))
    check(
        result == (),
        "L7: recall() excludes a record whose goal_metadata shares no "
        "(key, value) pair with the given goal's metadata",
    )

    same_key_diff_value = _FakeRecord(
        _FakeObservation(
            goal_metadata={"TICKER": "BBCA_OLD"},
            aggregated_outputs={"SCORE": 0.5},
        )
    )
    stub2 = RecordingMemory(records=(same_key_diff_value,))
    planner2 = GoalPlanner(_plain_skills(), memory=stub2)
    result2 = planner2.recall(Goal(metadata={"TICKER": "BBCA"}))
    check(
        result2 == (),
        "L7: recall() excludes a record whose value differs even when "
        "the key matches",
    )


# ---------------------------------------------------------------------------
# L8 -- recall never mutates memory
# ---------------------------------------------------------------------------
def scenario_recall_never_mutates_memory() -> None:
    record = _FakeRecord(
        _FakeObservation(
            goal_metadata={"TICKER": "BBCA"},
            aggregated_outputs={"SCORE": 0.9},
        )
    )
    stub = RecordingMemory(records=(record,))
    planner = GoalPlanner(_plain_skills(), memory=stub)

    before = stub._records
    for _ in range(5):
        planner.recall(Goal(metadata={"TICKER": "BBCA"}))
    after = stub._records

    check(
        before == after and before[0] is after[0],
        "L8: repeated recall() calls never change the memory "
        "collaborator's own stored records",
    )


# ---------------------------------------------------------------------------
# L9 -- recall never writes to memory
# ---------------------------------------------------------------------------
def scenario_recall_never_writes() -> None:
    record = _FakeRecord(
        _FakeObservation(
            goal_metadata={"TICKER": "BBCA"},
            aggregated_outputs={"SCORE": 0.9},
        )
    )
    stub = RecordingMemory(records=(record,))
    planner = GoalPlanner(_plain_skills(), memory=stub)

    for _ in range(3):
        planner.recall(Goal(metadata={"TICKER": "BBCA"}))

    check(
        stub.add_calls == [],
        "L9: recall() never invokes the memory collaborator's add() "
        "-- it only ever reads via list()",
    )


# ---------------------------------------------------------------------------
# L10 -- recall returns fresh copies
# ---------------------------------------------------------------------------
def scenario_recall_returns_fresh_copies() -> None:
    original_outputs = {"SCORE": 0.9}
    record = _FakeRecord(
        _FakeObservation(
            goal_metadata={"TICKER": "BBCA"},
            aggregated_outputs=original_outputs,
        )
    )
    stub = RecordingMemory(records=(record,))
    planner = GoalPlanner(_plain_skills(), memory=stub)

    result = planner.recall(Goal(metadata={"TICKER": "BBCA"}))
    returned_dict = result[0]
    returned_dict["SCORE"] = 999
    returned_dict["INJECTED"] = "bad"

    check(
        original_outputs == {"SCORE": 0.9},
        "L10: mutating a dict returned by recall() never affects the "
        "memory collaborator's own stored aggregated_outputs",
    )


# ---------------------------------------------------------------------------
# L11 -- recall works against a real MemoryStore
# ---------------------------------------------------------------------------
def scenario_recall_real_memory_store() -> None:
    store = MemoryStore()
    recorder = MemoryRecorder(store)

    observation = Observation(
        goal_metadata={"TICKER": "BBCA", "PERIOD": "1D"},
        plan_step_names=("a", "b"),
        steps=(),
        aggregated_outputs={"SCORE": 0.87},
    )
    recorder.record(observation)

    other_observation = Observation(
        goal_metadata={"TICKER": "UNVR"},
        plan_step_names=("a",),
        steps=(),
        aggregated_outputs={"SCORE": 0.2},
    )
    recorder.record(other_observation)

    planner = GoalPlanner(_plain_skills(), memory=store)
    result = planner.recall(Goal(metadata={"TICKER": "BBCA"}))

    check(
        result == ({"SCORE": 0.87},),
        "L11: recall() against a real MemoryStore/MemoryRecorder/"
        "Observation returns only the relevant record's aggregated_outputs",
    )
    check(
        len(store.list()) == 2,
        "L11: the real MemoryStore itself is completely unaffected by "
        "GoalPlanner.recall() -- both records remain stored",
    )


# ---------------------------------------------------------------------------
# L12 -- planner remains Reflection independent
# ---------------------------------------------------------------------------
def scenario_no_reflection_dependency() -> None:
    import Orchestration.planner as module

    for forbidden in ("Reflector", "ReflectionRecord", "Reflection"):
        check(
            forbidden not in vars(module),
            f"L12: Orchestration.planner's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# L13 -- planner remains LearningLoop independent
# ---------------------------------------------------------------------------
def scenario_no_learning_loop_dependency() -> None:
    import Orchestration.planner as module

    check(
        "LearningLoop" not in vars(module),
        "L13: Orchestration.planner's module namespace does not "
        "contain a 'LearningLoop' symbol",
    )


# ---------------------------------------------------------------------------
# L14 -- planner remains Runtime independent
# ---------------------------------------------------------------------------
def scenario_no_runtime_dependency() -> None:
    import Orchestration.planner as module

    for forbidden in ("WorkflowRuntime", "WorkflowEngine"):
        check(
            forbidden not in vars(module),
            f"L14: Orchestration.planner's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# L15 -- planner remains Executor independent
# ---------------------------------------------------------------------------
def scenario_no_executor_dependency() -> None:
    import Orchestration.planner as module

    check(
        "Executor" not in vars(module),
        "L15: Orchestration.planner's module namespace does not "
        "contain an 'Executor' symbol",
    )


# ---------------------------------------------------------------------------
# L16 -- planner never publishes/subscribes to events
# ---------------------------------------------------------------------------
def scenario_no_event_dependency() -> None:
    import Orchestration.planner as module

    for forbidden in ("EventBus", "Event"):
        check(
            forbidden not in vars(module),
            f"L16: Orchestration.planner's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )

    planner = GoalPlanner(_plain_skills())
    check(
        not hasattr(planner, "publish")
        and not hasattr(planner, "subscribe")
        and not hasattr(planner, "attach"),
        "L16: a GoalPlanner instance exposes no publish/subscribe/"
        "attach-shaped method",
    )


# ---------------------------------------------------------------------------
# L17 -- planner never starts a scheduler
# ---------------------------------------------------------------------------
def scenario_no_scheduler_dependency() -> None:
    import Orchestration.planner as module

    for forbidden in ("Scheduler", "AutonomousScheduler", "AutonomousHost"):
        check(
            forbidden not in vars(module),
            f"L17: Orchestration.planner's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# L18 -- planner never imports Memory/Composition Root implementation
# ---------------------------------------------------------------------------
def scenario_no_memory_or_composition_root_import() -> None:
    import Orchestration.planner as module

    for forbidden in ("MemoryStore", "MemoryRecorder", "CompositionRoot"):
        check(
            forbidden not in vars(module),
            f"L18: Orchestration.planner's module namespace does not "
            f"contain a {forbidden!r} symbol -- memory is accepted "
            f"purely by duck typing",
        )


# ---------------------------------------------------------------------------
# L19 -- planner still builds Workflow
# ---------------------------------------------------------------------------
def scenario_still_builds_workflow() -> None:
    from Orchestration.task import Task

    stub = RecordingMemory(records=())
    planner = GoalPlanner(_plain_skills(), memory=stub)
    task = Task(name="t1", description="d1")
    workflow = planner.build_workflow(
        name="wf", description="desc", tasks=[task], metadata={"k": "v"}
    )
    check(
        workflow.name == "wf" and tuple(workflow.tasks) == (task,),
        "L19: build_workflow() still constructs a Workflow correctly "
        "when a memory collaborator is attached",
    )


# ---------------------------------------------------------------------------
# L20 -- no regression across existing methods
# ---------------------------------------------------------------------------
def scenario_no_regression_existing_methods() -> None:
    skills = _plain_skills()
    goal = Goal(metadata={})

    plain_planner = GoalPlanner(skills)
    memory_planner = GoalPlanner(skills, memory=RecordingMemory(records=()))

    plan_plain = plain_planner.build_plan(goal)
    plan_memory = memory_planner.build_plan(goal)
    check(
        [s.service_name for s in plan_plain.steps]
        == [s.service_name for s in plan_memory.steps],
        "L20: build_plan() output is identical whether or not memory "
        "is attached",
    )

    results_plain = plain_planner.execute_plan(plan_plain)
    results_memory = memory_planner.execute_plan(plan_memory)
    check(
        [r.success for r in results_plain] == [r.success for r in results_memory],
        "L20: execute_plan() output is identical whether or not "
        "memory is attached",
    )

    ctx_plain = plain_planner.accumulate_context({}, results_plain[0])
    ctx_memory = memory_planner.accumulate_context({}, results_memory[0])
    check(
        ctx_plain == ctx_memory,
        "L20: accumulate_context() output is identical whether or not "
        "memory is attached",
    )

    risk_step = PlanStep(service_name="risk_management_service", inputs=())
    translated_plain = plain_planner.translate_metadata(risk_step, {MetadataKeys.PRICE: 100})
    translated_memory = memory_planner.translate_metadata(risk_step, {MetadataKeys.PRICE: 100})
    check(
        translated_plain == translated_memory,
        "L20: translate_metadata() output is identical whether or not "
        "memory is attached",
    )


# ---------------------------------------------------------------------------
# L21 -- multiple planner instances, no cross-talk
# ---------------------------------------------------------------------------
def scenario_multiple_planner_instances() -> None:
    record1 = _FakeRecord(
        _FakeObservation(goal_metadata={"TICKER": "BBCA"}, aggregated_outputs={"SCORE": 1})
    )
    record2 = _FakeRecord(
        _FakeObservation(goal_metadata={"TICKER": "BBCA"}, aggregated_outputs={"SCORE": 2})
    )
    stub1 = RecordingMemory(records=(record1,))
    stub2 = RecordingMemory(records=(record2,))

    planner1 = GoalPlanner(_plain_skills(), memory=stub1)
    planner2 = GoalPlanner(_plain_skills(), memory=stub2)

    result1 = planner1.recall(Goal(metadata={"TICKER": "BBCA"}))
    result2 = planner2.recall(Goal(metadata={"TICKER": "BBCA"}))

    check(
        result1 == ({"SCORE": 1},) and result2 == ({"SCORE": 2},),
        "L21: two GoalPlanner instances each recall only from their "
        "own attached memory collaborator -- no cross-talk",
    )
    check(
        stub1.list_calls == 1 and stub2.list_calls == 1,
        "L21: each planner's recall() call reaches only its own stub",
    )


# ---------------------------------------------------------------------------
# GoalPlannerError subclassing sanity (matches existing convention)
# ---------------------------------------------------------------------------
def scenario_error_type_convention() -> None:
    check(
        issubclass(GoalPlannerError, AgentError),
        "GoalPlannerError remains a subclass of Core.exceptions.AgentError",
    )


SCENARIOS = [
    scenario_planner_works_without_memory,
    scenario_planner_accepts_memory,
    scenario_invalid_memory_rejected,
    scenario_recall_no_memory,
    scenario_recall_reads_once,
    scenario_recall_returns_relevant,
    scenario_recall_excludes_irrelevant,
    scenario_recall_never_mutates_memory,
    scenario_recall_never_writes,
    scenario_recall_returns_fresh_copies,
    scenario_recall_real_memory_store,
    scenario_no_reflection_dependency,
    scenario_no_learning_loop_dependency,
    scenario_no_runtime_dependency,
    scenario_no_executor_dependency,
    scenario_no_event_dependency,
    scenario_no_scheduler_dependency,
    scenario_no_memory_or_composition_root_import,
    scenario_still_builds_workflow,
    scenario_no_regression_existing_methods,
    scenario_multiple_planner_instances,
    scenario_error_type_convention,
]


def main() -> int:
    for scenario in SCENARIOS:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001 -- a scenario crashing is a FAIL, not a suite abort
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__}: raised unexpectedly")
            print(f"  FAIL - {scenario.__name__}: raised unexpectedly")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"PHASE 4 SPRINT 42 PLANNER-MEMORY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)

    if _FAIL:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())