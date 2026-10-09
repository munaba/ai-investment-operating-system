"""Test IDXMarketCalendar fail-closed behavior for years outside 2026 coverage."""
from datetime import date

import pytest

from Business.idx_market_calendar import (
    IDXMarketCalendar,
    IDX_NATIONAL_HOLIDAYS_2026,
    load_idx_market_calendar,
)


class TestYearCoverage:
    """Verify fail-closed behavior for years without holiday data."""

    def test_2026_year_is_covered(self) -> None:
        """2026 is within the known holiday table range."""
        cal = load_idx_market_calendar()
        # Should NOT raise - 2026 is covered
        assert cal.is_trading_day(date(2026, 1, 5))  # Monday, not a holiday
        assert not cal.is_trading_day(date(2026, 1, 1))  # New Year's Day

    def test_2027_year_outside_coverage_returns_false_fail_closed(self) -> None:
        """For years outside 2026 without holidays provided, weekdays are fail-closed to False."""
        cal = load_idx_market_calendar()
        # 2027-01-01 is Friday - but outside coverage, no operator override → False
        assert cal.is_trading_day(date(2027, 1, 1)) is False
        # 2027-01-04 is Monday - outside coverage, no override → False
        assert cal.is_trading_day(date(2027, 1, 4)) is False

    def test_2025_year_outside_coverage_fail_closed(self) -> None:
        """2025 is also outside the 2026 holiday table - fail-closed."""
        cal = load_idx_market_calendar()
        # 2025-01-06 is Monday - no 2025 holidays provided → False
        assert cal.is_trading_day(date(2025, 1, 6)) is False

    def test_weekend_always_not_trading_day(self) -> None:
        """Weekends are never trading days regardless of year coverage."""
        cal = load_idx_market_calendar()
        # 2027-01-02 is Saturday
        assert cal.is_trading_day(date(2027, 1, 2)) is False
        # 2027-01-03 is Sunday
        assert cal.is_trading_day(date(2027, 1, 3)) is False

    def test_holiday_dates_coverage_range(self) -> None:
        """Verify the 2026 holiday table min/max dates."""
        assert min(IDX_NATIONAL_HOLIDAYS_2026) == date(2026, 1, 1)
        assert max(IDX_NATIONAL_HOLIDAYS_2026) == date(2026, 12, 25)


class TestFailClosedBehavior:
    """Test explicit fail-closed behavior when year is outside coverage.

    NOTE: The current implementation is fail-open for years outside 2026.
    A future change should make this fail-closed (return False or raise)
    for years not in the holiday table, with logging.
    """

    def test_current_behavior_fail_closed_2027(self) -> None:
        """Document fail-closed behavior: 2027 without operator override returns False."""
        cal = load_idx_market_calendar()
        # 2027-01-01 is Friday - New Year's Day
        # Current behavior: False (fail-closed, no 2027 holidays provided)
        result = cal.is_trading_day(date(2027, 1, 1))
        assert result is False, "Implementation is now fail-closed for years outside 2026"

    def test_manual_holiday_override_works(self) -> None:
        """Operator can add 2027 holidays via constructor."""
        holidays_2027 = {date(2027, 1, 1)}
        cal = IDXMarketCalendar(holiday_dates=frozenset(holidays_2027))
        # With manual override, New Year's Day 2027 is correctly not a trading day
        assert cal.is_trading_day(date(2027, 1, 1)) is False
        # But 2027-01-04 (Monday) is still a trading day
        assert cal.is_trading_day(date(2027, 1, 4)) is True
