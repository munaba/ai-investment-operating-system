from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from Core.exceptions import ValidationError
from Database.models import Position
from Database.position_constants import POSITION_DIRECTIONS, POSITION_STATUSES
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class PositionRepository(BasePersistenceRepository):
    """Persists and queries Positions -- one open/closed holding of a
    ``symbol`` within an ``account_id``.

    Sprint 4 STEP 2 scope: PERSISTENCE ONLY. This repository stores
    and retrieves whatever ``quantity``/``average_price``/
    ``realized_pnl``/``status`` values a caller supplies. It does NOT:

    * compute a weighted average price on a BUY merge,
    * decide how much ``quantity``/``realized_pnl`` change on a SELL,
    * decide when a position transitions OPEN -> CLOSED, or
    * enforce the lifecycle sequence (NO POSITION -> OPEN -> BUY ->
      MERGE -> SELL partial -> SELL all -> CLOSED) described in the
      Sprint 4 blueprint.

    All of the above is business logic reserved for a later Sprint 4
    STEP (e.g. a future ``PositionManager``/``PaperTradingEngine``),
    which is expected to call ``get_open_position``/``update`` here
    with values it has already computed itself.

    ``position_id`` is a caller-agnostic, repository-generated
    surrogate integer -- unlike ``AccountRepository``, this repository
    DOES generate its own identifier, because a position's natural key
    (``account_id`` + ``symbol``) is not stable across reopen cycles.
    See ``Database.models.Position`` for the full rationale.

    ``status`` validation reads from
    ``Database.position_constants.POSITION_STATUSES``, the same single
    source of truth the ``positions`` table's SQL ``CHECK`` constraint
    is generated from (see ``Database.migrations_positions``),
    mirroring ``AccountRepository``'s ``mode``/``asset_class``
    pattern.

    ``stop_loss``/``take_profit`` (Activation 3.8 STEP 2, additive):
    both ``create()`` and ``update()`` accept these as optional
    keyword args, defaulting to ``None`` (SQL ``NULL``) -- persisted
    and read back exactly as supplied, with no reference-price
    comparison or other validation performed here. That validation
    (LONG: ``stop_loss`` below entry, ``take_profit`` above entry)
    lives in ``Business.position_manager.PositionManager.
    set_stop_loss_take_profit``, matching this class's existing
    persistence-only scope boundary documented above. Defaulting to
    ``None`` also keeps every pre-existing call site of ``update()``
    (the BUY-merge/SELL-reduce paths in ``PositionManager``) safe to
    leave unchanged -- though ``PositionManager`` explicitly passes
    the position's current ``stop_loss``/``take_profit`` back through
    on every merge/reduce so a lifecycle update never silently wipes
    a previously configured level.
    """

    def create(
        self,
        account_id: str,
        symbol: str,
        quantity: float,
        average_price: float,
        realized_pnl: float,
        status: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        buy_fee_accumulated: float = 0.0,
        direction: str = "LONG",
    ) -> Position:
        """Create a new position row.

        Args:
            account_id: The owning account's ``account_id``. Must
                reference an existing row in ``accounts`` (enforced by
                the ``positions.account_id`` foreign key).
            symbol: The traded symbol/ticker this position holds.
            quantity: Current quantity held. Supplied by the caller
                as-is -- this method performs no averaging/merge math.
            average_price: Current average entry price. Supplied by
                the caller as-is.
            realized_pnl: Realized profit/loss accumulated so far.
                Supplied by the caller as-is.
            status: Must be one of
                ``Database.position_constants.POSITION_STATUSES``.
            stop_loss: Optional stop-loss level. Supplied by the
                caller as-is -- this method performs no reference-price
                validation; defaults to ``None`` (SQL ``NULL``).
            take_profit: Optional take-profit level. Supplied by the
                caller as-is -- this method performs no reference-price
                validation; defaults to ``None`` (SQL ``NULL``).
            buy_fee_accumulated: Running total of unrealized BUY
                ``Trade.fee`` (net-performance-after-fee). Supplied by
                the caller as-is; defaults to ``0.0``.

        Returns:
            The newly created :class:`Database.models.Position`,
            including the ``position_id`` assigned by the database.

            direction: Position direction (Activation 11.11,
                persistence groundwork only). Must be one of
                ``Database.position_constants.POSITION_DIRECTIONS``.
                Supplied by the caller as-is; defaults to ``"LONG"``,
                matching every existing call site's implicit prior
                behavior. No BUY/SELL-derived inference is performed
                here -- that is business logic reserved for a future
                ``PositionManager`` STEP.

        Raises:
            ValidationError: If ``status`` or ``direction`` is outside
                its allowed domain.
            RepositoryError: If ``account_id`` does not reference an
                existing account (foreign key violation), or the
                underlying statement fails for any other reason.
        """
        self._validate_status(status)
        self._validate_direction(direction)

        now = datetime.now(timezone.utc).isoformat()
        result = self._execute(
            """
            INSERT INTO positions
                (account_id, symbol, quantity, average_price, realized_pnl,
                 status, created_at, updated_at, stop_loss, take_profit,
                 buy_fee_accumulated, direction)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id, symbol, quantity, average_price, realized_pnl,
                status, now, now, stop_loss, take_profit, buy_fee_accumulated,
                direction,
            ),
        )
        return Position(
            position_id=result.lastrowid,
            account_id=account_id,
            symbol=symbol,
            quantity=quantity,
            average_price=average_price,
            realized_pnl=realized_pnl,
            status=status,
            created_at=now,
            updated_at=now,
            stop_loss=stop_loss,
            take_profit=take_profit,
            buy_fee_accumulated=buy_fee_accumulated,
            direction=direction,
        )

    def get_by_id(self, position_id: int) -> Optional[Position]:
        """Return the position with ``position_id``, or ``None`` if absent.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM positions WHERE position_id = ?", (position_id,))
        return self._row_to_position(result.rows[0]) if result.rows else None

    def get_open_position(self, account_id: str, symbol: str) -> Optional[Position]:
        """Return the single ``status='open'`` position for
        ``account_id`` + ``symbol``, or ``None`` if there isn't one.

        A pure lookup -- does not create, merge, or otherwise mutate
        anything. Intended for a later STEP's business logic to call
        before deciding whether a BUY should merge into an existing
        open position or ``create`` a fresh one.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM positions WHERE account_id = ? AND symbol = ? AND status = 'open'",
            (account_id, symbol),
        )
        return self._row_to_position(result.rows[0]) if result.rows else None

    def list_by_account(self, account_id: str) -> List[Position]:
        """Return every position for ``account_id``, ordered by
        ``position_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM positions WHERE account_id = ? ORDER BY position_id ASC",
            (account_id,),
        )
        return [self._row_to_position(row) for row in result.rows]

    def list_all(self) -> List[Position]:
        """Return every position, ordered by ``position_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM positions ORDER BY position_id ASC")
        return [self._row_to_position(row) for row in result.rows]

    def update(
        self,
        position_id: int,
        quantity: float,
        average_price: float,
        realized_pnl: float,
        status: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        buy_fee_accumulated: float = 0.0,
        direction: str = "LONG",
    ) -> None:
        """Update ``quantity``/``average_price``/``realized_pnl``/``status``/
        ``stop_loss``/``take_profit``/``buy_fee_accumulated`` in place,
        and bump ``updated_at``.

        Mutable update -- not append-only, mirrors
        ``AccountRepository.update_balances``. Performs no averaging,
        merge, or P/L computation itself: the caller supplies the
        already-computed final values. Silently affects zero rows if
        ``position_id`` does not exist (same tolerant style as
        ``AccountRepository.update_balances``; callers that need
        existence confirmation should ``get_by_id`` first).

        ``stop_loss``/``take_profit`` (Activation 3.8 STEP 2,
        additive): optional, default ``None``. Every value this method
        is called with -- including ``None`` -- is written verbatim;
        there is no "leave unchanged if omitted" behavior. Callers
        that must preserve an existing position's ``stop_loss``/
        ``take_profit`` across an unrelated update (e.g.
        ``PositionManager``'s BUY-merge/SELL-reduce paths) are
        responsible for reading the current row first and passing its
        values back through explicitly.

        ``direction`` (Activation 11.11, additive, persistence
        groundwork only): same "no leave-unchanged-if-omitted"
        contract as ``stop_loss``/``take_profit``/
        ``buy_fee_accumulated`` above -- every call writes exactly the
        ``direction`` value supplied, including the default
        ``"LONG"``. ``Business.position_manager.PositionManager`` is
        NOT modified by this STEP and its existing
        ``_merge_buy``/``_reduce_sell``/``set_stop_loss_take_profit``
        call sites do not pass ``direction`` -- every one of those
        existing calls therefore writes ``"LONG"`` on every update,
        which is a no-op today (no code path produces a ``"SHORT"``
        position yet, per Activation 11.10 Decision C). A future STEP
        that teaches ``PositionManager`` to open/merge/reduce SHORT
        positions must, at that time, read the current row's
        ``direction`` and pass it back through explicitly on every
        update -- exactly the same discipline already documented above
        for ``stop_loss``/``take_profit`` -- or a SHORT position's
        direction would be silently reset to ``"LONG"`` on its next
        merge/reduce. Not a concern for this STEP's actual callers,
        which never touch a SHORT row.

        Args:
            position_id: The position to update.
            quantity: New quantity value.
            average_price: New average price value.
            realized_pnl: New realized P/L value.
            status: Must be one of
                ``Database.position_constants.POSITION_STATUSES``.
            stop_loss: New stop-loss level, or ``None`` for SQL
                ``NULL``. No reference-price validation is performed
                here.
            take_profit: New take-profit level, or ``None`` for SQL
                ``NULL``. No reference-price validation is performed
                here.
            buy_fee_accumulated: New running total of unrealized BUY
                ``Trade.fee`` (net-performance-after-fee). Every value
                this method is called with -- including the default
                ``0.0`` -- is written verbatim, same "no
                leave-unchanged-if-omitted" behavior as
                ``stop_loss``/``take_profit``.
            direction: New direction value (Activation 11.11,
                persistence groundwork only). Must be one of
                ``Database.position_constants.POSITION_DIRECTIONS``.
                Written verbatim, including the default ``"LONG"`` --
                see the "no leave-unchanged-if-omitted" note above.

        Raises:
            ValidationError: If ``status`` or ``direction`` is outside
                its allowed domain.
            RepositoryError: If the underlying statement fails.
        """
        self._validate_status(status)
        self._validate_direction(direction)

        updated_at = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            UPDATE positions
            SET quantity = ?, average_price = ?, realized_pnl = ?, status = ?,
                updated_at = ?, stop_loss = ?, take_profit = ?,
                buy_fee_accumulated = ?, direction = ?
            WHERE position_id = ?
            """,
            (
                quantity, average_price, realized_pnl, status, updated_at,
                stop_loss, take_profit, buy_fee_accumulated, direction,
                position_id,
            ),
        )

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in POSITION_STATUSES:
            raise ValidationError(
                f"Invalid status '{status}': must be one of {list(POSITION_STATUSES)}",
                details={"status": status},
            )

    @staticmethod
    def _validate_direction(direction: str) -> None:
        """Validate ``direction`` against ``POSITION_DIRECTIONS`` (Activation
        11.11) -- mirrors ``_validate_status`` exactly, the same
        single-source-of-truth pattern used for ``status``. The SQL
        ``CHECK`` constraint generated from the same
        ``POSITION_DIRECTIONS`` tuple (see
        ``Database.migrations_positions`` version=18) is the final
        persistence guard; this Python-level check exists purely to
        raise the project's own ``ValidationError`` (with a clear
        message) instead of surfacing a raw SQLite ``IntegrityError``,
        matching how ``_validate_status`` already behaves relative to
        the ``status`` CHECK constraint.
        """
        if direction not in POSITION_DIRECTIONS:
            raise ValidationError(
                f"Invalid direction '{direction}': must be one of {list(POSITION_DIRECTIONS)}",
                details={"direction": direction},
            )

    @staticmethod
    def _row_to_position(row) -> Position:
        return Position(
            position_id=row["position_id"],
            account_id=row["account_id"],
            symbol=row["symbol"],
            quantity=row["quantity"],
            average_price=row["average_price"],
            realized_pnl=row["realized_pnl"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            buy_fee_accumulated=row["buy_fee_accumulated"],
            direction=row["direction"],
        )