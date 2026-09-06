

from __future__ import annotations

from typing import Protocol

from Core.event import Event, EventType, ScopeID


# ---------------------------------------------------------------------------
# Gateway -- abstraksi
# ---------------------------------------------------------------------------
class Gateway(Protocol):
    def translate(self, raw: bytes, source: str, causal_scope_id: ScopeID) -> Event:
        """
        Hanya framing (di mana pesan mulai/berakhir). TIDAK BOLEH branch
        berdasarkan isi `raw`. Selalu mengembalikan Event dengan id=None --
        Gateway tidak pernah menghasilkan EventID (itu tanggung jawab
        EventStore.append(), dipanggil oleh Runtime, bukan oleh Gateway).

        causal_scope_id diberikan oleh CALLER (Runtime/config), bukan
        diturunkan dari isi `raw` -- Gateway tidak boleh menyimpulkan
        scope dari payload (itu sudah interpretasi, pelanggaran Law III).
        Ini menjawab "bootstrapping asymmetry" yang dicatat spec.md §3
        Bagian A3: identitas scope selalu datang dari luar payload.
        """
        ...


# ---------------------------------------------------------------------------
# DefaultGateway -- implementasi referensi
# ---------------------------------------------------------------------------
class EmptyRawError(Exception):
    """Diangkat ketika raw kosong. Ini validasi FRAMING (apakah ada pesan
    sama sekali), bukan validasi ISI (bukan interpretasi domain)."""


class DefaultGateway:
    """
    Implementasi referensi Gateway yang membuktikan Law III secara mekanis:
    tidak ada satu baris pun di translate() yang membuka isi `raw` untuk
    keputusan. Satu-satunya pemeriksaan adalah struktural (apakah `raw`
    kosong) -- itu framing (ada/tidak ada pesan), bukan interpretasi isi
    (apa isi pesan itu).

    Setiap Event yang dihasilkan diberi type=EventType.OBSERVATION secara
    seragam -- BUKAN karena membaca isi raw, tapi karena "stimulus mentah
    dari luar" secara struktural adalah observasi, terlepas dari isinya
    apa pun. Kalau caller (Runtime, lewat Reasoner di sisi Implementation)
    kelak perlu mereklasifikasi Event ini menjadi INTENT/Action setelah
    ditafsirkan, itu terjadi di layer Semantic Boundary -- bukan di sini.
    """

    def translate(self, raw: bytes, source: str, causal_scope_id: ScopeID) -> Event:
        if not isinstance(raw, (bytes, bytearray)):
            raise TypeError(
                f"Gateway.translate() menerima bytes, dapat {type(raw).__name__}. "
                "Kalau caller mengirim objek domain (dict/str terparsi), itu "
                "pelanggaran Law III sebelum sampai ke Gateway."
            )
        if len(raw) == 0:
            raise EmptyRawError(
                f"raw kosong dari source={source!r} -- tidak ada pesan untuk di-frame."
            )
        if not source:
            raise ValueError("source tidak boleh kosong (framing metadata wajib)")

        # Tidak ada branch berdasarkan isi `raw` di bawah ini. `raw` hanya
        # dipindahkan apa adanya ke payload -- byte demi byte, tanpa dibuka.
        return Event(
            causal_scope_id=causal_scope_id,
            type=EventType.OBSERVATION,
            payload=bytes(raw),
            causal_refs=[],  # Gateway tidak tahu Event mana yang valid untuk
                             # dirujuk (itu butuh EventStore.exists(), yang
                             # tidak boleh diakses Gateway). Genesis atau
                             # observasi independen -- pengisian causal_refs
                             # non-kosong, kalau dibutuhkan, adalah keputusan
                             # Runtime setelah translate() kembali, bukan
                             # tanggung jawab Gateway.
        )