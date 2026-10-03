"""VisionResultSkill -- the canonical Vision Result contract (Phase
11, Sprint 138).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``VisionResultSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["vision_prompt"]`` (the output of Sprint
     137's ``Orchestration.vision_prompt_skill.VisionPromptSkill``)
     and produces a single, deterministic ``{"vision_result": {...}}``
     output. That is the entire behavior.

This Skill intentionally does NOT call Gemini, does NOT call Ollama,
and does NOT perform any image inference of any kind. It only
converts a valid ``VisionPrompt`` mapping into a deterministic
``VisionResult`` mapping by deriving one new field, ``result_status``,
from the incoming ``prompt_status`` value, and by attaching one fixed,
all-``null`` ``result`` object. This becomes the permanent JSON schema
that every future Vision Provider MUST produce -- nothing more.

Rule table (LOCKED, applied to ``vision_prompt["prompt_status"]``
only):

    prompt_status == "READY"    -> result_status = "WAITING"
    prompt_status == "INVALID"  -> result_status = "INVALID"
    anything else               -> result_status = "UNKNOWN"

``symbol``, ``timeframe``, ``chart_path``, ``status``,
``analysis_status``, and ``prompt_status`` are preserved exactly as
received -- never normalized, coerced, validated, or otherwise
transformed. They are read defensively via ``.get(...)`` and default
to ``None`` if absent, or if ``vision_prompt``/``context.parameters``
is not a mapping at all.

The ``result`` object is FIXED -- exactly the same eight keys every
execution, regardless of input, every value ``None``:

    trend, support, resistance, candlestick_pattern, volume_signal,
    rsi_signal, macd_signal, confidence

No AI, no inference, no calculations, no formatting, no JSON parsing
anywhere in this module.

Malformed input (LOCKED):

    missing "vision_prompt"              -> UNKNOWN object
    "vision_prompt" not a Mapping         -> UNKNOWN object
    non-Mapping context.parameters        -> UNKNOWN object

An "UNKNOWN object" means ``symbol``/``timeframe``/``chart_path``/
``status``/``analysis_status``/``prompt_status`` are all ``None`` and
``result_status`` is ``"UNKNOWN"`` -- the fixed, all-``None`` ``result``
object is still attached unchanged. This Skill never raises for
malformed or missing input -- it always returns a ``SkillResult`` with
``success=True``.

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
``numpy``, ``websocket``, ``asyncio``, ``threading``, or ``json``.
This Skill never calls ``self.execute_tool()`` or
``self.execute_tool_result()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class VisionResultSkill(BaseSkill):
    """Converts a valid ``VisionPrompt`` into a deterministic
    ``VisionResult`` object.

    This Skill does not call Gemini, does not call Ollama, and does
    not perform any image inference -- it only reads
    ``context.parameters`` defensively and derives a
    ``result_status`` for ``vision_prompt["prompt_status"]``, then
    attaches a fixed, all-``None`` ``result`` object. No state, no
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
            The literal string ``"vision_result"``.
        """
        return "vision_result"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Convert a valid vision prompt into a deterministic vision result."``.
        """
        return "Convert a valid vision prompt into a deterministic vision result."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_prompt"`` value and produce a single
        ``{"vision_result": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never calls Gemini, never calls Ollama, never performs any
        image inference, never checks the filesystem, and never
        makes any network call.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"vision_prompt"`` behaves as though
        missing. If ``"vision_prompt"`` is missing, or is present but
        not itself a ``Mapping``, ``symbol``/``timeframe``/
        ``chart_path``/``status``/``analysis_status``/
        ``prompt_status`` all behave as though missing (``None``) --
        never raising.

        ``prompt_status`` decides ``result_status`` via the locked
        rule table: ``"READY"`` yields ``"WAITING"``, ``"INVALID"``
        yields ``"INVALID"``, and everything else (including a
        missing or malformed ``vision_prompt``) yields ``"UNKNOWN"``.
        ``symbol``, ``timeframe``, ``chart_path``, ``status``,
        ``analysis_status``, and ``prompt_status`` are copied through
        exactly as received, never normalized or transformed. The
        ``result`` object is fixed: exactly eight keys (``trend``,
        ``support``, ``resistance``, ``candlestick_pattern``,
        ``volume_signal``, ``rsi_signal``, ``macd_signal``,
        ``confidence``), every value ``None``, identical on every
        execution regardless of input.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_prompt"`` mapping with
                ``"symbol"``, ``"timeframe"``, ``"chart_path"``,
                ``"status"``, ``"analysis_status"``, and
                ``"prompt_status"`` values. Read through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"vision_result": {"symbol":
            ..., "timeframe": ..., "chart_path": ..., "status": ...,
            "analysis_status": ..., "prompt_status": ...,
            "result_status": ..., "result": {"trend": None,
            "support": None, "resistance": None,
            "candlestick_pattern": None, "volume_signal": None,
            "rsi_signal": None, "macd_signal": None,
            "confidence": None}}}``, ``error=None``, and
            ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            vision_prompt = parameters.get("vision_prompt")
        else:
            vision_prompt = None

        if isinstance(vision_prompt, Mapping):
            symbol = vision_prompt.get("symbol")
            timeframe = vision_prompt.get("timeframe")
            chart_path = vision_prompt.get("chart_path")
            status = vision_prompt.get("status")
            analysis_status = vision_prompt.get("analysis_status")
            prompt_status = vision_prompt.get("prompt_status")
        else:
            symbol = None
            timeframe = None
            chart_path = None
            status = None
            analysis_status = None
            prompt_status = None

        if prompt_status == "READY":
            result_status = "WAITING"
        elif prompt_status == "INVALID":
            result_status = "INVALID"
        else:
            result_status = "UNKNOWN"

        result = {
            "trend": None,
            "support": None,
            "resistance": None,
            "candlestick_pattern": None,
            "volume_signal": None,
            "rsi_signal": None,
            "macd_signal": None,
            "confidence": None,
        }

        return SkillResult(
            success=True,
            output={
                "vision_result": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "chart_path": chart_path,
                    "status": status,
                    "analysis_status": analysis_status,
                    "prompt_status": prompt_status,
                    "result_status": result_status,
                    "result": result,
                }
            },
            error=None,
            metadata={},
        )