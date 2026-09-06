"""
Sprint 7 STEP 3 proof suite -- ``NotificationDispatcher`` /
``NotificationChannel``.

Scope: dedicated regression suite for
``Business.notification_dispatcher.NotificationDispatcher`` and
``Business.notification_dispatcher.NotificationChannel`` only.

This STEP is a pure dispatch abstraction. Nothing here sends
Telegram/Discord/email/webhook notifications, builds or mutates a
``NotificationEvent``, or reads ``Report``/``PerformanceSummary``/
``Repository``/``Database``. This suite proves: call count and order
per channel, identity-preserving pass-through (``is``, not ``==``),
empty-channel-list safety, exception propagation without wrapping or
swallowing, and the absence of any extra public surface.

Uses simple hand-written test-double channels (no mocking framework)
that record every event they receive, mirroring the plain-fixture
style of the other Business/Tests proof suites: a global pass/fail
counter, plain fixtures, and a ``main()`` runner.

Scenario coverage:
    S1  -- Constructor accepts a list of channels.
    S2  -- dispatch() calls send() exactly once on a single channel.
    S3  -- Two channels: both receive the event.
    S4  -- Three channels: all three receive the event.
    S5  -- Call order matches list order.
    S6  -- Empty channel list: no exception.
    S7  -- The event is forwarded with the same identity (``is``).
    S8  -- Dispatcher does not mutate the NotificationEvent.
    S9  -- A channel that raises: dispatcher propagates it unwrapped,
           unswallowed.
    S10 -- No dependency beyond the constructor's channel list.
    S11 -- Public API is exactly {dispatch}.
    S12 -- NotificationChannel Protocol exposes exactly {send}.
"""

from __future__ import annotations

import inspect
import sys
import traceback
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.notification_dispatcher import (
    NotificationChannel,
    NotificationDispatcher,
)
from Business.notification_event import NotificationEvent, NotificationEventType

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
# Fixtures / test doubles
# ---------------------------------------------------------------------------
def make_event() -> NotificationEvent:
    return NotificationEvent(
        event_type=NotificationEventType.DAILY_REPORT,
        timestamp="2026-08-02T09:00:00Z",
        title="Daily Report",
        message="Daily Report\n\nGenerated:\n2026-08-02T09:00:00Z",
        metadata={"total_symbols": 2},
    )


class RecordingChannel:
    """A minimal test double satisfying ``NotificationChannel``."""

    def __init__(self, name: str = "channel") -> None:
        self.name = name
        self.received: List[NotificationEvent] = []

    def send(self, event: NotificationEvent) -> None:
        self.received.append(event)


class RaisingChannel:
    """A test double whose ``send()`` always raises."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.called = False

    def send(self, event: NotificationEvent) -> None:
        self.called = True
        raise self._exc


class CustomError(Exception):
    """Distinct exception type used to prove propagation, not wrapping."""


# ---------------------------------------------------------------------------
# S1 -- constructor accepts a list of channels
# ---------------------------------------------------------------------------
def scenario_constructor_accepts_channel_list() -> None:
    channel = RecordingChannel()
    dispatcher = NotificationDispatcher(channels=[channel])
    check(
        isinstance(dispatcher, NotificationDispatcher),
        "S1: NotificationDispatcher(channels=[...]) constructs successfully",
    )

    sig = inspect.signature(NotificationDispatcher.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    check(
        len(params) == 1 and params[0].name == "channels",
        "S1: constructor takes exactly one parameter named 'channels'",
    )


# ---------------------------------------------------------------------------
# S2 -- dispatch() calls send() exactly once on a single channel
# ---------------------------------------------------------------------------
def scenario_dispatch_calls_send_exactly_once() -> None:
    channel = RecordingChannel()
    dispatcher = NotificationDispatcher(channels=[channel])
    event = make_event()

    dispatcher.dispatch(event)

    check(
        len(channel.received) == 1,
        "S2: send() is called exactly once on a single channel",
    )
    check(
        channel.received[0] is event,
        "S2: the single call received the dispatched event",
    )


# ---------------------------------------------------------------------------
# S3 -- two channels: both receive the event
# ---------------------------------------------------------------------------
def scenario_two_channels_both_receive_event() -> None:
    channel_a = RecordingChannel("a")
    channel_b = RecordingChannel("b")
    dispatcher = NotificationDispatcher(channels=[channel_a, channel_b])
    event = make_event()

    dispatcher.dispatch(event)

    check(len(channel_a.received) == 1, "S3: channel A received exactly one event")
    check(len(channel_b.received) == 1, "S3: channel B received exactly one event")
    check(channel_a.received[0] is event, "S3: channel A received the exact event")
    check(channel_b.received[0] is event, "S3: channel B received the exact event")


# ---------------------------------------------------------------------------
# S4 -- three channels: all three receive the event
# ---------------------------------------------------------------------------
def scenario_three_channels_all_receive_event() -> None:
    channels = [RecordingChannel(f"c{i}") for i in range(3)]
    dispatcher = NotificationDispatcher(channels=channels)
    event = make_event()

    dispatcher.dispatch(event)

    for i, channel in enumerate(channels):
        check(
            len(channel.received) == 1,
            f"S4: channel {i} received exactly one event",
        )
        check(
            channel.received[0] is event,
            f"S4: channel {i} received the exact event",
        )


# ---------------------------------------------------------------------------
# S5 -- call order matches list order
# ---------------------------------------------------------------------------
def scenario_call_order_matches_list_order() -> None:
    call_order: List[str] = []

    class OrderTrackingChannel:
        def __init__(self, name: str) -> None:
            self.name = name

        def send(self, event: NotificationEvent) -> None:
            call_order.append(self.name)

    channels = [
        OrderTrackingChannel("first"),
        OrderTrackingChannel("second"),
        OrderTrackingChannel("third"),
    ]
    dispatcher = NotificationDispatcher(channels=channels)
    dispatcher.dispatch(make_event())

    check(
        call_order == ["first", "second", "third"],
        "S5: channels are called in exactly the order given to the constructor",
    )


# ---------------------------------------------------------------------------
# S6 -- empty channel list: no exception
# ---------------------------------------------------------------------------
def scenario_empty_channel_list_no_exception() -> None:
    dispatcher = NotificationDispatcher(channels=[])
    raised = False
    try:
        dispatcher.dispatch(make_event())
    except Exception:  # noqa: BLE001
        raised = True
    check(not raised, "S6: dispatch() with an empty channel list raises nothing")


# ---------------------------------------------------------------------------
# S7 -- event forwarded with the same identity
# ---------------------------------------------------------------------------
def scenario_event_forwarded_with_same_identity() -> None:
    channel_a = RecordingChannel("a")
    channel_b = RecordingChannel("b")
    dispatcher = NotificationDispatcher(channels=[channel_a, channel_b])
    event = make_event()

    dispatcher.dispatch(event)

    check(
        channel_a.received[0] is event,
        "S7: channel A receives the identical object (is), not a copy",
    )
    check(
        channel_b.received[0] is event,
        "S7: channel B receives the identical object (is), not a copy",
    )
    check(
        channel_a.received[0] is channel_b.received[0],
        "S7: both channels received the exact same object instance",
    )


# ---------------------------------------------------------------------------
# S8 -- dispatcher does not mutate the event
# ---------------------------------------------------------------------------
def scenario_dispatcher_does_not_mutate_event() -> None:
    channel = RecordingChannel()
    dispatcher = NotificationDispatcher(channels=[channel])
    event = make_event()

    original_event_type = event.event_type
    original_timestamp = event.timestamp
    original_title = event.title
    original_message = event.message
    original_metadata = dict(event.metadata)

    dispatcher.dispatch(event)

    check(
        event.event_type == original_event_type,
        "S8: event.event_type is unchanged after dispatch()",
    )
    check(
        event.timestamp == original_timestamp,
        "S8: event.timestamp is unchanged after dispatch()",
    )
    check(
        event.title == original_title,
        "S8: event.title is unchanged after dispatch()",
    )
    check(
        event.message == original_message,
        "S8: event.message is unchanged after dispatch()",
    )
    check(
        dict(event.metadata) == original_metadata,
        "S8: event.metadata is unchanged after dispatch()",
    )

    # Frozen dataclass guarantee -- belt and suspenders.
    raised = False
    try:
        event.title = "mutated"  # type: ignore[misc]
    except FrozenInstanceError:
        raised = True
    check(
        raised,
        "S8: NotificationEvent remains frozen/immutable after passing "
        "through dispatch()",
    )


# ---------------------------------------------------------------------------
# S9 -- exception propagation, not wrapped, not swallowed
# ---------------------------------------------------------------------------
def scenario_channel_exception_propagates_unwrapped() -> None:
    custom_exc = CustomError("boom")
    raising_channel = RaisingChannel(custom_exc)
    dispatcher = NotificationDispatcher(channels=[raising_channel])

    caught: Exception | None = None
    try:
        dispatcher.dispatch(make_event())
    except Exception as exc:  # noqa: BLE001
        caught = exc

    check(caught is not None, "S9: dispatch() raises when a channel raises")
    check(
        caught is custom_exc,
        "S9: the exact same exception instance propagates (not wrapped)",
    )
    check(
        type(caught) is CustomError,
        "S9: the exception type is preserved exactly (CustomError)",
    )
    check(raising_channel.called, "S9: the raising channel's send() was invoked")


def scenario_channel_exception_stops_remaining_channels() -> None:
    """Not a numbered LOCKED scenario, but proves 'no try/except,
    no swallow' means a later channel never runs once an earlier one
    raises -- reinforces S9."""
    call_log: List[str] = []

    class LoggingRaisingChannel:
        def send(self, event: NotificationEvent) -> None:
            call_log.append("raiser")
            raise CustomError("stop here")

    class NeverCalledChannel:
        def send(self, event: NotificationEvent) -> None:
            call_log.append("never")

    dispatcher = NotificationDispatcher(
        channels=[LoggingRaisingChannel(), NeverCalledChannel()]
    )

    raised = False
    try:
        dispatcher.dispatch(make_event())
    except CustomError:
        raised = True

    check(raised, "S9: CustomError propagates out of dispatch()")
    check(
        call_log == ["raiser"],
        "S9: the channel after the raising one is never called "
        "(no swallow, no continue-on-error)",
    )


# ---------------------------------------------------------------------------
# S10 -- no dependency beyond the constructor's channel list
# ---------------------------------------------------------------------------
def scenario_no_dependency_beyond_channels() -> None:
    sig = inspect.signature(NotificationDispatcher.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    check(
        len(params) == 1,
        "S10: NotificationDispatcher.__init__ has exactly one non-self parameter",
    )
    check(
        params[0].default is inspect.Parameter.empty,
        "S10: 'channels' has no default -- it must be supplied explicitly",
    )

    dispatch_sig = inspect.signature(NotificationDispatcher.dispatch)
    dispatch_params = [p for p in dispatch_sig.parameters.values() if p.name != "self"]
    check(
        len(dispatch_params) == 1 and dispatch_params[0].name == "event",
        "S10: dispatch() takes exactly one parameter named 'event'",
    )


# ---------------------------------------------------------------------------
# S11 -- public API is exactly {dispatch}
# ---------------------------------------------------------------------------
def scenario_public_api_is_exactly_dispatch() -> None:
    public_methods = [
        name
        for name in dir(NotificationDispatcher)
        if not name.startswith("_")
        and callable(getattr(NotificationDispatcher, name))
    ]
    check(
        public_methods == ["dispatch"],
        f"S11: NotificationDispatcher exposes exactly one public method "
        f"(found: {public_methods})",
    )


# ---------------------------------------------------------------------------
# S12 -- NotificationChannel Protocol exposes exactly {send}
# ---------------------------------------------------------------------------
def scenario_notification_channel_protocol_exact_surface() -> None:
    check(
        hasattr(NotificationChannel, "send"),
        "S12: NotificationChannel declares a 'send' method",
    )

    public_members = [
        name
        for name in dir(NotificationChannel)
        if not name.startswith("_")
    ]
    check(
        public_members == ["send"],
        f"S12: NotificationChannel's only public member is 'send' "
        f"(found: {public_members})",
    )

    send_sig = inspect.signature(NotificationChannel.send)
    send_params = [p for p in send_sig.parameters.values() if p.name != "self"]
    check(
        len(send_params) == 1 and send_params[0].name == "event",
        "S12: send() takes exactly one parameter named 'event'",
    )

    # A plain duck-typed object with only send() satisfies the Protocol
    # structurally -- proving it's a minimal structural contract, not
    # requiring inheritance.
    class Duck:
        def send(self, event: NotificationEvent) -> None:
            pass

    check(
        isinstance(Duck(), NotificationChannel),
        "S12: a plain object exposing only send() satisfies "
        "NotificationChannel structurally (duck typing via Protocol)",
    )

    class NotAChannel:
        def receive(self, event: NotificationEvent) -> None:
            pass

    check(
        not isinstance(NotAChannel(), NotificationChannel),
        "S12: an object without a send() method does NOT satisfy "
        "NotificationChannel",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_accepts_channel_list,
        scenario_dispatch_calls_send_exactly_once,
        scenario_two_channels_both_receive_event,
        scenario_three_channels_all_receive_event,
        scenario_call_order_matches_list_order,
        scenario_empty_channel_list_no_exception,
        scenario_event_forwarded_with_same_identity,
        scenario_dispatcher_does_not_mutate_event,
        scenario_channel_exception_propagates_unwrapped,
        scenario_channel_exception_stops_remaining_channels,
        scenario_no_dependency_beyond_channels,
        scenario_public_api_is_exactly_dispatch,
        scenario_notification_channel_protocol_exact_surface,
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
    print(f"SPRINT 7 STEP 3 NOTIFICATION DISPATCHER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())