"""Standalone regression checks for
``Repository.persistence.snapshot_repository.SnapshotRepository``.

Covers Sprint 5 STEP 3 (Ranking Snapshot persistence):

* create/list_latest/list_by_scan_time/list_all happy paths;
* ``snapshot_id`` is repository-generated (autoincrement), never
  caller-supplied;
* this repository performs no ranking/recommendation computation --
  ``create`` persists exactly the values the caller supplies;
* SnapshotRepository is append-only: no update/delete/replace/modify
  method exists at all.

Run directly with ``python Tests/test_snapshot_repository.py`` -- no
external test framework required, matching ``test_trade_repository.py``.
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
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.models import RankingSnapshot  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.snapshot_repository import SnapshotRepository  # noqa: E402

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


def _build_repository(tmp_dir: str) -> SnapshotRepository:
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "snapshots_repo.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    return SnapshotRepository(manager)


def scenario_create_returns_ranking_snapshot():
    print("\n[Scenario 1] create() happy path returns a RankingSnapshot")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        snapshot = repo.create(
            scan_time="2026-08-01T09:00:00+00:00",
            symbol="BBCA",
            recommendation="SELL",
            confidence="LOW",
            priority=1,
            rank=1,
        )
        check(isinstance(snapshot, RankingSnapshot), "create() returns a RankingSnapshot instance")
        check(snapshot.snapshot_id is not None, "created snapshot has a repository-assigned snapshot_id")
        check(snapshot.scan_time == "2026-08-01T09:00:00+00:00", "scan_time persisted exactly as supplied")
        check(snapshot.symbol == "BBCA", "symbol persisted exactly as supplied")
        check(snapshot.recommendation == "SELL", "recommendation persisted exactly as supplied")
        check(snapshot.confidence == "LOW", "confidence persisted exactly as supplied")
        check(snapshot.priority == 1, "priority persisted exactly as supplied")
        check(snapshot.rank == 1, "rank persisted exactly as supplied")


def scenario_snapshot_id_is_repository_generated():
    print("\n[Scenario 2] snapshot_id is repository-generated, never caller-supplied")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        first = repo.create(
            scan_time="2026-08-01T09:00:00+00:00",
            symbol="BBCA",
            recommendation="SELL",
            confidence="LOW",
            priority=1,
            rank=1,
        )
        second = repo.create(
            scan_time="2026-08-01T09:00:00+00:00",
            symbol="TLKM",
            recommendation="SELL",
            confidence="LOW",
            priority=2,
            rank=2,
        )
        check(first.snapshot_id != second.snapshot_id, "two creates produce two distinct snapshot_id values")
        check(second.snapshot_id > first.snapshot_id, "snapshot_id increases with each create (autoincrement)")
        check(
            "snapshot_id" not in repo.create.__code__.co_varnames[: repo.create.__code__.co_argcount],
            "create() accepts no snapshot_id parameter (repository-generated only)",
        )


def scenario_list_by_scan_time():
    print("\n[Scenario 3] list_by_scan_time() returns only that scan's rows, ordered by rank")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        scan_a = "2026-08-01T09:00:00+00:00"
        scan_b = "2026-08-01T10:00:00+00:00"
        repo.create(scan_time=scan_a, symbol="TLKM", recommendation="SELL", confidence="LOW", priority=2, rank=2)
        repo.create(scan_time=scan_a, symbol="BBCA", recommendation="SELL", confidence="LOW", priority=1, rank=1)
        repo.create(scan_time=scan_b, symbol="ASII", recommendation="BUY", confidence="HIGH", priority=1, rank=1)

        results = repo.list_by_scan_time(scan_a)
        check(len(results) == 2, "list_by_scan_time returns only rows for the requested scan_time")
        check(all(r.scan_time == scan_a for r in results), "every returned row matches the requested scan_time")
        check([r.rank for r in results] == [1, 2], "results are ordered by rank ascending")

        empty = repo.list_by_scan_time("2099-01-01T00:00:00+00:00")
        check(empty == [], "list_by_scan_time returns an empty list for an unknown scan_time")


def scenario_list_latest():
    print("\n[Scenario 4] list_latest() returns only the most recent scan_time's rows")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        scan_a = "2026-08-01T09:00:00+00:00"
        scan_b = "2026-08-01T10:00:00+00:00"
        repo.create(scan_time=scan_a, symbol="BBCA", recommendation="SELL", confidence="LOW", priority=1, rank=1)
        repo.create(scan_time=scan_b, symbol="ASII", recommendation="BUY", confidence="HIGH", priority=1, rank=1)
        repo.create(scan_time=scan_b, symbol="TLKM", recommendation="BUY", confidence="HIGH", priority=2, rank=2)

        results = repo.list_latest()
        check(len(results) == 2, "list_latest returns only the rows from the most recent scan_time")
        check(all(r.scan_time == scan_b for r in results), "every returned row is from the latest scan_time")
        check([r.symbol for r in results] == ["ASII", "TLKM"], "results are ordered by rank ascending")


def scenario_list_latest_empty_table():
    print("\n[Scenario 5] list_latest() on an empty table returns an empty list, not an error")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        results = repo.list_latest()
        check(results == [], "list_latest() on an empty table returns an empty list")


def scenario_list_all():
    print("\n[Scenario 6] list_all() returns every row, ordered by snapshot_id ascending")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        first = repo.create(
            scan_time="2026-08-01T09:00:00+00:00", symbol="BBCA",
            recommendation="SELL", confidence="LOW", priority=1, rank=1,
        )
        second = repo.create(
            scan_time="2026-08-01T10:00:00+00:00", symbol="ASII",
            recommendation="BUY", confidence="HIGH", priority=1, rank=1,
        )
        results = repo.list_all()
        check(len(results) == 2, "list_all returns every persisted row")
        check(
            [r.snapshot_id for r in results] == [first.snapshot_id, second.snapshot_id],
            "list_all results are ordered by snapshot_id ascending",
        )


def scenario_get_by_id():
    print("\n[Scenario 6b] get_by_id() -- Activation 5.6 addition")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create(
            scan_time="2026-08-01T09:00:00+00:00", symbol="BBCA",
            recommendation="BUY", confidence="HIGH", priority=1, rank=1,
        )
        found = repo.get_by_id(created.snapshot_id)
        check(found is not None, "get_by_id() finds a real, just-created row")
        check(found == created, "get_by_id() returns the exact same row create() returned")
        missing = repo.get_by_id(999999)
        check(missing is None, "get_by_id() returns None for a snapshot_id that does not exist")


def scenario_no_mutation_methods_exist():
    print("\n[Scenario 7] SnapshotRepository is append-only -- no update/delete method exists")
    repo_methods = {name for name in dir(SnapshotRepository) if not name.startswith("_")}
    check("update" not in repo_methods, "SnapshotRepository has no update() method")
    check("delete" not in repo_methods, "SnapshotRepository has no delete() method")
    check("replace" not in repo_methods, "SnapshotRepository has no replace() method")
    check("modify" not in repo_methods, "SnapshotRepository has no modify() method")
    expected_public_methods = {
        "create",
        "list_latest",
        "list_by_scan_time",
        "list_all",
        "list_errors_by_scan_time",  # Activation 2.7
        "get_by_id",  # Activation 5.6
        "health_check",
    }
    check(
        repo_methods == expected_public_methods,
        f"SnapshotRepository's public API is exactly {sorted(expected_public_methods)}",
    )


def main() -> int:
    scenario_create_returns_ranking_snapshot()
    scenario_snapshot_id_is_repository_generated()
    scenario_list_by_scan_time()
    scenario_list_latest()
    scenario_list_latest_empty_table()
    scenario_list_all()
    scenario_get_by_id()
    scenario_no_mutation_methods_exist()

    print("\n" + "=" * 60)
    print(f"SNAPSHOT REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())