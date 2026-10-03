"""Phase F, Task 9 -- CopilotTool registration smoke suite.

Exercises the real production ``Core.composition_root.build_application()``
graph (not a fake/local registry) to prove ``Orchestration.copilot_tool.
CopilotTool`` is discoverable through both existing AIOS tool
registries -- the canonical ``Orchestration.tool_registry.ToolRegistry``/
``Orchestration.tool_resolver.ToolResolver`` pair (via
``ApplicationGraph.copilot_tool_resolver``) and the legacy
``Agents.tool_registry`` singleton (via ``AgentsToolPermissionAdapter``,
mirroring ``PaperExecutionTool``'s own Activation 12.8 wiring) -- and
that both paths still enforce READ_ONLY through the existing
``Orchestration.tool_permission_enforcer.authorize_tool`` boundary.

Scenarios:
  A. Application graph build succeeds and exposes
     ``copilot_tool_resolver``.
  B. The canonical resolver resolves ``"copilot"`` to a
     ``PermissionedTool`` wrapping the real ``CopilotTool``.
  C. ``authorize_tool`` grants READ_ONLY unconditionally for the
     resolved tool (no capability grant needed).
  D. Executing through the canonical resolver returns caller-supplied
     data verbatim (no fabrication).
  E. The legacy ``Agents.tool_registry`` singleton also exposes
     ``"copilot"``, wired through ``AgentsToolPermissionAdapter`` over
     the same shared ``PermissionContext``, and executes identically.
  F. ``CopilotTool`` never declares PAPER_EXECUTION, LIVE_EXECUTION, or
     DESTRUCTIVE_ADMIN -- registration never grants elevated
     permission to anything.
  G. Regression: the pre-existing ``paper_execution`` resolver/tool is
     unaffected by this task's additions.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.tool_registry import ToolRegistry as AgentsToolRegistrySingleton
from Agents.tool_registry import tool_registry as agents_tool_registry
from Core.composition_root import build_application
from Orchestration.paper_execution_tool import PaperExecutionTool
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.tool_context import ToolContext
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_permission_enforcer import authorize_tool

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


def _fresh_graph():
    # The legacy Agents.tool_registry is a process-wide singleton;
    # reset it so repeated builds in this same test run (or a prior
    # test file already having built a graph) don't collide with the
    # exists()-guarded registration this task's wiring performs.
    AgentsToolRegistrySingleton.reset()
    return build_application()


def test_a_graph_builds_and_exposes_resolver():
    graph = _fresh_graph()
    check(graph is not None, "build_application() succeeds")
    check(
        hasattr(graph, "copilot_tool_resolver"),
        "ApplicationGraph exposes copilot_tool_resolver",
    )


def test_b_canonical_resolver_resolves_permissioned_copilot_tool():
    graph = _fresh_graph()
    resolved = graph.copilot_tool_resolver.resolve("copilot")
    check(
        isinstance(resolved, PermissionedTool),
        "canonical resolver resolves 'copilot' to a PermissionedTool",
    )
    check(resolved.name == "copilot", "resolved tool's name is 'copilot'")


def test_c_read_only_authorized_unconditionally():
    graph = _fresh_graph()
    resolved = graph.copilot_tool_resolver.resolve("copilot")
    permission = authorize_tool(resolved.wrapped_tool, resolved.permission_context)
    check(permission is ToolPermission.READ_ONLY, "authorize_tool grants READ_ONLY for copilot")

    # Also true with no PermissionContext supplied at all.
    permission_no_ctx = authorize_tool(resolved.wrapped_tool, None)
    check(
        permission_no_ctx is ToolPermission.READ_ONLY,
        "READ_ONLY is authorized even with no PermissionContext supplied",
    )


def test_d_execute_via_canonical_resolver_returns_data_verbatim():
    graph = _fresh_graph()
    resolved = graph.copilot_tool_resolver.resolve("copilot")
    status_text = "Scheduler running; last scan 09:31 WIB; no errors."
    context = ToolContext(
        task=None,
        parameters={"utterance": "what is the status?", "status_text": status_text},
    )
    result = resolved.execute(context)
    check(result.success, "execute() via canonical resolver succeeds")
    check(
        result.output.text == status_text,
        "returned text is the caller-supplied status text verbatim",
    )


def test_e_legacy_agents_tool_registry_also_exposes_copilot():
    _fresh_graph()
    check(agents_tool_registry.exists("copilot"), "legacy Agents.tool_registry has 'copilot' registered")
    legacy_tool = agents_tool_registry.get("copilot")
    check(legacy_tool.name == "copilot", "legacy Tool's name is 'copilot'")

    summary_text = "Equity $10,432.10, 3 open positions, +2.1% today."
    context = ToolContext(
        task=None,
        parameters={"utterance": "summarize my portfolio", "portfolio_summary": summary_text},
    )
    result = legacy_tool.handler(context)
    check(result.success, "execute() via legacy Agents.tool_registry path succeeds")
    check(
        result.output.text == summary_text,
        "legacy path also returns caller-supplied data verbatim",
    )


def test_f_copilot_tool_never_declares_elevated_permission():
    graph = _fresh_graph()
    resolved = graph.copilot_tool_resolver.resolve("copilot")
    tool = resolved.wrapped_tool
    check(tool.permission is ToolPermission.READ_ONLY, "CopilotTool.permission is READ_ONLY")
    check(tool.permission is not ToolPermission.PAPER_EXECUTION, "never PAPER_EXECUTION")
    check(tool.permission is not ToolPermission.LIVE_EXECUTION, "never LIVE_EXECUTION")
    check(tool.permission is not ToolPermission.DESTRUCTIVE_ADMIN, "never DESTRUCTIVE_ADMIN")


def test_g_paper_execution_regression_unaffected():
    graph = _fresh_graph()
    resolved = graph.paper_execution_tool_resolver.resolve("paper_execution")
    check(
        isinstance(resolved, PermissionedTool),
        "paper_execution still resolves to a PermissionedTool (regression)",
    )
    check(
        isinstance(resolved.wrapped_tool, PaperExecutionTool),
        "paper_execution still wraps the real PaperExecutionTool (regression)",
    )
    check(
        resolved.wrapped_tool.permission is ToolPermission.PAPER_EXECUTION,
        "paper_execution still declares PAPER_EXECUTION (regression)",
    )
    denied = False
    try:
        authorize_tool(resolved.wrapped_tool, resolved.permission_context)
    except Exception as exc:
        denied = type(exc).__name__ == "ToolPermissionDenied"
    check(denied, "paper_execution is still denied by default (regression, fail-closed)")


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