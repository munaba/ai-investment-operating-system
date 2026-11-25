"""V005/V006 must treat datetime-typed Date values like plain dates.

``datetime`` subclasses ``date``, so an isinstance(date) check placed
before the isinstance(datetime) check swallows datetime values whole.
"""
from datetime import date, datetime

from Business.idx_data_validator import IDXDataValidator
from Business.idx_market_calendar import (
    IDXMarketCalendar,
    IDX_NATIONAL_HOLIDAYS_2026,
)


def _record(day):
    return {
        "Date": day,
        "Open": 10.0,
        "High": 11.0,
        "Low": 9.0,
        "Close": 10.5,
        "Volume": 1000,
    }


def _validator():
    return IDXDataValidator(
        calendar=IDXMarketCalendar(holiday_dates=IDX_NATIONAL_HOLIDAYS_2026)
    )


def test_datetime_dates_do_not_crash_staleness_check():
    """V006 subtracts a WIB date from the latest record date."""
    as_date = _validator().validate_ohlcv([_record(date(2026, 1, 5))], "BBCA")
    as_datetime = _validator().validate_ohlcv(
        [_record(datetime(2026, 1, 5, 9, 0))], "BBCA"
    )
    assert [r.rule_id for r in as_date.rejections] == [
        r.rule_id for r in as_datetime.rejections
    ]


def test_holiday_gap_is_not_flagged_for_datetime_dates():
    """2026-03-19..24 are Nyepi/Idulfitri/cuti, not missing data."""
    records = [
        _record(datetime(2026, 3, 18, 9, 0)),
        _record(datetime(2026, 3, 25, 9, 0)),
    ]
    result = _validator().validate_ohlcv(records, "BBCA")
    assert not any(r.rule_id == "V005" for r in result.rejections)


def test_mixed_date_and_datetime_dates_sort_cleanly():
    """A payload may mix the two types; gap detection must not crash."""
    records = [
        _record(date(2026, 3, 18)),
        _record(datetime(2026, 3, 25, 9, 0)),
    ]
    assert _validator()._check_calendar_gaps(records, "BBCA") == []
