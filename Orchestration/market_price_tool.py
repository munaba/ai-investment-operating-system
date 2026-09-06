"""MarketPriceTool -- the project's first concrete Tool (Phase 5,
Sprint 60).

Phase 8, Sprint 89 update: ``execute()``'s return annotation and
docstring stated explicitly that a future implementation is required
to return ``Orchestration.tool_result.ToolResult`` (Sprint 86's new
value object). Documentation/annotation-only; behavior unchanged.

Phase 9, Sprint 99 update (First Real Tool Implementation):
``execute()`` stopped raising and began returning a fixed, literal
``ToolResult`` -- ``{"symbol": "UNKNOWN", "price": None}`` on every
call, regardless of ``context``.

Phase 10, Sprint 110 update (First Real Market Analysis):
``execute()`` is no longer a fixed literal. It now performs real,
deterministic trend analysis driven entirely by whatever
``context.parameters`` contains, mirroring the same
never-raise-on-malformed-input, ``isinstance``-guarded extraction
style ``Orchestration.market_news_tool.MarketNewsTool`` already
established in Sprint 107.

New project policy (Sprint 107 onward, still in force): feature
development has priority over architecture expansion. This sprint
deliberately adds NO new abstraction of any kind -- no new class, no
Manager, Analyzer, Strategy, Engine, Registry, Factory, Adapter,
Pipeline, Utility, or helper module. Unlike ``MarketNewsTool`` (which
factors its extraction/classification logic into a handful of
private, module-level pure functions), this sprint's instructions are
explicit that all analysis must remain inside
``MarketPriceTool.execute()`` itself -- so every step below (reading
parameters, validating the two price values, and deriving the trend)
is written as plain, flat statements directly in that one method's
body. There is no nested function, no private module-level helper,
and no method beyond the three ``BaseTool`` requires anywhere on this
class.

What ``execute()`` now does, precisely:

  1. Reads ``context.parameters`` if present and a ``Mapping``;
     otherwise treats parameters as empty -- the exact same
     duck-typed, never-raising extraction ``MarketNewsTool.execute()``
     already uses.
  2. Reads ``parameters["symbol"]``. If it is missing, not a ``str``,
     or an empty ``str``, ``symbol`` falls back to ``"UNKNOWN"``
     (LOCKED default rule) -- never guessed, never inferred.
  3. Reads ``parameters["current_price"]`` and
     ``parameters["previous_price"]``. Each is only ever treated as a
     valid price if it is an ``int`` or ``float`` and NOT a ``bool``
     (``bool`` is a subclass of ``int`` in Python; excluding it keeps
     "valid price" limited to genuine numeric values, not ``True``/
     ``False`` masquerading as ``1``/``0``). Anything else -- missing,
     ``None``, a ``str``, a ``list``, ``NaN`` is not specially
     excluded since it is still a ``float`` and compares normally --
     counts as invalid.
  4. If BOTH prices are valid numbers (LOCKED trend rules):
       * ``current_price > previous_price`` -> ``trend = "bullish"``
       * ``current_price < previous_price`` -> ``trend = "bearish"``
       * ``current_price == previous_price`` -> ``trend = "neutral"``
     and ``price`` is set to ``current_price``.
  5. If either price is missing or invalid (LOCKED default rule):
     ``price = None`` and ``trend = "unknown"``. No value is guessed,
     inferred, or estimated.

Determinism (LOCKED): given the same ``context.parameters``, this
method always returns the exact same output. No timestamp, no
randomness, no UUID, no filesystem access, and no environment
inspection appears anywhere in this method.

Independence (LOCKED, unchanged from every prior sprint on this
class): no network call, no API call, no database access, no
``yfinance``, no ``requests``, no ``pandas``, no AI/LLM/Ollama call,
and no use of ``Provider``, ``Repository``, ``Runtime``, ``Workflow``,
``ToolManager``, ``ToolRegistry``, or the Composition Root anywhere in
this module. There is no caching, no retry, and no logging.

Dependencies (LOCKED): this module imports only
``Orchestration.base_tool.BaseTool``, ``Orchestration.tool_result.
ToolResult``, and stdlib ``typing`` -- nothing else. In particular it
does NOT import ``requests``, ``httpx``, ``aiohttp``, ``urllib``,
``pandas``, ``numpy``, ``yfinance``, ``ccxt``, ``polygon``, ``alpaca``,
``finnhub``, ``binance``, ``sqlite3``, ``json``, ``pathlib``, ``os``,
``time``, ``datetime``, ``uuid``, ``random``, or any Repository/
Services/Providers/Database/Agents/Planner/Executor/Workflow/Runtime/
EventBus/Memory/LearningLoop/Reflection/CompositionRoot/ToolRegistry/
ToolResolver/ToolManager/Skill/Capability module.
"""

from __future__ import annotations

from math import isfinite
from numbers import Real
from typing import Any, Mapping, Optional, Tuple

from Core.market_config import resolve_provider_symbol
from Orchestration.base_tool import BaseTool
from Orchestration.tool_result import ToolResult
from Services.service_context import ServiceContext
from Services.stock_service import StockService

#: Sentinel meaning "no symbol was supplied" -- identical to the LOCKED
#: default already used for the ``symbol`` output field. Only a resolved
#: symbol other than this sentinel is ever looked up against a real
#: repository (see ``_fetch_real_prices``); this preserves every existing
#: no-symbol/invalid-symbol scenario byte-for-byte.
_UNKNOWN_SYMBOL = "UNKNOWN"


def _fetch_real_prices(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """Phase 19 (Real Data Foundation): best-effort real current/previous
    close lookup for ``symbol``, reusing the existing, unmodified
    ``Services.stock_service.StockService`` -- never a new Repository
    wrapper, adapter, or duplicate fetch logic.

    Never raises: any failure (network, missing dependency, invalid
    ticker, insufficient history) is caught and reported as
    ``(None, None)``, which callers already treat identically to
    "no price parameters were supplied" -- the pre-Phase-19 fallback
    behavior.

    Args:
        symbol: The resolved ticker symbol to look up.

    Returns:
        A ``(current_price, previous_price)`` tuple, either or both of
        which may be ``None`` if real data could not be obtained.
    """
    try:
        # Activation 2.8: this project's real data provider (StockService
        # -> yfinance) resolves IDX-listed tickers only under their
        # Yahoo Finance exchange-suffixed form -- the exact convention
        # already established, unchanged, by this project's own
        # ``Core.request_defaults.DEFAULT_TICKER = "BBCA.JK"``. A bare
        # ticker with no "." (e.g. the "BBCA" a watchlist stores) is
        # resolved to that same ".JK" form here, at this real-provider
        # boundary only -- never changes what ``symbol`` is echoed back
        # in this Tool's own output, and never touches a symbol that
        # already carries an exchange suffix.
        provider_symbol = resolve_provider_symbol(symbol)
        service = StockService()
        context = ServiceContext(
            agent_name="market_price_tool",
            provider_name="market_price_tool",
            request_id="market_price_tool",
            user_input="",
            metadata={"ticker": provider_symbol},
        )
        result = service.execute(context)
        if not result.success or not isinstance(result.data, dict):
            return None, None
        history = result.data.get("history")
        if not isinstance(history, list):
            return None, None

        # Yahoo can include a latest in-progress/session row whose Close is
        # NaN. That row is not a usable observation and must not turn an
        # otherwise valid history into INSUFFICIENT_DATA. Select the newest
        # two finite numeric closes instead.
        valid_closes = []
        for record in reversed(history):
            if not isinstance(record, dict):
                continue
            close = record.get("Close")
            if isinstance(close, Real) and not isinstance(close, bool):
                try:
                    numeric_close = float(close)
                except (TypeError, ValueError):
                    continue
                if isfinite(numeric_close):
                    valid_closes.append(numeric_close)
                    if len(valid_closes) == 2:
                        break

        if not valid_closes:
            return None, None
        current_price = valid_closes[0]
        previous_price = valid_closes[1] if len(valid_closes) >= 2 else None
        return current_price, previous_price
    except Exception:  # noqa: BLE001 - never raise from this best-effort lookup
        return None, None


class MarketPriceTool(BaseTool):
    """The first concrete Tool: deterministic, parameter-driven
    price-trend analysis.

    No ``__init__`` of its own, no instance state, no cache, no
    network client. Every method beyond the three ``BaseTool``
    requires is deliberately absent -- there is no ``fetch``,
    ``download``, ``request``, ``query``, ``history``, ``latest``,
    ``ohlcv``, ``candles``, ``ticker``, ``quote``, ``stream``,
    ``subscribe``, ``connect``, ``disconnect``, ``refresh``,
    ``update``, ``reset``, ``validate``, ``build``, ``prepare``, or
    any private helper method anywhere on this class -- Sprint 110's
    analysis logic lives entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Tool's stable name.

        Returns:
            The literal string ``"market_price"``.
        """
        return "market_price"

    @property
    def description(self) -> str:
        """This Tool's human-readable description.

        Returns:
            The literal string ``"Retrieve market price
            information."``.
        """
        return "Retrieve market price information."

    def execute(self, context: Any) -> ToolResult:
        """Run this Tool: derive a deterministic price trend from
        ``context.parameters``.

        Phase 10, Sprint 110 (First Real Market Analysis): reads
        ``symbol``, ``current_price``, and ``previous_price`` out of
        ``context.parameters`` (falling back to safe, LOCKED defaults
        for any malformed or missing input, and never raising
        regardless of what ``context`` is), and derives ``trend``
        via the LOCKED four-rule table: ``"bullish"`` when
        ``current_price > previous_price``, ``"bearish"`` when
        ``current_price < previous_price``, ``"neutral"`` when they
        are equal, and ``"unknown"`` whenever either price is missing
        or not a valid number -- in which case ``price`` is also
        ``None``. No network call, no API call, no Service,
        Repository, Provider, or Database use, no filesystem access,
        and no AI, Runtime, or Workflow involvement -- this is pure,
        in-process comparison of whatever numbers were supplied.

        Args:
            context: Expected to be a ``ToolContext``-shaped object
                exposing a ``.parameters`` mapping with optional
                ``"symbol"`` (``str``), ``"current_price"``, and
                ``"previous_price"`` (each ``int``/``float``)
                entries. Any other shape (``None``, a plain string,
                an arbitrary object, a dict) is tolerated and treated
                as if no parameters were supplied.

        Returns:
            A ``ToolResult`` with ``success=True``, ``error=None``,
            ``metadata={}``, and ``output`` containing:

                * ``"symbol"`` -- the resolved symbol (``str``),
                  falling back to ``"UNKNOWN"`` if missing or
                  invalid.
                * ``"price"`` -- ``current_price`` if both prices
                  were valid numbers, otherwise ``None``.
                * ``"trend"`` -- one of ``"bullish"``, ``"bearish"``,
                  ``"neutral"``, or ``"unknown"``, per the LOCKED
                  rules above.
        """
        parameters = getattr(context, "parameters", None)
        if not isinstance(parameters, Mapping):
            parameters = {}

        symbol = parameters.get("symbol", "UNKNOWN")
        if not isinstance(symbol, str) or not symbol:
            symbol = "UNKNOWN"

        current_price = parameters.get("current_price")
        previous_price = parameters.get("previous_price")

        current_is_valid = isinstance(current_price, (int, float)) and not isinstance(current_price, bool)
        previous_is_valid = isinstance(previous_price, (int, float)) and not isinstance(previous_price, bool)

        # Phase 19 (Real Data Foundation): only when NEITHER explicit
        # price was supplied (or valid) AND a real symbol was given
        # (never the "UNKNOWN" sentinel) do we attempt a real,
        # best-effort lookup via the existing StockService/
        # StockDataRepository. Any explicit, valid current_price/
        # previous_price supplied by the caller always wins and skips
        # this lookup entirely -- byte-for-byte unchanged behavior for
        # every existing caller that already supplies real numbers.
        if not (current_is_valid and previous_is_valid) and symbol != _UNKNOWN_SYMBOL:
            real_current, real_previous = _fetch_real_prices(symbol)
            if not current_is_valid:
                current_price = real_current
                current_is_valid = isinstance(current_price, (int, float)) and not isinstance(current_price, bool)
            if not previous_is_valid:
                previous_price = real_previous
                previous_is_valid = isinstance(previous_price, (int, float)) and not isinstance(previous_price, bool)

        if current_is_valid and previous_is_valid:
            price = current_price
            if current_price > previous_price:
                trend = "bullish"
            elif current_price < previous_price:
                trend = "bearish"
            else:
                trend = "neutral"
        else:
            price = None
            trend = "unknown"

        return ToolResult(
            success=True,
            output={
                "symbol": symbol,
                "price": price,
                "trend": trend,
            },
            error=None,
            metadata={},
        )
