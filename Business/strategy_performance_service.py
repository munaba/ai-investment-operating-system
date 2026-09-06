"""StrategyPerformanceService -- ACTIVATION 7 (performance per strategy).

Gives ``Business.strategy_performance_engine.StrategyPerformanceEngine``
and ``Business.position_episode_replay_engine.PositionEpisodeReplayEngine``
a real, account-scoped, database-backed production path. Neither
engine is changed by this service -- both are called through their
existing, unmodified public methods, exactly as
``Business.trade_attribution_service.TradeAttributionService``
(Activation 5.6) already does for ``TradeAttributionEngine``/
``TradeHoldingPeriodEngine``. This service only resolves each engine's
inputs from real, already-persisted data, then delegates.

Mirrors the ``TradeAttributionService`` precedent exactly: a thin,
read-only orchestrator over already-existing, already-LOCKED
collaborators. No new engine formula beyond what
``StrategyPerformanceEngine``/``PositionEpisodeReplayEngine`` already
own, no new abstraction, no new schema, no migration.

LOCKED definition this service implements (verbatim, per the
ACTIVATION 7 instruction):

    closed Position episode
        -> replay TradeHoldingPeriodEngine (via
           ``PositionEpisodeReplayEngine``)
        -> opening trade = the trade that opens the episode
        -> strategy of a trade: ``"recommendation_following"`` if
           ``Order.analysis_snapshot_id`` is present, else
           ``"manual"`` -- the exact same rule
           ``Business.trade_attribution_engine.TradeAttributionEngine``
           already applies per trade (this service reuses that
           engine's own ``STRATEGY_RECOMMENDATION_FOLLOWING``/
           ``STRATEGY_MANUAL`` string constants rather than
           redeclaring them)
        -> if every trade in the episode shares the same strategy,
           use that strategy for the episode
        -> if the episode's trades carry more than one strategy,
           the episode's strategy is ``"mixed"``
    P/L of the episode = the closed ``Position.realized_pnl`` that
        episode matches -- already-existing, never recomputed here
        (LOCKED: "Gunakan Position.realized_pnl sebagai P/L episode
        yang sudah existing").

Episode <-> Position matching (structural, not a new field on either
model): for a single ``account_id`` + ``symbol``, ``PositionManager``
only ever creates a NEW ``Position`` row when there is no currently
OPEN position for that pair (see ``Database.models.Position``'s own
docstring: "since a position can go OPEN -> ... -> CLOSED and later
reopen on a fresh BUY, which must become a new row rather than
reusing the old (closed) one"). That means, for one ``account_id`` +
``symbol``, the Nth closed episode reconstructed (in chronological
order) from the real ``Trade`` ledger and the Nth ``status="closed"``
``Position`` row (in ``position_id`` ascending order, i.e. creation
order) are the SAME real-world episode. This service relies on that
existing structural invariant -- it adds no new field, column, or
migration to make the match; it only zips the two already-ordered
lists together. If the two lists ever disagree in length (a database
inconsistency PositionManager's own invariant should prevent), this
service raises ``RepositoryError`` rather than silently mismatching
an episode to the wrong ``Position`` row.

Account isolation: every read goes through ``account_id``, via each
repository's own ``account_id``-filtered method (``list_by_account``).
A trade, order, or position belonging to any other account is never
included.

Read-only / observational (LOCKED): this service never creates,
updates, or cancels an ``Order``, ``Trade``, or ``Position``. It only
reads already-persisted state and returns computed (never persisted)
``StrategyPerformanceStatistics`` rows.

Explicitly out of scope for this Activation (LOCKED DECISION, per the
instruction): no market regime, no new metric beyond performance
aggregation per strategy, no change to ``Position``, ``Trade``/
``Order`` schema, fee formula, trading flow, decision table, or market
regime, no new migration.
"""

from __future__ import annotations

from typing import Dict, List

from Business.position_episode_replay_engine import (
    PositionEpisode,
    PositionEpisodeReplayEngine,
)
from Business.strategy_performance_engine import (
    EpisodeStrategyOutcome,
    StrategyPerformanceEngine,
    StrategyPerformanceStatistics,
)
from Business.trade_attribution_engine import (
    STRATEGY_MANUAL,
    STRATEGY_RECOMMENDATION_FOLLOWING,
)
from Core.exceptions import RepositoryError, ValidationError
from Database.models import Order
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.trade_repository import TradeRepository

#: LOCKED: an episode whose trades carry more than one strategy label
#: (per-trade rule below) is reported as this literal string -- not a
#: fabricated/default single strategy, and not silently dropped.
STRATEGY_MIXED = "mixed"

#: Status value ``PositionRepository``/``PositionManager`` already
#: write for a closed position (see ``Database.position_constants.
#: POSITION_STATUSES``). Kept as a local constant rather than
#: importing a private name, same convention every other engine/
#: service in this project already follows.
_POSITION_STATUS_CLOSED = "closed"


class StrategyPerformanceService:
    """Builds a per-strategy performance breakdown for a real
    ``account_id`` from real, already-persisted data.

    Depends only on already-existing, already-real repositories plus
    the two Activation 7 collaborators (see module docstring). Holds
    no reference to ``PaperTradingEngine`` or ``SnapshotRepository`` --
    there is no import of either here: this service never needs to
    confirm a ``RankingSnapshot`` still exists (unlike
    ``TradeAttributionService``'s ``signal`` dimension), it only needs
    ``Order.analysis_snapshot_id``'s presence/absence.
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        trade_repository: TradeRepository,
        order_repository: OrderRepository,
        position_repository: PositionRepository,
        position_episode_replay_engine: PositionEpisodeReplayEngine,
        strategy_performance_engine: StrategyPerformanceEngine,
    ) -> None:
        """Store the collaborators this service composes
        performance-per-strategy from.

        Args:
            account_repository: Used only to confirm the account
                exists. Never written to.
            trade_repository: Used to read this account's trades.
                Never written to.
            order_repository: Used to look up, per trade, the
                ``Order`` it filled (for ``analysis_snapshot_id``).
                Never written to.
            position_repository: Used to read this account's
                positions (for each closed episode's already-existing
                ``realized_pnl``). Never written to.
            position_episode_replay_engine: The Activation 7 episode
                reconstructor -- the sole place episode grouping is
                computed. Never reimplemented here.
            strategy_performance_engine: The Activation 7 aggregator --
                the sole place per-strategy statistics are computed.
                Never reimplemented here.
        """
        self._account_repository = account_repository
        self._trade_repository = trade_repository
        self._order_repository = order_repository
        self._position_repository = position_repository
        self._position_episode_replay_engine = position_episode_replay_engine
        self._strategy_performance_engine = strategy_performance_engine

    def get_performance_by_strategy(
        self, account_id: str
    ) -> Dict[str, StrategyPerformanceStatistics]:
        """Compute a :class:`StrategyPerformanceStatistics` per
        distinct strategy, over every CLOSED position episode of
        ``account_id``, from real, already-persisted data.

        Never creates, updates, or cancels anything -- purely
        observational, then in-memory engine calls. Nothing here is
        persisted.

        Args:
            account_id: The account to summarize. Every underlying
                read is scoped to this ``account_id`` -- no other
                account's trades, orders, or positions are ever
                included.

        Returns:
            A ``dict`` mapping each distinct strategy label
            (``"recommendation_following"``/``"manual"``/``"mixed"``)
            observed among ``account_id``'s closed episodes to its
            :class:`StrategyPerformanceStatistics`. Empty ``dict`` if
            ``account_id`` has zero closed episodes.

        Raises:
            ValidationError: If ``account_id`` does not exist.
            RepositoryError: If any underlying repository call fails,
                or if the number of closed episodes reconstructed from
                the ``Trade`` ledger for some symbol does not match
                the number of ``status="closed"`` ``Position`` rows
                for that same symbol (a database-consistency guard --
                see the module docstring's matching-invariant note).
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot build strategy performance: account {account_id} not found",
                details={"account_id": account_id},
            )

        trades = self._trade_repository.list_by_account(account_id)

        # Episode replay is a per-(account, symbol) concept -- group
        # this account's real trades by symbol (preserving each
        # symbol's own chronological trade_id-ascending order) before
        # handing each group to PositionEpisodeReplayEngine, exactly
        # as TradeHoldingPeriodEngine's own contract requires.
        trades_by_symbol: Dict[str, List] = {}
        for trade in trades:
            trades_by_symbol.setdefault(trade.symbol, []).append(trade)

        # Closed positions, grouped by symbol, in position_id
        # ascending (creation) order -- the same chronological order
        # PositionManager creates one new row per episode in (see
        # module docstring's matching-invariant note).
        closed_positions_by_symbol: Dict[str, List] = {}
        for position in self._position_repository.list_by_account(account_id):
            if position.status == _POSITION_STATUS_CLOSED:
                closed_positions_by_symbol.setdefault(position.symbol, []).append(position)

        order_cache: Dict[int, Order] = {}
        outcomes: List[EpisodeStrategyOutcome] = []

        for symbol, symbol_trades in trades_by_symbol.items():
            episodes = self._position_episode_replay_engine.replay(symbol_trades)
            closed_episodes = [episode for episode in episodes if episode.closed]
            closed_positions = closed_positions_by_symbol.get(symbol, [])

            if len(closed_episodes) != len(closed_positions):
                raise RepositoryError(
                    "Cannot build strategy performance: closed episode count "
                    f"({len(closed_episodes)}) does not match closed Position count "
                    f"({len(closed_positions)}) for account {account_id} symbol {symbol}",
                    details={
                        "account_id": account_id,
                        "symbol": symbol,
                        "closed_episodes": len(closed_episodes),
                        "closed_positions": len(closed_positions),
                    },
                )

            for episode, position in zip(closed_episodes, closed_positions):
                strategy = self._resolve_episode_strategy(episode, order_cache)
                outcomes.append(
                    EpisodeStrategyOutcome(
                        strategy=strategy, realized_pnl=position.realized_pnl
                    )
                )

        return self._strategy_performance_engine.calculate(outcomes)

    def _resolve_episode_strategy(
        self, episode: PositionEpisode, order_cache: Dict[int, Order]
    ) -> str:
        """Resolve one closed episode's strategy label, per the
        LOCKED rule in the module docstring.

        Computes the same ``"recommendation_following"``/``"manual"``
        rule ``TradeAttributionEngine`` already applies, for every
        trade in ``episode`` (not only its ``opening_trade``) -- if
        they all agree, that shared value (which is, by construction,
        always the ``opening_trade``'s own strategy whenever the
        episode is single-strategy) is the episode's strategy;
        otherwise the episode's strategy is ``STRATEGY_MIXED``.

        Args:
            episode: The closed :class:`PositionEpisode` to resolve.
            order_cache: Mutated in place -- caches ``Order`` lookups
                across every episode this service resolves in one
                ``get_performance_by_strategy`` call, mirroring
                ``TradeAttributionService``'s own ``order_cache``
                pattern.

        Returns:
            ``STRATEGY_RECOMMENDATION_FOLLOWING``, ``STRATEGY_MANUAL``,
            or ``STRATEGY_MIXED``.

        Raises:
            RepositoryError: If a trade's ``order_id`` does not
                resolve to a real ``Order`` row (a NOT NULL foreign
                key violation the schema should already prevent --
                never silently treated as "manual").
        """
        strategies_observed = set()

        for trade in episode.trades:
            order = order_cache.get(trade.order_id)
            if order is None:
                order = self._order_repository.get_by_id(trade.order_id)
                if order is None:
                    raise RepositoryError(
                        "Cannot build strategy performance: trade "
                        f"{trade.trade_id} references missing order {trade.order_id}",
                        details={"trade_id": trade.trade_id, "order_id": trade.order_id},
                    )
                order_cache[trade.order_id] = order

            strategies_observed.add(
                STRATEGY_RECOMMENDATION_FOLLOWING
                if order.analysis_snapshot_id is not None
                else STRATEGY_MANUAL
            )

            if len(strategies_observed) > 1:
                return STRATEGY_MIXED

        return next(iter(strategies_observed))