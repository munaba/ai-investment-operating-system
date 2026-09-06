"""DailyReportOrchestrator -- Activation 6.4 (IMPLEMENT).

Thin orchestrator, nothing more: it sequences four already-completed,
already-LOCKED collaborators into one stable "daily report" call, in
exactly this order:

    ManualScanService.run_scan(generated_at)
        -> PerformanceSummaryProductionService.get_performance_summary(account_id)
        -> NotificationBuilder.build_daily_report(report, performance)
        -> NotificationManager.notify(event)

This mirrors ``Business.manual_scan_service.ManualScanService`` and
``Business.performance_summary_production_service.
PerformanceSummaryProductionService`` exactly: a pure sequencing layer
over already-existing, already-real components -- no new business
logic, no new formula, no new abstraction.

Explicitly out of scope for this Activation (per the Activation 6.4
brief): does not modify ``ManualScanService``, ``ReportService``,
``PerformanceSummaryService``, ``NotificationBuilder``,
``NotificationManager``, or ``TelegramNotificationChannel`` -- every
one of those remains untouched, called only through its own existing
public API. Introduces no scheduler and no background worker; this
class is only ever invoked synchronously by a caller (the CLI command
this Activation also adds, or any future caller), never on a timer or
thread of its own.

Constructor (LOCKED, mirrors ``ManualScanService``'s own shape):
exactly four dependencies -- ``ManualScanService``,
``PerformanceSummaryProductionService``, ``NotificationBuilder``,
``NotificationManager`` -- no other dependency of any kind.

Public API: exactly one public method, ``run_daily_report()``.

``generated_at`` is a required, caller-supplied value -- this class
does not generate a timestamp itself (no ``datetime.now()`` or
equivalent anywhere in this module), mirroring
``ManualScanService.run_scan()``'s own ``generated_at`` contract
exactly. The same ``generated_at`` value is used, unchanged, both as
the ``ManualScanService.run_scan()`` argument and (indirectly, via
``report.generated_at``) as the resulting notification's timestamp --
never a second, independently-generated timestamp.

Exception handling: no ``try``/``except`` anywhere in this module, and
no new exception type is defined. Any exception any of the four
collaborators raises -- including a ``NotificationManager.notify()``
failure -- propagates unchanged to the caller. A notification failure
is never swallowed, logged-and-ignored, or converted into a
degraded/partial success; it is a hard failure of this call, exactly
as the Activation 6.4 brief requires.

Knowledge boundary: this module imports only
``Business.manual_scan_service.ManualScanService``,
``Business.performance_summary_production_service.
PerformanceSummaryProductionService``,
``Business.notification_builder.NotificationBuilder``,
``Business.notification_event.NotificationEvent``, and
``Business.notification_manager.NotificationManager`` for the
constructor's own type annotations. It does not import
``Repository.*``, ``Database.*``, ``Services.notification_service.
NotificationService``, ``Business.telegram_notification_channel.
TelegramNotificationChannel``, or any scheduler/background-worker
module.
"""

from __future__ import annotations

from Business.manual_scan_service import ManualScanService
from Business.notification_builder import NotificationBuilder
from Business.notification_event import NotificationEvent
from Business.notification_manager import NotificationManager
from Business.performance_summary_production_service import (
    PerformanceSummaryProductionService,
)


class DailyReportOrchestrator:
    """Sequences the already-completed daily-report pipeline into one
    stable call.

    No business logic of its own -- no sorting, ranking, filtering,
    scoring, retry, or exception wrapping. The entire responsibility
    of this class is calling its four collaborators, in a fixed
    order, and returning the resulting ``NotificationEvent``.
    """

    def __init__(
        self,
        manual_scan_service: ManualScanService,
        performance_summary_production_service: PerformanceSummaryProductionService,
        notification_builder: NotificationBuilder,
        notification_manager: NotificationManager,
    ) -> None:
        """Store the exactly four collaborators this orchestrator will call.

        Args:
            manual_scan_service: The already-constructed
                ``ManualScanService`` used to run the Sprint 5 scan
                pipeline and produce a ``Report``. Stored by
                identity, never copied, never inspected, never
                wrapped.
            performance_summary_production_service: The
                already-constructed
                ``PerformanceSummaryProductionService`` used to build
                a real, account-scoped ``PerformanceSummary``. Stored
                by identity.
            notification_builder: The already-constructed
                ``NotificationBuilder`` used to turn the ``Report``
                and ``PerformanceSummary`` into a single
                ``NotificationEvent``. Stored by identity.
            notification_manager: The already-constructed
                ``NotificationManager`` used to send that
                ``NotificationEvent``. Stored by identity. Any wiring
                it needs (e.g. an already-connected
                ``NotificationDispatcher``/channel) must already be
                in place before it is handed to this constructor --
                this class injects nothing onto it.
        """
        self._manual_scan_service = manual_scan_service
        self._performance_summary_production_service = (
            performance_summary_production_service
        )
        self._notification_builder = notification_builder
        self._notification_manager = notification_manager

    def run_daily_report(self, account_id: str, generated_at: str) -> NotificationEvent:
        """Run the full daily-report pipeline and return the sent
        ``NotificationEvent``.

        Executes, in exactly this order:

            1. ``self._manual_scan_service.run_scan(generated_at)``
            2. ``self._performance_summary_production_service.
               get_performance_summary(account_id)``
            3. ``self._notification_builder.build_daily_report(report, performance)``
            4. ``self._notification_manager.notify(event)``
            5. return ``event``

        No sorting, ranking, filtering, scoring, retry, or exception
        wrapping of any kind is performed here -- each step's output
        is handed to the next exactly as produced.

        Args:
            account_id: The account to build the performance summary
                for, passed unchanged to
                ``PerformanceSummaryProductionService.
                get_performance_summary()``.
            generated_at: Caller-supplied timestamp string, used
                unchanged as the ``ManualScanService.run_scan()``
                argument. This method never generates its own
                timestamp.

        Returns:
            The exact ``NotificationEvent``
            ``NotificationBuilder.build_daily_report()`` returned --
            same object, never rebuilt or wrapped -- after it has
            already been handed to ``NotificationManager.notify()``.

        Raises:
            Exception: any exception raised by
                ``ManualScanService.run_scan()``,
                ``PerformanceSummaryProductionService.
                get_performance_summary()``,
                ``NotificationBuilder.build_daily_report()``, or
                ``NotificationManager.notify()`` propagates unchanged
                -- never caught, never wrapped. In particular, a
                notification failure is never swallowed here.
        """
        report = self._manual_scan_service.run_scan(generated_at)
        performance = self._performance_summary_production_service.get_performance_summary(
            account_id
        )
        event = self._notification_builder.build_daily_report(report, performance)
        self._notification_manager.notify(event)
        return event