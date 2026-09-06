"""Phase F, Task 8 -- CopilotTool / permission-boundary smoke suite.

Exercises the real ``Orchestration.copilot_tool.CopilotTool`` through
the existing ``Orchestration.permissioned_tool.PermissionedTool`` /
``Orchestration.tool_permission_enforcer.authorize_tool`` boundary
(the exact same enforcement point every other Tool in this codebase
already uses -- see ``Tests/test_activation12_3_permission_wiring.py``
for the pattern this file mirrors), plus deterministic fake tools for
the PAPER_EXECUTION/LIVE_EXECUTION/DESTRUCTIVE_ADMIN denial cases
``CopilotTool`` itself never exercises (it only ever declares
READ_ONLY).

Scenarios:
  A. READ_ONLY (CopilotTool, EXPLAIN_DECISION branch) is allowed with
     no PermissionContext at all (fail-closed default already permits
     READ_ONLY), and the returned data is the DecisionBrief's own
     ``reason`` field verbatim -- never reworded, never invented.
  B. READ_ONLY (CopilotTool, RECALL_PREFERENCE branch) is allowed and
     returns the exact stored PreferenceRecord's value verbatim.
  C. READ_ONLY (CopilotTool, SUMMARIZE_PORTFOLIO branch) returns the
     caller-supplied summary string verbatim, never computed.
  D. READ_ONLY (CopilotTool, ASK_STATUS branch) returns the
     caller-supplied status string verbatim, never computed.
  E. PAPER_EXECUTION is denied without an explicit capability grant,
     via the same enforcement boundary CopilotTool sits behind.
  F. LIVE_EXECUTION is denied without an explicit capability grant.
  G. DESTRUCTIVE_ADMIN is denied without an explicit capability grant.
  H. Denial raises the existing, explicit ``ToolPermissionDenied``
     (an ``AgentError``) -- not a silent no-op, not a generic
     exception -- and the underlying callable is never reached.
  I. CopilotTool itself always declares READ_ONLY -- it can never be
     the source of a PAPER_EXECUTION/LIVE_EXECUTION/DESTRUCTIVE_ADMIN
     capability, regardless of what utterance or context it is given.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Database.models import DecisionBrief
from Orchestration.copilot_tool import CopilotTool
from Orchestration.memory import MemoryStore, PreferenceRecord
from Orchestration.permission_context import PermissionContext
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.tool_context import ToolContext
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_permission_enforcer import ToolPermissionDenied, authorize_tool
from Orchestration.tool_result import ToolResult

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _FakeTool:
    """Deterministic fake tool. Raises if called after a denial should
    have prevented that -- proving the underlying callable was never
    reached."""

    def __init__(self, permission=None):
        if permission is not None:
            self.permission = permission
        self.calls = 0

    @property
    def name(self):
        return "fake"

    @property
    def description(self):
        return "fake deterministic tool"

    def execute(self, context):
        self.calls += 1
        return ToolResult(success=True, output="ok", error=None, metadata={})


def test_a_explain_decision_read_only_allowed_data_verbatim():
    brief = DecisionBrief(
        brief_id=1,
        symbol="AAPL",
        generated_at="2026-01-01T00:00:00Z",
        status="RISK_REJECTED",
        reason="Position size would exceed the account's risk limit.",
    )
    tool = CopilotTool()
    check(tool.permission is ToolPermission.READ_ONLY, "CopilotTool declares READ_ONLY")

    wrapped = PermissionedTool(tool)  # no PermissionContext at all
    context = ToolContext(
        task=None,
        parameters={"utterance": "why did the system reject that trade?", "decision_brief": brief},
    )
    result = wrapped.execute(context)
    check(isinstance(result, ToolResult), "execute() returns a ToolResult")
    check(result.success, "EXPLAIN_DECISION call succeeds")
    check(
        brief.symbol in result.output.text and brief.status in result.output.text,
        "explanation text (summary) reflects the DecisionBrief's own symbol/status verbatim",
    )
    check(result.output.data.brief_id == brief.brief_id, "underlying data references the exact DecisionBrief's brief_id")
    check(result.output.data.reason == brief.reason, "underlying data carries the DecisionBrief's reason verbatim")


def test_b_recall_preference_read_only_allowed_data_verbatim():
    store = MemoryStore()
    pref = PreferenceRecord(key="analysis_style", value="concise")
    store.add(pref)

    tool = CopilotTool()
    wrapped = PermissionedTool(tool, PermissionContext())
    context = ToolContext(
        task=None,
        parameters={
            "utterance": "what is my preference for analysis_style?",
            "memory_store": store,
            "memory_query": "analysis_style",
        },
    )
    result = wrapped.execute(context)
    check(result.success, "RECALL_PREFERENCE call succeeds")
    check(result.output.status == "FOUND", "preference lookup status is FOUND")
    check(
        result.output.data.latest.value == "concise",
        "returned preference value is the exact stored value verbatim",
    )
    check(result.output.data.latest is pref, "returned record is the exact stored PreferenceRecord instance")


def test_c_summarize_portfolio_verbatim_passthrough():
    tool = CopilotTool()
    wrapped = PermissionedTool(tool, PermissionContext())
    summary_text = "Equity $10,432.10, 3 open positions, +2.1% today."
    context = ToolContext(
        task=None,
        parameters={"utterance": "summarize my portfolio", "portfolio_summary": summary_text},
    )
    result = wrapped.execute(context)
    check(result.success, "SUMMARIZE_PORTFOLIO call succeeds")
    check(result.output.text == summary_text, "portfolio summary text is returned verbatim, uncomputed")


def test_d_ask_status_verbatim_passthrough():
    tool = CopilotTool()
    wrapped = PermissionedTool(tool, PermissionContext())
    status_text = "Scheduler running; last scan 09:31 WIB; no errors."
    context = ToolContext(
        task=None,
        parameters={"utterance": "what is the status?", "status_text": status_text},
    )
    result = wrapped.execute(context)
    check(result.success, "ASK_STATUS call succeeds")
    check(result.output.text == status_text, "status text is returned verbatim, uncomputed")


def test_e_paper_execution_denied_without_capability():
    t = _FakeTool(ToolPermission.PAPER_EXECUTION)
    wrapped = PermissionedTool(t, PermissionContext(paper_execution_allowed=False))
    denied = False
    try:
        wrapped.execute(ToolContext(task=None, parameters={}))
    except ToolPermissionDenied as exc:
        denied = True
        check(isinstance(exc, AgentError), "ToolPermissionDenied is an explicit AgentError subclass")
        check(len(str(exc)) > 0, "denial carries an explicit, non-empty message")
    check(denied, "PAPER_EXECUTION is denied without an explicit capability grant")
    check(t.calls == 0, "PAPER_EXECUTION underlying callable never executes when denied")


def test_f_live_execution_denied_without_capability():
    t = _FakeTool(ToolPermission.LIVE_EXECUTION)
    wrapped = PermissionedTool(t, PermissionContext(live_execution_allowed=False))
    denied = False
    try:
        wrapped.execute(ToolContext(task=None, parameters={}))
    except ToolPermissionDenied:
        denied = True
    check(denied, "LIVE_EXECUTION is denied without an explicit capability grant")
    check(t.calls == 0, "LIVE_EXECUTION underlying callable never executes when denied")

    # Also prove LIVE_EXECUTION is denied even with no PermissionContext
    # supplied at all (fail-closed default).
    wrapped_no_ctx = PermissionedTool(t)
    denied_no_ctx = False
    try:
        wrapped_no_ctx.execute(ToolContext(task=None, parameters={}))
    except ToolPermissionDenied:
        denied_no_ctx = True
    check(denied_no_ctx, "LIVE_EXECUTION is denied with no PermissionContext supplied (fail-closed)")
    check(t.calls == 0, "LIVE_EXECUTION underlying callable still never executes")


def test_g_destructive_admin_denied_without_capability():
    t = _FakeTool(ToolPermission.DESTRUCTIVE_ADMIN)
    wrapped = PermissionedTool(t, PermissionContext(destructive_admin_allowed=False))
    denied = False
    try:
        wrapped.execute(ToolContext(task=None, parameters={}))
    except ToolPermissionDenied:
        denied = True
    check(denied, "DESTRUCTIVE_ADMIN is denied without an explicit capability grant")
    check(t.calls == 0, "DESTRUCTIVE_ADMIN underlying callable never executes when denied")


def test_h_copilot_tool_never_declares_elevated_permission():
    tool = CopilotTool()
    check(tool.permission is ToolPermission.READ_ONLY, "CopilotTool.permission is READ_ONLY")
    check(tool.permission is not ToolPermission.PAPER_EXECUTION, "CopilotTool is never PAPER_EXECUTION")
    check(tool.permission is not ToolPermission.LIVE_EXECUTION, "CopilotTool is never LIVE_EXECUTION")
    check(tool.permission is not ToolPermission.DESTRUCTIVE_ADMIN, "CopilotTool is never DESTRUCTIVE_ADMIN")

    # Authorize directly (no context at all) -- must succeed for
    # CopilotTool regardless of PermissionContext, exactly like every
    # other undeclared/READ_ONLY tool already does.
    permission = authorize_tool(tool, None)
    check(permission is ToolPermission.READ_ONLY, "authorize_tool grants CopilotTool READ_ONLY with no context")


def test_i_missing_context_is_explicit_not_fabricated():
    """No decision_brief supplied -> explicit MISSING_CONTEXT, never a
    fabricated explanation."""
    tool = CopilotTool()
    wrapped = PermissionedTool(tool, PermissionContext())
    context = ToolContext(task=None, parameters={"utterance": "why did that happen?"})
    result = wrapped.execute(context)
    check(result.success, "MISSING_CONTEXT is still a successful, well-formed response")
    check(result.output.status == "MISSING_CONTEXT", "status is explicit MISSING_CONTEXT")
    check(
        "No decision brief was supplied" in result.output.text,
        "text explicitly states no data was supplied, rather than inventing an explanation",
    )


def main() -> int:
    for fn_name in [n for n in sorted(globals()) if n.startswith("test_")]:
        print(f"{fn_name}:")
        globals()[fn_name]()
    print()
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("FAILURES:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())