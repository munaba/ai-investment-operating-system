"""ForexPipPolicy -- Activation 11.2 (pip size / pip value, paper-only
scope).

Companion to ``Business.crypto_quantity_policy`` / ``Business.
crypto_price_policy`` / ``Business.us_market_policy`` for the (not yet
wired) Forex market: mirrors those modules' "small, explicit,
configurable *policy*, not a broker/exchange claim" discipline
exactly, scoped to exactly what Activation 11.2 asks for and nothing
else:

    * pip size
    * pip value (USD-quoted pairs only)

Governed entirely by the LOCKED decisions in ``Docs/ACTIVATION 11/
ACTIVATION_11_1_FOREX_POLICY_DECISION.md`` (Activation 11.1). This
module implements Decisions C (pip size) and D (pip value / currency
conversion) only -- it does not implement, and is not consulted by,
margin, spread, stop-loss, maximum loss, or any live/paper order flow.
It is not wired into ``Business.paper_trading_engine.
PaperTradingEngine``, ``main.py``, or any account/schema -- that
wiring is a separate, later atomic step.

Account currency (Decision A) is USD. Paper leverage (Decision B) is
1:1 -- this module does not use or depend on leverage at all; pip
value is pure quote-currency-independent arithmetic once a pair's
quote currency is USD.

Pip size (Decision C, LOCKED):

    quote currency == JPY  -> Decimal("0.01")
    otherwise               -> Decimal("0.0001")

``get_pip_size()`` implements this rule for ANY well-formed
BASE/QUOTE pair string -- including non-USD-quoted and JPY-quoted
pairs such as ``"USD/JPY"`` -- because pip size itself needs no
account-currency conversion (see Decision C's own rationale). This is
a pure classification function, not a claim that ``USD/JPY`` is a
supported *tradable* pair.

Pip value (Decision D, LOCKED):

    pip_value = pip_size * quantity_in_base_units

Because the paper account currency is USD (Decision A) and only
USD-quoted pairs are supported for pip-value calculation this
Activation (Decision D/E), this formula's result is always
denominated in USD with no conversion step. ``calculate_pip_value()``
enforces that restriction explicitly: for any pair whose quote
currency is not USD, it raises ``Core.exceptions.ValidationError``
rather than inventing or silently assuming an FX conversion rate --
that conversion source does not exist in this repository and Decision
D records it as ``BLOCKED BY EXTERNAL DEPENDENCY`` for a future
Activation.

Supported pip-value pairs this Activation (Decision E): exactly
``"EUR/USD"`` and ``"GBP/USD"`` (``SUPPORTED_PIP_VALUE_PAIRS`` below).

Quantity (Decision F): plain base-currency units (e.g. ``10000`` means
10,000 units of the base currency) -- no standard/mini/micro lot
conversion.

Precision handling -- ``Decimal``, not naive float arithmetic: binary
floats cannot represent most decimal fractions exactly (``0.1 + 0.2 !=
0.3``), so both functions below convert every numeric input to
``Decimal`` via ``Decimal(str(x))`` (the same "trust the decimal
literal, not the binary float" idiom ``CryptoQuantityPolicy``/
``CryptoPricePolicy`` already use) before any arithmetic. This module
does not perform a codebase-wide numeric-type refactor -- ``Decimal``
is used only locally, inside this module's two functions.

No hidden state: both functions are pure and stateless -- no module-
level cache, no mutable global, nothing retained between calls. Two
independent calls (e.g. one ``EUR/USD`` pip-value calculation and one
``GBP/USD`` pip-value calculation) can never influence each other.
"""

from __future__ import annotations

from decimal import Decimal
from numbers import Number

from Core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Locked constants (Activation 11.1 Decisions C/D/E)
# ---------------------------------------------------------------------------

#: Pip size for a pair quoted in Japanese Yen (Decision C).
PIP_SIZE_JPY_QUOTE: Decimal = Decimal("0.01")

#: Pip size for every other (non-JPY-quoted) pair (Decision C).
PIP_SIZE_DEFAULT: Decimal = Decimal("0.0001")

#: The only pairs ``calculate_pip_value`` accepts this Activation
#: (Decision E) -- both USD-quoted, satisfying Decision D's
#: "no conversion needed" restriction. Canonical ``"BASE/QUOTE"``
#: form, uppercase. Deliberately small -- this Activation does not
#: attempt to support the general Forex pair universe (see module
#: docstring / Decision E rationale).
SUPPORTED_PIP_VALUE_PAIRS: tuple[str, ...] = ("EUR/USD", "GBP/USD")

#: Account currency this module's pip-value output is always
#: denominated in (Decision A). Exposed for callers that want to
#: label the returned ``Decimal`` without hard-coding the string
#: themselves.
PIP_VALUE_CURRENCY: str = "USD"


# ---------------------------------------------------------------------------
# Pair normalization
# ---------------------------------------------------------------------------


def _normalize_pair(pair: str) -> str:
    """Normalize ``pair`` to canonical ``"BASE/QUOTE"`` form.

    Accepts either the slash-separated form (``"EUR/USD"``,
    case-insensitive, arbitrary surrounding whitespace) or the
    unseparated six-letter form (``"EURUSD"``) and returns the
    canonical uppercase ``"BASE/QUOTE"`` form for both. This is the
    only normalization this module performs -- no broader Forex
    symbol parser, no broker-specific alias table.

    Args:
        pair: The candidate currency pair, e.g. ``"EUR/USD"`` or
            ``"eurusd"``.

    Returns:
        The canonical ``"BASE/QUOTE"`` string, e.g. ``"EUR/USD"``.

    Raises:
        ValidationError: if ``pair`` is not a string, or is not a
            well-formed three-letter/three-letter currency pair in
            either accepted form.
    """
    if not isinstance(pair, str):
        raise ValidationError(
            f"Forex pair must be a string, got {type(pair).__name__}",
            details={"pair": pair},
        )

    candidate = pair.strip().upper()

    if "/" in candidate:
        parts = candidate.split("/")
        if len(parts) != 2:
            raise ValidationError(
                f"Malformed Forex pair: {pair!r} (expected exactly one '/')",
                details={"pair": pair},
            )
        base, quote = parts
    elif len(candidate) == 6:
        base, quote = candidate[:3], candidate[3:]
    else:
        raise ValidationError(
            f"Malformed Forex pair: {pair!r} (expected 'BASE/QUOTE' or "
            "six-letter 'BASEQUOTE', e.g. 'EUR/USD' or 'EURUSD')",
            details={"pair": pair},
        )

    if len(base) != 3 or len(quote) != 3 or not base.isalpha() or not quote.isalpha():
        raise ValidationError(
            f"Malformed Forex pair: {pair!r} (base/quote must each be exactly "
            "three letters)",
            details={"pair": pair},
        )

    return f"{base}/{quote}"


# ---------------------------------------------------------------------------
# Pip size
# ---------------------------------------------------------------------------


def get_pip_size(pair: str) -> Decimal:
    """Return the pip size for ``pair`` under the LOCKED Decision C rule.

    Pure classification -- requires no account-currency conversion,
    so this accepts ANY well-formed pair, including non-USD-quoted
    and JPY-quoted pairs (e.g. ``"USD/JPY"``). This does NOT mean
    such a pair is a supported *tradable*/pip-value pair -- see
    ``calculate_pip_value`` and ``SUPPORTED_PIP_VALUE_PAIRS`` for that
    separate, narrower restriction.

    Args:
        pair: The currency pair, e.g. ``"EUR/USD"``, ``"USD/JPY"``,
            or ``"eurusd"``.

    Returns:
        ``PIP_SIZE_JPY_QUOTE`` (``Decimal("0.01")``) if the pair's
        quote currency is ``"JPY"``, otherwise ``PIP_SIZE_DEFAULT``
        (``Decimal("0.0001")``).

    Raises:
        ValidationError: if ``pair`` is not a well-formed currency
            pair (see ``_normalize_pair``).
    """
    normalized = _normalize_pair(pair)
    quote = normalized.split("/")[1]
    if quote == "JPY":
        return PIP_SIZE_JPY_QUOTE
    return PIP_SIZE_DEFAULT


# ---------------------------------------------------------------------------
# Pip value
# ---------------------------------------------------------------------------


def calculate_pip_value(pair: str, quantity: float) -> Decimal:
    """Return the USD pip value for ``quantity`` base-currency units of ``pair``.

    Implements the LOCKED Decision D formula::

        pip_value = pip_size * quantity_in_base_units

    Only defined for pairs in ``SUPPORTED_PIP_VALUE_PAIRS`` (Decision
    E) -- both USD-quoted, so the result needs no currency conversion
    and is always denominated in ``PIP_VALUE_CURRENCY`` ("USD"). For
    any other, non-USD-quoted pair, this function does NOT attempt a
    conversion (none exists in this repository -- Decision D records
    that as ``BLOCKED BY EXTERNAL DEPENDENCY``) -- it raises
    ``ValidationError`` instead of silently guessing a rate.

    Args:
        pair: The currency pair, e.g. ``"EUR/USD"`` or ``"eurusd"``.
            Must normalize (``_normalize_pair``) to one of
            ``SUPPORTED_PIP_VALUE_PAIRS``.
        quantity: The order quantity, in base-currency units
            (Decision F -- e.g. ``10000`` for 10,000 EUR). Must be a
            positive real number.

    Returns:
        The pip value as a ``Decimal``, in USD.

    Raises:
        ValidationError: if ``pair`` is malformed, if ``pair``
            normalizes to a pair outside ``SUPPORTED_PIP_VALUE_PAIRS``
            (including a well-formed but non-USD-quoted pair such as
            ``"EUR/JPY"``), if ``quantity`` is not a real number, or
            if ``quantity`` is not strictly positive.
    """
    normalized = _normalize_pair(pair)

    if normalized not in SUPPORTED_PIP_VALUE_PAIRS:
        raise ValidationError(
            f"Pip value is not supported for {normalized!r} in this Activation: "
            f"only USD-quoted pairs {SUPPORTED_PIP_VALUE_PAIRS} are supported "
            "(Activation 11.1 Decision D -- a non-USD-quoted pair requires FX "
            "conversion against the USD paper account currency, which this "
            "repository does not implement)",
            details={"pair": normalized, "supported_pairs": SUPPORTED_PIP_VALUE_PAIRS},
        )

    if not isinstance(quantity, Number) or isinstance(quantity, bool):
        raise ValidationError(
            f"Forex quantity must be a real number, got {type(quantity).__name__}",
            details={"quantity": quantity},
        )

    quantity_decimal = Decimal(str(quantity))
    if quantity_decimal <= 0:
        raise ValidationError(
            f"Forex quantity must be strictly positive, got {quantity!r}",
            details={"quantity": quantity},
        )

    pip_size = get_pip_size(normalized)
    return pip_size * quantity_decimal


__all__ = [
    "PIP_SIZE_JPY_QUOTE",
    "PIP_SIZE_DEFAULT",
    "SUPPORTED_PIP_VALUE_PAIRS",
    "PIP_VALUE_CURRENCY",
    "get_pip_size",
    "calculate_pip_value",
]