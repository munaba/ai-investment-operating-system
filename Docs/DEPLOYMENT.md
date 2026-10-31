# Deployment Guide

## Database Migrations

### Order (CRITICAL)
1. **BACKUP FIRST** - Before any migration on live DB, create a backup (use SQLite backup API or copy `data/investment_platform.db`).
2. **Run snapshot migrations BEFORE any scan** - `python run_snapshot_migrations.py` must be run before `python main.py scan` or any operation that inserts into `ranking_snapshots`. 
3. **Verify** - Confirm migration applied (check `schema_migrations` table for expected version).

### Why
- `SnapshotRepository.create()` uses `INSERT ... ON CONFLICT(scan_time, symbol) DO NOTHING` which requires a UNIQUE constraint/index. Without `ux_ranking_snapshots_scan_time_symbol`, `create()` will raise `ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint` and crash.
- `python run_snapshot_migrations.py` applies ONLY `SNAPSHOTS_MIGRATIONS` (see `run_snapshot_migrations.py`).
- `python main.py init` applies all domain migrations via the migration registry (`_canonical_migrations()`).

### No Auto-Migration on Startup
- **No automatic schema bootstrap/migration at startup.** `build_application()` constructs the app graph but never calls `connect()` or `MigrationRunner.apply()`. 
- The server/dashboard/CLI do not run migrations automatically. All migrations must be run manually by the operator.
- One-shot CLI commands (watchlist/scan/paper/etc.) call `build_application()` and exit immediately after - no migrations are applied.

### Manual Migration Commands
```bash
# Apply only snapshot migrations (required before first scan if v34 not applied)
python run_snapshot_migrations.py

# Apply all migrations
python main.py init
```

### Production Notes
- Deploy order: migrate DB first, then deploy new code. The code cannot create snapshots without the unique index.
- Live DB must never be modified without backup and testing on a copy first.
- Always test migrations on a copy of production DB before applying to live.
