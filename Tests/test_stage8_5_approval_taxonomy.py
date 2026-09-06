"""
Stage 8.5 proof suite -- Approval taxonomy fix (ApprovalDenied / ApprovalPending).

Scope (per Docs/runtime_lifecycle.md §4, design-freeze Stage 8.4, approved
for implementation this session):
  - Core.exceptions.ApprovalDenied / ApprovalPending are distinct AgentError
    subclasses, NOT RuntimeInvariantError.
  - Agents.executor.Executor._translate_last_event() is the single dispatch
    point that maps a drained INTENT cycle's last Event to: a plain return
    value, ApprovalDenied, ApprovalPending, or (only for genuine contract
    violations) RuntimeInvariantError.
  - Runtime itself (Core/runtime.py) is untouched -- ApprovalOutcome.DENIED/
    PENDING already produce a DECISION Event correctly; the bug was only in
    Executor's translation of that Event.

Cakupan skenario:
  MAIN (Runtime asli + ApprovalPort test double -- sumber Event bukan buatan
  tangan, ini pembuktian utama taxonomy tidak drift dari apa yang Runtime
  betul-betul hasilkan):
    1. DENIED lewat Runtime asli -> DECISION(DENIED) ter-append, Sandbox
       TIDAK pernah dipanggil, Executor._translate_last_event() atas Event
       tsb menghasilkan ApprovalDenied (bukan RuntimeInvariantError).
    2. PENDING lewat Runtime asli -> sama, menghasilkan ApprovalPending.
    3. APPROVED lewat Runtime asli (happy path, regresi) -> Executor
       menghasilkan return value biasa, TIDAK ApprovalDenied/Pending/
       RuntimeInvariantError.
    4. Actor tetap alive & bisa dipakai lagi setelah DENIED (bukti "Actor
       untouched" di deskripsi ApprovalDenied).

  UNIT TAMBAHAN (Event dibangun tangan -- hanya pelengkap, bukan pembuktian
  utama):
    5. ApprovalDenied / ApprovalPending adalah subclass AgentError, bukan
       subclass RuntimeInvariantError.
    6. DECISION dengan outcome tak dikenal -> tetap RuntimeInvariantError
       (fallback invariant tidak melebar/menyempit).
    7. DECISION(APPROVED) sebagai Event TERAKHIR (kasus yang seharusnya
       unreachable lewat Runtime asli) -> RuntimeInvariantError, bukan
       ApprovalDenied/Pending, bukan silently accepted.
    8. Event type lain yang sama sekali tak dikenal -> RuntimeInvariantError
       (perilaku lama, harus tidak berubah).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import traceback
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.event import Event, EventID, EventType
from Core.event_store import InMemoryEventStore
from Core.exceptions import ApprovalDenied, ApprovalPending, RuntimeInvariantError, AgentError
from Core.gateaway import DefaultGateway
from Core.reducer_shell import ReducerShell, State
from Core.runtime import ApprovalOutcome, Runtime
from Agents.executor import Executor
from Agents.sandbox import GenericSandbox
from Agents.tool_registry import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# check() harness -- konvensi sama dengan test_stage8_1/test_stage8_2.
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


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _NoOpReducerLogic:
    version = "stage8-5-noop-reducer-v1"

    def reduce(self, state, event):  # noqa: ARG002
        return None


class ScriptedApproval:
    """ApprovalPort test double -- returns outcomes from a pre-scripted
    queue, one per call to check(). Records every Event it was asked to
    check (used to prove Runtime, not the test, decided the outcome)."""

    version = "stage8-5-policy-v1"

    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.checked: list = []

    def check(self, event: Event) -> ApprovalOutcome:
        self.checked.append(event)
        return self._outcomes.pop(0)


class RecordingSandbox:
    """SandboxPort test double that records whether it was ever called --
    used to prove DENIED/PENDING never reach Sandbox.execute()."""

    def __init__(self) -> None:
        self.calls: list = []

    def execute(self, intent_event: Event) -> bytes:
        self.calls.append(intent_event)
        return json.dumps({"status": "ok", "result": "should-not-happen"}).encode("utf-8")


def build_runtime(approval_outcomes, sandbox=None):
    """Build a real Runtime wired with a ScriptedApproval double -- same
    pattern as Tests/test_runtime_step_stage3.py::build_runtime, adapted for
    this suite. Executor's own private Runtime is never touched (Executor's
    constructor is LOCKED, unchanged) -- this is a standalone Runtime built
    directly in the test, exactly as approved."""
    event_store = InMemoryEventStore()
    gateway = DefaultGateway()
    reducer = ReducerShell(_NoOpReducerLogic())
    approval = ScriptedApproval(approval_outcomes)
    sandbox = sandbox if sandbox is not None else RecordingSandbox()
    runtime = Runtime(
        event_store=event_store,
        gateway=gateway,
        reducer=reducer,
        sandbox=sandbox,
        approval=approval,
    )
    return runtime, approval, sandbox


def make_decision_event(outcome: str, scope: str = "actor-manual", seq: int = 2, policy_version: Optional[str] = "v-manual") -> Event:
    """Hand-built DECISION Event -- ONLY for the small supplementary unit
    tests (5-8), never for the main proof (1-4)."""
    payload = json.dumps({"outcome": outcome, "policy_version": policy_version}).encode("utf-8")
    return Event(
        causal_scope_id=scope,
        type=EventType.DECISION,
        payload=payload,
        causal_refs=[],
        id=EventID(causal_scope_id=scope, seq=seq),
    )


# ---------------------------------------------------------------------------
# 1. MAIN: DENIED via real Runtime -> ApprovalDenied
# ---------------------------------------------------------------------------
def scenario_denied_via_real_runtime() -> None:
    runtime, approval, sandbox = build_runtime([ApprovalOutcome.DENIED])
    actor_id = runtime.create_actor(task=b"genesis")
    intent_payload = json.dumps({"tool_name": "transfer_funds", "args": [100]}).encode("utf-8")
    runtime.ingest(intent_payload, source="test", actor_id=actor_id, event_type=EventType.INTENT)

    runtime.step(actor_id)

    events, _state = runtime.replay(actor_id)
    last_event = events[-1]

    check(last_event.type == EventType.DECISION, "Runtime appends DECISION as last Event on DENIED (unchanged Runtime behavior)")
    check(len(sandbox.calls) == 0, "Sandbox.execute() is NEVER called when outcome is DENIED")

    raised = None
    try:
        Executor._translate_last_event(last_event, "transfer_funds", actor_id)
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(isinstance(raised, ApprovalDenied), "Executor._translate_last_event() raises ApprovalDenied for a real DECISION(DENIED) Event")
    check(not isinstance(raised, RuntimeInvariantError), "ApprovalDenied is NOT a RuntimeInvariantError")
    if raised is not None:
        check(raised.details.get("tool_name") == "transfer_funds", "ApprovalDenied.details carries tool_name")
        check(raised.details.get("policy_version") == approval.version, "ApprovalDenied.details carries the policy_version Runtime recorded")


# ---------------------------------------------------------------------------
# 2. MAIN: PENDING via real Runtime -> ApprovalPending
# ---------------------------------------------------------------------------
def scenario_pending_via_real_runtime() -> None:
    runtime, approval, sandbox = build_runtime([ApprovalOutcome.PENDING])
    actor_id = runtime.create_actor(task=b"genesis")
    intent_payload = json.dumps({"tool_name": "wire_transfer", "args": []}).encode("utf-8")
    runtime.ingest(intent_payload, source="test", actor_id=actor_id, event_type=EventType.INTENT)

    runtime.step(actor_id)

    events, _state = runtime.replay(actor_id)
    last_event = events[-1]

    check(last_event.type == EventType.DECISION, "Runtime appends DECISION as last Event on PENDING (unchanged Runtime behavior)")
    check(len(sandbox.calls) == 0, "Sandbox.execute() is NEVER called when outcome is PENDING")

    raised = None
    try:
        Executor._translate_last_event(last_event, "wire_transfer", actor_id)
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(isinstance(raised, ApprovalPending), "Executor._translate_last_event() raises ApprovalPending for a real DECISION(PENDING) Event")
    check(not isinstance(raised, RuntimeInvariantError), "ApprovalPending is NOT a RuntimeInvariantError")
    if raised is not None:
        check(raised.details.get("tool_name") == "wire_transfer", "ApprovalPending.details carries tool_name")


# ---------------------------------------------------------------------------
# 3. MAIN: APPROVED happy-path regression, via real Runtime + real Sandbox
# ---------------------------------------------------------------------------
def scenario_approved_happy_path_regression() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="add", description="adds two numbers", handler=lambda a, b: a + b))
    real_sandbox = GenericSandbox(registry)

    runtime, approval, _ = build_runtime([ApprovalOutcome.APPROVED], sandbox=real_sandbox)
    actor_id = runtime.create_actor(task=b"genesis")
    intent_payload = json.dumps({"tool_name": "add", "args": [2, 3]}).encode("utf-8")
    runtime.ingest(intent_payload, source="test", actor_id=actor_id, event_type=EventType.INTENT)

    runtime.step(actor_id)

    events, _state = runtime.replay(actor_id)
    last_event = events[-1]

    check(last_event.type == "EFFECT_COMPLETED", "Runtime appends EFFECT_COMPLETED as last Event on APPROVED (unchanged)")

    result = Executor._translate_last_event(last_event, "add", actor_id)
    check(result == 5, "Executor._translate_last_event() returns plain result on APPROVED/EFFECT_COMPLETED, unchanged Stage 8.2 behavior")

    registry.reset()


# ---------------------------------------------------------------------------
# 4. MAIN: Actor remains usable after DENIED (Actor untouched)
# ---------------------------------------------------------------------------
def scenario_actor_usable_after_denied() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="add", description="adds two numbers", handler=lambda a, b: a + b))
    real_sandbox = GenericSandbox(registry)

    runtime, approval, _ = build_runtime(
        [ApprovalOutcome.DENIED, ApprovalOutcome.APPROVED], sandbox=real_sandbox
    )
    actor_id = runtime.create_actor(task=b"genesis")

    intent_payload = json.dumps({"tool_name": "add", "args": [1, 1]}).encode("utf-8")
    runtime.ingest(intent_payload, source="test", actor_id=actor_id, event_type=EventType.INTENT)
    runtime.step(actor_id)

    check(runtime.is_alive(actor_id), "Actor is still alive after a DENIED outcome")

    # Same actor, second INTENT -- this time APPROVED.
    intent_payload_2 = json.dumps({"tool_name": "add", "args": [10, 20]}).encode("utf-8")
    runtime.ingest(intent_payload_2, source="test", actor_id=actor_id, event_type=EventType.INTENT)
    runtime.step(actor_id)

    events, _state = runtime.replay(actor_id)
    last_event = events[-1]
    result = Executor._translate_last_event(last_event, "add", actor_id)

    check(result == 30, "Same Actor accepts a fresh INTENT and succeeds normally after an earlier DENIED -- Actor was never damaged")


# ---------------------------------------------------------------------------
# 5. UNIT: exception hierarchy
# ---------------------------------------------------------------------------
def scenario_exception_hierarchy() -> None:
    check(issubclass(ApprovalDenied, AgentError), "ApprovalDenied is a subclass of AgentError")
    check(issubclass(ApprovalPending, AgentError), "ApprovalPending is a subclass of AgentError")
    check(not issubclass(ApprovalDenied, RuntimeInvariantError), "ApprovalDenied is NOT a subclass of RuntimeInvariantError")
    check(not issubclass(ApprovalPending, RuntimeInvariantError), "ApprovalPending is NOT a subclass of RuntimeInvariantError")


# ---------------------------------------------------------------------------
# 6. UNIT: unrecognized outcome value -> still RuntimeInvariantError
# ---------------------------------------------------------------------------
def scenario_unrecognized_outcome_manual_event() -> None:
    ev = make_decision_event(outcome="SOMETHING_ELSE")
    raised = None
    try:
        Executor._translate_last_event(ev, "some_tool", "actor-manual")
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(isinstance(raised, RuntimeInvariantError), "Unrecognized DECISION outcome still raises RuntimeInvariantError (fallback unchanged)")


# ---------------------------------------------------------------------------
# 7. UNIT: DECISION(APPROVED) as the LAST event -- structurally unreachable
#    via real Runtime, guarded explicitly rather than silently accepted.
# ---------------------------------------------------------------------------
def scenario_decision_approved_as_last_event_manual() -> None:
    ev = make_decision_event(outcome="APPROVED")
    raised = None
    try:
        Executor._translate_last_event(ev, "some_tool", "actor-manual")
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(isinstance(raised, RuntimeInvariantError), "DECISION(APPROVED) as the LAST event raises RuntimeInvariantError, not silently accepted")
    check(not isinstance(raised, (ApprovalDenied, ApprovalPending)), "DECISION(APPROVED)-as-last is not misreported as ApprovalDenied/Pending")


# ---------------------------------------------------------------------------
# 8. UNIT: completely unknown event type -- old behavior preserved
# ---------------------------------------------------------------------------
def scenario_unknown_event_type_manual() -> None:
    ev = Event(
        causal_scope_id="actor-manual",
        type="SOME_UNKNOWN_EVENT_TYPE",
        payload=b"irrelevant",
        causal_refs=[],
        id=EventID(causal_scope_id="actor-manual", seq=3),
    )
    raised = None
    try:
        Executor._translate_last_event(ev, "some_tool", "actor-manual")
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(isinstance(raised, RuntimeInvariantError), "Completely unknown Event type still raises RuntimeInvariantError (Stage 8.2 behavior preserved)")


def main() -> int:
    scenarios = [
        scenario_denied_via_real_runtime,
        scenario_pending_via_real_runtime,
        scenario_approved_happy_path_regression,
        scenario_actor_usable_after_denied,
        scenario_exception_hierarchy,
        scenario_unrecognized_outcome_manual_event,
        scenario_decision_approved_as_last_event_manual,
        scenario_unknown_event_type_manual,
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
    print(f"STAGE 8.5 APPROVAL TAXONOMY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())