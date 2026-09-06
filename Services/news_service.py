from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from Core.exceptions import AgentError, RepositoryError
from Core.logger import get_logger
from Core.request_defaults import DEFAULT_MAX_NEWS, DEFAULT_TICKER
from Repository.external.news_repository import NewsRepository
from Services.base_service import BaseService
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult
from Services.metadata_keys import MetadataKeys

logger = get_logger(__name__)


class NewsServiceError(AgentError):
    """Raised for any business-level failure while fetching news.

    Additive subclass of ``Core.exceptions.AgentError``, following the
    same pattern used elsewhere in the framework (e.g. ``PlannerError``,
    ``ToolExecutionError``). Never escapes :meth:`NewsService.execute` --
    it is always caught and converted into a failed
    :class:`Services.service_result.ServiceResult`.
    """


class NewsService(BaseService):
    """Fetches recent news articles for a given stock ticker via ``yfinance``.

    The service is stateless aside from its injected ``yfinance`` module
    reference, which is never mutated after construction -- a single
    instance can therefore be shared safely across threads without extra
    locking.

    Args:
        yfinance_module: Optional pre-imported module (or a
            test double exposing a compatible ``Ticker`` interface) to use
            instead of importing ``yfinance`` lazily. This is the same
            dependency-injection seam used by ``StockService``, and exists
            so this service can be smoke-tested without network access or
            without ``yfinance`` installed at all. Passed straight through
            to an internal :class:`NewsRepository`, which performs the
            actual external I/O. Ignored when ``news_repository`` is
            provided.
        news_repository: Optional pre-built
            :class:`~Repository.external.news_repository.NewsRepository`
            to use directly (Task 1B addition, additive only --
            Composition Root injection seam). When provided,
            ``yfinance_module`` is ignored entirely and this instance is
            held as-is, never copied or wrapped. When omitted (the
            default), behavior is exactly what it was before this seam
            existed: a ``NewsRepository`` is constructed internally from
            ``yfinance_module``.
    """

    def __init__(
        self,
        yfinance_module: Optional[Any] = None,
        news_repository: Optional[NewsRepository] = None,
    ) -> None:
        if news_repository is not None:
            self._repository = news_repository
        else:
            self._repository = NewsRepository(yfinance_module=yfinance_module)

    @property
    def name(self) -> str:
        """Unique, human-readable identifier for this service."""
        return "news_service"

    @property
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        return "Fetches recent news articles for a stock ticker using yfinance."

    @property
    def category(self) -> str:
        """Logical grouping this service belongs to."""
        return "finance"

    def execute(self, context: ServiceContext) -> ServiceResult:
        """Fetch news for the ticker/max_news given in ``context.metadata``.

        Args:
            context: Request context. Reads two optional metadata keys:
                ``ticker`` (str, defaults to :data:`DEFAULT_TICKER`) and
                ``max_news`` (int, defaults to :data:`DEFAULT_MAX_NEWS`).

        Returns:
            On success, a :class:`ServiceResult` whose ``data`` is
            ``{"ticker": ..., "news": [...], "total_news": ...}``.
            On any business or unexpected error, a failed
            :class:`ServiceResult` built via :meth:`ServiceResult.fail`.
            This method never raises.
        """
        started_at = time.monotonic()
        try:
            ticker = self._resolve_ticker(context)
            max_news = self._resolve_max_news(context)

            raw_news = self._fetch_raw_news(ticker)

            news_items = [self._normalize_news_item(item) for item in raw_news[:max_news]]

            elapsed_ms = (time.monotonic() - started_at) * 1000
            return ServiceResult.ok(
                data={
                    MetadataKeys.TICKER: ticker,
                    MetadataKeys.NEWS: news_items,
                    MetadataKeys.TOTAL_NEWS: len(news_items),
                },
                message=f"Fetched {len(news_items)} news item(s) for '{ticker}'.",
                execution_time_ms=elapsed_ms,
            )
        except NewsServiceError as exc:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            logger.warning(f"NewsService.execute failed: {exc}")
            return ServiceResult.fail(exc, execution_time_ms=elapsed_ms)
        except Exception as exc:  # noqa: BLE001 - normalize any unexpected failure
            elapsed_ms = (time.monotonic() - started_at) * 1000
            wrapped = NewsServiceError(
                "Unexpected error while fetching news", details={"error": str(exc)}
            )
            logger.error(f"NewsService.execute unexpected error: {exc}")
            return ServiceResult.fail(wrapped, execution_time_ms=elapsed_ms)

    @staticmethod
    def _resolve_ticker(context: ServiceContext) -> str:
        """Read and validate the ``ticker`` metadata value.

        Raises:
            NewsServiceError: If ``ticker`` is present but not a
                non-empty string.
        """
        ticker = context.get_metadata(MetadataKeys.TICKER, DEFAULT_TICKER)
        if not isinstance(ticker, str) or not ticker.strip():
            raise NewsServiceError(
                "ticker must be a non-empty string", details={"ticker": ticker}
            )
        return ticker.strip()

    @staticmethod
    def _resolve_max_news(context: ServiceContext) -> int:
        """Read and validate the ``max_news`` metadata value.

        Raises:
            NewsServiceError: If ``max_news`` cannot be interpreted as a
                positive integer.
        """
        raw_value = context.get_metadata(MetadataKeys.MAX_NEWS, DEFAULT_MAX_NEWS)
        try:
            max_news = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise NewsServiceError(
                f"max_news must be an integer, got {raw_value!r}",
                details={"max_news": raw_value},
            ) from exc
        if max_news <= 0:
            raise NewsServiceError(
                f"max_news must be a positive integer, got {max_news}",
                details={"max_news": max_news},
            )
        return max_news

    def _fetch_raw_news(self, ticker: str) -> List[Dict[str, Any]]:
        """Fetch and normalize the raw news payload for ``ticker``.

        Delegates the actual external call to :class:`NewsRepository`
        (which returns the payload unchanged), then applies the same
        normalization this method has always applied: a falsy payload
        (``None``, empty) becomes ``[]``, and any non-list payload is
        also treated as ``[]``.

        Args:
            ticker: The stock ticker symbol to fetch news for.

        Returns:
            The raw list of news dicts as returned by ``yfinance`` (may be
            empty if the ticker is invalid or has no recent news).

        Raises:
            NewsServiceError: If the underlying repository call fails.
        """
        try:
            raw_news = self._repository.get_news(ticker)
        except RepositoryError as exc:
            raise NewsServiceError(
                f"Failed to fetch news for ticker '{ticker}'",
                details={"ticker": ticker, "error": exc.details.get("error", str(exc))},
            ) from exc

        raw_news = raw_news or []
        if not isinstance(raw_news, list):
            return []
        return raw_news

    def _normalize_news_item(self, raw_item: Any) -> Dict[str, Any]:
        """Normalize one raw ``yfinance`` news entry into a stable shape.

        Handles both the legacy flat payload and the newer payload nested
        under a ``"content"`` key.

        Args:
            raw_item: A single raw news entry as returned by ``yfinance``.

        Returns:
            A dict with keys ``title``, ``publisher``, ``link``,
            ``published_time``, ``summary``, and ``related_tickers``.
        """
        if not isinstance(raw_item, dict):
            raw_item = {}
        content = raw_item.get("content")
        content = content if isinstance(content, dict) else {}

        title = raw_item.get("title") or content.get("title") or ""
        publisher = self._extract_publisher(raw_item, content)
        link = self._extract_link(raw_item, content)
        published_time = self._normalize_published_time(
            raw_item.get("providerPublishTime", content.get("pubDate"))
        )
        summary = raw_item.get("summary") or content.get("summary") or None

        related_tickers = raw_item.get("relatedTickers")
        if not isinstance(related_tickers, list):
            related_tickers = []

        return {
            "title": title,
            "publisher": publisher,
            "link": link,
            "published_time": published_time,
            "summary": summary,
            "related_tickers": related_tickers,
        }

    @staticmethod
    def _extract_publisher(raw_item: Dict[str, Any], content: Dict[str, Any]) -> str:
        """Extract the publisher name from either payload shape."""
        publisher = raw_item.get("publisher")
        if publisher:
            return str(publisher)
        provider = content.get("provider")
        if isinstance(provider, dict) and provider.get("displayName"):
            return str(provider["displayName"])
        return ""

    @staticmethod
    def _extract_link(raw_item: Dict[str, Any], content: Dict[str, Any]) -> str:
        """Extract the article URL from either payload shape."""
        link = raw_item.get("link")
        if link:
            return str(link)
        for url_field in ("canonicalUrl", "clickThroughUrl"):
            url_obj = content.get(url_field)
            if isinstance(url_obj, dict) and url_obj.get("url"):
                return str(url_obj["url"])
        return ""

    @staticmethod
    def _normalize_published_time(value: Any) -> Optional[str]:
        """Normalize a published-time value into an ISO-8601 UTC string.

        Args:
            value: Either a Unix epoch (``int``/``float``, legacy shape),
                an already-formatted ISO string (newer shape), or ``None``.

        Returns:
            An ISO-8601 UTC timestamp string, the original string
            unchanged, or ``None`` if ``value`` could not be interpreted.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str):
            return value
        return None

    def health_check(self) -> bool:
        """Report whether this service can currently resolve its dependency.

        Mirrors the ``bool``-returning contract shared by every
        ``health_check()`` in the framework (``BaseProvider``,
        ``BaseAgent``, ``BaseService``). Deliberately does not perform a
        live network call: delegates to ``NewsRepository.health_check()``,
        which only verifies that ``yfinance`` (injected or importable) is
        available, so health checks remain fast and safe to call
        frequently. Never raises.

        Returns:
            ``True`` if the ``yfinance`` dependency can be resolved,
            ``False`` otherwise.
        """
        try:
            return self._repository.health_check()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"NewsService.health_check failed: {exc}")
            return False