from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pandas as pd

from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)

_MA20_PERIOD: int = 20
_MA50_PERIOD: int = 50
_MA200_PERIOD: int = 200


class MovingAverageService(BaseService):
    """Computes MA20, MA50, and MA200 from OHLCV history.

    This service is stateless and reusable: it takes OHLCV history supplied
    via ``ServiceContext.metadata`` (e.g. produced by ``StockService``) and
    returns the latest simple moving average values. It does not fetch data
    itself.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "moving_average_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Computes MA20, MA50, and MA200 from OHLCV price history."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "market_data"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _calculate_ma(close: pd.Series, periode: int) -> Optional[float]:
        """Calculate the latest simple moving average value.

        Algorithm preserved identically from the legacy ``ma20``/``ma50``/
        ``ma200`` computation (``tail(periode).mean()`` with a length guard).

        Args:
            close: Series of closing prices.
            periode: Lookback period for the moving average.

        Returns:
            The latest moving average value, or ``None`` if there isn't
            enough data.
        """
        if len(close) < periode:
            return None

        return close.tail(periode).mean()

    @staticmethod
    def _extract_series(history: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert raw OHLCV history records into a DataFrame indexed for MA calculations.

        Args:
            history: List of OHLCV records, e.g. as produced by ``StockService``
                (each record expected to contain a ``Close`` key).

        Returns:
            A ``pandas.DataFrame`` built from the history records.

        Raises:
            ValueError: If required OHLCV columns are missing.
        """
        df = pd.DataFrame(history)
        required_columns = {"Close"}
        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"History is missing required column(s): {sorted(missing)}")
        return df

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Compute MA20, MA50, and MA200 from the OHLCV history in ``context.metadata``.

        Reads ``history`` (a list of OHLCV records) from ``context.metadata``.
        This never raises for business-level failures (missing/invalid input) --
        those are reported via ``ServiceResult.fail(...)`` instead, per
        ``BaseService``'s contract.

        Args:
            context: The request context to operate on. Must contain a
                ``history`` entry in its metadata.

        Returns:
            A successful ``ServiceResult`` with
            ``data={"ma20", "ma50", "ma200"}`` on success, or a failed
            ``ServiceResult`` describing what went wrong.
        """
        started_at = time.monotonic()
        history = context.get_metadata(MetadataKeys.HISTORY, None)
        request_metadata = {"history_length": len(history) if history else 0}

        if not history:
            return ServiceResult.fail(
                error=ValueError("Missing required 'history' in context metadata"),
                message="No OHLCV history was provided. Supply 'history' (e.g. from StockService) in context metadata.",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            df = self._extract_series(history)
        except ValueError as exc:
            return ServiceResult.fail(
                error=exc,
                message=str(exc),
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            close = df["Close"]

            ma20 = self._calculate_ma(close, _MA20_PERIOD)
            ma50 = self._calculate_ma(close, _MA50_PERIOD)
            ma200 = self._calculate_ma(close, _MA200_PERIOD)
        except Exception as exc:  # noqa: BLE001 - normalize any calculation failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to compute moving averages: {exc}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        return ServiceResult.ok(
            data={
                MetadataKeys.MA20: ma20,
                MetadataKeys.MA50: ma50,
                MetadataKeys.MA200: ma200,
            },
            message="Computed moving averages (MA20, MA50, MA200).",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently compute moving averages.

        Runs the calculation against a small synthetic close-price sample.
        Never raises: any failure is caught, logged, and reported as
        ``False``.

        Returns:
            ``True`` if the moving average calculations completed without
            error, ``False`` otherwise.
        """
        try:
            close = pd.Series([100.0 + i for i in range(30)])

            self._calculate_ma(close, _MA20_PERIOD)
            self._calculate_ma(close, _MA50_PERIOD)
            self._calculate_ma(close, _MA200_PERIOD)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"MovingAverageService health_check failed: {exc}")
            return False