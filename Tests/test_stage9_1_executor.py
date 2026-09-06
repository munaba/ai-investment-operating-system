"""
Stage 9.1 proof suite -- Executor Dependency Injection.

Scope (per this session's LOCKED design decision):
  - Agents/executor.py::Executor.__init__ gained three optional,
    additive parameters -- approval_port, gateway, event_store -- each
    defaulting to None, in which case the exact same concrete class
    Stage 8.2 always hardcoded is constructed instead (AlwaysApproveApprovalPort,
    DefaultGateway, InMemoryEventStore respectively). Nothing else about
    Executor changed: sandbox (GenericSandbox) and reducer (ReducerShell
    + _NoOpReducerLogic) remain hardcoded, out of this stage's scope.
  - Core.runtime.Runtime, Agents.base_agent.BaseAgent, Agents.planner.Planner,
    Core.composition_root -- all untouched.

Cakupan:
  1. Old-style construction, Executor(tool_registry) positional, still
     works unchanged (regression against Stage 8.2/9.0 call sites).
  2. Default behavior (no DI args supplied) is identical to Stage 8.2:
     a tool call succeeds through the real Runtime pipeline exactly as
     before.
  3. A custom approval_port is actually used by Runtime (not silently
     ignored) -- proven functionally: a deny-everything ApprovalPort
     causes ApprovalDenied, which was unreachable before Stage 9.1
     (AlwaysApproveApprovalPort was the only option).
  4. A custom gateway is actually used -- proven via a spy wrapper
     around the real DefaultGateway: translate() call count increments.
  5. A custom event_store is actually used -- same spy-wrapper approach
     around the real InMemoryEventStore: append() call count increments.
  6. New signature matches the design exactly:
     [self, tool_registry, approval_port, gateway, event_store].
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.approval import AlwaysApproveApprovalPort
from Core.event import Event
from Core.event_store import InMemoryEventStore
from Core.exceptions import ApprovalDenied
from Core.gateaway import DefaultGateway
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

    ToolRegistry.reset() first -- same reasoning as
    Tests/test_stock_agent_smoke.py::build_agent: it is a process-wide
    singleton whose tool names bind for the process lifetime, so each
    scenario here needs a clean slate.
    """
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name=tool_name, description="echoes its input", handler=lambda x: x))
    return registry


# ---------------------------------------------------------------------------
# 1 & 2. Old-style positional construction + default behavior identical
#        to Stage 8.2.
# ---------------------------------------------------------------------------
def scenario_positional_construction_and_default_behavior_unchanged() -> None:
    registry = _fresh_registry_with_echo_tool()
    executor = Executor(registry)  # positional, exactly as Stage 8.2/9.0 call it

    result = executor.execute("echo", "hello")
    check(result == "hello", "Executor(tool_registry) positional construction still works, tool executes")

    actor_id = executor.create_actor(b'{"genesis": "stage9-1-default"}')
    check(isinstance(actor_id, str) and len(actor_id) > 0, "create_actor() still works with default-constructed Runtime")


# ---------------------------------------------------------------------------
# 3. Custom approval_port actually used.
# ---------------------------------------------------------------------------
class _DenyAllApprovalPort:
    version = "stage9-1-deny-all-v1"

    def check(self, event: Event) -> ApprovalOutcome:  # noqa: ARG002
        return ApprovalOutcome.DENIED


def scenario_custom_approval_port_is_used() -> None:
    registry = _fresh_registry_with_echo_tool()
    executor = Executor(registry, approval_port=_DenyAllApprovalPort())

    raised = None
    try:
        executor.execute("echo", "hello")
    except ApprovalDenied as exc:
        raised = exc

    check(
        isinstance(raised, ApprovalDenied),
        "custom approval_port is actually consulted by Runtime -- deny-all port causes ApprovalDenied (unreachable pre-Stage-9.1)",
    )


# ---------------------------------------------------------------------------
# 4. Custom gateway actually used (spy wrapper around the real DefaultGateway).
# ---------------------------------------------------------------------------
class _SpyGateway:
    def __init__(self) -> None:
        self._real = DefaultGateway()
        self.translate_calls = 0

    def translate(self, raw: bytes, source: str, causal_scope_id: Any) -> Event:
        self.translate_calls += 1
        return self._real.translate(raw, source, causal_scope_id)


def scenario_custom_gateway_is_used() -> None:
    registry = _fresh_registry_with_echo_tool()
    spy_gateway = _SpyGateway()
    executor = Executor(registry, gateway=spy_gateway)

    check(spy_gateway.translate_calls == 0, "spy gateway starts with zero translate() calls")
    executor.execute("echo", "hello")
    check(spy_gateway.translate_calls > 0, f"custom gateway.translate() was actually called by Runtime ({spy_gateway.translate_calls} time(s))")


# ---------------------------------------------------------------------------
# 5. Custom event_store actually used (spy wrapper around InMemoryEventStore).
# ---------------------------------------------------------------------------
class _SpyEventStore:
    def __init__(self) -> None:
        self._real = InMemoryEventStore()
        self.append_calls = 0

    def append(self, event: Event):
        self.append_calls += 1
        return self._real.append(event)

    def exists(self, event_id):
        return self._real.exists(event_id)

    def get(self, event_id):
        return self._real.get(event_id)

    def read(self, causal_scope_id, from_seq: int = 0, to_seq=None):
        return self._real.read(causal_scope_id, from_seq, to_seq)

    def read_stream(self, causal_scope_id):
        return self._real.read_stream(causal_scope_id)


def scenario_custom_event_store_is_used() -> None:
    registry = _fresh_registry_with_echo_tool()
    spy_store = _SpyEventStore()
    executor = Executor(registry, event_store=spy_store)

    check(spy_store.append_calls == 0, "spy event_store starts with zero append() calls")
    executor.execute("echo", "hello")
    check(spy_store.append_calls > 0, f"custom event_store.append() was actually called by Runtime ({spy_store.append_calls} time(s))")


# ---------------------------------------------------------------------------
# 6. Signature matches the design exactly.
# ---------------------------------------------------------------------------
def scenario_signature_matches_design() -> None:
    import inspect

    params = list(inspect.signature(Executor.__init__).parameters.keys())
    check(
        params == ["self", "tool_registry", "approval_port", "gateway", "event_store"],
        f"Executor.__init__ signature matches Stage 9.1 design exactly: {params}",
    )


def main() -> int:
    scenarios = [
        scenario_positional_construction_and_default_behavior_unchanged,
        scenario_custom_approval_port_is_used,
        scenario_custom_gateway_is_used,
        scenario_custom_event_store_is_used,
        scenario_signature_matches_design,
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
    print(f"STAGE 9.1 EXECUTOR DI TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())