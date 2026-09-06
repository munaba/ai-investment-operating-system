"""Activation 11.8 -- Forex numerical reconciliation proof.

This is NOT ``Business.reconciliation_engine`` (the production
database-reconciliation engine) and does not call it. There is no DB
state to reconcile here -- this is a pure, read-only proof that the
mathematical state ``Business.forex_order_preview.preview_forex_order``
composes (pip value, stop-loss direction, maximum loss, required
margin) is internally coherent, ahead of any later Activation wiring
that database reconciliation. See ``Business.forex_order_preview``
module docstring and the Activation 11 Acceptance Gate ("Margin, pip
value, stop-loss, and maximum loss must be proven correct through
numerical tests and reconciliation").

No database, no CLI, no network, no broker, no ``PaperTradingEngine``.
No production code is imported for anything other than the four
already-LOCKED, already-tested Activation 11.2/11.4/11.5/11.6/11.7
modules:

    * ``Business.forex_pip_policy``
    * ``Business.forex_stop_loss_policy``
    * ``Business.forex_max_loss_policy``
    * ``Business.forex_margin_policy``
    * ``Business.forex_order_preview``

Per the Activation 11.8 brief, every expected value in this file is
computed INDEPENDENTLY of those production functions -- straight from
the LOCKED formulas themselves (``Docs/ACTIVATION 11/
ACTIVATION_11_1_FOREX_POLICY_DECISION.md``), using this test file's own
local ``Decimal`` arithmetic. This intentionally duplicates the
*arithmetic* (that is the entire point of an independent numerical
proof) but never the *validation* -- every invalid scenario below is
still expected to fail through the real, unmodified policy functions,
not through a parallel check written in this file.

Run directly:
``python Tests/test_activation11_8_forex_numerical_reconciliation.py``
-- no external test framework required, matching every other
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

from Business.forex_order_preview import ForexOrderPreview, preview_forex_order  # noqa: E402
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
# Independent expected-value arithmetic (LOCKED formulas, own Decimal
# math -- NOT calls into the production policy modules).
# ---------------------------------------------------------------------------

#: Pip size for any USD-quoted, non-JPY-quoted pair (Decision C). Both
#: pairs used in this file (EUR/USD, GBP/USD) fall under this rule.
_EXPECTED_PIP_SIZE = Decimal("0.0001")


def _expected_pip_value(quantity: Decimal) -> Decimal:
    """Independent restatement of Decision D: pip_size * quantity."""
    return _EXPECTED_PIP_SIZE * quantity


def _expected_pip_distance(entry_price: Decimal, stop_loss: Decimal) -> Decimal:
    """Independent restatement of Invariant 2: abs(entry - stop) / pip_size."""
    return abs(entry_price - stop_loss) / _EXPECTED_PIP_SIZE


def _expected_maximum_loss(entry_price: Decimal, stop_loss: Decimal, quantity: Decimal) -> Decimal:
    """Independent restatement of Decision H: pip_distance * pip_value."""
    return _expected_pip_distance(entry_price, stop_loss) * _expected_pip_value(quantity)


def _expected_required_margin(entry_price: Decimal, quantity: Decimal) -> Decimal:
    """Independent restatement of Decision B (1:1): entry_price * quantity."""
    return entry_price * quantity


@dataclasses.dataclass(frozen=True)
class _Scenario:
    label: str
    pair: str
    side: str
    entry_price: Decimal
    stop_loss: Decimal
    quantity: Decimal


# ---------------------------------------------------------------------------
# Scenario table -- both supported pairs, both sides, three quantities
# each, deterministic clean pip distances.
# ---------------------------------------------------------------------------

_SCENARIOS: tuple[_Scenario, ...] = (
    # EUR/USD
    _Scenario("1: EUR/USD BUY 10k", "EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000")),
    _Scenario("2: EUR/USD BUY 25k", "EUR/USD", "BUY", Decimal("1.2000"), Decimal("1.1950"), Decimal("25000")),
    _Scenario("3: EUR/USD BUY 100k", "EUR/USD", "BUY", Decimal("1.3000"), Decimal("1.2900"), Decimal("100000")),
    _Scenario("4: EUR/USD SELL 10k", "EUR/USD", "SELL", Decimal("1.1000"), Decimal("1.1050"), Decimal("10000")),
    _Scenario("5: EUR/USD SELL 25k", "EUR/USD", "SELL", Decimal("1.2000"), Decimal("1.2050"), Decimal("25000")),
    _Scenario("6: EUR/USD SELL 100k", "EUR/USD", "SELL", Decimal("1.3000"), Decimal("1.3100"), Decimal("100000")),
    # GBP/USD
    _Scenario("7: GBP/USD BUY 10k", "GBP/USD", "BUY", Decimal("1.2500"), Decimal("1.2450"), Decimal("10000")),
    _Scenario("8: GBP/USD BUY 25k", "GBP/USD", "BUY", Decimal("1.2500"), Decimal("1.2460"), Decimal("25000")),
    _Scenario("9: GBP/USD BUY 100k", "GBP/USD", "BUY", Decimal("1.3000"), Decimal("1.2900"), Decimal("100000")),
    _Scenario("10: GBP/USD SELL 10k", "GBP/USD", "SELL", Decimal("1.2500"), Decimal("1.2550"), Decimal("10000")),
    _Scenario("11: GBP/USD SELL 25k", "GBP/USD", "SELL", Decimal("1.2500"), Decimal("1.2540"), Decimal("25000")),
    _Scenario("12: GBP/USD SELL 100k", "GBP/USD", "SELL", Decimal("1.3000"), Decimal("1.3100"), Decimal("100000")),
)


# ---------------------------------------------------------------------------
# Invariants 1-5 -- proven across the full scenario table
# ---------------------------------------------------------------------------


def scenario_table_invariants() -> None:
    print(f"\n[Table] Invariants 1-5 across {len(_SCENARIOS)} scenarios (both pairs, both sides)")
    for scenario in _SCENARIOS:
        preview = preview_forex_order(
            scenario.pair,
            scenario.side,
            scenario.entry_price,
            scenario.stop_loss,
            scenario.quantity,
        )

        expected_pip_value = _expected_pip_value(scenario.quantity)
        expected_pip_distance = _expected_pip_distance(scenario.entry_price, scenario.stop_loss)
        expected_maximum_loss = _expected_maximum_loss(scenario.entry_price, scenario.stop_loss, scenario.quantity)
        expected_required_margin = _expected_required_margin(scenario.entry_price, scenario.quantity)

        # Invariant 1 -- pip value + currency.
        check(preview.pip_size == _EXPECTED_PIP_SIZE, f"{scenario.label}: pip_size == {_EXPECTED_PIP_SIZE}")
        check(
            preview.pip_value == expected_pip_value,
            f"{scenario.label}: pip_value == pip_size * quantity (got {preview.pip_value}, expected {expected_pip_value})",
        )

        # Invariant 2 -- pip distance is a clean Decimal for this table.
        actual_pip_distance = abs(preview.entry_price - preview.stop_loss) / preview.pip_size
        check(
            actual_pip_distance == expected_pip_distance,
            f"{scenario.label}: pip_distance == abs(entry-stop)/pip_size (got {actual_pip_distance})",
        )
        check(
            actual_pip_distance == actual_pip_distance.to_integral_value(),
            f"{scenario.label}: pip_distance is a clean integral Decimal (got {actual_pip_distance})",
        )

        # Invariant 3 -- maximum loss == pip_distance * pip_value.
        check(
            preview.maximum_loss == expected_maximum_loss,
            f"{scenario.label}: maximum_loss == pip_distance * pip_value "
            f"(got {preview.maximum_loss}, expected {expected_maximum_loss})",
        )

        # Invariant 4 -- required margin == entry_price * quantity, at
        # 1:1, independent of maximum_loss.
        check(
            preview.required_margin == expected_required_margin,
            f"{scenario.label}: required_margin == entry_price * quantity "
            f"(got {preview.required_margin}, expected {expected_required_margin})",
        )
        check(
            preview.required_margin != preview.maximum_loss,
            f"{scenario.label}: required_margin and maximum_loss remain distinct",
        )

        # Invariant 5 -- stop-loss direction, restated independently.
        if scenario.side == "BUY":
            check(preview.stop_loss < preview.entry_price, f"{scenario.label}: BUY stop_loss < entry_price")
        else:
            check(preview.stop_loss > preview.entry_price, f"{scenario.label}: SELL stop_loss > entry_price")


# ---------------------------------------------------------------------------
# A -- margin is not maximum loss
# ---------------------------------------------------------------------------


def scenario_a_margin_not_max_loss() -> None:
    print("\n[A] Margin is NOT maximum loss")
    preview = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000"))

    check(preview.required_margin == Decimal("11000.00"), f"A: required_margin == 11000.00 (got {preview.required_margin})")
    check(preview.maximum_loss == Decimal("50.00"), f"A: maximum_loss == 50.00 (got {preview.maximum_loss})")
    check(preview.required_margin != preview.maximum_loss, "A: required_margin != maximum_loss")
    check(
        preview.required_margin == _expected_required_margin(preview.entry_price, preview.quantity),
        "A: required_margin matches its own independent formula",
    )
    check(
        preview.maximum_loss == _expected_maximum_loss(preview.entry_price, preview.stop_loss, preview.quantity),
        "A: maximum_loss matches its own independent formula",
    )


# ---------------------------------------------------------------------------
# B -- quantity scaling
# ---------------------------------------------------------------------------


def scenario_b_quantity_scaling() -> None:
    print("\n[B] Scaling quantity doubles pip_value/maximum_loss/required_margin, pip_size unchanged")
    base = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000"))
    doubled = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("20000"))

    check(doubled.pip_value == base.pip_value * 2, f"B: pip_value doubles (got {base.pip_value} -> {doubled.pip_value})")
    check(
        doubled.maximum_loss == base.maximum_loss * 2,
        f"B: maximum_loss doubles (got {base.maximum_loss} -> {doubled.maximum_loss})",
    )
    check(
        doubled.required_margin == base.required_margin * 2,
        f"B: required_margin doubles (got {base.required_margin} -> {doubled.required_margin})",
    )
    check(doubled.pip_size == base.pip_size, f"B: pip_size unchanged (got {base.pip_size} -> {doubled.pip_size})")


# ---------------------------------------------------------------------------
# C -- stop-distance scaling
# ---------------------------------------------------------------------------


def scenario_c_stop_distance_scaling() -> None:
    print("\n[C] Doubling stop distance doubles maximum_loss; pip_value/required_margin unchanged")
    # 50-pip base distance.
    base = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000"))
    # 100-pip distance, same entry/quantity.
    doubled_distance = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0900"), Decimal("10000"))

    check(
        doubled_distance.maximum_loss == base.maximum_loss * 2,
        f"C: maximum_loss doubles with stop distance (got {base.maximum_loss} -> {doubled_distance.maximum_loss})",
    )
    check(
        doubled_distance.pip_value == base.pip_value,
        f"C: pip_value unaffected by stop distance (got {base.pip_value} -> {doubled_distance.pip_value})",
    )
    check(
        doubled_distance.required_margin == base.required_margin,
        f"C: required_margin unaffected by stop distance (got {base.required_margin} -> {doubled_distance.required_margin})",
    )


# ---------------------------------------------------------------------------
# D -- entry price scaling
# ---------------------------------------------------------------------------


def scenario_d_entry_price_scaling() -> None:
    print("\n[D] Changing entry price changes required_margin; maximum_loss follows stop distance, not entry level")
    low_entry = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000"))
    high_entry = preview_forex_order("EUR/USD", "BUY", Decimal("1.5000"), Decimal("1.4950"), Decimal("10000"))

    check(
        high_entry.required_margin != low_entry.required_margin,
        f"D: required_margin changes with entry price (got {low_entry.required_margin} -> {high_entry.required_margin})",
    )
    check(
        high_entry.required_margin == Decimal("1.5000") * Decimal("10000"),
        f"D: required_margin == new entry_price * quantity (got {high_entry.required_margin})",
    )
    # Same 50-pip stop distance at both entry levels -> identical
    # maximum_loss, proving maximum_loss tracks stop DISTANCE, not the
    # absolute entry price level.
    check(
        high_entry.maximum_loss == low_entry.maximum_loss,
        f"D: maximum_loss unaffected by entry-price level given equal stop distance "
        f"(got {low_entry.maximum_loss} -> {high_entry.maximum_loss})",
    )
    check(high_entry.maximum_loss == Decimal("50.00"), f"D: maximum_loss still 50.00 at higher entry (got {high_entry.maximum_loss})")

    # A genuinely wider stop distance at the higher entry level DOES
    # change maximum_loss, ruling out a hardcoded/stuck value.
    high_entry_wider_stop = preview_forex_order("EUR/USD", "BUY", Decimal("1.5000"), Decimal("1.4900"), Decimal("10000"))
    check(
        high_entry_wider_stop.maximum_loss != high_entry.maximum_loss,
        "D: maximum_loss changes when stop distance actually widens",
    )


# ---------------------------------------------------------------------------
# Directional symmetry
# ---------------------------------------------------------------------------


def scenario_directional_symmetry() -> None:
    print("\n[Symmetry] BUY/SELL with symmetric stop distance produce identical maximum_loss")
    buy = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000"))
    sell = preview_forex_order("EUR/USD", "SELL", Decimal("1.1000"), Decimal("1.1050"), Decimal("10000"))

    check(buy.maximum_loss == sell.maximum_loss, f"Symmetry: maximum_loss(BUY) == maximum_loss(SELL) ({buy.maximum_loss})")
    check(buy.side == "BUY" and sell.side == "SELL", "Symmetry: sides remain distinct and correctly labeled")
    check(buy.stop_loss < buy.entry_price, "Symmetry: BUY stop below entry")
    check(sell.stop_loss > sell.entry_price, "Symmetry: SELL stop above entry")
    check(
        buy.required_margin == sell.required_margin,
        f"Symmetry: required_margin identical for BUY/SELL at same entry/quantity ({buy.required_margin})",
    )


# ---------------------------------------------------------------------------
# Invalid scenarios -- must reject through the real, unmodified policies
# ---------------------------------------------------------------------------


def scenario_invalid_table() -> None:
    print("\n[Invalid] Negative-scenario table -- each must fail through the existing pure policies")
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.1050"), Decimal("10000")),
        "Invalid: BUY stop above entry rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.1000"), Decimal("10000")),
        "Invalid: BUY stop equal entry rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "SELL", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000")),
        "Invalid: SELL stop below entry rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "SELL", Decimal("1.1000"), Decimal("1.1000"), Decimal("10000")),
        "Invalid: SELL stop equal entry rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/JPY", "BUY", Decimal("150.00"), Decimal("149.50"), Decimal("10000")),
        "Invalid: unsupported pair (EUR/JPY) rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("0")),
        "Invalid: zero quantity rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("-10000")),
        "Invalid: negative quantity rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", Decimal("0"), Decimal("1.0950"), Decimal("10000")),
        "Invalid: non-positive entry rejected",
    )
    _expect_validation_error(
        lambda: preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("0"), Decimal("10000")),
        "Invalid: non-positive stop rejected",
    )


# ---------------------------------------------------------------------------
# Decimal precision
# ---------------------------------------------------------------------------


def scenario_decimal_precision() -> None:
    print("\n[Decimal] Binary-float-awkward inputs -- exact Decimal equality, no tolerance")
    # 33,333 units is the classic binary-float-lossy quantity already
    # used by the underlying policy test suites.
    preview_1 = preview_forex_order("EUR/USD", "BUY", Decimal("1.10001"), Decimal("1.09991"), Decimal("33333"))
    expected_pip_value_1 = _expected_pip_value(Decimal("33333"))
    expected_max_loss_1 = _expected_maximum_loss(Decimal("1.10001"), Decimal("1.09991"), Decimal("33333"))
    expected_margin_1 = _expected_required_margin(Decimal("1.10001"), Decimal("33333"))

    check(preview_1.pip_value == expected_pip_value_1 == Decimal("3.3333"), f"Decimal 1: pip_value exact (got {preview_1.pip_value})")
    check(preview_1.maximum_loss == expected_max_loss_1 == Decimal("3.3333"), f"Decimal 1: maximum_loss exact (got {preview_1.maximum_loss})")
    check(preview_1.required_margin == expected_margin_1, f"Decimal 1: required_margin exact (got {preview_1.required_margin})")

    # A second, differently-shaped case (fractional-pip price, GBP/USD).
    preview_2 = preview_forex_order("GBP/USD", "SELL", Decimal("1.25005"), Decimal("1.25015"), Decimal("10000"))
    expected_pip_value_2 = _expected_pip_value(Decimal("10000"))
    expected_max_loss_2 = _expected_maximum_loss(Decimal("1.25005"), Decimal("1.25015"), Decimal("10000"))
    expected_margin_2 = _expected_required_margin(Decimal("1.25005"), Decimal("10000"))

    check(preview_2.pip_value == expected_pip_value_2 == Decimal("1.00"), f"Decimal 2: pip_value exact (got {preview_2.pip_value})")
    check(preview_2.maximum_loss == expected_max_loss_2 == Decimal("1.00"), f"Decimal 2: maximum_loss exact (got {preview_2.maximum_loss})")
    check(preview_2.required_margin == expected_margin_2, f"Decimal 2: required_margin exact (got {preview_2.required_margin})")

    for preview in (preview_1, preview_2):
        check(isinstance(preview.pip_value, Decimal), "Decimal: pip_value is a Decimal, never a float")
        check(isinstance(preview.maximum_loss, Decimal), "Decimal: maximum_loss is a Decimal, never a float")
        check(isinstance(preview.required_margin, Decimal), "Decimal: required_margin is a Decimal, never a float")


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def scenario_immutability() -> None:
    print("\n[Immutability] ForexOrderPreview remains frozen for reconciliation safety")
    preview = preview_forex_order("EUR/USD", "BUY", Decimal("1.1000"), Decimal("1.0950"), Decimal("10000"))
    check(isinstance(preview, ForexOrderPreview), "Immutability: result is a ForexOrderPreview")

    for field_name, bad_value in (
        ("pip_value", Decimal("0")),
        ("maximum_loss", Decimal("0")),
        ("required_margin", Decimal("0")),
        ("pip_size", Decimal("0")),
    ):
        try:
            setattr(preview, field_name, bad_value)
        except dataclasses.FrozenInstanceError:
            check(True, f"Immutability: mutating '{field_name}' raises FrozenInstanceError")
        except AttributeError:
            check(True, f"Immutability: mutating '{field_name}' raises AttributeError (frozen dataclass)")
        else:
            check(False, f"Immutability: mutating '{field_name}' raises FrozenInstanceError (no error raised)")

    check(preview.maximum_loss == Decimal("50.00"), "Immutability: value unchanged after mutation attempts")


def main() -> int:
    scenario_table_invariants()
    scenario_a_margin_not_max_loss()
    scenario_b_quantity_scaling()
    scenario_c_stop_distance_scaling()
    scenario_d_entry_price_scaling()
    scenario_directional_symmetry()
    scenario_invalid_table()
    scenario_decimal_precision()
    scenario_immutability()

    print(f"\n{'=' * 70}")
    print(f"Activation 11.8 Forex numerical reconciliation proof: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())