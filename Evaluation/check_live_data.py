#!/usr/bin/env python3
"""Read-only health check: run eval against a backup copy of the live DB."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
_PY = sys.executable

def main():
    raw_path = os.environ.get("AIOS_EVAL_DB_PATH", "data/investment_platform.db")
    src_path = Path(raw_path).resolve()
    if not src_path.exists():
        print(f"Live DB not found at: {src_path}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmpdir:
        backup_path = Path(tmpdir) / "live_backup.db"
        
        # 1. Copy using sqlite3 backup API (safe even under active WAL)
        src_conn = sqlite3.connect(str(src_path))
        dst_conn = sqlite3.connect(str(backup_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # 2. Run eval on the backup copy
        env = {
            **os.environ,
            "AIOS_EVAL_DB_PATH": str(backup_path),
            "AIOS_EVAL_READ_ONLY": "1",
        }
        result = subprocess.run([str(_PY), str(_PROJ / "Evaluation" / "run_eval.py")], cwd=_PROJ, env=env)
        
        report_path = _PROJ / "Evaluation" / "run_eval_report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            l1 = report["details"]["L1_data"]
            print(json.dumps({"L1_data": l1}, indent=2))
        return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
