"""PaperTradingEngine -- Sprint 4 STEP 9, extended by Activation 3.2.

The end-to-end orchestrator for a single paper trade: runs pre-trade
validation, then -- only if every gate passes -- drives an order from
submission through to a filled ``Trade`` by calling two already-LOCKED
Sprint 4 Services in a fixed sequence.

    Caller
          v
    PaperTradingEngine.submit_order()
          v
    [Activation 3.2 + 8.4 + 9.4 + 10.5 + 10.6] 19 pre-trade gates, all read-only, in order
          v  (only if every gate passes)
    OrderLifecycleService  (Sprint 4 STEP 5)
          v
    ExecutionService        (Sprint 4 STEP 6)
          v
    [Activation 3.5] AccountBalanceService.apply_trade()
          v
    [Activation 3.5 STEP 2] PositionManager.apply_trade()
          v
    [Activation 3.2] OrderIdempotencyRepository.create()
          v
    Trade

Activation 3.2 scope and ground rules (LOCKED for this Activation, per
the brief):

* does NOT change Activation 3.1's audited transaction boundary in any
  way -- ``OrderLifecycleService.create_order()`` ->
  ``ExecutionService.execute_order()`` still run exactly as Activation
  3.1 documented them (five independent auto-committed statements, no
  ``_session()``, no new transaction wrapping). Every Activation 3.2
  gate is a pure read (``get_by_id``/``get_open_position``/
  ``get_by_key``) that runs *before* ``create_order()`` is ever
  called, so a failed gate touches zero rows in ``orders``/``trades``/
  ``accounts``/``positions``/``order_idempotency_keys`` -- there is
  nothing to roll back because nothing was written;
* does NOT introduce a new pipeline -- this is still the same
  ``PaperTradingEngine.submit_order()`` entry point, extended in
  place;
* does NOT move responsibility to another layer -- every gate lives on
  this class, reading through the same Repository pattern every other
  component in this codebase already uses;
* reuses existing production components (``AccountRepository``,
  ``PositionRepository``) plus one new one that genuinely did not
  exist anywhere in the codebase after audit
  (``OrderIdempotencyRepository`` -- duplicate-request detection has
  no prior implementation to reuse).

Pre-trade gates (LOCKED order for this Activation -- first failing
gate wins, checked in this exact sequence, mirroring
``OrderLifecycleService._validate``'s "first match wins" pattern):

    1.  account aktif            -> account exists (see LOCKED
        DECISION below -- "active" has no dedicated column)
    2.  signal/evidence tersedia -> ``signal_evidence`` truthy
    3.  user approval tersedia   -> ``user_approval is True``
    4.  symbol valid              -> non-empty/blank string
    5.  quantity valid            -> positive real number
    6.  IDX lot size valid        -> quantity is an exact multiple of
        ``self._execution_policy.lot_size`` (Activation 3.3 canonical
        ``Business.execution_policy_config.ExecutionPolicy`` --
        default reproduces
        ``Database.account_constants.IDX_LOT_SIZE_SHARES``)
    7.  price positif             -> positive real number
    8.  available cash            -> BUY only: account.cash >=
        (quantity * requested_price) + fee + tax (Activation 3.5
        STEP 3 -- see ``compute_buy_required_cash()`` note below;
        previously ``quantity * requested_price`` alone)
    9.  available position untuk SELL -> SELL only: an open position
        exists with quantity >= requested quantity
    10. duplicate request/idempotency -> ``idempotency_key`` not
        already recorded in ``order_idempotency_keys``
    11. risk limit                -> quantity * requested_price <=
        ``max_order_value``
    12. kill switch                -> ``kill_switch_engaged`` is False
    13. market kill switch (Activation 8.4) -> active market (``AIOS_MARKET``)
        not in ``halted_markets``
    14. symbol kill switch (Activation 8.4) -> ``symbol.upper()`` not in
        ``halted_symbols``
    15. daily loss kill switch (Activation 8.4, BUY only) -> account's
        summed ``Position.realized_pnl`` is not a loss of magnitude
        >= ``max_daily_loss`` (skipped entirely when ``max_daily_loss``
        is ``None``; see gate 15's inline comment for why "daily" means
        "cumulative" in this codebase)
    16. position kill switch (Activation 8.4, BUY only) -> resulting
        position value ((existing_quantity + quantity) *
        requested_price) <= ``max_position_value`` (skipped entirely
        when ``max_position_value`` is ``None``)
    17. US market session/calendar (Activation 9.4, ``market == "us"``
        only) -> ``Business.us_market_policy.USMarketCalendar().
        session(executed_at)`` (the same caller-supplied ``executed_at``
        threaded through to ``ExecutionService`` -- see gate 8's fee/tax
        note and the "``executed_at`` (LOCKED)" paragraph below; this
        gate generates no timestamp of its own either) is in
        ``Business.us_market_policy.US_ORDER_ALLOWED_SESSIONS``
        (currently: regular session only -- pre-market, after-hours,
        weekend, and holiday are all rejected; see that module's own
        docstring for why). Skipped entirely for ``market == "idx"``/
        ``market == "crypto"``, exactly like gate 6's existing
        ``market == "us"`` branch.
    18. crypto 24/7 market policy (Activation 10.5, ``market ==
        "crypto"`` only) -> ``Business.crypto_market_policy.
        CryptoMarketPolicy().is_trading_allowed(executed_at)`` (the
        same caller-supplied ``executed_at`` gate 17 above already
        parses for ``market == "us"``; this gate parses it
        independently for ``market == "crypto"``, never sharing gate
        17's parsed value across markets). Always ``True`` under the
        current policy -- crypto is modeled as a 24/7 market, so this
        gate never rejects for a *valid* timestamp; it only rejects an
        ``executed_at`` this engine cannot parse at all (fails safe,
        mirroring gate 17's own unparsable-timestamp handling).
        Skipped entirely for ``market == "idx"``/``market == "us"``,
        exactly like gate 17's own ``market == "us"`` branch, mirrored
        in the opposite direction.
    19. crypto exchange availability policy (Activation 10.6,
        ``market == "crypto"`` only) -> ``Business.
        crypto_exchange_availability_policy.
        CryptoExchangeAvailabilityPolicy().is_available()``. An
        injected/configurable paper venue-availability flag,
        deliberately independent of gate 18's 24/7 market-hours check
        (see ``Business.crypto_exchange_availability_policy`` module
        docstring's "IMPORTANT DISTINCTION" -- market hours and venue
        availability are different questions, never combined). Default
        ``available=True``, so existing crypto paper behavior is
        unchanged unless ``CRYPTO_EXCHANGE_AVAILABLE`` is explicitly
        set to a falsy value. Skipped entirely for ``market ==
        "idx"``/``market == "us"``, exactly like gate 18's own
        ``market == "crypto"``-only scoping.

Activation 10.2 (additive, does not renumber or change any gate
above): gate 6's ``market == "crypto"`` branch no longer bypasses
quantity validation outright -- it now consults a real, symbol-specific
``Business.crypto_quantity_policy.CryptoQuantityPolicy`` (quantity
precision + step size). Immediately after gate 7 validates
``requested_price``, one additional crypto-only check (minimum
notional, also from ``CryptoQuantityPolicy``) runs, price-dependent so
it cannot be evaluated any earlier than gate 7. Both checks are
skipped entirely for ``market in ("idx", "us")`` -- see
``Business.crypto_quantity_policy`` module docstring for full
rationale and Requirement 5 / IDX-US isolation.

Activation 10.3 (additive, does not renumber or change any gate
above): immediately after gate 7 validates ``requested_price`` and
BEFORE the Activation 10.2 minimum-notional check described above, one
further crypto-only check runs -- price tick alignment, via a new
``Business.crypto_price_policy.CryptoPricePolicy`` (loaded fresh, one
field: ``price_tick``). Skipped entirely for ``market in ("idx",
"us")``, exactly like the Activation 10.2 checks -- see
``Business.crypto_price_policy`` module docstring for full rationale
and Requirement 5 / IDX-US isolation.

Activation 11.14 (additive, does not renumber or change any gate
above): immediately after gate 7 validates ``requested_price`` and
AFTER the Activation 10.2/10.3 crypto-only checks above (this rule
runs for every account regardless of ``market``, so its position after
those two crypto-scoped checks is arbitrary -- it is simply "as soon
as ``requested_price`` and ``order_value`` are known"), one further
check runs, scoped to ``Account.asset_class == "forex"`` ONLY (a
completely different switch from the ``market``/``AIOS_MARKET`` gate 6
already reads): ``stop_loss`` is REQUIRED (Activation 11.10-H LOCKED)
and, when supplied, must be on the protective side of
``requested_price`` for the resulting/existing ``Position.direction``
(Activation 11.13's direction-aware rule, applied here via
``Business.position_manager.is_stop_loss_side_valid`` against
``requested_price`` rather than a persisted ``average_price``, since
no ``Position`` may exist yet). ``take_profit`` is explicitly OUT OF
SCOPE for this Activation -- no new gate reads or requires it; a
Forex ``Position``'s ``take_profit`` stays whatever
``PositionManager.apply_trade()``'s existing merge/reduce pass-through
already leaves it (``None`` unless a later, separate call sets it).
Skipped entirely for every non-Forex account -- IDX/US/Crypto orders
never evaluate this gate and their ``stop_loss`` argument (including
the default ``None``) is silently ignored. On success, the same
``stop_loss`` value is persisted onto the resulting ``Position`` by one
call to ``PositionManager.set_stop_loss_take_profit()`` at the end of
``submit_order()`` (see that method's own docstring) -- this gate only
validates; it never writes anything itself, consistent with every
gate above it being a pure read.

Activation 11.15 (additive, does not renumber or change any gate
above): immediately after the Activation 11.14 Forex stop-loss/
direction gate above (still scoped to ``Account.asset_class ==
"forex"`` ONLY), one further check runs -- required margin for this
order's incremental NEW exposure, computed via ``Business.
forex_margin_policy.calculate_required_margin`` (the LOCKED
``required_margin = price * quantity`` formula at 1:1 paper leverage;
never inlined/reimplemented in this engine). A trade on the SAME side
as any existing OPEN position adds new exposure equal to its full
quantity; a trade on the OPPOSITE side (reducing an existing position)
only creates new exposure for the portion, if any, exceeding that
position's quantity -- a pure reduction never requires margin, even
when the gross trade notional exceeds available cash. Rejects with
``PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN`` when the resulting
required margin exceeds ``Account.cash`` -- the sole affordability
source for this gate (``Account.buying_power`` is never read).
Skipped entirely for every non-Forex account. Gate 8 immediately below
is amended (``not is_forex`` added to its condition) so its own
gross-order-quantity cash check no longer runs for Forex accounts at
all -- this gate is their only affordability check, replacing gate 8
for Forex rather than running alongside it.

Any failing gate raises ``ValidationError`` with
``details={"reason": <PRETRADE_REASON_*>, ...}`` and calls neither
``OrderLifecycleService`` nor ``ExecutionService`` -- no ``Order``,
``Trade``, ``Position``, ``Account``, or idempotency-key row is ever
touched.

LOCKED DECISION -- "account aktif": the ``accounts`` table (migration
version=2, already applied/LOCKED) has no ``status``/``is_active``
column at all -- see ``Database.migrations_accounts``. Adding one is a
schema change outside this Activation's "gunakan komponen production
yang sudah ada" / "jangan membuat pipeline baru" constraints. This
gate therefore means "the account exists"
(``AccountRepository.get_by_id(account_id) is not None``) -- the
strongest activity signal available without a schema change. If a
future Activation adds a real status column, this gate is the single
place to update.

LOCKED DECISION -- ``signal_evidence``/``user_approval`` are supplied
by the caller as plain parameters, not looked up by this engine from
some evidence/approval store. Sourcing them is out of scope here (no
such store exists in this codebase to reuse, and building one would be
a new pipeline, which the brief explicitly forbids). This engine only
checks that the caller actually supplied them.

Activation 5.1 (additive, does not change the above LOCKED DECISION):
this engine now ALSO reads ``getattr(signal_evidence, "snapshot_id",
None)`` -- a pure attribute read on the object the caller already
supplied, not a new lookup -- and passes it through to
``OrderLifecycleService.create_order()`` as ``analysis_snapshot_id``,
so the ``RankingSnapshot`` ID backing this decision (when the caller's
``signal_evidence`` is one) is persisted on the resulting ``Order``.
Every other pre-trade gate and the required call order below are
unchanged.

LOCKED DECISION -- risk limit / kill switch are read from
``Core.config`` (the same env-var mechanism ``Core.approval_config``
already uses), injected into this engine's constructor by
``Core.composition_root`` -- not a new config mechanism. See
``Core.composition_root._kill_switch_engaged``/``_max_order_value``.

Activation 8.4 (additive, does not change any LOCKED DECISION above):
adds four more constructor-injected, construct-once values --
``halted_markets``/``halted_symbols``/``max_daily_loss``/
``max_position_value`` -- read from ``Core.config`` by
``Core.composition_root`` the identical way
``kill_switch_engaged``/``max_order_value`` already are. No broker
API, no network call, no live execution: every one of these four
gates is a read against already-persisted local state
(``os.environ``/``PositionRepository``), exactly like every gate
before it.

LOCKED DECISION -- idempotency-key write timing: the
``order_idempotency_keys`` row is written *after* ``Trade`` creation
succeeds (end of ``submit_order``), not before ``create_order()`` is
called. Trade-off, documented honestly: this means two concurrent
calls carrying the *same* ``idempotency_key`` could both pass gate 10
and both produce an ``Order``/``Trade`` before either write lands --
this engine (like every other Sprint 4 Service before it) is not
thread-safe against concurrent calls on the same key, and nothing in
this codebase calls ``submit_order()`` concurrently today (Activation
3.1 confirmed there is no production caller at all yet). Writing the
key only after full success, instead of earlier, guarantees the
opposite failure mode never happens: a request that fails partway
through never leaves a "used" key behind that would block a legitimate
retry.

Constructor dependency (LOCKED baseline, Activation 3.2): five
collaborators -- ``OrderLifecycleService``, ``ExecutionService``,
``AccountRepository``, ``PositionRepository``,
``OrderIdempotencyRepository`` -- plus two plain values,
``kill_switch_engaged`` and ``max_order_value``. No other Repository,
Service, Skill, or Tool. Activation 3.3 STEP 2 adds one further
optional value, ``execution_policy`` (the canonical
``Business.execution_policy_config.ExecutionPolicy``), defaulted so
every existing caller/test that does not pass it keeps working
unchanged -- see gate 6 below. Activation 3.5 STEP 1 adds one more
optional collaborator, ``account_balance_service`` (the canonical
``Business.account_balance_service.AccountBalanceService``, Sprint 4
STEP 7), defaulted to a fresh instance over this engine's own
``account_repository`` when not supplied -- same "additive, defaulted,
existing callers unchanged" pattern as ``execution_policy``. Activation
3.5 STEP 2 adds one further optional collaborator, ``position_manager``
(the canonical ``Business.position_manager.PositionManager``, Sprint 4
STEP 8), defaulted to a fresh instance over this engine's own
``position_repository`` when not supplied -- identical additive/
defaulted pattern.

LOCKED DECISION (Activation 3.3 STEP 2) -- gate 8's cash comparison
still does not branch on ``ExecutionPolicy.buying_power_policy``:
that field is defined canonically (Activation 3.3 scope item "buying
power policy") and defaults to naming today's comparison
(``"cash_only"``), but no gate reads it yet. A future Activation that
implements a second buying-power strategy reads this field to decide
which formula to apply.

SUPERSEDED (Activation 3.5 STEP 3) -- gate 8's cash comparison was
previously ``account.cash < order_value`` (``order_value ==
gross_value``, no fee/tax). Activation 3.5 STEP 2's audit found this
diverged from ``AccountBalanceService.apply_trade()``'s own BUY guard
(``gross_value + fee + tax > cash``), creating a reachable window
where a BUY could pass this gate, reach ``FILLED``, and only then be
rejected downstream once fee/tax were counted -- an orphaned
Order/Trade with no cash ever applied. Gate 8 now compares against
``compute_buy_required_cash(order_value, fee, tax)``
(``Business.account_balance_service``), the same function
``apply_trade()`` calls, with ``fee``/``tax`` read from this engine's
own ``self._execution_policy`` -- the same ``ExecutionPolicy``
instance the composition root also gives ``ExecutionService`` -- using
the identical BUY-side selection
``ExecutionService.execute_order()`` applies. See gate 8's inline
comment for the full rationale.

Public API (LOCKED, unchanged from Sprint 4 STEP 9): exactly one
public method, ``submit_order()``, now taking three additional
required parameters (``signal_evidence``, ``user_approval``,
``idempotency_key``).

``executed_at`` (LOCKED, unchanged): supplied by the caller and passed
straight through to ``ExecutionService.execute_order()``. This class
never generates a timestamp itself.

Required call order (extended, Activation 3.5 STEP 2): all 12
pre-trade gates, in order, then -- unchanged from Sprint 4 STEP 9 --
``OrderLifecycleService.create_order()``, then, only if
``Order.status == "PENDING"``, ``ExecutionService.execute_order()``,
then (Activation 3.5 STEP 1) ``AccountBalanceService.apply_trade()``,
then (new, Activation 3.5 STEP 2) ``PositionManager.apply_trade()``,
then ``OrderIdempotencyRepository.create()``. Both ``apply_trade()``
calls run before the idempotency-key write, mirroring how every other
step in this sequence already propagates a failure: if either the
``Trade``'s cash impact (``AccountBalanceService``) or its position
impact (``PositionManager``) cannot be applied, the exception
propagates out of ``submit_order()`` and the idempotency key is never
written -- consistent with the module's existing idempotency-key
write-timing rationale (a request that fails partway through never
leaves a "used" key behind).

LOCKED DECISION (Activation 3.5 STEP 2) -- ``PositionManager.
apply_trade()`` is a single method that dispatches BUY/SELL internally
based on ``trade.action`` (open/merge on BUY; reduce/close/oversell-
guard on SELL) -- this is ``PositionManager``'s own LOCKED "business
logic lives in PositionManager, not in the caller" decision. Wiring
this call in therefore activates both the BUY and SELL paths through
production at once; there is no way to wire "BUY only" without adding
an artificial ``if action == "BUY":`` check in this engine that would
duplicate a branch ``PositionManager`` already owns. ``realized_pnl``
is not computed by this wiring -- ``PositionManager`` itself does not
compute it yet, so it remains a pass-through placeholder pending a
future STEP.

Return type (LOCKED, unchanged): ``Trade``, and only ``Trade``.
"""

from __future__ import annotations

import math
import os
from datetime import datetime

from Business.account_balance_service import AccountBalanceService, compute_buy_required_cash
from Business.crypto_exchange_availability_policy import load_crypto_exchange_availability_policy
from Business.crypto_market_policy import load_crypto_market_policy
from Business.crypto_price_policy import load_crypto_price_policy
from Business.crypto_quantity_policy import load_crypto_quantity_policy
from Business.execution_policy_config import ExecutionPolicy, load_execution_policy
from Business.execution_service import ExecutionService
#: Activation 11.15 -- the single, LOCKED required-margin calculation
#: source (``required_margin = price * quantity`` at 1:1 paper
#: leverage). Never reimplemented/inlined here -- see the Forex
#: required-margin gate below.
from Business.forex_margin_policy import calculate_required_margin
from Business.notification_builder import NotificationBuilder
from Business.notification_dispatcher import NotificationDispatcher
from Business.notification_manager import NotificationManager
from Business.order_lifecycle_service import OrderLifecycleService
from Business.position_manager import (
    PositionManager,
    is_stop_loss_side_valid,
)
#: Activation 11.14 -- reuses ``PositionManager``'s own LOCKED
#: direction/asset-class domain constants rather than re-declaring
#: local string literals, mirroring ``Business.forex_order_preview``'s
#: existing precedent of importing a leading-underscore name across a
#: ``Business.*`` module boundary when it is the single source of
#: truth for a shared domain value.
from Business.position_manager import _DIRECTION_LONG, _DIRECTION_SHORT, _FOREX_ASSET_CLASS
from Business.us_market_policy import (
    US_ORDER_ALLOWED_SESSIONS,
    USMarketCalendar,
    load_us_fractional_share_policy,
    resolve_fee_tax,
)
from Core.exceptions import ValidationError
from Core.logger import get_logger
from Database.models import Trade
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_approval_repository import OrderApprovalRepository
from Repository.persistence.order_idempotency_repository import OrderIdempotencyRepository
from Repository.persistence.position_repository import PositionRepository

#: Activation 7 FIX (blocker 1): module-level logger, same
#: ``get_logger(__name__)`` pattern already used throughout this
#: codebase (``Database.sqlite_database``, ``Providers.provider_selector``,
#: etc.) -- introduced here only so an ``ORDER_EXECUTED`` notification
#: failure is visible (logged) instead of silently swallowed. Never
#: used for anything else in this module -- trading logic itself logs
#: nothing new.
logger = get_logger(__name__)

#: Reason text used only for the ValidationError message below when
#: create_order() leaves the Order somewhere other than PENDING (e.g.
#: REJECTED). Not a persisted reason code -- OrderLifecycleService
#: already persisted its own REJECTED reason via its own LOCKED
#: reason-code domain; this is purely this method's exception message.
_REASON_NOT_PENDING = "Order is not executable"

#: Actions this engine recognizes for the cash/position pre-trade
#: gates. Mirrors ``Business.order_lifecycle_service._VALID_ACTIONS``
#: -- deliberately re-declared here rather than imported, since that
#: name is a private module attribute of a different LOCKED module.
_BUY = "BUY"
_SELL = "SELL"

#: Pre-trade gate reason codes (Activation 3.2, LOCKED list). Every
#: ``ValidationError`` this engine's pre-trade validation raises uses
#: exactly one of these in ``details["reason"]``. Mirrors
#: ``Business.order_lifecycle_service.REJECTION_REASONS``'s pattern of
#: a single enumerated, documented reason-code domain.
PRETRADE_REASON_ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
PRETRADE_REASON_EVIDENCE_MISSING = "EVIDENCE_MISSING"
PRETRADE_REASON_APPROVAL_MISSING = "APPROVAL_MISSING"
PRETRADE_REASON_INVALID_SYMBOL = "INVALID_SYMBOL"
PRETRADE_REASON_INVALID_QUANTITY = "INVALID_QUANTITY"
PRETRADE_REASON_INVALID_LOT_SIZE = "INVALID_LOT_SIZE"
PRETRADE_REASON_INVALID_PRICE = "INVALID_PRICE"
PRETRADE_REASON_INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
PRETRADE_REASON_INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
PRETRADE_REASON_DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
PRETRADE_REASON_RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
PRETRADE_REASON_KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"

#: Activation 8.4 pre-trade gate reason codes (gates 13-16, additive).
#: Same "one reason code per gate, first match wins" domain the
#: Activation 3.2 list above already establishes -- these four simply
#: extend it, checked in order immediately after gate 12.
PRETRADE_REASON_MARKET_KILL_SWITCH_ENGAGED = "MARKET_KILL_SWITCH_ENGAGED"
PRETRADE_REASON_SYMBOL_KILL_SWITCH_ENGAGED = "SYMBOL_KILL_SWITCH_ENGAGED"
PRETRADE_REASON_DAILY_LOSS_LIMIT_EXCEEDED = "DAILY_LOSS_LIMIT_EXCEEDED"
PRETRADE_REASON_MAX_POSITION_VALUE_EXCEEDED = "MAX_POSITION_VALUE_EXCEEDED"

#: Activation 9.4 pre-trade gate reason code (gate 17, additive). Same
#: "one reason code per gate" domain as the Activation 8.4 block above
#: -- one narrowly-scoped new reason for the one new gate, not a new
#: taxonomy. Covers every way the US session/calendar policy can
#: reject an order: pre-market, after-hours, weekend, holiday, or an
#: ``executed_at`` this engine cannot parse at all (fails safe -- an
#: unparsable timestamp is never treated as "regular session").
PRETRADE_REASON_US_MARKET_SESSION_CLOSED = "US_MARKET_SESSION_CLOSED"

#: Activation 10.2 pre-trade gate reason code (crypto-only, checked
#: immediately after gate 7/price validation -- see
#: ``Business.crypto_quantity_policy`` module docstring). Covers only
#: "notional below the configured minimum" -- a quantity/step/
#: precision violation for ``market == "crypto"`` still raises under
#: ``PRETRADE_REASON_INVALID_LOT_SIZE`` (gate 6, same reason code the
#: existing IDX lot-size and US fractional-share branches already use
#: for "this quantity is not permitted under the active market's
#: quantity rule" -- deliberately not a new reason code for that half,
#: per the brief's "do not create a new error taxonomy unless
#: absolutely necessary"). Minimum notional is a genuinely different
#: concept (a price-dependent floor, not a quantity-shape rule), so it
#: gets its own reason code rather than overloading
#: ``PRETRADE_REASON_INVALID_LOT_SIZE`` with an unrelated meaning.
PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL = "BELOW_MINIMUM_NOTIONAL"

#: Activation 10.3 pre-trade gate reason code (crypto-only, checked
#: immediately after gate 7/price validation and BEFORE the existing
#: minimum-notional check above -- see
#: ``Business.crypto_price_policy`` module docstring). Covers only
#: "price not aligned to the configured tick" -- distinct from
#: ``PRETRADE_REASON_INVALID_PRICE`` (gate 7, "not a positive real
#: number at all") and from ``PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL``
#: (a price-and-quantity-dependent floor, not a per-price alignment
#: rule), per the brief's "do not create a new error taxonomy unless
#: absolutely necessary" -- one narrowly-scoped new reason for one
#: new, genuinely distinct concept.
PRETRADE_REASON_INVALID_PRICE_TICK = "INVALID_PRICE_TICK"

#: Activation 10.5 pre-trade gate reason code (gate 18, crypto-only,
#: additive). Same "one reason code per gate" domain as the Activation
#: 9.4/10.2/10.3 entries above -- one narrowly-scoped new reason for
#: the one new gate. Under the current 24/7 policy this reason is only
#: ever raised for an ``executed_at`` this engine cannot parse at all
#: (fails safe -- an unparsable timestamp is never treated as "market
#: open" by default, mirroring ``PRETRADE_REASON_US_MARKET_SESSION_
#: CLOSED``'s identical fail-safe contract for gate 17); a *valid*
#: timestamp never raises this reason, since ``CryptoMarketPolicy.
#: is_trading_allowed()`` always returns ``True`` for one (see
#: ``Business.crypto_market_policy`` module docstring).
PRETRADE_REASON_CRYPTO_MARKET_CLOSED = "CRYPTO_MARKET_CLOSED"

#: Activation 10.6 pre-trade gate reason code (gate 19, crypto-only,
#: additive). Same "one reason code per gate" domain as the Activation
#: 9.4/10.2/10.3/10.5 entries above -- one narrowly-scoped new reason
#: for the one new gate. Deliberately NOT
#: ``PRETRADE_REASON_CRYPTO_MARKET_CLOSED`` (per the Activation 10.6
#: brief: "the market may be 24/7 while the venue is unavailable" --
#: these are independent concepts with independent reason codes, see
#: ``Business.crypto_exchange_availability_policy`` module docstring's
#: "IMPORTANT DISTINCTION"). Raised whenever ``CryptoExchangeAvailability
#: Policy.is_available()`` is ``False`` for the active paper
#: configuration -- an injected/configurable paper state, never a live
#: exchange signal.
PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE = "CRYPTO_EXCHANGE_UNAVAILABLE"

#: Activation 11.14 pre-trade gate reason codes (Forex-only, additive,
#: checked immediately after gate 7/price validation -- see the
#: "Forex stop-loss required + direction" gate below). Two distinct
#: reasons, mirroring every other Activation's "one reason code per
#: genuinely distinct rejection" domain above: one for "no stop_loss
#: supplied at all" (Activation 11.10-H's LOCKED "Forex order without
#: stop-loss -> reject" requirement), one for "a stop_loss was
#: supplied but is not on the protective side of ``requested_price``
#: for the resulting/existing ``Position.direction``" (Activation
#: 11.13's direction-aware rule, applied here at the pre-trade
#: boundary via ``Business.position_manager.is_stop_loss_side_valid``).
#: Scoped to ``Account.asset_class == "forex"`` only -- IDX/US/Crypto
#: orders never evaluate either check and never raise either reason.
PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED = "FOREX_STOP_LOSS_REQUIRED"
PRETRADE_REASON_INVALID_FOREX_STOP_LOSS = "INVALID_FOREX_STOP_LOSS"

#: Activation 11.15 pre-trade gate reason code (Forex-only, additive,
#: checked immediately after the Activation 11.14 stop-loss gate
#: above -- see the "Forex required-margin gate" below). Raised only
#: when the required margin (``Business.forex_margin_policy.
#: calculate_required_margin``) for this order's incremental NEW
#: exposure (never the gross order quantity -- see that gate's own
#: docstring for the merge/reduce distinction) exceeds ``Account.cash``.
#: Scoped to ``Account.asset_class == "forex"`` ONLY -- IDX/US/Crypto
#: orders never evaluate this gate and never raise this reason;
#: gate 8's own ``PRETRADE_REASON_INSUFFICIENT_CASH`` remains
#: untouched and still applies, byte-for-byte, to every non-Forex
#: account.
PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN = "FOREX_INSUFFICIENT_MARGIN"

PRETRADE_REJECTION_REASONS: tuple[str, ...] = (
    PRETRADE_REASON_ACCOUNT_NOT_FOUND,
    PRETRADE_REASON_EVIDENCE_MISSING,
    PRETRADE_REASON_APPROVAL_MISSING,
    PRETRADE_REASON_INVALID_SYMBOL,
    PRETRADE_REASON_INVALID_QUANTITY,
    PRETRADE_REASON_INVALID_LOT_SIZE,
    PRETRADE_REASON_INVALID_PRICE,
    PRETRADE_REASON_INSUFFICIENT_CASH,
    PRETRADE_REASON_INSUFFICIENT_POSITION,
    PRETRADE_REASON_DUPLICATE_REQUEST,
    PRETRADE_REASON_RISK_LIMIT_EXCEEDED,
    PRETRADE_REASON_KILL_SWITCH_ENGAGED,
    PRETRADE_REASON_MARKET_KILL_SWITCH_ENGAGED,
    PRETRADE_REASON_SYMBOL_KILL_SWITCH_ENGAGED,
    PRETRADE_REASON_DAILY_LOSS_LIMIT_EXCEEDED,
    PRETRADE_REASON_MAX_POSITION_VALUE_EXCEEDED,
    PRETRADE_REASON_US_MARKET_SESSION_CLOSED,
    PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL,
    PRETRADE_REASON_INVALID_PRICE_TICK,
    PRETRADE_REASON_CRYPTO_MARKET_CLOSED,
    PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE,
    PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED,
    PRETRADE_REASON_INVALID_FOREX_STOP_LOSS,
    PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN,
)


class PaperTradingEngine:
    """Pre-trade validation gate, then -- if and only if every gate
    passes -- ``OrderLifecycleService.create_order()`` followed by
    ``ExecutionService.execute_order()`` (unchanged Sprint 4 STEP 9
    sequence), followed by ``OrderIdempotencyRepository.create()``
    (Activation 3.2).

    Depends on ``OrderLifecycleService``/``ExecutionService``/
    ``AccountRepository``/``PositionRepository``/
    ``OrderIdempotencyRepository``/``AccountBalanceService``/
    ``PositionManager`` only -- no other Repository, no other
    Service, no Skill, no Tool. Never opens a transaction
    itself: every pre-trade gate is a plain read via ``_execute()``
    (never ``_session()``), and both Sprint-4 collaborators still own
    their own persistence exactly as Activation 3.1 audited.

    Activation 7 Blocker #4 (additive only, optional): also accepts an
    ``OrderApprovalRepository`` this engine writes one best-effort
    audit row to, after the trading state above is already fully
    committed -- see ``submit_order()``. Does not change gate 3 (the
    approval check itself), the required call order above, execution
    logic, or the transaction boundary in any way.
    """

    def __init__(
        self,
        order_lifecycle_service: OrderLifecycleService,
        execution_service: ExecutionService,
        account_repository: AccountRepository,
        position_repository: PositionRepository,
        order_idempotency_repository: OrderIdempotencyRepository,
        kill_switch_engaged: bool,
        max_order_value: float,
        execution_policy: ExecutionPolicy | None = None,
        account_balance_service: AccountBalanceService | None = None,
        position_manager: PositionManager | None = None,
        notification_builder: NotificationBuilder | None = None,
        notification_manager: NotificationManager | None = None,
        order_approval_repository: OrderApprovalRepository | None = None,
        halted_markets: frozenset[str] | None = None,
        halted_symbols: frozenset[str] | None = None,
        max_daily_loss: float | None = None,
        max_position_value: float | None = None,
    ) -> None:
        """Initialize the engine.

        Args:
            order_lifecycle_service: Used to create and structurally
                validate the ``Order``. Stored by reference only.
            execution_service: Used to execute an ``Order`` that is
                ``PENDING`` after ``order_lifecycle_service``.
                Stored by reference only.
            account_repository: Used by the "account aktif" and
                "available cash" pre-trade gates. Read-only from this
                engine's perspective -- never written to here.
            position_repository: Used by the "available position untuk
                SELL" pre-trade gate. Read-only from this engine's
                perspective -- never written to here.
            order_idempotency_repository: Used by the "duplicate
                request/idempotency" pre-trade gate, and written to
                once, after a successful ``Trade`` is created.
            kill_switch_engaged: When ``True``, every call to
                ``submit_order()`` is rejected by the kill-switch gate
                regardless of any other input. A plain value, not a
                live callback -- this engine reads it once per
                ``submit_order()`` call, so a caller that flips the
                underlying config must rebuild the engine (or its
                composition root) to pick up the change, mirroring how
                every other constructor-injected value in this
                codebase already works.
            max_order_value: Ceiling (in account currency) on a single
                order's notional value (``quantity * requested_price``)
                for the "risk limit" pre-trade gate.
            execution_policy: Canonical ``ExecutionPolicy`` (Activation
                3.3) this engine reads ``lot_size`` from for the "IDX
                lot size valid" pre-trade gate. Defaults to
                ``Business.execution_policy_config.
                load_execution_policy()`` when not supplied -- mirrors
                ``Business.execution_service.ExecutionService``'s same
                default pattern. The default policy's ``lot_size``
                reproduces ``Database.account_constants.
                IDX_LOT_SIZE_SHARES`` (``100``), so this engine's
                gate-6 behaviour for any caller that does not pass a
                policy explicitly is unchanged from before this
                Activation.
            account_balance_service: Canonical
                ``Business.account_balance_service.AccountBalanceService``
                (Activation 3.5 STEP 1) this engine calls
                ``apply_trade()`` on, once, immediately after
                ``execution_service.execute_order()`` succeeds -- see
                ``submit_order()``. Defaults to a fresh
                ``AccountBalanceService(account_repository)`` when not
                supplied, mirroring ``execution_policy``'s default
                pattern above and reusing this engine's own
                ``account_repository`` rather than constructing a
                second one -- so every existing caller/test that does
                not pass it keeps working unchanged, now also getting
                the cash update for free.
            position_manager: Canonical
                ``Business.position_manager.PositionManager`` (Sprint 4
                STEP 8) this engine calls ``apply_trade()`` on, once,
                immediately after ``account_balance_service.
                apply_trade()`` succeeds -- see ``submit_order()``.
                Defaults to a fresh
                ``PositionManager(position_repository)`` when not
                supplied, mirroring ``account_balance_service``'s
                default pattern above and reusing this engine's own
                ``position_repository`` rather than constructing a
                second one -- so every existing caller/test that does
                not pass it keeps working unchanged, now also getting
                the position update for free.
            notification_builder: ``Business.notification_builder.
                NotificationBuilder`` this engine calls
                ``build_order_executed(trade)`` on, once, after the
                idempotency key has been recorded -- see
                ``submit_order()``. Defaults to a fresh
                ``NotificationBuilder()`` when not supplied (that
                constructor takes no dependency), mirroring the
                ``execution_policy``/``account_balance_service``/
                ``position_manager`` default pattern above.
            notification_manager: ``Business.notification_manager.
                NotificationManager`` this engine calls ``notify()``
                on, once, with the event built above. Defaults to a
                ``NotificationManager`` wrapping a
                ``NotificationDispatcher`` with no channels configured
                when not supplied -- an inert default (nothing to
                dispatch to) so every existing caller/test that does
                not pass it keeps working unchanged; wiring this to
                real channels is the composition root's responsibility,
                not this engine's.
            order_approval_repository: Activation 7 Blocker #4
                addition. ``Repository.persistence.
                order_approval_repository.OrderApprovalRepository``
                this engine writes one ``order_approvals`` row to,
                best-effort, after the trading state (Order/Trade/
                Account/Position/idempotency-key) is already fully
                committed -- see ``submit_order()``. Defaults to
                ``None``, in which case this engine writes no
                approval-audit row at all (same "existing caller/test
                keeps working unchanged" default pattern as every
                other optional collaborator above) -- gate 3 (the
                approval check itself), execution logic, and the
                transaction boundary are completely unaffected either
                way.
            halted_markets: Activation 8.4 addition. Set of lower-case
                market identifiers (matching
                ``Core.market_config.current_market()``'s return
                value, e.g. ``"idx"``/``"us"``/``"crypto"``) for which
                order submission is blocked -- the "market kill
                switch" gate. Defaults to ``frozenset()`` (no market
                halted), so every existing caller/test that does not
                pass it keeps working unchanged. A plain value, not a
                live callback -- read once per ``submit_order()``
                call, mirroring ``kill_switch_engaged``'s own
                construct-once contract above.
            halted_symbols: Activation 8.4 addition. Set of
                upper-case symbols for which order submission is
                blocked -- the "symbol kill switch" gate. Defaults to
                ``frozenset()`` (no symbol halted). Same construct-once
                contract as ``halted_markets``.
            max_daily_loss: Activation 8.4 addition. When not
                ``None``, the "daily loss" gate rejects a BUY once the
                account's summed ``Position.realized_pnl`` (see gate
                15's inline comment for the honestly-documented
                "cumulative, not calendar-day" caveat this shares with
                ``Business.daily_performance_service.
                DailyPerformanceService``) is a loss whose magnitude
                already meets or exceeds this ceiling -- a
                non-negative number of account-currency units.
                Defaults to ``None`` (no daily-loss ceiling
                configured, gate never rejects), so every existing
                caller/test that does not pass it keeps working
                unchanged.
            max_position_value: Activation 8.4 addition. When not
                ``None``, the "position kill switch" gate rejects a
                BUY whose resulting position notional value
                (``(existing_quantity + order_quantity) *
                requested_price``, existing open position for this
                account+symbol read via ``position_repository``) would
                exceed this ceiling. Defaults to ``None`` (no
                position-value ceiling configured, gate never
                rejects), so every existing caller/test that does not
                pass it keeps working unchanged.
        """
        self._order_lifecycle_service = order_lifecycle_service
        self._execution_service = execution_service
        self._account_repository = account_repository
        self._position_repository = position_repository
        self._order_idempotency_repository = order_idempotency_repository
        self._kill_switch_engaged = kill_switch_engaged
        self._max_order_value = max_order_value
        self._execution_policy = execution_policy if execution_policy is not None else load_execution_policy()
        self._account_balance_service = (
            account_balance_service
            if account_balance_service is not None
            else AccountBalanceService(account_repository)
        )
        self._position_manager = (
            position_manager
            if position_manager is not None
            else PositionManager(position_repository)
        )
        self._notification_builder = (
            notification_builder if notification_builder is not None else NotificationBuilder()
        )
        self._notification_manager = (
            notification_manager
            if notification_manager is not None
            else NotificationManager(NotificationDispatcher(channels=[]))
        )
        self._order_approval_repository = order_approval_repository
        # Normalized here, once, at construction time -- not just at
        # the composition-root call site -- so this engine's gate
        # 13/14 comparison is correct regardless of the case a caller
        # (composition root, a test, or any future wiring) happens to
        # pass in. Mirrors this method's own defensive posture toward
        # every other constructor-injected collection in this
        # codebase: never trust the caller to have already normalized
        # a value this class's own gate depends on.
        self._halted_markets = (
            frozenset(m.strip().lower() for m in halted_markets if isinstance(m, str))
            if halted_markets is not None
            else frozenset()
        )
        self._halted_symbols = (
            frozenset(s.strip().upper() for s in halted_symbols if isinstance(s, str))
            if halted_symbols is not None
            else frozenset()
        )
        self._max_daily_loss = max_daily_loss
        self._max_position_value = max_position_value

    def submit_order(
        self,
        account_id: str,
        symbol: str,
        action: str,
        quantity: float,
        requested_price: float,
        executed_at: str,
        signal_evidence: object,
        user_approval: bool,
        idempotency_key: str,
        stop_loss: float | None = None,
    ) -> Trade:
        """Run all 17 pre-trade gates, then submit and, if possible,
        execute a single paper order.

        If every pre-trade gate passes, calls
        ``OrderLifecycleService.create_order()`` first. If the
        resulting order's status is not ``"PENDING"`` (structural
        validation rejected it), no execution is attempted and this
        method raises ``ValidationError``. Otherwise calls
        ``ExecutionService.execute_order()`` on it, applies the
        resulting ``Trade``'s cash impact via
        ``AccountBalanceService.apply_trade()`` (Activation 3.5
        STEP 1), applies its position impact via
        ``PositionManager.apply_trade()`` (Activation 3.5 STEP 2),
        records the idempotency key, and returns the resulting
        ``Trade``.

        Args:
            account_id: Owning account's ``account_id``. Passed
                through to ``OrderLifecycleService.create_order()``
                unchanged.
            symbol: Traded symbol/ticker.
            action: Requested action (``"BUY"``/``"SELL"``).
            quantity: Requested quantity.
            requested_price: Requested price.
            executed_at: ISO-8601 timestamp passed through to
                ``ExecutionService.execute_order()`` unchanged -- this
                method generates no timestamp of its own.
            signal_evidence: Caller-supplied evidence backing this
                order (e.g. the signal/analysis that triggered it).
                Must be truthy -- gate 2.
            user_approval: Must be exactly ``True`` -- gate 3.
            idempotency_key: Caller-supplied, non-empty, unique-per-
                intended-submission key -- gate 10. Recorded in
                ``order_idempotency_keys`` after a successful
                ``Trade`` is created (see module docstring's LOCKED
                DECISION on write timing).
            stop_loss: Activation 11.14 addition, OPTIONAL, defaults
                to ``None``. Ignored entirely for every account whose
                ``Account.asset_class`` is not ``"forex"`` -- IDX/US/
                Crypto orders keep working exactly as before this
                Activation whether or not a caller passes this. For a
                Forex account ONLY: REQUIRED (``None`` is rejected by
                the new Forex stop-loss gate below) and validated
                against the resulting/existing ``Position.direction``
                using the same direction-aware rule Activation 11.13
                already established (LONG: below ``requested_price``;
                SHORT: above it; equal is always invalid). On success,
                persisted onto the ``Position`` via
                ``PositionManager.set_stop_loss_take_profit()``,
                called once, immediately after ``PositionManager.
                apply_trade()`` below -- this method still never
                writes a caller-supplied ``stop_loss``/``take_profit``
                value itself, per its own LOCKED docstring contract.

        Returns:
            The ``Trade`` created by ``ExecutionService.execute_order()``.

        Raises:
            ValidationError: If any pre-trade gate fails (see
                ``PRETRADE_REJECTION_REASONS``), if the order's status
                after ``create_order()`` is not ``"PENDING"``, or if
                any underlying Service/Repository raises one.
            RepositoryError: If any underlying repository call fails.
        """
        self._run_pre_trade_validation(
            account_id=account_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            requested_price=requested_price,
            executed_at=executed_at,
            signal_evidence=signal_evidence,
            user_approval=user_approval,
            idempotency_key=idempotency_key,
            stop_loss=stop_loss,
        )

        # Activation 5.1: the only decision-linkage field with a
        # genuine, already-existing production source (see
        # ``Database.models.Order`` docstring / ``Database.
        # migrations_orders`` version=15). ``signal_evidence`` is
        # already the caller's evidence object for this order (gate 2
        # above only checks it is truthy) -- if it happens to carry a
        # ``snapshot_id`` attribute (the production CLI path always
        # passes a ``RankingSnapshot``), that ID travels with the
        # ``Order`` it backs. Anything else (a plain dict/str/None, as
        # every non-CLI test in this suite already supplies) has no
        # such attribute, and this reads as ``None`` -- never guessed,
        # never fabricated.
        analysis_snapshot_id = getattr(signal_evidence, "snapshot_id", None)

        order = self._order_lifecycle_service.create_order(
            account_id=account_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            requested_price=requested_price,
            analysis_snapshot_id=analysis_snapshot_id,
        )

        if order.status != "PENDING":
            raise ValidationError(
                f"{_REASON_NOT_PENDING}: order {order.order_id} has status "
                f"'{order.status}', expected 'PENDING'",
                details={"order_id": order.order_id, "status": order.status},
            )

        trade = self._execution_service.execute_order(order.order_id, executed_at)

        self._account_balance_service.apply_trade(trade)

        position = self._position_manager.apply_trade(trade)

        # Activation 11.14: for a Forex account ONLY, the pre-trade
        # gate above has already required and direction-validated
        # ``stop_loss`` against ``requested_price`` -- this is the
        # single place that actually PERSISTS it onto the ``Position``
        # ``apply_trade()`` above just created/merged/reduced.
        # ``PositionManager.apply_trade()`` itself never writes a
        # caller-supplied ``stop_loss`` (see its own LOCKED docstring
        # contract) -- ``set_stop_loss_take_profit()`` is the only
        # method that ever does, and it re-validates against the
        # ``Position``'s now-final ``average_price`` using the exact
        # same ``is_stop_loss_side_valid()`` rule the pre-trade gate
        # already checked against ``requested_price``, so this call is
        # only ever a no-op re-confirmation for a fresh position
        # (``average_price == requested_price`` there) or a
        # same-price merge/reduce (this Activation's own test suite
        # only exercises those two shapes) -- never expected to raise
        # here. Not called at all for non-Forex accounts (``stop_loss
        # is None`` in that case, and ``set_stop_loss_take_profit``'s
        # own "leave unchanged only if the caller re-supplies the
        # current value" contract does not apply -- calling it with
        # ``None`` here would incorrectly CLEAR an existing SL/TP on
        # every single order, which this Activation must not do), so
        # this block is a strict no-op for every existing IDX/US/
        # Crypto caller.
        if stop_loss is not None:
            self._position_manager.set_stop_loss_take_profit(
                position.position_id,
                stop_loss=stop_loss,
                # Passed straight back through from the just-updated
                # ``position`` (never a bare ``None``) so this call
                # can only ever change ``stop_loss`` -- an existing
                # ``take_profit`` (out of scope for this Activation,
                # per the brief's "do not introduce a second large
                # API change solely for take_profit") is left exactly
                # as ``apply_trade()`` already carried it through.
                take_profit=position.take_profit,
            )

        self._order_idempotency_repository.create(
            idempotency_key=idempotency_key,
            account_id=account_id,
            order_id=trade.order_id,
            trade_id=trade.trade_id,
        )

        # Activation 7 Blocker #4: the trading state is already fully
        # committed at this point (Order/Trade/Account/Position/
        # idempotency-key rows all written) -- exactly the same
        # commit point the notification block below already documents
        # itself as running after. Persisting the ``user_approval``
        # gate-3 already required (LOCKED, unchanged) is best-effort
        # from here on: if writing the ``order_approvals`` row raises
        # for any reason, that exception is never propagated and never
        # rolls back the already-successful trade (``trade`` below is
        # returned unconditionally either way) -- mirroring the
        # notification failure handling immediately below, and per
        # this Activation's explicit brief ("tidak boleh membuat trade
        # rollback jika proses audit-record gagal"). No identity is
        # recorded -- only the approval state this engine's own gate 3
        # already verified (``user_approval is True``, or this method
        # would already have raised above), a write timestamp, and
        # linkage to the ``Order``/``Trade``/``Account`` it gated. A
        # caller that has not wired an ``order_approval_repository``
        # (the default) causes no write attempt at all -- unchanged
        # behaviour for every existing caller/test.
        if self._order_approval_repository is not None:
            try:
                self._order_approval_repository.create(
                    order_id=trade.order_id,
                    trade_id=trade.trade_id,
                    account_id=account_id,
                    approved=user_approval,
                )
            except Exception:
                logger.error(
                    "order_approvals audit record failed for trade_id=%s "
                    "order_id=%s account_id=%s symbol=%s -- trade remains "
                    "committed; approval audit row was not persisted.",
                    trade.trade_id,
                    trade.order_id,
                    account_id,
                    symbol,
                    exc_info=True,
                )

        # Activation (notification wiring), amended by Activation 7
        # FIX (blocker 1): the Trade is already fully committed at
        # this point (Order/Trade/Account/Position/idempotency-key
        # rows all written). Sending the ORDER_EXECUTED notification
        # remains best-effort from here on -- if building or sending
        # it raises for any reason, that exception is still never
        # propagated and never rolls back the already-successful
        # trade (``trade`` below is returned unconditionally,
        # regardless of what happens in this block). What changed:
        # the failure is no longer silently discarded -- it is logged
        # (visible in the application log, with the exception detail
        # and enough context to find the trade it belongs to) before
        # being swallowed. No retry, no queue, no new notification
        # channel, and no change to ``NotificationBuilder``/
        # ``NotificationManager``/the Telegram channel -- only this
        # one previously-bare ``except Exception: pass`` gained a
        # logging call.
        try:
            event = self._notification_builder.build_order_executed(trade)
            self._notification_manager.notify(event)
        except Exception:
            logger.error(
                "ORDER_EXECUTED notification failed for trade_id=%s order_id=%s "
                "account_id=%s symbol=%s -- trade remains committed; "
                "notification was not delivered.",
                trade.trade_id,
                trade.order_id,
                account_id,
                symbol,
                exc_info=True,
            )

        return trade

    def _run_pre_trade_validation(
        self,
        account_id: str,
        symbol: str,
        action: str,
        quantity: float,
        requested_price: float,
        executed_at: str,
        signal_evidence: object,
        user_approval: bool,
        idempotency_key: str,
        stop_loss: float | None = None,
    ) -> None:
        """Run all 19 pre-trade gates, in the LOCKED order documented
        in the module docstring. First failing gate raises
        ``ValidationError`` immediately -- every gate below it is
        never evaluated. Purely read-only: no ``_execute`` call made
        by any gate below is an ``INSERT``/``UPDATE``/``DELETE``.
        """
        # 1. account aktif (== exists; see LOCKED DECISION above)
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Account '{account_id}' not found",
                details={"reason": PRETRADE_REASON_ACCOUNT_NOT_FOUND, "account_id": account_id},
            )

        # 2. signal/evidence tersedia
        if not signal_evidence:
            raise ValidationError(
                "signal_evidence is required and must be truthy",
                details={"reason": PRETRADE_REASON_EVIDENCE_MISSING, "account_id": account_id},
            )

        # 3. user approval tersedia
        if user_approval is not True:
            raise ValidationError(
                "user_approval is required and must be True",
                details={"reason": PRETRADE_REASON_APPROVAL_MISSING, "account_id": account_id},
            )

        # 4. symbol valid
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValidationError(
                f"Invalid symbol: {symbol!r}",
                details={"reason": PRETRADE_REASON_INVALID_SYMBOL, "symbol": symbol},
            )

        # 5. quantity valid
        if not self._is_positive_number(quantity):
            raise ValidationError(
                f"Invalid quantity: {quantity!r}",
                details={"reason": PRETRADE_REASON_INVALID_QUANTITY, "quantity": quantity},
            )

        # 6. Market quantity rule
        #
        # Activation 9.2 bypassed the IDX lot-size multiple check for
        # both "crypto" and "us" -- IDX's 100-share lot convention is
        # an IDX-specific rule (Bursa Efek Indonesia board-lot
        # convention), not a universal one. Activation 9.3 STEP 1
        # replaces the bare "us" bypass with a real policy-driven
        # check: US common-stock/ETF orders now consult
        # ``Business.us_market_policy.USFractionalSharePolicy`` (via
        # ``load_us_fractional_share_policy()``, loaded fresh on every
        # call -- never cached -- so a test that changes
        # ``US_FRACTIONAL_*`` env vars between calls sees the new
        # policy immediately, Requirement 6) instead of merely
        # skipping the check. Default policy (fractional disabled,
        # whole-share precision) still rejects a fractional quantity,
        # so this is a strictly more precise version of the same
        # "whole US shares only by default" behavior the 9.2 comment
        # already documented, not a behavior change for the common
        # case. IDX's own enforcement (``market == "idx"``) is
        # completely untouched below. Crypto's existing bypass is also
        # completely untouched -- "market == 'crypto'" still skips
        # this check entirely, exactly as Activation 9.2 left it; this
        # STEP does not redesign crypto (see brief Requirement 5/G).
        lot_size = self._execution_policy.lot_size
        market = os.getenv("AIOS_MARKET", "idx").strip().lower() or "idx"
        if market == "us":
            us_fractional_policy = load_us_fractional_share_policy()
            if not us_fractional_policy.is_quantity_allowed(quantity):
                raise ValidationError(
                    f"Quantity {quantity} is not permitted under the US "
                    f"fractional-share policy (enabled="
                    f"{us_fractional_policy.enabled}, min_quantity="
                    f"{us_fractional_policy.min_quantity}, "
                    f"quantity_precision={us_fractional_policy.quantity_precision})",
                    details={
                        "reason": PRETRADE_REASON_INVALID_LOT_SIZE,
                        "quantity": quantity,
                        "market": market,
                    },
                )
        elif market == "crypto":
            # Activation 10.2: crypto quantities are no longer merely
            # bypassed -- they now consult a real, symbol-specific
            # ``CryptoQuantityPolicy`` (via ``load_crypto_quantity_
            # policy()``, loaded fresh on every call -- never cached,
            # mirroring ``load_us_fractional_share_policy()``'s own
            # contract immediately above) instead of skipping straight
            # through. This checks quantity precision AND step size
            # together (see ``Business.crypto_quantity_policy.
            # CryptoQuantityPolicy.is_quantity_valid``) -- minimum
            # notional is a separate, price-dependent check performed
            # further below, immediately after gate 7 validates
            # ``requested_price`` (this policy object is loaded once
            # here and reused there, so both checks agree on exactly
            # the same configured policy for this call). IDX's own
            # ``elif quantity % lot_size != 0`` branch below is
            # completely untouched -- this ``elif market == "crypto"``
            # branch is checked first and is mutually exclusive with
            # it, so "market == crypto" never falls through to the IDX
            # lot-size check (Requirement 5 / IDX isolation).
            crypto_quantity_policy = load_crypto_quantity_policy(symbol)
            if not crypto_quantity_policy.is_quantity_valid(quantity):
                raise ValidationError(
                    f"Quantity {quantity} is not permitted under the crypto "
                    f"quantity policy for '{symbol}' (step_size="
                    f"{crypto_quantity_policy.step_size}, quantity_precision="
                    f"{crypto_quantity_policy.quantity_precision})",
                    details={
                        "reason": PRETRADE_REASON_INVALID_LOT_SIZE,
                        "quantity": quantity,
                        "market": market,
                        "symbol": symbol,
                        "step_size": crypto_quantity_policy.step_size,
                        "quantity_precision": crypto_quantity_policy.quantity_precision,
                    },
                )
        elif market == "forex":
            # Activation 11.24: Forex quantity represents base-currency
            # units directly (Activation 11.1's LOCKED "quantity =
            # base-currency units directly" decision -- no
            # standard/mini/micro broker-lot conversion is introduced
            # here). The IDX 100-share lot convention above is an
            # IDX-specific board-lot rule and must not leak into Forex,
            # mirroring how "us"/"crypto" above each already bypass it
            # with their own market-appropriate check instead of a bare
            # skip. The only rule enforced at this initial paper-Forex
            # stage is "whole base-currency units" (no fractional-unit
            # support is invented, per the roadmap's explicit "do not
            # invent fractional Forex support"); this reuses
            # ``PRETRADE_REASON_INVALID_LOT_SIZE``, the same reason code
            # the "us"/IDX quantity-precision checks above already use
            # for an analogous violation, rather than adding a new
            # reason taxonomy for what is still fundamentally a
            # quantity-precision rejection. This branch is checked
            # before, and is mutually exclusive with, the IDX
            # ``elif quantity % lot_size != 0`` branch below, so a
            # Forex order never falls through to the IDX lot-size
            # check (Requirement: "IDX must remain unchanged").
            if quantity != math.floor(quantity):
                raise ValidationError(
                    f"Quantity {quantity} is not a whole number of base-currency "
                    f"units (Forex paper orders use whole base-currency units, "
                    f"not IDX-style lots)",
                    details={
                        "reason": PRETRADE_REASON_INVALID_LOT_SIZE,
                        "quantity": quantity,
                        "market": market,
                    },
                )
        elif quantity % lot_size != 0:
            raise ValidationError(
                f"Quantity {quantity} is not a multiple of the IDX lot size "
                f"({lot_size} shares)",
                details={
                    "reason": PRETRADE_REASON_INVALID_LOT_SIZE,
                    "quantity": quantity,
                    "lot_size": lot_size,
                },
            )

        # 7. price positif
        if not self._is_positive_number(requested_price):
            raise ValidationError(
                f"Invalid requested_price: {requested_price!r}",
                details={"reason": PRETRADE_REASON_INVALID_PRICE, "requested_price": requested_price},
            )

        order_value = quantity * requested_price

        # Crypto price tick (Activation 10.3, market == "crypto" only).
        # Checked here -- immediately after gate 7 validates
        # ``requested_price`` and BEFORE the minimum-notional check
        # immediately below -- because price tick is a pure per-price
        # alignment rule (does not depend on quantity at all), so it
        # naturally belongs right after the gate that first produces a
        # validated ``requested_price``, and checking it first
        # guarantees a price that is both off-tick AND
        # below-minimum-notional is rejected for the off-tick reason
        # (the more fundamental defect -- an unaligned price is not a
        # price this paper market can even express), not the
        # notional-floor reason (Requirement G of the Activation 10.3
        # brief). A price that IS on-tick but still below minimum
        # notional falls through to the existing minimum-notional
        # check unchanged. Uses ``Business.crypto_price_policy.
        # load_crypto_price_policy`` (loaded fresh on every call --
        # never cached -- mirroring ``load_crypto_quantity_policy``'s
        # own contract). Applies to BOTH BUY and SELL (Requirement 4):
        # neither side of the book is exempt, exactly like the
        # minimum-notional check immediately below. market == "idx"
        # and market == "us" never reach this branch at all -- crypto
        # price-tick rules cannot leak into either (Requirement 5 /
        # IDX-US isolation).
        if market == "crypto":
            crypto_price_policy = load_crypto_price_policy(symbol)
            if not crypto_price_policy.is_price_valid(requested_price):
                raise ValidationError(
                    f"Price {requested_price} for '{symbol}' is not aligned "
                    f"to the crypto price tick {crypto_price_policy.price_tick}",
                    details={
                        "reason": PRETRADE_REASON_INVALID_PRICE_TICK,
                        "market": market,
                        "symbol": symbol,
                        "requested_price": requested_price,
                        "price_tick": crypto_price_policy.price_tick,
                    },
                )

        # Crypto minimum notional (Activation 10.2, market == "crypto"
        # only). Checked here -- immediately after gate 7 validates
        # ``requested_price`` and computes ``order_value`` -- because
        # minimum notional is inherently price-dependent (unlike gate
        # 6's pure-quantity checks above), so it cannot be evaluated
        # any earlier. Reuses the exact same ``crypto_quantity_policy``
        # gate 6 already loaded for this call (never re-loaded, so
        # both checks are guaranteed to agree on the same configured
        # policy) and the exact same ``requested_price`` used for
        # ``order_value``/gate 8's required-cash calculation/the
        # eventual ``Trade.fill_price`` (``ExecutionService`` fills at
        # ``Order.requested_price`` -- see that module's own "filled
        # at the price that was requested" docstring note), never a
        # separately-fetched price. Applies to BOTH BUY and SELL
        # (Requirement 4): a SELL that would close out a
        # below-minimum-notional remainder is still rejected here,
        # exactly as the brief's minimum-notional semantics require --
        # this is not a "SELL is exempt like gates 8/15/16" case,
        # since shrinking a position below the exchange's minimum
        # tradable size is exactly the scenario a minimum-notional
        # rule exists to prevent, on either side of the book.
        # market == "idx" and market == "us" never reach this branch
        # at all -- crypto minimum-notional cannot leak into either
        # (Requirement 5 / IDX-US isolation).
        if market == "crypto" and not crypto_quantity_policy.meets_minimum_notional(
            quantity, requested_price
        ):
            raise ValidationError(
                f"Order notional {order_value} for '{symbol}' is below the "
                f"crypto minimum notional {crypto_quantity_policy.minimum_notional} "
                f"(quantity {quantity} x requested_price {requested_price})",
                details={
                    "reason": PRETRADE_REASON_BELOW_MINIMUM_NOTIONAL,
                    "market": market,
                    "symbol": symbol,
                    "quantity": quantity,
                    "requested_price": requested_price,
                    "order_value": order_value,
                    "minimum_notional": crypto_quantity_policy.minimum_notional,
                },
            )

        # Forex stop-loss required + direction gate (Activation 11.14,
        # additive, does not renumber any existing gate -- inserted
        # here, immediately after gate 7 validates ``requested_price``,
        # mirroring exactly where Activation 10.2/10.3 inserted their
        # own crypto-only checks above: this rule is price-dependent
        # (it compares ``stop_loss`` against ``requested_price``) and
        # must reject before any financial mutation, so it cannot run
        # any earlier than gate 7, and there is no reason to make it
        # run any later. Scoped to ``Account.asset_class == "forex"``
        # ONLY (Activation 11.10-H/11.12) -- ``market`` above is the
        # ``AIOS_MARKET`` env-derived idx/us/crypto switch gate 6
        # already reads, a completely separate concept from
        # ``Account.asset_class``; IDX/US/Crypto orders never touch
        # this block regardless of ``market``'s value, and their
        # ``stop_loss`` argument (whatever a caller passes, including
        # the default ``None``) is silently ignored here -- unchanged
        # behavior for every existing non-Forex caller/test.
        is_forex = account.asset_class == _FOREX_ASSET_CLASS
        if is_forex:
            # Effective direction of the Position this order will
            # create/merge/reduce: mirrors ``PositionManager.
            # apply_trade()``'s own LOCKED direction rules (Activation
            # 11.12) exactly -- an existing OPEN position's direction
            # always wins (a same-direction trade merges, an
            # opposite-direction trade reduces; either way the
            # Position's direction itself never changes mid-lifecycle);
            # only with NO existing OPEN position does the action
            # itself decide it (BUY -> LONG, SELL -> SHORT). Read-only
            # -- this lookup does not replace gate 9's own
            # ``get_open_position`` call below (kept separate so this
            # gate's docstring/scope stays self-contained), but it is
            # the same non-mutating repository method.
            open_position = self._position_repository.get_open_position(account_id, symbol)
            if open_position is not None:
                effective_direction = open_position.direction
            else:
                effective_direction = _DIRECTION_LONG if action == _BUY else _DIRECTION_SHORT

            if stop_loss is None:
                raise ValidationError(
                    f"stop_loss is required for Forex account '{account_id}' "
                    f"symbol '{symbol}'",
                    details={
                        "reason": PRETRADE_REASON_FOREX_STOP_LOSS_REQUIRED,
                        "account_id": account_id,
                        "symbol": symbol,
                        "action": action,
                    },
                )
            if not is_stop_loss_side_valid(effective_direction, requested_price, stop_loss):
                raise ValidationError(
                    f"stop_loss {stop_loss} is not valid against requested_price "
                    f"{requested_price} for account '{account_id}' symbol "
                    f"'{symbol}' ({effective_direction})",
                    details={
                        "reason": PRETRADE_REASON_INVALID_FOREX_STOP_LOSS,
                        "account_id": account_id,
                        "symbol": symbol,
                        "action": action,
                        "requested_price": requested_price,
                        "stop_loss": stop_loss,
                        "direction": effective_direction,
                    },
                )

            # Forex required-margin gate (Activation 11.15, additive,
            # does not renumber any existing gate). Inserted here --
            # immediately after the Forex stop-loss gate above,
            # reusing the same ``open_position`` lookup it already
            # performed (never a second, redundant read) -- so it runs
            # after symbol/quantity/price/stop-loss are all valid and
            # strictly before gate 8 / any Order/Trade/Account/
            # Position mutation, per the roadmap's gate-placement
            # rule. Scoped to ``Account.asset_class == "forex"`` ONLY
            # -- IDX/US/Crypto orders never evaluate this block and
            # never raise its reason code; their own gate 8 below is
            # completely unaffected (see gate 8's own inline comment
            # for the ``not is_forex`` exclusion this gate requires).
            #
            # Margin is required only for NEW exposure, never for the
            # gross order quantity (Activation 11.15 "IMPORTANT:
            # MARGIN IS FOR NEW EXPOSURE"): a trade on the SAME side as
            # any existing OPEN position (BUY on no-position/LONG,
            # SELL on no-position/SHORT) adds new exposure equal to
            # its full quantity; a trade on the OPPOSITE side (BUY
            # reducing an existing SHORT, SELL reducing an existing
            # LONG) only creates new exposure for the portion, if any,
            # that exceeds the existing position's quantity -- a pure
            # reduction (quantity <= existing quantity) is always
            # ``0.0`` new exposure and never requires margin, even
            # when the gross trade notional would exceed available
            # cash. ``trade_direction`` here is deliberately NOT the
            # same value as ``effective_direction`` above: that one is
            # "the resulting/existing position's direction" (used for
            # the stop-loss side check); this one is "the direction
            # this trade's action would open from flat" (used only to
            # decide merge-vs-reduce for margin), and the two disagree
            # exactly when this trade reduces an existing opposite
            # position -- which is precisely the case this gate must
            # tell apart from a merge.
            trade_direction = _DIRECTION_LONG if action == _BUY else _DIRECTION_SHORT
            if open_position is None or trade_direction == open_position.direction:
                new_exposure_quantity = quantity
            else:
                new_exposure_quantity = max(0.0, quantity - open_position.quantity)

            if new_exposure_quantity > 0:
                # Business.forex_margin_policy.calculate_required_margin
                # is the ONLY calculation source for required margin
                # (LOCKED formula: price * quantity at 1:1 paper
                # leverage) -- never inlined/reimplemented here. Its
                # own pair-normalization accepts ``symbol`` in either
                # ``"EUR/USD"`` or ``"EURUSD"`` form, so it is passed
                # through unchanged, exactly as every other gate above
                # already passes ``symbol`` straight through without
                # reformatting it.
                required_margin = calculate_required_margin(
                    symbol, requested_price, new_exposure_quantity
                )
                if account.cash < float(required_margin):
                    raise ValidationError(
                        f"Insufficient Forex margin: account '{account_id}' has "
                        f"cash {account.cash}, new exposure of "
                        f"{new_exposure_quantity} '{symbol}' at {requested_price} "
                        f"requires {required_margin}",
                        details={
                            "reason": PRETRADE_REASON_FOREX_INSUFFICIENT_MARGIN,
                            "account_id": account_id,
                            "symbol": symbol,
                            "action": action,
                            "cash": account.cash,
                            "requested_price": requested_price,
                            "order_quantity": quantity,
                            "new_exposure_quantity": new_exposure_quantity,
                            "required_margin": float(required_margin),
                        },
                    )

        # 8. available cash (BUY only)
        #
        # Activation 3.5 STEP 3: this gate used to compare against
        # bare ``order_value`` (== gross_value), which ignored fee/tax
        # entirely -- a real gap, since AccountBalanceService.
        # apply_trade() (the component that actually debits cash) has
        # always required ``gross_value + fee + tax``. A BUY could
        # pass this gate on cash that gross_value alone fit, reach
        # ExecutionService (Order -> FILLED, Trade persisted), and
        # only then be rejected by apply_trade() once fee/tax were
        # accounted for -- leaving an orphaned FILLED Order/Trade with
        # no cash impact ever applied.
        #
        # Fixed by using the same required_cash formula
        # AccountBalanceService uses (via the shared
        # ``compute_buy_required_cash()`` helper, so the sum itself is
        # written in exactly one place) against the same fee/tax this
        # BUY will actually carry. ``fee``/``tax`` here are resolved
        # via ``Business.us_market_policy.resolve_fee_tax()``
        # (Activation 9.3 STEP 1) -- the single shared selection
        # function ``ExecutionService.execute_order()`` also calls, so
        # both are guaranteed to agree: for ``market == "us"`` both
        # read ``USFeePolicy`` instead of silently falling back to
        # IDX's ``self._execution_policy`` (the exact leak the 9.3
        # audit found -- Requirement 2); for every other market
        # (``"idx"``, ``"crypto"``) both still read
        # ``self._execution_policy`` exactly as before this STEP
        # (Requirement 3, byte-for-byte unchanged). Because both
        # PaperTradingEngine and ExecutionService call the same
        # function with the same ``market``/``action`` inputs, the
        # fee/tax used here is guaranteed identical to what
        # ExecutionService will compute moments later for the same
        # order (Requirement 4).
        #
        # Activation 10.4 (additive): for market == "crypto",
        # resolve_fee_tax now also takes `symbol` and selects a fee
        # from Business.crypto_fee_policy.CryptoFeePolicy instead of
        # falling back to IDX's self._execution_policy (the leak
        # Activation 10.4 Requirement 3 closes -- see that function's
        # own docstring). `execution_liquidity` is left at its default
        # (Business.crypto_fee_policy.TAKER) here, matching every
        # current CLI market-style crypto order (see
        # Business.crypto_fee_policy module docstring's "Maker/taker
        # representation" section) -- this gate does not pass a
        # different value, since this engine has no maker-capable
        # order type to distinguish. market in ("idx", "us") are
        # completely unaffected by this parameter.
        # Activation 11.15 (additive): ``not is_forex`` added to this
        # gate's condition. Forex accounts have their own, exposure-
        # aware affordability gate above (required margin for the
        # incremental NEW exposure, via
        # ``Business.forex_margin_policy.calculate_required_margin``)
        # that already ran before this point -- this gate's
        # gross-order-quantity cash check (``order_value`` = full
        # trade notional, with no exposure-direction awareness) would
        # otherwise incorrectly reject a Forex BUY that reduces an
        # existing SHORT purely because the gross notional exceeds
        # cash, even though reducing exposure requires no new margin
        # at all (Case H in the Activation 11.15 brief). IDX/US/Crypto
        # accounts (``is_forex`` always ``False``) are completely
        # unaffected -- this gate's condition and behavior for every
        # existing non-Forex caller/test are byte-for-byte unchanged.
        buy_fee, buy_tax = resolve_fee_tax(market, action, self._execution_policy, symbol=symbol)
        required_cash = compute_buy_required_cash(order_value, buy_fee, buy_tax)
        if action == _BUY and not is_forex and account.cash < required_cash:
            raise ValidationError(
                f"Insufficient cash: account '{account_id}' has {account.cash}, "
                f"order requires {required_cash} (gross_value {order_value} + fee "
                f"{buy_fee} + tax {buy_tax})",
                details={
                    "reason": PRETRADE_REASON_INSUFFICIENT_CASH,
                    "account_id": account_id,
                    "cash": account.cash,
                    "order_value": order_value,
                    "fee": buy_fee,
                    "tax": buy_tax,
                    "required_cash": required_cash,
                },
            )

        # 9. available position untuk SELL (SELL only)
        #
        # Activation 11.14 (additive, does not change this gate's
        # behavior for any non-Forex account): a Forex SELL that opens
        # a brand-new SHORT (no existing OPEN position) or merges into
        # an existing SHORT (Activation 11.12's own LOCKED
        # same-direction-merge rule) is not "selling out of" a LONG at
        # all -- there is no quantity ceiling to bound it against, so
        # this gate must not apply to either case (it would otherwise
        # incorrectly reject every Forex short-open/short-add SELL
        # with "0.0 available" or an under-counted SHORT quantity,
        # which is exactly the pre-11.14 gap this Activation's audit
        # found: this gate long predates any Forex awareness and was
        # written assuming SELL can only ever reduce a LONG). Reuses
        # the ``open_position``/``is_forex`` the Forex stop-loss gate
        # above already computed -- never a second, redundant lookup
        # for a Forex account. A Forex SELL that reduces an existing
        # LONG (the opposite-direction case) still goes through the
        # unchanged check below, exactly like every non-Forex SELL.
        if action == _SELL:
            if is_forex:
                sell_position = open_position
            else:
                sell_position = self._position_repository.get_open_position(account_id, symbol)
            if is_forex and (sell_position is None or sell_position.direction == _DIRECTION_SHORT):
                pass
            else:
                available_quantity = sell_position.quantity if sell_position is not None else 0.0
                if available_quantity < quantity:
                    raise ValidationError(
                        f"Insufficient position: account '{account_id}' symbol "
                        f"'{symbol}' has {available_quantity}, order requests {quantity}",
                        details={
                            "reason": PRETRADE_REASON_INSUFFICIENT_POSITION,
                            "account_id": account_id,
                            "symbol": symbol,
                            "available_quantity": available_quantity,
                            "requested_quantity": quantity,
                        },
                    )

        # 10. duplicate request/idempotency
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError(
                f"Invalid idempotency_key: {idempotency_key!r}",
                details={
                    "reason": PRETRADE_REASON_DUPLICATE_REQUEST,
                    "idempotency_key": idempotency_key,
                },
            )
        existing = self._order_idempotency_repository.get_by_key(idempotency_key)
        if existing is not None:
            raise ValidationError(
                f"Duplicate request: idempotency_key '{idempotency_key}' already used "
                f"(order_id={existing.order_id}, trade_id={existing.trade_id})",
                details={
                    "reason": PRETRADE_REASON_DUPLICATE_REQUEST,
                    "idempotency_key": idempotency_key,
                    "order_id": existing.order_id,
                    "trade_id": existing.trade_id,
                },
            )

        # 11. risk limit
        if order_value > self._max_order_value:
            raise ValidationError(
                f"Order value {order_value} exceeds risk limit {self._max_order_value}",
                details={
                    "reason": PRETRADE_REASON_RISK_LIMIT_EXCEEDED,
                    "order_value": order_value,
                    "max_order_value": self._max_order_value,
                },
            )

        # 12. kill switch
        if self._kill_switch_engaged:
            raise ValidationError(
                "Kill switch is engaged: all order submission is blocked",
                details={"reason": PRETRADE_REASON_KILL_SWITCH_ENGAGED},
            )

        # 13. market kill switch (Activation 8.4)
        #
        # Blocks every order for the currently active market
        # (Core.market_config.current_market(), read the same way
        # gate 6 above already reads it via os.getenv("AIOS_MARKET")
        # -- deliberately the bare env read, not the module function,
        # mirroring gate 6's own "re-declared, not imported" style for
        # a value this engine only needs to compare, not resolve). A
        # halted market blocks BUY and SELL alike -- there is no
        # partial-halt concept here, matching the "global" kill
        # switch's own all-or-nothing semantics one level down.
        active_market = os.getenv("AIOS_MARKET", "idx").strip().lower() or "idx"
        if active_market in self._halted_markets:
            raise ValidationError(
                f"Market kill switch is engaged for market '{active_market}': "
                "order submission is blocked",
                details={
                    "reason": PRETRADE_REASON_MARKET_KILL_SWITCH_ENGAGED,
                    "market": active_market,
                },
            )

        # 14. symbol kill switch (Activation 8.4)
        #
        # Blocks every order for one specific symbol, independent of
        # the market-wide and global switches above. Compared
        # case-insensitively (upper-cased) since symbols elsewhere in
        # this codebase are conventionally upper-case (see
        # Core.market_config.is_crypto_symbol's own
        # ``symbol.upper()`` comparison) but a caller's raw input is
        # not itself validated for case by gate 4 above.
        symbol_upper = symbol.upper() if isinstance(symbol, str) else symbol
        if symbol_upper in self._halted_symbols:
            raise ValidationError(
                f"Symbol kill switch is engaged for '{symbol_upper}': "
                "order submission is blocked",
                details={
                    "reason": PRETRADE_REASON_SYMBOL_KILL_SWITCH_ENGAGED,
                    "symbol": symbol_upper,
                },
            )

        # 15. daily loss kill switch (Activation 8.4, BUY only)
        #
        # Rejects a BUY once the account's accumulated realized loss
        # already meets or exceeds ``max_daily_loss``. SELL is never
        # blocked by this gate: a losing account must still be able
        # to close/reduce a position to stop further loss, mirroring
        # why gate 8 ("available cash") is itself BUY-only -- blocking
        # SELL here would trap an account in a losing position exactly
        # when a risk limit fires, the opposite of what a loss limit
        # is for.
        #
        # Honestly-documented limitation (shared with, and no worse
        # than, Business.daily_performance_service.
        # DailyPerformanceService's own "realized_result" field): this
        # engine has no calendar/timezone/trading-day boundary of its
        # own (LOCKED for this codebase -- see that service's module
        # docstring) and Position.realized_pnl is a cumulative,
        # per-row field with no per-period history anywhere in the
        # schema. So "daily loss" here means the same thing
        # DailyPerformanceService's "realized_result" already means:
        # summed Position.realized_pnl across every position (open and
        # closed) for this account, read via
        # ``position_repository.list_by_account`` -- not literally
        # scoped to calendar-day boundaries, since no component in
        # this codebase can currently draw one. An operator resets the
        # effective "day" by restarting the process with a config
        # change (mirrors ``kill_switch_engaged``'s own construct-once
        # contract) once a per-period aggregation exists to replace
        # this, this gate reads that instead -- no other line in this
        # method changes.
        if action == _BUY and self._max_daily_loss is not None:
            positions = self._position_repository.list_by_account(account_id)
            realized_total = sum(position.realized_pnl for position in positions)
            if realized_total < 0 and abs(realized_total) >= self._max_daily_loss:
                raise ValidationError(
                    f"Daily loss limit exceeded for account '{account_id}': "
                    f"realized loss {abs(realized_total)} >= limit "
                    f"{self._max_daily_loss}",
                    details={
                        "reason": PRETRADE_REASON_DAILY_LOSS_LIMIT_EXCEEDED,
                        "account_id": account_id,
                        "realized_pnl": realized_total,
                        "max_daily_loss": self._max_daily_loss,
                    },
                )

        # 16. position kill switch (Activation 8.4, BUY only)
        #
        # Caps the resulting position's notional value
        # (quantity * requested_price) after this BUY is applied.
        # SELL is never blocked by this gate -- reducing a position
        # can only bring its notional value down, never up, so there
        # is nothing for a position-size ceiling to guard against on
        # that side (mirrors gate 8's/gate 15's own BUY-only scoping
        # for the identical reason: a size/loss ceiling exists to stop
        # a position from growing, not to stop it from shrinking).
        # ``existing_quantity`` reads the same open position gate 9
        # already reads for SELL, via the same
        # ``position_repository.get_open_position`` call -- 0.0 when
        # no open position exists yet, never fabricated.
        if action == _BUY and self._max_position_value is not None:
            existing_position = self._position_repository.get_open_position(account_id, symbol)
            existing_quantity = existing_position.quantity if existing_position is not None else 0.0
            resulting_value = (existing_quantity + quantity) * requested_price
            if resulting_value > self._max_position_value:
                raise ValidationError(
                    f"Max position value exceeded for account '{account_id}' "
                    f"symbol '{symbol}': resulting position value "
                    f"{resulting_value} exceeds limit {self._max_position_value}",
                    details={
                        "reason": PRETRADE_REASON_MAX_POSITION_VALUE_EXCEEDED,
                        "account_id": account_id,
                        "symbol": symbol,
                        "existing_quantity": existing_quantity,
                        "order_quantity": quantity,
                        "resulting_value": resulting_value,
                        "max_position_value": self._max_position_value,
                    },
                )

        # 17. US market session/calendar (Activation 9.4, market == "us" only)
        #
        # ``market`` here is the same value gate 6 above already
        # computed (``os.getenv("AIOS_MARKET", "idx").strip().lower()
        # or "idx"``) -- read once, reused, not re-fetched, so this
        # gate cannot disagree with gate 6 about which market is
        # active within the same call. ``executed_at`` is the exact
        # ISO-8601 string the caller passed to ``submit_order()``
        # (LOCKED -- this engine generates no timestamp of its own;
        # see the module docstring's "``executed_at`` (LOCKED,
        # unchanged)" paragraph), parsed once here and handed to
        # ``Business.us_market_policy.USMarketCalendar().session()``,
        # the same calendar/session classifier
        # ``Tests/test_us_market_policy.py`` already exercises
        # directly. IDX and crypto are completely untouched -- this
        # gate is skipped entirely for both, exactly like gate 6's
        # existing ``market == "us"`` branch above.
        #
        # Fails safe on an unparsable ``executed_at``: a caller that
        # cannot even produce a valid ISO-8601 timestamp is never
        # treated as "regular session" by default (per the roadmap's
        # explicit "do not silently treat an unknown US session as
        # regular session" requirement) -- it is rejected under the
        # same reason code as any other disallowed session.
        if market == "us":
            try:
                us_moment = datetime.fromisoformat(executed_at)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Invalid executed_at for US market session check: {executed_at!r}",
                    details={
                        "reason": PRETRADE_REASON_US_MARKET_SESSION_CLOSED,
                        "market": market,
                        "executed_at": executed_at,
                    },
                ) from exc
            us_session = USMarketCalendar().session(us_moment)
            if us_session not in US_ORDER_ALLOWED_SESSIONS:
                raise ValidationError(
                    f"US market session '{us_session}' does not permit order "
                    f"submission at {executed_at} (allowed sessions: "
                    f"{sorted(US_ORDER_ALLOWED_SESSIONS)})",
                    details={
                        "reason": PRETRADE_REASON_US_MARKET_SESSION_CLOSED,
                        "market": market,
                        "session": us_session,
                        "executed_at": executed_at,
                    },
                )

        # 18. Crypto 24/7 market policy (Activation 10.5, market ==
        # "crypto" only)
        #
        # Explicit counterpart to gate 17 above: before this gate
        # existed, ``market == "crypto"`` orders were never subject to
        # ANY time-based gate at all -- not because a policy said so,
        # but because gate 17 is scoped to ``market == "us"`` only and
        # no crypto-specific gate had ever been added (an accidental
        # absence, not a stated policy -- see the Activation 10.5
        # brief's "ROADMAP REQUIREMENT" section). This gate makes that
        # 24/7 behavior explicit and deliberate: it consults
        # ``Business.crypto_market_policy.CryptoMarketPolicy`` (via
        # ``load_crypto_market_policy()``, loaded fresh on every call
        # -- never cached -- mirroring every other crypto policy
        # loader in this module) instead of continuing to rely on an
        # accidental absence of a gate.
        #
        # ``executed_at`` is parsed independently here (never shared
        # with gate 17's parsed ``us_moment`` above -- the two markets
        # are mutually exclusive within a single call via ``market ==
        # ...``, so at most one of gate 17/gate 18's parse attempts
        # ever actually runs for a given order). Fails safe on an
        # unparsable ``executed_at``, mirroring gate 17's identical
        # contract: a caller that cannot produce a valid ISO-8601
        # timestamp is never treated as "market open" by default, even
        # though every *valid* timestamp is always allowed under the
        # current 24/7 policy.
        #
        # IDX and US are completely untouched -- this gate is skipped
        # entirely for both, exactly like gate 17's own ``market ==
        # "us"`` branch above, mirrored in the opposite direction (IDX
        # -US isolation).
        if market == "crypto":
            try:
                crypto_moment = datetime.fromisoformat(executed_at)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Invalid executed_at for crypto market policy check: {executed_at!r}",
                    details={
                        "reason": PRETRADE_REASON_CRYPTO_MARKET_CLOSED,
                        "market": market,
                        "executed_at": executed_at,
                    },
                ) from exc
            crypto_market_policy = load_crypto_market_policy()
            if not crypto_market_policy.is_trading_allowed(crypto_moment):
                raise ValidationError(
                    f"Crypto market policy does not permit order submission "
                    f"at {executed_at}",
                    details={
                        "reason": PRETRADE_REASON_CRYPTO_MARKET_CLOSED,
                        "market": market,
                        "executed_at": executed_at,
                    },
                )

        # 19. Crypto exchange availability policy (Activation 10.6,
        # market == "crypto" only)
        #
        # Independent of gate 18 above: gate 18 answers "is the market
        # modeled as open" (always True, 24/7); this gate answers "is
        # the execution venue currently available" -- an injected,
        # configurable paper state, deliberately never combined with
        # gate 18's check (see ``Business.crypto_exchange_availability_
        # policy`` module docstring's "IMPORTANT DISTINCTION"). Consults
        # ``Business.crypto_exchange_availability_policy.
        # CryptoExchangeAvailabilityPolicy`` (via ``load_crypto_
        # exchange_availability_policy()``, loaded fresh on every call
        # -- never cached -- mirroring every other crypto policy loader
        # in this module). Default ``available=True``, so this gate
        # never rejects an order unless ``CRYPTO_EXCHANGE_AVAILABLE``
        # is explicitly set to a falsy value -- existing crypto paper
        # behavior (Activation 10.1-10.5) is completely unchanged by
        # this gate's mere presence. Uses its own dedicated reason code
        # (``PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE``), never
        # ``PRETRADE_REASON_CRYPTO_MARKET_CLOSED`` -- the two rejection
        # reasons must stay distinguishable, per the brief.
        #
        # IDX and US are completely untouched -- this gate is skipped
        # entirely for both, exactly like gate 18's own ``market ==
        # "crypto"``-only scoping (IDX-US isolation).
        if market == "crypto":
            crypto_exchange_availability_policy = load_crypto_exchange_availability_policy()
            if not crypto_exchange_availability_policy.is_available():
                raise ValidationError(
                    f"Crypto exchange availability policy does not permit "
                    f"order submission for '{symbol}' (exchange currently "
                    f"unavailable)",
                    details={
                        "reason": PRETRADE_REASON_CRYPTO_EXCHANGE_UNAVAILABLE,
                        "market": market,
                        "symbol": symbol,
                        "executed_at": executed_at,
                    },
                )

    @staticmethod
    def _is_positive_number(value: object) -> bool:
        """``True`` iff ``value`` is an ``int``/``float`` (never
        ``bool``, which is an ``int`` subclass in Python) strictly
        greater than zero. Mirrors
        ``Business.order_lifecycle_service.OrderLifecycleService.
        _is_positive_number`` exactly.
        """
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0