"""EvidenceFusionSkill -- the first reasoning-fusion layer: five
independent reasoning objects -> one combined market-consensus view
(Phase 13, Sprint 149).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``EvidenceFusionSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["trend_reasoning"]``,
     ``context.parameters["momentum_reasoning"]``,
     ``context.parameters["volume_reasoning"]``,
     ``context.parameters["candlestick_reasoning"]``, and
     ``context.parameters["support_resistance_reasoning"]`` (the
     outputs of Sprints 144-148's five reasoning Skills) and produces
     a single, deterministic ``{"market_consensus": {...}}`` output.
     That is the entire behavior.

Sprints 144-148 each produced one independent piece of evidence.
``EvidenceFusionSkill`` is the first Skill that combines all five into
ONE market view -- it does not add new evidence of its own and it does
NOT make a trading decision. There is no BUY/SELL/WAIT signal, no
LONG/SHORT signal, no entry/exit, no stop loss, no take profit, no
position sizing, no capital allocation, no order, no portfolio action,
no risk assessment, no market prediction, no score, and no probability
anywhere in this module. It only reports how complete and how
consistent the five upstream evidence objects are.

FIELD EXTRACTION (LOCKED): each of the five ``*_bias`` fields is read
from the matching reasoning object's own ``"evidence"`` field, and
nothing else:

    trend_bias = trend_reasoning["evidence"]
    momentum_bias = momentum_reasoning["evidence"]
    volume_bias = volume_reasoning["evidence"]
    pattern_bias = candlestick_reasoning["evidence"]
    level_bias = support_resistance_reasoning["evidence"]

``symbol`` and ``timeframe`` are forwarded from ``trend_reasoning``
alone (its own ``"symbol"``/``"timeframe"`` fields), unchanged --
mirroring the "single source of truth" forwarding pattern already
used throughout Sprints 144-148. They are read defensively via
``.get(...)`` and default to ``None`` if ``trend_reasoning`` is
missing or not itself a ``Mapping``.

LOCKED RULE TABLE (checked in this exact order, first match wins):

    CASE 3: one or more of the five reasoning objects is missing, or
            present but not itself a ``Mapping``
            -> agreement="LOW", conflict=True, confidence="LOW",
               summary="Insufficient evidence"

    CASE 1: all five reasoning objects are present ``Mapping``s AND
            none of the five extracted ``*_bias`` values equals the
            string ``"UNKNOWN"``
            -> agreement="FULL", conflict=False, confidence="HIGH",
               summary="All evidence available"

    CASE 2: all five reasoning objects are present ``Mapping``s AND
            one or more of the five extracted ``*_bias`` values
            equals the string ``"UNKNOWN"``
            -> agreement="PARTIAL", conflict=False, confidence="MEDIUM",
               summary="Partial evidence available"

CASE 3 is checked first: it is purely a completeness check over the
five reasoning objects' own presence/shape, independent of what their
``"evidence"`` values happen to contain. CASE 1 vs. CASE 2 is then a
plain count of how many of the five extracted ``*_bias`` values equal
the literal string ``"UNKNOWN"`` (zero -> CASE 1, one or more ->
CASE 2). No numeric parsing, no scoring, and no weighting of any kind
-- the count is a direct equality check against the string
``"UNKNOWN"``.

This Skill DOES NOT determine BUY, SELL, WAIT, LONG, SHORT, ENTRY, or
EXIT -- it only reports how complete the evidence is.

ERROR HANDLING (LOCKED): this Skill never raises. A missing or
non-Mapping ``context.parameters`` behaves as though all five
reasoning objects are missing, which always falls through to CASE 3
above. This Skill always returns a ``SkillResult`` with
``success=True``.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseSkill`` already
supplies. Every member beyond the three ``BaseSkill``-required members
is deliberately absent -- the single fusion pass lives entirely inline
inside ``execute()`` itself.

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


class EvidenceFusionSkill(BaseSkill):
    """Combines five independent reasoning objects into one market
    consensus view.

    This Skill does not call an LLM, does not call a Tool, does not
    call another Skill, and does not perform any trading logic of any
    kind -- it only reads ``context.parameters`` defensively, checks
    that ``trend_reasoning``/``momentum_reasoning``/
    ``volume_reasoning``/``candlestick_reasoning``/
    ``support_resistance_reasoning`` are all present ``Mapping``s, and
    reads each one's own ``"evidence"`` field to derive
    ``trend_bias``/``momentum_bias``/``volume_bias``/``pattern_bias``/
    ``level_bias``, ``agreement``, ``conflict``, ``confidence``, and
    ``summary``. No state, no ``__init__`` of its own, no helper
    methods beyond what ``BaseSkill`` already supplies. Every member
    beyond the three ``BaseSkill``-required members is deliberately
    absent -- the single fusion pass lives entirely inline inside
    ``execute()`` itself. This Skill never connects to a network,
    never touches a filesystem, and never touches persistence of any
    kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"evidence_fusion"``.
        """
        return "evidence_fusion"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Combine independent reasoning evidence into one market consensus view."``.
        """
        return "Combine independent reasoning evidence into one market consensus view."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``' five
        ``*_reasoning`` values and produce a single
        ``{"market_consensus": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()`` --
        and calls no other Skill. It never calls an LLM, never
        performs any inference, never checks the filesystem, and
        never makes any network call. It never produces a
        BUY/SELL/WAIT/LONG/SHORT signal, an entry, an exit, a stop
        loss, a take profit, a position size, a capital allocation, an
        order, a portfolio action, a risk assessment, a market
        prediction, a score, or a probability of any kind.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, every one of the five ``*_reasoning``
        values behaves as though missing. Each of
        ``trend_reasoning``/``momentum_reasoning``/
        ``volume_reasoning``/``candlestick_reasoning``/
        ``support_resistance_reasoning`` must itself be a ``Mapping``
        to count as present; if one or more is missing or not a
        ``Mapping``, CASE 3 (insufficient evidence) applies
        regardless of the rest. Otherwise, each present reasoning
        object's own ``"evidence"`` field becomes its ``*_bias``
        value (``None`` if absent), and CASE 1 (full agreement)
        applies when none of the five equal the string ``"UNKNOWN"``,
        or CASE 2 (partial agreement) applies when one or more do.
        ``symbol``/``timeframe`` are forwarded from
        ``trend_reasoning`` alone, unchanged.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing ``"trend_reasoning"``,
                ``"momentum_reasoning"``, ``"volume_reasoning"``,
                ``"candlestick_reasoning"``, and
                ``"support_resistance_reasoning"`` mappings, each with
                its own ``"evidence"`` value. Read through
                defensively -- never copied, never mutated, and this
                method never raises regardless of shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"market_consensus": {
            "symbol": ..., "timeframe": ..., "trend_bias": ...,
            "momentum_bias": ..., "volume_bias": ...,
            "pattern_bias": ..., "level_bias": ..., "agreement": ...,
            "conflict": ..., "confidence": ..., "summary": ...}}``,
            ``error=None``, and ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            trend_reasoning = parameters.get("trend_reasoning")
            momentum_reasoning = parameters.get("momentum_reasoning")
            volume_reasoning = parameters.get("volume_reasoning")
            candlestick_reasoning = parameters.get("candlestick_reasoning")
            support_resistance_reasoning = parameters.get("support_resistance_reasoning")
        else:
            trend_reasoning = None
            momentum_reasoning = None
            volume_reasoning = None
            candlestick_reasoning = None
            support_resistance_reasoning = None

        all_present = (
            isinstance(trend_reasoning, Mapping)
            and isinstance(momentum_reasoning, Mapping)
            and isinstance(volume_reasoning, Mapping)
            and isinstance(candlestick_reasoning, Mapping)
            and isinstance(support_resistance_reasoning, Mapping)
        )

        if isinstance(trend_reasoning, Mapping):
            symbol = trend_reasoning.get("symbol")
            timeframe = trend_reasoning.get("timeframe")
        else:
            symbol = None
            timeframe = None

        trend_bias = trend_reasoning.get("evidence") if isinstance(trend_reasoning, Mapping) else None
        momentum_bias = momentum_reasoning.get("evidence") if isinstance(momentum_reasoning, Mapping) else None
        volume_bias = volume_reasoning.get("evidence") if isinstance(volume_reasoning, Mapping) else None
        pattern_bias = candlestick_reasoning.get("evidence") if isinstance(candlestick_reasoning, Mapping) else None
        level_bias = support_resistance_reasoning.get("evidence") if isinstance(support_resistance_reasoning, Mapping) else None

        if not all_present:
            agreement = "LOW"
            conflict = True
            confidence = "LOW"
            summary = "Insufficient evidence"
        else:
            biases = (trend_bias, momentum_bias, volume_bias, pattern_bias, level_bias)
            if all(bias != "UNKNOWN" for bias in biases):
                agreement = "FULL"
                conflict = False
                confidence = "HIGH"
                summary = "All evidence available"
            else:
                agreement = "PARTIAL"
                conflict = False
                confidence = "MEDIUM"
                summary = "Partial evidence available"

        return SkillResult(
            success=True,
            output={
                "market_consensus": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "trend_bias": trend_bias,
                    "momentum_bias": momentum_bias,
                    "volume_bias": volume_bias,
                    "pattern_bias": pattern_bias,
                    "level_bias": level_bias,
                    "agreement": agreement,
                    "conflict": conflict,
                    "confidence": confidence,
                    "summary": summary,
                }
            },
            error=None,
            metadata={},
        )