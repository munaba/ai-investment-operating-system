"""VisionServiceSkill -- the bridge between the Vision pipeline and
Vision Providers (Phase 11, Sprint 141).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``VisionServiceSkill`` -- a ``BaseSkill`` subclass that accepts
     exactly one constructor-injected dependency (``vision_provider``,
     a ``Providers.base_vision_provider.BaseVisionProvider``-shaped
     object), reads ``context.parameters["vision_prompt"]``
     defensively, and delegates it to
     ``vision_provider.analyze(vision_prompt)`` exactly once. That is
     the entire behavior.

This Skill performs NO image analysis, NO reasoning, NO parsing, and
NO AI logic of any kind. It does not know which Vision Provider it
holds (Gemini, Ollama, Qwen, or any other) -- it is a pure,
provider-agnostic delegation boundary between the Vision pipeline
(Sprints 135-138) and whatever concrete ``BaseVisionProvider`` (Sprint
139+) it was constructed with.

Constructor (LOCKED):

    ``__init__(self, vision_provider)`` stores ``vision_provider`` by
    identity on ``self._vision_provider``. No other constructor
    argument, no default value, no validation of ``vision_provider``'s
    shape or type. This Skill never constructs a Vision Provider
    itself -- one is always injected.

``execute(context)`` contract (LOCKED):

    ``context.parameters["vision_prompt"]`` is read defensively: if
    ``context.parameters`` is not a ``collections.abc.Mapping`` at
    all, ``vision_prompt`` behaves as though missing and is treated as
    ``None``. This method never raises for malformed or missing
    input.

    ``vision_provider.analyze(vision_prompt)`` is called exactly once,
    with ``vision_prompt`` forwarded by identity -- never copied,
    never inspected, never wrapped, never validated.

    The value ``vision_provider.analyze(...)`` returns is returned
    directly, by identity -- this method does not wrap it in a
    ``SkillResult``, does not rebuild it, does not copy it, does not
    inspect it, and does not modify it in any way. Whatever the
    injected Vision Provider returns is exactly what a caller of
    ``execute()`` receives.

No Tool usage of any kind: this Skill never calls
``self.execute_tool()`` or ``self.execute_tool_result()`` and never
resolves a Tool. No Service usage, no Repository usage, no
networking, no filesystem access anywhere in this module.

No state beyond the one injected dependency, no helper methods, no
nested functions, no additional abstraction, and no Provider
selection or dynamic routing logic -- this Skill is wired to exactly
one Vision Provider for its entire lifetime, decided once at
construction time by its caller.

Dependencies (LOCKED): this module imports only
``collections.abc.Mapping``, ``Orchestration.base_skill.BaseSkill``,
and stdlib ``typing`` -- nothing else. In particular it does NOT
import ``Providers.gemini_vision_provider.GeminiVisionProvider``,
``google.genai``, ``Ollama``, ``Qwen``, ``InternVL``, ``MiniCPM``,
``Llama``, ``Orchestration.skill_result.SkillResult``,
``Orchestration.executor.Executor``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_context.ToolContext``,
``Orchestration.base_tool.BaseTool``,
``Providers.provider_manager.ProviderManager``,
``Providers.provider_selector.ProviderSelector``, ``Services``,
``Database``, ``Agents``, ``os``, ``pathlib``, ``PIL``, ``cv2``,
``matplotlib``, ``requests``, ``sqlite3``, ``pandas``, ``numpy``,
``websocket``, ``asyncio``, ``threading``, or ``json``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill


class VisionServiceSkill(BaseSkill):
    """Delegates a ``VisionPrompt`` to a single, constructor-injected
    Vision Provider.

    This Skill performs no image analysis, no reasoning, no parsing,
    and no AI logic -- it only reads ``context.parameters``
    defensively and calls ``vision_provider.analyze(vision_prompt)``
    exactly once, returning whatever that call returns, unmodified
    and by identity. No helper methods, no nested functions, and no
    Provider selection or routing logic exist anywhere on this class
    -- it is wired to exactly one Vision Provider for its entire
    lifetime.
    """

    def __init__(self, vision_provider: Any) -> None:
        """Wire this Skill to exactly one Vision Provider.

        Args:
            vision_provider: The already-constructed Vision Provider
                to delegate every ``execute()`` call to. Stored by
                identity on ``self._vision_provider`` -- never
                copied, never validated, never wrapped. This Skill
                never constructs a Vision Provider of its own.
        """
        self._vision_provider = vision_provider

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"vision_service"``.
        """
        return "vision_service"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Delegate a vision prompt to a Vision Provider."``.
        """
        return "Delegate a vision prompt to a Vision Provider."

    def execute(self, context: Any) -> Any:
        """Run this Skill: read ``context.parameters``'
        ``"vision_prompt"`` value and delegate it to the injected
        Vision Provider.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never performs any image analysis, reasoning, parsing, or AI
        logic of its own.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, ``"vision_prompt"`` behaves as though
        missing and ``vision_prompt`` is ``None`` -- never raising.

        ``self._vision_provider.analyze(vision_prompt)`` is called
        exactly once, with ``vision_prompt`` forwarded by identity.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                optionally containing a ``"vision_prompt"`` value.
                Read through defensively -- never copied, never
                mutated, and this method never raises regardless of
                its shape.

        Returns:
            Exactly what ``self._vision_provider.analyze(
            vision_prompt)`` returns -- by identity. Not wrapped,
            not rebuilt, not copied, not inspected, not modified.
        """
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            vision_prompt = parameters.get("vision_prompt")
        else:
            vision_prompt = None

        return self._vision_provider.analyze(vision_prompt)