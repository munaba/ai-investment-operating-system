
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Tuple

from Core.exceptions import AgentError


class ToolDescriptorError(AgentError):
    """Raised when ``ToolDescriptor`` is given invalid inputs at
    construction time.

    Following the same convention as ``TaskError``/
    ``ExecutionContextError``/``WorkflowError``/``SkillResultError``/
    ``ToolContextError``/``SkillContextError``/``CapabilityError``/
    ``SkillDescriptorError`` (all subclass ``Core.exceptions.
    AgentError`` directly). Raised by ``ToolDescriptor.__post_init__``
    for an invalid ``name``, ``description``, ``metadata``, or
    ``tags`` field. No other validation exists.
    """


@dataclass(frozen=True)
class ToolDescriptor:
    """The immutable metadata layer that describes a Tool without
    containing or executing it.

    ``ToolDescriptor`` is a pure, passive value object and nothing
    more: it names a Tool, describes what it does, and carries
    optional metadata/tags -- and it does nothing with any of that
    itself. It does not instantiate or execute a Tool, validate a
    ``BaseTool``, or call any registry, resolver, planner, runtime,
    or workflow. It is not wired into ``BaseTool``, ``BaseSkill``,
    ``ToolContext``, ``ToolRegistry``, ``ToolResolver``,
    ``SkillDescriptor``, ``Capability``, ``SkillRegistry``,
    ``SkillResolver``, ``Executor``, ``WorkflowRuntime``,
    ``WorkflowEngine``, ``WorkflowExecutionCoordinator``, ``Planner``,
    ``Memory``, ``LearningLoop``, ``Reflection``, ``EventBus``,
    ``Services``, ``Repository``, ``Providers``, ``Database``,
    ``Agents``, or the Composition Root -- this sprint introduces the
    shape only. There is no execution method, no registration, no
    discovery, no persistence, no serialization, and no eventing
    anywhere in this module; the only methods this class defines at
    all are ``__post_init__`` and ``__hash__``.

    Instances are frozen (immutable) -- once constructed, none of a
    ``ToolDescriptor``'s fields can be reassigned. ``metadata`` is
    additionally locked down (see ``__post_init__``) so that mutating
    the original mapping passed in -- or attempting to mutate
    ``descriptor.metadata`` itself -- has no effect on this instance
    after construction. This mirrors the same "freeze the mapping
    too" pattern ``Orchestration.task.Task``,
    ``Orchestration.execution_context.ExecutionContext``,
    ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_session.WorkflowSession``,
    ``Orchestration.skill_result.SkillResult``,
    ``Orchestration.tool_context.ToolContext``,
    ``Orchestration.skill_context.SkillContext``,
    ``Orchestration.capability.Capability``, and
    ``Orchestration.skill_descriptor.SkillDescriptor`` already use for
    their own metadata/payload fields. ``tags`` is already immutable
    by virtue of being a tuple and is stored exactly as validated,
    with no copying, sorting, or deduplication.

    Attributes:
        name: The Tool's identifying name. Must be a non-empty
            string whose stripped form is also non-empty.
        description: A human-readable description of what this Tool
            does. Must be a non-empty string.
        metadata: Optional contextual information about this Tool.
            Stored internally as an immutable ``MappingProxyType``
            snapshot of whatever mapping was passed in.
        tags: An immutable tuple of non-empty string tags describing
            or categorizing this Tool. Stored exactly as given.
    """

    name: str
    description: str
    metadata: Mapping[str, Any]
    tags: Tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate ``name``, ``description``, ``metadata``, and
        ``tags``, and freeze ``metadata`` into an immutable snapshot.

        ``dataclass(frozen=True)`` already prevents reassigning any
        field (including ``self.metadata``) to a different object,
        but it does nothing to stop the *contents* of a mutable
        mapping from being changed out from under this
        ``ToolDescriptor`` after construction. Wrapping a
        freshly-copied ``dict`` in ``MappingProxyType`` closes that
        gap: the ``metadata`` any caller observes is guaranteed to be
        exactly what it was at construction time, for the lifetime of
        this instance.

        ``object.__setattr__`` is used deliberately here (the one
        sanctioned way to set a field from inside a frozen
        dataclass's own ``__post_init__``) -- this is not a way
        around the class's immutability from the outside.

        Raises:
            ToolDescriptorError: if ``name`` is not a non-empty
                string (after stripping whitespace); if
                ``description`` is not a non-empty string (after
                stripping whitespace); if ``metadata`` is not a
                ``Mapping``; if ``tags`` is not a ``tuple``; if any
                element of ``tags`` is not a string; or if any
                element of ``tags`` is an empty string.
        """
        if not isinstance(self.name, str):
            raise ToolDescriptorError(
                f"ToolDescriptor requires 'name' to be a str; got "
                f"{self.name!r}"
            )
        if len(self.name.strip()) == 0:
            raise ToolDescriptorError(
                "ToolDescriptor requires 'name' to be non-empty (after "
                "stripping whitespace)"
            )

        if not isinstance(self.description, str):
            raise ToolDescriptorError(
                f"ToolDescriptor requires 'description' to be a str; "
                f"got {self.description!r}"
            )
        if len(self.description.strip()) == 0:
            raise ToolDescriptorError(
                "ToolDescriptor requires 'description' to be non-empty "
                "(after stripping whitespace)"
            )

        if not isinstance(self.metadata, Mapping):
            raise ToolDescriptorError(
                f"ToolDescriptor requires 'metadata' to be a Mapping; "
                f"got {self.metadata!r}"
            )

        if not isinstance(self.tags, tuple):
            raise ToolDescriptorError(
                f"ToolDescriptor requires 'tags' to be a tuple; got "
                f"{self.tags!r}"
            )
        for tag in self.tags:
            if not isinstance(tag, str):
                raise ToolDescriptorError(
                    f"ToolDescriptor requires every 'tags' element to "
                    f"be a str; got {tag!r}"
                )
            if len(tag) == 0:
                raise ToolDescriptorError(
                    "ToolDescriptor requires every 'tags' element to "
                    "be non-empty"
                )

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    def __hash__(self) -> int:
        """Hash by ``name`` alone.

        Tool names are the natural identity for hashing (mirroring
        ``Orchestration.capability.Capability`` and
        ``Orchestration.skill_descriptor.SkillDescriptor``, which
        likewise hash by ``name`` alone). ``description``,
        ``metadata``, and ``tags`` are deliberately excluded from the
        hash.

        The dataclass-generated ``__eq__`` (left untouched, comparing
        every field) still governs equality -- two ``ToolDescriptor``
        instances are only ``==`` when *all four* fields match. Two
        ``ToolDescriptor`` instances sharing the same ``name`` may
        differ in ``description``/``metadata``/``tags`` and thus
        share a hash without being equal -- which is exactly what
        Python's hash/eq contract permits (it only requires equal
        objects to share a hash, never the reverse).
        """
        return hash(self.name)