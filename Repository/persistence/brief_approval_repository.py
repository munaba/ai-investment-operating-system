from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from Database.models import BriefApproval
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class BriefApprovalRepository(BasePersistenceRepository):
    """Persists and queries ``brief_approvals`` rows -- Phase G (Task
    1/2, "Approved Brief -> Paper Link Contract").

    PERSISTENCE ONLY, mirroring ``OrderApprovalRepository`` exactly.
    This repository does not decide whether a brief is eligible to be
    linked (``status == "SUCCESS"``) or whether a human actually
    approved it -- both decisions are made exclusively by
    ``Services.brief_approval_service.BriefApprovalService`` before
    this repository is ever called. This repository only records the
    outcome of a decision that has already been made and already
    resulted in a fully-committed ``Trade``.

    Deliberately has NO ``update``/``delete`` method: rows here are
    immutable, mirroring ``OrderApprovalRepository``. ``brief_id`` is
    the table's ``PRIMARY KEY`` (see
    ``Database.migrations_brief_approvals``), so the database itself
    -- not just this class -- enforces "one link per brief": a second
    ``create()`` for the same ``brief_id`` raises ``RepositoryError``
    from the underlying ``PRIMARY KEY`` violation.
    """

    def create(
        self,
        brief_id: int,
        order_id: int,
        trade_id: int,
        approved_at: str,
    ) -> BriefApproval:
        """Record that ``brief_id`` was approved and linked to the
        paper order/trade it resulted in.

        Intended caller: ``BriefApprovalService``, once, immediately
        after ``PaperTradingEngine.submit_order()`` has already
        returned a fully-committed ``Trade`` -- never before. This
        method itself performs no existence check on ``brief_id`` and
        relies on the table's ``PRIMARY KEY`` to reject a true
        duplicate insert (one link per brief), mirroring
        ``OrderApprovalRepository.create()``.

        Args:
            brief_id: The ``decision_briefs.brief_id`` being linked.
                Must reference a ``SUCCESS`` brief -- not validated
                here; the caller is responsible for that check.
            order_id: The ``orders.order_id`` this approved brief
                resulted in.
            trade_id: The ``trades.trade_id`` that order resulted in.
            approved_at: ISO-8601 timestamp of the explicit human
                approval decision, caller-supplied -- this repository
                does not generate it.

        Returns:
            The newly created :class:`Database.models.BriefApproval`.

        Raises:
            RepositoryError: If ``brief_id`` already has a link row
                (PRIMARY KEY violation -- one link per brief), if
                ``brief_id``/``order_id``/``trade_id`` do not
                reference existing rows (foreign key violation), or
                the underlying statement fails for any other reason.
                Per the Phase G brief, the caller (``BriefApprovalService``)
                is required to treat any such failure as best-effort
                -- it must never roll back or otherwise affect the
                already-committed trade.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._execute(
            """
            INSERT INTO brief_approvals
                (brief_id, order_id, trade_id, approved_at, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (brief_id, order_id, trade_id, approved_at, now),
        )
        return BriefApproval(
            brief_id=brief_id,
            order_id=order_id,
            trade_id=trade_id,
            approved_at=approved_at,
            recorded_at=now,
        )

    def get_by_brief_id(self, brief_id: int) -> Optional[BriefApproval]:
        """Return the link row for ``brief_id``, or ``None`` if absent.

        A pure lookup -- does not create or mutate anything.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM brief_approvals WHERE brief_id = ?",
            (brief_id,),
        )
        return self._row_to_approval(result.rows[0]) if result.rows else None

    def get_by_order_id(self, order_id: int) -> Optional[BriefApproval]:
        """Return the link row for ``order_id``, or ``None`` if absent.

        A pure lookup -- does not create or mutate anything.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM brief_approvals WHERE order_id = ?",
            (order_id,),
        )
        return self._row_to_approval(result.rows[0]) if result.rows else None

    def list_all(self) -> List[BriefApproval]:
        """Return every brief_approvals row, ordered by ``brief_id``
        ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM brief_approvals ORDER BY brief_id ASC")
        return [self._row_to_approval(row) for row in result.rows]

    @staticmethod
    def _row_to_approval(row) -> BriefApproval:
        return BriefApproval(
            brief_id=row["brief_id"],
            order_id=row["order_id"],
            trade_id=row["trade_id"],
            approved_at=row["approved_at"],
            recorded_at=row["recorded_at"],
        )