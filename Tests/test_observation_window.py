"""Standalone regression checks for
``Repository.persistence.observation_window_repository.ObservationWindowRepository``
and ``Services.observation_window_service.ObservationWindowService``
(Phase H Task 1 -- "Observation Window + Sustained-Use Review Record").

Covers:

* create/open a window;
* reading it back after a fresh repository instance over the same
  on-disk file (restart survival);
* explicit close, preserving original start/end/timezone/created_at;
* an invalid date range (end not strictly after start) is rejected;
* the operator-supplied timezone is preserved verbatim;
* a second ``open()`` while one window is already ACTIVE is rejected
  deterministically (never silently replaced or auto-closed);
* no trading state (orders/trades/paper execution) is touched by any
  of the above -- verified by asserting the service/repository source
  never references any trading-engine table or component.

Run directly with ``python Tests/test_observation_window.py`` -- no
external test framework required, matching
``test_decision_brief_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_observation_window import OBSERVATION_WINDOW_MIGRATIONS  # noqa: E402
from Database.models import ObservationWindow  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.observation_window_repository import ObservationWindowRepository  # noqa: E402
from Services.observation_window_service import ObservationWindowService  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _build_service(db_path: Path) -> ObservationWindowService:
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(list(OBSERVATION_WINDOW_MIGRATIONS))
    manager = DatabaseManager(db, cfg)
    repo = ObservationWindowRepository(manager)
    return ObservationWindowService(repo)


def scenario_create_open_returns_active_window():
    print("\n[Scenario 1] open() creates an ACTIVE ObservationWindow")
    with tempfile.TemporaryDirectory() as tmp:
        service = _build_service(Path(tmp) / "obs.db")
        window = service.open(
            start_at="2026-07-01T00:00:00",
            end_at="2026-07-31T23:59:59",
            timezone_name="Asia/Jakarta",
            note="August cool-down observation",
        )
        check(isinstance(window, ObservationWindow), "open() returns an ObservationWindow instance")
        check(window.window_id is not None, "opened window has a repository-assigned window_id")
        check(window.status == "ACTIVE", "newly opened window has status ACTIVE")
        check(window.start_at == "2026-07-01T00:00:00", "start_at persisted exactly as supplied")
        check(window.end_at == "2026-07-31T23:59:59", "end_at persisted exactly as supplied")
        check(window.note == "August cool-down observation", "note persisted exactly as supplied")
        check(window.closed_at is None, "newly opened window has no closed_at")


def scenario_retrieve_after_restart():
    print("\n[Scenario 2] a persisted window survives a fresh repository instance (restart survival)")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "obs.db"
        service = _build_service(db_path)
        opened = service.open(
            start_at="2026-06-01T00:00:00",
            end_at="2026-06-30T00:00:00",
            timezone_name="Asia/Jakarta",
        )

        # Fresh connection/service over the SAME on-disk file --
        # simulates a process restart, never reusing the original
        # in-memory objects.
        cfg = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        repo2 = ObservationWindowRepository(manager2)
        service2 = ObservationWindowService(repo2)

        current = service2.get_current()
        check(current is not None, "get_current() finds the window after restart")
        check(current.window_id == opened.window_id, "restart-read window_id matches the originally opened one")
        check(current.start_at == "2026-06-01T00:00:00", "start_at survives restart")
        check(current.end_at == "2026-06-30T00:00:00", "end_at survives restart")
        check(current.status == "ACTIVE", "status survives restart as ACTIVE")


def scenario_close_preserves_original_fields():
    print("\n[Scenario 3] close() transitions to CLOSED and preserves original timestamps")
    with tempfile.TemporaryDirectory() as tmp:
        service = _build_service(Path(tmp) / "obs.db")
        opened = service.open(
            start_at="2026-05-01T00:00:00",
            end_at="2026-05-15T00:00:00",
            timezone_name="Asia/Jakarta",
            note="mid-May check",
        )
        closed = service.close()
        check(closed.status == "CLOSED", "close() transitions status to CLOSED")
        check(closed.window_id == opened.window_id, "close() acts on the currently ACTIVE window")
        check(closed.start_at == opened.start_at, "start_at unchanged by close()")
        check(closed.end_at == opened.end_at, "end_at unchanged by close()")
        check(closed.timezone == opened.timezone, "timezone unchanged by close()")
        check(closed.created_at == opened.created_at, "created_at unchanged by close()")
        check(closed.closed_at is not None, "close() sets closed_at")

        check(service.get_current() is None, "get_current() returns None once the window is closed")

        # closing an already-CLOSED window is rejected, not silently
        # accepted a second time.
        raised = False
        try:
            service.close(opened.window_id)
        except ValueError:
            raised = True
        check(raised, "closing an already-CLOSED window raises ValueError")


def scenario_invalid_date_range_rejected():
    print("\n[Scenario 4] open() rejects an invalid date range")
    with tempfile.TemporaryDirectory() as tmp:
        service = _build_service(Path(tmp) / "obs.db")

        raised_equal = False
        try:
            service.open(start_at="2026-07-01T00:00:00", end_at="2026-07-01T00:00:00", timezone_name="Asia/Jakarta")
        except ValueError:
            raised_equal = True
        check(raised_equal, "open() rejects end_at equal to start_at")

        raised_reversed = False
        try:
            service.open(start_at="2026-07-15T00:00:00", end_at="2026-07-01T00:00:00", timezone_name="Asia/Jakarta")
        except ValueError:
            raised_reversed = True
        check(raised_reversed, "open() rejects end_at before start_at")

        raised_unparseable = False
        try:
            service.open(start_at="not-a-date", end_at="2026-07-01T00:00:00", timezone_name="Asia/Jakarta")
        except ValueError:
            raised_unparseable = True
        check(raised_unparseable, "open() rejects an unparseable start_at")

        check(service.get_current() is None, "no window was persisted after every rejected open() attempt")


def scenario_timezone_preserved():
    print("\n[Scenario 5] the operator-supplied timezone is preserved verbatim")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "obs.db"
        service = _build_service(db_path)
        opened = service.open(
            start_at="2026-04-01T00:00:00",
            end_at="2026-04-30T00:00:00",
            timezone_name="America/New_York",
        )
        check(opened.timezone == "America/New_York", "timezone persisted exactly as supplied on open()")

        cfg = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        service2 = ObservationWindowService(ObservationWindowRepository(manager2))
        current = service2.get_current()
        check(current.timezone == "America/New_York", "timezone survives restart")

        closed = service2.close()
        check(closed.timezone == "America/New_York", "timezone unchanged by close()")

        raised_empty_tz = False
        try:
            service.open(start_at="2026-08-01T00:00:00", end_at="2026-08-02T00:00:00", timezone_name="")
        except ValueError:
            raised_empty_tz = True
        check(raised_empty_tz, "open() rejects an empty timezone_name")


def scenario_duplicate_active_window_rejected():
    print("\n[Scenario 6] a second open() while one window is ACTIVE is rejected deterministically")
    with tempfile.TemporaryDirectory() as tmp:
        service = _build_service(Path(tmp) / "obs.db")
        first = service.open(start_at="2026-03-01T00:00:00", end_at="2026-03-31T00:00:00", timezone_name="Asia/Jakarta")

        raised = False
        try:
            service.open(start_at="2026-04-01T00:00:00", end_at="2026-04-30T00:00:00", timezone_name="Asia/Jakarta")
        except ValueError:
            raised = True
        check(raised, "open() while another window is ACTIVE raises ValueError")

        current = service.get_current()
        check(current is not None, "the original window is still ACTIVE after the rejected second open()")
        check(current.window_id == first.window_id, "the original ACTIVE window is unchanged (never auto-replaced)")

        # Close the first, then a second open() succeeds -- proves the
        # rejection is deliberate serialization, not a permanent lock.
        service.close(first.window_id)
        second = service.open(start_at="2026-04-01T00:00:00", end_at="2026-04-30T00:00:00", timezone_name="Asia/Jakarta")
        check(second.window_id != first.window_id, "a second window opens once the first is explicitly closed")
        check(service.get_current().window_id == second.window_id, "get_current() now returns the second window")


def scenario_no_trading_state_modified():
    print("\n[Scenario 7] the observation-window vertical slice touches no trading state")
    # Check actual code lines (imports, instantiations, SQL) rather than
    # the whole file text, so a docstring merely *discussing* what this
    # module deliberately avoids (e.g. "holds no reference to
    # PaperTradingEngine") does not itself trip the check.
    import Repository.persistence.observation_window_repository as repo_module
    import Services.observation_window_service as service_module

    forbidden_import_terms = [
        "PaperTradingEngine",
        "OrderLifecycleService",
        "ExecutionService",
        "RiskLedgerPolicy",
        "RiskLimitsRepository",
        "OrderRepository",
        "TradeRepository",
        "PositionRepository",
    ]
    service_globals = set(vars(service_module).keys())
    repo_globals = set(vars(repo_module).keys())
    for term in forbidden_import_terms:
        check(term not in service_globals, f"observation_window_service.py does not import {term!r}")
        check(term not in repo_globals, f"observation_window_repository.py does not import {term!r}")

    repo_source = Path(_PROJECT_ROOT / "Repository" / "persistence" / "observation_window_repository.py").read_text()
    for sql_term in ["INSERT INTO orders", "INSERT INTO trades", "INSERT INTO positions", "INSERT INTO risk_limits"]:
        check(sql_term not in repo_source, f"observation_window_repository.py does not execute {sql_term!r}")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "obs.db"
        service = _build_service(db_path)
        service.open(start_at="2026-02-01T00:00:00", end_at="2026-02-28T00:00:00", timezone_name="Asia/Jakarta")
        service.close()

        # The only table this migration creates/touches is
        # operator_observation_windows -- confirm no orders/trades/
        # positions/risk_limits tables were created as a side effect
        # (they simply don't exist in this scratch database, since
        # only OBSERVATION_WINDOW_MIGRATIONS was ever applied to it).
        cfg = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        result = db2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = {row["name"] for row in result.rows}
        check(
            table_names == {"schema_migrations", "operator_observation_windows"},
            f"only schema_migrations/operator_observation_windows tables exist, got {sorted(table_names)}",
        )


def main() -> int:
    scenario_create_open_returns_active_window()
    scenario_retrieve_after_restart()
    scenario_close_preserves_original_fields()
    scenario_invalid_date_range_rejected()
    scenario_timezone_preserved()
    scenario_duplicate_active_window_rejected()
    scenario_no_trading_state_modified()

    print("\n" + "=" * 60)
    print(f"OBSERVATION WINDOW TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
