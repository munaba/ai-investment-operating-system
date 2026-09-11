from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from Core.exceptions import RepositoryError
from Core.logger import get_logger
from Core.request_defaults import DEFAULT_INTERVAL, DEFAULT_PERIOD, DEFAULT_TICKER
from Repository.external.stock_data_repository import StockDataRepository
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)

# Best-effort candidate key names for extracting valuation/profitability
# metrics from yfinance's ``Ticker.info`` dict. Tried in order; the first
# key present in ``info`` wins. Key names are not guaranteed by yfinance
# across versions/tickers, hence the fallback list per metric.
_PER_INFO_KEYS: Tuple[str, ...] = ("trailingPE", "forwardPE")
_ROE_INFO_KEYS: Tuple[str, ...] = ("returnOnEquity",)
_DIVIDEND_YIELD_INFO_KEYS: Tuple[str, ...] = ("dividendYield", "trailingAnnualDividendYield")


class StockService(BaseService):
    """Fetches OHLCV history and company info for a ticker via ``yfinance``.

    Attributes:
        yfinance_module: The ``yfinance``-compatible module used to fetch
            data. Defaults to ``None``, meaning the real ``yfinance``
            package is imported lazily on first use. Ignored when
            ``stock_repository`` is provided (see below).
    """

    def __init__(
        self,
        yfinance_module: Optional[Any] = None,
        stock_repository: Optional[StockDataRepository] = None,
    ) -> None:
        """Initialize the service without importing ``yfinance`` yet.

        Args:
            yfinance_module: Optional substitute for the real ``yfinance``
                module, exposing the same ``Ticker(symbol)`` interface.
                Intended for tests; production callers should omit this.
                Ignored when ``stock_repository`` is provided.
            stock_repository: Optional pre-built
                :class:`~Repository.external.stock_data_repository.StockDataRepository`
                to use directly (Task 1B addition, additive only --
                Composition Root injection seam). When provided,
                ``yfinance_module`` is ignored entirely and this instance
                is held as-is, never copied or wrapped. When omitted
                (the default), behavior is exactly what it was before
                this seam existed: a ``StockDataRepository`` is
                constructed internally from ``yfinance_module``.
        """
        self._yfinance_module: Optional[Any] = yfinance_module
        if stock_repository is not None:
            self._stock_repository = stock_repository
        else:
            self._stock_repository = StockDataRepository(yfinance_module=yfinance_module)

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "stock_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Fetches OHLCV price history, volume, and company info for a stock ticker via yfinance."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "market_data"

    def _resolve_yfinance(self) -> Any:
        """Return the injected ``yfinance``-compatible module, or import the real one.

        Raises:
            ImportError: If no module was injected and the real ``yfinance``
                package is not installed.
        """
        if self._yfinance_module is not None:
            return self._yfinance_module
        import yfinance as yf  # noqa: PLC0415 - intentionally lazy, see module docstring

        return yf

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _extract_latest_close(history_records: List[Dict[str, Any]]) -> Optional[Any]:
        """Best-effort extraction of the latest closing price already present in ``history_records``.

        Does not fetch any new data -- only reads the ``"Close"`` field of
        the last record already produced in this call.

        Args:
            history_records: OHLCV records as already built in ``execute()``
                (e.g. via ``history.reset_index().to_dict(orient="records")``).

        Returns:
            The ``"Close"`` value of the last record, or ``None`` if
            ``history_records`` is empty or the last record has no
            ``"Close"`` field.
        """
        if not history_records:
            return None
        return history_records[-1].get("Close")

    @staticmethod
    def _extract_info_metric(info: Optional[Dict[str, Any]], keys: Tuple[str, ...]) -> Optional[Any]:
        """Best-effort extraction of the first available metric from ``info``.

        Args:
            info: The already-fetched yfinance ``info`` dict (may be
                ``None``).
            keys: Candidate key names to try, in priority order.

        Returns:
            The first non-``None`` value found under any of ``keys``, or
            ``None`` if ``info`` is ``None``/empty or none of ``keys`` are
            present. Never raises.
        """
        if not info:
            return None
        for key in keys:
            value = info.get(key)
            if value is not None:
                return value
        return None

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Fetch OHLCV history and company info for the requested ticker.

        Reads ``ticker``, ``period``, and ``interval`` from
        ``context.metadata`` (falling back to ``"BBCA.JK"``, ``"6mo"``, and
        ``"1d"`` respectively when absent).

        This never raises for business-level failures (missing ticker, bad
        data, network/SDK errors) -- all of those are reported via
        ``ServiceResult.fail(...)`` instead, per ``BaseService``'s contract.

        Args:
            context: The request context to operate on.

        Returns:
            A successful ``ServiceResult`` with
            ``data={"ticker", "history", "info", "harga", "per", "roe",
            "dividend_yield"}`` on success, or a failed ``ServiceResult``
            describing what went wrong. ``harga`` is derived from the
            already-fetched history; ``per``/``roe``/``dividend_yield`` are
            best-effort extractions from the already-fetched ``info`` and
            are ``None`` when unavailable.
        """
        started_at = time.monotonic()
        ticker_symbol = context.get_metadata(MetadataKeys.TICKER, DEFAULT_TICKER)
        period = context.get_metadata(MetadataKeys.PERIOD, DEFAULT_PERIOD)
        interval = context.get_metadata(MetadataKeys.INTERVAL, DEFAULT_INTERVAL)
        request_metadata = {
            MetadataKeys.TICKER: ticker_symbol,
            MetadataKeys.PERIOD: period,
            MetadataKeys.INTERVAL: interval,
        }

        try:
            history = self._stock_repository.get_history(ticker_symbol, period, interval)
        except RepositoryError as exc:  # noqa: BLE001 - normalize any yfinance/network failure
            original_error = exc.__cause__ or exc
            if isinstance(original_error, ImportError):
                return ServiceResult.fail(
                    error=original_error,
                    message="yfinance is not installed. Install it with 'pip install yfinance'.",
                    metadata=request_metadata,
                    execution_time_ms=self._elapsed_ms(started_at),
                )
            return ServiceResult.fail(
                error=original_error,
                message=f"Failed to fetch history for ticker '{ticker_symbol}': {original_error}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        if history is None or history.empty:
            return ServiceResult.fail(
                error=ValueError(f"No data found for ticker '{ticker_symbol}'"),
                message=(
                    f"No historical data found for ticker '{ticker_symbol}'. "
                    "It may be delisted, invalid, or unsupported for the given period/interval."
                ),
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        history_records = history.reset_index().to_dict(orient="records")

        info: Optional[Dict[str, Any]]
        try:
            info = self._stock_repository.get_info(ticker_symbol) or None
        except RepositoryError as exc:  # noqa: BLE001 - company info is best-effort only
            original_error = exc.__cause__ or exc
            logger.warning(f"Could not fetch company info for '{ticker_symbol}': {original_error}")
            info = None

        harga = self._extract_latest_close(history_records)
        per = self._extract_info_metric(info, _PER_INFO_KEYS)
        roe = self._extract_info_metric(info, _ROE_INFO_KEYS)
        dividend_yield = self._extract_info_metric(info, _DIVIDEND_YIELD_INFO_KEYS)

        return ServiceResult.ok(
            data={
                MetadataKeys.TICKER: ticker_symbol,
                MetadataKeys.HISTORY: history_records,
                MetadataKeys.INFO: info,
                MetadataKeys.PRICE: harga,
                MetadataKeys.PER: per,
                MetadataKeys.ROE: roe,
                MetadataKeys.DIVIDEND_YIELD: dividend_yield,
            },
            message=f"Fetched {len(history_records)} row(s) of history for '{ticker_symbol}'.",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently reach ``yfinance``.

        Attempts a minimal history fetch for the default ticker. Never
        raises: any failure (missing dependency, network error, empty
        result) is caught, logged, and reported as ``False``.

        Returns:
            ``True`` if a small history fetch succeeded, ``False`` otherwise.
        """
        return self._stock_repository.health_check()