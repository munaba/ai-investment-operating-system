from __future__ import annotations

from typing import List

from Database.models import Account, Position, RankingSnapshot, Trade
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class PerformanceRepository(BasePersistenceRepository):
    """Read-only query layer over the data needed for performance
    analysis -- Trades, Positions, Accounts, and RankingSnapshots.

    Sprint 6 STEP 1 scope: QUERY ONLY. This repository exists purely
    so a later Sprint 6 STEP can read the raw rows it needs to compute
    performance statistics. It does NOT:

    * filter, group, or sort for any business reason (its four methods
      each return the entire table, in a fixed, structural order),
    * aggregate anything,
    * compute win rate, expectancy, drawdown, or any other statistic,
    * create, insert, update, or delete anything.

    All of the above is business logic reserved for STEP 2 onward
    (e.g. a future ``PerformanceAnalysisService``), which is expected
    to call this repository's methods and do its own filtering/
    grouping/aggregation over the results.

    Uses only the models already established by prior Sprints --
    ``Trade``/``Position``/``Account`` (Sprint 4) and
    ``RankingSnapshot`` (Sprint 5 STEP 3). No new model is introduced
    here.

    Mirrors ``TradeRepository``/``AccountRepository``/
    ``PositionRepository``/``SnapshotRepository`` exactly: depends only
    on ``DatabaseManager`` via ``BasePersistenceRepository``, issuing
    its own SQL through ``_execute`` and translating each row via a
    private ``_row_to_*`` helper -- never a generic CRUD base.
    """

    def get_all_trades(self) -> List[Trade]:
        """Return every trade, ordered by ``executed_at`` ascending.

        ``executed_at`` is the business timestamp of when a trade
        executed (see ``Database.models.Trade``), which is the
        chronological order a performance analysis needs -- unlike
        ``TradeRepository.list_all``'s ``trade_id`` ordering, which is
        purely a persistence-insertion order.

        Returns an empty list if the table has no rows.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM trades ORDER BY executed_at ASC")
        return [self._row_to_trade(row) for row in result.rows]

    def get_all_positions(self) -> List[Position]:
        """Return every position, ordered by ``position_id`` ascending.

        Returns an empty list if the table has no rows.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM positions ORDER BY position_id ASC")
        return [self._row_to_position(row) for row in result.rows]

    def get_all_accounts(self) -> List[Account]:
        """Return every account, ordered by ``account_id`` ascending.

        Returns an empty list if the table has no rows. In practice
        there is usually only one account, but this method makes no
        assumption about that.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM accounts ORDER BY account_id ASC")
        return [self._row_to_account(row) for row in result.rows]

    def get_all_snapshots(self) -> List[RankingSnapshot]:
        """Return every ranking snapshot, ordered by ``snapshot_id``
        ascending.

        Returns an empty list if the table has no rows.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM ranking_snapshots ORDER BY snapshot_id ASC")
        return [self._row_to_snapshot(row) for row in result.rows]

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
        )

    @staticmethod
    def _row_to_account(row) -> Account:
        return Account(
            account_id=row["account_id"],
            account_name=row["account_name"],
            mode=row["mode"],
            currency=row["currency"],
            asset_class=row["asset_class"],
            cash=row["cash"],
            equity=row["equity"],
            buying_power=row["buying_power"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_snapshot(row) -> RankingSnapshot:
        # Activation 2.7: ranking_snapshots (migration version=11)
        # gained status/score/score_breakdown_json/evidence_summary/
        # error_message columns. Read defensively (a database only
        # migrated through version=10 still has the narrower shape)
        # rather than assuming every deployment is already on v11.
        keys = row.keys() if hasattr(row, "keys") else {}
        return RankingSnapshot(
            snapshot_id=row["snapshot_id"],
            scan_time=row["scan_time"],
            symbol=row["symbol"],
            recommendation=row["recommendation"],
            confidence=row["confidence"],
            priority=row["priority"],
            rank=row["rank"],
            status=row["status"] if "status" in keys else "success",
            score=row["score"] if "score" in keys else None,
            score_breakdown_json=row["score_breakdown_json"] if "score_breakdown_json" in keys else None,
            evidence_summary=row["evidence_summary"] if "evidence_summary" in keys else None,
            error_message=row["error_message"] if "error_message" in keys else None,
        )