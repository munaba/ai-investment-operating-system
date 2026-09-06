"""DailyPerformanceService -- Activation 5.3.

Composes an already-real, already-verified summary of one ``Account``'s
trading performance over a caller-supplied
``[start_timestamp, end_timestamp]`` period into a single
:class:`Database.models.DailyPerformance` row and persists it via
``DailyPerformanceRepository``. This module computes nothing that
isn't already backed by an existing, real source -- see the
field-by-field rationale below and in
``Database.models.DailyPerformance``.

Read-only / observational toward trading state (LOCKED, mirrors
Activation 5.2 rule 18): this service never creates, updates, or
cancels an ``Order`` or a ``Trade``, never calls
``PaperTradingEngine``, and never mutates ``Account``/``Position``/
``PortfolioSnapshot`` in any way. It only reads already-persisted
state and writes one new, additional ``DailyPerformance`` row.

No scheduler, no background worker, no daemon (LOCKED, mirrors
Activation 5.2 rule 17): ``compute_daily_performance()`` is an
ordinary, synchronous method a caller invokes explicitly -- nothing
here schedules, loops, sleeps, or runs itself.

No calendar/timezone/trading-day logic (LOCKED, Activation 5.3
scope): ``start_timestamp``/``end_timestamp`` are opaque, caller-
supplied ISO-8601 strings compared lexicographically against
``Trade.executed_at``/``PortfolioSnapshot.timestamp`` -- this service
never derives "today", a trading calendar, or a timezone-aware
midnight boundary itself. Deciding what period to summarize is the
caller's business logic, not this service's.

Field sources (each already real, never fabricated):

* ``start_timestamp``/``end_timestamp`` -- taken verbatim from the
  caller; this service does not determine its own period.
* ``starting_equity``/``ending_equity`` -- the ``PortfolioSnapshot.
  equity`` of the latest snapshot, for this account, with
  ``timestamp <= start_timestamp``/``timestamp <= end_timestamp``
  respectively, read via
  ``PortfolioSnapshotRepository.list_by_account`` (chronological
  insertion order). ``None`` when no such snapshot exists -- never
  fabricated as ``0.0`` or the account's current cash.
* ``realized_result`` -- summed across every ``Position`` row (open
  and closed) for this account, straight off ``Position.
  realized_pnl`` -- mirrors ``PortfolioSnapshotService``. Not
  filtered to the period: ``Position.realized_pnl`` is a cumulative,
  per-row field with no per-period history anywhere in the codebase
  (see ``Database.models.Position``/``Business.position_manager``),
  the exact same limitation ``PortfolioSnapshotService`` already
  inherits and documents.
* ``unrealized_result`` -- summed across this account's OPEN
  positions using the existing, LOCKED ``Business.
  unrealized_pnl_engine.UnrealizedPnLEngine`` (the sole business
  owner of unrealized P/L, per its own module docstring). This
  service never computes ``(market_price - average_price) *
  quantity`` itself.
* ``fees``/``tax`` -- summed across this account's ``Trade`` rows
  (via ``TradeRepository.list_by_account``) whose ``executed_at``
  falls within ``[start_timestamp, end_timestamp]`` (inclusive,
  string comparison against the caller-supplied ISO-8601 boundaries)
  -- straight off ``Trade.fee``/``Trade.tax``.
* ``net_result`` -- ``realized_result + unrealized_result - fees -
  tax``. A direct derivation; no separate ``NetResultEngine`` is
  built or needed for this.
* ``drawdown`` -- computed by the existing, LOCKED ``Business.
  maximum_drawdown_engine.MaximumDrawdownEngine`` over this account's
  real, already-persisted ``PortfolioSnapshot.equity`` values whose
  ``timestamp`` falls within ``[start_timestamp, end_timestamp]``
  (chronological, via ``PortfolioSnapshotRepository.
  list_by_account``). This service never reimplements the
  peak/drawdown formula itself.
* ``number_of_signals`` -- always ``None`` at this Activation. NOT
  VERIFIABLE / GAP -- see ``Database.models.DailyPerformance``
  docstring for the full audit finding (no ``Signal`` entity exists
  in the codebase; ``RankingSnapshot`` is a different, per-symbol
  scan-run record and is never substituted here).
* ``number_of_executions`` -- the count of this account's ``Trade``
  rows within ``[start_timestamp, end_timestamp]`` (the same filtered
  set used for ``fees``/``tax``).
* ``timestamp`` -- ``datetime.now(timezone.utc).isoformat()``, the
  real instant this method composed the row -- the same pattern
  already used for ``PortfolioSnapshot.timestamp``.

Dependencies (LOCKED, all pre-existing components -- no new engine is
constructed by this Activation): ``AccountRepository``,
``PositionRepository``, ``TradeRepository``,
``PortfolioSnapshotRepository``, ``UnrealizedPnLEngine``,
``MaximumDrawdownEngine``, ``DailyPerformanceRepository``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from Business.maximum_drawdown_engine import MaximumDrawdownEngine
from Business.unrealized_pnl_engine import UnrealizedPnLEngine
from Core.exceptions import ValidationError
from Database.models import DailyPerformance
from Database.position_constants import POSITION_STATUSES
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.daily_performance_repository import DailyPerformanceRepository
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.trade_repository import TradeRepository

_OPEN_STATUS = "open"
assert _OPEN_STATUS in POSITION_STATUSES  # guards against POSITION_STATUSES drifting


class DailyPerformanceService:
    """Builds and persists one :class:`DailyPerformance` row for a
    given ``account_id`` and ``[start_timestamp, end_timestamp]``
    period, on demand.

    Depends only on already-existing, already-real components (see
    module docstring). Holds no reference to ``PaperTradingEngine`` or
    ``OrderRepository`` -- there is no import of either here,
    enforcing the read-only/observational boundary structurally, not
    just by convention.
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        position_repository: PositionRepository,
        trade_repository: TradeRepository,
        portfolio_snapshot_repository: PortfolioSnapshotRepository,
        unrealized_pnl_engine: UnrealizedPnLEngine,
        maximum_drawdown_engine: MaximumDrawdownEngine,
        daily_performance_repository: DailyPerformanceRepository,
    ) -> None:
        """Store the collaborators this service composes a daily
        performance row from.

        Args:
            account_repository: Used only to confirm the account
                exists. Never written to.
            position_repository: Used to read this account's
                positions (open, for ``unrealized_result``; all, for
                ``realized_result``). Never written to.
            trade_repository: Used to read this account's trades,
                filtered in-process to the requested period, for
                ``fees``/``tax``/``number_of_executions``. Never
                written to.
            portfolio_snapshot_repository: Used to read this account's
                prior snapshots for ``starting_equity``/
                ``ending_equity``/``drawdown``. Never written to.
            unrealized_pnl_engine: The existing, LOCKED sole owner of
                unrealized P/L computation. Never reimplemented here.
            maximum_drawdown_engine: The existing, LOCKED drawdown
                formula. Never reimplemented here.
            daily_performance_repository: Used to persist the composed
                row. The only repository this service ever writes
                through.
        """
        self._account_repository = account_repository
        self._position_repository = position_repository
        self._trade_repository = trade_repository
        self._portfolio_snapshot_repository = portfolio_snapshot_repository
        self._unrealized_pnl_engine = unrealized_pnl_engine
        self._maximum_drawdown_engine = maximum_drawdown_engine
        self._daily_performance_repository = daily_performance_repository

    def compute_daily_performance(
        self, account_id: str, start_timestamp: str, end_timestamp: str
    ) -> DailyPerformance:
        """Compose and persist one daily performance row for
        ``account_id`` over ``[start_timestamp, end_timestamp]``.

        Never creates, updates, or cancels an ``Order`` or ``Trade``,
        and never mutates ``Account``/``Position``/
        ``PortfolioSnapshot`` -- purely observational, then a single
        ``INSERT`` via ``DailyPerformanceRepository.create``.

        Args:
            account_id: The account to summarize.
            start_timestamp: ISO-8601 inclusive start of the period.
                Not validated against a calendar or timezone -- taken
                verbatim from the caller.
            end_timestamp: ISO-8601 inclusive end of the period. Not
                validated against a calendar or timezone -- taken
                verbatim from the caller.

        Returns:
            The newly persisted
            :class:`Database.models.DailyPerformance`.

        Raises:
            ValidationError: If ``account_id`` does not exist, or if
                ``UnrealizedPnLEngine`` cannot resolve a real market
                price for one of this account's open positions (this
                service never fabricates a market value/unrealized
                P/L from a missing price -- the whole computation
                fails rather than persist a partly-invented number).
            RepositoryError: If any underlying repository call fails.
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot compute daily performance: account {account_id} not found",
                details={"account_id": account_id},
            )

        all_positions = self._position_repository.list_by_account(account_id)
        open_positions = [p for p in all_positions if p.status == _OPEN_STATUS]

        unrealized_result = 0.0
        for position in open_positions:
            result = self._unrealized_pnl_engine.calculate(position)
            unrealized_result += result.unrealized_pnl

        realized_result = sum(p.realized_pnl for p in all_positions)

        all_trades = self._trade_repository.list_by_account(account_id)
        period_trades = [
            t
            for t in all_trades
            if start_timestamp <= t.executed_at <= end_timestamp
        ]
        fees = sum(t.fee for t in period_trades)
        tax = sum(t.tax for t in period_trades)
        number_of_executions = len(period_trades)

        net_result = realized_result + unrealized_result - fees - tax

        snapshots = self._portfolio_snapshot_repository.list_by_account(account_id)

        starting_equity: Optional[float] = None
        for snapshot in snapshots:
            if snapshot.timestamp <= start_timestamp:
                starting_equity = snapshot.equity
            else:
                break

        ending_equity: Optional[float] = None
        for snapshot in snapshots:
            if snapshot.timestamp <= end_timestamp:
                ending_equity = snapshot.equity
            else:
                break

        equity_curve: List[float] = [
            s.equity
            for s in snapshots
            if start_timestamp <= s.timestamp <= end_timestamp
        ]
        drawdown_result = self._maximum_drawdown_engine.calculate(equity_curve)

        timestamp = datetime.now(timezone.utc).isoformat()

        return self._daily_performance_repository.create(
            account_id=account_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            realized_result=realized_result,
            unrealized_result=unrealized_result,
            fees=fees,
            tax=tax,
            net_result=net_result,
            drawdown=drawdown_result.maximum_drawdown,
            number_of_executions=number_of_executions,
            timestamp=timestamp,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            number_of_signals=None,
        )
