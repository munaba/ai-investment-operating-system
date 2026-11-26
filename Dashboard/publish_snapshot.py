"""Export a fresh snapshot and publish it to the `dashboard-data` branch.

Run from the repository root with the AIOS virtualenv:

    python Dashboard/publish_snapshot.py

The branch always holds exactly one commit containing `snapshot.json`; each
publish replaces it (force-push), so daily refreshes never add commits to
master. The working tree, index and current branch are not touched: the
commit is built with git plumbing (hash-object, mktree, commit-tree).

The hosted dashboard reads the file from
https://raw.githubusercontent.com/<owner>/<repo>/dashboard-data/snapshot.json
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from export_snapshot import DEFAULT_DB, REPO_ROOT, export

BRANCH = "dashboard-data"


#: Runs unattended (Hermes scheduled task, no console): git must fail fast
#: instead of waiting for a credential prompt nobody can answer.
_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GIT_ASKPASS": "",
}
_GIT_TIMEOUT_SECONDS = 60

#: Git for Windows installs here. A git bundled under WindowsApps cannot be
#: launched by a regular CreateProcess on this host (WinError 5).
_SYSTEM_GIT_PATHS = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
)


def _git_executable() -> str:
    """Return a git binary that the scheduled job can actually launch.

    The Hermes-bundled git under ``C:\\Program Files\\WindowsApps`` is first on
    PATH, but spawning it raises ``PermissionError: [WinError 5]`` before git
    runs at all (PUBLISH ok=False in idx_tick.log). Prefer the system install.
    """
    on_path = shutil.which("git")
    if os.name == "nt" and (not on_path or "windowsapps" in on_path.lower()):
        for candidate in _SYSTEM_GIT_PATHS:
            if Path(candidate).is_file():
                return candidate
    return on_path or "git"


def _step(label: str, started: float) -> None:
    print(f"  {label}: {time.monotonic() - started:.1f}s", file=sys.stderr, flush=True)


def _git(*args: str, stdin: str | None = None) -> str:
    # Bytes, not text mode: on Windows text mode turns "\n" into "\r\n",
    # which would make mktree record the file name as "snapshot.json\r".
    try:
        result = subprocess.run(
            [_git_executable(), *args],
            cwd=REPO_ROOT,
            input=stdin.encode("utf-8") if stdin is not None else None,
            capture_output=True,
            check=False,
            env=_GIT_ENV,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"git {args[0]} timed out after {_GIT_TIMEOUT_SECONDS}s (credentials prompt?)") from None
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode("utf-8").strip()


def publish(db_path: Path = DEFAULT_DB, remote: str = "origin") -> str:
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        snapshot_file = Path(tmp) / "snapshot.json"
        export(db_path, snapshot_file)
        _step("export + evaluation", started)
        blob = _git("hash-object", "-w", str(snapshot_file))

    tree = _git("mktree", stdin=f"100644 blob {blob}\tsnapshot.json\n")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    commit = _git("commit-tree", tree, "-m", f"data: dashboard snapshot {stamp}")
    _step("local commit", started)
    _git("push", "--force", remote, f"{commit}:refs/heads/{BRANCH}")
    _step("push", started)
    return commit


if __name__ == "__main__":
    sha = publish()
    print(f"Published snapshot to {BRANCH} ({sha[:7]})")
    sys.exit(0)
