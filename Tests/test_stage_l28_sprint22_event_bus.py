"""
Phase 3 Sprint 22B proof suite -- ``Event`` / ``EventBus`` (the Event
Bus designed in Sprint 22A).

Scope: dedicated regression suite for the two new types introduced in
Sprint 22B, ``Orchestration.event_bus.Event`` and
``Orchestration.event_bus.EventBus``. Neither type is wired into
``AutonomousScheduler``, ``AutonomousHost``, ``AutonomousAgent``, or
``RuntimeAnalysisPipeline`` yet -- this suite exercises the bus
entirely in isolation, with plain fake handlers standing in for future
subscribers.

No real ``RuntimeAnalysisPipeline``, ``GoalPlanner``, or any other
existing Orchestration component is built here -- this suite has no
dependency on any of that.

No threading, no asyncio, no timers, no sleep, no persistence -- all
explicitly out of scope for Sprint 22B and never exercised or required
by this suite.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    E1  -- Event construction succeeds with required fields.
    E2  -- event_id is a non-empty str and is unique across instances.
    E3  -- timestamp is a timezone-aware UTC datetime, generated at
           construction time.
    E4  -- Event is frozen -- reassigning any field raises.
    E5  -- payload is immutable after construction -- mutating the
           returned mapping raises, and mutating the original dict
           passed in has no effect on the already-constructed event.
    E6  -- subscribe() with an invalid event_name raises
           EventBusError.
    E7  -- subscribe() with a non-callable handler raises
           EventBusError.
    E8  -- subscribe() rejects a duplicate (event_name, handler) pair.
    E9  -- unsubscribe() removes exactly the targeted subscription.
    E10 -- unsubscribe() with an unknown handler raises
           EventBusError, including when event_name was never
           subscribed to at all.
    E11 -- once() invokes its handler exactly once across multiple
           publish() calls, and auto-unsubscribes after the first
           successful invocation.
    E12 -- once() does not unsubscribe if the wrapped handler raises;
           the subscription remains eligible to fire again.
    E13 -- publish() delivers to subscribers in strict FIFO
           (subscribe-order) sequence.
    E14 -- publish() delivers to every subscriber of an event_name,
           not just the first.
    E15 -- publish() with no subscribers for that event_name is a
           safe no-op.
    E16 -- a subscriber exception propagates out of publish()
           unchanged, and stops delivery to subscribers still to come
           for that publish() call.
    E17 -- two different event_names are completely isolated from one
           another (subscribing/publishing one never touches the
           other).
    E18 -- repeated publish() calls each independently re-deliver to
           still-subscribed handlers (no one-shot-by-default
           behavior for plain subscribe()).
    E19 -- a fresh EventBus starts with no subscriptions at all.
    E20 -- two independent EventBus instances never share
           subscription state.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.event_bus import Event, EventBus, EventBusError

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


def _make_event(name: str = "scheduler.job_scheduled", **payload) -> Event:
    return Event(event_name=name, source="TestSource", payload=dict(payload))


class _RecordingHandler:
    """A callable that records every Event it was invoked with, in
    invocation order."""

    def __init__(self) -> None:
        self.calls: List[Event] = []

    def __call__(self, event: Event) -> None:
        self.calls.append(event)


class _RaisingHandler:
    """A callable that always raises when invoked."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.call_count = 0

    def __call__(self, event: Event) -> None:
        self.call_count += 1
        raise self._exc


# ---------------------------------------------------------------------------
# E1 -- Event construction succeeds with required fields
# ---------------------------------------------------------------------------
def scenario_event_construction_succeeds() -> None:
    event = Event(
        event_name="scheduler.job_scheduled",
        source="AutonomousScheduler",
        payload={"job_id": "abc-123"},
    )

    check(
        event.event_name == "scheduler.job_scheduled"
        and event.source == "AutonomousScheduler"
        and event.payload == {"job_id": "abc-123"},
        "E1: Event construction succeeds and exposes event_name, "
        "source, and payload exactly as given",
    )
    check(
        isinstance(event.event_id, str) and event.event_id != "",
        "E1: Event auto-generates a non-empty str event_id",
    )
    check(
        isinstance(event.timestamp, datetime),
        "E1: Event auto-generates a datetime timestamp",
    )


# ---------------------------------------------------------------------------
# E2 -- event_id is unique across instances
# ---------------------------------------------------------------------------
def scenario_event_id_is_unique() -> None:
    events = [_make_event() for _ in range(5)]
    ids = [event.event_id for event in events]

    check(
        len(set(ids)) == len(ids),
        "E2: event_id is unique across multiple Event instances, even "
        "with identical event_name/source/payload",
    )


# ---------------------------------------------------------------------------
# E3 -- timestamp is a timezone-aware UTC datetime
# ---------------------------------------------------------------------------
def scenario_timestamp_is_utc_and_recent() -> None:
    before = datetime.now(timezone.utc)
    event = _make_event()
    after = datetime.now(timezone.utc)

    check(
        event.timestamp.tzinfo is not None
        and event.timestamp.utcoffset() == timezone.utc.utcoffset(None),
        "E3: Event.timestamp is timezone-aware and in UTC",
    )
    check(
        before <= event.timestamp <= after,
        "E3: Event.timestamp reflects the moment of construction",
    )


# ---------------------------------------------------------------------------
# E4 -- Event is frozen (immutable dataclass)
# ---------------------------------------------------------------------------
def scenario_event_is_frozen() -> None:
    event = _make_event()

    for field_name, value in (
        ("event_name", "something_else"),
        ("source", "SomeoneElse"),
        ("event_id", "forged-id"),
    ):
        try:
            setattr(event, field_name, value)
            check(
                False,
                f"E4: reassigning Event.{field_name} raises "
                f"(frozen dataclass)",
            )
        except (AttributeError, TypeError):
            check(
                True,
                f"E4: reassigning Event.{field_name} raises "
                f"(frozen dataclass)",
            )


# ---------------------------------------------------------------------------
# E5 -- payload is immutable after construction
# ---------------------------------------------------------------------------
def scenario_payload_is_immutable() -> None:
    original = {"job_id": "abc-123", "iterations": 3}
    event = Event(event_name="scheduler.job_scheduled", source="Test", payload=original)

    check(
        isinstance(event.payload, MappingProxyType),
        "E5: Event.payload is stored as an immutable MappingProxyType",
    )

    try:
        event.payload["job_id"] = "tampered"
        check(
            False,
            "E5: mutating event.payload directly raises (payload is "
            "read-only)",
        )
    except TypeError:
        check(
            True,
            "E5: mutating event.payload directly raises (payload is "
            "read-only)",
        )

    original["job_id"] = "mutated-after-construction"
    check(
        event.payload["job_id"] == "abc-123",
        "E5: mutating the original dict after construction has no "
        "effect on the already-constructed event's payload",
    )


# ---------------------------------------------------------------------------
# E6 -- subscribe() with an invalid event_name raises
# ---------------------------------------------------------------------------
def scenario_subscribe_invalid_event_name_raises() -> None:
    bus = EventBus()
    handler = _RecordingHandler()

    for bad_name in ("", "   ", None, 123, [1]):
        try:
            bus.subscribe(bad_name, handler)
            check(
                False,
                f"E6: subscribe({bad_name!r}, handler) raises "
                f"EventBusError for an invalid event_name",
            )
        except EventBusError:
            check(
                True,
                f"E6: subscribe({bad_name!r}, handler) raises "
                f"EventBusError for an invalid event_name",
            )


# ---------------------------------------------------------------------------
# E7 -- subscribe() with a non-callable handler raises
# ---------------------------------------------------------------------------
def scenario_subscribe_non_callable_handler_raises() -> None:
    bus = EventBus()

    for bad_handler in (None, "not-callable", 42, [1, 2, 3]):
        try:
            bus.subscribe("scheduler.job_scheduled", bad_handler)
            check(
                False,
                f"E7: subscribe(event_name, {bad_handler!r}) raises "
                f"EventBusError for a non-callable handler",
            )
        except EventBusError:
            check(
                True,
                f"E7: subscribe(event_name, {bad_handler!r}) raises "
                f"EventBusError for a non-callable handler",
            )


# ---------------------------------------------------------------------------
# E8 -- subscribe() rejects a duplicate (event_name, handler) pair
# ---------------------------------------------------------------------------
def scenario_subscribe_rejects_duplicate() -> None:
    bus = EventBus()
    handler = _RecordingHandler()

    bus.subscribe("scheduler.job_scheduled", handler)

    try:
        bus.subscribe("scheduler.job_scheduled", handler)
        check(
            False,
            "E8: subscribing the exact same handler to the same "
            "event_name twice raises EventBusError",
        )
    except EventBusError:
        check(
            True,
            "E8: subscribing the exact same handler to the same "
            "event_name twice raises EventBusError",
        )

    # The same handler on a *different* event_name is not a duplicate.
    try:
        bus.subscribe("scheduler.job_cancelled", handler)
        check(
            True,
            "E8: the same handler subscribed to a different event_name "
            "is not treated as a duplicate",
        )
    except EventBusError:
        check(
            False,
            "E8: the same handler subscribed to a different event_name "
            "is not treated as a duplicate",
        )


# ---------------------------------------------------------------------------
# E9 -- unsubscribe() removes exactly the targeted subscription
# ---------------------------------------------------------------------------
def scenario_unsubscribe_removes_targeted_subscription() -> None:
    bus = EventBus()
    handler_a = _RecordingHandler()
    handler_b = _RecordingHandler()

    bus.subscribe("scheduler.job_scheduled", handler_a)
    bus.subscribe("scheduler.job_scheduled", handler_b)

    bus.unsubscribe("scheduler.job_scheduled", handler_a)
    bus.publish(_make_event())

    check(
        len(handler_a.calls) == 0 and len(handler_b.calls) == 1,
        "E9: unsubscribe() removes exactly the targeted handler; the "
        "remaining handler still receives publish()",
    )


# ---------------------------------------------------------------------------
# E10 -- unsubscribe() with an unknown handler raises
# ---------------------------------------------------------------------------
def scenario_unsubscribe_unknown_handler_raises() -> None:
    bus = EventBus()
    handler = _RecordingHandler()
    stranger = _RecordingHandler()

    # event_name never subscribed to at all.
    try:
        bus.unsubscribe("scheduler.job_scheduled", handler)
        check(
            False,
            "E10: unsubscribe() on an event_name with no subscribers at "
            "all raises EventBusError",
        )
    except EventBusError:
        check(
            True,
            "E10: unsubscribe() on an event_name with no subscribers at "
            "all raises EventBusError",
        )

    # event_name has subscribers, but not this handler.
    bus.subscribe("scheduler.job_scheduled", handler)
    try:
        bus.unsubscribe("scheduler.job_scheduled", stranger)
        check(
            False,
            "E10: unsubscribe() with a handler that was never "
            "subscribed to this event_name raises EventBusError",
        )
    except EventBusError:
        check(
            True,
            "E10: unsubscribe() with a handler that was never "
            "subscribed to this event_name raises EventBusError",
        )


# ---------------------------------------------------------------------------
# E11 -- once() fires exactly once and auto-unsubscribes
# ---------------------------------------------------------------------------
def scenario_once_fires_exactly_once() -> None:
    bus = EventBus()
    handler = _RecordingHandler()

    bus.once("scheduler.job_scheduled", handler)

    bus.publish(_make_event())
    bus.publish(_make_event())
    bus.publish(_make_event())

    check(
        len(handler.calls) == 1,
        "E11: once() invokes its handler exactly once across multiple "
        "publish() calls",
    )


# ---------------------------------------------------------------------------
# E12 -- once() does not unsubscribe if the wrapped handler raises
# ---------------------------------------------------------------------------
def scenario_once_does_not_unsubscribe_on_raise() -> None:
    bus = EventBus()
    boom = ValueError("boom")
    handler = _RaisingHandler(boom)

    bus.once("scheduler.job_scheduled", handler)

    try:
        bus.publish(_make_event())
        check(
            False,
            "E12: publish() propagates the once()-wrapped handler's "
            "exception unchanged",
        )
    except ValueError as exc:
        check(
            exc is boom,
            "E12: publish() propagates the once()-wrapped handler's "
            "exception unchanged",
        )

    check(
        handler.call_count == 1,
        "E12: the once()-wrapped handler was invoked exactly once so far",
    )

    # Since the first invocation raised, the subscription must still be
    # active -- publishing again should invoke it a second time.
    try:
        bus.publish(_make_event())
    except ValueError:
        pass

    check(
        handler.call_count == 2,
        "E12: once() does not auto-unsubscribe after a raising "
        "invocation -- the handler remains eligible to fire again",
    )


# ---------------------------------------------------------------------------
# E13 -- publish() delivers in strict FIFO (subscribe-order) sequence
# ---------------------------------------------------------------------------
def scenario_publish_delivers_in_fifo_order() -> None:
    bus = EventBus()
    order: List[str] = []

    def handler_a(event: Event) -> None:
        order.append("a")

    def handler_b(event: Event) -> None:
        order.append("b")

    def handler_c(event: Event) -> None:
        order.append("c")

    bus.subscribe("scheduler.job_scheduled", handler_a)
    bus.subscribe("scheduler.job_scheduled", handler_b)
    bus.subscribe("scheduler.job_scheduled", handler_c)

    bus.publish(_make_event())

    check(
        order == ["a", "b", "c"],
        "E13: publish() invokes subscribers in strict subscribe-order "
        "(FIFO)",
    )


# ---------------------------------------------------------------------------
# E14 -- publish() delivers to every subscriber, not just the first
# ---------------------------------------------------------------------------
def scenario_publish_delivers_to_every_subscriber() -> None:
    bus = EventBus()
    handlers = [_RecordingHandler() for _ in range(4)]
    for handler in handlers:
        bus.subscribe("scheduler.job_scheduled", handler)

    event = _make_event()
    bus.publish(event)

    check(
        all(len(handler.calls) == 1 and handler.calls[0] is event for handler in handlers),
        "E14: publish() delivers the exact same event to every one of "
        "multiple subscribers",
    )


# ---------------------------------------------------------------------------
# E15 -- publish() with no subscribers is a safe no-op
# ---------------------------------------------------------------------------
def scenario_publish_with_no_subscribers_is_noop() -> None:
    bus = EventBus()

    result = bus.publish(_make_event(name="nobody.listens"))

    check(
        result is None,
        "E15: publish() to an event_name with zero subscribers returns "
        "None and raises nothing",
    )


# ---------------------------------------------------------------------------
# E16 -- a subscriber exception propagates and stops later delivery
# ---------------------------------------------------------------------------
def scenario_subscriber_exception_propagates_and_stops_delivery() -> None:
    bus = EventBus()
    first = _RecordingHandler()
    boom = RuntimeError("subscriber failure")
    failing = _RaisingHandler(boom)
    never_reached = _RecordingHandler()

    bus.subscribe("scheduler.job_scheduled", first)
    bus.subscribe("scheduler.job_scheduled", failing)
    bus.subscribe("scheduler.job_scheduled", never_reached)

    try:
        bus.publish(_make_event())
        check(
            False,
            "E16: publish() propagates a subscriber's exception "
            "unchanged instead of swallowing it",
        )
    except RuntimeError as exc:
        check(
            exc is boom,
            "E16: publish() propagates a subscriber's exception "
            "unchanged instead of swallowing it",
        )

    check(
        len(first.calls) == 1,
        "E16: the subscriber before the failing one still ran normally",
    )
    check(
        len(never_reached.calls) == 0,
        "E16: a subscriber queued after the failing one is never "
        "invoked for that publish() call",
    )


# ---------------------------------------------------------------------------
# E17 -- two different event_names are completely isolated
# ---------------------------------------------------------------------------
def scenario_different_event_names_are_isolated() -> None:
    bus = EventBus()
    scheduled_handler = _RecordingHandler()
    cancelled_handler = _RecordingHandler()

    bus.subscribe("scheduler.job_scheduled", scheduled_handler)
    bus.subscribe("scheduler.job_cancelled", cancelled_handler)

    bus.publish(_make_event(name="scheduler.job_scheduled"))

    check(
        len(scheduled_handler.calls) == 1 and len(cancelled_handler.calls) == 0,
        "E17: publishing one event_name never invokes a different "
        "event_name's subscribers",
    )


# ---------------------------------------------------------------------------
# E18 -- repeated publish() calls each re-deliver to plain subscribers
# ---------------------------------------------------------------------------
def scenario_repeated_publish_redelivers_each_time() -> None:
    bus = EventBus()
    handler = _RecordingHandler()
    bus.subscribe("scheduler.job_scheduled", handler)

    for _ in range(3):
        bus.publish(_make_event())

    check(
        len(handler.calls) == 3,
        "E18: a plainly-subscribed handler (not once()) fires once per "
        "publish() call, with no automatic one-shot behavior",
    )


# ---------------------------------------------------------------------------
# E19 -- a fresh EventBus starts with no subscriptions at all
# ---------------------------------------------------------------------------
def scenario_fresh_event_bus_starts_empty() -> None:
    bus = EventBus()

    check(
        bus._subscribers == {},
        "E19: a freshly-constructed EventBus starts with an empty "
        "subscriber map",
    )

    try:
        bus.unsubscribe("anything.at_all", _RecordingHandler())
        check(
            False,
            "E19: unsubscribe() on a completely fresh EventBus raises "
            "EventBusError (nothing was ever subscribed)",
        )
    except EventBusError:
        check(
            True,
            "E19: unsubscribe() on a completely fresh EventBus raises "
            "EventBusError (nothing was ever subscribed)",
        )

    result = bus.publish(_make_event())
    check(
        result is None,
        "E19: publish() on a completely fresh EventBus is a safe no-op",
    )


# ---------------------------------------------------------------------------
# E20 -- two independent EventBus instances never share state
# ---------------------------------------------------------------------------
def scenario_instances_do_not_share_state() -> None:
    bus_a = EventBus()
    bus_b = EventBus()

    handler_a = _RecordingHandler()
    handler_b = _RecordingHandler()

    bus_a.subscribe("scheduler.job_scheduled", handler_a)
    bus_b.subscribe("scheduler.job_scheduled", handler_b)

    bus_a.publish(_make_event())

    check(
        len(handler_a.calls) == 1 and len(handler_b.calls) == 0,
        "E20: publishing on bus_a never reaches bus_b's subscribers",
    )

    try:
        bus_b.unsubscribe("scheduler.job_scheduled", handler_a)
        check(
            False,
            "E20: bus_b has no knowledge of a handler only ever "
            "subscribed on bus_a",
        )
    except EventBusError:
        check(
            True,
            "E20: bus_b has no knowledge of a handler only ever "
            "subscribed on bus_a",
        )


# ---------------------------------------------------------------------------
# Bonus -- EventBusError is an AgentError subclass (consistency check)
# ---------------------------------------------------------------------------
def scenario_event_bus_error_is_agent_error_subclass() -> None:
    bus = EventBus()

    try:
        bus.unsubscribe("never.subscribed", _RecordingHandler())
        check(
            False,
            "Bonus: EventBusError raised by unsubscribe() is an "
            "instance of AgentError",
        )
    except EventBusError as exc:
        check(
            isinstance(exc, AgentError),
            "Bonus: EventBusError raised by unsubscribe() is an "
            "instance of AgentError",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_event_construction_succeeds,
        scenario_event_id_is_unique,
        scenario_timestamp_is_utc_and_recent,
        scenario_event_is_frozen,
        scenario_payload_is_immutable,
        scenario_subscribe_invalid_event_name_raises,
        scenario_subscribe_non_callable_handler_raises,
        scenario_subscribe_rejects_duplicate,
        scenario_unsubscribe_removes_targeted_subscription,
        scenario_unsubscribe_unknown_handler_raises,
        scenario_once_fires_exactly_once,
        scenario_once_does_not_unsubscribe_on_raise,
        scenario_publish_delivers_in_fifo_order,
        scenario_publish_delivers_to_every_subscriber,
        scenario_publish_with_no_subscribers_is_noop,
        scenario_subscriber_exception_propagates_and_stops_delivery,
        scenario_different_event_names_are_isolated,
        scenario_repeated_publish_redelivers_each_time,
        scenario_fresh_event_bus_starts_empty,
        scenario_instances_do_not_share_state,
        scenario_event_bus_error_is_agent_error_subclass,
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
    print(f"PHASE 3 SPRINT 22B EVENT BUS RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())