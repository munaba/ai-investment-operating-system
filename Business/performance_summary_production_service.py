"""PerformanceSummaryProductionService -- Activation 5.5.

Gives ``PerformanceSummaryService`` (Sprint 6 STEP 7, LOCKED) a real,
account-scoped, database-backed production path. ``PerformanceSummaryService.
build()`` itself is unchanged -- LOCKED constructor (exactly six engines),
LOCKED call order, no repository access of its own (see its own module
docstring). This service only supplies its three parameters
(``trades``, ``positions``, ``equity_curve``) from real, already-
persisted data, then delegates to it verbatim.

Mirrors the ``DailyPerformanceService`` (Activation 5.3) precedent
exactly: a thin, read-only orchestrator over already-existing,
already-LOCKED collaborators. No new engine, no new formula, no new
abstraction.

Field sources (each already real, never fabricated):

* ``trades`` -- ``TradeRepository.list_by_account(account_id)``,
  passed unchanged to ``PerformanceSummaryService.build()``.
* ``positions`` -- ``PositionRepository.list_by_account(account_id)``,
  passed unchanged to ``PerformanceSummaryService.build()``.
* ``equity_curve`` -- ``PortfolioSnapshotService.get_equity_curve(
  account_id, ...)`` (Activation 5.4), which reads real, already-
  persisted ``PortfolioSnapshot`` rows via
  ``PortfolioSnapshotRepository.list_by_account_for_equity_curve``.
  Each ``EquityCurvePoint.equity`` is taken verbatim (``[point.equity
  for point in curve]``) -- no gap-fill, no synthetic point.

Account isolation: every read goes through the same ``account_id``,
via each repository's own ``account_id``-filtered method
(``list_by_account`` / ``get_equity_curve``'s ``account_id`` filter).
A position, trade, or snapshot belonging to any other account is
never included.

Read-only / observational (LOCKED, mirrors Activation 5.2/5.3 rule
18): this service never creates, updates, or cancels an ``Order``,
``Trade``, ``Position``, or ``PortfolioSnapshot``. It only reads
already-persisted state and returns a computed (never persisted)
``PerformanceSummary``.

Failure is never swallowed: if ``account_id`` does not exist, or if
any underlying repository/service call raises, this service lets that
exception propagate unchanged -- it never substitutes an empty/zero
summary for a real failure.

Dependencies (LOCKED, all pre-existing components -- no new engine or
abstraction is constructed by this Activation): ``AccountRepository``,
``TradeRepository``, ``PositionRepository``, ``PortfolioSnapshotService``,
``PerformanceSummaryService``.
"""

from __future__ import annotations

from typing import Optional

from Business.performance_summary_service import (
    PerformanceSummary,
    PerformanceSummaryService,
)
from Business.portfolio_snapshot_service import PortfolioSnapshotService
from Core.exceptions import ValidationError
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.trade_repository import TradeRepository


class PerformanceSummaryProductionService:
    """Builds a :class:`PerformanceSummary` for a real ``account_id``
    from real, already-persisted data.

    Depends only on already-existing, already-real components (see
    module docstring). Holds no reference to ``PaperTradingEngine`` or
    ``OrderRepository`` -- there is no import of either here,
    enforcing the read-only/observational boundary structurally, not
    just by convention.
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        trade_repository: TradeRepository,
        position_repository: PositionRepository,
        portfolio_snapshot_service: PortfolioSnapshotService,
        performance_summary_service: PerformanceSummaryService,
    ) -> None:
        """Store the collaborators this service composes a
        performance summary from.

        Args:
            account_repository: Used only to confirm the account
                exists before touching any other repository. Never
                written to.
            trade_repository: Used to read this account's trades.
                Never written to.
            position_repository: Used to read this account's
                positions. Never written to.
            portfolio_snapshot_service: The existing, LOCKED
                Activation 5.4 ``get_equity_curve()`` -- the sole
                source of the equity curve. Never reimplemented here.
            performance_summary_service: The existing, LOCKED Sprint 6
                STEP 7 orchestrator -- the sole place the six engines
                are actually called. Never reimplemented here.
        """
        self._account_repository = account_repository
        self._trade_repository = trade_repository
        self._position_repository = position_repository
        self._portfolio_snapshot_service = portfolio_snapshot_service
        self._performance_summary_service = performance_summary_service

    def get_performance_summary(
        self,
        account_id: str,
        *,
        start_timestamp: Optional[str] = None,
        end_timestamp: Optional[str] = None,
    ) -> PerformanceSummary:
        """Compose a :class:`PerformanceSummary` for ``account_id``
        from real, already-persisted data.

        Never creates, updates, or cancels anything -- purely
        observational, then a single, in-memory
        ``PerformanceSummaryService.build()`` call. Nothing here is
        persisted.

        Args:
            account_id: The account to summarize. Every underlying
                read is scoped to this ``account_id`` -- no other
                account's trades, positions, or snapshots are ever
                included.
            start_timestamp: Optional ISO-8601 inclusive lower bound
                for the equity curve, passed unchanged to
                ``PortfolioSnapshotService.get_equity_curve``. Does
                NOT filter ``trades``/``positions`` -- mirrors
                ``PerformanceSummaryService.build()``'s own contract
                of taking whatever ``trades``/``positions`` list it is
                given, exactly as ``TradeStatisticsEngine``/
                ``PositionPerformanceEngine`` already do for every
                other caller.
            end_timestamp: Optional ISO-8601 inclusive upper bound,
                same contract as ``start_timestamp``.

        Returns:
            The :class:`PerformanceSummary` returned by
            ``PerformanceSummaryService.build()`` -- exactly the six
            engines' own results, unmodified.

        Raises:
            ValidationError: If ``account_id`` does not exist.
            RepositoryError: If any underlying repository call fails.
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot build performance summary: account {account_id} not found",
                details={"account_id": account_id},
            )

        trades = self._trade_repository.list_by_account(account_id)
        positions = self._position_repository.list_by_account(account_id)

        equity_curve_points = self._portfolio_snapshot_service.get_equity_curve(
            account_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        equity_curve = [point.equity for point in equity_curve_points]

        return self._performance_summary_service.build(
            trades=trades,
            positions=positions,
            equity_curve=equity_curve,
        )