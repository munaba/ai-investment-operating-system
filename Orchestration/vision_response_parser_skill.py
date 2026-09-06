"""VisionResponseParserSkill -- the first AI Intelligence layer:
raw Gemini text -> structured Vision fields (Phase 12, Sprint 143).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``VisionResponseParserSkill`` -- a ``BaseSkill`` subclass that
     reads ``context.parameters["vision_result"]`` (the
     ``VisionResult`` object produced by Sprint 142's
     ``Providers.gemini_vision_provider.GeminiVisionProvider``,
     matching the Sprint 138 ``VisionResult`` contract) and produces
     a single, deterministic ``{"vision_analysis": {...}}`` output.
     That is the entire behavior.

This Skill performs PARSING ONLY. It never makes a trading decision,
never scores anything, never recommends anything, and never reasons
about the chart. It reads ``vision_result["result"]["raw_response"]``
-- the verbatim Gemini text stored by ``GeminiVisionProvider`` -- and
extracts exactly eight fields from it using plain, line-oriented text
parsing:

    trend, support, resistance, candlestick_pattern, volume_signal,
    rsi_signal, macd_signal, confidence

``symbol``, ``timeframe``, ``chart_path``, ``status``,
``analysis_status``, ``prompt_status``, and ``result_status`` are
forwarded from ``vision_result`` completely unchanged -- never
normalized, coerced, validated, derived, or otherwise transformed.
They are read defensively via ``.get(...)`` and default to ``None``
if absent, or if ``vision_result``/``context.parameters`` is not a
mapping at all.

PARSING ALGORITHM (LOCKED, simple text parsing only -- no AI
reasoning, no second LLM call, no JSON library, no regex library):

    1. If ``raw_response`` is not a ``str``, every one of the eight
       fields is ``None`` and parsing stops there.
    2. Otherwise, ``raw_response`` is split into lines
       (``str.splitlines()``). Each line without a ``":"`` is
       skipped.
    3. Each remaining line is split on its FIRST ``":"`` into a label
       and a value (``str.partition(":")``).
    4. The label is normalized: surrounding whitespace and the
       characters `` \\t\\r\\n*_-#>bullet"'.`` are stripped from both
       ends, internal ``"_"``/``"-"`` are turned into spaces, runs of
       internal whitespace are collapsed to one space, and the result
       is lower-cased. This turns ``"**Trend**"``, ``"- Trend"``,
       ``"Candlestick_Pattern"``, and ``"Trend"`` all into the same
       normalized label.
    5. The normalized label is looked up in a fixed synonym table
       (``trend``, ``support``, ``resistance``, ``candlestick`` /
       ``candlestick pattern``, ``volume`` / ``volume signal``,
       ``rsi`` / ``rsi signal``, ``macd`` / ``macd signal``,
       ``confidence``). A label that matches nothing in the table is
       ignored -- no guessing at what an unrecognized label might
       mean.
    6. The value is stripped the same way (whitespace, a single
       trailing comma, then the same strip-character set). If the
       stripped value -- compared case-insensitively -- is empty, or
       is one of ``"null"``/``"none"``/``"n/a"``/``"na"``/
       ``"unknown"``/``"-"``, the field is set to ``None`` rather than
       that literal placeholder text.
    7. The FIRST line that resolves to a given field wins; any later
       line for the same field is ignored, so parsing a fixed
       ``raw_response`` string always yields the same result.

If a field's label is never found on any line, that field is
``None`` -- nothing is invented, guessed, defaulted to a non-``None``
placeholder, or inferred from context.

FORBIDDEN (LOCKED): this Skill never produces a BUY/SELL/HOLD
recommendation, a score, a probability, a prediction, a strategy, a
``PositionSizing``, a ``CapitalAllocation``, or a ``TradingDecision``
of any kind. It performs parsing only.

ERROR HANDLING (LOCKED): this Skill never raises. Malformed input at
any level -- non-Mapping ``context.parameters``, a missing or
non-Mapping ``vision_result``, a missing or non-Mapping ``result``,
or a missing/non-``str`` ``raw_response`` -- simply yields ``None``
for every one of the eight parsed fields (and, for the higher-level
malformations, ``None`` for the forwarded fields too). This Skill
always returns a ``SkillResult`` with ``success=True``.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseSkill`` already
supplies. Every method beyond the three ``BaseSkill``-required
members is deliberately absent -- the single parsing pass lives
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

_FIELD_LABELS = {
    "trend": "trend",
    "support": "support",
    "resistance": "resistance",
    "candlestick": "candlestick_pattern",
    "candlestick pattern": "candlestick_pattern",
    "volume": "volume_signal",
    "volume signal": "volume_signal",
    "rsi": "rsi_signal",
    "rsi signal": "rsi_signal",
    "macd": "macd_signal",
    "macd signal": "macd_signal",
    "confidence": "confidence",
}

_STRIP_CHARS = " \t\r\n*_-#>\u2022\"'."

_NULL_TOKENS = {"", "null", "none", "n/a", "na", "unknown", "-"}


class VisionResponseParserSkill(BaseSkill):
    """Parses a raw Gemini vision response into structured fields.

    This Skill does not call Gemini, does not call Ollama, and does
    not perform any image inference or reasoning of any kind -- it
    only reads ``context.parameters`` defensively, splits
    ``vision_result["result"]["raw_response"]`` into lines, and
    matches each ``label: value`` line against a fixed synonym table
    for exactly eight fields. No state, no ``__init__`` of its own,
    no helper methods beyond what ``BaseSkill`` already supplies.
    Every method beyond the three ``BaseSkill``-required members is
    deliberately absent -- the single parsing pass lives entirely
    inline inside ``execute()`` itself. This Skill never connects to
    a network, never touches a filesystem, and never touches
    persistence of any kind. It never produces a trading decision, a
    score, or a recommendation of any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"vision_response_parser"``.
        """
        return "vision_response_parser"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Parse a raw Gemini vision response into structured vision analysis fields."``.
        """
        return "Parse a raw Gemini vision response into structured vision analysis fields."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters``'
        ``"vision_result"`` value and produce a single
        ``{"vision_analysis": {...}}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never calls Gemini, never calls Ollama, never performs any
        image inference or reasoning, never checks the filesystem,
        and never makes any network call. It never produces a
        BUY/SELL/HOLD recommendation, a score, a probability, a
        prediction, a strategy, a ``PositionSizing``, a
        ``CapitalAllocation``, or a ``TradingDecision``.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"vision_result"`` behaves as though
        missing. If ``"vision_result"`` is missing, or is present but
        not itself a ``Mapping``, ``symbol``/``timeframe``/
        ``chart_path``/``status``/``analysis_status``/
        ``prompt_status``/``result_status`` all behave as though
        missing (``None``), and ``raw_response`` behaves as though
        missing too -- never raising. The same defensive handling
        applies one level down to ``vision_result["result"]``: if it
        is missing or not a ``Mapping``, ``raw_response`` is ``None``.

        If ``raw_response`` is a ``str``, it is split into lines and
        each ``label: value`` line is matched against a fixed synonym
        table for exactly eight fields (``trend``, ``support``,
        ``resistance``, ``candlestick_pattern``, ``volume_signal``,
        ``rsi_signal``, ``macd_signal``, ``confidence``); see the
        module docstring for the full normalization and null-token
        rules. The first line that resolves to a given field wins.
        Any field whose label is never found is ``None`` -- nothing
        is invented or guessed. If ``raw_response`` is not a ``str``
        (missing, ``None``, or any other type), all eight fields are
        ``None``.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"vision_result"`` mapping with
                ``"symbol"``, ``"timeframe"``, ``"chart_path"``,
                ``"status"``, ``"analysis_status"``,
                ``"prompt_status"``, ``"result_status"``, and a
                ``"result"`` mapping holding ``"raw_response"``. Read
                through defensively -- never copied, never mutated,
                and this method never raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"vision_analysis": {
            "symbol": ..., "timeframe": ..., "chart_path": ...,
            "status": ..., "analysis_status": ..., "prompt_status":
            ..., "result_status": ..., "trend": ..., "support": ...,
            "resistance": ..., "candlestick_pattern": ...,
            "volume_signal": ..., "rsi_signal": ..., "macd_signal":
            ..., "confidence": ...}}``, ``error=None``, and
            ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            vision_result = parameters.get("vision_result")
        else:
            vision_result = None

        if isinstance(vision_result, Mapping):
            symbol = vision_result.get("symbol")
            timeframe = vision_result.get("timeframe")
            chart_path = vision_result.get("chart_path")
            status = vision_result.get("status")
            analysis_status = vision_result.get("analysis_status")
            prompt_status = vision_result.get("prompt_status")
            result_status = vision_result.get("result_status")
            inner_result = vision_result.get("result")
        else:
            symbol = None
            timeframe = None
            chart_path = None
            status = None
            analysis_status = None
            prompt_status = None
            result_status = None
            inner_result = None

        if isinstance(inner_result, Mapping):
            raw_response = inner_result.get("raw_response")
        else:
            raw_response = None

        parsed_fields: dict = {}
        if isinstance(raw_response, str):
            for line in raw_response.splitlines():
                if ":" not in line:
                    continue

                raw_label, _, raw_value = line.partition(":")

                label = raw_label.strip(_STRIP_CHARS)
                label = label.replace("_", " ").replace("-", " ")
                label = " ".join(label.split()).lower()

                field_name = _FIELD_LABELS.get(label)
                if field_name is None or field_name in parsed_fields:
                    continue

                value = raw_value.strip()
                if value.endswith(","):
                    value = value[:-1]
                value = value.strip(_STRIP_CHARS)

                if value.lower() in _NULL_TOKENS:
                    value = None

                parsed_fields[field_name] = value

        return SkillResult(
            success=True,
            output={
                "vision_analysis": {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "chart_path": chart_path,
                    "status": status,
                    "analysis_status": analysis_status,
                    "prompt_status": prompt_status,
                    "result_status": result_status,
                    "trend": parsed_fields.get("trend"),
                    "support": parsed_fields.get("support"),
                    "resistance": parsed_fields.get("resistance"),
                    "candlestick_pattern": parsed_fields.get("candlestick_pattern"),
                    "volume_signal": parsed_fields.get("volume_signal"),
                    "rsi_signal": parsed_fields.get("rsi_signal"),
                    "macd_signal": parsed_fields.get("macd_signal"),
                    "confidence": parsed_fields.get("confidence"),
                }
            },
            error=None,
            metadata={},
        )