"""Activation 12.3 REVERT + REWIRE update.

This test's original premise -- that ``BaseSkill.execute_tool()``
itself enforces permission -- was the illegal locked-surface wiring
Activation 12.3 removed (see ``Orchestration/base_skill.py`` and the
Activation 12.3 audit). Per the Legacy Test Update Rule, this file is
rewritten (not deleted) to validate the corrected architecture instead:

  1. ``BaseSkill.execute_tool()`` now runs whatever tool its resolver
     returns completely unconditionally -- no permission check, exactly
     its pre-Activation-12.2 behavior.
  2. Permission enforcement instead lives one layer down, in
     ``Orchestration.permissioned_tool.PermissionedTool`` -- when a
     Skill's resolver hands back a ``PermissionedTool`` instead of a
     raw tool, *that* is what blocks LIVE_EXECUTION/DESTRUCTIVE_ADMIN
     (and denies/allows PAPER_EXECUTION per its ``PermissionContext``)
     before the real, wrapped tool's ``execute()`` ever runs.

``BaseSkill`` itself is proven never to know or care which kind of
tool object it was handed.
"""

from __future__ import annotations

from Orchestration.base_skill import BaseSkill
from Orchestration.permission_context import PermissionContext
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.skill_result import SkillResult
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_permission_enforcer import ToolPermissionDenied
from Orchestration.tool_result import ToolResult


class _FakeTool:
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
        return ToolResult(success=True, output="ok", error=None, metadata={})


class _FakeSkill(BaseSkill):
    @property
    def name(self):
        return "fake-skill"

    @property
    def description(self):
        return "fake skill"

    def execute(self, context):
        return SkillResult(success=True, output="ok", error=None, metadata={})


def _skill_with(tool):
    skill = _FakeSkill()
    skill._resolve_tool = lambda name: tool
    return skill


def main():
    checks = 0

    # (1) BaseSkill.execute_tool() is unconditional: a raw, undeclared
    # tool runs with no permission check at all -- proving BaseSkill
    # itself performs no enforcement.
    t = _FakeTool()
    assert _skill_with(t).execute_tool("fake", {}).success
    assert t.calls == 1
    checks += 2

    # (2) A raw LIVE_EXECUTION tool, handed directly to BaseSkill (not
    # wrapped in PermissionedTool), also runs unconditionally -- this
    # is the proof that permission enforcement is no longer BaseSkill's
    # job.
    t = _FakeTool(ToolPermission.LIVE_EXECUTION)
    assert _skill_with(t).execute_tool("fake", {}).success
    assert t.calls == 1
    checks += 2

    # (3) Wrapping the same LIVE_EXECUTION tool in PermissionedTool and
    # handing *that* to BaseSkill now blocks it before the underlying
    # tool's execute() runs -- proving enforcement moved to the
    # composition-boundary wrapper, not BaseSkill.
    t = _FakeTool(ToolPermission.LIVE_EXECUTION)
    wrapped = PermissionedTool(t, PermissionContext())
    try:
        _skill_with(wrapped).execute_tool("fake", {})
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("live execution was not blocked by PermissionedTool")
    assert t.calls == 0
    checks += 2

    # (4) Same for DESTRUCTIVE_ADMIN.
    t = _FakeTool(ToolPermission.DESTRUCTIVE_ADMIN)
    wrapped = PermissionedTool(t, PermissionContext())
    try:
        _skill_with(wrapped).execute_tool("fake", {})
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError(
            "destructive/admin execution was not blocked by PermissionedTool"
        )
    assert t.calls == 0
    checks += 2

    # (5) A wrapped PAPER_EXECUTION tool is denied without an
    # authorizing PermissionContext...
    t = _FakeTool(ToolPermission.PAPER_EXECUTION)
    wrapped = PermissionedTool(t, PermissionContext(paper_execution_allowed=False))
    try:
        _skill_with(wrapped).execute_tool("fake", {})
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("paper execution was not denied without authorization")
    assert t.calls == 0
    checks += 2

    # (6) ...and succeeds once explicitly authorized.
    t = _FakeTool(ToolPermission.PAPER_EXECUTION)
    wrapped = PermissionedTool(t, PermissionContext(paper_execution_allowed=True))
    assert _skill_with(wrapped).execute_tool("fake", {}).success
    assert t.calls == 1
    checks += 2

    print(f"{checks}/{checks} PASS")


if __name__ == "__main__":
    main()