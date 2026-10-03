"""
Phase 4 Sprint 39 proof suite -- ``Reflector`` <-> ``EventBus``
integration.

Scope: dedicated regression suite for the Sprint 39 addition only --
``Reflector.attach(event_bus)`` subscribing this ``Reflector`` to an
``EventBus``'s ``"runtime.completed"``/``"runtime.failed"`` events
(published by ``WorkflowRuntime`` as of Sprint 38), and its private
handler invoking the exact same, already-locked ``reflect()`` --
tested in full by ``Tests/test_stage_l18_reflection.py`` -- exactly
once per event. ``EventBus``, ``Event``, ``WorkflowRuntime``,
``WorkflowSession``, ``WorkflowSessionManager``, ``WorkflowEngine``,
``WorkflowExecutionCoordinator``, and ``Executor`` are all untouched by
this sprint and are exercised here only as the real, unmodified
``EventBus``/``Event`` Sprint 39 actually depends on -- their own
already-locked behavior (covered by
``Tests/test_stage_l28_sprint22_event_bus.py`` and
``Tests/test_stage_l38_runtime_events.py``) is not re-verified beyond
what this integration itself needs. This suite never imports or
constructs ``WorkflowRuntime`` at all -- ``Reflector`` is proven here
against a bare ``EventBus`` publishing hand-built ``Event`` instances,
exactly mirroring the shape ``WorkflowRuntime.run()`` publishes,
without pulling in that whole collaborator graph.

This sprint introduces no new architectural layer and no new value
object: ``attach()`` is the only new public member on ``Reflector``,
and its private handler (``_on_runtime_event``) calls the existing
``reflect()`` -- there is no second reflection path anywhere.
``Reflector`` still never imports, constructs, or references
``WorkflowRuntime``, ``WorkflowEngine``, ``Executor``, ``Scheduler``,
``Memory``, or ``LearningLoop`` -- it only knows ``EventBus``/
``Event``.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L3x / Sprint 1x-39 proof suites: a global
pass/fail counter, plain fixtures (a real ``EventBus``, plus a thin
``Reflector`` subclass overriding only ``reflect()`` to count/record
calls -- the same recording-subclass technique already used
throughout this codebase), and a ``main()`` runner.

Invariant coverage:
    R1  -- attach() validation: a non-EventBus event_bus (None, wrong
           type) raises ReflectionError; a valid EventBus succeeds and
           returns None.
    R2  -- single subscription: after attach(bus), exactly one handler
           is registered for "runtime.completed" and exactly one for
           "runtime.failed" (bus._subscribers introspection).
    R3  -- duplicate attach prevention: calling attach() a second time
           with the same Reflector instance on the same EventBus
           raises EventBusError (EventBus's own duplicate-subscription
           guard -- attach() adds no separate mechanism).
    R4  -- attach() to two different EventBus instances with the same
           Reflector succeeds for both (no cross-bus state prevents
           it) -- proving Reflector stores nothing bus-specific.
    R5  -- runtime.completed handled: publishing a "runtime.completed"
           Event on an attached bus invokes reflect() exactly once.
    R6  -- runtime.failed handled: publishing a "runtime.failed" Event
           on an attached bus invokes reflect() exactly once.
    R7  -- unrelated events ignored: publishing any other event_name
           (including "runtime.started") on an attached bus never
           invokes reflect().
    R8  -- reflection logic executed exactly once: for N
           "runtime.completed"/"runtime.failed" publishes, reflect()
           is called exactly N times -- never 0, never 2+ per event.
    R9  -- no duplicated reflection logic: the handler calls reflect()
           with an empty tuple (the same, single reflect() contract --
           no second/parallel analysis path exists on Reflector).
    R10 -- payload extraction: the Event delivered to the handler
           carries the expected workflow_id/session_id/execution_id
           (and exception_type for failures) -- proving the handler
           genuinely receives the full Event, not a stripped-down
           substitute.
    R11 -- Reflector statelessness preserved: vars(reflector) == {}
           both before and after attach() and after handling several
           events (Sprint 39 introduces no instance state).
    R12 -- decoupling: Orchestration.reflection's module namespace
           never references WorkflowRuntime, WorkflowEngine, Executor,
           AutonomousScheduler, Memory (the class), or LearningLoop.
    R13 -- existing Reflector behavior unaffected: reflect() called
           directly (bypassing attach()/EventBus entirely) still
           behaves exactly as Sprint/Stage L18 locked it.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.event_bus import Event, EventBus, EventBusError
from Orchestration.memory import MemoryRecord
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


class RecordingReflector(Reflector):
    """A ``Reflector`` subclass that records every ``reflect()`` call
    (its exact input) without changing behavior at all -- ``reflect()``
    still calls ``super().reflect()`` and returns exactly what that
    returns.

    Used to prove ``reflect()`` is invoked exactly once per
    ``"runtime.completed"``/``"runtime.failed"`` event (R5, R6, R8),
    while still exercising the real, unmodified Sprint/Stage L18
    ``reflect()`` behavior underneath. Note: this subclass adds one
    instance attribute (``calls``) purely for test observation --
    Sprint 39's own ``attach()``/``_on_runtime_event()`` on the base
    ``Reflector`` class still store nothing on ``self`` (see R11,
    exercised against a plain ``Reflector()``).
    """

    def __init__(self) -> None:
        self.calls: List[Tuple] = []

    def reflect(self, records: Tuple) -> ReflectionRecord:
        self.calls.append(records)
        return super().reflect(records)


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


# ---------------------------------------------------------------------------
# R1 -- attach() validation
# ---------------------------------------------------------------------------
def scenario_attach_validation() -> None:
    reflector = Reflector()

    for bad in (None, "not-a-bus", 123, [], {}, object()):
        raised = False
        try:
            reflector.attach(bad)  # type: ignore[arg-type]
        except ReflectionError:
            raised = True
        check(
            raised,
            f"R1: attach({bad!r}) raises ReflectionError for a "
            f"non-EventBus argument",
        )

    bus = EventBus()
    result = Reflector().attach(bus)
    check(result is None, "R1: attach() with a valid EventBus returns None")


# ---------------------------------------------------------------------------
# R2 -- single subscription
# ---------------------------------------------------------------------------
def scenario_single_subscription() -> None:
    bus = EventBus()
    reflector = Reflector()
    reflector.attach(bus)

    check(
        len(bus._subscribers.get("runtime.completed", [])) == 1,
        "R2: exactly one handler registered for runtime.completed "
        "after attach()",
    )
    check(
        len(bus._subscribers.get("runtime.failed", [])) == 1,
        "R2: exactly one handler registered for runtime.failed after "
        "attach()",
    )
    check(
        bus._subscribers["runtime.completed"][0]
        == bus._subscribers["runtime.failed"][0],
        "R2: the same bound handler is used for both event names",
    )


# ---------------------------------------------------------------------------
# R3 -- duplicate attach prevention
# ---------------------------------------------------------------------------
def scenario_duplicate_attach_prevented() -> None:
    bus = EventBus()
    reflector = Reflector()
    reflector.attach(bus)

    raised = False
    try:
        reflector.attach(bus)
    except EventBusError:
        raised = True
    check(
        raised,
        "R3: attaching the same Reflector instance to the same "
        "EventBus a second time raises EventBusError (EventBus's own "
        "duplicate-subscription guard)",
    )


# ---------------------------------------------------------------------------
# R4 -- attach() to two different EventBus instances
# ---------------------------------------------------------------------------
def scenario_attach_to_multiple_buses() -> None:
    reflector = Reflector()
    bus1 = EventBus()
    bus2 = EventBus()

    raised = False
    try:
        reflector.attach(bus1)
        reflector.attach(bus2)
    except Exception:  # noqa: BLE001
        raised = True

    check(
        not raised,
        "R4: the same Reflector instance can attach() to two different "
        "EventBus instances without error",
    )
    check(
        len(bus1._subscribers.get("runtime.completed", [])) == 1
        and len(bus2._subscribers.get("runtime.completed", [])) == 1,
        "R4: both buses independently register the subscription",
    )


# ---------------------------------------------------------------------------
# R5 -- runtime.completed handled
# ---------------------------------------------------------------------------
def scenario_runtime_completed_handled() -> None:
    bus = EventBus()
    reflector = RecordingReflector()
    reflector.attach(bus)

    bus.publish(_completed_event())

    check(
        len(reflector.calls) == 1,
        "R5: publishing runtime.completed invokes reflect() exactly "
        "once",
    )
    check(
        reflector.calls[0] == (),
        "R5: reflect() is invoked with an empty tuple (no second "
        "reflection path/payload-to-MemoryRecord mapping invented)",
    )


# ---------------------------------------------------------------------------
# R6 -- runtime.failed handled
# ---------------------------------------------------------------------------
def scenario_runtime_failed_handled() -> None:
    bus = EventBus()
    reflector = RecordingReflector()
    reflector.attach(bus)

    bus.publish(_failed_event())

    check(
        len(reflector.calls) == 1,
        "R6: publishing runtime.failed invokes reflect() exactly once",
    )
    check(
        reflector.calls[0] == (),
        "R6: reflect() is invoked with an empty tuple on the failure "
        "path too",
    )


# ---------------------------------------------------------------------------
# R7 -- unrelated events ignored
# ---------------------------------------------------------------------------
def scenario_unrelated_events_ignored() -> None:
    bus = EventBus()
    reflector = RecordingReflector()
    reflector.attach(bus)

    for event_name in ("runtime.started", "scheduler.job_scheduled", "something.else"):
        bus.publish(Event(event_name=event_name, source="Other", payload={}))

    check(
        reflector.calls == [],
        "R7: unrelated events (including runtime.started) never "
        "invoke reflect()",
    )


# ---------------------------------------------------------------------------
# R8 -- reflection logic executed exactly once per event
# ---------------------------------------------------------------------------
def scenario_reflect_called_exactly_once_per_event() -> None:
    bus = EventBus()
    reflector = RecordingReflector()
    reflector.attach(bus)

    bus.publish(_completed_event())
    bus.publish(_failed_event())
    bus.publish(_completed_event())

    check(
        len(reflector.calls) == 3,
        f"R8: three published runtime events yield exactly three "
        f"reflect() calls; got {len(reflector.calls)}",
    )


# ---------------------------------------------------------------------------
# R9 -- no duplicated reflection logic
# ---------------------------------------------------------------------------
def scenario_no_duplicated_reflection_logic() -> None:
    import ast

    import Orchestration.reflection as module

    tree = ast.parse(Path(module.__file__).read_text())
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Reflector"
    )
    defined_methods = {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    check(
        defined_methods == {"attach", "_on_runtime_event", "reflect"},
        f"R9: Reflector defines exactly attach, _on_runtime_event, and "
        f"reflect -- Sprint 40 folds learning-loop attachment into "
        f"attach()'s existing signature instead of adding a new "
        f"method, so no second/parallel reflection method exists; "
        f"found {sorted(defined_methods)!r}",
    )

    handler_node = next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "_on_runtime_event"
    )
    calls_reflect = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "reflect"
        for node in ast.walk(handler_node)
    )
    check(
        calls_reflect,
        "R9: _on_runtime_event() calls .reflect(...) -- delegating to "
        "the single existing reflection method",
    )


# ---------------------------------------------------------------------------
# R10 -- payload extraction
# ---------------------------------------------------------------------------
def scenario_payload_extraction() -> None:
    bus = EventBus()
    observed: List[Event] = []

    class ObservingReflector(Reflector):
        def _on_runtime_event(self, event: Event) -> None:  # type: ignore[override]
            observed.append(event)
            super()._on_runtime_event(event)

    reflector = ObservingReflector()
    reflector.attach(bus)

    bus.publish(_completed_event(workflow_id="wf-42", session_id="sess-42", execution_id="exec-42"))
    bus.publish(
        _failed_event(
            workflow_id="wf-99",
            session_id="sess-99",
            execution_id="exec-99",
            exception_type="RuntimeError",
        )
    )

    check(len(observed) == 2, "R10: the handler receives both published events")
    check(
        observed[0].payload["workflow_id"] == "wf-42"
        and observed[0].payload["session_id"] == "sess-42"
        and observed[0].payload["execution_id"] == "exec-42",
        "R10: the runtime.completed Event's payload identifiers are "
        "delivered to the handler unchanged",
    )
    check(
        observed[1].payload["workflow_id"] == "wf-99"
        and observed[1].payload["exception_type"] == "RuntimeError",
        "R10: the runtime.failed Event's payload (including "
        "exception_type) is delivered to the handler unchanged",
    )


# ---------------------------------------------------------------------------
# R11 -- Reflector statelessness preserved
# ---------------------------------------------------------------------------
def scenario_statelessness_preserved() -> None:
    reflector = Reflector()
    check(
        vars(reflector) == {},
        "R11: a fresh Reflector holds no instance attributes",
    )

    bus = EventBus()
    reflector.attach(bus)
    check(
        vars(reflector) == {},
        "R11: attach() stores nothing on self -- vars() is still empty",
    )

    bus.publish(_completed_event())
    bus.publish(_failed_event())
    check(
        vars(reflector) == {},
        "R11: handling events leaves no instance state behind either",
    )


# ---------------------------------------------------------------------------
# R12 -- decoupling: forbidden references absent
# ---------------------------------------------------------------------------
def scenario_forbidden_references_absent() -> None:
    import Orchestration.reflection as module

    module_symbols = vars(module)
    for forbidden in (
        "WorkflowRuntime",
        "WorkflowEngine",
        "Executor",
        "AutonomousScheduler",
        "Memory",
        "LearningLoop",
    ):
        check(
            forbidden not in module_symbols,
            f"R12: Orchestration.reflection's module namespace does "
            f"not contain a {forbidden!r} symbol",
        )


# ---------------------------------------------------------------------------
# R13 -- existing Reflector behavior unaffected
# ---------------------------------------------------------------------------
def scenario_direct_reflect_unaffected() -> None:
    reflector = Reflector()
    records = (MemoryRecord(observation=_empty_observation_stub()),)

    record = reflector.reflect(records)
    check(
        record.source_record_count == 1,
        "R13: calling reflect() directly (bypassing attach()/EventBus "
        "entirely) still behaves exactly as before",
    )

    raised_type = None
    try:
        reflector.reflect([])  # type: ignore[arg-type]
    except ReflectionError:
        raised_type = ReflectionError
    check(
        raised_type is ReflectionError,
        "R13: reflect()'s existing type validation (non-tuple input) "
        "is unaffected by Sprint 39",
    )


def _empty_observation_stub():
    from Orchestration.observation import Observation

    return Observation(
        goal_metadata={},
        plan_step_names=(),
        steps=(),
        aggregated_outputs={},
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_attach_validation,
        scenario_single_subscription,
        scenario_duplicate_attach_prevented,
        scenario_attach_to_multiple_buses,
        scenario_runtime_completed_handled,
        scenario_runtime_failed_handled,
        scenario_unrelated_events_ignored,
        scenario_reflect_called_exactly_once_per_event,
        scenario_no_duplicated_reflection_logic,
        scenario_payload_extraction,
        scenario_statelessness_preserved,
        scenario_forbidden_references_absent,
        scenario_direct_reflect_unaffected,
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
        f"PHASE 4 SPRINT 39 REFLECTION EVENTS RESULTS: {_PASS} PASS / "
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