"""SkillToolRegistry -- a simple mapping catalog declaring which Tool
names belong to a given Skill (Phase 5, Sprint 58).

Scope note (LOCKED baseline): this module is a pure metadata catalog
and nothing more. It implements exactly two things:

  1. ``SkillToolRegistryError`` -- the module's own exception type,
     following the same convention as ``SkillRegistryError``/
     ``ToolRegistryError``/``SkillResolverError``/``ToolResolverError``
     (subclasses ``Core.exceptions.AgentError`` directly, no
     intermediate layer).
  2. ``SkillToolRegistry`` -- an in-memory catalog mapping a skill
     name (``str``) to a tuple of tool names (``Tuple[str, ...]``).
     It stores and returns the declared relationship; it never
     resolves, instantiates, executes, or validates the existence of
     any Skill or Tool. Tool names are plain, opaque strings -- this
     module does not require, define, or import ``BaseSkill``,
     ``BaseTool``, ``SkillRegistry``, ``ToolRegistry``,
     ``SkillResolver``, or ``ToolResolver`` at all.

This sprint introduces exactly the structural relationship

    Skill
        |
        v
    Tool

the same way ``SkillRegistry`` and ``ToolRegistry`` are kept separate
from each other -- ``SkillToolRegistry`` is a third, independent
catalog that merely *declares* which tool names a skill name is
associated with. It does not look either name up anywhere, does not
check that a skill or tool by that name actually exists, and does not
wire the two registries together.

Explicitly NOT part of this milestone: any execution surface (no
``run``/``execute``/``call``/``invoke``/``dispatch`` method anywhere
on this class), any routing or selection logic, any
resolver/executor/runtime built on top of this catalog, any singleton
or module-level global registry instance, and any wiring into
``BaseSkill``, ``BaseTool``, ``SkillRegistry``, ``ToolRegistry``,
``SkillResolver``, ``ToolResolver``, ``Planner``, ``Executor``,
``WorkflowRuntime``, ``WorkflowEngine``,
``WorkflowExecutionCoordinator``, ``EventBus``, ``Memory``,
``Reflection``, or ``LearningLoop``. This module is not imported by,
and does not import from, any of those. It is additive-only, standing
on its own until a future sprint builds something that consumes this
declared relationship.

Dependencies (LOCKED): this module imports only
``Core.exceptions.AgentError`` and the ``typing`` standard-library
module -- nothing else, not even ``Core.logger``.

Internal storage (LOCKED design constraint): a single, private, plain
``Dict[str, Tuple[str, ...]]`` -- no singleton, no module-level
state, no thread-safety machinery. Every ``SkillToolRegistry()``
instance owns its own independent dictionary; two instances never
share state.
"""

from __future__ import annotations

from typing import Dict, Tuple

from Core.exceptions import AgentError


class SkillToolRegistryError(AgentError):
    """Raised by :class:`SkillToolRegistry` for its own catalog-level
    failures.

    Following the same convention as ``SkillRegistryError``/
    ``ToolRegistryError``/``SkillResolverError``/``ToolResolverError``
    (all subclass ``Core.exceptions.AgentError`` directly). Raised by
    :meth:`SkillToolRegistry.register` for an invalid ``skill_name``,
    an invalid ``tool_names`` tuple, or a duplicate ``skill_name``; by
    :meth:`SkillToolRegistry.unregister` and
    :meth:`SkillToolRegistry.get` when ``skill_name`` is not
    registered. Never raised by :meth:`SkillToolRegistry.has` or
    :meth:`SkillToolRegistry.list` -- a missing name is a normal,
    expected outcome for those two (see their own docstrings).
    """


class SkillToolRegistry:
    """A simple in-memory catalog declaring which tool names belong to
    a given skill name.

    Purely a catalog (LOCKED scope for Sprint 58): stores and returns
    the ``Tuple[str, ...]`` of tool names it is given under a skill
    name, and nothing more. It never resolves a skill name or a tool
    name against any other registry, never instantiates a Skill or a
    Tool, and never validates that either actually exists -- both
    ``skill_name`` and every entry of ``tool_names`` are opaque
    strings to this class.

    Holds one private, mutable collection internally (a
    ``Dict[str, Tuple[str, ...]]``) but never exposes it or any live
    reference to it -- :meth:`get` and :meth:`list` always return
    values (a ``tuple`` and its elements) that are independent of the
    registry's internal mutable state going forward.
    """

    def __init__(self) -> None:
        """Start empty. No dependencies -- ``SkillToolRegistry`` does
        not call ``SkillRegistry``, ``ToolRegistry``, ``BaseSkill``,
        ``BaseTool``, or any resolver, so it has nothing to be
        constructed with. No singleton, no module-level global: each
        instance owns its own independent dictionary."""
        self._mapping: Dict[str, Tuple[str, ...]] = {}

    def register(self, skill_name: str, tool_names: Tuple[str, ...]) -> None:
        """Declare that ``skill_name`` is associated with
        ``tool_names``.

        Args:
            skill_name: The skill name to register the tool names
                under. Must be a non-empty ``str`` (whitespace-only is
                rejected).
            tool_names: The tuple of tool names associated with
                ``skill_name``. Must be a ``tuple`` whose every
                element is a non-empty ``str``, with no duplicate
                entries. Never inspected further, never resolved
                against any registry, and never checked for
                real-world existence.

        Raises:
            SkillToolRegistryError: If ``skill_name`` is not a
                non-empty ``str``; if ``tool_names`` is not a
                ``tuple``; if any element of ``tool_names`` is not a
                non-empty ``str``; if ``tool_names`` contains
                duplicate entries; or if ``skill_name`` is already
                registered (duplicate registration is rejected, not
                silently overwritten).
        """
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise SkillToolRegistryError(
                f"SkillToolRegistry.register requires a non-empty str "
                f"'skill_name'; got {skill_name!r}"
            )

        if not isinstance(tool_names, tuple):
            raise SkillToolRegistryError(
                f"SkillToolRegistry.register requires 'tool_names' to "
                f"be a tuple; got {tool_names!r}"
            )

        for tool_name in tool_names:
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise SkillToolRegistryError(
                    f"SkillToolRegistry.register requires every "
                    f"'tool_names' element to be a non-empty str; got "
                    f"{tool_name!r}"
                )

        if len(set(tool_names)) != len(tool_names):
            raise SkillToolRegistryError(
                f"SkillToolRegistry.register requires 'tool_names' to "
                f"contain no duplicate entries; got {tool_names!r}"
            )

        if skill_name in self._mapping:
            raise SkillToolRegistryError(
                f"SkillToolRegistry.register: tool names are already "
                f"registered under skill_name={skill_name!r} -- "
                f"duplicate registration is not allowed.",
                details={"skill_name": skill_name},
            )

        self._mapping[skill_name] = tool_names

    def unregister(self, skill_name: str) -> None:
        """Remove the tool-name tuple registered under ``skill_name``.

        Args:
            skill_name: The skill name whose mapping should be
                removed.

        Raises:
            SkillToolRegistryError: If no tool names are registered
                under ``skill_name``.
        """
        if skill_name not in self._mapping:
            raise SkillToolRegistryError(
                f"SkillToolRegistry.unregister: no tool names "
                f"registered under skill_name={skill_name!r}.",
                details={"skill_name": skill_name},
            )

        del self._mapping[skill_name]

    def get(self, skill_name: str) -> Tuple[str, ...]:
        """Return the tuple of tool names registered under
        ``skill_name``.

        Args:
            skill_name: The skill name to look up.

        Returns:
            The exact ``Tuple[str, ...]`` previously passed to
            :meth:`register` -- unmodified, unwrapped.

        Raises:
            SkillToolRegistryError: If no tool names are registered
                under ``skill_name``. A missing skill name here is
                treated as a genuine misuse -- callers ask for a
                mapping they expect to exist.
        """
        if skill_name not in self._mapping:
            raise SkillToolRegistryError(
                f"SkillToolRegistry.get: no tool names registered "
                f"under skill_name={skill_name!r}.",
                details={"skill_name": skill_name},
            )

        return self._mapping[skill_name]

    def has(self, skill_name: str) -> bool:
        """Return whether tool names are registered under
        ``skill_name``.

        Args:
            skill_name: The skill name to check.

        Returns:
            ``True`` if tool names are registered under
            ``skill_name``, else ``False``. Never raises for a
            missing name -- an ordinary, expected query.
        """
        return skill_name in self._mapping

    def list(self) -> Tuple[str, ...]:
        """Return every registered skill name, in insertion order.

        Returns:
            A ``Tuple[str, ...]`` of every registered skill name, in
            the order each was first registered. Always a fresh
            ``tuple`` snapshot -- never the internal ``dict``, its
            keys view, or any other object sharing live state with
            this registry. Mutating (or attempting to mutate) the
            returned tuple never affects the registry.
        """
        return tuple(self._mapping.keys())