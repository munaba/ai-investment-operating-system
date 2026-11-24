# Operations

How AIOS runs unattended, and how to move it to another Windows machine.

Exactly one machine runs AIOS at a time: the scheduler writes a local
SQLite database, so two machines would produce two diverging databases.

## What runs where

| Hermes job | Schedule (WIB) | What it does |
|---|---|---|
| `AIOS idx-tick` | every 5 min, 08:00-15:55, Mon-Fri | `main.py scheduler idx-tick`; after the daily review: verified backup and dashboard publish, retried on later ticks if they fail (`hermes/aios_idx_tick.py`) |
| `AIOS v2 rank IDX` | 08:30 Mon-Fri | `main.py v2 rank --market idx`; picks go to Telegram on a rebalance (`hermes/aios_v2_rank_idx.py`) |
| `AIOS v2 rank US` | 20:45 Mon-Fri | same for US stocks, before the US open |
| `AIOS daily audit` | 07:30, 12:30, 20:30 | agent job in a separate worktree: audit, at most one small fix, tests, push (`hermes/daily_audit_prompt.txt`) |

`9router/` starts the local model gateway at logon; the audit job uses its
`HERMES` model. The wrapper scripts read the checkout path from the
`AIOS_REPO` environment variable.

## Moving to the laptop

1. On the laptop, install Git, Python 3.14, Node.js, 9router
   (`npm install -g 9router`, start it once and sign in) and Hermes (sign in
   to Telegram there). Then:

   ```powershell
   git clone https://github.com/munaba/ai-investment-operating-system.git C:\AIOS
   powershell -ExecutionPolicy Bypass -File C:\AIOS\ops\setup_server.ps1 -RepoDir C:\AIOS
   ```

   This creates `.venv`, installs the scripts and autostart, keeps the
   laptop awake on AC power with the lid closed, and creates the jobs
   **paused**.
2. Copy `.env` from the PC to the laptop's checkout by hand (USB or a
   password manager). Never commit it or paste it into a chat.
3. On the PC, after 16:00 WIB:

   ```powershell
   powershell -ExecutionPolicy Bypass -File "F:\My Son\ops\export_db_from_pc.ps1" -OutDir E:\aios-handover
   ```

   It pauses the PC's AIOS jobs, takes a verified backup and copies the
   database with its SHA-256.
4. On the laptop:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\AIOS\ops\import_db_on_laptop.ps1 -From E:\aios-handover
   ```

   It checks the hash and integrity, runs one harmless tick and resumes the
   laptop's jobs.
5. Watch one full trading day: `%LOCALAPPDATA%\AIOS\idx_tick.log`,
   `%LOCALAPPDATA%\AIOS\v2_rank.log`, the Telegram messages and the
   dashboard. To roll back, pause the laptop's jobs and resume the PC's
   (`Import-Module ops\AiosHermesJobs.psm1; Set-AiosJobsState resume`).

## Keeping a 24/7 laptop healthy

- Keep it on AC power; if the maker's tool offers a battery charge limit
  (60-80%), turn it on.
- Startup-folder programs only start after a login. After a Windows Update
  restart nobody logs in, so either enable automatic login (`netplwiz`) or
  set Windows Update active hours to cover 08:00-23:00.
- Prefer a wired network connection.
