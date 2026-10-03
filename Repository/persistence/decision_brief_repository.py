from __future__ import annotations

from typing import List, Optional

from Database.models import DecisionBrief
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class DecisionBriefRepository(BasePersistenceRepository):
    """Persists and queries ``DecisionBrief`` rows -- Phase B ("Decision
    Copilot").

    PERSISTENCE ONLY, mirroring ``SnapshotRepository`` exactly. This
    repository stores and retrieves whatever fields
    ``Services.decision_brief_service.DecisionBriefService`` supplies.
    It does NOT:

    * run ``RankingEngine``/``RiskManagementService`` or compute a
      status, a plan, or a rejection reason,
    * decide whether a brief is actionable,
    * update or delete a previously recorded brief.

    Immutable / append-only (mirrors ``SnapshotRepository``/
    ``TradeRepository``): no ``update``/``delete``/``replace``/
    ``modify`` method exists here. A brief, once created, survives a
    process restart unchanged -- any future correction is a new row.

    ``brief_id`` is a repository-generated surrogate integer, exactly
    like ``RankingSnapshot.snapshot_id``.
    """

    def create(
        self,
        symbol: str,
        generated_at: str,
        status: str,
        *,
        source_snapshot_id: Optional[int] = None,
        reason: Optional[str] = None,
        entry_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        risk_amount: Optional[float] = None,
        position_size: Optional[float] = None,
        risk_reward_ratio: Optional[float] = None,
    ) -> DecisionBrief:
        """Create a new, immutable decision brief row.

        Args:
            symbol: The symbol this brief was generated for.
            generated_at: ISO-8601 timestamp of when the brief was
                generated. Required, caller-supplied -- this
                repository does not auto-generate it, mirroring
                ``SnapshotRepository.create``'s ``scan_time``.
            status: One of the eight Phase-B statuses.
            source_snapshot_id: The ``RankingSnapshot.snapshot_id``
                this brief was derived from, if any.
            reason: Human-readable explanation, required for every
                non-``SUCCESS`` status.
            entry_price, stop_loss_price, take_profit_price,
            risk_amount, position_size, risk_reward_ratio: The plan,
                verbatim from ``RiskManagementService`` -- ``None``
                for every status except ``SUCCESS``. Not validated or
                enforced here; ``DecisionBriefService`` is responsible
                for never passing a plan alongside a non-``SUCCESS``
                status.

        Returns:
            The newly created :class:`Database.models.DecisionBrief`,
            including the ``brief_id`` assigned by the database.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            INSERT INTO decision_briefs
                (symbol, generated_at, status, source_snapshot_id, reason,
                 entry_price, stop_loss_price, take_profit_price,
                 risk_amount, position_size, risk_reward_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                generated_at,
                status,
                source_snapshot_id,
                reason,
                entry_price,
                stop_loss_price,
                take_profit_price,
                risk_amount,
                position_size,
                risk_reward_ratio,
            ),
        )
        return DecisionBrief(
            brief_id=result.lastrowid,
            symbol=symbol,
            generated_at=generated_at,
            status=status,
            source_snapshot_id=source_snapshot_id,
            reason=reason,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_amount=risk_amount,
            position_size=position_size,
            risk_reward_ratio=risk_reward_ratio,
        )

    def get_by_id(self, brief_id: int) -> Optional[DecisionBrief]:
        """Return the decision brief with ``brief_id``, or ``None`` if absent.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM decision_briefs WHERE brief_id = ?",
            (brief_id,),
        )
        return self._row_to_brief(result.rows[0]) if result.rows else None

    def get_latest_for_symbol(self, symbol: str) -> Optional[DecisionBrief]:
        """Return the most recently generated brief for ``symbol``, or
        ``None`` if none exists.

        "Most recent" is by ``generated_at`` descending, tie-broken by
        ``brief_id`` descending (the repository-assigned insertion
        order) so two briefs generated within the same timestamp
        resolution still resolve deterministically to the latest
        insert.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            SELECT * FROM decision_briefs
            WHERE symbol = ?
            ORDER BY generated_at DESC, brief_id DESC
            LIMIT 1
            """,
            (symbol,),
        )
        return self._row_to_brief(result.rows[0]) if result.rows else None

    def list_by_symbol(self, symbol: str) -> List[DecisionBrief]:
        """Return every brief recorded for ``symbol``, ordered by
        ``brief_id`` ascending (oldest first).

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM decision_briefs WHERE symbol = ? ORDER BY brief_id ASC",
            (symbol,),
        )
        return [self._row_to_brief(row) for row in result.rows]

    def list_all(self) -> List[DecisionBrief]:
        """Return every decision brief, ordered by ``brief_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM decision_briefs ORDER BY brief_id ASC")
        return [self._row_to_brief(row) for row in result.rows]

    @staticmethod
    def _row_to_brief(row) -> DecisionBrief:
        return DecisionBrief(
            brief_id=row["brief_id"],
            symbol=row["symbol"],
            generated_at=row["generated_at"],
            status=row["status"],
            source_snapshot_id=row["source_snapshot_id"],
            reason=row["reason"],
            entry_price=row["entry_price"],
            stop_loss_price=row["stop_loss_price"],
            take_profit_price=row["take_profit_price"],
            risk_amount=row["risk_amount"],
            position_size=row["position_size"],
            risk_reward_ratio=row["risk_reward_ratio"],
        )