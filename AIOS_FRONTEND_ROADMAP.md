# AIOS Frontend Dashboard — Roadmap

## Prinsip dasar (jangan dilanggar)

- **Read-only.** Frontend ini tidak pernah submit trade, journal, atau
  ubah risk limits. Semua write tetap lewat CLI (`main.py ...`) atau
  Hermes. Ini bukan aturan sembarangan — ini menjaga supaya approval
  flow (risk-limits check, RISK_REJECTED gate, dll.) yang sudah ada
  di `Business/`/`Services/` tidak diduplikasi atau dilewati oleh
  jalur baru yang belum teruji.
- **Tidak boleh mengganggu observation window Phase H.** Project ini
  jalan di luar rutinitas pagi brief→journal, bukan menggantikannya.
- **Additive-only terhadap AIOS.** Frontend membaca `data/investment_platform.db`
  langsung (SQLite) — tidak mengubah schema, tidak menulis migration
  baru, tidak menyentuh kode `Core/`, `Business/`, `Services/`.
- Setiap tahap harus *terlihat jadi* dalam hitungan jam–hari, bukan
  minggu — supaya progres kerasa dan tidak jadi rabbit hole.

## Stack

**Streamlit** (Python murni, cocok untuk dashboard baca-data, cepat
untuk versi awal). Kalau nanti v1–v3 kerasa nyaman dan kamu mau
tampilan lebih custom, opsional pindah ke FastAPI + React di v4 —
tapi jangan mulai dari situ.

---

## Tahap 0 — Setup & koneksi read-only (target: <1 jam)

- Project folder terpisah, misal `aios_dashboard/`, di luar folder
  AIOS utama (biar jelas ini bukan bagian dari phase-locked codebase).
- `pip install streamlit pandas`
- Koneksi read-only ke `data/investment_platform.db` pakai
  `sqlite3.connect(..., uri=True)` dengan mode `?mode=ro` — supaya
  secara teknis pun mustahil menulis lewat dashboard ini meski ada
  bug di kode kamu sendiri.
- **Acceptance:** halaman Streamlit kosong yang berhasil `SELECT 1`
  dari DB tanpa error.

## Tahap 1 — Journal & Brief viewer (target: 1 sesi kerja)

- Tabel journal terbaru: baca dari `journal_entries` (decision,
  decided_at, risk_policy, note, planned_r) — urut dari terbaru.
- Detail brief per entry: join ke `decision_briefs` (status, entry,
  stop, target, source_snapshot_id, generated_at) lewat brief_id.
- Filter simpel: by simbol, by decision (TAKE/SKIP/WAIT), by tanggal.
- **Acceptance:** kamu bisa lihat riwayat journal hari ini di
  browser, tanpa buka CLI.

## Tahap 2 — Observation window & evidence status (target: 1 sesi kerja)

- Tampilkan `operator_observation_windows` (window aktif, mulai
  kapan, status).
- Tampilkan ringkasan report `sustained-use` yang biasanya kamu minta
  manual dari Hermes — availability, freshness, dedup, adherence,
  paper reconciliation, dll. — sebagai kartu status per dimensi
  (AVAILABLE / NO_DATA / INSUFFICIENT_DATA / NOT_VERIFIABLE), warna
  beda per status, **tanpa** dashboard ini yang menyimpulkan
  `human_decision` — itu tetap manual, kamu isi lewat CLI kapan
  waktunya.
- **Acceptance:** kamu bisa lihat progres observation window (sudah
  berapa hari, berapa journal entries) sekali lihat, tanpa nanya
  Hermes tiap kali.

## Tahap 3 — Paper positions & scheduler health (target: 1 sesi kerja)

- Tabel `positions` (open/closed), `orders`, `trades` — status
  posisi paper saat ini, P&L kalau ada.
- Ringkasan scheduler health terakhir (dari job run log/notification
  log kalau ada tabelnya — cek `Database/migrations_scheduler.py`
  buat nama tabel pastinya sebelum implementasi).
- **Acceptance:** satu layar nunjukin "kondisi AIOS hari ini" — posisi
  terbuka, scheduler jalan atau nggak, data fresh atau nggak.

## Tahap 4 — Polish & daily-use quality (target: fleksibel, opsional)

- Auto-refresh berkala (polling, bukan websocket).
- Export ringkas (CSV/markdown) buat laporan mingguan yang kamu baca
  sendiri saat mau isi `human_decision` nanti.
- Styling supaya enak dipakai tiap pagi.
- Ini tahap "nice to have" — boleh disetop kapan saja begitu Tahap
  1–3 sudah cukup buat kebutuhan harian kamu.

---

## Definition of done keseluruhan

Frontend ini dianggap "jadi" ketika: kamu bisa buka satu halaman
browser tiap pagi, lihat brief/journal/posisi/status observation
window tanpa perlu tanya Hermes atau buka CLI manual — dan tetap
memutuskan TAKE/SKIP/WAIT serta submit lewat CLI/Hermes seperti
biasa. Dashboard ini alat bantu lihat, bukan alat bantu eksekusi.
