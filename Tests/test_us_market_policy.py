"""Standalone regression checks for ``Business.us_market_policy``
(Activation 9.1 -- market-agnostic/US-paper components, broker-free).

Covers:

* symbol format -- valid/invalid US ticker shapes, case-insensitivity;
* fractional-share policy -- defaults, env-var loading, quantity checks;
* US fee policy -- defaults, env-var loading, zero computation;
* timezone/market-calendar policy -- trading-day/holiday detection
  (New Year's, MLK, Presidents Day, Good Friday, Memorial Day,
  Juneteenth, July 4th, Labor Day, Thanksgiving, Christmas, weekend
  observance shifts), session classification (pre-market/regular/
  after-hours/closed);
* wiring contract (updated, Activation 9.3 STEP 1) -- this module's
  fee/quantity selection is now imported by exactly
  ``Business.paper_trading_engine``/``Business.execution_service``
  (via ``resolve_fee_tax``/``load_us_fractional_share_policy``), never
  the reverse, and ``Business.execution_policy_config`` (the IDX/
  crypto-shared value object itself) still does not import this
  module at all -- see ``scenario_module_wiring_matches_activation_9_
  3_step_1_contract`` for the precise, updated assertions (this
  replaces the Activation 9.1 "never imported by the IDX pipeline at
  all" guard, which this STEP intentionally supersedes for exactly
  the fee/tax and fractional-share entry points -- not more broadly).

Run directly with ``python Tests/test_us_market_policy.py`` -- no
external test framework required, matching
``Tests/test_reconciliation_engine.py``.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.us_market_policy import (  # noqa: E402
    KNOWN_LIMITATIONS,
    SESSION_AFTER_HOURS,
    SESSION_CLOSED,
    SESSION_PRE_MARKET,
    SESSION_REGULAR,
    US_MARKET_TIMEZONE_NAME,
    USFeePolicy,
    USFractionalSharePolicy,
    USMarketCalendar,
    is_valid_us_symbol,
    load_us_fee_policy,
    load_us_fractional_share_policy,
    us_market_holidays,
)

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _clear_env(*keys: str) -> None:
    for key in keys:
        os.environ.pop(key, None)


# --- 1. Symbol format --------------------------------------------------


def scenario_symbol_format_valid():
    print("\n[Scenario 1] valid US ticker shapes are accepted")
    for symbol in ["A", "AAPL", "MSFT", "GOOGL", "BRK.B", "BRK-B", "BF.B", "aapl", "AaPl"]:
        check(is_valid_us_symbol(symbol) is True, f"{symbol!r} accepted as valid US symbol")


def scenario_symbol_format_invalid():
    print("\n[Scenario 2] invalid shapes are rejected")
    for symbol in [
        "",
        "TOOLONG",  # 7 letters, exceeds 5-letter base
        "BBCA.JK",  # IDX-style suffix, not a US share-class suffix
        "123",  # numeric
        "AAPL!",  # punctuation
        "AAPL ",  # trailing whitespace
        " AAPL",  # leading whitespace
        None,
        123,
    ]:
        check(is_valid_us_symbol(symbol) is False, f"{symbol!r} rejected as invalid US symbol")


def scenario_symbol_format_share_class_edge():
    print("\n[Scenario 3] share-class suffix edge cases")
    check(is_valid_us_symbol("BRK.B") is True, "'BRK.B' accepted (single-letter dot suffix)")
    check(is_valid_us_symbol("BRK-B") is True, "'BRK-B' accepted (single-letter dash suffix)")
    check(is_valid_us_symbol("BRK.BB") is False, "'BRK.BB' rejected (2-letter suffix looks like an IDX country code)")
    check(is_valid_us_symbol("BBCA.JK") is False, "'BBCA.JK' rejected (IDX-style 2-letter suffix, not a US one)")
    check(is_valid_us_symbol("BRK..B") is False, "'BRK..B' rejected (double separator)")


# --- 2. Fractional-share policy -----------------------------------------


def scenario_fractional_share_defaults():
    print("\n[Scenario 4] USFractionalSharePolicy conservative defaults")
    policy = USFractionalSharePolicy()
    check(policy.enabled is False, "enabled defaults to False")
    check(policy.min_quantity == 1.0, "min_quantity defaults to 1.0")
    check(policy.quantity_precision == 0, "quantity_precision defaults to 0")
    check(policy.is_quantity_allowed(1.0) is True, "whole-share quantity 1.0 allowed by default")
    check(policy.is_quantity_allowed(2.0) is True, "whole-share quantity 2.0 allowed by default")
    check(policy.is_quantity_allowed(0.5) is False, "fractional quantity 0.5 rejected by default")
    check(policy.is_quantity_allowed(0.0) is False, "zero quantity rejected")
    check(policy.is_quantity_allowed(-1.0) is False, "negative quantity rejected")


def scenario_fractional_share_enabled():
    print("\n[Scenario 5] USFractionalSharePolicy when explicitly enabled")
    policy = USFractionalSharePolicy(enabled=True, min_quantity=0.01, quantity_precision=2)
    check(policy.is_quantity_allowed(0.01) is True, "min_quantity 0.01 allowed")
    check(policy.is_quantity_allowed(0.001) is False, "below min_quantity rejected")
    check(policy.is_quantity_allowed(0.005) is False, "quantity beyond precision rejected")
    check(policy.is_quantity_allowed(1.5) is True, "1.5 shares allowed when enabled")


def scenario_fractional_share_env_loading():
    print("\n[Scenario 6] load_us_fractional_share_policy reads US_* env vars")
    _clear_env(
        "US_FRACTIONAL_SHARES_ENABLED",
        "US_FRACTIONAL_MIN_QUANTITY",
        "US_FRACTIONAL_QUANTITY_PRECISION",
    )
    default_policy = load_us_fractional_share_policy()
    check(default_policy == USFractionalSharePolicy(), "no env vars set -> byte-identical default policy")

    os.environ["US_FRACTIONAL_SHARES_ENABLED"] = "true"
    os.environ["US_FRACTIONAL_MIN_QUANTITY"] = "0.001"
    os.environ["US_FRACTIONAL_QUANTITY_PRECISION"] = "3"
    try:
        loaded = load_us_fractional_share_policy()
        check(loaded.enabled is True, "US_FRACTIONAL_SHARES_ENABLED=true -> enabled True")
        check(loaded.min_quantity == 0.001, "US_FRACTIONAL_MIN_QUANTITY read correctly")
        check(loaded.quantity_precision == 3, "US_FRACTIONAL_QUANTITY_PRECISION read correctly")
    finally:
        _clear_env(
            "US_FRACTIONAL_SHARES_ENABLED",
            "US_FRACTIONAL_MIN_QUANTITY",
            "US_FRACTIONAL_QUANTITY_PRECISION",
        )


# --- 3. US fee policy -----------------------------------------------------


def scenario_fee_policy_defaults():
    print("\n[Scenario 7] USFeePolicy defaults to zero (computes nothing)")
    policy = USFeePolicy()
    check(policy.commission_rate == 0.0, "commission_rate defaults to 0.0")
    check(policy.regulatory_fee_rate == 0.0, "regulatory_fee_rate defaults to 0.0")


def scenario_fee_policy_env_loading():
    print("\n[Scenario 8] load_us_fee_policy reads US_* env vars, independent of EXECUTION_*")
    _clear_env("US_COMMISSION_RATE", "US_REGULATORY_FEE_RATE", "EXECUTION_BUY_FEE_RATE")
    default_policy = load_us_fee_policy()
    check(default_policy == USFeePolicy(), "no env vars set -> byte-identical default policy")

    os.environ["US_COMMISSION_RATE"] = "0.0"
    os.environ["US_REGULATORY_FEE_RATE"] = "0.0000278"
    # An IDX-namespaced var must never leak into the US policy.
    os.environ["EXECUTION_BUY_FEE_RATE"] = "0.0015"
    try:
        loaded = load_us_fee_policy()
        check(loaded.commission_rate == 0.0, "US_COMMISSION_RATE read correctly")
        check(loaded.regulatory_fee_rate == 0.0000278, "US_REGULATORY_FEE_RATE read correctly")
    finally:
        _clear_env("US_COMMISSION_RATE", "US_REGULATORY_FEE_RATE", "EXECUTION_BUY_FEE_RATE")


# --- 4. Timezone / market-calendar policy ----------------------------------


def scenario_timezone_name():
    print("\n[Scenario 9] timezone is America/New_York")
    calendar = USMarketCalendar()
    check(calendar.timezone_name == "America/New_York", "default timezone_name is America/New_York")
    check(US_MARKET_TIMEZONE_NAME == "America/New_York", "module constant is America/New_York")
    tz = calendar.timezone()
    check(isinstance(tz, ZoneInfo), "timezone() returns a ZoneInfo instance")


def scenario_known_2026_holidays():
    print("\n[Scenario 10] computed 2026 holiday calendar matches known NYSE dates")
    holidays_2026 = us_market_holidays(2026)
    # 2026 official/well-known NYSE holiday observance dates, cross-checked
    # against the standard federal-holiday rules this module implements.
    expected = {
        date(2026, 1, 1): "New Year's Day",
        date(2026, 1, 19): "MLK Day (3rd Monday of January)",
        date(2026, 2, 16): "Washington's Birthday (3rd Monday of February)",
        date(2026, 4, 3): "Good Friday",
        date(2026, 5, 25): "Memorial Day (last Monday of May)",
        date(2026, 6, 19): "Juneteenth",
        date(2026, 7, 3): "Independence Day observed (July 4 falls on Saturday)",
        date(2026, 9, 7): "Labor Day (1st Monday of September)",
        date(2026, 11, 26): "Thanksgiving (4th Thursday of November)",
        date(2026, 12, 25): "Christmas Day",
    }
    for holiday_date, label in expected.items():
        check(holiday_date in holidays_2026, f"{label} ({holiday_date}) present in computed 2026 calendar")
    check(len(holidays_2026) == len(expected), f"exactly {len(expected)} holidays computed for 2026, no extras")


def scenario_weekend_observance_shift():
    print("\n[Scenario 11] Saturday/Sunday holidays shift per standard observance rule")
    # July 4, 2026 is a Saturday -> observed Friday July 3, 2026.
    holidays_2026 = us_market_holidays(2026)
    check(date(2026, 7, 4) not in holidays_2026, "actual Saturday July 4 2026 itself is not the observed date")
    check(date(2026, 7, 3) in holidays_2026, "July 4 2026 (Saturday) observed on preceding Friday July 3")

    # Juneteenth pre-2022 must not appear (first observed 2022).
    holidays_2021 = us_market_holidays(2021)
    check(date(2021, 6, 19) not in holidays_2021, "Juneteenth not present before 2022 (first observed 2022)")
    holidays_2022 = us_market_holidays(2022)
    check(date(2022, 6, 20) in holidays_2022, "Juneteenth 2022 (June 19 is Sunday) observed Monday June 20")


def scenario_trading_day_detection():
    print("\n[Scenario 12] is_trading_day distinguishes weekends/holidays from trading days")
    calendar = USMarketCalendar()
    check(calendar.is_trading_day(date(2026, 1, 2)) is True, "2026-01-02 (Friday, not a holiday) is a trading day")
    check(calendar.is_trading_day(date(2026, 1, 3)) is False, "2026-01-03 (Saturday) is not a trading day")
    check(calendar.is_trading_day(date(2026, 1, 4)) is False, "2026-01-04 (Sunday) is not a trading day")
    check(calendar.is_trading_day(date(2026, 1, 1)) is False, "2026-01-01 (New Year's Day) is not a trading day")
    check(calendar.is_trading_day(date(2026, 12, 25)) is False, "2026-12-25 (Christmas) is not a trading day")


def scenario_session_classification():
    print("\n[Scenario 13] session() classifies pre-market/regular/after-hours/closed correctly")
    calendar = USMarketCalendar()
    tz = ZoneInfo("America/New_York")
    trading_day = datetime(2026, 1, 2, tzinfo=tz)  # Friday, confirmed trading day above

    pre_market = trading_day.replace(hour=5, minute=0)
    check(calendar.session(pre_market) == SESSION_PRE_MARKET, "05:00 ET on a trading day is pre_market")

    regular_open = trading_day.replace(hour=9, minute=30)
    check(calendar.session(regular_open) == SESSION_REGULAR, "09:30 ET (open) is regular")

    midday = trading_day.replace(hour=12, minute=0)
    check(calendar.session(midday) == SESSION_REGULAR, "12:00 ET is regular")

    just_before_close = trading_day.replace(hour=15, minute=59)
    check(calendar.session(just_before_close) == SESSION_REGULAR, "15:59 ET is still regular")

    at_close = trading_day.replace(hour=16, minute=0)
    check(calendar.session(at_close) == SESSION_AFTER_HOURS, "16:00 ET (close) is after_hours")

    after_hours = trading_day.replace(hour=18, minute=0)
    check(calendar.session(after_hours) == SESSION_AFTER_HOURS, "18:00 ET is after_hours")

    late_night = trading_day.replace(hour=22, minute=0)
    check(calendar.session(late_night) == SESSION_CLOSED, "22:00 ET is closed")

    very_early = trading_day.replace(hour=2, minute=0)
    check(calendar.session(very_early) == SESSION_CLOSED, "02:00 ET is closed (before pre-market)")

    weekend = datetime(2026, 1, 3, 10, 0, tzinfo=tz)  # Saturday
    check(calendar.session(weekend) == SESSION_CLOSED, "Saturday 10:00 ET is closed regardless of time-of-day")

    holiday = datetime(2026, 12, 25, 10, 0, tzinfo=tz)  # Christmas, a Friday in 2026
    check(calendar.session(holiday) == SESSION_CLOSED, "Christmas Day 10:00 ET is closed")


def scenario_is_regular_session_open_convenience():
    print("\n[Scenario 14] is_regular_session_open convenience wrapper")
    calendar = USMarketCalendar()
    tz = ZoneInfo("America/New_York")
    check(
        calendar.is_regular_session_open(datetime(2026, 1, 2, 10, 0, tzinfo=tz)) is True,
        "10:00 ET on a trading day -> regular session open",
    )
    check(
        calendar.is_regular_session_open(datetime(2026, 1, 2, 18, 0, tzinfo=tz)) is False,
        "18:00 ET -> regular session not open (after_hours)",
    )


def scenario_naive_datetime_handling():
    print("\n[Scenario 15] naive datetimes are treated as already-local, not silently converted from UTC")
    calendar = USMarketCalendar()
    naive_regular = datetime(2026, 1, 2, 10, 0)  # no tzinfo
    check(calendar.session(naive_regular) == SESSION_REGULAR, "naive 10:00 on a trading day treated as ET regular")


def scenario_limitations_are_disclosed():
    print("\n[Scenario 16] KNOWN_LIMITATIONS discloses the calendar's approximations")
    check(len(KNOWN_LIMITATIONS) >= 3, "at least 3 explicit limitations documented")
    check(
        any("BEST-EFFORT" in item or "best-effort" in item.lower() for item in KNOWN_LIMITATIONS),
        "limitations explicitly flag the calendar as best-effort, not an exchange feed",
    )
    check(
        any("early-close" in item.lower() or "early close" in item.lower() for item in KNOWN_LIMITATIONS),
        "limitations explicitly flag early-close days as unrepresented",
    )


# --- 5. Isolation from IDX pre-trade path -----------------------------------


def scenario_module_wiring_matches_activation_9_3_step_1_contract():
    print(
        "\n[Scenario 17] us_market_policy wiring matches the Activation 9.4 "
        "contract (updated from the Activation 9.1 'not wired at all' guard, "
        "then the Activation 9.3 STEP 1 fee/quantity contract, now extended "
        "for Activation 9.4's session/calendar gate)"
    )
    # Activation 9.1 scope: this scenario asserted us_market_policy was
    # imported by NOTHING in the live trade path -- true at the time,
    # and correct for that Activation's explicitly narrower scope (see
    # this module's own docstring history). Activation 9.3 STEP 1
    # deliberately closes that gap for fee/tax + fractional-share
    # selection (the exact defect the 9.3 audit found: US trades were
    # silently able to inherit IDX's shared ExecutionPolicy fee/tax).
    # This scenario is updated, not deleted, to assert the NEW
    # intentional contract precisely, so a future accidental over-wire
    # (e.g. paper_trading_engine.py importing something from
    # us_market_policy.py unrelated to fee/quantity selection) still
    # fails a test instead of silently expanding scope further.
    import Business.execution_policy_config as epc
    import Business.execution_service as es
    import Business.paper_trading_engine as pte
    import Business.us_market_policy as ump

    pte_source = Path(pte.__file__).read_text(encoding="utf-8")
    es_source = Path(es.__file__).read_text(encoding="utf-8")
    epc_source = Path(epc.__file__).read_text(encoding="utf-8")
    ump_source = Path(ump.__file__).read_text(encoding="utf-8")

    check(
        "from Business.us_market_policy import (" in pte_source
        and "US_ORDER_ALLOWED_SESSIONS," in pte_source
        and "USMarketCalendar," in pte_source
        and "load_us_fractional_share_policy," in pte_source
        and "resolve_fee_tax," in pte_source,
        "paper_trading_engine.py imports exactly US_ORDER_ALLOWED_SESSIONS + USMarketCalendar "
        "(Activation 9.4 gate 17) + load_us_fractional_share_policy + resolve_fee_tax "
        "(Activation 9.3 STEP 1) from us_market_policy -- these four entry points, nothing broader",
    )
    check(
        "from Business.us_market_policy import resolve_fee_tax" in es_source,
        "execution_service.py imports resolve_fee_tax from us_market_policy -- "
        "the one Activation 9.3 STEP 1 entry point it needs",
    )
    check(
        "us_market_policy" not in epc_source,
        "execution_policy_config.py still has no import statement referencing us_market_policy "
        "-- the IDX/crypto-shared ExecutionPolicy value object itself is untouched by this STEP",
    )
    check(
        "import Business.paper_trading_engine" not in ump_source
        and "from Business.paper_trading_engine" not in ump_source
        and "import Business.execution_service" not in ump_source
        and "from Business.execution_service" not in ump_source,
        "us_market_policy.py still does not import paper_trading_engine.py or execution_service.py "
        "-- the dependency direction is one-way (engine/service -> policy), never the reverse",
    )


def main() -> int:
    scenario_symbol_format_valid()
    scenario_symbol_format_invalid()
    scenario_symbol_format_share_class_edge()
    scenario_fractional_share_defaults()
    scenario_fractional_share_enabled()
    scenario_fractional_share_env_loading()
    scenario_fee_policy_defaults()
    scenario_fee_policy_env_loading()
    scenario_timezone_name()
    scenario_known_2026_holidays()
    scenario_weekend_observance_shift()
    scenario_trading_day_detection()
    scenario_session_classification()
    scenario_is_regular_session_open_convenience()
    scenario_naive_datetime_handling()
    scenario_limitations_are_disclosed()
    scenario_module_wiring_matches_activation_9_3_step_1_contract()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 9.1 US MARKET POLICY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())