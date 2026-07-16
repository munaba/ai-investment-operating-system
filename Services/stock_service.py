from __future__ import annotations

import time
from typing import Any, Dict, Optional

from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult

logger = get_logger(__name__)

_DEFAULT_TICKER: str = "BBCA.JK"
_DEFAULT_PERIOD: str = "6mo"
_DEFAULT_INTERVAL: str = "1d"


class StockService(BaseService):
    """Fetches OHLCV history and company info for a ticker via ``yfinance``.

    Attributes:
        yfinance_module: The ``yfinance``-compatible module used to fetch
            data. Defaults to ``None``, meaning the real ``yfinance``
            package is imported lazily on first use.
    """

    def __init__(self, yfinance_module: Optional[Any] = None) -> None:
        """Initialize the service without importing ``yfinance`` yet.

        Args:
            yfinance_module: Optional substitute for the real ``yfinance``
                module, exposing the same ``Ticker(symbol)`` interface.
                Intended for tests; production callers should omit this.
        """
        self._yfinance_module: Optional[Any] = yfinance_module

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
            ``data={"ticker", "history", "info"}`` on success, or a failed
            ``ServiceResult`` describing what went wrong.
        """
        started_at = time.monotonic()
        ticker_symbol = context.get_metadata("ticker", _DEFAULT_TICKER)
        period = context.get_metadata("period", _DEFAULT_PERIOD)
        interval = context.get_metadata("interval", _DEFAULT_INTERVAL)
        request_metadata = {"ticker": ticker_symbol, "period": period, "interval": interval}

        try:
            yfinance_module = self._resolve_yfinance()
        except ImportError as exc:
            return ServiceResult.fail(
                error=exc,
                message="yfinance is not installed. Install it with 'pip install yfinance'.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            ticker = yfinance_module.Ticker(ticker_symbol)
            history = ticker.history(period=period, interval=interval)
        except Exception as exc:  # noqa: BLE001 - normalize any yfinance/network failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to fetch history for ticker '{ticker_symbol}': {exc}",
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
            info = ticker.info or None
        except Exception as exc:  # noqa: BLE001 - company info is best-effort only
            logger.warning(f"Could not fetch company info for '{ticker_symbol}': {exc}")
            info = None

        return ServiceResult.ok(
            data={"ticker": ticker_symbol, "history": history_records, "info": info},
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
        try:
            yfinance_module = self._resolve_yfinance()
            ticker = yfinance_module.Ticker(_DEFAULT_TICKER)
            history = ticker.history(period="1d", interval="1d")
            return history is not None and not history.empty
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"StockService health_check failed: {exc}")
            return False