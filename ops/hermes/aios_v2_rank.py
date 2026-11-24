"""Hermes no-agent wrapper: one `python main.py v2 rank --market <m>` run.

Used by two cron jobs through tiny entry scripts (aios_v2_rank_idx.py,
aios_v2_rank_us.py). The app itself sends the Telegram picks on a new
rebalance; this wrapper only reports.

Output contract (Hermes delivers stdout; exit 1 = failure):
  - the command's summary lines, exit 0   : ranking stored (or already stored)
  - "AIOS v2 <M> ALERT ...", exit 1        : non-zero rc, timeout or traceback
"""
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The AIOS checkout this machine runs from (ops/setup_server.ps1 sets AIOS_REPO).
REPO = os.environ.get("AIOS_REPO") or r"F:\My Son"
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")
LOG = Path(os.environ.get("AIOS_WRAPPER_DIR") or Path(os.environ["LOCALAPPDATA"]) / "AIOS") / "v2_rank.log"
WIB = timezone(timedelta(hours=7), "WIB")


def run(market: str) -> int:
    now = datetime.now(WIB).isoformat(timespec="seconds")
    try:
        p = subprocess.run(
            [PY, "main.py", "v2", "rank", "--market", market],
            cwd=REPO, env={**os.environ, "PYTHONPATH": "."},
            capture_output=True, text=True, timeout=180,
        )
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = -1, "", "timed out after 180s"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{now} market={market} rc={rc} stdout={out[-4000:]!r} stderr={err[-4000:]!r}\n")

    summary = [line for line in out.splitlines() if line.startswith(("V2 RANK", "  "))]
    if rc != 0 or "Traceback" in out or "Traceback" in err:
        print(f"AIOS v2 {market.upper()} ALERT rc={rc}")
        for line in (summary or (out + err).splitlines())[-8:]:
            print(line)
        return 1
    print("\n".join(summary) or f"AIOS v2 {market.upper()}: no output")
    return 0
