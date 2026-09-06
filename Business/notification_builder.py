"""NotificationBuilder -- Sprint 7 STEP 2 (LOCKED DECISION).

Turns already-computed business-layer output (a ``Report`` and a
``PerformanceSummary``) into a single ``NotificationEvent``. This is a
pure, in-memory builder -- nothing more.

Explicitly out of scope for this STEP (LOCKED DECISION): no sending of
any kind. It does not know about ``Services.notification_service.
NotificationService``, Telegram, Discord, email, or webhooks. It does
not call ``Repository.*`` or ``Database.*``. It does not read files,
log, retry, or schedule anything. It does not recompute any statistic
-- every number in the resulting event's message/metadata comes
verbatim from ``PerformanceSummary``.

Constructor (LOCKED): ``NotificationBuilder()`` -- no dependency
whatsoever.

Public API: ``build_daily_report()`` (LOCKED, Sprint 7 STEP 2), plus
``build_order_executed()`` (added for the paper-trading notification
wiring). Both are pure builders -- neither sends anything, recomputes
any statistic, or mutates its input.

``build_order_executed()`` turns an already-persisted ``Database.
models.Trade`` into a single ``NotificationEvent`` with
``event_type=NotificationEventType.ORDER_EXECUTED``. Every value in
its message/metadata comes verbatim from the given ``Trade`` -- no new
computation, no lookup, no additional dependency.

Knowledge boundary: this module imports only
``Business.notification_event`` (for ``NotificationEvent`` /
``NotificationEventType``), plus ``Business.report_service.Report``
and ``Business.performance_summary_service.PerformanceSummary`` for
``build_daily_report()``'s input type annotations, and
``Database.models.Trade`` for ``build_order_executed()``'s input type
annotation only (never constructed or mutated here).

Does not modify ``Report``, ``PerformanceSummary``, ``NotificationEvent``,
or ``NotificationEventType`` -- no new field, no subclass, no monkey
patch, anywhere in this module.
"""

from __future__ import annotations

from Business.notification_event import NotificationEvent, NotificationEventType
from Business.performance_summary_service import PerformanceSummary
from Business.report_service import Report
from Database.models import Trade


class NotificationBuilder:
    """Builds ``NotificationEvent`` objects from business-layer output.

    Pure builder: no dependency, no side effect, no network, no
    filesystem, no logging, no recomputation of any statistic.
    """

    def __init__(self) -> None:
        """No dependency whatsoever."""
        pass

    def build_daily_report(
        self, report: Report, performance: PerformanceSummary
    ) -> NotificationEvent:
        """Build the single ``DAILY_REPORT`` notification event.

        Args:
            report: Caller-supplied ``Report`` (Sprint 5, LOCKED
                contract). Read-only -- never mutated.
            performance: Caller-supplied ``PerformanceSummary``
                (Sprint 6, LOCKED contract). Read-only -- never
                mutated, no field recomputed.

        Returns:
            A ``NotificationEvent`` with
            ``event_type=NotificationEventType.DAILY_REPORT``,
            ``timestamp=report.generated_at``, a plain-text message
            built only from ``report.generated_at``,
            ``report.total_symbols``, ``performance.win_rate``, and
            ``performance.maximum_drawdown.maximum_drawdown``, and a
            metadata dict containing exactly those same four values.
        """
        generated_at = report.generated_at
        total_symbols = report.total_symbols
        win_rate = performance.win_rate
        maximum_drawdown = performance.maximum_drawdown.maximum_drawdown

        message = (
            "Daily Report\n"
            "\n"
            "Generated:\n"
            f"{generated_at}\n"
            "\n"
            "Symbols:\n"
            f"{total_symbols}\n"
            "\n"
            "Win Rate:\n"
            f"{win_rate:.2%}\n"
            "\n"
            "Maximum Drawdown:\n"
            f"{maximum_drawdown:.2%}"
        )

        metadata = {
            "generated_at": generated_at,
            "total_symbols": total_symbols,
            "win_rate": win_rate,
            "maximum_drawdown": maximum_drawdown,
        }

        return NotificationEvent(
            event_type=NotificationEventType.DAILY_REPORT,
            timestamp=generated_at,
            title="Daily Report",
            message=message,
            metadata=metadata,
        )

    def build_order_executed(self, trade: Trade) -> NotificationEvent:
        """Build the single ``ORDER_EXECUTED`` notification event.

        Args:
            trade: Caller-supplied ``Trade`` (Sprint 4, LOCKED
                contract) -- already persisted by
                ``ExecutionService``. Read-only -- never mutated.

        Returns:
            A ``NotificationEvent`` with
            ``event_type=NotificationEventType.ORDER_EXECUTED``,
            ``timestamp=trade.executed_at``, a plain-text message
            built only from ``trade``'s own fields, and a metadata
            dict containing those same fields.
        """
        message = (
            "Order Executed\n"
            "\n"
            "Symbol:\n"
            f"{trade.symbol}\n"
            "\n"
            "Action:\n"
            f"{trade.action}\n"
            "\n"
            "Quantity:\n"
            f"{trade.quantity}\n"
            "\n"
            "Fill Price:\n"
            f"{trade.fill_price}\n"
            "\n"
            "Fee:\n"
            f"{trade.fee}\n"
            "\n"
            "Tax:\n"
            f"{trade.tax}\n"
            "\n"
            "Executed:\n"
            f"{trade.executed_at}"
        )

        metadata = {
            "trade_id": trade.trade_id,
            "order_id": trade.order_id,
            "account_id": trade.account_id,
            "symbol": trade.symbol,
            "action": trade.action,
            "quantity": trade.quantity,
            "fill_price": trade.fill_price,
            "fee": trade.fee,
            "tax": trade.tax,
            "executed_at": trade.executed_at,
        }

        return NotificationEvent(
            event_type=NotificationEventType.ORDER_EXECUTED,
            timestamp=trade.executed_at,
            title="Order Executed",
            message=message,
            metadata=metadata,
        )