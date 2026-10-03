from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, List, Optional

from Core.exceptions import RepositoryError
from Repository.external.base_external_repository import BaseExternalRepository


class NewsRepository(BaseExternalRepository):
    """Fetches raw news payloads for a ticker via ``yfinance``.

    Mirrors exactly what ``Services.news_service.NewsService`` previously
    did directly against ``yfinance`` -- ``Ticker(symbol).news`` -- but
    returns the raw payload unchanged. This repository does not:

    * Fall back ``None``/non-list payloads to ``[]``.
    * Validate the payload shape.
    * Know about ``ServiceContext``, ``MetadataKeys``, or ``ServiceResult``.

    All of that normalization remains the responsibility of ``NewsService``.
    """

    def __init__(self, yfinance_module: Optional[Any] = None) -> None:
        """Initialize without importing ``yfinance`` yet.

        Args:
            yfinance_module: Optional substitute for the real ``yfinance``
                module, exposing the same ``Ticker(symbol)`` interface.
                Intended for tests; production callers should omit this,
                in which case the real ``yfinance`` module is imported
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
                ``yfinance`` package is not installed. Raised directly
                (not routed through ``_call``), so this failure is never
                wrapped a second time.
        """
        if self._client is not None:
            return self._client
        try:
            import yfinance as yf  # noqa: PLC0415 - intentionally lazy, mirrors StockDataRepository
        except ImportError as exc:
            raise RepositoryError(
                "yfinance is not installed. Install it with 'pip install yfinance'.",
                details={"error": str(exc)},
            ) from exc
        return yf

    def get_news(self, ticker: str) -> Any:
        """Fetch the raw news payload for ``ticker``.

        Args:
            ticker: Ticker symbol to fetch news for.

        Returns:
            The raw value of ``yfinance.Ticker(ticker).news``, unchanged --
            may be ``None`` (attribute absent), a list, or any other type
            depending on the SDK/test-double. No normalization (``or []``,
            ``isinstance`` checks) is performed here -- that is
            ``NewsService``'s responsibility.

        Raises:
            RepositoryError: If ``yfinance`` is not installed, or the
                underlying fetch fails for any reason (network error, bad
                ticker, SDK error). The original exception is preserved
                as ``__cause__``. Client resolution happens before
                entering ``_call``, so a missing-dependency failure
                surfaces as a single ``RepositoryError``, not a
                ``RepositoryError`` wrapping another ``RepositoryError``.
        """
        client = self._resolve_client()

        def _fetch() -> Any:
            ticker_obj = client.Ticker(ticker)
            raw_news = getattr(ticker_obj, "news", None)
            if raw_news or self._client is not None:
                return raw_news

            # Yahoo Finance can legitimately return an empty ``news`` list
            # for IDX symbols even when current external news exists. The
            # roadmap requires real news evidence for successful analysis,
            # so use a read-only RSS fallback rather than inventing or
            # weakening the stock decision table. This path is only used
            # with the real production client; injected test doubles remain
            # deterministic and unchanged.
            return self._fetch_google_news_rss(ticker)

        return self._call(_fetch)

    @staticmethod
    def _fetch_google_news_rss(ticker: str) -> List[dict]:
        base_symbol = ticker.split(".", 1)[0]

        # The deterministic sentiment lexicon is English-only. For IDX
        # production evidence, prefer a real English Google News feed so
        # that retrieved headlines can actually be classified instead of
        # being silently reduced to ``neutral`` merely because the feed
        # language differs from the classifier contract. If no English
        # results exist, retain the Indonesian feed as a real-news fallback.
        queries = (
            (f"{base_symbol} stock Indonesia", "en-US", "US", "US:en"),
            (f"{base_symbol} saham", "id", "ID", "ID:id"),
        )

        for query_text, lang, geo, edition in queries:
            query = urllib.parse.quote_plus(query_text)
            url = (
                f"https://news.google.com/rss/search?q={query}"
                f"&hl={lang}&gl={geo}&ceid={edition}"
            )
            request = urllib.request.Request(
                url, headers={"User-Agent": "AIOS/1.0"}
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                root = ET.fromstring(response.read())

            items: List[dict] = []
            for item in root.findall("./channel/item")[:10]:
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate")
                source = item.findtext("source") or "Google News"
                if title:
                    items.append({
                        "title": title,
                        "link": link,
                        "publisher": source,
                        "pubDate": pub_date,
                        "summary": None,
                        "relatedTickers": [ticker],
                    })
            if items:
                return items

        return []

    def health_check(self) -> bool:
        """Check whether this repository can currently resolve its client.

        Deliberately does not perform a live network call: it only
        verifies that ``yfinance`` (injected or importable) is available,
        mirroring the previous ``NewsService.health_check()`` behavior
        exactly. Never raises.

        Returns:
            ``True`` if the ``yfinance``-compatible client can be
            resolved, ``False`` otherwise.
        """
        try:
            self._resolve_client()
            return True
        except RepositoryError:
            return False