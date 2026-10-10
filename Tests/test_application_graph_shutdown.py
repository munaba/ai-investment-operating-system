"""Test ApplicationGraph.shutdown() closes database without leaked connection warning.

Verifies that normal startup/shutdown does NOT trigger the
"Reclaimed and closed leaked connection" log message, which would
indicate a connection that escaped deterministic cleanup.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.composition_root import build_application


class LeakDetectionHandler(logging.Handler):
    """Captures log records containing leak-related messages."""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "Reclaimed and closed leaked connection" in msg or "leaked connection" in msg.lower():
            self.records.append(record)


@pytest.mark.parametrize("use_context_manager", [False, True])
def test_shutdown_closes_database_without_leak_warning(use_context_manager: bool, caplog: pytest.LogCaptureFixture) -> None:
    """Verify ApplicationGraph.shutdown() prevents leaked connection logs."""
    leak_handler = LeakDetectionHandler()
    logging.root.addHandler(leak_handler)
    
    try:
        if use_context_manager:
            with build_application() as app:
                db = app.database_manager
                db.connect()
                assert db.is_connected
            # __exit__ called shutdown()
        else:
            app = build_application()
            db = app.database_manager
            db.connect()
            assert db.is_connected
            app.shutdown()
        
        # After shutdown, no connection should remain
        # The leak detection finalizer should NOT have fired
        leaked = [r for r in leak_handler.records if "Reclaimed and closed leaked" in r.getMessage()]
        assert len(leaked) == 0, f"Leaked connection warning found: {leaked}"
    finally:
        logging.root.removeHandler(leak_handler)
