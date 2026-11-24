"""Hermes no-agent wrapper: one AIOS `scheduler idx-tick` run per cron fire.

Output contract (Hermes delivers stdout; exit 1 = alert):
  - silent, exit 0   : nothing noteworthy (routine data_health_check /
                       session_scan succeeded, or no job considered)
  - lines,  exit 0   : a once-per-day job ran and succeeded
  - ALERT,  exit 1   : non-zero rc, Traceback, unparseable output, any
                       attempted job with outcome != SUCCESS, or a
                       session_scan that ranked 0 symbols (once per day)
  - SKIPPED, exit 1  : Yahoo unreachable during session hours (first time
                       per local date only; later skips that day are silent)

Words such as "error", "failed" or "WARNING" in the app's own log lines
never trigger an alert on their own.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

# The AIOS checkout this machine runs from (ops/setup_server.ps1 sets AIOS_REPO).
REPO = os.environ.get("AIOS_REPO") or r"F:\My Son"
PY = os.path.join(REPO, ".venv", "Scripts", "python.exe")
PUBLISH_SCRIPT = Path(REPO) / "Dashboard" / "publish_snapshot.py"
# Publish the dashboard snapshot once the day's closing review has run.
PUBLISH_AFTER_JOB = "daily_review"
STATE_DIR = Path(os.environ.get("AIOS_WRAPPER_DIR") or Path(os.environ["LOCALAPPDATA"]) / "AIOS")
LOG = STATE_DIR / "idx_tick.log"
OLD = STATE_DIR / "idx_tick.log.old"
STATE = STATE_DIR / "idx_tick_state.json"
MAX_LOG = 5 * 1024 * 1024
MAX_FIELD = 20000

# WIB is UTC+7 all year (no DST); a fixed offset avoids needing tzdata on Windows.
WIB = timezone(timedelta(hours=7), "WIB")

# Yahoo is only needed while session_scan can fire (IDX open session,
# Business/idx_market_calendar.py: 09:00-12:00 and 13:30-15:49).
FETCH_WINDOWS = ((time(9, 0), time(12, 0)), (time(13, 30), time(15, 49)))

# Jobs that run on every eligible tick; silent when they succeed.
ROUTINE_JOBS = {"data_health_check", "session_scan"}

HEADER_RE = re.compile(r"^IDX SCHEDULER TICK\s")
NO_JOB_RE = re.compile(r"^\s+\(no job considered this tick")
JOB_RE = re.compile(r"^\s+- (?P<job>\w+): attempted=(?P<att>True|False) outcome=(?P<out>\w+)(?: detail=(?P<detail>.*))?$")

PROBE_CODE = (
    "import sys, yfinance as yf\n"
    "d = yf.Ticker('BBCA.JK').history(period='5d')\n"
    "sys.exit(0 if len(d) > 0 else 2)\n"
)


def now_wib():
    return datetime.now(WIB)


def in_fetch_window(now):
    t = now.timetz().replace(tzinfo=None)
    return now.weekday() < 5 and any(a <= t < b for a, b in FETCH_WINDOWS)


def yahoo_ok():
    try:
        r = subprocess.run([PY, "-c", PROBE_CODE], cwd=REPO, capture_output=True, text=True, timeout=25)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def run_tick():
    p = subprocess.run(
        [PY, "main.py", "scheduler", "idx-tick"],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": "."},
        capture_output=True,
        text=True,
        timeout=240,
    )
    return p.returncode, p.stdout, p.stderr


def publish_snapshot():
    """Run Dashboard/publish_snapshot.py; returns (ok, output)."""
    if not PUBLISH_SCRIPT.is_file():
        return True, "publish skipped: Dashboard/publish_snapshot.py not present"
    try:
        p = subprocess.run([PY, str(PUBLISH_SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "publish timed out after 180s"
    return p.returncode == 0, (p.stdout + p.stderr).strip()


BACKUP_KEEP = 14  # daily backups kept in data\backups


def backup_db():
    """Run `main.py backup --keep N` (verified backup + retention); returns (ok, output)."""
    if "prune_backups" not in (Path(REPO) / "main.py").read_text(encoding="utf-8", errors="ignore"):
        return True, "backup skipped: this checkout's main.py has no --keep support yet"
    try:
        p = subprocess.run([PY, "main.py", "backup", "--keep", str(BACKUP_KEEP)], cwd=REPO,
                           env={**os.environ, "PYTHONPATH": "."}, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "backup timed out after 180s"
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def write_log(now, text):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > MAX_LOG:
        os.replace(LOG, OLD)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{now.isoformat(timespec='seconds')} {text}\n")


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state), encoding="utf-8")


def once_per_day(key, today):
    """True the first time `key` is seen on `today` (local date)."""
    state = load_state()
    if state.get(key) == today:
        return False
    state[key] = today
    save_state(state)
    return True


def alert(summary, out, err):
    print(f"AIOS idx-tick ALERT: {summary}")
    for line in (out.splitlines() + err.splitlines())[-10:]:
        print(line)
    return 1


def parse_jobs(out):
    header = no_job = False
    jobs = []
    for line in out.splitlines():
        if HEADER_RE.match(line):
            header = True
        elif NO_JOB_RE.match(line):
            no_job = True
        else:
            m = JOB_RE.match(line)
            if m:
                jobs.append(m.groupdict())
    return header, no_job, jobs


def detail_json(detail):
    try:
        v = json.loads(detail or "")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def main(now=None, probe=yahoo_ok, tick=run_tick, publish=publish_snapshot, backup=backup_db):
    now = now or now_wib()
    today = now.date().isoformat()

    if in_fetch_window(now) and not probe():
        write_log(now, "SKIPPED provider_down")
        if once_per_day("provider_down", today):
            print("AIOS idx-tick SKIPPED: Yahoo unreachable")
            return 1
        return 0

    rc, out, err = tick()
    write_log(now, f"rc={rc} stdout={out[-MAX_FIELD:]!r} stderr={err[-MAX_FIELD:]!r}")

    if rc != 0:
        return alert(f"rc={rc}", out, err)
    if "Traceback" in err or "Traceback" in out:
        return alert("Traceback in output", out, err)

    header, no_job, jobs = parse_jobs(out)
    if not header or (not jobs and not no_job):
        return alert("unrecognised idx-tick output", out, err)

    bad = [j for j in jobs if j["att"] == "True" and j["out"] != "SUCCESS"]
    if bad:
        return alert(", ".join(f"{j['job']}={j['out']}" for j in bad), out, err)

    for j in jobs:
        if j["job"] == "session_scan" and j["att"] == "True":
            if detail_json(j["detail"]).get("total_symbols", 0) == 0 and once_per_day("empty_scan", today):
                return alert("session_scan ranked 0 symbols", out, err)

    lines = []
    for j in jobs:
        if j["att"] != "True" or j["job"] in ROUTINE_JOBS:
            continue
        d = detail_json(j["detail"])
        extra = d.get("status") or d.get("title") or ""
        lines.append(f"AIOS {j['job']}: {j['out']}" + (f" ({extra})" if extra else ""))

    # Closing steps (backup, then publish) start on the tick where
    # daily_review ran and are retried on later ticks the same day until
    # each succeeds once (2026-11-24: the single 15:50 attempt timed out
    # and nothing tried again).
    state = load_state()
    if any(j["job"] == PUBLISH_AFTER_JOB and j["att"] == "True" for j in jobs):
        state["closing_date"] = today
        save_state(state)
    if state.get("closing_date") == today:
        if state.get("backup_done") != today:
            ok, output = backup()
            write_log(now, f"BACKUP ok={ok} {output[-MAX_FIELD:]!r}")
            if not ok:
                if lines:
                    print("\n".join(lines))
                return alert("daily database backup failed (will retry next tick)", output, "")
            state["backup_done"] = today
            save_state(state)
            lines.append(f"AIOS backup: {output.splitlines()[-1] if output else 'done'}")

        if state.get("publish_done") != today:
            ok, output = publish()
            write_log(now, f"PUBLISH ok={ok} {output[-MAX_FIELD:]!r}")
            if not ok:
                if lines:
                    print("\n".join(lines))
                return alert("dashboard snapshot publish failed (will retry next tick)", output, "")
            state["publish_done"] = today
            save_state(state)
            lines.append(f"AIOS dashboard: {output.splitlines()[-1] if output else 'published'}")

    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
