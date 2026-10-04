#!/usr/bin/env python3
"""L5 Tick Runner — idempotent scheduler tick CLI.

Usage:
    python Orchestration/tick_runner.py [--dry-run]

Calls idx_daily_scheduler.tick(now) once. With --dry-run, logs only (no DB writes).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJ))

from Core.composition_root import build_application


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    app = build_application()
    scheduler = app.idx_daily_scheduler
    now = datetime.now(timezone.utc)
    
    print(f"=== AIOS L5 Tick Runner ===")
    print(f"Now (UTC): {now.isoformat()}")
    print(f"Dry-run: {dry_run}")
    
    if dry_run:
        print("Dry-run mode: tick() will execute but no DB commit (if supported).")
        print("Note: Current scheduler does not support dry-run rollback internally.")
        print("      Jobs will execute normally. Use test DB or backup before real run.")
    
    tick_result = scheduler.tick(now)
    
    print(f"\nTick result:")
    print(f"  Trading date: {tick_result.trading_date}")
    print(f"  Session: {tick_result.session}")
    print(f"  Jobs scheduled: {len(tick_result.jobs)}")
    for job in tick_result.jobs:
        print(f"    - {job}")
    # reason_no_jobs no longer exists on TickResult
    print(f"  Reason (if none): N/A")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
