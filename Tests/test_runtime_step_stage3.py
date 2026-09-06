from __future__ import annotations

from pathlib import Path
import sys
import traceback
from typing import Any, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.event import Event, EventType
from Core.event_store import InMemoryEventStore
from Core.gateaway import DefaultGateway
from Core.reducer_shell import ReducerShell, State
from Core.runtime import (
    ApprovalOutcome,
    ActorTerminatedError,
    NoEventToProcessError,
    Runtime,
    StepResult,
)


# ---------------------------------------------------------------------------
# Test doubles -- minimal, only implement the Port surface Runtime depends on.
# ---------------------------------------------------------------------------
class RecordingReducerLogic:
    """
    Pure, deterministic: new value = old value + [(event.type, event.causal_scope_id,
    event.id.seq, event.payload)]. No clock/random/network/filesystem access --
    must survive ReducerShell's purity guard. This is exactly what lets test 7
    (replay parity) compare live-state vs. independently-reduced-state by value
    equality: same Event sequence -> same accumulated list, deterministically.
    """

    version = "test-reducer-v1"

    def reduce(self, state: State, event: Event) -> Any:
        prior = state.value or []
        return prior + [(event.type, event.causal_scope_id, event.id.seq, event.payload)]


class ScriptedApproval:
    """ApprovalPort test double -- returns outcomes from a pre-scripted queue,
    one per call to check(). Records every Event it was asked to check."""

    version = "policy-v1"

    def __init__(self, outcomes: list[ApprovalOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.checked: list[Event] = []

    def check(self, event: Event) -> ApprovalOutcome:
        self.checked.append(event)
        return self._outcomes.pop(0)


class RecordingSandbox:
    """SandboxPort test double -- returns a fixed bytes payload, records which
    intent_event it was called with (to prove Runtime never calls it for
    DENIED/PENDING, and always passes the INTENT event, not the Decision)."""

    def __init__(self, effect_payload: bytes = b"effect-ok") -> None:
        self._effect_payload = effect_payload
        self.executed_with: list[Event] = []

    def execute(self, intent_event: Event) -> bytes:
        self.executed_with.append(intent_event)
        return self._effect_payload


def build_runtime(approval_outcomes: Optional[list[ApprovalOutcome]] = None):
    event_store = InMemoryEventStore()
    gateway = DefaultGateway()
    logic = RecordingReducerLogic()
    reducer = ReducerShell(logic)
    sandbox = RecordingSandbox()
    approval = ScriptedApproval(approval_outcomes or [])
    runtime = Runtime(
        event_store=event_store,
        gateway=gateway,
        reducer=reducer,
        sandbox=sandbox,
        approval=approval,
    )
    return runtime, event_store, logic, sandbox, approval


# ---------------------------------------------------------------------------
# check() harness -- matches Tests/test_stock_agent_smoke.py convention.
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
# 1. OBSERVATION path
# ---------------------------------------------------------------------------
def scenario_observation_path() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime()
    actor_id = runtime.create_actor(task=b"genesis-task")

    runtime.ingest(b"raw-observation", source="test", actor_id=actor_id)
    result = runtime.step(actor_id)

    check(result == StepResult.CONTINUE, "OBSERVATION trigger -> step() returns CONTINUE")
    check(
        runtime._cursors[actor_id] == 1,
        "OBSERVATION trigger -> cursor advances exactly one position (genesis=0, obs=1)",
    )
    check(len(sandbox.executed_with) == 0, "OBSERVATION trigger -> Sandbox never called")
    check(len(approval.checked) == 0, "OBSERVATION trigger -> ApprovalPort never called")
    check(
        runtime._states[actor_id].value[-1][0] == EventType.OBSERVATION,
        "OBSERVATION trigger -> reduced value reflects OBSERVATION type",
    )


# ---------------------------------------------------------------------------
# 2. INTENT -> APPROVED -> EFFECT_COMPLETED
# ---------------------------------------------------------------------------
def scenario_intent_approved_effect_completed() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.APPROVED]
    )
    actor_id = runtime.create_actor(task=b"genesis-task")
    runtime.ingest(b"buy-order", source="test", actor_id=actor_id, event_type=EventType.INTENT)

    result = runtime.step(actor_id)

    check(result == StepResult.CONTINUE, "INTENT/APPROVED -> step() returns CONTINUE")
    check(len(sandbox.executed_with) == 1, "INTENT/APPROVED -> Sandbox.execute() called exactly once")

    stream = list(event_store.read_stream(actor_id))
    # [0]=genesis, [1]=INTENT, [2]=Decision, [3]=EFFECT_COMPLETED
    check(len(stream) == 4, "INTENT/APPROVED -> exactly 4 Events in stream (genesis, intent, decision, effect)")
    check(stream[1].type == EventType.INTENT, "stream[1] is the INTENT trigger")
    check(stream[2].type == EventType.DECISION, "stream[2] is the Decision")
    check(stream[2].causal_refs == [stream[1].id], "Decision.causal_refs points at the INTENT Event")
    check(stream[3].type == "EFFECT_COMPLETED", "stream[3] is EFFECT_COMPLETED")
    check(
        stream[3].causal_refs == [stream[1].id],
        "EFFECT_COMPLETED.causal_refs points at the INTENT Event, NOT the Decision Event",
    )
    check(
        sandbox.executed_with[0] is stream[1],
        "Sandbox.execute() was called with the canonical INTENT Event (post-append, id filled)",
    )
    check(
        runtime._cursors[actor_id] == 3,
        "cursor advanced past all 3 mechanical consequences in the SAME step() call (ND-1)",
    )
    check(
        [row[0] for row in runtime._states[actor_id].value] ==
        [EventType.OBSERVATION, EventType.INTENT, EventType.DECISION, "EFFECT_COMPLETED"],
        "reduced state reflects genesis+intent+decision+effect in order, each reduced exactly once",
    )


# ---------------------------------------------------------------------------
# 3. INTENT -> DENIED
# ---------------------------------------------------------------------------
def scenario_intent_denied() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.DENIED]
    )
    actor_id = runtime.create_actor(task=b"genesis-task")
    runtime.ingest(b"buy-order", source="test", actor_id=actor_id, event_type=EventType.INTENT)

    result = runtime.step(actor_id)

    check(result == StepResult.CONTINUE, "INTENT/DENIED -> step() returns CONTINUE")
    check(len(sandbox.executed_with) == 0, "INTENT/DENIED -> Sandbox.execute() never called")

    stream = list(event_store.read_stream(actor_id))
    check(len(stream) == 3, "INTENT/DENIED -> exactly 3 Events (genesis, intent, decision) -- no effect")
    check(stream[2].type == EventType.DECISION, "stream[2] is the Decision")
    check(runtime._cursors[actor_id] == 2, "cursor advances through Decision, then stops (no effect)")


# ---------------------------------------------------------------------------
# 4. INTENT -> PENDING (and: no retry of the old INTENT)
# ---------------------------------------------------------------------------
def scenario_intent_pending_no_retry() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.PENDING]
    )
    actor_id = runtime.create_actor(task=b"genesis-task")
    runtime.ingest(b"buy-order", source="test", actor_id=actor_id, event_type=EventType.INTENT)

    result = runtime.step(actor_id)

    check(result == StepResult.CONTINUE, "INTENT/PENDING -> step() returns CONTINUE")
    check(len(sandbox.executed_with) == 0, "INTENT/PENDING -> Sandbox.execute() never called")
    stream = list(event_store.read_stream(actor_id))
    check(len(stream) == 3, "INTENT/PENDING -> Decision(Pending) is still appended (3 events total)")
    check(runtime._cursors[actor_id] == 2, "INTENT/PENDING -> Decision(Pending) is still reduced, cursor still advances")

    # ND-3: Runtime never retries the old INTENT. Calling step() again with
    # nothing new ingested must NOT re-process the same INTENT -- it must
    # fail with NoEventToProcessError, exactly like any other exhausted stream.
    raised = False
    try:
        runtime.step(actor_id)
    except NoEventToProcessError:
        raised = True
    check(raised, "INTENT/PENDING -> next step() with nothing new raises NoEventToProcessError, not a retry")
    check(len(approval.checked) == 1, "ApprovalPort.check() was called exactly once total -- no re-check of the old INTENT")


# ---------------------------------------------------------------------------
# 5. ACTOR_TERMINATED as a normal trigger Event
# ---------------------------------------------------------------------------
def scenario_actor_terminated_as_normal_event() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime()
    actor_id = runtime.create_actor(task=b"genesis-task")

    # Simulates the Implementation layer deciding termination and emitting it
    # as an ordinary Event -- NOT via Runtime.terminate(). Runtime.step() must
    # not special-case this beyond reporting what the Event already says (ND-2).
    runtime.ingest(
        b"termination-reason",
        source="implementation-layer",
        actor_id=actor_id,
        event_type=EventType.ACTOR_TERMINATED,
    )

    result = runtime.step(actor_id)

    check(result == StepResult.TERMINATED, "ACTOR_TERMINATED trigger -> step() returns TERMINATED")
    check(runtime._cursors[actor_id] == 1, "ACTOR_TERMINATED trigger -> reduced and cursor advanced like any Event")
    check(runtime.is_alive(actor_id) is False, "is_alive() agrees with step()'s TERMINATED result (single source of truth)")

    raised = False
    try:
        runtime.step(actor_id)
    except ActorTerminatedError:
        raised = True
    check(raised, "step() on an already-TERMINATED Actor raises ActorTerminatedError, refuses further operation")


# ---------------------------------------------------------------------------
# 6. NoEventToProcessError
# ---------------------------------------------------------------------------
def scenario_no_event_to_process() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime()
    actor_id = runtime.create_actor(task=b"genesis-task")
    # No ingest() call -- cursor is at genesis (0), nothing at position 1.

    raised = False
    try:
        runtime.step(actor_id)
    except NoEventToProcessError as exc:
        raised = True
        check(exc.actor_id == actor_id, "NoEventToProcessError carries the actor_id")
        check(exc.cursor == 0, "NoEventToProcessError carries the cursor it failed at")
    check(raised, "step() with nothing past the cursor raises NoEventToProcessError (never a silent no-op)")


# ---------------------------------------------------------------------------
# 7. Replay parity: independently-reduced state == live-stepped state
# ---------------------------------------------------------------------------
def scenario_replay_parity() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED]
    )
    actor_id = runtime.create_actor(task=b"genesis-task")

    runtime.ingest(b"obs-1", source="test", actor_id=actor_id)
    runtime.step(actor_id)

    runtime.ingest(b"intent-1", source="test", actor_id=actor_id, event_type=EventType.INTENT)
    runtime.step(actor_id)  # -> APPROVED -> Decision + EFFECT_COMPLETED

    runtime.ingest(b"intent-2", source="test", actor_id=actor_id, event_type=EventType.INTENT)
    runtime.step(actor_id)  # -> DENIED -> Decision only

    live_state = runtime._states[actor_id]
    live_cursor = runtime._cursors[actor_id]

    # Independent replay: fresh ReducerShell over the SAME logic (same
    # .version, same pure function), folding over the entire stream read
    # straight from the Event Store -- no access to Runtime's private
    # bookkeeping at all, matching "Prinsip replay: reduce(reducer.apply,
    # seluruh Event, initial_state)".
    fresh_reducer = ReducerShell(RecordingReducerLogic())
    replayed_state = State.empty()
    replayed_stream = list(event_store.read_stream(actor_id))
    for event in replayed_stream:
        replayed_state = fresh_reducer.apply(replayed_state, event)

    check(
        len(replayed_stream) == live_cursor + 1,
        "replay reads exactly as many Events as the live cursor processed (every appended Event reduced once)",
    )
    check(
        replayed_state.value == live_state.value,
        "replay-derived state.value == live-stepped state.value (replay parity)",
    )
    check(
        replayed_state.reducer_version == live_state.reducer_version,
        "replay-derived reducer_version == live-stepped reducer_version",
    )


def main() -> int:
    scenarios = [
        scenario_observation_path,
        scenario_intent_approved_effect_completed,
        scenario_intent_denied,
        scenario_intent_pending_no_retry,
        scenario_actor_terminated_as_normal_event,
        scenario_no_event_to_process,
        scenario_replay_parity,
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
    print(f"STAGE 3 STEP() TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())