"""ChartVisionSkill -- the project's first AI Vision capability
foundation (Phase 11, Sprint 135).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``ChartVisionSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["symbol"]``, ``context.parameters
     ["timeframe"]``, and ``context.parameters["chart_path"]`` and
     produces a single, deterministic ``{"vision_request": {...}}``
     output. That is the entire behavior.

This Skill intentionally does NOT call any LLM, does NOT perform any
AI inference, and does NOT read, open, decode, or otherwise touch any
image file. It only validates the shape of its input and produces a
``VisionRequest``-shaped dictionary for a future sprint (136+) to
consume. This sprint establishes the architecture and contract every
future Vision provider (Gemini Vision / Ollama Vision / Qwen-VL /
etc.) will follow -- nothing more.

No file reading, no image loading, no Pillow, no cv2, no matplotlib,
no inference, no Gemini, no Ollama, no HTTP, and no filesystem
validation (no ``os.path.exists()``) anywhere in this module. Only
the input contract itself is validated.

Rule table (LOCKED, applied to ``chart_path`` only):

    missing               -> status = "INVALID"
    empty string ("")     -> status = "INVALID"
    non-string value      -> status = "INVALID"
    any other string      -> status = "READY"

``symbol`` and ``timeframe`` are preserved exactly as received --
never normalized, coerced, validated, or otherwise transformed. They
are read defensively via ``.get(...)`` and default to ``None`` if
absent or if ``context.parameters`` is not a mapping at all.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``validate``, ``build``, ``normalize``, or
``check`` anywhere on this class; the single validation lives
entirely inline inside ``execute()`` itself. This Skill never raises
for malformed or missing input -- it always returns a
``SkillResult`` with ``success=True``.

Dependencies (LOCKED): this module imports only
``collections.abc.Mapping``, ``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib ``typing`` --
nothing else. In particular it does NOT import ``Providers``,
``Services``, ``Repository``, ``Database``, ``Agents``,
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


class ChartVisionSkill(BaseSkill):
    """Validates a single chart-image input and produces a
    deterministic ``VisionRequest`` dictionary.

    This Skill does not perform any AI inference and does not read,
    open, or decode any image file -- it only reads
    ``context.parameters`` defensively and derives a ``status`` for
    ``chart_path``. No state, no ``__init__`` of its own, no helper
    methods beyond what ``BaseSkill`` already supplies. Every method
    beyond the three ``BaseSkill``-required members is deliberately
    absent -- the single validation lives entirely inline inside
    ``execute()`` itself. This Skill never connects to a network,
    never touches a filesystem, and never touches persistence of any
    kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"chart_vision"``.
        """
        return "chart_vision"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Validate a chart image input and produce a deterministic vision request."``.
        """
        return "Validate a chart image input and produce a deterministic vision request."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``' ``"symbol"``,
        ``"timeframe"``, and ``"chart_path"`` values and produce a
        single ``{"vision_request": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never reads, opens, or decodes any image file, never checks
        the filesystem, and never makes any network call.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"symbol"``, ``"timeframe"``, and
        ``"chart_path"`` all behave as though missing (``None``) --
        never raising.

        ``chart_path`` decides ``status`` via the locked rule table:
        missing, an empty string, or any non-string value all yield
        ``"INVALID"``; any other string yields ``"READY"``.
        ``symbol`` and ``timeframe`` are copied through exactly as
        received, never normalized or transformed.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing ``"symbol"``, ``"timeframe"``, and
                ``"chart_path"`` values. Read through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"vision_request": {"symbol":
            ..., "timeframe": ..., "chart_path": ..., "status":
            ...}}``, ``error=None``, and ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            symbol = parameters.get("symbol")
            timeframe = parameters.get("timeframe")
            chart_path = parameters.get("chart_path")
        else:
            symbol = None
            timeframe = None
            chart_path = None

        if isinstance(chart_path, str) and chart_path != "":
            status = "READY"
        else:
            status = "INVALID"

        return SkillResult(
            success=True,
            output={
                "vision_request": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "chart_path": chart_path,
                    "status": status,
                }
            },
            error=None,
            metadata={},
        )