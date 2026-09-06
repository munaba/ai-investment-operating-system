from __future__ import annotations

import builtins
import random
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator, Protocol

from Core.event import Event


# ---------------------------------------------------------------------------
# State -- Projection, bukan Boundary/Process. Didefinisikan di sini karena
# ini file pertama dalam urutan implementasi yang membutuhkan bentuknya
# (Gap 3 menambahkan reducer_version ke State/Snapshot). Bukan komponen
# baru -- ini realisasi Projection yang sudah disebut di ontology awal.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class State:
    """
    value           : domain-derived, BURAM bagi Shell -- Shell tidak pernah
                       membuka/membandingkan isinya, hanya membungkusnya
                       ulang di dalam State baru.
    reducer_version : SELALU diisi oleh ReducerShell dari logic.version,
                       TIDAK PERNAH oleh Reducer Logic sendiri. Ini
                       provenance authority (Gap 3) -- logic tidak bisa
                       berbohong soal versinya sendiri lewat return value,
                       karena Shell tidak pernah membaca version dari sana.
    """

    value: Any
    reducer_version: str

    @staticmethod
    def empty(reducer_version: str = "unversioned") -> "State":
        return State(value=None, reducer_version=reducer_version)


# ---------------------------------------------------------------------------
# ReducerPort -- shape lokal untuk kebutuhan reducer_shell.py.
# Definisi Protocol RESMI tanpa logic akan dipindah ke contracts/reducer.py
# di langkah 7, TANPA mengubah bentuk ini -- didefinisikan di sini terlebih
# dahulu karena Shell butuh tipe ini untuk type-check `logic` yang di-inject.
# ---------------------------------------------------------------------------
class ReducerPort(Protocol):
    version: str  # wajib, opaque -- semver atau content-hash, bukan makna domain

    def reduce(self, state: State, event: Event) -> Any:
        """
        Mengembalikan `value` domain baru (BUKAN State utuh) -- pembungkusan
        menjadi State(value=..., reducer_version=...) adalah tugas Shell,
        bukan logic. Logic TIDAK PERNAH menerima/mengetahui handle apa pun
        selain (state, event) -- tidak ada EventStore, tidak ada network,
        tidak ada clock, tidak ada randomness yang disuntikkan lewat
        signature ini.
        """
        ...


class PurityViolationError(Exception):
    """Diangkat oleh guard best-effort ketika logic.reduce() mencoba
    mengakses clock/random/network/filesystem selama jendela pemanggilan.
    Lihat catatan jujur di docstring modul: ini BEST-EFFORT, bukan
    penutupan penuh atas Kelas C1/C2."""


# ---------------------------------------------------------------------------
# Guard best-effort -- defense-in-depth, BUKAN isolasi sesungguhnya
# ---------------------------------------------------------------------------
@contextmanager
def _purity_guard() -> Iterator[None]:
    """
    Mem-patch sementara sejumlah entry point non-determinisme yang paling
    umum dipakai (clock, randomness, network socket, filesystem open) agar
    melempar PurityViolationError jika dipanggil SELAMA jendela ini aktif.
    Dipulihkan tanpa syarat sesudahnya (finally), bahkan kalau reduce()
    melempar exception.

    Ini TIDAK mencegah:
      - logic yang menyimpan referensi ke fungsi asli SEBELUM guard aktif
        (mis. `_t = time.time` di level modul saat import).
      - akses lewat syscall/C-extension yang tidak lewat modul stdlib yang
        di-patch di sini.
      - proses terpisah / thread lain yang tidak berbagi monkey-patch ini.

    Cakupan ini dinyatakan eksplisit -- guard ini menangkap kasus naif
    (memanggil time.time()/random.random()/socket.socket()/open() langsung
    di dalam badan reduce()), bukan seluruh permukaan Kelas C1/C2.
    """

    def _blocked(name: str):
        def _raise(*args, **kwargs):
            raise PurityViolationError(
                f"Reducer logic mencoba memanggil '{name}' selama reduce() -- "
                "ini pelanggaran purity (Law II: reduce harus deterministik "
                "murni dari (state, event)). Lihat core/reducer_shell.py "
                "untuk cakupan guard ini."
            )

        return _raise

    originals = {
        "time.time": time.time,
        "time.monotonic": time.monotonic,
        "datetime.now": datetime.now,
        "random.random": random.random,
        "random.randint": random.randint,
        "socket.socket": socket.socket,
        "builtins.open": builtins.open,
    }

    time.time = _blocked("time.time")
    time.monotonic = _blocked("time.monotonic")
    random.random = _blocked("random.random")
    random.randint = _blocked("random.randint")
    socket.socket = _blocked("socket.socket")
    builtins.open = _blocked("open")
    # datetime.now dipatch lewat class method assignment tidak semudah yang
    # lain (datetime adalah C type di banyak build) -- dibiarkan sebagai
    # entri terdokumentasi yang tidak dipatch, dicatat jujur sebagai batas
    # cakupan guard ini, bukan disembunyikan.

    try:
        yield
    finally:
        time.time = originals["time.time"]
        time.monotonic = originals["time.monotonic"]
        random.random = originals["random.random"]
        random.randint = originals["random.randint"]
        socket.socket = originals["socket.socket"]
        builtins.open = originals["builtins.open"]


# ---------------------------------------------------------------------------
# ReducerShell -- satu-satunya adapter Runtime <-> Reducer Logic
# ---------------------------------------------------------------------------
class ReducerShell:
    def __init__(self, logic: ReducerPort, *, guard: bool = True) -> None:
        """
        logic : ReducerPort yang di-bind SEKALI saat construction. Shell
                menyimpan referensi ini hanya untuk membaca `.version` dan
                memanggil `.reduce()` -- tidak pernah meneruskan handle lain
                ke dalamnya.
        guard : aktifkan _purity_guard() best-effort di atas selama
                pemanggilan reduce(). Default True. Bisa dimatikan untuk
                debugging/profiling, TIDAK untuk produksi -- mematikan guard
                tidak menghilangkan invariant purity, hanya menghilangkan
                satu lapis deteksi mekanis untuk kasus naif.
        """
        self._logic = logic
        self._guard = guard

    @property
    def version(self) -> str:
        """
        Read-only pass-through ke `self._logic.version` -- ditambahkan Stage
        5 (Blocker 1, disetujui eksplisit) supaya Runtime.resume() bisa
        membandingkan reducer_version tanpa membaca `_logic` (private)
        langsung. Murni exposure, tidak mengubah apply()/State/provenance
        Gap 3 -- Shell tetap satu-satunya pihak yang menulis
        `State.reducer_version`, property ini hanya membaca apa yang sudah
        di-bind saat construction.
        """
        return self._logic.version

    def apply(self, state: State, event: Event) -> State:
        """
        SATU-SATUNYA method publik. Memanggil logic.reduce(state, event)
        dengan HANYA dua argumen ini, lalu membungkus hasilnya sebagai
        State baru dengan reducer_version dari self._logic.version --
        TIDAK PERNAH dari nilai balik reduce() itu sendiri (provenance
        authority, Gap 3).
        """
        if self._guard:
            with _purity_guard():
                new_value = self._logic.reduce(state, event)
        else:
            new_value = self._logic.reduce(state, event)

        return State(value=new_value, reducer_version=self._logic.version)