"""NotificationDispatcher -- Sprint 7 STEP 3 (LOCKED DECISION).

A pure dispatch abstraction: takes an already-built ``NotificationEvent``
and forwards it, unchanged, to each configured channel. Nothing in
this module knows about Telegram, Discord, email, or webhooks -- those
are concrete channel adapters reserved for a later STEP.

Explicitly out of scope for this STEP (LOCKED DECISION): no retry, no
queue, no async, no thread, no scheduler, no logging, no print, no
telemetry, no metric, no exception handling of any kind. It does not
build or mutate ``NotificationEvent``, and it does not read ``Report``,
``PerformanceSummary``, ``Repository``, or ``Database``.

Constructor (LOCKED): ``NotificationDispatcher(channels: List[
NotificationChannel])`` -- no other dependency.

Public API (LOCKED): exactly one public method, ``dispatch()``.

Knowledge boundary (LOCKED): this module imports only
``Business.notification_event.NotificationEvent`` and ``typing``.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from Business.notification_event import NotificationEvent


@runtime_checkable
class NotificationChannel(Protocol):
    """Minimal channel contract: anything that can ``send()`` an event.

    Exactly one method (LOCKED) -- no ``connect()``, no ``configure()``,
    no ``close()``, no property, nothing else.
    """

    def send(self, event: NotificationEvent) -> None:
        """Send ``event`` through this channel."""
        ...


class NotificationDispatcher:
    """Forwards a ``NotificationEvent`` to each configured channel.

    Pure dispatcher: no side effect of its own beyond calling
    ``channel.send(event)`` once per channel, in list order. Does not
    create, mutate, or inspect the event beyond passing it along. Does
    not catch any exception a channel raises -- it propagates
    unchanged.
    """

    def __init__(self, channels: List[NotificationChannel]) -> None:
        """Stores the given channel list. No other dependency."""
        self._channels = channels

    def dispatch(self, event: NotificationEvent) -> None:
        """Send ``event`` to every configured channel, in order.

        Calls ``channel.send(event)`` exactly once per channel, in the
        same order as ``self._channels``. The same ``event`` object
        (same identity) is passed to every channel -- never copied,
        never mutated. If ``self._channels`` is empty, this simply
        returns without doing anything and without raising. If any
        channel's ``send()`` raises, that exception propagates
        immediately and unchanged -- no try/except anywhere here, and
        no remaining channel is called.

        Args:
            event: The ``NotificationEvent`` to forward.
        """
        for channel in self._channels:
            channel.send(event)