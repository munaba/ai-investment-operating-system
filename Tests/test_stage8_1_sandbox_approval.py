"""
Stage 8.1 proof suite -- GenericSandbox + AlwaysApproveApprovalPort.

Cakupan (diperbarui Stage 8.2 -- GenericSandbox sekarang error-as-data,
LOCKED: tidak pernah lagi melempar exception untuk kegagalan tool normal):
  1. AlwaysApproveApprovalPort.check() selalu APPROVED, tidak pernah
     membuka event.payload.
  2. GenericSandbox.execute() -- happy path: decode envelope, panggil
     handler lewat ToolRegistry, encode hasil.
  3. GenericSandbox -- args/kwargs diteruskan dengan benar ke handler.
  4. GenericSandbox -- payload bukan JSON -> bytes {"status":"error",
     "error_type":"decode_error"}, BUKAN exception.
  5. GenericSandbox -- envelope tanpa 'tool_name' -> bytes {"status":"error",
     "error_type":"decode_error"}, BUKAN exception.
  6. GenericSandbox -- tool_name tidak terdaftar -> bytes {"status":"error",
     "error_type":"tool_not_found"}, BUKAN ToolNotFoundError yang dilempar.
  7. GenericSandbox -- handler melempar exception -> bytes {"status":"error",
     "error_type":"execution_error"}, BUKAN SandboxExecutionError.
  8. Wiring end-to-end lewat Runtime.step() asli (bukan test double):
     create_actor -> ingest(INTENT) -> step() -> EFFECT_COMPLETED
     ter-append dengan payload hasil Sandbox, ApprovalPort dipanggil
     tepat sekali, Sandbox dipanggil tepat sekali.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import traceback
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.event import Event, EventID, EventType
from Core.event_store import InMemoryEventStore
from Core.gateaway import DefaultGateway
from Core.reducer_shell import ReducerShell, State
from Core.runtime import ApprovalOutcome, Runtime
from Core.approval import AlwaysApproveApprovalPort
from Agents.sandbox import GenericSandbox
from Agents.tool_registry import ToolRegistry, Tool


# ---------------------------------------------------------------------------
# check() harness -- sama konvensi dengan Tests/test_runtime_step_stage3.py
# ---------------------------------------------------------------------------
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


def make_intent_event(payload: bytes, scope: str = "actor-1", seq: int = 1) -> Event:
    """Bikin Event INTENT kanonik (id terisi) untuk test Sandbox terisolasi,
    tanpa perlu lewat Runtime penuh."""
    return Event(
        causal_scope_id=scope,
        type=EventType.INTENT,
        payload=payload,
        causal_refs=[],
        id=EventID(causal_scope_id=scope, seq=seq),
    )


# ---------------------------------------------------------------------------
# 1. AlwaysApproveApprovalPort
# ---------------------------------------------------------------------------
def scenario_always_approve() -> None:
    port = AlwaysApproveApprovalPort()
    ev = make_intent_event(b"anything-not-json-at-all")

    outcome = port.check(ev)

    check(outcome == ApprovalOutcome.APPROVED, "AlwaysApproveApprovalPort.check() returns APPROVED")
    check(isinstance(port.version, str) and len(port.version) > 0, "version is a non-empty opaque string")


# ---------------------------------------------------------------------------
# 2. GenericSandbox -- happy path
# ---------------------------------------------------------------------------
def scenario_sandbox_happy_path() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="add", description="adds two numbers", handler=lambda a, b: a + b))

    sandbox = GenericSandbox(registry)
    payload = json.dumps({"tool_name": "add", "args": [2, 3]}).encode("utf-8")
    ev = make_intent_event(payload)

    result_bytes = sandbox.execute(ev)
    decoded = json.loads(result_bytes.decode("utf-8"))

    check(decoded == {"status": "ok", "result": 5}, "GenericSandbox happy path returns encoded {status, result}")
    registry.reset()


# ---------------------------------------------------------------------------
# 3. args/kwargs forwarding
# ---------------------------------------------------------------------------
def scenario_sandbox_args_kwargs() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    calls = []

    def handler(*args, **kwargs):
        calls.append((args, kwargs))
        return {"echo": True}

    registry.register(Tool(name="echo", description="records call", handler=handler))
    sandbox = GenericSandbox(registry)

    payload = json.dumps(
        {"tool_name": "echo", "args": ["x"], "kwargs": {"y": 1}}
    ).encode("utf-8")
    ev = make_intent_event(payload)
    sandbox.execute(ev)

    check(calls == [(("x",), {"y": 1})], "GenericSandbox forwards args and kwargs verbatim to handler")
    registry.reset()


# ---------------------------------------------------------------------------
# 4. invalid JSON payload -- error-as-data (Stage 8.2)
# ---------------------------------------------------------------------------
def scenario_sandbox_invalid_json() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    sandbox = GenericSandbox(registry)
    ev = make_intent_event(b"not-json{{{")

    result_bytes = sandbox.execute(ev)
    decoded = json.loads(result_bytes.decode("utf-8"))

    check(decoded.get("status") == "error", "GenericSandbox returns status=error for non-JSON payload (no exception)")
    check(decoded.get("error_type") == "decode_error", "error_type is 'decode_error' for non-JSON payload")
    registry.reset()


# ---------------------------------------------------------------------------
# 5. missing tool_name -- error-as-data (Stage 8.2)
# ---------------------------------------------------------------------------
def scenario_sandbox_missing_tool_name() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    sandbox = GenericSandbox(registry)
    ev = make_intent_event(json.dumps({"args": [1]}).encode("utf-8"))

    result_bytes = sandbox.execute(ev)
    decoded = json.loads(result_bytes.decode("utf-8"))

    check(decoded.get("status") == "error", "GenericSandbox returns status=error when 'tool_name' is missing (no exception)")
    check(decoded.get("error_type") == "decode_error", "error_type is 'decode_error' when 'tool_name' is missing")
    registry.reset()


# ---------------------------------------------------------------------------
# 6. unknown tool -- error-as-data (Stage 8.2), no exception propagates
# ---------------------------------------------------------------------------
def scenario_sandbox_unknown_tool() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    sandbox = GenericSandbox(registry)
    ev = make_intent_event(json.dumps({"tool_name": "does_not_exist"}).encode("utf-8"))

    result_bytes = sandbox.execute(ev)
    decoded = json.loads(result_bytes.decode("utf-8"))

    check(decoded.get("status") == "error", "GenericSandbox returns status=error for unregistered tool_name (no exception)")
    check(decoded.get("error_type") == "tool_not_found", "error_type is 'tool_not_found' for unregistered tool_name")
    check(decoded.get("tool_name") == "does_not_exist", "error payload carries tool_name")
    registry.reset()


# ---------------------------------------------------------------------------
# 7. handler raises -- error-as-data (Stage 8.2), no exception propagates
# ---------------------------------------------------------------------------
def scenario_sandbox_handler_raises() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()

    def boom():
        raise RuntimeError("kaboom")

    registry.register(Tool(name="boom", description="always fails", handler=boom))
    sandbox = GenericSandbox(registry)
    ev = make_intent_event(json.dumps({"tool_name": "boom"}).encode("utf-8"))

    result_bytes = sandbox.execute(ev)
    decoded = json.loads(result_bytes.decode("utf-8"))

    check(decoded.get("status") == "error", "GenericSandbox returns status=error when handler raises (no exception)")
    check(decoded.get("error_type") == "execution_error", "error_type is 'execution_error' when handler raises")
    check(decoded.get("tool_name") == "boom", "error payload carries tool_name")
    check(decoded.get("error_class") == "RuntimeError", "error payload carries original error_class")
    check(decoded.get("message") == "kaboom", "error payload carries original message")
    registry.reset()


# ---------------------------------------------------------------------------
# 8. end-to-end wiring through the real Runtime
# ---------------------------------------------------------------------------
def scenario_end_to_end_through_runtime() -> None:
    class RecordingReducerLogic:
        version = "stage8-reducer-v1"

        def reduce(self, state, event):
            prior = state.value or []
            return prior + [(event.type, event.payload)]

    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="add", description="adds two numbers", handler=lambda a, b: a + b))

    event_store = InMemoryEventStore()
    gateway = DefaultGateway()
    reducer = ReducerShell(RecordingReducerLogic())
    sandbox = GenericSandbox(registry)
    approval = AlwaysApproveApprovalPort()

    runtime = Runtime(
        event_store=event_store,
        gateway=gateway,
        reducer=reducer,
        sandbox=sandbox,
        approval=approval,
    )

    actor_id = runtime.create_actor(task=b"genesis")
    intent_payload = json.dumps({"tool_name": "add", "args": [10, 32]}).encode("utf-8")
    runtime.ingest(intent_payload, source="test", actor_id=actor_id, event_type=EventType.INTENT)

    result = runtime.step(actor_id)

    stream = list(event_store.read_stream(actor_id))
    effect_events = [e for e in stream if e.type == "EFFECT_COMPLETED"]

    check(result.name == "CONTINUE", "step() on INTENT -> AlwaysApprove -> Sandbox returns CONTINUE")
    check(len(effect_events) == 1, "exactly one EFFECT_COMPLETED appended")
    if effect_events:
        decoded = json.loads(effect_events[0].payload.decode("utf-8"))
        check(decoded == {"status": "ok", "result": 42}, "EFFECT_COMPLETED payload carries Sandbox's encoded result")

    registry.reset()


def main() -> int:
    scenarios = [
        scenario_always_approve,
        scenario_sandbox_happy_path,
        scenario_sandbox_args_kwargs,
        scenario_sandbox_invalid_json,
        scenario_sandbox_missing_tool_name,
        scenario_sandbox_unknown_tool,
        scenario_sandbox_handler_raises,
        scenario_end_to_end_through_runtime,
    ]

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
    print(f"STAGE 8.1 SANDBOX/APPROVAL TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())