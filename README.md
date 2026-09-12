# AIOS — AI Investment Operating System

> Evidence-led decision support for the Indonesian stock market (IDX) — no broker, no auto-trading, human always decides.

AIOS is a personal, evidence-led daily trading decision-support agent for IDX. It assembles sourced evidence with timestamps, applies a risk ledger and human-approval gates, and only then — on `SUCCESS` — surfaces a conditional trade plan. Every other outcome is an explicit non-action status. Built as a learning and technical-demonstration project.

![AIOS Dashboard](docs/screenshot-dashboard.png)
<!-- Replace the placeholder above with a real screenshot: docs/screenshot-dashboard.png -->

## Features

- **Evidence before plan** — every brief carries sources and timestamps; missing/stale/contradictory inputs → `NO_TRADE` / `DATA_STALE` / `INSUFFICIENT_DATA`
- **Risk ledger & policy gates** — position, loss, and window checks before any plan is formed
- **Paper trading (explicit only)** — a journal decision never auto-creates a paper order
- **Observation windows & sustained-use review** — Phase H infrastructure for long-horizon review
- **Multi-provider LLM** — Gemini / Ollama behind a capability-based selector (no hard vendor lock-in)
- **Dashboard** — Blazor Server (`aios_dashboard_csharp`, .NET 8), SQLite source of truth
- **Fail-closed** — provider, scheduler, notification, or persistence failures are surfaced in health/audit, never as a trade

## Tech Stack

| Layer | Stack |
|---|---|
| Python core | Python 3.11+, `pandas`, `yfinance`, `python-dotenv` (+ optional `google-genai`, `requests`, chart/backtest libs) |
| Persistence | SQLite + custom migrations (`Database/migrations_*.py`, `run_*_migrations.py`) |
| C# dashboard | ASP.NET Core 8, Blazor Server, EF Core Sqlite, BCrypt.Net-Next, CsvHelper |
| Providers | `Providers/` (Gemini, Ollama, selector) |
| Tests | `pytest` / `vitest` / `playwright` |

## Development Process

This project was architected and directed by Nabil, with implementation carried out through AI-assisted engineering — using Claude, ChatGPT, and an autonomous coding agent (Hermes) to implement the design across iterative phases (see `Docs/` for phase-by-phase closeout reports). Nabil defined the system architecture, risk policies, and decision-flow requirements, then broke them into tasks directed to AI agents, reviewing and testing each output.

This reflects an AI-directed development workflow — a skill increasingly relevant in modern software engineering — rather than a claim that every line was hand-written unassisted.

## Project Structure

```
.
├── Core/                 # composition root, bootstrap, doctor, config
├── Business/             # risk ledger, policies, calendars, paper engine
├── Orchestration/        # copilot skills, tools, planner, scheduler
├── Services/             # decision brief, journal, notifications
├── Repository/           # persistence base + per-feature repos
├── Providers/            # LLM provider abstraction
├── Agents/               # agent framework primitives
├── Database/             # DB manager, migrations (one file per feature)
├── Tests/                # one file per stage/feature
├── Docs/                 # closeout reports per activation/phase
├── aios_dashboard_csharp/  # Blazor Server dashboard (.NET 8)
├── aios_dashboard_react/   # deprecated, archived — see git history (tag archive/react-dashboard)
├── data/                 # SQLite DB lives here (gitignored; seed via migrations)
├── main.py               # entry point (Python copilot)
├── requirements*.txt     # core + provider/optional/dev/full manifests
├── .env.example          # template (copy to .env, never commit .env)
└── run_*_migrations.py  # standalone migration runners
```

## Installation

```bash
# 1. Clone
git clone https://github.com/munaba/ai-investment-operating-system.git
cd ai-investment-operating-system

# 2. Python env (3.11+)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
# optional — pick what you need:
pip install -r requirements-gemini.txt      # Gemini provider
pip install -r requirements-ollama.txt      # Ollama provider
pip install -r requirements-optional.txt    # chart/backtest/market-data
pip install -r requirements-dev.txt         # test suite
# or everything:
# pip install -r requirements-full.txt

# 3. Configure
cp .env.example .env
# edit .env: set ACTIVE_PROVIDER, GEMINI_API_KEY / OLLAMA_HOST, etc.

# 4. Database (creates data/investment_platform.db)
python run_watchlist_migrations.py
python run_position_migrations.py
python run_order_migrations.py
python run_trade_migrations.py
python run_snapshot_migrations.py
python run_portfolio_snapshot_migrations.py
python run_account_migrations.py
python run_risk_ledger_migrations.py
python run_decision_brief_migrations.py
python run_observation_window_migrations.py
python run_sustained_use_final_review_migrations.py
# (or run the subset you need — each script is idempotent)
```

### C# Dashboard

```bash
cd aios_dashboard_csharp
dotnet restore
dotnet run
# → http://localhost:5000
# default account is seeded; reset password:
dotnet run --project reset-password
```

## Running

```bash
# Python copilot (uses Core/composition_root + .env)
python main.py

# Telegram / notification wiring is credential-gated — without
# TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID the app still starts; doctor
# reports the gap and no message is sent (fail-closed).

# Tests
pytest -q
# or: python -m pytest Tests/test_stage9_4_startup_validation.py -v
```

## Status

Actively developed — **Phase H (Sustained-use review, no automatic expansion)**. Phases A–G are gated and closed (see `Docs/` closeout reports). The roadmap in `AIOS_Personal_IDX_Decision_Agent_Roadmap.md` is the source of truth for scope and gates.

## Disclaimer

> This project is built for **learning and technical demonstration** purposes. It is **not** a broker, financial adviser, or autonomous trading bot, and does **not** submit live orders. Nothing here constitutes investment or financial advice. A human is always the final decision-maker and acts at their own broker at their own risk.

## Author

**Nabil** — GitHub: `github.com/munaba` · LinkedIn: `linkedin.com/in/munaba` · Email: `munaba@example.com`

## License

MIT — see [LICENSE](LICENSE).
