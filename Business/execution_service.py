"""ExecutionService -- Sprint 4 STEP 6.

Performs *paper* execution of a ``PENDING`` ``Order``: records a
``Trade`` and transitions the ``Order`` to ``FILLED``. No broker, no
API, no websocket, no network of any kind -- everything is a database
state change via ``OrderRepository``/``TradeRepository`` (both
already LOCKED, Sprint 4 STEP 3/STEP 4).

Scope (LOCKED for this STEP):

* reads an ``Order`` via ``OrderRepository``;
* requires ``Order.status == "PENDING"`` -- any other status (or a
  missing order) raises ``ValidationError``, which also covers
  idempotency: a previously ``FILLED`` order is simply "not PENDING"
  and is rejected the same way, so it can never produce a second
  ``Trade``;
* creates exactly one ``Trade`` per call, full-fill only (Sprint 4
  does not implement partial fills): ``Trade.quantity ==
  Order.quantity``, ``Trade.fill_price == Order.requested_price`` (no
  price fetch, no price computation, no ``StockService`` call);

``Trade.fill_price`` source (LOCKED DECISION, Sprint 4 STOP
resolution at PaperTradingEngine/STEP 9 integration): earlier this
STEP read ``Order.filled_price``. That field is set to ``0.0`` at
creation by ``Business.order_lifecycle_service.OrderLifecycleService.
create_order()`` and nothing in the STEP 5/STEP 6 chain ever writes a
different value into it before ``execute_order()`` runs -- so every
Trade produced by the full ``create_order()`` -> ``execute_order()``
chain would silently carry ``fill_price == 0.0`` regardless of the
requested price. This was never exercised by this file's own test
suite because its fixtures create the ``Order`` directly through
``OrderRepository.create(filled_price=<nonzero>, ...)``, bypassing
``OrderLifecycleService`` entirely. Fixed by reading
``Order.requested_price`` instead -- Sprint 4 has no execution-price
model beyond "filled at the price that was requested" (no slippage,
no partial fills, no live quote), so ``requested_price`` is the only
value already on the Order that means "the price this paper-fill
executed at". ``Order.filled_price`` was left untouched by this STEP
at the time (still nobody's job to write it -- that scope note is
superseded by Activation 3.4 STEP 2 below, which is the first STEP
whose job it becomes).
* moves ``Order.status`` to ``FILLED`` and, as of Activation 3.4
  STEP 2 (via ``OrderRepository.record_fill``), also copies
  ``Order.filled_price``/``Order.filled_quantity``/``Order.filled_at``
  from the ``Trade`` this same call just created -- superseding the
  earlier Sprint 4 STEP 6 scope note below, which limited this STEP to
  ``status`` only. The Activation 3.4 STEP 1 audit found that
  limitation was exactly why ``Order``/``Trade`` were guaranteed
  inconsistent on every fill; Activation 3.4 STEP 2's roadmap contract
  requires ``Order.filled_price = Trade.fill_price``,
  ``Order.filled_quantity = Trade.quantity``, and
  ``Order.filled_at = Trade.executed_at``, so this call now sets all
  four fields together, atomically from the caller's perspective (one
  ``UPDATE`` statement), sourced only from the already-persisted
  ``trade`` object -- never recomputed;
* returns the created ``Trade`` as the execution result.

This STEP does NOT touch cash, account balance, position, portfolio
value, realized P/L, unrealized P/L, fee, or tax computation -- all of
that is reserved for later Sprint 4 STEPs (none of which exist yet).

``fee``/``tax`` (updated, Activation 3.3 STEP 2): this service still
does not know any fee/tax *formula* and never will until a dedicated
Fee/Tax Policy STEP exists -- this STEP does not compute a fee or a
tax from anything. What changed is *where* the placeholder value comes
from: instead of the bare literals ``0.0``/``0.0`` written directly at
the call site, this service now reads
``self._execution_policy.buy_fee_rate``/``sell_fee_rate`` (by
``order.action``) and ``self._execution_policy.sell_tax_rate`` (BUY
has no tax leg on IDX) from the canonical
``Business.execution_policy_config.ExecutionPolicy`` passed into its
constructor. The default policy's rates are all ``0.0``, so every
``Trade`` this service creates today still carries ``fee=0.0``/
``tax=0.0`` -- byte-for-byte the same runtime value as before this
STEP, just sourced from one canonical place instead of a scattered
literal. ``TradeRepository``'s already-LOCKED signature/schema/
migration is unchanged by this STEP.

``executed_at`` (LOCKED, mirrors ``TradeRepository``): supplied by
the caller. This service never generates a timestamp itself.

Repository dependency (LOCKED): ``OrderRepository`` and
``TradeRepository`` only. This service does not read or write
``AccountRepository``/``PositionRepository``, and does not call
``Services.stock_service.StockService``.
"""

from __future__ import annotations

import os

from Business.execution_policy_config import ExecutionPolicy, load_execution_policy
from Business.us_market_policy import resolve_fee_tax
from Core.exceptions import ValidationError
from Database.models import Trade
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.trade_repository import TradeRepository

#: Reason text persisted on an Order transitioning to FILLED. Not a
#: LOCKED reason-code domain (STEP 5's REJECTED reason-code list does
#: not apply to FILLED) -- plain descriptive text, mirroring how
#: ``Business.order_lifecycle_service`` records non-REJECTED reasons.
_REASON_FILLED = "order filled by ExecutionService"

#: Action this service treats as "BUY" when selecting which
#: ``ExecutionPolicy`` fee rate applies. Mirrors
#: ``Business.paper_trading_engine._BUY`` -- deliberately re-declared
#: here rather than imported, same reasoning as that module gives for
#: not importing ``Business.order_lifecycle_service._VALID_ACTIONS``:
#: a private module attribute of a different LOCKED module.
_BUY = "BUY"


class ExecutionService:
    """Performs paper execution of a single ``PENDING`` Order.

    Depends on ``OrderRepository``/``TradeRepository`` only -- no
    other repository, no Service, no Skill, no Tool. Never opens a
    transaction itself; transaction orchestration is out of scope for
    this STEP and reserved for a future ``PaperTradingEngine``.
    """

    def __init__(
        self,
        order_repository: OrderRepository,
        trade_repository: TradeRepository,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            order_repository: Used to read the Order and to record its
                ``FILLED`` transition. Stored by reference only.
            trade_repository: Used to create the resulting ``Trade``.
                Stored by reference only.
            execution_policy: Canonical ``ExecutionPolicy`` (Activation
                3.3) this service reads its ``fee``/``tax`` placeholder
                values from. Defaults to
                ``Business.execution_policy_config.
                load_execution_policy()`` when not supplied -- mirrors
                ``Business.ranking_engine.RankingEngine``'s
                ``weights``/``load_ranking_weights()`` default
                pattern. The default policy's rates are all ``0.0``,
                reproducing this service's pre-3.3 behaviour exactly
                for any caller that does not pass one explicitly.
        """
        self._order_repository = order_repository
        self._trade_repository = trade_repository
        self._execution_policy = execution_policy if execution_policy is not None else load_execution_policy()

    def execute_order(self, order_id: int, executed_at: str) -> Trade:
        """Execute ``order_id``: create its ``Trade`` and mark it ``FILLED``.

        Args:
            order_id: The order to execute. Must currently exist and
                have ``status == "PENDING"``.
            executed_at: ISO-8601 timestamp of when this trade
                executed, supplied by the caller and passed through to
                ``TradeRepository.create`` unchanged -- this method
                generates no timestamp of its own.

        Returns:
            The newly created, immutable ``Trade``.

        Raises:
            ValidationError: If ``order_id`` does not exist, or the
                order's current status is not ``"PENDING"`` (this
                includes an already-``FILLED`` order -- there is no
                separate "already executed" error, "not PENDING"
                covers it).
            RepositoryError: If any underlying repository call fails.
        """
        order = self._order_repository.get_by_id(order_id)
        if order is None:
            raise ValidationError(
                f"Order {order_id} not found",
                details={"order_id": order_id},
            )

        if order.status != "PENDING":
            raise ValidationError(
                f"Cannot execute order {order_id}: status is '{order.status}', expected 'PENDING'",
                details={"order_id": order_id, "status": order.status},
            )

        # Activation 9.3 STEP 1: fee/tax are resolved via the shared
        # ``Business.us_market_policy.resolve_fee_tax()`` selection
        # function -- the same one ``PaperTradingEngine`` gate 8
        # already called moments earlier for this same order, using
        # the same market/action inputs, so the fee/tax actually
        # persisted here is guaranteed to match what gate 8 used for
        # its required-cash calculation (Requirement 4). ``market`` is
        # read the same way ``PaperTradingEngine`` gates 6/13 already
        # read it (``os.getenv("AIOS_MARKET", "idx")``) -- this
        # service still has no ``AIOS_MARKET``-aware constructor
        # collaborator; the read happens once, here, at call time.
        # For ``market == "us"`` this now reads ``USFeePolicy``
        # instead of silently falling back to IDX's
        # ``self._execution_policy`` (the leak the 9.3 audit found);
        # for every other market (``"idx"``, ``"crypto"``) this is
        # byte-for-byte the same ``self._execution_policy`` lookup
        # this service already performed before this STEP.
        # Activation 10.4 (additive): `symbol` is passed through so
        # market == "crypto" orders resolve fee/tax from
        # Business.crypto_fee_policy.CryptoFeePolicy (via
        # resolve_fee_tax) instead of silently falling back to IDX's
        # self._execution_policy -- see that function's own docstring
        # for the full rationale. `execution_liquidity` is left at its
        # default (taker), matching every current order this service
        # ever executes (no maker-capable order type exists yet -- see
        # Business.crypto_fee_policy module docstring). market in
        # ("idx", "us") are completely unaffected.
        market = os.getenv("AIOS_MARKET", "idx").strip().lower() or "idx"
        fee, tax = resolve_fee_tax(market, order.action, self._execution_policy, symbol=order.symbol)

        trade = self._trade_repository.create(
            order_id=order.order_id,
            account_id=order.account_id,
            symbol=order.symbol,
            action=order.action,
            quantity=order.quantity,
            fill_price=order.requested_price,
            fee=fee,
            tax=tax,
            executed_at=executed_at,
        )

        # Activation 3.4 STEP 2: synchronize the Order's fill fields
        # from the Trade that was just persisted, instead of only
        # transitioning status (the Activation 3.4 STEP 1 audit found
        # this was the exact gap causing Order.filled_price/
        # filled_quantity to stay 0.0/absent forever, and
        # Order.filled_at not to exist at all). Every value passed
        # here comes straight off `trade` -- the object this method
        # just got back from `self._trade_repository.create()` -- not
        # recomputed, not re-read from `order`, so Trade remains the
        # single source of truth for what actually executed, exactly
        # as the audit's LOCKED DECISION already established. If this
        # call raises, it propagates unchanged (no try/except here):
        # the Trade row this method already created stays committed,
        # and the caller (PaperTradingEngine.submit_order()) sees the
        # exception and does not write an idempotency-key row, per the
        # module's own already-audited failure semantics.
        self._order_repository.record_fill(
            order.order_id,
            status="FILLED",
            filled_price=trade.fill_price,
            filled_quantity=trade.quantity,
            filled_at=trade.executed_at,
            reason=_REASON_FILLED,
        )

        return trade