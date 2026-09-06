"""ForexMaxLossPolicy -- Activation 11.4 (maximum loss, paper-only
scope).

Companion to ``Business.forex_pip_policy`` (Activation 11.2): builds
Activation 11.1's LOCKED Decision H invariant directly on top of that
module's public API, scoped to exactly what Activation 11.4 asks for
and nothing else:

    * maximum loss

Governed entirely by ``Docs/ACTIVATION 11/
ACTIVATION_11_1_FOREX_POLICY_DECISION.md`` (Decision H). This module
does not implement, and is not consulted by, margin, spread, stop-loss
*validation*/monitoring, or any live/paper order flow. It is not wired
into ``Business.paper_trading_engine.PaperTradingEngine``, ``main.py``,
or any account/schema -- that wiring is a separate, later atomic step.

Locked formula (Decision H)::

    pip_distance  = abs(entry_price - stop_loss) / pip_size
    maximum_loss  = pip_distance * pip_value_per_pip(quantity)

where ``pip_size`` and ``pip_value_per_pip`` come from
``Business.forex_pip_policy.get_pip_size`` /
``Business.forex_pip_policy.calculate_pip_value`` -- this module does
NOT reimplement pip-size or pip-value logic, and does NOT duplicate
``SUPPORTED_PIP_VALUE_PAIRS``; both are answered by the existing pip
policy so pip-value changes there propagate here automatically (see
Activation 11.3, which confirmed ``forex_pip_policy`` remains the
single pair-universe source of truth).

This algebraically simplifies to ``abs(entry_price - stop_loss) *
quantity`` for the current USD-quoted-only pip policy, but this module
deliberately does not take that shortcut -- it always routes through
``get_pip_size``/``calculate_pip_value`` so a future change to either
(e.g. a different pip-size rule, or pip value gaining a currency-
conversion path for a pair currently unsupported) is picked up here
with no change to this module's own logic.

Currency: always USD (``Business.forex_pip_policy.PIP_VALUE_CURRENCY``
-- Decision A/D), because ``calculate_pip_value`` only ever returns a
USD figure or raises.

Directional semantics (Decision H / this Activation's own "Option A"
choice): this module computes maximum loss as a pure, unsigned risk
amount from the absolute distance between ``entry_price`` and
``stop_loss``. It does NOT validate that the stop-loss is on the
correct side of entry for a BUY vs. a SELL (e.g. that a BUY's
stop-loss is below entry) -- that is a distinct, later concern
("whether this stop-loss is valid for BUY/SELL") explicitly deferred
to a future, separate stop-loss/risk policy. Passing this module a
directionally "wrong" stop-loss still returns a mathematically
correct, positive maximum-loss figure for that (possibly invalid)
distance -- it is the caller's responsibility to also validate
direction once that policy exists.

Spread/fees: NOT included (Decision H states both are deferred -- no
Forex-specific fee policy exists yet, and Decision G's spread model is
architecture-only at this point). ``maximum_loss`` here is exactly
``stop-loss price distance x pip value``, nothing more.

Precision handling -- ``Decimal`` throughout, no float in the middle:
mirrors ``Business.forex_pip_policy``'s own "trust the decimal
literal, not the binary float" discipline. Every numeric input is
converted to ``Decimal`` via ``Decimal(str(x))`` before any
arithmetic, and the pip-distance division is performed in ``Decimal``
(never rounded early, never round-tripped through ``float``).

No hidden state: pure and stateless, like ``forex_pip_policy`` -- no
module-level cache, no mutable global, nothing retained between calls.
"""

from __future__ import annotations

from decimal import Decimal
from numbers import Number

from Business.forex_pip_policy import calculate_pip_value, get_pip_size
from Core.exceptions import ValidationError

__all__ = ["calculate_maximum_loss"]


def _to_positive_decimal(value: float, *, field_name: str) -> Decimal:
    """Validate and convert ``value`` to a strictly positive ``Decimal``.

    Shared validation for ``entry_price``/``stop_loss`` (``quantity``
    is validated separately, by ``calculate_pip_value`` itself, so
    this module does not duplicate that check).

    Args:
        value: The candidate numeric value.
        field_name: Name used in the raised error's message/details
            (e.g. ``"entry_price"``, ``"stop_loss"``).

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


def calculate_maximum_loss(
    pair: str,
    entry_price: float,
    stop_loss: float,
    quantity: float,
) -> Decimal:
    """Return the maximum loss, in USD, for a Forex position under Decision H.

    Implements the LOCKED formula::

        pip_distance = abs(entry_price - stop_loss) / get_pip_size(pair)
        maximum_loss = pip_distance * calculate_pip_value(pair, quantity)

    Only defined for pairs ``calculate_pip_value`` itself supports
    (``Business.forex_pip_policy.SUPPORTED_PIP_VALUE_PAIRS`` -- USD-
    quoted pairs only, this Activation exactly ``"EUR/USD"``/
    ``"GBP/USD"``). This function does not itself decide pair support
    -- it delegates entirely to ``calculate_pip_value``, so the pair
    universe is never duplicated here (see module docstring / this
    Activation's own scope note referencing Activation 11.3).

    Does not validate BUY/SELL directional correctness of the
    stop-loss relative to entry (see module docstring's "Directional
    semantics" section) -- only the unsigned distance is used.

    Args:
        pair: The currency pair, e.g. ``"EUR/USD"`` or ``"eurusd"``.
            Must normalize to a pair in
            ``Business.forex_pip_policy.SUPPORTED_PIP_VALUE_PAIRS``.
        entry_price: The position's entry price. Must be strictly
            positive.
        stop_loss: The position's stop-loss price. Must be strictly
            positive. May be above or below ``entry_price`` -- only
            the absolute distance between the two is used.
        quantity: The position size, in base-currency units (Decision
            F). Must be strictly positive.

    Returns:
        The maximum loss as a ``Decimal``, in USD
        (``Business.forex_pip_policy.PIP_VALUE_CURRENCY``).

    Raises:
        ValidationError: if ``pair`` is malformed or normalizes to an
            unsupported (non-USD-quoted) pair, if ``entry_price`` or
            ``stop_loss`` is not a strictly positive real number, or
            if ``quantity`` is not a strictly positive real number
            (that last check is performed by ``calculate_pip_value``,
            not duplicated here).
    """
    entry_price_decimal = _to_positive_decimal(entry_price, field_name="entry_price")
    stop_loss_decimal = _to_positive_decimal(stop_loss, field_name="stop_loss")

    # Reused, not reimplemented -- Business.forex_pip_policy is the
    # single source of truth for both pip size and pip value/pair
    # support (Activation 11.2 / Activation 11.3). Any pair-support
    # or quantity-validity error raised here originates from those
    # functions, unmodified.
    pip_size = get_pip_size(pair)
    pip_value_per_pip = calculate_pip_value(pair, quantity)

    price_distance = abs(entry_price_decimal - stop_loss_decimal)
    pip_distance = price_distance / pip_size

    return pip_distance * pip_value_per_pip