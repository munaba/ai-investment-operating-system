"""CryptoAnalysisSkill -- Activation 7 Crypto Validation Profile.

A deliberately separate, parallel Skill to
``Orchestration.text_analysis_skill.TextAnalysisSkill`` -- NOT a
modification of it. ``TextAnalysisSkill`` and its LOCKED four-row
(price + news + fundamental) decision table remain completely
untouched, byte-for-byte, for every stock symbol. This Skill exists
because crypto has no P/E-style "fundamental valuation" concept for
``MarketFundamentalTool`` to compute -- a crypto symbol run through
the stock table would always fall through to its "insufficient data"
branch, not because the symbol is actually unanalyzable but because
one of the three required inputs simply does not exist for it (see
the Activation 7 pipeline audit this Skill resolves).

Mirrors ``TextAnalysisSkill``'s shape closely so it is a drop-in
replacement in the one slot that selects between them
(``Orchestration.market_analysis_skill.MarketAnalysisSkill``, see that
module's Activation 7 update): same two real Tools
(``"market_price"``, ``"market_news"``), called through the same,
already-frozen ``BaseSkill.execute_tool_result()`` integration point,
with real data -- no third Tool call, no fabricated/mocked data. The
only difference is the decision table itself, which is NOT
reimplemented here: this Skill calls the already-existing, already
pure ``Business.crypto_signal_engine.evaluate_crypto_signal()``
function (LOCKED two-row table: bullish+positive -> BUY/MEDIUM,
bearish+negative -> SELL/MEDIUM, anything else -> UNKNOWN/LOW/
"insufficient data") rather than writing a second copy of that logic
inline.

Output shape (LOCKED to match ``TextAnalysisSkill``'s ``"analysis"``
dict exactly, so every downstream consumer --
``Orchestration.market_analysis_skill.MarketAnalysisSkill``,
``Business.ranking_engine.RankingEngine``,
``Business.recommendation_service.RecommendationService``,
``Business.report_service.ReportService``,
``Repository.persistence.snapshot_repository.SnapshotRepository`` --
needs zero changes to consume a crypto symbol's result): ``"price"``,
``"news"``, ``"analysis"`` (with ``"recommendation"``, ``"confidence"``,
``"reason"``, ``"strengths"``, ``"risks"``, ``"summary"``, ``"status"``
sub-keys). There is deliberately NO ``"fundamental"`` key -- adding one
with a fabricated or ``None`` valuation would misrepresent this
profile as having considered fundamentals when it structurally
excludes that input; callers that need to know whether a result came
from the stock or crypto profile can already do so by checking which
Tool outputs are present.

``"strengths"``/``"risks"``/``"summary"`` are derived the same way
``TextAnalysisSkill`` derives them -- literal, independent ``if``
checks against ``price_trend``/``news_sentiment`` only (no
fundamental-derived entries, since there is no fundamental input to
read from) -- so a human reading a crypto recommendation sees the
same investment-thesis shape as a stock one, honestly reflecting the
narrower evidence this profile has.

``"status"`` follows the exact same precedence
``TextAnalysisSkill`` uses: ``"DATA_ERROR"`` if either Tool call
failed, else ``"INSUFFICIENT_DATA"`` if the decision table fell
through to its "insufficient data" row, else ``"SUCCESS"``.
``"recommendation"`` is ``None`` whenever ``"status"`` is not
``"SUCCESS"`` -- identical convention to ``TextAnalysisSkill``.

No state, no ``__init__`` of its own, no helper method beyond the
three ``BaseSkill``-required members -- the two Tool calls and the
result-combination logic live directly inline inside ``execute()``,
mirroring ``TextAnalysisSkill``'s own style.

Dependencies (LOCKED, mirrors ``TextAnalysisSkill``'s own dependency
list minus the fundamental Tool): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``,
``Business.crypto_signal_engine.evaluate_crypto_signal``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In particular
it does NOT import ``Orchestration.text_analysis_skill.TextAnalysisSkill``
(no dependency in either direction -- these are independent, parallel
Skills, not a subclass/superclass pair) or
``Orchestration.market_fundamental_tool.MarketFundamentalTool``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Business.crypto_signal_engine import evaluate_crypto_signal
from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class CryptoAnalysisSkill(BaseSkill):
    """The crypto counterpart to ``TextAnalysisSkill``: orchestrates
    ``MarketPriceTool``/``MarketNewsTool`` (real data, same Tools the
    stock profile already uses) and applies the LOCKED, already-pure
    two-row crypto decision table from
    ``Business.crypto_signal_engine.evaluate_crypto_signal()``.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"crypto_analysis"``.
        """
        return "crypto_analysis"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Analyze a crypto symbol using price and news only (no fundamental valuation)."``.
        """
        return "Analyze a crypto symbol using price and news only (no fundamental valuation)."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: orchestrate the ``market_price`` and
        ``market_news`` Tools and apply the LOCKED crypto decision
        table.

        Calls ``self.execute_tool_result("market_price", context)``
        then ``self.execute_tool_result("market_news", context)`` --
        the exact same integration method ``TextAnalysisSkill`` uses,
        called against the exact same two Tool names, with ``context``
        forwarded unchanged to both calls. This Skill never resolves
        or instantiates a Tool itself.

        Args:
            context: Passed straight through, unexamined, to both
                ``self.execute_tool_result(...)`` calls -- the exact
                same object, never copied or wrapped.

        Returns:
            A single, freshly constructed ``SkillResult`` combining
            both Tools' outputs: ``success`` is the AND of both;
            ``output`` is ``{"price": ..., "news": ..., "analysis":
            ...}``; ``error`` is ``None`` if both succeeded, otherwise
            a joined failure string; ``metadata`` is ``{}``.

        Raises:
            Exception: any exception raised by either
                ``self.execute_tool_result()`` call propagates
                unchanged -- never caught, never wrapped.
        """
        price_result = self.execute_tool_result("market_price", context)
        news_result = self.execute_tool_result("market_news", context)

        combined_success = price_result.success and news_result.success

        combined_error = None
        if not combined_success:
            failures = []
            if not price_result.success:
                failures.append(f"market_price: {price_result.error}")
            if not news_result.success:
                failures.append(f"market_news: {news_result.error}")
            combined_error = "; ".join(failures)

        price_trend = None
        if isinstance(price_result.output, dict):
            price_trend = price_result.output.get("trend")

        news_sentiment = None
        if isinstance(news_result.output, dict):
            news_sentiment = news_result.output.get("overall_sentiment")

        decision = evaluate_crypto_signal(price_trend, news_sentiment)
        recommendation = decision.recommendation
        confidence = decision.confidence
        reason = decision.reason

        # Investment thesis: same literal, independent-if style as
        # TextAnalysisSkill, but over only the two inputs this profile
        # actually has -- no fundamental-derived entries.
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
        for strength in strengths:
            summary_lines.append(f"- {strength}")
        summary_lines.append("")
        summary_lines.append("Risks:")
        for risk in risks:
            summary_lines.append(f"- {risk}")
        summary_lines.append("")
        summary_lines.append(f"Reason: {reason}")
        summary = "\n".join(summary_lines)

        # Status precedence identical to TextAnalysisSkill's own:
        # DATA_ERROR (a Tool call failed) beats INSUFFICIENT_DATA
        # (both Tools succeeded but the table found no match), beats
        # SUCCESS. Identified purely from state already computed
        # above -- no new business logic.
        if not combined_success:
            status = "DATA_ERROR"
        elif recommendation == "UNKNOWN" and confidence == "LOW" and reason == "insufficient data":
            status = "INSUFFICIENT_DATA"
        else:
            status = "SUCCESS"

        recommendation_for_output = recommendation if status == "SUCCESS" else None

        return SkillResult(
            success=combined_success,
            output={
                "price": price_result.output,
                "news": news_result.output,
                "analysis": {
                    "recommendation": recommendation_for_output,
                    "confidence": confidence,
                    "reason": reason,
                    "strengths": strengths,
                    "risks": risks,
                    "summary": summary,
                    "status": status,
                },
            },
            error=combined_error,
            metadata={},
        )