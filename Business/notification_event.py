"""Notification event model (Sprint 7 STEP 1 -- foundation only).

Defines the standard event shape that all future Sprint 7 notification
work will build on: a fixed enum of event types and a single immutable
dataclass carrying the event's fields.

This module intentionally contains no behavior. It does not send
notifications, does not format messages, and does not integrate with
``Services.notification_service.NotificationService``. It is data only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class NotificationEventType(Enum):
    """Fixed set of notification event types.

    No other members may be added without a new, explicit decision.
    """

    NEW_SIGNAL = "NEW_SIGNAL"
    ORDER_EXECUTED = "ORDER_EXECUTED"
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    DAILY_REPORT = "DAILY_REPORT"
    DATA_FETCH_FAILED = "DATA_FETCH_FAILED"
    SCAN_FAILED = "SCAN_FAILED"


@dataclass(frozen=True)
class NotificationEvent:
    """Immutable notification event.

    Fields:
        event_type: The kind of event, one of ``NotificationEventType``.
        timestamp: When the event occurred.
        title: Short human-readable title.
        message: Full human-readable message body.
        metadata: Arbitrary additional data associated with the event.
    """

    event_type: NotificationEventType
    timestamp: str
    title: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)