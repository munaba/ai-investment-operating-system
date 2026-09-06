from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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


def scenario_connect_disconnect_health_check():
    print("\n[Scenario 1] connect/disconnect/health_check basic lifecycle")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "test1.db")
        db = SQLiteDatabase(cfg)
        check(not db.is_connected, "not connected before connect()")
        db.connect()
        check(db.is_connected, "connected after connect()")
        check(db.health_check() is True, "health_check() True while connected")
        db.disconnect()
        check(not db.is_connected, "not connected after disconnect()")
        # health_check should reconnect lazily and still succeed
        check(db.health_check() is True, "health_check() reconnects lazily")


def scenario_execute_and_query_result_shape():
    print("\n[Scenario 2] execute() normalizes to QueryResult")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "test2.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        db.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, name TEXT)")
        result = db.execute("INSERT INTO t (name) VALUES (?)", ("alice",))
        check(result.lastrowid == 1, "lastrowid reported for INSERT")
        select_result = db.execute("SELECT id, name FROM t")
        check(len(select_result.rows) == 1, "SELECT returns 1 row")
        check(select_result.rows[0]["name"] == "alice", "row dict has expected value")
        check(isinstance(select_result.rows[0], dict), "row is a plain dict")


def scenario_transaction_commit():
    print("\n[Scenario 3] transaction commits on clean exit")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "test3.db")
        db = SQLiteDatabase(cfg)
        manager = DatabaseManager(db, cfg)
        manager.connect()
        manager.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, name TEXT)")
        with manager.session() as session:
            session.execute("INSERT INTO t (name) VALUES (?)", ("bob",))
            session.execute("INSERT INTO t (name) VALUES (?)", ("carol",))
        rows = manager.execute("SELECT name FROM t ORDER BY id").rows
        check([r["name"] for r in rows] == ["bob", "carol"], "both inserts committed")


def scenario_transaction_rollback_on_exception():
    print("\n[Scenario 4] transaction rolls back on exception")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "test4.db")
        db = SQLiteDatabase(cfg)
        manager = DatabaseManager(db, cfg)
        manager.connect()
        manager.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, name TEXT)")
        try:
            with manager.session() as session:
                session.execute("INSERT INTO t (name) VALUES (?)", ("dave",))
                raise RuntimeError("simulated failure mid-transaction")
        except RuntimeError:
            pass
        rows = manager.execute("SELECT name FROM t").rows
        check(len(rows) == 0, "insert was rolled back after exception")


def scenario_migration_runner():
    print("\n[Scenario 5] MigrationRunner applies pending migrations exactly once")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "test5.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        runner = MigrationRunner(db)

        migrations = [
            Migration(
                version=1,
                name="create_watchlist_table",
                up_statements=[
                    "CREATE TABLE IF NOT EXISTS watchlist (id INTEGER PRIMARY KEY, ticker TEXT NOT NULL)"
                ],
            ),
            Migration(
                version=2,
                name="create_watchlist_index",
                up_statements=[
                    "CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker)"
                ],
            ),
        ]

        applied = runner.apply(migrations)
        check(len(applied) == 2, "both migrations applied on first run")
        check(applied[0].version == 1 and applied[1].version == 2, "applied in version order")

        # Applying again should be a no-op (idempotent).
        applied_again = runner.apply(migrations)
        check(applied_again == [], "re-applying is a no-op")

        check(sorted(runner.applied_versions()) == [1, 2], "schema_migrations records both versions")

        # Confirm the table from migration 1 actually exists and is usable.
        db.execute("INSERT INTO watchlist (ticker) VALUES (?)", ("BBCA.JK",))
        rows = db.execute("SELECT ticker FROM watchlist").rows
        check(rows == [{"ticker": "BBCA.JK"}], "migrated table is queryable")


def scenario_thread_local_connections():
    print("\n[Scenario 6] each thread gets its own connection")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "test6.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        main_conn_id = id(db._local.connection)

        other_thread_conn_id = []

        def worker():
            db.connect()
            other_thread_conn_id.append(id(db._local.connection))
            db.disconnect()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        check(len(other_thread_conn_id) == 1, "worker thread connected successfully")
        check(other_thread_conn_id[0] != main_conn_id, "worker thread got a distinct connection object")
        check(db.is_connected, "main thread connection unaffected by worker's disconnect()")


def scenario_optional_backward_compatible_config():
    print("\n[Scenario 7] DatabaseConfig.from_env() works with no env vars set")
    cfg = DatabaseConfig.from_env()
    check(isinstance(cfg, DatabaseConfig), "from_env() returns a DatabaseConfig")
    check(cfg.journal_mode == "WAL", "default journal_mode applied")
    check(cfg.foreign_keys is True, "default foreign_keys applied")


def main() -> int:
    scenario_connect_disconnect_health_check()
    scenario_execute_and_query_result_shape()
    scenario_transaction_commit()
    scenario_transaction_rollback_on_exception()
    scenario_migration_runner()
    scenario_thread_local_connections()
    scenario_optional_backward_compatible_config()

    print("\n" + "=" * 60)
    print(f"DATABASE LAYER SMOKE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())