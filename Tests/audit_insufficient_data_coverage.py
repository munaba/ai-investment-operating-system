"""Audit script (read-only, additive) -- Activation audit requested by
Nabil: "Do a focused audit of StockService -> MarketPriceTool ->
MarketNewsTool -> MarketFundamentalTool -> TextAnalysisSkill ->
RankingEngine -> RecommendationService. Determine whether current
INSUFFICIENT_DATA is correct due to the locked 4-row decision table or
identify an actual contract bug."

This script does NOT change any production code. It drives the REAL
``Orchestration.text_analysis_skill.TextAnalysisSkill.execute()`` --
through the REAL ``Orchestration.tool_resolver.ToolResolver`` /
``Orchestration.tool_registry.ToolRegistry`` -- for every one of the
3x3x3 = 27 possible (price trend, news sentiment, fundamental
valuation) combinations the three Tools can legitimately produce, by
injecting the trend/sentiment/valuation values directly as Tool
parameters (the same "explicit value always wins" seam each Tool's
own Phase-19 docstring documents -- this is not a mock of the Tools'
logic, it is the Tools' own, real, documented input contract).

Conclusion this script exists to support:

    The wiring from StockService through RecommendationService is
    contract-correct (verified separately, by direct code reading, at
    every field-name boundary: "trend"/"overall_sentiment"/
    "valuation"/"quality", the SkillContext.parameters={"symbol":...}
    thread, the ToolResolver bridge injected in
    Core.composition_root._build_market_analysis_agent, and
    WatchlistAnalysisSkill's status-aware normalization that stops a
    failed/insufficient analysis from being silently promoted into a
    fake "SELL"/"LOW" recommendation).

    INSUFFICIENT_DATA is NOT a wiring bug. It is the mathematically
    expected outcome of the LOCKED 4-row table: only 4 of the 27
    possible (trend, sentiment, valuation) combinations produce a
    recommendation. In particular there is NO row for the case where
    price trend and news sentiment agree (both bullish or both
    bearish) while fundamental valuation is "fair" -- which is the
    single most likely outcome for an ordinary, unremarkable stock
    (PE between 15 and 25 is "fair" by the Tool's own LOCKED rule, and
    trend/sentiment agreement is the common case, not the exception).
    Every "neutral" trend and every "neutral" sentiment also falls
    outside all 4 rows, by design.

Run directly: ``python Tests/audit_insufficient_data_coverage.py``
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Orchestration.market_fundamental_tool import MarketFundamentalTool
from Orchestration.market_news_tool import MarketNewsTool
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.skill_context import SkillContext
from Orchestration.text_analysis_skill import TextAnalysisSkill
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver

TRENDS = ("bullish", "bearish", "neutral")
SENTIMENTS = ("positive", "negative", "neutral")
VALUATIONS = ("undervalued", "fair", "overvalued")

# Parameter values that force each Tool to the requested output
# WITHOUT touching the network -- this is each Tool's own documented,
# LOCKED "explicit value always wins over the real-data lookup" seam,
# not a stand-in for the Tool's logic.
_TREND_PARAMS = {
    "bullish": {"current_price": 110, "previous_price": 100},
    "bearish": {"current_price": 90, "previous_price": 100},
    "neutral": {"current_price": 100, "previous_price": 100},
}
_SENTIMENT_PARAMS = {
    "positive": {"headlines": ["Company beats earnings, profit surges"]},
    "negative": {"headlines": ["Company misses estimates amid lawsuit"]},
    "neutral": {"headlines": ["Company holds annual meeting"]},
}
_VALUATION_PARAMS = {
    "undervalued": {"pe_ratio": 10},
    "fair": {"pe_ratio": 20},
    "overvalued": {"pe_ratio": 30},
}


def build_skill() -> TextAnalysisSkill:
    registry = ToolRegistry()
    registry.register("market_price", MarketPriceTool())
    registry.register("market_news", MarketNewsTool())
    registry.register("market_fundamental", MarketFundamentalTool())
    resolver = ToolResolver(registry)

    skill = TextAnalysisSkill()
    skill._resolve_tool = resolver.resolve
    return skill


def run_one(skill: TextAnalysisSkill, trend: str, sentiment: str, valuation: str):
    params = {"symbol": "TESTX", "roe": 16}  # roe fixed: irrelevant to the 4-row table
    params.update(_TREND_PARAMS[trend])
    params.update(_SENTIMENT_PARAMS[sentiment])
    params.update(_VALUATION_PARAMS[valuation])

    context = SkillContext(task=None, parameters=params, metadata={}, tool_context_factory=None)
    result = skill.execute(context)
    analysis = result.output["analysis"]

    # Sanity: confirm the Tools actually reproduced the requested
    # trend/sentiment/valuation (i.e. the injection seam worked) --
    # otherwise this audit would be silently testing the wrong inputs.
    assert result.output["price"]["trend"] == trend, (trend, result.output["price"])
    assert result.output["news"]["overall_sentiment"] == sentiment, (sentiment, result.output["news"])
    assert result.output["fundamental"]["valuation"] == valuation, (valuation, result.output["fundamental"])

    return analysis["recommendation"], analysis["confidence"], analysis["status"]


def main() -> int:
    skill = build_skill()

    signal_rows = []
    insufficient_rows = []

    for trend, sentiment, valuation in itertools.product(TRENDS, SENTIMENTS, VALUATIONS):
        recommendation, confidence, status = run_one(skill, trend, sentiment, valuation)
        row = (trend, sentiment, valuation, recommendation, confidence, status)
        if status == "SUCCESS":
            signal_rows.append(row)
        else:
            insufficient_rows.append(row)

    total = len(signal_rows) + len(insufficient_rows)

    print("=" * 78)
    print("SIGNAL-PRODUCING combinations (status == SUCCESS)")
    print("=" * 78)
    for trend, sentiment, valuation, rec, conf, status in signal_rows:
        print(f"  {trend:8s} + {sentiment:8s} + {valuation:11s} -> {rec}/{conf}")

    print()
    print("=" * 78)
    print("INSUFFICIENT_DATA combinations (status == INSUFFICIENT_DATA)")
    print("=" * 78)
    for trend, sentiment, valuation, rec, conf, status in insufficient_rows:
        tag = ""
        agreeing = (trend, sentiment) in (("bullish", "positive"), ("bearish", "negative"))
        if agreeing and valuation == "fair":
            tag = "  <-- trend & sentiment AGREE, valuation is FAIR (common real-world case)"
        print(f"  {trend:8s} + {sentiment:8s} + {valuation:11s} -> {rec}/{conf}{tag}")

    print()
    print("=" * 78)
    print(f"COVERAGE: {len(signal_rows)}/{total} combinations produce a signal "
          f"({100 * len(signal_rows) / total:.1f}%)")
    print(f"          {len(insufficient_rows)}/{total} combinations fall through to "
          f"INSUFFICIENT_DATA ({100 * len(insufficient_rows) / total:.1f}%)")
    print("=" * 78)

    # ------------------------------------------------------------------
    # Regression assertions -- lock in today's audited, correct
    # behaviour so a future change to the table (or a real wiring
    # regression) is caught immediately.
    # ------------------------------------------------------------------
    assert len(signal_rows) == 4, f"expected exactly 4 LOCKED signal rows, got {len(signal_rows)}"
    assert len(insufficient_rows) == 23, f"expected 23 INSUFFICIENT_DATA rows, got {len(insufficient_rows)}"

    expected_signals = {
        ("bullish", "positive", "undervalued"): ("BUY", "HIGH"),
        ("bearish", "negative", "overvalued"): ("SELL", "HIGH"),
        ("bullish", "negative", "fair"): ("WAIT", "MEDIUM"),
        ("bearish", "positive", "fair"): ("WAIT", "MEDIUM"),
    }
    actual_signals = {
        (trend, sentiment, valuation): (rec, conf)
        for trend, sentiment, valuation, rec, conf, _status in signal_rows
    }
    assert actual_signals == expected_signals, (actual_signals, expected_signals)

    # The specific, common-in-practice gap this audit was asked to
    # characterize: agreeing trend+sentiment with "fair" valuation is
    # NOT covered by the LOCKED table.
    for combo in (("bullish", "positive", "fair"), ("bearish", "negative", "fair")):
        assert combo in {(t, s, v) for t, s, v, *_ in insufficient_rows}, combo

    print()
    print("AUDIT CONCLUSION")
    print("-" * 78)
    print("No wiring/contract bug found in StockService -> MarketPriceTool ->")
    print("MarketNewsTool -> MarketFundamentalTool -> TextAnalysisSkill ->")
    print("RankingEngine -> RecommendationService. Field names, the")
    print("SkillContext.parameters={'symbol': ...} thread, the ToolResolver")
    print("bridge, and WatchlistAnalysisSkill's status-aware normalization")
    print("are all contract-correct.")
    print()
    print("INSUFFICIENT_DATA is CORRECT: only 4 of 27 (trend, sentiment,")
    print("valuation) combinations are recognized by the LOCKED table. Any")
    print("'fair' valuation (PE 15-25) combined with agreeing trend+sentiment")
    print("-- the common case for an unremarkable stock -- has no matching")
    print("row and falls through to INSUFFICIENT_DATA by design.")
    print("=" * 78)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())