"""PermissionedTool -- Activation 12.3's composition-boundary permission
wrapper.

Wraps an existing, opaque tool object without changing its externally
visible shape (``name``, ``description``, ``execute(context)``), so no
existing call site -- ``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_resolver.ToolResolver``, or
``Orchestration.base_skill.BaseSkill.execute_tool()`` -- needs to know
or care whether it is holding a raw tool or a permission-aware one.

This module exists because ``ToolRegistry.register(name, tool)``
intentionally accepts any opaque Python object and
``ToolResolver.resolve(name)`` returns that exact object unexamined
(see both modules' own docstrings) -- Activation 12.3's Phase 1B audit
confirmed this is the correct, narrowest injection seam. Wrapping
happens once, at tool-registration time in
``Core.composition_root._build_market_tool_resolver()``; nothing about
``ToolRegistry``, ``ToolResolver``, ``BaseSkill``, ``Executor``,
``ToolDescriptor``, or ``ToolInvocation`` is modified to make this
work.

Canonical permission source (LOCKED for this Activation): this wrapper
calls ``Orchestration.tool_permission_enforcer.authorize_tool`` --
and only that function -- to make its permission decision. It does not
duplicate permission logic, and it never imports
``Orchestration.tool_permission_gate`` (removed by this same
Activation step).
"""

from __future__ import annotations

from typing import Any, Optional

from Orchestration.permission_context import PermissionContext
from Orchestration.tool_permission_enforcer import authorize_tool


class PermissionedTool:
    """A thin, transparent wrapper that authorizes a tool's declared
    permission before delegating to its ``execute(context)``.

    Holds exactly two collaborators -- the wrapped tool and an optional
    ``PermissionContext`` -- and nothing else. Never inspects, copies,
    or mutates either. ``name`` and ``description`` are forwarded
    straight through to the wrapped tool by identity, unexamined.
    """

    def __init__(
        self,
        wrapped_tool: Any,
        permission_context: Optional[PermissionContext] = None,
    ) -> None:
        """Wrap ``wrapped_tool`` via dependency injection only.

        Args:
            wrapped_tool: The already-constructed tool object to wrap.
                Never constructed here, never copied. Stored by
                identity. Must expose ``name``, ``description``, and
                ``execute(context)`` -- the same shape every existing
                tool call site already expects.
            permission_context: Optional ``PermissionContext`` this
                wrapper hands to ``authorize_tool`` on every
                ``execute()`` call. Defaults to ``None``, which
                preserves ``authorize_tool``'s Activation 12.2
                behavior (READ_ONLY/PAPER_EXECUTION permitted,
                LIVE_EXECUTION/DESTRUCTIVE_ADMIN denied).
        """
        self._wrapped_tool = wrapped_tool
        self._permission_context = permission_context

    @property
    def name(self) -> str:
        """The wrapped tool's ``name``, forwarded unexamined."""
        return self._wrapped_tool.name

    @property
    def description(self) -> str:
        """The wrapped tool's ``description``, forwarded unexamined."""
        return self._wrapped_tool.description

    @property
    def wrapped_tool(self) -> Any:
        """The exact tool object this wrapper was constructed with."""
        return self._wrapped_tool

    @property
    def permission_context(self) -> Optional[PermissionContext]:
        """The ``PermissionContext`` this wrapper authorizes against,
        if any."""
        return self._permission_context

    def execute(self, context: Any) -> Any:
        """Authorize the wrapped tool's declared permission, then
        delegate to its ``execute(context)`` exactly once.

        Args:
            context: Passed straight through, unexamined, to
                ``self.wrapped_tool.execute(context)``.

        Returns:
            Whatever ``self.wrapped_tool.execute(context)`` returns,
            propagated unchanged.

        Raises:
            Orchestration.tool_permission_enforcer.ToolPermissionDenied:
                If ``authorize_tool`` denies the wrapped tool's
                declared permission under ``self.permission_context``.
                The wrapped tool's ``execute`` is never reached in
                this case -- authorization happens strictly before
                delegation.
        """
        authorize_tool(self._wrapped_tool, self._permission_context)
        return self._wrapped_tool.execute(context)