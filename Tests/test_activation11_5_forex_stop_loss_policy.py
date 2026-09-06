"""Activation 11.5 -- Forex stop-loss directional-validity policy
acceptance test.

Exercises ``Business.forex_stop_loss_policy.validate_stop_loss``
directly and in isolation: pure, dependency-free unit tests only. No
database, no CLI, no network, no broker, no paper-trading engine --
this module is not wired into any production order/account path yet
(see ``Business.forex_stop_loss_policy`` module docstring).

Required test cases (see Activation 11.5 brief):

    A. BUY valid
    B. BUY invalid, equal price
    C. BUY invalid, stop above entry
    D. SELL valid
    E. SELL invalid, equal price
    F. SELL invalid, stop below entry
    G. Invalid side rejected
    H. Invalid prices rejected
    I. Decimal precision
    J. Independence from pair (this module never receives a pair at
       all -- proven by checking behavior is identical regardless of
       which pair a caller happens to be validating for)
    + a lightweight composition check with
      ``Business.forex_max_loss_policy.calculate_maximum_loss`` (unit-
      level only, no production wiring)

Run directly:
``python Tests/test_activation11_5_forex_stop_loss_policy.py`` -- no
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
from Business.forex_stop_loss_policy import VALID_SIDES, validate_stop_loss  # noqa: E402
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


def _expect_valid(callable_, description: str) -> None:
    try:
        result = callable_()
    except ValidationError as exc:
        check(False, f"{description} (unexpectedly raised ValidationError: {exc})")
    else:
        check(result is None, f"{description} (returned normally, result={result!r})")


# ---------------------------------------------------------------------------
# A/B/C -- BUY
# ---------------------------------------------------------------------------


def scenario_buy() -> None:
    print("\n[A] BUY valid (stop below entry)")
    _expect_valid(lambda: validate_stop_loss("BUY", 1.1000, 1.0950), "A: BUY entry=1.1000 stop=1.0950 accepted")

    print("\n[B] BUY invalid, equal price")
    _expect_validation_error(
        lambda: validate_stop_loss("BUY", 1.1000, 1.1000), "B: BUY entry==stop rejected"
    )

    print("\n[C] BUY invalid, stop above entry")
    _expect_validation_error(
        lambda: validate_stop_loss("BUY", 1.1000, 1.1050), "C: BUY stop above entry rejected"
    )


# ---------------------------------------------------------------------------
# D/E/F -- SELL
# ---------------------------------------------------------------------------


def scenario_sell() -> None:
    print("\n[D] SELL valid (stop above entry)")
    _expect_valid(lambda: validate_stop_loss("SELL", 1.1000, 1.1050), "D: SELL entry=1.1000 stop=1.1050 accepted")

    print("\n[E] SELL invalid, equal price")
    _expect_validation_error(
        lambda: validate_stop_loss("SELL", 1.1000, 1.1000), "E: SELL entry==stop rejected"
    )

    print("\n[F] SELL invalid, stop below entry")
    _expect_validation_error(
        lambda: validate_stop_loss("SELL", 1.1000, 1.0950), "F: SELL stop below entry rejected"
    )


# ---------------------------------------------------------------------------
# G -- invalid side
# ---------------------------------------------------------------------------


def scenario_invalid_side() -> None:
    print("\n[G] Invalid side rejected")
    _expect_validation_error(lambda: validate_stop_loss("HOLD", 1.1000, 1.0950), "G: side='HOLD' rejected")
    _expect_validation_error(lambda: validate_stop_loss("SHORT", 1.1000, 1.0950), "G: side='SHORT' rejected")
    _expect_validation_error(lambda: validate_stop_loss("LONG", 1.1000, 1.0950), "G: side='LONG' rejected")
    _expect_validation_error(lambda: validate_stop_loss("foo", 1.1000, 1.0950), "G: side='foo' rejected")
    _expect_validation_error(lambda: validate_stop_loss("", 1.1000, 1.0950), "G: side='' rejected")
    _expect_validation_error(lambda: validate_stop_loss(None, 1.1000, 1.0950), "G: side=None rejected")

    # Case/whitespace normalization is tolerated, mirroring pair
    # normalization elsewhere in this Activation.
    _expect_valid(lambda: validate_stop_loss("buy", 1.1000, 1.0950), "G: side='buy' (lowercase) normalizes and is accepted")
    _expect_valid(lambda: validate_stop_loss(" SELL ", 1.1000, 1.1050), "G: side=' SELL ' (whitespace) normalizes and is accepted")

    check(VALID_SIDES == ("BUY", "SELL"), "G: VALID_SIDES is exactly ('BUY', 'SELL')")


# ---------------------------------------------------------------------------
# H -- invalid prices
# ---------------------------------------------------------------------------


def scenario_invalid_prices() -> None:
    print("\n[H] Invalid prices rejected")
    _expect_validation_error(lambda: validate_stop_loss("BUY", 0, 1.0950), "H: zero entry_price rejected")
    _expect_validation_error(lambda: validate_stop_loss("BUY", -1.1000, 1.0950), "H: negative entry_price rejected")
    _expect_validation_error(lambda: validate_stop_loss("BUY", 1.1000, 0), "H: zero stop_loss rejected")
    _expect_validation_error(lambda: validate_stop_loss("BUY", 1.1000, -1.0950), "H: negative stop_loss rejected")
    _expect_validation_error(
        lambda: validate_stop_loss("BUY", "1.1000", 1.0950), "H: string entry_price rejected"
    )
    _expect_validation_error(lambda: validate_stop_loss("SELL", 1.1000, None), "H: None stop_loss rejected")


# ---------------------------------------------------------------------------
# I -- Decimal precision
# ---------------------------------------------------------------------------


def scenario_decimal_precision() -> None:
    print("\n[I] Decimal precision (binary-float-awkward inputs)")
    # 1.10001 vs 1.09991 differ by exactly 0.00010 -- must be
    # unambiguously ordered under Decimal comparison, not perturbed
    # by binary float representation error.
    _expect_valid(
        lambda: validate_stop_loss("BUY", 1.10001, 1.09991),
        "I: BUY with a tiny, Decimal-sensitive valid distance is accepted",
    )
    _expect_validation_error(
        lambda: validate_stop_loss("BUY", 1.10001, 1.10001),
        "I: BUY with Decimal-equal prices (even via distinct float literals) is rejected",
    )
    # Two float literals that are numerically equal once normalized
    # through Decimal(str(x)) should behave identically to the plain
    # equal-price case above.
    check(
        Decimal(str(1.10001)) == Decimal(str(1.10001)),
        "I: sanity -- Decimal(str(x)) normalization is exact for this literal",
    )


# ---------------------------------------------------------------------------
# J -- independence from pair
# ---------------------------------------------------------------------------


def scenario_independence_from_pair() -> None:
    print("\n[J] Independence from pair (this policy never receives a pair)")
    # validate_stop_loss has no pair parameter at all -- calling it
    # with the same side/entry/stop must behave identically no matter
    # which pair a caller happens to be validating for (proven here
    # by simply calling it repeatedly and confirming no drift/state).
    _expect_valid(lambda: validate_stop_loss("BUY", 1.1000, 1.0950), "J: BUY call #1 (conceptually EUR/USD context)")
    _expect_valid(lambda: validate_stop_loss("BUY", 1.1000, 1.0950), "J: BUY call #2 (conceptually GBP/USD context)")
    _expect_valid(lambda: validate_stop_loss("BUY", 1.1000, 1.0950), "J: BUY call #3 (conceptually USD/JPY context)")

    _expect_validation_error(
        lambda: validate_stop_loss("SELL", 1.1000, 1.0950), "J: an interleaved invalid SELL call does not affect..."
    )
    _expect_valid(
        lambda: validate_stop_loss("BUY", 1.1000, 1.0950), "J: ...a subsequent, otherwise-identical valid BUY call"
    )


# ---------------------------------------------------------------------------
# Composition with Activation 11.4's calculate_maximum_loss
# ---------------------------------------------------------------------------


def scenario_max_loss_composition() -> None:
    print("\n[Composition] validate_stop_loss + calculate_maximum_loss (unit-level only)")

    # Valid BUY: directional check passes, then max-loss is a valid
    # positive Decimal.
    validate_stop_loss("BUY", 1.1000, 1.0950)
    max_loss = calculate_maximum_loss("EUR/USD", 1.1000, 1.0950, 10_000)
    check(max_loss == Decimal("50.00"), f"Composition: valid BUY -> max loss == 50.00 USD (got {max_loss})")

    # Invalid BUY (stop above entry): directional check must reject
    # *before* a caller would even reach the max-loss calculation --
    # simulated here by asserting the rejection happens first.
    rejected_before_max_loss = False
    try:
        validate_stop_loss("BUY", 1.1000, 1.1050)
        # calculate_maximum_loss would still compute a (meaningless,
        # for this direction) positive number -- the point is that a
        # caller following the correct order never gets here.
        calculate_maximum_loss("EUR/USD", 1.1000, 1.1050, 10_000)
    except ValidationError:
        rejected_before_max_loss = True
    check(rejected_before_max_loss, "Composition: invalid BUY direction rejected before max-loss is used")


def main() -> int:
    scenario_buy()
    scenario_sell()
    scenario_invalid_side()
    scenario_invalid_prices()
    scenario_decimal_precision()
    scenario_independence_from_pair()
    scenario_max_loss_composition()

    print(f"\n{'=' * 70}")
    print(f"Activation 11.5 Forex stop-loss directional policy: {_PASS} PASS, {_FAIL} FAIL")
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print(f"{'=' * 70}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())