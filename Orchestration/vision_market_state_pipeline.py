"""VisionMarketStatePipeline -- production wiring for the modern
Vision -> Reasoning -> MarketState chain (Phase 13, Sprint 151).

This module introduces NO new reasoning concept and NO new Skill.
Every step below is an existing, unmodified Skill or Provider defined
elsewhere; this class only sequences ``SkillContext`` construction and
hands each Skill's flat output mapping to the next Skill's expected
input key, mirroring the same "wiring-only" pattern
``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``
already established for the classic ``AnalysisPipeline``.

Fixed order (LOCKED by the Sprint 151 target flow):

    ChartVisionSkill -> VisionAnalysisSkill -> VisionPromptSkill ->
    VisionResultSkill -> (Vision Provider, e.g. GeminiVisionProvider)
    -> VisionResponseParserSkill -> TrendReasoningSkill,
    MomentumReasoningSkill, VolumeReasoningSkill,
    CandlestickReasoningSkill, SupportResistanceReasoningSkill ->
    EvidenceFusionSkill -> MarketStateSkill.

``VisionResultSkill`` is executed for stage-order fidelity (so every
modern stage genuinely runs, in order, exactly once) even though its
fixed, all-``None`` placeholder output is superseded immediately after
by the real Vision Provider's result -- which shares the exact same
``VisionResult`` contract (see
``Providers.base_vision_provider.BaseVisionProvider``), so nothing
downstream can tell the difference in shape, only in content.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from Orchestration.candlestick_reasoning_skill import CandlestickReasoningSkill
from Orchestration.chart_vision_skill import ChartVisionSkill
from Orchestration.evidence_fusion_skill import EvidenceFusionSkill
from Orchestration.market_state_skill import MarketStateSkill
from Orchestration.momentum_reasoning_skill import MomentumReasoningSkill
from Orchestration.skill_context import SkillContext
from Orchestration.support_resistance_reasoning_skill import (
    SupportResistanceReasoningSkill,
)
from Orchestration.trend_reasoning_skill import TrendReasoningSkill
from Orchestration.vision_analysis_skill import VisionAnalysisSkill
from Orchestration.vision_prompt_skill import VisionPromptSkill
from Orchestration.vision_response_parser_skill import VisionResponseParserSkill
from Orchestration.vision_result_skill import VisionResultSkill
from Orchestration.volume_reasoning_skill import VolumeReasoningSkill


class VisionMarketStatePipeline:
    """Runs the fixed, existing modern vision + reasoning Skill chain
    for one chart and returns the final ``market_state`` mapping.

    Stateless beyond its constructor-injected ``vision_provider`` and
    the twelve existing Skill instances it constructs once (each
    Skill here takes no constructor arguments -- see each Skill's own
    module). No Skill logic is duplicated or rewritten; this class
    only sequences existing ``execute(context)`` calls.
    """

    def __init__(self, vision_provider: Any) -> None:
        """Wire this pipeline to exactly one Vision Provider.

        Args:
            vision_provider: An object satisfying
                ``Providers.base_vision_provider.BaseVisionProvider``'s
                ``analyze(vision_prompt) -> VisionResult`` contract
                (e.g. ``Providers.gemini_vision_provider.GeminiVisionProvider``).
                Stored by identity; never constructed here.
        """
        self._vision_provider = vision_provider
        self._chart_vision_skill = ChartVisionSkill()
        self._vision_analysis_skill = VisionAnalysisSkill()
        self._vision_prompt_skill = VisionPromptSkill()
        self._vision_result_skill = VisionResultSkill()
        self._vision_response_parser_skill = VisionResponseParserSkill()
        self._trend_reasoning_skill = TrendReasoningSkill()
        self._momentum_reasoning_skill = MomentumReasoningSkill()
        self._volume_reasoning_skill = VolumeReasoningSkill()
        self._candlestick_reasoning_skill = CandlestickReasoningSkill()
        self._support_resistance_reasoning_skill = SupportResistanceReasoningSkill()
        self._evidence_fusion_skill = EvidenceFusionSkill()
        self._market_state_skill = MarketStateSkill()

    def run(
        self,
        symbol: Optional[str],
        timeframe: Optional[str],
        chart_path: str,
    ) -> Mapping[str, Any]:
        """Run the full modern vision pipeline for one chart.

        Args:
            symbol: Forwarded unchanged into ``ChartVisionSkill``'s
                ``"symbol"`` parameter.
            timeframe: Forwarded unchanged into ``ChartVisionSkill``'s
                ``"timeframe"`` parameter.
            chart_path: The chart image path -- the existing input
                contract ``ChartVisionSkill`` already expects.

        Returns:
            The ``market_state`` mapping produced by
            ``MarketStateSkill`` for this chart.

        Raises:
            Exception: Any exception raised by a Skill or by
                ``vision_provider.analyze()`` propagates unchanged --
                this method performs no error handling of its own.
                (Every Skill and provider in this chain is documented
                never to raise; a caller wanting a hard safety net
                around a misbehaving injected provider should catch
                around this call -- see
                ``RuntimeAnalysisPipeline._maybe_run_vision``.)
        """
        vision_request = self._chart_vision_skill.execute(
            SkillContext(
                task=None,
                parameters={
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "chart_path": chart_path,
                },
            )
        ).output["vision_request"]

        vision_analysis_stage1 = self._vision_analysis_skill.execute(
            SkillContext(task=None, parameters={"vision_request": vision_request})
        ).output["vision_analysis"]

        vision_prompt = self._vision_prompt_skill.execute(
            SkillContext(task=None, parameters={"vision_analysis": vision_analysis_stage1})
        ).output["vision_prompt"]

        # Executed for stage-order fidelity only -- see module docstring.
        self._vision_result_skill.execute(
            SkillContext(task=None, parameters={"vision_prompt": vision_prompt})
        )

        vision_result = self._vision_provider.analyze(vision_prompt)

        vision_analysis_parsed = self._vision_response_parser_skill.execute(
            SkillContext(task=None, parameters={"vision_result": vision_result})
        ).output["vision_analysis"]

        reasoning_parameters = {"vision_analysis": vision_analysis_parsed}

        trend_reasoning = self._trend_reasoning_skill.execute(
            SkillContext(task=None, parameters=reasoning_parameters)
        ).output["trend_reasoning"]
        momentum_reasoning = self._momentum_reasoning_skill.execute(
            SkillContext(task=None, parameters=reasoning_parameters)
        ).output["momentum_reasoning"]
        volume_reasoning = self._volume_reasoning_skill.execute(
            SkillContext(task=None, parameters=reasoning_parameters)
        ).output["volume_reasoning"]
        candlestick_reasoning = self._candlestick_reasoning_skill.execute(
            SkillContext(task=None, parameters=reasoning_parameters)
        ).output["candlestick_reasoning"]
        support_resistance_reasoning = self._support_resistance_reasoning_skill.execute(
            SkillContext(task=None, parameters=reasoning_parameters)
        ).output["support_resistance_reasoning"]

        market_consensus = self._evidence_fusion_skill.execute(
            SkillContext(
                task=None,
                parameters={
                    "trend_reasoning": trend_reasoning,
                    "momentum_reasoning": momentum_reasoning,
                    "volume_reasoning": volume_reasoning,
                    "candlestick_reasoning": candlestick_reasoning,
                    "support_resistance_reasoning": support_resistance_reasoning,
                },
            )
        ).output["market_consensus"]

        market_state = self._market_state_skill.execute(
            SkillContext(task=None, parameters={"market_consensus": market_consensus})
        ).output["market_state"]

        return market_state