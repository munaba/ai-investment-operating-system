"""SupportResistanceReasoningSkill -- the fifth AI reasoning layer:
extracted support/resistance levels -> structured support/resistance
evidence (Phase 13, Sprint 148).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``SupportResistanceReasoningSkill`` -- a ``BaseSkill`` subclass
     that reads ``context.parameters["vision_analysis"]`` (the output
     of Sprint 143's ``Orchestration.vision_response_parser_skill.
     VisionResponseParserSkill``) and produces a single, deterministic
     ``{"support_resistance_reasoning": {...}}`` output. That is the
     entire behavior.

Sprint 143's ``VisionResponseParserSkill`` only extracts raw
``support``/``resistance`` text -- it never interprets it. This Skill
is the fifth reasoning Skill: it looks at those two free-text fields
and derives ``level_state``, ``level_strength``, ``level_reason``, and
``evidence`` from their mere presence -- no numeric parsing, no float
conversion, and no validation of their contents. There is no trading
decision, no recommendation, no BUY/SELL/WAIT signal, no entry/exit,
no stop loss, no take profit, no position sizing, no capital
allocation, no order, no portfolio action, no risk assessment, no
market prediction, and no score anywhere in this module.

Rule table (LOCKED, applied to ``vision_analysis["support"]`` and
``vision_analysis["resistance"]`` only, first match wins):

    CASE 1: support exists AND resistance exists
            -> level_state="DEFINED", level_strength="KNOWN",
               level_reason="Support and resistance identified",
               evidence="LEVELS_PRESENT"

    CASE 2: otherwise
            -> level_state="UNKNOWN", level_strength=None,
               level_reason=None, evidence="UNKNOWN"

"Support exists" and "resistance exists" both mean: the value is an
instance of ``str`` AND ``value.strip() != ""``. This is pure presence
detection -- no numeric parsing, no float conversion, and no other
validation of the string's contents.

``symbol``, ``timeframe``, ``support``, and ``resistance`` are
preserved exactly as received from ``vision_analysis`` -- never
normalized, coerced, validated, or otherwise transformed -- alongside
the four newly derived level fields. They are all read defensively via
``.get(...)`` and default to ``None`` if absent, or if
``vision_analysis``/``context.parameters`` is not a mapping at all.

``trend``, ``volume_signal``, ``candlestick_pattern``, ``rsi_signal``,
``macd_signal``, and ``confidence`` are read from ``vision_analysis``
by nothing in this module -- this Skill reasons about ``support`` and
``resistance`` only, exactly as scoped for Sprint 148. Those six
fields are simply not part of this Skill's output.

ERROR HANDLING (LOCKED): this Skill never raises. Malformed input at
any level -- non-Mapping ``context.parameters``, a missing or
non-Mapping ``vision_analysis``, or a non-``str`` ``support``/
``resistance`` -- always falls through to CASE 2 above. This Skill
always returns a ``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseSkill`` already
supplies. Every member beyond the three ``BaseSkill``-required members
is deliberately absent -- the single reasoning pass, using an inline
check, lives entirely inline inside ``execute()`` itself.

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


class SupportResistanceReasoningSkill(BaseSkill):
    """Interprets parsed ``support``/``resistance`` strings into
    normalized support/resistance evidence.

    This Skill does not call an LLM, does not call a Tool, does not
    call another Skill, and does not perform any trading logic of any
    kind -- it only reads ``context.parameters`` defensively and
    checks ``vision_analysis["support"]``/``vision_analysis[
    "resistance"]`` for mere non-empty-string presence to derive
    ``level_state``, ``level_strength``, ``level_reason``, and
    ``evidence``. No state, no ``__init__`` of its own, no helper
    methods beyond what ``BaseSkill`` already supplies. Every member
    beyond the three ``BaseSkill``-required members is deliberately
    absent -- the single reasoning pass lives entirely inline inside
    ``execute()`` itself, using a plain inline check. This Skill never
    connects to a network, never touches a filesystem, and never
    touches persistence of any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"support_resistance_reasoning"``.
        """
        return "support_resistance_reasoning"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Interpret parsed support and resistance levels into structured evidence."``.
        """
        return "Interpret parsed support and resistance levels into structured evidence."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_analysis"`` value and produce a single
        ``{"support_resistance_reasoning": {...}}`` output.

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
        ``support``/``resistance`` all behave as though missing
        (``None``) -- never raising.

        ``support``/``resistance`` decide ``level_state``/
        ``level_strength``/``level_reason``/``evidence`` via the
        locked rule table: when both ``support`` and ``resistance``
        are instances of ``str`` with non-empty content after
        stripping whitespace, the defined (CASE 1) row is produced;
        otherwise -- including a missing, non-``str``, empty, or
        whitespace-only value for either field -- the unknown (CASE 2)
        row is produced. No numeric parsing, no float conversion, and
        no other validation of either field's contents is performed.
        ``symbol``, ``timeframe``, ``support``, and ``resistance`` are
        copied through exactly as received, never normalized or
        transformed.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_analysis"`` mapping with
                ``"symbol"``, ``"timeframe"``, ``"support"``, and
                ``"resistance"`` values. Read through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={
            "support_resistance_reasoning": {"symbol": ...,
            "timeframe": ..., "support": ..., "resistance": ...,
            "level_state": ..., "level_strength": ...,
            "level_reason": ..., "evidence": ...}}``, ``error=None``,
            and ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            vision_analysis = parameters.get("vision_analysis")
        else:
            vision_analysis = None

        if isinstance(vision_analysis, Mapping):
            symbol = vision_analysis.get("symbol")
            timeframe = vision_analysis.get("timeframe")
            support = vision_analysis.get("support")
            resistance = vision_analysis.get("resistance")
        else:
            symbol = None
            timeframe = None
            support = None
            resistance = None

        support_exists = isinstance(support, str) and support.strip() != ""
        resistance_exists = isinstance(resistance, str) and resistance.strip() != ""

        if support_exists and resistance_exists:
            level_state = "DEFINED"
            level_strength = "KNOWN"
            level_reason = "Support and resistance identified"
            evidence = "LEVELS_PRESENT"
        else:
            level_state = "UNKNOWN"
            level_strength = None
            level_reason = None
            evidence = "UNKNOWN"

        return SkillResult(
            success=True,
            output={
                "support_resistance_reasoning": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "support": support,
                    "resistance": resistance,
                    "level_state": level_state,
                    "level_strength": level_strength,
                    "level_reason": level_reason,
                    "evidence": evidence,
                }
            },
            error=None,
            metadata={},
        )