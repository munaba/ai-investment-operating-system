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

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from export_snapshot import DEFAULT_DB, REPO_ROOT, export

BRANCH = "dashboard-data"


def _git(*args: str, stdin: str | None = None) -> str:
    # Bytes, not text mode: on Windows text mode turns "\n" into "\r\n",
    # which would make mktree record the file name as "snapshot.json\r".
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        input=stdin.encode("utf-8") if stdin is not None else None,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode("utf-8").strip()


def publish(db_path: Path = DEFAULT_DB, remote: str = "origin") -> str:
    with tempfile.TemporaryDirectory() as tmp:
        snapshot_file = Path(tmp) / "snapshot.json"
        export(db_path, snapshot_file)
        blob = _git("hash-object", "-w", str(snapshot_file))

    tree = _git("mktree", stdin=f"100644 blob {blob}\tsnapshot.json\n")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    commit = _git("commit-tree", tree, "-m", f"data: dashboard snapshot {stamp}")
    _git("push", "--force", remote, f"{commit}:refs/heads/{BRANCH}")
    return commit


if __name__ == "__main__":
    sha = publish()
    print(f"Published snapshot to {BRANCH} ({sha[:7]})")
    sys.exit(0)
