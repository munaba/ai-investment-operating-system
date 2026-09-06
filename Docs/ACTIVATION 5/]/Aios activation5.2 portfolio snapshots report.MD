
# ACTIVATION 5.2 — PORTFOLIO SNAPSHOTS — OUTPUT REPORT

## 1. File yang berubah

**Baru:**

- `Database/migrations_portfolio_snapshots.py` — migration (version=8)
- `Repository/persistence/portfolio_snapshot_repository.py`
- `Business/portfolio_snapshot_service.py`
- `run_portfolio_snapshot_migrations.py`
- `Tests/test_portfolio_snapshot_migration.py` (18 checks)
- `Tests/test_portfolio_snapshot_repository.py` (32 checks)
- `Tests/test_portfolio_snapshot_service.py` (35 checks)

**Diubah (additive only):**

- `Database/models.py` — ditambahkan dataclass `PortfolioSnapshot`. Tidak ada dataclass lain yang diubah.

**Tidak diubah:** `PaperTradingEngine`, pre-trade gates, execution flow, order state machine, `Trade`/`Order`/`Position` immutability rules, `AccountBalanceService`, `PositionManager`, `UnrealizedPnLEngine`, `MaximumDrawdownEngine`, `Core.composition_root`, semua Activation 3.x/4 file.

## 2. Komponen existing yang di-reuse

| Komponen                                                                                      | Digunakan untuk                                                                                              |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `AccountRepository.get_by_id`                                                               | `cash` real dari Account                                                                                   |
| `PositionRepository.list_by_account`                                                        | Semua Position (open+closed) untuk`realized_pnl`; open positions untuk `market_value`/`unrealized_pnl` |
| `Business.unrealized_pnl_engine.UnrealizedPnLEngine` (LOCKED, sole owner of unrealized P/L) | `market_price` real + `unrealized_pnl` per posisi, dijumlahkan — formula tidak diduplikasi              |
| `Business.maximum_drawdown_engine.MaximumDrawdownEngine` (LOCKED)                           | `drawdown`, dihitung dari equity curve historis snapshot yang sudah persisted                              |
| `Repository.persistence.base_persistence_repository.BasePersistenceRepository`              | Pola akses DB (mirrors`SnapshotRepository`/`TradeRepository`)                                            |
| Pola migration reserved-version                                                               | Migration version=8 (sudah dialokasikan sejak`migrations_accounts.py` untuk `portfolio_snapshots`)       |

**Tidak ada Strategy/RiskPlan/Decision/Signal atau entity baru yang dibuat.** Tidak ada formula unrealized P/L / drawdown baru — keduanya reuse murni.

## 3. Schema/model/repository yang ditambahkan

- Tabel `portfolio_snapshots` (migration version=8):
  `snapshot_id PK`, `account_id (FK accounts)`, `cash`, `market_value`, `equity`, `realized_pnl`, `unrealized_pnl`, `exposure (NULLABLE)`, `drawdown`, `timestamp`. Immutable/append-only — tidak ada UPDATE/DELETE statement.
- `Database.models.PortfolioSnapshot` — dataclass baru, additive.
- `Repository.persistence.portfolio_snapshot_repository.PortfolioSnapshotRepository` — `create`, `get_by_id`, `list_by_account`, `list_all`, `get_latest_by_account`. **Tidak ada method update/delete** (dibuktikan oleh test).
- `Business.portfolio_snapshot_service.PortfolioSnapshotService.take_snapshot(account_id)` — compose + persist satu snapshot, tanpa scheduler/daemon (dibuktikan oleh test source-scan).

**Catatan wiring (deliberate scope decision):** migration ini **TIDAK** didaftarkan ke `Database.migration_registry.MIGRATION_MODULES`. Alasan: registry itu dikonsumsi oleh `python main.py init` dan `Core.doctor`, dan `Tests/test_doctor_command.py` (`_apply_all_migrations`) meng-hardcode tepat 7 domain migration serta meng-assert "Migrations section is READY once all 7 are applied". Menambah domain ke-8 di registry tanpa menyentuh test tersebut akan membuat test itu FAIL — yang berarti melanggar larangan mengubah behavior/test di luar scope Activation 5.2 ini. Migration ini tetap dapat dijalankan secara eksplisit lewat `run_portfolio_snapshot_migrations.py`, persis pola yang sudah dipakai oleh domain-domain lain sebelum mereka didaftarkan ke registry. Ini murni keputusan wiring, bukan functionality gap.

## 4. Sumber setiap field snapshot

| Field                                                  | Sumber                                                                                                                                                                                                                                                                                                                                                                                  | Status                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `cash`                                               | `Account.cash` (verbatim)                                                                                                                                                                                                                                                                                                                                                             | ✅ REAL                                                                                                                                                                                                                                                                  |
| `market_value`                                       | Σ (`UnrealizedPnLEngine.calculate(position).market_price × quantity`) atas open positions                                                                                                                                                                                                                                                                                           | ✅ REAL                                                                                                                                                                                                                                                                  |
| `realized_pnl`                                       | Σ`Position.realized_pnl` atas SEMUA posisi (open+closed) milik account                                                                                                                                                                                                                                                                                                               | ✅ REAL                                                                                                                                                                                                                                                                  |
| `unrealized_pnl`                                     | Σ`UnrealizedPnLEngine.calculate(position).unrealized_pnl` atas open positions — formula LOCKED, tidak diduplikasi                                                                                                                                                                                                                                                                   | ✅ REAL                                                                                                                                                                                                                                                                  |
| `equity`                                             | `cash + market_value` (kedua komponen sudah real). **Sengaja TIDAK memakai `Account.equity`** — field itu terdokumentasi eksplisit di `Business/account_balance_service.py` sebagai "portfolio valuation, reserved for a future STEP" dan hanya di-pass-through tanpa pernah dihitung ulang oleh kode manapun; memakainya akan mem-persist nilai basi/tak pernah dihitung. | ✅ REAL (derived)                                                                                                                                                                                                                                                        |
| `exposure`                                           | —                                                                                                                                                                                                                                                                                                                                                                                      | ❌**NOT VERIFIABLE / GAP** (lihat §5)                                                                                                                                                                                                                             |
| `drawdown`                                           | `MaximumDrawdownEngine.calculate(equity_curve)` atas riwayat `PortfolioSnapshot.equity` yang sudah persisted + equity snapshot ini — formula LOCKED, tidak diduplikasi                                                                                                                                                                                                             | ✅ REAL                                                                                                                                                                                                                                                                  |
| `timestamp`                                          | `datetime.now(timezone.utc).isoformat()` saat snapshot dikomposisi                                                                                                                                                                                                                                                                                                                    | ✅ REAL                                                                                                                                                                                                                                                                  |
| `account_id` (field tambahan, di luar 8 field wajib) | Parameter caller, memvalidasi keberadaan lewat`AccountRepository`                                                                                                                                                                                                                                                                                                                     | Ditambahkan**dengan alasan eksplisit**: setiap nilai lain di baris ini (cash, posisi, dll) scoped ke satu Account tertentu — tanpa `account_id`, baris snapshot ambigu begitu ada >1 account, persis alasan yang sama dipakai `Position`/`Order`/`Trade`. |

## 5. Field yang PASS dan field yang NOT VERIFIABLE/GAP

**PASS (7 dari 8 field wajib):** `cash`, `market_value`, `equity`, `realized_pnl`, `unrealized_pnl`, `drawdown`, `timestamp`.

**GAP — `exposure`:** Audit codebase tidak menemukan sumber/engine yang menghitung *total portfolio exposure* yang real. Satu-satunya kandidat yang ditemukan, `Orchestration.portfolio_engine.PortfolioEngine.exposure`, adalah konsep berbeda: pass-through `position_size` dari hasil eksekusi *hipotetis* per-signal (Stage L25), bukan pengukuran exposure dari portfolio real yang sedang berjalan — sehingga **tidak memenuhi syarat sebagai sumber**. Kolom `exposure` tetap ada di schema (sesuai kewajiban roadmap menyimpan field ini) sebagai `REAL NULL`, dan `PortfolioSnapshotService` **tidak pernah mengisi nilai** ke sana (selalu `None`) — tidak ada formula yang dikarang (mis. `market_value / equity`), sesuai larangan eksplisit di roadmap.

## 6. Test result

- `Tests/test_portfolio_snapshot_migration.py` — **18/18 PASS**
- `Tests/test_portfolio_snapshot_repository.py` — **32/32 PASS**
- `Tests/test_portfolio_snapshot_service.py` — **35/35 PASS**

Setiap test mengassert nilai eksplisit (bukan row-count saja): nilai `cash`/`market_value`/`unrealized_pnl`/`realized_pnl`/`equity`/`drawdown` dicek terhadap perhitungan independen, termasuk cross-check `drawdown` terhadap `MaximumDrawdownEngine` yang dipanggil ulang secara independen di dalam test.

## 7. Regression result

Dijalankan seluruh `Tests/*.py` (267 file) dan dibandingkan dengan hasil run yang sama persis di atas **zip asli belum-diubah**:

- **Baseline (zip asli):** 202 file lulus bersih, 62 file gagal.
- **Setelah implementasi:** 205 file lulus bersih (202 + 3 file test baru), 62 file gagal — **daftar 62 file yang gagal identik byte-per-byte** dengan baseline.
- Semua test regresi Activation 3.x/4 yang eksplisit lulus penuh: `activation_3_2_independent_proof.py`* , `activation_3_5_step1_proof.py` (21/21), `activation_3_5_step3_proof.py`, `activation_3_6_step3_proof.py`, `activation_3_7_step2_proof.py` (31/31), `activation_3_7_step4_proof.py` (23/23), `proof_activation_3_4_step2.py` (39/39), `activation4_session2_acceptance_proof.py` (36/36), `test_activation4_session1_cli_commands.py` (53/53), `test_activation4_session2_cli_commands.py` (29/29).

  \* `activation_3_2_independent_proof.py` gagal di kedua kondisi (baseline maupun setelah implementasi) dengan error yang identik (`ModuleNotFoundError` karena test ini mengasumsikan struktur folder `../extracted` yang tidak ada di lingkungan ini) — pre-existing, tidak berkaitan dengan Activation 5.2.
- Semua 18 test yang meng-import `Database.models` (yang saya ubah secara additive) lulus bersih.

**Kesimpulan: nol regresi baru diperkenalkan oleh Activation 5.2.**

## 8. Konfirmasi tidak ada autonomous execution

`PortfolioSnapshotService` tidak memiliki scheduler/loop/daemon/cron (dibuktikan lewat source-scan di test). `take_snapshot()` adalah method sinkron biasa, dipanggil eksplisit oleh caller. Tidak ada wiring ke `Core.composition_root` untuk auto-trigger.

## 9. Konfirmasi tidak ada perubahan Activation 3.x/4 yang tidak diperlukan

Tidak ada baris kode Activation 3.x/4 yang diubah. `PaperTradingEngine`, execution flow, order state machine, dan trade immutability tidak disentuh. Satu-satunya perubahan pada file lama adalah penambahan murni-aditif (`PortfolioSnapshot` dataclass) di `Database/models.py`.

## 10. GAP — penjelasan lengkap tanpa asumsi

**`exposure` tidak dapat diverifikasi** dari codebase yang ada. Tidak ada engine/formula portfolio-level exposure yang sudah production. Saya **tidak** mengarang formula (misalnya `market_value / equity` atau sejenisnya) karena itu akan menjadi formula fiktif yang tidak berasal dari sumber codebase manapun — melanggar rule 5/9/10 roadmap. Field tetap tersimpan sebagai `NULL` di setiap baris hingga Activation berikutnya menetapkan sumber yang sah untuk exposure (misalnya definisi bisnis resmi + data broker/margin yang belum ada di sistem ini).

---

## STOP CONDITION

`STOP — Activation 5.2 partial.`

Semua field kecuali `exposure` selesai diimplementasikan, diverifikasi dari sumber real, dipersist, dan diuji end-to-end (termasuk round-trip setelah restart proses). `exposure` adalah GAP eksplisit — tidak diperbaiki dengan asumsi, tidak ada architecture baru dibuat untuk mengisinya di luar scope roadmap ini.
