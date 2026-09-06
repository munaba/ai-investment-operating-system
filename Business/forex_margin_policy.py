"""ForexMarginPolicy -- Activation 11.6 (required margin, paper-only
scope, 1:1 leverage).

Companion to ``Business.forex_pip_policy`` (Activation 11.2) and
``Business.forex_max_loss_policy`` (Activation 11.4): builds
Activation 11.1's LOCKED Decision B (paper leverage = 1:1) directly on
top of the pip policy's public API, scoped to exactly what Activation
11.6 asks for and nothing else:

    * required margin

Governed entirely by ``Docs/ACTIVATION 11/
ACTIVATION_11_1_FOREX_POLICY_DECISION.md`` (Decision B). This module
does not implement, and is not consulted by, leverage > 1:1, initial
margin %, maintenance margin %, margin level, free margin, margin
call, liquidation, spread, or any live/paper order flow. It is not
wired into ``Business.paper_trading_engine.PaperTradingEngine``,
``main.py``, or any account/schema -- that wiring is a separate, later
atomic step.

Locked formula (Decision B, 1:1 paper leverage)::

    required_margin = price * quantity

where ``price`` is the execution/reference price the future paper
trade would use and ``quantity`` is base-currency units (Decision F).
This is deliberately NOT derived from pip value or pip size --
``required_margin`` (position notional under 1:1) and
``maximum_loss`` (``Business.forex_max_loss_policy``, stop-loss
distance x pip value) are different quantities, both expressed in
USD, that must never be combined or confused with one another. No
stop-loss input belongs in this module.

No ``leverage`` parameter exists on this module's public function --
Decision B explicitly locks this Activation to 1:1. A later Activation
may introduce configurable paper leverage if justified and tested; it
does not change this module without a separate change.

Pair support is NOT duplicated here: ``calculate_required_margin``
reuses ``Business.forex_pip_policy.calculate_pip_value`` purely to
validate ``pair``/``quantity`` against the existing, single pair-
universe source of truth (``SUPPORTED_PIP_VALUE_PAIRS`` -- this
Activation exactly ``"EUR/USD"``/``"GBP/USD"``) -- the returned pip
value itself is discarded, since margin's formula does not use pip
value at all (see "Locked formula" above). Any pair-support or
quantity-validity error raised here originates unmodified from that
existing pip-policy path, never from a second hardcoded pair list.

Currency: always USD (``Business.forex_pip_policy.PIP_VALUE_CURRENCY``
-- Decision A), because the initial supported pairs are USD-quoted and
the paper account itself is USD.

Precision handling -- ``Decimal`` throughout, no float in the middle:
mirrors ``Business.forex_pip_policy`` / ``Business.
forex_max_loss_policy``'s own "trust the decimal literal, not the
binary float" discipline. Every numeric input is converted to
``Decimal`` via ``Decimal(str(x))`` before any arithmetic, and the
final multiplication is never rounded early.

No hidden state: pure and stateless, like ``forex_pip_policy`` /
``forex_max_loss_policy`` -- no module-level cache, no mutable global,
nothing retained between calls.
"""

from __future__ import annotations

from decimal import Decimal
from numbers import Number

from Business.forex_pip_policy import PIP_VALUE_CURRENCY, calculate_pip_value
from Core.exceptions import ValidationError

__all__ = ["REQUIRED_MARGIN_CURRENCY", "calculate_required_margin"]

#: Account currency this module's margin output is always denominated
#: in (Decision A). Re-exported from ``forex_pip_policy`` rather than
#: redefined, so both modules can never drift apart on this constant.
REQUIRED_MARGIN_CURRENCY: str = PIP_VALUE_CURRENCY


def _to_positive_decimal(value: float, *, field_name: str) -> Decimal:
    """Validate and convert ``value`` to a strictly positive ``Decimal``.

    Shared validation for ``price`` (``quantity`` is validated
    separately, by ``calculate_pip_value`` itself, so this module does
    not duplicate that check -- see module docstring).

    Args:
        value: The candidate numeric value.
        field_name: Name used in the raised error's message/details
            (e.g. ``"price"``).

    Returns:
        ``value`` as a ``Decimal``.

    Raises:
        ValidationError: if ``value`` is not a real number, or is not
            strictly positive.
    """
    if not isinstance(value, Number) or isinstance(value, bool):
        raise ValidationError(
            f"Forex {field_name} must be a real number, got {type(value).__name__}",
            details={field_name: value},
        )

    value_decimal = Decimal(str(value))
    if value_decimal <= 0:
        raise ValidationError(
            f"Forex {field_name} must be strictly positive, got {value!r}",
            details={field_name: value},
        )

    return value_decimal


def calculate_required_margin(
    pair: str,
    price: float,
    quantity: float,
) -> Decimal:
    """Return the required margin, in USD, for a Forex position at 1:1.

    Implements the LOCKED Decision B formula::

        required_margin = price * quantity

    Only defined for pairs ``calculate_pip_value`` itself supports
    (``Business.forex_pip_policy.SUPPORTED_PIP_VALUE_PAIRS`` -- USD-
    quoted pairs only, this Activation exactly ``"EUR/USD"``/
    ``"GBP/USD"``). This function does not itself decide pair support
    -- it delegates entirely to ``calculate_pip_value``, so the pair
    universe is never duplicated here (see module docstring). The pip
    value returned by that call is intentionally discarded -- margin
    is never derived from pip value or pip size (see module
    docstring's "Locked formula" section).

    Does not accept, use, or validate a stop-loss -- required margin
    and maximum loss (``Business.forex_max_loss_policy.
    calculate_maximum_loss``) are independent quantities.

    Does not accept a ``leverage`` parameter -- this Activation is
    locked to 1:1 (Decision B).

    Args:
        pair: The currency pair, e.g. ``"EUR/USD"`` or ``"eurusd"``.
            Must normalize to a pair in
            ``Business.forex_pip_policy.SUPPORTED_PIP_VALUE_PAIRS``.
        price: The execution/reference price the future paper trade
            would use. Must be strictly positive.
        quantity: The position size, in base-currency units (Decision
            F). Must be strictly positive.

    Returns:
        The required margin as a ``Decimal``, in USD
        (``REQUIRED_MARGIN_CURRENCY``).

    Raises:
        ValidationError: if ``pair`` is malformed or normalizes to an
            unsupported (non-USD-quoted) pair, if ``price`` is not a
            strictly positive real number, or if ``quantity`` is not a
            strictly positive real number (that last check is
            performed by ``calculate_pip_value``, not duplicated
            here).
    """
    price_decimal = _to_positive_decimal(price, field_name="price")

    # Reused, not reimplemented -- Business.forex_pip_policy is the
    # single pair-universe source of truth (Activation 11.2/11.3).
    # The returned pip value is discarded: margin's formula does not
    # use it (see module docstring). This call's sole purpose here is
    # to validate `pair` (supported/normalizable) and `quantity`
    # (strictly positive real number) through the existing path.
    calculate_pip_value(pair, quantity)

    quantity_decimal = Decimal(str(quantity))

    return price_decimal * quantity_decimal