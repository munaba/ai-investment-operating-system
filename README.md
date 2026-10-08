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

- Python 3.11+
- .NET 8 SDK (for the dashboard)
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
python run_brief_approval_migrations.py
python run_daily_performance_migrations.py
python run_idempotency_migrations.py
python run_llm_output_audit_migrations.py
python run_scheduler_migrations.py
python run_telegram_control_migrations.py
python run_valuation_observation_migrations.py
```

### Run

Python copilot (interactive REPL):

```bash
python main.py
```

C# dashboard (Blazor Server, .NET 8):

```bash
cd aios_dashboard_csharp
cp appsettings.json.example appsettings.json   # then set DashboardAuth:Username and a BCrypt PasswordHash
dotnet restore
dotnet run                                     # default: http://localhost:5000
dotnet run --project reset-password            # generate password hash (hidden input)
```

Login is fail-closed: with no password hash configured, nobody can sign in. `appsettings.json` is git-ignored. The example config binds Kestrel to `0.0.0.0:5000` (reachable from your LAN); change the URL to `http://localhost:5000` if you do not want that.

## Testing

```bash
pip install pytest
PYTHONPATH=. python -m pytest -q          # 204 tests collected
```

Standalone gate scripts (not collected by pytest, run each from the repo root with `PYTHONPATH=.`; 350 checks in total):

| Script | Checks |
|--------|--------|
| `Tests/test_phase_i_gate1_decision_copilot.py` | 120 |
| `Tests/test_phase_i_gate3_cli_bridge.py` | 83 |
| `Tests/test_phase_i_gate3.1_datetime.py` | 65 |
| `Tests/test_phase_a_decision_copilot.py` | 45 |
| `Tests/test_activation12_2_permission_enforcer.py` | 26 |
| `Tests/test_activation12_3_permission_wiring.py` | 11 |

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
| `aios_dashboard_csharp/` | Blazor Server dashboard |

Scheduler details: `README_SCHEDULER.md`.

## Development

Architected and directed by Nabil; implemented through AI-assisted engineering (Claude, ChatGPT, Hermes agent) across iterative phases.

- **Phases A–G**: complete (scanner, analysis, copilot, paper trading, notifications)
- **Phase H**: sustained-use review (observation windows, evidence assembly)
- **Phase I**: evidence profile analysis job added
- **Parked**: US stocks, crypto, forex (IDX only)

## License

No license has been chosen yet; all rights reserved.
