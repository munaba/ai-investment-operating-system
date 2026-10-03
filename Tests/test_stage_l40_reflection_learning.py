"""
Phase 4 Sprint 40 proof suite -- ``Reflector`` -> ``LearningLoop``
integration.

Scope: dedicated regression suite for the Sprint 40 addition only --
``Reflector.attach(event_bus, learning_loop=...)`` accepting an
optional learning-loop collaborator, and ``Reflector.reflect()``
forwarding the ``ReflectionRecord`` it just built to that
collaborator's ``learn(...)`` method, exactly once per call. This is
integration only: no new architectural layer, no new value object, no
duplicated reflection or learning logic. ``Reflector`` still exposes
exactly the same two public members (``attach``, ``reflect``) locked
by Stage L18 and exercised in full by
``Tests/test_stage_l18_reflection.py`` and
``Tests/test_stage_l39_reflection_events.py`` -- this suite does not
re-verify that base behavior beyond what the Sprint 40 wiring itself
needs. ``LearningLoop`` is exercised here only through a
duck-typed-collaborator lens (via ``learn(...)``); its own existing
behavior is covered in full by ``Tests/test_stage_l27_learning_loop.py``
and is not re-verified here beyond confirming Sprint 40 introduces no
change to it.

Reflector never imports, constructs, or references LearningLoop
(proven by module-namespace inspection, mirroring
test_stage_l39_reflection_events.py's R12). LearningLoop never
imports, constructs, or references EventBus, WorkflowRuntime,
Executor, Scheduler, or Memory (proven the same way). Reflector
remains the only EventBus subscriber -- LearningLoop is never given
the bus and never subscribes to it.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L3x / Sprint 1x-40 proof suites: a global
pass/fail counter, plain fixtures (a real ``EventBus``, plus a thin
recording stand-in for a learning loop -- the same recording-stub
technique already used throughout this codebase), and a ``main()``
runner.

Invariant coverage:
    S1  -- learning loop attached: attach(bus, learning_loop=stub)
           succeeds and returns None.
    S2  -- invalid attachment rejected: attach(bus, learning_loop=X)
           raises ReflectionError when X has no callable learn
           attribute (None already covered by S1 as "no loop given").
    S3  -- reflection invokes learning exactly once: publishing one
           runtime event with a learning loop attached calls
           stub.learn() exactly once, with the ReflectionRecord
           reflect() just produced.
    S4  -- multiple reflections: N published runtime events yield
           exactly N learn() calls, each with its own
           ReflectionRecord.
    S5  -- learning not called on attach: attach() itself never calls
           learn() -- stub.calls is empty immediately after attach(),
           before any event is published.
    S6  -- reflection behavior unchanged: reflect()'s return value
           (source_record_count/reflected_at) is identical whether or
           not a learning loop is attached.
    S7  -- learning behavior unchanged: LearningLoop.learn() itself,
           called directly with a portfolio-risk-shaped object, still
           behaves exactly as Stage L27 locked it -- Sprint 40 makes
           no change to LearningLoop's own implementation.
    S8  -- reflection remains EventBus subscriber: after attach(bus,
           learning_loop=stub), the bus still shows exactly one
           subscriber for runtime.completed/runtime.failed, and it is
           the Reflector's handler -- not the learning loop.
    S9  -- learning remains EventBus independent: Orchestration.
           learning_loop's module namespace never contains "EventBus"
           or "Event"; a bare LearningLoop instance is never given the
           bus and exposes no subscribe-shaped method.
    S10 -- multiple learning loop instances: two Reflector instances,
           each attach()ed with its own distinct stub, forward only to
           their own stub -- no cross-talk.
    S11 -- multiple reflection instances: same as S10, phrased over
           independently constructed Reflector instances publishing
           on independent buses.
    S12 -- no Runtime dependency: neither module's namespace contains
           WorkflowRuntime.
    S13 -- no Scheduler dependency: neither module's namespace
           contains AutonomousScheduler/Scheduler.
    S14 -- no Memory dependency inside LearningLoop: Orchestration.
           learning_loop's module namespace contains no Memory symbol
           (Reflector's own Memory-independence is already covered by
           test_stage_l39_reflection_events.py's R12).
    S15 -- no duplicate learning invocation: a single published event
           calls learn() exactly once, never twice (e.g. not once from
           attach() and again from the handler).
    S16 -- reflect() called directly (bypassing EventBus/attach()
           entirely) with a learning loop pre-attached still forwards
           to it exactly once -- proving the forwarding lives in
           reflect() itself, not only in the event handler path.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.event_bus import Event, EventBus
from Orchestration.learning_loop import LearningLoop, LearningLoopResult
from Orchestration.reflection import ReflectionError, ReflectionRecord, Reflector

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


class RecordingLearningLoop:
    """A minimal duck-typed learning-loop stand-in that records every
    ``learn()`` call (its exact input) without doing anything else.

    Deliberately NOT a ``LearningLoop`` subclass -- Sprint 40's
    forwarding is proven here to work against anything shaped like a
    learning loop (has a callable ``learn``), exactly as
    ``Reflector.attach()``'s duck-typing validation requires. The real
    ``LearningLoop`` itself is exercised separately (S7) to confirm
    its own Stage L27 behavior is untouched.
    """

    def __init__(self) -> None:
        self.calls: List[ReflectionRecord] = []

    def learn(self, reflection_record: ReflectionRecord) -> None:
        self.calls.append(reflection_record)


def _completed_event(**payload_overrides) -> Event:
    payload = {
        "workflow_id": "wf-1",
        "session_id": "sess-1",
        "execution_id": "exec-1",
    }
    payload.update(payload_overrides)
    return Event(event_name="runtime.completed", source="WorkflowRuntime", payload=payload)


def _failed_event(**payload_overrides) -> Event:
    payload = {
        "workflow_id": "wf-1",
        "session_id": "sess-1",
        "execution_id": "exec-1",
        "exception_type": "ValueError",
    }
    payload.update(payload_overrides)
    return Event(event_name="runtime.failed", source="WorkflowRuntime", payload=payload)


class _ApprovedRiskResult:
    approved = True
    exposure_level = "LOW"
    diversification_level = "HIGH"
    violations = ()


# ---------------------------------------------------------------------------
# S1 -- learning loop attached
# ---------------------------------------------------------------------------
def scenario_learning_loop_attached() -> None:
    bus = EventBus()
    reflector = Reflector()
    stub = RecordingLearningLoop()

    result = reflector.attach(bus, learning_loop=stub)
    check(result is None, "S1: attach(bus, learning_loop=stub) returns None")

    result2 = Reflector().attach(EventBus(), learning_loop=LearningLoop())
    check(
        result2 is None,
        "S1: attach() also accepts a real LearningLoop instance as "
        "learning_loop",
    )


# ---------------------------------------------------------------------------
# S2 -- invalid attachment rejected
# ---------------------------------------------------------------------------
def scenario_invalid_attachment_rejected() -> None:
    for bad in ("not-a-loop", 123, object(), [], {}):
        bus = EventBus()
        reflector = Reflector()
        raised = False
        try:
            reflector.attach(bus, learning_loop=bad)  # type: ignore[arg-type]
        except ReflectionError:
            raised = True
        check(
            raised,
            f"S2: attach(bus, learning_loop={bad!r}) raises "
            f"ReflectionError when learning_loop has no callable "
            f"learn attribute",
        )

    class NoLearnMethod:
        learn = "not callable"

    bus = EventBus()
    raised = False
    try:
        Reflector().attach(bus, learning_loop=NoLearnMethod())
    except ReflectionError:
        raised = True
    check(
        raised,
        "S2: attach() rejects an object whose 'learn' attribute "
        "exists but is not callable",
    )


# ---------------------------------------------------------------------------
# S3 -- reflection invokes learning exactly once
# ---------------------------------------------------------------------------
def scenario_reflection_invokes_learning_once() -> None:
    bus = EventBus()
    reflector = Reflector()
    stub = RecordingLearningLoop()
    reflector.attach(bus, learning_loop=stub)

    bus.publish(_completed_event())

    check(
        len(stub.calls) == 1,
        "S3: publishing one runtime event calls learn() exactly once",
    )
    check(
        isinstance(stub.calls[0], ReflectionRecord),
        "S3: learn() is called with the ReflectionRecord reflect() "
        "produced",
    )
    check(
        stub.calls[0].source_record_count == 0,
        "S3: the forwarded ReflectionRecord matches what reflect(()) "
        "actually returns for an event-driven (empty-batch) reflection",
    )


# ---------------------------------------------------------------------------
# S4 -- multiple reflections
# ---------------------------------------------------------------------------
def scenario_multiple_reflections() -> None:
    bus = EventBus()
    reflector = Reflector()
    stub = RecordingLearningLoop()
    reflector.attach(bus, learning_loop=stub)

    bus.publish(_completed_event())
    bus.publish(_failed_event())
    bus.publish(_completed_event())

    check(
        len(stub.calls) == 3,
        f"S4: three published runtime events yield exactly three "
        f"learn() calls; got {len(stub.calls)}",
    )
    check(
        all(isinstance(c, ReflectionRecord) for c in stub.calls),
        "S4: every forwarded call carries a genuine ReflectionRecord",
    )


# ---------------------------------------------------------------------------
# S5 -- learning not called on attach
# ---------------------------------------------------------------------------
def scenario_learning_not_called_on_attach() -> None:
    bus = EventBus()
    reflector = Reflector()
    stub = RecordingLearningLoop()

    reflector.attach(bus, learning_loop=stub)

    check(
        stub.calls == [],
        "S5: attach() itself never calls learn() -- only a subsequent "
        "reflection does",
    )


# ---------------------------------------------------------------------------
# S6 -- reflection behavior unchanged
# ---------------------------------------------------------------------------
def scenario_reflection_behavior_unchanged() -> None:
    plain = Reflector()
    plain_result = plain.reflect(())

    attached = Reflector()
    attached.attach(EventBus(), learning_loop=RecordingLearningLoop())
    attached_result = attached.reflect(())

    check(
        plain_result.source_record_count == attached_result.source_record_count == 0,
        "S6: reflect(()) returns source_record_count=0 identically, "
        "with or without a learning loop attached",
    )

    raised_without = False
    try:
        plain.reflect([])  # type: ignore[arg-type]
    except ReflectionError:
        raised_without = True

    raised_with = False
    try:
        attached.reflect([])  # type: ignore[arg-type]
    except ReflectionError:
        raised_with = True

    check(
        raised_without and raised_with,
        "S6: reflect()'s existing type validation (non-tuple input) "
        "is identical with or without a learning loop attached",
    )


# ---------------------------------------------------------------------------
# S7 -- learning behavior unchanged
# ---------------------------------------------------------------------------
def scenario_learning_behavior_unchanged() -> None:
    loop = LearningLoop()
    result = loop.learn(_ApprovedRiskResult())

    check(
        isinstance(result, LearningLoopResult)
        and result.recorded is True
        and result.signal == "POSITIVE"
        and result.violation_count == 0,
        "S7: LearningLoop.learn() called directly with a "
        "portfolio-risk-shaped object behaves exactly as Stage L27 "
        "locked it -- Sprint 40 makes no change to LearningLoop's own "
        "implementation",
    )


# ---------------------------------------------------------------------------
# S8 -- reflection remains EventBus subscriber
# ---------------------------------------------------------------------------
def scenario_reflection_remains_sole_subscriber() -> None:
    bus = EventBus()
    reflector = Reflector()
    stub = RecordingLearningLoop()
    reflector.attach(bus, learning_loop=stub)

    check(
        len(bus._subscribers.get("runtime.completed", [])) == 1
        and len(bus._subscribers.get("runtime.failed", [])) == 1,
        "S8: exactly one subscriber remains registered per event name "
        "after attach(bus, learning_loop=stub)",
    )
    check(
        bus._subscribers["runtime.completed"][0] == reflector._on_runtime_event,
        "S8: the registered subscriber is the Reflector's own handler "
        "-- not the learning loop",
    )
    check(
        not hasattr(stub, "_subscribers")
        and stub not in bus._subscribers.get("runtime.completed", []),
        "S8: the learning loop stub itself never becomes an EventBus "
        "subscriber",
    )


# ---------------------------------------------------------------------------
# S9 -- learning remains EventBus independent
# ---------------------------------------------------------------------------
def scenario_learning_remains_eventbus_independent() -> None:
    import Orchestration.learning_loop as module

    module_symbols = vars(module)
    for forbidden in ("EventBus", "Event"):
        check(
            forbidden not in module_symbols,
            f"S9: Orchestration.learning_loop's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )

    loop = LearningLoop()
    check(
        not hasattr(loop, "subscribe") and not hasattr(loop, "attach"),
        "S9: a LearningLoop instance exposes no subscribe/attach-shaped "
        "method -- it is never given the EventBus",
    )


# ---------------------------------------------------------------------------
# S10 -- multiple learning loop instances
# ---------------------------------------------------------------------------
def scenario_multiple_learning_loop_instances() -> None:
    bus1, bus2 = EventBus(), EventBus()
    reflector1, reflector2 = Reflector(), Reflector()
    stub1, stub2 = RecordingLearningLoop(), RecordingLearningLoop()

    reflector1.attach(bus1, learning_loop=stub1)
    reflector2.attach(bus2, learning_loop=stub2)

    bus1.publish(_completed_event())
    bus2.publish(_completed_event())
    bus2.publish(_failed_event())

    check(
        len(stub1.calls) == 1 and len(stub2.calls) == 2,
        "S10: each Reflector forwards only to its own attached "
        "learning loop -- no cross-talk between stub1 and stub2",
    )


# ---------------------------------------------------------------------------
# S11 -- multiple reflection instances
# ---------------------------------------------------------------------------
def scenario_multiple_reflection_instances() -> None:
    reflectors_and_stubs = []
    for _ in range(3):
        bus = EventBus()
        reflector = Reflector()
        stub = RecordingLearningLoop()
        reflector.attach(bus, learning_loop=stub)
        reflectors_and_stubs.append((bus, stub))

    for bus, _stub in reflectors_and_stubs:
        bus.publish(_completed_event())

    check(
        all(len(stub.calls) == 1 for _bus, stub in reflectors_and_stubs),
        "S11: three independently constructed Reflector/bus/stub "
        "triples each record exactly one learn() call, entirely "
        "independent of one another",
    )


# ---------------------------------------------------------------------------
# S12/S13/S14 -- no Runtime/Scheduler/Memory dependency
# ---------------------------------------------------------------------------
def scenario_no_forbidden_dependencies() -> None:
    import Orchestration.learning_loop as learning_module
    import Orchestration.reflection as reflection_module

    for forbidden in ("WorkflowRuntime", "WorkflowEngine", "Executor"):
        check(
            forbidden not in vars(learning_module),
            f"S12: Orchestration.learning_loop's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )
        check(
            forbidden not in vars(reflection_module),
            f"S12: Orchestration.reflection's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )

    for forbidden in ("AutonomousScheduler", "Scheduler"):
        check(
            forbidden not in vars(learning_module),
            f"S13: Orchestration.learning_loop's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )
        check(
            forbidden not in vars(reflection_module),
            f"S13: Orchestration.reflection's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )

    check(
        "Memory" not in vars(learning_module),
        "S14: Orchestration.learning_loop's module namespace does not "
        "contain a 'Memory' symbol",
    )


# ---------------------------------------------------------------------------
# S15 -- no duplicate learning invocation
# ---------------------------------------------------------------------------
def scenario_no_duplicate_learning_invocation() -> None:
    bus = EventBus()
    reflector = Reflector()
    stub = RecordingLearningLoop()
    reflector.attach(bus, learning_loop=stub)

    bus.publish(_completed_event())

    check(
        len(stub.calls) == 1,
        "S15: a single published event results in exactly one "
        "learn() call, never two (e.g. not once from attach() plus "
        "once from the handler)",
    )


# ---------------------------------------------------------------------------
# S16 -- direct reflect() call also forwards
# ---------------------------------------------------------------------------
def scenario_direct_reflect_also_forwards() -> None:
    reflector = Reflector()
    stub = RecordingLearningLoop()
    reflector.attach(EventBus(), learning_loop=stub)

    record = reflector.reflect(())

    check(
        len(stub.calls) == 1 and stub.calls[0] is record,
        "S16: calling reflect() directly (bypassing EventBus/publish "
        "entirely) still forwards its own returned ReflectionRecord "
        "to the attached learning loop exactly once",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_learning_loop_attached,
        scenario_invalid_attachment_rejected,
        scenario_reflection_invokes_learning_once,
        scenario_multiple_reflections,
        scenario_learning_not_called_on_attach,
        scenario_reflection_behavior_unchanged,
        scenario_learning_behavior_unchanged,
        scenario_reflection_remains_sole_subscriber,
        scenario_learning_remains_eventbus_independent,
        scenario_multiple_learning_loop_instances,
        scenario_multiple_reflection_instances,
        scenario_no_forbidden_dependencies,
        scenario_no_duplicate_learning_invocation,
        scenario_direct_reflect_also_forwards,
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
        f"PHASE 4 SPRINT 40 REFLECTION LEARNING RESULTS: {_PASS} PASS / "
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