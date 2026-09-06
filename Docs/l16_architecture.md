# L16 — Architecture Proposal (Planning Only, No Code)

Status: **DRAFT FOR REVIEW** — architecture only, tidak ada implementasi.
Baseline: L11, L12, L13, L15 Phase 1 — semua **CLOSED**, tidak
diredesain, tidak disentuh.

> **Catatan transparansi (wajib dibaca sebelum bagian lain):** `l14_handover.md`
> tidak ditemukan di file yang tersedia bagi saya — tidak ada di upload,
> tidak ada di memori kerja. Dokumen ini disusun berdasarkan pembacaan
> langsung terhadap source code yang sudah terverifikasi
> (`Agents/planner.py`, `Orchestration/planner.py`,
> `Core/composition_root.py`, `Core/event.py`, `Agents/memory.py`,
> `Agents/base_agent.py`) plus `l15_phase1_handover.md` yang sudah ada.
> Kalau isi `l14_handover.md` yang sebenarnya berbeda dari asumsi di
> bawah, dokumen ini perlu direkonsiliasi sebelum L16 dianggap final.

---

## 1. Kenapa L16 Ada

`GoalPlanner` (L15) bisa membangun dan menjalankan `ExecutionPlan` — tapi
hanya dari `Goal.metadata` yang **sudah tersedia sebelum planning
dimulai**. Tidak ada satu komponen pun di L11–L15 yang bertugas mengisi
`Goal.metadata` itu secara otomatis dari dunia luar (harga terkini,
histori, status eksekusi sebelumnya, dsb.). Saat ini metadata itu harus
sudah "ada" di tangan caller sebelum `build_plan()` dipanggil — sumbernya
belum didefinisikan di layer manapun.

L16 ada untuk mengisi celah itu: menyediakan satu sumber kebenaran yang
terstruktur, dapat diaudit, dan dapat dipakai ulang untuk "apa yang
sedang/baru saja terjadi" — sehingga `Goal.metadata` (dan nantinya
Memory, Reflection) punya bahan baku yang konsisten, bukan setiap
caller menyusun sendiri secara ad-hoc.

## 2. Celah Arsitektural Setelah L15

| Yang sudah ada | Yang belum ada |
| --- | --- |
| `ServiceResult` — hasil satu panggilan Service, sekali pakai, tidak persisten | Representasi hasil itu setelah dikumpulkan/diberi makna lintas waktu |
| `GoalPlanner.accumulate_context()` — akumulasi *dalam satu* `execute_plan()` call, hilang begitu plan selesai | Akumulasi yang bertahan *lintas* pemanggilan `execute_plan()` |
| `Agents.memory.ConversationMemory` — histori pesan chat (user/assistant) | Histori *observasi domain* (harga, skor, hasil eksekusi) — bukan sama sekali objek yang sama |
| `Core.event.EventType.OBSERVATION` — tipe event struktural di Runtime (genesis/ingest), opaque string | Observasi bermakna domain (AIOS sense) — beda konsep, sama nama |
| `Goal(metadata={...})` dibuat manual oleh caller | Sumber yang bisa mengisi `Goal.metadata` secara sistematis dari kondisi terkini |

Dua kolom terakhir di baris 3 dan 4 sengaja saya soroti sebagai
**risiko penamaan**, bukan risiko desain — lihat §8 dan §14.

## 3. Layer Mana yang Harus Datang Berikutnya

**Observation Layer.** Ini konsisten dengan keputusan yang sudah dikunci
di `l15_phase1_handover.md` §6 (urutan `Observation → Memory →
Reflection`), dan direvalidasi di sini dengan alasan independen di §4.

Observation Layer **bukan** re-desain apa pun dari L11–L15. Ia murni
komponen baru yang duduk *di antara* `ServiceResult`/`GoalPlanner` dan
Memory (yang belum ada), tanpa mengubah kontrak satu pun dari keduanya.

## 4. Kenapa Layer Ini Sebelum Memory

Memory butuh sesuatu yang bisa disimpan yang sudah **bersih, terstruktur,
dan bermakna** — bukan `ServiceResult` mentah (yang membawa `error:
Optional[Exception]`, tidak serializable, dan bentuknya beda-beda per
Service) dan bukan juga `List[ServiceResult]` mentah dari
`execute_plan()`.

Kalau Memory dibangun lebih dulu, ia akan terpaksa langsung bicara ke
`ServiceResult`/`GoalPlanner` secara langsung — dan begitu Observation
Layer datang belakangan, Memory harus di-refactor supaya bicara ke
Observation, bukan lagi ke `ServiceResult`. Itu melanggar prinsip
*additive-only, no rework* yang sudah dipegang sejak L11. Observation
lebih dulu berarti Memory dari hari pertama hanya pernah bicara ke satu
kontrak (Observation), tidak pernah ke `ServiceResult` langsung.

## 5. Kenapa Memory Sebelum Reflection

Reflection (evaluasi/pembelajaran atas apa yang sudah terjadi) butuh
histori yang sudah tersimpan untuk direnungkan. Tanpa Memory, Reflection
tidak punya apa pun untuk direfleksikan selain state sesaat — yang
sudah dipegang `GoalPlanner.accumulate_context()` secara sementara dan
hilang begitu `execute_plan()` selesai. Reflection secara definisi
beroperasi *lintas waktu*; Memory adalah prasyarat struktural untuk itu,
bukan pilihan urutan yang sewenang-wenang.

## 6. Tanggung Jawab yang Diperlukan (Required Responsibilities)

Observation Layer bertanggung jawab untuk:

1. Mengubah satu `ServiceResult` (atau satu batch `List[ServiceResult]`
   dari `execute_plan()`) menjadi satu atau lebih objek `Observation`
   yang terstruktur, immutable, dan self-describing (punya sumbernya
   sendiri: service_name mana, kapan, sukses/gagal).
2. Menyimpan `Observation` dalam bentuk yang **read-only setelah
   dibuat** (immutable value object, sama seperti `Goal`/`PlanStep`/
   `ExecutionPlan` di L15).
3. Menyediakan akses baca (query) atas `Observation` yang sudah
   terkumpul — untuk dipakai Memory (nanti) dan, secara opsional,
   sebagai sumber pengisi `Goal.metadata` untuk `GoalPlanner` yang
   sudah ada.
4. Menjaga satu observasi = satu fakta tunggal yang tidak berubah;
   revisi/observasi baru selalu berupa entri baru, bukan mutasi entri
   lama (Law of immutability yang sama dipakai `Core.event.Event`).

## 7. Tanggung Jawab yang Dilarang (Forbidden Responsibilities)

Observation Layer **tidak boleh**:

- Membuat keputusan (itu domain `GoalPlanner`/Reflection nanti, bukan
  Observation).
- Memanggil `ServiceSkill.execute(...)` sendiri, atau menjalankan apa
  pun. Observation Layer bersifat pasif: ia hanya menerima
  `ServiceResult` yang sudah dihasilkan pihak lain, tidak pernah
  memicu eksekusi baru.
- Menyentuh `Core.runtime`, `Agents.executor`, `Agents.sandbox`,
  `Agents.tool_registry`, atau `Core.event_store` — Observation Layer
  ada di layer Orchestration/Services, bukan Runtime.
- Mengubah `Core.analysis_pipeline.AnalysisPipeline` atau
  `Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline`
  dengan cara apa pun.
- Mengubah `GoalPlanner` (`build_plan`, `execute_plan`,
  `accumulate_context`, `translate_metadata`) — keempatnya tetap seperti
  yang dikunci di L15.
- Melakukan translasi metadata bergaya `translate_metadata()`
  (satu-satunya tempat aturan `PRICE → ENTRY_PRICE` boleh hidup tetap
  `GoalPlanner`, tidak diduplikasi di Observation).
- Menjadi pengganti `Agents.memory.ConversationMemory` (histori chat) —
  keduanya harus tetap dua objek terpisah dengan tujuan yang sepenuhnya
  berbeda (lihat §14).
- Mem-persist ke storage permanen (database/file). Observation Layer di
  L16 adalah struktur-dalam-memori saja; persistensi (kalau dibutuhkan)
  adalah keputusan Memory Layer, bukan Observation.

## 8. Interaksi dengan Runtime

**Tidak ada.** Observation Layer tidak mengimpor dari, tidak dipanggil
oleh, dan tidak memanggil `Core.runtime`, `Core.event`,
`Core.event_store`, `Agents.executor`, atau `Agents.sandbox`. Ini
konsisten dengan `GoalPlanner` sendiri, yang juga tidak menyentuh
Runtime sama sekali (L15, keputusan #3 di handover).

Satu hal yang **harus** ditegaskan eksplisit di implementasi nanti
(bukan sekadar "kebetulan tidak overlap"): `Core.event.EventType.OBSERVATION`
adalah kosakata struktural Runtime yang sudah ada sejak Stage 5 — dipakai
untuk menandai *jenis Event* (genesis, ingest) di level event-sourcing,
sama sekali bukan konsep yang sama dengan `Observation` domain (AIOS)
yang diusulkan di sini. Dua hal ini kebetulan berbagi nama Inggris yang
sama tapi berasal dari dua tingkat abstraksi yang berbeda dan tidak
boleh disatukan atau saling mereferensikan.

## 9. Interaksi dengan Planner

Observation Layer **tidak memanggil** `GoalPlanner` dengan cara apa pun,
dan `GoalPlanner` **tidak diwajibkan** memanggil Observation Layer di
L16 — interaksi antar keduanya, kalau ada, harus tetap satu arah dan
opsional:

- `GoalPlanner.execute_plan()` yang sudah ada tetap mengembalikan
  `List[ServiceResult]` persis seperti sekarang — tidak berubah bentuk.
- Sebuah caller (bukan `GoalPlanner` itu sendiri) *boleh* mengambil
  `List[ServiceResult]` itu setelah `execute_plan()` selesai dan
  menyerahkannya ke Observation Layer untuk direkam — ini terjadi **di
  luar** `GoalPlanner`, bukan di dalam method-nya.
- `Goal.metadata` yang menjadi input `build_plan()` *boleh* diisi dari
  hasil query Observation Layer sebelum `Goal` dikonstruksi — juga
  terjadi di luar `GoalPlanner`, oleh calling code, bukan oleh
  perubahan pada `GoalPlanner` sendiri.

Dengan kata lain: Observation Layer adalah tetangga `GoalPlanner`, bukan
kolaborator internalnya. `GoalPlanner` tidak perlu tahu Observation
Layer ada.

## 10. Interaksi dengan Service

Observation Layer tidak pernah memanggil `ServiceSkill` atau
`BaseService` secara langsung. Satu-satunya bentuk kontak dengan
Service adalah **pasif**: menerima `ServiceResult` yang sudah
dihasilkan (baik dari pemanggilan `ServiceSkill.execute()` langsung,
maupun dari `GoalPlanner.execute_plan()`) sebagai input untuk dijadikan
`Observation`.

## 11. Model Observasi (Observation Model)

Prinsip: satu `Observation` = satu fakta atomik, immutable, dengan
provenance jelas. Bentuk konseptual (bukan kode):

- `source` — nama Service/skill asal (`service_name`), sama vocabulary
  dengan `SkillMetadata.service_name`.
- `observed_at` — timestamp pembuatan observasi.
- `success` — apakah `ServiceResult` sumbernya sukses.
- `payload` — data yang diobservasi (turunan dari `ServiceResult.data`
  saat sukses; `None`/kosong saat gagal — Observation tidak
  menyimpulkan apa pun tentang kegagalan, hanya mencatatnya apa adanya).
- `correlation` — cara menelusuri observasi ini balik ke `PlanStep`/
  `ExecutionPlan` asalnya (kalau berasal dari `GoalPlanner`), tanpa
  Observation Layer perlu tahu bentuk `ExecutionPlan` secara mendalam.

Tidak ada skema "importance", "confidence", atau interpretasi lain di
L16 — itu domain Reflection, bukan Observation. Observation Layer
mencatat fakta, bukan menilai fakta.

## 12. Alur Data (Data Flow)

```
ServiceSkill.execute(...)  → ServiceResult          (sudah ada, L13)
        │
        ▼
GoalPlanner.execute_plan() → List[ServiceResult]    (sudah ada, L15)
        │
        ▼  (di luar GoalPlanner, oleh calling code -- L16 BARU)
ObservationRecorder.record(service_result / list)
        │
        ▼
Observation (immutable, tersimpan di ObservationStore in-memory)
        │
        ▼  (query, opsional, oleh calling code -- bukan otomatis)
ObservationStore.query(...) → dipakai untuk menyusun Goal.metadata
                                berikutnya, ATAU dipakai Memory Layer
                                (L17/berikutnya) untuk persistensi
                                jangka panjang
```

Panah dari `GoalPlanner`/`ServiceSkill` ke Observation Layer adalah **satu
arah**. Tidak ada panah balik dari Observation ke `GoalPlanner` di
dalam kode `GoalPlanner` sendiri — kalau ada penggunaan hasil query
Observation untuk membangun `Goal` berikutnya, itu terjadi di kode
pemanggil (composition/orkestrasi level atas), bukan di method
`GoalPlanner`.

## 13. Objek yang Diperlukan (Objects Required)

Konsep-level saja (bukan skeleton kode, sesuai batasan tugas):

- **`Observation`** — value object immutable, seperti dijelaskan di §11.
- **`ObservationRecorder`** — komponen tunggal, bertugas menerjemahkan
  `ServiceResult`/`List[ServiceResult]` menjadi `Observation`. Analog
  perannya dengan `ServiceSkill` di L13: satu kelas generik, tidak
  disubclass per Service.
- **`ObservationStore`** (in-memory, L16 scope) — penyimpanan dan query
  sederhana atas `Observation` yang sudah direkam. Bukan database,
  bukan persistensi lintas proses — itu keputusan Memory Layer.
- **`ObservationError`** — subclass `Core.exceptions.AgentError`, pola
  yang identik dengan `GoalPlannerError`/`PlannerError` yang sudah ada.

Tidak ada objek baru yang menyentuh `Goal`/`PlanStep`/`ExecutionPlan` —
ketiganya tetap seperti yang dikunci L15.

## 14. Batasan (Boundaries)

- **Observation (AIOS, domain baru) ≠ `EventType.OBSERVATION` (Runtime,
  event-sourcing, sudah ada sejak Stage 5).** Nama sama, konsep beda,
  layer beda, tidak boleh saling referensi atau digabung.
- **`Observation` (domain, baru) ≠ `Agents.memory.ConversationMemory`
  (histori chat, sudah ada sejak awal proyek).** `ConversationMemory`
  menyimpan `Message` percakapan user/assistant; `Observation`
  menyimpan hasil domain (harga, skor, hasil eksekusi Service). Dua
  hal ini tetap dua objek terpisah — Observation Layer tidak menulis
  ke `ConversationMemory`, dan `ConversationMemory` tidak menulis ke
  Observation.
- **Observation Layer ≠ Memory Layer.** Observation adalah "apa yang
  baru saja terjadi, dicatat apa adanya, dalam memori proses saat
  ini". Memory (stage berikutnya) adalah "apa yang sudah pernah
  terjadi, dipertahankan lintas waktu/proses". L16 hanya membangun
  yang pertama.
- **Observation Layer tidak boleh membuat `GoalPlanner` bergantung
  padanya.** `GoalPlanner` harus tetap bisa berjalan sendiri (seperti
  di seluruh test L15) tanpa Observation Layer ada sama sekali —
  ketergantungan hanya boleh satu arah (calling code → Observation),
  tidak pernah `GoalPlanner` → Observation secara internal.

## 15. Technical Debt yang Diwarisi

Semua debt dari L13/L15 tetap berlaku dan **tidak diperbaiki oleh L16**:

- **R3 (L13)** — fallback `str(result)` di `GenericSandbox` untuk
  return value non-JSON-serializable. Tidak relevan buat Observation
  Layer (yang tidak lewat Sandbox), tapi tetap debt aktif di layer
  `ServiceSkill`.
- **R4 (L13)** — `ServiceSkill.execute()` langsung (bukan lewat
  `GoalPlanner`) tetap tidak punya context accumulation. Observation
  Layer tidak mengubah ini.
- **Blocked-steps tidak dipertahankan (L15)** — `build_plan()` masih
  hanya nge-log skill yang tidak reachable, tidak menyimpan alasannya
  di `ExecutionPlan`. L16 tidak menyentuh ini; kalau nanti Reflection
  butuh tahu "skill apa yang tidak pernah reachable", itu perlu
  pekerjaan tambahan di `GoalPlanner` sendiri di luar lingkup L16.
- **`translate_metadata` single-purpose (L15)** — tetap hanya satu
  aturan (`PRICE → ENTRY_PRICE`). Observation Layer tidak menambah
  aturan translasi baru di `GoalPlanner`.

## 16. Pertanyaan Terbuka (Open Questions)

Perlu dijawab sebelum/selama implementasi L16 (bukan pertanyaan
arsitektur besar, tapi keputusan detail yang belum dikunci):

1. Apakah `ObservationRecorder` merekam **setiap** `ServiceResult`
   secara otomatis (misalnya lewat semacam hook di calling code
   setelah `execute_plan()`), atau murni dipanggil eksplisit oleh
   caller per kasus? (Mempengaruhi seberapa "invisible" Observation
   Layer terhadap kode yang sudah ada.)
2. Apakah `ObservationStore` butuh batas ukuran (mirip
   `ConversationMemory.max_size`, FIFO), atau tidak terbatas di L16
   dan baru dibatasi saat Memory Layer datang?
3. Apakah query `ObservationStore` perlu difilter per `source`
   (service_name) sebagai first-class API, atau cukup "semua
   Observation, filter di sisi caller"?
4. Apakah `Observation.payload` untuk hasil gagal (`success=False`)
   perlu menyimpan pesan error (`ServiceResult.error`/`message`) atau
   sengaja dikosongkan sepenuhnya? (Berdampak ke privasi/ukuran data,
   bukan ke desain inti.)
5. Siapa pemilik siklus hidup `ObservationStore` di
   `ApplicationGraph` — field baru di `ApplicationGraph` (pola yang
   sama dengan `service_skills`/`goal_planner`), atau sesuatu yang
   dipegang di luar composition root untuk sementara?

Tidak satu pun dari pertanyaan ini butuh jawaban sebelum architecture
review ini disetujui — semuanya keputusan implementasi-level yang aman
ditunda ke saat coding dimulai.

## 17. Keputusan yang Sudah Terkunci (Locked, dari L15 dan direvalidasi di L16)

1. `AnalysisPipeline` tetap production, tidak disentuh.
2. `GoalPlanner` tetap tidak berubah — semua 4 method-nya tetap seperti
   L15, tidak ada method baru ditambahkan untuk L16.
3. `ServiceSkill` tetap thin wrapper, tidak ada tanggung jawab baru.
4. Urutan roadmap: **Observation → Memory → Reflection** (dikunci di
   L15 handover §6, dikonfirmasi ulang dengan alasan independen di §4–5
   dokumen ini).
5. Observation Layer sepenuhnya additive: tidak ada file existing yang
   perlu diubah perilakunya (di luar kemungkinan satu baris opsional di
   composition root untuk mendaftarkan komponen baru — analog pola
   `_build_service_skills`/`_build_goal_planner`, dibahas lebih lanjut
   saat implementasi, bukan bagian keputusan arsitektur ini).
6. Observation ≠ `EventType.OBSERVATION` (Runtime) dan Observation ≠
   `ConversationMemory` (chat history) — dua batasan penamaan/konsep
   ini terkunci sebagai bagian dari desain L16, tidak boleh dilanggar
   saat implementasi.

## 18. File yang Akan Ditambahkan L16

Estimasi lokasi (mengikuti pola L13/L15 — modul baru di
`Orchestration/`, tidak menyentuh `Core/`, `Services/`, atau `Agents/`
yang sudah ada):

- `Orchestration/observation.py` — `Observation`, `ObservationError`,
  `ObservationRecorder`, `ObservationStore` (nama final ditentukan saat
  implementasi; ini estimasi struktural, bukan komitmen kode).
- `Tests/test_stage_l16_observation.py` — regression suite khusus
  Observation Layer, gaya sama dengan L11/L12/L13/L15 (no pytest, no
  external mocks, scenario-based).
- `Docs/l16_handover.md` — handover penutup, dibuat setelah
  implementasi selesai (bukan bagian dari deliverable arsitektur ini).

Kemungkinan satu baris tambahan additive di `Core/composition_root.py`
(field baru + factory function, pola identik `_build_goal_planner`) —
**opsional**, bergantung jawaban §16 pertanyaan 5, dan tetap harus
melalui review terpisah sebelum diimplementasikan.

## 19. File yang TIDAK BOLEH Diubah L16

- `Orchestration/planner.py` — `GoalPlanner` dan semua value object-nya.
- `Orchestration/service_skill.py` — `ServiceSkill`, `SkillMetadata`,
  `SKILL_METADATA_BY_SERVICE`.
- `Services/service_result.py`, `Services/service_context.py`,
  `Services/base_service.py`, dan seluruh 11 implementasi Service.
- `Core/analysis_pipeline.py`.
- `Orchestration/runtime_analysis_pipeline.py`.
- `Core/runtime.py`, `Core/event.py`, `Core/event_store.py`,
  `Core/gateaway.py`.
- `Agents/base_agent.py`, `Agents/executor.py`, `Agents/sandbox.py`,
  `Agents/tool_registry.py`, `Agents/memory.py`, `Agents/planner.py`
  (`Planner`/`PlannerError`, bukan `GoalPlanner`).
- `Agents/stock_agent.py`.
- Semua test file L11–L15 yang sudah ada
  (`Tests/test_stage_l11_*.py` s.d. `Tests/test_stage_l15_planner.py`).

## 20. Urutan Implementasi yang Direkomendasikan

Setelah architecture review ini disetujui:

1. Jawab pertanyaan terbuka di §16 yang benar-benar memblokir desain
   objek (khususnya #1 dan #5) — sisanya bisa diputuskan sambil jalan.
2. Implementasi `Observation` (value object) — paling kecil blast
   radius, tidak bergantung apa pun selain `ServiceResult`.
3. Implementasi `ObservationError`.
4. Implementasi `ObservationRecorder` (murni fungsi transformasi
   `ServiceResult`/`List[ServiceResult]` → `Observation`).
5. Implementasi `ObservationStore` (penyimpanan + query in-memory).
6. (Opsional, additive) Wiring di `Core/composition_root.py` — hanya
   kalau §16 #5 dijawab "ya, taruh di ApplicationGraph".
7. `Tests/test_stage_l16_observation.py` — regression suite, mengikuti
   gaya L11–L15.
8. Jalankan ulang seluruh regression L11/L12/L13/L15 untuk memastikan
   nol regresi.
9. `Docs/l16_handover.md` — penutup stage, format sama dengan L15.

Tidak ada langkah di atas yang boleh mulai sebelum konfirmasi eksplisit
dari Anda atas dokumen ini.

---

**STOP.** Dokumen ini murni arsitektur dan perencanaan. Tidak ada kode,
skeleton class, atau file produksi yang dibuat/diubah dalam proses
penyusunan dokumen ini. Menunggu konfirmasi sebelum implementasi L16
dimulai.
