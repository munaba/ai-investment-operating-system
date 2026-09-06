"""Activation 11.7 -- Forex order preview composition acceptance test.

Exercises ``Business.forex_order_preview.preview_forex_order`` (and its
``ForexOrderPreview`` result) directly and in isolation: pure,
dependency-free unit/composition tests only. No database, no CLI, no
network, no broker, no ``PaperTradingEngine``, no ``Trade``/
``Position`` creation -- this module is not wired into any production
order/account path yet (see ``Business.forex_order_preview`` module
docstring).

Required test cases (see Activation 11.7 brief):

    A. BUY preview (EUR/USD)
    B. SELL preview (EUR/USD), same magnitude, opposite direction
    C. GBP/USD, pair-independent composition
    D. Invalid BUY stop (at/above entry) rejected
    E. Invalid SELL stop (at/below entry) rejected
    F. Unsupported pair (EUR/JPY) rejected
    G. Invalid quantity (zero/negative) rejected
    H. Invalid entry/stop (zero/negative) rejected
    I. Decimal precision
    J. Result immutability
    K. Policy composition -- preview values match the underlying
       policy functions' own return values (not a re-implementation)

Run directly:
``python Tests/test_activation11_7_forex_order_preview.py`` -- no
external test framework required, matching every other
``Tests/test_*.py`` script in this suite.
"""

from __future__ import annotations

import dataclasses
import sys
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.forex_margin_policy import calculate_required_margin  # noqa: E402
from Business.forex_max_loss_policy import calculate_maximum_loss  # noqa: E402
from Business.forex_order_preview import (  # noqa: E402
    ForexOrderPreview,
    preview_forex_order,
)
from Business.forex_pip_policy import calculate_pip_value, get_pip_size  # noqa: E402
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
# A -- BUY preview
# ---------------------------------------------------------------------------


def scenario_a_buy_preview() -> None:
    print("\n[A] BUY preview (EUR/USD)")
    preview = preview_forex_order("EUR/USD", "BUY", 1.1000, 1.0950, 10_000)

    check(isinstance(preview, ForexOrderPreview), "A: preview_forex_order returns a ForexOrderPreview")
    check(preview.pair == "EUR/USD", f"A: pair == 'EUR/USD' (got {preview.pair})")
    check(preview.side == "BUY", f"A: side == 'BUY' (got {preview.side})")
    check(preview.entry_price == Decimal("1.1000"), f"A: entry_price echoed (got {preview.entry_price})")
    check(preview.stop_loss == Decimal("1.0950"), f"A: stop_loss echoed (got {preview.stop_loss})")
    check(preview.quantity == Decimal("10000"), f"A: quantity echoed (got {preview.quantity})")
    check(preview.pip_size == Decimal("0.0001"), f"A: pip_size == 0.0001 (got {preview.pip_size})")
    check(preview.pip_value == Decimal("1.00"), f"A: pip_value == 1.00 USD (got {preview.pip_value})")
    check(
        preview.required_margin == Decimal("11000.00"),
        f"A: required_margin == 11,000.00 USD (got {preview.required_margin})",
    )
    check(preview.maximum_loss == Decimal("50.00"), f"A: maximum_loss == 50.00 USD (got {preview.maximum_loss})")


# ---------------------------------------------------------------------------
# B -- SELL preview
# ---------------------------------------------------------------------------


def scenario_b_sell_preview() -> None:
    print("\n[B] SELL preview (EUR/USD), same magnitude opposite direction")
    preview = preview_forex_order("EUR/USD", "SELL", 1.1000, 1.1050, 10_000)

    check(preview.side == "SELL", f"B: side == 'SELL' (got {preview.side})")
    check(preview.maximum_loss == Decimal("50.00"), f"B: maximum_loss == 50.00 USD (got {preview.maximum_loss})")
    check(
        preview.required_margin == Decimal("11000.00"),
        f"B: required_margin unaffected by side (got {preview.required_margin})",
    )

    print("  lower-case side tolerated")
    preview_lower = preview_forex_order("EUR/USD", "sell", 1.1000, 1.1050, 10_000)
    check(preview_lower.side == "SELL", f"B: lower-case 'sell' normalizes to 'SELL' (got {preview_lower.side})")


# ---------------------------------------------------------------------------
# C -- GBP/USD, pair-independent composition
# ---------------------------------------------------------------------------


def scenario_c_gbp_usd() -> None:
    print("\n[C] GBP/USD pair-independent composition")
    preview = preview_forex_order("GBP/USD", "BUY", 1.2500, 1.2460, 25_000)

    check(preview.pair == "GBP/USD", f"C: pair == 'GBP/USD' (got {preview.pair})")
    check(preview.pip_value == Decimal("2.50"), f"C: GBP/USD pip_value == 2.50 USD (got {preview.pip_value})")
    check(
        preview.required_margin == Decimal("31250.00"),
        f"C: GBP/USD required_margin == 31,250.00 USD (got {preview.required_margin})",
    )
    check(preview.maximum_loss == Decimal("100.00"), f"C: GBP/USD maximum_loss == 100.00 USD (got {preview.maximum_loss})")


# ---------------------------------------------------------------------------
# D/E -- invalid stop-loss direction
# ---------------------------------------------------------------------------


def scenario_de_invalid_stop_direction() -> None:
    print("\n[D] Invalid BUY stop (at/above entry) rejected")
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", 1.1000, 1.1050, 10_000),
        "D: BUY stop above entry raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", 1.1000, 1.1000, 10_000),
        "D: BUY stop equal to entry raises ValidationError",
    )

    print("\n[E] Invalid SELL stop (at/below entry) rejected")
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "SELL", 1.1000, 1.0950, 10_000),
        "E: SELL stop below entry raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "SELL", 1.1000, 1.1000, 10_000),
        "E: SELL stop equal to entry raises ValidationError",
    )


# ---------------------------------------------------------------------------
# F -- unsupported pair
# ---------------------------------------------------------------------------


def scenario_f_unsupported_pair() -> None:
    print("\n[F] Unsupported pair (EUR/JPY) rejected")
    _expect_validation_error(
        lambda: preview_forex_order("EUR/JPY", "BUY", 150.00, 149.50, 10_000),
        "F: EUR/JPY (non-USD quote) raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("USD/JPY", "BUY", 150.00, 149.50, 10_000),
        "F: USD/JPY (non-USD quote) raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("NOTAPAIR", "BUY", 1.1000, 1.0950, 10_000),
        "F: malformed pair raises ValidationError",
    )


# ---------------------------------------------------------------------------
# G -- invalid quantity
# ---------------------------------------------------------------------------


def scenario_g_invalid_quantity() -> None:
    print("\n[G] Invalid quantity (zero/negative) rejected")
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", 1.1000, 1.0950, 0),
        "G: zero quantity raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", 1.1000, 1.0950, -10_000),
        "G: negative quantity raises ValidationError",
    )


# ---------------------------------------------------------------------------
# H -- invalid entry/stop
# ---------------------------------------------------------------------------


def scenario_h_invalid_prices() -> None:
    print("\n[H] Invalid entry/stop (zero/negative) rejected")
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", 0, 1.0950, 10_000),
        "H: zero entry_price raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", -1.1000, 1.0950, 10_000),
        "H: negative entry_price raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", 1.1000, 0, 10_000),
        "H: zero stop_loss raises ValidationError",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", 1.1000, -1.0950, 10_000),
        "H: negative stop_loss raises ValidationError",
    )


# ---------------------------------------------------------------------------
# I -- Decimal precision
# ---------------------------------------------------------------------------


def scenario_i_decimal_precision() -> None:
    print("\n[I] Decimal precision (binary-float-awkward inputs)")
    preview = preview_forex_order("EUR/USD", "BUY", 1.10001, 1.09991, 33_333)

    check(preview.pip_value == Decimal("3.3333"), f"I: pip_value exact (got {preview.pip_value})")
    check(
        preview.required_margin == Decimal("1.10001") * Decimal("33333"),
        f"I: required_margin exact (got {preview.required_margin})",
    )
    check(preview.maximum_loss == Decimal("3.3333"), f"I: maximum_loss exact (got {preview.maximum_loss})")
    check(isinstance(preview.pip_value, Decimal), "I: pip_value is a Decimal")
    check(isinstance(preview.required_margin, Decimal), "I: required_margin is a Decimal")
    check(isinstance(preview.maximum_loss, Decimal), "I: maximum_loss is a Decimal")


# ---------------------------------------------------------------------------
# J -- result immutability
# ---------------------------------------------------------------------------


def scenario_j_immutability() -> None:
    print("\n[J] Result immutability")
    preview = preview_forex_order("EUR/USD", "BUY", 1.1000, 1.0950, 10_000)

    for field_name, bad_value in (
        ("pip_value", Decimal("999.99")),
        ("required_margin", Decimal("0")),
        ("maximum_loss", Decimal("0")),
        ("pair", "GBP/USD"),
        ("side", "SELL"),
    ):
        try:
            setattr(preview, field_name, bad_value)
        except dataclasses.FrozenInstanceError:
            check(True, f"J: mutating '{field_name}' raises FrozenInstanceError")
        except AttributeError:
            check(True, f"J: mutating '{field_name}' raises AttributeError (frozen dataclass)")
        else:
            check(False, f"J: mutating '{field_name}' raises FrozenInstanceError (no error raised)")

    check(preview.maximum_loss == Decimal("50.00"), "J: original maximum_loss unchanged after mutation attempts")


# ---------------------------------------------------------------------------
# K -- policy composition (not re-implemented)
# ---------------------------------------------------------------------------


def scenario_k_policy_composition() -> None:
    print("\n[K] Policy composition -- preview matches underlying policy calls directly")

    pair, side, entry, stop, qty = "GBP/USD", "BUY", 1.3000, 1.2900, 50_000
    preview = preview_forex_order(pair, side, entry, stop, qty)

    expected_pip_size = get_pip_size(pair)
    expected_pip_value = calculate_pip_value(pair, qty)
    expected_margin = calculate_required_margin(pair, entry, qty)
    expected_max_loss = calculate_maximum_loss(pair, entry, stop, qty)

    check(preview.pip_size == expected_pip_size, "K: preview.pip_size == forex_pip_policy.get_pip_size(...)")
    check(
        preview.pip_value == expected_pip_value,
        "K: preview.pip_value == forex_pip_policy.calculate_pip_value(...)",
    )
    check(
        preview.required_margin == expected_margin,
        "K: preview.required_margin == forex_margin_policy.calculate_required_margin(...)",
    )
    check(
        preview.maximum_loss == expected_max_loss,
        "K: preview.maximum_loss == forex_max_loss_policy.calculate_maximum_loss(...)",
    )

    # Distinct, deliberately-chosen values per policy rule out a
    # coincidental match (e.g. a re-implemented formula that happens
    # to agree only for round numbers).
    check(expected_pip_value == Decimal("5.00"), f"K: sanity -- pip_value 5.00 (got {expected_pip_value})")
    check(expected_margin == Decimal("65000.00"), f"K: sanity -- margin 65000.00 (got {expected_margin})")
    check(expected_max_loss == Decimal("500.00"), f"K: sanity -- max_loss 500.00 (got {expected_max_loss})")


def main() -> int:
    scenario_a_buy_preview()
    scenario_b_sell_preview()
    scenario_c_gbp_usd()
    scenario_de_invalid_stop_direction()
    scenario_f_unsupported_pair()
    scenario_g_invalid_quantity()
    scenario_h_invalid_prices()
    scenario_i_decimal_precision()
    scenario_j_immutability()
    scenario_k_policy_composition()

    print(f"\n{'=' * 70}")
    print(f"Activation 11.7 Forex order preview: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())