"""PermissionContext -- the smallest additive capability grant object
required by Activation 12.3.

This module answers exactly one question for
``Orchestration.tool_permission_enforcer.authorize_tool``: "is
PAPER_EXECUTION / LIVE_EXECUTION / DESTRUCTIVE_ADMIN currently
authorized for this application graph?" It is a capability context, not
an IAM system: no users, roles, authentication, API keys, broker
credentials, or persistent permission state live here.

Scope note (LOCKED for this Activation): exactly one frozen dataclass
with exactly three boolean fields, all defaulting to ``False``
(fail-closed). No methods beyond the dataclass-generated ones, no
factory, no persistence, no environment-variable reading, no global/
singleton instance. The Composition Root constructs exactly one
instance per application graph and injects it, by reference, into every
``Orchestration.permissioned_tool.PermissionedTool`` wrapper that needs
it -- this module itself does not wire into anything.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionContext:
    """An immutable capability grant for the current application graph.

    Attributes:
        paper_execution_allowed: Whether PAPER_EXECUTION-permission
            tools are authorized to run. Defaults to ``False``
            (fail-closed) -- must be explicitly set ``True`` by the
            Composition Root for a paper-capable graph/test path.
        live_execution_allowed: Whether LIVE_EXECUTION-permission tools
            are authorized to run. Defaults to ``False``. No Activation
            up to and including 12.3 authorizes live execution.
        destructive_admin_allowed: Whether DESTRUCTIVE_ADMIN-permission
            tools are authorized to run. Defaults to ``False``. No
            Activation up to and including 12.3 authorizes destructive/
            admin operations.
    """

    paper_execution_allowed: bool = False
    live_execution_allowed: bool = False
    destructive_admin_allowed: bool = False