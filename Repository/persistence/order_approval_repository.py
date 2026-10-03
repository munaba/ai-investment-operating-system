from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from Database.models import OrderApproval
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class OrderApprovalRepository(BasePersistenceRepository):
    """Persists and queries ``order_approvals`` rows -- makes the
    ``user_approval`` that already gates
    ``Business.paper_trading_engine.PaperTradingEngine.submit_order``
    (gate 3, LOCKED, unchanged by this Activation) auditable from the
    database.

    Activation 7 Blocker #4 scope: PERSISTENCE ONLY, mirroring
    ``OrderIdempotencyRepository``. This repository does not decide
    whether an order was approved -- that decision is still made
    exclusively by gate 3 in ``PaperTradingEngine``, before this
    repository is ever called. This repository only records the
    outcome of a decision that has already been made and already
    resulted in a fully-committed ``Trade``.

    Deliberately has NO ``update``/``delete`` method: rows here are
    immutable, mirroring ``OrderIdempotencyRepository``/
    ``TradeRepository`` -- once an approval has been recorded, it is
    never changed or removed.
    """

    def get_by_order_id(self, order_id: int) -> Optional[OrderApproval]:
        """Return the row for ``order_id``, or ``None`` if absent.

        A pure lookup -- does not create or mutate anything.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM order_approvals WHERE order_id = ?",
            (order_id,),
        )
        return self._row_to_approval(result.rows[0]) if result.rows else None

    def create(
        self,
        order_id: int,
        trade_id: int,
        account_id: str,
        approved: bool,
    ) -> OrderApproval:
        """Record that ``order_id`` was approved (``approved`` --
        already checked ``True`` by gate 3 before this is ever called)
        and linked to ``trade_id``/``account_id``.

        Intended caller: ``PaperTradingEngine.submit_order()``, once,
        immediately after the trading state (Order/Trade/Account/
        Position/idempotency-key) is already fully committed -- never
        before. This method itself performs no existence check and
        relies on the table's ``order_id`` ``PRIMARY KEY`` to reject a
        true duplicate insert, mirroring
        ``OrderIdempotencyRepository.create()``.

        Args:
            order_id: The ``orders.order_id`` this approval gated.
            trade_id: The ``trades.trade_id`` that order resulted in.
            account_id: Owning account's ``account_id``.
            approved: The ``user_approval`` value gate 3 already
                required to be ``True``.

        Returns:
            The newly created :class:`Database.models.OrderApproval`.

        Raises:
            RepositoryError: If ``order_id`` already has an approval
                row (PRIMARY KEY violation), if ``order_id``/
                ``trade_id``/``account_id`` do not reference existing
                rows (foreign key violation), or the underlying
                statement fails for any other reason. Per the
                Activation 7 Blocker #4 brief, the caller
                (``PaperTradingEngine``) is required to treat any such
                failure as best-effort -- it must never roll back or
                otherwise affect the already-committed trade.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            INSERT INTO order_approvals
                (order_id, trade_id, account_id, approved, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, trade_id, account_id, 1 if approved else 0, now),
        )
        return OrderApproval(
            order_id=order_id,
            trade_id=trade_id,
            account_id=account_id,
            approved=approved,
            recorded_at=now,
        )

    @staticmethod
    def _row_to_approval(row) -> OrderApproval:
        return OrderApproval(
            order_id=row["order_id"],
            trade_id=row["trade_id"],
            account_id=row["account_id"],
            approved=bool(row["approved"]),
            recorded_at=row["recorded_at"],
        )