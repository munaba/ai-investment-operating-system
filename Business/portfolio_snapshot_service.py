"""PortfolioSnapshotService -- Activation 5.2.

Composes an already-real, already-verified picture of one ``Account``'s
portfolio state into a single :class:`Database.models.PortfolioSnapshot`
row and persists it via ``PortfolioSnapshotRepository``. This module
computes nothing that isn't already backed by an existing, real
source -- see the field-by-field rationale below and in
``Database.models.PortfolioSnapshot``.

Read-only / observational toward trading state (LOCKED, Activation
5.2 rule 18): this service never creates, updates, or cancels an
``Order`` or a ``Trade``, never calls ``PaperTradingEngine``, and
never mutates ``Account`` or ``Position`` in any way. It only reads
already-persisted state and writes one new, additional
``PortfolioSnapshot`` row.

No scheduler, no background worker, no daemon (LOCKED, Activation 5.2
rule 17): ``take_snapshot()`` is an ordinary, synchronous method a
caller invokes explicitly -- nothing here schedules, loops, sleeps, or
runs itself.

Field sources (each already real, never fabricated):

* ``cash`` -- ``Account.cash``, read via ``AccountRepository.get_by_id``.
* ``market_value`` / ``unrealized_pnl`` -- summed across this
  account's OPEN positions using the existing, LOCKED
  ``Business.unrealized_pnl_engine.UnrealizedPnLEngine`` (the sole
  business owner of unrealized P/L, per its own module docstring).
  This service never computes ``(market_price - average_price) *
  quantity`` itself -- it only sums ``UnrealizedPnLEngine.calculate()``
  results. ``market_value`` for one position is
  ``result.market_price * result.quantity`` -- ``market_price`` comes
  straight from ``UnrealizedPnLEngine``'s own real ``MarketPriceTool``
  call, never a second/parallel price lookup.
* ``realized_pnl`` -- summed across every ``Position`` row (open and
  closed) for this account, straight off ``Position.realized_pnl``
  (Sprint 4's cumulative-per-row field -- see
  ``Database.models.Position``/``Business.position_manager``).
* ``equity`` -- ``cash + market_value``. Deliberately NOT
  ``Account.equity``: that field is explicitly documented, in
  ``Business.account_balance_service``, as "portfolio valuation,
  reserved for a future STEP" and is only ever passed through
  unchanged, never recomputed by anything in this codebase today --
  reading it here would silently persist a stale/never-computed
  value, which Activation 5.2 rule 13 forbids treating as real.
* ``exposure`` -- always ``None`` at this Activation. NOT VERIFIABLE
  / GAP -- see ``Database.migrations_portfolio_snapshots`` module
  docstring for the full audit finding (no existing, already-computed
  total-portfolio exposure source exists in the codebase;
  ``Orchestration.portfolio_engine.PortfolioEngine.exposure`` is a
  different, per-signal concept and is never imported here).
* ``drawdown`` -- computed by the existing, LOCKED
  ``Business.maximum_drawdown_engine.MaximumDrawdownEngine`` over this
  account's real, already-persisted prior ``PortfolioSnapshot.equity``
  values (chronological, via ``PortfolioSnapshotRepository.
  list_by_account``) plus this snapshot's own just-computed ``equity``
  as the final point. This service never reimplements the
  peak/drawdown formula itself.
* ``timestamp`` -- ``datetime.now(timezone.utc).isoformat()``, the
  real instant this method composed the snapshot -- the same pattern
  already used for ``Account``/``Position``/``Order`` ``created_at``/
  ``updated_at`` and ``UnrealizedPnLEngine.market_timestamp``.
* ``valuation_status`` -- Phase G Task 3 addition. ``None`` unless the
  injected ``UnrealizedPnLEngine`` has freshness tracking enabled (see
  that engine's own module docstring), in which case it is ``"STALE"``
  if any open position's market price had to fall back to a retained
  last-good observation, else ``"FRESH"``. This service never
  fabricates this label -- it is purely a portfolio-level summary of
  the per-position ``valuation_status`` values ``UnrealizedPnLEngine``
  already computed. An UNAVAILABLE valuation (no live price and no
  durable last-good observation for some position) is never persisted
  as part of a snapshot at all -- ``UnrealizedPnLEngine.calculate()``
  raises ``ValidationError`` in that case, which propagates out of
  ``take_snapshot()`` unchanged, exactly like the pre-Phase-G-Task-3
  "missing price fails the whole snapshot" contract.

Dependencies (LOCKED, all pre-existing components -- no new engine is
constructed by this Activation): ``AccountRepository``,
``PositionRepository``, ``UnrealizedPnLEngine``,
``MaximumDrawdownEngine``, ``PortfolioSnapshotRepository``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from Business.maximum_drawdown_engine import MaximumDrawdownEngine
from Business.unrealized_pnl_engine import UnrealizedPnLEngine
from Core.exceptions import ValidationError
from Database.models import PortfolioSnapshot
from Database.position_constants import POSITION_STATUSES
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository
from Repository.persistence.position_repository import PositionRepository

_OPEN_STATUS = "open"
assert _OPEN_STATUS in POSITION_STATUSES  # guards against POSITION_STATUSES drifting


@dataclass
class EquityCurvePoint:
    """One point of a production equity curve (Activation 5.4).

    Exactly two fields -- no drawdown, no derived return, no gap-fill
    of any kind -- both taken verbatim from a real, already-persisted
    :class:`Database.models.PortfolioSnapshot` row.

    Attributes:
        timestamp: ``PortfolioSnapshot.timestamp`` verbatim.
        equity: ``PortfolioSnapshot.equity`` verbatim.
    """

    timestamp: str
    equity: float


class PortfolioSnapshotService:
    """Builds and persists one :class:`PortfolioSnapshot` for a given
    ``account_id``, on demand.

    Depends only on already-existing, already-real components (see
    module docstring). Holds no reference to ``PaperTradingEngine``,
    ``OrderRepository``, ``TradeRepository``, or any other component
    capable of creating an ``Order``/``Trade`` -- there is no import
    of any of those here, enforcing the read-only/observational
    boundary structurally, not just by convention.
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        position_repository: PositionRepository,
        unrealized_pnl_engine: UnrealizedPnLEngine,
        maximum_drawdown_engine: MaximumDrawdownEngine,
        portfolio_snapshot_repository: PortfolioSnapshotRepository,
    ) -> None:
        """Store the collaborators this service composes a snapshot from.

        Args:
            account_repository: Used to read the account's current
                ``cash`` (and to confirm the account exists). Never
                written to.
            position_repository: Used to read this account's
                positions (open, for ``market_value``/
                ``unrealized_pnl``; all, for ``realized_pnl``). Never
                written to.
            unrealized_pnl_engine: The existing, LOCKED sole owner of
                unrealized P/L computation. Never reimplemented here.
            maximum_drawdown_engine: The existing, LOCKED drawdown
                formula. Never reimplemented here.
            portfolio_snapshot_repository: Used to persist the
                composed snapshot. The only repository this service
                ever writes through.
        """
        self._account_repository = account_repository
        self._position_repository = position_repository
        self._unrealized_pnl_engine = unrealized_pnl_engine
        self._maximum_drawdown_engine = maximum_drawdown_engine
        self._portfolio_snapshot_repository = portfolio_snapshot_repository

    def take_snapshot(self, account_id: str) -> PortfolioSnapshot:
        """Compose and persist one portfolio snapshot for ``account_id``.

        Never creates, updates, or cancels an ``Order`` or ``Trade``,
        and never mutates ``Account``/``Position`` -- purely
        observational, then a single ``INSERT`` via
        ``PortfolioSnapshotRepository.create``.

        Args:
            account_id: The account to snapshot.

        Returns:
            The newly persisted :class:`Database.models.PortfolioSnapshot`.

        Raises:
            ValidationError: If ``account_id`` does not exist, or if
                ``UnrealizedPnLEngine`` cannot resolve a real market
                price for one of this account's open positions (this
                service never fabricates a market value/unrealized
                P/L from a missing price -- the whole snapshot fails
                rather than persist a partly-invented number).
            RepositoryError: If any underlying repository call fails.
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot take portfolio snapshot: account {account_id} not found",
                details={"account_id": account_id},
            )

        all_positions = self._position_repository.list_by_account(account_id)
        open_positions = [p for p in all_positions if p.status == _OPEN_STATUS]

        market_value = 0.0
        unrealized_pnl = 0.0
        valuation_statuses = []
        for position in open_positions:
            result = self._unrealized_pnl_engine.calculate(position)
            market_value += result.market_price * result.quantity
            unrealized_pnl += result.unrealized_pnl
            if result.valuation_status is not None:
                valuation_statuses.append(result.valuation_status)

        # Phase G Task 3: portfolio-level valuation freshness summary.
        # Only meaningful when the injected UnrealizedPnLEngine has
        # freshness tracking enabled (see that engine's module
        # docstring) -- every open position then reports a non-None
        # ``valuation_status``. ``None`` here (unchanged from the
        # pre-Phase-G-Task-3 default) when freshness tracking is
        # disabled, or when there are no open positions to report on.
        # "STALE" wins over "FRESH" whenever any single position had
        # to fall back to a retained last-good price -- a portfolio
        # review must not report the whole snapshot as trustworthy
        # when even one input to it was not.
        if not valuation_statuses:
            valuation_status = None
        elif any(status == "STALE" for status in valuation_statuses):
            valuation_status = "STALE"
        else:
            valuation_status = "FRESH"

        realized_pnl = sum(p.realized_pnl for p in all_positions)

        cash = account.cash
        equity = cash + market_value

        prior_snapshots = self._portfolio_snapshot_repository.list_by_account(account_id)
        equity_curve: List[float] = [s.equity for s in prior_snapshots] + [equity]
        drawdown_result = self._maximum_drawdown_engine.calculate(equity_curve)

        timestamp = datetime.now(timezone.utc).isoformat()

        return self._portfolio_snapshot_repository.create(
            account_id=account_id,
            cash=cash,
            market_value=market_value,
            equity=equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            drawdown=drawdown_result.maximum_drawdown,
            timestamp=timestamp,
            exposure=None,
            valuation_status=valuation_status,
        )

    def get_equity_curve(
        self,
        account_id: str,
        *,
        start_timestamp: Optional[str] = None,
        end_timestamp: Optional[str] = None,
    ) -> List[EquityCurvePoint]:
        """Build ``account_id``'s equity curve from real, already-
        persisted ``PortfolioSnapshot`` rows (Activation 5.4).

        Purely observational, like ``take_snapshot()``: reads via
        ``PortfolioSnapshotRepository.list_by_account_for_equity_curve``
        only -- never creates, updates, or cancels an ``Order``,
        ``Trade``, or ``PortfolioSnapshot``, and never mutates
        ``Account``/``Position``.

        Args:
            account_id: The account to build the curve for. A
                snapshot belonging to any other account is never
                included (enforced by the repository's ``account_id``
                filter).
            start_timestamp: Optional ISO-8601 inclusive lower bound,
                passed unchanged to
                ``PortfolioSnapshotRepository.list_by_account_for_equity_curve``.
            end_timestamp: Optional ISO-8601 inclusive upper bound,
                passed unchanged to
                ``PortfolioSnapshotRepository.list_by_account_for_equity_curve``.

        Returns:
            A list of :class:`EquityCurvePoint`, ordered ``timestamp
            ASC`` (``snapshot_id ASC`` tie-break) -- exactly the
            repository's own ordering, never re-sorted here. Empty
            list -- never a synthetic ``0.0`` point -- if
            ``account_id`` has no snapshot (in range, when a range is
            supplied). Feed ``[point.equity for point in curve]``
            straight into ``MaximumDrawdownEngine.calculate()``
            unchanged if a drawdown figure is also needed -- this
            method never reimplements that formula.

        Raises:
            ValidationError: If ``account_id`` does not exist.
            RepositoryError: If the underlying repository call fails.
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot build equity curve: account {account_id} not found",
                details={"account_id": account_id},
            )

        snapshots = self._portfolio_snapshot_repository.list_by_account_for_equity_curve(
            account_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        return [
            EquityCurvePoint(timestamp=s.timestamp, equity=s.equity)
            for s in snapshots
        ]