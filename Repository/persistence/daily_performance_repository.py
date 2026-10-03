from __future__ import annotations

from typing import List, Optional

from Database.models import DailyPerformance
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class DailyPerformanceRepository(BasePersistenceRepository):
    """Persists and queries ``DailyPerformance`` rows -- one
    append-only summary of an ``Account``'s trading performance over a
    caller-supplied ``[start_timestamp, end_timestamp]`` period
    (Activation 5.3).

    Activation 5.3 scope: PERSISTENCE ONLY. This repository stores and
    retrieves whatever ``account_id``/``start_timestamp``/
    ``end_timestamp``/``starting_equity``/``ending_equity``/
    ``realized_result``/``unrealized_result``/``fees``/``tax``/
    ``net_result``/``drawdown``/``number_of_signals``/
    ``number_of_executions``/``timestamp`` values a caller supplies.
    It does NOT:

    * read ``Account``, ``Position``, ``Trade``, or
      ``PortfolioSnapshot`` itself,
    * compute ``realized_result``, ``unrealized_result``, ``fees``,
      ``tax``, ``net_result``, ``drawdown``, or ``number_of_executions``,
    * create, update, or cancel an ``Order`` or ``Trade``,
    * update or delete a previously recorded daily performance row.

    All of that composition/computation is
    ``Business.daily_performance_service.DailyPerformanceService``'s
    job, exactly the same division of responsibility
    ``PortfolioSnapshotRepository`` already establishes relative to
    ``PortfolioSnapshotService``.

    Immutable / append-only (LOCKED design decision, mirrors
    ``PortfolioSnapshotRepository``/``TradeRepository``): this
    repository exposes no ``update``/``delete``/``replace``/``modify``
    method of any kind. Once a ``DailyPerformance`` row is inserted it
    can never be changed or removed through this repository -- any
    future correction must be represented as an additional row, never
    an in-place mutation.

    ``daily_performance_id`` is a caller-agnostic, repository-generated
    surrogate integer -- mirrors ``PortfolioSnapshotRepository``/
    ``TradeRepository``/``PositionRepository``/``OrderRepository``.
    """

    def create(
        self,
        account_id: str,
        start_timestamp: str,
        end_timestamp: str,
        realized_result: float,
        unrealized_result: float,
        fees: float,
        tax: float,
        net_result: float,
        drawdown: float,
        number_of_executions: int,
        timestamp: str,
        *,
        starting_equity: Optional[float] = None,
        ending_equity: Optional[float] = None,
        number_of_signals: Optional[int] = None,
    ) -> DailyPerformance:
        """Create a new, immutable daily performance row.

        Every argument is persisted exactly as supplied -- this method
        performs no computation, validation of financial correctness,
        or defaulting beyond ``starting_equity``/``ending_equity``/
        ``number_of_signals`` (see ``Database.models.DailyPerformance``
        for why each is ``Optional`` and typically ``None``).

        Args:
            account_id: The account this row summarizes.
            start_timestamp: ISO-8601 start of the summarized period.
            end_timestamp: ISO-8601 end of the summarized period.
            realized_result: Sum of realized P/L across the account's
                positions.
            unrealized_result: Sum of unrealized P/L across the
                account's open positions.
            fees: Sum of trade fees within the period.
            tax: Sum of trade tax within the period.
            net_result: ``realized_result + unrealized_result - fees
                - tax``.
            drawdown: Maximum drawdown over the equity curve within
                the period.
            number_of_executions: Count of trades within the period.
            timestamp: ISO-8601 UTC timestamp this row was composed
                at. Required, caller-supplied -- this repository does
                not auto-generate it (the caller,
                ``DailyPerformanceService``, owns "the moment this row
                was composed" as a business fact, exactly like
                ``PortfolioSnapshot.timestamp``).
            starting_equity: Caller-supplied starting equity, or
                ``None`` when no qualifying snapshot exists.
            ending_equity: Caller-supplied ending equity, or ``None``
                when no qualifying snapshot exists.
            number_of_signals: Caller-supplied signal count, or
                ``None`` when not yet verifiable (the expected value
                at this Activation -- see
                ``Database.models.DailyPerformance``).

        Returns:
            The newly created
            :class:`Database.models.DailyPerformance`, including the
            ``daily_performance_id`` assigned by the database.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            INSERT INTO daily_performance
                (account_id, start_timestamp, end_timestamp,
                 starting_equity, ending_equity, realized_result,
                 unrealized_result, fees, tax, net_result, drawdown,
                 number_of_signals, number_of_executions, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                start_timestamp,
                end_timestamp,
                starting_equity,
                ending_equity,
                realized_result,
                unrealized_result,
                fees,
                tax,
                net_result,
                drawdown,
                number_of_signals,
                number_of_executions,
                timestamp,
            ),
        )
        return DailyPerformance(
            daily_performance_id=result.lastrowid,
            account_id=account_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            realized_result=realized_result,
            unrealized_result=unrealized_result,
            fees=fees,
            tax=tax,
            net_result=net_result,
            drawdown=drawdown,
            number_of_signals=number_of_signals,
            number_of_executions=number_of_executions,
            timestamp=timestamp,
        )

    def get_by_id(self, daily_performance_id: int) -> Optional[DailyPerformance]:
        """Return the daily performance row with ``daily_performance_id``,
        or ``None`` if absent.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM daily_performance WHERE daily_performance_id = ?",
            (daily_performance_id,),
        )
        return self._row_to_daily_performance(result.rows[0]) if result.rows else None

    def list_by_account(self, account_id: str) -> List[DailyPerformance]:
        """Return every daily performance row for ``account_id``,
        ordered by ``daily_performance_id`` ascending (i.e.
        chronological insertion order).

        Returns an empty list if none exist for ``account_id``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM daily_performance WHERE account_id = ? ORDER BY daily_performance_id ASC",
            (account_id,),
        )
        return [self._row_to_daily_performance(row) for row in result.rows]

    def list_all(self) -> List[DailyPerformance]:
        """Return every daily performance row, ordered by
        ``daily_performance_id`` ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM daily_performance ORDER BY daily_performance_id ASC")
        return [self._row_to_daily_performance(row) for row in result.rows]

    def get_latest_by_account(self, account_id: str) -> Optional[DailyPerformance]:
        """Return the most recently inserted daily performance row for
        ``account_id`` (highest ``daily_performance_id``), or ``None``
        if none exist.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            SELECT * FROM daily_performance
            WHERE account_id = ?
            ORDER BY daily_performance_id DESC
            LIMIT 1
            """,
            (account_id,),
        )
        return self._row_to_daily_performance(result.rows[0]) if result.rows else None

    @staticmethod
    def _row_to_daily_performance(row) -> DailyPerformance:
        return DailyPerformance(
            daily_performance_id=row["daily_performance_id"],
            account_id=row["account_id"],
            start_timestamp=row["start_timestamp"],
            end_timestamp=row["end_timestamp"],
            starting_equity=row["starting_equity"],
            ending_equity=row["ending_equity"],
            realized_result=row["realized_result"],
            unrealized_result=row["unrealized_result"],
            fees=row["fees"],
            tax=row["tax"],
            net_result=row["net_result"],
            drawdown=row["drawdown"],
            number_of_signals=row["number_of_signals"],
            number_of_executions=row["number_of_executions"],
            timestamp=row["timestamp"],
        )
