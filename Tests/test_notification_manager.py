"""
Sprint 7 STEP 5 proof suite -- ``NotificationManager``.

Scope: dedicated regression suite for
``Business.notification_manager.NotificationManager`` only.

This STEP is pure pass-through orchestration: the single entry point
that forwards an already-built ``NotificationEvent`` to
``NotificationDispatcher.dispatch()`` exactly once. Nothing here
builds ``NotificationEvent``/``Report``/``PerformanceSummary``/
``ServiceContext``, reads ``Repository``/``Database``/
``ManualScanService``, retries, queues, schedules, logs, or catches
any exception. This suite uses a hand-written dispatcher spy (no
mocking framework) to prove: exact dependency count, exact
``dispatch()`` call count/order, identity-preserving pass-through
(``is``, not ``==``), non-mutation of the event, exception propagation
without wrapping/retrying, coverage across every
``NotificationEventType`` and an empty-metadata event, and the absence
of any extra public surface or forbidden import.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Business/Tests proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Scenario coverage:
    S1  -- Constructor accepts exactly one dependency.
    S2  -- notify() calls dispatcher.dispatch() exactly once.
    S3  -- The event is forwarded with the same identity (``is``).
    S4  -- No new NotificationEvent is built.
    S5  -- dispatch() is called even when metadata is empty.
    S6  -- dispatch() is called for every NotificationEventType.
    S7  -- Exceptions propagate unwrapped.
    S8  -- No retry: dispatch() called exactly once even when it
           raises.
    S9  -- Constructor has no dependency beyond the dispatcher.
    S10 -- Input NotificationEvent is not mutated.
    S11 -- No forbidden import (Repository, Database,
           Services.notification_service, telegram, requests).
    S12 -- Public API is exactly {notify}.
"""

from __future__ import annotations

import ast
import inspect
import sys
import traceback
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.notification_dispatcher import NotificationDispatcher
from Business.notification_event import NotificationEvent, NotificationEventType
from Business.notification_manager import NotificationManager

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
def make_event(
    event_type: NotificationEventType = NotificationEventType.DAILY_REPORT,
    metadata: dict | None = None,
) -> NotificationEvent:
    return NotificationEvent(
        event_type=event_type,
        timestamp="2026-08-02T09:00:00Z",
        title="Some Title",
        message="Some message.",
        metadata=metadata if metadata is not None else {"key": "value"},
    )


class SpyDispatcher:
    """A minimal stand-in for ``NotificationDispatcher`` that records calls."""

    def __init__(self, raise_exc: Exception | None = None) -> None:
        self.dispatch_calls: List[NotificationEvent] = []
        self._raise_exc = raise_exc

    def dispatch(self, event: NotificationEvent) -> None:
        self.dispatch_calls.append(event)
        if self._raise_exc is not None:
            raise self._raise_exc


class CustomError(Exception):
    """Distinct exception type used to prove propagation, not wrapping."""


# ---------------------------------------------------------------------------
# S1 -- constructor accepts exactly one dependency
# ---------------------------------------------------------------------------
def scenario_constructor_accepts_exactly_one_dependency() -> None:
    dispatcher = SpyDispatcher()
    manager = NotificationManager(dispatcher=dispatcher)
    check(
        isinstance(manager, NotificationManager),
        "S1: NotificationManager(dispatcher=...) constructs successfully",
    )

    sig = inspect.signature(NotificationManager.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    check(
        len(params) == 1 and params[0].name == "dispatcher",
        "S1: constructor takes exactly one parameter named 'dispatcher'",
    )


# ---------------------------------------------------------------------------
# S2 -- notify() calls dispatch() exactly once
# ---------------------------------------------------------------------------
def scenario_notify_calls_dispatch_exactly_once() -> None:
    dispatcher = SpyDispatcher()
    manager = NotificationManager(dispatcher)
    event = make_event()

    manager.notify(event)

    check(
        len(dispatcher.dispatch_calls) == 1,
        "S2: dispatcher.dispatch() is called exactly once",
    )


# ---------------------------------------------------------------------------
# S3 -- event forwarded with the same identity
# ---------------------------------------------------------------------------
def scenario_event_forwarded_with_same_identity() -> None:
    dispatcher = SpyDispatcher()
    manager = NotificationManager(dispatcher)
    event = make_event()

    manager.notify(event)

    check(
        dispatcher.dispatch_calls[0] is event,
        "S3: dispatch() receives the identical event object (is), not a copy",
    )


# ---------------------------------------------------------------------------
# S4 -- no new NotificationEvent is built
# ---------------------------------------------------------------------------
def scenario_no_new_notification_event_built() -> None:
    dispatcher = SpyDispatcher()
    manager = NotificationManager(dispatcher)
    event = make_event()

    manager.notify(event)

    check(
        len(dispatcher.dispatch_calls) == 1,
        "S4: exactly one event reached the dispatcher (no extra "
        "event constructed/dispatched)",
    )
    check(
        dispatcher.dispatch_calls[0] is event,
        "S4: the single event that reached the dispatcher is the exact "
        "input object, not a newly built one",
    )


# ---------------------------------------------------------------------------
# S5 -- dispatch() called even when metadata is empty
# ---------------------------------------------------------------------------
def scenario_dispatch_called_with_empty_metadata() -> None:
    dispatcher = SpyDispatcher()
    manager = NotificationManager(dispatcher)
    event = make_event(metadata={})

    manager.notify(event)

    check(
        len(dispatcher.dispatch_calls) == 1,
        "S5: dispatch() is called exactly once even when event.metadata "
        "is an empty dict",
    )
    check(
        dispatcher.dispatch_calls[0].metadata == {},
        "S5: the empty metadata dict is forwarded unchanged",
    )


# ---------------------------------------------------------------------------
# S6 -- dispatch() called for every NotificationEventType
# ---------------------------------------------------------------------------
def scenario_dispatch_called_for_every_event_type() -> None:
    for event_type in NotificationEventType:
        dispatcher = SpyDispatcher()
        manager = NotificationManager(dispatcher)
        event = make_event(event_type=event_type)

        manager.notify(event)

        check(
            len(dispatcher.dispatch_calls) == 1,
            f"S6: dispatch() is called exactly once for "
            f"NotificationEventType.{event_type.name}",
        )
        check(
            dispatcher.dispatch_calls[0].event_type == event_type,
            f"S6: the dispatched event retains event_type "
            f"{event_type.name}",
        )


# ---------------------------------------------------------------------------
# S7 -- exceptions propagate unwrapped
# ---------------------------------------------------------------------------
def scenario_exception_propagates_unwrapped() -> None:
    custom_exc = CustomError("dispatch failed")
    dispatcher = SpyDispatcher(raise_exc=custom_exc)
    manager = NotificationManager(dispatcher)

    caught: Exception | None = None
    try:
        manager.notify(make_event())
    except Exception as exc:  # noqa: BLE001
        caught = exc

    check(caught is not None, "S7: notify() raises when dispatch() raises")
    check(
        caught is custom_exc,
        "S7: the exact same exception instance propagates (not wrapped)",
    )
    check(
        type(caught) is CustomError,
        "S7: the exception type is preserved exactly (CustomError)",
    )


# ---------------------------------------------------------------------------
# S8 -- no retry: dispatch() called exactly once even when it raises
# ---------------------------------------------------------------------------
def scenario_no_retry_on_exception() -> None:
    dispatcher = SpyDispatcher(raise_exc=CustomError("boom"))
    manager = NotificationManager(dispatcher)

    try:
        manager.notify(make_event())
    except CustomError:
        pass

    check(
        len(dispatcher.dispatch_calls) == 1,
        "S8: dispatch() was called exactly once, even though it raised "
        "(no retry)",
    )


# ---------------------------------------------------------------------------
# S9 -- constructor has no dependency beyond the dispatcher
# ---------------------------------------------------------------------------
def scenario_no_extra_dependency() -> None:
    sig = inspect.signature(NotificationManager.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    check(
        len(params) == 1,
        "S9: NotificationManager.__init__ has exactly one non-self parameter",
    )
    check(
        params[0].default is inspect.Parameter.empty,
        "S9: 'dispatcher' has no default -- it must be supplied explicitly",
    )

    notify_sig = inspect.signature(NotificationManager.notify)
    notify_params = [p for p in notify_sig.parameters.values() if p.name != "self"]
    check(
        len(notify_params) == 1 and notify_params[0].name == "event",
        "S9: notify() takes exactly one parameter named 'event'",
    )


# ---------------------------------------------------------------------------
# S10 -- input NotificationEvent is not mutated
# ---------------------------------------------------------------------------
def scenario_event_not_mutated() -> None:
    dispatcher = SpyDispatcher()
    manager = NotificationManager(dispatcher)
    event = make_event()

    original_event_type = event.event_type
    original_timestamp = event.timestamp
    original_title = event.title
    original_message = event.message
    original_metadata = dict(event.metadata)

    manager.notify(event)

    check(
        event.event_type == original_event_type,
        "S10: event.event_type is unchanged after notify()",
    )
    check(
        event.timestamp == original_timestamp,
        "S10: event.timestamp is unchanged after notify()",
    )
    check(
        event.title == original_title,
        "S10: event.title is unchanged after notify()",
    )
    check(
        event.message == original_message,
        "S10: event.message is unchanged after notify()",
    )
    check(
        dict(event.metadata) == original_metadata,
        "S10: event.metadata is unchanged after notify()",
    )

    raised = False
    try:
        event.title = "mutated"  # type: ignore[misc]
    except FrozenInstanceError:
        raised = True
    check(
        raised,
        "S10: NotificationEvent remains frozen/immutable after passing "
        "through notify()",
    )


# ---------------------------------------------------------------------------
# S11 -- no forbidden import (AST inspection)
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    module_path = ROOT / "Business" / "notification_manager.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)

    forbidden_substrings = (
        "Repository",
        "Database",
        "Services.notification_service",
        "telegram",
        "requests",
        "report_service",
        "performance_summary_service",
        "manual_scan_service",
    )
    violations = [
        m
        for m in imported_modules
        for bad in forbidden_substrings
        if bad.lower() in m.lower()
    ]
    check(
        len(violations) == 0,
        f"S11: no forbidden module imported by notification_manager.py "
        f"(found: {violations})",
    )

    allowed_prefixes = (
        "__future__",
        "Business.notification_dispatcher",
        "Business.notification_event",
    )
    unexpected = [
        m
        for m in imported_modules
        if not any(m == p or m.startswith(p) for p in allowed_prefixes)
    ]
    check(
        len(unexpected) == 0,
        f"S11: only the expected modules are imported (unexpected: {unexpected})",
    )


# ---------------------------------------------------------------------------
# S12 -- public API is exactly {notify}
# ---------------------------------------------------------------------------
def scenario_public_api_is_exactly_notify() -> None:
    public_methods = [
        name
        for name in dir(NotificationManager)
        if not name.startswith("_") and callable(getattr(NotificationManager, name))
    ]
    check(
        public_methods == ["notify"],
        f"S12: NotificationManager exposes exactly one public method "
        f"(found: {public_methods})",
    )


# ---------------------------------------------------------------------------
# Extra -- end-to-end with a real NotificationDispatcher (not just the spy)
# ---------------------------------------------------------------------------
def scenario_end_to_end_with_real_dispatcher() -> None:
    class RecordingChannel:
        def __init__(self) -> None:
            self.received: List[NotificationEvent] = []

        def send(self, event: NotificationEvent) -> None:
            self.received.append(event)

    channel_a = RecordingChannel()
    channel_b = RecordingChannel()
    real_dispatcher = NotificationDispatcher(channels=[channel_a, channel_b])
    manager = NotificationManager(real_dispatcher)
    event = make_event()

    manager.notify(event)

    check(
        len(channel_a.received) == 1 and channel_a.received[0] is event,
        "Extra: through a real NotificationDispatcher, channel A "
        "receives the exact event",
    )
    check(
        len(channel_b.received) == 1 and channel_b.received[0] is event,
        "Extra: through a real NotificationDispatcher, channel B "
        "receives the exact event",
    )


def scenario_end_to_end_empty_channels_no_exception() -> None:
    real_dispatcher = NotificationDispatcher(channels=[])
    manager = NotificationManager(real_dispatcher)

    raised = False
    try:
        manager.notify(make_event())
    except Exception:  # noqa: BLE001
        raised = True

    check(
        not raised,
        "Extra: notify() through a real dispatcher with zero channels "
        "raises nothing",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_accepts_exactly_one_dependency,
        scenario_notify_calls_dispatch_exactly_once,
        scenario_event_forwarded_with_same_identity,
        scenario_no_new_notification_event_built,
        scenario_dispatch_called_with_empty_metadata,
        scenario_dispatch_called_for_every_event_type,
        scenario_exception_propagates_unwrapped,
        scenario_no_retry_on_exception,
        scenario_no_extra_dependency,
        scenario_event_not_mutated,
        scenario_no_forbidden_imports,
        scenario_public_api_is_exactly_notify,
        scenario_end_to_end_with_real_dispatcher,
        scenario_end_to_end_empty_channels_no_exception,
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
    print(f"SPRINT 7 STEP 5 NOTIFICATION MANAGER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())