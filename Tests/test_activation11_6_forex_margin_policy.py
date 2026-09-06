"""Activation 11.6 -- Forex required-margin policy acceptance test.

Exercises ``Business.forex_margin_policy.calculate_required_margin``
directly and in isolation: pure, dependency-free unit tests only. No
database, no CLI, no network, no broker, no paper-trading engine, no
reconciliation -- this module is not wired into any production
order/account path yet (see ``Business.forex_margin_policy`` module
docstring and Activation 11.1's locked Decision B).

Required test cases (see Activation 11.6 brief):

    A. EUR/USD, 10k -> 11,000.00 USD
    B. EUR/USD, 100k -> 110,000.00 USD
    C. GBP/USD, independent calculation
    D. Decimal precision
    E. Zero quantity rejected
    F. Negative quantity rejected
    G. Zero price rejected
    H. Negative price rejected
    I. Unsupported pair rejected (EUR/JPY, USD/JPY, USD/CHF)
    J. Malformed pair rejected
    K. No leverage parameter
    L. Independence from the maximum-loss policy

Run directly:
``python Tests/test_activation11_6_forex_margin_policy.py`` -- no
external test framework required, matching every other
``Tests/test_*.py`` script in this suite.
"""

from __future__ import annotations

import inspect
import sys
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.forex_margin_policy import (  # noqa: E402
    REQUIRED_MARGIN_CURRENCY,
    calculate_required_margin,
)
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
# A/B -- EUR/USD locked examples
# ---------------------------------------------------------------------------


def scenario_a_eur_usd_10k() -> None:
    print("\n[A] EUR/USD, 10k units -> 11,000.00 USD")
    value = calculate_required_margin("EUR/USD", 1.1000, 10_000)
    check(value == Decimal("11000.00"), f"A: EUR/USD 10k required margin == 11000.00 USD (got {value})")
    check(isinstance(value, Decimal), "A: calculate_required_margin returns a Decimal, not a float")


def scenario_b_eur_usd_100k() -> None:
    print("\n[B] EUR/USD, 100k units -> 110,000.00 USD")
    value = calculate_required_margin("EUR/USD", 1.1000, 100_000)
    check(value == Decimal("110000.00"), f"B: EUR/USD 100k required margin == 110000.00 USD (got {value})")


# ---------------------------------------------------------------------------
# C -- GBP/USD independent calculation
# ---------------------------------------------------------------------------


def scenario_c_gbp_usd_independent() -> None:
    print("\n[C] GBP/USD independent calculation (not EUR/USD-hardcoded)")
    value = calculate_required_margin("GBP/USD", 1.2500, 25_000)
    check(value == Decimal("31250.00"), f"C: GBP/USD 25k @ 1.2500 required margin == 31250.00 USD (got {value})")

    value2 = calculate_required_margin("GBP/USD", 1.3000, 50_000)
    check(value2 == Decimal("65000.00"), f"C: GBP/USD 50k @ 1.3000 required margin == 65000.00 USD (got {value2})")
    check(value != value2, "C: two different GBP/USD scenarios produce different results (not hardcoded)")

    print("  Currency label")
    check(REQUIRED_MARGIN_CURRENCY == "USD", f"C: REQUIRED_MARGIN_CURRENCY == 'USD' (got {REQUIRED_MARGIN_CURRENCY})")


# ---------------------------------------------------------------------------
# D -- Decimal precision
# ---------------------------------------------------------------------------


def scenario_d_decimal_precision() -> None:
    print("\n[D] Decimal precision (binary-float-awkward inputs)")
    # 1.10001 * 33,333 is not exactly representable via naive binary
    # float multiplication -- Decimal(str(x)) arithmetic must be exact.
    value = calculate_required_margin("EUR/USD", 1.10001, 33_333)
    check(
        value == Decimal("1.10001") * Decimal("33333"),
        f"D: Decimal precision preserved exactly (got {value})",
    )
    check(isinstance(value, Decimal), "D: result is a Decimal")

    value2 = calculate_required_margin("GBP/USD", 1.25005, 10_000)
    check(value2 == Decimal("12500.50"), f"D: fractional-price case exact (got {value2})")


# ---------------------------------------------------------------------------
# E/F -- invalid quantity
# ---------------------------------------------------------------------------


def scenario_ef_invalid_quantity() -> None:
    print("\n[E] Zero quantity rejected")
    _expect_validation_error(
        lambda: calculate_required_margin("EUR/USD", 1.1000, 0),
        "E: zero quantity raises ValidationError",
    )

    print("\n[F] Negative quantity rejected")
    _expect_validation_error(
        lambda: calculate_required_margin("EUR/USD", 1.1000, -10_000),
        "F: negative quantity raises ValidationError",
    )


# ---------------------------------------------------------------------------
# G/H -- invalid price
# ---------------------------------------------------------------------------


def scenario_gh_invalid_price() -> None:
    print("\n[G] Zero price rejected")
    _expect_validation_error(
        lambda: calculate_required_margin("EUR/USD", 0, 10_000),
        "G: zero price raises ValidationError",
    )

    print("\n[H] Negative price rejected")
    _expect_validation_error(
        lambda: calculate_required_margin("EUR/USD", -1.1000, 10_000),
        "H: negative price raises ValidationError",
    )

    print("\n[G/H] Non-numeric price rejected")
    _expect_validation_error(
        lambda: calculate_required_margin("EUR/USD", "1.1000", 10_000),
        "G: string price raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_required_margin("EUR/USD", None, 10_000),
        "H: None price raises ValidationError",
    )


# ---------------------------------------------------------------------------
# I/J -- unsupported / malformed pair
# ---------------------------------------------------------------------------


def scenario_ij_unsupported_pair() -> None:
    print("\n[I] Unsupported non-USD pair rejected")
    _expect_validation_error(
        lambda: calculate_required_margin("EUR/JPY", 150.00, 10_000),
        "I: EUR/JPY (non-USD quote) raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_required_margin("USD/JPY", 150.00, 10_000),
        "I: USD/JPY (non-USD quote) raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_required_margin("USD/CHF", 0.9000, 10_000),
        "I: USD/CHF (non-USD quote) raises ValidationError",
    )

    print("\n[J] Malformed pair rejected")
    _expect_validation_error(
        lambda: calculate_required_margin("NOTAPAIR", 1.1000, 10_000),
        "J: malformed pair raises ValidationError",
    )
    _expect_validation_error(
        lambda: calculate_required_margin("EU/USD", 1.1000, 10_000),
        "J: malformed (too-short base) pair raises ValidationError",
    )


# ---------------------------------------------------------------------------
# K -- no leverage parameter
# ---------------------------------------------------------------------------


def scenario_k_no_leverage_parameter() -> None:
    print("\n[K] No leverage parameter -- policy is intrinsically 1:1")
    signature = inspect.signature(calculate_required_margin)
    check("leverage" not in signature.parameters, "K: calculate_required_margin has no 'leverage' parameter")
    check(
        list(signature.parameters) == ["pair", "price", "quantity"],
        f"K: signature is exactly (pair, price, quantity) (got {list(signature.parameters)})",
    )

    try:
        calculate_required_margin("EUR/USD", 1.1000, 10_000, leverage=50)  # type: ignore[call-arg]
    except TypeError:
        check(True, "K: passing an arbitrary leverage= kwarg raises TypeError (not silently accepted)")
    else:
        check(False, "K: passing an arbitrary leverage= kwarg raises TypeError (no error raised)")

    # 1:1 means margin always equals full notional -- never a
    # fraction of it -- for any price/quantity pair.
    value = calculate_required_margin("EUR/USD", 2.0000, 1_000)
    check(value == Decimal("2000.00"), f"K: margin == full notional at 1:1 (got {value})")


# ---------------------------------------------------------------------------
# L -- independence from maximum-loss policy
# ---------------------------------------------------------------------------


def scenario_l_independence_from_max_loss() -> None:
    print("\n[L] Independence from the maximum-loss policy")
    margin = calculate_required_margin("EUR/USD", 1.1000, 10_000)
    max_loss = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)

    check(margin == Decimal("11000.00"), f"L: required margin unaffected by stop-loss concept (got {margin})")
    check(max_loss == Decimal("50.00"), f"L: maximum loss computed independently (got {max_loss})")
    check(margin != max_loss, "L: margin and maximum loss are different quantities, not interchangeable")

    # A prior maximum-loss call must not influence a subsequent margin
    # call (rules out any accidental shared/global state), and vice
    # versa.
    margin_again = calculate_required_margin("EUR/USD", 1.1000, 10_000)
    check(margin_again == margin, "L: margin result unaffected by an intervening maximum-loss call")

    _ = calculate_required_margin("EUR/USD", 1.5000, 1_000_000)
    max_loss_again = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)
    check(max_loss_again == max_loss, "L: maximum-loss result unaffected by an intervening large margin call")


def main() -> int:
    scenario_a_eur_usd_10k()
    scenario_b_eur_usd_100k()
    scenario_c_gbp_usd_independent()
    scenario_d_decimal_precision()
    scenario_ef_invalid_quantity()
    scenario_gh_invalid_price()
    scenario_ij_unsupported_pair()
    scenario_k_no_leverage_parameter()
    scenario_l_independence_from_max_loss()

    print(f"\n{'=' * 70}")
    print(f"Activation 11.6 Forex required-margin policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())