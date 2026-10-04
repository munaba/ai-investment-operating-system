"""Per-date tests for IDX_NATIONAL_HOLIDAYS_2026.

Source: SKB 3 Menteri (Menteri Agama / Menaker / Menpan-RB)
  No. 1497/2025, No. 2/2025, No. 5/2025 (announced 2025-10).
  See also: https://setneg.go.id/baca/index/inilah_skb_3_menteri_libur_nasional_dan_cuti_bersama_2026
  and IDX Peng-00171BEI.POP09-2025 (Kalender Libur Bursa 2026).

Each holiday is verified to make IDXMarketCalendar.is_trading_day return False.
Weekend dates included in the set are noted; they are already non-trading.

If the source cannot be accessed, mark as BLOCKED with the exact curl error.
"""

from datetime import date

import pytest

from Business.idx_market_calendar import IDX_NATIONAL_HOLIDAYS_2026, IDXMarketCalendar, load_idx_market_calendar


# National holidays from SKB 3 Menteri 2026 (16 libur nasional, counted date-wise
# within the 25 total days libur nasional + cuti bersama). Entries that are
# weekends in 2026 are marked [weekend] -- they are already covered by the
# weekend guard in is_trading_day(), but must still appear here per calendar.
_EXPECTED_DATES = frozenset(
    {
        date(2026, 1, 1),  # Tahun Baru Masehi                 (Kamis)
        date(2026, 1, 16),  # Isra Mikraj                       (Jumat)
        date(2026, 2, 17),  # Tahun Baru Imlek 2577             (Selasa)
        date(2026, 3, 19),  # Hari Suci Nyepi 1948              (Kamis)
        date(2026, 3, 20),  # Cuti bersama: Nyepi               (Jumat)
        date(2026, 3, 21),  # Idul Fitri 1447 (Sabtu)   [weekend]
        date(2026, 3, 22),  # Idul Fitri 1447 (Minggu)  [weekend]
        date(2026, 3, 23),  # Idul Fitri (cuti bersama)         (Senin)
        date(2026, 3, 24),  # Idul Fitri (cuti bersama)         (Selasa)
        date(2026, 4, 3),  # Wafat Isa Almasih                 (Jumat)
        date(2026, 5, 1),  # Hari Buruh                        (Jumat)
        date(2026, 5, 14),  # Kenaikan Isa Almasih              (Kamis)
        date(2026, 5, 27),  # Idul Adha 1447                    (Rabu)
        date(2026, 5, 31),  # Hari Lahir Pancasila (minggu) [weekend]
        date(2026, 6, 1),  # Hari Lahir Pancasila (senin)      (Senin)
        date(2026, 6, 7),  # Waisak 2570 BE (minggu)    [weekend]
        date(2026, 6, 16),  # Tahun Baru Islam 1448             (Selasa)
        date(2026, 8, 17),  # Proklamasi Kemerdekaan             (Senin)
        date(2026, 8, 25),  # Maulid Nabi 1448 H                 (Selasa)
        date(2026, 12, 24),  # Cuti bersama Natal               (Kamis)
        date(2026, 12, 25),  # Hari Raya Natal                  (Jumat)
    }
)


def test_count_matches_spec():
    """Count reconciliation for the 21-date set (16 libur nasional + 5 cuti bersama)."""
    if len(IDX_NATIONAL_HOLIDAYS_2026) != len(_EXPECTED_DATES):
        missing = _EXPECTED_DATES - IDX_NATIONAL_HOLIDAYS_2026
        extra = IDX_NATIONAL_HOLIDAYS_2026 - _EXPECTED_DATES
        pytest.fail(
            f"IDX_NATIONAL_HOLIDAYS_2026 has {len(IDX_NATIONAL_HOLIDAYS_2026)} entries, "
            f"expected {len(_EXPECTED_DATES)}. "
            f"Missing={missing}, extra={extra}"
        )


@pytest.mark.parametrize("d", sorted(_EXPECTED_DATES))
def test_holiday_is_not_trading_day(d):
    """Each SKB date is not a trading day (weekend || national holiday)."""
    cal = IDXMarketCalendar(holiday_dates=IDX_NATIONAL_HOLIDAYS_2026)
    assert not cal.is_trading_day(d), f"{d.isoformat()} must not be a trading day"


@pytest.mark.parametrize(
    "d",
    [date(2026, 8, 17), date(2026, 8, 25)],
)
def test_specific_dates_included(d):
    """Spot-check per the spec: Kemerdekaan and Maulid."""
    assert d in IDX_NATIONAL_HOLIDAYS_2026, f"{d.isoformat()} must be in the set"


def test_trading_day_not_in_set_is_trading():
    """A normal weekday not in the set must remain a trading day."""
    cal = IDXMarketCalendar(holiday_dates=IDX_NATIONAL_HOLIDAYS_2026)
    # Monday 2026-03-16 is not listed; weekday => trading.
    assert cal.is_trading_day(date(2026, 3, 16))


def test_load_idx_market_calendar_includes_all_holidays():
    """load_idx_market_calendar() unions IDX_NATIONAL_HOLIDAYS_2026."""
    cal = load_idx_market_calendar(env_get=lambda _k, _d: "")
    for d in _EXPECTED_DATES:
        assert d in cal.holiday_dates, f"load_idx_market_calendar missing {d.isoformat()}"
        assert not cal.is_trading_day(d), f"{d.isoformat()} must not be trading via load_idx_market_calendar"
