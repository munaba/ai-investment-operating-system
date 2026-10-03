"""Activation 12.4b -- update for the two-argument authorize_tool(tool,
permission_context=None) contract.

Covers all twelve required cases: READ_ONLY with/without context, and
PAPER_EXECUTION/LIVE_EXECUTION/DESTRUCTIVE_ADMIN each denied with no
context, denied with an explicit False, and allowed with an explicit
True -- plus proof that PermissionedTool.execute() no longer raises the
TypeError.
"""

from __future__ import annotations

from Orchestration.permission_context import PermissionContext
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_permission_enforcer import (
    PermissionedToolInvoker,
    ToolPermissionDenied,
    authorize_tool,
    permission_for_tool,
)


class _Tool:
    def __init__(self, permission=None):
        if permission is not None:
            self.permission = permission
        self.calls = 0

    @property
    def name(self):
        return "fake"

    @property
    def description(self):
        return "fake"

    def execute(self, context):
        self.calls += 1
        return context


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main():
    checks = 0
    invoker = PermissionedToolInvoker()

    # 1. READ_ONLY + no context -> PASS
    t = _Tool()
    assert permission_for_tool(t) is ToolPermission.READ_ONLY
    assert authorize_tool(t) is ToolPermission.READ_ONLY
    assert invoker.execute(t, "ok") == "ok"
    assert t.calls == 1
    checks += 4

    # 2. READ_ONLY + context -> PASS
    t = _Tool()
    assert authorize_tool(t, PermissionContext()) is ToolPermission.READ_ONLY
    assert invoker.execute(t, "ok", PermissionContext()) == "ok"
    checks += 2

    # 3. PAPER_EXECUTION + no context -> DENY
    t = _Tool(ToolPermission.PAPER_EXECUTION)
    try:
        authorize_tool(t)
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("PAPER_EXECUTION with no context was not denied")
    checks += 1

    # 4. PAPER_EXECUTION + paper_execution_allowed=False -> DENY
    t = _Tool(ToolPermission.PAPER_EXECUTION)
    try:
        authorize_tool(t, PermissionContext(paper_execution_allowed=False))
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("PAPER_EXECUTION=False was not denied")
    checks += 1

    # 5. PAPER_EXECUTION + paper_execution_allowed=True -> PASS
    t = _Tool(ToolPermission.PAPER_EXECUTION)
    ctx = PermissionContext(paper_execution_allowed=True)
    assert authorize_tool(t, ctx) is ToolPermission.PAPER_EXECUTION
    assert invoker.execute(t, "paper", ctx) == "paper"
    assert t.calls == 1
    checks += 3

    # 6. LIVE_EXECUTION + no context -> DENY
    t = _Tool(ToolPermission.LIVE_EXECUTION)
    try:
        authorize_tool(t)
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("LIVE_EXECUTION with no context was not denied")
    checks += 1

    # 7. LIVE_EXECUTION + live_execution_allowed=False -> DENY
    t = _Tool(ToolPermission.LIVE_EXECUTION)
    try:
        authorize_tool(t, PermissionContext(live_execution_allowed=False))
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("LIVE_EXECUTION=False was not denied")
    checks += 1

    # 8. LIVE_EXECUTION + live_execution_allowed=True -> PASS
    t = _Tool(ToolPermission.LIVE_EXECUTION)
    ctx = PermissionContext(live_execution_allowed=True)
    assert authorize_tool(t, ctx) is ToolPermission.LIVE_EXECUTION
    assert invoker.execute(t, "live", ctx) == "live"
    assert t.calls == 1
    checks += 3

    # 9. DESTRUCTIVE_ADMIN + no context -> DENY
    t = _Tool(ToolPermission.DESTRUCTIVE_ADMIN)
    try:
        authorize_tool(t)
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("DESTRUCTIVE_ADMIN with no context was not denied")
    checks += 1

    # 10. DESTRUCTIVE_ADMIN + destructive_admin_allowed=False -> DENY
    t = _Tool(ToolPermission.DESTRUCTIVE_ADMIN)
    try:
        authorize_tool(t, PermissionContext(destructive_admin_allowed=False))
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("DESTRUCTIVE_ADMIN=False was not denied")
    checks += 1

    # 11. DESTRUCTIVE_ADMIN + destructive_admin_allowed=True -> PASS
    t = _Tool(ToolPermission.DESTRUCTIVE_ADMIN)
    ctx = PermissionContext(destructive_admin_allowed=True)
    assert authorize_tool(t, ctx) is ToolPermission.DESTRUCTIVE_ADMIN
    assert invoker.execute(t, "admin", ctx) == "admin"
    assert t.calls == 1
    checks += 3

    # invalid permission value still raises
    try:
        authorize_tool(_Tool("invalid"))
    except Exception:
        checks += 1
    else:
        raise AssertionError("invalid permission was accepted")

    # 12. PermissionedTool.execute() no longer throws the TypeError.
    t = _Tool()
    wrapped = PermissionedTool(t, None)
    assert wrapped.execute("via-wrapper") == "via-wrapper"
    assert t.calls == 1
    checks += 2

    t2 = _Tool(ToolPermission.PAPER_EXECUTION)
    wrapped2 = PermissionedTool(t2, PermissionContext(paper_execution_allowed=True))
    assert wrapped2.execute("paper-via-wrapper") == "paper-via-wrapper"
    assert t2.calls == 1
    checks += 2

    print(f"{checks}/{checks} PASS")


if __name__ == "__main__":
    main()