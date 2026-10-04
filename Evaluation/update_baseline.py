#!/usr/bin/env python3
"""Update Evaluation/baseline.json dengan metrik run terbaru.

Script eksplisit (bukan otomatis) untuk memperbarui baseline setelah
perbaikan yang disengaja — upgrade engine, fix bug, tambah test case.
Jangan pernah di-commit tanpa verifikasi manual bahwa perbaikan itu
benar-benar perbaikan, bukan regresi yang diberi label "improvement".

Usage:
    python Evaluation/update_baseline.py

Akan:
1. Jalankan run_eval.py
2. Ambil metrik dari run_eval_report.json
3. Tulis ke baseline.json dengan timestamp + commit baru
4. Tunjukkan diff sebelum vs sesudah
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
_PY = sys.executable


def main() -> None:
    print("=== Update baseline.json ===\n")
    
    baseline_path = _PROJ / "Evaluation" / "baseline.json"
    if baseline_path.exists():
        old_baseline = json.loads(baseline_path.read_text())
        print(f"Old baseline: {old_baseline['generated_at']} @ {old_baseline['commit'][:7]}")
    else:
        old_baseline = None
        print("No existing baseline.json")
    
    # Run eval
    print("\nRunning Evaluation/run_eval.py...")
    result = subprocess.run(
        [_PY, str(_PROJ / "Evaluation" / "run_eval.py")],
        cwd=_PROJ,
        capture_output=True,
        text=True,
    )
    print(f"Exit code: {result.returncode}")
    
    report_path = _PROJ / "Evaluation" / "run_eval_report.json"
    if not report_path.exists():
        print("ERROR: run_eval_report.json not generated")
        sys.exit(1)
    
    data = json.loads(report_path.read_text())
    details = data["details"]
    
    # Get current commit
    commit_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_PROJ,
        capture_output=True,
        text=True,
    )
    commit = commit_result.stdout.strip()
    
    # Build new baseline
    now_utc = datetime.now(timezone.utc)
    # Convert to WIB (UTC+7)
    from datetime import timedelta
    now_wib = now_utc + timedelta(hours=7)
    timestamp = now_wib.strftime("%Y-%m-%dT%H:%M+07:00")
    
    new_baseline = {
        "generated_at": timestamp,
        "commit": commit,
        "L2_expectancy_golden": details["L2_expectancy_golden"],
        "L2_max_drawdown_golden": details["L2_max_drawdown_golden"],
        "L2_forex_max_loss_golden": details["L2_forex_max_loss_golden"],
        "L2_position_performance_golden": details["L2_position_performance_golden"],
        "L2_profit_factor_golden": details["L2_profit_factor_golden"],
        "L2_expectancy_property": details["L2_expectancy_property"],
        "L2_max_drawdown_property": details["L2_max_drawdown_property"],
        "L2_position_performance_property": details["L2_position_performance_property"],
        "L2_profit_factor_property": details["L2_profit_factor_property"],
        "L1_gap_count": details["L1_data"]["failed"],
        "L4_recall": None,  # DATA_TIDAK_CUKUP saat ini
        "L4_fpr": None,
        "L3_abstain_synthetic": details["L3_abstain_calibration_synthetic"],
    }
    
    # Show diff
    print("\n=== Metric changes ===")
    if old_baseline:
        for key in new_baseline:
            if key in ("generated_at", "commit"):
                continue
            old_val = old_baseline.get(key)
            new_val = new_baseline[key]
            if old_val != new_val:
                print(f"  {key}: {old_val} -> {new_val}")
        if old_baseline == new_baseline:
            print("  (no changes)")
    else:
        print("  (new baseline)")
    
    # Write
    baseline_path.write_text(json.dumps(new_baseline, indent=2))
    print(f"\nWrote {baseline_path}")
    print(f"New baseline: {timestamp} @ {commit[:7]}")
    print("\nReview the diff, then commit if this is a genuine improvement.")


if __name__ == "__main__":
    main()
