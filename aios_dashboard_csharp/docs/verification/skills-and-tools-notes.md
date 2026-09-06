# Skills & Tools Notes (Referensi Kerja)

> Catatan pointer, bukan copy isi. Terakhir diupdate: 26 Aug 2026.

## Skill lokal: `blazor-server-dashboard-patterns`

- **Lokasi:** `C:\Users\Nabil\AppData\Local\hermes\skills\software-development\blazor-server-dashboard-patterns\`
- **Provenance:** ⚠️ **AUTO-GENERATED dari project ini sendiri** (dibuat 25 Aug 2026 selama rewrite dashboard) — BUKAN skill komunitas pre-existing. Sempat salah dilabeli "kandidat eksternal" dan sudah dikoreksi.
- **Isi:** pola yang sudah terbukti di project ini — ReadOnlyDbContext (`Mode=ReadOnly` + SaveChanges throw), composite key `scheduler_job_runs(job_type, trading_date)`, PeriodicTimer auto-refresh + IDisposable, Chart.js interop dengan locale id-ID, external CLI mutation pattern, honest empty states.
- **Relevansi:** source of truth pola untuk pengembangan AIOS lanjutan; perlu adaptasi bila dipakai untuk project lain.

## Skill lokal lain yang dipakai dalam workflow AIOS

- `requesting-code-review` — pre-commit verification pipeline (independent reviewer fail-closed)
- `test-driven-development` — RED-GREEN-REFACTOR
- `systematic-debugging` — root cause sebelum fix
- Ketiganya builtin/generic, genuine pre-existing.

## Referensi eksternal (clone-only, di `F:\My Son\_reference\`)

### Vibe-Trading (`_reference/vibe-trading/`)
- Repo: https://github.com/HKUDS/Vibe-Trading · Lisensi: **MIT** (dicek dari LICENSE file)
- Clone 26 Aug 2026, shallow. Tidak diinstall/dijalankan.
- **Alasan relevan:** filosofi mandate-gated order & human-gate sejalan dengan AIOS. File worth dibaca:
  - `agent/src/live/mandate/`, `agent/src/live/order_guard.py`, `sdk_order_gate.py`
  - `agent/src/live/audit.py` (audit trail), `agent/src/tools/report_audit_tool.py`
  - Tests sebagai dokumentasi safety model: `test_mandate_enforcement.py`, `test_killswitch_blocks_orders.py`

### Fincept Terminal (`_reference/fincept-terminal/`)
- Repo: https://github.com/Fincept-Corporation/FinceptTerminal · Lisensi: **AGPL-3.0** (dicek dari LICENSE file)
- ⚠️ **JANGAN copy kode** — AGPL menular. Pelajari struktur ide saja: `fincept-qt/src/screens/` (katalog fitur dashboard finansial), `storage/` vs `services/` separation, `datahub/`.

## Skills Hub global

- Command riset: `hermes skills search <query>` / `hermes skills browse` (~90k skill terindeks).
- Skill baru terinstall 26 Aug 2026 (Top-5): `docker-management` (official Nous), `secret-scanning` (github/awesome-copilot), `security-audit` (cloudflare), `testing-anti-patterns` (obra/superpowers), `refactoring`.
