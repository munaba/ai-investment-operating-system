"""CryptoQuantityPolicy -- Activation 10.2 (crypto quantity precision /
step size / minimum notional, paper-only scope).

Companion to ``Business.us_market_policy`` for the crypto market:
mirrors that module's "configurable *policy* value object, not a
broker/exchange claim" discipline exactly (see
``USFractionalSharePolicy``), scoped to exactly what Activation 10.2's
roadmap item asks for and nothing else:

    * quantity precision
    * step size
    * minimum notional

IMPORTANT -- these are AIOS paper-market constraints, not claims about
any real exchange's current rules. Activation 10 has no exchange
adapter (Binance/Coinbase/etc. are explicitly out of scope -- see
``Business.paper_trading_engine`` module docstring's Activation 10
roadmap list). The values ``_DEFAULT_CRYPTO_QUANTITY_POLICIES`` below
are a deterministic, documented paper-trading default this codebase
enforces for its own two supported crypto symbols
(``Core.market_config.CRYPTO_SYMBOLS`` -- ``BTC-USD``/``ETH-USD``),
chosen to be plausible and internally consistent, never asserted to
match any specific exchange's actual current step size/minimum
notional.

Scope (LOCKED for this Activation, per the brief):

* this module does not call an exchange, does not add exchange
  credentials, and does not implement price tick, maker/taker fee, or
  any other still-open Activation 10 roadmap item -- see
  ``Business.paper_trading_engine``'s module docstring for the full
  remaining list;
* this module computes nothing beyond the two pure checks below
  (quantity validity, minimum notional) -- no order/account/position
  mutation of any kind;
* consumed by exactly one caller, ``Business.paper_trading_engine.
  PaperTradingEngine._run_pre_trade_validation`` (gate 6's ``market ==
  "crypto"`` branch, plus one new crypto-only minimum-notional check
  immediately after price validation) -- market == "idx" and
  market == "us" never construct or consult this policy at all, so
  crypto quantity/notional rules cannot leak into either (Requirement
  5 / IDX-US isolation).

Design decision -- why one ``step_size`` AND one ``quantity_precision``
field, not just one: real exchange quantity rules are usually
expressible as a single step size (a quantity is valid iff it is an
exact non-negative-integer multiple of the step), which alone would
satisfy both "quantity precision" and "step size" from the roadmap.
This module keeps both fields anyway, as two independently-checked
constraints, for two reasons: (1) the roadmap explicitly lists
``quantity_precision`` as its own configuration knob (see the
REQUIREMENT 3 config-shape block in the Activation 10.2 brief), so a
future operator/Activation that needs to loosen/tighten one without
the other has a place to do it without redesigning this object; (2) it
lets this module reject a quantity that is too finely expressed (more
decimal digits than ``quantity_precision`` allows, mirroring
``USFractionalSharePolicy.is_quantity_allowed``'s own
``round(quantity, precision) != quantity`` check) independently of
whether it happens to still land on a step boundary. In this module's
own default policies the two constraints agree (``step_size``'s
decimal-exponent equals ``quantity_precision``); nothing prevents an
operator from configuring them to disagree (e.g. a coarser
``step_size`` than ``quantity_precision`` alone would require) -- see
``load_crypto_quantity_policy``'s env-var docstring.

Precision handling -- ``Decimal``, not naive float comparison: binary
floats cannot represent most decimal fractions exactly (``0.1 + 0.2 !=
0.3``), so both checks below convert the caller-supplied quantity/
price/step/minimum-notional to ``Decimal`` via ``Decimal(str(x))``
(the standard "trust the decimal literal, not the binary float" idiom
-- ``Decimal(str(0.001)) == Decimal("0.001")`` where ``Decimal(0.001)``
directly would not be) before ever comparing or taking a modulus. This
module does not perform a codebase-wide numeric-type refactor (no
other module's numbers become ``Decimal``) -- ``Decimal`` is used only
locally, inside this module's two validation methods, exactly at the
boundary the brief asks for ("assess whether using Decimal locally at
the validation boundary is the smallest safe approach").
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from Core.config import config
from Core.market_config import CRYPTO_SYMBOLS

# ---------------------------------------------------------------------------
# Policy value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CryptoQuantityPolicy:
    """Configurable crypto quantity/notional policy (value object, not
    an exchange claim).

    Immutable (``frozen=True``), mirroring ``Business.
    us_market_policy.USFractionalSharePolicy`` /
    ``Business.execution_policy_config.ExecutionPolicy``: a snapshot
    handed to (or consulted once per gate call by)
    ``PaperTradingEngine``, never a live, mutable settings object.

    Attributes:
        step_size: The smallest permitted quantity increment. A
            quantity is only valid if it is an exact multiple of this
            value (checked via ``Decimal`` modulus -- see module
            docstring). Must be strictly positive.
        quantity_precision: Number of decimal places a quantity may be
            expressed to. A quantity with more decimal digits than
            this is rejected, independent of the step-size check (see
            module docstring's "Design decision" section) -- mirrors
            ``USFractionalSharePolicy.quantity_precision``'s own
            ``round(quantity, precision) != quantity`` convention.
        minimum_notional: The smallest permitted ``quantity *
            execution_price`` for an order in this symbol. Checked by
            ``meets_minimum_notional`` using the same price
            ``PaperTradingEngine``/``ExecutionService`` actually use
            for this order (``requested_price`` -- see
            ``Business.execution_service.ExecutionService``'s own
            "filled at the price that was requested" docstring note),
            never a separately-fetched price.
    """

    step_size: float
    quantity_precision: int
    minimum_notional: float

    def is_quantity_valid(self, quantity: float) -> bool:
        """Return whether ``quantity`` is permitted under this policy.

        Pure arithmetic check only -- does not touch any account,
        order, or position, and does not consider price/notional (see
        ``meets_minimum_notional`` for that). A quantity is valid when
        it is positive, exactly representable at
        ``quantity_precision`` decimal places, and an exact multiple
        of ``step_size`` -- both checks performed via ``Decimal``
        (module docstring) so ordinary decimal literals like ``0.001``
        never fail due to binary-float representation error.

        Args:
            quantity: The candidate order quantity, in the traded
                asset's units (e.g. BTC, ETH).

        Returns:
            ``True`` if ``quantity`` satisfies every check above,
            ``False`` otherwise (including for a non-``int``/``float``
            or non-positive input, treated defensively rather than
            raising -- mirrors ``USFractionalSharePolicy.
            is_quantity_allowed``'s own defensive posture).
        """
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
            return False
        if quantity <= 0:
            return False

        # Precision check: reject a quantity expressed with more
        # decimal digits than quantity_precision permits (e.g.
        # 0.0015 when quantity_precision == 3). Same
        # round-trip-via-round() idiom USFractionalSharePolicy already
        # uses -- kept in ordinary float arithmetic here (not Decimal)
        # deliberately, so this check's behavior matches that
        # already-LOCKED pattern byte-for-byte, not a new convention.
        if round(quantity, self.quantity_precision) != quantity:
            return False

        # Step-size check: reject a quantity that is not an exact
        # multiple of step_size (e.g. 0.0025 when step_size == 0.001).
        # Decimal, not float modulus -- see module docstring.
        quantity_decimal = Decimal(str(quantity))
        step_decimal = Decimal(str(self.step_size))
        if step_decimal <= 0:
            return False
        remainder = quantity_decimal % step_decimal
        return remainder == 0

    def meets_minimum_notional(self, quantity: float, execution_price: float) -> bool:
        """Return whether ``quantity * execution_price >=
        minimum_notional`` under this policy.

        Pure arithmetic check only. Uses the *same* price the caller
        actually used to compute the order's own notional value / the
        price ``ExecutionService`` will fill at -- this method never
        fetches or derives a price of its own (Requirement 3 of the
        Activation 10.2 brief).

        Args:
            quantity: The candidate order quantity.
            execution_price: The price this order is being validated
                against -- the same ``requested_price`` used
                everywhere else in this order's pre-trade validation
                and, per ``ExecutionService``, the same price the
                resulting ``Trade`` will actually fill at.

        Returns:
            ``True`` if the computed notional is greater than or equal
            to ``minimum_notional``, ``False`` otherwise.
        """
        quantity_decimal = Decimal(str(quantity))
        price_decimal = Decimal(str(execution_price))
        minimum_decimal = Decimal(str(self.minimum_notional))
        notional_decimal = quantity_decimal * price_decimal
        return notional_decimal >= minimum_decimal


# ---------------------------------------------------------------------------
# Paper-trading defaults
# ---------------------------------------------------------------------------

#: Activation 10.2 paper-trading defaults for the two currently
#: supported crypto symbols (``Core.market_config.CRYPTO_SYMBOLS``).
#: These are AIOS paper-market constraints only -- NOT a claim about
#: any real exchange's current step size / minimum notional (see
#: module docstring). Chosen to be internally consistent
#: (``step_size``'s decimal-exponent equals ``quantity_precision`` for
#: both symbols) and deterministic, so the same quantity is always
#: accepted or rejected the same way absent an explicit env-var
#: override.
_DEFAULT_CRYPTO_QUANTITY_POLICIES: dict[str, CryptoQuantityPolicy] = {
    "BTC-USD": CryptoQuantityPolicy(
        step_size=0.001,
        quantity_precision=3,
        minimum_notional=10.0,
    ),
    "ETH-USD": CryptoQuantityPolicy(
        step_size=0.01,
        quantity_precision=2,
        minimum_notional=10.0,
    ),
}

#: Fallback policy for any symbol ``Core.market_config.is_crypto_symbol``
#: has not (yet) been told is crypto but that nonetheless reaches this
#: module with ``market == "crypto"`` (defensive only -- every current
#: production caller, ``main.py``, already restricts crypto orders to
#: ``CRYPTO_SYMBOLS`` before an order ever reaches
#: ``PaperTradingEngine``; see that module's ``is_crypto_symbol``
#: gate). Conservative (finer precision, same minimum notional as the
#: two named symbols above) rather than permissive, mirroring
#: ``USFractionalSharePolicy``'s own "default to the conservative
#: choice when nothing confirms otherwise" convention.
_FALLBACK_CRYPTO_QUANTITY_POLICY = CryptoQuantityPolicy(
    step_size=0.0001,
    quantity_precision=4,
    minimum_notional=10.0,
)


def load_crypto_quantity_policy(symbol: str) -> CryptoQuantityPolicy:
    """Load the ``CryptoQuantityPolicy`` for ``symbol``.

    Loaded fresh on every call -- never cached at import time or on
    any caller -- mirroring ``Business.us_market_policy.
    load_us_fractional_share_policy``'s own "a test that changes env
    vars between calls sees the new policy immediately" contract.

    Resolution order for each of the three fields, independently:

    1.  A per-symbol env var override, if set:
        ``CRYPTO_<SYMBOL>_STEP_SIZE`` / ``CRYPTO_<SYMBOL>_QUANTITY_
        PRECISION`` / ``CRYPTO_<SYMBOL>_MINIMUM_NOTIONAL``, where
        ``<SYMBOL>`` is ``symbol.upper()`` with ``-`` replaced by
        ``_`` (e.g. ``BTC-USD`` -> ``CRYPTO_BTC_USD_STEP_SIZE``).
    2.  This module's own default for that symbol
        (``_DEFAULT_CRYPTO_QUANTITY_POLICIES``), if ``symbol`` is one
        of the two currently supported crypto symbols.
    3.  ``_FALLBACK_CRYPTO_QUANTITY_POLICY``, for any other symbol
        (defensive only -- see that constant's docstring).

    Args:
        symbol: The traded symbol, in any case (e.g. ``"btc-usd"``,
            ``"BTC-USD"``). Only used to select the default/fallback
            policy and to build the per-symbol env var names above --
            never itself validated here (``Core.market_config.
            is_crypto_symbol`` / ``PaperTradingEngine`` gate 4 already
            own symbol validation).

    Returns:
        A ``CryptoQuantityPolicy`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config``'s typed getters if one of the env
            vars above is set to a value of the wrong type.
    """
    symbol_upper = symbol.upper() if isinstance(symbol, str) else ""
    base = _DEFAULT_CRYPTO_QUANTITY_POLICIES.get(symbol_upper, _FALLBACK_CRYPTO_QUANTITY_POLICY)

    env_prefix = f"CRYPTO_{symbol_upper.replace('-', '_')}_" if symbol_upper else "CRYPTO_"

    return CryptoQuantityPolicy(
        step_size=config.get_float(f"{env_prefix}STEP_SIZE", base.step_size),
        quantity_precision=config.get_int(f"{env_prefix}QUANTITY_PRECISION", base.quantity_precision),
        minimum_notional=config.get_float(f"{env_prefix}MINIMUM_NOTIONAL", base.minimum_notional),
    )


__all__ = [
    "CryptoQuantityPolicy",
    "load_crypto_quantity_policy",
    "CRYPTO_SYMBOLS",
]