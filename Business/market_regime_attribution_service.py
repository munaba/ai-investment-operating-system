"""MarketRegimeAttributionService -- ACTIVATION 7 (performance per
market regime / market-condition variety).

Gives ``Business.market_regime_performance_engine.
MarketRegimePerformanceEngine`` a real, account-scoped,
database-and-real-OHLCV-backed production path, and separately
exposes real, currently-observed market-condition variety. Mirrors
``Business.strategy_performance_service.StrategyPerformanceService``'s
own shape closely (same episode reconstruction, same closed-episode /
closed-Position count-matching invariant/guard) -- the one difference
is what each closed episode is grouped by: here, the real market
regime observed at the moment the episode opened, resolved via
``Business.market_regime_service.MarketRegimeService`` (real OHLCV,
deterministically recomputed, never persisted -- see that module's
docstring for the full persistence-vs-recovery rationale).

Regime-per-episode rule (LOCKED, documented here): an episode's
regime is the regime of its ``opening_trade`` alone (real symbol,
real ``executed_at`` timestamp, real OHLCV as of that moment) -- NOT
an aggregate/"mixed" label across every trade in the episode. This is
a deliberate, narrower choice than
``StrategyPerformanceService``'s "mixed" strategy rule: strategy is a
per-trade *decision* (recommendation-following vs. manual) that can
legitimately differ trade-to-trade within one episode, whereas market
regime is a property of *when the position was opened* -- the single
moment that actually determined the market condition the strategy was
validated against for that episode. Re-classifying at every
subsequent trade inside the same still-open episode would not change
which regime the roadmap's "performance per market regime" gate cares
about (the condition the entry decision was made in), and would only
multiply real-data (OHLCV) fetches for no additional evidence value.

Explicitly out of scope for this addition: no change to
``Position``/``Trade``/``Order`` schema, no new migration, no new
table, no change to fee formula, trading flow, decision table,
recommendation logic, ranking logic, paper approval flow, notification
flow, or live execution.
"""

from __future__ import annotations

from typing import Dict, List

from Business.market_regime_engine import STATUS_CLASSIFIED, STATUS_INSUFFICIENT_DATA
from Business.market_regime_performance_engine import (
    EpisodeRegimeOutcome,
    MarketRegimePerformanceEngine,
    MarketRegimePerformanceStatistics,
)
from Business.market_regime_service import MarketRegimeService
from Business.position_episode_replay_engine import PositionEpisodeReplayEngine
from Core.exceptions import RepositoryError, ValidationError
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.trade_repository import TradeRepository
from Repository.persistence.watchlist_repository import WatchlistRepository

#: Label used for a closed episode whose opening-trade regime could
#: not be classified from real data (see
#: ``Business.market_regime_engine.STATUS_INSUFFICIENT_DATA``) --
#: reported as its own explicit group, never silently dropped and
#: never guessed into "trending"/"ranging"/"volatile".
REGIME_INSUFFICIENT_DATA = STATUS_INSUFFICIENT_DATA

#: Status value ``PositionRepository``/``PositionManager`` already
#: write for a closed position (mirrors the same local constant in
#: ``Business.strategy_performance_service``).
_POSITION_STATUS_CLOSED = "closed"


class MarketRegimeAttributionService:
    """Builds a per-market-regime performance breakdown for a real
    ``account_id``, and reports real, currently-observed
    market-condition variety, from real, already-persisted data plus
    real OHLCV history.

    Depends only on already-existing, already-real repositories, the
    Activation 7 episode reconstructor
    (``PositionEpisodeReplayEngine``, reused as-is -- never a second
    instance/reimplementation), and the two new-this-session
    collaborators (``MarketRegimeService``,
    ``MarketRegimePerformanceEngine``).
    """

    def __init__(
        self,
        account_repository: AccountRepository,
        trade_repository: TradeRepository,
        position_repository: PositionRepository,
        watchlist_repository: WatchlistRepository,
        position_episode_replay_engine: PositionEpisodeReplayEngine,
        market_regime_service: MarketRegimeService,
        market_regime_performance_engine: MarketRegimePerformanceEngine,
    ) -> None:
        """Store the collaborators this service composes performance
        per market regime from.

        Args:
            account_repository: Used only to confirm the account
                exists. Never written to.
            trade_repository: Used to read this account's trades.
                Never written to.
            position_repository: Used to read this account's
                positions (for each closed episode's already-existing
                ``realized_pnl``). Never written to.
            watchlist_repository: Used only by
                ``get_market_condition_variety`` to read the real,
                currently-tracked symbol list. Never written to.
            position_episode_replay_engine: The existing, LOCKED
                Activation 7 episode reconstructor -- the sole place
                episode grouping is computed. Never reimplemented
                here.
            market_regime_service: Resolves one symbol's real,
                deterministic market-regime classification from real
                OHLCV history. Never reimplemented here.
            market_regime_performance_engine: The pure aggregator --
                the sole place per-regime statistics are computed.
                Never reimplemented here.
        """
        self._account_repository = account_repository
        self._trade_repository = trade_repository
        self._position_repository = position_repository
        self._watchlist_repository = watchlist_repository
        self._position_episode_replay_engine = position_episode_replay_engine
        self._market_regime_service = market_regime_service
        self._market_regime_performance_engine = market_regime_performance_engine

    def get_performance_by_regime(
        self, account_id: str
    ) -> Dict[str, MarketRegimePerformanceStatistics]:
        """Compute a :class:`MarketRegimePerformanceStatistics` per
        distinct market regime, over every CLOSED position episode of
        ``account_id``, from real, already-persisted trades/positions
        plus real OHLCV history.

        Never creates, updates, or cancels anything -- purely
        observational, then in-memory engine calls. Nothing here is
        persisted.

        Args:
            account_id: The account to summarize. Every underlying
                read is scoped to this ``account_id`` -- no other
                account's trades or positions are ever included.

        Returns:
            A ``dict`` mapping each distinct regime label observed
            among ``account_id``'s closed episodes (including
            ``REGIME_INSUFFICIENT_DATA`` when real OHLCV history was
            not sufficient for a given episode's opening moment) to
            its :class:`MarketRegimePerformanceStatistics`. Empty
            ``dict`` if ``account_id`` has zero closed episodes.

        Raises:
            ValidationError: If ``account_id`` does not exist.
            RepositoryError: If the number of closed episodes
                reconstructed from the ``Trade`` ledger for some
                symbol does not match the number of ``status="closed"``
                ``Position`` rows for that same symbol -- mirrors
                ``StrategyPerformanceService``'s own consistency
                guard exactly.
        """
        account = self._account_repository.get_by_id(account_id)
        if account is None:
            raise ValidationError(
                f"Cannot build market regime performance: account {account_id} not found",
                details={"account_id": account_id},
            )

        trades = self._trade_repository.list_by_account(account_id)

        trades_by_symbol: Dict[str, List] = {}
        for trade in trades:
            trades_by_symbol.setdefault(trade.symbol, []).append(trade)

        closed_positions_by_symbol: Dict[str, List] = {}
        for position in self._position_repository.list_by_account(account_id):
            if position.status == _POSITION_STATUS_CLOSED:
                closed_positions_by_symbol.setdefault(position.symbol, []).append(position)

        outcomes: List[EpisodeRegimeOutcome] = []

        for symbol, symbol_trades in trades_by_symbol.items():
            episodes = self._position_episode_replay_engine.replay(symbol_trades)
            closed_episodes = [episode for episode in episodes if episode.closed]
            closed_positions = closed_positions_by_symbol.get(symbol, [])

            if len(closed_episodes) != len(closed_positions):
                raise RepositoryError(
                    "Cannot build market regime performance: closed episode count "
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
                regime = self._resolve_episode_regime(episode)
                outcomes.append(
                    EpisodeRegimeOutcome(regime=regime, realized_pnl=position.realized_pnl)
                )

        return self._market_regime_performance_engine.calculate(outcomes)

    def get_market_condition_variety(self) -> Dict[str, object]:
        """Report real, currently-observed market-condition variety
        across the real, currently-tracked watchlist.

        Classifies every symbol on ``WatchlistRepository.list_all()``
        "as of now" (no ``as_of`` bound), via the exact same
        ``MarketRegimeService.classify_symbol_regime`` this service's
        episode attribution uses. Purely observational -- no write,
        no scan-pipeline call, no recommendation/ranking logic
        touched.

        Returns:
            A ``dict`` with:

            * ``"observed_regimes"``: sorted ``list`` of distinct
              regime labels actually classified (excludes
              ``REGIME_INSUFFICIENT_DATA`` -- that is not a real
              market condition, it is an absence of data).
            * ``"regime_count"``: ``len(observed_regimes)`` -- the
              roadmap's "variasi kondisi pasar" (market-condition
              variety) number.
            * ``"symbols_classified"``: count of watchlist symbols
              that were successfully classified.
            * ``"symbols_insufficient_data"``: count of watchlist
              symbols real OHLCV history was not sufficient for.
            * ``"per_symbol"``: ``dict`` mapping each watchlist symbol
              to its classified regime label (or
              ``REGIME_INSUFFICIENT_DATA``) -- the real, per-symbol
              evidence backing the two counts above, never
              summarized away.

            Every value here is derived from a real
            ``MarketRegimeService`` call over the real, current
            watchlist -- nothing is fabricated, and an empty
            watchlist honestly produces all-zero counts rather than a
            guessed variety.
        """
        symbols = self._watchlist_repository.list_all()

        per_symbol: Dict[str, str] = {}
        observed_regimes = set()
        symbols_classified = 0
        symbols_insufficient_data = 0

        for symbol in symbols:
            classification = self._market_regime_service.classify_symbol_regime(symbol)
            if classification.status == STATUS_CLASSIFIED:
                per_symbol[symbol] = classification.regime
                observed_regimes.add(classification.regime)
                symbols_classified += 1
            else:
                per_symbol[symbol] = REGIME_INSUFFICIENT_DATA
                symbols_insufficient_data += 1

        return {
            "observed_regimes": sorted(observed_regimes),
            "regime_count": len(observed_regimes),
            "symbols_classified": symbols_classified,
            "symbols_insufficient_data": symbols_insufficient_data,
            "per_symbol": per_symbol,
        }

    def _resolve_episode_regime(self, episode) -> str:
        """Resolve one closed episode's regime label, per the LOCKED
        rule in the module docstring: the real market regime observed
        at ``episode.opening_trade``'s real ``symbol``/``executed_at``.

        Args:
            episode: The closed ``PositionEpisode`` to resolve.

        Returns:
            ``"trending"``/``"ranging"``/``"volatile"``, or
            ``REGIME_INSUFFICIENT_DATA`` when real OHLCV history was
            not sufficient to classify this episode's opening moment.
        """
        opening_trade = episode.opening_trade
        classification = self._market_regime_service.classify_symbol_regime(
            opening_trade.symbol, as_of=opening_trade.executed_at
        )
        if classification.status == STATUS_CLASSIFIED:
            return classification.regime
        return REGIME_INSUFFICIENT_DATA