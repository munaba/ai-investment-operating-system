"""GeminiVisionProvider -- API activation for the Gemini Vision
Provider (Phase 11, Sprint 142).

Scope note (LOCKED baseline): this module introduces exactly one
behavioral change to the existing ``GeminiVisionProvider`` (Sprint
140) and nothing more.

  1. ``GeminiVisionProvider.analyze(vision_prompt)`` now actually
     talks to the real Gemini Vision SDK (``google.genai``): it reads
     the chart image bytes from ``vision_prompt["chart_path"]``,
     sends ``image + prompt`` to Gemini via
     ``client.models.generate_content(...)``, and returns the raw
     model response text unmodified inside the ``VisionResult``
     contract. That is the entire behavior change.

This sprint establishes ONLY the provider -> Gemini communication
channel. It performs NO chart interpretation, NO reasoning about the
response, NO trading logic, and NO parsing of any kind -- not JSON
parsing, not markdown parsing, not regex parsing. The Gemini response
text is stored verbatim as ``result["raw_response"]`` and nothing
else is derived from it. Trend detection, candlestick recognition,
support/resistance, RSI, MACD, confidence calculation, and any
trading recommendation are explicitly out of scope for this module
and are deferred to later sprints.

``name`` (LOCKED, unchanged from Sprint 140):

    Returns the literal string ``"gemini"``.

``description`` (LOCKED, unchanged from Sprint 140):

    Returns the literal string ``"Gemini Vision Provider"``.

``analyze(vision_prompt)`` contract (LOCKED):

    Input  -- ``vision_prompt``, the object produced by Sprint 137's
              ``Orchestration.vision_prompt_skill.VisionPromptSkill``.
              Read defensively via ``.get(...)`` if it is a
              ``collections.abc.Mapping``; treated as though every
              field were missing (``None``) otherwise. Never
              mutated, never validated, never coerced.
    Output -- the exact ``VisionResult`` contract (Sprint 138): a
              dict with ``symbol``, ``timeframe``, ``chart_path``,
              ``status``, ``analysis_status``, and ``prompt_status``
              forwarded unchanged from ``vision_prompt``, plus
              ``result_status`` and ``result`` derived from the
              outcome of the Gemini call (see below).

On success:

    1. The image bytes at ``vision_prompt["chart_path"]`` are read
       from disk (``open(chart_path, "rb").read()``).
    2. ``Core.config.config`` supplies ``GEMINI_API_KEY`` and
       ``GEMINI_MODEL`` -- the same configuration keys and lookup
       style already used by ``Providers.gemini.GeminiProvider``.
       No API key is ever hardcoded.
    3. ``google.genai.Client(api_key=...)`` is constructed and
       ``client.models.generate_content(model=..., contents=[image,
       prompt_text])`` is called exactly once, sending the image
       bytes and ``vision_prompt["prompt"]`` together.
    4. ``result_status`` is set to ``"COMPLETED"`` and ``result`` is
       set to exactly ``{"raw_response": response.text}`` -- the raw
       Gemini response text, verbatim, with no other field added.

On any failure (missing/unreadable image, missing configuration,
SDK not installed, network error, or any other exception raised
anywhere in the steps above):

    ``result_status`` is set to ``"FAILED"`` and ``result`` is set
    to exactly ``{"raw_response": None}``. This method never raises
    -- every exception is caught and converted into this fixed
    ``FAILED`` shape.

No parsing of the Gemini response of any kind: no JSON extraction, no
markdown parsing, no regex parsing, no trend/candlestick/support/
resistance/RSI/MACD detection, no confidence calculation, no trading
recommendation. This provider remains strictly model-specific --
communication with Gemini only.

No state, no ``__init__`` of its own, no helper classes, no helper
methods, no nested functions, beyond what ``BaseVisionProvider``
already supplies. Every member beyond the three
``BaseVisionProvider``-required members is deliberately absent; the
single Gemini call lives entirely inline inside ``analyze()`` itself.
A fresh ``genai.Client`` is constructed on every ``analyze()`` call --
there is no cached client, no connection pool, and no instance
attribute of any kind.

Dependencies (LOCKED): this module imports only
``collections.abc.Mapping``, ``Core.config.config``,
``Orchestration.base_vision_provider.BaseVisionProvider``, and stdlib
``typing`` at module scope. ``google.genai`` (and ``google.genai.
types``) is imported lazily, inside ``analyze()`` itself -- exactly
the same lazy-import convention already used by
``Providers.gemini.GeminiProvider.connect()`` -- so this module
remains importable even in environments where the SDK is not
installed. In particular this module does NOT import ``Ollama``,
``Qwen``, ``InternVL``, ``MiniCPM``, ``Llama``, ``VisionEngine``,
``VisionManager``, ``VisionFactory``, ``VisionRegistry``,
``VisionPipeline``, ``VisionWorkflow``, ``VisionCoordinator``,
``VisionService``, ``VisionRepository``,
``Orchestration.base_skill.BaseSkill``,
``Orchestration.base_tool.BaseTool``,
``Orchestration.vision_prompt_skill.VisionPromptSkill``,
``Orchestration.vision_result_skill.VisionResultSkill``,
``Orchestration.executor.Executor``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_registry.ToolRegistry``,
``Providers.provider_manager.ProviderManager``,
``Providers.provider_selector.ProviderSelector``, ``Database``,
``Agents``, ``PIL``, ``cv2``, ``matplotlib``, ``requests``,
``sqlite3``, ``pandas``, ``numpy``, ``websocket``, ``asyncio``,
``threading``, or ``json``. It does not define ``VisionEngine``,
``ProviderManager``, ``Factory``, ``Registry``, ``Coordinator``,
``Workflow``, ``Pipeline``, ``Service``, or ``Repository`` -- no
helper classes of any kind exist in this module beyond
``GeminiVisionProvider`` itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Core.config import config
from Providers.base_vision_provider import BaseVisionProvider


class GeminiVisionProvider(BaseVisionProvider):
    """The production Gemini Vision Provider -- now wired to the
    real Gemini Vision SDK.

    This class forwards the incoming ``VisionPrompt`` fields
    unchanged, reads the chart image at ``chart_path``, sends it
    together with ``prompt`` to Gemini via ``google.genai``, and
    returns the raw response text inside the Sprint 138
    ``VisionResult`` contract. It performs no chart interpretation,
    no reasoning, no parsing, and no trading logic of any kind. No
    state, no ``__init__`` of its own, no helper methods beyond what
    ``BaseVisionProvider`` already supplies. The single Gemini call
    lives entirely inline inside ``analyze()`` itself.
    """

    @property
    def name(self) -> str:
        """This Vision Provider's stable name.

        Returns:
            The literal string ``"gemini"``.
        """
        return "gemini"

    @property
    def description(self) -> str:
        """This Vision Provider's human-readable description.

        Returns:
            The literal string ``"Gemini Vision Provider"``.
        """
        return "Gemini Vision Provider"

    def analyze(self, vision_prompt: Any) -> Any:
        """Send a vision prompt's chart image and prompt text to the
        real Gemini Vision SDK and return the raw response.

        This method reads ``vision_prompt`` defensively: if it is
        not a ``Mapping`` at all, ``symbol``/``timeframe``/
        ``chart_path``/``status``/``analysis_status``/
        ``prompt_status``/``prompt`` all behave as though missing
        (``None``) -- never raising. When it is a ``Mapping``, those
        fields are read through exactly as received, never
        normalized or transformed.

        On success, this method reads the image bytes at
        ``chart_path``, constructs a fresh ``google.genai.Client``
        using ``Core.config.config``'s ``GEMINI_API_KEY``/
        ``GEMINI_MODEL`` (never hardcoded), and calls
        ``client.models.generate_content(...)`` exactly once with
        the image bytes and ``prompt`` together. ``result_status``
        becomes ``"COMPLETED"`` and ``result`` becomes exactly
        ``{"raw_response": <Gemini response text>}`` -- no parsing,
        no JSON extraction, no trend/candlestick/support/resistance/
        RSI/MACD detection, no confidence calculation, no trading
        recommendation is ever derived from it.

        On any exception -- a missing/unreadable image, missing
        configuration, the SDK not being installed, a network error,
        or any other failure -- this method never raises:
        ``result_status`` becomes ``"FAILED"`` and ``result``
        becomes exactly ``{"raw_response": None}``.

        Args:
            vision_prompt: The object produced by Sprint 137's
                ``Orchestration.vision_prompt_skill.VisionPromptSkill``.
                Read through defensively -- never copied, never
                mutated, and this method never raises regardless of
                its shape.

        Returns:
            A freshly constructed ``dict`` matching the exact
            ``VisionResult`` contract (Sprint 138): ``{"symbol":
            ..., "timeframe": ..., "chart_path": ..., "status": ...,
            "analysis_status": ..., "prompt_status": ...,
            "result_status": "COMPLETED" | "FAILED", "result":
            {"raw_response": <str or None>}}``.
        """
        if isinstance(vision_prompt, Mapping):
            symbol = vision_prompt.get("symbol")
            timeframe = vision_prompt.get("timeframe")
            chart_path = vision_prompt.get("chart_path")
            status = vision_prompt.get("status")
            analysis_status = vision_prompt.get("analysis_status")
            prompt_status = vision_prompt.get("prompt_status")
            prompt_text = vision_prompt.get("prompt")
        else:
            symbol = None
            timeframe = None
            chart_path = None
            status = None
            analysis_status = None
            prompt_status = None
            prompt_text = None

        try:
            from google import genai
            from google.genai import types

            with open(chart_path, "rb") as image_file:
                image_bytes = image_file.read()

            image_part = types.Part.from_bytes(
                data=image_bytes, mime_type="image/png"
            )

            client = genai.Client(api_key=config.get("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model=config.get("GEMINI_MODEL"),
                contents=[image_part, prompt_text],
            )

            result_status = "COMPLETED"
            result = {"raw_response": response.text}
        except Exception:  # noqa: BLE001
            result_status = "FAILED"
            result = {"raw_response": None}

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "chart_path": chart_path,
            "status": status,
            "analysis_status": analysis_status,
            "prompt_status": prompt_status,
            "result_status": result_status,
            "result": result,
        }