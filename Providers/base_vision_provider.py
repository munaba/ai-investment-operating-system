"""BaseVisionProvider -- the abstract interface every future Vision
Provider will implement (Phase 11, Sprint 139).

Scope note (LOCKED baseline): this module introduces exactly one
abstraction and nothing more.

  1. ``BaseVisionProvider`` -- an ``abc.ABC`` with exactly three
     abstract members: the read-only properties ``name`` and
     ``description``, and the method ``analyze(vision_prompt)``. That
     is the entire contract.

This is NOT Gemini. This is NOT Ollama. This is NOT Qwen. This
module defines the production contract only -- it performs no
inference of any kind and is not wired into any Skill, Tool, Planner,
registry, or execution path.

``analyze(vision_prompt)`` contract (LOCKED):

    Input  -- ``vision_prompt``, the object produced by Sprint 137's
              ``Orchestration.vision_prompt_skill.VisionPromptSkill``.
    Output -- MUST be the exact ``VisionResult`` contract established
              by Sprint 138's
              ``Orchestration.vision_result_skill.VisionResultSkill``
              (a mapping with ``symbol``, ``timeframe``,
              ``chart_path``, ``status``, ``analysis_status``,
              ``prompt_status``, ``result_status``, and a fixed
              ``result`` object containing ``trend``, ``support``,
              ``resistance``, ``candlestick_pattern``,
              ``volume_signal``, ``rsi_signal``, ``macd_signal``, and
              ``confidence``).

``BaseVisionProvider`` itself performs no inference, no validation,
no coercion, and no wrapping of any kind -- ``analyze()`` is a pure
abstract declaration with no default implementation.

Explicitly NOT part of this milestone (LOCKED): a constructor,
instance state, helper methods, nested functions, metadata, priority,
tags, category, permissions, config, schema, validation, a registry
id or aliases, caching, retries, timeouts, logging, events, memory,
planning, reflection, learning, a scheduler, a runtime, a workflow,
an executor, a host, an agent, or any concrete Vision Provider (no
Gemini, no Ollama, no InternVL, no Qwen, no MiniCPM, no Llama). There
is no ``Factory``, no ``Registry``, no ``Manager``, no
``Coordinator``, no ``Workflow``, no ``Pipeline``, no ``Service``,
and no ``Repository`` anywhere in this module.

No default implementation (LOCKED design constraint): ``analyze()``
is abstract and raises ``NotImplementedError`` if called directly
without a subclass override (which ``abc.ABC`` already prevents at
instantiation time). ``BaseVisionProvider`` defines no ``__init__``
of its own -- it inherits ``object``'s -- and carries no instance
state whatsoever. A concrete subclass MUST supply its own ``name``,
``description``, and ``analyze()`` -- nothing is inherited for free.

No networking, no filesystem: this module performs no network I/O
and no filesystem I/O of any kind, and imports no networking or
filesystem module (no ``socket``, no ``requests``, no ``urllib``,
no ``http``, no ``os``, no ``pathlib``, no ``open``, no ``io``).

Dependencies (LOCKED): this module imports only the stdlib ``abc``
and ``typing`` modules -- nothing else. In particular it does NOT
import ``Gemini``, ``Ollama``, ``Qwen``, ``InternVL``, ``MiniCPM``,
``Llama``, ``VisionEngine``, ``VisionManager``, ``VisionFactory``,
``VisionRegistry``, ``VisionPipeline``, ``VisionWorkflow``,
``VisionCoordinator``, ``VisionService``, ``VisionRepository``,
``Orchestration.base_skill.BaseSkill``,
``Orchestration.base_tool.BaseTool``,
``Orchestration.vision_prompt_skill.VisionPromptSkill``,
``Orchestration.vision_result_skill.VisionResultSkill``,
``Orchestration.executor.Executor``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_registry.ToolRegistry``, ``Providers.
provider_manager.ProviderManager``,
``Providers.provider_selector.ProviderSelector``, ``Database``,
``Agents``, ``os``, ``pathlib``, ``PIL``, ``cv2``, ``matplotlib``,
``requests``, ``sqlite3``, ``pandas``, ``numpy``, ``websocket``,
``asyncio``, ``threading``, or ``json``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseVisionProvider(ABC):
    """The abstract contract every concrete Vision Provider must
    satisfy.

    Purely an interface (LOCKED scope for Sprint 139): three abstract
    members, no state, no ``__init__`` of its own, no default
    behavior for any of them. ``abc.ABC`` enforces that
    ``BaseVisionProvider`` itself can never be instantiated, and that
    no subclass can be instantiated either until it overrides all
    three abstract members. This class performs no inference, no
    networking, and no filesystem access -- it only declares the
    shape a future Vision Provider (Gemini, Ollama, Qwen, or any
    other) must take.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The Vision Provider's name.

        Returns:
            A ``str`` identifying this Vision Provider.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """The Vision Provider's description.

        Returns:
            A ``str`` describing this Vision Provider.
        """
        raise NotImplementedError

    @abstractmethod
    def analyze(self, vision_prompt: Any) -> Any:
        """Analyze a vision prompt and produce a Vision Result.

        Every concrete Vision Provider implementation of
        ``analyze()`` MUST return the exact ``VisionResult`` contract
        established by Sprint 138's
        ``Orchestration.vision_result_skill.VisionResultSkill`` --
        this is the whole of the contract this method documents.
        ``BaseVisionProvider`` itself performs no inference, no
        validation of the input, no wrapping of the return value, and
        no execution of any kind: this method has no default
        implementation, no ``isinstance()`` check, no coercion, and
        no side effect whatsoever -- it is a pure abstract
        declaration that always raises ``NotImplementedError``.

        Args:
            vision_prompt: The object produced by Sprint 137's
                ``Orchestration.vision_prompt_skill.VisionPromptSkill``.
                Opaque to ``BaseVisionProvider`` itself -- this
                contract does not constrain its type or shape in any
                way.

        Returns:
            The ``VisionResult`` contract (Sprint 138) describing
            what this Vision Provider produced.
            ``BaseVisionProvider`` supplies no default implementation
            and performs no validation or wrapping of the value a
            subclass returns.
        """
        raise NotImplementedError