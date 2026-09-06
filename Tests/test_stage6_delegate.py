"""
Stage 6 proof suite -- delegate().

Cakupan (disetujui eksplisit di sesi ini):
  1. delegate() membuat child Actor baru.
  2. Parent mendapat TEPAT SATU DELEGATION_ISSUED.
  3. Child genesis causal_refs == [delegation_event.id] -- TEPAT itu, bukan
     tail parent, bukan event lain.
  4. Payload DELEGATION_ISSUED == child_task, byte-identik.
  5. Parent tidak berubah (_states/_cursors) sampai step(parent) dipanggil.
  6. Child langsung punya state genesis (seperti create_actor()).
  7. Parent TERMINATED -> delegate() ditolak (ActorTerminatedError).
  8. Unknown parent -> ActorNotFoundError.
  9. Replay parity tetap berlaku untuk parent maupun child setelah delegasi.

Plus: satu proof eksplisit "parent-child causal linkage" -- persis level
ketelitian yang sama dengan test EFFECT_COMPLETED->INTENT di Stage 3.
"""
from __future__ import annotations

import copy

import pytest

from Core.event_store import InMemoryEventStore
from Core.gateaway import DefaultGateway
from Core.reducer_shell import ReducerShell, State
from Core.runtime import ActorNotFoundError, ActorTerminatedError, Runtime


# ---------------------------------------------------------------------------
# Fixtures -- sama seperti test_stage5 (reducer logic domain-blind sederhana)
# ---------------------------------------------------------------------------
class _ListAppendReducerLogic:
    def __init__(self, version: str) -> None:
        self.version = version

    def reduce(self, state: State, event) -> list:
        prior = list(state.value) if state.value is not None else []
        prior.append(event.type)
        return prior


class _NullSandbox:
    def execute(self, intent_event) -> bytes:  # pragma: no cover
        return b"unused"


class _AlwaysApprovedApproval:
    version = "approval-v1"

    def check(self, event):  # pragma: no cover
        from Core.runtime import ApprovalOutcome

        return ApprovalOutcome.APPROVED


def make_runtime(reducer_version: str = "reducer-v1") -> Runtime:
    logic = _ListAppendReducerLogic(reducer_version)
    return Runtime(
        event_store=InMemoryEventStore(),
        gateway=DefaultGateway(),
        reducer=ReducerShell(logic),
        sandbox=_NullSandbox(),
        approval=_AlwaysApprovedApproval(),
    )


# ---------------------------------------------------------------------------
# 1. delegate() membuat child Actor baru
# ---------------------------------------------------------------------------
def test_delegate_creates_new_child_actor():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")

    child_id = runtime.delegate(parent_id, child_task=b"child-task")

    assert isinstance(child_id, str)
    assert child_id != parent_id
    # child harus benar-benar punya stream sendiri yang bisa dibaca.
    child_stream = list(runtime._event_store.read_stream(child_id))
    assert len(child_stream) == 1


# ---------------------------------------------------------------------------
# 2. Parent mendapat TEPAT SATU DELEGATION_ISSUED
# ---------------------------------------------------------------------------
def test_parent_gets_exactly_one_delegation_issued():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")

    runtime.delegate(parent_id, child_task=b"child-task")

    parent_stream = list(runtime._event_store.read_stream(parent_id))
    delegation_events = [e for e in parent_stream if e.type == "DELEGATION_ISSUED"]
    assert len(delegation_events) == 1


# ---------------------------------------------------------------------------
# 3. THE core linkage proof -- child genesis causal_refs harus TEPAT
# menunjuk ke DELEGATION_ISSUED, bukan tail parent / event lain / event
# tidak terkait.
# ---------------------------------------------------------------------------
def test_child_genesis_points_exactly_to_delegation_issued_not_any_other_event():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")
    # tambah noise di parent SEBELUM delegasi, supaya ada beberapa Event lain
    # yang TIDAK boleh salah dirujuk oleh child genesis.
    runtime.ingest(raw=b"noise-1", source="test", actor_id=parent_id)
    runtime.step(parent_id)
    runtime.ingest(raw=b"noise-2", source="test", actor_id=parent_id)
    runtime.step(parent_id)

    child_id = runtime.delegate(parent_id, child_task=b"child-task")

    parent_stream = list(runtime._event_store.read_stream(parent_id))
    delegation_events = [e for e in parent_stream if e.type == "DELEGATION_ISSUED"]
    assert len(delegation_events) == 1
    delegation_event = delegation_events[0]

    child_stream = list(runtime._event_store.read_stream(child_id))
    assert len(child_stream) == 1
    genesis_event = child_stream[0]

    # TEPAT satu causal_ref, dan TEPAT ke delegation_event -- bukan ke Event
    # lain di parent (genesis parent, noise-1, noise-2), dan bukan ke child
    # itu sendiri.
    assert genesis_event.causal_refs == [delegation_event.id]

    other_parent_event_ids = {e.id for e in parent_stream if e.id != delegation_event.id}
    assert genesis_event.causal_refs[0] not in other_parent_event_ids

    # cross-scope: id yang dirujuk memang ada di scope PARENT, bukan scope
    # child sendiri.
    assert genesis_event.causal_refs[0].causal_scope_id == parent_id

    # dan benar-benar resolvable (bukan dangling) lewat EventStore.get() --
    # inilah "koneksi eksplisit lintas scope" yang bisa ditelusuri manual.
    resolved = runtime._event_store.get(genesis_event.causal_refs[0])
    assert resolved is delegation_event
    assert resolved.type == "DELEGATION_ISSUED"


# ---------------------------------------------------------------------------
# 4. Payload DELEGATION_ISSUED == child_task, byte-identik
# ---------------------------------------------------------------------------
def test_delegation_issued_payload_is_child_task_verbatim():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")
    child_task = b"exact-bytes-of-child-task-\x00\x01\x02"

    runtime.delegate(parent_id, child_task=child_task)

    parent_stream = list(runtime._event_store.read_stream(parent_id))
    [delegation_event] = [e for e in parent_stream if e.type == "DELEGATION_ISSUED"]
    assert delegation_event.payload == child_task


# ---------------------------------------------------------------------------
# 5. Parent tidak berubah (_states/_cursors) sampai step(parent) dipanggil
# ---------------------------------------------------------------------------
def test_parent_bookkeeping_untouched_until_step():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")

    state_before = runtime._states[parent_id]
    cursor_before = runtime._cursors[parent_id]

    runtime.delegate(parent_id, child_task=b"child-task")

    # sebelum step(parent): bookkeeping HARUS identik seperti sebelum delegate().
    assert runtime._states[parent_id] == state_before
    assert runtime._cursors[parent_id] == cursor_before

    # setelah step(parent): DELEGATION_ISSUED baru direduce, cursor maju.
    result = runtime.step(parent_id)
    assert runtime._cursors[parent_id] == cursor_before + 1
    assert runtime._states[parent_id] != state_before
    assert runtime._states[parent_id].value[-1] == "DELEGATION_ISSUED"
    from Core.runtime import StepResult

    assert result == StepResult.CONTINUE


# ---------------------------------------------------------------------------
# 6. Child langsung punya state genesis (seperti create_actor())
# ---------------------------------------------------------------------------
def test_child_has_genesis_state_immediately():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")

    child_id = runtime.delegate(parent_id, child_task=b"child-task")

    assert child_id in runtime._states
    assert child_id in runtime._cursors
    assert runtime._cursors[child_id] == 0
    assert runtime._states[child_id].value == ["Observation"]  # genesis Gateway default
    assert runtime._states[child_id].reducer_version == "reducer-v1"
    assert runtime.is_alive(child_id) is True


# ---------------------------------------------------------------------------
# 7. Parent TERMINATED -> delegate() ditolak
# ---------------------------------------------------------------------------
def test_delegate_from_terminated_parent_raises():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")
    runtime.terminate(parent_id, reason=b"done")
    runtime.step(parent_id)  # reduce ACTOR_TERMINATED

    with pytest.raises(ActorTerminatedError):
        runtime.delegate(parent_id, child_task=b"too-late")


# ---------------------------------------------------------------------------
# 8. Unknown parent -> ActorNotFoundError
# ---------------------------------------------------------------------------
def test_delegate_unknown_parent_raises_not_found():
    runtime = make_runtime()

    with pytest.raises(ActorNotFoundError):
        runtime.delegate("no-such-parent", child_task=b"child-task")


# ---------------------------------------------------------------------------
# 9. Replay parity untuk parent maupun child setelah delegasi
# ---------------------------------------------------------------------------
def test_replay_parity_for_parent_and_child_after_delegation():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent-genesis")
    runtime.ingest(raw=b"noise-1", source="test", actor_id=parent_id)
    runtime.step(parent_id)

    child_id = runtime.delegate(parent_id, child_task=b"child-task")
    runtime.step(parent_id)  # reduce DELEGATION_ISSUED di parent

    # -- parent --
    parent_events, parent_state = runtime.replay(parent_id)
    assert parent_state == runtime._states[parent_id]
    assert [e.type for e in parent_events] == [
        "Observation",  # genesis
        "Observation",  # noise-1
        "DELEGATION_ISSUED",
    ]
    # replay parent TIDAK PERNAH memuat Event milik child.
    assert all(e.causal_scope_id == parent_id for e in parent_events)

    # -- child --
    child_events, child_state = runtime.replay(child_id)
    assert child_state == runtime._states[child_id]
    assert [e.type for e in child_events] == ["Observation"]  # genesis child saja
    # replay child TIDAK PERNAH memuat Event milik parent, walau genesis-nya
    # secara causal_refs menunjuk ke parent.
    assert all(e.causal_scope_id == child_id for e in child_events)


# ---------------------------------------------------------------------------
# Sanity tambahan: delegate() tidak punya parameter causal_refs sama sekali
# di signature publiknya -- caller tidak bisa menyusun graph kausal sendiri.
# ---------------------------------------------------------------------------
def test_delegate_signature_has_no_causal_refs_parameter():
    import inspect

    sig = inspect.signature(Runtime.delegate)
    assert "causal_refs" not in sig.parameters


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))