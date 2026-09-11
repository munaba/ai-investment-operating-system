from __future__ import annotations

from dataclasses import dataclass, field, replace as _dataclass_replace
from datetime import datetime, timezone
from typing import Optional


ScopeID = str


# ---------------------------------------------------------------------------
# EventID  (Gap 1 — Global Event Identity)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EventID:
    """
    Identitas global sebuah Event, terstruktur sebagai (causal_scope_id, seq).

    HANYA dibentuk oleh EventStore.append() (core/event_store.py, langkah
    berikutnya). Tidak ada constructor helper di sini yang membuat EventID
    "baru dari nol" untuk sebuah Event yang belum pernah di-append — kalau
    caller butuh EventID, itu tandanya caller sedang mereferensikan Event
    yang SUDAH ada (mis. untuk causal_refs), bukan membuat identitas untuk
    Event miliknya sendiri yang belum tercatat.

    encode() memberi representasi string yang tetap resolvable ke
    (causal_scope_id, seq) tanpa perlu index global — opaque bagi semua
    pihak KECUALI Event Store.
    """

    causal_scope_id: ScopeID
    seq: int

    def __post_init__(self) -> None:
        if not self.causal_scope_id:
            raise ValueError("EventID.causal_scope_id tidak boleh kosong")
        if self.seq < 0:
            raise ValueError("EventID.seq tidak boleh negatif")

    def encode(self) -> str:
        return f"{self.causal_scope_id}:{self.seq}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.encode()


# ---------------------------------------------------------------------------
# EventType — kosakata struktural, BUKAN Enum tertutup
# ---------------------------------------------------------------------------
class EventType:
    """
    Kumpulan konstanta string untuk kategori Event yang sudah punya makna
    STRUKTURAL di level Runtime (dipakai Runtime untuk bercabang atas
    MEKANISME, bukan makna domain — lihat Runtime Spec v1.0 Gap 4, catatan
    soal Law III).

    Sengaja BUKAN Enum tertutup: spec.md §1 menyatakan `type` adalah
    "opaque string, Runtime tidak menafsirkannya". Menutupnya jadi Enum
    akan memaksa Runtime mengetahui seluruh kosakata type di compile time,
    yang sedikit bertentangan dengan opacity. Implementation bebas memakai
    string type lain di luar daftar ini; konstanta di bawah hanya
    memberi nama kanonik untuk kasus yang sudah eksplisit final di dokumen
    spec (dipakai literal pada pseudocode Gap 3/Gap 4).

    Ini adalah satu keputusan desain non-forced (Enum vs konstanta string) —
    dinyatakan eksplisit, bukan disamarkan sebagai derivasi.
    """

    ACTION = "Action"
    OBSERVATION = "Observation"
    DECISION = "Decision"
    CONTROL_SIGNAL = "ControlSignal"

    # Nilai literal yang sudah dipakai di pseudocode Runtime Spec v1.0:
    INTENT = "INTENT"
    ACTOR_TERMINATED = "ACTOR_TERMINATED"


# ---------------------------------------------------------------------------
# Event — Primitive
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    """
    Primitive tunggal dalam ontology. Immutable secara struktural
    (frozen=True) -- mutasi Event lama adalah pelanggaran Law I, ditegakkan
    oleh Python sendiri di sini, bukan hanya oleh konvensi/CI test di
    lapisan Event Store.

    Field:
        causal_scope_id  : scope kepemilikan (Identity Boundary, invariant
                            "ownership"). Wajib pada setiap Event.
        type             : string opaque. Lihat EventType di atas untuk
                            kosakata struktural yang sudah final.
        payload          : bytes, OPAQUE bagi Runtime. Tidak ada method di
                            kelas ini yang membuka/mem-parse isinya --
                            itu tanggung jawab sisi Implementation
                            (Semantic Boundary), bukan Primitive ini.
        causal_refs      : daftar EventID yang sudah ter-append sebelumnya
                            (Law II -- causal relation harus eksplisit).
                            Default list kosong (BUKAN None) supaya
                            `event.causal_refs == []` tetap predikat valid
                            tanpa null-check di caller manapun.
        timestamp        : metadata observability, timezone-aware (UTC).
                            BUKAN sumber ordering otoritatif -- ordering
                            otoritatif selalu `seq` di dalam EventID
                            (Law II). Dinyatakan eksplisit supaya tidak ada
                            yang diam-diam memakai timestamp untuk causal
                            ordering.
        id               : None sebelum di-append. Diisi HANYA oleh
                            EventStore.append() lewat with_id(). Tidak ada
                            jalur lain di kelas ini yang membuat EventID
                            baru untuk instance ini sendiri.
    """

    causal_scope_id: ScopeID
    type: str
    payload: bytes
    causal_refs: list[EventID] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: Optional[EventID] = None

    def __post_init__(self) -> None:
        if not self.causal_scope_id:
            raise ValueError("Event.causal_scope_id tidak boleh kosong")
        if not isinstance(self.payload, (bytes, bytearray)):
            raise TypeError(
                "Event.payload harus bytes (opaque) -- dapat "
                f"{type(self.payload).__name__}. Ini pelanggaran Law III "
                "kalau dibiarkan lolos: Runtime/Event tidak boleh tahu "
                "bentuk domain dari payload."
            )
        if not isinstance(self.causal_refs, list) or not all(
            isinstance(ref, EventID) for ref in self.causal_refs
        ):
            raise TypeError(
                "Event.causal_refs harus list[EventID] -- rujukan kausal "
                "harus resolvable secara struktural (Gap 1), bukan string bebas."
            )
        if self.timestamp.tzinfo is None:
            raise ValueError(
                "Event.timestamp harus timezone-aware (gunakan UTC) untuk "
                "menghindari ambiguitas -- meskipun timestamp bukan sumber "
                "ordering otoritatif."
            )

    @property
    def is_appended(self) -> bool:
        """True jika Event ini sudah punya identitas global (sudah lolos
        EventStore.append()). False berarti ini masih 'intent' di tangan
        caller, belum jadi realitas menurut Law I."""
        return self.id is not None

    def with_id(self, event_id: EventID) -> "Event":
        """
        Menempelkan EventID yang SUDAH dibentuk oleh EventStore.append().

        Method ini secara sengaja tidak membangun EventID sendiri -- ia
        hanya menerima EventID jadi dari luar. EventStore adalah satu-
        satunya pemanggil yang sah untuk method ini; caller lain yang
        memanggilnya sebelum append() adalah kesalahan pemakaian (Event
        yang dihasilkan tidak merepresentasikan realitas yang sudah
        tercatat, hanya replika identitas tanpa append yang sesungguhnya).
        """
        if self.is_appended:
            raise ValueError(
                "Event ini sudah punya id -- Event immutable, tidak boleh "
                "di-reassign id-nya (Law I: identitas sekali ditetapkan, "
                "tetap selamanya)."
            )
        if event_id.causal_scope_id != self.causal_scope_id:
            raise ValueError(
                "EventID.causal_scope_id tidak cocok dengan "
                "Event.causal_scope_id -- identitas hanya boleh ditempelkan "
                "pada scope yang sama."
            )
        return _dataclass_replace(self, id=event_id)