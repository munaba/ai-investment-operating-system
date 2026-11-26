"""Regression tests for the git binary used by the dashboard publisher."""
from __future__ import annotations

import sys
from pathlib import Path

_DASH_DIR = Path(__file__).resolve().parent.parent / "Dashboard"
if str(_DASH_DIR) not in sys.path:
    sys.path.insert(0, str(_DASH_DIR))

import publish_snapshot  # noqa: E402


def test_windowsapps_git_on_path_falls_back_to_system_git(monkeypatch, tmp_path: Path) -> None:
    """A git bundled under WindowsApps cannot be spawned; use the real install."""
    fake_git = tmp_path / "git.exe"
    fake_git.write_text("", encoding="utf-8")
    monkeypatch.setattr(publish_snapshot.shutil, "which", lambda _: r"C:\Program Files\WindowsApps\Hermes\git.exe")
    monkeypatch.setattr(publish_snapshot, "_SYSTEM_GIT_PATHS", (str(fake_git),))
    monkeypatch.setattr(publish_snapshot.os, "name", "nt")

    assert publish_snapshot._git_executable() == str(fake_git)


def test_launchable_git_on_path_is_kept(monkeypatch) -> None:
    monkeypatch.setattr(publish_snapshot.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(publish_snapshot.os, "name", "posix")

    assert publish_snapshot._git_executable() == "/usr/bin/git"


def test_git_invocation_uses_resolved_executable(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = b"ok\n"
        stderr = b""

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return Result()

    monkeypatch.setattr(publish_snapshot, "_git_executable", lambda: r"C:\real\git.exe")
    monkeypatch.setattr(publish_snapshot.subprocess, "run", fake_run)

    assert publish_snapshot._git("hash-object", "-w", "snapshot.json") == "ok"
    assert calls[0] == [r"C:\real\git.exe", "hash-object", "-w", "snapshot.json"]
