"""ForexStopLossPolicy -- Activation 11.5 (stop-loss directional
validity, paper-only scope).

Companion to ``Business.forex_max_loss_policy`` (Activation 11.4):
implements the piece Decision H / Activation 11.4 explicitly deferred
-- "whether this stop-loss is valid for BUY/SELL" -- as its own,
separate, pure policy, scoped to exactly what Activation 11.5 asks for
and nothing else:

    * stop-loss directional validity

Governed by ``Docs/ACTIVATION 11/
ACTIVATION_11_1_FOREX_POLICY_DECISION.md`` (Decision H) and this
Activation's own locked directional rule. This module does not
calculate pip distance, pip value, or maximum loss (that is
``Business.forex_max_loss_policy.calculate_maximum_loss``, unchanged
and not imported here) and does not know about currency pairs at all
-- directional correctness depends only on ``side``/``entry_price``/
``stop_loss``, never on the traded pair, so this module deliberately
does not import ``Business.forex_pip_policy`` and does not duplicate
or reference ``SUPPORTED_PIP_VALUE_PAIRS`` (keeping Activation 11.3's
"exactly one pair-universe owner" finding intact). It is not wired
into ``Business.paper_trading_engine.PaperTradingEngine``, ``main.py``,
or any account/schema -- that wiring, and composing this module with
``calculate_maximum_loss`` into one caller-side risk check, is a
separate, later atomic step.

Locked directional rule (Activation 11.5)::

    BUY:  valid iff stop_loss < entry_price
    SELL: valid iff stop_loss > entry_price

``stop_loss == entry_price`` is invalid for both sides -- a stop-loss
exactly at entry has zero risk-defining distance and does not fit
either inequality above.

Side convention: the exact two-value ``"BUY"``/``"SELL`` convention
already used throughout this repository for ``Order.action`` /
``Trade.action`` (see ``Business.position_manager._VALID_ACTIONS``) --
no new direction enum, no ``LONG``/``SHORT`` alias. Case-normalized
(``side.strip().upper()``) before comparison, mirroring the
capitalization-tolerant normalization ``Business.forex_pip_policy.
_normalize_pair`` already uses for pair strings; any other value
(``"HOLD"``, ``"SHORT"``, ``"LONG"``, ``"foo"``, ...) is rejected.

Precision handling -- ``Decimal``, not naive float comparison: mirrors
``Business.forex_pip_policy`` / ``Business.forex_max_loss_policy``'s
own "trust the decimal literal, not the binary float" discipline.
``entry_price``/``stop_loss`` are converted to ``Decimal`` via
``Decimal(str(x))`` before any comparison.

No hidden state: pure and stateless, like the two companion modules --
no module-level cache, no mutable global, nothing retained between
calls. The result does not depend on, or get affected by, which pair
a caller happens to be validating a stop-loss for -- this module never
receives a pair at all.
"""

from __future__ import annotations

from decimal import Decimal
from numbers import Number

from Core.exceptions import ValidationError

__all__ = ["VALID_SIDES", "validate_stop_loss"]

#: The only two accepted ``side`` values, matching ``Order.action`` /
#: ``Trade.action``'s existing ``"BUY"``/``"SELL"`` convention
#: (``Business.position_manager._VALID_ACTIONS``). No independent
#: direction enum is introduced.
VALID_SIDES: tuple[str, ...] = ("BUY", "SELL")


def _to_positive_decimal(value: float, *, field_name: str) -> Decimal:
    """Validate and convert ``value`` to a strictly positive ``Decimal``.

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


def validate_stop_loss(side: str, entry_price: float, stop_loss: float) -> None:
    """Validate that ``stop_loss`` is on the directionally correct side of ``entry_price``.

    Pure directional check only -- does not compute pip distance, pip
    value, or maximum loss (see ``Business.forex_max_loss_policy.
    calculate_maximum_loss`` for that, an intentionally separate,
    composable call), and does not know about currency pairs at all
    (see module docstring).

    Locked rule:

        * ``side == "BUY"``:  valid iff ``stop_loss < entry_price``
        * ``side == "SELL"``: valid iff ``stop_loss > entry_price``

    ``stop_loss == entry_price`` is invalid for either side.

    Args:
        side: ``"BUY"`` or ``"SELL"`` (case-insensitive, surrounding
            whitespace tolerated -- normalized the same way pair
            strings are elsewhere in this Activation). Any other
            value is rejected.
        entry_price: The position's entry price. Must be strictly
            positive.
        stop_loss: The candidate stop-loss price. Must be strictly
            positive.

    Returns:
        ``None`` -- returns normally when ``stop_loss`` is
        directionally valid for ``side``.

    Raises:
        ValidationError: if ``side`` is not ``"BUY"``/``"SELL"``
            (after normalization), if ``entry_price`` or
            ``stop_loss`` is not a strictly positive real number, or
            if ``stop_loss`` is not on the directionally correct side
            of ``entry_price`` for ``side`` (including the equal-price
            case).
    """
    if not isinstance(side, str):
        raise ValidationError(
            f"Forex side must be a string, got {type(side).__name__}",
            details={"side": side},
        )

    normalized_side = side.strip().upper()
    if normalized_side not in VALID_SIDES:
        raise ValidationError(
            f"Unsupported Forex side: {side!r} (supported: {VALID_SIDES})",
            details={"side": side, "supported_sides": VALID_SIDES},
        )

    entry_price_decimal = _to_positive_decimal(entry_price, field_name="entry_price")
    stop_loss_decimal = _to_positive_decimal(stop_loss, field_name="stop_loss")

    if normalized_side == "BUY":
        if not stop_loss_decimal < entry_price_decimal:
            raise ValidationError(
                f"Invalid BUY stop-loss: stop_loss ({stop_loss!r}) must be strictly "
                f"below entry_price ({entry_price!r})",
                details={
                    "side": normalized_side,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                },
            )
    else:  # normalized_side == "SELL"
        if not stop_loss_decimal > entry_price_decimal:
            raise ValidationError(
                f"Invalid SELL stop-loss: stop_loss ({stop_loss!r}) must be strictly "
                f"above entry_price ({entry_price!r})",
                details={
                    "side": normalized_side,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                },
            )