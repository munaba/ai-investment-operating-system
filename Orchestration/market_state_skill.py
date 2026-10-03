"""MarketStateSkill -- the first high-level market understanding layer:
one combined market-consensus view -> one abstract market state
(Phase 13, Sprint 150).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``MarketStateSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["market_consensus"]`` (the output of Sprint
     149's ``EvidenceFusionSkill``) and produces a single,
     deterministic ``{"market_state": {...}}`` output. That is the
     entire behavior.

``EvidenceFusionSkill`` already combines all reasoning evidence into
one market-consensus view. ``MarketStateSkill`` is the first Skill
that transforms that consensus into one abstract description of the
current market condition -- it does NOT produce a trading decision.
There is no BUY/SELL/WAIT signal, no LONG/SHORT signal, no entry, no
exit, no stop loss, no take profit, no position size, no capital
allocation, no order, no portfolio action, no risk assessment, no
recommendation, and no other trading signal anywhere in this module.
It only tells "what is the market currently like?"

FIELD EXTRACTION (LOCKED): ``agreement`` and ``confidence`` are read
directly from ``market_consensus["agreement"]`` and
``market_consensus["confidence"]``, and nothing else. ``symbol``,
``timeframe``, and ``summary`` are forwarded from ``market_consensus``
unchanged, read defensively via ``.get(...)`` and defaulting to
``None`` if ``market_consensus`` is missing or not itself a
``Mapping``.

LOCKED RULE TABLE (checked in this exact order, first match wins):

    CASE 1: agreement == "FULL" AND confidence == "HIGH"
            -> market_state="CONFIRMED", state_strength="HIGH",
               state_reason="Evidence strongly aligned"

    CASE 2: agreement == "PARTIAL"
            -> market_state="DEVELOPING", state_strength="MEDIUM",
               state_reason="Evidence partially aligned"

    CASE 3: anything else (including a missing or non-Mapping
            ``market_consensus``, a missing ``agreement``/
            ``confidence``, or any other combination)
            -> market_state="UNCERTAIN", state_strength="LOW",
               state_reason="Evidence incomplete"

CASE 1 is checked first, requiring both ``agreement == "FULL"`` and
``confidence == "HIGH"`` simultaneously. CASE 2 is checked next,
requiring only ``agreement == "PARTIAL"`` (``confidence`` is not
consulted for CASE 2). CASE 3 is the fall-through default for every
other combination, including malformed input. No numeric parsing, no
scoring, and no weighting of any kind -- the rule table is a plain,
ordered set of equality checks.

This Skill DOES NOT predict price and DOES NOT recommend trades --
there is no BUY, SELL, WAIT, ENTRY, EXIT, LONG, SHORT, POSITION,
CAPITAL, PORTFOLIO, ORDER, RISK, RECOMMENDATION, or SIGNAL anywhere in
this module.

ERROR HANDLING (LOCKED): this Skill never raises. A missing or
non-Mapping ``context.parameters``, a missing or non-Mapping
``market_consensus``, or a missing ``agreement``/``confidence`` all
fall through to CASE 3 above. This Skill always returns a
``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseSkill`` already
supplies. Every member beyond the three ``BaseSkill``-required members
is deliberately absent -- the single state-derivation pass lives
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
never calls ``self.execute_tool()`` or ``self.execute_tool_result()``,
and never calls another Skill.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class MarketStateSkill(BaseSkill):
    """Transforms one market-consensus view into one abstract market
    state.

    This Skill does not call an LLM, does not call a Tool, does not
    call another Skill, and does not perform any trading logic of any
    kind -- it only reads ``context.parameters`` defensively, reads
    ``market_consensus``'s own ``"agreement"``/``"confidence"``
    fields, and applies the locked three-case rule table to derive
    ``market_state``/``state_strength``/``state_reason``. No state, no
    ``__init__`` of its own, no helper methods beyond what
    ``BaseSkill`` already supplies. Every member beyond the three
    ``BaseSkill``-required members is deliberately absent -- the
    single state-derivation pass lives entirely inline inside
    ``execute()`` itself. This Skill never connects to a network,
    never touches a filesystem, and never touches persistence of any
    kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"market_state"``.
        """
        return "market_state"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Describe the current market condition from a market consensus view."``.
        """
        return "Describe the current market condition from a market consensus view."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``market_consensus`` value and produce a single
        ``{"market_state": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()`` --
        and calls no other Skill. It never calls an LLM, never
        performs any inference, never checks the filesystem, and
        never makes any network call. It never produces a
        BUY/SELL/WAIT/LONG/SHORT signal, an entry, an exit, a
        position, a capital allocation, an order, a portfolio action,
        a risk assessment, a recommendation, or any other trading
        signal of any kind.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``market_consensus`` behaves as though
        missing. ``market_consensus`` must itself be a ``Mapping`` to
        be read at all; if it is missing or not a ``Mapping``, CASE 3
        (uncertain) applies. Otherwise, ``agreement`` and
        ``confidence`` are read directly from ``market_consensus``,
        and ``symbol``/``timeframe``/``summary`` are forwarded
        unchanged. CASE 1 (confirmed) applies when
        ``agreement == "FULL"`` and ``confidence == "HIGH"``; CASE 2
        (developing) applies when ``agreement == "PARTIAL"``; CASE 3
        (uncertain) applies to everything else.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing ``"market_consensus"``, itself a mapping
                with ``"symbol"``, ``"timeframe"``, ``"agreement"``,
                ``"confidence"``, and ``"summary"`` values. Read
                through defensively -- never copied, never mutated,
                and this method never raises regardless of shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"market_state": {
            "symbol": ..., "timeframe": ..., "market_state": ...,
            "state_strength": ..., "state_reason": ...,
            "confidence": ..., "agreement": ..., "summary": ...}}``,
            ``error=None``, and ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            market_consensus = parameters.get("market_consensus")
        else:
            market_consensus = None

        if isinstance(market_consensus, Mapping):
            symbol = market_consensus.get("symbol")
            timeframe = market_consensus.get("timeframe")
            agreement = market_consensus.get("agreement")
            confidence = market_consensus.get("confidence")
            summary = market_consensus.get("summary")
        else:
            symbol = None
            timeframe = None
            agreement = None
            confidence = None
            summary = None

        if agreement == "FULL" and confidence == "HIGH":
            market_state = "CONFIRMED"
            state_strength = "HIGH"
            state_reason = "Evidence strongly aligned"
        elif agreement == "PARTIAL":
            market_state = "DEVELOPING"
            state_strength = "MEDIUM"
            state_reason = "Evidence partially aligned"
        else:
            market_state = "UNCERTAIN"
            state_strength = "LOW"
            state_reason = "Evidence incomplete"

        return SkillResult(
            success=True,
            output={
                "market_state": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "market_state": market_state,
                    "state_strength": state_strength,
                    "state_reason": state_reason,
                    "confidence": confidence,
                    "agreement": agreement,
                    "summary": summary,
                }
            },
            error=None,
            metadata={},
        )