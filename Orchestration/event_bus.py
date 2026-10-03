from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping
from uuid import uuid4

from Core.exceptions import AgentError


class EventBusError(AgentError):
    """Raised when ``EventBus`` is given invalid inputs, or when a
    ``subscribe()``/``unsubscribe()`` call cannot be satisfied.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``AutonomousSchedulerError``,
    ``AutonomousHostError``, ``AutonomousAgentError``, and others),
    rather than deriving from the bare ``Exception`` class.
    """

    pass


@dataclass(frozen=True)
class Event:
    """Sprint 22A/22B -- an immutable value object describing exactly
    one fact that has already happened somewhere in the system (e.g.
    "a job was scheduled", "an agent run completed").

    ``Event`` carries no behavior of its own; it is a plain data
    carrier published through ``EventBus.publish()``. Instances are
    frozen (immutable) once constructed, and ``payload`` itself is
    additionally locked down (see ``__post_init__``) so that no
    subscriber can mutate the payload another subscriber already
    observed.

    Attributes:
        event_name: The event's name, e.g. ``"scheduler.job_scheduled"``.
            Follows the ``"<component>.<past_tense_fact>"`` naming
            convention from the Sprint 22A design.
        source: The name of the component that published this event,
            e.g. ``"AutonomousScheduler"``.
        payload: Event-specific data. Stored internally as an
            immutable ``MappingProxyType`` snapshot of whatever
            mapping was passed in, so mutating the original dict (or
            attempting to mutate ``event.payload`` itself) has no
            effect on this event.
        event_id: A ``uuid4`` string minted once, at construction
            time, uniquely identifying this specific event instance.
        timestamp: A timezone-aware UTC ``datetime`` marking when this
            event was constructed.
    """

    event_name: str
    source: str
    payload: Mapping[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        """Freeze ``payload`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning
        ``self.payload`` to a different object, but it does nothing to
        stop the *contents* of a mutable mapping from being changed
        out from under this event after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the payload observed by every subscriber is guaranteed to
        be exactly what it was at publish time, for the lifetime of
        this event.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way around
        the class's immutability from the outside.
        """
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class EventBus:
    """Sprint 22B -- the synchronous, single-threaded, in-process
    Event Bus designed in Sprint 22A.

    ``EventBus`` owns exactly one thing: a mapping of ``event_name`` to
    the ordered list of handlers currently subscribed to it. It holds
    no other state, and it never executes anything on its own --
    delivery happens exclusively when a caller invokes ``publish()``.

    This is purely observational infrastructure: it is not wired into
    ``AutonomousScheduler``, ``AutonomousHost``, ``AutonomousAgent``,
    or ``RuntimeAnalysisPipeline`` in this sprint, and importing this
    module has zero effect on any of those existing components.

    Delivery is synchronous and FIFO, on the publisher's own call
    stack -- there is no threading, no asyncio, no timers, no
    background execution, and no persistence of any kind (nothing is
    written to disk/DB; the subscriber lists live only in this
    instance's own process memory and are lost the moment the instance
    is garbage collected).

    Not a global singleton: each ``EventBus()`` instance owns its own,
    completely independent set of subscriptions.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = {}

    def _validate_event_name(self, event_name: str) -> None:
        """Reject anything that isn't a non-empty ``str`` event name.

        Raises:
            EventBusError: if ``event_name`` is not a ``str``, or is
                an empty/whitespace-only string.
        """
        if not isinstance(event_name, str) or not event_name.strip():
            raise EventBusError(
                f"EventBus requires a non-empty str 'event_name'; got "
                f"{event_name!r}"
            )

    def _validate_handler(self, handler: Callable[[Event], None]) -> None:
        """Reject anything that isn't callable.

        Raises:
            EventBusError: if ``handler`` is not callable.
        """
        if not callable(handler):
            raise EventBusError(
                f"EventBus requires a callable 'handler'; got {handler!r}"
            )

    def subscribe(
        self, event_name: str, handler: Callable[[Event], None]
    ) -> None:
        """Register ``handler`` to be invoked on every future
        ``publish()`` of ``event_name``.

        Args:
            event_name: the event name to subscribe to. Must be a
                non-empty ``str``.
            handler: a callable accepting exactly one ``Event``
                positional argument. Must be callable.

        Returns:
            ``None``.

        Raises:
            EventBusError: if ``event_name`` is invalid, if
                ``handler`` is not callable, or if this exact
                ``(event_name, handler)`` pair is already subscribed
                (duplicate subscriptions of the same handler for the
                same event name are rejected).
        """
        self._validate_event_name(event_name)
        self._validate_handler(handler)

        handlers = self._subscribers.setdefault(event_name, [])
        if handler in handlers:
            raise EventBusError(
                f"EventBus.subscribe() rejects a duplicate subscription "
                f"of the same handler for event_name {event_name!r}"
            )

        handlers.append(handler)
        return None

    def unsubscribe(
        self, event_name: str, handler: Callable[[Event], None]
    ) -> None:
        """Remove exactly one previously-registered ``(event_name,
        handler)`` subscription.

        Args:
            event_name: the event name ``handler`` was subscribed to.
            handler: the exact callable previously passed to
                ``subscribe()`` (or ``once()``'s original handler
                mapping -- see ``once()``).

        Returns:
            ``None``.

        Raises:
            EventBusError: if ``event_name`` is invalid, if
                ``handler`` is not callable, or if no such
                subscription currently exists (including when
                ``event_name`` has never been subscribed to at all).
        """
        self._validate_event_name(event_name)
        self._validate_handler(handler)

        handlers = self._subscribers.get(event_name)
        if not handlers or handler not in handlers:
            raise EventBusError(
                f"EventBus.unsubscribe() received an unknown handler for "
                f"event_name {event_name!r}"
            )

        handlers.remove(handler)
        return None

    def once(
        self, event_name: str, handler: Callable[[Event], None]
    ) -> None:
        """Register ``handler`` to run exactly once for
        ``event_name``, auto-unsubscribing immediately after its
        first successful (non-raising) invocation.

        If the wrapped ``handler`` raises when invoked, the exception
        propagates out of ``publish()`` unchanged (same as any other
        subscriber -- see ``publish()``), and this subscription is
        *not* removed, since the invocation did not complete
        successfully; it remains eligible to fire again on a future
        ``publish()`` of the same event.

        Args:
            event_name: the event name to subscribe to. Must be a
                non-empty ``str``.
            handler: a callable accepting exactly one ``Event``
                positional argument. Must be callable.

        Returns:
            ``None``.

        Raises:
            EventBusError: if ``event_name`` is invalid, if
                ``handler`` is not callable, or if this exact wrapper
                is somehow already registered (not reachable through
                normal use -- each ``once()`` call creates a brand-new
                wrapper closure).
        """
        self._validate_event_name(event_name)
        self._validate_handler(handler)

        def _once_wrapper(event: Event) -> None:
            handler(event)
            self.unsubscribe(event_name, _once_wrapper)

        self.subscribe(event_name, _once_wrapper)
        return None

    def publish(self, event: Event) -> None:
        """Synchronously deliver ``event`` to every handler currently
        subscribed to ``event.event_name``, strictly in the order
        they were subscribed (FIFO).

        Delivery happens entirely on the caller's own call stack --
        there is no background execution, no retry, and no logging.
        If a subscriber raises, the exception propagates out of
        ``publish()`` immediately and unchanged (it is never caught,
        wrapped, or swallowed here), and any subscribers still to come
        for this ``publish()`` call are not invoked.

        Publishing an event with no subscribers registered for its
        ``event_name`` is a safe no-op.

        Args:
            event: the ``Event`` to deliver. Its ``event_name``
                determines which handlers, if any, are invoked.

        Returns:
            ``None``.
        """
        handlers = self._subscribers.get(event.event_name, ())
        for handler in tuple(handlers):
            handler(event)
        return None