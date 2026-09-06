ACTIVATION 3.1 — Audit Transaction Boundary: Paper Trading
0. Temuan paling penting dulu

Tidak ada jalur produksi yang benar-benar memanggil PaperTradingEngine.submit_order().

Saya grep seluruh repo (di luar Tests/) untuk setiap pemanggilan paper_trading_engine. / .submit_order(. Satu-satunya kemunculan paper_trading_engine di luar test:

File	Yang terjadi
Core/composition_root.py	Membangun objeknya (_build_paper_trading_engine(order_lifecycle_service, execution_service)), expose sebagai app.paper_trading_engine. Komentar di baris tepat sesudahnya, verbatim: "Purely additive: nothing below this line reads paper_trading_engine yet."
Business/recommendation_service.py, Business/ranking_engine.py	Hanya disebut di docstring sebagai daftar dependency yang tidak dipakai kelas tsb.
main.py	Zero referensi (watchlist, scan, auto, chat — tak satu pun menyentuh paper_trading_engine).

Jalur trading yang memang dipanggil dari CLI (auto <ticker></ticker> → AutonomousAgent → ... → TradingDecisionAgent) memakai Orchestration.paper_trading_skill.PaperTradingSkill — komponen berbeda, nama mirip, tapi menurut docstringnya sendiri: "does NOT... touch any network or persistence layer of any kind". Ia hanya mapping status→execution_status in-memory, tidak menyentuh OrderRepository/TradeRepository/PositionRepository/AccountRepository sama sekali.

Jadi pertanyaan "jalur eksekusi paper order yang digunakan production" punya dua jawaban terpisah, dan saya laporkan keduanya:

A. Jalur yang benar-benar tersambung ke persistence (PaperTradingEngine.submit_order()) — dibangun tapi tidak dipanggil siapa pun di production.
B. Jalur yang benar-benar dipanggil dari CLI production (PaperTradingSkill) — tidak melakukan persistence sama sekali, jadi tidak relevan untuk audit transaction boundary (tidak ada transaksi DB di jalur ini).

Sisa laporan ini mengaudit Jalur A — karena itulah satu-satunya kode yang benar-benar menjalankan tahap-tahap yang diminta (order creation → execution → trade → fill → dst), meski secara faktual belum ter-wire ke pemanggil produksi manapun.

1. Urutan eksekusi aktual (PaperTradingEngine.submit_order())
2. OrderLifecycleService.create_order()
   1a. OrderRepository.create()            INSERT orders (status=NEW)
   1b. OrderLifecycleService._validate()   (in-memory, tidak menyentuh DB)
   1c. jika valid:
   transition_status(..., "VALIDATED")
   → OrderRepository.get_by_id()   SELECT
   → OrderRepository.update_status()  UPDATE orders (status=VALIDATED)
   → OrderRepository.get_by_id()   SELECT
   transition_status(..., "PENDING")
   → OrderRepository.get_by_id()   SELECT
   → OrderRepository.update_status()  UPDATE orders (status=PENDING)
   → OrderRepository.get_by_id()   SELECT
   jika tidak valid:
   transition_status(..., "REJECTED", reason)  → return; PaperTradingEngine raise ValidationError, ExecutionService TIDAK dipanggil
3. [hanya jika Order.status == "PENDING"] ExecutionService.execute_order()
   2a. OrderRepository.get_by_id()         SELECT
   2b. TradeRepository.create()            INSERT trades
   2c. OrderRepository.update_status()     UPDATE orders (status=FILLED)

Tahap yang diminta di brief tapi TIDAK ADA di jalur ini sama sekali:

order fill update (ini identik dengan 2c di atas — sudah ada)
cash update — AccountBalanceService.apply_trade() ada, teruji, tapi tidak dipanggil dari PaperTradingEngine maupun siapa pun di produksi (grep .apply_trade( di luar Tests: nol hasil pemanggilan, hanya definisi).
position update — PositionManager.apply_trade() sama persis: ada, teruji, tidak dipanggil siapa pun di produksi.
P/L update — tidak ada penulisan realized_pnl/unrealized_pnl di jalur eksekusi manapun. Position.realized_pnl hanya pernah ditulis oleh PositionManager (yang sendiri tidak terpanggil), dan hanya pernah dibaca belakangan oleh engine pelaporan offline (PositionPerformanceEngine → WinRateEngine/ExpectancyEngine/dst) — subsistem laporan terpisah, bukan bagian transaksi eksekusi.
portfolio snapshot — tidak eksis sebagai fitur. portfolio_snapshots hanya nomor versi migrasi yang direservasi (Database/migrations_snapshots.py: "version 8 = portfolio_snapshots... a different, ERD-defined schema... not yet implemented"). Tidak ada tabel, tidak ada repository, tidak ada kode yang menulis snapshot portofolio di jalur trading manapun.

Dokumentasi sumbernya sendiri eksplisit dan konsisten di tiga file (OrderLifecycleService, ExecutionService, PositionManager, AccountBalanceService): masing-masing menyatakan "Never opens a transaction itself" dan mendaftar Account/Position/Portfolio/P/L sebagai eksplisit di luar scope-nya, "reserved for a future STEP" yang faktanya belum pernah dipanggil.

2. Repository/service yang terlibat (Jalur A)
   Komponen	Dipanggil?	Tabel yang disentuh
   OrderLifecycleService	Ya	orders
   OrderRepository	Ya (via di atas + ExecutionService)	orders
   ExecutionService	Ya	trades, orders
   TradeRepository	Ya	trades
   PositionManager	Tidak	positions — tidak disentuh
   PositionRepository	Tidak (dari jalur ini)	—
   AccountBalanceService	Tidak	accounts — tidak disentuh
   AccountRepository	Tidak (dari jalur ini)	—
   Portfolio snapshot repository	Tidak ada implementasinya	—
3. Batas transaksi database (mekanisme aktual)

BasePersistenceRepository menyediakan dua helper:

_execute(sql, params) → passthrough ke DatabaseManager.execute() → SQLiteDatabase.execute(). Docstring-nya sendiri: "Execute a single statement outside of an explicit transaction."
_session(...) → context manager transaksional eksplisit (begin/commit/rollback), "Commits on clean exit, rolls back if the block raises."

Setiap satu method di OrderRepository/TradeRepository/PositionRepository/AccountRepository yang dipakai jalur ini memakai _execute(), tidak satupun memakai _session(). Saya grep semua empat file repository ini secara eksplisit: hasilnya seragam — hanya _execute( yang dipanggil, nol pemanggilan _session(.

Koneksi SQLite dibuka dengan isolation_level=None (Database/sqlite_database.py, dikomentari: "manual transaction control via begin/commit/rollback"). Karena execute() tidak pernah memanggil connection.commit() sendiri dan tidak ada begin() eksplisit di jalur _execute, setiap statement berjalan dalam autocommit native SQLite — setiap INSERT/UPDATE individual committed ke disk seketika, independen dari statement lain.

Kesimpulan batas transaksi: tidak ada. Setiap baris SQL di seluruh urutan Bagian 1 adalah transaksi database-nya sendiri yang commit sendiri-sendiri, terlepas dari statement sebelum/sesudahnya.

4. Apakah seluruh langkah berada dalam satu transaksi?

Tidak. Dari kelima statement DB yang benar-benar dieksekusi (INSERT orders, UPDATE→VALIDATED, UPDATE→PENDING, INSERT trades, UPDATE→FILLED) — masing-masing adalah unit commit terpisah. Tidak ada BEGIN yang membungkus lebih dari satu statement di jalur ini. PaperTradingEngine sendiri menyatakan eksplisit di docstring-nya: "Never opens a transaction itself; both collaborators already own their own persistence." — dan kedua collaborator itu (OrderLifecycleService, ExecutionService) masing-masing juga menyatakan hal yang sama tentang dirinya sendiri.

5. Titik commit

Lima titik commit terpisah, masing-masing seketika saat statement-nya dieksekusi:

INSERT orders (status=NEW) — commit saat create_order() baris pertama.
UPDATE orders (status=VALIDATED) — commit terpisah.
UPDATE orders (status=PENDING) — commit terpisah.
INSERT trades — commit terpisah (di execute_order()).
UPDATE orders (status=FILLED) — commit terpisah, setelah trade sudah permanen tersimpan.
6. Titik rollback

Tidak ada mekanisme rollback database di jalur ini sama sekali — karena tidak ada transaksi yang dibuka untuk di-rollback. Yang ada hanyalah exception Python (ValidationError/RepositoryError) yang menghentikan eksekusi method Python berikutnya, tapi statement-statement yang sudah ter-commit sebelum exception itu tetap permanen di database, tidak pernah ditarik balik.

7. Apakah ada state yang bisa terlanjur tersimpan bila satu tahap gagal? — Ya, beberapa skenario nyata:
   Skenario kegagalan	State yang terlanjur permanen
   OrderRepository.create() sukses (row NEW tersimpan), lalu proses crash/exception sebelum transition_status pertama	Order nyangkut permanen di status NEW selamanya — tidak pernah divalidasi, tidak pernah PENDING/REJECTED.
   transition_status(..., "VALIDATED") sukses commit, tapi exception terjadi sebelum transition_status(..., "PENDING") dipanggil	Order nyangkut permanen di VALIDATED — status antara yang menurut docstring OrderLifecycleService sendiri tidak punya transisi keluar yang didefinisikan (hanya VALIDATED → PENDING yang legal); order ini functionally stuck selamanya.
   TradeRepository.create() sukses (Trade ter-INSERT dan commit permanen), lalu OrderRepository.update_status(..., "FILLED") gagal (mis. RepositoryError di tengah jalan)	Trade sudah permanen ada di tabel trades, tapi Order.status masih PENDING. Karena ExecutionService.execute_order() menolak eksekusi ulang berdasarkan status Order (status != "PENDING" → reject), Order yang stuck di PENDING ini justru bisa dieksekusi lagi oleh pemanggil berikutnya → Trade kedua untuk order yang sama akan tercipta. Idempotency yang diklaim docstring ExecutionService ("a previously FILLED order... rejected... can never produce a second Trade") gagal justru pada kegagalan parsial persis di titik ini — begitu Trade ter-commit tapi status-update belum, guard idempotency-nya belum aktif.
   Seandainya PaperTradingEngine benar-benar dipanggil produksi hari ini: Trade sukses ter-commit, tapi cash tidak pernah dikurangi/ditambah (AccountBalanceService.apply_trade tidak pernah dipanggil dari jalur ini), posisi tidak pernah diperbarui (PositionManager.apply_trade idem), tidak ada snapshot portofolio. Ini bukan skenario "gagal di tengah" — ini adalah perilaku normal jalur ini pada kasus sukses: Trade permanen tersimpan sebagai satu-satunya jejak sebuah eksekusi, sementara cash/posisi/P/L akun tidak pernah mencerminkannya sama sekali kecuali seseorang secara terpisah memanggil AccountBalanceService/PositionManager dengan Trade yang sama secara manual.
   Ringkasan kontrak aktual
   Transaction manager: tidak ada — tiap repository call = 1 auto-committed statement (isolation_level=None, tanpa BEGIN eksplisit di jalur _execute).
   Atomicity lintas tahap: nol. Order create/validate/pending, Trade create, Order fill — lima commit independen.
   Rollback: tidak eksis untuk jalur ini; hanya exception Python yang menghentikan lanjutan, bukan menarik balik yang sudah tersimpan.
   Cash/Position/P/L/Portfolio snapshot: komponennya ada (AccountBalanceService, PositionManager) dan sudah teruji unit, tapi tidak tersambung ke PaperTradingEngine maupun pemanggil produksi manapun — secara faktual bukan bagian dari "transaction boundary" karena memang tidak pernah dieksekusi bersama alur ini.
   Jalur yang benar-benar aktif dari CLI production (auto) memakai PaperTradingSkill, yang tidak melakukan I/O database sama sekali — sehingga tidak punya transaction boundary untuk diaudit.

Tidak ada perubahan kode yang saya lakukan — laporan ini murni observasi atas kontrak yang sudah ada di Business/paper_trading_engine.py, Business/order_lifecycle_service.py, Business/execution_service.py, Business/position_manager.py, Business/account_balance_service.py, Repository/persistence/base_persistence_repository.py, Database/database_manager.py, Database/sqlite_database.py, dan Core/composition_root.py.
