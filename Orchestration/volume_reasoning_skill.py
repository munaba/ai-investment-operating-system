"""VolumeReasoningSkill -- the third AI reasoning layer: parsed
volume text -> structured volume evidence (Phase 13, Sprint 146).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``VolumeReasoningSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["vision_analysis"]`` (the output of
     Sprint 143's ``Orchestration.vision_response_parser_skill.
     VisionResponseParserSkill``) and produces a single,
     deterministic ``{"volume_reasoning": {...}}`` output. That is
     the entire behavior.

Sprint 143's ``VisionResponseParserSkill`` only extracts raw
``volume_signal`` text -- it never interprets it. This Skill is the
third reasoning Skill: it looks at that one free-text field and
derives ``volume_state``, ``volume_strength``, ``volume_reason``, and
``evidence`` from it via simple, fixed, case-insensitive,
whitespace-tolerant substring matching. There is no trading decision,
no recommendation, no BUY/SELL/WAIT signal, no entry/exit, no stop
loss, no take profit, no position sizing, no capital allocation, no
order, no portfolio action, no risk assessment, no market prediction,
and no score anywhere in this module.

Rule table (LOCKED, applied to ``vision_analysis["volume_signal"]``
only, checked in this exact order, case-insensitively, first match
wins):

    CASE 1: volume_signal contains "Increasing" OR "High"
            -> volume_state="STRONG", volume_strength="HIGH",
               volume_reason="Strong buying participation",
               evidence="HIGH_VOLUME"

    CASE 2: volume_signal contains "Decreasing" OR "Low"
            -> volume_state="WEAK", volume_strength="LOW",
               volume_reason="Weak market participation",
               evidence="LOW_VOLUME"

    CASE 3: neither rule matches
            -> volume_state="UNKNOWN", volume_strength=None,
               volume_reason=None, evidence="UNKNOWN"

"Neither rule matches" covers ``volume_signal`` that is missing,
``None``, not a ``str``, an empty string, or a string that matches
neither substring family. The match is a plain case-insensitive,
whitespace-tolerant substring check (leading/trailing whitespace on
the field is stripped before lower-casing and searching) -- no
regular expressions, no JSON parsing, no tokenization, no
natural-language processing, no second LLM call, and no call to
another Skill of any kind.

``symbol``, ``timeframe``, and ``volume_signal`` are preserved
exactly as received from ``vision_analysis`` -- never normalized,
coerced, validated, or otherwise transformed -- alongside the four
newly derived volume fields. They are all read defensively via
``.get(...)`` and default to ``None`` if absent, or if
``vision_analysis``/``context.parameters`` is not a mapping at all.

``trend``, ``support``, ``resistance``, ``candlestick_pattern``,
``rsi_signal``, ``macd_signal``, and ``confidence`` are read from
``vision_analysis`` by nothing in this module -- this Skill reasons
about ``volume_signal`` only, exactly as scoped for Sprint 146. Those
seven fields are simply not part of this Skill's output.

ERROR HANDLING (LOCKED): this Skill never raises. Malformed input at
any level -- non-Mapping ``context.parameters``, a missing or
non-Mapping ``vision_analysis``, or a non-``str`` ``volume_signal``
-- always falls through to CASE 3 above. This Skill always returns a
``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseSkill`` already
supplies. Every member beyond the three ``BaseSkill``-required
members is deliberately absent -- the single reasoning pass, using an
inline loop, lives entirely inline inside ``execute()`` itself.

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


class VolumeReasoningSkill(BaseSkill):
    """Interprets a parsed ``volume_signal`` string into normalized
    volume evidence.

    This Skill does not call an LLM, does not call a Tool, does not
    call another Skill, and does not perform any trading logic of any
    kind -- it only reads ``context.parameters`` defensively and
    matches ``vision_analysis["volume_signal"]`` against a fixed,
    case-insensitive, whitespace-tolerant substring rule table to
    derive ``volume_state``, ``volume_strength``, ``volume_reason``,
    and ``evidence``. No state, no ``__init__`` of its own, no helper
    methods beyond what ``BaseSkill`` already supplies. Every method
    beyond the three ``BaseSkill``-required members is deliberately
    absent -- the single reasoning pass lives entirely inline inside
    ``execute()`` itself, using a plain inline loop. This Skill never
    connects to a network, never touches a filesystem, and never
    touches persistence of any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"volume_reasoning"``.
        """
        return "volume_reasoning"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Interpret a parsed volume signal into structured volume evidence."``.
        """
        return "Interpret a parsed volume signal into structured volume evidence."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_analysis"`` value and produce a single
        ``{"volume_reasoning": {...}}`` output.

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
        ``volume_signal`` all behave as though missing (``None``) --
        never raising.

        ``volume_signal`` decides ``volume_state``/
        ``volume_strength``/``volume_reason``/``evidence`` via the
        locked rule table, checked in order, case-insensitively, and
        tolerant of surrounding whitespace on the field: a
        ``volume_signal`` containing ``"Increasing"`` or ``"High"``
        yields the strong (CASE 1) row; otherwise, a ``volume_signal``
        containing ``"Decreasing"`` or ``"Low"`` yields the weak
        (CASE 2) row; anything else -- including missing, non-``str``,
        or unmatched values -- yields ``volume_state="UNKNOWN"``,
        ``volume_strength=None``, ``volume_reason=None``,
        ``evidence="UNKNOWN"`` (CASE 3). ``symbol``, ``timeframe``, and
        ``volume_signal`` are copied through exactly as received,
        never normalized or transformed.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_analysis"`` mapping with
                ``"symbol"``, ``"timeframe"``, and
                ``"volume_signal"`` values. Read through defensively
                -- never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"volume_reasoning": {
            "symbol": ..., "timeframe": ..., "volume_signal": ...,
            "volume_state": ..., "volume_strength": ...,
            "volume_reason": ..., "evidence": ...}}``,
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
            volume_signal = vision_analysis.get("volume_signal")
        else:
            symbol = None
            timeframe = None
            volume_signal = None

        normalized = []
        for raw_signal in (volume_signal,):
            if isinstance(raw_signal, str):
                normalized.append(raw_signal.strip().lower())
            else:
                normalized.append("")
        (volume_lower,) = normalized

        if "increasing" in volume_lower or "high" in volume_lower:
            volume_state = "STRONG"
            volume_strength = "HIGH"
            volume_reason = "Strong buying participation"
            evidence = "HIGH_VOLUME"
        elif "decreasing" in volume_lower or "low" in volume_lower:
            volume_state = "WEAK"
            volume_strength = "LOW"
            volume_reason = "Weak market participation"
            evidence = "LOW_VOLUME"
        else:
            volume_state = "UNKNOWN"
            volume_strength = None
            volume_reason = None
            evidence = "UNKNOWN"

        return SkillResult(
            success=True,
            output={
                "volume_reasoning": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "volume_signal": volume_signal,
                    "volume_state": volume_state,
                    "volume_strength": volume_strength,
                    "volume_reason": volume_reason,
                    "evidence": evidence,
                }
            },
            error=None,
            metadata={},
        )