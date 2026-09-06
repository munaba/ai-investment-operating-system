"""Regression tests for the 6 blockers raised in the Database Layer audit.

Run standalone (matches the style of test_databse_layer_smoke.py, no
pytest dependency) or under pytest -- every function starting with
scenario_/test_ is a self-contained check.

Covers:
    1. Connection lifecycle (leak reclamation, close_all())
    2. Nested transactions via SAVEPOINT
    3. Migration locking (single-process contention + real multi-process race)
    4. Error contract (DatabaseError shape/consistency)
    5. The ':memory:' multi-thread trap
    6. Backend abstraction documentation (smoke-checked, not just prose)
"""
from __future__ import annotations

import gc
import multiprocessing
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.exceptions import DatabaseError
from Database import (
    DatabaseConfig,
    DatabaseManager,
    Migration,
    MigrationRunner,
    SQLiteDatabase,
)

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# Blocker 1: connection lifecycle
# ---------------------------------------------------------------------------

def scenario_close_all_shuts_down_every_tracked_connection():
    print("\n[Blocker 1] close_all() closes connections across threads")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t1.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        check(db.active_connection_count == 1, "1 connection tracked after main-thread connect()")

        connected_in_worker = threading.Event()
        keep_worker_alive = threading.Event()

        def worker():
            db.connect()
            connected_in_worker.set()
            keep_worker_alive.wait(timeout=5)

        t = threading.Thread(target=worker)
        t.start()
        connected_in_worker.wait(timeout=5)
        check(db.active_connection_count == 2, "2 connections tracked (main + worker)")

        keep_worker_alive.set()
        t.join()

        db.close_all()
        check(db.active_connection_count == 0, "close_all() clears the registry")
        check(not db.is_connected, "calling thread's connection closed by close_all()")

        # Lazily reconnecting afterwards must still work (close_all() isn't terminal).
        check(db.health_check() is True, "database still usable after close_all() via lazy reconnect")
        db.disconnect()  # close the lazily-reopened connection before TemporaryDirectory cleans up


def scenario_leaked_connection_is_reclaimed_on_thread_gc():
    print("\n[Blocker 1] a thread that never calls disconnect() doesn't leak forever")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t2.db")
        db = SQLiteDatabase(cfg)
        db.connect()

        def worker_that_forgets_to_disconnect():
            db.connect()  # never calls db.disconnect()

        t = threading.Thread(target=worker_that_forgets_to_disconnect)
        t.start()
        t.join()
        check(db.active_connection_count == 2, "leaked worker connection still tracked right after join()")

        # The Thread object is the only thing keeping the finalizer armed;
        # once nothing references it, gc.collect() should trigger cleanup.
        del t
        gc.collect()
        # Give the finalizer a moment; weakref.finalize runs synchronously
        # during collection in CPython, but keep this robust either way.
        deadline = time.time() + 2
        while db.active_connection_count > 1 and time.time() < deadline:
            gc.collect()
            time.sleep(0.05)
        check(db.active_connection_count == 1, "leaked connection reclaimed after thread object is collected")

        db.close_all()


# ---------------------------------------------------------------------------
# Blocker 2: nested transactions
# ---------------------------------------------------------------------------

def scenario_nested_transactions_commit():
    print("\n[Blocker 2] nested begin()/commit() via SAVEPOINT, both commit")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t3.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        db.execute("CREATE TABLE t (name TEXT)")

        db.begin()
        db.execute("INSERT INTO t VALUES ('outer')")
        db.begin()  # nested -> savepoint, must NOT raise
        db.execute("INSERT INTO t VALUES ('inner')")
        db.commit()  # releases the savepoint only
        rows_before_outer_commit = db.execute("SELECT name FROM t").rows
        db.commit()  # commits the outer transaction

        rows = db.execute("SELECT name FROM t ORDER BY name").rows
        check([r["name"] for r in rows] == ["inner", "outer"], "both nested inserts persisted after outer commit")
        check(
            len(rows_before_outer_commit) == 2,
            "inner insert visible on this connection before outer commit (same-connection read-your-writes)",
        )
        db.disconnect()  # close before TemporaryDirectory cleans up (Windows file-lock)


def scenario_nested_savepoint_rollback_does_not_undo_outer_work():
    print("\n[Blocker 2] rolling back an inner savepoint leaves the outer transaction intact")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t4.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        db.execute("CREATE TABLE t (name TEXT)")

        db.begin()
        db.execute("INSERT INTO t VALUES ('keep_me')")
        db.begin()  # nested
        db.execute("INSERT INTO t VALUES ('discard_me')")
        db.rollback()  # rolls back only the inner savepoint
        db.commit()  # commits the outer transaction

        rows = db.execute("SELECT name FROM t").rows
        check([r["name"] for r in rows] == ["keep_me"], "outer work survives an inner rollback")
        db.disconnect()  # close before TemporaryDirectory cleans up (Windows file-lock)


def scenario_composable_repository_pattern_via_manager_session():
    print("\n[Blocker 2] DatabaseManager.session() composes: nested call doesn't raise")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t5.db")
        db = SQLiteDatabase(cfg)
        manager = DatabaseManager(db, cfg)
        manager.connect()
        manager.execute("CREATE TABLE t (name TEXT)")

        def repository_method_a(name: str) -> None:
            with manager.session() as session:
                session.execute("INSERT INTO t VALUES (?)", (name,))
                repository_method_b(name + "_via_b")

        def repository_method_b(name: str) -> None:
            # Composability requirement from the audit: a repository method
            # can open its own session() even when called from inside
            # another repository method's session(), without raising.
            with manager.session() as session:
                session.execute("INSERT INTO t VALUES (?)", (name,))

        repository_method_a("alice")
        rows = manager.execute("SELECT name FROM t ORDER BY name").rows
        check(
            [r["name"] for r in rows] == ["alice", "alice_via_b"],
            "nested repository-style session() calls compose without raising",
        )
        manager.disconnect()  # close before TemporaryDirectory cleans up (Windows file-lock)


# ---------------------------------------------------------------------------
# Blocker 3: migration locking
# ---------------------------------------------------------------------------

def scenario_migration_lock_is_exclusive_within_one_process():
    print("\n[Blocker 3] a second concurrent apply() in the same process waits, then sees nothing pending")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "t6.db"
        cfg = DatabaseConfig(db_path=db_path, timeout=5.0)
        db_a = SQLiteDatabase(cfg)
        db_b = SQLiteDatabase(DatabaseConfig(db_path=db_path, timeout=5.0))
        db_a.connect()
        db_b.connect()

        migrations = [
            Migration(version=1, name="m1", up_statements=["CREATE TABLE IF NOT EXISTS a (id INTEGER)"]),
            Migration(version=2, name="m2", up_statements=["CREATE TABLE IF NOT EXISTS b (id INTEGER)"]),
        ]

        results = {}

        def run_a():
            runner = MigrationRunner(db_a)
            results["a"] = runner.apply(migrations)

        def run_b():
            runner = MigrationRunner(db_b)
            results["b"] = runner.apply(migrations)

        t_a = threading.Thread(target=run_a)
        t_b = threading.Thread(target=run_b)
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        total_applied = len(results.get("a", [])) + len(results.get("b", []))
        check(total_applied == 2, f"exactly 2 migrations applied in total across both runners (got {total_applied})")

        runner_check = MigrationRunner(db_a)
        check(sorted(runner_check.applied_versions()) == [1, 2], "schema_migrations has exactly versions 1 and 2 (no duplicates)")

        db_a.close_all()
        db_b.close_all()


def _mp_worker_apply_migrations(db_path: str, ready_barrier, result_queue) -> None:
    """Top-level function (required for multiprocessing spawn/pickling) that
    a separate OS process runs to race against another process applying the
    same migrations to the same file."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from Database import DatabaseConfig, Migration, MigrationRunner, SQLiteDatabase  # noqa: E402

    db = SQLiteDatabase(DatabaseConfig(db_path=Path(db_path), timeout=10.0))
    db.connect()
    migrations = [
        Migration(version=1, name="m1", up_statements=["CREATE TABLE IF NOT EXISTS a (id INTEGER)"]),
        Migration(version=2, name="m2", up_statements=["CREATE TABLE IF NOT EXISTS b (id INTEGER)"]),
    ]
    ready_barrier.wait()  # line both processes up to hit apply() at nearly the same instant
    runner = MigrationRunner(db)
    applied = runner.apply(migrations)
    result_queue.put(len(applied))
    db.close_all()


def scenario_migration_lock_across_real_processes():
    print("\n[Blocker 3] two REAL OS processes racing to migrate the same file don't double-apply")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "t7.db")
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(2)
        result_queue = ctx.Queue()

        p1 = ctx.Process(target=_mp_worker_apply_migrations, args=(db_path, barrier, result_queue))
        p2 = ctx.Process(target=_mp_worker_apply_migrations, args=(db_path, barrier, result_queue))
        p1.start()
        p2.start()
        p1.join(timeout=20)
        p2.join(timeout=20)

        check(p1.exitcode == 0, f"process 1 exited cleanly (exitcode={p1.exitcode})")
        check(p2.exitcode == 0, f"process 2 exited cleanly (exitcode={p2.exitcode})")

        counts = []
        while not result_queue.empty():
            counts.append(result_queue.get())
        check(sum(counts) == 2, f"exactly 2 migrations applied in total across both OS processes (got {counts})")

        verify_db = SQLiteDatabase(DatabaseConfig(db_path=Path(db_path)))
        verify_db.connect()
        runner = MigrationRunner(verify_db)
        check(sorted(runner.applied_versions()) == [1, 2], "final schema_migrations has exactly versions 1 and 2")
        tables = verify_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('a','b')"
        ).rows
        check(len(tables) == 2, "both migrated tables actually exist exactly once")
        verify_db.close_all()


def scenario_migration_batch_is_atomic_on_failure():
    print("\n[Blocker 3] a failing migration rolls back the WHOLE batch, not just itself")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t8.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        migrations = [
            Migration(version=1, name="good", up_statements=["CREATE TABLE ok (id INTEGER)"]),
            Migration(version=2, name="bad", up_statements=["THIS IS NOT VALID SQL"]),
        ]
        runner = MigrationRunner(db)
        raised = False
        try:
            runner.apply(migrations)
        except DatabaseError:
            raised = True
        check(raised, "apply() raises DatabaseError when a migration in the batch fails")
        check(runner.applied_versions() == [], "no migration recorded as applied -- batch rolled back entirely")
        table_exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ok'"
        ).rows
        check(table_exists == [], "the earlier-in-batch migration's table was rolled back too")
        db.disconnect()  # close before TemporaryDirectory cleans up (Windows file-lock)


# ---------------------------------------------------------------------------
# Blocker 4: error contract
# ---------------------------------------------------------------------------

def scenario_database_errors_carry_consistent_shape():
    print("\n[Blocker 4] every failure surfaces as DatabaseError with message + details")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "t9.db")
        db = SQLiteDatabase(cfg)
        db.connect()

        raised = None
        try:
            db.execute("SELECT * FROM this_table_does_not_exist")
        except DatabaseError as exc:
            raised = exc
        check(raised is not None, "invalid SQL raises DatabaseError (not a raw sqlite3.Error)")
        check(hasattr(raised, "message") and isinstance(raised.message, str), "DatabaseError.message is a string")
        check(hasattr(raised, "details") and isinstance(raised.details, dict), "DatabaseError.details is a dict")

        raised_commit = None
        try:
            db.commit()  # nothing active
        except DatabaseError as exc:
            raised_commit = exc
        check(raised_commit is not None, "commit() with no active transaction raises DatabaseError")

        # rollback() must NEVER raise, per the documented contract (so
        # cleanup code can call it unconditionally in a finally block).
        no_exception = True
        try:
            db.rollback()
            db.rollback()
        except Exception:
            no_exception = False
        check(no_exception, "rollback() never raises, even with nothing active (repeated calls)")
        db.disconnect()  # close before TemporaryDirectory cleans up (Windows file-lock)


# ---------------------------------------------------------------------------
# Blocker 5: the ':memory:' trap
# ---------------------------------------------------------------------------

def scenario_bare_memory_path_is_rejected():
    print("\n[Blocker 5] bare ':memory:' is rejected up front")
    raised = None
    try:
        SQLiteDatabase(DatabaseConfig(db_path=Path(":memory:")))
    except DatabaseError as exc:
        raised = exc
    check(raised is not None, "constructing SQLiteDatabase with db_path=':memory:' raises DatabaseError immediately")


def scenario_shared_cache_memory_uri_is_the_documented_escape_hatch():
    print("\n[Blocker 5] uri_mode=True + shared-cache URI is usable across threads")
    cfg = DatabaseConfig(db_path=Path("file:hardening_test_shared?mode=memory&cache=shared"), uri_mode=True)
    db = SQLiteDatabase(cfg)
    db.connect()
    db.execute("CREATE TABLE IF NOT EXISTS shared_t (name TEXT)")
    db.execute("INSERT INTO shared_t VALUES ('from_main_thread')")

    seen_from_worker = []

    def worker():
        db.connect()
        rows = db.execute("SELECT name FROM shared_t").rows
        seen_from_worker.append([r["name"] for r in rows])

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    check(
        seen_from_worker and seen_from_worker[0] == ["from_main_thread"],
        "a worker thread sees data written by the main thread via the shared-cache URI",
    )
    db.close_all()


# ---------------------------------------------------------------------------
# Blocker 6: backend abstraction is honestly documented (spot-check, not just prose)
# ---------------------------------------------------------------------------

def scenario_backend_abstraction_doc_exists_and_is_current():
    print("\n[Blocker 6] ARCHITECTURE.md exists and mentions the key non-abstracted areas")
    doc_path = Path(__file__).resolve().parents[1] / "Database" / "architecture.md"
    check(doc_path.exists(), "Database/architecture.md exists")
    if doc_path.exists():
        text = doc_path.read_text()
        for must_mention in ["SQL dialect", "pragma", ":memory:", "exclusive", "RepositoryError"]:
            check(must_mention.lower() in text.lower(), f"ARCHITECTURE.md mentions '{must_mention}'")


def main() -> int:
    scenario_close_all_shuts_down_every_tracked_connection()
    scenario_leaked_connection_is_reclaimed_on_thread_gc()
    scenario_nested_transactions_commit()
    scenario_nested_savepoint_rollback_does_not_undo_outer_work()
    scenario_composable_repository_pattern_via_manager_session()
    scenario_migration_lock_is_exclusive_within_one_process()
    scenario_migration_lock_across_real_processes()
    scenario_migration_batch_is_atomic_on_failure()
    scenario_database_errors_carry_consistent_shape()
    scenario_bare_memory_path_is_rejected()
    scenario_shared_cache_memory_uri_is_the_documented_escape_hatch()
    scenario_backend_abstraction_doc_exists_and_is_current()

    print("\n" + "=" * 60)
    print(f"DATABASE LAYER HARDENING TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())