"""PositionManager -- Sprint 4 STEP 8.

Applies a already-recorded ``Trade`` (Sprint 4 STEP 6, produced by
``Business.execution_service.ExecutionService``) to its owning
``Position`` -- the Sprint 4 blueprint's BUY-merge / SELL-reduce /
CLOSED lifecycle.

Scope (LOCKED for this STEP):

* reads the current OPEN position (if any) for ``trade.account_id`` +
  ``trade.symbol`` via ``PositionRepository.get_open_position``;
* ``BUY``, no OPEN position -> creates a new ``Position``
  (``quantity = trade.quantity``, ``average_price = trade.fill_price``,
  ``status = "open"``);
* ``BUY``, OPEN position exists -> merges into it: quantity adds,
  ``average_price`` becomes the quantity-weighted average of the old
  position and this trade, ``status`` stays ``"open"``;
* ``SELL``, OPEN position exists -> quantity decreases by
  ``trade.quantity``, ``average_price`` is left untouched, and
  (Activation 3.6 STEP 3) ``realized_pnl`` increases by
  ``(trade.fill_price - average_price) * trade.quantity`` using the
  OLD ``average_price``; if the resulting quantity reaches zero,
  ``status`` becomes ``"closed"``, otherwise it stays ``"open"``;
* ``SELL``, no OPEN position -> ``ValidationError`` (nothing to sell);
* ``SELL`` for more than the OPEN position currently holds ->
  ``ValidationError`` (mirrors
  ``Business.account_balance_service.AccountBalanceService``'s
  insufficient-cash guard on a BUY -- this is a bounds check against
  going negative, not a P/L computation);
* persists the result via ``PositionRepository.create``/``update``.

``status`` values (LOCKED domain, ``Database.position_constants.
POSITION_STATUSES``): ``"open"``/``"closed"``, lowercase -- this
module always writes those exact strings, never ``"OPEN"``/
``"CLOSED"``, to match the already-LOCKED schema/CHECK constraint.

"BUY on a CLOSED position creates a new Position, never merges into
the closed one" falls out of ``get_open_position`` itself: it only
ever returns a ``status="open"`` row, so a CLOSED position is simply
invisible to this service and a following BUY takes the
no-open-position branch above, exactly like the very first BUY for
that symbol. No extra logic is needed to enforce this.

``realized_pnl`` (Activation 3.7 STEP 2 -- supersedes Activation 3.6
STEP 3 for the SELL path only, by extending the formula to include
transaction costs; BUY/new-position behaviour is unchanged):

* on a brand new ``Position`` (first BUY, or a fresh BUY after the
  prior position closed), ``realized_pnl`` is still passed as the
  literal ``0.0`` -- unchanged from Sprint 4 STEP 8;
* on a BUY merge into an existing OPEN position, ``realized_pnl`` is
  still read from the existing position and passed straight back
  through unchanged -- unchanged from Sprint 4 STEP 8 (a BUY realizes
  nothing; it only changes cost basis, and this Activation does not
  touch the weighted-average formula);
* on a SELL (partial or full), ``realized_pnl`` is now computed as
  ``position.realized_pnl + (trade.fill_price - position.
  average_price) * trade.quantity - trade.fee - trade.tax`` -- the
  OLD ``average_price`` (captured before this SELL's quantity/status
  update), never the average_price after the update, and never a
  price recomputed from ``Order``. ``trade.fee``/``trade.tax`` are
  this SELL ``Trade``'s own real values (Activation 3.3), read once
  and subtracted once. See ``_reduce_sell`` for the exact
  computation.

Pre-3.7 LOCKED DECISION (superseded above for SELL's fee/tax
treatment, kept here for BUY/new-position, which this Activation
deliberately does not touch): this service never computes realized
P/L on a BUY. On a brand new ``Position`` (first BUY, or a fresh BUY
after the prior position closed), ``realized_pnl`` is passed as the
literal ``0.0`` -- a technical placeholder only, written directly at
the call site with no constant or helper. On a BUY merge, the
existing position's ``realized_pnl`` is read and passed straight back
through unchanged, exactly like AccountBalanceService passes
``equity``/``buying_power`` through unchanged -- never recomputed,
never zeroed out. A BUY's own ``trade.fee``/``trade.tax`` are not
read anywhere in this module; they remain baked into cash movement
only (``AccountBalanceService``), never into ``average_price`` or
``realized_pnl`` -- this Activation only ever reads ``fee``/``tax``
off the ``Trade`` passed into ``_reduce_sell`` (a SELL).

Strictly DILARANG (forbidden), still true after Activation 3.7
STEP 2: Account, Equity, BuyingPower, Portfolio, unrealized P/L, stop
loss, take profit, scheduler, runtime pipeline, trading decision
agent, PaperTradingEngine, reading ``Order``. None of those are
implemented here, and this service holds no reference to any
repository/service that could do them (no ``AccountRepository``, no
``TradeRepository``, no ``OrderRepository`` -- the ``Trade`` is
supplied by the caller, already created by STEP 6, never created or
fetched by this service). Realized P/L on SELL (Activation 3.6 STEP 3)
and its fee/tax adjustment (Activation 3.7 STEP 2) are the two items
removed from this forbidden list so far -- everything else on it
remains untouched and out of scope. Unrealized P/L in particular is
explicitly NOT implemented by this Activation and is reserved for a
future STEP.

Net-performance-after-fee (additive, this Activation --
``Position.buy_fee_accumulated``): tracked alongside, and computed
independently from, ``average_price``/``realized_pnl``/``Account.cash``
/SELL fee-tax handling above, none of which this Activation changes.
A BUY (new position or merge) adds ``trade.fee`` to the accumulator.
A SELL keeps the fraction of the OLD accumulator proportional to the
quantity remaining held (``buy_fee_accumulated * (new_quantity /
old_quantity)``) -- so the complementary, sold-proportional fraction
is realized off the position, and a full SELL always leaves exactly
``0.0``. See ``_merge_buy``/``_reduce_sell`` for the exact
computation.

Repository dependency (LOCKED): ``PositionRepository`` only.

``stop_loss``/``take_profit`` (Activation 3.8 STEP 2 -- the one item
removed from the "Strictly DILARANG" list above so far, for
persistence only; everything else on that list, including any
trigger/execution/monitoring behavior for these two levels, remains
untouched and out of scope):

* ``apply_trade`` itself is unchanged for BOTH branches --
  ``stop_loss``/``take_profit`` are never set, computed, or inferred
  from a ``Trade``. A brand-new ``Position`` (first BUY, or a fresh
  BUY reopening after a CLOSE) is still created with no stop-loss/
  take-profit configured (``None``/SQL ``NULL``), exactly like
  ``realized_pnl``'s ``0.0`` placeholder is a technical default, not a
  business decision about what the caller "should" want.
* ``_merge_buy``/``_reduce_sell`` (BUY-merge, SELL-reduce) now read
  the existing position's ``stop_loss``/``take_profit`` and pass them
  straight back through to ``PositionRepository.update`` UNCHANGED --
  this is the LOCKED, documented, minimal choice for "SL/TP behavior
  on merge is undefined by the roadmap": neither recomputed, nor
  cleared, nor validated against the new ``average_price``. A BUY
  merge that moves ``average_price`` can, as a result, leave a
  previously-valid ``stop_loss``/``take_profit`` on the "wrong" side
  of the new entry price -- this is a known, accepted consequence of
  choosing pass-through over inventing an unrequested recompute
  formula, and is left for a future STEP to address if the roadmap
  ever asks for it.
* ``set_stop_loss_take_profit`` (Sprint 4 STEP 2 originally, made
  direction-aware by Activation 11.13): the only way
  ``stop_loss``/``take_profit`` are ever actually set to a caller-
  supplied value. Reads ``direction`` off the already-loaded
  ``Position`` (never accepts it as an argument, so it can never be
  called with a direction that contradicts persisted state) and
  validates against it when a value is given: LONG -- ``stop_loss``
  below the position's current ``average_price``, ``take_profit``
  above it (unchanged from before this STEP, so every existing
  IDX/US/Crypto position, which always has ``direction == "LONG"``,
  behaves byte-for-byte as before); SHORT -- the mirror image,
  ``stop_loss`` above ``average_price``, ``take_profit`` below it.
  Either direction, ``stop_loss``/``take_profit`` exactly equal to
  ``average_price`` is invalid (no zero-distance risk controls).
  Writes only ``stop_loss``/``take_profit``, and leaves
  ``quantity``/``average_price``/``realized_pnl``/``status``/
  ``direction`` byte-for-byte unchanged (all read from the current
  row and passed straight back through to
  ``PositionRepository.update``, never recomputed -- ``direction`` is
  now passed through explicitly here too, closing a latent gap where
  omitting it would have silently reset a SHORT position's
  ``direction`` to ``PositionRepository.update``'s ``"LONG"``
  default). No trigger, no automatic SELL, no monitoring, no pip/
  maximum-loss math -- this method only ever writes two nullable
  columns, purely by comparing them against ``average_price`` given
  ``direction``.

``direction`` / Forex SHORT semantics (Activation 11.12, implements
Activation 11.10 Decision C -- the only piece of that LOCKED decision
record this STEP is scoped to implement):

* ``Position.direction`` (Activation 11.11, persistence groundwork
  only -- this STEP is the first to ever write ``"SHORT"``) is set
  once, when a position opens from flat, and never changes for that
  position's lifetime. A reversal is always a NEW position row, never
  a mutation of an existing row's ``direction`` -- mirrors ``status``:
  a CLOSED position is never reopened, per the pre-existing
  ``get_open_position`` behavior documented above.
* ``BUY`` with no OPEN position (every account, unchanged): opens
  ``direction="LONG"``.
* ``SELL`` with no OPEN position, account's ``Account.asset_class ==
  "forex"`` (``Database.account_constants.ACCOUNT_ASSET_CLASSES``)
  ONLY: opens ``direction="SHORT"`` instead of raising. Every other
  asset class keeps the pre-11.12 behavior byte-for-byte: SELL with
  no OPEN position raises ``ValidationError``. Determined via a new,
  OPTIONAL ``account_repository`` constructor dependency (defaults to
  ``None``) -- when absent, this service can never observe an account
  as Forex and behaves exactly as it did before this STEP for every
  caller that does not pass one in.
* Same-direction trade (``BUY`` on an OPEN ``LONG``, or ``SELL`` on an
  OPEN ``SHORT``): ``_merge_same_direction`` (generalizes the former
  ``_merge_buy`` to run for either case) -- quantity increases,
  ``average_price`` becomes the quantity-weighted average of the old
  position and this trade (same formula as before), ``direction`` is
  read off the existing position and passed straight back through
  (never hard-coded), ``status`` stays ``"open"``.
* Opposite-direction trade (``SELL`` on an OPEN ``LONG``, or ``BUY``
  on an OPEN ``SHORT``): ``_reduce_opposite_direction`` (generalizes
  the former ``_reduce_sell`` to run for either case) -- quantity
  decreases by ``trade.quantity``, ``average_price`` is left
  untouched, ``direction`` is read off the existing position and
  passed straight back through (never hard-coded), ``status`` becomes
  ``"closed"`` once quantity reaches zero. Realized P/L is
  direction-signed: LONG uses ``(trade.fill_price -
  position.average_price) * trade.quantity`` (unchanged formula);
  SHORT uses ``(position.average_price - trade.fill_price) *
  trade.quantity`` (sign flipped -- a SHORT profits when price
  falls) -- both then have ``trade.fee``/``trade.tax`` subtracted
  exactly as before. If ``trade.quantity`` exceeds the OPEN
  position's ``quantity``, this raises the same bounds-check
  ``ValidationError`` as before (now for either direction) -- this is
  also how same-trade reversal (close-and-flip in one order) is
  rejected: Activation 11.10 Decision C explicitly puts that out of
  scope, and this bounds check is the only guard needed to enforce it,
  with zero extra logic.
* ``buy_fee_accumulated`` for the reworked paths: opening a SHORT
  (the SELL-with-no-position branch) seeds it with ``trade.fee``, the
  same treatment the pre-existing BUY-opens-LONG branch already gives
  its own opening trade. ``_merge_same_direction`` adds ``trade.fee``
  to the existing accumulator (same formula as the former
  ``_merge_buy``). ``_reduce_opposite_direction`` keeps the
  quantity-remaining-proportional fraction of the old accumulator
  (same formula as the former ``_reduce_sell``). No Forex-specific
  fee/tax policy is introduced anywhere in this STEP -- see Design
  Requirement 7 / the Activation 11.12 brief; every fee/tax value
  used here is still exactly whatever the already-created ``Trade``
  carries.

Strictly out of scope for Activation 11.12 (per the roadmap brief):
Forex account creation, Forex CLI, Forex market routing, margin,
stop-loss/take-profit direction-aware validation (Decision D, still
deferred), max-loss, spread, reconciliation, leverage, liquidation,
broker API. None of those are touched by this STEP.
"""

from __future__ import annotations

from typing import Optional

from Core.exceptions import ValidationError
from Database.account_constants import ACCOUNT_ASSET_CLASSES
from Database.models import Position, Trade
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.position_repository import PositionRepository

#: Trade actions this service knows how to apply. Mirrors
#: ``Business.account_balance_service._VALID_ACTIONS`` -- kept as a
#: separate local tuple rather than importing that private name, same
#: as every other Sprint 4 STEP keeps its own domain checks local.
_VALID_ACTIONS = ("BUY", "SELL")

#: LOCKED domain values (``Database.position_constants.
#: POSITION_STATUSES``), lowercase. Named constants here purely to
#: avoid repeating the string literals below -- not a new domain, not
#: a redefinition of the single source of truth.
_STATUS_OPEN = "open"
_STATUS_CLOSED = "closed"

#: LOCKED domain values (``Database.position_constants.
#: POSITION_DIRECTIONS``). Named constants here purely to avoid
#: repeating the string literals below -- not a new domain, not a
#: redefinition of the single source of truth.
_DIRECTION_LONG = "LONG"
_DIRECTION_SHORT = "SHORT"

#: The one ``Database.account_constants.ACCOUNT_ASSET_CLASSES`` value
#: that unlocks Activation 11.10 Decision C's SELL-with-no-OPEN-
#: position -> opens SHORT behavior. Every other asset class in
#: ``ACCOUNT_ASSET_CLASSES`` keeps the pre-11.12 SELL-with-no-OPEN-
#: position -> ``ValidationError`` behavior unchanged. Sourced from
#: the existing single-source-of-truth tuple (never a bare guessed
#: string) -- ``assert`` below only guards against that tuple ever
#: dropping the value this module depends on.
_FOREX_ASSET_CLASS = "forex"
assert _FOREX_ASSET_CLASS in ACCOUNT_ASSET_CLASSES


def is_stop_loss_side_valid(direction: str, reference_price: float, stop_loss: float) -> bool:
    """Return whether ``stop_loss`` is on the protective side of
    ``reference_price`` for ``direction`` (Activation 11.13's
    direction-aware rule, extracted as a standalone, importable
    predicate by Activation 11.14 so ``PaperTradingEngine`` can apply
    the identical rule at the pre-trade boundary -- before any
    ``Position`` exists to read ``average_price`` from -- without
    duplicating the comparison logic).

    ``direction == "SHORT"``: ``stop_loss`` must be strictly ABOVE
    ``reference_price``. Every other ``direction`` (i.e. ``"LONG"``,
    the default): ``stop_loss`` must be strictly BELOW
    ``reference_price``. Either direction, ``stop_loss ==
    reference_price`` is always invalid (no zero-distance stop) --
    this falls out of using strict ``<``/``>`` rather than ``<=``/
    ``>=`` below.

    ``reference_price`` is deliberately named generically, not
    ``average_price``: ``set_stop_loss_take_profit`` below calls this
    with an existing ``Position.average_price``, while
    ``PaperTradingEngine``'s pre-trade gate calls it with an
    order's not-yet-filled ``requested_price`` -- this function has no
    opinion on which, it only compares two numbers given a direction.
    """
    if direction == _DIRECTION_SHORT:
        return stop_loss > reference_price
    return stop_loss < reference_price


def is_take_profit_side_valid(direction: str, reference_price: float, take_profit: float) -> bool:
    """The ``take_profit`` mirror of ``is_stop_loss_side_valid`` --
    same rationale, same strict-inequality/no-zero-distance contract,
    opposite side: ``direction == "SHORT"`` requires ``take_profit``
    strictly BELOW ``reference_price``; every other ``direction``
    requires it strictly ABOVE.
    """
    if direction == _DIRECTION_SHORT:
        return take_profit < reference_price
    return take_profit > reference_price


class PositionManager:
    """Applies a single ``Trade``'s effect to its OPEN ``Position``.

    Depends on ``PositionRepository`` always, and OPTIONALLY on
    ``AccountRepository`` (Activation 11.12, additive) -- no other
    repository, no Service, no Skill, no Tool. Never opens a
    transaction itself.
    """

    def __init__(
        self,
        position_repository: PositionRepository,
        account_repository: Optional[AccountRepository] = None,
    ) -> None:
        """Initialize the service.

        Args:
            position_repository: Used to look up the current OPEN
                position and to create/update it. Stored by reference
                only.
            account_repository: OPTIONAL (Activation 11.12, additive).
                Used only to look up ``Account.asset_class`` for the
                account a SELL-with-no-OPEN-position trade targets, to
                decide whether that SELL may open a SHORT position
                (Forex only -- see Activation 11.10 Decision C).
                Defaults to ``None``, which preserves every pre-11.12
                caller's behavior byte-for-byte: with no
                ``account_repository``, this service can never observe
                an account as Forex, so a SELL with no OPEN position
                always raises ``ValidationError``, exactly as before
                this STEP. Stored by reference only.
        """
        self._position_repository = position_repository
        self._account_repository = account_repository

    def apply_trade(self, trade: Trade) -> Position:
        """Apply ``trade`` to the OPEN position for its account+symbol.

        Args:
            trade: An already-created, immutable ``Trade`` (Sprint 4
                STEP 6). ``trade.quantity``/``trade.fill_price``/
                ``trade.action`` decide the resulting position; this
                method never creates, fetches, or mutates a ``Trade``
                itself.

        Returns:
            The ``Position`` as it now stands after the update (newly
            created on a first/reopening BUY, or on a Forex SELL that
            opens a SHORT; the existing row after a same-direction
            merge or an opposite-direction reduce/close otherwise).

        Raises:
            ValidationError: If ``trade.action`` is not
                ``"BUY"``/``"SELL"``; if a ``SELL`` has no OPEN
                position to sell from and the account is not Forex
                (``Account.asset_class == "forex"``); or if an
                opposite-direction trade's ``trade.quantity`` exceeds
                the OPEN position's current ``quantity`` (would go
                negative -- this is also how same-trade reversal /
                close-and-flip is rejected, per Activation 11.10
                Decision C). In every case, no repository write
                happens.
            RepositoryError: If any underlying repository call fails.
        """
        if trade.action not in _VALID_ACTIONS:
            raise ValidationError(
                f"Cannot apply trade {trade.trade_id}: unknown action '{trade.action}'",
                details={"trade_id": trade.trade_id, "action": trade.action},
            )

        open_position = self._position_repository.get_open_position(trade.account_id, trade.symbol)

        if trade.action == "BUY":
            if open_position is None:
                return self._position_repository.create(
                    account_id=trade.account_id,
                    symbol=trade.symbol,
                    quantity=trade.quantity,
                    average_price=trade.fill_price,
                    realized_pnl=0.0,
                    status=_STATUS_OPEN,
                    buy_fee_accumulated=trade.fee,
                    direction=_DIRECTION_LONG,
                )
            if open_position.direction == _DIRECTION_LONG:
                return self._merge_same_direction(open_position, trade)
            return self._reduce_opposite_direction(open_position, trade)

        # SELL
        if open_position is None:
            if self._is_forex_account(trade.account_id):
                return self._position_repository.create(
                    account_id=trade.account_id,
                    symbol=trade.symbol,
                    quantity=trade.quantity,
                    average_price=trade.fill_price,
                    realized_pnl=0.0,
                    status=_STATUS_OPEN,
                    buy_fee_accumulated=trade.fee,
                    direction=_DIRECTION_SHORT,
                )
            raise ValidationError(
                f"Cannot sell {trade.symbol} for account {trade.account_id}: no OPEN position",
                details={"account_id": trade.account_id, "symbol": trade.symbol},
            )
        if open_position.direction == _DIRECTION_SHORT:
            return self._merge_same_direction(open_position, trade)
        return self._reduce_opposite_direction(open_position, trade)

    def _is_forex_account(self, account_id: str) -> bool:
        """Return whether ``account_id`` references a Forex account.

        ``True`` only when an ``account_repository`` was supplied at
        construction AND that account exists AND its ``asset_class``
        is exactly ``"forex"`` (``Database.account_constants.
        ACCOUNT_ASSET_CLASSES``). Read-only lookup -- never creates,
        updates, or caches anything. With no ``account_repository``
        (the default), always returns ``False``, which is what makes
        every pre-11.12 caller's behavior unchanged.
        """
        if self._account_repository is None:
            return False
        account = self._account_repository.get_by_id(account_id)
        return account is not None and account.asset_class == _FOREX_ASSET_CLASS

    def _merge_same_direction(self, position: Position, trade: Trade) -> Position:
        """Merge a same-direction trade into an existing OPEN ``position``.

        Generalizes the pre-11.12 ``_merge_buy`` (BUY into a LONG) to
        also cover a SELL into a SHORT (Activation 11.10 Decision C)
        -- the arithmetic is identical either way, only the direction
        this method is called for differs.

        ``average_price`` becomes the quantity-weighted average of the
        old position and this trade:
        ``(old_qty * old_avg + new_qty * trade_price) / (old_qty + new_qty)``.
        ``realized_pnl`` is passed through unchanged (never
        recomputed). ``status`` stays ``"open"``. ``direction`` is
        read off the existing ``position`` and passed straight back
        through unchanged -- never hard-coded to ``"LONG"`` -- so a
        SHORT position merging a further SELL stays SHORT.
        """
        new_quantity = position.quantity + trade.quantity
        new_average_price = (
            position.quantity * position.average_price + trade.quantity * trade.fill_price
        ) / new_quantity
        new_buy_fee_accumulated = position.buy_fee_accumulated + trade.fee

        self._position_repository.update(
            position_id=position.position_id,
            quantity=new_quantity,
            average_price=new_average_price,
            realized_pnl=position.realized_pnl,
            status=_STATUS_OPEN,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            buy_fee_accumulated=new_buy_fee_accumulated,
            direction=position.direction,
        )
        return self._position_repository.get_by_id(position.position_id)

    def _reduce_opposite_direction(self, position: Position, trade: Trade) -> Position:
        """Reduce an existing OPEN ``position`` by an opposite-direction trade.

        Generalizes the pre-11.12 ``_reduce_sell`` (SELL against a
        LONG) to also cover a BUY against a SHORT (Activation 11.10
        Decision C) -- the shape is identical either way; only the
        realized-P/L sign and which trade action is "opposite" differ
        per direction.

        ``average_price`` is left untouched (read here *before* this
        trade's quantity change, and never recomputed here -- only a
        same-direction merge changes it). ``direction`` is read off
        the existing ``position`` and passed straight back through
        unchanged -- never hard-coded -- so a SHORT position being
        reduced/closed stays SHORT.

        ``realized_pnl`` (Activation 3.6 STEP 3 / Activation 3.7
        STEP 2 for LONG, generalized to SHORT by Activation 11.10
        Decision C / this STEP): becomes ``position.realized_pnl +
        pnl_delta - trade.fee - trade.tax``, using the OLD
        ``position.average_price`` (captured in this method's
        ``position`` argument before any write) and
        ``trade.fill_price``/``trade.quantity``/``trade.fee``/
        ``trade.tax`` exactly as recorded on the already-created
        ``Trade`` -- never a price recomputed from ``Order``, never
        the position's average_price after this update.
        ``pnl_delta`` is direction-signed:

        * LONG: ``(trade.fill_price - position.average_price) *
          trade.quantity`` (unchanged formula -- a LONG profits when
          price rises).
        * SHORT: ``(position.average_price - trade.fill_price) *
          trade.quantity`` (sign flipped -- a SHORT profits when
          price falls).

        ``trade.fee``/``trade.tax`` are read exactly once here (this
        ``Trade`` is applied exactly once by ``apply_trade``), so
        there is no double-counting. ``status`` becomes ``"closed"``
        once ``quantity`` reaches zero, otherwise stays ``"open"``.

        If ``trade.quantity`` exceeds the OPEN position's
        ``quantity``, raises ``ValidationError`` -- this bounds check
        is also what rejects a same-trade reversal (close-and-flip in
        one order), per Activation 11.10 Decision C: a caller must
        close to flat first, then open the opposite direction as a
        second trade.
        """
        if trade.quantity > position.quantity:
            raise ValidationError(
                f"Cannot {trade.action.lower()} {trade.quantity} of {trade.symbol} for account "
                f"{trade.account_id}: only {position.quantity} held ({position.direction})",
                details={
                    "account_id": trade.account_id,
                    "symbol": trade.symbol,
                    "held": position.quantity,
                    "trade_quantity": trade.quantity,
                    "direction": position.direction,
                },
            )

        new_quantity = position.quantity - trade.quantity
        new_status = _STATUS_CLOSED if new_quantity == 0.0 else _STATUS_OPEN

        if position.direction == _DIRECTION_LONG:
            pnl_delta = (trade.fill_price - position.average_price) * trade.quantity
        else:
            pnl_delta = (position.average_price - trade.fill_price) * trade.quantity

        new_realized_pnl = position.realized_pnl + pnl_delta - trade.fee - trade.tax
        # Net-performance-after-fee (additive, does not touch
        # realized_pnl/average_price/cash): the fraction of the OLD
        # buy_fee_accumulated proportional to the quantity remaining
        # HELD stays with the position; the complementary,
        # traded-away fraction is realized. Computed directly from
        # the remaining-quantity ratio (not by subtracting a
        # separately-rounded "realized" amount) so a full close
        # (new_quantity == 0.0) always leaves exactly 0.0.
        new_buy_fee_accumulated = position.buy_fee_accumulated * (new_quantity / position.quantity)

        self._position_repository.update(
            position_id=position.position_id,
            quantity=new_quantity,
            average_price=position.average_price,
            realized_pnl=new_realized_pnl,
            status=new_status,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            buy_fee_accumulated=new_buy_fee_accumulated,
            direction=position.direction,
        )
        return self._position_repository.get_by_id(position.position_id)

    def set_stop_loss_take_profit(
        self,
        position_id: int,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> Position:
        """Set (or clear) ``stop_loss``/``take_profit`` on an existing
        ``Position``, direction-aware (Activation 11.13).

        This is the only method on this service that ever writes a
        caller-supplied ``stop_loss``/``take_profit`` value (see the
        module docstring's Activation 3.8 STEP 2 section).
        ``quantity``/``average_price``/``realized_pnl``/``status`` are
        read from the current row and passed straight back through
        unchanged -- never recomputed by this method.

        Direction-aware validation (Activation 11.13, generalizes the
        former LONG-only rule using the already-persisted
        ``position.direction`` -- no ``direction`` argument is
        accepted here, and none is needed: the Position itself is the
        source of truth, so this method can never be called with a
        direction that contradicts the persisted position state):

        * ``LONG`` (the default -- so IDX/US/Crypto positions, which
          never set ``direction`` away from ``"LONG"``, keep exactly
          the pre-11.13 rule): ``stop_loss`` must be strictly below
          ``average_price``; ``take_profit`` must be strictly above
          it.
        * ``SHORT``: the mirror image -- ``stop_loss`` must be
          strictly above ``average_price``; ``take_profit`` must be
          strictly below it.
        * Either direction: ``stop_loss == average_price`` or
          ``take_profit == average_price`` is always invalid (no
          zero-distance risk controls).

        This method has no knowledge of pairs, pips, or maximum loss
        -- it only ever compares ``stop_loss``/``take_profit`` against
        ``average_price`` given ``direction``.

        Args:
            position_id: The position to update. Must already exist.
            stop_loss: New stop-loss level, or ``None`` to clear it
                (SQL ``NULL``). When given (not ``None``), validated
                against the position's ``direction`` as described
                above.
            take_profit: New take-profit level, or ``None`` to clear
                it. When given (not ``None``), validated against the
                position's ``direction`` as described above.

        Returns:
            The ``Position`` as it now stands after the update.

        Raises:
            ValidationError: If ``position_id`` does not reference an
                existing position, or if ``stop_loss``/``take_profit``
                fails the direction-aware check above. In every case,
                no repository write happens.
            RepositoryError: If any underlying repository call fails.
        """
        position = self._position_repository.get_by_id(position_id)
        if position is None:
            raise ValidationError(
                f"Cannot set stop_loss/take_profit: no position {position_id}",
                details={"position_id": position_id},
            )

        direction = position.direction

        if stop_loss is not None and not is_stop_loss_side_valid(direction, position.average_price, stop_loss):
            raise ValidationError(
                f"stop_loss {stop_loss} is not valid against average_price "
                f"{position.average_price} for position {position_id} ({direction})",
                details={
                    "position_id": position_id,
                    "stop_loss": stop_loss,
                    "average_price": position.average_price,
                    "direction": direction,
                },
            )
        if take_profit is not None and not is_take_profit_side_valid(direction, position.average_price, take_profit):
            raise ValidationError(
                f"take_profit {take_profit} is not valid against average_price "
                f"{position.average_price} for position {position_id} ({direction})",
                details={
                    "position_id": position_id,
                    "take_profit": take_profit,
                    "average_price": position.average_price,
                    "direction": direction,
                },
            )

        self._position_repository.update(
            position_id=position.position_id,
            quantity=position.quantity,
            average_price=position.average_price,
            realized_pnl=position.realized_pnl,
            status=position.status,
            stop_loss=stop_loss,
            take_profit=take_profit,
            buy_fee_accumulated=position.buy_fee_accumulated,
            direction=direction,
        )
        return self._position_repository.get_by_id(position.position_id)