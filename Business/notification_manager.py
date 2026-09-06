"""NotificationManager -- Sprint 7 STEP 5 (LOCKED DECISION).

The single entry point for sending an already-built ``NotificationEvent``.
Pure pass-through orchestration: takes an event and forwards it to
``NotificationDispatcher.dispatch()`` exactly once. Nothing more.

Explicitly out of scope for this STEP (LOCKED DECISION): does not
build ``NotificationEvent``, ``Report``, ``PerformanceSummary``, or
``ServiceContext`` -- those are all other layers' responsibility. Does
not read ``Repository``, ``Database``, ``Report``,
``PerformanceSummary``, or ``ManualScanService``. No retry, no queue,
no scheduler, no logging, no async, no thread. Does not catch any
exception ``dispatcher.dispatch()`` raises -- it propagates unchanged.
Not wired into ``composition_root.py``.

Constructor (LOCKED): exactly one dependency -- a
``NotificationDispatcher`` instance.

Public API (LOCKED): exactly one public method, ``notify()``.

Knowledge boundary (LOCKED): this module imports only
``Business.notification_event.NotificationEvent`` (for the parameter
type annotation only) and
``Business.notification_dispatcher.NotificationDispatcher``.
"""

from __future__ import annotations

from Business.notification_dispatcher import NotificationDispatcher
from Business.notification_event import NotificationEvent


class NotificationManager:
    """The single entry point for sending a ``NotificationEvent``.

    Pure orchestration: no side effect of its own beyond calling
    ``dispatcher.dispatch(event)`` once. Does not build, mutate, or
    inspect the event beyond passing it along.
    """

    def __init__(self, dispatcher: NotificationDispatcher) -> None:
        """Stores the given dispatcher. No other dependency."""
        self._dispatcher = dispatcher

    def notify(self, event: NotificationEvent) -> None:
        """Forward ``event`` to the configured dispatcher, unchanged.

        Calls ``dispatcher.dispatch(event)`` exactly once, passing the
        same ``event`` object (same identity) through -- never copied,
        never mutated, never rebuilt. If ``dispatcher.dispatch()``
        raises, that exception propagates immediately and unchanged --
        no try/except anywhere here.

        Args:
            event: The ``NotificationEvent`` to send.
        """
        self._dispatcher.dispatch(event)