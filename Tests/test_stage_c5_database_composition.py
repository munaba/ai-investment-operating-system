"""
Stage C5 proof suite -- Database Layer -> Composition Root.

Scope (per this session's LOCKED design decision, explicit approval given
to reopen ``Core/composition_root.py``):
  - ``Core.composition_root.build_application()`` now also constructs a
    ``Database.database_manager.DatabaseManager`` wrapping a
    ``Database.sqlite_database.SQLiteDatabase`` (built from
    ``Database.database_config.DatabaseConfig.from_env()``), and exposes
    it as ``ApplicationGraph.database_manager``.
  - Construct-only: ``DatabaseManager.connect()`` is never called by
    ``build_application()``. No migration is run. No ``.db`` file is
    created. This suite proves that by observation, not by reading
    source text.
  - Nothing about the Stage 9.0-9.4 contract (hermeticity, idempotency,
    singleton identity, agent registration) is changed. This suite
    re-proves those specific properties still hold for the *new* field
    without duplicating the full Stage 9.0/9.3/9.4 suites -- those are
    run separately as the full regression proof.
  - ``Database.*``, ``Repository.*``, ``Core.runtime``, ``Agents.executor``,
    ``Agents.base_agent``, ``Core.startup_validation``, ``Core.approval*``,
    ``main.py`` -- untouched, out of scope.

Cakupan skenario (test plan yang disepakati):
  1. build_application() tetap hermetic (no network, no external package,
     no secret required).
  2. Tidak ada file/direktori SQLite yang dibuat oleh build_application().
  3. DatabaseManager berhasil dikonstruksi (real class, not a fake).
  4. SQLiteDatabase berhasil dikonstruksi, unconnected.
  5. graph.database_manager.database is-a SQLiteDatabase.
  6. build_application() dipanggil dua kali tetap aman (tidak raise, dan
     database_manager tetap fresh instance tiap panggilan -- bukan
     singleton, didokumentasikan eksplisit sebagai bukan bug).
  7. Full regression (Stage 9.0/9.3/9.4 dan seluruh Tests/test_*.py lain)
     dijalankan terpisah, bukan bagian dari file ini -- dicatat di
     laporan, bukan di sini, supaya file ini tetap fokus pada Stage C5.

All filesystem/env mutation is wrapped in try/finally to avoid leaking
state into other scenarios or other test files run in the same process.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.composition_root import ApplicationGraph, build_application
from Database.database_manager import DatabaseManager
from Database.sqlite_database import SQLiteDatabase

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _EnvSandbox:
    """Context manager: set the given env vars, always restore the
    previous values (including "was unset") on exit. Same pattern as
    Tests/test_stage9_4_startup_validation.py::_EnvSandbox."""

    def __init__(self, **overrides: Optional[str]) -> None:
        self._overrides = overrides
        self._previous: dict[str, Optional[str]] = {}

    def __enter__(self) -> "_EnvSandbox":
        for key, value in self._overrides.items():
            self._previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc_info: object) -> None:
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Scenario 1 + 3 + 4 + 5 -- graph builds, database_manager is real and
# construct-only.
# ---------------------------------------------------------------------------
def scenario_graph_builds_with_database_manager() -> ApplicationGraph:
    graph = build_application(
        provider_name="gemini-stage-c5-test",
        agent_name="stock_agent-stage-c5-test",
    )
    check(isinstance(graph, ApplicationGraph), "build_application() returns an ApplicationGraph")
    check(
        isinstance(graph.database_manager, DatabaseManager),
        "graph.database_manager is a real DatabaseManager (not a fake/double)",
    )
    check(
        isinstance(graph.database_manager.database, SQLiteDatabase),
        "graph.database_manager.database is a real SQLiteDatabase",
    )
    check(
        graph.database_manager.is_connected is False,
        "graph.database_manager is NOT connected -- build_application() is construct-only",
    )
    return graph


# ---------------------------------------------------------------------------
# Scenario 2 -- no filesystem I/O: no db file/directory created, no DB_PATH
# required.
# ---------------------------------------------------------------------------
def scenario_no_sqlite_file_created_and_no_db_path_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cwd_before = os.getcwd()
        try:
            os.chdir(tmp)
            with _EnvSandbox(DB_PATH=None):
                before = set(Path(tmp).rglob("*"))
                graph = build_application(
                    provider_name="gemini-stage-c5-fsio",
                    agent_name="stock_agent-stage-c5-fsio",
                )
                after = set(Path(tmp).rglob("*"))
                check(
                    before == after,
                    f"build_application() created no new file/directory under cwd (new entries: {after - before})",
                )
                check(
                    isinstance(graph.database_manager, DatabaseManager),
                    "build_application() still succeeds with DB_PATH unset (uses documented default)",
                )
        finally:
            os.chdir(cwd_before)


# ---------------------------------------------------------------------------
# Scenario 1 (hermeticity) -- no external package / secret required, no
# network. Re-confirms the same environment probe Stage 9.0 already
# recorded still holds after Stage C5's addition.
# ---------------------------------------------------------------------------
def scenario_hermetic_no_external_dependency_required() -> None:
    import importlib.util

    has_gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
    has_google_genai = importlib.util.find_spec("google.generativeai") is not None
    has_yfinance = importlib.util.find_spec("yfinance") is not None
    print(
        f"  INFO - environment: GEMINI_API_KEY={'set' if has_gemini_key else 'unset'}, "
        f"google-generativeai={'installed' if has_google_genai else 'absent'}, "
        f"yfinance={'installed' if has_yfinance else 'absent'}"
    )
    raised: Optional[Exception] = None
    try:
        build_application(
            provider_name="gemini-stage-c5-hermetic",
            agent_name="stock_agent-stage-c5-hermetic",
        )
    except Exception as exc:  # noqa: BLE001
        raised = exc
    check(
        raised is None,
        f"build_application() succeeds with no secrets/external packages present (got: {raised!r})",
    )


# ---------------------------------------------------------------------------
# Scenario 6 -- idempotent / safe to call twice; database_manager is a
# fresh instance each call (documented as correct, not a bug).
# ---------------------------------------------------------------------------
def scenario_build_application_twice_is_safe() -> None:
    graph_a = build_application(
        provider_name="gemini-stage-c5-idempotency",
        agent_name="stock_agent-stage-c5-idempotency",
    )
    raised: Optional[Exception] = None
    graph_b: Optional[ApplicationGraph] = None
    try:
        graph_b = build_application(
            provider_name="gemini-stage-c5-idempotency",
            agent_name="stock_agent-stage-c5-idempotency",
        )
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(raised is None, f"calling build_application() twice does not raise (got: {raised!r})")
    if graph_b is not None:
        check(
            isinstance(graph_b.database_manager, DatabaseManager),
            "second call also returns a real DatabaseManager",
        )
        check(
            graph_a.database_manager is not graph_b.database_manager,
            "database_manager is a fresh instance per call (not a singleton -- documented, expected)",
        )
        check(
            graph_a.agent_registry is graph_b.agent_registry,
            "singleton registries (unaffected by C5) are still shared across calls",
        )
        check(
            graph_b.database_manager.is_connected is False,
            "second call's database_manager is also unconnected",
        )


def main() -> int:
    scenarios = [
        scenario_graph_builds_with_database_manager,
        scenario_no_sqlite_file_created_and_no_db_path_required,
        scenario_hermetic_no_external_dependency_required,
        scenario_build_application_twice_is_safe,
    ]

    import traceback

    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE C5 DATABASE COMPOSITION TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())