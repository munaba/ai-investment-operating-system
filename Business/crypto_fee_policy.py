"""CryptoFeePolicy -- Activation 10.4 (crypto maker/taker fee, paper-only
scope).

Companion to ``Business.crypto_quantity_policy`` /
``Business.crypto_price_policy`` for the same paper crypto market:
mirrors those modules' "configurable *policy* value object, not a
broker/exchange claim" discipline exactly, scoped to exactly what
Activation 10.4's roadmap item asks for and nothing else:

    * maker fee rate
    * taker fee rate

IMPORTANT -- these are AIOS paper-market constraints, not claims about
any real exchange's current fee schedule. Activation 10 has no
exchange adapter (Binance/Coinbase/Kraken are explicitly out of scope
-- see ``Business.paper_trading_engine`` module docstring's Activation
10 roadmap list). The values in ``_DEFAULT_CRYPTO_FEE_POLICIES`` below
are a deterministic, documented paper-trading default this codebase
enforces for its own two currently supported crypto symbols
(``Core.market_config.CRYPTO_SYMBOLS`` -- ``BTC-USD``/``ETH-USD``),
chosen to be plausible and internally consistent, never asserted to
match any specific exchange's actual current maker/taker rates.

Scope (LOCKED for this Activation, per the brief):

* this module does not call an exchange, does not add exchange
  credentials, and does not implement 24/7 market, exchange downtime,
  wallet/balance, API rate limit, custody/security, or live exchange
  API -- see ``Business.paper_trading_engine``'s module docstring for
  the full remaining Activation 10 roadmap list;
* this module computes nothing beyond exposing the two configured
  rates and a pure ``fee_rate_for(liquidity)`` selector -- no
  order/account/position mutation of any kind, and no order-book/
  matching-engine logic;
* consumed by ``Business.us_market_policy.resolve_fee_tax`` (the
  single shared fee/tax selection function already called by both
  ``Business.paper_trading_engine.PaperTradingEngine`` gate 8's
  required-cash calculation and ``Business.execution_service.
  ExecutionService.execute_order()`` -- see that function's docstring)
  for ``market == "crypto"`` only. ``market == "idx"`` and
  ``market == "us"`` never construct or consult this policy at all, so
  crypto maker/taker fees cannot leak into either (Requirement 3 /
  IDX-US isolation).

Maker/taker representation (LOCKED DECISION for this Activation): the
current paper order model (``Database.models.Order``/``Trade``) has no
order-type/liquidity field, and the current CLI (``paper buy``/
``paper sell``, both routed through the single
``PaperTradingEngine.submit_order()`` entry point -- see that module's
docstring) represents every order as an immediate market-style fill.
There is no order book, no resting order, and therefore no
architectural basis on which "this specific paper order matched as a
liquidity maker" could ever be determined today. Rather than inventing
a fake exchange-matching engine to manufacture that distinction (which
the brief explicitly forbids), this module instead exposes liquidity
selection as an explicit, narrow parameter -- ``fee_rate_for(
execution_liquidity)`` -- that any caller can pass ``"maker"`` or
``"taker"`` to. ``Business.us_market_policy.resolve_fee_tax`` (the only
production caller) always passes ``"taker"`` for
``market == "crypto"``, matching every current CLI order's true
execution semantics. The ``"maker"`` path is fully implemented and
independently testable at this policy/selection layer (see
Requirement 2 / Test Case E of the Activation 10.4 brief) without
requiring a limit-order matching engine, which is explicitly out of
scope for this Activation.

IMPORTANT -- "rate" naming, no ``amount * rate`` formula (LOCKED,
matches existing codebase convention): mirrors ``Business.
execution_policy_config.ExecutionPolicy.buy_fee_rate``/
``sell_fee_rate``/``sell_tax_rate`` and ``Business.us_market_policy.
USFeePolicy.commission_rate``/``regulatory_fee_rate`` exactly --
despite the ``_rate`` naming (kept only for naming-convention
consistency with those two sibling policies and the roadmap's own
``CRYPTO_<SYMBOL>_MAKER_FEE_RATE``/``TAKER_FEE_RATE`` env var names),
none of this codebase's fee/tax policies compute ``notional * rate``
anywhere. ``Business.execution_policy_config`` module docstring is
explicit that this is LOCKED ("implementasi atomik, not a fee/tax/
slippage engine" -- "this module does not compute anything -- no
``amount * rate``"), and ``Business.execution_service.
ExecutionService.execute_order()`` still passes whatever
``resolve_fee_tax()`` returns straight through to
``TradeRepository.create(fee=..., tax=...)`` unchanged -- exactly the
same "placeholder value, no formula yet" contract every other market's
fee resolution already has. This module's ``maker_fee_rate``/
``taker_fee_rate`` are therefore the *effective per-trade fee/tax
placeholder amount* for that liquidity side (in account-currency
units, i.e. USD for both current crypto symbols), not a percentage
multiplied against ``quantity * requested_price`` -- consistent with
every other market this codebase already prices this way. A future
Activation that implements a real ``notional * rate`` fee/tax formula
(for any market, not just crypto) is the place that formula belongs;
this Activation's brief explicitly reserves that ("Do NOT perform a
global financial-number migration").

Precision (float, not Decimal): unlike ``CryptoQuantityPolicy``/
``CryptoPricePolicy``, this module performs no modulus/step-alignment
arithmetic -- ``fee_rate_for`` is a pure dictionary-style lookup
(``"maker"`` -> ``maker_fee_rate``, anything else -> ``taker_fee_rate``),
so there is no binary-float representation-error boundary to guard
against here.
"""

from __future__ import annotations

from dataclasses import dataclass

from Core.config import config
from Core.market_config import CRYPTO_SYMBOLS

# ---------------------------------------------------------------------------
# Policy value object
# ---------------------------------------------------------------------------

#: Liquidity-side identifiers this policy recognizes. Any value other
#: than ``"maker"`` selects the taker rate (see ``fee_rate_for``) --
#: deliberately permissive rather than raising, mirroring
#: ``Business.paper_trading_engine``'s own "any other value is treated
#: as SELL-side" convention for ``action`` in
#: ``Business.us_market_policy.resolve_fee_tax``.
MAKER = "maker"
TAKER = "taker"


@dataclass(frozen=True)
class CryptoFeePolicy:
    """Configurable crypto maker/taker fee policy (value object, not
    an exchange claim).

    Immutable (``frozen=True``), mirroring ``Business.
    crypto_quantity_policy.CryptoQuantityPolicy`` /
    ``Business.crypto_price_policy.CryptoPricePolicy``: a snapshot
    handed to (or consulted once per call by) ``Business.
    us_market_policy.resolve_fee_tax``, never a live, mutable settings
    object.

    Attributes:
        maker_fee_rate: Placeholder per-trade fee *amount* (account-
            currency units, e.g. USD -- see module docstring's "rate
            naming" note; not multiplied against notional anywhere)
            applied when an order provides liquidity (a resting order
            that is later matched against). No current paper order
            type reaches this value in production -- see module
            docstring's "Maker/taker representation" section -- but it
            is fully configurable and testable independently of that
            fact.
        taker_fee_rate: Placeholder per-trade fee *amount* (same units
            and caveat as ``maker_fee_rate``) applied when an order
            removes liquidity (an immediate/market-style fill). Every
            current CLI ``paper buy``/``paper sell`` crypto order uses
            this value (see module docstring).
    """

    maker_fee_rate: float
    taker_fee_rate: float

    def fee_rate_for(self, execution_liquidity: str) -> float:
        """Return the configured fee amount for one liquidity side.

        Pure lookup only -- does not touch any account, order, or
        trade, and (per module docstring's "rate naming" note) is not
        multiplied by a notional value anywhere in this codebase.

        Args:
            execution_liquidity: ``"maker"`` selects
                ``maker_fee_rate``; any other value (including
                ``"taker"``, the only other value this codebase
                currently produces) selects ``taker_fee_rate``.

        Returns:
            The selected fee amount, as a plain ``float``.
        """
        return self.maker_fee_rate if execution_liquidity == MAKER else self.taker_fee_rate


# ---------------------------------------------------------------------------
# Paper-trading defaults
# ---------------------------------------------------------------------------

#: Activation 10.4 paper-trading defaults for the two currently
#: supported crypto symbols (``Core.market_config.CRYPTO_SYMBOLS``).
#: These are AIOS paper-market constraints only -- NOT a claim about
#: any real exchange's current maker/taker fee schedule (see module
#: docstring). Values are flat per-trade placeholder amounts in
#: account-currency units (USD for both symbols below), per the
#: module docstring's "rate naming, no amount * rate formula" note --
#: NOT a percentage multiplied against order notional. Chosen to be
#: deterministic and internally consistent (taker >= maker, mirroring
#: the well-known industry convention that removing liquidity costs at
#: least as much as providing it, without asserting any specific
#: exchange's actual numbers or formula).
_DEFAULT_CRYPTO_FEE_POLICIES: dict[str, CryptoFeePolicy] = {
    "BTC-USD": CryptoFeePolicy(maker_fee_rate=0.10, taker_fee_rate=0.20),
    "ETH-USD": CryptoFeePolicy(maker_fee_rate=0.10, taker_fee_rate=0.20),
}

#: Fallback policy for any symbol ``Core.market_config.is_crypto_symbol``
#: has not (yet) been told is crypto but that nonetheless reaches this
#: module with ``market == "crypto"`` (defensive only -- every current
#: production caller, ``main.py``, already restricts crypto orders to
#: ``CRYPTO_SYMBOLS`` before an order ever reaches
#: ``PaperTradingEngine``; see that module's ``is_crypto_symbol``
#: gate). Same amounts as the two named symbols above -- there is no
#: "conservative" direction for a flat fee amount the way there is for
#: quantity precision/price tick (a higher fee is not obviously safer
#: for either side of a trade), so this fallback simply reuses the
#: named-symbol default rather than inventing a different number.
_FALLBACK_CRYPTO_FEE_POLICY = CryptoFeePolicy(maker_fee_rate=0.10, taker_fee_rate=0.20)


def load_crypto_fee_policy(symbol: str) -> CryptoFeePolicy:
    """Load the ``CryptoFeePolicy`` for ``symbol``.

    Loaded fresh on every call -- never cached at import time or on
    any caller -- mirroring ``Business.crypto_quantity_policy.
    load_crypto_quantity_policy`` / ``Business.crypto_price_policy.
    load_crypto_price_policy``'s own "a test that changes env vars
    between calls sees the new policy immediately" contract.

    Resolution order for each of the two fields, independently:

    1.  A per-symbol env var override, if set:
        ``CRYPTO_<SYMBOL>_MAKER_FEE_RATE`` /
        ``CRYPTO_<SYMBOL>_TAKER_FEE_RATE``, where ``<SYMBOL>`` is
        ``symbol.upper()`` with ``-`` replaced by ``_`` (e.g.
        ``BTC-USD`` -> ``CRYPTO_BTC_USD_MAKER_FEE_RATE``) -- the
        identical per-symbol env var convention
        ``load_crypto_quantity_policy``/``load_crypto_price_policy``
        already established.
    2.  This module's own default for that symbol
        (``_DEFAULT_CRYPTO_FEE_POLICIES``), if ``symbol`` is one of
        the two currently supported crypto symbols.
    3.  ``_FALLBACK_CRYPTO_FEE_POLICY``, for any other symbol
        (defensive only -- see that constant's docstring).

    Args:
        symbol: The traded symbol, in any case (e.g. ``"btc-usd"``,
            ``"BTC-USD"``). Only used to select the default/fallback
            policy and to build the per-symbol env var names above --
            never itself validated here (``Core.market_config.
            is_crypto_symbol`` / ``PaperTradingEngine`` gate 4 already
            own symbol validation).

    Returns:
        A ``CryptoFeePolicy`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config``'s typed getters if one of the env
            vars above is set to a value of the wrong type.
    """
    symbol_upper = symbol.upper() if isinstance(symbol, str) else ""
    base = _DEFAULT_CRYPTO_FEE_POLICIES.get(symbol_upper, _FALLBACK_CRYPTO_FEE_POLICY)

    env_prefix = f"CRYPTO_{symbol_upper.replace('-', '_')}_" if symbol_upper else "CRYPTO_"

    return CryptoFeePolicy(
        maker_fee_rate=config.get_float(f"{env_prefix}MAKER_FEE_RATE", base.maker_fee_rate),
        taker_fee_rate=config.get_float(f"{env_prefix}TAKER_FEE_RATE", base.taker_fee_rate),
    )


__all__ = [
    "MAKER",
    "TAKER",
    "CryptoFeePolicy",
    "load_crypto_fee_policy",
    "CRYPTO_SYMBOLS",
]