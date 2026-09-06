"""Activation 11.2 -- Forex pip size / pip value acceptance test.

Exercises ``Business.forex_pip_policy`` directly and in isolation:
pure, dependency-free unit tests only. No database, no CLI, no
network, no broker, no paper-trading engine -- this module is not
wired into any production order/account path yet (see
``Business.forex_pip_policy`` module docstring and Activation 11.1's
locked decision record).

Required test cases (see Activation 11.2 brief):

    A. EUR/USD pip size
    B. GBP/USD pip size
    C. JPY pip-size branch (policy-level only, USD/JPY is NOT a
       supported pip-value pair)
    D. EUR/USD pip value, 10,000 units
    E. EUR/USD pip value, 100,000 units
    F. GBP/USD pip value, 25,000 units
    G. Decimal precision (values awkward for binary floats)
    H. Zero quantity rejected
    I. Negative quantity rejected
    J. Unsupported non-USD quote (EUR/JPY) rejected for pip value
    K. Malformed pair rejected
    L. Independence -- no shared/mutable state between calls

Run directly: ``python Tests/test_activation11_2_forex_pip_policy.py``
-- no external test framework required, matching every other
``Tests/test_*.py`` script in this suite.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.forex_pip_policy import (  # noqa: E402
    PIP_SIZE_DEFAULT,
    PIP_SIZE_JPY_QUOTE,
    SUPPORTED_PIP_VALUE_PAIRS,
    calculate_pip_value,
    get_pip_size,
)
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
# A/B/C -- pip size
# ---------------------------------------------------------------------------


def scenario_pip_size() -> None:
    print("\n[A] EUR/USD pip size")
    check(get_pip_size("EUR/USD") == PIP_SIZE_DEFAULT, "A: EUR/USD pip size == 0.0001")
    check(get_pip_size("EUR/USD") == Decimal("0.0001"), "A: EUR/USD pip size literal == 0.0001")

    print("\n[B] GBP/USD pip size")
    check(get_pip_size("GBP/USD") == PIP_SIZE_DEFAULT, "B: GBP/USD pip size == 0.0001")
    check(get_pip_size("GBP/USD") == Decimal("0.0001"), "B: GBP/USD pip size literal == 0.0001")

    print("\n[C] JPY pip-size branch (policy-level only)")
    check(get_pip_size("USD/JPY") == PIP_SIZE_JPY_QUOTE, "C: USD/JPY pip size == 0.01")
    check(get_pip_size("USD/JPY") == Decimal("0.01"), "C: USD/JPY pip size literal == 0.01")
    check(get_pip_size("EUR/JPY") == Decimal("0.01"), "C: EUR/JPY pip size == 0.01 (any JPY quote)")
    check(
        "USD/JPY" not in SUPPORTED_PIP_VALUE_PAIRS,
        "C: USD/JPY is NOT a supported pip-value pair despite having a defined pip size",
    )
    # accepts unseparated six-letter form too
    check(get_pip_size("USDJPY") == Decimal("0.01"), "C: 'USDJPY' (no slash) normalizes the same as 'USD/JPY'")
    check(get_pip_size("eurusd") == Decimal("0.0001"), "A: 'eurusd' (lowercase, no slash) normalizes correctly")


# ---------------------------------------------------------------------------
# D/E/F -- pip value, locked examples
# ---------------------------------------------------------------------------


def scenario_pip_value_locked_examples() -> None:
    print("\n[D] EUR/USD pip value, 10,000 units")
    value = calculate_pip_value("EUR/USD", 10_000)
    check(value == Decimal("1.00"), f"D: EUR/USD pip value @ 10,000 units == 1.00 USD (got {value})")

    print("\n[E] EUR/USD pip value, 100,000 units")
    value = calculate_pip_value("EUR/USD", 100_000)
    check(value == Decimal("10.00"), f"E: EUR/USD pip value @ 100,000 units == 10.00 USD (got {value})")

    print("\n[F] GBP/USD pip value, 25,000 units")
    value = calculate_pip_value("GBP/USD", 25_000)
    check(value == Decimal("2.50"), f"F: GBP/USD pip value @ 25,000 units == 2.50 USD (got {value})")


# ---------------------------------------------------------------------------
# G -- Decimal precision
# ---------------------------------------------------------------------------


def scenario_decimal_precision() -> None:
    print("\n[G] Decimal precision (binary-float-awkward inputs)")

    # 0.1 + 0.2 != 0.3 in binary float; 33333 * 0.0001 is similarly
    # awkward in binary float representation.
    value = calculate_pip_value("EUR/USD", 33_333)
    check(value == Decimal("3.3333"), f"G: EUR/USD pip value @ 33,333 units == 3.3333 USD exactly (got {value})")
    check(isinstance(value, Decimal), "G: calculate_pip_value returns a Decimal, not a float")

    # A quantity supplied as a string-like float that is notoriously
    # lossy in raw binary form (0.1 * 3 != 0.3) -- fractional base
    # units are unusual for Forex quantity but the arithmetic must
    # still be exact if supplied.
    value_a = calculate_pip_value("GBP/USD", 12_345.6789)
    expected_a = Decimal("0.0001") * Decimal("12345.6789")
    check(value_a == expected_a, f"G: fractional quantity stays exact via Decimal (got {value_a}, expected {expected_a})")


# ---------------------------------------------------------------------------
# H/I -- invalid quantity
# ---------------------------------------------------------------------------


def scenario_invalid_quantity() -> None:
    print("\n[H] Zero quantity rejected")
    _expect_validation_error(lambda: calculate_pip_value("EUR/USD", 0), "H: zero quantity raises ValidationError")

    print("\n[I] Negative quantity rejected")
    _expect_validation_error(
        lambda: calculate_pip_value("EUR/USD", -10_000), "I: negative quantity raises ValidationError"
    )
    _expect_validation_error(
        lambda: calculate_pip_value("GBP/USD", -0.01), "I: small negative quantity raises ValidationError"
    )

    print("\n[I] Non-numeric quantity rejected")
    _expect_validation_error(
        lambda: calculate_pip_value("EUR/USD", "10000"), "I: string quantity raises ValidationError"
    )
    _expect_validation_error(
        lambda: calculate_pip_value("EUR/USD", None), "I: None quantity raises ValidationError"
    )


# ---------------------------------------------------------------------------
# J -- unsupported non-USD quote
# ---------------------------------------------------------------------------


def scenario_unsupported_non_usd_quote() -> None:
    print("\n[J] Unsupported non-USD quote pairs rejected for pip value")
    _expect_validation_error(
        lambda: calculate_pip_value("EUR/JPY", 10_000),
        "J: EUR/JPY (non-USD quote) raises ValidationError for pip value",
    )
    _expect_validation_error(
        lambda: calculate_pip_value("USD/JPY", 10_000),
        "J: USD/JPY (non-USD quote) raises ValidationError for pip value",
    )
    _expect_validation_error(
        lambda: calculate_pip_value("USD/CHF", 10_000),
        "J: USD/CHF (non-USD quote) raises ValidationError for pip value",
    )
    # Sanity: get_pip_size still works for these (Decision C is
    # independent of the account-currency restriction, Decision D).
    check(get_pip_size("EUR/JPY") == Decimal("0.01"), "J: get_pip_size still succeeds for EUR/JPY (pure pip size)")


# ---------------------------------------------------------------------------
# K -- malformed pair
# ---------------------------------------------------------------------------


def scenario_malformed_pair() -> None:
    print("\n[K] Malformed pair rejected")
    _expect_validation_error(lambda: calculate_pip_value("EURUSD/", 10_000), "K: trailing slash rejected")
    _expect_validation_error(lambda: calculate_pip_value("EUR//USD", 10_000), "K: double slash rejected")
    _expect_validation_error(lambda: calculate_pip_value("EU/USD", 10_000), "K: two-letter base rejected")
    _expect_validation_error(lambda: calculate_pip_value("EUR/US", 10_000), "K: two-letter quote rejected")
    _expect_validation_error(lambda: calculate_pip_value("EURUS", 10_000), "K: five-letter unseparated form rejected")
    _expect_validation_error(lambda: calculate_pip_value("", 10_000), "K: empty string rejected")
    _expect_validation_error(lambda: calculate_pip_value("123/456", 10_000), "K: numeric pair rejected")
    _expect_validation_error(lambda: calculate_pip_value(None, 10_000), "K: non-string pair rejected")
    _expect_validation_error(lambda: get_pip_size("NOTAPAIR"), "K: get_pip_size also rejects malformed pair")


# ---------------------------------------------------------------------------
# L -- independence / no shared state
# ---------------------------------------------------------------------------


def scenario_independence() -> None:
    print("\n[L] Independence -- no shared/mutable state between calls")

    eur_value_before = calculate_pip_value("EUR/USD", 10_000)
    gbp_value = calculate_pip_value("GBP/USD", 25_000)
    eur_value_after = calculate_pip_value("EUR/USD", 10_000)

    check(eur_value_before == eur_value_after, "L: EUR/USD result unaffected by an intervening GBP/USD call")
    check(eur_value_before == Decimal("1.00"), "L: EUR/USD value still correct after intervening call")
    check(gbp_value == Decimal("2.50"), "L: GBP/USD value correct and unaffected by EUR/USD calls")

    # Calling with a large quantity must not corrupt a subsequent
    # small-quantity call (rules out any accidental module-level
    # accumulator/cache).
    _ = calculate_pip_value("EUR/USD", 1_000_000)
    eur_value_again = calculate_pip_value("EUR/USD", 10_000)
    check(eur_value_again == Decimal("1.00"), "L: EUR/USD @ 10,000 unaffected by a prior large-quantity call")

    # get_pip_size is independent of calculate_pip_value's supported-
    # pair restriction and of any prior calls.
    check(get_pip_size("EUR/USD") == Decimal("0.0001"), "L: get_pip_size stable across repeated calls")
    check(get_pip_size("EUR/USD") == Decimal("0.0001"), "L: get_pip_size stable across repeated calls (again)")


def main() -> int:
    scenario_pip_size()
    scenario_pip_value_locked_examples()
    scenario_decimal_precision()
    scenario_invalid_quantity()
    scenario_unsupported_non_usd_quote()
    scenario_malformed_pair()
    scenario_independence()

    print(f"\n{'=' * 70}")
    print(f"Activation 11.2 Forex pip policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())