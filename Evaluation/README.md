# AIOS Accuracy Evaluation Harness

## Purpose
Mengukur dan meningkatkan akurasi AIOS per lapisan dengan metrik terukur.

## Layer Map

| Layer | Komponen | Metrik | Target | Cara Ukur |
|-------|----------|--------|--------|-----------|
| **L1 Data** | `Services/stock_service.py`, `news_service.py`, `Repository/external/*`, `Business/idx_market_calendar.py` | 99.9% record lolos validasi skema/rentang, 0 duplikat, 0 gap tak terdeteksi | 99.9% | Validasi DB constraints, gap detection, duplicate scan |
| **L2 Engine** | `Business/*_engine.py`, `Business/*_policy.py` (62 files) | 100% cocok dengan hitungan referensi independen (toleransi numerik eksplisit) | 100% | Property-based test dengan 1000 input acak vs referensi independen |
| **L3 Signals** | `Orchestration/decision_copilot.py`, `Business/ranking_engine.py`, `crypto_signal_engine.py` | Kalibrasi: Brier score, ECE <= 0.05, reliability diagram vs baseline naif | ECE <= 0.05 | Walk-forward evaluation (DATA TIDAK CUKUP: 80 snapshots, 0 trades) |
| **L4 LLM** | `Providers/gemini.py`, `nine_router.py`, `Services/copilot_explanation_llm_narrator.py` | >= 99% klaim numerik/faktual dalam output cocok dengan data sumber (groundedness), 0 angka tanpa sumber | >= 99% | Extract angka dari output, cocokkan ke data sumber (BLOCKED: no output archive) |
| **L5 Orchestration** | `Orchestration/idx_daily_scheduler.py`, `autonomous_scheduler.py` | 99%+ job selesai sesuai jadwal, idempoten, aman diulang | 99%+ | Audit `scheduler_job_runs` table, log event counts |

## Baseline (TAHAP 2 — ukur dulu, jangan ubah kode)

### Test Suite (pytest)
```
Tests/ : 391 files, 99 test functions (14 pytest-style + 4684 scenario funcs in 340 files)
pytest -q --ignore=Tests/test_phase_i_gate3.1_datetime.py:
  98 passed, 1 failed (test_market_analysis_foundation.py::TestIDXTickerExtractorPlaceholder::test_extract_raises_not_implemented_error)
  2 warnings (PytestReturnNotNoneWarning in E2e_test.py, integration_test.py)
```

### L1 Data Baseline
- **DB State**: `ranking_snapshots` 80 rows, 8 scan_time distinct (2026-08-22, 08-24, 09-11)
- **Gap**: Aug 24 → Sep 11 (18 hari)
- **Duplikat**: 0 (PK constraint OK)
- **Validasi pelanggaran**: 0 (semua `status='success'`)
- **Job gagal/terlewat**: `scheduler_job_runs` hanya 2 rows (satu tanggal: 2026-08-24), no `pre_market_check`/`market_close_recap`/`daily_review`
- **Log**: 0 production fetch failures, 8 mock failures

### L2 Engine Baseline
**Kandidat untuk property-based test (1000 input acak):**
1. `Business/maximum_drawdown_engine.py` — `calculate(equity_curve)` O(N) vs O(N²) brute-force
2. `Business/expectancy_engine.py` — `calculate(stats)` zero-division, presisi float
3. `Business/crypto_quantity_policy.py` — `is_quantity_valid(quantity)` float vs Decimal round-off
4. `Business/forex_max_loss_policy.py` — `calculate_maximum_loss(pair, entry, stop, qty)` pip distance
5. `Business/profit_factor_engine.py` — `calculate(stats)` zero-division `0.0` vs `NaN`/`Infinity`

**Belum dijalankan** — butuh implementasi referensi independen + hypothesis test harness.

### L3 Signals Baseline
**DATA TIDAK CUKUP:**
- `ranking_snapshots`: 80 rows (8 timestamp) — tidak cukup untuk walk-forward (butuh >= 200 sampel per kelas)
- `decision_briefs`: 5 rows (ANTM, 2026-08-22) — 3 SUCCESS + 2 POLICY_BLOCKED
- `journal_entries`, `trades`, `orders`, `positions`, `portfolio_snapshots`: **0 rows**
- Tidak ada OHLC history table atau CSV historis
- Tidak ada tabel `forex`/`crypto` trade/signal

**Walk-forward evaluation: BLOCKED** — butuh backfill OHLC eksternal atau koleksi live berminggu-minggu.

### L4 LLM Baseline
**BLOCKED: no output archive**
- `copilot_explanation_llm_narrator.narrate_explanation()` tidak menyimpan output historis
- Test suite (`_FakeHealthyProvider`) hanya fixed string, bukan real LLM response
- `decision_briefs` table hanya 5 rows, tidak ada field `llm_output`
- System instruction melarang fabrikasi angka: "Do not invent any number, price, timestamp"

**Untuk melanjutkan:** butuh logging output LLM ke DB atau file, lalu ekstrak 30-50 output.

### L5 Orchestration Baseline
- **Job runs**: 2/6 jobs (session_scan, data_health_check) on 2026-08-24
- **Missing**: pre_market_check, market_close_recap, daily_review (0 rows)
- **Audit events**: 12 rows (job_started×4, job_succeeded×4, notification_sent×3)
- **Idempotency**: `scheduler_job_runs` PK `(job_type, trading_date)` OK
- **Observation window**: 1 CLOSED (2026-08-24 to 09-23)

## Metrik yang TIDAK mencapai target
- **L1**: Gap 18 hari (target: 0 gap tak terdeteksi) — scheduler tidak jalan rutin
- **L2**: Belum diukur (butuh harness)
- **L3**: DATA TIDAK CUKUP (butuh >= 200 sampel per kelas)
- **L4**: BLOCKED (no output archive)
- **L5**: 2/6 jobs (33%), target 99%+ — scheduler hanya jalan sekali

## Run Command
```bash
python Evaluation/run_eval.py
```
Exit code non-zero bila ada metrik di bawah target.
