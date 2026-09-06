from __future__ import annotations

from typing import List, Optional

from Database.models import PortfolioSnapshot
from Repository.persistence.base_persistence_repository import BasePersistenceRepository


class PortfolioSnapshotRepository(BasePersistenceRepository):
    """Persists and queries ``PortfolioSnapshot`` rows -- one
    append-only record of an ``Account``'s portfolio state at a point
    in time (Activation 5.2).

    Activation 5.2 scope: PERSISTENCE ONLY. This repository stores and
    retrieves whatever ``account_id``/``cash``/``market_value``/
    ``equity``/``realized_pnl``/``unrealized_pnl``/``exposure``/
    ``drawdown``/``timestamp`` values a caller supplies. It does NOT:

    * read ``Account``, ``Position``, or any market-price source
      itself,
    * compute ``cash``, ``market_value``, ``equity``, ``realized_pnl``,
      ``unrealized_pnl``, ``exposure``, or ``drawdown``,
    * create, update, or cancel an ``Order`` or ``Trade``,
    * update or delete a previously recorded snapshot.

    All of that composition/computation is
    ``Business.portfolio_snapshot_service.PortfolioSnapshotService``'s
    job, exactly the same division of responsibility
    ``SnapshotRepository`` already establishes relative to
    ``RankingEngine``.

    Immutable / append-only (LOCKED design decision, mirrors
    ``TradeRepository``/``SnapshotRepository``): this repository
    exposes no ``update``/``delete``/``replace``/``modify`` method of
    any kind. Once a ``PortfolioSnapshot`` row is inserted it can
    never be changed or removed through this repository -- any future
    correction must be represented as an additional row, never an
    in-place mutation.

    ``snapshot_id`` is a caller-agnostic, repository-generated
    surrogate integer -- mirrors ``TradeRepository``/
    ``PositionRepository``/``OrderRepository``/``SnapshotRepository``.
    """

    def create(
        self,
        account_id: str,
        cash: float,
        market_value: float,
        equity: float,
        realized_pnl: float,
        unrealized_pnl: float,
        drawdown: float,
        timestamp: str,
        *,
        exposure: Optional[float] = None,
        valuation_status: Optional[str] = None,
    ) -> PortfolioSnapshot:
        """Create a new, immutable portfolio snapshot row.

        Every argument is persisted exactly as supplied -- this method
        performs no computation, validation of financial correctness,
        or defaulting beyond ``exposure`` (see
        ``Database.models.PortfolioSnapshot`` for why ``exposure`` is
        ``Optional`` and typically ``None``).

        Args:
            account_id: The account this snapshot was captured for.
            cash: The account's cash at snapshot time.
            market_value: Total market value of this account's open
                positions at snapshot time.
            equity: ``cash + market_value`` at snapshot time.
            realized_pnl: Total realized P/L across this account's
                positions at snapshot time.
            unrealized_pnl: Total unrealized P/L across this account's
                open positions at snapshot time.
            drawdown: Maximum drawdown of this account's equity curve
                up to and including this snapshot.
            timestamp: ISO-8601 UTC timestamp this snapshot was
                composed at. Required, caller-supplied -- this
                repository does not auto-generate it (the caller,
                ``PortfolioSnapshotService``, owns "the moment this
                snapshot was taken" as a business fact, exactly like
                ``scan_time`` on ``RankingSnapshot``).
            exposure: Caller-supplied exposure value, or ``None`` when
                not yet verifiable (the expected value at this
                Activation -- see ``Database.models.PortfolioSnapshot``).
            valuation_status: Phase G Task 3 addition -- portfolio-level
                valuation freshness summary (``"FRESH"``/``"STALE"``),
                or ``None`` when freshness tracking was not enabled
                for this snapshot. See ``Database.models.
                PortfolioSnapshot.valuation_status``. Requires
                ``Database.migrations_portfolio_snapshot_valuation_status``
                to have been applied; passed through unchanged.

        Returns:
            The newly created :class:`Database.models.PortfolioSnapshot`,
            including the ``snapshot_id`` assigned by the database.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        # Phase G Task 3: ``valuation_status`` only exists once
        # ``Database.migrations_portfolio_snapshot_valuation_status``
        # (version=29) has been applied on top of the original
        # version=8 table. A caller (or an existing test fixture) that
        # has only applied version=8's ``PORTFOLIO_SNAPSHOTS_MIGRATIONS``
        # must keep working unchanged, so this method checks the real
        # schema before deciding which column list to insert -- never
        # assumes the additive migration has been applied.
        has_valuation_status_column = self._has_valuation_status_column()

        if has_valuation_status_column:
            result = self._execute(
                """
                INSERT INTO portfolio_snapshots
                    (account_id, cash, market_value, equity, realized_pnl,
                     unrealized_pnl, exposure, drawdown, timestamp, valuation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    cash,
                    market_value,
                    equity,
                    realized_pnl,
                    unrealized_pnl,
                    exposure,
                    drawdown,
                    timestamp,
                    valuation_status,
                ),
            )
        else:
            result = self._execute(
                """
                INSERT INTO portfolio_snapshots
                    (account_id, cash, market_value, equity, realized_pnl,
                     unrealized_pnl, exposure, drawdown, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    cash,
                    market_value,
                    equity,
                    realized_pnl,
                    unrealized_pnl,
                    exposure,
                    drawdown,
                    timestamp,
                ),
            )
            valuation_status = None
        return PortfolioSnapshot(
            snapshot_id=result.lastrowid,
            account_id=account_id,
            cash=cash,
            market_value=market_value,
            equity=equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            exposure=exposure,
            drawdown=drawdown,
            timestamp=timestamp,
            valuation_status=valuation_status,
        )

    def _has_valuation_status_column(self) -> bool:
        """Return whether the real ``portfolio_snapshots`` table already
        has the Phase G Task 3 ``valuation_status`` column.

        Cheap schema introspection via ``PRAGMA table_info`` -- run
        fresh on every ``create()`` call rather than cached, since
        this repository is never the sole owner of when the additive
        migration is applied relative to its own construction.
        """
        result = self._execute("PRAGMA table_info(portfolio_snapshots)")
        return any(row.get("name") == "valuation_status" for row in result.rows)

    def get_by_id(self, snapshot_id: int) -> Optional[PortfolioSnapshot]:
        """Return the portfolio snapshot with ``snapshot_id``, or
        ``None`` if absent.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM portfolio_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        return self._row_to_snapshot(result.rows[0]) if result.rows else None

    def list_by_account(self, account_id: str) -> List[PortfolioSnapshot]:
        """Return every portfolio snapshot for ``account_id``, ordered
        by ``snapshot_id`` ascending (i.e. chronological insertion
        order -- the order ``Business.portfolio_snapshot_service.
        PortfolioSnapshotService`` needs to build an equity curve for
        ``Business.maximum_drawdown_engine.MaximumDrawdownEngine``).

        Returns an empty list if none exist for ``account_id``.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            "SELECT * FROM portfolio_snapshots WHERE account_id = ? ORDER BY snapshot_id ASC",
            (account_id,),
        )
        return [self._row_to_snapshot(row) for row in result.rows]

    def list_all(self) -> List[PortfolioSnapshot]:
        """Return every portfolio snapshot, ordered by ``snapshot_id``
        ascending.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute("SELECT * FROM portfolio_snapshots ORDER BY snapshot_id ASC")
        return [self._row_to_snapshot(row) for row in result.rows]

    def list_by_account_for_equity_curve(
        self,
        account_id: str,
        *,
        start_timestamp: Optional[str] = None,
        end_timestamp: Optional[str] = None,
    ) -> List[PortfolioSnapshot]:
        """Return ``account_id``'s snapshots ordered deterministically
        by ``timestamp`` ascending, for building an equity curve
        (Activation 5.4).

        Ordered by ``timestamp ASC`` with ``snapshot_id ASC`` as the
        tie-breaker when two rows share the same ``timestamp`` --
        unlike ``list_by_account``/``list_all`` (ordered by
        ``snapshot_id`` alone), this method's contract is the
        chronological instant each snapshot represents, not insertion
        order, so it stays correct even if rows are ever inserted
        out of chronological order (e.g. a backfilled snapshot).

        Args:
            account_id: The account to build an equity curve for.
                Never mixes another account's snapshots into the
                result (see ``account_id`` filter below).
            start_timestamp: Optional ISO-8601 inclusive lower bound,
                compared lexicographically against ``timestamp`` --
                the same ``[start_timestamp, end_timestamp]``
                inclusive-boundary, string-comparison contract already
                used by
                ``Business.daily_performance_service.DailyPerformanceService``.
                ``None`` (default) applies no lower bound.
            end_timestamp: Optional ISO-8601 inclusive upper bound,
                same contract as ``start_timestamp``. ``None``
                (default) applies no upper bound.

        Returns:
            A list of :class:`Database.models.PortfolioSnapshot`,
            ordered ``timestamp ASC, snapshot_id ASC``. Empty list --
            never a fabricated point -- if ``account_id`` has no
            snapshot (in range, when a range is supplied).

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        sql = "SELECT * FROM portfolio_snapshots WHERE account_id = ?"
        params: List[object] = [account_id]

        if start_timestamp is not None:
            sql += " AND timestamp >= ?"
            params.append(start_timestamp)
        if end_timestamp is not None:
            sql += " AND timestamp <= ?"
            params.append(end_timestamp)

        sql += " ORDER BY timestamp ASC, snapshot_id ASC"

        result = self._execute(sql, tuple(params))
        return [self._row_to_snapshot(row) for row in result.rows]

    def get_latest_by_account(self, account_id: str) -> Optional[PortfolioSnapshot]:
        """Return the most recently inserted portfolio snapshot for
        ``account_id`` (highest ``snapshot_id``), or ``None`` if none
        exist.

        Raises:
            RepositoryError: If the underlying statement fails.
        """
        result = self._execute(
            """
            SELECT * FROM portfolio_snapshots
            WHERE account_id = ?
            ORDER BY snapshot_id DESC
            LIMIT 1
            """,
            (account_id,),
        )
        return self._row_to_snapshot(result.rows[0]) if result.rows else None

    @staticmethod
    def _row_to_snapshot(row) -> PortfolioSnapshot:
        # Phase G Task 3: ``valuation_status`` only exists once
        # ``Database.migrations_portfolio_snapshot_valuation_status``
        # (version=29) has been applied on top of the original
        # version=8 table. Read defensively so this repository keeps
        # working, unchanged, against any database that has not yet
        # applied that additive migration -- mirrors how every other
        # column here is read (a caller on an old schema simply never
        # sees this optional field, rather than the query failing).
        try:
            valuation_status = row["valuation_status"]
        except KeyError:
            valuation_status = None
        return PortfolioSnapshot(
            snapshot_id=row["snapshot_id"],
            account_id=row["account_id"],
            cash=row["cash"],
            market_value=row["market_value"],
            equity=row["equity"],
            realized_pnl=row["realized_pnl"],
            unrealized_pnl=row["unrealized_pnl"],
            exposure=row["exposure"],
            drawdown=row["drawdown"],
            timestamp=row["timestamp"],
            valuation_status=valuation_status,
        )