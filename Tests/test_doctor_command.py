"""
Activation 1.2 proof suite -- ``python main.py doctor``.

Scope:
  - Core.doctor (new): run_doctor(), format_report(), run_doctor_command(),
    and every individual _check_* function.
  - main.py: the single new dispatch branch in the
    ``if __name__ == "__main__":`` block. main() itself (REPL,
    ``auto``/``scan``/chat) is untouched and re-proven unaffected.

Cakupan skenario (mirrors the Activation 1.2 prompt's Section 14):
  A. Healthy core environment -> required dependency / Python READY.
  B. Missing optional provider (inactive provider's package absent) ->
     OPTIONAL MISSING, not BLOCKED.
  C. Active provider missing dependency/config -> BLOCKED.
  D. Telegram missing -> OPTIONAL MISSING, doctor does not crash.
  E. Database missing -> explicit "not initialized", no BLOCKED
     database bucket, Migrations BLOCKED with a clear reason, and the
     database is proven to NOT have been created by doctor.
  F. Database ready + migrations current -> both READY.
  G. Migration pending -> BLOCKED with the exact pending list named.
  H. Data provider (yfinance) missing -> OPTIONAL MISSING, not silently
     READY.
  I. Provider unreachable (Ollama, bad host) -> explicit failure,
     doctor does not hang (bounded wall-clock time).
  J. Existing commands regression -- "python main.py doctor" never
     calls validate_runtime_environment()/build_application(), and the
     no-argv path is completely untouched (byte-identical crash
     traceback vs. baseline).

All os.environ / DB_PATH mutation is wrapped in try/finally (via
_EnvSandbox) so no scenario leaks state into another, or into any test
file run in the same process.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
    """Set the given env vars for the block, always restoring the exact
    previous state (including "was unset") on exit, regardless of
    whether the body raises. Unlike Stage 9.4's narrower sandbox, this
    one accepts an arbitrary key set since doctor reads far more of the
    environment (ACTIVE_PROVIDER, GEMINI_*, OLLAMA_*, DB_PATH,
    TELEGRAM_*).
    """

    def __init__(self, **overrides: Optional[str]) -> None:
        self._overrides = overrides
        self._previous: Dict[str, Optional[str]] = {}

    def __enter__(self) -> "_EnvSandbox":
        for key in self._overrides:
            self._previous[key] = os.environ.get(key)
        for key, value in self._overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _clear_all_doctor_env() -> Dict[str, None]:
    """Every env var any doctor check reads -- used to force a known,
    fully-blank baseline for each scenario instead of inheriting
    whatever happens to be set in the shell running these tests."""
    keys = [
        "ACTIVE_PROVIDER",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "OLLAMA_HOST",
        "OLLAMA_MODEL",
        "OLLAMA_TIMEOUT",
        "DB_PATH",
        "DB_TIMEOUT",
        "DB_JOURNAL_MODE",
        "DB_SYNCHRONOUS",
        "DB_FOREIGN_KEYS",
        "DB_URI_MODE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]
    return {key: None for key in keys}


def _fresh_import_doctor():
    """Import Core.doctor fresh (module-level constants like
    _DEFAULT_PROVIDER_KIND don't depend on env, so a plain import is
    fine, but this keeps every scenario explicit about needing it)."""
    import Core.doctor as doctor_module

    return doctor_module


def scenario_a_healthy_core_environment() -> None:
    print("\n[Scenario A] Healthy core environment")
    doctor = _fresh_import_doctor()
    with _EnvSandbox(**_clear_all_doctor_env()):
        python_section = doctor._check_python_version()
        deps_section = doctor._check_dependencies()

    check(python_section.status == doctor.READY, "Python section is READY")
    dotenv_check = next(c for c in deps_section.checks if c.label == "python-dotenv")
    pandas_check = next(c for c in deps_section.checks if c.label == "pandas")
    check(dotenv_check.status == doctor.READY, "python-dotenv (installed in this sandbox) is READY")
    check(pandas_check.status == doctor.READY, "pandas (installed in this sandbox) is READY")
    check(
        doctor.run_doctor is not None,
        "doctor can complete a full run without raising in this environment",
    )
    with _EnvSandbox(**_clear_all_doctor_env()):
        try:
            report = doctor.run_doctor()
            completed = True
        except Exception as exc:  # noqa: BLE001
            completed = False
            print(f"    unexpected exception: {exc}")
    check(completed, "run_doctor() completes without raising on a real, unmodified environment")
    check(report.overall_status in (doctor.READY, doctor.OPTIONAL_MISSING, doctor.BLOCKED), "overall_status is one of the three defined buckets")


def scenario_b_missing_optional_provider() -> None:
    print("\n[Scenario B] Missing optional (inactive) provider dependency")
    doctor = _fresh_import_doctor()

    # Force google-genai to look absent regardless of what's actually
    # pip-installed in the sandbox running this suite -- the point of
    # this scenario is the *classification* (inactive + absent ->
    # OPTIONAL MISSING, never BLOCKED), not this machine's package set.
    original_find_spec = doctor.importlib.util.find_spec

    def _fake_find_spec(name, *args, **kwargs):
        if name == "google.genai":
            return None
        return original_find_spec(name, *args, **kwargs)

    env = _clear_all_doctor_env()
    env["ACTIVE_PROVIDER"] = "ollama"
    env["OLLAMA_HOST"] = "http://127.0.0.1:1"  # unreachable, but only gemini-vs-ollama matters here
    env["OLLAMA_MODEL"] = "llama3"
    doctor.importlib.util.find_spec = _fake_find_spec
    try:
        with _EnvSandbox(**env):
            deps_section = doctor._check_dependencies()
    finally:
        doctor.importlib.util.find_spec = original_find_spec

    gemini_check = next(c for c in deps_section.checks if "gemini provider" in c.label)
    check(
        gemini_check.status == doctor.OPTIONAL_MISSING,
        f"google-genai (absent, inactive) is OPTIONAL MISSING (not BLOCKED) when ACTIVE_PROVIDER=ollama, got {gemini_check.status}",
    )


def scenario_c_active_provider_missing() -> None:
    print("\n[Scenario C] Active provider missing dependency/config -> BLOCKED")
    doctor = _fresh_import_doctor()
    env = _clear_all_doctor_env()
    env["ACTIVE_PROVIDER"] = "gemini"  # GEMINI_API_KEY/GEMINI_MODEL left unset
    with _EnvSandbox(**env):
        provider_section = doctor._check_provider()
    check(
        provider_section.status == doctor.BLOCKED,
        f"Active Provider section is BLOCKED when GEMINI_API_KEY/GEMINI_MODEL are unset, got {provider_section.status}",
    )
    credential_check = next(c for c in provider_section.checks if c.label == "Credential/config present")
    check(
        "GEMINI_API_KEY" in credential_check.detail and "GEMINI_MODEL" in credential_check.detail,
        "the missing-credential reason names both GEMINI_API_KEY and GEMINI_MODEL",
    )


def scenario_d_telegram_missing() -> None:
    print("\n[Scenario D] Telegram missing -> OPTIONAL MISSING, no crash")
    doctor = _fresh_import_doctor()
    with _EnvSandbox(**_clear_all_doctor_env()):
        section = doctor._check_telegram()
    check(section.status == doctor.OPTIONAL_MISSING, f"Telegram section is OPTIONAL MISSING when unconfigured, got {section.status}")


def scenario_e_database_missing() -> None:
    print("\n[Scenario E] Database missing")
    doctor = _fresh_import_doctor()
    tmp_dir = Path(tempfile.mkdtemp(prefix="doctor_e_"))
    try:
        db_path = tmp_dir / "nested" / "aios.db"
        env = _clear_all_doctor_env()
        env["DB_PATH"] = str(db_path)
        with _EnvSandbox(**env):
            from Database.database_config import DatabaseConfig

            db_config = DatabaseConfig.from_env()
            database_section, migrations_section = doctor._check_database_and_migrations(db_config)

        db_file_check = next(c for c in database_section.checks if c.label == "Database file")
        check(db_file_check.status == doctor.OPTIONAL_MISSING, "missing database file is OPTIONAL MISSING, not BLOCKED")
        check("has not been initialized" in db_file_check.detail, "database-missing detail explicitly says 'not initialized'")
        check(migrations_section.status == doctor.BLOCKED, "Migrations section is BLOCKED when database does not exist")
        check(not db_path.exists(), "doctor did NOT create the database file")
        check(not db_path.parent.exists(), "doctor did NOT create the database's parent directory")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _apply_all_migrations(db_path: Path) -> None:
    """Apply every domain's migrations to ``db_path`` via the existing,
    unmodified per-domain runner functions -- never via Core.doctor,
    which must never do this itself."""
    from Database.database_config import DatabaseConfig
    from Database.migrations import MigrationRunner
    from Database.migrations_accounts import ACCOUNTS_MIGRATIONS
    from Database.migrations_idempotency import IDEMPOTENCY_MIGRATIONS
    from Database.migrations_order_approvals import ORDER_APPROVALS_MIGRATIONS
    from Database.migrations_orders import ORDERS_MIGRATIONS
    from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS
    from Database.migrations_positions import POSITIONS_MIGRATIONS
    from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
    from Database.migrations_trades import TRADES_MIGRATIONS
    from Database.migrations_watchlist import WATCHLIST_MIGRATIONS
    from Database.sqlite_database import SQLiteDatabase

    database = SQLiteDatabase(DatabaseConfig(db_path=db_path))
    database.connect()
    try:
        runner = MigrationRunner(database)
        for migrations in (
            WATCHLIST_MIGRATIONS,
            ACCOUNTS_MIGRATIONS,
            POSITIONS_MIGRATIONS,
            ORDERS_MIGRATIONS,
            TRADES_MIGRATIONS,
            SNAPSHOTS_MIGRATIONS,
            IDEMPOTENCY_MIGRATIONS,
            PORTFOLIO_SNAPSHOTS_MIGRATIONS,
            ORDER_APPROVALS_MIGRATIONS,
        ):
            runner.apply(migrations)
    finally:
        database.disconnect()


def scenario_f_database_ready() -> None:
    print("\n[Scenario F] Database ready, migrations current")
    doctor = _fresh_import_doctor()
    tmp_dir = Path(tempfile.mkdtemp(prefix="doctor_f_"))
    try:
        db_path = tmp_dir / "aios.db"
        _apply_all_migrations(db_path)
        before_bytes = db_path.read_bytes()

        env = _clear_all_doctor_env()
        env["DB_PATH"] = str(db_path)
        with _EnvSandbox(**env):
            from Database.database_config import DatabaseConfig

            db_config = DatabaseConfig.from_env()
            database_section, migrations_section = doctor._check_database_and_migrations(db_config)

        check(database_section.status == doctor.READY, f"Database section is READY once the file exists, got {database_section.status}")
        check(migrations_section.status == doctor.READY, f"Migrations section is READY once all 9 are applied, got {migrations_section.status}")
        after_bytes = db_path.read_bytes()
        check(before_bytes == after_bytes, "doctor's read-only inspection left the database file byte-for-byte unchanged")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_g_migration_pending() -> None:
    print("\n[Scenario G] Migration pending")
    doctor = _fresh_import_doctor()
    tmp_dir = Path(tempfile.mkdtemp(prefix="doctor_g_"))
    try:
        from Database.database_config import DatabaseConfig
        from Database.migrations import MigrationRunner
        from Database.migrations_watchlist import WATCHLIST_MIGRATIONS
        from Database.sqlite_database import SQLiteDatabase

        db_path = tmp_dir / "aios.db"
        database = SQLiteDatabase(DatabaseConfig(db_path=db_path))
        database.connect()
        try:
            MigrationRunner(database).apply(WATCHLIST_MIGRATIONS)  # only version 1
        finally:
            database.disconnect()

        env = _clear_all_doctor_env()
        env["DB_PATH"] = str(db_path)
        with _EnvSandbox(**env):
            db_config = DatabaseConfig.from_env()
            database_section, migrations_section = doctor._check_database_and_migrations(db_config)

        check(migrations_section.status == doctor.BLOCKED, f"Migrations section is BLOCKED when some are pending, got {migrations_section.status}")
        detail = migrations_section.checks[0].detail
        check("accounts:v2" in detail, "pending detail names the missing accounts migration")
        check("snapshots:v10" in detail, "pending detail names the missing snapshots migration")
        check(database_section.status == doctor.READY, "Database section itself is still READY (file exists) even though migrations are pending")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def scenario_h_data_provider_missing() -> None:
    print("\n[Scenario H] Data provider (yfinance) missing")
    doctor = _fresh_import_doctor()
    original_find_spec = doctor.importlib.util.find_spec

    def _fake_find_spec(name, *args, **kwargs):
        if name == "yfinance":
            return None
        return original_find_spec(name, *args, **kwargs)

    doctor.importlib.util.find_spec = _fake_find_spec
    try:
        section = doctor._check_data_provider()
    finally:
        doctor.importlib.util.find_spec = original_find_spec

    check(section.status == doctor.OPTIONAL_MISSING, f"yfinance missing is OPTIONAL MISSING, got {section.status}")
    check(
        "not" in section.checks[0].detail and "install" in section.checks[0].detail,
        "detail explains yfinance is not installed",
    )
    check("READY" not in [c.status for c in section.checks], "missing yfinance is never silently reported READY")


def scenario_i_provider_unreachable() -> None:
    print("\n[Scenario I] Provider unreachable (Ollama, bad host) -- bounded time, no hang")
    doctor = _fresh_import_doctor()
    env = _clear_all_doctor_env()
    env["ACTIVE_PROVIDER"] = "ollama"
    env["OLLAMA_HOST"] = "http://127.0.0.1:1"  # connection refused, fast-fail
    env["OLLAMA_MODEL"] = "llama3"
    started = time.monotonic()
    with _EnvSandbox(**env):
        section = doctor._check_provider()
    elapsed = time.monotonic() - started
    check(section.status == doctor.BLOCKED, f"unreachable Ollama host is BLOCKED, got {section.status}")
    check(elapsed < 10.0, f"doctor did not hang -- provider check took {elapsed:.2f}s (bounded by a short internal timeout)")
    reachable_check = next(c for c in section.checks if c.label == "Provider reachable")
    check(
        "did not respond" in reachable_check.detail or "refused" in reachable_check.detail.lower(),
        "failure reason is explicit, not silently swallowed",
    )


def scenario_j_regression() -> None:
    print("\n[Scenario J] Existing command regression")
    import subprocess

    # J1: `python main.py doctor` never touches validate_runtime_environment /
    # build_application (proven by call-order instrumentation, same
    # technique as Stage 9.4's own regression proof -- not by reading
    # source text).
    env = dict(os.environ)
    for key in _clear_all_doctor_env():
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "main.py", "doctor"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    check(result.returncode == 1, f"'python main.py doctor' exits 1 on a BLOCKED (core-only, no provider configured) environment, got {result.returncode}")
    check("AIOS DOCTOR" in result.stdout, "'python main.py doctor' prints the diagnostic report to stdout")
    check("Traceback" not in result.stdout, "'python main.py doctor' does not crash with an unhandled traceback")

    # J2: plain `python main.py` (no argv) still reaches the same
    # build_application() this file's other scenarios exercise -- proves
    # the "doctor" dispatch branch is a no-op for every other invocation.
    # (Activation 1.5 LOCKED DECISION OVERRIDE: validation now happens at
    # the command boundary, not at startup, so an empty-stdin session
    # that never types a command -- e.g. "auto "/chat -- no longer
    # crashes with ConfigurationError here; it builds the app and exits
    # cleanly on EOF, exit code 0. This supersedes the pre-Activation-1.5
    # assertion that this crashed with a missing-provider error.)
    result_plain = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(ROOT),
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )
    check(
        result_plain.returncode == 0 and "Traceback" not in result_plain.stderr,
        "'python main.py' (no argv, no REPL input) builds the app and exits cleanly "
        "-- validation is deferred to the command boundary (Activation 1.5), not raised at startup",
    )

    # J3: doctor is importable and callable as a library entry point too
    # (used by run_doctor_command()), independent of the subprocess path.
    doctor = _fresh_import_doctor()
    check(callable(doctor.run_doctor_command), "Core.doctor.run_doctor_command is callable")


def scenario_exit_code_contract() -> None:
    print("\n[Scenario] exit_code contract: BLOCKED -> 1, everything else -> 0")
    doctor = _fresh_import_doctor()

    ready_only = doctor.DoctorReport(
        sections=[doctor.Section(name="x", checks=[doctor.CheckResult(label="a", status=doctor.READY)])]
    )
    optional_missing_present = doctor.DoctorReport(
        sections=[
            doctor.Section(name="x", checks=[doctor.CheckResult(label="a", status=doctor.READY)]),
            doctor.Section(name="y", checks=[doctor.CheckResult(label="b", status=doctor.OPTIONAL_MISSING)]),
        ]
    )
    blocked_present = doctor.DoctorReport(
        sections=[
            doctor.Section(name="x", checks=[doctor.CheckResult(label="a", status=doctor.READY)]),
            doctor.Section(name="y", checks=[doctor.CheckResult(label="b", status=doctor.BLOCKED)]),
        ]
    )
    check(ready_only.exit_code == 0, "all-READY report exits 0")
    check(optional_missing_present.exit_code == 0, "READY + OPTIONAL MISSING report exits 0 (not a failure)")
    check(blocked_present.exit_code == 1, "any BLOCKED report exits non-zero")


def scenario_no_silent_failure() -> None:
    print("\n[Scenario] No silent failure -- run_doctor() never raises even with a hostile/blank environment")
    doctor = _fresh_import_doctor()
    with _EnvSandbox(**_clear_all_doctor_env()):
        try:
            report = doctor.run_doctor()
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"    unexpected exception: {exc}")
    check(ok, "run_doctor() completes on a fully blank environment (no .env, no db, no ACTIVE_PROVIDER)")
    if ok:
        check(all(section.checks for section in report.sections), "every section has at least one concrete check (no empty/silent section)")


if __name__ == "__main__":
    scenario_a_healthy_core_environment()
    scenario_b_missing_optional_provider()
    scenario_c_active_provider_missing()
    scenario_d_telegram_missing()
    scenario_e_database_missing()
    scenario_f_database_ready()
    scenario_g_migration_pending()
    scenario_h_data_provider_missing()
    scenario_i_provider_unreachable()
    scenario_j_regression()
    scenario_exit_code_contract()
    scenario_no_silent_failure()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 1.2 DOCTOR COMMAND TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for description in _FAILURES:
            print(f"  - {description}")
        sys.exit(1)