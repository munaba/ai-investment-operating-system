"""Standalone Activation 12 permission enforcement boundary.

Kept separate from locked ToolDescriptor/BaseTool/BaseSkill/Executor surfaces.
The boundary evaluates a declared tool permission before execution; existing
legacy tools without a declaration are treated as READ_ONLY for compatibility.

Activation 12.4b: ``authorize_tool`` now also accepts an optional
``Orchestration.permission_context.PermissionContext`` so that
``Orchestration.permissioned_tool.PermissionedTool.execute`` -- which calls
``authorize_tool(self._wrapped_tool, self._permission_context)`` -- can
delegate to this enforcer without a ``TypeError``. The permission context is
fail-closed: PAPER_EXECUTION, LIVE_EXECUTION, and DESTRUCTIVE_ADMIN are all
denied unless a context is supplied AND that context explicitly grants the
matching capability. READ_ONLY remains always allowed, with or without a
context, preserving Activation 12.2 behavior.
"""

from __future__ import annotations

from typing import Any, Optional

from Core.exceptions import AgentError
from Orchestration.permission_context import PermissionContext
from Orchestration.tool_permission import ToolPermission


class ToolPermissionDenied(AgentError):
    """Raised when a tool permission is not allowed by the current boundary."""


def permission_for_tool(tool: Any) -> ToolPermission:
    raw = getattr(tool, "permission", ToolPermission.READ_ONLY)
    return ToolPermission.from_value(raw)


def authorize_tool(
    tool: Any,
    permission_context: Optional[PermissionContext] = None,
) -> ToolPermission:
    """Authorize ``tool``'s declared permission under ``permission_context``.

    Args:
        tool: The tool whose declared permission is being checked. See
            ``permission_for_tool``.
        permission_context: Optional ``PermissionContext`` granting
            PAPER_EXECUTION / LIVE_EXECUTION / DESTRUCTIVE_ADMIN
            capabilities for the current application graph. Defaults to
            ``None``, which fail-closed denies every capability except
            READ_ONLY.

    Returns:
        The tool's declared ``ToolPermission`` if authorized.

    Raises:
        ToolPermissionDenied: If the declared permission is not
            authorized under ``permission_context``.
    """
    permission = permission_for_tool(tool)

    if permission is ToolPermission.READ_ONLY:
        return permission

    if permission is ToolPermission.PAPER_EXECUTION:
        granted = bool(
            permission_context is not None
            and permission_context.paper_execution_allowed
        )
    elif permission is ToolPermission.LIVE_EXECUTION:
        granted = bool(
            permission_context is not None
            and permission_context.live_execution_allowed
        )
    elif permission is ToolPermission.DESTRUCTIVE_ADMIN:
        granted = bool(
            permission_context is not None
            and permission_context.destructive_admin_allowed
        )
    else:
        granted = False

    if not granted:
        raise ToolPermissionDenied(
            f"Tool execution denied: {permission.value}"
        )
    return permission


class PermissionedToolInvoker:
    """Small adapter that enforces permission before delegating to ``execute``."""

    def execute(
        self,
        tool: Any,
        context: Any,
        permission_context: Optional[PermissionContext] = None,
    ) -> Any:
        authorize_tool(tool, permission_context)
        return tool.execute(context)