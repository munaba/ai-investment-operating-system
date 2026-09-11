from __future__ import annotations

import functools
import json
import uuid
from dataclasses import replace as _dataclass_replace
from enum import Enum
from typing import Optional, Protocol

from Core.event import Event, EventType, ScopeID
from Core.event_store import EventStore, Position
from Core.gateaway import Gateway
from Core.reducer_shell import ReducerShell, State


# ---------------------------------------------------------------------------
# Public type aliases -- bukan tipe baru, hanya nama yang sudah disepakati
# di desain publik API.
# ---------------------------------------------------------------------------
ActorID = ScopeID
"""Actor diidentifikasi oleh causal_scope_id miliknya sendiri (derivasi §2:
Actor = Identity Boundary yang individuating, 1:1 terhadap genesis). Tidak
ada identitas terpisah untuk Actor di luar scope Event-nya."""

Snapshot = State
"""Checkpoint == Snapshot == Projection dari State (sudah closed di draft,
dipakai literal oleh Gap 3). Bukan skema terpisah."""


# ---------------------------------------------------------------------------
# StepResult -- nilai balik step(), bagian dari Public API yang sudah final.
# ---------------------------------------------------------------------------
class StepResult(Enum):
    CONTINUE = "CONTINUE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# ApprovalOutcome -- nilai balik ApprovalPort.check(). Enum tertutup (BUKAN
# EventType) karena ini kontrak Semantic Boundary yang forced bentuknya oleh
# Runtime Spec v1.0 Gap 4: "Approved | Denied | Pending", bukan kosakata
# domain bebas seperti Event.type.
# ---------------------------------------------------------------------------
class ApprovalOutcome(Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PENDING = "PENDING"


# ---------------------------------------------------------------------------
# ApprovalPort -- Port lokal (Semantic Boundary), TIDAK diimpor dari
# implementations/. Signature final ikut v1.0 Gap 4 (`check`, bukan
# `evaluate` -- derivasi awal memakai `evaluate`, tapi v1.0 CLOSED adalah
# field-level authority per instruksi, dan pseudocode Gap 4 memakai `check`
# secara eksplisit; nama ini yang dipakai di kode).
# ---------------------------------------------------------------------------
class ApprovalPort(Protocol):
    version: str  # wajib, opaque -- policy_version yang ikut tercatat di Decision payload

    def check(self, event: Event) -> ApprovalOutcome:
        """
        Dipanggil Runtime HANYA untuk Event bertipe INTENT, SEBELUM
        Sandbox.execute() boleh dipanggil (Gap 4, non-negotiable).
        Runtime memegang nilai balik ini sebagai enum -- tidak pernah
        membuka/menafsirkan alasan di baliknya (opaque, sama seperti
        Event.payload).
        """
        ...


# ---------------------------------------------------------------------------
# SandboxPort -- Port lokal (Identity Boundary sisi eksekusi efek).
# execute() menerima Event INTENT (bukan payload mentah yang sudah dibuka
# Runtime -- Sandbox sendiri yang domain-aware di sisi Implementation lewat
# ReasonerPort/DispatcherPort di baliknya) dan mengembalikan bytes opaque
# untuk dibungkus Runtime menjadi payload EFFECT_COMPLETED. Runtime tidak
# pernah membuka bytes ini.
# ---------------------------------------------------------------------------
class SandboxPort(Protocol):
    def execute(self, intent_event: Event) -> bytes:
        """
        Protokol dua-fase (spec.md §4/§13): Runtime tidak menjamin exactly-
        once atas *efek dunia nyata* -- hanya atas pencatatan Event-nya.
        Kalau proses crash tepat setelah execute() nyata terjadi tapi
        sebelum EFFECT_COMPLETED sempat di-append, itu batas fisik yang
        sudah dinyatakan eksplisit di spec, bukan sesuatu yang coba
        ditutup di sini.
        """
        ...


# ---------------------------------------------------------------------------
# Exceptions -- lokal ke Runtime, mengikuti pola exception lokal per-modul
# yang sudah dipakai core/event_store.py dan core/gateaway.py (bukan
# AgentError -- itu hierarki modul domain lain di luar /core).
# ---------------------------------------------------------------------------
class ActorNotFoundError(Exception):
    def __init__(self, actor_id: ActorID):
        self.actor_id = actor_id
        super().__init__(f"Actor tidak ditemukan / belum punya genesis Event: {actor_id!r}")


class ActorTerminatedError(Exception):
    """Diangkat ketika operasi lanjutan (step/resume/cancel/delegate)
    dipanggil pada Actor yang is_alive()-nya sudah False. Invariant:
    'Actor TERMINATED menolak operasi lanjutan'."""

    def __init__(self, actor_id: ActorID):
        self.actor_id = actor_id
        super().__init__(f"Actor sudah TERMINATED, menolak operasi lanjutan: {actor_id!r}")


class NoEventToProcessError(Exception):
    """Diangkat oleh step() ketika tidak ada Event di posisi cursor + 1.

    Keputusan eksplisit (Open Question 1, disetujui): step() TIDAK
    diam-diam menjadi no-op ketika tidak ada trigger Event. Kontraknya
    tetap: satu panggilan step() memproses TEPAT SATU trigger Event
    (plus konsekuensi mekanisnya) -- atau gagal. Polling/menunggu
    Event baru adalah tanggung jawab pemanggil (Implementation layer),
    bukan Runtime -- Runtime tidak punya loop tersembunyi di sini."""

    def __init__(self, actor_id: ActorID, cursor: int):
        self.actor_id = actor_id
        self.cursor = cursor
        super().__init__(
            f"Tidak ada Event di posisi {cursor + 1} untuk Actor {actor_id!r} "
            f"(cursor saat ini = {cursor}). step() tidak boleh diam-diam "
            "menjadi no-op -- ingest() Event baru dulu sebelum memanggil step() lagi."
        )


class ActorNotTerminatedError(Exception):
    """Raised by archive_actor() when asked to archive an Actor that is
    still alive. Archiving a live Actor would corrupt later step() calls
    (they index self._cursors[actor_id] directly) -- so this refuses
    rather than silently evicting a live Actor's bookkeeping."""

    def __init__(self, actor_id: ActorID):
        self.actor_id = actor_id
        super().__init__(
            f"Actor masih hidup, tidak bisa diarsipkan: {actor_id!r}"
        )


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
class Runtime:
    """
    Infrastructure, domain-blind (Law III). Menjalankan loop atas Actor
    lewat lima dependency yang di-inject sekali saat construction -- tidak
    ada dependency lain yang boleh diimpor selain core.event,
    core.event_store, core.gateaway, core.reducer_shell, dan dua Port lokal
    di atas.

    Struktur internal:
      _cursors : posisi (seq) Event TERAKHIR yang sudah lolos
                 reducer.apply() untuk sebuah Actor. Definisi tunggal ini
                 dipakai oleh SEMUA cabang di step() (Event biasa, INTENT
                 Approved/Denied/Pending) -- tidak ada cabang yang punya
                 arti "maju" berbeda. Event pada posisi `cursor` adalah
                 Event terakhir yang state-nya sudah tercermin di _states.
                 Event pada posisi `cursor + 1` (kalau ada) adalah Event
                 BERIKUTNYA yang akan diambil step().

      _states  : State ter-commit terakhir per Actor, hasil reducer.apply()
                 pada Event di posisi `cursor`. Cache murni -- otoritas
                 tetap Event Store; cache ini bisa selalu dibangun ulang
                 lewat replay().

    Kedua dict ini BUKAN Projection/Boundary baru -- keduanya adalah
    bookkeeping implementasi murni di sisi Runtime, tidak pernah di-
    persist sebagai Event dan tidak pernah jadi sumber kebenaran (Event
    Store tetap satu-satunya sumber kebenaran, Law I).
    """

    def __init__(
        self,
        event_store: EventStore,
        gateway: Gateway,
        reducer: ReducerShell,
        sandbox: SandboxPort,
        approval: ApprovalPort,
    ) -> None:
        self._event_store = event_store
        self._gateway = gateway
        self._reducer = reducer
        self._sandbox = sandbox
        self._approval = approval

        self._cursors: dict[ActorID, int] = {}
        self._states: dict[ActorID, State] = {}

        # _children : parent ActorID -> list[child ActorID], urutan delegasi.
        #
        # Runtime bookkeeping untuk traversal delegation selama Runtime
        # instance hidup. BERBEDA dengan _states dan _cursors, struktur ini
        # TIDAK dapat direkonstruksi dari Event Store menggunakan API saat
        # ini (DELEGATION_ISSUED.payload = child_task verbatim, tidak
        # menyimpan child ActorID; EventStore tidak punya reverse-lookup
        # dari causal_refs), dan sengaja TIDAK dipersist. Ditulis HANYA oleh
        # delegate(), dibaca HANYA oleh cancel() -- bukan source of truth,
        # bukan Projection/Boundary baru.
        #
        # Dukungan cascade cancellation lintas restart Runtime berada di
        # luar cakupan desain saat ini dan merupakan Design Freedom yang
        # ditunda (disetujui eksplisit, paralel dengan Stage 5 Blocker 2
        # untuk suspend()/resume()). Setelah restart, _children kosong dan
        # cascade terhadap delegasi yang dibuat sebelum restart tidak
        # dijamin bekerja -- konsekuensi desain yang disengaja, bukan bug.
        #
        # Design Freedom lain yang DIKUNCI di Stage 7 dan memakai _children
        # ini sebagai mekanismenya: traversal cascade cancel() mengikuti
        # struktur Delegation (_children), BUKAN lifecycle Actor perantara
        # -- Actor TERMINATED di tengah jalur tidak memutus propagasi ke
        # descendant-nya. Ini BUKAN konsekuensi Law I-III; diaudit eksplisit
        # terhadap derivation/spec/audit dan terbukti tidak ada invariant
        # yang memaksa salah satu arah (propagasi vs cutoff) -- keputusan
        # murni proyek, lihat docstring _cancel_recursive() untuk detail.
        self._children: dict[ActorID, list[ActorID]] = {}

    # -- lifecycle (Stage 2) -------------------------------------------

    def create_actor(self, task: bytes) -> ActorID:
        """
        Satu-satunya jalur genesis TANPA causal_refs (selalu []). Caller
        hanya mengirim stimulus mentah -- Runtime yang memanggil
        Gateway.translate() untuk membentuk Event, lalu EventStore.append()
        untuk memberinya identitas (seq == 0 pada scope barunya).

        Sengaja TIDAK menerima causal_refs sebagai parameter: caller tidak
        pernah menyusun graph kausal sendiri (itu kebocoran boundary).
        Genesis dengan causal_refs terisi HANYA lewat delegate() (Stage 5),
        yang membangun causal_refs secara internal, tidak dari argumen
        publik manapun.

        Genesis LANGSUNG di-reduce di sini (bukan menunggu step() pertama)
        supaya definisi cursor -- "posisi Event terakhir yang sudah lolos
        reducer.apply()" -- konsisten sejak Actor lahir, tidak ada jendela
        di mana Actor "ada" tapi state-nya kosong/tidak terdefinisi.
        """
        new_actor_id: ActorID = str(uuid.uuid4())
        # ScopeID pembuatan Actor baru bukan diturunkan dari isi task
        # (itu akan melanggar Gateway docstring: causal_scope_id datang
        # dari CALLER, bukan dari payload) -- uuid4 di sini murni
        # kebutuhan implementasi Python untuk identitas unik, dipaksa
        # oleh keharusan "caller memberi scope", bukan abstraksi baru.
        draft_event = self._gateway.translate(task, source="create_actor", causal_scope_id=new_actor_id)
        position = self._event_store.append(draft_event)
        genesis_event = self._event_store.get(position)  # ambil versi kanonik (id terisi)

        committed_state = self._reducer.apply(State.empty(), genesis_event)
        self._states[new_actor_id] = committed_state
        self._cursors[new_actor_id] = position.seq  # == 0

        return new_actor_id

    def is_alive(self, actor_id: ActorID) -> bool:
        """
        Predikat struktural murni atas trajectory -- BUKAN flag internal.
        Tidak ada dual source of truth: satu-satunya otoritas adalah
        keberadaan Event ACTOR_TERMINATED di stream, dibaca langsung dari
        Event Store setiap kali dipanggil.
        """
        stream = list(self._event_store.read_stream(actor_id))
        if not stream:
            return False
        return not self._has_terminal_event(stream)

    def terminate(self, actor_id: ActorID, reason: bytes) -> Position:
        """
        Sama seperti operasi Runtime lain: reason (bytes) -> translate()
        -> reklasifikasi type jadi ACTOR_TERMINATED -> append(). Runtime
        TIDAK mengubah status Actor secara langsung -- status berubah
        semata-mata karena Event ini sekarang ada di stream (simetris
        dengan is_alive()).

        causal_refs diisi menunjuk ke Event TERAKHIR yang sudah nyata
        ter-append di stream (tail, bukan cursor) -- Event ini bukan
        genesis, jadi ia butuh rujukan kausal eksplisit (Law II) ke apa
        yang mendahuluinya secara faktual di log, bukan ke seberapa jauh
        reduksi sudah berjalan.

        Idempotent secara semantik lewat exception, bukan diam-diam
        no-op: dipanggil pada Actor yang sudah TERMINATED -> raise
        ActorTerminatedError, bukan menghasilkan ACTOR_TERMINATED kedua.
        """
        stream = self._stream_or_raise(actor_id)
        if self._has_terminal_event(stream):
            raise ActorTerminatedError(actor_id)

        draft_event = self._gateway.translate(reason, source="terminate", causal_scope_id=actor_id)
        last_event = stream[-1]
        terminal_event = _dataclass_replace(
            draft_event,
            type=EventType.ACTOR_TERMINATED,
            causal_refs=[last_event.id],
        )
        return self._event_store.append(terminal_event)

    def ingest(
        self,
        raw: bytes,
        source: str,
        actor_id: ActorID,
        event_type: str = EventType.OBSERVATION,
    ) -> Position:
        """
        raw -> translate() -> (reklasifikasi type bila perlu) -> append().
        TIDAK memanggil reducer, TIDAK mengubah cursor/state -- satu-
        satunya jalur yang mengubah state tetap step() (Stage 3). Ini
        mencegah dua jalur mutasi state yang harus dijaga tetap sinkron
        secara manual.

        event_type : default EventType.OBSERVATION, sama seperti sebelum
                     parameter ini ada -- DefaultGateway.translate() SELALU
                     menghasilkan OBSERVATION (Gateway CLOSED, tidak boleh
                     diubah). Kalau caller (Implementation layer) butuh
                     Event ini diklasifikasi sebagai INTENT, ia meminta
                     eksplisit lewat argumen ini -- Runtime mereklasifikasi
                     `type` SETELAH translate() kembali, dengan pola yang
                     identik dengan terminate() di atas (_dataclass_replace
                     pada field type, tanpa pernah membuka `raw`/payload
                     untuk memutuskannya). Runtime tetap tidak pernah
                     menafsirkan payload -- keputusan "ini INTENT" datang
                     murni dari argumen caller, bukan dari isi raw.

        Tipe dianotasikan `str`, bukan `EventType`: EventType adalah
        namespace konstanta string (bukan Enum tertutup, lihat event.py),
        jadi nilai run-time-nya selalu str -- anotasi `EventType` di sini
        akan menyesatkan type-checker tanpa menambah jaminan apa pun.
        """
        stream = self._stream_or_raise(actor_id)
        if self._has_terminal_event(stream):
            raise ActorTerminatedError(actor_id)

        event = self._gateway.translate(raw, source=source, causal_scope_id=actor_id)
        if event_type != EventType.OBSERVATION:
            event = _dataclass_replace(event, type=event_type)
        return self._event_store.append(event)

    # -- internal helpers (lifecycle) ------------------------------------

    @staticmethod
    def _has_terminal_event(stream: list[Event]) -> bool:
        return any(e.type == EventType.ACTOR_TERMINATED for e in stream)

    def _stream_or_raise(self, actor_id: ActorID) -> list[Event]:
        stream = list(self._event_store.read_stream(actor_id))
        if not stream:
            raise ActorNotFoundError(actor_id)
        return stream

    # -- internal helpers (step) -----------------------------------------

    def _reduce_and_advance(self, actor_id: ActorID, event: Event) -> State:
        """
        SATU-SATUNYA tempat di Runtime yang boleh: memanggil
        reducer.apply(), menulis _states[actor_id], dan memajukan
        _cursors[actor_id]. Setiap Event yang diproses Runtime -- trigger
        maupun konsekuensi mekanisnya (Decision, EFFECT_COMPLETED) --
        WAJIB lewat sini, tanpa kecuali.

        Ini bukan kenyamanan gaya penulisan -- ini structural guarantee
        untuk replay parity (instruksi eksplisit): karena hanya ada SATU
        titik yang mengubah (_states, _cursors), tidak mungkin ada cabang
        di step() yang lupa memajukan cursor atau lupa mereduce sebuah
        Event yang sudah di-append. Kalau nanti ada cabang baru
        ditambahkan ke step() (Stage 5 dst.) dan cabang itu lupa memanggil
        helper ini, Event tersebut tetap ter-append tapi TIDAK ter-reduce
        -- pelanggaran "setiap Event yang berhasil di-append harus
        direduce tepat satu kali" akan terlihat lewat cursor yang berhenti
        maju, bukan tersembunyi di dalam duplikasi logic reduce() yang
        di-inline berkali-kali.

        event harus sudah appended (event.id terisi) -- dipanggil hanya
        dengan Event kanonik dari EventStore.append()/.get(), tidak pernah
        dengan draft Event.
        """
        state = self._reducer.apply(self._states[actor_id], event)
        self._states[actor_id] = state
        self._cursors[actor_id] = event.id.seq
        return state

    @staticmethod
    def _encode_decision_payload(outcome: ApprovalOutcome, policy_version: str) -> bytes:
        """
        Encoding JSON untuk payload Decision (disetujui sebagai default
        implementasi, bukan bagian forced dari ontology -- payload tetap
        opaque bagi Runtime setelah dibentuk; Runtime tidak pernah
        membacanya kembali untuk keputusan, hanya menulisnya untuk audit,
        lihat Gap 4 §3 catatan Law III).
        """
        return json.dumps(
            {"outcome": outcome.value, "policy_version": policy_version}
        ).encode("utf-8")

    def _is_terminated_as_of(self, actor_id: ActorID, cursor: int) -> bool:
        """
        Apakah Event TERAKHIR yang sudah direduce (posisi `cursor`) adalah
        ACTOR_TERMINATED.

        SENGAJA BEDA dari _has_terminal_event(stream) yang dipakai
        ingest()/terminate(): keduanya memeriksa SELURUH raw stream
        (termasuk Event yang belum direduce) -- benar untuk mereka, karena
        begitu ACTOR_TERMINATED ter-append di scope manapun, tidak boleh
        ada penulisan baru lagi, terlepas dari cursor Runtime.

        step() butuh definisi yang lebih sempit: ia harus TETAP BOLEH
        memproses ACTOR_TERMINATED itu sendiri sebagai trigger Event --
        itu justru caranya ia menjadi TERMINATED (ND-2). Kalau step()
        memakai _has_terminal_event(stream) di sini, ia akan menolak
        ACTOR_TERMINATED SEBELUM sempat mereduce-nya, karena Event itu
        sudah ada di raw stream begitu di-ingest -- kontradiksi terhadap
        instruksi "ACTOR_TERMINATED diperlakukan seperti Event lain:
        di-append, direduce SATU KALI, cursor maju". step() harus menolak
        HANYA ketika Actor SUDAH melewati titik itu di panggilan
        SEBELUMNYA -- yaitu Event pada posisi cursor saat ini (yang sudah
        direduce) adalah ACTOR_TERMINATED.
        """
        [last_reduced] = self._event_store.read(actor_id, from_seq=cursor, to_seq=cursor)
        return last_reduced.type == EventType.ACTOR_TERMINATED

    # -- step loop (Stage 3) --------------------------------------------

    def step(self, actor_id: ActorID) -> StepResult:
        """
        Satu panggilan = satu trigger Event (di posisi cursor + 1) +
        konsekuensi mekanisnya yang lahir SINKRON dalam panggilan yang
        sama (Decision, EFFECT_COMPLETED) -- ND-1. Tidak ada retry Event
        lama (ND-3): kalau tidak ada trigger Event, step() gagal lewat
        NoEventToProcessError (Open Question 1) -- ia tidak menunggu,
        tidak polling, dan tidak diam-diam no-op.

        StepResult yang bisa dikembalikan Stage 3 ini HANYA CONTINUE dan
        TERMINATED (Open Question 2, disetujui) -- SUSPENDED sengaja tidak
        pernah dikonstruksi di sini; ia tetap ada di enum publik untuk
        stage Runtime berikutnya yang belum ditentukan bentuknya.
        """
        self._stream_or_raise(actor_id)  # ActorNotFoundError kalau belum genesis
        cursor = self._cursors[actor_id]
        if self._is_terminated_as_of(actor_id, cursor):
            raise ActorTerminatedError(actor_id)

        trigger_seq = cursor + 1
        candidates = self._event_store.read(actor_id, from_seq=trigger_seq, to_seq=trigger_seq)
        if not candidates:
            raise NoEventToProcessError(actor_id, cursor)
        trigger_event = candidates[0]

        self._reduce_and_advance(actor_id, trigger_event)

        if trigger_event.type == EventType.ACTOR_TERMINATED:
            # Runtime tidak "memutuskan" TERMINATED -- ia melaporkan
            # struktur Event yang baru saja direduce (ND-2). Simetris
            # dengan is_alive(): satu-satunya otoritas adalah keberadaan
            # Event ini di stream, bukan flag internal.
            return StepResult.TERMINATED

        if trigger_event.type == EventType.INTENT:
            outcome = self._approval.check(trigger_event)

            draft_decision = Event(
                causal_scope_id=actor_id,
                type=EventType.DECISION,
                payload=self._encode_decision_payload(outcome, self._approval.version),
                causal_refs=[trigger_event.id],
            )
            decision_position = self._event_store.append(draft_decision)
            canonical_decision = self._event_store.get(decision_position)
            self._reduce_and_advance(actor_id, canonical_decision)

            if outcome == ApprovalOutcome.APPROVED:
                effect_bytes = self._sandbox.execute(trigger_event)

                # "EFFECT_COMPLETED" -- literal string, sengaja BUKAN
                # EventType.EFFECT_COMPLETED (Open Question 3, disetujui):
                # event.py CLOSED, tidak disentuh. EventType sengaja
                # namespace terbuka (bukan Enum tertutup), jadi literal
                # ini sah dipakai Implementation manapun juga -- menjadi
                # konstanta kanonik adalah keputusan cleanup terpisah di
                # masa depan, bukan bagian Stage 3.
                draft_effect = Event(
                    causal_scope_id=actor_id,
                    type="EFFECT_COMPLETED",
                    payload=effect_bytes,
                    causal_refs=[trigger_event.id],  # tetap intent_event, bukan decision_event
                )
                effect_position = self._event_store.append(draft_effect)
                canonical_effect = self._event_store.get(effect_position)
                self._reduce_and_advance(actor_id, canonical_effect)

            # DENIED / PENDING: tidak ada aksi lebih lanjut. Decision
            # sudah ter-append dan ter-reduce di atas; cursor sudah maju.
            # Runtime tidak retry INTENT ini (ND-3) -- panggilan step()
            # berikutnya akan mengambil apa pun yang ada di cursor + 1
            # berikutnya, kalau ada.

        return StepResult.CONTINUE

    def suspend(self, actor_id: ActorID) -> Snapshot:
        """
        Checkpoint di dalam Runtime instance yang sama (Stage 5, Blocker 2
        disetujui sebagai skenario (a) -- BUKAN cross-process persistence).

        Snapshot == State ter-commit terakhir (`self._states[actor_id]`),
        tidak ada wrapper/skema baru. Ini murni PEMBACAAN:

          - TIDAK append Event apa pun (tidak ada ACTOR_SUSPENDED atau
            sejenisnya -- tidak diminta, tidak ada di ontology).
          - TIDAK menulis ke `_states`/`_cursors` -- struktural sama seperti
            replay(), method ini tidak pernah menjadi sisi kiri assignment
            ke kedua dict itu di badan method ini.

        Actor TERMINATED ditolak (ActorTerminatedError) -- simetris dengan
        ingest()/terminate()/step(): checkpoint dari Actor yang sudah tidak
        punya eksekusi masa depan tidak punya makna operasional (disetujui
        eksplisit).
        """
        stream = self._stream_or_raise(actor_id)  # ActorNotFoundError kalau belum genesis
        if self._has_terminal_event(stream):
            raise ActorTerminatedError(actor_id)

        return self._states[actor_id]

    def resume(self, actor_id: ActorID, snapshot: Snapshot) -> ActorID:
        """
        Dua cabang, persis pseudocode Gap 3 (CLOSED) -- tidak diparafrasekan:

          reducer_version sama   -> restore Snapshot langsung (tidak ada
                                     reduksi kedua, tidak ada penulisan
                                     _cursors -- lihat catatan di bawah).
          reducer_version beda   -> self.replay(actor_id) penuh, SATU-
                                     SATUNYA mekanisme rekonstruksi state
                                     (tidak ada algoritma reduksi kedua).

        Cursor pada cabang "restore langsung": Blocker 2 membatasi Stage 5
        pada skenario (a) -- checkpoint di dalam SATU Runtime instance yang
        sama. Karena suspend() dilarang memutasi bookkeeping (di atas),
        `_cursors[actor_id]` tidak pernah hilang di antara suspend() dan
        resume(); ia sudah benar tanpa disentuh. Snapshot sengaja tidak
        membawa posisi apa pun -- menambahkannya akan melanggar identitas
        Snapshot == State yang closed. (Cross-process resume, yang akan
        butuh posisi eksplisit, sengaja ditahan di luar Stage 5.)

        Actor TERMINATED ditolak sebelum kedua cabang di atas dievaluasi --
        alasan yang sama seperti suspend().

        Atomicity (disetujui): kedua cabang menghitung nilai baru dulu
        (reducer_version check pada cabang pertama tidak pernah gagal
        setelah lolos comparison; replay() pada cabang kedua adalah
        pembacaan murni yang TIDAK menyentuh bookkeeping sama sekali kalau
        ia raise) sebelum menulis ke `_states`/`_cursors` -- tidak ada
        state Runtime yang teramati setengah-tertulis kalau ada exception.
        """
        stream = self._stream_or_raise(actor_id)  # ActorNotFoundError kalau belum genesis
        if self._has_terminal_event(stream):
            raise ActorTerminatedError(actor_id)

        if snapshot.reducer_version == self._reducer.version:
            # Restore langsung -- tidak ada reduksi kedua, tidak ada
            # penulisan _cursors (lihat docstring: skenario (a), cursor
            # sudah benar sejak sebelum suspend()).
            self._states[actor_id] = snapshot
            return actor_id

        # reducer_version berbeda -- Snapshot diabaikan sepenuhnya, state
        # dibangun ulang HANYA lewat replay() (satu-satunya mekanisme
        # rekonstruksi). replay() sendiri pure-read, dihitung penuh dulu
        # sebelum satu pun bookkeeping ditulis (atomicity).
        events, state = self.replay(actor_id)
        new_cursor = events[-1].id.seq  # stream dijamin non-kosong oleh _stream_or_raise di atas

        self._states[actor_id] = state
        self._cursors[actor_id] = new_cursor
        return actor_id

    # -- replay (Stage 4) -------------------------------------------------

    def replay(
        self, actor_id: ActorID, target_seq: Optional[int] = None
    ) -> tuple[list[Event], State]:
        """
        Replay = reduce(reducer.apply, seluruh Event, initial_state) --
        "Prinsip replay" (dokumen instruksi awal), diimplementasikan
        harfiah, bukan diparafrasakan ke algoritma reduksi lain.
        `self._reducer` yang dipakai adalah instance ReducerShell yang
        SAMA dengan yang dipakai step()/create_actor() -- bukan instance
        baru -- supaya replay dan live execution TIDAK MUNGKIN drift atas
        reducer_version (Gap 3) atau atas urutan reduksi (ND-1..4).

        target_seq=None -> replay seluruh trajectory (dari genesis sampai
        Event terakhir yang ter-append). target_seq=N -> replay berhenti
        TEPAT di posisi N inklusif; Event pada seq > N tidak dibaca sama
        sekali (bukan dibaca lalu dibuang -- read() sendiri yang
        membatasi range, lihat EventStore.read()).

        TIDAK memeriksa is_alive()/ACTOR_TERMINATED -- replay adalah
        fungsi baca murni atas Trajectory yang sudah ada, harus bekerja
        sama persis untuk Actor yang masih Running maupun yang sudah
        TERMINATED (justru itu yang harus dibuktikan sama dengan live
        execution, termasuk kasus ACTOR_TERMINATED sebagai trigger Event
        biasa, Stage 3 skenario 5).

        TIDAK PERNAH menulis ke self._states / self._cursors -- replay
        murni membaca dari Event Store dan mereduksi ke variabel lokal.
        Ini bukan sekadar disiplin programmer: replay() secara struktural
        tidak punya akses tulis ke bookkeeping live Runtime di method ini
        sama sekali, sehingga "replay never mutates live state" adalah
        fakta struktural, bukan konvensi yang bisa dilanggar diam-diam.
        """
        stream = self._stream_or_raise(actor_id)  # ActorNotFoundError kalau belum genesis

        if target_seq is None:
            events = stream
        else:
            if target_seq < 0:
                raise ValueError(
                    f"target_seq tidak boleh negatif, dapat {target_seq!r}"
                )
            last_available_seq = stream[-1].id.seq
            if target_seq > last_available_seq:
                raise ValueError(
                    f"target_seq={target_seq} melampaui Event terakhir yang "
                    f"ter-append untuk Actor {actor_id!r} (seq terakhir = "
                    f"{last_available_seq}). replay() tidak mereplay Event "
                    "yang belum pernah nyata ter-append."
                )
            events = self._event_store.read(actor_id, from_seq=0, to_seq=target_seq)

        state = functools.reduce(self._reducer.apply, events, State.empty())
        return events, state

    # -- delegation & cancellation (Stage 5) -------------------------------

    def delegate(self, parent_actor_id: ActorID, child_task: bytes) -> ActorID:
        """
        Satu-satunya jalur genesis DENGAN causal_refs terisi (spec.md §12).
        Dua append(), urutan tetap (disetujui eksplisit, Stage 6):

          1. DELEGATION_ISSUED di scope PARENT.
             - payload = child_task VERBATIM (Runtime tetap payload-blind,
               Law III -- tidak ada transformasi/interpretasi isi, hanya
               dipindahkan apa adanya, sama seperti Gateway memindahkan
               `raw` byte demi byte).
             - causal_refs = [tail_event.id] milik parent -- tail STREAM
               FAKTUAL (bukan cursor), pola identik dengan terminate().
          2. genesis child, causal_refs = [delegation_event.id] (cross-scope,
             menunjuk TEPAT ke DELEGATION_ISSUED yang baru saja di-append,
             bukan ke Event parent manapun yang lain).

        Satu-satunya transformasi yang dilakukan Runtime terhadap kedua
        Event ini adalah metadata (causal_scope_id, causal_refs, type) --
        payload keduanya tetap byte mentah dari child_task, tidak pernah
        dibuka/ditafsirkan.

        DEFERRED reduction (disetujui eksplisit, Stage 6): delegate() TIDAK
        memanggil _reduce_and_advance() untuk DELEGATION_ISSUED. Parent
        HANYA boleh maju lewat step() -- invariant yang sama yang sudah
        dijaga ingest()/terminate() sejak Stage 2/3. Kalau delegate() ikut
        mereduce parent di sini, itu akan jadi jalur kedua yang memajukan
        Actor yang sudah hidup, mengecualikan DELEGATION_ISSUED dari aturan
        "semua evolusi Actor pasca-genesis lewat append -> step() -> reduce
        -> cursor advance" yang berlaku untuk setiap Event lain. Karena itu,
        method ini TIDAK PERNAH menyentuh
        `self._states[parent_actor_id]` / `self._cursors[parent_actor_id]`.
        Parent baru benar-benar berubah saat step(parent_actor_id) mencapai
        DELEGATION_ISSUED di posisi cursor+1 -- Runtime tidak "memutuskan"
        parent sudah mendelegasikan, ia melaporkan struktur Event yang
        sudah ter-append (pola yang sama seperti ND-2 untuk
        ACTOR_TERMINATED).

        Genesis child TETAP langsung direduce (sama seperti create_actor()):
        tidak ada jendela di mana child "ada" tapi state-nya belum
        terdefinisi -- genesis selalu diperlakukan istimewa, terlepas dari
        causal_refs-nya kosong (create_actor()) atau terisi (delegate()).

        Actor TERMINATED ditolak SEBELUM append apa pun -- tidak masuk akal
        mendelegasikan dari Actor yang sudah tidak punya eksekusi masa
        depan (simetris dengan suspend()/resume()/ingest()/terminate()).
        """
        parent_stream = self._stream_or_raise(parent_actor_id)  # ActorNotFoundError kalau belum genesis
        if self._has_terminal_event(parent_stream):
            raise ActorTerminatedError(parent_actor_id)

        # -- 1. DELEGATION_ISSUED di scope parent ---------------------------
        parent_tail = parent_stream[-1]
        draft_delegation = self._gateway.translate(
            child_task, source="delegate", causal_scope_id=parent_actor_id
        )
        draft_delegation = _dataclass_replace(
            draft_delegation,
            type="DELEGATION_ISSUED",  # literal string, sama pola dgn "EFFECT_COMPLETED"
            causal_refs=[parent_tail.id],
        )
        delegation_position = self._event_store.append(draft_delegation)
        delegation_event = self._event_store.get(delegation_position)  # versi kanonik (id terisi)

        # -- 2. genesis child, causal_refs -> TEPAT delegation_event.id -----
        new_child_id: ActorID = str(uuid.uuid4())
        draft_genesis = self._gateway.translate(
            child_task, source="delegate", causal_scope_id=new_child_id
        )
        draft_genesis = _dataclass_replace(
            draft_genesis,
            causal_refs=[delegation_event.id],  # type tetap OBSERVATION (default Gateway)
        )
        genesis_position = self._event_store.append(draft_genesis)
        genesis_event = self._event_store.get(genesis_position)

        committed_state = self._reducer.apply(State.empty(), genesis_event)
        self._states[new_child_id] = committed_state
        self._cursors[new_child_id] = genesis_position.seq  # == 0

        # _children link (Stage 7 prerequisite): bookkeeping murni, TIDAK
        # ter-derive dari Event Store (lihat docstring _children di
        # __init__). Ditulis di sini, satu-satunya tempat yang boleh
        # menulis _children.
        self._children.setdefault(parent_actor_id, []).append(new_child_id)

        return new_child_id

    def cancel(self, actor_id: ActorID, depth: int) -> None:
        """
        Append CANCELLATION_REQUESTED ke actor_id, lalu cascade ke child-nya
        (lewat _children, lihat __init__) sepanjang edge Delegation, sampai
        `depth` hop (disetujui eksplisit):

          depth=0 -> HANYA actor_id sendiri, tidak ada cascade ke child.
          depth=N -> actor_id + child (N-1) + cucu (N-2) + ... -- setiap
                     level Delegation mengurangi depth tepat satu.

        Event type literal "CANCELLATION_REQUESTED" (disetujui eksplisit,
        SCREAMING_SNAKE -- konsisten dengan ACTOR_TERMINATED/EFFECT_COMPLETED
        /DELEGATION_ISSUED yang sudah dipakai). "CancellationSignal" tetap
        nama konsep ontologis di derivation/audit, tidak dipakai literal di
        Trajectory.

        DEFERRED reduction, pola identik dengan DELEGATION_ISSUED di
        delegate() (Stage 6): cancel() HANYA append -- tidak pernah
        memanggil _reduce_and_advance, tidak pernah memanggil Sandbox.
        Runtime tidak memutuskan ACTOR_TERMINATED di sini (ND-2) -- ia
        hanya mencatat niat pembatalan sebagai Event biasa. cursor/_states
        actor yang terkena baru maju lewat step() berikutnya, ketika
        CANCELLATION_REQUESTED ini sampai di posisi cursor+1 miliknya
        sendiri.

        Event disintesis langsung (BUKAN lewat Gateway.translate()): tidak
        ada `raw` eksternal dari caller -- signature cancel() hanya
        (actor_id, depth), sama alasannya dengan Decision/EFFECT_COMPLETED
        di step() yang juga dikonstruksi langsung. Payload berisi metadata
        struktural (origin_actor_id, depth_remaining) lewat encoding JSON,
        pola sama dengan _encode_decision_payload -- tetap opaque bagi
        Runtime setelah ditulis, tidak pernah dibaca ulang untuk keputusan.

        Actor ROOT (actor_id) yang sudah TERMINATED -> ActorTerminatedError,
        simetris dengan seluruh method publik lain.

        Actor yang ditemukan SUDAH TERMINATED selama cascade (bukan root):
        DIKUNCI sebagai Design Freedom (Stage 7, disetujui eksplisit setelah
        audit derivation/spec/audit membuktikan tidak ada invariant yang
        memaksa salah satu arah) -- di-SKIP (tidak di-append
        CANCELLATION_REQUESTED kedua ke Actor yang sudah selesai), TAPI
        cascade TETAP diteruskan ke children-nya. Traversal yang dipakai
        adalah struktur Delegation (_children), BUKAN lifecycle Actor
        perantara -- lihat komentar _cancel_recursive() dan _children di
        __init__ untuk rationale lengkapnya.
        """
        if depth < 0:
            raise ValueError(f"depth tidak boleh negatif, dapat {depth!r}")

        root_stream = self._stream_or_raise(actor_id)  # ActorNotFoundError kalau belum genesis
        if self._has_terminal_event(root_stream):
            raise ActorTerminatedError(actor_id)

        self._cancel_recursive(origin_actor_id=actor_id, actor_id=actor_id, depth=depth)

    def _cancel_recursive(self, origin_actor_id: ActorID, actor_id: ActorID, depth: int) -> None:
        """
        Satu-satunya tempat yang boleh membentuk & append Event
        CANCELLATION_REQUESTED. actor_id di sini dijamin sudah genesis --
        satu-satunya pemanggil rekursif adalah lewat _children, yang hanya
        pernah diisi dengan child ActorID yang sudah nyata di-genesis oleh
        delegate() (invariant struktural, tidak divalidasi ulang di sini).

        Design Freedom (Stage 7), DIKUNCI:
        Delegation traversal is structural. A TERMINATED intermediate
        Actor does not receive a new CANCELLATION_REQUESTED Event, but it
        also does not terminate propagation toward its descendants. This
        behavior is a project-level design decision. The runtime ontology
        does not mandate either propagation or cutoff -- diaudit eksplisit
        terhadap derivation.md, spec.md/specification-v1_0.md, dan
        implementation-layer-audit.md: ketiganya hanya menyatakan
        "CancellationSignal menjalar sepanjang edge Delegation, dibatasi
        depth/budget" (derivation §2 / audit §13), tidak ada yang
        membahas nasib edge saat node perantaranya sudah TERMINATED.
        Karena itu keputusan "skip-but-continue" di bawah ini BUKAN
        derivasi dari Law I-III -- ia keputusan desain proyek yang
        dipilih secara sadar di antara dua opsi yang sama-sama sah, dan
        sekarang closed untuk implementasi Runtime ini.
        """
        stream = list(self._event_store.read_stream(actor_id))
        if not self._has_terminal_event(stream):
            tail_event = stream[-1]
            draft = Event(
                causal_scope_id=actor_id,
                type="CANCELLATION_REQUESTED",
                payload=self._encode_cancellation_payload(origin_actor_id, depth),
                causal_refs=[tail_event.id],
            )
            self._event_store.append(draft)

        if depth > 0:
            for child_id in self._children.get(actor_id, []):
                self._cancel_recursive(origin_actor_id, child_id, depth - 1)

    @staticmethod
    def _encode_cancellation_payload(origin_actor_id: ActorID, depth_remaining: int) -> bytes:
        """
        Encoding JSON untuk payload CANCELLATION_REQUESTED (disetujui
        sebagai default implementasi, sama status desainnya dengan
        _encode_decision_payload -- payload tetap opaque bagi Runtime
        setelah dibentuk, hanya untuk audit/provenance).
        """
        return json.dumps(
            {"origin_actor_id": origin_actor_id, "depth_remaining": depth_remaining}
        ).encode("utf-8")

    def archive_actor(self, actor_id: ActorID) -> None:
        """Evict a TERMINATED Actor's Runtime-side bookkeeping (_states,
        _cursors, _children) so long-lived processes don't grow these
        dicts without bound. Purely additive, opt-in -- nothing calls
        this automatically from inside Runtime itself.

        Only permitted once ACTOR_TERMINATED is on the stream
        (is_alive() is False) -- otherwise raises ActorNotTerminatedError,
        since removing _cursors[actor_id] for a live Actor would make its
        next step() call raise KeyError instead of a meaningful error.

        Does NOT touch the Event Store's own record of what happened by
        default -- Event Store retention (if any) is the EventStore
        implementation's own concern (see EventStore.forget(), called
        here only if the injected implementation provides it).
        """
        if self.is_alive(actor_id):
            raise ActorNotTerminatedError(actor_id)

        self._cursors.pop(actor_id, None)
        self._states.pop(actor_id, None)
        self._children.pop(actor_id, None)

        forget = getattr(self._event_store, "forget", None)
        if callable(forget):
            forget(actor_id)