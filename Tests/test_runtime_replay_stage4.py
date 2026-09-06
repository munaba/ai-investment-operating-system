from __future__ import annotations

from pathlib import Path
import sys
import traceback
from typing import Any, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.event import EventType
from Core.event_store import InMemoryEventStore
from Core.gateaway import DefaultGateway
from Core.reducer_shell import ReducerShell, State
from Core.runtime import ApprovalOutcome, Runtime


# ---------------------------------------------------------------------------
# Test doubles -- same shapes as Tests/test_runtime_step_stage3.py, kept
# local (not imported) so this file proves Stage 4 in isolation, the same
# way the Stage 3 file proves Stage 3 in isolation.
# ---------------------------------------------------------------------------
class RecordingReducerLogic:
    version = "test-reducer-v1"

    def reduce(self, state: State, event) -> Any:
        prior = state.value or []
        return prior + [(event.type, event.causal_scope_id, event.id.seq, event.payload)]


class ScriptedApproval:
    version = "policy-v1"

    def __init__(self, outcomes: list[ApprovalOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.checked: list = []

    def check(self, event) -> ApprovalOutcome:
        self.checked.append(event)
        return self._outcomes.pop(0)


class RecordingSandbox:
    def __init__(self, effect_payload: bytes = b"effect-ok") -> None:
        self._effect_payload = effect_payload
        self.executed_with: list = []

    def execute(self, intent_event) -> bytes:
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


def build_actor_with_mixed_history(runtime):
    """genesis(0) -> obs(1) -> intent/APPROVED -> decision(2) -> effect(3)
    -> intent/DENIED -> decision(4). Mirrors Stage 3's replay-parity fixture
    so both files are provably testing the same trajectory shape."""
    actor_id = runtime.create_actor(task=b"genesis-task")

    runtime.ingest(b"obs-1", source="test", actor_id=actor_id)
    runtime.step(actor_id)

    runtime.ingest(b"intent-1", source="test", actor_id=actor_id, event_type=EventType.INTENT)
    runtime.step(actor_id)  # APPROVED -> decision + effect

    runtime.ingest(b"intent-2", source="test", actor_id=actor_id, event_type=EventType.INTENT)
    runtime.step(actor_id)  # DENIED -> decision only

    return actor_id


# ---------------------------------------------------------------------------
# check() harness
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
# 1. Full replay == live state
# ---------------------------------------------------------------------------
def scenario_full_replay_equals_live_state() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED]
    )
    actor_id = build_actor_with_mixed_history(runtime)

    live_state = runtime._states[actor_id]
    live_cursor = runtime._cursors[actor_id]

    events, replayed_state = runtime.replay(actor_id)

    check(len(events) == live_cursor + 1, "replay() returns exactly as many Events as the live cursor processed")
    check(replayed_state.value == live_state.value, "replay(actor_id) state.value == live state.value")
    check(
        replayed_state.reducer_version == live_state.reducer_version,
        "replay(actor_id) reducer_version == live reducer_version",
    )
    check(
        events == list(event_store.read_stream(actor_id)),
        "replay() events == the full canonical stream read directly from the Event Store",
    )


# ---------------------------------------------------------------------------
# 2. Partial replay stops exactly at target_seq
# ---------------------------------------------------------------------------
def scenario_partial_replay_stops_at_target_seq() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED]
    )
    actor_id = build_actor_with_mixed_history(runtime)
    # Full trajectory is seq 0..4 (genesis, obs, decision(approved), effect, decision(denied)).

    events, state = runtime.replay(actor_id, target_seq=1)
    check(len(events) == 2, "target_seq=1 -> exactly 2 Events replayed (seq 0 and 1)")
    check(events[-1].id.seq == 1, "target_seq=1 -> last replayed Event is at seq 1, not beyond")
    check(len(state.value) == 2, "target_seq=1 -> reduced state.value has exactly 2 rows (seq 0 and 1)")
    check(state.value[-1][2] == 1, "target_seq=1 -> last reduced row's seq is 1, confirming replay stopped there")

    events_full, state_full = runtime.replay(actor_id)
    check(len(events_full) == 7, "sanity: full trajectory for this fixture is 7 Events (0..6: obs,obs,intent,decision,effect,intent,decision)")
    check(len(events) < len(events_full), "partial replay (target_seq=1) returns strictly fewer Events than full replay")

    # target_seq beyond the last appended Event must fail loudly, not clamp silently.
    raised_over = False
    try:
        runtime.replay(actor_id, target_seq=999)
    except ValueError:
        raised_over = True
    check(raised_over, "target_seq beyond the last appended Event raises ValueError (no silent clamping)")

    # negative target_seq must also fail loudly.
    raised_negative = False
    try:
        runtime.replay(actor_id, target_seq=-1)
    except ValueError:
        raised_negative = True
    check(raised_negative, "negative target_seq raises ValueError")


# ---------------------------------------------------------------------------
# 3. reducer_version provenance is preserved
# ---------------------------------------------------------------------------
def scenario_reducer_version_provenance_preserved() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime()
    actor_id = runtime.create_actor(task=b"genesis-task")
    runtime.ingest(b"obs-1", source="test", actor_id=actor_id)
    runtime.step(actor_id)

    _, full_state = runtime.replay(actor_id)
    _, partial_state = runtime.replay(actor_id, target_seq=0)

    check(
        full_state.reducer_version == logic.version,
        "full replay's State carries the bound ReducerLogic's version (Gap 3 provenance)",
    )
    check(
        partial_state.reducer_version == logic.version,
        "partial replay's State also carries the bound ReducerLogic's version",
    )
    check(
        full_state.reducer_version == runtime._states[actor_id].reducer_version,
        "replayed reducer_version matches live-stepped reducer_version -- no drift",
    )


# ---------------------------------------------------------------------------
# 4. Replay never mutates Runtime live state
# ---------------------------------------------------------------------------
def scenario_replay_never_mutates_live_state() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED]
    )
    actor_id = build_actor_with_mixed_history(runtime)

    live_state_before = runtime._states[actor_id]
    live_cursor_before = runtime._cursors[actor_id]
    stream_len_before = len(list(event_store.read_stream(actor_id)))

    runtime.replay(actor_id)
    runtime.replay(actor_id, target_seq=2)
    runtime.replay(actor_id)

    check(
        runtime._states[actor_id] is live_state_before,
        "runtime._states[actor_id] is the SAME object after replay() calls (never reassigned)",
    )
    check(runtime._cursors[actor_id] == live_cursor_before, "runtime._cursors[actor_id] is unchanged after replay() calls")
    check(
        len(list(event_store.read_stream(actor_id))) == stream_len_before,
        "Event Store gained no new Events from replay() (replay never appends)",
    )

    # And step()/ingest() must still work normally afterward -- replay left
    # no residue that would corrupt subsequent live execution.
    runtime.ingest(b"obs-2", source="test", actor_id=actor_id)
    result = runtime.step(actor_id)
    check(result.name == "CONTINUE", "live stepping still works correctly after replay() calls (no corrupted bookkeeping)")


# ---------------------------------------------------------------------------
# 5. Replay is deterministic
# ---------------------------------------------------------------------------
def scenario_replay_is_deterministic() -> None:
    runtime, event_store, logic, sandbox, approval = build_runtime(
        approval_outcomes=[ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED]
    )
    actor_id = build_actor_with_mixed_history(runtime)

    events_a, state_a = runtime.replay(actor_id)
    events_b, state_b = runtime.replay(actor_id)

    check(events_a == events_b, "replay() called twice returns equal Event lists")
    check(state_a.value == state_b.value, "replay() called twice returns equal state.value")
    check(
        state_a.reducer_version == state_b.reducer_version,
        "replay() called twice returns equal reducer_version",
    )

    events_c, state_c = runtime.replay(actor_id, target_seq=2)
    events_d, state_d = runtime.replay(actor_id, target_seq=2)
    check(events_c == events_d, "partial replay(target_seq=2) called twice returns equal Event lists")
    check(state_c.value == state_d.value, "partial replay(target_seq=2) called twice returns equal state.value")


def main() -> int:
    scenarios = [
        scenario_full_replay_equals_live_state,
        scenario_partial_replay_stops_at_target_seq,
        scenario_reducer_version_provenance_preserved,
        scenario_replay_never_mutates_live_state,
        scenario_replay_is_deterministic,
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
    print(f"STAGE 4 REPLAY() TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())