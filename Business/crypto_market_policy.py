"""CryptoMarketPolicy -- Activation 10.5 (crypto 24/7 market policy,
paper-only scope).

Companion to ``Business.crypto_price_policy`` / ``Business.
crypto_quantity_policy`` / ``Business.crypto_fee_policy`` for the same
paper crypto market: mirrors those modules' "small, explicit,
configurable *policy* value object, not a broker/exchange claim"
discipline exactly, scoped to exactly what the Activation 10.5 roadmap
item asks for and nothing else:

    * 24/7 market

IMPORTANT DISTINCTION (see the Activation 10.5 brief) -- this module
states a ``24/7 MARKET POLICY``. It does NOT claim ``EXCHANGE ALWAYS
AVAILABLE``. Those are different things:

    paper crypto market  = always open   (this module)
    exchange availability = unknown / not modeled (out of scope)

A future Activation may add exchange downtime detection, maintenance
windows, or an exchange-status API. This module deliberately does none
of that -- see ``Business.paper_trading_engine`` module docstring for
the full remaining Activation 10 roadmap list.

Before this Activation, Crypto had NO explicit market-hours
representation at all: it simply never consulted ``Business.
us_market_policy.USMarketCalendar`` (gate 17 is scoped to
``market == "us"`` only), so Crypto orders were never rejected for
time-of-day/day-of-week reasons -- but that was an ACCIDENTAL absence
of a gate, not a stated policy. This module closes that gap with an
explicit, dedicated Crypto policy object that says so on purpose.

Scope (LOCKED for this Activation, per the brief):

* this module does not call an exchange, does not add exchange
  credentials, and does not implement exchange downtime, maintenance
  windows, an exchange-status API, wallet/balance, API rate limit,
  custody/security, or live exchange API;
* this module does not reuse ``Business.us_market_policy.
  USMarketCalendar`` and is not a large generic market-calendar
  abstraction -- it is the smallest explicit policy the roadmap item
  asks for;
* consumed by exactly one caller, ``Business.paper_trading_engine.
  PaperTradingEngine._run_pre_trade_validation`` (the new gate 18,
  ``market == "crypto"`` only, checked immediately after gate 17) --
  market == "idx" and market == "us" never construct or consult this
  policy at all, so it cannot leak into either (IDX-US isolation, same
  convention every other crypto policy module in this codebase already
  follows).

Determinism -- this module never calls ``datetime.now()`` (or any
other wall-clock source) anywhere. ``is_trading_allowed()`` is a pure
function of the ``executed_at`` moment the caller supplies (the same
caller-supplied ``executed_at`` already threaded through
``PaperTradingEngine.submit_order()`` -- see that module's
"``executed_at`` (LOCKED, unchanged)" docstring paragraph); this
module introduces no new clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# ---------------------------------------------------------------------------
# Policy value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CryptoMarketPolicy:
    """Explicit crypto market-hours policy (value object, paper-market
    only -- not a claim about any real exchange's actual availability).

    Immutable (``frozen=True``), mirroring every other crypto policy
    value object in this codebase (``CryptoQuantityPolicy``,
    ``CryptoPricePolicy``, ``CryptoFeePolicy``): a snapshot consulted
    once per pre-trade gate call by ``PaperTradingEngine``, never a
    live, mutable settings object.

    This policy has no configurable fields -- 24/7 is not a threshold
    or a rate that could plausibly vary per symbol or per deployment
    (unlike price tick, step size, or fee rate), it is the roadmap's
    stated, fixed representation of the paper crypto market. A future
    Activation that DOES need to model exchange downtime/maintenance
    windows gets its own, separately-scoped policy object rather than
    a field bolted onto this one (see module docstring's "IMPORTANT
    DISTINCTION").
    """

    def is_trading_allowed(self, executed_at: datetime) -> bool:
        """Return whether crypto trading is permitted at ``executed_at``.

        Always ``True`` for the paper crypto market: crypto is
        modeled as a 24/7 market, with no day-of-week, time-of-day, or
        holiday restriction of any kind (see module docstring's
        "IMPORTANT DISTINCTION" -- this says nothing about whether any
        real exchange is actually reachable at that moment).

        Args:
            executed_at: A timezone-aware ``datetime``, the same
                caller-supplied moment used elsewhere in the pre-trade
                path. Accepted (and required to be a ``datetime``) so
                this method's signature stays honest about being a
                function of a specific moment, and so a caller who
                later adds a genuine time-based restriction (e.g. a
                future maintenance-window policy) has a call site that
                already threads the right value through -- this
                method itself does not yet branch on it.

        Returns:
            ``True`` unconditionally, for any ``datetime`` input
            (including naive ones -- this policy makes no timezone
            distinction, since every moment is allowed regardless).
        """
        return True


def load_crypto_market_policy() -> CryptoMarketPolicy:
    """Load the ``CryptoMarketPolicy``.

    Mirrors the ``load_crypto_*_policy()`` naming/shape convention
    every other crypto policy module in this codebase already
    establishes (``load_crypto_quantity_policy``, ``load_crypto_
    price_policy``, ``load_crypto_fee_policy``), even though this
    policy currently has no env-var-configurable fields to load (see
    ``CryptoMarketPolicy`` docstring) -- callers consult this loader
    rather than constructing ``CryptoMarketPolicy()`` directly, so a
    future Activation that DOES add a configurable field to this
    policy (still within the "24/7 market policy" scope -- e.g. an
    operator-level kill switch, not exchange downtime) can do so
    without changing any call site.

    Returns:
        A ``CryptoMarketPolicy`` instance.
    """
    return CryptoMarketPolicy()


__all__ = [
    "CryptoMarketPolicy",
    "load_crypto_market_policy",
]