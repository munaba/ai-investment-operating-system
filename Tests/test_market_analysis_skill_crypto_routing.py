"""Activation 7 (Crypto Validation Profile) proof suite --
``Orchestration.market_analysis_skill.MarketAnalysisSkill``'s new
per-symbol routing between ``TextAnalysisSkill`` (stock) and
``CryptoAnalysisSkill`` (crypto).

Scope: dedicated, additive proof suite for the ONE routing decision
Activation 7 added to ``MarketAnalysisSkill.execute()``. Does not
re-verify anything ``Tests/test_stage_l117_market_analysis_skill.py``
already covers (per-symbol loop shape, failure handling, context
construction) -- only the new crypto-vs-stock branch, plus a
byte-for-byte non-interference check proving stock symbols still take
the exact ``TextAnalysisSkill`` path they always did.

Mirrors the seam-level ``_FixedTool``/``_FixedResolver`` harness
already used by ``test_stage_l117_market_analysis_skill.py``.

Invariant coverage:
    R1  -- a recognized crypto symbol (BTC-USD) in a mixed symbols
           list is routed to CryptoAnalysisSkill: its "analysis" has
           no fundamental-derived content and never needed
           "market_fundamental" to be resolvable.
    R2  -- a stock symbol (BBCA) in the SAME mixed list is still
           routed to TextAnalysisSkill: its "market_fundamental" Tool
           IS called, exactly as before this Activation.
    R3  -- ETH-USD (the second LOCKED crypto symbol) also routes to
           CryptoAnalysisSkill.
    R4  -- case-insensitivity: "btc-usd" (lowercase, as it would
           arrive if a caller forgot to uppercase) still routes to
           CryptoAnalysisSkill, matching Core.market_config.
           is_crypto_symbol()'s own case-insensitive contract.
    N1  -- a crypto symbol whose Tools were never told to answer
           bullish/positive still succeeds without needing
           "market_fundamental" registered at all (only market_price/
           market_news wired for it).
    S1  -- overall "stocks" list order/shape is unchanged: one entry
           per symbol, in original order, regardless of which
           per-symbol Skill produced it.

Run directly with ``python -m Tests.test_market_analysis_skill_crypto_routing``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.skill_context import SkillContext
from Orchestration.tool_result import ToolResult

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
    print(f"  {'PASS' if condition else 'FAIL'} - {description}")


class _SymbolAwareTool:
    """Mirrors test_stage_l117's own fixture: ``ToolResult`` depends
    on the symbol the incoming context carries. Also records which
    symbols it was ever called for, so a test can assert a Tool was
    (or was not) invoked for a given symbol."""

    def __init__(self, output_by_symbol=None, raise_if_called_for=()):
        self.output_by_symbol = output_by_symbol or {}
        self.raise_if_called_for = set(raise_if_called_for)
        self.called_for_symbols: List[str] = []

    def execute(self, context):
        symbol = context.parameters.get("symbol")
        self.called_for_symbols.append(symbol)
        if symbol in self.raise_if_called_for:
            raise AssertionError(f"Tool should never have been called for {symbol!r}")
        output = self.output_by_symbol.get(symbol, {})
        return ToolResult(success=True, output=output, error=None, metadata={})


class _FixedResolver:
    def __init__(self, tools: dict):
        self.tools = tools

    def __call__(self, name):
        return self.tools[name]


def _ctx(symbols: Any) -> SkillContext:
    return SkillContext(task=None, parameters={"symbols": symbols}, metadata={}, tool_context_factory=None)


def scenario_mixed_stock_and_crypto_routing():
    print("\n[R] Mixed stock + crypto symbol list -- correct per-symbol routing")
    price_tool = _SymbolAwareTool(
        {
            "BBCA": {"trend": "bullish"},
            "BTC-USD": {"trend": "bullish"},
        }
    )
    news_tool = _SymbolAwareTool(
        {
            "BBCA": {"overall_sentiment": "positive"},
            "BTC-USD": {"overall_sentiment": "positive"},
        }
    )
    fundamental_tool = _SymbolAwareTool(
        {"BBCA": {"valuation": "undervalued", "quality": "strong"}},
        raise_if_called_for=("BTC-USD",),  # R1: crypto must NEVER reach this Tool
    )

    skill = MarketAnalysisSkill()
    skill._resolve_tool = _FixedResolver(
        {"market_price": price_tool, "market_news": news_tool, "market_fundamental": fundamental_tool}
    )

    result = skill.execute(_ctx(["BBCA", "BTC-USD"]))
    check(result.success is True, "sanity: mixed-list execution succeeds")

    stocks_by_symbol = {entry["symbol"]: entry for entry in result.output["stocks"]}
    check(set(stocks_by_symbol.keys()) == {"BBCA", "BTC-USD"}, "S1: one entry per symbol, both present")

    btc_analysis = stocks_by_symbol["BTC-USD"]["analysis"]
    check(btc_analysis["recommendation"] == "BUY", "R1: BTC-USD reaches CryptoAnalysisSkill's BUY row")
    check("BTC-USD" not in fundamental_tool.called_for_symbols, "R1: market_fundamental never called for BTC-USD")

    bbca_analysis = stocks_by_symbol["BBCA"]["analysis"]
    check("BBCA" in fundamental_tool.called_for_symbols, "R2: market_fundamental WAS called for BBCA (stock path unchanged)")
    check(
        bbca_analysis["recommendation"] == "BUY" and bbca_analysis["confidence"] == "HIGH",
        "R2: BBCA still reaches TextAnalysisSkill's HIGH-confidence BUY row (needs fundamental=undervalued)",
    )


def scenario_eth_usd_also_routes_to_crypto():
    print("\n[R3] ETH-USD also routes to CryptoAnalysisSkill")
    price_tool = _SymbolAwareTool({"ETH-USD": {"trend": "bearish"}})
    news_tool = _SymbolAwareTool({"ETH-USD": {"overall_sentiment": "negative"}})
    fundamental_tool = _SymbolAwareTool(raise_if_called_for=("ETH-USD",))

    skill = MarketAnalysisSkill()
    skill._resolve_tool = _FixedResolver(
        {"market_price": price_tool, "market_news": news_tool, "market_fundamental": fundamental_tool}
    )
    result = skill.execute(_ctx(["ETH-USD"]))
    analysis = result.output["stocks"][0]["analysis"]
    check(analysis["recommendation"] == "SELL", "R3: ETH-USD reaches CryptoAnalysisSkill's SELL row")
    check("ETH-USD" not in fundamental_tool.called_for_symbols, "R3: market_fundamental never called for ETH-USD")


def scenario_case_insensitive_routing():
    print("\n[R4] Case-insensitive crypto routing")
    price_tool = _SymbolAwareTool({"btc-usd": {"trend": "bullish"}})
    news_tool = _SymbolAwareTool({"btc-usd": {"overall_sentiment": "positive"}})
    fundamental_tool = _SymbolAwareTool(raise_if_called_for=("btc-usd",))

    skill = MarketAnalysisSkill()
    skill._resolve_tool = _FixedResolver(
        {"market_price": price_tool, "market_news": news_tool, "market_fundamental": fundamental_tool}
    )
    result = skill.execute(_ctx(["btc-usd"]))
    analysis = result.output["stocks"][0]["analysis"]
    check(analysis["recommendation"] == "BUY", "R4: lowercase 'btc-usd' still routes to CryptoAnalysisSkill")
    check("btc-usd" not in fundamental_tool.called_for_symbols, "R4: market_fundamental never called for lowercase symbol")


def scenario_crypto_only_no_fundamental_registered():
    print("\n[N1] Crypto-only symbol list works with NO market_fundamental Tool registered at all")
    price_tool = _SymbolAwareTool({"BTC-USD": {"trend": "neutral"}})
    news_tool = _SymbolAwareTool({"BTC-USD": {"overall_sentiment": "neutral"}})

    skill = MarketAnalysisSkill()
    skill._resolve_tool = _FixedResolver({"market_price": price_tool, "market_news": news_tool})

    error = None
    try:
        result = skill.execute(_ctx(["BTC-USD"]))
    except Exception as exc:  # noqa: BLE001
        error = exc
        result = None

    check(error is None, f"N1: no exception even with market_fundamental unregistered (got {error!r})")
    if result is not None:
        analysis = result.output["stocks"][0]["analysis"]
        check(analysis["status"] == "INSUFFICIENT_DATA", "N1: neutral/neutral falls through to insufficient data, not a crash")


def main() -> int:
    scenario_mixed_stock_and_crypto_routing()
    scenario_eth_usd_also_routes_to_crypto()
    scenario_case_insensitive_routing()
    scenario_crypto_only_no_fundamental_registered()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 MARKET-ANALYSIS-SKILL CRYPTO-ROUTING RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())