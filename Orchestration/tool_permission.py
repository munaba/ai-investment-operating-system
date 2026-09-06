"""Permission vocabulary for Activation 12 tool capabilities.

This module defines only the four permission classes required by the
Activation 12 roadmap.  It does not execute tools, grant live access,
perform authentication, or bypass any existing financial/risk state
machine.  A later integration step may enforce these declarations at the
ToolResolver/Executor boundary.
"""

from __future__ import annotations

from enum import Enum

from Core.exceptions import AgentError


class ToolPermissionError(AgentError):
    """Raised when an invalid tool permission value is requested."""


class ToolPermission(str, Enum):
    """The four permission classes required by Activation 12."""

    READ_ONLY = "read-only"
    PAPER_EXECUTION = "paper execution"
    LIVE_EXECUTION = "live execution"
    DESTRUCTIVE_ADMIN = "destructive/admin"

    @classmethod
    def from_value(cls, value: str) -> "ToolPermission":
        """Normalize a permission string to the canonical enum member."""
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ToolPermissionError(
                f"ToolPermission requires a str value; got {value!r}"
            )
        normalized = value.strip().lower()
        for permission in cls:
            if normalized == permission.value:
                return permission
        raise ToolPermissionError(
            f"Unknown tool permission: {value!r}"
        )
