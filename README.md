# AIOS — AI Investment Operating System

> Evidence-led decision support for the Indonesian stock market (IDX) — no broker, no auto-trading, human always decides.

AIOS is a personal decision-support agent for IDX stock analysis. It assembles evidence with timestamps, applies risk gates, and surfaces a conditional trade plan only when the evidence check returns `SUCCESS`; every other state is an explicit non-action. A human is always the final decision-maker.

## Disclaimer

AIOS is a personal research and learning project. It is not a broker, not an autonomous trading bot, and not financial advice. It never submits live orders, and nothing in this repository recommends buying or selling any security. Use at your own risk.

## What it does

- **Evidence first** — every brief carries sources and timestamps; missing or stale inputs yield `NO_TRADE`, `DATA_STALE`, or `INSUFFICIENT_DATA`
- **Risk gates** — position, loss, and window checks before any plan forms
- **Paper trading** — explicit journal entries only; no auto-execution
- **Multi-provider LLM** — Gemini / Ollama selector (no vendor lock-in)
- **Fail-closed** — provider, scheduler, and DB failures surface in the audit trail, never as a trade

## Quick Start

### Prerequisites

- Python 3.14 (tested)
- SQLite

### Install

```bash
git clone https://github.com/munaba/ai-investment-operating-system.git
cd ai-investment-operating-system

python -m venv .venv
.venv\Scripts\activate        # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

cp .env.example .env          # Windows cmd: copy .env.example .env
# edit .env: ACTIVE_PROVIDER, GEMINI_API_KEY or OLLAMA_HOST
```

### Database

```bash
python main.py init      # applies every pending migration (all 20 domains, in version order)
python main.py doctor    # read-only check: environment, database, migrations, data freshness
```

`init` reads the canonical list in `Database/migration_registry.py`; a test fails if a
`Database/migrations_*.py` module is ever left out of it. The per-domain
`run_*_migrations.py` scripts still exist for applying a single domain by hand.

### Deployment order

- **Back up the DB first** — use the SQLite backup API or copy `data/investment_platform.db`.
- Run `python main.py init` before any scan, then confirm with `python main.py doctor`.
- Migrate the DB first, then deploy new code.
- No auto-migration at startup — the operator runs migrations manually.
- Details: [Docs/DEPLOYMENT.md](Docs/DEPLOYMENT.md).

### Run

Python copilot (interactive REPL):

```bash
python main.py
```

### Dashboard (Streamlit, read-only)

The dashboard never touches the live database. A small exporter reads it in SQLite
read-only mode and writes `Dashboard/data/snapshot.json`; the Streamlit app only reads
that file, so it can be hosted publicly (e.g. Streamlit Community Cloud with main file
`Dashboard/streamlit_app.py`).

```bash
python Dashboard/export_snapshot.py               # refresh the snapshot (AIOS venv)

python -m venv .venv-dashboard                    # separate, lightweight venv
.venv-dashboard\Scripts\activate
pip install -r Dashboard/requirements.txt
streamlit run Dashboard/streamlit_app.py          # http://localhost:8501
```

Pages: overview, scans and signals, decision briefs, paper trading, system health.
Telegram state, raw audit payloads and free-text operator feedback are never exported.

## Testing

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q          # 276 passed with a local data/ database
```

`hypothesis` is also required by `Evaluation/run_eval.py` (property-based L2 checks). PowerShell: `$env:PYTHONPATH="."; python -m pytest -q`.

Tests never write to the live database: `Tests/conftest.py` points `DB_PATH` at a temporary file, and the few tests that read `data/investment_platform.db` open it read-only (and are skipped when it is absent).

`Tests/` also holds about 300 standalone scenario scripts (no `def test_`, so pytest does not collect them); run one from the repo root with `PYTHONPATH=.` and `DB_PATH` pointing at a scratch database. Retired sprint-snapshot scripts live in `Tests/archive/` (see its README).

Dashboard smoke test (dashboard venv): `python -m pytest Dashboard/test_dashboard.py -q`.

## Important: Market Calendar Coverage

**IDX trading calendar currently covers 2026 only.** Before 2027-01-01, populate `Business/idx_market_calendar.py::IDX_NATIONAL_HOLIDAYS_2027` from official sources:

- Bursa Efek Indonesia (BEI) official trading calendar
- SKB 3 Menteri (joint decree on national holidays)

The scheduler operates **fail-closed** for years without coverage: any date outside 2026 returns `False` for `is_trading_day()` unless overridden via constructor or `TRADING_CALENDAR_OVERRIDE_ALLOW_UNKNOWN_YEARS=1`. An alert fires once per uncovered year when the scheduler ticks.

**Do not fabricate holiday dates.** Obtain them from authoritative government/exchange sources only.

## Evaluation

The evaluation harness covers layers L1–L5; see `Evaluation/README.md`. Latest committed baseline (2026-10-04, `Evaluation/baseline.json`): L2 engine 4032/4032 passed (32 golden cases + 4000 property-based).

## Architecture

| Folder | Role |
|--------|------|
| `Core/` | Composition root, bootstrap, config |
| `Business/` | Risk ledger, engines, policies, calendars |
| `Orchestration/` | Skills, tools, scheduler, permissions |
| `Services/` | Decision brief, journal, notifications |
| `Repository/` | Persistence layer |
| `Providers/` | LLM abstraction (Gemini, Ollama) |
| `Agents/` | Agent registry, planner, executor |
| `Database/` | DB manager |
| `Tests/` | pytest suite and standalone gate scripts |
| `Evaluation/` | Evaluation harness, golden cases |
| `Dashboard/` | Read-only Streamlit dashboard and snapshot exporter |

Scheduler details: `README_SCHEDULER.md`.

## Engineering notes

- 270+ pytest tests
- Global test for migration-version uniqueness (caught a version collision)
- Migration registry completeness test (caught `init` skipping 10 of 20 domains)
- v34: guarded unique index on ranking_snapshots (scan_time, symbol); clear RepositoryError if the index is missing
- Retry classifier rebuilt as an allowlist (27 tests; 21 fail on the old logic)
- Deterministic evaluation harness; insufficient data reports DATA_TIDAK_CUKUP instead of a false pass
- CLI commands use `with build_application()` so connections are closed

## Development

AIOS was architected and directed by Nabil, with implementation carried out through AI-assisted engineering, using Claude, ChatGPT, and an autonomous coding agent (Hermes) across iterative phases. Nabil defined the system architecture, risk policies, and decision-flow requirements, broke them into tasks for the AI agents, and reviewed and tested each output.

This is an AI-directed development workflow, not a claim that every line was written by hand without assistance.

- **Phases A–G**: complete (scanner, analysis, copilot, paper trading, notifications)
- **Phase H**: sustained-use review (observation windows, evidence assembly)
- **Phase I**: evidence profile analysis job added
- **Parked**: US stocks, crypto, forex (IDX only)

## Author

Muhammad Nabil Baihaqi - GitHub: github.com/munaba - LinkedIn: linkedin.com/in/muhammad-nabil-baihaqi-munaba - Email: munaba1006@gmail.com

## License

No license has been chosen yet; all rights reserved.
