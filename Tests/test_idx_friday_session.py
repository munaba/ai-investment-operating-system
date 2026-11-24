"""IDX Friday trading hours: Session I ends 11:30, Session II opens 14:00."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from Business.idx_market_calendar import (
    SESSION_AFTER_HOURS,
    SESSION_LUNCH_BREAK,
    SESSION_REGULAR,
    IDXMarketCalendar,
)

WIB = ZoneInfo("Asia/Jakarta")
CAL = IDXMarketCalendar()


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=WIB)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (9, 30, SESSION_REGULAR),
        (11, 29, SESSION_REGULAR),
        (11, 30, SESSION_LUNCH_BREAK),   # Friday Session I is over
        (13, 45, SESSION_LUNCH_BREAK),   # Monday-Thursday this would already be Session II
        (14, 0, SESSION_REGULAR),
        (15, 48, SESSION_REGULAR),
        (15, 50, SESSION_AFTER_HOURS),
    ],
)
def test_friday_sessions(hour: int, minute: int, expected: str) -> None:
    assert CAL.session(_at(27, hour, minute)) == expected  # Fri 27 Nov 2026


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(11, 45, SESSION_REGULAR), (13, 45, SESSION_REGULAR), (12, 30, SESSION_LUNCH_BREAK)],
)
def test_thursday_keeps_the_regular_schedule(hour: int, minute: int, expected: str) -> None:
    assert CAL.session(_at(26, hour, minute)) == expected  # Thu 26 Nov 2026


def test_no_scan_during_the_friday_break() -> None:
    assert CAL.is_market_open(_at(27, 11, 45)) is False
    assert CAL.is_market_open(_at(27, 13, 45)) is False
