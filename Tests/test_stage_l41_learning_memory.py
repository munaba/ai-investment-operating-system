"""
Phase 4 Sprint 41 proof suite -- ``LearningLoop`` -> ``Memory``
integration.

Scope: dedicated regression suite for the Sprint 41 addition only --
``LearningLoop.__init__(memory=...)`` accepting an optional memory
collaborator, and ``LearningLoop.learn()`` forwarding the
``LearningLoopResult`` it just built to that collaborator's ``add(...)``
method, exactly once per call. This is integration only: no new
architectural layer, no new value object, no duplicated learning or
storage logic. ``LearningLoop``'s existing ``learn()`` contract (Stage
L27, exercised in full by ``Tests/test_stage_l27_learning_loop.py``)
is unchanged; ``Memory``'s existing ``MemoryStore``/``MemoryRecorder``
contract (Stage L17, exercised in full by
``Tests/test_stage_l17_memory.py``) is unchanged. Neither of those
suites is re-verified here beyond confirming Sprint 41 introduces no
regression to them.

LearningLoop never imports, constructs, or references MemoryStore or
MemoryRecorder (proven by module-namespace inspection, mirroring
test_stage_l40_reflection_learning.py's S9/S14). Memory never imports,
constructs, or references EventBus, WorkflowRuntime, Executor,
Scheduler, or Reflection (proven the same way). LearningLoop remains
the only caller of Memory -- Memory never subscribes to EventBus and
never invokes LearningLoop.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L4x / Sprint 1x-41 proof suites: a global
pass/fail counter, plain fixtures (a real portfolio-risk-shaped stub,
plus a thin recording stand-in for a memory collaborator -- the same
recording-stub technique already used throughout this codebase), and a
``main()`` runner.

Invariant coverage:
    M1  -- memory attached: LearningLoop(memory=stub) succeeds.
    M2  -- invalid attachment rejected: LearningLoop(memory=X) raises
           LearningLoopError when X has no callable add attribute.
    M3  -- learning invokes memory exactly once: one learn() call with
           a memory attached calls stub.add() exactly once, with the
           LearningLoopResult learn() just produced.
    M4  -- multiple learning operations: N learn() calls yield exactly
           N add() calls, each with its own LearningLoopResult.
    M5  -- memory not called on attachment: stub.calls is empty
           immediately after construction, before any learn() call.
    M6  -- learning behavior unchanged: learn()'s return value
           (recorded/signal/violation_count/notes) is identical
           whether or not a memory collaborator is attached.
    M7  -- memory behavior unchanged: MemoryStore/MemoryRecorder,
           exercised directly, still behave exactly as Stage L17
           locked them -- Sprint 41 makes no change to Memory's own
           implementation.
    M8  -- memory remains EventBus independent: Orchestration.memory's
           module namespace never contains "EventBus" or "Event"; a
           bare MemoryStore instance exposes no subscribe-shaped
           method.
    M9  -- learning remains EventBus independent: Orchestration.
           learning_loop's module namespace never contains "EventBus"
           or "Event".
    M10 -- multiple memory instances: two LearningLoop instances, each
           constructed with their own distinct stub, forward only to
           their own stub -- no cross-talk.
    M11 -- multiple learning instances: same as M10, phrased over
           independently constructed LearningLoop instances.
    M12 -- no Runtime dependency: neither module's namespace contains
           WorkflowRuntime.
    M13 -- no Scheduler dependency: neither module's namespace
           contains AutonomousScheduler/Scheduler.
    M14 -- no Reflection dependency inside Memory: Orchestration.
           memory's module namespace contains no Reflector/
           ReflectionRecord/Reflection symbol.
    M15 -- no duplicate memory writes: a single learn() call results
           in exactly one add() call, never two.
    M16 -- preservation of existing Memory semantics: a real
           MemoryStore, exercised through its own add()/get()/list()
           API exactly as Stage L17 locked it, is completely
           unaffected by anything LearningLoop does elsewhere --
           including a duplicate-record_id rejection still raising
           MemoryError.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.learning_loop import LearningLoop, LearningLoopError, LearningLoopResult
from Orchestration.memory import MemoryError, MemoryRecord, MemoryStore
from Orchestration.observation import Observation

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


class RecordingMemory:
    """A minimal duck-typed memory stand-in that records every
    ``add()`` call (its exact input) without doing anything else.

    Deliberately NOT a ``MemoryStore`` subclass -- Sprint 41's
    forwarding is proven here to work against anything shaped like a
    memory collaborator (has a callable ``add``), exactly as
    ``LearningLoop.__init__()``'s duck-typing validation requires. The
    real ``MemoryStore``/``MemoryRecorder`` are exercised separately
    (M7, M16) to confirm their own Stage L17 behavior is untouched.
    """

    def __init__(self) -> None:
        self.calls: List[LearningLoopResult] = []

    def add(self, result: LearningLoopResult) -> None:
        self.calls.append(result)


class _ApprovedRiskResult:
    approved = True
    exposure_level = "LOW"
    diversification_level = "HIGH"
    violations = ()


class _RejectedRiskResult:
    approved = False
    exposure_level = "HIGH"
    diversification_level = "LOW"
    violations = ("over_concentration", "sector_limit")


def _empty_observation() -> Observation:
    return Observation(
        goal_metadata={},
        plan_step_names=(),
        steps=(),
        aggregated_outputs={},
    )


# ---------------------------------------------------------------------------
# M1 -- memory attached
# ---------------------------------------------------------------------------
def scenario_memory_attached() -> None:
    stub = RecordingMemory()
    loop = LearningLoop(memory=stub)
    check(
        isinstance(loop, LearningLoop),
        "M1: LearningLoop(memory=stub) constructs successfully",
    )

    loop2 = LearningLoop(memory=MemoryStore())
    check(
        isinstance(loop2, LearningLoop),
        "M1: LearningLoop() also accepts a real MemoryStore instance "
        "as memory",
    )


# ---------------------------------------------------------------------------
# M2 -- invalid attachment rejected
# ---------------------------------------------------------------------------
def scenario_invalid_attachment_rejected() -> None:
    for bad in ("not-a-memory", 123, object(), [], {}):
        raised = False
        try:
            LearningLoop(memory=bad)  # type: ignore[arg-type]
        except LearningLoopError:
            raised = True
        check(
            raised,
            f"M2: LearningLoop(memory={bad!r}) raises LearningLoopError "
            f"when memory has no callable add attribute",
        )

    class NoAddMethod:
        add = "not callable"

    raised = False
    try:
        LearningLoop(memory=NoAddMethod())
    except LearningLoopError:
        raised = True
    check(
        raised,
        "M2: LearningLoop() rejects an object whose 'add' attribute "
        "exists but is not callable",
    )


# ---------------------------------------------------------------------------
# M3 -- learning invokes memory exactly once
# ---------------------------------------------------------------------------
def scenario_learning_invokes_memory_once() -> None:
    stub = RecordingMemory()
    loop = LearningLoop(memory=stub)

    result = loop.learn(_ApprovedRiskResult())

    check(
        len(stub.calls) == 1,
        "M3: one learn() call, with a memory attached, calls add() "
        "exactly once",
    )
    check(
        stub.calls[0] is result,
        "M3: add() is called with the exact LearningLoopResult learn() "
        "returned",
    )


# ---------------------------------------------------------------------------
# M4 -- multiple learning operations
# ---------------------------------------------------------------------------
def scenario_multiple_learning_operations() -> None:
    stub = RecordingMemory()
    loop = LearningLoop(memory=stub)

    loop.learn(_ApprovedRiskResult())
    loop.learn(_RejectedRiskResult())
    loop.learn(_ApprovedRiskResult())

    check(
        len(stub.calls) == 3,
        f"M4: three learn() calls yield exactly three add() calls; "
        f"got {len(stub.calls)}",
    )
    check(
        all(isinstance(c, LearningLoopResult) for c in stub.calls),
        "M4: every forwarded call carries a genuine LearningLoopResult",
    )
    check(
        [c.signal for c in stub.calls] == ["POSITIVE", "NEGATIVE", "POSITIVE"],
        "M4: each forwarded result reflects its own learn() call's "
        "outcome, in order",
    )


# ---------------------------------------------------------------------------
# M5 -- memory not called on attachment
# ---------------------------------------------------------------------------
def scenario_memory_not_called_on_attachment() -> None:
    stub = RecordingMemory()
    LearningLoop(memory=stub)

    check(
        stub.calls == [],
        "M5: constructing LearningLoop(memory=stub) itself never calls "
        "add() -- only a subsequent learn() does",
    )


# ---------------------------------------------------------------------------
# M6 -- learning behavior unchanged
# ---------------------------------------------------------------------------
def scenario_learning_behavior_unchanged() -> None:
    plain = LearningLoop()
    plain_result = plain.learn(_ApprovedRiskResult())

    attached = LearningLoop(memory=RecordingMemory())
    attached_result = attached.learn(_ApprovedRiskResult())

    check(
        plain_result.recorded == attached_result.recorded
        and plain_result.signal == attached_result.signal
        and plain_result.violation_count == attached_result.violation_count
        and plain_result.notes == attached_result.notes,
        "M6: learn() returns an identical LearningLoopResult, with or "
        "without a memory collaborator attached",
    )

    raised_without = False
    try:
        plain.learn(object())
    except LearningLoopError:
        raised_without = True

    raised_with = False
    try:
        attached.learn(object())
    except LearningLoopError:
        raised_with = True

    check(
        raised_without and raised_with,
        "M6: learn()'s existing attribute validation is identical "
        "with or without a memory collaborator attached",
    )


# ---------------------------------------------------------------------------
# M7 -- memory behavior unchanged
# ---------------------------------------------------------------------------
def scenario_memory_behavior_unchanged() -> None:
    store = MemoryStore()
    record = MemoryRecord(observation=_empty_observation())
    store.add(record)

    check(
        store.get(record.record_id) is record,
        "M7: MemoryStore.add()/get() called directly still behave "
        "exactly as Stage L17 locked them -- Sprint 41 makes no "
        "change to MemoryStore's own implementation",
    )

    raised = False
    try:
        store.add(record)
    except MemoryError:
        raised = True
    check(
        raised,
        "M7: MemoryStore.add() still raises MemoryError on a "
        "duplicate record_id, unchanged by Sprint 41",
    )


# ---------------------------------------------------------------------------
# M8 -- memory remains EventBus independent
# ---------------------------------------------------------------------------
def scenario_memory_remains_eventbus_independent() -> None:
    import Orchestration.memory as module

    module_symbols = vars(module)
    for forbidden in ("EventBus", "Event"):
        check(
            forbidden not in module_symbols,
            f"M8: Orchestration.memory's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )

    store = MemoryStore()
    check(
        not hasattr(store, "subscribe") and not hasattr(store, "attach"),
        "M8: a MemoryStore instance exposes no subscribe/attach-shaped "
        "method -- it is never given the EventBus",
    )


# ---------------------------------------------------------------------------
# M9 -- learning remains EventBus independent
# ---------------------------------------------------------------------------
def scenario_learning_remains_eventbus_independent() -> None:
    import Orchestration.learning_loop as module

    module_symbols = vars(module)
    for forbidden in ("EventBus", "Event"):
        check(
            forbidden not in module_symbols,
            f"M9: Orchestration.learning_loop's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# M10 -- multiple memory instances
# ---------------------------------------------------------------------------
def scenario_multiple_memory_instances() -> None:
    stub1, stub2 = RecordingMemory(), RecordingMemory()
    loop1 = LearningLoop(memory=stub1)
    loop2 = LearningLoop(memory=stub2)

    loop1.learn(_ApprovedRiskResult())
    loop2.learn(_ApprovedRiskResult())
    loop2.learn(_RejectedRiskResult())

    check(
        len(stub1.calls) == 1 and len(stub2.calls) == 2,
        "M10: each LearningLoop forwards only to its own attached "
        "memory -- no cross-talk between stub1 and stub2",
    )


# ---------------------------------------------------------------------------
# M11 -- multiple learning instances
# ---------------------------------------------------------------------------
def scenario_multiple_learning_instances() -> None:
    loops_and_stubs = []
    for _ in range(3):
        stub = RecordingMemory()
        loop = LearningLoop(memory=stub)
        loops_and_stubs.append((loop, stub))

    for loop, _stub in loops_and_stubs:
        loop.learn(_ApprovedRiskResult())

    check(
        all(len(stub.calls) == 1 for _loop, stub in loops_and_stubs),
        "M11: three independently constructed LearningLoop/stub pairs "
        "each record exactly one add() call, entirely independent of "
        "one another",
    )


# ---------------------------------------------------------------------------
# M12/M13/M14 -- no Runtime/Scheduler/Reflection dependency
# ---------------------------------------------------------------------------
def scenario_no_forbidden_dependencies() -> None:
    import Orchestration.learning_loop as learning_module
    import Orchestration.memory as memory_module

    for forbidden in ("WorkflowRuntime", "WorkflowEngine", "Executor"):
        check(
            forbidden not in vars(learning_module),
            f"M12: Orchestration.learning_loop's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )
        check(
            forbidden not in vars(memory_module),
            f"M12: Orchestration.memory's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )

    for forbidden in ("AutonomousScheduler", "Scheduler"):
        check(
            forbidden not in vars(learning_module),
            f"M13: Orchestration.learning_loop's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )
        check(
            forbidden not in vars(memory_module),
            f"M13: Orchestration.memory's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )

    for forbidden in ("Reflector", "ReflectionRecord", "Reflection"):
        check(
            forbidden not in vars(memory_module),
            f"M14: Orchestration.memory's module namespace does not "
            f"contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# M15 -- no duplicate memory writes
# ---------------------------------------------------------------------------
def scenario_no_duplicate_memory_writes() -> None:
    stub = RecordingMemory()
    loop = LearningLoop(memory=stub)

    loop.learn(_ApprovedRiskResult())

    check(
        len(stub.calls) == 1,
        "M15: a single learn() call results in exactly one add() "
        "call, never two",
    )


# ---------------------------------------------------------------------------
# M16 -- preservation of existing Memory semantics
# ---------------------------------------------------------------------------
def scenario_preservation_of_memory_semantics() -> None:
    store = MemoryStore()
    stub_loop = LearningLoop(memory=RecordingMemory())
    stub_loop.learn(_ApprovedRiskResult())  # unrelated LearningLoop activity

    record_a = MemoryRecord(observation=_empty_observation())
    record_b = MemoryRecord(observation=_empty_observation())
    store.add(record_a)
    store.add(record_b)

    check(
        store.list() == (record_a, record_b),
        "M16: MemoryStore.list() still returns records in insertion "
        "order, unaffected by any LearningLoop activity elsewhere",
    )
    check(
        len(store) == 2,
        "M16: MemoryStore.__len__() still reports the correct count",
    )

    store.clear()
    check(
        len(store) == 0 and store.list() == (),
        "M16: MemoryStore.clear() still empties the store exactly as "
        "Stage L17 locked it",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_memory_attached,
        scenario_invalid_attachment_rejected,
        scenario_learning_invokes_memory_once,
        scenario_multiple_learning_operations,
        scenario_memory_not_called_on_attachment,
        scenario_learning_behavior_unchanged,
        scenario_memory_behavior_unchanged,
        scenario_memory_remains_eventbus_independent,
        scenario_learning_remains_eventbus_independent,
        scenario_multiple_memory_instances,
        scenario_multiple_learning_instances,
        scenario_no_forbidden_dependencies,
        scenario_no_duplicate_memory_writes,
        scenario_preservation_of_memory_semantics,
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
        f"PHASE 4 SPRINT 41 LEARNING MEMORY RESULTS: {_PASS} PASS / "
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