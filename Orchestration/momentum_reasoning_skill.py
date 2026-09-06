"""MomentumReasoningSkill -- the second AI reasoning layer: parsed
RSI/MACD text -> structured momentum evidence (Phase 13, Sprint 145).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``MomentumReasoningSkill`` -- a ``BaseSkill`` subclass that
     reads ``context.parameters["vision_analysis"]`` (the output of
     Sprint 143's ``Orchestration.vision_response_parser_skill.
     VisionResponseParserSkill``) and produces a single,
     deterministic ``{"momentum_reasoning": {...}}`` output. That is
     the entire behavior.

Sprint 143's ``VisionResponseParserSkill`` only extracts raw
``rsi_signal``/``macd_signal`` text -- it never interprets it. This
Skill is the second reasoning Skill: it looks at those two free-text
fields and derives ``momentum_direction``, ``momentum_strength``,
``momentum_state``, ``momentum_reason``, and ``evidence`` from them
via simple, fixed, case-insensitive, whitespace-tolerant substring
matching. There is no trading decision, no recommendation, no
BUY/SELL/WAIT signal, no entry/exit, no stop loss, no take profit, no
position sizing, no capital allocation, no order, no portfolio
action, no risk assessment, no market prediction, and no score
anywhere in this module.

Rule table (LOCKED, applied to ``vision_analysis["rsi_signal"]`` and
``vision_analysis["macd_signal"]`` only, checked in this exact order,
case-insensitively, first match wins):

    CASE 1: rsi_signal contains "Overbought"
            OR macd_signal contains "Bear"
            -> momentum_direction="DOWN", momentum_strength="STRONG",
               momentum_state="BEARISH",
               momentum_reason="Negative momentum detected",
               evidence="BEARISH"

    CASE 2: rsi_signal contains "Oversold"
            OR macd_signal contains "Bull"
            -> momentum_direction="UP", momentum_strength="STRONG",
               momentum_state="BULLISH",
               momentum_reason="Positive momentum detected",
               evidence="BULLISH"

    CASE 3: neither rule matches
            -> momentum_direction=None, momentum_strength=None,
               momentum_state="UNKNOWN", momentum_reason=None,
               evidence="UNKNOWN"

CASE 1 is checked strictly before CASE 2, so a response where
``rsi_signal`` says "Overbought" while ``macd_signal`` separately says
"Bull" still resolves to CASE 1 (bearish) -- the RSI overbought /
MACD bearish condition always takes priority. "Neither rule matches"
covers ``rsi_signal``/``macd_signal`` that are missing, ``None``, not
a ``str``, an empty string, or a string that matches neither
substring family. The match is a plain case-insensitive,
whitespace-tolerant substring check (leading/trailing whitespace on
the field is stripped before lower-casing and searching) -- no
regular expressions, no JSON parsing, no tokenization, no
natural-language processing, no second LLM call, and no call to
another Skill of any kind.

``symbol``, ``timeframe``, ``rsi_signal``, and ``macd_signal`` are
preserved exactly as received from ``vision_analysis`` -- never
normalized, coerced, validated, or otherwise transformed -- alongside
the five newly derived momentum fields. They are all read defensively
via ``.get(...)`` and default to ``None`` if absent, or if
``vision_analysis``/``context.parameters`` is not a mapping at all.

``trend``, ``support``, ``resistance``, ``candlestick_pattern``,
``volume_signal``, and ``confidence`` are read from
``vision_analysis`` by nothing in this module -- this Skill reasons
about ``rsi_signal``/``macd_signal`` only, exactly as scoped for
Sprint 145. Those six fields are simply not part of this Skill's
output.

ERROR HANDLING (LOCKED): this Skill never raises. Malformed input at
any level -- non-Mapping ``context.parameters``, a missing or
non-Mapping ``vision_analysis``, or non-``str`` ``rsi_signal``/
``macd_signal`` -- always falls through to CASE 3 above. This Skill
always returns a ``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseSkill`` already
supplies. Every member beyond the three ``BaseSkill``-required
members is deliberately absent -- the single reasoning pass, using an
inline loop over the two signal fields, lives entirely inline inside
``execute()`` itself.

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
never calls ``self.execute_tool()`` or ``self.execute_tool_result()``,
and never calls another Skill.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class MomentumReasoningSkill(BaseSkill):
    """Interprets parsed ``rsi_signal``/``macd_signal`` strings into
    normalized momentum evidence.

    This Skill does not call an LLM, does not call a Tool, does not
    call another Skill, and does not perform any trading logic of any
    kind -- it only reads ``context.parameters`` defensively and
    matches ``vision_analysis["rsi_signal"]``/
    ``vision_analysis["macd_signal"]`` against a fixed,
    case-insensitive, whitespace-tolerant substring rule table to
    derive ``momentum_direction``, ``momentum_strength``,
    ``momentum_state``, ``momentum_reason``, and ``evidence``. No
    state, no ``__init__`` of its own, no helper methods beyond what
    ``BaseSkill`` already supplies. Every method beyond the three
    ``BaseSkill``-required members is deliberately absent -- the
    single reasoning pass lives entirely inline inside ``execute()``
    itself, using a plain inline loop over the two signal fields.
    This Skill never connects to a network, never touches a
    filesystem, and never touches persistence of any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"momentum_reasoning"``.
        """
        return "momentum_reasoning"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Interpret parsed RSI and MACD signals into structured momentum evidence."``.
        """
        return "Interpret parsed RSI and MACD signals into structured momentum evidence."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_analysis"`` value and produce a single
        ``{"momentum_reasoning": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()`` --
        and calls no other Skill. It never calls an LLM, never
        performs any image inference, never checks the filesystem,
        and never makes any network call. It never produces a
        BUY/SELL/WAIT signal, an entry, an exit, a stop loss, a take
        profit, a position size, a capital allocation, an order, a
        portfolio action, a risk assessment, a market prediction, or a
        score of any kind.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"vision_analysis"`` behaves as though
        missing. If ``"vision_analysis"`` is missing, or is present
        but not itself a ``Mapping``, ``symbol``/``timeframe``/
        ``rsi_signal``/``macd_signal`` all behave as though missing
        (``None``) -- never raising.

        ``rsi_signal`` and ``macd_signal`` decide
        ``momentum_direction``/``momentum_strength``/
        ``momentum_state``/``momentum_reason``/``evidence`` via the
        locked rule table, checked in order, case-insensitively, and
        tolerant of surrounding whitespace on each field: a
        ``rsi_signal`` containing ``"Overbought"`` or a
        ``macd_signal`` containing ``"Bear"`` yields the bearish
        (CASE 1) row; otherwise, a ``rsi_signal`` containing
        ``"Oversold"`` or a ``macd_signal`` containing ``"Bull"``
        yields the bullish (CASE 2) row; anything else -- including
        missing, non-``str``, or unmatched values for both fields --
        yields ``momentum_direction=None``,
        ``momentum_strength=None``, ``momentum_state="UNKNOWN"``,
        ``momentum_reason=None``, ``evidence="UNKNOWN"`` (CASE 3).
        ``symbol``, ``timeframe``, ``rsi_signal``, and
        ``macd_signal`` are copied through exactly as received,
        never normalized or transformed.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_analysis"`` mapping with
                ``"symbol"``, ``"timeframe"``, ``"rsi_signal"``, and
                ``"macd_signal"`` values. Read through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"momentum_reasoning": {
            "symbol": ..., "timeframe": ..., "rsi_signal": ...,
            "macd_signal": ..., "momentum_direction": ...,
            "momentum_strength": ..., "momentum_state": ...,
            "momentum_reason": ..., "evidence": ...}}``,
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
            rsi_signal = vision_analysis.get("rsi_signal")
            macd_signal = vision_analysis.get("macd_signal")
        else:
            symbol = None
            timeframe = None
            rsi_signal = None
            macd_signal = None

        normalized = []
        for raw_signal in (rsi_signal, macd_signal):
            if isinstance(raw_signal, str):
                normalized.append(raw_signal.strip().lower())
            else:
                normalized.append("")
        rsi_lower, macd_lower = normalized

        if "overbought" in rsi_lower or "bear" in macd_lower:
            momentum_direction = "DOWN"
            momentum_strength = "STRONG"
            momentum_state = "BEARISH"
            momentum_reason = "Negative momentum detected"
            evidence = "BEARISH"
        elif "oversold" in rsi_lower or "bull" in macd_lower:
            momentum_direction = "UP"
            momentum_strength = "STRONG"
            momentum_state = "BULLISH"
            momentum_reason = "Positive momentum detected"
            evidence = "BULLISH"
        else:
            momentum_direction = None
            momentum_strength = None
            momentum_state = "UNKNOWN"
            momentum_reason = None
            evidence = "UNKNOWN"

        return SkillResult(
            success=True,
            output={
                "momentum_reasoning": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "rsi_signal": rsi_signal,
                    "macd_signal": macd_signal,
                    "momentum_direction": momentum_direction,
                    "momentum_strength": momentum_strength,
                    "momentum_state": momentum_state,
                    "momentum_reason": momentum_reason,
                    "evidence": evidence,
                }
            },
            error=None,
            metadata={},
        )