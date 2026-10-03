"""TelegramNotificationChannel -- Sprint 7 STEP 4 REVISED, Activation 6.2
(failure propagation).

A pure business-layer adapter that translates an already-built
``NotificationEvent`` into the ``ServiceContext`` contract required by
``Services.notification_service.NotificationService``, and forwards it
by calling ``notification_service.execute(context)`` exactly once.

This class satisfies ``Business.notification_dispatcher.
NotificationChannel`` (structural ``send(event) -> None``), so it can
be plugged directly into a ``NotificationDispatcher`` alongside any
other channel.

Explicitly out of scope (unchanged by Activation 6.2):
``Services/notification_service.py`` is never modified -- credentials
(bot token, chat id) remain entirely that service's own concern and
are never accepted here; the Telegram message/format it builds is
untouched. No retry, no queue, no async, no logging, no scheduler.
Does not build or mutate ``NotificationEvent``. Does not read
``Report``, ``PerformanceSummary``, ``Repository``, or ``Database``,
or any trading state (``Order``/``Trade``/``Position``/``Account``).
Not wired into ``composition_root.py``'s send/dispatch/notify path.

Constructor (LOCKED): exactly two dependencies -- the
``NotificationService`` instance to delegate to, and a
``service_context_factory`` callable responsible for producing a
fully-formed ``ServiceContext`` (including whatever ``agent_name``/
``provider_name``/``request_id``/``user_input`` values the composition
root wants to use) from the metadata this adapter supplies.

Public API (LOCKED): exactly one public method, ``send()``.

Activation 6.2 (failure propagation, LOCKED DECISION): ``send()``'s
own ``-> None`` signature means the only way it can make a failed
``NotificationService.execute()`` call observable to
``NotificationDispatcher``/``NotificationManager`` -- which both
already propagate any exception unchanged, by their own LOCKED
contracts -- is to raise. So ``send()`` now inspects the
``ServiceResult`` returned by ``execute()`` and, when
``result.success`` is ``False``, re-raises the exact exception
``NotificationService`` already captured in ``result.error`` (never a
newly invented error, never a swallowed/logged-only failure). A
successful ``ServiceResult`` still results in a normal return (``None``),
exactly as before. This is the sole behavior this STEP adds; everything
else about this adapter (metadata contract, no retry, no mutation) is
unchanged from Sprint 7 STEP 4.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from Business.notification_event import NotificationEvent
from Services.metadata_keys import MetadataKeys
from Services.notification_service import NotificationService, NotificationServiceError
from Services.service_context import ServiceContext

#: Fixed channel identifier this adapter always requests.
_TELEGRAM_CHANNEL_VALUE: str = "telegram"


class TelegramNotificationChannel:
    """Adapts ``NotificationEvent`` -> ``NotificationService.execute()``.

    Pure adapter: no side effect of its own beyond building one
    ``ServiceContext`` (via the injected factory) and calling
    ``notification_service.execute(context)`` once. Does not catch any
    exception ``execute()`` raises -- it propagates unchanged. As of
    Activation 6.2, it also does not swallow a *failed but non-raising*
    ``ServiceResult`` -- see module docstring.
    """

    def __init__(
        self,
        notification_service: NotificationService,
        service_context_factory: Callable[..., ServiceContext],
    ) -> None:
        """Stores the two injected dependencies. No other dependency.

        Args:
            notification_service: The existing, unmodified
                ``NotificationService`` to delegate to.
            service_context_factory: Callable that produces a
                ``ServiceContext`` given this adapter's metadata dict.
                Responsible for filling in whatever other
                ``ServiceContext`` fields (``agent_name``,
                ``provider_name``, ``request_id``, ``user_input``) are
                required -- this adapter itself supplies only the
                notification metadata.
        """
        self._notification_service = notification_service
        self._service_context_factory = service_context_factory

    def send(self, event: NotificationEvent) -> None:
        """Send ``event`` via ``NotificationService`` over Telegram.

        Builds exactly one ``ServiceContext`` (via
        ``service_context_factory``) whose metadata contains exactly
        ``channel="telegram"`` and ``message=event.message`` -- taken
        verbatim, with no reformatting, no markdown, no emoji, no
        prepended timestamp, and no appended metadata. Then calls
        ``notification_service.execute(context)`` exactly once.

        Never wraps, swallows, or retries any exception raised by
        ``execute()`` -- it propagates unchanged. ``event`` itself is
        never mutated or rebuilt.

        Activation 6.2: ``execute()`` itself never raises (it catches
        its own failures internally and returns a failed
        ``ServiceResult`` instead -- see
        ``NotificationService.execute()``). So the returned
        ``ServiceResult`` is now inspected: when ``result.success`` is
        ``False``, the exact exception ``NotificationService`` already
        captured (``result.error``) is re-raised here -- never a new,
        different, or generic error, and never turned into a success.
        If ``result.error`` is ever ``None`` on a failed result (not
        expected from the current ``NotificationService`` contract,
        but defended against rather than assumed), a
        ``NotificationServiceError`` carrying ``result.message`` is
        raised instead, so a failure can never be silently absorbed
        here regardless of exactly how ``NotificationService`` shaped
        it. On success, this method still simply returns ``None``.

        Args:
            event: The ``NotificationEvent`` to forward. Read-only.

        Raises:
            Exception: Whatever ``NotificationService.execute()``
                raises directly (defensive; the current contract does
                not raise), or the exception captured in a failed
                ``ServiceResult.error`` (the normal path today), or a
                ``NotificationServiceError`` as a last-resort fallback
                when a failed result carries no captured exception.
        """
        metadata: Dict[str, Any] = {
            MetadataKeys.CHANNEL: _TELEGRAM_CHANNEL_VALUE,
            MetadataKeys.MESSAGE: event.message,
        }
        context = self._service_context_factory(metadata=metadata)
        result = self._notification_service.execute(context)
        if not result.success:
            if result.error is not None:
                raise result.error
            raise NotificationServiceError(
                result.message or "Notification failed with no captured error."
            )