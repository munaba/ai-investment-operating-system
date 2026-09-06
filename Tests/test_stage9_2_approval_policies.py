"""
Stage 9.2 proof suite -- Policy-based ApprovalPort implementations.

Scope (per this session's LOCKED design decision):
  - Core.runtime, Agents.executor, Agents.base_agent, Agents.planner,
    Core.composition_root, Core.event, Core.event_store, Agents.sandbox
    -- all untouched.
  - Core/approval.py gained four new, additive ApprovalPort
    implementations (DenyAllApprovalPort, ToolWhitelistApprovalPort,
    ToolBlacklistApprovalPort, PredicateApprovalPort), alongside the
    existing AlwaysApproveApprovalPort (unchanged).
  - Goal: prove the DI seam opened in Stage 9.1
    (Executor(tool_registry, approval_port=...)) genuinely accepts and
    uses these policies -- not a new mechanism, just new occupants of an
    already-open seam.

Cakupan skenario:
  1. AlwaysApproveApprovalPort -- sanity regression, tool succeeds.
  2. DenyAllApprovalPort -- every tool call -> ApprovalDenied.
  3. ToolWhitelistApprovalPort -- allowed tool -> EFFECT_COMPLETED
     (plain return value); tool not on the list -> ApprovalDenied.
  4. ToolBlacklistApprovalPort -- blocked tool -> ApprovalDenied; tool
     not on the list -> EFFECT_COMPLETED.
  5. PredicateApprovalPort -- predicate is actually invoked with the
     real INTENT Event (spy), and its bool return value drives the
     outcome both ways (True -> approved, False -> denied).
  6. All five ApprovalPort implementations satisfy the Protocol
     contract: `version: str` attribute + `check(event) -> ApprovalOutcome`.
  7. Actor remains alive/usable after a DENIED outcome, for a
     policy-driven denial (not just the hand-rolled test double Stage
     8.5 used) -- regression proof that this Runtime invariant is
     general, not specific to one ApprovalPort implementation.
  8. Core.composition_root.build_application() still wires
     AlwaysApproveApprovalPort by construction -- Stage 9.2 did not
     change production wiring.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.approval import (
    AlwaysApproveApprovalPort,
    DenyAllApprovalPort,
    PredicateApprovalPort,
    ToolBlacklistApprovalPort,
    ToolWhitelistApprovalPort,
)
from Core.event import Event
from Core.exceptions import ApprovalDenied
from Core.runtime import ApprovalOutcome
from Agents.executor import Executor
from Agents.tool_registry import Tool, ToolRegistry


_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _fresh_registry_with_echo_tool(tool_name: str = "echo") -> ToolRegistry:
    """A fresh, isolated ToolRegistry with one trivial tool registered.

    Same reasoning as Tests/test_stage9_1_executor.py -- ToolRegistry is
    a process-wide singleton, each scenario here needs a clean slate.
    """
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name=tool_name, description="echoes its input", handler=lambda x: x))
    return registry


# ---------------------------------------------------------------------------
# 1. AlwaysApproveApprovalPort -- sanity regression.
# ---------------------------------------------------------------------------
def scenario_always_approve_sanity() -> None:
    registry = _fresh_registry_with_echo_tool()
    executor = Executor(registry, approval_port=AlwaysApproveApprovalPort())

    result = executor.execute("echo", "hello")
    check(result == "hello", "AlwaysApproveApprovalPort: tool call succeeds through the real pipeline")


# ---------------------------------------------------------------------------
# 2. DenyAllApprovalPort -- every call denied.
# ---------------------------------------------------------------------------
def scenario_deny_all() -> None:
    registry = _fresh_registry_with_echo_tool()
    executor = Executor(registry, approval_port=DenyAllApprovalPort())

    raised = None
    try:
        executor.execute("echo", "hello")
    except ApprovalDenied as exc:
        raised = exc

    check(isinstance(raised, ApprovalDenied), "DenyAllApprovalPort: tool call raises ApprovalDenied")


# ---------------------------------------------------------------------------
# 3. ToolWhitelistApprovalPort -- allow vs deny by name.
# ---------------------------------------------------------------------------
def scenario_tool_whitelist() -> None:
    registry = _fresh_registry_with_echo_tool("echo")
    registry.register(Tool(name="shout", description="uppercases its input", handler=lambda x: x.upper()))

    executor = Executor(registry, approval_port=ToolWhitelistApprovalPort(allowed_tools=["echo"]))

    result = executor.execute("echo", "hello")
    check(result == "hello", "ToolWhitelistApprovalPort: whitelisted tool succeeds (EFFECT_COMPLETED)")

    raised = None
    try:
        executor.execute("shout", "hello")
    except ApprovalDenied as exc:
        raised = exc
    check(isinstance(raised, ApprovalDenied), "ToolWhitelistApprovalPort: non-whitelisted tool raises ApprovalDenied")


# ---------------------------------------------------------------------------
# 4. ToolBlacklistApprovalPort -- deny vs allow by name.
# ---------------------------------------------------------------------------
def scenario_tool_blacklist() -> None:
    registry = _fresh_registry_with_echo_tool("echo")
    registry.register(Tool(name="shout", description="uppercases its input", handler=lambda x: x.upper()))

    executor = Executor(registry, approval_port=ToolBlacklistApprovalPort(blocked_tools=["shout"]))

    raised = None
    try:
        executor.execute("shout", "hello")
    except ApprovalDenied as exc:
        raised = exc
    check(isinstance(raised, ApprovalDenied), "ToolBlacklistApprovalPort: blacklisted tool raises ApprovalDenied")

    result = executor.execute("echo", "hello")
    check(result == "hello", "ToolBlacklistApprovalPort: non-blacklisted tool succeeds (EFFECT_COMPLETED)")


# ---------------------------------------------------------------------------
# 5. PredicateApprovalPort -- spy proves the predicate is actually
#    invoked with the real INTENT Event, and its return value drives
#    the outcome both ways.
# ---------------------------------------------------------------------------
def scenario_predicate_approval() -> None:
    registry = _fresh_registry_with_echo_tool()

    calls: List[Event] = []

    def predicate(event: Event) -> bool:
        calls.append(event)
        envelope = json.loads(event.payload.decode("utf-8"))
        return envelope["tool_name"] == "echo" and envelope["args"] == ["approve-me"]

    executor = Executor(registry, approval_port=PredicateApprovalPort(predicate=predicate))

    result = executor.execute("echo", "approve-me")
    check(result == "approve-me", "PredicateApprovalPort: predicate True -> APPROVED -> tool succeeds")
    check(len(calls) == 1, "PredicateApprovalPort: predicate was actually invoked once")
    check(
        isinstance(calls[0], Event) and calls[0].type == "INTENT",
        "PredicateApprovalPort: predicate received the real INTENT Event, not a stand-in",
    )

    raised = None
    try:
        executor.execute("echo", "deny-me")
    except ApprovalDenied as exc:
        raised = exc
    check(isinstance(raised, ApprovalDenied), "PredicateApprovalPort: predicate False -> DENIED -> ApprovalDenied")
    check(len(calls) == 2, "PredicateApprovalPort: predicate was invoked again for the second call")


# ---------------------------------------------------------------------------
# 6. Protocol compliance -- every new policy exposes `version: str` and
#    `check(event) -> ApprovalOutcome`.
# ---------------------------------------------------------------------------
def scenario_protocol_compliance() -> None:
    ports = [
        AlwaysApproveApprovalPort(),
        DenyAllApprovalPort(),
        ToolWhitelistApprovalPort(allowed_tools=["echo"]),
        ToolBlacklistApprovalPort(blocked_tools=["echo"]),
        PredicateApprovalPort(predicate=lambda event: True),  # noqa: ARG005
    ]
    for port in ports:
        name = type(port).__name__
        check(isinstance(getattr(port, "version", None), str), f"{name}: has string `version` attribute")
        check(callable(getattr(port, "check", None)), f"{name}: has callable `check` method")
        params = list(inspect.signature(port.check).parameters.keys())
        check(params == ["event"], f"{name}: check(event) signature matches ApprovalPort Protocol ({params})")


# ---------------------------------------------------------------------------
# 7. Actor remains alive/usable after a policy-driven DENIED outcome.
# ---------------------------------------------------------------------------
def scenario_actor_alive_after_policy_denial() -> None:
    registry = _fresh_registry_with_echo_tool()
    executor = Executor(registry, approval_port=DenyAllApprovalPort())

    actor_id = executor.create_actor(task=b'{"genesis": "stage9-2-actor-alive"}')

    raised = None
    try:
        executor.execute("echo", "hello", actor_id=actor_id)
    except ApprovalDenied as exc:
        raised = exc
    check(isinstance(raised, ApprovalDenied), "Actor-alive scenario: first call on reused Actor is denied as expected")

    # Actor must still accept further execute() calls on the same actor_id
    # -- proof the DENIED outcome did not corrupt/terminate the Actor.
    raised_again = None
    try:
        executor.execute("echo", "hello again", actor_id=actor_id)
    except ApprovalDenied as exc:
        raised_again = exc
    check(
        isinstance(raised_again, ApprovalDenied),
        "Actor remains alive and usable after a policy-driven DENIED -- second execute() on same actor_id still runs (denied again, not crashed/rejected as dead)",
    )


# ---------------------------------------------------------------------------
# 8. Composition Root untouched -- production graph still wires
#    AlwaysApproveApprovalPort by construction (no approval_port passed).
# ---------------------------------------------------------------------------
def scenario_composition_root_unchanged() -> None:
    from Core.composition_root import build_application

    graph = build_application(
        provider_name="gemini-stage9-2-composition-root-check",
        agent_name="stock_agent-stage9-2-composition-root-check",
    )
    approval_port = graph.executor._runtime._approval  # noqa: SLF001 -- deliberate white-box check
    check(
        isinstance(approval_port, AlwaysApproveApprovalPort),
        f"Composition Root still wires AlwaysApproveApprovalPort by default (got {type(approval_port).__name__})",
    )


def main() -> int:
    scenarios = [
        scenario_always_approve_sanity,
        scenario_deny_all,
        scenario_tool_whitelist,
        scenario_tool_blacklist,
        scenario_predicate_approval,
        scenario_protocol_compliance,
        scenario_actor_alive_after_policy_denial,
        scenario_composition_root_unchanged,
    ]

    import traceback

    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE 9.2 APPROVAL POLICIES TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())