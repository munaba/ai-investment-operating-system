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

_DEFAULT_RSI_PERIOD: int = 14
_DEFAULT_BOLLINGER_PERIOD: int = 20
_DEFAULT_ATR_PERIOD: int = 14


class TechnicalIndicatorService(BaseService):
    """Computes technical indicators (RSI, MACD, Bollinger Band, ATR, OBV) from OHLCV history.

    This service is stateless and reusable: it takes OHLCV history supplied
    via ``ServiceContext.metadata`` (e.g. produced by ``StockService``) and
    returns computed indicator values. It does not fetch data itself.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "technical_indicator_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Computes RSI, MACD, Bollinger Band, ATR, and OBV from OHLCV price history."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "market_data"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _calculate_rsi(close: pd.Series, periode: int = _DEFAULT_RSI_PERIOD) -> Optional[float]:
        """Calculate the latest Relative Strength Index (RSI) value.

        Algorithm preserved identically from the legacy ``hitung_rsi`` function.

        Args:
            close: Series of closing prices.
            periode: Lookback period for the RSI calculation.

        Returns:
            The latest RSI value, or ``None`` if there isn't enough data.
        """
        if len(close) < periode + 1:
            return None

        delta = close.diff()
        naik = delta.where(delta > 0, 0)
        turun = -delta.where(delta < 0, 0)

        rata_naik = naik.rolling(window=periode).mean()
        rata_turun = turun.rolling(window=periode).mean()

        rata_turun_terakhir = rata_turun.iloc[-1]
        rata_naik_terakhir = rata_naik.iloc[-1]

        if pd.isna(rata_turun_terakhir) or pd.isna(rata_naik_terakhir):
            return None

        if rata_turun_terakhir == 0:
            if rata_naik_terakhir == 0:
                return 50.0
            return 100.0

        rs = rata_naik_terakhir / rata_turun_terakhir
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def _calculate_macd(close: pd.Series) -> tuple[float, float]:
        """Calculate the latest MACD line and signal line values.

        Algorithm preserved identically from the legacy ``hitung_macd`` function.

        Args:
            close: Series of closing prices.

        Returns:
            A ``(macd_line, signal_line)`` tuple of the latest values.
        """
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()

        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()

        return macd_line.iloc[-1], signal_line.iloc[-1]

    @staticmethod
    def _calculate_bollinger(close: pd.Series, periode: int = _DEFAULT_BOLLINGER_PERIOD) -> tuple[float, float]:
        """Calculate the latest Bollinger Band upper and lower values.

        Algorithm preserved identically from the legacy ``hitung_bollinger`` function.

        Args:
            close: Series of closing prices.
            periode: Lookback period for the moving average and standard deviation.

        Returns:
            An ``(upper_band, lower_band)`` tuple.
        """
        middle_band = close.tail(periode).mean()
        std_dev = close.tail(periode).std()

        upper_band = middle_band + (2 * std_dev)
        lower_band = middle_band - (2 * std_dev)

        return upper_band, lower_band

    @staticmethod
    def _calculate_atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        periode: int = _DEFAULT_ATR_PERIOD,
    ) -> Optional[float]:
        """Calculate the latest Average True Range (ATR) value.

        Algorithm preserved identically from the legacy ``hitung_atr`` function.

        Args:
            high: Series of high prices.
            low: Series of low prices.
            close: Series of closing prices.
            periode: Lookback period for the ATR calculation.

        Returns:
            The latest ATR value, or ``None`` if there isn't enough data.
        """
        high_low = high - low
        high_close_sebelumnya = (high - close.shift(1)).abs()
        low_close_sebelumnya = (low - close.shift(1)).abs()

        true_range = pd.concat([high_low, high_close_sebelumnya, low_close_sebelumnya], axis=1).max(axis=1)

        atr = true_range.rolling(window=periode).mean()

        if len(atr) == 0 or pd.isna(atr.iloc[-1]):
            return None

        return atr.iloc[-1]

    @staticmethod
    def _calculate_obv(close: pd.Series, volume: pd.Series) -> Optional[float]:
        """Calculate the latest On-Balance Volume (OBV) value.

        Algorithm preserved identically from the legacy ``hitung_obv`` function.

        Args:
            close: Series of closing prices.
            volume: Series of traded volume.

        Returns:
            The latest OBV value, or ``None`` if there isn't enough data.
        """
        perubahan_harga = close.diff()

        arah = perubahan_harga.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

        obv = (arah * volume).cumsum()

        if len(obv) == 0 or pd.isna(obv.iloc[-1]):
            return None

        return obv.iloc[-1]

    @staticmethod
    def _extract_series(history: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert raw OHLCV history records into a DataFrame indexed for indicator calculations.

        Args:
            history: List of OHLCV records, e.g. as produced by ``StockService``
                (each record expected to contain ``Close``/``High``/``Low``/``Volume`` keys).

        Returns:
            A ``pandas.DataFrame`` built from the history records.

        Raises:
            ValueError: If required OHLCV columns are missing.
        """
        df = pd.DataFrame(history)
        required_columns = {"Close", "High", "Low", "Volume"}
        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"History is missing required column(s): {sorted(missing)}")
        return df

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Compute technical indicators from the OHLCV history in ``context.metadata``.

        Reads ``history`` (a list of OHLCV records) from ``context.metadata``.
        This never raises for business-level failures (missing/invalid input) --
        those are reported via ``ServiceResult.fail(...)`` instead, per
        ``BaseService``'s contract.

        Args:
            context: The request context to operate on. Must contain a
                ``history`` entry in its metadata.

        Returns:
            A successful ``ServiceResult`` with
            ``data={"rsi", "macd", "macd_signal", "bollinger_upper",
            "bollinger_lower", "atr", "obv"}`` on success, or a failed
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
            close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]

            rsi = self._calculate_rsi(close)
            macd_line, macd_signal = self._calculate_macd(close)
            bollinger_upper, bollinger_lower = self._calculate_bollinger(close)
            atr = self._calculate_atr(high, low, close)
            obv = self._calculate_obv(close, volume)
        except Exception as exc:  # noqa: BLE001 - normalize any calculation failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to compute technical indicators: {exc}",
                metadata=request_metadata,
                execution_time_ms=self._elapsed_ms(started_at),
            )

        return ServiceResult.ok(
            data={
                MetadataKeys.RSI: rsi,
                MetadataKeys.MACD: macd_line,
                MetadataKeys.MACD_SIGNAL: macd_signal,
                MetadataKeys.BOLLINGER_UPPER: bollinger_upper,
                MetadataKeys.BOLLINGER_LOWER: bollinger_lower,
                MetadataKeys.ATR: atr,
                MetadataKeys.OBV: obv,
            },
            message="Computed technical indicators (RSI, MACD, Bollinger Band, ATR, OBV).",
            metadata=request_metadata,
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def health_check(self) -> bool:
        """Check whether this service can currently compute indicators.

        Runs each calculation against a small synthetic OHLCV sample. Never
        raises: any failure is caught, logged, and reported as ``False``.

        Returns:
            ``True`` if all indicator calculations completed without error,
            ``False`` otherwise.
        """
        try:
            close = pd.Series([100.0 + i for i in range(30)])
            high = close + 1
            low = close - 1
            volume = pd.Series([1000 + i * 10 for i in range(30)])

            self._calculate_rsi(close)
            self._calculate_macd(close)
            self._calculate_bollinger(close)
            self._calculate_atr(high, low, close)
            self._calculate_obv(close, volume)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"TechnicalIndicatorService health_check failed: {exc}")
            return False