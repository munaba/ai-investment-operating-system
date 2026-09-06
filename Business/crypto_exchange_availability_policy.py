"""CryptoExchangeAvailabilityPolicy -- Activation 10.6 (crypto exchange
availability, paper-only scope).

Companion to ``Business.crypto_market_policy`` for the same paper
crypto market: mirrors that module's (and ``Business.
crypto_quantity_policy`` / ``Business.crypto_price_policy`` / ``Business.
crypto_fee_policy``'s) "small, explicit, configurable *policy* value
object, not a broker/exchange claim" discipline exactly, scoped to
exactly what the Activation 10.6 roadmap item asks for and nothing
else:

    * exchange downtime / exchange availability

IMPORTANT DISTINCTION (see the Activation 10.6 brief, and the
Activation 10.5 audit that preceded it) -- this module answers a
different question than ``Business.crypto_market_policy.
CryptoMarketPolicy`` does:

    CryptoMarketPolicy.is_trading_allowed(executed_at)
        = "is the paper market MODELED AS OPEN at this moment"
          (a pure calendar/clock question -- always True, 24/7)

    CryptoExchangeAvailabilityPolicy.is_available()
        = "is the execution VENUE currently capable of accepting
          orders" (an independent, injected/configurable paper state)

These two are deliberately NOT combined into one object and NOT
evaluated together: the market can be (and, per Activation 10.5,
always is) open 24/7 while the venue is, independently, unavailable
under this policy -- and vice versa is equally representable (this
module has no opinion on market hours at all). This module never
imports, constructs, or otherwise touches ``CryptoMarketPolicy``, and
``CryptoMarketPolicy`` is not modified by this Activation.

Scope (LOCKED for this Activation, per the brief):

* this module does not call an exchange, does not add exchange
  credentials, and does not implement wallet/balance, API rate
  limiting, custody/security, live exchange API, exchange status REST,
  exchange WebSocket, maintenance-schedule API, network health probes,
  or retry/backoff -- see ``Business.paper_trading_engine``'s module
  docstring for the full remaining Activation 10 roadmap list;
* this policy is deliberately an INJECTED/CONFIGURABLE paper state,
  not a live signal from any real venue -- there is no exchange name,
  no per-exchange configuration, and no claim that any specific real
  exchange is actually available or unavailable at any given moment;
* consumed by exactly one caller, ``Business.paper_trading_engine.
  PaperTradingEngine._run_pre_trade_validation`` (the new gate 19,
  ``market == "crypto"`` only, checked immediately after gate 18's
  ``CryptoMarketPolicy`` check) -- market == "idx" and market == "us"
  never construct or consult this policy at all, so it cannot leak
  into either (IDX-US isolation, same convention every other crypto
  policy module in this codebase already follows).

Determinism -- this module never calls ``datetime.now()`` or any other
wall-clock/network source. ``is_available()`` takes no arguments and
is a pure function of the ``CryptoExchangeAvailabilityPolicy``
instance's own ``available`` field -- the exact same "value object,
computes nothing beyond a stored flag/threshold" shape ``Business.
crypto_market_policy.CryptoMarketPolicy`` and every other crypto
policy module in this codebase already use.
"""

from __future__ import annotations

from dataclasses import dataclass

from Core.config import config

# ---------------------------------------------------------------------------
# Policy value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CryptoExchangeAvailabilityPolicy:
    """Explicit crypto exchange-availability policy (value object,
    injected/configurable paper state -- not a live exchange signal).

    Immutable (``frozen=True``), mirroring every other crypto policy
    value object in this codebase (``CryptoMarketPolicy``,
    ``CryptoQuantityPolicy``, ``CryptoPricePolicy``, ``CryptoFeePolicy``):
    a snapshot consulted once per pre-trade gate call by
    ``PaperTradingEngine``, never a live, mutable settings object.

    Attributes:
        available: Whether the crypto execution venue is modeled as
            available. Defaults are resolved by ``load_crypto_
            exchange_availability_policy()`` (default ``True`` --
            existing crypto paper behavior is unchanged unless a
            caller/test explicitly overrides this to ``False``); this
            field itself carries no default so every construction site
            states its intent explicitly.
    """

    available: bool

    def is_available(self) -> bool:
        """Return whether the crypto execution venue is available.

        Pure accessor only -- does not touch any account, order, or
        position, and does not consider market hours (see module
        docstring's "IMPORTANT DISTINCTION" -- that is ``Business.
        crypto_market_policy.CryptoMarketPolicy``'s separate concern).

        Returns:
            ``self.available``, unchanged.
        """
        return self.available


# ---------------------------------------------------------------------------
# Paper-trading configuration
# ---------------------------------------------------------------------------

#: Env var controlling the paper crypto exchange-availability override.
#: Narrowly scoped, venue-agnostic (no exchange name -- see module
#: docstring's "Configuration" section: this Activation deliberately
#: does not introduce Binance/Coinbase/Kraken-specific configuration).
#: Resolved via ``Core.config.Config.get_bool`` (module docstring
#: below) -- the exact same boolean-parsing convention every other
#: boolean env var in this codebase already uses (e.g.
#: ``KILL_SWITCH_ENABLED`` in ``Core.composition_root``,
#: ``US_FRACTIONAL_SHARES_ENABLED`` in ``Business.us_market_policy``),
#: so ``"true"``/``"false"`` (case-insensitive, plus ``1``/``0``,
#: ``yes``/``no``, ``on``/``off``) are the only accepted values; any
#: other string (e.g. ``"abc"``) raises ``ConfigurationError`` rather
#: than being silently interpreted as ``False`` -- ``get_bool`` never
#: falls back to its default on an invalid (as opposed to unset) value.
CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR: str = "CRYPTO_EXCHANGE_AVAILABLE"

#: Default availability when ``CRYPTO_EXCHANGE_AVAILABLE`` is unset.
#: ``True`` (available) -- per the brief's "Default behavior must
#: remain available == True, so existing crypto paper behavior remains
#: unchanged unless a test/configuration explicitly marks the exchange
#: unavailable."
_DEFAULT_AVAILABLE: bool = True


def load_crypto_exchange_availability_policy() -> CryptoExchangeAvailabilityPolicy:
    """Load the ``CryptoExchangeAvailabilityPolicy`` from environment
    configuration.

    Loaded fresh on every call -- never cached at import time or on
    any caller -- mirroring every other crypto policy loader in this
    codebase (``load_crypto_market_policy``, ``load_crypto_quantity_
    policy``, ``load_crypto_price_policy``, ``load_crypto_fee_policy``):
    a test that changes ``CRYPTO_EXCHANGE_AVAILABLE`` between calls
    sees the new policy immediately, with no engine/service rebuild
    required.

    Resolution:

    1.  ``CRYPTO_EXCHANGE_AVAILABLE`` env var, if set -- parsed via
        ``Core.config.Config.get_bool`` (accepts ``true``/``false``,
        ``1``/``0``, ``yes``/``no``, ``on``/``off``, case-insensitive;
        any other set value raises ``ConfigurationError`` -- never
        silently treated as ``False``, per the brief's "Do not
        silently accept arbitrary strings as false").
    2.  ``_DEFAULT_AVAILABLE`` (``True``), if the env var is unset.

    Returns:
        A ``CryptoExchangeAvailabilityPolicy`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config.get_bool`` if ``CRYPTO_EXCHANGE_
            AVAILABLE`` is set to a value that is not a recognized
            boolean string.
    """
    return CryptoExchangeAvailabilityPolicy(
        available=config.get_bool(CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR, _DEFAULT_AVAILABLE),
    )


__all__ = [
    "CryptoExchangeAvailabilityPolicy",
    "load_crypto_exchange_availability_policy",
    "CRYPTO_EXCHANGE_AVAILABLE_ENV_VAR",
]