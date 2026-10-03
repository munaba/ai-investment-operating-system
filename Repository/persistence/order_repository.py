from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from Core.exceptions import ValidationError
from Database.models import Order
from Database.order_constants import ORDER_STATUSES
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class OrderRepository(BasePersistenceRepository):
    """Persists and queries Orders -- one request to buy/sell ``quantity``
    of ``symbol`` within an ``account_id``.

    Sprint 4 STEP 3 scope: PERSISTENCE ONLY. This repository stores
    and retrieves whatever ``action``/``quantity``/``requested_price``/
    ``filled_price``/``filled_quantity``/``status``/``reason`` values a
    caller supplies. It does NOT:

    * validate an order before it is created (that is
      ``OrderValidationSkill``'s job today, and a future
      ``OrderLifecycleService``'s job at the persistence-consuming
      layer),
    * execute an order or decide when/how much of it fills,
    * merge fill results into a ``Position`` (that is a future
      ``PositionManager``/``PaperTradingEngine`` concern),
    * compute an average fill price, fee, or tax,
    * validate available lots or cash, or
    * enforce the lifecycle sequence (NEW -> VALIDATED -> PENDING ->
      PARTIALLY_FILLED/FILLED/REJECTED/CANCELLED/EXPIRED) described in
      the Sprint 4 blueprint.

    All of the above is business logic reserved for a later Sprint 4
    STEP (e.g. a future ``OrderLifecycleService``), which is expected
    to call ``get_by_id``/``update``/``update_status`` here with values
    it has already computed itself -- exactly the same division of
    responsibility ``PositionRepository`` already establishes.

    ``order_id`` is a caller-agnostic, repository-generated surrogate
    integer -- mirrors ``PositionRepository``, not ``AccountRepository``:
    an order's natural key (``account_id`` + ``symbol``) is not stable
    or unique across the many orders an account can place over time.
    See ``Database.models.Order`` for the full rationale.

    ``status`` validation reads from
    ``Database.order_constants.ORDER_STATUSES``, the same single
    source of truth the ``orders`` table's SQL ``CHECK`` constraint is
    generated from (see ``Database.migrations_orders``), mirroring the
    ``status``/``mode``/``asset_class`` pattern already established by
    ``PositionRepository``/``AccountRepository``.

    ``action`` is deliberately NOT validated here. Constraining it
    (e.g. to ``BUY``/``SELL``) was never part of this STEP's locked
    scope (see ``Database.migrations_orders`` module docstring) --
    only ``status`` was asked for a single source of truth + CHECK.
    """

    def create(
        self,
        account_id: str,
        symbol: str,
        action: str,
        quantity: float,
        requested_price: float,
        filled_price: float,
        status: str,
        reason: str,
        filled_quantity: float = 0.0,
        analysis_snapshot_id: Optional[int] = None,
    ) -> Order:
        """Create a new order row.

        Args:
            account_id: The owning account's ``account_id``. Must
                reference an existing row in ``accounts`` (enforced by
                the ``orders.account_id`` foreign key).
            symbol: The traded symbol/ticker this order targets.
            action: Caller-supplied action label (e.g. ``"BUY"``/
                ``"SELL"``). Not validated against a domain here -- see
                class docstring.
            quantity: Requested quantity. Supplied by the caller as-is.
            requested_price: Requested price. Supplied by the caller
                as-is.
            filled_price: Price actually filled so far. Supplied by
                the caller as-is -- this method performs no fill
                computation.
            status: Must be one of
                ``Database.order_constants.ORDER_STATUSES``.
            reason: Caller-supplied human-readable reason/note for
                this order's current state.
            filled_quantity: Quantity actually filled so far. Defaults
                to ``0.0`` (nothing filled yet) -- see
                ``Database.models.Order`` for why ``0.0``, not
                ``NULL``, is this field's default. Sprint 4 does not
                yet compute this value anywhere; it is only stored.
            analysis_snapshot_id: (Activation 5.1, additive) the
                ``RankingSnapshot.snapshot_id`` backing this order's
                decision, if the caller has one. Defaults to ``None``
                -- supplied as-is, never looked up or validated
                against ``ranking_snapshots`` by this repository (see
                ``Database.migrations_orders`` version=15 for why no
                foreign key is enforced here).

        Returns:
            The newly created :class:`Database.models.Order`,
            including the ``order_id`` assigned by the database.

        Raises:
            ValidationError: If ``status`` is outside the allowed
                domain.
            RepositoryError: If ``account_id`` does not reference an
                existing account (foreign key violation), or the
                underlying statement fails for any other reason.
        """
        self._validate_status(status)

        now = datetime.now(timezone.utc).isoformat()
        result = self._execute(
            """
            INSERT INTO orders
                (account_id, symbol, action, quantity, requested_price,
                 filled_price, filled_quantity, status, reason,
                 created_at, updated_at, filled_at, analysis_snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id, symbol, action, quantity, requested_price,
                filled_price, filled_quantity, status, reason, now, now, None,
                analysis_snapshot_id,
            ),
        )
        return Order(
            order_id=result.lastrowid,
            account_id=account_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            requested_price=requested_price,
            filled_price=filled_price,
            filled_quantity=filled_quantity,
            status=status,
            reason=reason,
            created_at=now,
            updated_at=now,
            filled_at=None,
            analysis_snapshot_id=analysis_snapshot_id,
        )

    def get_by_id(self, order_id: int) -> Optional[Order]:
        """Return the order with ``order_id``, or ``None`` if absent.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        return self._row_to_order(result.rows[0]) if result.rows else None

    def list_by_account(self, account_id: str) -> List[Order]:
        """Return every order for ``account_id``, ordered by
        ``order_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM orders WHERE account_id = ? ORDER BY order_id ASC",
            (account_id,),
        )
        return [self._row_to_order(row) for row in result.rows]

    def list_all(self) -> List[Order]:
        """Return every order, ordered by ``order_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM orders ORDER BY order_id ASC")
        return [self._row_to_order(row) for row in result.rows]

    def update(
        self,
        order_id: int,
        filled_price: float,
        filled_quantity: float,
        status: str,
        reason: str,
    ) -> None:
        """Update ``filled_price``/``filled_quantity``/``status``/
        ``reason`` in place, and bump ``updated_at``.

        Mutable update -- not append-only, mirrors
        ``PositionRepository.update``. Performs no fill computation,
        averaging, or lifecycle-sequence enforcement itself: the
        caller supplies the already-computed final values. Silently
        affects zero rows if ``order_id`` does not exist (same
        tolerant style as ``PositionRepository.update``; callers that
        need existence confirmation should ``get_by_id`` first).

        Args:
            order_id: The order to update.
            filled_price: New filled price value.
            filled_quantity: New filled quantity value.
            status: Must be one of
                ``Database.order_constants.ORDER_STATUSES``.
            reason: New reason/note value.

        Raises:
            ValidationError: If ``status`` is outside the allowed
                domain.
            RepositoryError: If the underlying statement fails.
        """
        self._validate_status(status)

        updated_at = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            UPDATE orders
            SET filled_price = ?, filled_quantity = ?, status = ?, reason = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (filled_price, filled_quantity, status, reason, updated_at, order_id),
        )

    def update_status(self, order_id: int, status: str, reason: str) -> None:
        """Update only ``status``/``reason`` in place, and bump
        ``updated_at``.

        Narrower than ``update``: for a caller that only needs to
        record a status transition (e.g. NEW -> VALIDATED, or
        VALIDATED -> REJECTED) without touching fill data.
        ``filled_price``/``filled_quantity`` are left untouched.
        Silently affects zero rows if ``order_id`` does not exist,
        same tolerant style as ``update``.

        Args:
            order_id: The order to update.
            status: Must be one of
                ``Database.order_constants.ORDER_STATUSES``.
            reason: New reason/note value.

        Raises:
            ValidationError: If ``status`` is outside the allowed
                domain.
            RepositoryError: If the underlying statement fails.
        """
        self._validate_status(status)

        updated_at = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            UPDATE orders
            SET status = ?, reason = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (status, reason, updated_at, order_id),
        )

    def record_fill(
        self,
        order_id: int,
        status: str,
        filled_price: float,
        filled_quantity: float,
        filled_at: str,
        reason: str,
    ) -> None:
        """Synchronize ``status``/``filled_price``/``filled_quantity``/
        ``filled_at`` in place from an already-persisted ``Trade``, and
        bump ``updated_at``.

        Added (Activation 3.4 STEP 2, additive) specifically for the
        Order<->Trade consistency contract: ``Business.
        execution_service.ExecutionService.execute_order()`` calls this
        exactly once, immediately after ``TradeRepository.create()``
        succeeds, passing the four values straight off the ``Trade``
        object that was just persisted (``Trade.fill_price``/
        ``Trade.quantity``/``Trade.executed_at``) -- never recomputed,
        never re-read from anywhere else. This keeps ``Trade`` the one
        source of truth for fill facts (per the Activation 3.4 STEP 1
        audit) while still letting ``Order`` carry a consistent copy.

        Deliberately a new, narrower method rather than widening
        ``update()``: ``update()`` predates ``filled_at`` entirely, is
        already exercised by its own test fixtures with its existing
        four-argument shape, and is not used by any production caller
        today -- changing its signature would risk that existing
        contract for no benefit. ``update_status()`` is also left
        untouched, since it explicitly promises to leave fill fields
        alone. This method is the one and only place that writes
        ``filled_at``.

        Args:
            order_id: The order to update.
            status: Must be one of
                ``Database.order_constants.ORDER_STATUSES`` (typically
                ``"FILLED"``, but not restricted to it -- this method
                only persists whatever the caller supplies).
            filled_price: New filled price value -- the caller's
                ``Trade.fill_price``.
            filled_quantity: New filled quantity value -- the caller's
                ``Trade.quantity``.
            filled_at: New filled-at timestamp -- the caller's
                ``Trade.executed_at``.
            reason: New reason/note value.

        Raises:
            ValidationError: If ``status`` is outside the allowed
                domain.
            RepositoryError: If the underlying statement fails. The
                caller (``ExecutionService``) does not catch this --
                a ``Trade`` row that was already committed and an
                ``Order`` that failed to sync are surfaced, not
                silently swallowed.
        """
        self._validate_status(status)

        updated_at = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            UPDATE orders
            SET status = ?, filled_price = ?, filled_quantity = ?,
                filled_at = ?, reason = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (status, filled_price, filled_quantity, filled_at, reason, updated_at, order_id),
        )

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in ORDER_STATUSES:
            raise ValidationError(
                f"Invalid status '{status}': must be one of {list(ORDER_STATUSES)}",
                details={"status": status},
            )

    @staticmethod
    def _row_to_order(row) -> Order:
        # `filled_at` (Activation 3.4 STEP 2): read defensively via
        # ``row.keys()`` rather than a bare ``row["filled_at"]``. This
        # repository must keep working unchanged against any database
        # that has had ``Database.migrations_orders`` versions 1-12
        # applied but not yet version=13 (the additive migration is
        # opt-in, applied explicitly like every other migration in this
        # codebase -- see that module's docstring) -- such a row simply
        # has no ``filled_at`` column at all, which is different from
        # (and must not raise like) a column that exists but is NULL.
        filled_at = row["filled_at"] if "filled_at" in row.keys() else None
        # `analysis_snapshot_id` (Activation 5.1): same defensive
        # ``row.keys()`` read as `filled_at` above, for the identical
        # reason -- a database with orders migrations 1-13 applied but
        # not yet version=15 simply has no such column at all.
        analysis_snapshot_id = (
            row["analysis_snapshot_id"] if "analysis_snapshot_id" in row.keys() else None
        )
        return Order(
            order_id=row["order_id"],
            account_id=row["account_id"],
            symbol=row["symbol"],
            action=row["action"],
            quantity=row["quantity"],
            requested_price=row["requested_price"],
            filled_price=row["filled_price"],
            filled_quantity=row["filled_quantity"],
            status=row["status"],
            reason=row["reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            filled_at=filled_at,
            analysis_snapshot_id=analysis_snapshot_id,
        )