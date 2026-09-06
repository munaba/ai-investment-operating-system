"""VisionPromptSkill -- the stable Vision Prompt contract (Phase 11,
Sprint 137).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``VisionPromptSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["vision_analysis"]`` (the output of Sprint
     136's ``Orchestration.vision_analysis_skill.VisionAnalysisSkill``)
     and produces a single, deterministic ``{"vision_prompt": {...}}``
     output. That is the entire behavior.

This Skill intentionally does NOT call Gemini, does NOT call Ollama,
and does NOT perform any image inference of any kind. It only
converts a valid ``VisionAnalysis`` mapping into a deterministic
``VisionPrompt`` mapping by deriving one new field, ``prompt_status``,
from the incoming ``analysis_status`` value, and by attaching one
fixed ``prompt`` string. This becomes the single source of truth for
Vision prompting that every future Vision Provider will consume --
nothing more.

Rule table (LOCKED, applied to ``vision_analysis["analysis_status"]``
only):

    analysis_status == "PENDING"  -> prompt_status = "READY"
    analysis_status == "INVALID"  -> prompt_status = "INVALID"
    anything else                 -> prompt_status = "UNKNOWN"

``symbol``, ``timeframe``, ``chart_path``, ``status``, and
``analysis_status`` are preserved exactly as received -- never
normalized, coerced, validated, or otherwise transformed. They are
read defensively via ``.get(...)`` and default to ``None`` if absent,
or if ``vision_analysis``/``context.parameters`` is not a mapping at
all.

The ``prompt`` string is FIXED -- exactly the same string every
execution, regardless of input. No formatting changes, no markdown
generation, no calculations:

    "Analyze this stock chart.\\n\\nFocus only on:\\n1. Trend\\n2.
    Support\\n3. Resistance\\n4. Candlestick Pattern\\n5. Volume\\n6.
    RSI\\n7. MACD\\n\\nReturn JSON only."

Malformed input (LOCKED):

    missing "vision_analysis"              -> UNKNOWN object
    "vision_analysis" not a Mapping         -> UNKNOWN object
    non-Mapping context.parameters          -> UNKNOWN object

An "UNKNOWN object" means ``symbol``/``timeframe``/``chart_path``/
``status``/``analysis_status`` are all ``None`` and ``prompt_status``
is ``"UNKNOWN"`` -- the fixed ``prompt`` string is still attached
unchanged. This Skill never raises for malformed or missing input --
it always returns a ``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``validate``, ``derive``, ``build``,
``normalize``, or ``check`` anywhere on this class; the single
derivation lives entirely inline inside ``execute()`` itself.

Dependencies (LOCKED): this module imports only
``collections.abc.Mapping``, ``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib ``typing`` --
nothing else. In particular it does NOT import ``VisionEngine``,
``VisionManager``, ``VisionProvider``, ``Gemini``, ``Ollama``,
``Qwen``, ``InternVL``, ``MiniCPM``, ``Llama``, ``PromptBuilder``,
``PromptEngine``, ``Factory``, ``Registry``, ``Pipeline``,
``Workflow``, ``Coordinator``, ``Helper``, ``Repository``,
``Service``, ``Services``, ``Database``, ``Agents``,
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


class VisionPromptSkill(BaseSkill):
    """Converts a valid ``VisionAnalysis`` into a deterministic
    ``VisionPrompt`` object.

    This Skill does not call Gemini, does not call Ollama, and does
    not perform any image inference -- it only reads
    ``context.parameters`` defensively and derives a
    ``prompt_status`` for ``vision_analysis["analysis_status"]``,
    then attaches a fixed ``prompt`` string. No state, no
    ``__init__`` of its own, no helper methods beyond what
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
            The literal string ``"vision_prompt"``.
        """
        return "vision_prompt"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Convert a valid vision analysis into a deterministic vision prompt."``.
        """
        return "Convert a valid vision analysis into a deterministic vision prompt."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_analysis"`` value and produce a single
        ``{"vision_prompt": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never calls Gemini, never calls Ollama, never performs any
        image inference, never checks the filesystem, and never
        makes any network call.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"vision_analysis"`` behaves as though
        missing. If ``"vision_analysis"`` is missing, or is present
        but not itself a ``Mapping``, ``symbol``/``timeframe``/
        ``chart_path``/``status``/``analysis_status`` all behave as
        though missing (``None``) -- never raising.

        ``analysis_status`` decides ``prompt_status`` via the locked
        rule table: ``"PENDING"`` yields ``"READY"``, ``"INVALID"``
        yields ``"INVALID"``, and everything else (including a
        missing or malformed ``vision_analysis``) yields ``"UNKNOWN"``.
        ``symbol``, ``timeframe``, ``chart_path``, ``status``, and
        ``analysis_status`` are copied through exactly as received,
        never normalized or transformed. ``prompt`` is a fixed string,
        identical on every execution regardless of input.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_analysis"`` mapping with
                ``"symbol"``, ``"timeframe"``, ``"chart_path"``,
                ``"status"``, and ``"analysis_status"`` values. Read
                through defensively -- never copied, never mutated,
                and this method never raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"vision_prompt": {"symbol":
            ..., "timeframe": ..., "chart_path": ..., "status": ...,
            "analysis_status": ..., "prompt_status": ..., "prompt":
            ...}}``, ``error=None``, and ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            vision_analysis = parameters.get("vision_analysis")
        else:
            vision_analysis = None

        if isinstance(vision_analysis, Mapping):
            symbol = vision_analysis.get("symbol")
            timeframe = vision_analysis.get("timeframe")
            chart_path = vision_analysis.get("chart_path")
            status = vision_analysis.get("status")
            analysis_status = vision_analysis.get("analysis_status")
        else:
            symbol = None
            timeframe = None
            chart_path = None
            status = None
            analysis_status = None

        if analysis_status == "PENDING":
            prompt_status = "READY"
        elif analysis_status == "INVALID":
            prompt_status = "INVALID"
        else:
            prompt_status = "UNKNOWN"

        prompt = (
            "Analyze this stock chart.\n\n"
            "Focus only on:\n"
            "1. Trend\n"
            "2. Support\n"
            "3. Resistance\n"
            "4. Candlestick Pattern\n"
            "5. Volume\n"
            "6. RSI\n"
            "7. MACD\n\n"
            "Return JSON only."
        )

        return SkillResult(
            success=True,
            output={
                "vision_prompt": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "chart_path": chart_path,
                    "status": status,
                    "analysis_status": analysis_status,
                    "prompt_status": prompt_status,
                    "prompt": prompt,
                }
            },
            error=None,
            metadata={},
        )