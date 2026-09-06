from __future__ import annotations

from typing import Any, Dict, Optional

from Core.exceptions import RepositoryError
from Core.request_defaults import DEFAULT_TICKER
from Repository.external.base_external_repository import BaseExternalRepository


class StockDataRepository(BaseExternalRepository):
    """Fetches raw OHLCV history and company info for a ticker via ``yfinance``.

    Mirrors exactly what ``Services.stock_service.StockService`` currently
    does directly against ``yfinance`` -- ``Ticker(symbol).history(...)``
    and ``ticker.info`` -- but returns the raw ``yfinance`` types
    unchanged. This repository does not:

    * Normalize the ``DataFrame`` into a list-of-dict.
    * Extract PER, ROE, or dividend yield from ``info``.
    * Know about ``ServiceContext``, ``MetadataKeys``, or ``ServiceResult``.

    All of that remains the responsibility of ``StockService``, which is
    not yet wired to this repository (a separate sprint).
    """

    def __init__(self, yfinance_module: Optional[Any] = None) -> None:
        """Initialize without importing ``yfinance`` yet.

        Args:
            yfinance_module: Optional substitute for the real ``yfinance``
                module, exposing the same ``Ticker(symbol)`` interface.
                Intended for tests; production callers should omit this,
                in which case the real ``yfinance`` package is imported
                lazily on first use.
        """
        super().__init__(client=yfinance_module)

    def _resolve_client(self) -> Any:
        """Return the injected ``yfinance``-compatible module, or import the real one.

        Returns:
            The injected client if one was provided, otherwise the real
            ``yfinance`` module (imported lazily).

        Raises:
            RepositoryError: If no module was injected and the real
                ``yfinance`` package is not installed.
        """
        if self._client is not None:
            return self._client
        try:
            import yfinance as yf  # noqa: PLC0415 - intentionally lazy, mirrors StockService
        except ImportError as exc:
            raise RepositoryError(
                "yfinance is not installed. Install it with 'pip install yfinance'.",
                details={"error": str(exc)},
            ) from exc
        return yf

    def get_history(self, ticker: str, period: str, interval: str) -> Any:
        """Fetch raw OHLCV history for ``ticker``.

        Args:
            ticker: Ticker symbol to fetch history for.
            period: ``yfinance``-style lookback period (e.g. ``"6mo"``).
            interval: ``yfinance``-style bar interval (e.g. ``"1d"``).

        Returns:
            The raw ``pandas.DataFrame`` returned by
            ``yfinance.Ticker(ticker).history(...)``, unchanged -- may be
            empty if no data is available for ``ticker``/``period``/
            ``interval``.

        Raises:
            RepositoryError: If ``yfinance`` is not installed, or the
                underlying fetch fails for any reason (network error, bad
                ticker, SDK error). The original exception is preserved
                as ``__cause__``.
        """

        client = self._resolve_client()

        def _fetch() -> Any:
            return client.Ticker(ticker).history(period=period, interval=interval)

        return self._call(_fetch)

    def get_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch raw company info for ``ticker``.

        Args:
            ticker: Ticker symbol to fetch info for.

        Returns:
            The raw ``dict`` returned by ``yfinance.Ticker(ticker).info``,
            unchanged.

        Raises:
            RepositoryError: If ``yfinance`` is not installed, or the
                underlying fetch fails for any reason. The original
                exception is preserved as ``__cause__``.
        """

        client = self._resolve_client()

        def _fetch() -> Any:
            return client.Ticker(ticker).info

        return self._call(_fetch)

    def health_check(self) -> bool:
        """Check whether this repository can currently reach ``yfinance``.

        Attempts a minimal history fetch for the default ticker, mirroring
        ``Services.stock_service.StockService.health_check()`` exactly
        (same ticker, same ``period``/``interval``). Never raises: any
        failure (missing dependency, network error, empty result) is
        caught and reported as ``False``.

        Returns:
            ``True`` if a small history fetch succeeded, ``False``
            otherwise.
        """
        try:
            history = self.get_history(DEFAULT_TICKER, period="1d", interval="1d")
            return history is not None and not history.empty
        except RepositoryError:
            return False