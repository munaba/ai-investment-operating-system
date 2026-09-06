"""
Stage 5 proof suite -- suspend() / resume().

Cakupan (disetujui eksplisit di sesi ini):
  1. suspend() mengembalikan State ter-commit yang sama persis, tanpa mutasi.
  2. suspend() tidak append Event apa pun.
  3. suspend() tidak mengubah bookkeeping Runtime (_states/_cursors).
  4. resume() dengan reducer_version SAMA -> restore langsung dari Snapshot.
  5. resume() dengan reducer_version BEDA -> rekonstruksi HANYA lewat replay().
  6. replay() benar-benar dipanggil pada path mismatch (spy).
  7. reducer_version setelah resume() == reducer_version yang sedang di-bind.
  8. suspend()/resume() pada Actor TERMINATED -> ActorTerminatedError.

  Tambahan: atomicity -- tidak ada bookkeeping yang teramati "separuh
  tertulis" kalau replay() gagal di tengah jalan pada path mismatch.

Skenario dibatasi pada satu Runtime instance yang sama (Blocker 2 = (a)),
sesuai keputusan yang disetujui -- tidak ada test cross-process resume di
sini, itu sengaja di luar scope Stage 5.
"""
from __future__ import annotations

import copy

import pytest

from Core.event import EventType
from Core.event_store import InMemoryEventStore
from Core.gateaway import DefaultGateway
from Core.reducer_shell import ReducerShell, State
from Core.runtime import ActorTerminatedError, ActorNotFoundError, Runtime


# ---------------------------------------------------------------------------
# Fixtures -- fake Reducer Logic / Sandbox / Approval, minimal, domain-blind
# ---------------------------------------------------------------------------
class _ListAppendReducerLogic:
    """Reducer logic paling sederhana yang mungkin: `value` adalah list
    berisi `event.type` untuk setiap Event yang direduce. Cukup untuk
    membuktikan replay parity tanpa perlu domain apa pun."""

    def __init__(self, version: str) -> None:
        self.version = version

    def reduce(self, state: State, event) -> list:
        prior = list(state.value) if state.value is not None else []
        prior.append(event.type)
        return prior


class _NullSandbox:
    def execute(self, intent_event) -> bytes:  # pragma: no cover - tidak dipakai test ini
        return b"unused"


class _AlwaysApprovedApproval:
    version = "approval-v1"

    def check(self, event):  # pragma: no cover - tidak dipakai test ini
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


def make_actor_with_events(runtime: Runtime, n_observations: int = 2) -> str:
    """Buat satu Actor, lalu ingest() + step() beberapa Observation supaya
    ada Trajectory non-trivial untuk direduce/di-replay."""
    actor_id = runtime.create_actor(task=b"genesis-task")
    for i in range(n_observations):
        runtime.ingest(raw=f"obs-{i}".encode(), source="test", actor_id=actor_id)
        runtime.step(actor_id)
    return actor_id


# ---------------------------------------------------------------------------
# 1 & 3. suspend() -- tidak memutasi Runtime, mengembalikan State yang sama
# ---------------------------------------------------------------------------
def test_suspend_returns_current_state_without_mutation():
    runtime = make_runtime()
    actor_id = make_actor_with_events(runtime, n_observations=2)

    states_before = copy.copy(runtime._states)
    cursors_before = copy.copy(runtime._cursors)

    snapshot = runtime.suspend(actor_id)

    # (1) Snapshot == State ter-commit yang sudah ada di bookkeeping.
    assert snapshot == runtime._states[actor_id]
    # genesis (via DefaultGateway) juga bertipe Observation, jadi
    # n_observations=2 ingest+step menghasilkan 3 entri total (genesis + 2).
    assert snapshot.value == ["Observation", "Observation", "Observation"]
    assert snapshot.reducer_version == "reducer-v1"

    # (3) bookkeeping benar-benar tidak berubah (identity dict tetap sama isi).
    assert runtime._states == states_before
    assert runtime._cursors == cursors_before


# ---------------------------------------------------------------------------
# 2. suspend() tidak append Event apa pun
# ---------------------------------------------------------------------------
def test_suspend_appends_no_events():
    runtime = make_runtime()
    actor_id = make_actor_with_events(runtime, n_observations=2)

    stream_before = list(runtime._event_store.read_stream(actor_id))
    runtime.suspend(actor_id)
    stream_after = list(runtime._event_store.read_stream(actor_id))

    assert len(stream_after) == len(stream_before)
    assert [e.id for e in stream_after] == [e.id for e in stream_before]


# ---------------------------------------------------------------------------
# 4. resume() dengan reducer_version SAMA -> restore langsung
# ---------------------------------------------------------------------------
def test_resume_matching_version_restores_snapshot_directly(monkeypatch):
    runtime = make_runtime(reducer_version="reducer-v1")
    actor_id = make_actor_with_events(runtime, n_observations=2)
    snapshot = runtime.suspend(actor_id)

    replay_calls = []
    original_replay = runtime.replay

    def spying_replay(*args, **kwargs):
        replay_calls.append((args, kwargs))
        return original_replay(*args, **kwargs)

    monkeypatch.setattr(runtime, "replay", spying_replay)

    cursor_before = runtime._cursors[actor_id]
    returned_id = runtime.resume(actor_id, snapshot)

    assert returned_id == actor_id
    assert runtime._states[actor_id] == snapshot
    # cursor tidak disentuh pada path ini (Blocker 2: skenario (a) --
    # cursor sudah benar sejak sebelum suspend(), tidak pernah hilang).
    assert runtime._cursors[actor_id] == cursor_before
    # (6, negative check) replay() TIDAK dipanggil sama sekali pada path ini.
    assert replay_calls == []


# ---------------------------------------------------------------------------
# 5 & 6. resume() dengan reducer_version BEDA -> replay() dipanggil, satu-
# satunya mekanisme rekonstruksi.
# ---------------------------------------------------------------------------
def test_resume_mismatched_version_uses_replay_exclusively(monkeypatch):
    runtime = make_runtime(reducer_version="reducer-v1")
    actor_id = make_actor_with_events(runtime, n_observations=3)
    snapshot = runtime.suspend(actor_id)  # reducer_version="reducer-v1"

    # Simulasikan reducer yang sudah di-upgrade di Runtime yang sama:
    # snapshot lama sekarang punya reducer_version berbeda dari yang
    # sedang di-bind saat ini.
    upgraded_logic = _ListAppendReducerLogic("reducer-v2")
    runtime._reducer = ReducerShell(upgraded_logic)

    replay_calls = []
    original_replay = runtime.replay

    def spying_replay(*args, **kwargs):
        replay_calls.append((args, kwargs))
        return original_replay(*args, **kwargs)

    monkeypatch.setattr(runtime, "replay", spying_replay)

    returned_id = runtime.resume(actor_id, snapshot)

    assert returned_id == actor_id
    # (6) replay() benar-benar dipanggil, tepat sekali, untuk actor_id ini.
    assert len(replay_calls) == 1
    assert replay_calls[0][0][0] == actor_id

    # (5) hasil akhir == hasil replay() langsung dari genesis (bukan
    # dibangun dari isi Snapshot lama yang reducer_version-nya sudah usang).
    _, direct_replay_state = runtime.replay(actor_id)
    assert runtime._states[actor_id] == direct_replay_state
    # genesis + 3 ingest+step = 4 entri Observation total.
    assert runtime._states[actor_id].value == [
        "Observation", "Observation", "Observation", "Observation",
    ]

    # bookkeeping (cursor) ikut dipulihkan konsisten dengan replay penuh.
    expected_cursor = list(runtime._event_store.read_stream(actor_id))[-1].id.seq
    assert runtime._cursors[actor_id] == expected_cursor


# ---------------------------------------------------------------------------
# 7. reducer_version setelah resume() == reducer_version yang sedang di-bind
# ---------------------------------------------------------------------------
def test_reducer_version_after_resume_matches_bound_reducer():
    runtime = make_runtime(reducer_version="reducer-v1")
    actor_id = make_actor_with_events(runtime, n_observations=1)
    snapshot = runtime.suspend(actor_id)

    runtime.resume(actor_id, snapshot)
    assert runtime._states[actor_id].reducer_version == runtime._reducer.version

    # juga pada path mismatch:
    upgraded_logic = _ListAppendReducerLogic("reducer-v2")
    runtime._reducer = ReducerShell(upgraded_logic)
    runtime.resume(actor_id, snapshot)
    assert runtime._states[actor_id].reducer_version == "reducer-v2"
    assert runtime._states[actor_id].reducer_version == runtime._reducer.version


# ---------------------------------------------------------------------------
# 8. suspend()/resume() pada Actor TERMINATED -> ActorTerminatedError
# ---------------------------------------------------------------------------
def test_suspend_on_terminated_actor_raises():
    runtime = make_runtime()
    actor_id = make_actor_with_events(runtime, n_observations=1)
    runtime.terminate(actor_id, reason=b"done")
    runtime.step(actor_id)  # reduce ACTOR_TERMINATED, actor sekarang benar2 mati

    with pytest.raises(ActorTerminatedError):
        runtime.suspend(actor_id)


def test_resume_on_terminated_actor_raises():
    runtime = make_runtime()
    actor_id = make_actor_with_events(runtime, n_observations=1)
    snapshot = runtime.suspend(actor_id)  # ambil snapshot SEBELUM terminate

    runtime.terminate(actor_id, reason=b"done")
    runtime.step(actor_id)

    with pytest.raises(ActorTerminatedError):
        runtime.resume(actor_id, snapshot)


# ---------------------------------------------------------------------------
# suspend()/resume() pada actor yang belum pernah genesis
# ---------------------------------------------------------------------------
def test_suspend_and_resume_on_unknown_actor_raises_not_found():
    runtime = make_runtime()
    fake_snapshot = State.empty("reducer-v1")

    with pytest.raises(ActorNotFoundError):
        runtime.suspend("no-such-actor")

    with pytest.raises(ActorNotFoundError):
        runtime.resume("no-such-actor", fake_snapshot)


# ---------------------------------------------------------------------------
# Atomicity -- kalau replay() gagal di tengah jalan pada path mismatch,
# bookkeeping tidak boleh teramati "separuh tertulis".
# ---------------------------------------------------------------------------
def test_resume_mismatch_path_atomic_on_replay_failure(monkeypatch):
    runtime = make_runtime(reducer_version="reducer-v1")
    actor_id = make_actor_with_events(runtime, n_observations=2)
    snapshot = runtime.suspend(actor_id)

    upgraded_logic = _ListAppendReducerLogic("reducer-v2")
    runtime._reducer = ReducerShell(upgraded_logic)

    states_before = copy.copy(runtime._states)
    cursors_before = copy.copy(runtime._cursors)

    def failing_replay(*args, **kwargs):
        raise RuntimeError("simulated replay failure")

    monkeypatch.setattr(runtime, "replay", failing_replay)

    with pytest.raises(RuntimeError):
        runtime.resume(actor_id, snapshot)

    # tidak ada tulisan parsial: _states/_cursors identik seperti sebelum
    # resume() dipanggil sama sekali.
    assert runtime._states == states_before
    assert runtime._cursors == cursors_before


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))