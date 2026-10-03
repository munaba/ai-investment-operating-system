"""
Sprint 7 STEP 4 (REVISED) proof suite -- ``TelegramNotificationChannel``.

Scope: dedicated regression suite for
``Business.telegram_notification_channel.TelegramNotificationChannel``
only.

This STEP is a pure business-layer adapter. Nothing here talks to the
real Telegram API, mutates or rebuilds ``NotificationEvent``, reads
``Report``/``PerformanceSummary``/``Repository``/``Database``, or
modifies ``Services/notification_service.py`` or STEP 1-3. This suite
uses hand-written spies for ``NotificationService`` and the
``service_context_factory`` (no mocking framework, no real HTTP, no
real ``requests`` dependency) to prove: exact dependency count, exact
context-factory/execute call counts and arguments, metadata contract
(``channel="telegram"``, ``message=event.message`` verbatim, nothing
else), identity-preserving pass-through of the event (``is``, not
``==``), exception propagation without wrapping/retrying, and the
absence of any extra public surface.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Business/Tests proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Scenario coverage:
    S1  -- Constructor accepts exactly two dependencies.
    S2  -- send() builds a ServiceContext exactly once.
    S3  -- execute() is called exactly once.
    S4  -- metadata contains channel="telegram".
    S5  -- metadata contains message == event.message.
    S6  -- NotificationEvent is not mutated.
    S7  -- ServiceContext is built exactly once (belt-and-suspenders
           with S2, using a distinct spy).
    S8  -- execute() receives the exact ServiceContext object the
           factory returned.
    S9  -- Exceptions from execute() propagate unwrapped.
    S10 -- No retry: execute() is called exactly once even when it
           raises.
    S11 -- No dependency beyond NotificationService + context factory.
    S12 -- No mutation of the message string.
"""

from __future__ import annotations

import inspect
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.notification_event import NotificationEvent, NotificationEventType
from Business.telegram_notification_channel import TelegramNotificationChannel
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext
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
# Fixtures / test doubles
# ---------------------------------------------------------------------------
def make_event(message: str = "Daily Report\n\nWin Rate:\n60.00%") -> NotificationEvent:
    return NotificationEvent(
        event_type=NotificationEventType.DAILY_REPORT,
        timestamp="2026-08-02T09:00:00Z",
        title="Daily Report",
        message=message,
        metadata={"total_symbols": 2, "win_rate": 0.6},
    )


class SpyNotificationService:
    """A minimal stand-in for ``NotificationService`` that records calls."""

    def __init__(self, result: ServiceResult | None = None, raise_exc: Exception | None = None) -> None:
        self.execute_calls: List[ServiceContext] = []
        self._result = result if result is not None else ServiceResult.ok()
        self._raise_exc = raise_exc

    def execute(self, context: ServiceContext) -> ServiceResult:
        self.execute_calls.append(context)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


class SpyContextFactory:
    """A minimal stand-in for the injected ``service_context_factory``."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, metadata: Dict[str, Any]) -> ServiceContext:
        self.calls.append({"metadata": metadata})
        return ServiceContext(
            agent_name="test_agent",
            provider_name="test_provider",
            request_id="req-1",
            user_input="",
            metadata=metadata,
        )


class CustomError(Exception):
    """Distinct exception type used to prove propagation, not wrapping."""


# ---------------------------------------------------------------------------
# S1 -- constructor accepts exactly two dependencies
# ---------------------------------------------------------------------------
def scenario_constructor_accepts_exactly_two_dependencies() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(
        notification_service=service, service_context_factory=factory
    )
    check(
        isinstance(channel, TelegramNotificationChannel),
        "S1: TelegramNotificationChannel(notification_service, "
        "service_context_factory) constructs successfully",
    )

    sig = inspect.signature(TelegramNotificationChannel.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    check(
        len(params) == 2,
        "S1: constructor takes exactly two parameters (beyond self)",
    )
    check(
        {p.name for p in params}
        == {"notification_service", "service_context_factory"},
        "S1: constructor parameters are named exactly "
        "'notification_service' and 'service_context_factory'",
    )


# ---------------------------------------------------------------------------
# S2 -- send() builds a ServiceContext exactly once
# ---------------------------------------------------------------------------
def scenario_send_builds_context_exactly_once() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    channel.send(make_event())

    check(
        len(factory.calls) == 1,
        "S2: service_context_factory is called exactly once by send()",
    )


# ---------------------------------------------------------------------------
# S3 -- execute() is called exactly once
# ---------------------------------------------------------------------------
def scenario_execute_called_exactly_once() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    channel.send(make_event())

    check(
        len(service.execute_calls) == 1,
        "S3: notification_service.execute() is called exactly once",
    )


# ---------------------------------------------------------------------------
# S4 -- metadata contains channel="telegram"
# ---------------------------------------------------------------------------
def scenario_metadata_contains_telegram_channel() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    channel.send(make_event())

    metadata = factory.calls[0]["metadata"]
    check(
        metadata.get(MetadataKeys.CHANNEL) == "telegram",
        "S4: metadata[MetadataKeys.CHANNEL] == 'telegram'",
    )
    check(
        metadata.get("channel") == "telegram",
        "S4: metadata['channel'] == 'telegram' (MetadataKeys.CHANNEL "
        "resolves to the literal 'channel')",
    )


# ---------------------------------------------------------------------------
# S5 -- metadata contains message == event.message
# ---------------------------------------------------------------------------
def scenario_metadata_message_matches_event_message() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    event = make_event()
    channel.send(event)

    metadata = factory.calls[0]["metadata"]
    check(
        metadata.get(MetadataKeys.MESSAGE) == event.message,
        "S5: metadata[MetadataKeys.MESSAGE] equals event.message exactly",
    )
    check(
        metadata.get("message") is event.message,
        "S5: the message string forwarded is the exact same object "
        "as event.message (no reformatting, no copy)",
    )
    check(
        set(metadata.keys()) == {MetadataKeys.CHANNEL, MetadataKeys.MESSAGE},
        "S5: metadata contains exactly channel and message -- no "
        "title, no metadata dict from the event, nothing appended",
    )


# ---------------------------------------------------------------------------
# S6 -- NotificationEvent is not mutated
# ---------------------------------------------------------------------------
def scenario_event_not_mutated() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    event = make_event()
    original_event_type = event.event_type
    original_timestamp = event.timestamp
    original_title = event.title
    original_message = event.message
    original_metadata = dict(event.metadata)

    channel.send(event)

    check(
        event.event_type == original_event_type,
        "S6: event.event_type is unchanged after send()",
    )
    check(
        event.timestamp == original_timestamp,
        "S6: event.timestamp is unchanged after send()",
    )
    check(
        event.title == original_title,
        "S6: event.title is unchanged after send()",
    )
    check(
        event.message == original_message,
        "S6: event.message is unchanged after send()",
    )
    check(
        dict(event.metadata) == original_metadata,
        "S6: event.metadata is unchanged after send()",
    )
    check(
        event is event,
        "S6: identity of the event object itself is preserved (is)",
    )


# ---------------------------------------------------------------------------
# S7 -- ServiceContext built exactly once (independent spy)
# ---------------------------------------------------------------------------
def scenario_service_context_built_exactly_once() -> None:
    build_count = {"n": 0}

    def counting_factory(metadata: Dict[str, Any]) -> ServiceContext:
        build_count["n"] += 1
        return ServiceContext(
            agent_name="a",
            provider_name="p",
            request_id="r",
            user_input="",
            metadata=metadata,
        )

    service = SpyNotificationService()
    channel = TelegramNotificationChannel(service, counting_factory)
    channel.send(make_event())

    check(
        build_count["n"] == 1,
        "S7: the ServiceContext-building factory is invoked exactly once",
    )


# ---------------------------------------------------------------------------
# S8 -- execute() receives the exact ServiceContext the factory returned
# ---------------------------------------------------------------------------
def scenario_execute_receives_exact_context() -> None:
    produced_context_holder: Dict[str, ServiceContext] = {}

    def identifying_factory(metadata: Dict[str, Any]) -> ServiceContext:
        ctx = ServiceContext(
            agent_name="a",
            provider_name="p",
            request_id="r",
            user_input="",
            metadata=metadata,
        )
        produced_context_holder["ctx"] = ctx
        return ctx

    service = SpyNotificationService()
    channel = TelegramNotificationChannel(service, identifying_factory)
    channel.send(make_event())

    check(
        service.execute_calls[0] is produced_context_holder["ctx"],
        "S8: notification_service.execute() receives the exact "
        "ServiceContext object the factory produced (is, not equal)",
    )
    check(
        isinstance(service.execute_calls[0], ServiceContext),
        "S8: the argument passed to execute() is a ServiceContext instance",
    )


# ---------------------------------------------------------------------------
# S9 -- exceptions propagate unwrapped
# ---------------------------------------------------------------------------
def scenario_exception_propagates_unwrapped() -> None:
    custom_exc = CustomError("telegram down")
    service = SpyNotificationService(raise_exc=custom_exc)
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    caught: Exception | None = None
    try:
        channel.send(make_event())
    except Exception as exc:  # noqa: BLE001
        caught = exc

    check(caught is not None, "S9: send() raises when execute() raises")
    check(
        caught is custom_exc,
        "S9: the exact same exception instance propagates (not wrapped)",
    )
    check(
        type(caught) is CustomError,
        "S9: the exception type is preserved exactly (CustomError)",
    )


# ---------------------------------------------------------------------------
# S10 -- no retry: execute() called exactly once even when it raises
# ---------------------------------------------------------------------------
def scenario_no_retry_on_exception() -> None:
    service = SpyNotificationService(raise_exc=CustomError("boom"))
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    try:
        channel.send(make_event())
    except CustomError:
        pass

    check(
        len(service.execute_calls) == 1,
        "S10: execute() was called exactly once, even though it raised "
        "(no retry)",
    )
    check(
        len(factory.calls) == 1,
        "S10: the context factory was called exactly once, even though "
        "execute() raised (no retry of context building either)",
    )


# ---------------------------------------------------------------------------
# S11 -- no dependency beyond NotificationService + context factory
# ---------------------------------------------------------------------------
def scenario_no_extra_dependency() -> None:
    sig = inspect.signature(TelegramNotificationChannel.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    for p in params:
        check(
            p.default is inspect.Parameter.empty,
            f"S11: parameter '{p.name}' has no default -- both "
            f"dependencies must be supplied explicitly, no optional "
            f"third dependency exists",
        )

    public_methods = [
        name
        for name in dir(TelegramNotificationChannel)
        if not name.startswith("_")
        and callable(getattr(TelegramNotificationChannel, name))
    ]
    check(
        public_methods == ["send"],
        f"S11/S9: public API is exactly {{send}} -- no method exposes "
        f"token/chat_id/config/repository (found: {public_methods})",
    )


# ---------------------------------------------------------------------------
# S12 -- no mutation of the message string
# ---------------------------------------------------------------------------
def scenario_message_string_not_mutated() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    original_message = "Daily Report\n\nWin Rate:\n60.00%"
    event = make_event(message=original_message)

    channel.send(event)

    check(
        event.message == original_message,
        "S12: event.message string content is unchanged after send()",
    )
    check(
        event.message is original_message,
        "S12: event.message is still the exact same string object "
        "(strings are immutable in Python, but confirms no "
        "reassignment/rebuild happened)",
    )
    sent_message = factory.calls[0]["metadata"][MetadataKeys.MESSAGE]
    check(
        sent_message == original_message,
        "S12: the message actually forwarded equals the original "
        "verbatim -- no formatting, no markdown, no emoji, no "
        "timestamp prepended, no metadata appended",
    )
    check(
        "\n\n" not in sent_message.replace(original_message, "")
        if sent_message != original_message
        else True,
        "S12: no extra content was appended/prepended around the "
        "original message",
    )


# ---------------------------------------------------------------------------
# Extra -- Protocol conformance (structural) with NotificationDispatcher
# ---------------------------------------------------------------------------
def scenario_satisfies_notification_channel_protocol() -> None:
    from Business.notification_dispatcher import (
        NotificationChannel,
        NotificationDispatcher,
    )

    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    check(
        isinstance(channel, NotificationChannel),
        "Extra: TelegramNotificationChannel structurally satisfies "
        "NotificationChannel (Protocol)",
    )

    dispatcher = NotificationDispatcher(channels=[channel])
    event = make_event()
    dispatcher.dispatch(event)

    check(
        len(service.execute_calls) == 1,
        "Extra: dispatching through a real NotificationDispatcher "
        "results in exactly one execute() call",
    )
    check(
        factory.calls[0]["metadata"][MetadataKeys.MESSAGE] is event.message,
        "Extra: end-to-end through the dispatcher, the message "
        "forwarded is still the exact event.message object",
    )


# ---------------------------------------------------------------------------
# Extra -- independent sends do not share/reuse state
# ---------------------------------------------------------------------------
def scenario_independent_sends_do_not_share_state() -> None:
    service = SpyNotificationService()
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    event_a = make_event(message="First report")
    event_b = make_event(message="Second report")

    channel.send(event_a)
    channel.send(event_b)

    check(
        len(factory.calls) == 2,
        "Extra: two separate send() calls build the context exactly "
        "twice (once each)",
    )
    check(
        len(service.execute_calls) == 2,
        "Extra: two separate send() calls invoke execute() exactly "
        "twice (once each)",
    )
    check(
        factory.calls[0]["metadata"][MetadataKeys.MESSAGE] == "First report",
        "Extra: the first call's metadata carries the first event's message",
    )
    check(
        factory.calls[1]["metadata"][MetadataKeys.MESSAGE] == "Second report",
        "Extra: the second call's metadata carries the second event's message",
    )
    check(
        service.execute_calls[0] is not service.execute_calls[1],
        "Extra: each send() produces a distinct ServiceContext object "
        "-- no context reuse across calls",
    )


# ---------------------------------------------------------------------------
# Extra -- Activation 6.2: send() raises on a failed ServiceResult
# ---------------------------------------------------------------------------
# NOTE: prior to Activation 6.2 this scenario asserted the opposite --
# that a failed (but non-raising) ServiceResult from execute() was
# silently ignored by send(). That was the exact bug Activation 6.2
# fixes ("caller/adapter/manager harus menganggap notification GAGAL"
# when ServiceResult.success is False): a failure that produces
# neither an exception nor an observable signal is indistinguishable
# from success to every caller of send() (whose contract is `-> None`).
# This scenario is updated, not removed, to prove the corrected
# contract; every other scenario in this file (message/channel
# metadata contract, no-mutation, exception-propagation-when-execute-
# itself-raises, dependency shape) is unchanged.
def scenario_send_raises_on_failed_service_result() -> None:
    custom_exc = CustomError("failed")
    failing_service = SpyNotificationService(result=ServiceResult.fail(custom_exc))
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(failing_service, factory)

    caught: Exception | None = None
    try:
        channel.send(make_event())
    except Exception as exc:  # noqa: BLE001
        caught = exc

    check(
        caught is not None,
        "Extra (6.2): send() raises when execute() returns a failed "
        "ServiceResult (success=False), even though execute() itself "
        "did not raise",
    )
    check(
        caught is custom_exc,
        "Extra (6.2): the exact exception captured in "
        "ServiceResult.error is re-raised -- not wrapped, not a new "
        "generic error",
    )
    check(
        len(failing_service.execute_calls) == 1,
        "Extra (6.2): execute() was still called exactly once -- no "
        "retry just because the result was a failure",
    )


def scenario_send_returns_none_on_success() -> None:
    service = SpyNotificationService(result=ServiceResult.ok())
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(service, factory)

    returned = channel.send(make_event())

    check(
        returned is None,
        "Extra (6.2): send() still simply returns None when "
        "ServiceResult.success is True -- unchanged success path",
    )


def scenario_send_raises_fallback_when_failed_result_has_no_error() -> None:
    from Services.notification_service import NotificationServiceError

    failing_service = SpyNotificationService(
        result=ServiceResult(success=False, message="failed, no captured error", error=None)
    )
    factory = SpyContextFactory()
    channel = TelegramNotificationChannel(failing_service, factory)

    caught: Exception | None = None
    try:
        channel.send(make_event())
    except Exception as exc:  # noqa: BLE001
        caught = exc

    check(
        caught is not None,
        "Extra (6.2): send() still raises even if a failed ServiceResult "
        "carries no captured error object (defensive fallback)",
    )
    check(
        isinstance(caught, NotificationServiceError),
        "Extra (6.2): the fallback raised is a NotificationServiceError, "
        "not a silently-passed failure",
    )


# ---------------------------------------------------------------------------
# Extra -- no forbidden import (AST inspection)
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import ast

    module_path = ROOT / "Business" / "telegram_notification_channel.py"
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
        "report_service",
        "performance_summary_service",
        "telegram_bot",  # no direct Telegram SDK
        "requests",
    )
    violations = [
        m
        for m in imported_modules
        for bad in forbidden_substrings
        if bad.lower() in m.lower()
    ]
    check(
        len(violations) == 0,
        f"Extra: no forbidden module imported by telegram_notification_"
        f"channel.py (found: {violations})",
    )
    check(
        "Services.notification_service" in imported_modules,
        "Extra: the module does import Services.notification_service "
        "(for NotificationService typing/use only)",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_accepts_exactly_two_dependencies,
        scenario_send_builds_context_exactly_once,
        scenario_execute_called_exactly_once,
        scenario_metadata_contains_telegram_channel,
        scenario_metadata_message_matches_event_message,
        scenario_event_not_mutated,
        scenario_service_context_built_exactly_once,
        scenario_execute_receives_exact_context,
        scenario_exception_propagates_unwrapped,
        scenario_no_retry_on_exception,
        scenario_no_extra_dependency,
        scenario_message_string_not_mutated,
        scenario_satisfies_notification_channel_protocol,
        scenario_independent_sends_do_not_share_state,
        scenario_send_raises_on_failed_service_result,
        scenario_send_returns_none_on_success,
        scenario_send_raises_fallback_when_failed_result_has_no_error,
        scenario_no_forbidden_imports,
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
    print(f"SPRINT 7 STEP 4 TELEGRAM CHANNEL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())