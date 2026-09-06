"""ForexAnalysisSkill -- initial Activation 11 paper-analysis profile.

Uses the existing market-price and market-news Tools only. No fundamental
valuation is attempted for Forex, because the initial Activation 11 scope
locks EUR/USD and GBP/USD and does not define a Forex fundamental model.
The output shape intentionally matches the existing analysis Skills so the
watchlist/ranking/recommendation pipeline needs no Forex-specific downstream
branch.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class ForexAnalysisSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "forex_analysis"

    @property
    def description(self) -> str:
        return "Analyze a Forex pair using price trend and market news."

    def execute(self, context: Any) -> SkillResult:
        price_result = self.execute_tool_result("market_price", context)
        news_result = self.execute_tool_result("market_news", context)

        combined_success = price_result.success and news_result.success
        failures = []
        if not price_result.success:
            failures.append(f"market_price: {price_result.error}")
        if not news_result.success:
            failures.append(f"market_news: {news_result.error}")

        price_trend = None
        if isinstance(price_result.output, Mapping):
            price_trend = price_result.output.get("trend")

        news_sentiment = None
        if isinstance(news_result.output, Mapping):
            news_sentiment = news_result.output.get("overall_sentiment")

        if price_trend == "bullish" and news_sentiment == "positive":
            recommendation, confidence, reason = "BUY", "MEDIUM", "bullish price and positive sentiment"
        elif price_trend == "bearish" and news_sentiment == "negative":
            recommendation, confidence, reason = "SELL", "MEDIUM", "bearish price and negative sentiment"
        else:
            recommendation, confidence, reason = "UNKNOWN", "LOW", "insufficient data"

        strengths = []
        if price_trend == "bullish":
            strengths.append("bullish price trend")
        if news_sentiment == "positive":
            strengths.append("positive market sentiment")
        if not strengths:
            strengths = ["No major strength detected"]

        risks = []
        if price_trend == "bearish":
            risks.append("bearish price trend")
        if news_sentiment == "negative":
            risks.append("negative market sentiment")
        if not risks:
            risks = ["No major risk detected"]

        summary_lines = [
            f"Recommendation: {recommendation}",
            f"Confidence: {confidence}",
            "",
            "Strengths:",
        ]
        summary_lines.extend(f"- {strength}" for strength in strengths)
        summary_lines += ["", "Risks:"]
        summary_lines.extend(f"- {risk}" for risk in risks)
        summary_lines += ["", f"Reason: {reason}"]

        status = "DATA_ERROR" if not combined_success else (
            "INSUFFICIENT_DATA" if recommendation == "UNKNOWN" else "SUCCESS"
        )

        return SkillResult(
            success=combined_success,
            output={
                "price": price_result.output,
                "news": news_result.output,
                "analysis": {
                    "recommendation": recommendation if status == "SUCCESS" else None,
                    "confidence": confidence,
                    "reason": reason,
                    "strengths": strengths,
                    "risks": risks,
                    "summary": "\n".join(summary_lines),
                    "status": status,
                },
            },
            error="; ".join(failures) if failures else None,
            metadata={},
        )
