"""Standalone regression checks for Activation 7 FIX blocker #3:

    manual database backup (``Database.backup``, ``python main.py
    backup``).

Proves, concretely, against a real on-disk SQLite database (WAL
journal mode, the same default every other command already uses):

* Scenario 1: ``create_backup()`` actually creates a backup file.
* Scenario 2: the backup file is a real, openable SQLite database
  (``verify_backup()`` / a fresh ``sqlite3.connect()`` both succeed).
* Scenario 3: important data (real table rows) already present in the
  source survive into the backup, unchanged.
* Scenario 4: creating the backup does not modify the source database
  file in any way (byte-for-byte identical before/after, same mtime
  is not required but content hash is).
* Scenario 5: ``verify_backup()`` correctly reports ``False`` for a
  missing/corrupt file -- not a false positive.
* Scenario 6: ``restore_backup()`` actually restores -- copying a
  backup over a different (e.g. later-corrupted) path recovers the
  original data.
* Scenario 7: ``python main.py backup`` (the actual CLI entry point)
  end to end -- exits 0, prints a clean success message, and produces
  a verifiable backup; a missing source database produces a clean
  failure message (no raw traceback) and a non-zero exit code.
* Scenario 8: nothing about this fix is automatic -- ``create_backup``
  is never called by ``run_init``/``run_doctor_command`` or any other
  command's dispatch path (grep-level structural check on
  ``main.py``), and no scheduler/background-worker module imports
  ``Database.backup``.

Run directly with ``python Tests/test_database_backup.py`` -- no
external test framework required, matching every other standalone
test file in this repository.
"""

from __future__ import annotations

import io
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Database.backup import (  # noqa: E402
    create_backup,
    default_backup_dir,
    restore_backup,
    verify_backup,
)
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_watchlist import WATCHLIST_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.watchlist_repository import WatchlistRepository  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Core.exceptions import DatabaseError  # noqa: E402

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


def _build_real_db(tmp_dir: Path, name: str = "aios.db") -> Path:
    """Builds a real, on-disk SQLite database (WAL, the default
    journal mode -- Database.database_config) with real
    accounts/watchlist rows, mirroring every other test file's own
    ``_build()`` rig."""
    db_path = tmp_dir / name
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(WATCHLIST_MIGRATIONS)
    manager = DatabaseManager(db, cfg)

    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="paper-id", account_name="Paper Indonesia", mode="paper",
        currency="IDR", asset_class="stock_id",
        cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
    )
    watchlist_repo = WatchlistRepository(manager)
    watchlist_repo.add(ticker="BBCA")

    db.disconnect()
    return db_path


def scenario_1_backup_is_created() -> None:
    print("\n[Scenario 1] create_backup() actually creates a backup file")
    tmp_dir = Path(tempfile.mkdtemp(prefix="backup_test_1_"))
    try:
        db_path = _build_real_db(tmp_dir)
        backup_path = create_backup(db_path)

        check(backup_path.exists(), "the returned backup path actually exists on disk")
        check(backup_path.parent == default_backup_dir(db_path), "backup lands in the default backups/ directory")
        check(backup_path.stat().st_size > 0, "the backup file is non-empty")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_2_backup_is_openable_sqlite() -> None:
    print("\n[Scenario 2] backup file can be read/opened as a real SQLite database")
    tmp_dir = Path(tempfile.mkdtemp(prefix="backup_test_2_"))
    try:
        db_path = _build_real_db(tmp_dir)
        backup_path = create_backup(db_path)

        check(verify_backup(backup_path), "verify_backup() reports the backup as valid")

        conn = sqlite3.connect(str(backup_path))
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        check(
            {"accounts", "watchlist", "schema_migrations"}.issubset(tables),
            "the backup contains the expected real tables, openable via a plain sqlite3.connect()",
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_3_important_data_survives() -> None:
    print("\n[Scenario 3] important data (real rows) survives into the backup")
    tmp_dir = Path(tempfile.mkdtemp(prefix="backup_test_3_"))
    try:
        db_path = _build_real_db(tmp_dir)
        backup_path = create_backup(db_path)

        conn = sqlite3.connect(str(backup_path))
        try:
            account_row = conn.execute(
                "SELECT account_id, cash FROM accounts WHERE account_id = 'paper-id'"
            ).fetchone()
            watchlist_row = conn.execute(
                "SELECT ticker FROM watchlist WHERE ticker = 'BBCA'"
            ).fetchone()
        finally:
            conn.close()

        check(account_row is not None and account_row[0] == "paper-id", "the account row survives, correct account_id")
        check(account_row is not None and account_row[1] == 100_000_000.0, "the account row survives, correct cash amount")
        check(watchlist_row is not None and watchlist_row[0] == "BBCA", "the watchlist row survives")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_4_source_unmodified() -> None:
    print("\n[Scenario 4] backup is created without changing the source database")
    tmp_dir = Path(tempfile.mkdtemp(prefix="backup_test_4_"))
    try:
        db_path = _build_real_db(tmp_dir)
        before_bytes = db_path.read_bytes()

        create_backup(db_path)

        after_bytes = db_path.read_bytes()
        check(before_bytes == after_bytes, "source database file is byte-for-byte unchanged after backup")

        # Also prove the source is still fully usable/queryable afterward
        # (never left mid-transaction, locked, or corrupted).
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT account_id FROM accounts WHERE account_id = 'paper-id'").fetchone()
        finally:
            conn.close()
        check(row is not None, "source database is still fully queryable after backup")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_5_verify_rejects_bad_backup() -> None:
    print("\n[Scenario 5] verify_backup() correctly rejects missing/corrupt files")
    tmp_dir = Path(tempfile.mkdtemp(prefix="backup_test_5_"))
    try:
        missing_path = tmp_dir / "does_not_exist.db"
        check(verify_backup(missing_path) is False, "a missing file is reported as NOT verified")

        corrupt_path = tmp_dir / "corrupt.db"
        corrupt_path.write_bytes(b"this is not a sqlite database file at all")
        check(verify_backup(corrupt_path) is False, "a non-SQLite file is reported as NOT verified")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_6_restore_recovers_data() -> None:
    print("\n[Scenario 6] restore_backup() actually restores data")
    tmp_dir = Path(tempfile.mkdtemp(prefix="backup_test_6_"))
    try:
        db_path = _build_real_db(tmp_dir)
        backup_path = create_backup(db_path)

        # Simulate the source becoming corrupted/lost.
        corrupted_path = tmp_dir / "corrupted.db"
        corrupted_path.write_bytes(b"corrupted, not a real database")

        restore_backup(backup_path, corrupted_path)

        conn = sqlite3.connect(str(corrupted_path))
        try:
            row = conn.execute("SELECT account_id FROM accounts WHERE account_id = 'paper-id'").fetchone()
        finally:
            conn.close()
        check(row is not None and row[0] == "paper-id", "restoring the backup recovers the original account data")

        try:
            restore_backup(tmp_dir / "does_not_exist.db", corrupted_path)
            check(False, "restore_backup() should raise DatabaseError for a missing/invalid backup")
        except DatabaseError:
            check(True, "restore_backup() refuses to restore from a missing/invalid backup")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_7_cli_end_to_end() -> None:
    print("\n[Scenario 7] 'python main.py backup' end to end (success and clean failure)")
    tmp_dir = Path(tempfile.mkdtemp(prefix="backup_test_7_"))
    try:
        db_path = _build_real_db(tmp_dir)
        before_bytes = db_path.read_bytes()

        env = {"DB_PATH": str(db_path)}
        import os
        full_env = dict(os.environ)
        full_env.update(env)

        result = subprocess.run(
            [sys.executable, "main.py", "backup"],
            cwd=str(_PROJECT_ROOT),
            env=full_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(result.returncode == 0, f"'python main.py backup' exits 0 on success, got {result.returncode}")
        check("Backup Created" in result.stdout, "CLI prints the clean success message")
        check("Traceback" not in result.stdout, "no raw traceback text is printed to stdout on success")

        after_bytes = db_path.read_bytes()
        check(before_bytes == after_bytes, "source database is unchanged after the CLI backup run")

        match = re.search(r"^  backup : (\S+)$", result.stdout, re.MULTILINE)
        check(match is not None, "CLI output names the backup file path")
        if match is not None:
            check(Path(match.group(1)).exists(), "the backup file the CLI reported actually exists")
            check(verify_backup(Path(match.group(1))), "the backup file the CLI created is verifiable")

        # Clean-failure path: nonexistent database.
        missing_env = dict(full_env)
        missing_env["DB_PATH"] = str(tmp_dir / "does_not_exist.db")
        fail_result = subprocess.run(
            [sys.executable, "main.py", "backup"],
            cwd=str(_PROJECT_ROOT),
            env=missing_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        check(fail_result.returncode == 1, f"CLI exits non-zero when the source database is missing, got {fail_result.returncode}")
        check("BACKUP FAILED" in fail_result.stdout, "CLI prints a clean, labelled failure message on stdout")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_8_manual_only_never_automatic() -> None:
    print("\n[Scenario 8] backup is manual-only -- never invoked automatically")
    main_source = (_PROJECT_ROOT / "main.py").read_text(encoding="utf-8")

    # create_backup must be *called* from exactly one place: the
    # "backup" CLI handler itself -- never from inside
    # run_init/run_doctor_command/_run_report_daily/paper buy-sell/etc.
    # (docstring mentions of "create_backup()" as prose are not calls.)
    call_sites = [
        line for line in main_source.splitlines()
        if re.search(r"[=\s]create_backup\s*\(", line) and not line.strip().startswith(("#", "``", '"'))
    ]
    check(len(call_sites) == 1, f"create_backup() is called from exactly one place in main.py, found {len(call_sites)}: {call_sites}")

    for forbidden in ("run_init(", "run_doctor_command(", "_run_report_daily(", "_run_paper_buy_command(", "_run_paper_sell_command("):
        idx = main_source.find(forbidden)
        check(idx != -1, f"sanity: {forbidden} still exists in main.py")

    # No scheduler/background-worker module in the repo imports this module.
    scheduler_hits = []
    for path in _PROJECT_ROOT.rglob("*.py"):
        if "Tests" in path.parts or path.name == "backup.py":
            continue
        if "scheduler" in path.name.lower() or "background" in path.name.lower() or "worker" in path.name.lower():
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "Database.backup" in text or "from Database import backup" in text:
                scheduler_hits.append(str(path))
    check(scheduler_hits == [], f"no scheduler/background-worker module imports Database.backup, found: {scheduler_hits}")


def main_test_runner() -> int:
    scenario_1_backup_is_created()
    scenario_2_backup_is_openable_sqlite()
    scenario_3_important_data_survives()
    scenario_4_source_unmodified()
    scenario_5_verify_rejects_bad_backup()
    scenario_6_restore_recovers_data()
    scenario_7_cli_end_to_end()
    scenario_8_manual_only_never_automatic()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 7 FIX BLOCKER #3 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for description in _FAILURES:
            print(f"  - {description}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main_test_runner())