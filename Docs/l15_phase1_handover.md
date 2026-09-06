# Stage L15 — Phase 1 — Handover

Status: **CLOSED** (Steps 1–8 complete, regression hijau)
Scope: `GoalPlanner` (`Orchestration/planner.py`) + wiring-nya di
`Core/composition_root.py`. Tidak ada perubahan pada Runtime, Executor,
Sandbox, ToolRegistry, Observation, Memory, Reflection, StockAgent,
RuntimeAnalysisPipeline, atau AnalysisPipeline.

---

## 1. Ringkasan Implementasi (Step 1–8)

| Step | Isi | Status |
| --- | --- | --- |
| 1 | `GoalPlannerError` + skeleton `GoalPlanner` (constructor-only, DI atas `Dict[str, ServiceSkill]` yang sama dengan L13) | Selesai |
| 2 | Value object immutable: `Goal`, `PlanStep`, `ExecutionPlan` (semua `@dataclass(frozen=True)`) | Selesai |
| 3 | `build_plan()` — forward-chaining fixed-point closure murni di atas `SkillMetadata.required_inputs` / `produced_outputs` | Selesai |
| 4 | `execute_plan()` — jalan in-order atas `ExecutionPlan.steps`, resolve `ServiceSkill` per step, panggil `.execute(...)`, kumpulkan `ServiceResult` | Selesai |
| 5 | `accumulate_context()` — dict merge murni, later-key-wins, tidak pernah mutate context lama | Selesai |
| 6 | `translate_metadata()` — satu aturan eksplisit: `PRICE → ENTRY_PRICE` khusus untuk `risk_management_service`, jika `ENTRY_PRICE` belum ada | Selesai |
| 7 | Composition Root Integration — `ApplicationGraph.goal_planner` + `_build_goal_planner()`, additive-only, dibangun di atas `service_skills` yang sama, tidak diregistrasikan sebagai Tool | Selesai |
| 8 | `Tests/test_stage_l15_planner.py` — regression suite khusus Planner (7 grup, 28 skenario, 47 check) | Selesai |

Alur kerja `GoalPlanner` end-to-end (dipakai oleh `execute_plan`):

```
Goal.metadata
  → build_plan()            (statis, tanpa eksekusi apa pun)
  → ExecutionPlan.steps      (urutan PlanStep, deterministik)
  → untuk setiap step:
       translate_metadata(step, running_context)  → metadata terjemahan
       ServiceSkill.execute(metadata=...)          → ServiceResult
       accumulate_context(running_context, result) → running_context baru
  → List[ServiceResult]
```

Tidak ada bagian dari alur ini yang menyentuh `Core.runtime`,
`Agents.executor`, `Agents.sandbox`, atau `AnalysisPipeline` — `GoalPlanner`
berjalan sepenuhnya di atas `ServiceSkill` (L13), independen dari jalur
produksi `StockAgent → RuntimeAnalysisPipeline → Runtime →
AnalysisPipeline`.

---

## 2. File yang Ditambah / Diubah

| File | Jenis | Catatan |
| --- | --- | --- |
| `Orchestration/planner.py` | **Baru** | `GoalPlannerError`, `Goal`, `PlanStep`, `ExecutionPlan`, `GoalPlanner` (constructor + 4 method: `build_plan`, `execute_plan`, `accumulate_context`, `translate_metadata`) |
| `Core/composition_root.py` | **Diubah (additive)** | Import `Orchestration.planner.GoalPlanner`; `ApplicationGraph` mendapat field baru `goal_planner: GoalPlanner`; fungsi baru `_build_goal_planner(service_skills)`; satu baris tambahan di `build_application()` untuk memanggilnya dan menaruh hasilnya ke `ApplicationGraph` |
| `Tests/test_stage_l15_planner.py` | **Baru** | Regression suite Step 8 — lihat §6 laporan sebelumnya (47/47 PASS) |

Tidak ada file lain yang disentuh. Tidak ada production bug yang
ditemukan selama Step 8, sehingga tidak ada perubahan kode produksi di
luar dua file di atas (yang sudah selesai sejak Step 1–7).

---

## 3. Yang Sengaja Tidak Diimplementasikan (Out of Scope, Phase 1)

Semua ini adalah keputusan sadar, bukan kelalaian:

- **Observation, Memory, Reflection** — belum ada integrasi sama sekali.
  `GoalPlanner` tidak tahu-menahu tentang layer-layer ini; Planner murni
  bekerja di atas `Goal.metadata` yang diberikan di awal.
- **Goal schema yang lebih kaya** — `Goal` hanya berisi `metadata: Dict[str, Any]`.
  Tidak ada notion "intent", "task type", atau deskripsi bahasa natural.
  Terjemahan dari permintaan pengguna (natural language) → `Goal` belum
  ada di stage manapun.
- **Retry / skip policy** — `execute_plan()` tidak retry apa pun. Business
  failure (`ServiceResult.fail()`) dikumpulkan apa adanya, tidak
  mempengaruhi step berikutnya.
- **Replanning / branching / DAG paralel** — urutan eksekusi 100% mengikuti
  urutan `ExecutionPlan.steps` yang sudah dibangun `build_plan()`; tidak
  ada percabangan atau eksekusi paralel.
- **Blocked-steps tracking** — skill yang tidak reachable oleh
  forward-chaining closure hanya di-*log* (`logger.warning`) lalu dibuang
  begitu saja dari plan. Tidak ada field `blocked_steps` di
  `ExecutionPlan` yang menyimpan *kenapa* sebuah skill dikecualikan — ada
  TODO eksplisit di `build_plan()` untuk ini (lihat §4 debt di bawah).
- **Translation engine umum** — `translate_metadata()` hanya berisi satu
  aturan hardcoded (`PRICE → ENTRY_PRICE` untuk `risk_management_service`).
  Tidak ada mapping registry, pattern matching, atau inferensi generik.
- **Wiring ke jalur produksi** — `goal_planner` ada di `ApplicationGraph`
  tapi tidak dipanggil oleh `StockAgent`, tidak diregistrasikan sebagai
  Tool, dan tidak menyentuh `RuntimeAnalysisPipeline`/`AnalysisPipeline`.
  Ia murni "tersedia untuk dipakai stage berikutnya".

---

## 4. Keputusan Arsitektur yang Terkunci (LOCKED)

1. **`ServiceSkill` tetap thin wrapper** (keputusan L13, tidak diubah di
   L15) — `GoalPlanner` tidak pernah membangun `ServiceSkill` sendiri,
   hanya menerimanya lewat dependency injection dan memanggil
   `.metadata` / `.execute(...)`.
2. **`SkillMetadata` tetap murni deklaratif** — `build_plan()` hanya
   membaca `required_inputs`/`produced_outputs`, tidak pernah
   memvalidasi, mem-parsing, atau menyimpulkan sendiri dependency graph.
3. **`AnalysisPipeline` tetap fixed pipeline, tidak dipecah** — L15 tidak
   menyentuh, mengimpor dari, atau diimpor oleh
   `Core.analysis_pipeline`, `Orchestration.runtime_analysis_pipeline`,
   atau kode Runtime/Agent mana pun.
4. **`GoalPlanner` sepenuhnya additive** — dikonstruksi dan dipakai hanya
   oleh stage masa depan yang belum ditentukan; tidak ada satu pun jalur
   produksi yang berubah perilakunya akibat keberadaan `GoalPlanner`.
5. **`CompositionRoot` adalah satu-satunya tempat wiring `GoalPlanner`**
   — `_build_goal_planner()` membangun `GoalPlanner` di atas
   `service_skills` yang **sama persis** (bukan instance/dict baru),
   sama seperti pola `_build_service_skills()` di L13.
6. **`build_plan()` murni & non-eksekutif** — tidak pernah memanggil
   `ServiceSkill.execute(...)`. Satu-satunya pertanyaan yang diajukan ke
   setiap skill adalah "apakah `required_inputs`-nya sudah tersedia di
   `available`?" — tidak ada percabangan khusus per nama service.
7. **Urutan plan deterministik** — skill yang satisfied di ronde yang
   sama diurutkan berdasarkan `service_name` (alfabetis), bukan urutan
   insersi dict. `Goal` yang identik selalu menghasilkan `ExecutionPlan`
   yang identik (dibuktikan di Group 2 & Group 7 regression suite).
8. **Context accumulation searah** — `accumulate_context()` hanya
   mengalir maju (step sebelumnya → step berikutnya), tidak pernah
   sebaliknya. `translate_metadata()` hanya mempengaruhi metadata yang
   dilihat *step yang sedang berjalan*, tidak pernah "bocor" ke context
   yang diakumulasi untuk step-step berikutnya.
9. **Business failure vs. unexpected exception dibedakan tegas** —
   `ServiceResult.fail()` dikumpulkan seperti biasa (bukan error);
   exception tak terduga dari `ServiceSkill.execute(...)` selalu
   dibungkus jadi `GoalPlannerError`, tidak pernah dibiarkan propagate
   mentah.
10. **`goal.metadata` tidak pernah berubah** — baik `build_plan()` maupun
    `execute_plan()` tidak pernah mutate dict `metadata` milik `Goal`
    aslinya; semua akumulasi/translasi bekerja di atas dict baru.

---

## 5. Technical Debt yang Masih Terbuka

Diwarisi dari stage sebelumnya (tidak diperbaiki di L15, di luar
lingkup):

- **R3 (L13)** — `GenericSandbox`'s fallback `str(result)` untuk nilai
  Tool non-JSON-serializable masih berlaku; `ServiceResult` yang
  dikembalikan `ServiceSkill.execute()` bukan JSON-serializable. Belum
  relevan untuk `GoalPlanner` karena `GoalPlanner` tidak lewat
  `Executor`/Sandbox sama sekali, tapi tetap tercatat sebagai debt aktif
  di layer `ServiceSkill`.
- **R4 (L13)** — Tidak ada context accumulation *di level* `ServiceSkill`
  itu sendiri (setiap `execute()` independen). `GoalPlanner` **tidak**
  mewarisi debt ini — `accumulate_context`/`translate_metadata` di
  Planner justru dibangun spesifik untuk mengisi celah ini, tapi hanya
  untuk pemanggilan lewat `GoalPlanner`, bukan pemanggilan langsung ke
  `ServiceSkill`.

Baru, muncul dari L15 Phase 1 sendiri:

- **Blocked-steps tidak dipertahankan** — skill yang gagal masuk plan
  hanya di-log, alasannya (`missing required_inputs`) tidak disimpan di
  `ExecutionPlan`. Ada TODO eksplisit di kode untuk field
  `blocked_steps` di masa depan (dibutuhkan kalau nanti ada
  Reflection/replanning yang perlu tahu *kenapa* sebuah skill
  dikecualikan tanpa menjalankan ulang closure-nya).
- **`translate_metadata` single-purpose** — hanya menangani satu kasus
  (`risk_management_service`). Kalau ada Service lain di masa depan yang
  butuh translasi serupa (misalnya precondition service lain yang juga
  butuh "derived field" dari context), aturan baru harus ditambahkan
  satu per satu secara eksplisit — belum ada mekanisme generik.
- **`Goal` minim sekali** — tidak ada validasi terhadap `metadata` yang
  diberikan (tipe, kelengkapan, dsb.). Kalau `Goal` dibangun otomatis
  dari Observation/Reasoning layer nanti, validasi tersebut belum ada
  tempatnya.
- **Tidak ada limit/guard pada fixed-point loop** — `build_plan()`
  secara teoretis bisa berjalan sebanyak jumlah skill (worst case), yang
  aman untuk ukuran registry saat ini (11 service) tapi belum
  di-benchmark untuk skala yang jauh lebih besar.

---

## 6. Rekomendasi Ruang Lingkup L16

`GoalPlanner` (L15) sekarang berdiri sebagai layer baru yang solid,
additive, dan teruji (47/47), tanpa menyentuh fondasi L11–L13. Tiga opsi
yang dipertimbangkan:

1. **Observation Layer** (sesuai roadmap AIOS)
2. **Goal Generation / Reasoning Layer**
3. **Planner Runtime Integration** (menggantikan `AnalysisPipeline`
   secara bertahap di jalur produksi)

Urutan yang direkomendasikan: **Observation → Memory → Reflection**,
mengikuti roadmap AIOS yang sudah ditetapkan sebelumnya, dengan alasan:

- `GoalPlanner` saat ini membangun & menjalankan plan dari `Goal.metadata`
  yang **sudah tersedia di awal** — belum ada sumber yang mengisi
  `Goal.metadata` itu secara otomatis dari dunia luar (harga terkini,
  status portofolio, sinyal pasar, dsb.). Observation Layer mengisi
  celah itu tanpa perlu menyentuh `GoalPlanner` sama sekali (tetap
  additive, sama seperti pola L13→L15).
- Menunda **Planner Runtime Integration** (opsi 3) masuk akal karena itu
  satu-satunya opsi yang menyentuh jalur produksi
  (`StockAgent → RuntimeAnalysisPipeline → Runtime → AnalysisPipeline`)
  — risikonya jauh lebih tinggi dan sebaiknya baru dilakukan setelah
  Observation/Memory/Reflection matang, supaya `GoalPlanner` yang
  menggantikan `AnalysisPipeline` nanti sudah punya konteks yang jauh
  lebih kaya daripada sekadar `Goal.metadata` statis.
- **Goal Generation/Reasoning** logikanya berada *di atas* Observation +
  Memory (butuh tahu apa yang sedang terjadi dan apa yang sudah pernah
  terjadi sebelum bisa merumuskan Goal baru) — jadi baru masuk akal
  setelah keduanya ada.

Setiap stage berikutnya sebaiknya tetap mengikuti pola yang sudah
terbukti aman di L11–L15: **additive-only, tidak menyentuh jalur
produksi, batas tanggung jawab jelas, dan diakhiri dengan regression
suite + handover-nya sendiri** sebelum stage berikutnya dimulai.
