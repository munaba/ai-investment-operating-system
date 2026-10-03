"""OrderLifecycleService -- Sprint 4 STEP 5.

Owner of the ``Order`` state machine. This is the project's first
business-layer component (see ``Docs/document.md`` "Sprint 4 -- Paper
Trading Engine"): everything before this STEP was persistence-only
(``AccountRepository``/``PositionRepository``/``OrderRepository``/
``TradeRepository``, Sprint 4 STEP 1-4).

Scope (LOCKED for this STEP):

* creates a new ``Order`` (status ``NEW``);
* runs only *structural* validation against it;
* moves it to ``VALIDATED`` -> ``PENDING`` on success, or straight to
  ``REJECTED`` (with a reason code) on failure;
* persists every status change through ``OrderRepository``.

This STEP does NOT execute orders, does NOT create a ``Trade``, does
NOT touch a ``Position``, does NOT touch ``Account`` cash/equity, and
does NOT compute fees, tax, or P/L of any kind. All of that is
reserved for a later Sprint 4 STEP (``ExecutionService``/
``PositionManager``/``AccountBalanceService``/``PaperTradingEngine``,
none of which exist yet).

State machine (LOCKED domain -- ``Database.order_constants.
ORDER_STATUSES``): ``NEW``, ``VALIDATED``, ``PENDING``,
``PARTIALLY_FILLED``, ``FILLED``, ``REJECTED``, ``CANCELLED``,
``EXPIRED``. Sprint 4 only implements two paths through it:

    NEW -> VALIDATED -> PENDING   (structural validation passes)
    NEW -> REJECTED                (structural validation fails)

Every other status (``PARTIALLY_FILLED``/``FILLED``/``CANCELLED``/
``EXPIRED``) already exists in the domain (so the ``orders`` table's
CHECK constraint accepts them, and no future migration is needed
purely to add a value that was already known/approved -- see
``Database.order_constants``), but this STEP defines no transition
into or out of them. Any attempted transition this STEP does not
define above is illegal and is rejected with ``ValidationError`` --
this is what "state lain hanya disiapkan, belum ada logic-nya" means
in code: the values exist, the transitions do not (yet).

Repository dependency (LOCKED): ``OrderRepository`` only. This
service does not read or write ``AccountRepository``,
``PositionRepository``, or ``TradeRepository``, and does not call
``Services.stock_service.StockService``. The STEP 5 spec allows a
read-only ``AccountRepository``/``StockService`` call *only* if the
blueprint requires this service to compute ``quantity`` from
``capital`` for a minimum-lot check -- no such approval exists in any
document available to this implementation (``Docs/document.md``'s
Sprint 4 section lists "lot size saham Indonesia" as a Sprint-4-wide
requirement but does not specify a lot size, a source for it, or
which STEP owns computing it). Introducing that logic here without an
explicit LOCKED decision would be inventing a validation rule outside
the blueprint, which the STEP 5 spec explicitly forbids ("Jangan
menambahkan validasi baru di luar blueprint"). See
``REASON_INSUFFICIENT_MINIMUM_LOT`` below for how this gap is
represented instead of silently guessed at.

Validation rules (LOCKED, structural only), first match wins, checked
in this exact order:

    1. ``symbol`` empty/blank            -> REASON_INVALID_SYMBOL
    2. ``action`` not in {"BUY", "SELL"} -> REASON_INVALID_ACTION
    3. ``quantity`` not a positive real   -> REASON_INVALID_QUANTITY
    4. ``requested_price`` not a positive
       real                               -> REASON_INVALID_PRICE

``REASON_INSUFFICIENT_MINIMUM_LOT`` is defined (it is part of the
STEP 5-approved reason-code domain) but is never raised by this
implementation, for the reason documented above.
"""

from __future__ import annotations

from typing import Optional

from Core.exceptions import ValidationError
from Database.models import Order
from Repository.persistence.order_repository import OrderRepository

#: Structural reason codes this STEP is approved to record on a
#: REJECTED order (LOCKED list from the STEP 5 spec). Nothing beyond
#: this tuple may be used as a REJECTED reason without approval.
REASON_INVALID_SYMBOL = "INVALID_SYMBOL"
REASON_INVALID_ACTION = "INVALID_ACTION"
REASON_INVALID_QUANTITY = "INVALID_QUANTITY"
REASON_INVALID_PRICE = "INVALID_PRICE"
REASON_INSUFFICIENT_MINIMUM_LOT = "INSUFFICIENT_MINIMUM_LOT"

REJECTION_REASONS: tuple[str, ...] = (
    REASON_INVALID_SYMBOL,
    REASON_INVALID_ACTION,
    REASON_INVALID_QUANTITY,
    REASON_INVALID_PRICE,
    REASON_INSUFFICIENT_MINIMUM_LOT,
)

#: Human-readable, non-REJECTED reason text for the two non-terminal
#: transitions this STEP performs. These are NOT part of
#: ``REJECTION_REASONS`` -- the spec only LOCKS a reason-code domain
#: for the REJECTED status, not for VALIDATED/PENDING.
_REASON_VALIDATED = "structural validation passed"
_REASON_PENDING = "queued after validation"

#: Actions this STEP recognizes structurally. Deliberately defined
#: here, not in ``Database.order_constants`` -- persistence layer
#: (``OrderRepository``) intentionally does NOT validate ``action``
#: (see its class docstring); constraining it is business logic, and
#: this business-layer service is exactly where that belongs.
_VALID_ACTIONS = ("BUY", "SELL")

#: Legal status transitions this STEP implements, keyed by current
#: status. Any current status not present as a key (PENDING and every
#: not-yet-implemented status) has no legal outgoing transition yet --
#: attempting one raises ValidationError. This is the single source of
#: truth for what "Sprint 4 aktif" state machine subset means in code.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"VALIDATED", "REJECTED"}),
    "VALIDATED": frozenset({"PENDING"}),
}


class OrderLifecycleService:
    """Owner of the ``Order`` state machine (Sprint 4 STEP 5).

    Depends on ``OrderRepository`` only -- no other repository, no
    Service, no Skill, no Tool. Never opens a transaction itself
    (``begin()``/``commit()``/``rollback()``); transaction
    orchestration is out of scope for this STEP and reserved for a
    future ``PaperTradingEngine``.
    """

    def __init__(self, order_repository: OrderRepository) -> None:
        """Initialize the service.

        Args:
            order_repository: The single repository this service is
                allowed to use. Stored by reference only -- this
                constructor performs no I/O.
        """
        self._order_repository = order_repository

    def create_order(
        self,
        account_id: str,
        symbol: str,
        action: str,
        quantity: float,
        requested_price: float,
        analysis_snapshot_id: Optional[int] = None,
    ) -> Order:
        """Create a new Order and run it through structural validation.

        Always persists a ``NEW`` row first (via
        ``OrderRepository.create``), then immediately drives it
        through the LOCKED Sprint 4 path:

            NEW -> VALIDATED -> PENDING   (validation passes)
            NEW -> REJECTED                (validation fails, reason set)

        Args:
            account_id: Owning account's ``account_id``. Passed
                through to ``OrderRepository.create`` unchanged --
                not itself validated here (that is
                ``AccountRepository``'s/a future STEP's concern).
            symbol: Traded symbol/ticker.
            action: Requested action. Must be ``"BUY"`` or ``"SELL"``
                to pass structural validation.
            quantity: Requested quantity. Must be a positive
                ``int``/``float`` to pass structural validation.
            requested_price: Requested price. Must be a positive
                ``int``/``float`` to pass structural validation.
            analysis_snapshot_id: (Activation 5.1, additive) the
                ``RankingSnapshot.snapshot_id`` backing this order's
                decision, if the caller has one. Passed straight
                through to ``OrderRepository.create()`` unchanged --
                not itself validated here, exactly like ``account_id``
                above. Defaults to ``None``.

        Returns:
            The ``Order`` as it stands after this call -- either
            ``status == "REJECTED"`` with a reason, or
            ``status == "PENDING"``.

        Raises:
            RepositoryError: If any underlying repository call fails.
        """
        order = self._order_repository.create(
            account_id=account_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            requested_price=requested_price,
            filled_price=0.0,
            status="NEW",
            reason="",
            analysis_snapshot_id=analysis_snapshot_id,
        )

        rejection_reason = self._validate(symbol, action, quantity, requested_price)
        if rejection_reason is not None:
            return self.transition_status(order.order_id, "REJECTED", rejection_reason)

        self.transition_status(order.order_id, "VALIDATED", _REASON_VALIDATED)
        return self.transition_status(order.order_id, "PENDING", _REASON_PENDING)

    def transition_status(self, order_id: int, to_status: str, reason: str) -> Order:
        """Move ``order_id`` to ``to_status``, recording ``reason``.

        Re-reads the order's *current* status from
        ``OrderRepository`` rather than trusting a caller-supplied
        "from" status -- the legality of a transition is always
        checked against what is actually persisted.

        Args:
            order_id: The order to transition.
            to_status: Target status. Must be a legal transition from
                the order's current persisted status (see
                ``_ALLOWED_TRANSITIONS``).
            reason: Reason/note to persist alongside the new status.

        Returns:
            The ``Order`` as it stands after the update.

        Raises:
            ValidationError: If ``order_id`` does not exist, or the
                transition from the order's current status to
                ``to_status`` is not one this STEP implements.
            RepositoryError: If any underlying repository call fails.
        """
        order = self._order_repository.get_by_id(order_id)
        if order is None:
            raise ValidationError(
                f"Order {order_id} not found",
                details={"order_id": order_id},
            )

        allowed = _ALLOWED_TRANSITIONS.get(order.status, frozenset())
        if to_status not in allowed:
            raise ValidationError(
                f"Illegal order status transition: '{order.status}' -> '{to_status}'",
                details={
                    "order_id": order_id,
                    "from_status": order.status,
                    "to_status": to_status,
                },
            )

        self._order_repository.update_status(order_id, to_status, reason)
        return self._order_repository.get_by_id(order_id)

    @staticmethod
    def _validate(
        symbol: str,
        action: str,
        quantity: float,
        requested_price: float,
    ) -> Optional[str]:
        """Run the LOCKED structural validation rule chain.

        First matching rule wins, checked in the exact order listed
        in the module docstring.

        Returns:
            The rejection reason code, or ``None`` if every rule
            passes.
        """
        if not isinstance(symbol, str) or not symbol.strip():
            return REASON_INVALID_SYMBOL

        if action not in _VALID_ACTIONS:
            return REASON_INVALID_ACTION

        if not OrderLifecycleService._is_positive_number(quantity):
            return REASON_INVALID_QUANTITY

        if not OrderLifecycleService._is_positive_number(requested_price):
            return REASON_INVALID_PRICE

        return None

    @staticmethod
    def _is_positive_number(value: object) -> bool:
        """``True`` iff ``value`` is an ``int``/``float`` (never
        ``bool``, which is an ``int`` subclass in Python) strictly
        greater than zero.
        """
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0