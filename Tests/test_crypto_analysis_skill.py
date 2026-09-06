"""Activation 7 (Crypto Validation Profile) proof suite --
``Orchestration.crypto_analysis_skill.CryptoAnalysisSkill``.

Mirrors the seam-level Tool-double harness already used by
``Tests/test_stage_l112_text_analysis_fundamental_integration.py`` and
``Tests/test_stage_l117_market_analysis_skill.py`` -- duck-typed
``_FixedTool``/``_FixedResolver`` stand-ins injected as
``self._resolve_tool``, the same seam ``Executor.invoke_current_skill()``
uses in production. No pytest, no mocking framework, global-counter-
plus-``main()`` style, matching every other test file in this
project.

Invariant coverage (expanded crypto signal table --
``Business.crypto_signal_engine.evaluate_crypto_signal``):
    R1  -- bullish + positive -> BUY / MEDIUM.
    R2  -- bearish + negative -> SELL / MEDIUM.
    R3  -- bullish + neutral -> BUY / LOW.
    R4  -- bearish + neutral -> SELL / LOW.
    R5  -- bullish + negative, bearish + positive (contradictory) ->
           UNKNOWN / LOW / "contradictory signal". Note this is
           status=SUCCESS with recommendation="UNKNOWN" surfaced (not
           None) -- the skill's DATA_ERROR/INSUFFICIENT_DATA/SUCCESS
           precedence only special-cases the exact "insufficient
           data" reason, so a contradictory-but-directional read is
           reported as a real (if unhelpful) result, not a data gap.
    R6  -- every other (trend, sentiment) pair -- i.e. any
           non-bullish/non-bearish trend, or a directional trend paired
           with an unrecognized sentiment -> UNKNOWN / LOW /
           "insufficient data" / status=INSUFFICIENT_DATA /
           recommendation=None (exhaustive sweep over all 5x5
           combinations plus None/missing, minus the six locked pairs
           above).
    S1  -- output has exactly three top-level keys: "price", "news",
           "analysis" -- in particular NO "fundamental" key.
    S2  -- "analysis" has exactly the same seven keys
           TextAnalysisSkill's "analysis" dict has: recommendation,
           confidence, reason, strengths, risks, summary, status.
    S3  -- "price"/"news" are forwarded by identity from the
           underlying ToolResult outputs.
    C1  -- combined success = AND of both Tool calls; error is None
           when both succeed.
    F1  -- one failed Tool call -> combined success=False, "analysis"
           still a real dict (status=DATA_ERROR), recommendation=None.
    T1  -- both Tools are called by name exactly once each
           ("market_price", "market_news") -- never "market_fundamental".
    T2  -- the context passed to execute_tool_result is forwarded
           unchanged (same object identity) to both Tool calls.
    A1  -- name == "crypto_analysis", description is the fixed string.
    I1  -- real integration smoke test: genuine Executor, ToolRegistry,
           ToolResolver, real CryptoAnalysisSkill, real MarketPriceTool,
           real MarketNewsTool (no MarketFundamentalTool registered at
           all) -- proves this Skill never needs that Tool to run.

Run directly with ``python Tests/test_crypto_analysis_skill.py`` --
no external test framework required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Business.crypto_signal_engine import CRYPTO_CONFIDENCE_KEYS, CRYPTO_RECOMMENDATION_KEYS
from Orchestration.crypto_analysis_skill import CryptoAnalysisSkill
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


# ---------------------------------------------------------------------------
# Fixtures -- duck-typed Tool stand-ins, mirroring test_stage_l112's own.
# ---------------------------------------------------------------------------
class _FixedTool:
    def __init__(self, output, success=True, error=None):
        self.output = output
        self.success = success
        self.error = error
        self.received_contexts: List[Any] = []
        self.call_count = 0

    def execute(self, context):
        self.call_count += 1
        self.received_contexts.append(context)
        return ToolResult(success=self.success, output=self.output, error=self.error, metadata={})


class _FixedResolver:
    def __init__(self, tools: dict):
        self.tools = tools
        self.requested_names: List[str] = []

    def __call__(self, name):
        self.requested_names.append(name)
        if name not in self.tools:
            raise KeyError(name)
        return self.tools[name]


def _ctx(symbol: str = "BTC-USD") -> SkillContext:
    return SkillContext(task=None, parameters={"symbol": symbol}, metadata={}, tool_context_factory=None)


def _skill_with(price_output, news_output, price_success=True, news_success=True):
    skill = CryptoAnalysisSkill()
    resolver = _FixedResolver(
        {
            "market_price": _FixedTool(price_output, success=price_success, error=None if price_success else "boom"),
            "market_news": _FixedTool(news_output, success=news_success, error=None if news_success else "boom"),
        }
    )
    skill._resolve_tool = resolver
    return skill, resolver


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def scenario_decision_table():
    print("\n[R] Expanded crypto signal table")
    skill, _ = _skill_with({"trend": "bullish"}, {"overall_sentiment": "positive"})
    result = skill.execute(_ctx())
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "BUY", "R1: bullish+positive -> BUY")
    check(analysis["confidence"] == "MEDIUM", "R1: bullish+positive -> MEDIUM confidence")

    skill, _ = _skill_with({"trend": "bearish"}, {"overall_sentiment": "negative"})
    result = skill.execute(_ctx())
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "SELL", "R2: bearish+negative -> SELL")
    check(analysis["confidence"] == "MEDIUM", "R2: bearish+negative -> MEDIUM confidence")

    skill, _ = _skill_with({"trend": "bullish"}, {"overall_sentiment": "neutral"})
    result = skill.execute(_ctx())
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "BUY", "R3: bullish+neutral -> BUY")
    check(analysis["confidence"] == "LOW", "R3: bullish+neutral -> LOW confidence")
    check(analysis["status"] == "SUCCESS", "R3: bullish+neutral -> status SUCCESS")

    skill, _ = _skill_with({"trend": "bearish"}, {"overall_sentiment": "neutral"})
    result = skill.execute(_ctx())
    analysis = result.output["analysis"]
    check(analysis["recommendation"] == "SELL", "R4: bearish+neutral -> SELL")
    check(analysis["confidence"] == "LOW", "R4: bearish+neutral -> LOW confidence")
    check(analysis["status"] == "SUCCESS", "R4: bearish+neutral -> status SUCCESS")

    for trend, sentiment, label in (
        ("bullish", "negative", "R5a"),
        ("bearish", "positive", "R5b"),
    ):
        skill, _ = _skill_with({"trend": trend}, {"overall_sentiment": sentiment})
        result = skill.execute(_ctx())
        analysis = result.output["analysis"]
        check(analysis["recommendation"] == "UNKNOWN", f"{label}: {trend}+{sentiment} (contradictory) -> UNKNOWN")
        check(analysis["confidence"] == "LOW", f"{label}: {trend}+{sentiment} -> LOW confidence")
        check(analysis["reason"] == "contradictory signal", f"{label}: {trend}+{sentiment} -> reason == contradictory signal")
        check(analysis["status"] == "SUCCESS", f"{label}: {trend}+{sentiment} -> status SUCCESS (a real, if unhelpful, read)")

    locked_pairs = {
        ("bullish", "positive"),
        ("bearish", "negative"),
        ("bullish", "neutral"),
        ("bearish", "neutral"),
        ("bullish", "negative"),
        ("bearish", "positive"),
    }
    trends = ["bullish", "bearish", "neutral", None, "garbage"]
    sentiments = ["positive", "negative", "neutral", None, "garbage"]
    exhaustive_ok = True
    for t in trends:
        for s in sentiments:
            if (t, s) in locked_pairs:
                continue
            skill, _ = _skill_with({"trend": t}, {"overall_sentiment": s})
            analysis = skill.execute(_ctx()).output["analysis"]
            if not (
                analysis["recommendation"] is None
                and analysis["confidence"] == "LOW"
                and analysis["reason"] == "insufficient data"
                and analysis["status"] == "INSUFFICIENT_DATA"
            ):
                exhaustive_ok = False
    check(exhaustive_ok, "R6: exhaustive sweep -- every non-locked combination -> UNKNOWN/LOW/insufficient data")

    check(set(CRYPTO_RECOMMENDATION_KEYS) == {"BUY", "SELL", "UNKNOWN"}, "recommendation vocabulary unchanged (BUY/SELL/UNKNOWN)")
    check(set(CRYPTO_CONFIDENCE_KEYS) == {"MEDIUM", "LOW"}, "confidence vocabulary unchanged (MEDIUM/LOW) -- crypto never claims HIGH")


def scenario_output_shape():
    print("\n[S] Output shape")
    skill, _ = _skill_with({"trend": "bullish"}, {"overall_sentiment": "positive"})
    result = skill.execute(_ctx())

    check(set(result.output.keys()) == {"price", "news", "analysis"}, "S1: exactly price/news/analysis top-level keys (NO fundamental)")
    check(
        set(result.output["analysis"].keys())
        == {"recommendation", "confidence", "reason", "strengths", "risks", "summary", "status"},
        "S2: analysis has exactly the 7 keys matching TextAnalysisSkill's shape",
    )

    price_output = {"trend": "bullish"}
    news_output = {"overall_sentiment": "positive"}
    skill2, _ = _skill_with(price_output, news_output)
    result2 = skill2.execute(_ctx())
    check(result2.output["price"] is price_output, "S3: price forwarded by identity")
    check(result2.output["news"] is news_output, "S3: news forwarded by identity")


def scenario_combined_success_and_failure():
    print("\n[C/F] Combined success/failure handling")
    skill, _ = _skill_with({"trend": "bullish"}, {"overall_sentiment": "positive"})
    result = skill.execute(_ctx())
    check(result.success is True, "C1: both Tools succeed -> success=True")
    check(result.error is None, "C1: both Tools succeed -> error=None")

    skill, _ = _skill_with({"trend": "bullish"}, {"overall_sentiment": "positive"}, price_success=False)
    result = skill.execute(_ctx())
    check(result.success is False, "F1: failed market_price -> combined success=False")
    check(result.output["analysis"] is not None, "F1: analysis is still a real dict")
    check(result.output["analysis"]["status"] == "DATA_ERROR", "F1: status == DATA_ERROR")
    check(result.output["analysis"]["recommendation"] is None, "F1: recommendation is None when status != SUCCESS")
    check(result.error is not None and "market_price" in result.error, "F1: error mentions market_price")

    skill, _ = _skill_with({"trend": "bullish"}, {"overall_sentiment": "positive"}, price_success=False, news_success=False)
    result = skill.execute(_ctx())
    check(result.error is not None and "market_price" in result.error and "market_news" in result.error, "F1b: both failures joined in error")


def scenario_tool_calls():
    print("\n[T] Tool call discipline")
    skill, resolver = _skill_with({"trend": "bullish"}, {"overall_sentiment": "positive"})
    context = _ctx("ETH-USD")
    skill.execute(context)

    check(resolver.requested_names == ["market_price", "market_news"], "T1: exactly market_price then market_news, no market_fundamental")
    check("market_fundamental" not in resolver.requested_names, "T1: market_fundamental never requested")

    price_tool = resolver.tools["market_price"]
    news_tool = resolver.tools["market_news"]
    check(price_tool.call_count == 1, "T1: market_price called exactly once")
    check(news_tool.call_count == 1, "T1: market_news called exactly once")
    check(price_tool.received_contexts[0] is context, "T2: context forwarded unchanged (identity) to market_price")
    check(news_tool.received_contexts[0] is context, "T2: context forwarded unchanged (identity) to market_news")


def scenario_class_shape():
    print("\n[A] Class shape")
    skill = CryptoAnalysisSkill()
    check(skill.name == "crypto_analysis", "A1: name == 'crypto_analysis'")
    check(
        skill.description == "Analyze a crypto symbol using price and news only (no fundamental valuation).",
        "A1: description is the fixed string",
    )


def scenario_real_integration():
    print("\n[I] Real integration -- genuine ToolRegistry/ToolResolver, real Tools, no MarketFundamentalTool registered at all")
    try:
        from Orchestration.market_news_tool import MarketNewsTool
        from Orchestration.market_price_tool import MarketPriceTool
        from Orchestration.tool_registry import ToolRegistry
        from Orchestration.tool_resolver import ToolResolver
    except Exception as exc:  # noqa: BLE001
        check(False, f"I1: could not import real collaborators for integration test ({exc})")
        return

    tool_registry = ToolRegistry()
    tool_registry.register("market_price", MarketPriceTool())
    tool_registry.register("market_news", MarketNewsTool())
    # Deliberately NOT registering "market_fundamental" at all -- proves
    # CryptoAnalysisSkill genuinely never needs it, unlike TextAnalysisSkill.
    tool_resolver = ToolResolver(tool_registry)

    skill = CryptoAnalysisSkill()
    skill._resolve_tool = tool_resolver.resolve  # the exact seam Executor itself injects

    error = None
    result = None
    try:
        result = skill.execute(_ctx("BTC-USD"))
    except Exception as exc:  # noqa: BLE001
        error = exc

    check(error is None, f"I1: real Skill -> real Tools pipeline runs end-to-end without raising (got {error!r})")
    if result is not None:
        check(isinstance(result.output, dict) and "analysis" in result.output, "I1: real integration returns a real 'analysis' dict")
        check("fundamental" not in result.output, "I1: no 'fundamental' key even in a real integration run")


def main() -> int:
    scenario_decision_table()
    scenario_output_shape()
    scenario_combined_success_and_failure()
    scenario_tool_calls()
    scenario_class_shape()
    scenario_real_integration()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 CRYPTO-ANALYSIS-SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())