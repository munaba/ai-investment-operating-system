from __future__ import annotations

from typing import List, Optional

from Database.models import Trade
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class TradeRepository(BasePersistenceRepository):
    """Persists and queries Trades -- one append-only ledger entry
    recording that ``quantity`` of ``symbol`` filled at ``fill_price``
    for an ``order_id``/``account_id``.

    Sprint 4 STEP 4 scope: PERSISTENCE ONLY. This repository stores
    and retrieves whatever ``action``/``quantity``/``fill_price``/
    ``fee``/``tax``/``executed_at`` values a caller supplies. It does
    NOT:

    * decide whether/when/how much of an order fills (that is a
      future ``ExecutionService``'s job),
    * merge a trade's effect into a ``Position`` (that is a future
      ``PositionManager``/``PaperTradingEngine`` concern),
    * compute an average fill price, fee, or tax,
    * compute realized/unrealized P/L,
    * update or delete a previously recorded trade.

    All of the above is business logic reserved for a later Sprint 4
    STEP, which is expected to call ``create`` here with values it has
    already computed itself -- exactly the same division of
    responsibility ``OrderRepository``/``PositionRepository`` already
    establish.

    Immutable / append-only (LOCKED design decision): unlike
    ``AccountRepository``/``PositionRepository``/``OrderRepository``,
    this repository exposes no ``update``/``delete``/``replace``/
    ``modify`` method of any kind. Once a ``Trade`` row is inserted it
    can never be changed or removed through this repository -- any
    future correction must be represented as an additional ``Trade``
    row, never an in-place mutation. See ``Database.models.Trade`` for
    the full rationale.

    ``trade_id`` is a caller-agnostic, repository-generated surrogate
    integer -- mirrors ``PositionRepository``/``OrderRepository``, not
    ``AccountRepository``: a trade's natural key (``order_id`` +
    ``account_id`` + ``symbol``) is not stable or unique, since one
    order can produce more than one trade (partial fills). See
    ``Database.models.Trade`` for the full rationale.

    ``executed_at`` is a required, caller-supplied value -- this
    repository does not auto-generate it (unlike ``created_at``/
    ``updated_at`` on ``Account``/``Position``/``Order``, which record
    persistence-lifecycle time). ``executed_at`` is a business fact
    (when the trade executed), and deciding that value is business
    logic reserved for a future ``ExecutionService`` -- this STEP only
    stores whatever the caller supplies, exactly like every other
    field here.

    ``action`` is deliberately NOT validated here, mirroring
    ``OrderRepository`` -- see ``Database.migrations_trades`` module
    docstring for the full reasoning (no ``Database.trade_constants``
    single source of truth exists, because ``Trade`` has no domain
    field like ``status`` that needs one).
    """

    def create(
        self,
        order_id: int,
        account_id: str,
        symbol: str,
        action: str,
        quantity: float,
        fill_price: float,
        fee: float,
        tax: float,
        executed_at: str,
    ) -> Trade:
        """Create a new, immutable trade row.

        Args:
            order_id: The originating order's ``order_id``. Must
                reference an existing row in ``orders`` (enforced by
                the ``trades.order_id`` foreign key).
            account_id: The owning account's ``account_id``. Must
                reference an existing row in ``accounts`` (enforced
                by the ``trades.account_id`` foreign key).
            symbol: The traded symbol/ticker this trade fills.
            action: Caller-supplied action label (e.g. ``"BUY"``/
                ``"SELL"``). Not validated against a domain here --
                see class docstring.
            quantity: Quantity filled by this trade. Supplied by the
                caller as-is.
            fill_price: Price this trade filled at. Supplied by the
                caller as-is -- this method performs no fill
                computation.
            fee: Fee charged for this trade. Supplied by the caller
                as-is -- this method performs no fee calculation.
            tax: Tax charged for this trade. Supplied by the caller
                as-is -- this method performs no tax calculation.
            executed_at: ISO-8601 timestamp of when this trade
                executed. Required, caller-supplied -- see class
                docstring for why this is not auto-generated.

        Returns:
            The newly created :class:`Database.models.Trade`,
            including the ``trade_id`` assigned by the database.

        Raises:
            RepositoryError: If ``order_id`` does not reference an
                existing order, ``account_id`` does not reference an
                existing account (foreign key violations), or the
                underlying statement fails for any other reason.
        """
        result = self._execute(
            """
            INSERT INTO trades
                (order_id, account_id, symbol, action, quantity,
                 fill_price, fee, tax, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id, account_id, symbol, action, quantity,
                fill_price, fee, tax, executed_at,
            ),
        )
        return Trade(
            trade_id=result.lastrowid,
            order_id=order_id,
            account_id=account_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            fill_price=fill_price,
            fee=fee,
            tax=tax,
            executed_at=executed_at,
        )

    def get_by_id(self, trade_id: int) -> Optional[Trade]:
        """Return the trade with ``trade_id``, or ``None`` if absent.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,))
        return self._row_to_trade(result.rows[0]) if result.rows else None

    def list_by_account(self, account_id: str) -> List[Trade]:
        """Return every trade for ``account_id``, ordered by
        ``trade_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM trades WHERE account_id = ? ORDER BY trade_id ASC",
            (account_id,),
        )
        return [self._row_to_trade(row) for row in result.rows]

    def list_by_order(self, order_id: int) -> List[Trade]:
        """Return every trade produced by ``order_id`` (e.g. every
        partial fill), ordered by ``trade_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM trades WHERE order_id = ? ORDER BY trade_id ASC",
            (order_id,),
        )
        return [self._row_to_trade(row) for row in result.rows]

    def list_all(self) -> List[Trade]:
        """Return every trade, ordered by ``trade_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM trades ORDER BY trade_id ASC")
        return [self._row_to_trade(row) for row in result.rows]

    @staticmethod
    def _row_to_trade(row) -> Trade:
        return Trade(
            trade_id=row["trade_id"],
            order_id=row["order_id"],
            account_id=row["account_id"],
            symbol=row["symbol"],
            action=row["action"],
            quantity=row["quantity"],
            fill_price=row["fill_price"],
            fee=row["fee"],
            tax=row["tax"],
            executed_at=row["executed_at"],
        )