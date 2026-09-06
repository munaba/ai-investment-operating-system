# AIOS Day-Trade Decision Copilot — Roadmap

## Product decision

AIOS akan menjadi **asisten pengambil keputusan day trade pribadi**, bukan bot eksekusi otomatis dan bukan penasihat investasi. Sistem mengumpulkan bukti, menyaring kandidat, membuat trade plan, menjaga disiplin risiko, mencatat keputusan pengguna, dan melakukan evaluasi. Keputusan serta order final tetap dilakukan pengguna di broker.

Konsekuensinya:

- Broker tidak diperlukan untuk MVP dan tidak boleh menghalangi startup.
- `paper trading` tetap tersedia sebagai simulator terpisah.
- Live broker, API credential broker, dan autonomous buy/sell berada di luar roadmap ini.
- Telegram adalah channel pertama; Discord ditunda sampai ada kebutuhan multi-channel atau multi-user yang nyata.

## Audit baseline yang dipakai

Roadmap ini diturunkan dari isi arsip `Zip.zip`, khususnya `Master Prompt (Roadmap).md`, laporan Activation 2, 7, dan 12, serta struktur source saat ini.

### Kapabilitas yang sudah ada dan layak dipakai ulang

- Provider: `Providers/ollama.py` dan provider Gemini.
- Core kontrol: event/runtime, sandbox, approval, tool registry, permission enforcement, scheduler, event bus, workflow dan autonomous host.
- Trading: market analysis, ranking, risk management, paper execution, performance, journal/memory records, SQLite persistence, dan notification Telegram.
- Safety: human approval, kill-switch, audit approval, backup, reconciliation, dan failure handling notification.

### Temuan yang menentukan urutan kerja

- Sistem masih berorientasi command-line dan domain trading; belum ada inbound conversational channel/sesi pengguna.
- `ConversationMemory` pada `Agents/memory.py` bersifat in-memory dan terbatas pada umur proses. Memory personal yang dapat diambil kembali secara aman belum menjadi alur produk end-to-end.
- Activation 7 menyatakan sistem **tidak ready for live**. Bukti data pasar nyata dari Yahoo Finance masih diblokir oleh jaringan pada audit tersebut; status error harus tetap eksplisit dan tidak boleh berubah menjadi sinyal.
- Activation 12 menyatakan tool permission, scheduler, memory record, dan self-diagnostic sudah tersedia. Multi-agent sengaja tidak ditambah karena belum ada manfaat produk yang terukur.

## Prinsip desain yang dikunci

1. **Evidence before recommendation.** Tidak ada BUY/SELL/WAIT bila data, analisis, atau risk calculation gagal. Gunakan status seperti `DATA_ERROR`, `INSUFFICIENT_DATA`, `ANALYSIS_FAILED`, `RISK_REJECTED`, dan `NO_TRADE`.
2. **No trade adalah hasil valid.** AIOS tidak boleh dipaksa mengeluarkan setup.
3. **User decides, AIOS records.** AIOS boleh memberi decision brief; ia tidak boleh mengirim order broker.
4. **Risk-first.** Stop loss, invalidation, ukuran risiko, batas loss harian, dan batas jumlah trade ditampilkan sebelum ide entry.
5. **Fail closed.** Channel, tool, data provider, atau credentials yang gagal harus menghasilkan error yang terlihat, bukan fallback ke aksi finansial.
6. **Satu workflow nyata sebelum perluasan.** Fokus pertama adalah IDX day-trade decision support. Crypto, forex, US market, dashboard, Discord, vision, dan multi-agent tidak ditambah sebelum workflow inti terbukti.

## Target workflow MVP

```text
Pesan Telegram pengguna
→ autentikasi user & session
→ intent (scan / plan / journal / review)
→ data pasar + validasi timestamp/kualitas
→ analisis & ranking lintas watchlist
→ risk gate
→ decision brief (atau explicit no-trade/error)
→ pengguna menyimpan / menolak / mencatat hasil
→ jurnal dan evaluasi harian
```

Contoh brief harus memuat: instrumen, timeframe, status, evidence dan timestamp, entry zone, invalidation/stop, target, rasio risk/reward, risk per trade, alasan setup, risiko/news flag, dan alasan `NO_TRADE` bila tidak layak.

## Roadmap implementasi

### Phase 0 — Re-baseline dan boundary produk

**Objective:** memastikan source, database, startup, dan jalur CLI benar-benar dapat direproduksi sebelum perubahan produk.

**Work:**

- Ekstrak repositori ke workspace kerja tanpa mengganti artefak sumber.
- Jalankan `doctor`, `init`, migration, dan test suite sesuai instruksi aktual proyek.
- Buat peta kontrak aktual untuk `composition_root`, provider selector, `MarketAnalysisAgent`, `RuntimeAnalysisPipeline`, scheduler, Telegram notification, approval/permission, serta persistence journal.
- Catat kondisi external dependency/data provider sebagai `READY`, `OPTIONAL MISSING`, atau `BLOCKED`.
- Tambahkan konfigurasi mode produk `decision_copilot`; mode ini menonaktifkan broker/live execution secara eksplisit.

**Acceptance gate:** satu laporan baseline berisi command, hasil nyata, database path, test yang valid/gagal, dan blocker eksternal. Tidak ada klaim readiness live.

### Phase 1 — Decision Brief contract

**Objective:** membuat output trading yang konsisten, dapat diaudit, dan aman sebelum ada chat interface.

**Work:**

- Definisikan result model tunggal untuk `SUCCESS`, `NO_TRADE`, dan semua status gagal eksplisit.
- Bangun `DecisionBrief` dari hasil analisis/ranking/risk yang sudah ada; jangan menduplikasi engine strategi.
- Wajibkan evidence, source, data timestamp, confidence, entry/invalidation/target bila tersedia, dan reason code.
- Tambahkan `DecisionPolicy`: menolak brief jika evidence kurang, data stale, risk calculation tidak valid, atau loss limit sesi telah tercapai.
- Tambahkan command CLI read-only untuk menghasilkan dan menampilkan brief dari watchlist.

**Acceptance gate:** beberapa ticker valid mendapat brief berbeda; ticker gagal tidak masuk ranking dan tidak menghasilkan rekomendasi tersamarkan; semua brief dapat dibaca kembali dari database.

### Phase 2 — Risk ledger dan trading journal

**Objective:** AIOS membantu disiplin keputusan, bukan hanya menghasilkan sinyal.

**Work:**

- Tambah jurnal keputusan: brief yang diterima, aksi pengguna (`TAKE`, `SKIP`, `WAIT`), alasan, harga eksekusi manual opsional, dan hasil penutupan.
- Konfigurasi batas pribadi: modal referensi, risiko maksimum per trade, loss harian, jumlah trade maksimum, cooldown loss streak, dan instrumen yang diizinkan.
- Hitung metrik jurnal secara eksplisit: planned R, realised R bila tersedia, adherence terhadap stop, dan alasan pelanggaran.
- Pisahkan jurnal manual dari `PaperTradingEngine`; jangan membuat order/trade paper tanpa perintah eksplisit pengguna.

**Acceptance gate:** satu rangkaian plan → keputusan → hasil → review tersimpan, bertahan setelah restart, dan limit risiko menolak plan yang melanggar aturan.

### Phase 3 — Telegram inbound MVP

**Objective:** menjadikan AIOS berguna dari ponsel dengan satu user yang diizinkan.

**Work:**

- Implementasikan adapter inbound Telegram terpisah dari notification channel yang ada.
- Whitelist satu atau beberapa Telegram `chat_id`; semua pengirim lain ditolak dan dicatat tanpa memproses command.
- Buat session router yang mengubah pesan menjadi intent terbatas: `/scan`, `/plan SYMBOL`, `/journal`, `/review`, `/help`.
- Gunakan format balasan yang deterministik terlebih dahulu; LLM tidak boleh menentukan risk limit atau melewati intent policy.
- Kegagalan pengiriman/polling wajib terlog dan terlihat melalui `doctor`/self-diagnostic.

**Acceptance gate:** pesan dari chat yang diizinkan menjalankan satu intent read-only dan menerima brief; chat lain tidak punya akses; restart tidak menghilangkan jurnal atau konfigurasi.

### Phase 4 — Ollama copilot layer

**Objective:** membuat interaksi terasa seperti asisten tanpa memberi model wewenang finansial.

**Work:**

- Pakai `OllamaProvider` yang sudah ada sebagai provider default opsional, melalui konfigurasi lokal.
- LLM hanya melakukan klasifikasi intent, penjelasan evidence, ringkasan jurnal, dan tanya-jawab atas data yang tersedia.
- Tool schema untuk model bersifat allowlist dan read-only pada fase ini.
- Simpan percakapan relevan serta preferensi pengguna secara durable; retrieval harus menyertakan sumber dan tidak mengubah record trading.
- Tambahkan fallback deterministik: bila Ollama down, command inti tetap dapat berjalan dan menjelaskan error provider.

**Acceptance gate:** AIOS dapat menjawab pertanyaan seperti “kenapa plan ini ditolak?” berdasarkan brief/risk ledger yang benar, tanpa mengarang data atau memberi order.

### Phase 5 — Proactive routine dan observability

**Objective:** AIOS secara konsisten membantu rutinitas day trade tanpa tindakan otomatis.

**Work:**

- Gunakan scheduler yang sudah ada untuk pre-market checklist, watchlist scan, alert data/news-risk, market-close recap, dan daily review.
- Semua alert harus idempotent, time-zone aware, mudah dinonaktifkan, dan tidak mengandung ajakan pasti untuk membeli/menjual.
- Tambahkan health summary: provider/data feed status, timestamp data terakhir, scheduler status, Telegram status, dan kill-switch status.
- Tambahkan audit event untuk command, brief, approval/skip, dan error.

**Acceptance gate:** satu hari kerja simulasi menghasilkan pre-market brief, alert yang sah, market-close recap, dan daily review tanpa duplikasi atau tindakan eksekusi.

### Phase 6 — Paper validation (opsional, setelah MVP stabil)

**Objective:** menguji apakah disiplin keputusan dan rules engine konsisten tanpa uang sungguhan.

**Work:**

- Hubungkan `DecisionBrief` yang disetujui secara eksplisit ke paper-trading flow yang sudah ada.
- Pertahankan transaction boundary, approval, reconciliation, backup, dan restart recovery dari activation sebelumnya.
- Bandingkan plan dengan hasil paper; jangan gunakan hasil tersebut sebagai janji performa.

**Acceptance gate:** paper order yang disetujui mengubah cash, position, fee, dan journal secara atomik; failure tidak menciptakan state parsial; production data provider tetap menghasilkan error eksplisit bila tidak tersedia.

## Ditunda dengan sengaja

- Broker atau live execution.
- Discord adapter.
- Multi-agent dan self-modifying skills.
- Crypto, forex, US market, dan strategi tambahan.
- Dashboard web/visual yang besar.
- Akses email, filesystem luas, atau kredensial pihak ketiga.

## Definition of Done untuk MVP

MVP selesai hanya jika satu pengguna yang diizinkan dapat, dari Telegram, meminta scan/plan, menerima **brief berbasis evidence atau alasan no-trade/error**, menyimpan keputusan dan hasilnya, lalu menerima review harian yang dapat ditelusuri setelah restart. Tidak ada broker, API key broker, atau eksekusi order otomatis dalam jalur tersebut.

## Urutan eksekusi sekarang

1. Phase 0: ekstrak repo, reproduksi baseline, dan verifikasi kontrak aktual.
2. Phase 1: buat `DecisionBrief` + policy status yang eksplisit.
3. Phase 2: risk ledger dan journal sebagai pembeda utama AIOS dari scanner biasa.
4. Phase 3: Telegram inbound dengan command terbatas.

Fase berikutnya tidak dimulai sebelum acceptance gate fase sebelumnya terbukti dengan command/test/state nyata.
