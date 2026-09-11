from __future__ import annotations

import threading
from typing import Iterator, Optional, Protocol

from Core.event import Event, EventID, ScopeID


# ---------------------------------------------------------------------------
# Position -- BUKAN konsep baru, alias murni untuk EventID.
# ---------------------------------------------------------------------------
# spec.md / derivasi menyebut nilai balik append() sebagai "Position".
# Daripada memperkenalkan tipe baru, kita nyatakan eksplisit bahwa Position
# dan EventID adalah satu hal yang sama (posisi = identitas di sini, karena
# EventID sudah berisi (causal_scope_id, seq)).
Position = EventID


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class DanglingReferenceError(Exception):
    """Diangkat saat append() menemukan entri di causal_refs yang tidak
    resolve ke Event manapun yang sudah ter-append -- termasuk entri yang
    menunjuk causal_scope_id lain (Delegation). Realisasi Gap 2."""

    def __init__(self, ref: EventID):
        self.ref = ref
        super().__init__(
            f"Dangling causal_ref: {ref.encode()} tidak pernah ter-append. "
            "Ini pelanggaran Law II (rujukan kausal harus eksplisit dan nyata)."
        )


class EventNotFoundError(Exception):
    """Diangkat oleh get() ketika EventID yang diminta tidak ada di store.
    Berbeda dari DanglingReferenceError: ini kesalahan pemakaian get()
    langsung oleh caller, bukan hasil validasi append()."""

    def __init__(self, event_id: EventID):
        self.event_id = event_id
        super().__init__(f"Event tidak ditemukan: {event_id.encode()}")


class AlreadyAppendedError(Exception):
    """Diangkat ketika append() menerima Event yang sudah punya id
    (event.is_appended is True). EventID HANYA boleh dibentuk oleh
    append() itu sendiri (Gap 1) -- menerima Event yang sudah punya id
    berarti seseorang memalsukan identitas di luar store, atau mencoba
    menambahkan Event yang sama dua kali. Keduanya harus ditolak, bukan
    diam-diam diterima."""

    def __init__(self, event: Event):
        super().__init__(
            f"Event sudah punya id ({event.id.encode() if event.id else None}) "
            "-- append() hanya menerima Event yang belum ter-append. "
            "EventID tidak boleh dibentuk di luar EventStore.append()."
        )


# ---------------------------------------------------------------------------
# EventStore -- abstraksi, tidak terikat storage apa pun
# ---------------------------------------------------------------------------
class EventStore(Protocol):
    def append(self, event: Event) -> Position:
        """
        SATU-SATUNYA tempat yang boleh:
          - membuat EventID (assign seq berikutnya untuk causal_scope_id)
          - memasang id ke Event lewat Event.with_id()
          - memvalidasi seluruh causal_refs (menolak dangling reference)
          - menegakkan append-only (Event yang sudah punya id ditolak)

        Menolak (raise), tidak pernah diam-diam menerima, jika:
          - event.is_appended sudah True             -> AlreadyAppendedError
          - ada ref di event.causal_refs yang belum
            pernah ter-append                         -> DanglingReferenceError
        """
        ...

    def exists(self, event_id: EventID) -> bool:
        """O(1). Dipakai secara internal oleh append() untuk validasi
        causal_refs, dan tersedia publik karena itu satu-satunya cara
        memvalidasi referential integrity tanpa menambah konsep baru."""
        ...

    def get(self, event_id: EventID) -> Event:
        """O(1). Raise EventNotFoundError jika tidak ada."""
        ...

    def read(
        self,
        causal_scope_id: ScopeID,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> list[Event]:
        """Baca rentang [from_seq, to_seq] (inclusive) dari satu scope,
        terurut sesuai seq (Total Order per Scope). to_seq=None berarti
        sampai akhir stream saat ini."""
        ...

    def read_stream(self, causal_scope_id: ScopeID) -> Iterator[Event]:
        """Baca seluruh stream satu scope secara terurut."""
        ...


# ---------------------------------------------------------------------------
# InMemoryEventStore -- implementasi referensi
# ---------------------------------------------------------------------------
class InMemoryEventStore:
    """
    Implementasi referensi EventStore. Menyimpan satu list Event per
    causal_scope_id. seq untuk sebuah scope selalu sama dengan index di
    dalam list-nya sendiri (rapat, monoton naik dari 0) -- inilah yang
    membuat exists()/get() O(1): tidak perlu index terpisah, seq LANGSUNG
    jadi alamat.

    Concurrency: satu lock per causal_scope_id untuk mencegah dua append()
    konkuren pada scope yang sama balapan mengambil seq yang sama. ini
    adalah keputusan IMPLEMENTASI (bukan bagian dari Protocol EventStore
    di atas) -- implementasi storage lain boleh menegakkan atomicity ini
    dengan mekanisme berbeda (transaction, unique constraint, dst).
    """

    def __init__(self) -> None:
        self._streams: dict[ScopeID, list[Event]] = {}
        self._store_lock = threading.Lock()  # melindungi pembuatan lock per-scope
        self._scope_locks: dict[ScopeID, threading.Lock] = {}

    # -- internal helpers -----------------------------------------------

    def _lock_for(self, causal_scope_id: ScopeID) -> threading.Lock:
        with self._store_lock:
            lock = self._scope_locks.get(causal_scope_id)
            if lock is None:
                lock = threading.Lock()
                self._scope_locks[causal_scope_id] = lock
            return lock

    def _stream_for(self, causal_scope_id: ScopeID) -> list[Event]:
        return self._streams.setdefault(causal_scope_id, [])

    # -- public API --------------------------------------------------------

    def append(self, event: Event) -> Position:
        if event.is_appended:
            raise AlreadyAppendedError(event)

        # Referential Integrity (Gap 2). Untuk genesis dengan causal_refs
        # kosong ini adalah no-op (list kosong, tidak ada yang divalidasi)
        # -- sama persis dengan yang dinyatakan v1.0 §Gap2 poin 1, hanya
        # di sini tidak perlu di-special-case terpisah karena perilakunya
        # sudah identik secara struktural.
        for ref in event.causal_refs:
            if not self.exists(ref):
                raise DanglingReferenceError(ref)

        with self._lock_for(event.causal_scope_id):
            stream = self._stream_for(event.causal_scope_id)
            next_seq = len(stream)  # Total Order per Scope: seq == posisi
            event_id = EventID(causal_scope_id=event.causal_scope_id, seq=next_seq)
            appended_event = event.with_id(event_id)
            stream.append(appended_event)
            return appended_event.id  # Position == EventID

    def exists(self, event_id: EventID) -> bool:
        stream = self._streams.get(event_id.causal_scope_id)
        if stream is None:
            return False
        return 0 <= event_id.seq < len(stream)

    def get(self, event_id: EventID) -> Event:
        if not self.exists(event_id):
            raise EventNotFoundError(event_id)
        return self._streams[event_id.causal_scope_id][event_id.seq]

    def read(
        self,
        causal_scope_id: ScopeID,
        from_seq: int = 0,
        to_seq: Optional[int] = None,
    ) -> list[Event]:
        stream = self._streams.get(causal_scope_id, [])
        end = len(stream) if to_seq is None else min(to_seq + 1, len(stream))
        start = max(from_seq, 0)
        if start >= end:
            return []
        return list(stream[start:end])

    def read_stream(self, causal_scope_id: ScopeID) -> Iterator[Event]:
        # snapshot list di awal supaya append() setelahnya (di scope yang
        # sama, dari thread lain) tidak mengubah iterasi yang sedang
        # berjalan -- append-only tetap dijaga (kita tidak pernah mutasi
        # elemen), ini murni soal konsistensi snapshot pembacaan.
        stream = list(self._streams.get(causal_scope_id, []))
        return iter(stream)

    def forget(self, causal_scope_id: ScopeID) -> None:
        """Drop this scope's stream and lock entirely (additive retention
        hook, not part of the EventStore Protocol -- callers must check
        for it via hasattr/getattr, see Runtime.archive_actor()).

        After this call, exists()/get()/read()/read_stream() for
        causal_scope_id behave exactly as if genesis never happened.
        Only safe to call for a scope nothing will ever reference again.
        """
        with self._store_lock:
            self._streams.pop(causal_scope_id, None)
            self._scope_locks.pop(causal_scope_id, None)