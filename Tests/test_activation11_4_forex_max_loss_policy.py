"""Activation 11.4 -- Forex maximum-loss policy acceptance test.

Exercises ``Business.forex_max_loss_policy.calculate_maximum_loss``
directly and in isolation: pure, dependency-free unit tests only. No
database, no CLI, no network, no broker, no paper-trading engine, no
reconciliation -- this module is not wired into any production
order/account path yet (see ``Business.forex_max_loss_policy`` module
docstring and Activation 11.1's locked Decision H).

Required test cases (see Activation 11.4 brief):

    1. EUR/USD 10,000 units -> 50 USD
    2. EUR/USD 100,000 units -> 1,000 USD
    3. GBP/USD independent calculation
    4. Absolute-distance behavior (stop above entry)
    5. Decimal precision
    6. Zero quantity rejected
    7. Negative quantity rejected
    8. Non-positive entry rejected
    9. Non-positive stop rejected
    10. Unsupported non-USD pair rejected
    11. No mutable/cache state
    12. Existing pip-policy tests remain green (run separately, see
        Activation 11.4 brief's regression list -- not re-asserted
        inside this file to avoid duplicating
        ``Tests/test_activation11_2_forex_pip_policy.py``)

Run directly:
``python Tests/test_activation11_4_forex_max_loss_policy.py`` -- no
external test framework required, matching every other
``Tests/test_*.py`` script in this suite.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.forex_max_loss_policy import calculate_maximum_loss  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: list[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _expect_validation_error(callable_, description: str) -> None:
    try:
        callable_()
    except ValidationError:
        check(True, description)
    else:
        check(False, f"{description} (no ValidationError raised)")


# ---------------------------------------------------------------------------
# 1/2 -- EUR/USD locked examples
# ---------------------------------------------------------------------------


def scenario_eur_usd_locked_examples() -> None:
    print("\n[1] EUR/USD 10,000 units -> 50 USD")
    value = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)
    check(value == Decimal("50.00"), f"1: EUR/USD 10,000-unit max loss == 50.00 USD (got {value})")

    print("\n[2] EUR/USD 100,000 units -> 1,000 USD")
    value = calculate_maximum_loss("EUR/USD", 1.1000, 1.0900, 100_000)
    check(value == Decimal("1000.00"), f"2: EUR/USD 100,000-unit max loss == 1000.00 USD (got {value})")


# ---------------------------------------------------------------------------
# 3 -- GBP/USD independent calculation
# ---------------------------------------------------------------------------


def scenario_gbp_usd_independent() -> None:
    print("\n[3] GBP/USD independent calculation (not EUR/USD-hardcoded)")
    # 40-pip distance on 25,000 units: pip_value = 0.0001 * 25,000 = 2.50 USD/pip
    # -> max loss = 40 * 2.50 = 100.00 USD
    value = calculate_maximum_loss("GBP/USD", 1.2500, 1.2460, 25_000)
    check(value == Decimal("100.00"), f"3: GBP/USD 25,000-unit, 40-pip max loss == 100.00 USD (got {value})")

    # Different distance/quantity than the EUR/USD cases, to prove
    # this isn't secretly reusing EUR/USD's pip value.
    value2 = calculate_maximum_loss("GBP/USD", 1.3000, 1.2900, 50_000)
    check(value2 == Decimal("500.00"), f"3: GBP/USD 50,000-unit, 100-pip max loss == 500.00 USD (got {value2})")
    check(value != value2, "3: two different GBP/USD scenarios produce different results (not hardcoded)")


# ---------------------------------------------------------------------------
# 4 -- absolute-distance behavior
# ---------------------------------------------------------------------------


def scenario_absolute_distance() -> None:
    print("\n[4] Absolute-distance behavior (stop above entry)")
    # Same 50-pip distance as case 1, but stop_loss ABOVE entry_price
    # (e.g. what a SELL's stop-loss would look like) -- must produce
    # the identical, positive result, since this module does not
    # validate BUY/SELL directional correctness (see module
    # docstring).
    below = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)
    above = calculate_maximum_loss("EUR/USD", 1.0950, 1.1000, 10_000)
    check(below == above, f"4: stop below vs. above entry give the same magnitude (below={below}, above={above})")
    check(above == Decimal("50.00"), f"4: stop-above-entry case still == 50.00 USD (got {above})")
    check(above > 0, "4: maximum loss is always positive regardless of stop-loss direction")


# ---------------------------------------------------------------------------
# 5 -- Decimal precision
# ---------------------------------------------------------------------------


def scenario_decimal_precision() -> None:
    print("\n[5] Decimal precision (binary-float-awkward inputs)")
    # entry - stop = 1.10001 - 1.09991 = 0.00010 exactly (10 pips at
    # 0.0001 pip size), on a quantity chosen to be binary-float-lossy
    # (33,333 units, same value used in the pip-policy test).
    value = calculate_maximum_loss("EUR/USD", 1.10001, 1.09991, 33_333)
    # pip_distance = 0.00010 / 0.0001 = 1 pip
    # pip_value_per_pip = 0.0001 * 33333 = 3.3333
    # maximum_loss = 1 * 3.3333 = 3.3333
    check(value == Decimal("3.3333"), f"5: Decimal precision preserved exactly (got {value})")
    check(isinstance(value, Decimal), "5: calculate_maximum_loss returns a Decimal, not a float")

    # A fractional-pip distance, to confirm no early rounding.
    value2 = calculate_maximum_loss("GBP/USD", 1.25005, 1.24995, 10_000)
    # price_distance = 0.00010, pip_distance = 1 pip, pip_value = 1.00
    # -> 1.00 USD exactly
    check(value2 == Decimal("1.00"), f"5: fractional-pip-distance case exact (got {value2})")


# ---------------------------------------------------------------------------
# 6/7 -- invalid quantity
# ---------------------------------------------------------------------------


def scenario_invalid_quantity() -> None:
    print("\n[6] Zero quantity rejected")
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 0),
        "6: zero quantity raises ValidationError",
    )

    print("\n[7] Negative quantity rejected")
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, -10_000),
        "7: negative quantity raises ValidationError",
    )


# ---------------------------------------------------------------------------
# 8/9 -- invalid prices
# ---------------------------------------------------------------------------


def scenario_invalid_prices() -> None:
    print("\n[8] Non-positive entry rejected")
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", 0, 1.0950, 10_000),
        "8: zero entry_price raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", -1.1000, 1.0950, 10_000),
        "8: negative entry_price raises ValidationError",
    )

    print("\n[9] Non-positive stop rejected")
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", 1.1000, 0, 10_000),
        "9: zero stop_loss raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", 1.1000, -1.0950, 10_000),
        "9: negative stop_loss raises ValidationError",
    )

    print("\n[8/9] Non-numeric prices rejected")
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", "1.1000", 1.0950, 10_000),
        "8: string entry_price raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/USD", 1.1000, None, 10_000),
        "9: None stop_loss raises ValidationError",
    )


# ---------------------------------------------------------------------------
# 10 -- unsupported non-USD pair
# ---------------------------------------------------------------------------


def scenario_unsupported_pair() -> None:
    print("\n[10] Unsupported non-USD pair rejected")
    _expect_validation_error(
        lambda: calculate_maximum_loss("EUR/JPY", 150.00, 149.50, 10_000),
        "10: EUR/JPY (non-USD quote) raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_maximum_loss("USD/JPY", 150.00, 149.50, 10_000),
        "10: USD/JPY (non-USD quote) raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_maximum_loss("USD/CHF", 0.9000, 0.8950, 10_000),
        "10: USD/CHF (non-USD quote) raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_maximum_loss("NOTAPAIR", 1.1000, 1.0950, 10_000),
        "10: malformed pair raises ValidationError",
    )


# ---------------------------------------------------------------------------
# 11 -- independence / no shared state
# ---------------------------------------------------------------------------


def scenario_independence() -> None:
    print("\n[11] Independence -- no shared/mutable state between calls")

    eur_before = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)
    gbp = calculate_maximum_loss("GBP/USD", 1.2500, 1.2460, 25_000)
    eur_after = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)

    check(eur_before == eur_after, "11: EUR/USD result unaffected by an intervening GBP/USD call")
    check(eur_before == Decimal("50.00"), "11: EUR/USD result still correct after intervening call")
    check(gbp == Decimal("100.00"), "11: GBP/USD result correct and unaffected by EUR/USD calls")

    # A prior large-quantity/large-distance call must not corrupt a
    # subsequent small one (rules out any accidental accumulator).
    _ = calculate_maximum_loss("EUR/USD", 1.5000, 1.0000, 1_000_000)
    eur_again = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)
    check(eur_again == Decimal("50.00"), "11: EUR/USD result unaffected by a prior large-scenario call")


def main() -> int:
    scenario_eur_usd_locked_examples()
    scenario_gbp_usd_independent()
    scenario_absolute_distance()
    scenario_decimal_precision()
    scenario_invalid_quantity()
    scenario_invalid_prices()
    scenario_unsupported_pair()
    scenario_independence()

    print(f"\n{'=' * 70}")
    print(f"Activation 11.4 Forex maximum-loss policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())