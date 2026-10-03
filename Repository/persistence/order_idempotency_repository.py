from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from Database.models import OrderIdempotencyKey
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class OrderIdempotencyRepository(BasePersistenceRepository):
    """Persists and queries ``order_idempotency_keys`` rows -- backs the
    "duplicate request/idempotency" pre-trade gate in
    ``Business.paper_trading_engine.PaperTradingEngine``.

    Activation 3.2 scope: PERSISTENCE ONLY, mirroring
    ``PositionRepository``/``AccountRepository``. This repository does
    NOT decide when a key counts as "used" or what to do about a
    duplicate -- it only stores/looks up rows. That decision belongs
    to ``PaperTradingEngine``.

    Deliberately has NO ``update``/``delete`` method: rows here are
    immutable, mirroring ``TradeRepository`` -- once an idempotency key
    has been recorded, it is never changed or removed.
    """

    def get_by_key(self, idempotency_key: str) -> Optional[OrderIdempotencyKey]:
        """Return the row for ``idempotency_key``, or ``None`` if absent.

        A pure lookup -- does not create or mutate anything. Intended
        for ``PaperTradingEngine`` to call before submitting a new
        order: a non-``None`` result means this key has already been
        used for a completed order/trade.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM order_idempotency_keys WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return self._row_to_key(result.rows[0]) if result.rows else None

    def create(
        self,
        idempotency_key: str,
        account_id: str,
        order_id: int,
        trade_id: int,
    ) -> OrderIdempotencyKey:
        """Record that ``idempotency_key`` has now been used.

        Check-then-insert is the caller's (``PaperTradingEngine``'s)
        responsibility via ``get_by_key`` first -- this method itself
        performs no existence check and relies on the table's
        ``idempotency_key`` ``PRIMARY KEY`` to reject a true duplicate
        insert (mirrors ``Core.bootstrap.ensure_default_paper_account``'s
        check-then-insert pattern).

        Args:
            idempotency_key: The caller-supplied key to record.
            account_id: Owning account's ``account_id``.
            order_id: The ``orders.order_id`` this key resulted in.
            trade_id: The ``trades.trade_id`` this key resulted in.

        Returns:
            The newly created :class:`Database.models.OrderIdempotencyKey`.

        Raises:
            RepositoryError: If ``idempotency_key`` already exists
                (PRIMARY KEY violation), if ``account_id``/``order_id``/
                ``trade_id`` do not reference existing rows (foreign
                key violation), or the underlying statement fails for
                any other reason.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            INSERT INTO order_idempotency_keys
                (idempotency_key, account_id, order_id, trade_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (idempotency_key, account_id, order_id, trade_id, now),
        )
        return OrderIdempotencyKey(
            idempotency_key=idempotency_key,
            account_id=account_id,
            order_id=order_id,
            trade_id=trade_id,
            created_at=now,
        )

    @staticmethod
    def _row_to_key(row) -> OrderIdempotencyKey:
        return OrderIdempotencyKey(
            idempotency_key=row["idempotency_key"],
            account_id=row["account_id"],
            order_id=row["order_id"],
            trade_id=row["trade_id"],
            created_at=row["created_at"],
        )
