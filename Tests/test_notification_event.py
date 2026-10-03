"""
Sprint 7 STEP 1 proof suite -- the Notification Event Model (foundation only).

Scope: dedicated regression suite for
``Business.notification_event.NotificationEventType`` /
``Business.notification_event.NotificationEvent`` only.

This is a pure data-model sprint. Nothing here sends a notification,
touches Telegram/Discord/email/webhook, or wires into the existing
``Services.notification_service.NotificationService``. This suite
proves the *shape* of the model (exact enum members, exact dataclass
fields, immutability, default metadata) and the *absence* of any
extra surface area.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Business/Tests proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Scenario coverage:
    S1 -- Enum has exactly 7 members.
    S2 -- Every enum member has a unique value.
    S3 -- NotificationEvent can be constructed.
    S4 -- metadata defaults to an empty dict when omitted.
    S5 -- metadata can be supplied explicitly.
    S6 -- NotificationEvent is immutable -- mutating any field raises.
    S7 -- All fields are stored exactly as given.
    S8 -- No extra fields exist on the dataclass.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
# S1 -- enum has exactly 7 members
# ---------------------------------------------------------------------------
def scenario_enum_has_exactly_seven_members() -> None:
    members = list(NotificationEventType)
    check(len(members) == 7, "S1: NotificationEventType has exactly 7 members")

    expected_names = {
        "NEW_SIGNAL",
        "ORDER_EXECUTED",
        "STOP_LOSS_TRIGGERED",
        "RISK_LIMIT_EXCEEDED",
        "DAILY_REPORT",
        "DATA_FETCH_FAILED",
        "SCAN_FAILED",
    }
    actual_names = {member.name for member in members}
    check(
        actual_names == expected_names,
        "S1: NotificationEventType member names match exactly the "
        "locked set (no more, no fewer)",
    )

    for name in expected_names:
        check(
            hasattr(NotificationEventType, name),
            f"S1: NotificationEventType.{name} exists",
        )


# ---------------------------------------------------------------------------
# S2 -- every enum member is unique
# ---------------------------------------------------------------------------
def scenario_enum_members_are_unique() -> None:
    values = [member.value for member in NotificationEventType]
    check(
        len(values) == len(set(values)),
        "S2: all NotificationEventType values are unique",
    )

    names = [member.name for member in NotificationEventType]
    check(
        len(names) == len(set(names)),
        "S2: all NotificationEventType names are unique",
    )

    # Pairwise distinctness check (belt-and-suspenders on top of the set check).
    all_distinct = True
    for i, a in enumerate(NotificationEventType):
        for b in list(NotificationEventType)[i + 1 :]:
            if a.value == b.value:
                all_distinct = False
    check(all_distinct, "S2: no two distinct members share a value")


# ---------------------------------------------------------------------------
# S3 -- NotificationEvent can be constructed
# ---------------------------------------------------------------------------
def scenario_notification_event_can_be_constructed() -> None:
    event = NotificationEvent(
        event_type=NotificationEventType.NEW_SIGNAL,
        timestamp="2026-08-02T10:00:00Z",
        title="New Signal",
        message="A new trading signal was generated.",
    )
    check(
        isinstance(event, NotificationEvent),
        "S3: NotificationEvent() constructs a NotificationEvent instance",
    )
    check(
        event.event_type == NotificationEventType.NEW_SIGNAL,
        "S3: constructed event has the given event_type",
    )


# ---------------------------------------------------------------------------
# S4 -- metadata defaults to an empty dict
# ---------------------------------------------------------------------------
def scenario_metadata_defaults_to_empty_dict() -> None:
    event = NotificationEvent(
        event_type=NotificationEventType.DAILY_REPORT,
        timestamp="2026-08-02T10:00:00Z",
        title="Daily Report",
        message="Daily performance report.",
    )
    check(
        event.metadata == {},
        "S4: metadata defaults to an empty dict when omitted",
    )
    check(
        isinstance(event.metadata, dict),
        "S4: default metadata is a dict instance",
    )

    # Default factory must produce independent dicts across instances.
    other = NotificationEvent(
        event_type=NotificationEventType.SCAN_FAILED,
        timestamp="2026-08-02T10:01:00Z",
        title="Scan Failed",
        message="Scan failed.",
    )
    check(
        event.metadata is not other.metadata,
        "S4: default metadata dict is not shared/aliased across instances",
    )


# ---------------------------------------------------------------------------
# S5 -- metadata can be supplied
# ---------------------------------------------------------------------------
def scenario_metadata_can_be_supplied() -> None:
    metadata = {"symbol": "BBCA", "confidence": 0.87}
    event = NotificationEvent(
        event_type=NotificationEventType.ORDER_EXECUTED,
        timestamp="2026-08-02T10:02:00Z",
        title="Order Executed",
        message="Order filled.",
        metadata=metadata,
    )
    check(
        event.metadata == metadata,
        "S5: explicitly supplied metadata is stored exactly",
    )
    check(
        event.metadata["symbol"] == "BBCA",
        "S5: individual metadata keys are accessible",
    )


# ---------------------------------------------------------------------------
# S6 -- immutability
# ---------------------------------------------------------------------------
def scenario_object_is_immutable() -> None:
    event = NotificationEvent(
        event_type=NotificationEventType.STOP_LOSS_TRIGGERED,
        timestamp="2026-08-02T10:03:00Z",
        title="Stop Loss",
        message="Stop loss triggered.",
    )

    for field_name, new_value in (
        ("event_type", NotificationEventType.RISK_LIMIT_EXCEEDED),
        ("timestamp", "2026-08-02T10:04:00Z"),
        ("title", "changed"),
        ("message", "changed"),
        ("metadata", {"x": 1}),
    ):
        raised = False
        try:
            setattr(event, field_name, new_value)
        except FrozenInstanceError:
            raised = True
        except AttributeError:
            # dataclass(frozen=True) raises FrozenInstanceError, which is
            # itself a subclass of AttributeError -- accept either.
            raised = True
        check(
            raised,
            f"S6: mutating field '{field_name}' on a constructed "
            f"NotificationEvent raises an exception",
        )


# ---------------------------------------------------------------------------
# S7 -- all fields stored correctly
# ---------------------------------------------------------------------------
def scenario_all_fields_stored_correctly() -> None:
    metadata = {"account_id": 1, "order_id": "ORD-1"}
    event = NotificationEvent(
        event_type=NotificationEventType.DATA_FETCH_FAILED,
        timestamp="2026-08-02T10:05:00Z",
        title="Data Fetch Failed",
        message="Failed to fetch market data.",
        metadata=metadata,
    )
    check(
        event.event_type == NotificationEventType.DATA_FETCH_FAILED,
        "S7: event_type stored correctly",
    )
    check(
        event.timestamp == "2026-08-02T10:05:00Z",
        "S7: timestamp stored correctly",
    )
    check(
        event.title == "Data Fetch Failed",
        "S7: title stored correctly",
    )
    check(
        event.message == "Failed to fetch market data.",
        "S7: message stored correctly",
    )
    check(
        event.metadata == metadata,
        "S7: metadata stored correctly",
    )


# ---------------------------------------------------------------------------
# S8 -- no extra fields
# ---------------------------------------------------------------------------
def scenario_no_extra_fields() -> None:
    field_names = {f.name for f in fields(NotificationEvent)}
    expected = {"event_type", "timestamp", "title", "message", "metadata"}
    check(
        field_names == expected,
        "S8: NotificationEvent has exactly the fields "
        "{event_type, timestamp, title, message, metadata} -- nothing else",
    )
    check(
        len(fields(NotificationEvent)) == 5,
        "S8: NotificationEvent has exactly 5 fields",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_enum_has_exactly_seven_members,
        scenario_enum_members_are_unique,
        scenario_notification_event_can_be_constructed,
        scenario_metadata_defaults_to_empty_dict,
        scenario_metadata_can_be_supplied,
        scenario_object_is_immutable,
        scenario_all_fields_stored_correctly,
        scenario_no_extra_fields,
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
    print(f"SPRINT 7 STEP 1 NOTIFICATION EVENT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())