from __future__ import annotations
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import pandas as pd
from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)

SUPPORTED_INDICATORS: Tuple[str, ...] = (
    "volume",
    "ema20",
    "ema50",
    "sma20",
    "sma50",
    "rsi",
    "macd",
    "bollinger",
)

_DEFAULT_INDICATORS: Tuple[str, ...] = SUPPORTED_INDICATORS
_DATE_COLUMN_CANDIDATES: Tuple[str, ...] = ("Date", "Datetime", "date", "datetime")
_RSI_PERIOD: int = 14
_MACD_FAST: int = 12
_MACD_SLOW: int = 26
_MACD_SIGNAL: int = 9
_BOLLINGER_PERIOD: int = 20
_BOLLINGER_STD_MULTIPLIER: float = 2.0


class ChartService(BaseService):
    """Builds a multi-panel technical-analysis chart from supplied OHLC data.

    Attributes:
        go_module: Injected substitute for ``plotly.graph_objects``.
            Defaults to ``None``, meaning the real module is imported
            lazily on first use.
        make_subplots_func: Injected substitute for
            ``plotly.subplots.make_subplots``. Defaults to ``None`` for the
            same reason.
    """

    def __init__(
        self,
        go_module: Optional[Any] = None,
        make_subplots_func: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Initialize the service without importing ``plotly`` yet.

        Args:
            go_module: Optional substitute for ``plotly.graph_objects``,
                exposing ``Candlestick``, ``Scatter``, ``Bar``, and
                ``Figure``. Intended for tests; production callers should
                omit this.
            make_subplots_func: Optional substitute for
                ``plotly.subplots.make_subplots``. Intended for tests;
                production callers should omit this.
        """
        self._go_module: Optional[Any] = go_module
        self._make_subplots_func: Optional[Callable[..., Any]] = make_subplots_func

    @property
    def name(self) -> str:
        """Unique identifier for this service."""
        return "chart_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return (
            "Builds candlestick charts with optional Volume, EMA20/50, SMA20/50, "
            "RSI, MACD, and Bollinger Band overlays from supplied OHLC data."
        )

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "visualization"

    def _resolve_plotly(self) -> Tuple[Any, Callable[..., Any]]:
        """Return the injected (``go``, ``make_subplots``) pair, or import the real ones.

        Raises:
            ImportError: If nothing was injected and the real ``plotly``
                package is not installed.
        """
        if self._go_module is not None and self._make_subplots_func is not None:
            return self._go_module, self._make_subplots_func
        import plotly.graph_objects as go  # noqa: PLC0415 - intentionally lazy, see module docstring
        from plotly.subplots import make_subplots  # noqa: PLC0415

        return go, make_subplots

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Compute elapsed milliseconds since ``started_at`` (a ``time.monotonic()`` reading)."""
        return (time.monotonic() - started_at) * 1000

    @staticmethod
    def _to_dataframe(history: Any) -> Optional[pd.DataFrame]:
        """Normalize supplied OHLC data into a ``pandas.DataFrame``.

        Args:
            history: Either a ``pandas.DataFrame`` already, or a list of
                row dicts (e.g. ``StockService``'s
                ``history.reset_index().to_dict(orient="records")`` output).

        Returns:
            A ``DataFrame``, or ``None`` if ``history`` is empty/unusable.
        """
        if isinstance(history, pd.DataFrame):
            df = history.copy()
        elif isinstance(history, list) and history:
            df = pd.DataFrame(history)
        else:
            return None
        return df if not df.empty else None

    @staticmethod
    def _find_date_column(df: pd.DataFrame) -> Optional[str]:
        """Find whichever known date/datetime column name is present, if any."""
        for candidate in _DATE_COLUMN_CANDIDATES:
            if candidate in df.columns:
                return candidate
        return None

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = _RSI_PERIOD) -> pd.Series:
        """Compute the Relative Strength Index for a close-price series."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _compute_macd(
        close: pd.Series,
        fast: int = _MACD_FAST,
        slow: int = _MACD_SLOW,
        signal: int = _MACD_SIGNAL,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Compute (macd_line, signal_line, histogram) for a close-price series."""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def _compute_bollinger(
        close: pd.Series,
        period: int = _BOLLINGER_PERIOD,
        std_multiplier: float = _BOLLINGER_STD_MULTIPLIER,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Compute (middle, upper, lower) Bollinger Bands for a close-price series."""
        middle = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = middle + std_multiplier * std
        lower = middle - std_multiplier * std
        return middle, upper, lower

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Build a technical-analysis chart from OHLC data in ``context.metadata``.

        Reads from ``context.metadata``:
            history: OHLC(V) data -- a list of row dicts or a DataFrame.
                Required; expected columns include ``Open``/``High``/
                ``Low``/``Close`` (``Volume`` only needed if the
                ``"volume"`` indicator is requested).
            ticker: Optional label used in the chart title. Defaults to
                ``""``.
            indicators: Optional list restricting which of
                ``SUPPORTED_INDICATORS`` to compute/draw. Defaults to all
                of them.
            image_path: Optional filesystem path. When given, the figure
                is saved there via Plotly's ``write_image`` (requires
                ``kaleido``).

        This never raises for business-level failures (missing/empty
        data, unknown indicators, image-save failures) -- all of those are
        reported via ``ServiceResult.fail(...)`` or degraded gracefully,
        per ``BaseService``'s contract.

        Args:
            context: The request context to operate on.

        Returns:
            A successful ``ServiceResult`` with
            ``data={"figure", "image_path", "metadata"}`` on success, or a
            failed ``ServiceResult`` describing what went wrong.
        """
        started_at = time.monotonic()
        ticker = context.get_metadata(MetadataKeys.TICKER, "")
        raw_history = context.get_metadata(MetadataKeys.HISTORY)
        requested_indicators = context.get_metadata(MetadataKeys.INDICATORS, list(_DEFAULT_INDICATORS))
        image_path = context.get_metadata(MetadataKeys.IMAGE_PATH)

        unknown = sorted(set(requested_indicators) - set(SUPPORTED_INDICATORS))
        if unknown:
            return ServiceResult.fail(
                error=ValueError(f"Unknown indicator(s): {unknown}"),
                message=f"Unknown indicator(s) requested: {unknown}. Supported: {list(SUPPORTED_INDICATORS)}.",
                metadata={MetadataKeys.TICKER: ticker, "requested_indicators": requested_indicators},
                execution_time_ms=self._elapsed_ms(started_at),
            )

        df = self._to_dataframe(raw_history)
        if df is None:
            return ServiceResult.fail(
                error=ValueError("No OHLC data supplied"),
                message="ChartService requires non-empty OHLC data in context.metadata['history'].",
                metadata={MetadataKeys.TICKER: ticker},
                execution_time_ms=self._elapsed_ms(started_at),
            )

        missing_columns = sorted(set(["Open", "High", "Low", "Close"]) - set(df.columns))
        if missing_columns:
            return ServiceResult.fail(
                error=ValueError(f"Missing required column(s): {missing_columns}"),
                message=f"Supplied OHLC data is missing required column(s): {missing_columns}.",
                metadata={MetadataKeys.TICKER: ticker, "columns_present": list(df.columns)},
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            go, make_subplots = self._resolve_plotly()
        except ImportError as exc:
            return ServiceResult.fail(
                error=exc,
                message="plotly is not installed. Install it with 'pip install plotly kaleido'.",
                metadata={MetadataKeys.TICKER: ticker},
                execution_time_ms=self._elapsed_ms(started_at),
            )

        try:
            fig, skipped = self._build_figure(df, ticker, requested_indicators, go, make_subplots)
        except Exception as exc:  # noqa: BLE001 - normalize any unexpected chart-building failure
            return ServiceResult.fail(
                error=exc,
                message=f"Failed to build chart: {exc}",
                metadata={MetadataKeys.TICKER: ticker},
                execution_time_ms=self._elapsed_ms(started_at),
            )

        saved_image_path: Optional[str] = None
        if image_path:
            try:
                fig.write_image(image_path)
                saved_image_path = image_path
            except Exception as exc:  # noqa: BLE001 - image export (kaleido) is best-effort only
                logger.warning(f"Could not save chart image to '{image_path}': {exc}")

        chart_metadata: Dict[str, Any] = {
            MetadataKeys.TICKER: ticker,
            "rows": len(df),
            "indicators_included": [i for i in requested_indicators if i not in skipped],
            "indicators_skipped": skipped,
        }

        return ServiceResult.ok(
            data={MetadataKeys.FIGURE: fig, MetadataKeys.IMAGE_PATH: saved_image_path, MetadataKeys.CHART_METADATA: chart_metadata},
            message=f"Chart built for '{ticker or 'unlabeled ticker'}' with {len(df)} row(s) of data.",
            metadata={MetadataKeys.TICKER: ticker, "image_saved": saved_image_path is not None},
            execution_time_ms=self._elapsed_ms(started_at),
        )

    def _build_figure(
        self,
        df: pd.DataFrame,
        ticker: str,
        indicators: List[str],
        go: Any,
        make_subplots: Callable[..., Any],
    ) -> Tuple[Any, List[str]]:
        """Build the multi-panel Plotly figure.

        Args:
            df: Normalized OHLC(V) DataFrame.
            ticker: Label used in the chart title.
            indicators: Indicator keys to compute/draw.
            go: ``plotly.graph_objects`` (or an injected substitute).
            make_subplots: ``plotly.subplots.make_subplots`` (or an
                injected substitute).

        Returns:
            A tuple of ``(figure, skipped_indicators)`` where
            ``skipped_indicators`` lists any requested indicator that could
            not be drawn (e.g. ``"volume"`` requested but no ``Volume``
            column present).
        """
        skipped: List[str] = []
        date_column = self._find_date_column(df)
        x_values = df[date_column] if date_column else df.index
        close = df["Close"]

        want_volume = "volume" in indicators and "Volume" in df.columns
        if "volume" in indicators and "Volume" not in df.columns:
            skipped.append("volume")
        want_rsi = "rsi" in indicators
        want_macd = "macd" in indicators

        row_specs = [("price", True)]
        if want_volume:
            row_specs.append(("volume", True))
        if want_rsi:
            row_specs.append(("rsi", True))
        if want_macd:
            row_specs.append(("macd", True))

        row_heights = [0.5] + [0.5 / (len(row_specs) - 1)] * (len(row_specs) - 1) if len(row_specs) > 1 else [1.0]
        fig = make_subplots(
            rows=len(row_specs),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=row_heights,
            subplot_titles=[label.upper() for label, _ in row_specs],
        )
        row_index = {label: idx + 1 for idx, (label, _) in enumerate(row_specs)}

        fig.add_trace(
            go.Candlestick(
                x=x_values,
                open=df["Open"],
                high=df["High"],
                low=df["Low"],
                close=close,
                name="OHLC",
            ),
            row=row_index["price"],
            col=1,
        )

        if "ema20" in indicators:
            ema20 = close.ewm(span=20, adjust=False).mean()
            fig.add_trace(go.Scatter(x=x_values, y=ema20, name="EMA 20", mode="lines"), row=row_index["price"], col=1)
        if "ema50" in indicators:
            ema50 = close.ewm(span=50, adjust=False).mean()
            fig.add_trace(go.Scatter(x=x_values, y=ema50, name="EMA 50", mode="lines"), row=row_index["price"], col=1)
        if "sma20" in indicators:
            sma20 = close.rolling(window=20).mean()
            fig.add_trace(go.Scatter(x=x_values, y=sma20, name="SMA 20", mode="lines"), row=row_index["price"], col=1)
        if "sma50" in indicators:
            sma50 = close.rolling(window=50).mean()
            fig.add_trace(go.Scatter(x=x_values, y=sma50, name="SMA 50", mode="lines"), row=row_index["price"], col=1)
        if "bollinger" in indicators:
            middle, upper, lower = self._compute_bollinger(close)
            fig.add_trace(go.Scatter(x=x_values, y=upper, name="Bollinger Upper", mode="lines"), row=row_index["price"], col=1)
            fig.add_trace(go.Scatter(x=x_values, y=middle, name="Bollinger Mid", mode="lines"), row=row_index["price"], col=1)
            fig.add_trace(go.Scatter(x=x_values, y=lower, name="Bollinger Lower", mode="lines"), row=row_index["price"], col=1)

        if want_volume:
            fig.add_trace(go.Bar(x=x_values, y=df["Volume"], name="Volume"), row=row_index["volume"], col=1)

        if want_rsi:
            rsi = self._compute_rsi(close)
            fig.add_trace(go.Scatter(x=x_values, y=rsi, name="RSI (14)", mode="lines"), row=row_index["rsi"], col=1)

        if want_macd:
            macd_line, signal_line, histogram = self._compute_macd(close)
            fig.add_trace(go.Scatter(x=x_values, y=macd_line, name="MACD", mode="lines"), row=row_index["macd"], col=1)
            fig.add_trace(go.Scatter(x=x_values, y=signal_line, name="Signal", mode="lines"), row=row_index["macd"], col=1)
            fig.add_trace(go.Bar(x=x_values, y=histogram, name="MACD Histogram"), row=row_index["macd"], col=1)

        fig.update_layout(
            title=f"{ticker} Technical Chart" if ticker else "Technical Chart",
            xaxis_rangeslider_visible=False,
            showlegend=True,
        )
        return fig, skipped

    def health_check(self) -> bool:
        """Check whether this service can currently build a minimal chart.

        Attempts to import/resolve ``plotly`` and construct a trivial
        one-row figure. Never raises: any failure (missing dependency,
        unexpected SDK error) is caught, logged, and reported as ``False``.
        This does not attempt an image export, since that requires the
        separate, optional ``kaleido`` package.

        Returns:
            ``True`` if a minimal figure could be built, ``False`` otherwise.
        """
        try:
            go, make_subplots = self._resolve_plotly()
            fig = make_subplots(rows=1, cols=1)
            fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], name="health_check"), row=1, col=1)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"ChartService health_check failed: {exc}")
            return False