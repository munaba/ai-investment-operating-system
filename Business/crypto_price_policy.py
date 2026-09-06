"""CryptoPricePolicy -- Activation 10.3 (crypto price tick, paper-only
scope).

Companion to ``Business.crypto_quantity_policy`` for the same paper
crypto market: mirrors that module's "configurable *policy* value
object, not a broker/exchange claim" discipline exactly
(``CryptoQuantityPolicy``), scoped to exactly what Activation 10.3's
roadmap item asks for and nothing else:

    * price tick

IMPORTANT -- these are AIOS paper-market constraints, not claims about
any real exchange's current rules. Activation 10 has no exchange
adapter (Binance/Coinbase/Kraken are explicitly out of scope -- see
``Business.paper_trading_engine`` module docstring's Activation 10
roadmap list). The values in ``_DEFAULT_CRYPTO_PRICE_POLICIES`` below
are a deterministic, documented paper-trading default this codebase
enforces for its own two supported crypto symbols
(``Core.market_config.CRYPTO_SYMBOLS`` -- ``BTC-USD``/``ETH-USD``),
chosen to be plausible and internally consistent, never asserted to
match any specific exchange's actual current tick size.

Scope (LOCKED for this Activation, per the brief):

* this module does not call an exchange, does not add exchange
  credentials, and does not implement maker/taker fee, 24/7 market,
  exchange downtime, wallet/balance, API rate limit, custody/security,
  or live exchange API -- see ``Business.paper_trading_engine``'s
  module docstring for the full remaining Activation 10 roadmap list;
* this module computes nothing beyond the one pure check below (price
  tick alignment) -- no order/account/position mutation of any kind;
* consumed by exactly one caller, ``Business.paper_trading_engine.
  PaperTradingEngine._run_pre_trade_validation`` (immediately after
  gate 7 validates ``requested_price``, before the existing crypto
  minimum-notional check -- see that module's docstring) -- market ==
  "idx" and market == "us" never construct or consult this policy at
  all, so crypto price-tick rules cannot leak into either
  (Requirement 5 / IDX-US isolation).

Precision handling -- ``Decimal``, not naive float modulo: binary
floats cannot represent most decimal fractions exactly (``0.1 + 0.2 !=
0.3``), so the check below converts the caller-supplied price/tick to
``Decimal`` via ``Decimal(str(x))`` (the same "trust the decimal
literal, not the binary float" idiom ``CryptoQuantityPolicy`` already
uses) before ever comparing or taking a modulus. This module does not
perform a codebase-wide numeric-type refactor -- ``Decimal`` is used
only locally, inside this module's one validation method, exactly at
the boundary the brief asks for.
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
class CryptoPricePolicy:
    """Configurable crypto price-tick policy (value object, not an
    exchange claim).

    Immutable (``frozen=True``), mirroring ``Business.
    crypto_quantity_policy.CryptoQuantityPolicy``: a snapshot handed
    to (or consulted once per gate call by) ``PaperTradingEngine``,
    never a live, mutable settings object.

    Attributes:
        price_tick: The smallest permitted price increment. A price
            is only valid if it is an exact multiple of this value
            (checked via ``Decimal`` modulus -- see module
            docstring). Must be strictly positive.
    """

    price_tick: float

    def is_price_valid(self, price: float) -> bool:
        """Return whether ``price`` is permitted under this policy.

        Pure arithmetic check only -- does not touch any account,
        order, or position, and does not consider quantity/notional
        (see ``Business.crypto_quantity_policy.CryptoQuantityPolicy.
        meets_minimum_notional`` for that, a separate, already-LOCKED
        check). A price is valid when it is positive and an exact
        multiple of ``price_tick`` -- checked via ``Decimal`` (module
        docstring) so ordinary decimal literals like ``0.01`` never
        fail due to binary-float representation error.

        Args:
            price: The candidate order price, in the traded pair's
                quote currency (e.g. USD).

        Returns:
            ``True`` if ``price`` satisfies every check above,
            ``False`` otherwise (including for a non-``int``/``float``
            or non-positive input, treated defensively rather than
            raising -- mirrors ``CryptoQuantityPolicy.
            is_quantity_valid``'s own defensive posture).
        """
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            return False
        if price <= 0:
            return False

        price_decimal = Decimal(str(price))
        tick_decimal = Decimal(str(self.price_tick))
        if tick_decimal <= 0:
            return False
        remainder = price_decimal % tick_decimal
        return remainder == 0


# ---------------------------------------------------------------------------
# Paper-trading defaults
# ---------------------------------------------------------------------------

#: Activation 10.3 paper-trading defaults for the two currently
#: supported crypto symbols (``Core.market_config.CRYPTO_SYMBOLS``).
#: These are AIOS paper-market constraints only -- NOT a claim about
#: any real exchange's current tick size (see module docstring).
#: Chosen to be deterministic and compatible with the paper prices
#: already used across the Activation 10.1/10.2 test suites (e.g.
#: ``CRYPTO_PRICE = 100.0`` in ``Tests/
#: test_activation10_2_crypto_quantity_policy.py``, an exact multiple
#: of both values below).
_DEFAULT_CRYPTO_PRICE_POLICIES: dict[str, CryptoPricePolicy] = {
    "BTC-USD": CryptoPricePolicy(price_tick=0.01),
    "ETH-USD": CryptoPricePolicy(price_tick=0.01),
}

#: Fallback policy for any symbol ``Core.market_config.is_crypto_symbol``
#: has not (yet) been told is crypto but that nonetheless reaches this
#: module with ``market == "crypto"`` (defensive only -- every current
#: production caller, ``main.py``, already restricts crypto orders to
#: ``CRYPTO_SYMBOLS`` before an order ever reaches
#: ``PaperTradingEngine``; see that module's ``is_crypto_symbol``
#: gate). Conservative (finer tick than the two named symbols above)
#: rather than permissive, mirroring ``CryptoQuantityPolicy``'s own
#: "default to the conservative choice when nothing confirms
#: otherwise" convention.
_FALLBACK_CRYPTO_PRICE_POLICY = CryptoPricePolicy(price_tick=0.0001)


def load_crypto_price_policy(symbol: str) -> CryptoPricePolicy:
    """Load the ``CryptoPricePolicy`` for ``symbol``.

    Loaded fresh on every call -- never cached at import time or on
    any caller -- mirroring ``Business.crypto_quantity_policy.
    load_crypto_quantity_policy``'s own "a test that changes env vars
    between calls sees the new policy immediately" contract.

    Resolution order:

    1.  A per-symbol env var override, if set: ``CRYPTO_<SYMBOL>_
        PRICE_TICK``, where ``<SYMBOL>`` is ``symbol.upper()`` with
        ``-`` replaced by ``_`` (e.g. ``BTC-USD`` ->
        ``CRYPTO_BTC_USD_PRICE_TICK``) -- the identical per-symbol env
        var convention ``load_crypto_quantity_policy`` already
        established (``CRYPTO_<SYMBOL>_STEP_SIZE`` etc.).
    2.  This module's own default for that symbol
        (``_DEFAULT_CRYPTO_PRICE_POLICIES``), if ``symbol`` is one of
        the two currently supported crypto symbols.
    3.  ``_FALLBACK_CRYPTO_PRICE_POLICY``, for any other symbol
        (defensive only -- see that constant's docstring).

    Args:
        symbol: The traded symbol, in any case (e.g. ``"btc-usd"``,
            ``"BTC-USD"``). Only used to select the default/fallback
            policy and to build the per-symbol env var name above --
            never itself validated here (``Core.market_config.
            is_crypto_symbol`` / ``PaperTradingEngine`` gate 4 already
            own symbol validation).

    Returns:
        A ``CryptoPricePolicy`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config``'s typed getters if the env var
            above is set to a value of the wrong type.
    """
    symbol_upper = symbol.upper() if isinstance(symbol, str) else ""
    base = _DEFAULT_CRYPTO_PRICE_POLICIES.get(symbol_upper, _FALLBACK_CRYPTO_PRICE_POLICY)

    env_prefix = f"CRYPTO_{symbol_upper.replace('-', '_')}_" if symbol_upper else "CRYPTO_"

    return CryptoPricePolicy(
        price_tick=config.get_float(f"{env_prefix}PRICE_TICK", base.price_tick),
    )


__all__ = [
    "CryptoPricePolicy",
    "load_crypto_price_policy",
    "CRYPTO_SYMBOLS",
]