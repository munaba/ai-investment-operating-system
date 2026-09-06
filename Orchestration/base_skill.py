"""BaseSkill -- the common contract every Skill will implement
(Phase 5, Sprint 46).

Scope note (LOCKED baseline): this module introduces exactly one
abstraction and nothing more.

  1. ``BaseSkill`` -- an ``abc.ABC`` with exactly three abstract
     members: the read-only properties ``name`` and ``description``,
     and the method ``execute(context)``. That is the entire
     contract.

Explicitly NOT part of this milestone: metadata, priority, tags,
category, permissions, config, schema, validation, a registry id or
aliases, requirements/dependencies, events, logging, memory,
planning, reflection, learning, a scheduler, a runtime, a workflow, an
executor, a host, or an agent. ``BaseSkill`` knows about none of
those -- it is a pure, minimal interface describing "what a Skill
is," not how one is stored, resolved, scheduled, or run.

No default implementation (LOCKED design constraint): ``execute()``
is abstract and raises ``NotImplementedError`` if a subclass somehow
calls it without overriding (which ``abc.ABC`` already prevents at
instantiation time) -- there is no pass-through, no helper method, no
convenience method, and no mixin anywhere in this module. A concrete
subclass MUST supply its own ``name``, ``description``, and
``execute()`` -- nothing is inherited for free.

Dependencies (LOCKED): this module imports only the stdlib ``abc``
and ``typing`` modules -- nothing else. It is not imported by, and
does not import from, ``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``,
``Orchestration.executor.Executor``, or any other Orchestration/
Agents/Core module. It is additive-only, standing on its own until a
future sprint has concrete Skills derive from it.

Phase 8, Sprint 87 update: ``execute_tool()``'s return annotation and
docstring now state explicitly that a Tool is required to return
``Orchestration.tool_result.ToolResult`` (Sprint 86's new value
object). This is a documentation/annotation-only change -- the one
new import (``Orchestration.tool_result.ToolResult``) exists solely
for that annotation. ``execute_tool()``'s implementation, control
flow, and every other behavior are byte-for-byte identical to Sprint
85: it still resolves the Tool via ``self._resolve_tool(tool_name)``
exactly once and returns ``tool.execute(context)`` exactly once,
completely unexamined -- no ``isinstance()`` check, no inspection, no
copy, no wrapping, no caching, no logging, no retry, and no transform
of the result was added.

Phase 8, Sprint 88 update: ``execute()``'s return annotation and
docstring now state explicitly that every concrete Skill is required
to return ``Orchestration.skill_result.SkillResult`` (Sprint 47's
value object). This is a documentation/annotation-only change -- the
one new import (``Orchestration.skill_result.SkillResult``) exists
solely for that annotation. ``execute()`` remains abstract, still
raises ``NotImplementedError``, still has no default implementation,
no pass-through, and no change to its decorators -- byte-for-byte
identical in behavior to Sprint 46.

Phase 8, Sprint 94 update: ``execute_tool()`` now constructs an
``Orchestration.tool_invocation.ToolInvocation`` immediately before
resolving the Tool, to establish the immutable Skill/Tool execution
boundary one sprint ahead of it being put to any use. The one new
import (``Orchestration.tool_invocation.ToolInvocation``) exists
solely for that construction. The ``ToolInvocation`` instance is
intentionally unused: it is never passed to ``self._resolve_tool``
or to ``tool.execute``, never inspected, never modified, never
cached, and never stored on ``self`` or returned. Tool resolution
and execution remain byte-for-byte identical to Sprint 87 -- still
``tool = self._resolve_tool(tool_name)`` followed by ``return
tool.execute(context)``, in that order, each called exactly once,
with no ``isinstance()`` check, no wrapping, no caching, no logging,
and no retry added anywhere in this method.

Phase 9, Sprint 100 update (Skill / Tool Integration): ``BaseSkill``
gains exactly one new concrete public method, ``execute_tool_result(
tool_name, context)`` -- the first integration between ``ToolResult``
and ``SkillResult``. It reuses ``self.execute_tool(tool_name,
context)`` exactly once (no duplicated resolve/execute logic) and
constructs exactly one ``SkillResult``, forwarding ``success``,
``output``, ``error``, and ``metadata`` straight from the returned
``ToolResult`` -- by identity, with no copy, no inspection, no
validation, no transform, no wrapping, no caching, no retry, and no
logging. Any exception raised by ``execute_tool()`` (including a
missing-resolver ``SkillError`` or any Tool-side failure) propagates
unchanged; ``execute_tool_result()`` never catches anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from Core.exceptions import AgentError
from Orchestration.skill_result import SkillResult
from Orchestration.tool_invocation import ToolInvocation
from Orchestration.tool_result import ToolResult


class SkillError(AgentError):
    """Raised by :class:`BaseSkill`'s own helper methods for their
    own failures.

    Following the same convention as ``ExecutorError``/
    ``SkillContextError``/``ToolResolverError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised by
    :meth:`BaseSkill.execute_tool` when the Skill instance has no
    ``_resolve_tool`` attribute (i.e. no ``ToolResolver`` was ever
    injected by an ``Executor``). Never raised for any other reason --
    a resolver-side or Tool-side failure propagates unchanged, never
    wrapped as a ``SkillError``.
    """


class BaseSkill(ABC):
    """The abstract contract every concrete Skill must satisfy.

    Purely an interface (LOCKED scope for Sprint 46): three abstract
    members, no state, no ``__init__`` of its own, no default
    behavior for any of them. ``abc.ABC`` enforces that ``BaseSkill``
    itself can never be instantiated, and that no subclass can be
    instantiated either until it overrides all three abstract
    members.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The Skill's name.

        Returns:
            A ``str`` identifying this Skill.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """The Skill's description.

        Returns:
            A ``str`` describing this Skill.
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, context: Any) -> SkillResult:
        """Run this Skill.

        As of Sprint 88, every concrete Skill is contractually
        required to return an ``Orchestration.skill_result.
        SkillResult`` -- this method's return annotation reflects
        that contract. ``execute()`` remains abstract: this base
        method still supplies no implementation, no default return
        value, and no pass-through of any kind. It merely documents
        the required return type; it does not construct, validate,
        or otherwise touch ``SkillResult`` itself.

        Args:
            context: Whatever the concrete Skill needs to run. Opaque
                to ``BaseSkill`` itself -- this contract does not
                constrain its type or shape in any way.

        Returns:
            The ``SkillResult`` the concrete Skill produces.
        """
        raise NotImplementedError

    def execute_tool(self, tool_name: Any, context: Any) -> ToolResult:
        """Resolve a Tool by name and run it (Phase 8 Sprint 85 --
        Skill Executes Tool; Sprint 87 -- ``ToolResult`` contract).

        A thin, concrete convenience method -- not part of the
        abstract contract -- that lets any Skill make use of the
        ``ToolResolver`` an ``Executor`` may have injected as
        ``self._resolve_tool`` (see ``Orchestration.executor.Executor
        .invoke_current_skill()``, Phase 8 Sprint 84). This is the
        only place ``BaseSkill`` reaches for ``_resolve_tool`` --
        nothing else in this module reads or sets that attribute.

        As of Sprint 86, every Tool's ``execute()`` is contractually
        required to return an ``Orchestration.tool_result.
        ToolResult`` -- this method's return annotation reflects that
        contract, but ``execute_tool()`` neither enforces nor relies
        on it: the ``ToolResult`` returned by ``tool.execute(context)``
        is propagated straight through, by identity, completely
        unexamined. There is no ``isinstance()`` check, no
        inspection, no copy, no wrapping, no caching, no logging, no
        retry, and no transform of the result anywhere in this
        method.

        As of Sprint 94, this method also constructs an
        ``Orchestration.tool_invocation.ToolInvocation`` immediately
        before resolving the Tool, to mark the immutable Skill/Tool
        execution boundary. That ``ToolInvocation`` is intentionally
        unused: it is not passed to ``self._resolve_tool`` or to
        ``tool.execute``, not inspected, not modified, not cached,
        and not stored or returned. Tool resolution and execution are
        otherwise unchanged -- still exactly
        ``tool = self._resolve_tool(tool_name)`` followed by
        ``return tool.execute(context)``.

        Args:
            tool_name: Passed straight through, unexamined, to
                ``self._resolve_tool(tool_name)``.
            context: Passed straight through, unexamined, to
                ``tool.execute(context)`` -- the exact same object,
                never copied or wrapped.

        Returns:
            The ``ToolResult`` that ``tool.execute(context)``
            returns, propagated unchanged -- the exact same object by
            identity, never a copy or a wrapper.

        Raises:
            SkillError: if this Skill instance has no
                ``_resolve_tool`` attribute at all (no ``ToolResolver``
                was ever injected).
            Exception: any exception raised by
                ``self._resolve_tool(tool_name)`` or by
                ``tool.execute(context)`` propagates unchanged --
                never caught, never wrapped.
        """
        if not hasattr(self, "_resolve_tool"):
            raise SkillError(
                "BaseSkill.execute_tool() requires '_resolve_tool' to "
                "have been injected (no ToolResolver was ever "
                "supplied by the Executor)"
            )

        invocation = ToolInvocation(
            tool_name=tool_name,
            context=context,
            metadata={}
        )

        tool = self._resolve_tool(tool_name)

        return tool.execute(context)

    def execute_tool_result(self, tool_name: Any, context: Any) -> SkillResult:
        """Run a Tool and convert its ``ToolResult`` into a
        ``SkillResult`` (Phase 9 Sprint 100 -- the first integration
        between ``ToolResult`` and ``SkillResult``).

        A thin, concrete convenience method -- not part of the
        abstract contract -- that reuses ``self.execute_tool(
        tool_name, context)`` exactly once and does nothing else but
        rewrap its return value as a ``SkillResult``. Every field is
        forwarded straight from the ``ToolResult`` by identity --
        ``success``, ``output``, ``error``, and ``metadata`` are
        passed to the ``SkillResult`` constructor exactly as received,
        with no copy, no ``isinstance()`` check, no inspection, no
        validation, no transform, no wrapping, no caching, no
        logging, and no retry anywhere in this method.

        Args:
            tool_name: Passed straight through, unexamined, to
                ``self.execute_tool(tool_name, context)``.
            context: Passed straight through, unexamined, to
                ``self.execute_tool(tool_name, context)``.

        Returns:
            A single, freshly constructed ``SkillResult`` whose
            ``success``/``output``/``error``/``metadata`` fields are
            exactly the ``ToolResult``'s own field values, by
            identity.

        Raises:
            Exception: any exception raised by
                ``self.execute_tool(tool_name, context)`` (including
                ``SkillError`` for a missing resolver, or any
                exception a Tool's own ``execute()`` raises)
                propagates unchanged -- never caught, never wrapped.
        """
        tool_result = self.execute_tool(tool_name, context)

        result = SkillResult(
            success=tool_result.success,
            output=tool_result.output,
            error=tool_result.error,
            metadata=tool_result.metadata,
        )
        return result