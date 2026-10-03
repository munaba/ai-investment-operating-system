"""Standalone regression checks for
``Repository.persistence.decision_brief_repository.DecisionBriefRepository``.

Covers Phase B ("Decision Copilot") persistence:

* create/get_by_id/get_latest_for_symbol/list_by_symbol/list_all happy
  paths;
* ``brief_id`` is repository-generated (autoincrement), never
  caller-supplied;
* this repository performs no status/plan computation -- ``create``
  persists exactly the values the caller supplies;
* DecisionBriefRepository is append-only: no update/delete/replace/
  modify method exists;
* a persisted brief survives a fresh repository instance over the
  same on-disk database file (restart survival).

Run directly with ``python Tests/test_decision_brief_repository.py``
-- no external test framework required, matching
``test_snapshot_repository.py``.
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
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.models import DecisionBrief  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
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


def _build_repository(db_path: Path) -> DecisionBriefRepository:
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(DECISION_BRIEFS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    return DecisionBriefRepository(manager)


def _build_repository_with_snapshot(db_path: Path) -> tuple[DecisionBriefRepository, int]:
    """Same as ``_build_repository``, plus one real ``RankingSnapshot``
    row so tests can supply a valid ``source_snapshot_id`` (this
    table's FK is enforced -- ``PRAGMA foreign_keys = ON``).
    """
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(DECISION_BRIEFS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    snapshot_repo = SnapshotRepository(manager)
    snapshot = snapshot_repo.create(
        scan_time="2026-08-22T08:00:00+00:00",
        symbol="BBCA",
        recommendation="BUY",
        confidence="HIGH",
        priority=1,
        rank=1,
    )
    return DecisionBriefRepository(manager), snapshot.snapshot_id


def scenario_create_success_returns_decision_brief():
    print("\n[Scenario 1] create() SUCCESS happy path returns a DecisionBrief")
    with tempfile.TemporaryDirectory() as tmp:
        repo, snapshot_id = _build_repository_with_snapshot(Path(tmp) / "briefs.db")
        brief = repo.create(
            symbol="BBCA",
            generated_at="2026-08-22T09:00:00+00:00",
            status="SUCCESS",
            source_snapshot_id=snapshot_id,
            reason=None,
            entry_price=9000.0,
            stop_loss_price=8820.0,
            take_profit_price=9360.0,
            risk_amount=100000.0,
            position_size=555.5,
            risk_reward_ratio=2.0,
        )
        check(isinstance(brief, DecisionBrief), "create() returns a DecisionBrief instance")
        check(brief.brief_id is not None, "created brief has a repository-assigned brief_id")
        check(brief.symbol == "BBCA", "symbol persisted exactly as supplied")
        check(brief.status == "SUCCESS", "status persisted exactly as supplied")
        check(brief.entry_price == 9000.0, "entry_price persisted exactly as supplied")
        check(brief.stop_loss_price == 8820.0, "stop_loss_price persisted exactly as supplied")
        check(brief.risk_reward_ratio == 2.0, "risk_reward_ratio persisted exactly as supplied")


def scenario_create_non_success_has_no_plan():
    print("\n[Scenario 2] create() non-SUCCESS status round-trips with no plan fields")
    with tempfile.TemporaryDirectory() as tmp:
        repo, snapshot_id = _build_repository_with_snapshot(Path(tmp) / "briefs.db")
        brief = repo.create(
            symbol="TLKM",
            generated_at="2026-08-22T09:00:00+00:00",
            status="DATA_STALE",
            source_snapshot_id=snapshot_id,
            reason="Snapshot is 8 hours old.",
        )
        check(brief.status == "DATA_STALE", "status persisted exactly as supplied")
        check(brief.reason == "Snapshot is 8 hours old.", "reason persisted exactly as supplied")
        check(brief.entry_price is None, "entry_price is None for a non-SUCCESS brief")
        check(brief.stop_loss_price is None, "stop_loss_price is None for a non-SUCCESS brief")
        check(brief.take_profit_price is None, "take_profit_price is None for a non-SUCCESS brief")
        check(brief.position_size is None, "position_size is None for a non-SUCCESS brief")
        check(brief.risk_reward_ratio is None, "risk_reward_ratio is None for a non-SUCCESS brief")


def scenario_brief_id_is_repository_generated():
    print("\n[Scenario 3] brief_id is repository-generated, never caller-supplied")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(Path(tmp) / "briefs.db")
        first = repo.create(symbol="BBCA", generated_at="2026-08-22T09:00:00+00:00", status="NO_TRADE", reason="x")
        second = repo.create(symbol="TLKM", generated_at="2026-08-22T09:05:00+00:00", status="NO_TRADE", reason="x")
        check(first.brief_id != second.brief_id, "two creates produce two distinct brief_id values")
        check(second.brief_id > first.brief_id, "brief_id increases with each create (autoincrement)")
        check(
            "brief_id" not in repo.create.__code__.co_varnames[: repo.create.__code__.co_argcount],
            "create() accepts no brief_id parameter (repository-generated only)",
        )


def scenario_get_latest_for_symbol():
    print("\n[Scenario 4] get_latest_for_symbol() returns the most recently generated brief")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(Path(tmp) / "briefs.db")
        repo.create(symbol="BBCA", generated_at="2026-08-22T09:00:00+00:00", status="NO_TRADE", reason="x")
        newest = repo.create(symbol="BBCA", generated_at="2026-08-22T10:00:00+00:00", status="NO_TRADE", reason="y")
        repo.create(symbol="TLKM", generated_at="2026-08-22T11:00:00+00:00", status="NO_TRADE", reason="z")

        latest = repo.get_latest_for_symbol("BBCA")
        check(latest is not None, "get_latest_for_symbol() finds a brief for an existing symbol")
        check(latest.brief_id == newest.brief_id, "get_latest_for_symbol() returns the most recently generated row")
        check(repo.get_latest_for_symbol("UNKNOWN") is None, "get_latest_for_symbol() returns None for an unknown symbol")


def scenario_list_by_symbol_and_list_all():
    print("\n[Scenario 5] list_by_symbol() / list_all() ordering")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(Path(tmp) / "briefs.db")
        b1 = repo.create(symbol="BBCA", generated_at="2026-08-22T09:00:00+00:00", status="NO_TRADE", reason="x")
        b2 = repo.create(symbol="TLKM", generated_at="2026-08-22T09:05:00+00:00", status="NO_TRADE", reason="x")
        b3 = repo.create(symbol="BBCA", generated_at="2026-08-22T10:00:00+00:00", status="NO_TRADE", reason="y")

        bbca_only = repo.list_by_symbol("BBCA")
        check(len(bbca_only) == 2, "list_by_symbol() returns only that symbol's rows")
        check([b.brief_id for b in bbca_only] == [b1.brief_id, b3.brief_id], "list_by_symbol() ordered by brief_id ascending")

        every_brief = repo.list_all()
        check(len(every_brief) == 3, "list_all() returns every brief across symbols")
        check(
            [b.brief_id for b in every_brief] == [b1.brief_id, b2.brief_id, b3.brief_id],
            "list_all() ordered by brief_id ascending",
        )


def scenario_get_by_id():
    print("\n[Scenario 6] get_by_id() returns the exact row or None")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(Path(tmp) / "briefs.db")
        created = repo.create(symbol="BBCA", generated_at="2026-08-22T09:00:00+00:00", status="NO_TRADE", reason="x")
        fetched = repo.get_by_id(created.brief_id)
        check(fetched is not None, "get_by_id() finds an existing brief")
        check(fetched.symbol == "BBCA", "get_by_id() returns the correct row")
        check(repo.get_by_id(999999) is None, "get_by_id() returns None for a nonexistent id")


def scenario_brief_survives_restart():
    print("\n[Scenario 7] a persisted brief survives a fresh repository instance (restart survival)")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "briefs.db"
        repo, snapshot_id = _build_repository_with_snapshot(db_path)
        created = repo.create(
            symbol="BBCA",
            generated_at="2026-08-22T09:00:00+00:00",
            status="SUCCESS",
            source_snapshot_id=snapshot_id,
            entry_price=9000.0,
            stop_loss_price=8820.0,
            take_profit_price=9360.0,
            risk_amount=100000.0,
            position_size=555.5,
            risk_reward_ratio=2.0,
        )

        # Fresh connection/repository over the SAME on-disk file --
        # simulates a process restart, never reusing the original
        # in-memory objects.
        cfg = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg)
        repo2 = DecisionBriefRepository(manager2)

        reloaded = repo2.get_by_id(created.brief_id)
        check(reloaded is not None, "brief is still present after reconnecting to the same database file")
        check(reloaded.symbol == "BBCA", "symbol survives restart")
        check(reloaded.status == "SUCCESS", "status survives restart")
        check(reloaded.entry_price == 9000.0, "entry_price survives restart")
        check(reloaded.risk_reward_ratio == 2.0, "risk_reward_ratio survives restart")


def scenario_no_mutation_methods_exist():
    print("\n[Scenario 8] DecisionBriefRepository is append-only")
    repo_methods = {
        name
        for name in dir(DecisionBriefRepository)
        if not name.startswith("_") and callable(getattr(DecisionBriefRepository, name))
    }
    check("update" not in repo_methods, "DecisionBriefRepository has no update() method")
    check("delete" not in repo_methods, "DecisionBriefRepository has no delete() method")
    check("replace" not in repo_methods, "DecisionBriefRepository has no replace() method")
    check("modify" not in repo_methods, "DecisionBriefRepository has no modify() method")
    expected_public_methods = {
        "create",
        "get_by_id",
        "get_latest_for_symbol",
        "list_by_symbol",
        "list_all",
        "health_check",
    }
    check(
        repo_methods == expected_public_methods,
        f"DecisionBriefRepository's public API is exactly {sorted(expected_public_methods)}",
    )


def main() -> int:
    scenario_create_success_returns_decision_brief()
    scenario_create_non_success_has_no_plan()
    scenario_brief_id_is_repository_generated()
    scenario_get_latest_for_symbol()
    scenario_list_by_symbol_and_list_all()
    scenario_get_by_id()
    scenario_brief_survives_restart()
    scenario_no_mutation_methods_exist()

    print("\n" + "=" * 60)
    print(f"DECISION BRIEF REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())