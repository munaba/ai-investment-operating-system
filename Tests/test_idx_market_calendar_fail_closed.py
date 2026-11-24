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

    def test_2027_is_covered_by_the_built_in_table(self) -> None:
        """2027 holidays come from the SKB 3 Menteri and BEI announcements."""
        cal = load_idx_market_calendar()
        assert cal.covers_year(2027)
        assert cal.is_trading_day(date(2027, 1, 1)) is False  # Tahun Baru
        assert cal.is_trading_day(date(2027, 1, 4)) is True  # ordinary Monday

    def test_2027_matches_bei_241_trading_days(self) -> None:
        """BEI Peng-00169/BEI.POP/09-2026: 241 trading days in 2027."""
        from datetime import timedelta

        cal = load_idx_market_calendar()
        days = [date(2027, 1, 1) + timedelta(days=i) for i in range(365)]
        assert sum(cal.is_trading_day(d) for d in days) == 241
        march = [d for d in days if d.month == 3]
        assert sum(cal.is_trading_day(d) for d in march) == 15
        assert cal.is_trading_day(date(2027, 3, 16)) is True  # first session after Idulfitri
        assert cal.is_trading_day(date(2027, 12, 31)) is False

    def test_2028_year_outside_coverage_returns_false_fail_closed(self) -> None:
        """For years without holidays provided, weekdays are fail-closed to False."""
        cal = load_idx_market_calendar()
        # 2028-01-03 is Monday - outside coverage, no override -> False
        assert cal.is_trading_day(date(2028, 1, 3)) is False
        assert not cal.covers_year(2028)

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
        assert max(IDX_NATIONAL_HOLIDAYS_2026) == date(2026, 12, 31)


class TestFailClosedBehavior:
    """Test explicit fail-closed behavior when year is outside coverage.

    Implementation is fail-closed (return False) for years outside 2026
    unless the operator has explicitly added holidays for that year.
    """

    def test_current_behavior_fail_closed_2028(self) -> None:
        """Document fail-closed behavior: 2028 without operator override returns False."""
        cal = load_idx_market_calendar()
        # 2028-01-04 is Tuesday; no 2028 holidays provided -> fail-closed
        result = cal.is_trading_day(date(2028, 1, 4))
        assert result is False, "Implementation is fail-closed for years without holiday data"

    def test_manual_holiday_override_works(self) -> None:
        """Operator can add 2027 holidays via constructor."""
        holidays_2027 = {date(2027, 1, 1)}
        cal = IDXMarketCalendar(holiday_dates=frozenset(holidays_2027))
        # With manual override, New Year's Day 2027 is correctly not a trading day
        assert cal.is_trading_day(date(2027, 1, 1)) is False
        # But 2027-01-04 (Monday) is still a trading day
        assert cal.is_trading_day(date(2027, 1, 4)) is True
