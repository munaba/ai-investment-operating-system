"""Regression proof: RotatingFileHandler rollover tolerates WinError 32.

All files live under pytest's tmp_path -- the real logs/app.log is never
opened, renamed, deleted, or modified by this suite.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

import pytest

from Core.logger import WinError32SafeRotatingFileHandler


def _record(text: str) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, text, (), None)


def _handler(path: Path) -> WinError32SafeRotatingFileHandler:
    handler = WinError32SafeRotatingFileHandler(
        str(path), maxBytes=40, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def test_normal_rotation_creates_backup(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    handler = _handler(log)
    try:
        handler.emit(_record("A" * 80))
        handler.emit(_record("B" * 80))
        assert (tmp_path / "app.log.1").exists()
        assert "A" * 80 in (tmp_path / "app.log.1").read_text(encoding="utf-8")
        assert "B" * 80 in log.read_text(encoding="utf-8")
    finally:
        handler.close()


@pytest.mark.skipif(sys.platform != "win32", reason="WinError 32 is Windows-only")
def test_winerror32_rollover_keeps_writing_without_logging_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "app.log"
    handler = _handler(log)
    try:
        handler.emit(_record("A" * 80))

        def _deny_rename(src: str, dst: str) -> None:
            raise ctypes.WinError(32)

        monkeypatch.setattr(os, "rename", _deny_rename)
        handler.emit(_record("B" * 80))  # must not raise
        handler.emit(_record("keep-me"))

        captured = capsys.readouterr()
        assert "Logging error" not in captured.err
        assert "keep-me" in log.read_text(encoding="utf-8")
    finally:
        handler.close()


def test_other_permission_error_propagates_from_do_rollover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "app.log"
    handler = _handler(log)
    try:
        handler.emit(_record("A" * 80))

        def _deny_rename(src: str, dst: str) -> None:
            raise PermissionError(5, "access denied")

        monkeypatch.setattr(os, "rename", _deny_rename)
        with pytest.raises(PermissionError):
            handler.doRollover()
    finally:
        handler.close()
