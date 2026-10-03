"""VisionAnalysisSkill -- the stable Vision Analysis contract (Phase
11, Sprint 136).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``VisionAnalysisSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["vision_request"]`` (the output of Sprint
     135's ``Orchestration.chart_vision_skill.ChartVisionSkill``) and
     produces a single, deterministic ``{"vision_analysis": {...}}``
     output. That is the entire behavior.

This Skill intentionally does NOT call Gemini, does NOT call Ollama,
and does NOT perform any image inference of any kind. It only
converts a valid ``VisionRequest`` mapping into a deterministic
``VisionAnalysis`` mapping by deriving one new field,
``analysis_status``, from the incoming ``status`` value. This
establishes the stable contract every future Vision Provider will
build on top of -- nothing more.

Rule table (LOCKED, applied to ``vision_request["status"]`` only):

    status == "READY"    -> analysis_status = "PENDING"
    status == "INVALID"  -> analysis_status = "INVALID"
    anything else        -> analysis_status = "UNKNOWN"

``symbol``, ``timeframe``, ``chart_path``, and ``status`` are
preserved exactly as received -- never normalized, coerced,
validated, or otherwise transformed. They are read defensively via
``.get(...)`` and default to ``None`` if absent, or if
``vision_request``/``context.parameters`` is not a mapping at all.

Malformed input (LOCKED):

    missing "vision_request"               -> UNKNOWN object
    "vision_request" not a Mapping          -> UNKNOWN object
    non-Mapping context.parameters          -> UNKNOWN object

An "UNKNOWN object" means ``symbol``/``timeframe``/``chart_path``/
``status`` are all ``None`` and ``analysis_status`` is ``"UNKNOWN"``.
This Skill never raises for malformed or missing input -- it always
returns a ``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``validate``, ``derive``, ``normalize``, or
``check`` anywhere on this class; the single derivation lives
entirely inline inside ``execute()`` itself.

Dependencies (LOCKED): this module imports only
``collections.abc.Mapping``, ``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib ``typing`` --
nothing else. In particular it does NOT import ``VisionEngine``,
``VisionManager``, ``VisionProvider``, ``Gemini``, ``Ollama``,
``Qwen``, ``InternVL``, ``Factory``, ``Registry``, ``Pipeline``,
``Workflow``, ``Coordinator``, ``Helper``, ``Repository``,
``Service``, ``Services``, ``Repository``, ``Database``, ``Agents``,
``Orchestration.executor.Executor``,
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


class VisionAnalysisSkill(BaseSkill):
    """Converts a valid ``VisionRequest`` into a deterministic
    ``VisionAnalysis`` object.

    This Skill does not call Gemini, does not call Ollama, and does
    not perform any image inference -- it only reads
    ``context.parameters`` defensively and derives an
    ``analysis_status`` for ``vision_request["status"]``. No state,
    no ``__init__`` of its own, no helper methods beyond what
    ``BaseSkill`` already supplies. Every method beyond the three
    ``BaseSkill``-required members is deliberately absent -- the
    single derivation lives entirely inline inside ``execute()``
    itself. This Skill never connects to a network, never touches a
    filesystem, and never touches persistence of any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"vision_analysis"``.
        """
        return "vision_analysis"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Convert a valid vision request into a deterministic vision analysis."``.
        """
        return "Convert a valid vision request into a deterministic vision analysis."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_request"`` value and produce a single
        ``{"vision_analysis": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never calls Gemini, never calls Ollama, never performs any
        image inference, never checks the filesystem, and never
        makes any network call.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"vision_request"`` behaves as though
        missing. If ``"vision_request"`` is missing, or is present
        but not itself a ``Mapping``, ``symbol``/``timeframe``/
        ``chart_path``/``status`` all behave as though missing
        (``None``) -- never raising.

        ``status`` decides ``analysis_status`` via the locked rule
        table: ``"READY"`` yields ``"PENDING"``, ``"INVALID"`` yields
        ``"INVALID"``, and everything else (including a missing or
        malformed ``vision_request``) yields ``"UNKNOWN"``.
        ``symbol``, ``timeframe``, ``chart_path``, and ``status`` are
        copied through exactly as received, never normalized or
        transformed.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_request"`` mapping with
                ``"symbol"``, ``"timeframe"``, ``"chart_path"``, and
                ``"status"`` values. Read through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"vision_analysis": {"symbol":
            ..., "timeframe": ..., "chart_path": ..., "status": ...,
            "analysis_status": ...}}``, ``error=None``, and
            ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            vision_request = parameters.get("vision_request")
        else:
            vision_request = None

        if isinstance(vision_request, Mapping):
            symbol = vision_request.get("symbol")
            timeframe = vision_request.get("timeframe")
            chart_path = vision_request.get("chart_path")
            status = vision_request.get("status")
        else:
            symbol = None
            timeframe = None
            chart_path = None
            status = None

        if status == "READY":
            analysis_status = "PENDING"
        elif status == "INVALID":
            analysis_status = "INVALID"
        else:
            analysis_status = "UNKNOWN"

        return SkillResult(
            success=True,
            output={
                "vision_analysis": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "chart_path": chart_path,
                    "status": status,
                    "analysis_status": analysis_status,
                }
            },
            error=None,
            metadata={},
        )