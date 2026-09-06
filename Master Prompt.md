# MASTER PROMPT — AIOS PRODUCT ACTIVATION ROADMAP

Saya sedang membangun AIOS pribadi seperti Hermes/OpenClaw, tetapi berfokus sebagai alat bantu menghasilkan keputusan dan mengelola aktivitas trading/investasi.

Target market bertahap:

1. Saham Indonesia.
2. Saham Amerika Serikat.
3. Crypto.
4. Forex.

AIOS ini digunakan untuk pribadi dan harus bisa digunakan secepat mungkin. Fokus utama bukan memperbanyak modul, agent, abstraction, atau test kosmetik. Fokus utamanya adalah membuat satu workflow trading nyata bekerja secara end-to-end, dapat diaudit, aman, dan dapat diukur.

AIOS tidak boleh menjanjikan profit. Sistem harus membantu analisis, pengambilan keputusan, pengelolaan risiko, paper trading, evaluasi performa, dan nantinya eksekusi live dengan persetujuan pengguna.

---

# A. KONDISI PROYEK BERDASARKAN AUDIT SOURCE CODE

Gunakan informasi berikut sebagai baseline. Jangan menganggap sprint lama sudah benar hanya karena test-nya hijau.

## 1. Scanner belum menghasilkan analisis valid

Pada composition root, `MarketAnalysisAgent` dibangun dengan `MarketAnalysisSkill` yang tidak memiliki resolver/tool yang diperlukan.

Akibatnya:

* analysis dapat bernilai `None`;
* kegagalan analisis ditahan;
* downstream mengubah data kosong menjadi rekomendasi defensif;
* hasil scan menjadi `SELL`, `LOW`, `rank=1`;
* semua simbol dapat menghasilkan output identik.

Kegagalan data tidak boleh berubah menjadi sinyal trading valid.

Status yang benar untuk kegagalan adalah seperti:

* `DATA_ERROR`;
* `ANALYSIS_FAILED`;
* `INSUFFICIENT_DATA`;
* `SKIPPED`.

## 2. Ranking belum benar-benar melakukan ranking

Scanner memproses satu ticker per satu pemanggilan agent.

Akibatnya:

* setiap ticker dapat memperoleh `rank=1`;
* setiap ticker dapat memperoleh `priority=1`;
* `RankingEngine` saat ini lebih menyerupai normalizer;
* sorting lintas seluruh watchlist belum benar-benar dilakukan.

Ranking harus dilakukan setelah semua hasil analisis valid dikumpulkan.

## 3. PaperTradingEngine belum stateful secara end-to-end

Alur saat ini pada dasarnya hanya:

```text
OrderLifecycleService
→ ExecutionService
→ Trade
```

Engine belum menjamin:

* cash berkurang ketika BUY;
* cash bertambah ketika SELL;
* Position dibuat atau diperbarui;
* average price diperbarui;
* realized P/L dihitung;
* fee dan tax dihitung;
* lot IDX divalidasi;
* oversell dicegah;
* insufficient cash dicegah sebelum fill;
* seluruh operasi berada dalam satu transaction.

Dalam pengujian nyata, Order dan Trade dapat tercipta tetapi cash tidak berubah dan Position tetap kosong.

## 4. Filled Order dapat tidak konsisten dengan Trade

Order dapat memiliki:

```text
status = FILLED
filled_price = 0
filled_quantity = 0
```

sementara Trade memiliki harga dan quantity yang benar.

Order dan Trade harus konsisten.

## 5. Realized P/L belum dihitung

`PositionManager` masih mempertahankan `realized_pnl=0`.

Akibatnya:

* win rate tidak bermakna;
* expectancy tidak bermakna;
* profit factor tidak bermakna;
* performance summary tidak mencerminkan hasil trading nyata.

## 6. Equity curve belum tersedia

Belum ada production flow yang secara konsisten menghasilkan:

* portfolio snapshots;
* daily performance;
* equity curve;
* drawdown series.

`PerformanceSummaryService` belum memiliki input production yang lengkap.

## 7. Runtime masih dapat memakai capital nol

Ada jalur runtime yang meneruskan:

```python
capital = 0
```

Position sizing tidak boleh menggunakan nilai nol atau fallback ambigu ketika account paper yang sebenarnya tersedia.

## 8. Fee, tax, lot, stop loss, dan take profit belum operasional

Belum ada implementasi production lengkap untuk:

* IDX lot size 100;
* broker buy fee;
* broker sell fee;
* pajak penjualan;
* stop-loss trigger;
* take-profit trigger;
* forced exit;
* risk limit sebelum eksekusi.

## 9. Notification sudah di-wire tetapi belum operasional

Notification abstraction sudah tersedia:

* NotificationEvent;
* NotificationBuilder;
* NotificationDispatcher;
* NotificationManager;
* TelegramNotificationChannel.

Namun terdapat masalah:

* Telegram membutuhkan token dan chat ID melalui ServiceContext;
* context factory belum menjamin credential tersedia;
* `NotificationService.execute()` dapat mengembalikan `ServiceResult.fail`;
* Telegram adapter dapat mengabaikan hasil gagal tersebut;
* caller dapat menganggap notifikasi berhasil walaupun tidak terkirim;
* belum ada runtime event bernilai yang memicu notification.

## 10. Startup belum reproducible

Belum tersedia secara konsisten:

* dependency manifest resmi;
* satu migration runner;
* database bootstrap;
* default paper account;
* CLI command yang lengkap;
* command-specific environment validation;
* startup yang dapat digunakan dari instalasi baru.

Beberapa migration masih harus dijalankan manual.

## 11. Multi-market belum nyata

Nama market/schema mungkin sudah menyebut:

* IDX;
* US stocks;
* crypto;
* forex.

Namun implementasi market-specific belum lengkap:

* symbol normalization;
* trading hours;
* lot/quantity precision;
* fee model;
* settlement;
* leverage;
* margin;
* rollover;
* exchange/broker adapter;
* market-specific risk.

Jangan menganggap multi-market tersedia hanya karena enum atau schema sudah ada.

---

# B. TUJUAN PRODUK YANG HARUS DICAPAI

Workflow utama yang harus berhasil:

```text
Command pengguna
→ ambil data pasar
→ validasi data
→ analisis dengan evidence
→ ranking lintas watchlist
→ rekomendasi
→ risk validation
→ persetujuan pengguna
→ paper execution atomik
→ update cash dan position
→ simpan audit trail
→ hitung performa
→ kirim notification
```

Setiap tahap harus dapat:

* dijalankan dari command yang jelas;
* gagal secara eksplisit;
* menyimpan state ke database;
* dipulihkan setelah restart;
* diuji sebagai alur end-to-end.

---

# C. ATURAN KERJA WAJIB

## 1. Source code adalah sumber kebenaran

Sebelum membuat prompt implementasi:

1. Baca file aktual.
2. Cari class atau service yang sudah ada.
3. Periksa constructor aktual.
4. Periksa return type aktual.
5. Periksa composition root.
6. Periksa test aktual.
7. Periksa migration dan schema aktual.

Jangan membuat nama method, constructor, field, atau dependency berdasarkan asumsi.

Contoh kesalahan yang dilarang:

```python
notification_service.kirim_telegram()
```

ketika source aktual hanya memiliki:

```python
notification_service.execute(context)
```

## 2. Jangan langsung mengunci desain sebelum audit

Urutan yang benar:

```text
Audit kontrak aktual
→ temukan gap
→ pilih perubahan paling kecil
→ baru buat LOCKED DECISION
```

Bukan:

```text
Buat LOCKED DECISION
→ ternyata source berbeda
→ membuat workaround baru
```

## 3. Jangan menilai selesai hanya dari jumlah test

Dilarang menetapkan target seperti:

```text
minimal 40 assertion
minimal 50 assertion
```

Jumlah assertion bukan ukuran kesiapan produk.

Test harus berdasarkan skenario dan risiko.

Minimal jenis test:

* unit calculation;
* integration repository/database;
* end-to-end workflow;
* failure path;
* rollback;
* restart/recovery;
* state consistency;
* regression test relevan.

## 4. Definition of Done harus berbasis perilaku nyata

Sebuah tahap belum selesai hanya karena:

* file berhasil dibuat;
* import berhasil;
* protocol terpenuhi;
* dependency ter-wire;
* unit test hijau.

Tahap hanya selesai jika acceptance gate production-nya terbukti.

Contoh paper BUY dianggap berhasil hanya jika:

```text
Order FILLED
Trade tercatat
Cash berkurang
Position bertambah
Fee tercatat
Filled price dan quantity konsisten
State tetap benar setelah restart
```

## 5. Tidak boleh mengubah error menjadi sinyal trading

Dilarang:

```text
data kosong → SELL
analisis gagal → LOW confidence
provider gagal → WAIT
```

tanpa status error eksplisit.

Gunakan result model seperti:

```text
SUCCESS
DATA_ERROR
ANALYSIS_FAILED
INSUFFICIENT_DATA
RISK_REJECTED
EXECUTION_FAILED
```

Hanya hasil `SUCCESS` yang boleh masuk ranking atau execution.

## 6. Satu perubahan harus menghasilkan satu kemampuan produk

Hindari membuat wrapper berlapis tanpa perubahan perilaku.

Setiap step harus menjawab salah satu pertanyaan nyata:

* Apakah aplikasi dapat dijalankan?
* Apakah data pasar berhasil diambil?
* Apakah analisis valid?
* Apakah saham dapat dibandingkan?
* Apakah order mengubah portfolio?
* Apakah hasil dapat dihitung?
* Apakah pengguna menerima notifikasi?

## 7. Jangan memperluas scope

Sebelum IDX workflow selesai, jangan mengerjakan:

* multi-agent baru;
* skill registry baru;
* vector memory lanjutan;
* WorkflowRuntime kompleks;
* dashboard estetis;
* Discord;
* US stocks;
* crypto;
* forex;
* live auto-trading.

## 8. Human approval tetap wajib

AIOS adalah analyst dan operating assistant.

Sebelum live execution tersedia:

```text
AI recommendation
→ risk validation
→ user approval
→ execution
```

Jangan membuat autonomous live execution pada activation awal.

## 9. Jangan menyembunyikan kegagalan

Exception atau failed result harus:

* dikembalikan;
* disimpan;
* ditampilkan;
* atau dilaporkan secara eksplisit.

Jangan mengabaikan:

```python
ServiceResult.success is False
```

## 10. Jangan menyebut “selesai” tanpa bukti

Gunakan status:

* `STRUCTURE READY`;
* `UNIT VERIFIED`;
* `INTEGRATION VERIFIED`;
* `E2E VERIFIED`;
* `PRODUCTION PATH VERIFIED`;
* `BLOCKED`.

Hanya gunakan `PRODUCTION PATH VERIFIED` jika alur nyata sudah dijalankan.

---

# D. FORMAT WAJIB UNTUK SETIAP STEP

Untuk setiap step, hasilkan prompt implementasi dengan struktur berikut:

## 1. Objective

Satu kemampuan produk yang ingin dicapai.

## 2. Current Source Findings

Tuliskan file, class, method, dan kontrak aktual yang relevan.

Jangan membuat bagian ini dari asumsi.

## 3. Gap

Jelaskan perilaku aktual dan perilaku target.

## 4. Allowed Files

Sebutkan file yang boleh diubah berdasarkan hasil audit.

Jangan terlalu sempit jika perubahan lintas layer memang diperlukan.

## 5. Forbidden Changes

Larang perubahan yang tidak relevan.

## 6. Implementation Requirements

Tuliskan perilaku, bukan hanya nama class.

## 7. Transaction and Failure Rules

Jelaskan:

* kapan rollback;
* kapan error diteruskan;
* kapan result gagal disimpan;
* apa yang tidak boleh berubah jika gagal.

## 8. Test Scenarios

Tidak menggunakan target jumlah assertion.

Gunakan skenario nyata.

## 9. Acceptance Gate

Tuliskan bukti yang harus diberikan sebelum step dinyatakan selesai.

## 10. STOP Rules

STOP hanya untuk konflik kontrak source yang nyata, misalnya:

* dependency tidak tersedia;
* schema tidak mendukung;
* perubahan membutuhkan keputusan domain;
* ada implementasi existing yang duplikatif.

Jangan membuat STOP berdasarkan asumsi.

## 11. Deliverable Report

Minta laporan:

1. File dibaca.
2. File diubah.
3. Perilaku sebelum dan sesudah.
4. Test yang dijalankan.
5. Bukti database/state.
6. Failure path.
7. Risiko.
8. Status: BLOCKED / UNIT VERIFIED / INTEGRATION VERIFIED / E2E VERIFIED.

---

# E. ROADMAP PRODUCT ACTIVATION

Kerjakan roadmap ini secara berurutan.

Jangan melompat ke fase berikutnya sebelum acceptance gate fase sebelumnya terpenuhi.

---

# ACTIVATION 0 — BASELINE DAN PROJECT CONTROL

## Tujuan

Membuat kondisi proyek saat ini dapat direproduksi dan dibandingkan.

## Langkah

### 0.1 Repository baseline

* catat struktur project;
* catat Python version;
* catat dependency yang dipakai;
* catat migration yang tersedia;
* catat entry point;
* catat seluruh test suite;
* catat failure yang sudah ada sebelum perubahan.

### 0.2 Baseline test report

Pisahkan:

* test hijau;
* test gagal;
* test stale;
* test yang hanya menguji struktur;
* test yang menguji production flow.

### 0.3 Product flow map

Dokumentasikan jalur aktual:

```text
startup
scan
analysis
ranking
recommendation
paper order
trade
position
performance
notification
```

Tandai setiap jalur:

* connected;
* disconnected;
* placeholder;
* untested;
* silently failing.

## Acceptance Gate

Tersedia satu baseline report yang menjadi referensi semua perubahan berikutnya.

Tidak ada code feature baru pada Activation 0.

---

# ACTIVATION 1 — REPRODUCIBLE STARTUP

## Tujuan

AIOS dapat dijalankan dari instalasi baru tanpa menjalankan enam script manual atau menebak dependency.

## Langkah

### 1.1 Dependency manifest

Buat manifest resmi berdasarkan import aktual.

Gunakan salah satu yang sesuai project:

* `requirements.txt`;
* atau `pyproject.toml`.

Pisahkan dependency:

* wajib;
* optional;
* provider-specific;
* development/test.

Jangan mewajibkan dependency yang tidak dibutuhkan oleh command tertentu.

### 1.2 Command `doctor`

Buat:

```bash
python main.py doctor
```

Harus memeriksa:

* Python version;
* dependency wajib;
* database path;
* migration status;
* provider availability;
* Telegram config;
* data provider availability.

Hasil harus menunjukkan:

```text
READY
OPTIONAL MISSING
BLOCKED
```

### 1.3 Unified migration runner

Buat satu command:

```bash
python main.py init
```

Harus:

* membuat database;
* menjalankan seluruh migration sesuai urutan;
* idempotent;
* aman dijalankan ulang;
* menampilkan migration version;
* rollback jika migration gagal.

### 1.4 Bootstrap data minimum

`init` dapat membuat:

* default paper account;
* default account currency;
* empty watchlist;
* config template yang aman.

Jangan memasukkan API key ke repository.

### 1.5 Command-specific validation

`scan` tidak boleh gagal hanya karena Telegram belum dikonfigurasi.

`doctor` harus membedakan dependency per fitur.

## Acceptance Gate

Pada environment bersih:

```bash
pip install ...
python main.py doctor
python main.py init
```

berhasil.

Restart aplikasi tidak merusak database.

Migration ulang tidak menduplikasi data.

---

# ACTIVATION 2 — VALID IDX DATA AND SCANNER

## Tujuan

Membuat scanner IDX menghasilkan analisis valid dan membedakan error dari rekomendasi.

## Langkah

### 2.1 Audit canonical analysis path

Bandingkan:

* `MarketAnalysisAgent`;
* `MarketAnalysisSkill`;
* `AnalysisPipeline`;
* technical service;
* fundamental service;
* news service;
* risk service;
* ToolResolver/ToolRegistry.

Pilih jalur yang paling lengkap dan paling sedikit duplikasi.

Jangan langsung membuat pipeline baru.

### 2.2 Perbaiki dependency resolver

Pastikan skill yang membutuhkan tool benar-benar memperoleh resolver/tool yang sama dengan production runtime.

Jangan menggunakan resolver palsu pada production.

### 2.3 Explicit analysis result status

Hasil per ticker harus memiliki status eksplisit:

```text
SUCCESS
DATA_ERROR
ANALYSIS_FAILED
INSUFFICIENT_DATA
```

Field recommendation hanya boleh diisi untuk status `SUCCESS`.

### 2.4 Evidence minimum

Setiap hasil sukses harus menyimpan:

* symbol;
* market;
* data timestamp;
* source/provider;
* current/reference price;
* technical evidence;
* fundamental evidence;
* news/sentiment evidence;
* recommendation;
* confidence numeric;
* risk level;
* reason;
* entry zone jika tersedia;
* stop level jika tersedia.

Jangan mengarang evidence yang tidak dihasilkan source.

### 2.5 Cross-symbol ranking

Proses yang benar:

```text
ambil seluruh watchlist
→ analisis seluruh ticker
→ keluarkan hasil gagal
→ hitung score
→ sort seluruh hasil sukses
→ beri rank unik
```

`RankingEngine` harus benar-benar:

* menghitung score;
* melakukan sorting;
* menghasilkan rank lintas watchlist.

### 2.6 Ranking score transparency

Score harus dapat dijelaskan.

Contoh komponen:

```text
technical score
fundamental score
sentiment score
confidence
risk penalty
data completeness penalty
```

Bobot harus configurable dan tersimpan.

### 2.7 Scanner persistence

Simpan:

* analysis snapshot;
* recommendation;
* ranking snapshot;
* status error;
* timestamp;
* evidence linkage.

### 2.8 CLI scanner

Target command:

```bash
python main.py watchlist add BBCA BMRI TLKM
python main.py watchlist list
python main.py scan --market idx
```

## Acceptance Gate

### Success case

Minimal tiga ticker dengan data berbeda menghasilkan:

* evidence berbeda;
* score berbeda;
* rank unik;
* hasil terurut.

### Failure case

Data provider gagal pada satu ticker:

* ticker tersebut berstatus `DATA_ERROR`;
* tidak berubah menjadi BUY/SELL/WAIT;
* tidak masuk ranking valid;
* ticker lain tetap diproses.

### Restart case

Snapshot hasil scan tetap dapat dibaca setelah aplikasi restart.

### Production proof

Tampilkan output nyata dari command scanner, bukan hanya fake unit test.

---

# ACTIVATION 3 — ATOMIC PAPER TRADING ENGINE

## Tujuan

Membuat satu paper order mengubah seluruh state portfolio secara konsisten dan atomik.

## Langkah

### 3.1 Tentukan transaction boundary

Satu paper execution harus mencakup:

```text
pre-trade validation
order creation
execution
trade creation
order fill update
cash update
position update
P/L update
portfolio snapshot
commit
```

Jika satu tahap gagal:

```text
rollback seluruh perubahan
```

### 3.2 Pre-trade validation

Sebelum Order di-fill, validasi:

* account aktif;
* signal/evidence tersedia;
* user approval tersedia;
* symbol valid;
* quantity valid;
* IDX lot size valid;
* price positif;
* available cash;
* available position untuk SELL;
* duplicate request/idempotency;
* risk limit;
* kill switch.

### 3.3 IDX execution policy

Buat policy/config untuk:

* lot size 100;
* buy fee;
* sell fee;
* pajak penjualan;
* slippage optional;
* buying power.

Jangan hard-code angka tanpa config atau domain decision yang jelas.

### 3.4 Consistent Order and Trade

Setelah fill:

```text
Order.status = FILLED
Order.filled_price = Trade.fill_price
Order.filled_quantity = Trade.quantity
Order.filled_at = Trade.executed_at
```

### 3.5 Cash update

BUY:

```text
cash -= gross value + fee + tax
```

SELL:

```text
cash += gross value - fee - tax
```

Cash tidak boleh negatif.

### 3.6 Position update

BUY:

* membuat posisi baru;
* atau merge posisi;
* menghitung weighted average price.

SELL:

* mengurangi quantity;
* menolak oversell;
* menutup posisi jika quantity nol;
* menghitung realized P/L.

### 3.7 Realized dan unrealized P/L

Realized P/L harus memperhitungkan biaya yang relevan.

Unrealized P/L harus menggunakan harga pasar terbaru dan timestamp.

### 3.8 Stop loss dan take profit

Simpan pada position/order strategy:

* stop-loss;
* take-profit;
* trailing rule jika nanti diperlukan.

Pada activation awal, trigger boleh manual atau melalui explicit monitoring command. Jangan langsung membuat background autonomous execution.

### 3.9 Reconciliation

Buat pemeriksaan:

```text
Order
Trade
Cash
Position
Portfolio snapshot
```

harus konsisten.

## Acceptance Gate

### BUY scenario

Account awal:

```text
cash = 10.000.000
BUY BBCA dengan quantity dan price valid
```

Bukti wajib:

* Order FILLED;
* filled fields benar;
* Trade tercatat;
* fee/tax tercatat;
* cash berkurang tepat;
* Position dibuat;
* average price benar.

### SELL partial

Bukti:

* quantity Position berkurang;
* cash bertambah;
* realized P/L dihitung.

### SELL full

Bukti:

* Position ditutup secara benar;
* realized P/L tersimpan;
* closed trade dapat dihitung performanya.

### Failure rollback

Insufficient cash atau oversell:

* tidak ada Trade;
* Order tidak menjadi FILLED;
* cash tidak berubah;
* Position tidak berubah.

### Restart

State account dan position tetap sama setelah restart.

---

# ACTIVATION 4 — MANUAL DAILY TRADING LOOP

## Tujuan

Membuat AIOS dapat digunakan setiap hari oleh pengguna tanpa mengedit code.

## Command minimum

```bash
python main.py doctor
python main.py init

python main.py watchlist add BBCA BMRI TLKM
python main.py watchlist remove TLKM
python main.py watchlist list

python main.py scan --market idx
python main.py recommendation BBCA

python main.py paper buy BBCA --allocation 0.05
python main.py paper sell BBCA --quantity 100

python main.py portfolio
python main.py account
python main.py orders
python main.py trades
```

## Rules

### Scan tidak langsung mengeksekusi order

Flow:

```text
scan
→ recommendation
→ user review
→ user approval
→ paper order
```

### Allocation

Jika menggunakan allocation:

```text
quantity dihitung dari actual cash
→ disesuaikan dengan lot IDX
→ divalidasi ulang
```

Jangan menggunakan `capital=0`.

### Output

Output harus menunjukkan:

* signal;
* confidence;
* reason;
* data timestamp;
* risk;
* suggested allocation;
* estimated cost;
* fee;
* stop;
* user confirmation status.

## Acceptance Gate

Satu sesi terminal nyata harus berhasil:

```text
init
→ add watchlist
→ scan
→ approve recommendation
→ paper buy
→ portfolio
→ restart
→ portfolio tetap benar
→ paper sell
→ performance berubah
```

---

# ACTIVATION 5 — AUDIT TRAIL AND PERFORMANCE

## Tujuan

Membuktikan apakah strategi membantu atau merugikan setelah biaya.

## Langkah

### 5.1 Decision linkage

Setiap keputusan harus memiliki linkage:

```text
signal_id
analysis_snapshot_id
recommendation_id
strategy_name
strategy_version
entry_reason
exit_reason
risk_validation_id
approval_id
order_id
trade_id
position_id
timestamp
```

### 5.2 Portfolio snapshots

Simpan snapshot berkala:

* cash;
* market value;
* equity;
* realized P/L;
* unrealized P/L;
* exposure;
* drawdown;
* timestamp.

### 5.3 Daily performance

Simpan:

* starting equity;
* ending equity;
* realized result;
* unrealized result;
* fees;
* tax;
* net result;
* drawdown;
* number of signals;
* number of executions.

### 5.4 Equity curve

Equity curve harus berasal dari portfolio snapshots nyata.

Jangan meminta caller memberikan list manual tanpa sumber production.

### 5.5 Performance service wiring

Hubungkan repository nyata ke:

* trade statistics;
* position statistics;
* win rate;
* expectancy;
* profit factor;
* maximum drawdown;
* performance summary.

### 5.6 Strategy attribution

Trade harus dapat dikelompokkan berdasarkan:

* strategy;
* market;
* signal;
* holding period;
* risk category.

## Acceptance Gate

Setelah beberapa transaksi BUY dan SELL:

* realized P/L tidak nol secara default;
* fee memengaruhi net result;
* equity curve terbentuk;
* maximum drawdown dapat dihitung;
* win rate dapat dihitung;
* expectancy dapat dihitung;
* profit factor dapat dihitung;
* hasil tetap sama setelah restart;
* setiap angka dapat ditelusuri ke Trade dan Position.

---

# ACTIVATION 6 — OPERATIONAL NOTIFICATION

## Tujuan

Mengaktifkan notification setelah event production benar-benar valid.

## Prioritas awal

Gunakan Telegram saja.

Tunda:

* Discord;
* email;
* multi-channel kompleks.

## Event awal

* scan completed;
* top opportunity ditemukan;
* paper order executed;
* paper order rejected;
* stop-loss triggered;
* risk limit exceeded;
* data fetch failed;
* daily performance ready.

## Langkah

### 6.1 Context credential source

Pastikan `ServiceContext` memperoleh:

* telegram bot token;
* telegram chat ID;
* message;
* title jika diperlukan.

Credential berasal dari config/environment, bukan hard-coded.

### 6.2 Result handling

Jika:

```python
NotificationService.execute(...)
```

menghasilkan:

```python
ServiceResult.success == False
```

maka adapter/manager harus menganggap notification gagal.

Jangan diam-diam sukses.

### 6.3 Commit ordering

Event `ORDER_EXECUTED` hanya dikirim setelah database transaction berhasil commit.

Jangan mengirim notifikasi sukses sebelum state berhasil disimpan.

### 6.4 Daily report

Daily notification harus menggunakan:

* Report nyata;
* PerformanceSummary nyata.

Jangan membuat performance summary kosong atau nol palsu.

## Acceptance Gate

### Success

Notifikasi nyata terkirim ke Telegram.

### Failure

Token salah atau jaringan gagal:

* caller mengetahui failure;
* failure tersimpan/logged;
* trading transaction yang sudah commit tidak di-rollback hanya karena Telegram gagal;
* notification dapat dicoba ulang secara manual.

---

# ACTIVATION 7 — PAPER VALIDATION

## Tujuan

Menguji sistem dan strategi dengan data serta transaksi paper yang cukup sebelum modal nyata.

## Jangan menggunakan satu-satunya gate berbasis waktu

Gunakan kombinasi:

* jumlah closed trades;
* variasi kondisi pasar;
* kualitas data;
* net performance setelah fee;
* drawdown;
* failure rate;
* reconciliation error.

## Minimum validation dimensions

### System validation

* tidak ada cash negatif;
* tidak ada oversell;
* tidak ada duplicate trade;
* tidak ada filled Order tanpa Trade;
* tidak ada Trade tanpa cash/position update;
* restart recovery berhasil;
* database reconciliation bersih;
* failed data tidak menghasilkan signal.

### Strategy validation

* net expectancy setelah fee;
* profit factor;
* maximum drawdown;
* win rate;
* average win;
* average loss;
* holding period;
* performance per strategy;
* performance per market regime;
* execution rate.

### Operational validation

* scanner dapat dijalankan setiap hari;
* data error terlihat;
* output dapat dipahami;
* user approval tercatat;
* notification dapat diterima;
* backup database berhasil.

## Live Readiness Gate

Jangan lanjut live jika masih ada:

* state inconsistency;
* silent failure;
* unresolved reconciliation error;
* fake/default performance;
* missing audit linkage;
* risk validation bypass;
* negative expectancy setelah biaya pada sample yang digunakan;
* drawdown melebihi batas yang pengguna setujui.

---

# ACTIVATION 8 — SMALL-CAPITAL LIVE IDX

## Tujuan

Menghubungkan broker IDX dengan modal kecil dan kontrol ketat.

## Prinsip

Live adapter harus terpisah dari paper engine.

Gunakan interface bersama bila memang cocok, tetapi jangan memaksa broker nyata mengikuti asumsi paper engine.

## Langkah

### 8.1 Broker adapter audit

Periksa:

* API resmi yang tersedia;
* authentication;
* market order/limit order;
* order status;
* cancel;
* partial fill;
* trading hours;
* settlement;
* rate limit.

Jangan mengarang endpoint broker.

### 8.2 Dry-run mode

Sebelum order nyata:

```text
request
→ validation
→ estimated value
→ fee
→ risk
→ user confirmation
→ dry-run output
```

### 8.3 Human approval

Setiap live order membutuhkan approval eksplisit.

### 8.4 Kill switch

Harus tersedia:

* global disable;
* market disable;
* symbol disable;
* max daily loss;
* max position;
* max order value.

### 8.5 Reconciliation

Broker menjadi sumber kebenaran untuk:

* order status;
* partial fill;
* rejected order;
* actual fee;
* actual position.

Local database harus direkonsiliasi.

## Acceptance Gate

Sebelum order live pertama:

* paper validation lulus;
* dry-run lulus;
* approval lulus;
* kill switch diuji;
* credential aman;
* duplicate prevention diuji;
* reconciliation tersedia.

Mulai dengan modal yang kerugiannya dapat diterima sepenuhnya oleh pengguna.

---

# ACTIVATION 9 — US STOCKS

Kerjakan setelah IDX production workflow stabil.

## Tambahkan MarketAdapter US

Harus menangani:

* symbol format;
* timezone;
* market calendar;
* pre-market/after-hours policy;
* USD account;
* fractional share jika broker mendukung;
* commission/fee;
* currency conversion;
* settlement;
* data provider;
* broker adapter;
* tax reporting metadata.

Jangan mencampur fee dan lot IDX dengan US.

## Acceptance Gate

Seluruh workflow scanner → paper → performance bekerja terpisah untuk market US tanpa merusak IDX.

---

# ACTIVATION 10 — CRYPTO

Kerjakan setelah US atau setelah core multi-market abstraction terbukti stabil.

## Harus menangani

* exchange;
* trading pair;
* base/quote asset;
* quantity precision;
* price tick;
* minimum notional;
* maker/taker fee;
* 24/7 market;
* exchange downtime;
* wallet/balance;
* order status;
* API rate limit;
* custody/security.

Pada activation awal:

* spot trading saja;
* tanpa leverage;
* tanpa futures;
* tanpa automatic withdrawal.

## Acceptance Gate

Paper crypto dan reconciliation berjalan sebelum API trading live diaktifkan.

---

# ACTIVATION 11 — FOREX

Forex dikerjakan terakhir karena menambah risiko:

* leverage;
* margin;
* spread;
* pip value;
* lot size;
* rollover;
* session;
* liquidation;
* broker-specific rules.

## Activation awal

* analysis;
* paper forex;
* no leverage live;
* no autonomous execution.

## Acceptance Gate

Margin, pip value, stop-loss, dan maximum loss harus terbukti benar melalui test numerik dan reconciliation.

---

# ACTIVATION 12 — HERMES / OPENCLAW-LIKE AIOS CAPABILITIES

Fitur agent lanjutan baru dikerjakan setelah workflow trading menghasilkan state dan performance nyata.

## Fitur yang dapat ditambahkan

### Tool and capability registry

Agent dapat mengetahui tool yang tersedia.

### Permission model

Tool dibagi menjadi:

* read-only;
* paper execution;
* live execution;
* destructive/admin.

### Planner

Planner dapat menyusun task, tetapi tidak boleh melewati:

* risk validation;
* human approval;
* live kill switch.

### Memory

Simpan:

* user preferences;
* portfolio context;
* strategy notes;
* previous decisions;
* lessons from failed trades.

Jangan menggunakan memory sebagai pengganti database finansial.

### Scheduler

Scheduler dapat menjalankan:

* morning scan;
* market close recap;
* performance report;
* data health check.

Scheduler tidak boleh langsung melakukan live execution pada activation awal.

### Multi-agent

Multi-agent hanya ditambahkan jika ada manfaat terukur, misalnya:

* market analyst;
* risk reviewer;
* portfolio reviewer.

Jangan menambah agent hanya agar sistem terlihat kompleks.

### Self-diagnostic

AIOS harus dapat menjawab:

* provider mana gagal;
* data mana stale;
* migration mana belum jalan;
* account mana tidak reconcile;
* notification mana gagal;
* tool mana tidak tersedia.

## Acceptance Gate

Capability agent lanjutan tidak boleh dapat melewati safety dan financial state machine.

---

# F. URUTAN PRIORITAS FINAL

Gunakan urutan berikut:

```text
0. Baseline
1. Reproducible startup
2. Valid IDX scanner
3. Atomic paper trading
4. Manual daily workflow
5. Audit trail and performance
6. Operational notification
7. Paper validation
8. Small-capital live IDX
9. US stocks
10. Crypto
11. Forex
12. Hermes/OpenClaw-like advanced capabilities
```

---

# G. CARA BERINTERAKSI DENGAN SAYA

Jangan memberikan seluruh implementation prompt sekaligus.

Untuk setiap interaksi:

1. Tentukan activation dan step aktif.
2. Audit source code yang relevan.
3. Laporkan kontrak aktual.
4. Buat satu prompt implementasi atomik.
5. Tunggu laporan implementasi.
6. Evaluasi laporan terhadap acceptance gate.
7. Jangan menyatakan selesai bila hanya unit test hijau.
8. Berikan prompt step berikutnya hanya setelah gate terpenuhi.

Ketika saya memberikan laporan dari Claude atau coding agent:

* periksa apakah laporan membuktikan behavior;
* jangan hanya menghitung PASS/FAIL;
* cari state database sebelum/sesudah;
* cari failure-path proof;
* cari restart proof;
* cari silent fallback;
* cari mismatch antara Order, Trade, Cash, Position, dan Performance.

---

# H. INSTRUKSI PERTAMA UNTUKMU

Mulai dari:

```text
ACTIVATION 0 — BASELINE DAN PROJECT CONTROL
```

Jangan coding dahulu.

Audit repository aktual dan hasilkan:

1. baseline structure report;
2. production flow map;
3. daftar test struktural versus test end-to-end;
4. daftar known failures/stale tests;
5. daftar blocker untuk Activation 1;
6. satu prompt implementasi untuk step pertama Activation 1.

Jangan membuat class atau abstraction baru pada tahap audit.
