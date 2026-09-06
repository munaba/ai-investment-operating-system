# L18 Closure — Implementation Specification

**Stage:** L18 — Reflection Layer, closure milestone
**Status of this document:** Specification only. No code written yet.
**Baseline it closes against:** `Docs/l18_handover.md` (NOT CLOSED, §3/§7)
**Author role:** Principal Architect / Code Reviewer sign-off, pre-implementation

---

## 1. Ruang Lingkup Implementasi

**In scope — satu hal saja:**

- Menulis `Tests/test_stage_l18_reflection.py` (saat ini 0 byte) sebagai
  regression suite berdiri sendiri untuk tiga simbol yang sudah ada di
  `Orchestration/reflection.py`: `ReflectionError`, `ReflectionRecord`,
  `Reflector`.
- Suite membuktikan perilaku yang **sudah diimplementasikan**, bukan
  menambah perilaku baru. Tidak ada perubahan pada `reflection.py` itu
  sendiri kecuali test menemukan implementasi tidak sesuai
  dokumentasinya sendiri (lihat §8, Exit Criteria, jalur kegagalan).

**Eksplisit di luar scope (tidak boleh dikerjakan dalam milestone ini):**

- Analisis reflection yang sesungguhnya (success/fail ratio, ranking,
  trend detection) — tetap "Phase 1", ditunda sesuai docstring modul.
- `ReflectionStore` atau persistensi `ReflectionRecord` apa pun.
- Wiring `Reflector`/`ReflectionRecord` ke `Core/composition_root.py`.
- Invocation otomatis `Reflector.reflect(...)` setelah
  `MemoryRecorder.record(...)` atau lewat scheduler apa pun.
- Reflection lintas-Skill (masih satu domain: IDX stock analysis).
- Perubahan apa pun pada `Orchestration/memory.py`,
  `Orchestration/observation.py`, `Orchestration/planner.py`, atau
  `Core/composition_root.py`.

Keempat opsi roadmap yang sudah tercatat (Composition Root wiring,
retention policy Observation/Memory, Skill kedua) **tidak dibuka** di
milestone ini — itu keputusan giliran berikutnya, setelah exit
criteria §8 terpenuhi.

---

## 2. Invariant yang Harus Dibuktikan

Diambil langsung dari `l18_handover.md` §4 (enam keputusan locked-at-source)
dan §3 (daftar yang belum terverifikasi). Setiap baris di bawah harus
punya minimal satu assertion eksplisit di suite:

| #                                      | Invariant                                                                                                                                                                                                                           | Sumber locked |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| I1                                     | `ReflectionRecord` benar-benar frozen/immutable (assignment ke field manapun raise `FrozenInstanceError` atau setara `dataclasses.FrozenInstanceError`).                                                                      | §4.3         |
| I2                                     | `Reflector.reflect(records)` raise `ReflectionError` — bukan `TypeError`/exception lain — ketika `records` bukan `tuple` (list, `None`, generator, dsb).                                                              | §4.5         |
| I3                                     | `ReflectionRecord.source_record_count == len(records)` untuk batch non-trivial (0, 1, banyak elemen).                                                                                                                             | §4.5         |
| I4                                     | `Reflector` genuinely stateless: instance yang sama dipakai berkali-kali (beda batch berturut-turut) tidak punya efek silang; tidak ada instance attribute yang bocor antar panggilan.                                            | §4.2         |
| I5                                     | `Reflector` tidak pernah mengimpor, mengkonstruksi, atau mereferensikan `MemoryStore` — dicek secara statis (module-level `import`/attribute check pada `Orchestration.reflection`), bukan hanya lewat observasi perilaku. | §4.2         |
| I6                                     | Exception tak terduga selama konstruksi`ReflectionRecord` (bukan jalur validasi tipe) selalu dibungkus ulang jadi `ReflectionError` dengan original exception ter-chain via `from exc`.                                       | §4.6         |
| I7 (tambahan, bukan pengurangan scope) | `records=()` (tuple kosong) adalah input valid, menghasilkan `source_record_count=0`, **bukan** error — membuktikan validasi ketat pada tipe, longgar pada kekosongan (§4.5, baris terakhir).                           | §4.5         |
| I8 (tambahan)                          | `ReflectionRecord` tidak menyimpan referensi ke tuple `MemoryRecord` input apa pun — hanya dua field (`source_record_count`, `reflected_at`) yang ada pada instance (cek lewat `dataclasses.fields()`).                  | §4.3         |

I4 dan I5 memerlukan teknik pembuktian yang sedikit berbeda dari pola
test L11–L17 yang murni behavioral: I5 dicek dengan inspeksi modul
(`Orchestration.reflection.__dict__`/`dir()` tidak memuat simbol
`MemoryStore`, dan `Reflector` tidak punya method/atribut yang
menerimanya), bukan dengan menjalankan skenario. Ini didokumentasikan
eksplisit di dalam file test sebagai catatan gaya, supaya reviewer
berikutnya tidak bingung kenapa satu-dua check di file ini terlihat
"statis" dibanding yang lain.

**Batas eksplisit invariant I5 (penting, dicatat di sini dan wajib
diulang sebagai komentar di dalam test itu sendiri):** pemeriksaan
statis ini adalah **architectural guard terhadap bentuk kode saat
ini** — ia membuktikan bahwa, pada commit ini,
`Orchestration/reflection.py` tidak mengimpor/mereferensikan
`MemoryStore`. Ia **bukan bukti formal** bahwa coupling semacam itu
tidak mungkin muncul di masa depan: seseorang tetap bisa menambahkan
`import Orchestration.memory.MemoryStore` di revisi berikutnya, dan
guard ini hanya akan menangkapnya kalau test yang sama dijalankan lagi
setelah perubahan itu (yaitu, sebagai regression check pada CI/manual
run berikutnya, bukan sebagai jaminan struktural yang ditegakkan
runtime). Ini konsisten dengan sifat setiap regression test di repo
ini — ia membuktikan invariant terhadap kode yang ada sekarang, bukan
menutup kemungkinan pelanggaran di masa depan. Test wajib mencantumkan
kalimat pembatas ini di docstring/komentar skenario I5, agar tidak
salah dibaca sebagai jaminan yang lebih kuat dari yang sebenarnya.

---

## 3. File yang Akan Disentuh

- **`Tests/test_stage_l18_reflection.py`** — dibuat dari 0 byte menjadi
  suite lengkap. Satu-satunya file produksi/test yang ditulis.

Tidak ada file lain yang ditulis dalam milestone ini kecuali salah satu
invariant di §2 gagal dibuktikan terhadap implementasi saat ini — lihat
jalur kegagalan di §8.

---

## 4. File yang Tidak Boleh Disentuh

- `Orchestration/reflection.py` (kecuali jalur kegagalan §8)
- `Orchestration/memory.py`
- `Orchestration/observation.py`
- `Orchestration/planner.py`
- `Core/composition_root.py`
- `Core/exceptions.py`
- Seluruh file di bawah `Core/runtime.py`, `Core/event.py`,
  `Core/event_store.py`, `Core/reducer_shell.py` (kernel ontology — tidak
  relevan, tidak disentuh)
- Seluruh test file lain (`test_stage_l11_*.py` s.d.
  `test_stage_l17_memory.py`, dan seluruh test non-L1x) — dijalankan
  ulang untuk regression check (§6), tidak diedit.

---

## 5. Dependency Graph

```
Tests/test_stage_l18_reflection.py
        │
        │ imports
        ▼
Orchestration/reflection.py
   ReflectionError ──subclasses──▶ Core/exceptions.py :: AgentError
   ReflectionRecord   (no further dependency — value object)
   Reflector.reflect(records: Tuple[MemoryRecord, ...])
        │
        │ type-only reference (never constructed/called)
        ▼
Orchestration/memory.py :: MemoryRecord   (dataclass, used only as a
                                            type hint + as fixture input
                                            built directly by the test —
                                            MemoryStore/MemoryRecorder are
                                            NOT imported by reflection.py
                                            and must not be imported by
                                            the test's Reflector-facing
                                            assertions either)
```

Arah dependency yang dikunci (tidak berubah oleh milestone ini):
Reflection → Memory (read-only type dependency). Memory tidak pernah
mengetahui Reflection ada. Test file boleh mengimpor `MemoryRecord`
langsung untuk membangun fixture, tapi tidak boleh mengimpor
`MemoryStore`/`MemoryRecorder` ke dalam skenario yang menguji
`Reflector` — itu justru akan melanggar invariant I5 yang sedang
dibuktikan.

---

## 6. Regression Impact

- **Blast radius: nol pada kode produksi.** Tidak ada file produksi yang
  diedit (kecuali jalur kegagalan §8), sehingga tidak ada jalur
  eksekusi lain di repo yang bisa regresi.
- **Full suite re-run wajib** — lihat definisi eksplisit "full
  regression suite" di Acceptance Criteria §7 poin 5 (39 file per isi
  direktori `Tests/` saat ini, bukan angka "34" di `l18_handover.md`
  §6 yang sudah tidak cocok) — sebagai bagian dari acceptance, bukan
  opsional.
- **Kegagalan pre-existing yang sudah diketahui**
  (`Tests/test_stage_l6_multi_provider_registry.py`, stale
  `ApplicationGraph` field-set scope guard) **tetap di luar scope** —
  dicatat sebagai baseline yang sudah gagal sebelum milestone ini
  dimulai, tidak boleh dijadikan alasan menunda closure L18, dan tidak
  boleh "diperbaiki sekalian" di sini (itu perubahan di file lain, di
  luar §3).

---

## 7. Acceptance Criteria

Suite `Tests/test_stage_l18_reflection.py` dinyatakan lengkap jika dan
hanya jika:

1. Mengikuti gaya file test L11–L17 yang sudah ada: scenario-based,
   tanpa `pytest`, tanpa mock eksternal, global pass/fail counter, dan
   fungsi `main()` runner (pola persis seperti
   `test_stage_l17_memory.py`).
2. Kedelapan invariant di §2 (I1–I8) masing-masing punya minimal satu
   `check(...)` dengan deskripsi yang jelas menyebut invariant mana yang
   dibuktikan.
3. Tidak mengimpor `MemoryStore` atau `MemoryRecorder` untuk skenario
   apa pun yang menguji `Reflector` (lihat §5).
4. Dijalankan langsung (`python Tests/test_stage_l18_reflection.py`)
   dan seluruh check **PASS** — nol `FAIL`.
5. **"Full regression suite" didefinisikan eksplisit sebagai berikut**
   (menggantikan angka "34 file" di `l18_handover.md` §6, yang tidak
   lagi cocok dengan isi direktori saat ini — lihat catatan di bawah):

   - **Cakupan:** setiap file `*.py` langsung di bawah `Tests/`
     (tidak termasuk `Tests/__pycache__/` dan `Tests/.pytest_cache/`),
     dihitung pada commit tempat milestone ini ditutup. Pada saat
     spesifikasi ini ditulis, itu berarti **39 file**, termasuk
     `test_stage_l18_reflection.py` yang sedang dibangun di milestone
     ini sendiri.
   - **Cara menjalankan:** dua kelompok, sesuai konvensi yang sudah
     ada di repo — bukan konvensi baru yang diperkenalkan di sini:
     - 36 file mengikuti pola standalone runner (tanpa `pytest`,
       fungsi `main()` sendiri, sama seperti
       `test_stage_l17_memory.py`) — dijalankan satu per satu via
       `python Tests/<nama_file>.py`.
     - 3 file menggunakan `pytest` secara eksplisit
       (`test_stage5_suspend_resume.py`, `test_stage6_delegate.py`,
       `test_stage7_cancel.py`) — dijalankan via `pytest Tests/<nama_file>.py`.
   - **Kriteria lulus:** seluruh 39 file mengembalikan hasil hijau
     (exit code 0 / seluruh `check(...)` PASS / seluruh pytest test
     PASS), **kecuali** satu kegagalan baseline yang sudah diketahui
     dan tercatat sebelum milestone ini dimulai:
     `Tests/test_stage_l6_multi_provider_registry.py` (stale
     `ApplicationGraph` field-set scope guard, §6). Tidak ada file
     lain yang boleh berubah dari PASS menjadi FAIL dibanding hasil
     run sebelum milestone ini.
   - **Catatan ketidakcocokan angka:** `l18_handover.md` §6 menyebut
     "34 test files, everything through L17" pada saat ditulis. Isi
     direktori `Tests/` saat ini menghasilkan 39 file (38 pre-existing
     + 1 file L18 yang sedang diisi). Selisih ini tidak diselidiki di
       sini (bukan scope milestone ini untuk merekonsiliasi hitungan
       historis) — definisi yang berlaku untuk closure L18 adalah
       hitungan aktual di atas, diverifikasi langsung dari isi
       direktori pada saat run, bukan angka yang tertulis di dokumen
       manapun.

---

## 8. Exit Criteria — L18 Resmi CLOSED

L18 dinyatakan **CLOSED** (status sama seperti L11–L17) hanya jika
seluruh berikut terpenuhi, dan dicatat di dalam `l18_handover.md`
sebagai addendum (bukan dokumen baru):

1. Acceptance criteria §7 terpenuhi seluruhnya.
2. `l18_handover.md` §7 dan baris penutup (`## L18 — NOT CLOSED — ...`) diperbarui menjadi `## L18 — CLOSED`, dengan referensi ke
   commit/PR yang menambahkan suite tersebut.
3. Tidak ada perubahan pada `Orchestration/reflection.py` yang belum
   direview — **jalur kegagalan**: jika salah satu invariant I1–I8
   ternyata **tidak benar** terhadap implementasi saat ini (mis. exception
   yang salah, atau field tersembunyi yang bocor), maka:
   - milestone ini **berhenti**, tidak lanjut menulis test yang
     "menyesuaikan diri" dengan bug,
   - temuan dilaporkan sebagai finding terpisah (format review yang
     sudah disepakati: FACT/CHANGE/WHY/REGRESSION RISK/DECISION/NEXT
     STEP/STOP),
   - perubahan pada `reflection.py` (jika disetujui) menjadi milestone
     tersendiri dengan spec-nya sendiri, bukan disisipkan diam-diam ke
     dalam PR test ini.
4. Setelah (1)–(3) terpenuhi dan dicatat, roadmap berikutnya (Composition
   Root wiring / retention policy Observation-Memory / Skill kedua)
   baru boleh dibuka untuk dibahas.

---

**Belum ada baris kode yang ditulis oleh dokumen ini.** Menunggu
persetujuan eksplisit atas spesifikasi di atas sebelum implementasi
`Tests/test_stage_l18_reflection.py` dimulai.
