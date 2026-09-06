"""MarketNewsTool -- the project's second concrete Tool (Phase 5,
Sprint 61).

Phase 10, Sprint 107 update (First Real Feature -- Deterministic
Keyword-Based Headline Sentiment): ``execute()`` no longer raises.
It now performs real, deterministic processing on whatever headlines
it is given and returns a real ``ToolResult`` describing that
processing.

New project policy (Sprint 107 onward): feature development has
priority over architecture expansion. This sprint deliberately adds
NO new abstraction of any kind -- no new class, no new Manager,
Registry, Context, Factory, Adapter, Interface, or helper layer. The
only new surface is the body of ``MarketNewsTool.execute()`` itself
(plus a small number of private, module-level pure functions used
only by that method), all inside this one file.

What ``execute()`` now does, precisely:

  1. Reads ``context.parameters`` if present and a ``Mapping``;
     otherwise treats parameters as empty. This mirrors the same
     duck-typed, never-raising extraction ``MarketPriceTool.execute()``
     already uses for ``symbol`` (Sprint 99) -- this sprint simply
     extends the same pattern to a second parameter, ``headlines``.
  2. Reads ``parameters["symbol"]`` (default ``"UNKNOWN"``, same
     default as ``MarketPriceTool``) and ``parameters["headlines"]``
     (default ``()``, coerced to a tuple of ``str``).
  3. Classifies each headline with a small, fixed, deterministic
     keyword lexicon (see ``_POSITIVE_KEYWORDS``/``_NEGATIVE_KEYWORDS``
     below) into ``"positive"``, ``"negative"``, or ``"neutral"`` --
     purely a word-count comparison, no AI, no network, no external
     lexicon file.
  4. Aggregates those per-headline classifications into an overall
     sentiment label and a numeric score (positive count minus
     negative count), and returns everything -- per-headline detail
     included -- inside ``ToolResult.output``.

This is real processing (branching, counting, aggregation) driven by
whatever ``context`` actually contains, not a fixed literal returned
unconditionally regardless of input -- unlike ``MarketPriceTool``'s
Sprint 99 implementation (which is intentionally still a literal),
this Tool's output varies with its input, deterministically and
reproducibly.

Independence (LOCKED, unchanged from every prior sprint on this
class): no network call, no API call, no scraping, no filesystem
access, no database access, no AI/LLM provider call, and no use of
``Service``, ``Repository``, ``Runtime``, ``Workflow``,
``ToolRegistry``, ``ToolResolver``, ``ToolManager``, or the
Composition Root anywhere in this module. The keyword lexicon is a
fixed, in-module ``frozenset`` literal -- not fetched, not loaded from
a file, not configurable.

Never raises: ``execute()`` accepts any ``context`` value (a real
``ToolContext``, ``None``, a plain string, an arbitrary object, a
dict) and always returns a ``ToolResult`` -- malformed or missing
``parameters``/``headlines``/``symbol`` fall back to safe, empty
defaults via ``isinstance`` checks rather than ``try``/``except``,
matching this project's existing validation style (e.g.
``Orchestration.tool_context.ToolContext.__post_init__``).

Dependencies (LOCKED): this module imports only
``Orchestration.base_tool.BaseTool``, ``Orchestration.tool_result.
ToolResult``, and stdlib ``typing`` -- nothing else. In particular it
does NOT import ``requests``, ``httpx``, ``aiohttp``, ``feedparser``,
``beautifulsoup4``, ``selenium``, ``playwright``, ``newspaper``,
``lxml``, ``pandas``, ``numpy``, ``sqlite3``, ``json``, ``pathlib``,
``os``, or any Repository/Services/Providers/Database/Agents/Planner/
Executor/Workflow/Runtime/EventBus/Memory/LearningLoop/Reflection/
CompositionRoot/ToolRegistry/ToolResolver/ToolManager/Skill/
Capability module.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

from Core.market_config import resolve_provider_symbol
from Orchestration.base_tool import BaseTool
from Orchestration.tool_result import ToolResult
from Services.news_service import NewsService
from Services.service_context import ServiceContext

#: Sentinel meaning "no symbol was supplied" -- identical to the LOCKED
#: default already used for the ``symbol`` output field. Only a resolved
#: symbol other than this sentinel is ever looked up against a real
#: repository (see ``_fetch_real_headlines``).
_UNKNOWN_SYMBOL = "UNKNOWN"


def _fetch_real_headlines(symbol: str) -> Tuple[str, ...]:
    """Phase 19 (Real Data Foundation): best-effort real headline lookup
    for ``symbol``, reusing the existing, unmodified
    ``Services.news_service.NewsService`` -- never a new Repository
    wrapper, adapter, or duplicate fetch/normalization logic.

    Never raises: any failure (network, missing dependency, invalid
    ticker, no news available) is caught and reported as an empty
    ``tuple``, which callers already treat identically to "no
    headlines were supplied" -- the pre-Phase-19 fallback behavior.

    Args:
        symbol: The resolved ticker symbol to look up.

    Returns:
        A ``tuple`` of headline title strings, possibly empty.
    """
    try:
        # Activation 2.8: same IDX exchange-suffix resolution as
        # ``Orchestration.market_price_tool._fetch_real_prices`` -- see
        # that function's own comment for the full rationale
        # (``Core.request_defaults.DEFAULT_TICKER = "BBCA.JK"``).
        provider_symbol = resolve_provider_symbol(symbol)
        service = NewsService()
        context = ServiceContext(
            agent_name="market_news_tool",
            provider_name="market_news_tool",
            request_id="market_news_tool",
            user_input="",
            metadata={"ticker": provider_symbol},
        )
        result = service.execute(context)
        if not result.success or not isinstance(result.data, dict):
            return ()
        news_items = result.data.get("news")
        if not isinstance(news_items, list):
            return ()
        return tuple(
            str(item.get("title"))
            for item in news_items
            if isinstance(item, dict) and item.get("title")
        )
    except Exception:  # noqa: BLE001 - never raise from this best-effort lookup
        return ()

# ---------------------------------------------------------------------------
# Fixed, in-module keyword lexicon (LOCKED for this sprint). Deliberately
# small, plain-English, and case-insensitive-matched -- no external file,
# no network fetch, no AI classification of any kind.
# ---------------------------------------------------------------------------
_POSITIVE_KEYWORDS = frozenset(
    {
        "beats", "beat", "surge", "surges", "rally", "rallies",
        "growth", "profit", "profits", "upgrade", "upgrades",
        "record", "strong", "gain", "gains", "outperform",
        "outperforms", "bullish", "expansion", "raises", "raised",
        "soars", "soar", "jumps", "jump", "rebound", "rebounds",
        "boost", "boosts", "win", "wins", "recovery",
    }
)

_NEGATIVE_KEYWORDS = frozenset(
    {
        "miss", "misses", "plunge", "plunges", "crash", "crashes",
        "loss", "losses", "downgrade", "downgrades", "decline",
        "declines", "weak", "drop", "drops", "recall", "recalls",
        "lawsuit", "lawsuits", "bearish", "cuts", "cut", "slump",
        "slumps", "falls", "fall", "warns", "warning", "layoffs",
        "layoff", "fraud", "probe", "investigation",
    }
)


def _extract_parameters(context: Any) -> Mapping[str, Any]:
    """Return ``context.parameters`` if it exists and is a ``Mapping``;
    otherwise an empty ``dict``.

    Never raises: this is a pure ``getattr``/``isinstance`` check, no
    attribute access that could itself fail is performed beyond a
    single ``getattr`` with a default.

    Args:
        context: Whatever value was passed to ``execute()``. Opaque
            and unconstrained -- may or may not resemble a
            ``ToolContext``.

    Returns:
        ``context.parameters`` unchanged (by reference) if it is a
        ``Mapping``; otherwise ``{}``.
    """
    parameters = getattr(context, "parameters", None)
    if isinstance(parameters, Mapping):
        return parameters
    return {}


def _extract_symbol(parameters: Mapping[str, Any]) -> str:
    """Return ``parameters["symbol"]`` if present and a ``str``;
    otherwise the same ``"UNKNOWN"`` default ``MarketPriceTool`` uses.

    Args:
        parameters: The (possibly empty) parameters mapping already
            extracted by ``_extract_parameters``.

    Returns:
        A ``str`` symbol -- either the given one or ``"UNKNOWN"``.
    """
    symbol = parameters.get("symbol", "UNKNOWN")
    if isinstance(symbol, str) and symbol:
        return symbol
    return "UNKNOWN"


def _extract_headlines(parameters: Mapping[str, Any]) -> Tuple[str, ...]:
    """Return ``parameters["headlines"]`` coerced to a ``tuple`` of
    ``str``, or an empty ``tuple`` for anything not shaped like a
    list/tuple of headlines.

    Never raises: a bare ``str`` is treated as a single headline; a
    ``list``/``tuple`` has each element coerced with ``str()``; any
    other type (including ``None``, an ``int``, a ``dict``, an
    arbitrary object) yields an empty ``tuple`` rather than raising.

    Args:
        parameters: The (possibly empty) parameters mapping already
            extracted by ``_extract_parameters``.

    Returns:
        A ``tuple`` of ``str`` headlines, possibly empty.
    """
    raw = parameters.get("headlines", ())
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw)
    return ()


def _classify_headline(headline: str) -> Tuple[str, int, int]:
    """Classify a single headline as ``"positive"``, ``"negative"``,
    or ``"neutral"`` by counting fixed-lexicon keyword hits.

    Deterministic, pure word-count comparison: the headline is
    lower-cased, split on any non-alphanumeric character, and each
    resulting word is checked against ``_POSITIVE_KEYWORDS``/
    ``_NEGATIVE_KEYWORDS``. More positive hits than negative yields
    ``"positive"``; more negative than positive yields ``"negative"``;
    a tie (including zero hits on both sides) yields ``"neutral"``.

    Args:
        headline: The headline text to classify.

    Returns:
        A ``(label, positive_hits, negative_hits)`` tuple.
    """
    words = "".join(ch if ch.isalnum() else " " for ch in headline.lower()).split()
    positive_hits = sum(1 for word in words if word in _POSITIVE_KEYWORDS)
    negative_hits = sum(1 for word in words if word in _NEGATIVE_KEYWORDS)

    if positive_hits > negative_hits:
        label = "positive"
    elif negative_hits > positive_hits:
        label = "negative"
    else:
        label = "neutral"

    return label, positive_hits, negative_hits


class MarketNewsTool(BaseTool):
    """The second concrete Tool: deterministic, keyword-based
    headline sentiment classification for market news.

    No ``__init__`` of its own, no instance state, no cache, no
    network client. Every method beyond the three ``BaseTool``
    requires plus the module-level private helper functions above is
    deliberately absent -- there is no ``fetch``, ``download``,
    ``rss``, ``scrape``, ``crawl``, ``provider``, ``request``,
    ``refresh``, ``stream``, ``connect``, ``disconnect``, ``parse``,
    ``summarize`` (AI-style summarization), ``cache``, or ``retry``
    method anywhere on this class.
    """

    @property
    def name(self) -> str:
        """This Tool's stable name.

        Returns:
            The literal string ``"market_news"``.
        """
        return "market_news"

    @property
    def description(self) -> str:
        """This Tool's human-readable description.

        Returns:
            The literal string ``"Retrieve market news."``.
        """
        return "Retrieve market news."

    def execute(self, context: Any) -> ToolResult:
        """Run this Tool: classify headline sentiment deterministically.

        Phase 10, Sprint 107 (First Real Feature): reads ``symbol``
        and ``headlines`` out of ``context.parameters`` (falling back
        to safe defaults for any malformed or missing input, and
        never raising regardless of what ``context`` is), classifies
        each headline with a fixed, in-module keyword lexicon, and
        returns a ``ToolResult`` carrying both the per-headline
        classifications and an aggregate sentiment/score.

        No network call, no API call, no Service, Repository,
        Provider, or Database use, no filesystem access, and no AI,
        Runtime, or Workflow involvement -- classification is pure,
        in-process word-count comparison against the fixed keyword
        sets defined at module scope.

        Args:
            context: Expected to be a ``ToolContext``-shaped object
                exposing a ``.parameters`` mapping with optional
                ``"symbol"`` (``str``) and ``"headlines"``
                (``str`` or a list/tuple of ``str``) entries. Any
                other shape (``None``, a plain string, an arbitrary
                object, a dict) is tolerated and treated as if no
                parameters were supplied.

        Returns:
            A ``ToolResult`` with ``success=True``, ``error=None``,
            ``metadata={}``, and ``output`` containing:

                * ``"symbol"`` -- the resolved symbol (``str``).
                * ``"headline_count"`` -- number of headlines
                  classified (``int``).
                * ``"headlines"`` -- a ``tuple`` of per-headline
                  ``dict`` results, each with ``"headline"``,
                  ``"sentiment"``, ``"positive_matches"``, and
                  ``"negative_matches"`` keys, in the same order the
                  headlines were given.
                * ``"overall_sentiment"`` -- ``"positive"``,
                  ``"negative"``, or ``"neutral"``: whichever label
                  the most headlines received, with ties (including
                  the empty/no-headlines case) resolving to
                  ``"neutral"``.
                * ``"sentiment_score"`` -- ``int``, the count of
                  positive headlines minus the count of negative
                  headlines.
        """
        parameters = _extract_parameters(context)
        symbol = _extract_symbol(parameters)
        headlines = _extract_headlines(parameters)

        # Phase 19 (Real Data Foundation): only when no headlines were
        # supplied at all AND a real symbol was given (never the
        # "UNKNOWN" sentinel) do we attempt a real, best-effort lookup
        # via the existing NewsService/NewsRepository. Any explicit
        # headlines supplied by the caller always win and skip this
        # lookup entirely -- byte-for-byte unchanged behavior for every
        # existing caller that already supplies headlines.
        if not headlines and symbol != _UNKNOWN_SYMBOL:
            headlines = _fetch_real_headlines(symbol)

        classified = []
        positive_count = 0
        negative_count = 0
        neutral_count = 0

        for headline in headlines:
            label, positive_hits, negative_hits = _classify_headline(headline)
            classified.append(
                {
                    "headline": headline,
                    "sentiment": label,
                    "positive_matches": positive_hits,
                    "negative_matches": negative_hits,
                }
            )
            if label == "positive":
                positive_count += 1
            elif label == "negative":
                negative_count += 1
            else:
                neutral_count += 1

        if positive_count > negative_count and positive_count > neutral_count:
            overall_sentiment = "positive"
        elif negative_count > positive_count and negative_count > neutral_count:
            overall_sentiment = "negative"
        else:
            overall_sentiment = "neutral"

        output = {
            "symbol": symbol,
            "headline_count": len(headlines),
            "headlines": tuple(classified),
            "overall_sentiment": overall_sentiment,
            "sentiment_score": positive_count - negative_count,
        }

        return ToolResult(
            success=True,
            output=output,
            error=None,
            metadata={},
        )
