"""TrendReasoningSkill -- the first real AI reasoning layer: parsed
trend text -> a normalized trend reasoning object (Phase 13, Sprint
144).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``TrendReasoningSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["vision_analysis"]`` (the output of Sprint
     143's ``Orchestration.vision_response_parser_skill.
     VisionResponseParserSkill``) and produces a single,
     deterministic ``{"trend_reasoning": {...}}`` output. That is the
     entire behavior.

Sprint 143's ``VisionResponseParserSkill`` only extracts raw text --
it never interprets it. This Skill is the first Skill that actually
*reasons* about that extracted text: it looks at the free-text
``trend`` field and derives ``trend_direction``, ``trend_strength``,
``trend_state``, and ``trend_reason`` from it via simple, fixed,
case-insensitive substring matching. There is no trading decision, no
BUY/SELL/WAIT signal, no entry/exit, no stop loss, no take profit, no
position sizing, no capital allocation, no order, no portfolio
action, no score, and no probability anywhere in this module.

Rule table (LOCKED, applied to ``vision_analysis["trend"]`` only,
checked in this exact order, case-insensitively, first match wins):

    trend contains "Bull"  -> trend_direction="UP",
                               trend_strength="STRONG",
                               trend_state="TRENDING",
                               trend_reason="Bullish trend detected"
    trend contains "Bear"  -> trend_direction="DOWN",
                               trend_strength="STRONG",
                               trend_state="TRENDING",
                               trend_reason="Bearish trend detected"
    trend contains "Side"  -> trend_direction="SIDEWAYS",
                               trend_strength="WEAK",
                               trend_state="RANGING",
                               trend_reason="Sideways market"
    trend contains "Range" -> trend_direction="SIDEWAYS",
                               trend_strength="WEAK",
                               trend_state="RANGING",
                               trend_reason="Range market"
    anything else           -> trend_direction=None,
                               trend_strength=None,
                               trend_state="UNKNOWN",
                               trend_reason=None

"Anything else" covers a ``trend`` that is missing, ``None``, not a
``str``, an empty string, or a string that matches none of the four
substrings above. The match is a plain case-insensitive substring
check (``"bull" in trend.lower()``, etc.) -- no regular expressions,
no JSON parsing, no tokenization, no natural-language processing of
any kind.

``symbol`` and ``timeframe`` are preserved exactly as received from
``vision_analysis`` -- never normalized, coerced, validated, or
otherwise transformed. ``trend`` itself is also forwarded through to
the output completely unchanged (whatever value -- or absence of one
-- was received), alongside the four newly derived reasoning fields.
They are all read defensively via ``.get(...)`` and default to
``None`` if absent, or if ``vision_analysis``/``context.parameters``
is not a mapping at all.

``support``, ``resistance``, ``candlestick_pattern``,
``volume_signal``, ``rsi_signal``, ``macd_signal``, and
``confidence`` are read from ``vision_analysis`` by nothing in this
module -- this Skill reasons about ``trend`` only, exactly as scoped
for Sprint 144. Those seven fields are simply not part of this
Skill's output.

ERROR HANDLING (LOCKED): this Skill never raises. Malformed input at
any level -- non-Mapping ``context.parameters``, a missing or
non-Mapping ``vision_analysis``, or a non-``str`` ``trend`` -- always
falls through to the "anything else" row above. This Skill always
returns a ``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseSkill`` already
supplies. Every member beyond the three ``BaseSkill``-required
members is deliberately absent -- the single reasoning pass lives
entirely inline inside ``execute()`` itself.

Dependencies (LOCKED): this module imports only
``collections.abc.Mapping``, ``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib ``typing`` --
nothing else. In particular it does NOT import ``json``, ``re``,
``VisionEngine``, ``VisionManager``, ``VisionProvider``, ``Gemini``,
``Ollama``, ``Qwen``, ``InternVL``, ``MiniCPM``, ``Llama``,
``Factory``, ``Registry``, ``Pipeline``, ``Workflow``,
``Coordinator``, ``Helper``, ``Repository``, ``Service``,
``Database``, ``Agents``, ``Orchestration.executor.Executor``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_context.ToolContext``,
``Orchestration.base_tool.BaseTool``, ``os``, ``pathlib``, ``PIL``,
``cv2``, ``matplotlib``, ``requests``, ``sqlite3``, ``pandas``,
``numpy``, ``websocket``, ``asyncio``, or ``threading``. This Skill
never calls ``self.execute_tool()`` or ``self.execute_tool_result()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class TrendReasoningSkill(BaseSkill):
    """Interprets a parsed ``trend`` string into a normalized trend
    reasoning object.

    This Skill does not call an LLM, does not call a Tool, and does
    not perform any trading logic of any kind -- it only reads
    ``context.parameters`` defensively and matches
    ``vision_analysis["trend"]`` against a fixed, case-insensitive
    substring rule table to derive ``trend_direction``,
    ``trend_strength``, ``trend_state``, and ``trend_reason``. No
    state, no ``__init__`` of its own, no helper methods beyond what
    ``BaseSkill`` already supplies. Every method beyond the three
    ``BaseSkill``-required members is deliberately absent -- the
    single reasoning pass lives entirely inline inside ``execute()``
    itself. This Skill never connects to a network, never touches a
    filesystem, and never touches persistence of any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"trend_reasoning"``.
        """
        return "trend_reasoning"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Interpret a parsed trend string into a normalized trend reasoning object."``.
        """
        return "Interpret a parsed trend string into a normalized trend reasoning object."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_analysis"`` value and produce a single
        ``{"trend_reasoning": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never calls an LLM, never performs any image inference, never
        checks the filesystem, and never makes any network call. It
        never produces a BUY/SELL/WAIT signal, an entry, an exit, a
        stop loss, a take profit, a position size, a capital
        allocation, an order, or a portfolio action of any kind.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"vision_analysis"`` behaves as though
        missing. If ``"vision_analysis"`` is missing, or is present
        but not itself a ``Mapping``, ``symbol``/``timeframe``/
        ``trend`` all behave as though missing (``None``) -- never
        raising.

        ``trend`` decides ``trend_direction``/``trend_strength``/
        ``trend_state``/``trend_reason`` via the locked rule table,
        checked in order and case-insensitively: a ``trend``
        containing ``"Bull"`` yields the bullish row, containing
        ``"Bear"`` yields the bearish row, containing ``"Side"``
        yields the sideways row, containing ``"Range"`` yields the
        range row, and anything else -- including a missing,
        non-``str``, or unmatched ``trend`` -- yields
        ``trend_direction=None``, ``trend_strength=None``,
        ``trend_state="UNKNOWN"``, ``trend_reason=None``. ``symbol``,
        ``timeframe``, and ``trend`` itself are copied through
        exactly as received, never normalized or transformed.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_analysis"`` mapping with
                ``"symbol"``, ``"timeframe"``, and ``"trend"``
                values. Read through defensively -- never copied,
                never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"trend_reasoning": {
            "symbol": ..., "timeframe": ..., "trend": ...,
            "trend_direction": ..., "trend_strength": ...,
            "trend_state": ..., "trend_reason": ...}}``,
            ``error=None``, and ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            vision_analysis = parameters.get("vision_analysis")
        else:
            vision_analysis = None

        if isinstance(vision_analysis, Mapping):
            symbol = vision_analysis.get("symbol")
            timeframe = vision_analysis.get("timeframe")
            trend = vision_analysis.get("trend")
        else:
            symbol = None
            timeframe = None
            trend = None

        trend_lower = trend.lower() if isinstance(trend, str) else None

        if trend_lower is not None and "bull" in trend_lower:
            trend_direction = "UP"
            trend_strength = "STRONG"
            trend_state = "TRENDING"
            trend_reason = "Bullish trend detected"
        elif trend_lower is not None and "bear" in trend_lower:
            trend_direction = "DOWN"
            trend_strength = "STRONG"
            trend_state = "TRENDING"
            trend_reason = "Bearish trend detected"
        elif trend_lower is not None and "side" in trend_lower:
            trend_direction = "SIDEWAYS"
            trend_strength = "WEAK"
            trend_state = "RANGING"
            trend_reason = "Sideways market"
        elif trend_lower is not None and "range" in trend_lower:
            trend_direction = "SIDEWAYS"
            trend_strength = "WEAK"
            trend_state = "RANGING"
            trend_reason = "Range market"
        else:
            trend_direction = None
            trend_strength = None
            trend_state = "UNKNOWN"
            trend_reason = None

        return SkillResult(
            success=True,
            output={
                "trend_reasoning": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "trend": trend,
                    "trend_direction": trend_direction,
                    "trend_strength": trend_strength,
                    "trend_state": trend_state,
                    "trend_reason": trend_reason,
                }
            },
            error=None,
            metadata={},
        )