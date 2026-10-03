"""
Stage 7 proof suite -- cancel().

Cakupan (disetujui eksplisit di sesi ini):
  1. cancel() append TEPAT SATU CANCELLATION_REQUESTED ke actor_id sendiri.
  2. depth=0 -> hanya actor asal, TIDAK ada cascade ke child.
  3. depth=1 -> cascade ke child langsung, TIDAK sampai cucu.
  4. depth=2 -> cascade sampai cucu.
  5. DEFERRED reduction: _states/_cursors TIDAK berubah sampai step()
     memproses CANCELLATION_REQUESTED masing-masing actor.
  6. Root TERMINATED -> ActorTerminatedError, TIDAK ada Event ter-append.
  7. Unknown root -> ActorNotFoundError.
  8. depth negatif -> ValueError.
  9. Actor TERMINATED yang ditemukan SELAMA cascade (bukan root) -> di-skip
     (tidak dapat CANCELLATION_REQUESTED kedua), TAPI cascade tetap lanjut
     ke children-nya. STATUS: proof resmi terhadap Design Freedom yang
     sudah DIKUNCI (bukan lagi hipotesis) -- diaudit eksplisit terhadap
     derivation.md/spec.md/specification-v1_0.md/implementation-layer-
     audit.md dan terbukti tidak ada invariant yang memaksa propagasi
     ataupun cutoff saat node perantara TERMINATED. Keputusan proyek:
     skip-but-continue (Opsi 1) -- traversal mengikuti struktur Delegation
     (_children), bukan lifecycle Actor perantara.
  10. Payload berisi origin_actor_id + depth_remaining yang benar per level.
  11. Replay parity setelah cancel() + step() di setiap actor yang terkena.
  12. _children hanya diisi oleh delegate(), cancel() tidak pernah menulis
      ke dalamnya.
"""
from __future__ import annotations

import json

import pytest

from Core.event_store import InMemoryEventStore
from Core.gateaway import DefaultGateway
from Core.reducer_shell import ReducerShell, State
from Core.runtime import ActorNotFoundError, ActorTerminatedError, Runtime, StepResult


# ---------------------------------------------------------------------------
# Fixtures -- identik pola dengan test_stage6_delegate.py
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


def _payload(event) -> dict:
    return json.loads(event.payload.decode("utf-8"))


# ---------------------------------------------------------------------------
# 1. cancel() append TEPAT SATU CANCELLATION_REQUESTED ke actor_id sendiri
# ---------------------------------------------------------------------------
def test_cancel_appends_exactly_one_cancellation_requested_to_root():
    runtime = make_runtime()
    actor_id = runtime.create_actor(task=b"genesis")

    runtime.cancel(actor_id, depth=0)

    stream = list(runtime._event_store.read_stream(actor_id))
    cancels = [e for e in stream if e.type == "CANCELLATION_REQUESTED"]
    assert len(cancels) == 1
    assert cancels[0].causal_refs == [stream[0].id]  # tail sebelum cancel == genesis


# ---------------------------------------------------------------------------
# 2. depth=0 -> tidak ada cascade ke child
# ---------------------------------------------------------------------------
def test_depth_zero_does_not_cascade_to_children():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")

    runtime.cancel(parent_id, depth=0)

    child_stream = list(runtime._event_store.read_stream(child_id))
    assert all(e.type != "CANCELLATION_REQUESTED" for e in child_stream)


# ---------------------------------------------------------------------------
# 3. depth=1 -> cascade ke child langsung, tidak sampai cucu
# ---------------------------------------------------------------------------
def test_depth_one_cascades_to_direct_child_only():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")
    grandchild_id = runtime.delegate(child_id, child_task=b"grandchild-task")

    runtime.cancel(parent_id, depth=1)

    parent_stream = list(runtime._event_store.read_stream(parent_id))
    child_stream = list(runtime._event_store.read_stream(child_id))
    grandchild_stream = list(runtime._event_store.read_stream(grandchild_id))

    assert any(e.type == "CANCELLATION_REQUESTED" for e in parent_stream)
    assert any(e.type == "CANCELLATION_REQUESTED" for e in child_stream)
    assert all(e.type != "CANCELLATION_REQUESTED" for e in grandchild_stream)


# ---------------------------------------------------------------------------
# 4. depth=2 -> cascade sampai cucu
# ---------------------------------------------------------------------------
def test_depth_two_cascades_to_grandchild():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")
    grandchild_id = runtime.delegate(child_id, child_task=b"grandchild-task")

    runtime.cancel(parent_id, depth=2)

    for actor_id in (parent_id, child_id, grandchild_id):
        stream = list(runtime._event_store.read_stream(actor_id))
        assert any(e.type == "CANCELLATION_REQUESTED" for e in stream), actor_id


# ---------------------------------------------------------------------------
# 5. DEFERRED reduction -- _states/_cursors tidak berubah sampai step()
# ---------------------------------------------------------------------------
def test_cancel_does_not_mutate_bookkeeping_until_step():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")
    runtime.step(parent_id)  # reduce DELEGATION_ISSUED dulu, supaya bersih

    parent_cursor_before = runtime._cursors[parent_id]
    parent_state_before = runtime._states[parent_id]
    child_cursor_before = runtime._cursors[child_id]
    child_state_before = runtime._states[child_id]

    runtime.cancel(parent_id, depth=1)

    assert runtime._cursors[parent_id] == parent_cursor_before
    assert runtime._states[parent_id] == parent_state_before
    assert runtime._cursors[child_id] == child_cursor_before
    assert runtime._states[child_id] == child_state_before

    # setelah step() masing-masing: baru maju.
    runtime.step(parent_id)
    runtime.step(child_id)
    assert runtime._cursors[parent_id] == parent_cursor_before + 1
    assert runtime._cursors[child_id] == child_cursor_before + 1
    assert runtime._states[parent_id].value[-1] == "CANCELLATION_REQUESTED"
    assert runtime._states[child_id].value[-1] == "CANCELLATION_REQUESTED"


# ---------------------------------------------------------------------------
# 6. Root TERMINATED -> ActorTerminatedError, tidak ada Event ter-append
# ---------------------------------------------------------------------------
def test_cancel_on_terminated_root_raises_and_appends_nothing():
    runtime = make_runtime()
    actor_id = runtime.create_actor(task=b"genesis")
    runtime.terminate(actor_id, reason=b"done")
    runtime.step(actor_id)

    stream_before = list(runtime._event_store.read_stream(actor_id))

    with pytest.raises(ActorTerminatedError):
        runtime.cancel(actor_id, depth=0)

    stream_after = list(runtime._event_store.read_stream(actor_id))
    assert len(stream_after) == len(stream_before)


# ---------------------------------------------------------------------------
# 7. Unknown root -> ActorNotFoundError
# ---------------------------------------------------------------------------
def test_cancel_unknown_actor_raises_not_found():
    runtime = make_runtime()

    with pytest.raises(ActorNotFoundError):
        runtime.cancel("no-such-actor", depth=0)


# ---------------------------------------------------------------------------
# 8. depth negatif -> ValueError
# ---------------------------------------------------------------------------
def test_cancel_negative_depth_raises_value_error():
    runtime = make_runtime()
    actor_id = runtime.create_actor(task=b"genesis")

    with pytest.raises(ValueError):
        runtime.cancel(actor_id, depth=-1)


# ---------------------------------------------------------------------------
# 9. PROOF terhadap Design Freedom yang DIKUNCI (Opsi 1 -- skip-but-continue):
#    Actor TERMINATED di tengah cascade tidak dapat CANCELLATION_REQUESTED
#    kedua, tapi cascade tetap diteruskan ke children-nya. Traversal
#    memakai struktur Delegation (_children), bukan lifecycle Actor
#    perantara. Bukan derivasi dari Law I-III -- keputusan desain proyek
#    yang disetujui eksplisit setelah audit membuktikan tidak ada
#    invariant yang memaksa salah satu arah.
#
#    Topologi:
#        A
#        └── B (TERMINATED)
#             └── C
#    cancel(A, depth=2) -> A: CANCELLATION_REQUESTED,
#                           B: tidak ada Event baru,
#                           C: CANCELLATION_REQUESTED
# ---------------------------------------------------------------------------
def test_terminated_actor_mid_cascade_is_skipped_but_cascade_continues():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")
    grandchild_id = runtime.delegate(child_id, child_task=b"grandchild-task")

    # child sudah TERMINATED lebih dulu, lewat jalur lain (bukan cancel()).
    runtime.step(parent_id)  # reduce DELEGATION_ISSUED parent->child dulu
    runtime.terminate(child_id, reason=b"already-done")
    runtime.step(child_id)  # reduce ACTOR_TERMINATED

    child_len_before = len(list(runtime._event_store.read_stream(child_id)))

    runtime.cancel(parent_id, depth=2)

    child_stream_after = list(runtime._event_store.read_stream(child_id))
    # child TIDAK dapat CANCELLATION_REQUESTED kedua (sudah terminated).
    assert len(child_stream_after) == child_len_before
    assert all(e.type != "CANCELLATION_REQUESTED" for e in child_stream_after)

    # tapi grandchild (masih hidup) TETAP kena cascade -- traversal
    # mengikuti struktur Delegation, bukan lifecycle B.
    grandchild_stream = list(runtime._event_store.read_stream(grandchild_id))
    assert any(e.type == "CANCELLATION_REQUESTED" for e in grandchild_stream)


# ---------------------------------------------------------------------------
# 10. Payload berisi origin_actor_id + depth_remaining yang benar per level
# ---------------------------------------------------------------------------
def test_cancellation_payload_carries_origin_and_depth_remaining():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")

    runtime.cancel(parent_id, depth=1)

    [parent_cancel] = [
        e for e in runtime._event_store.read_stream(parent_id)
        if e.type == "CANCELLATION_REQUESTED"
    ]
    [child_cancel] = [
        e for e in runtime._event_store.read_stream(child_id)
        if e.type == "CANCELLATION_REQUESTED"
    ]

    assert _payload(parent_cancel) == {
        "origin_actor_id": parent_id,
        "depth_remaining": 1,
    }
    assert _payload(child_cancel) == {
        "origin_actor_id": parent_id,
        "depth_remaining": 0,
    }


# ---------------------------------------------------------------------------
# 11. Replay parity setelah cancel() + step() di setiap actor yang terkena
# ---------------------------------------------------------------------------
def test_replay_parity_after_cancel_and_step():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")
    runtime.step(parent_id)  # reduce DELEGATION_ISSUED

    runtime.cancel(parent_id, depth=1)
    runtime.step(parent_id)
    runtime.step(child_id)

    parent_events, parent_state = runtime.replay(parent_id)
    assert parent_state == runtime._states[parent_id]
    assert [e.type for e in parent_events] == [
        "Observation",
        "DELEGATION_ISSUED",
        "CANCELLATION_REQUESTED",
    ]

    child_events, child_state = runtime.replay(child_id)
    assert child_state == runtime._states[child_id]
    assert [e.type for e in child_events] == [
        "Observation",
        "CANCELLATION_REQUESTED",
    ]


# ---------------------------------------------------------------------------
# 12. _children hanya diisi oleh delegate(); cancel() tidak menulisnya
# ---------------------------------------------------------------------------
def test_children_bookkeeping_only_written_by_delegate_not_by_cancel():
    runtime = make_runtime()
    parent_id = runtime.create_actor(task=b"parent")
    child_id = runtime.delegate(parent_id, child_task=b"child-task")

    assert runtime._children == {parent_id: [child_id]}

    children_before = dict(runtime._children)
    runtime.cancel(parent_id, depth=1)
    assert runtime._children == children_before


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))