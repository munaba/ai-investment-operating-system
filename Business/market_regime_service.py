"""MarketRegimeService -- ACTIVATION 7 (performance per market regime).

Thin orchestrator that gives ``Business.market_regime_engine.
MarketRegimeEngine`` a real, symbol-scoped production path over real
OHLCV history already available through
``Repository.external.stock_data_repository.StockDataRepository``
(``yfinance``) -- the exact repository the ACTIVATION 7 instruction
named. Mirrors ``Business.strategy_performance_service.
StrategyPerformanceService``'s own "thin service delegates to a pure
engine" shape: no new formula lives here, only real-data resolution
plus one delegated ``MarketRegimeEngine.classify()`` call.

Persistence decision (LOCKED for this addition, documented here
rather than silently assumed): regime is NEVER persisted to a new
column or a new table. Per the ACTIVATION 7 instruction ("Persist OR
deterministically recover the regime ... so closed episodes can be
attributed to a regime after restart"), this module chooses
*deterministic recovery* -- a closed episode's regime is always
recomputed, on demand, from the real historical OHLCV bars ending at
(and including) the point in time being classified. Real historical
daily bars for a past date do not change between one process run and
the next, so re-fetching the same ``(symbol, as_of)`` window after a
full restart reproduces the identical
:class:`~Business.market_regime_engine.MarketRegimeClassification` --
this is what makes restart-safety possible with zero schema/migration
footprint (no new database table, per the instruction's explicit
preference).

Explicitly out of scope for this addition: no caching layer, no new
repository, no change to ``StockDataRepository``/``StockService``, no
change to any scan/ranking/recommendation/paper-approval/notification
flow, no live broker/execution code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from Business.market_regime_engine import (
    MarketRegimeClassification,
    MarketRegimeEngine,
    STATUS_INSUFFICIENT_DATA,
)
from Core.exceptions import RepositoryError
from Core.logger import get_logger
from Repository.external.stock_data_repository import StockDataRepository

logger = get_logger(__name__)

#: Lookback period requested from ``StockDataRepository.get_history``.
#: Wide enough to always contain at least
#: ``Business.market_regime_engine.MIN_BARS`` trading days even after
#: filtering to bars at/before an ``as_of`` date well in the past,
#: for any real, actively-traded symbol. Mirrors
#: ``Core.request_defaults.DEFAULT_PERIOD`` (``"6mo"``) -- same value,
#: kept as a local, explicit constant rather than importing that
#: general-purpose default, because this module's requirement
#: ("enough bars to classify a window ending at an arbitrary past
#: date") is specific to this use, not the general stock-lookup
#: default.
REGIME_LOOKBACK_PERIOD: str = "6mo"
#: Bar interval requested -- daily bars, matching
#: ``Core.request_defaults.DEFAULT_INTERVAL`` and the engine's own
#: "daily return" definition.
REGIME_LOOKBACK_INTERVAL: str = "1d"

#: The trailing window size (in trading days) handed to
#: ``MarketRegimeEngine.classify()``. Kept in this module (not the
#: engine) because it is a data-selection concern -- the engine only
#: knows how to classify whatever window it is given.
REGIME_WINDOW_BARS: int = 20


class MarketRegimeService:
    """Resolves a real, deterministic
    :class:`~Business.market_regime_engine.MarketRegimeClassification`
    for one symbol, optionally as of a specific past timestamp.

    Depends only on ``StockDataRepository`` (real ``yfinance`` OHLCV)
    and ``MarketRegimeEngine`` (pure classifier) -- no other
    collaborator, no database, no other repository.
    """

    def __init__(
        self,
        stock_data_repository: StockDataRepository,
        market_regime_engine: MarketRegimeEngine,
    ) -> None:
        """Store the two collaborators this service composes.

        Args:
            stock_data_repository: Already-constructed repository used
                to fetch real OHLCV history. Stored by identity, never
                copied.
            market_regime_engine: The pure classifier this service
                delegates to. Stored by identity, never copied, never
                reimplemented here.
        """
        self._stock_data_repository = stock_data_repository
        self._market_regime_engine = market_regime_engine

    def classify_symbol_regime(
        self, symbol: str, as_of: Optional[str] = None
    ) -> MarketRegimeClassification:
        """Classify ``symbol``'s market regime from real OHLCV history.

        Args:
            symbol: Ticker symbol to classify (whatever format
                ``StockDataRepository``/``yfinance`` already accepts
                for this symbol -- this method performs no symbol
                normalization of its own).
            as_of: Optional ISO-8601 timestamp string. When given,
                only real bars dated at or before ``as_of`` are used
                (the trailing ``REGIME_WINDOW_BARS`` of those), so a
                closed episode that opened in the past is classified
                using only data that was actually real and available
                as of that moment -- never future/lookahead bars.
                When omitted, the most recent trailing window is used
                (i.e. "as of now").

        Returns:
            A :class:`~Business.market_regime_engine.
            MarketRegimeClassification` with
            ``status=STATUS_INSUFFICIENT_DATA`` (never a fabricated
            regime) if history could not be fetched, was empty, or
            did not contain enough real bars at/before ``as_of``.
        """
        try:
            history = self._stock_data_repository.get_history(
                symbol, period=REGIME_LOOKBACK_PERIOD, interval=REGIME_LOOKBACK_INTERVAL
            )
        except RepositoryError as exc:
            logger.warning(
                f"MarketRegimeService: could not fetch history for '{symbol}': {exc}"
            )
            return self._insufficient(bar_count=0)

        if history is None or history.empty:
            return self._insufficient(bar_count=0)

        records = history.reset_index().to_dict(orient="records")
        closes = self._extract_closes(records, as_of)

        window = closes[-REGIME_WINDOW_BARS:] if closes else []
        return self._market_regime_engine.classify(window)

    @staticmethod
    def _extract_closes(records: List[Any], as_of: Optional[str]) -> List[float]:
        """Extract real, chronologically-ordered closes from raw
        ``StockDataRepository`` records, optionally bounded to
        ``as_of``.

        Mirrors ``Services.stock_service.StockService.
        _extract_latest_close``'s own defensive-``dict``-read style --
        never raises on a malformed/missing field, simply excludes
        that record.

        Args:
            records: ``history.reset_index().to_dict(orient="records")``
                output -- each a ``dict`` with (among others) a
                ``"Date"`` and a ``"Close"`` key, in chronological
                order (``yfinance``'s own contract).
            as_of: Optional ISO-8601 timestamp string upper bound
                (inclusive). Records dated after this are excluded.
                Comparison is on the date portion only (``as_of``'s
                own timezone/precision is not assumed to match the
                bar timestamp's).

        Returns:
            Real ``Close`` values, oldest first, newest last, with
            any record missing/non-numeric ``"Close"`` or occurring
            after ``as_of`` silently excluded (never fabricated,
            never interpolated).
        """
        as_of_date = None
        if as_of:
            try:
                as_of_date = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date()
            except ValueError:
                as_of_date = None

        closes: List[float] = []
        for record in records:
            close = record.get("Close")
            if close is None:
                continue
            try:
                close_value = float(close)
            except (TypeError, ValueError):
                continue
            if close_value != close_value:  # NaN guard (NaN != NaN)
                continue

            if as_of_date is not None:
                bar_date = record.get("Date")
                bar_day = MarketRegimeService._coerce_date(bar_date)
                if bar_day is not None and bar_day > as_of_date:
                    continue

            closes.append(close_value)

        return closes

    @staticmethod
    def _coerce_date(bar_date: Any):
        """Best-effort coercion of a raw ``"Date"`` field (a
        ``pandas.Timestamp``, ``datetime``, or ``str``) to a plain
        ``datetime.date`` for comparison. Returns ``None`` (never
        raises) if ``bar_date`` is in a shape this cannot interpret --
        callers treat that as "no bound available for this record",
        never as an error.
        """
        if bar_date is None:
            return None
        if hasattr(bar_date, "date"):
            try:
                return bar_date.date()
            except Exception:  # noqa: BLE001 - defensive, never raises
                return None
        if isinstance(bar_date, str):
            try:
                return datetime.fromisoformat(bar_date.replace("Z", "+00:00")).date()
            except ValueError:
                return None
        return None

    @staticmethod
    def _insufficient(bar_count: int) -> MarketRegimeClassification:
        """Build an explicit ``STATUS_INSUFFICIENT_DATA`` result --
        the single place this service reports "could not classify",
        so every early-return above stays honest and consistent.
        """
        return MarketRegimeClassification(
            status=STATUS_INSUFFICIENT_DATA,
            regime=None,
            volatility=None,
            efficiency_ratio=None,
            bar_count=bar_count,
        )