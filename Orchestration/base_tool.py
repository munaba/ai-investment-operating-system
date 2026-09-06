"""BaseTool -- the common contract every Tool will implement
(Phase 5, Sprint 50).

Scope note (LOCKED baseline): this module introduces exactly one
abstraction and nothing more.

  1. ``BaseTool`` -- an ``abc.ABC`` with exactly three abstract
     members: the read-only properties ``name`` and ``description``,
     and the method ``execute(context)``. That is the entire
     contract.

This mirrors ``Orchestration.base_skill.BaseSkill`` (Sprint 46)
exactly, one layer down the architecture:

    Planner -> Skill -> Tool -> Services / Repository / API

This sprint defines only the interface every future Tool must
implement -- it does not wire ``BaseTool`` into any Skill, Planner,
Service, Repository, or API. No concrete Tool, no registry, no
resolver, and no execution path exists yet.

Phase 8, Sprint 86 update: ``execute()``'s documentation/contract now
states explicitly that it returns ``Orchestration.tool_result.
ToolResult`` (Sprint 86's new value object). This is a
documentation/annotation-only change -- the constructor is untouched
(``BaseTool`` still defines none), no attribute is added, no helper
method is added, and ``execute()`` remains abstract with no default
implementation. No concrete Tool is changed or created by this
update.

Explicitly NOT part of this milestone: a constructor, metadata,
priority, tags, category, permissions, config, schema, validation, a
registry id or aliases, requirements/dependencies, events, logging,
memory, planning, reflection, learning, a scheduler, a runtime, a
workflow, an executor, a host, or an agent. ``BaseTool`` knows about
none of those -- it is a pure, minimal interface describing "what a
Tool is," not how one is stored, resolved, scheduled, or run. There is
no ``execute_async()``, no ``schema()``, no ``validate()``, no
``permissions()``, no ``capability()``, no ``config()``, no
``metadata()``, no ``timeout()``, and no ``retry()`` anywhere in this
module.

No default implementation (LOCKED design constraint): ``execute()``
is abstract and raises ``NotImplementedError`` if a subclass somehow
calls it without overriding (which ``abc.ABC`` already prevents at
instantiation time) -- there is no pass-through, no helper method, no
convenience method, and no mixin anywhere in this module. A concrete
subclass MUST supply its own ``name``, ``description``, and
``execute()`` -- nothing is inherited for free.

Dependencies: this module imports the stdlib ``abc`` and ``typing``
modules, plus (as of Sprint 86) ``Orchestration.tool_result.
ToolResult`` -- solely to annotate ``execute()``'s return type and
document its contract. Nothing else. It is not imported by, and does
not import from, ``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_context.SkillContext``,
``Orchestration.skill_result.SkillResult``,
``Orchestration.file_system_skill.FileSystemSkill``,
``Orchestration.text_analysis_skill.TextAnalysisSkill``,
``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``,
``Orchestration.executor.Executor``, or any other Orchestration/
Agents/Core/Services/Providers/Repository/Database module. It is
additive-only, standing on its own until a future sprint has concrete
Tools derive from it.

Phase 8, Sprint 92 update: ``execute()``'s docstring is restated in
prose (annotation and signature unchanged from Sprint 86) to state
explicitly that every concrete Tool implementation MUST return a
``ToolResult``, and that ``BaseTool`` itself performs no validation,
no wrapping, and no execution of any kind. ``execute()`` remains
``@abstractmethod`` with its body unchanged (``raise
NotImplementedError``, no return statement) -- no constructor,
helper, attribute, state, cache, retry, logging, or validation was
added anywhere in this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from Orchestration.tool_result import ToolResult


class BaseTool(ABC):
    """The abstract contract every concrete Tool must satisfy.

    Purely an interface (LOCKED scope for Sprint 50): three abstract
    members, no state, no ``__init__`` of its own, no default
    behavior for any of them. ``abc.ABC`` enforces that ``BaseTool``
    itself can never be instantiated, and that no subclass can be
    instantiated either until it overrides all three abstract
    members.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The Tool's name.

        Returns:
            A ``str`` identifying this Tool.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """The Tool's description.

        Returns:
            A ``str`` describing this Tool.
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, context: Any) -> ToolResult:
        """Run this Tool.

        Every concrete Tool implementation of ``execute()`` MUST
        return an ``Orchestration.tool_result.ToolResult`` -- this
        is the whole of the contract this method documents.
        ``BaseTool`` itself performs no validation of that return
        value, no wrapping of it, and no execution of any kind: this
        method has no default implementation, no ``isinstance()``
        check, no coercion, and no side effect whatsoever -- it is a
        pure abstract declaration that always raises
        ``NotImplementedError``.

        Args:
            context: Whatever the concrete Tool needs to run. Opaque
                to ``BaseTool`` itself -- this contract does not
                constrain its type or shape in any way.

        Returns:
            A ``ToolResult`` (Sprint 86, ``Orchestration.tool_result.
            ToolResult``) describing what this Tool produced. This
            sprint (92) restates that contract explicitly in prose --
            ``BaseTool`` still supplies no default implementation,
            performs no validation or wrapping of the value a
            subclass returns, and does not itself execute anything.
        """
        raise NotImplementedError