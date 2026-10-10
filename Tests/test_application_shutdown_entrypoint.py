"""Test main.py application shutdown"""
import sys
import logging
import pytest
from main import main
from Tests.test_application_graph_shutdown import LeakDetectionHandler

def test_main_repl_shuts_down_properly(monkeypatch):
    leak_handler = LeakDetectionHandler()
    logging.root.addHandler(leak_handler)
    monkeypatch.setattr("builtins.input", lambda *a, **k: exec("raise EOFError()"))
    try:
        main()
        leaked = [r for r in leak_handler.records if "leaked connection" in r.getMessage()]
        assert not leaked, "Leaked connection found during main() REPL exit"
    finally:
        logging.root.removeHandler(leak_handler)
