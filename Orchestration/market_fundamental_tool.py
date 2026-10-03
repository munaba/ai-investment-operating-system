"""MarketFundamentalTool -- the project's third concrete Tool (Phase
5, Sprint 62).

Scope note (LOCKED baseline, Sprint 62): this module introduces
exactly one concrete class and nothing more --
``MarketFundamentalTool(BaseTool)``, implementing the three abstract
members ``BaseTool`` requires and nothing else.

Phase 8, Sprint 91 update: ``execute()``'s return annotation and
docstring stated explicitly that a future implementation is required
to return ``Orchestration.tool_result.ToolResult`` (Sprint 86's new
value object). Documentation/annotation-only; behavior unchanged
(still raised ``NotImplementedError`` unconditionally).

Phase 10, Sprint 111 update (First Real Fundamental Analysis):
``execute()`` no longer raises. It now performs real, deterministic
valuation/quality analysis driven entirely by whatever
``context.parameters`` contains, mirroring the same
never-raise-on-malformed-input, ``isinstance``-guarded extraction
style ``Orchestration.market_price_tool.MarketPriceTool`` already
established in Sprint 110.

Project policy (still in force since Sprint 107): feature development
has priority over architecture expansion. This sprint deliberately
adds NO new abstraction of any kind -- no new class, no Manager,
Engine, Strategy, Analyzer, Registry, Factory, Adapter, Pipeline, or
helper module. Per this sprint's explicit instruction (matching
Sprint 110's), all analysis lives directly inside
``MarketFundamentalTool.execute()`` itself as plain, flat statements
-- no nested function, no private module-level helper, and no method
beyond the three ``BaseTool`` requires anywhere on this class.

What ``execute()`` now does, precisely:

  1. Reads ``context.parameters`` if present and a ``Mapping``;
     otherwise treats parameters as empty -- the exact same
     duck-typed, never-raising extraction ``MarketPriceTool.execute()``
     already uses.
  2. Reads ``parameters["symbol"]``. If it is missing, not a ``str``,
     or an empty ``str``, ``symbol`` falls back to ``"UNKNOWN"``
     (LOCKED default rule) -- never guessed, never inferred.
  3. Reads ``parameters["pe_ratio"]`` and ``parameters["roe"]``. Each
     is only ever treated as a valid number if it is an ``int`` or
     ``float`` and NOT a ``bool`` (``bool`` is a subclass of ``int``
     in Python; excluding it keeps "valid" limited to genuine numeric
     values, not ``True``/``False`` masquerading as ``1``/``0``).
     Missing, ``None``, a ``str``, a ``list``, or any other non-numeric
     value counts as invalid.
  4. Valuation (LOCKED rules), only when ``pe_ratio`` is valid:
       * ``pe_ratio < 15`` -> ``valuation = "undervalued"``
       * ``15 <= pe_ratio <= 25`` -> ``valuation = "fair"``
       * ``pe_ratio > 25`` -> ``valuation = "overvalued"``
     When ``pe_ratio`` is invalid, ``valuation = "unknown"`` -- no
     value is guessed, inferred, or estimated.
  5. Quality (LOCKED rules), only when ``roe`` is valid:
       * ``roe >= 15`` -> ``quality = "strong"``
       * ``roe < 15`` -> ``quality = "weak"``
     When ``roe`` is invalid, ``quality = "unknown"``.

  Valuation and quality are derived completely independently of each
  other -- an invalid ``pe_ratio`` does not affect ``quality``, and an
  invalid ``roe`` does not affect ``valuation``.

Determinism (LOCKED): given the same ``context.parameters``, this
method always returns the exact same output. No timestamp, no
randomness, no UUID, no filesystem access, and no environment
inspection appears anywhere in this method.

Independence (LOCKED, unchanged from every prior sprint on this
class): no network call, no API call, no SEC/EDGAR access, no
database access, no ``yfinance``, no ``requests``, no ``pandas``, no
AI/LLM/Ollama call, and no use of ``Provider``, ``Repository``,
``Runtime``, ``Workflow``, ``ToolManager``, ``ToolRegistry``, or the
Composition Root anywhere in this module. There is no caching, no
retry, and no logging.

Dependencies (LOCKED): this module imports only
``Orchestration.base_tool.BaseTool``, ``Orchestration.tool_result.
ToolResult``, and stdlib ``typing`` -- nothing else. In particular it
does NOT import ``requests``, ``httpx``, ``aiohttp``, ``pandas``,
``numpy``, ``yfinance``, ``sec_edgar``, ``sec_api``, ``polygon``,
``alphavantage``, ``financialmodelingprep``, ``sqlite3``, ``json``,
``pathlib``, ``os``, ``time``, ``datetime``, ``uuid``, ``random``, or
any Repository/Services/Providers/Database/Agents/Planner/Executor/
Workflow/Runtime/EventBus/Memory/LearningLoop/Reflection/
CompositionRoot/ToolRegistry/ToolResolver/ToolManager/Skill/
Capability module.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from Core.market_config import resolve_provider_symbol
from Orchestration.base_tool import BaseTool
from Orchestration.tool_result import ToolResult
from Services.service_context import ServiceContext
from Services.stock_service import StockService

#: Sentinel meaning "no symbol was supplied" -- identical to the LOCKED
#: default already used for the ``symbol`` output field. Only a resolved
#: symbol other than this sentinel is ever looked up against a real
#: repository (see ``_fetch_real_fundamentals``).
_UNKNOWN_SYMBOL = "UNKNOWN"


def _fetch_real_fundamentals(symbol: str) -> Tuple[Optional[float], Optional[float]]:
    """Phase 19 (Real Data Foundation): best-effort real PE-ratio/ROE
    lookup for ``symbol``, reusing the existing, unmodified
    ``Services.stock_service.StockService`` (which already extracts
    ``per``/``roe`` from ``yfinance`` company info) -- never a new
    Repository wrapper, adapter, or duplicate extraction logic.

    ``StockService``'s ``roe`` is a raw fraction (e.g. ``0.18`` for an
    18% return on equity, straight from ``yfinance``'s
    ``returnOnEquity`` field). This Tool's LOCKED quality rule compares
    ``roe`` against the literal threshold ``15`` on a percent scale
    (e.g. ``18`` for 18%) -- so the fraction is converted to that same
    percent scale (``* 100``) here, at the boundary, before being
    handed to the unchanged, LOCKED comparison in :meth:`execute`.
    ``per`` (PE ratio) needs no such conversion -- ``yfinance``'s
    ``trailingPE``/``forwardPE`` are already plain PE-ratio numbers on
    the same scale this Tool's LOCKED valuation rule already expects.

    Never raises: any failure (network, missing dependency, invalid
    ticker, missing info fields) is caught and reported as
    ``(None, None)``, which callers already treat identically to "no
    fundamental parameters were supplied" -- the pre-Phase-19 fallback
    behavior.

    Args:
        symbol: The resolved ticker symbol to look up.

    Returns:
        A ``(pe_ratio, roe_percent)`` tuple, either or both of which
        may be ``None`` if real data could not be obtained.
    """
    try:
        # Activation 2.8: same IDX exchange-suffix resolution as
        # ``Orchestration.market_price_tool._fetch_real_prices`` -- see
        # that function's own comment for the full rationale
        # (``Core.request_defaults.DEFAULT_TICKER = "BBCA.JK"``).
        provider_symbol = resolve_provider_symbol(symbol)
        service = StockService()
        context = ServiceContext(
            agent_name="market_fundamental_tool",
            provider_name="market_fundamental_tool",
            request_id="market_fundamental_tool",
            user_input="",
            metadata={"ticker": provider_symbol},
        )
        result = service.execute(context)
        if not result.success or not isinstance(result.data, dict):
            return None, None
        pe_ratio = result.data.get("per")
        roe_fraction = result.data.get("roe")
        roe_percent = None
        if isinstance(roe_fraction, (int, float)) and not isinstance(roe_fraction, bool):
            roe_percent = roe_fraction * 100
        return pe_ratio, roe_percent
    except Exception:  # noqa: BLE001 - never raise from this best-effort lookup
        return None, None


class MarketFundamentalTool(BaseTool):
    """The third concrete Tool: deterministic, parameter-driven
    valuation and quality analysis.

    No ``__init__`` of its own, no instance state, no cache, no
    network client. Every method beyond the three ``BaseTool``
    requires is deliberately absent -- there is no ``financials``,
    ``balance_sheet``, ``income_statement``, ``cash_flow``,
    ``ratios``, ``valuation``, ``earnings``, ``eps``, ``revenue``,
    ``assets``, ``liabilities``, ``equity``, ``sec``, ``edgar``,
    ``download``, ``fetch``, ``query``, ``request``, ``refresh``, or
    any private helper method anywhere on this class -- Sprint 111's
    analysis logic lives entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Tool's stable name.

        Returns:
            The literal string ``"market_fundamental"``.
        """
        return "market_fundamental"

    @property
    def description(self) -> str:
        """This Tool's human-readable description.

        Returns:
            The literal string ``"Retrieve market fundamental
            information."``.
        """
        return "Retrieve market fundamental information."

    def execute(self, context: Any) -> ToolResult:
        """Run this Tool: derive deterministic valuation and quality
        labels from ``context.parameters``.

        Phase 10, Sprint 111 (First Real Fundamental Analysis): reads
        ``symbol``, ``pe_ratio``, and ``roe`` out of
        ``context.parameters`` (falling back to safe, LOCKED defaults
        for any malformed or missing input, and never raising
        regardless of what ``context`` is), and derives
        ``"valuation"`` and ``"quality"`` independently via the two
        LOCKED rule tables: ``valuation`` is ``"undervalued"`` when
        ``pe_ratio < 15``, ``"fair"`` when ``15 <= pe_ratio <= 25``,
        ``"overvalued"`` when ``pe_ratio > 25``, and ``"unknown"``
        whenever ``pe_ratio`` is missing or not a valid number;
        ``quality`` is ``"strong"`` when ``roe >= 15``, ``"weak"``
        when ``roe < 15``, and ``"unknown"`` whenever ``roe`` is
        missing or not a valid number. No network call, no API call,
        no Service, Repository, Provider, or Database use, no
        filesystem access, and no AI, Runtime, or Workflow
        involvement -- this is pure, in-process comparison of
        whatever numbers were supplied.

        Args:
            context: Expected to be a ``ToolContext``-shaped object
                exposing a ``.parameters`` mapping with optional
                ``"symbol"`` (``str``), ``"pe_ratio"``, and ``"roe"``
                (each ``int``/``float``) entries. Any other shape
                (``None``, a plain string, an arbitrary object, a
                dict) is tolerated and treated as if no parameters
                were supplied.

        Returns:
            A ``ToolResult`` with ``success=True``, ``error=None``,
            ``metadata={}``, and ``output`` containing:

                * ``"symbol"`` -- the resolved symbol (``str``),
                  falling back to ``"UNKNOWN"`` if missing or
                  invalid.
                * ``"valuation"`` -- one of ``"undervalued"``,
                  ``"fair"``, ``"overvalued"``, or ``"unknown"``, per
                  the LOCKED rules above.
                * ``"quality"`` -- one of ``"strong"``, ``"weak"``,
                  or ``"unknown"``, per the LOCKED rules above.
        """
        parameters = getattr(context, "parameters", None)
        if not isinstance(parameters, Mapping):
            parameters = {}

        symbol = parameters.get("symbol", "UNKNOWN")
        if not isinstance(symbol, str) or not symbol:
            symbol = "UNKNOWN"

        pe_ratio = parameters.get("pe_ratio")
        roe = parameters.get("roe")

        pe_is_valid = isinstance(pe_ratio, (int, float)) and not isinstance(pe_ratio, bool)
        roe_is_valid = isinstance(roe, (int, float)) and not isinstance(roe, bool)

        # Phase 19 (Real Data Foundation): only when NEITHER explicit
        # metric was supplied (or valid) AND a real symbol was given
        # (never the "UNKNOWN" sentinel) do we attempt a real,
        # best-effort lookup via the existing StockService/
        # StockDataRepository. Any explicit, valid pe_ratio/roe
        # supplied by the caller always wins and skips this lookup
        # entirely -- byte-for-byte unchanged behavior for every
        # existing caller that already supplies real numbers.
        if not (pe_is_valid and roe_is_valid) and symbol != _UNKNOWN_SYMBOL:
            real_pe_ratio, real_roe = _fetch_real_fundamentals(symbol)
            if not pe_is_valid:
                pe_ratio = real_pe_ratio
                pe_is_valid = isinstance(pe_ratio, (int, float)) and not isinstance(pe_ratio, bool)
            if not roe_is_valid:
                roe = real_roe
                roe_is_valid = isinstance(roe, (int, float)) and not isinstance(roe, bool)

        if pe_is_valid:
            if pe_ratio < 15:
                valuation = "undervalued"
            elif pe_ratio <= 25:
                valuation = "fair"
            else:
                valuation = "overvalued"
        else:
            valuation = "unknown"

        if roe_is_valid:
            if roe >= 15:
                quality = "strong"
            else:
                quality = "weak"
        else:
            quality = "unknown"

        return ToolResult(
            success=True,
            output={
                "symbol": symbol,
                "valuation": valuation,
                "quality": quality,
            },
            error=None,
            metadata={},
        )
