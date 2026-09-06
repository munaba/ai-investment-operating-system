"""ReconciliationEngine -- Activation 3.9 STEP 2.

Read-only consistency checker over the four already-LOCKED production
entities the Activation 3.9 STEP 1 audit confirmed exist and work:
``Order``, ``Trade``, ``Account`` (cash), ``Position``. Answers exactly
one question per account: ``CONSISTENT`` or ``INCONSISTENT``, with the
specific invariant(s) that failed listed alongside.

Scope (LOCKED for this Activation, per the STEP 2 brief):

* reads through ``OrderRepository``/``TradeRepository``/
  ``AccountRepository``/``PositionRepository`` ONLY, and only via
  methods that already existed before this Activation
  (``get_by_id``/``list_by_account``/``list_all``/
  ``get_open_position``);
* NEVER calls ``create``/``update``/``update_balances``/
  ``update_status``/``record_fill`` or any other write method on any
  repository -- see "READ-ONLY GUARANTEE" below;
* NEVER calls ``PaperTradingEngine.submit_order()`` or any other
  Service that could write;
* performs no repair, no auto-correction, no compensating write of
  any kind. A caller that wants to *fix* an inconsistency must do so
  through the existing, already-LOCKED production pipeline
  (``PaperTradingEngine``) -- this engine only ever reports.

READ-ONLY GUARANTEE: every method on this class is built exclusively
from ``self._<repo>.get_*``/``list_*`` calls. Grep for ``.create(``,
``.update(``, ``.update_balances(``, ``.update_status(``,
``.record_fill(`` against ``self._order_repository`` /
``self._trade_repository`` / ``self._account_repository`` /
``self._position_repository`` in this module returns zero matches --
that is a structural property of this file, not just documentation.

Invariants checked by ``reconcile_account()`` (formulas taken verbatim
from the Activation 3.9 STEP 1 audit, sections 3-4 -- NOT
re-derived, NOT changed):

1.  Order <-> Trade -- for every ``Order`` with ``status == "FILLED"``,
    exactly one ``Trade`` exists for that ``order_id``, and
    ``Order.filled_price``/``filled_quantity``/``filled_at`` equal
    that ``Trade``'s ``fill_price``/``quantity``/``executed_at``
    exactly. For every ``Order`` with a non-``FILLED`` status, no
    ``Trade`` is assumed or fabricated -- this engine only flags the
    case where a non-FILLED order unexpectedly *does* have a Trade
    (which the current state machine should never produce); it never
    invents a requirement that a non-FILLED order lack one for some
    other reason.

2.  Trade <-> Cash -- replays every ``Trade`` for the account, in
    ``trade_id`` order, against the BUY/SELL cash formula documented
    in ``Business.account_balance_service`` (``compute_buy_required_cash``
    for BUY, ``gross_value - fee - tax`` for SELL), starting from a
    caller-supplied ``starting_cash`` anchor, and compares the result
    to the account's current persisted ``cash``. Uses ``Trade.fee``/
    ``Trade.tax`` exactly as persisted -- never recomputed from
    ``ExecutionPolicy``. If ``starting_cash`` is not supplied, this
    invariant cannot be checked (see "PORTFOLIO / CASH-HISTORY
    LIMITATION" below) and is reported under ``not_verifiable``
    instead of silently skipped or force-passed.

3.  Trade <-> Position -- replays every ``Trade`` for the account, per
    symbol, in ``trade_id`` order, from an empty starting position
    (no anchor needed -- a symbol's position history always starts
    from "no position" the very first time it is ever traded),
    against the exact BUY-merge / SELL-reduce / realized_pnl /
    net-performance-after-fee formulas in
    ``Business.position_manager.PositionManager``, and compares the
    replayed final ``quantity``/``average_price``/``realized_pnl``/
    ``buy_fee_accumulated``/``status`` to the currently persisted
    ``Position`` row for that symbol (the OPEN one if present, else
    the most recently created CLOSED one).

4.  Portfolio state sanity -- ``Account.cash`` is not negative, no
    ``Position.quantity`` is negative, and ``status`` agrees with
    ``quantity`` (``quantity == 0`` implies ``status == "closed"``;
    ``quantity > 0`` implies ``status == "open"``). This is the
    on-demand, non-persisted portfolio check the STEP 2 brief asks
    for in place of a ``PortfolioSnapshot`` that does not exist (see
    limitation below) -- computed fresh from ``Account``/``Position``
    every call, never stored.

PORTFOLIO / CASH-HISTORY LIMITATION (explicit, per STEP 2 brief
section 5 -- reported, not worked around): this codebase persists no
portfolio snapshot and no cash-history/audit-trail table (the
Activation 3.9 STEP 1 audit confirmed both are GAPs). ``Account.cash``
is a single mutable current value -- once a trade updates it, the cash
value that existed immediately *before* that trade is gone forever
unless a caller captured it externally. Consequently:

* full trade-history cash reconciliation (invariant 2 above) is only
  checkable when the caller supplies the account's true starting cash
  (e.g. a value captured immediately after account creation, before
  any trade). This engine does NOT invent, estimate, or back-compute
  that anchor from ``account.cash`` minus the replayed deltas -- doing
  so would make the check vacuously pass by construction (comparing a
  derived number to itself) rather than genuinely verifying anything;
* true portfolio *valuation* (mark-to-market equity using a live
  market price) is out of scope for the same reason
  ``AccountBalanceService`` never computes ``equity`` itself (see that
  module's docstring, Activation 3.5 STEP 1): no price feed is wired
  to this engine, and none should be added here -- that is a
  different Activation's scope, not this one's.

Both limitations are reported verbatim in
``ReconciliationResult.not_verifiable`` on every call -- never
silently dropped, never forced to ``CONSISTENT``.

Repository dependency (LOCKED, additive-only): ``OrderRepository``,
``TradeRepository``, ``AccountRepository``, ``PositionRepository`` --
the same four already-production repositories audited in Activation
3.9 STEP 1. No new repository, no new Service, no Skill, no Tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from Business.forex_margin_policy import calculate_required_margin
from Business.forex_max_loss_policy import calculate_maximum_loss
from Business.forex_pip_policy import calculate_pip_value
from Business.position_manager import (
    _DIRECTION_LONG,
    _DIRECTION_SHORT,
    _FOREX_ASSET_CLASS,
    is_stop_loss_side_valid,
)
from Core.exceptions import ValidationError
from Database.models import Trade
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.trade_repository import TradeRepository

#: Trade actions this engine's replay logic understands. Mirrors
#: ``Business.account_balance_service._VALID_ACTIONS`` /
#: ``Business.position_manager._VALID_ACTIONS`` -- kept as a separate
#: local tuple rather than importing a private name from either
#: module, same convention every other Sprint 4 / Activation module in
#: this codebase already follows.
_BUY = "BUY"
_SELL = "SELL"

_STATUS_FILLED = "FILLED"
_STATUS_OPEN = "open"
_STATUS_CLOSED = "closed"

#: Floating point comparisons throughout this module use this
#: tolerance rather than ``==``, since every quantity/price/cash value
#: flowing through this engine is a Python ``float`` accumulated
#: through the same arithmetic ``AccountBalanceService``/
#: ``PositionManager`` already perform. Deliberately tiny -- this is
#: for float representation noise only, not a business rounding rule
#: (no rounding rule exists anywhere else in this codebase either).
_EPSILON = 1e-9

#: Text used verbatim for both cash-history limitations documented in
#: the module docstring, so ``not_verifiable`` entries are consistent
#: and grep-able across every call site/test.
NOT_VERIFIABLE_CASH_HISTORY = (
    "Trade<->Cash full-history reconciliation: NOT VERIFIABLE WITH CURRENT "
    "PERSISTED STATE -- no persisted starting-cash/cash-history table exists "
    "in this codebase to anchor a replay (Account.cash is a single mutable "
    "current value with no audit trail). Pass starting_cash explicitly "
    "(e.g. the account's cash immediately after creation, before any trade) "
    "to verify against a known anchor."
)
NOT_VERIFIABLE_PORTFOLIO_VALUATION = (
    "Portfolio equity/valuation (mark-to-market): NOT VERIFIABLE WITH "
    "CURRENT PERSISTED STATE -- no PortfolioSnapshot exists (Activation 3.9 "
    "STEP 1 audit sec. 5, confirmed GAP) and no market-price source is wired "
    "to this engine. Account.equity/buying_power are pass-through-only and "
    "are never recomputed anywhere in this codebase (see "
    "Business.account_balance_service module docstring)."
)


@dataclass
class ReconciliationResult:
    """Outcome of one ``ReconciliationEngine.reconcile_account()`` call.

    ``consistent`` / ``status`` answer the STEP 2 brief's required
    binary question directly. ``violations`` lists every invariant
    that failed (empty iff ``consistent`` is ``True``).
    ``not_verifiable`` lists invariants this engine could not check at
    all given currently persisted state (see module docstring's
    "PORTFOLIO / CASH-HISTORY LIMITATION") -- these never count as
    violations and never flip ``consistent`` to ``False`` by
    themselves.
    """

    consistent: bool
    violations: List[str] = field(default_factory=list)
    not_verifiable: List[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        """``"CONSISTENT"`` or ``"INCONSISTENT"`` -- the STEP 2 brief's
        exact required vocabulary."""
        return "CONSISTENT" if self.consistent else "INCONSISTENT"


class ReconciliationEngine:
    """Read-only Order/Trade/Cash/Position/Portfolio consistency checker.

    Depends on ``OrderRepository``/``TradeRepository``/
    ``AccountRepository``/``PositionRepository`` only -- no other
    Repository, no Service, no Skill, no Tool. Never opens a
    transaction, never writes. See module docstring's "READ-ONLY
    GUARANTEE".
    """

    def __init__(
        self,
        order_repository: OrderRepository,
        trade_repository: TradeRepository,
        account_repository: AccountRepository,
        position_repository: PositionRepository,
    ) -> None:
        """Initialize the engine.

        Args:
            order_repository: Read-only source for ``Order`` rows.
            trade_repository: Read-only source for ``Trade`` rows.
            account_repository: Read-only source for the ``Account``
                (cash) row.
            position_repository: Read-only source for ``Position``
                rows.
        """
        self._order_repository = order_repository
        self._trade_repository = trade_repository
        self._account_repository = account_repository
        self._position_repository = position_repository

    def reconcile_account(
        self, account_id: str, starting_cash: Optional[float] = None
    ) -> ReconciliationResult:
        """Check every invariant documented in the module docstring for
        a single account.

        Args:
            account_id: The account to reconcile.
            starting_cash: The account's true cash value immediately
                after creation, before any trade. Optional -- when
                omitted, the Trade<->Cash invariant is reported under
                ``not_verifiable`` instead of checked (see module
                docstring's "PORTFOLIO / CASH-HISTORY LIMITATION").
                Never inferred or back-computed by this method.

        Returns:
            A :class:`ReconciliationResult`. ``consistent`` is
            ``True`` iff ``violations`` is empty -- ``not_verifiable``
            entries never affect it.
        """
        violations: List[str] = []
        not_verifiable: List[str] = []

        account = self._account_repository.get_by_id(account_id)
        if account is None:
            return ReconciliationResult(
                consistent=False,
                violations=[f"account '{account_id}' does not exist"],
            )

        orders = self._order_repository.list_by_account(account_id)
        trades = self._trade_repository.list_by_account(account_id)
        positions = self._position_repository.list_by_account(account_id)
        is_forex = account.asset_class == _FOREX_ASSET_CLASS

        self._check_order_trade(orders, trades, violations)
        self._check_trade_cash(account_id, account.cash, trades, starting_cash, violations, not_verifiable)
        self._check_trade_position(trades, positions, violations, is_forex=is_forex)
        self._check_portfolio_state(account_id, account.cash, positions, violations, not_verifiable)
        if is_forex:
            self._check_forex_state(positions, violations)

        return ReconciliationResult(
            consistent=len(violations) == 0,
            violations=violations,
            not_verifiable=not_verifiable,
        )

    # -- invariant 1: Order <-> Trade --------------------------------

    @staticmethod
    def _check_order_trade(orders, trades, violations: List[str]) -> None:
        trades_by_order: Dict[int, List[Trade]] = {}
        for trade in trades:
            trades_by_order.setdefault(trade.order_id, []).append(trade)

        for order in orders:
            order_trades = trades_by_order.get(order.order_id, [])
            if order.status == _STATUS_FILLED:
                if len(order_trades) != 1:
                    violations.append(
                        f"order {order.order_id} status FILLED but has "
                        f"{len(order_trades)} trade(s) (expected exactly 1)"
                    )
                    continue
                trade = order_trades[0]
                if order.filled_price != trade.fill_price:
                    violations.append(
                        f"order {order.order_id} filled_price {order.filled_price!r} "
                        f"!= trade {trade.trade_id} fill_price {trade.fill_price!r}"
                    )
                if order.filled_quantity != trade.quantity:
                    violations.append(
                        f"order {order.order_id} filled_quantity {order.filled_quantity!r} "
                        f"!= trade {trade.trade_id} quantity {trade.quantity!r}"
                    )
                if order.filled_at != trade.executed_at:
                    violations.append(
                        f"order {order.order_id} filled_at {order.filled_at!r} "
                        f"!= trade {trade.trade_id} executed_at {trade.executed_at!r}"
                    )
            else:
                if order_trades:
                    violations.append(
                        f"order {order.order_id} status '{order.status}' (non-FILLED) "
                        f"unexpectedly has {len(order_trades)} trade(s)"
                    )

    # -- invariant 2: Trade <-> Cash ----------------------------------

    @staticmethod
    def _check_trade_cash(
        account_id: str,
        current_cash: float,
        trades: List[Trade],
        starting_cash: Optional[float],
        violations: List[str],
        not_verifiable: List[str],
    ) -> None:
        if starting_cash is None:
            not_verifiable.append(NOT_VERIFIABLE_CASH_HISTORY)
            return

        expected_cash = starting_cash
        for trade in sorted(trades, key=lambda t: t.trade_id):
            gross_value = trade.quantity * trade.fill_price
            if trade.action == _BUY:
                expected_cash -= gross_value + trade.fee + trade.tax
            elif trade.action == _SELL:
                expected_cash += gross_value - trade.fee - trade.tax
            else:
                violations.append(
                    f"trade {trade.trade_id} has unrecognized action '{trade.action}'"
                )

        if abs(expected_cash - current_cash) > _EPSILON:
            violations.append(
                f"account {account_id} cash {current_cash!r} != expected {expected_cash!r} "
                f"(replayed from starting_cash {starting_cash!r} over {len(trades)} trade(s))"
            )

    # -- invariant 3: Trade <-> Position --------------------------------

    @staticmethod
    def _check_trade_position(
        trades: List[Trade], positions, violations: List[str], is_forex: bool = False
    ) -> None:
        symbols = sorted({t.symbol for t in trades} | {p.symbol for p in positions})
        for symbol in symbols:
            symbol_trades = sorted(
                (t for t in trades if t.symbol == symbol), key=lambda t: t.trade_id
            )
            replayed = _replay_position(symbol_trades, violations, is_forex=is_forex)
            symbol_positions = [p for p in positions if p.symbol == symbol]

            if not symbol_positions:
                if replayed is not None:
                    violations.append(
                        f"symbol {symbol}: trade history implies a position but none is persisted"
                    )
                continue

            # ``position_id`` is a repository-generated, ascending
            # surrogate integer (see Database.models.Position) -- the
            # highest one for this symbol is either the current OPEN
            # position, or, if none is open, the most recently CLOSED
            # one. Mirrors PositionManager's own "get_open_position
            # only ever sees the latest cycle" behavior.
            current = max(symbol_positions, key=lambda p: p.position_id)

            if replayed is None:
                violations.append(
                    f"symbol {symbol}: position {current.position_id} is persisted but no trades exist for it"
                )
                continue

            if not _close(current.quantity, replayed["quantity"]):
                violations.append(
                    f"symbol {symbol} position {current.position_id}: quantity "
                    f"{current.quantity!r} != replayed {replayed['quantity']!r}"
                )
            if not _close(current.average_price, replayed["average_price"]):
                violations.append(
                    f"symbol {symbol} position {current.position_id}: average_price "
                    f"{current.average_price!r} != replayed {replayed['average_price']!r}"
                )
            if not _close(current.realized_pnl, replayed["realized_pnl"]):
                violations.append(
                    f"symbol {symbol} position {current.position_id}: realized_pnl "
                    f"{current.realized_pnl!r} != replayed {replayed['realized_pnl']!r}"
                )
            if not _close(current.buy_fee_accumulated, replayed["buy_fee_accumulated"]):
                violations.append(
                    f"symbol {symbol} position {current.position_id}: buy_fee_accumulated "
                    f"{current.buy_fee_accumulated!r} != replayed {replayed['buy_fee_accumulated']!r}"
                )
            if current.status != replayed["status"]:
                violations.append(
                    f"symbol {symbol} position {current.position_id}: status "
                    f"'{current.status}' != replayed '{replayed['status']}'"
                )
            if current.direction != replayed["direction"]:
                violations.append(
                    f"FOREX_DIRECTION_MISMATCH: symbol {symbol} position "
                    f"{current.position_id}: direction '{current.direction}' != "
                    f"replayed '{replayed['direction']}'"
                )

    # -- invariant 4: portfolio state sanity -----------------------------

    @staticmethod
    def _check_portfolio_state(
        account_id: str,
        cash: float,
        positions,
        violations: List[str],
        not_verifiable: List[str],
    ) -> None:
        if cash < 0:
            violations.append(f"account {account_id} cash {cash!r} is negative")

        for position in positions:
            if position.quantity < 0:
                violations.append(
                    f"position {position.position_id} quantity {position.quantity!r} is negative"
                )
            if _close(position.quantity, 0.0) and position.status != _STATUS_CLOSED:
                violations.append(
                    f"position {position.position_id} quantity is 0 but status is "
                    f"'{position.status}', expected '{_STATUS_CLOSED}'"
                )
            if position.quantity > 0.0 and position.status != _STATUS_OPEN:
                violations.append(
                    f"position {position.position_id} quantity is {position.quantity!r} "
                    f"but status is '{position.status}', expected '{_STATUS_OPEN}'"
                )

        not_verifiable.append(NOT_VERIFIABLE_PORTFOLIO_VALUATION)

    # -- Forex invariants (Activation 11.16, additive) --------------------
    #
    # Only ever invoked when ``Account.asset_class == "forex"``
    # (``reconcile_account`` above) -- IDX/US/Crypto accounts never
    # reach this method, so their reconciliation semantics are
    # provably byte-for-byte unchanged by this Activation.
    #
    # None of this persists a new field or a margin ledger. Every
    # check below recomputes a Forex risk quantity from currently
    # persisted ``Position`` state (``direction``/``average_price``/
    # ``quantity``/``symbol``/``stop_loss``) through the existing,
    # already-LOCKED policy functions (``Business.position_manager.
    # is_stop_loss_side_valid`` -- the direction-aware LONG/SHORT rule,
    # not ``Business.forex_stop_loss_policy``'s BUY/SELL-sided one,
    # since reconciliation reads a persisted ``direction``, not an
    # order ``action`` -- ``Business.forex_pip_policy.
    # calculate_pip_value``, ``Business.forex_margin_policy.
    # calculate_required_margin``, ``Business.forex_max_loss_policy.
    # calculate_maximum_loss``) -- never a second/duplicated formula.
    #
    # Price basis (see module/Activation-report "CRITICAL QUESTION --
    # WHICH PRICE" discussion): ``Position.average_price`` is used for
    # both margin and maximum-loss reconstruction. This is the same
    # reference price ``is_stop_loss_side_valid`` is already defined
    # against for an existing position (see that function's own
    # docstring), it is PositionManager's own quantity-weighted entry
    # basis (correct for a merged multi-trade position, unlike any
    # single ``Trade.fill_price``), and it is the only entry-price
    # value this engine can read without re-deriving one from replayed
    # trade history (which invariant 3 above already does, separately,
    # for its own purpose). ``Order.requested_price`` is not used --
    # it is a pre-trade value, not part of the persisted Position/
    # Trade state a reconciliation reads.
    #
    # There is no persisted ``pip_value``/``required_margin``/
    # ``maximum_loss`` field to diff a recomputed value against (by
    # design -- see the "REQUIRED MARGIN" / "MAXIMUM LOSS" sections of
    # the roadmap brief this Activation implements: both are
    # explicitly derived-only state, and no schema change is made
    # here). So the check these three make is reconstructability
    # itself: recomputation must succeed (not raise) against the
    # currently persisted symbol/price/quantity/stop-loss. A
    # ``ValidationError`` here means this engine cannot prove the risk
    # layer's number is reconstructable from what is actually
    # persisted -- reported as an explicit violation, never silently
    # swallowed.
    @staticmethod
    def _check_forex_state(positions, violations: List[str]) -> None:
        for position in positions:
            if position.quantity <= 0.0:
                # A CLOSED Forex position carries no live protective
                # state to reconstruct -- nothing further to check.
                continue

            symbol = position.symbol
            quantity = position.quantity
            average_price = position.average_price
            direction = position.direction
            stop_loss = position.stop_loss

            # -- stop-loss presence + directional validity ------------
            if stop_loss is None:
                violations.append(
                    f"FOREX_STOP_LOSS_MISSING: position {position.position_id} "
                    f"symbol {symbol} is an OPEN Forex position with no "
                    f"persisted stop_loss (required by the production Forex "
                    f"order contract, Activation 11.14)"
                )
            elif not is_stop_loss_side_valid(direction, average_price, stop_loss):
                violations.append(
                    f"FOREX_STOP_LOSS_INVALID: position {position.position_id} "
                    f"symbol {symbol} direction {direction}: stop_loss "
                    f"{stop_loss!r} is not valid against average_price "
                    f"{average_price!r}"
                )

            # -- pip value reconstruction ------------------------------
            try:
                calculate_pip_value(symbol, quantity)
            except ValidationError as exc:
                violations.append(
                    f"FOREX_PIP_VALUE_MISMATCH: position {position.position_id} "
                    f"symbol {symbol}: pip value could not be reconstructed "
                    f"from persisted state ({exc})"
                )

            # -- required margin reconstruction ------------------------
            try:
                calculate_required_margin(symbol, average_price, quantity)
            except ValidationError as exc:
                violations.append(
                    f"FOREX_MARGIN_MISMATCH: position {position.position_id} "
                    f"symbol {symbol}: required margin could not be "
                    f"reconstructed from persisted state ({exc})"
                )

            # -- maximum loss reconstruction ---------------------------
            # Only attempted when a stop_loss is actually persisted --
            # calculate_maximum_loss requires one as input, and the
            # missing/invalid cases are already reported above under
            # their own, more specific violation categories.
            if stop_loss is not None:
                try:
                    calculate_maximum_loss(symbol, average_price, stop_loss, quantity)
                except ValidationError as exc:
                    violations.append(
                        f"FOREX_MAX_LOSS_MISMATCH: position {position.position_id} "
                        f"symbol {symbol}: maximum loss could not be "
                        f"reconstructed from persisted state ({exc})"
                    )


def _close(a: float, b: float, epsilon: float = _EPSILON) -> bool:
    return abs(a - b) <= epsilon


def _replay_position(
    symbol_trades: List[Trade], violations: List[str], is_forex: bool = False
) -> Optional[dict]:
    """Replay one symbol's ``Trade`` history, in ``trade_id`` order,
    into the final ``quantity``/``average_price``/``realized_pnl``/
    ``buy_fee_accumulated``/``status``/``direction`` state, mirroring
    ``Business.position_manager.PositionManager.apply_trade``/
    ``_merge_same_direction``/``_reduce_opposite_direction`` exactly
    (same formulas, not re-derived).

    ``is_forex`` (Activation 11.16, additive): ``False`` preserves
    this function's pre-11.16 behavior byte-for-byte -- a SELL with no
    open state replayed so far is flagged as a violation, exactly as
    before, and every position that ever opens does so LONG (the only
    direction IDX/US/Crypto ever produce). ``True`` mirrors
    ``PositionManager.apply_trade``'s Forex-only rule (Activation
    11.10 Decision C / 11.12): a SELL with no open state replayed so
    far OPENS a SHORT instead of being flagged. From then on, a
    same-direction trade (BUY into LONG, SELL into SHORT) merges
    (``_merge_same_direction``'s weighted-average-price formula); an
    opposite-direction trade (SELL against LONG, BUY against SHORT)
    reduces (``_reduce_opposite_direction``'s direction-signed
    realized-P/L formula). Only ever called with ``True`` when the
    owning ``Account.asset_class == "forex"`` (see
    ``ReconciliationEngine.reconcile_account``), so this parameter
    changes nothing for any IDX/US/Crypto account.

    No anchor is needed (unlike cash): a symbol's position history
    always starts from "no position" the first time it is ever
    traded, so this function needs nothing beyond the trades
    themselves.

    Returns:
        ``None`` if ``symbol_trades`` is empty. Otherwise a dict with
        keys ``quantity``/``average_price``/``realized_pnl``/
        ``buy_fee_accumulated``/``status``/``direction`` reflecting
        the position as it stands after the last trade replayed (i.e.
        after the most recent open-or-reopen cycle -- exactly what
        the currently persisted highest-``position_id`` row for this
        symbol should equal).
    """
    state: Optional[dict] = None
    for trade in symbol_trades:
        if trade.action not in (_BUY, _SELL):
            violations.append(
                f"trade {trade.trade_id} has unrecognized action '{trade.action}'"
            )
            continue

        if state is None or state["status"] == _STATUS_CLOSED:
            # Opening (or re-opening after a full close) trade.
            if trade.action == _BUY:
                direction = _DIRECTION_LONG
            elif is_forex:
                direction = _DIRECTION_SHORT
            else:
                # Read-only/defensive only: production pre-trade gate 9
                # already prevents this from ever happening through the
                # real pipeline for a non-Forex account (Activation 3.9
                # STEP 1 audit sec. 6). Flag it rather than fabricate a
                # position.
                violations.append(
                    f"trade {trade.trade_id} SELLs {trade.symbol} with no open "
                    f"position replayed from trade history so far"
                )
                continue
            state = {
                "quantity": trade.quantity,
                "average_price": trade.fill_price,
                "realized_pnl": 0.0,
                "status": _STATUS_OPEN,
                "buy_fee_accumulated": trade.fee,
                "direction": direction,
            }
            continue

        same_direction = (trade.action == _BUY and state["direction"] == _DIRECTION_LONG) or (
            trade.action == _SELL and state["direction"] == _DIRECTION_SHORT
        )

        if same_direction:
            # Mirrors PositionManager._merge_same_direction exactly.
            old_quantity = state["quantity"]
            old_average_price = state["average_price"]
            new_quantity = old_quantity + trade.quantity
            state["quantity"] = new_quantity
            state["average_price"] = (
                old_quantity * old_average_price + trade.quantity * trade.fill_price
            ) / new_quantity
            state["buy_fee_accumulated"] = state["buy_fee_accumulated"] + trade.fee
            # realized_pnl/status/direction unchanged on a same-direction
            # merge -- mirrors PositionManager._merge_same_direction.
        else:
            # Mirrors PositionManager._reduce_opposite_direction exactly.
            if trade.quantity > state["quantity"]:
                violations.append(
                    f"trade {trade.trade_id} {trade.action}s {trade.quantity} of "
                    f"{trade.symbol}, exceeding the {state['quantity']!r} replayed "
                    f"as held ({state['direction']})"
                )
                continue
            old_average_price = state["average_price"]
            old_quantity = state["quantity"]
            new_quantity = old_quantity - trade.quantity
            if state["direction"] == _DIRECTION_LONG:
                pnl_delta = (trade.fill_price - old_average_price) * trade.quantity
            else:
                pnl_delta = (old_average_price - trade.fill_price) * trade.quantity
            state["realized_pnl"] = state["realized_pnl"] + pnl_delta - trade.fee - trade.tax
            state["buy_fee_accumulated"] = state["buy_fee_accumulated"] * (new_quantity / old_quantity)
            state["quantity"] = new_quantity
            state["status"] = _STATUS_CLOSED if new_quantity == 0.0 else _STATUS_OPEN
            # average_price/direction unchanged on a reduce -- mirrors
            # PositionManager._reduce_opposite_direction exactly.
    return state