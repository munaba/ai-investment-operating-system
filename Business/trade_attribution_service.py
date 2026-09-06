"""TradeAttributionService -- Activation 5.6.

Gives :class:`Business.trade_attribution_engine.TradeAttributionEngine`
and :class:`Business.trade_holding_period_engine.TradeHoldingPeriodEngine`
a real, account-scoped, database-backed production path. Neither
engine is changed by this service -- both are called through their
existing, unmodified public methods, exactly as
``Business.performance_summary_production_service.
PerformanceSummaryProductionService`` (Activation 5.5) already does
for ``PerformanceSummaryService``. This service only resolves each
engine's inputs from real, already-persisted data, then delegates.

Mirrors the ``PerformanceSummaryProductionService`` precedent exactly:
a thin, read-only orchestrator over already-existing, already-LOCKED
collaborators. No new engine, no new formula, no new abstraction, no
new schema.

Field sources (each already real, never fabricated):

* ``trades`` -- ``TradeRepository.list_by_account(account_id)``, the
  same real, chronological (``trade_id`` ascending, which mirrors
  insertion/``executed_at`` order since trades are only ever appended)
  ledger every other Activation 5.x reporting component reads.
* ``market`` -- ``Account.asset_class``, read once via
  ``AccountRepository.get_by_id(account_id)``.
* ``signal_snapshot_id`` -- resolved in two steps: first
  ``Order.analysis_snapshot_id`` (via ``OrderRepository.
  get_by_id(trade.order_id)``), then, if not ``None``, a REAL
  ``SnapshotRepository.get_by_id()`` lookup to confirm that id still
  points at an existing ``RankingSnapshot`` row. An
  ``analysis_snapshot_id`` that no longer resolves (e.g. a since-
  deleted or never-existing row) resolves to ``None`` here -- this
  service never blindly echoes the raw id without confirming it
  actually resolves, which is the literal Activation 5.6 requirement
  (\"Signal harus di-resolve melalui Order.analysis_snapshot_id\").
* ``holding_period_seconds`` -- ``TradeHoldingPeriodEngine.calculate()``,
  called once per (``account_id``, ``symbol``) group of this
  account's real trades, in chronological order.

Account isolation: every read goes through ``account_id``, via each
repository's own ``account_id``-filtered method
(``list_by_account``/``get_by_id``). A trade, order, or snapshot
belonging to any other account is never included (an ``Order`` is
looked up by ``trade.order_id`` only after that ``Trade`` was already
returned by the ``account_id``-filtered ``list_by_account`` call, so
it is structurally impossible for a cross-account order to leak in).

Read-only / observational (LOCKED, mirrors Activation 5.5's own
rule): this service never creates, updates, or cancels an ``Order``,
``Trade``, ``Position``, or ``RankingSnapshot``. It only reads
already-persisted state and returns computed (never persisted)
``TradeAttribution`` rows.

Failure is never swallowed: if ``account_id`` does not exist, this
service raises ``ValidationError`` -- it never substitutes an empty
attribution list for a real failure. Any underlying repository
failure propagates unchanged.

Dependencies (LOCKED, all pre-existing components plus the two new
Activation 5.6 engines -- no new repository is constructed by this
service beyond what already exists): ``AccountRepository``,
``TradeRepository``, ``OrderRepository``, ``SnapshotRepository``,
``TradeAttributionEngine``, ``TradeHoldingPeriodEngine``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from Business.trade_attribution_engine import TradeAttribution, TradeAttributionEngine
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine
from Core.exceptions import RepositoryError, ValidationError
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.snapshot_repository import SnapshotRepository
from Repository.persistence.trade_repository import TradeRepository

#: Maps each of the Activation 5.6 roadmap's five grouping dimension
#: names to the actual :class:`TradeAttribution` attribute that
#: backs it. ``"signal"``/``"holding_period"`` are spelled slightly
#: differently on the dataclass itself (``signal_snapshot_id``/
#: ``holding_period_seconds``) to stay unambiguous about what they
#: actually hold -- this map is the single place that reconciles the
#: roadmap's five short names with those real field names.
GROUPING_DIMENSIONS: Dict[str, str] = {
    "strategy": "strategy",
    "market": "market",
    "signal": "signal_snapshot_id",
    "holding_period": "holding_period_seconds",
    "risk_category": "risk_category",
}


def group_trade_attributions(
    attributions: List[TradeAttribution], dimension: str
) -> Dict[Any, List[TradeAttribution]]:
    """Group already-computed ``attributions`` by one of the five
    Activation 5.6 dimensions.

    Pure, read-only grouping -- no recomputation of any
    :class:`TradeAttribution` field, no filtering, no sorting beyond
    the grouping itself (insertion order within each group mirrors
    ``attributions``' own order).

    Args:
        attributions: The list to group, as returned by
            ``TradeAttributionService.get_attribution``.
        dimension: One of ``"strategy"``, ``"market"``, ``"signal"``,
            ``"holding_period"``, ``"risk_category"`` -- the five
            Activation 5.6 roadmap dimensions (see
            :data:`GROUPING_DIMENSIONS`).

    Returns:
        A ``dict`` mapping each distinct value observed for that
        dimension to the list of :class:`TradeAttribution` rows
        sharing it, in ``attributions``' original relative order.

    Raises:
        ValueError: If ``dimension`` is not one of the five LOCKED
            dimension names.
    """
    field_name = GROUPING_DIMENSIONS.get(dimension)
    if field_name is None:
        raise ValueError(
            f"Unknown attribution dimension {dimension!r}; expected one of "
            f"{sorted(GROUPING_DIMENSIONS)}"
        )

    groups: Dict[Any, List[TradeAttribution]] = {}
    for attribution in attributions:
        key = getattr(attribution, field_name)
        groups.setdefault(key, []).append(attribution)
    return groups


class TradeAttributionService:
    """Builds a ``List[TradeAttribution]`` for a real ``account_id``
    from real, already-persisted data.

    Depends only on already-existing, already-real repositories plus
    the two new Activation 5.6 engines (see module docstring). Holds
    no reference to ``PaperTradingEngine``, ``PositionRepository``,
    or ``PositionManager`` -- there is no import of any of them here,
    enforcing the read-only/observational boundary structurally (this
    service never needs ``Position`` at all: holding period is
    reconstructed purely from the immutable ``Trade`` ledger by
    ``TradeHoldingPeriodEngine``, and every other dimension comes from
    ``Trade``/``Order``/``Account``/``RankingSnapshot``).
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        trade_repository: TradeRepository,
        order_repository: OrderRepository,
        snapshot_repository: SnapshotRepository,
        trade_attribution_engine: TradeAttributionEngine,
        trade_holding_period_engine: TradeHoldingPeriodEngine,
    ) -> None:
        """Store the collaborators this service composes attribution
        from.

        Args:
            account_repository: Used only to confirm the account
                exists and to read its ``asset_class`` (``market``).
                Never written to.
            trade_repository: Used to read this account's trades.
                Never written to.
            order_repository: Used to look up, per trade, the
                ``Order`` it filled (for ``analysis_snapshot_id``).
                Never written to.
            snapshot_repository: Used to confirm a resolved
                ``analysis_snapshot_id`` still points at a real
                ``RankingSnapshot`` row. Never written to.
            trade_attribution_engine: The existing, LOCKED per-trade
                assembler -- the sole place the five dimensions are
                combined. Never reimplemented here.
            trade_holding_period_engine: The existing, LOCKED episode
                reconstructor -- the sole place holding period is
                computed. Never reimplemented here.
        """
        self._account_repository = account_repository
        self._trade_repository = trade_repository
        self._order_repository = order_repository
        self._snapshot_repository = snapshot_repository
        self._trade_attribution_engine = trade_attribution_engine
        self._trade_holding_period_engine = trade_holding_period_engine

    def get_attribution(self, account_id: str) -> List[TradeAttribution]:
        """Compute a :class:`TradeAttribution` for every trade of
        ``account_id``, from real, already-persisted data.

        Never creates, updates, or cancels anything -- purely
        observational, then in-memory engine calls. Nothing here is
        persisted.

        Args:
            account_id: The account to attribute. Every underlying
                read is scoped to this ``account_id`` -- no other
                account's trades, orders, or snapshots are ever
                included.

        Returns:
            One :class:`TradeAttribution` per real ``Trade`` row for
            ``account_id``, in the same order
            ``TradeRepository.list_by_account`` returns them
            (``trade_id`` ascending).

        Raises:
            ValidationError: If ``account_id`` does not exist.
            RepositoryError: If any underlying repository call fails.
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot build trade attribution: account {account_id} not found",
                details={"account_id": account_id},
            )

        trades = self._trade_repository.list_by_account(account_id)

        # Holding period is a per-(account, symbol) episode concept --
        # group this account's real trades by symbol (preserving each
        # symbol's own chronological trade_id-ascending order) before
        # handing each group to TradeHoldingPeriodEngine, exactly as
        # its own contract requires.
        trades_by_symbol: Dict[str, List] = {}
        for trade in trades:
            trades_by_symbol.setdefault(trade.symbol, []).append(trade)

        holding_periods: Dict[int, Any] = {}
        for symbol_trades in trades_by_symbol.values():
            holding_periods.update(
                self._trade_holding_period_engine.calculate(symbol_trades)
            )

        order_cache: Dict[int, Any] = {}
        snapshot_exists_cache: Dict[int, bool] = {}
        attributions: List[TradeAttribution] = []

        for trade in trades:
            order = order_cache.get(trade.order_id)
            if order is None:
                order = self._order_repository.get_by_id(trade.order_id)
                if order is None:
                    # trades.order_id carries a NOT NULL foreign key
                    # to orders.order_id (see Database.migrations_trades),
                    # so this can only happen if the database itself is
                    # inconsistent -- never silently attributed as
                    # "manual", always a hard failure.
                    raise RepositoryError(
                        f"Cannot build trade attribution: trade {trade.trade_id} "
                        f"references missing order {trade.order_id}",
                        details={"trade_id": trade.trade_id, "order_id": trade.order_id},
                    )
                order_cache[trade.order_id] = order

            signal_snapshot_id = None
            if order is not None and order.analysis_snapshot_id is not None:
                candidate_id = order.analysis_snapshot_id
                if candidate_id not in snapshot_exists_cache:
                    snapshot = self._snapshot_repository.get_by_id(candidate_id)
                    snapshot_exists_cache[candidate_id] = snapshot is not None
                if snapshot_exists_cache[candidate_id]:
                    signal_snapshot_id = candidate_id

            attribution = self._trade_attribution_engine.calculate(
                trade=trade,
                order=order,
                market=account.asset_class,
                signal_snapshot_id=signal_snapshot_id,
                holding_period_seconds=holding_periods.get(trade.trade_id),
            )
            attributions.append(attribution)

        return attributions

    def get_attribution_grouped(
        self, account_id: str, dimension: str
    ) -> Dict[Any, List[TradeAttribution]]:
        """Convenience wrapper: ``get_attribution`` followed by
        ``group_trade_attributions``.

        Args:
            account_id: Passed unchanged to ``get_attribution``.
            dimension: Passed unchanged to
                ``group_trade_attributions`` -- one of ``"strategy"``,
                ``"market"``, ``"signal"``, ``"holding_period"``,
                ``"risk_category"``.

        Returns:
            The grouped ``dict`` ``group_trade_attributions`` returns.

        Raises:
            ValidationError: If ``account_id`` does not exist.
            ValueError: If ``dimension`` is not one of the five LOCKED
                dimension names.
            RepositoryError: If any underlying repository call fails.
        """
        attributions = self.get_attribution(account_id)
        return group_trade_attributions(attributions, dimension)
