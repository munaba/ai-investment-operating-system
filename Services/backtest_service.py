from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Tuple
from Core.exceptions import AgentError
from Core.logger import get_logger
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult

logger = get_logger(__name__)

EMA_CROSS_STRATEGY: str = "ema_cross"
SMA_CROSS_STRATEGY: str = "sma_cross"
SUPPORTED_STRATEGIES: frozenset = frozenset({EMA_CROSS_STRATEGY, SMA_CROSS_STRATEGY})

DEFAULT_STRATEGY: str = EMA_CROSS_STRATEGY
DEFAULT_INITIAL_CAPITAL: float = 100_000_000.0
DEFAULT_FAST_PERIOD: int = 20
DEFAULT_SLOW_PERIOD: int = 50


class BacktestServiceError(AgentError):
    """Raised for any business-level failure while running a backtest.

    Additive subclass of ``Core.exceptions.AgentError``, following the
    same pattern used elsewhere in the framework (e.g. ``PlannerError``,
    ``NewsServiceError``, ``NotificationServiceError``). Never escapes
    :meth:`BacktestService.execute` -- it is always caught and converted
    into a failed :class:`Services.service_result.ServiceResult`.
    """


class BacktestService(BaseService):
    """Runs a simple fast/slow moving-average crossover backtest.

    The service holds no mutable state of its own -- every call to
    :meth:`execute` is fully self-contained -- so a single instance can be
    shared safely across threads without extra locking.
    """

    @property
    def name(self) -> str:
        """Unique, human-readable identifier for this service."""
        return "backtest_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Runs a simple moving-average crossover backtest against historical price data."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "finance"

    @staticmethod
    def _get_pandas() -> Any:
        """Lazily import and return the ``pandas`` module.

        Raises:
            BacktestServiceError: If ``pandas`` is not installed.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise BacktestServiceError(
                "pandas is not installed. Install it with 'pip install pandas'.",
                details={"error": str(exc)},
            ) from exc
        return pd

    @staticmethod
    def _get_numpy() -> Any:
        """Lazily import and return the ``numpy`` module.

        Raises:
            BacktestServiceError: If ``numpy`` is not installed.
        """
        try:
            import numpy as np
        except ImportError as exc:
            raise BacktestServiceError(
                "numpy is not installed. Install it with 'pip install numpy'.",
                details={"error": str(exc)},
            ) from exc
        return np

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Run a moving-average crossover backtest as described by ``context``.

        Args:
            context: Request context. Reads the following metadata keys:
                ``history`` (required -- a non-empty list of records, or a
                ``pandas.DataFrame``, each containing at least a ``close``
                field and, optionally, a ``date`` field),
                ``strategy`` (str, defaults to :data:`DEFAULT_STRATEGY`,
                one of ``"ema_cross"``/``"sma_cross"``),
                ``initial_capital`` (number, defaults to
                :data:`DEFAULT_INITIAL_CAPITAL`),
                ``fast_period`` (int, defaults to
                :data:`DEFAULT_FAST_PERIOD`),
                ``slow_period`` (int, defaults to
                :data:`DEFAULT_SLOW_PERIOD`).

        Returns:
            On success, a :class:`ServiceResult` whose ``data`` contains
            ``strategy``, ``total_return`` (percent), ``final_capital``,
            ``total_trade``, ``win_rate`` (percent), and ``trade_history``.
            On any business or unexpected error, a failed
            :class:`ServiceResult` built via :meth:`ServiceResult.fail`.
            This method never raises.
        """
        started_at = time.monotonic()
        try:
            pandas_module = self._get_pandas()

            strategy = self._resolve_strategy(context)
            initial_capital = self._resolve_initial_capital(context)
            fast_period, slow_period = self._resolve_periods(context)

            dataframe = self._to_dataframe(pandas_module, context.get_metadata("history"))
            fast_ma, slow_ma = self._compute_moving_averages(
                dataframe["close"], strategy, fast_period, slow_period
            )

            trade_history, final_capital = self._run_backtest(
                dataframe, fast_ma, slow_ma, initial_capital
            )

            total_trade = sum(1 for trade in trade_history if trade["action"] == "SELL")
            wins = sum(
                1
                for trade in trade_history
                if trade["action"] == "SELL" and trade.get("pnl", 0.0) > 0
            )
            win_rate = (wins / total_trade * 100.0) if total_trade > 0 else 0.0
            total_return = (
                ((final_capital - initial_capital) / initial_capital) * 100.0
                if initial_capital > 0
                else 0.0
            )

            elapsed_ms = (time.monotonic() - started_at) * 1000
            return ServiceResult.ok(
                data={
                    "strategy": strategy,
                    "total_return": total_return,
                    "final_capital": final_capital,
                    "total_trade": total_trade,
                    "win_rate": win_rate,
                    "trade_history": trade_history,
                },
                message=f"Backtest completed using '{strategy}' strategy ({total_trade} trade(s)).",
                execution_time_ms=elapsed_ms,
            )
        except BacktestServiceError as exc:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            logger.warning(f"BacktestService.execute failed: {exc}")
            return ServiceResult.fail(exc, execution_time_ms=elapsed_ms)
        except Exception as exc:  # noqa: BLE001 - normalize any unexpected failure
            elapsed_ms = (time.monotonic() - started_at) * 1000
            wrapped = BacktestServiceError(
                "Unexpected error during backtest", details={"error": str(exc)}
            )
            logger.error(f"BacktestService.execute unexpected error: {exc}")
            return ServiceResult.fail(wrapped, execution_time_ms=elapsed_ms)

    @staticmethod
    def _resolve_strategy(context: ServiceContext) -> str:
        """Read and validate the ``strategy`` metadata value.

        Raises:
            BacktestServiceError: If ``strategy`` is not a string or not
                one of :data:`SUPPORTED_STRATEGIES`.
        """
        strategy = context.get_metadata("strategy", DEFAULT_STRATEGY)
        if not isinstance(strategy, str) or not strategy.strip():
            raise BacktestServiceError(
                "strategy must be a non-empty string", details={"strategy": strategy}
            )
        normalized = strategy.strip().lower()
        if normalized not in SUPPORTED_STRATEGIES:
            raise BacktestServiceError(
                f"Invalid strategy: '{strategy}'. Supported strategies: "
                f"{sorted(SUPPORTED_STRATEGIES)}",
                details={"strategy": strategy},
            )
        return normalized

    @staticmethod
    def _resolve_initial_capital(context: ServiceContext) -> float:
        """Read and validate the ``initial_capital`` metadata value.

        Raises:
            BacktestServiceError: If ``initial_capital`` cannot be
                interpreted as a positive number.
        """
        raw_value = context.get_metadata("initial_capital", DEFAULT_INITIAL_CAPITAL)
        try:
            capital = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise BacktestServiceError(
                f"initial_capital must be a number, got {raw_value!r}",
                details={"initial_capital": raw_value},
            ) from exc
        if capital <= 0:
            raise BacktestServiceError(
                f"initial_capital must be positive, got {capital}",
                details={"initial_capital": capital},
            )
        return capital

    @staticmethod
    def _resolve_periods(context: ServiceContext) -> Tuple[int, int]:
        """Read and validate ``fast_period``/``slow_period`` metadata values.

        Raises:
            BacktestServiceError: If either value is not a positive
                integer, or ``fast_period`` is not strictly less than
                ``slow_period``.
        """
        raw_fast = context.get_metadata("fast_period", DEFAULT_FAST_PERIOD)
        raw_slow = context.get_metadata("slow_period", DEFAULT_SLOW_PERIOD)
        try:
            fast_period = int(raw_fast)
            slow_period = int(raw_slow)
        except (TypeError, ValueError) as exc:
            raise BacktestServiceError(
                f"fast_period/slow_period must be integers, got "
                f"{raw_fast!r}/{raw_slow!r}",
                details={"fast_period": raw_fast, "slow_period": raw_slow},
            ) from exc
        if fast_period <= 0 or slow_period <= 0:
            raise BacktestServiceError(
                "fast_period and slow_period must be positive integers",
                details={"fast_period": fast_period, "slow_period": slow_period},
            )
        if fast_period >= slow_period:
            raise BacktestServiceError(
                f"fast_period ({fast_period}) must be less than slow_period ({slow_period})",
                details={"fast_period": fast_period, "slow_period": slow_period},
            )
        return fast_period, slow_period

    @staticmethod
    def _to_dataframe(pandas_module: Any, history: Any) -> Any:
        """Normalize ``history`` into a ``pandas.DataFrame`` with a ``close`` column.

        Args:
            pandas_module: The resolved ``pandas`` module.
            history: Either a non-empty list/tuple of record dicts, or a
                ``pandas.DataFrame``, each containing at least a ``close``
                field (case-insensitive) and, optionally, a ``date`` field.

        Returns:
            A ``pandas.DataFrame`` with lower-cased column names, a
            ``float`` ``close`` column, and a reset integer index.

        Raises:
            BacktestServiceError: If ``history`` is empty, of an
                unsupported type, or has no ``close`` field.
        """
        if history is None:
            raise BacktestServiceError("history must not be empty", details={"history": history})

        if isinstance(history, pandas_module.DataFrame):
            dataframe = history.copy()
        elif isinstance(history, (list, tuple)):
            if len(history) == 0:
                raise BacktestServiceError(
                    "history must not be empty", details={"history": history}
                )
            dataframe = pandas_module.DataFrame(list(history))
        else:
            raise BacktestServiceError(
                f"history must be a list of records or a DataFrame, got "
                f"{type(history).__name__}",
                details={"history_type": type(history).__name__},
            )

        if dataframe.empty:
            raise BacktestServiceError("history must not be empty", details={"history": history})

        dataframe.columns = [str(column).strip().lower() for column in dataframe.columns]
        if "close" not in dataframe.columns:
            raise BacktestServiceError(
                "history records must contain a 'close' field",
                details={"columns": list(dataframe.columns)},
            )

        dataframe = dataframe.reset_index(drop=True)
        try:
            dataframe["close"] = dataframe["close"].astype(float)
        except (TypeError, ValueError) as exc:
            raise BacktestServiceError(
                "history 'close' field must be numeric", details={"error": str(exc)}
            ) from exc
        return dataframe

    @staticmethod
    def _compute_moving_averages(
        close_series: Any, strategy: str, fast_period: int, slow_period: int
    ) -> Tuple[Any, Any]:
        """Compute the fast/slow moving-average pair for ``strategy``.

        Args:
            close_series: A ``pandas.Series`` of closing prices.
            strategy: Either :data:`EMA_CROSS_STRATEGY` or
                :data:`SMA_CROSS_STRATEGY`.
            fast_period: Window/span used for the fast moving average.
            slow_period: Window/span used for the slow moving average.

        Returns:
            A ``(fast_ma, slow_ma)`` tuple of ``pandas.Series``.
        """
        if strategy == EMA_CROSS_STRATEGY:
            fast_ma = close_series.ewm(span=fast_period, adjust=False, min_periods=fast_period).mean()
            slow_ma = close_series.ewm(span=slow_period, adjust=False, min_periods=slow_period).mean()
        else: 
            fast_ma = close_series.rolling(window=fast_period).mean()
            slow_ma = close_series.rolling(window=slow_period).mean()
        return fast_ma, slow_ma

    @staticmethod
    def _run_backtest(
        dataframe: Any, fast_ma: Any, slow_ma: Any, initial_capital: float
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Simulate an all-in/all-out crossover strategy bar by bar.

        Buys with the full available cash when the fast MA crosses above
        the slow MA, and sells the entire position when the fast MA
        crosses below the slow MA (see module Architecture Notes for the
        simplifications this makes).

        Args:
            dataframe: Normalized OHLC-like DataFrame (must contain
                ``close`` and, optionally, ``date``).
            fast_ma: Fast moving-average series aligned to ``dataframe``.
            slow_ma: Slow moving-average series aligned to ``dataframe``.
            initial_capital: Starting cash balance.

        Returns:
            A ``(trade_history, final_capital)`` tuple. ``trade_history``
            is a list of ``{"action", "date", "price", "shares", "pnl"?}``
            dicts in chronological order (``pnl`` is present only on
            ``"SELL"`` entries). ``final_capital`` is the ending cash
            balance, mark-to-market against the last close price if a
            position is still open.
        """
        has_date_column = "date" in dataframe.columns
        diff = fast_ma - slow_ma
        previous_diff = diff.shift(1)

        capital = initial_capital
        shares = 0.0
        entry_price: Optional[float] = None
        trade_history: List[Dict[str, Any]] = []

        for i in range(len(dataframe)):
            current_diff_value = diff.iloc[i]
            previous_diff_value = previous_diff.iloc[i]
            close_price = float(dataframe["close"].iloc[i])
            date_value = dataframe["date"].iloc[i] if has_date_column else i

            buy_signal = previous_diff_value <= 0 and current_diff_value > 0
            sell_signal = previous_diff_value >= 0 and current_diff_value < 0

            if buy_signal and shares == 0.0:
                shares = capital / close_price
                entry_price = close_price
                capital = 0.0
                trade_history.append(
                    {
                        "action": "BUY",
                        "date": str(date_value),
                        "price": close_price,
                        "shares": shares,
                    }
                )
            elif sell_signal and shares > 0.0:
                proceeds = shares * close_price
                cost_basis = (entry_price or 0.0) * shares
                pnl = proceeds - cost_basis
                trade_history.append(
                    {
                        "action": "SELL",
                        "date": str(date_value),
                        "price": close_price,
                        "shares": shares,
                        "pnl": pnl,
                    }
                )
                capital = proceeds
                shares = 0.0
                entry_price = None

        final_capital = capital
        if shares > 0.0:
            last_close = float(dataframe["close"].iloc[-1])
            final_capital = shares * last_close

        return trade_history, final_capital

    def health_check(self) -> bool:
        """Report whether this service can currently resolve its dependencies.

        Mirrors the ``bool``-returning contract shared by every
        ``health_check()`` in the framework (``BaseProvider``,
        ``BaseAgent``, ``BaseService``). Only verifies that ``pandas`` and
        ``numpy`` are importable -- no network access is ever needed, so
        this check is always fast and safe to call frequently. Never
        raises.

        Returns:
            ``True`` if both dependencies can be resolved, ``False``
            otherwise.
        """
        try:
            self._get_pandas()
            self._get_numpy()
            return True
        except Exception as exc:  
            logger.warning(f"BacktestService.health_check failed: {exc}")
            return False