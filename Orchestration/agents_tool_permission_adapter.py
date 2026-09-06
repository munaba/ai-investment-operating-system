"""AgentsToolPermissionAdapter -- Activation 12.5's composition-boundary
permission wrapper for the legacy ``Agents.tool_registry`` path.

Phase 1 source audit (Activation 12.5) confirmed
``Orchestration.permissioned_tool.PermissionedTool`` (Activation 12.3)
cannot transparently wrap a legacy ``Agents.tool_registry.Tool``:
``PermissionedTool`` forwards to a wrapped object's ``execute(context)``
method, while ``Agents.tool_registry.Tool.handler`` is a bare
``Callable[..., Any]`` invoked as ``handler(*args, **kwargs)`` by
``Agents.sandbox.GenericSandbox.execute()`` (see that module, LOCKED).
The two call shapes are incompatible, so the smallest adapter possible
is this module: a permission-aware *callable* -- not a tool-shaped
object -- that can be plugged in directly as ``Agents.tool_registry.
Tool.handler`` without changing ``Agents.tool_registry.Tool``,
``Agents.tool_registry.ToolRegistry``, ``Agents.executor.Executor``, or
``Agents.sandbox.GenericSandbox`` in any way.

Canonical permission source (LOCKED for this Activation, same as
``PermissionedTool``): this adapter calls
``Orchestration.tool_permission_enforcer.authorize_tool`` -- and only
that function -- to make its permission decision. It does not duplicate
permission logic, does not introduce a second permission model, and
never imports ``Orchestration.tool_permission_gate`` (removed by
Activation 12.3).

Wired once, at tool-registration time, in
``Core.composition_root._build_service_skills()`` -- the only call
site. Nothing about ``Agents.tool_registry``, ``Agents.executor``,
``Agents.sandbox``, ``Orchestration.tool_registry``,
``Orchestration.tool_resolver``, or ``Orchestration.base_skill`` is
modified to make this work.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from Orchestration.permission_context import PermissionContext
from Orchestration.tool_permission_enforcer import authorize_tool


class AgentsToolPermissionAdapter:
    """A thin, transparent, callable wrapper that authorizes a declared
    tool permission before delegating to a legacy Agents Tool handler.

    Holds exactly three collaborators -- the object whose declared
    ``.permission`` is checked, the underlying handler callable to
    delegate to, and an optional ``PermissionContext`` -- and nothing
    else. Never inspects, copies, or mutates any of them. Instances of
    this class are used directly as an ``Agents.tool_registry.Tool.
    handler`` value: ``Agents.sandbox.GenericSandbox.execute()`` calls
    ``tool.handler(*args, **kwargs)``, which resolves to
    :meth:`__call__` below, unchanged from that call site's point of
    view -- it remains a bare ``Callable[..., Any]``.
    """

    def __init__(
        self,
        wrapped_tool: Any,
        handler: Callable[..., Any],
        permission_context: Optional[PermissionContext] = None,
    ) -> None:
        """Wrap ``handler`` via dependency injection only.

        Args:
            wrapped_tool: The object whose declared permission is
                checked on every call, via
                ``Orchestration.tool_permission_enforcer.
                authorize_tool``. Never constructed here, never copied,
                stored by identity. Needs no particular shape beyond
                what ``authorize_tool``/``permission_for_tool`` already
                read (an optional ``.permission`` attribute; absent
                defaults to ``ToolPermission.READ_ONLY``, unchanged
                Activation 12 semantics).
            handler: The already-constructed callable to delegate to
                once authorization succeeds. Never constructed here,
                never copied, stored by identity. Called as
                ``handler(*args, **kwargs)`` -- the exact same
                invocation shape ``Agents.sandbox.GenericSandbox.
                execute()`` already uses for every ``Tool.handler``.
            permission_context: Optional ``PermissionContext`` this
                wrapper hands to ``authorize_tool`` on every call.
                Defaults to ``None``, which preserves ``authorize_tool``'s
                fail-closed Activation 12.4b behavior (READ_ONLY always
                permitted; PAPER_EXECUTION/LIVE_EXECUTION/
                DESTRUCTIVE_ADMIN denied without an explicit grant).
        """
        self._wrapped_tool = wrapped_tool
        self._handler = handler
        self._permission_context = permission_context

    @property
    def wrapped_tool(self) -> Any:
        """The object this wrapper authorizes against, forwarded by
        identity."""
        return self._wrapped_tool

    @property
    def handler(self) -> Callable[..., Any]:
        """The underlying handler this wrapper delegates to once
        authorized, forwarded by identity."""
        return self._handler

    @property
    def permission_context(self) -> Optional[PermissionContext]:
        """The ``PermissionContext`` this wrapper authorizes against, if
        any."""
        return self._permission_context

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Authorize ``self.wrapped_tool``'s declared permission, then
        delegate to ``self.handler(*args, **kwargs)`` exactly once.

        Args:
            *args: Forwarded, unexamined, to ``self.handler``.
            **kwargs: Forwarded, unexamined, to ``self.handler``.

        Returns:
            Whatever ``self.handler(*args, **kwargs)`` returns,
            propagated unchanged.

        Raises:
            Orchestration.tool_permission_enforcer.ToolPermissionDenied:
                If ``authorize_tool`` denies ``self.wrapped_tool``'s
                declared permission under ``self.permission_context``.
                ``self.handler`` is never reached in this case --
                authorization happens strictly before delegation.
        """
        authorize_tool(self._wrapped_tool, self._permission_context)
        return self._handler(*args, **kwargs)