"""
Activation 1.3 proof suite -- ``python main.py init``.

Scope:
  - Core.init_command (new): run_init(), main().
  - Database.migration_registry (new): all_migrations()/expected_migrations(),
    the canonical migration ordering now shared with Core.doctor.
  - Database.migration_cli_helper (new): apply_domain_migrations(), the
    shared implementation behind the six standalone run_*_migrations.py
    compatibility wrappers.
  - main.py: the new "init" dispatch branch in the
    ``if __name__ == "__main__":`` block. main() itself and the
    pre-existing "doctor" branch are untouched and re-proven unaffected.

Cakupan skenario (mirrors the Activation 1.3 prompt's Section 19):
  A. Fresh database -- file+directory created, all migrations applied,
     version reported.
  B. Re-run init -- idempotent, no duplicate schema/migration records.
  C. Partial migration state -- only pending migrations applied,
     already-applied ones left untouched.
  D. Forced migration failure -- failure detected, exit non-zero, the
     specific failing migration correctly identified from the actual
     raised error (not guessed from list position), and the entire
     batch proven rolled back (no domain tables left behind, not even
     ones ordered before the forced failure).
  E. Recovery after a fix -- rerunning init with the bad migration
     removed completes successfully with no duplicates.
  F. Database path -- init and doctor read the exact same
     DatabaseConfig.from_env() source; doctor sees what init wrote.
  G. Provider independence -- ``python main.py init`` succeeds with a
     completely blank environment (no Gemini/Ollama/Telegram/DB_* env
     vars beyond DB_PATH itself).
  H. Existing command regression -- ``python main.py doctor`` and
     plain ``python main.py`` (no argv) are unaffected by the new
     "init" branch.

All os.environ / DB_PATH mutation is wrapped in try/finally (via
_EnvSandbox, copied from test_doctor_command.py's own pattern) so no
scenario leaks state into another test file run in the same process.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
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
    previous state (including "was unset") on exit. Copied from
    Tests/test_doctor_command.py's own ``_EnvSandbox`` so both proof
    suites sandbox the environment identically.
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


def _table_names(db_path: Path) -> List[str]:
    """Every user-defined table -- excludes 'sqlite_sequence', SQLite's
    own internal bookkeeping table auto-created the moment any table
    uses AUTOINCREMENT (e.g. positions/orders/trades/ranking_snapshots
    here), which is not something any migration creates directly.
    """
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        ).fetchall()
        return sorted(r[0] for r in rows)
    finally:
        con.close()


def scenario_a_fresh_database() -> None:
    print("\n[Scenario A] Fresh database")
    from Database.database_config import DatabaseConfig
    from Database.migration_registry import all_migrations
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "nested" / "aios.db"
        cfg = DatabaseConfig(db_path=db_path)

        check(not db_path.parent.exists(), "parent directory does not exist before init")
        check(not db_path.exists(), "database file does not exist before init")

        rc = run_init(db_config=cfg, print_fn=lambda _text: None)

        check(rc == 0, f"init exits 0 on a fresh environment, got {rc}")
        check(db_path.parent.exists(), "parent directory was created")
        check(db_path.is_file(), "database file was created")

        tables = _table_names(db_path)
        check("schema_migrations" in tables, "schema_migrations bookkeeping table exists")
        for table in ("watchlist", "accounts", "positions", "orders", "trades", "ranking_snapshots"):
            check(table in tables, f"'{table}' table exists after fresh init")

        expected_versions = {m.version for m, _domain in all_migrations()}
        con = sqlite3.connect(str(db_path))
        try:
            applied = {row[0] for row in con.execute("SELECT version FROM schema_migrations").fetchall()}
        finally:
            con.close()
        check(applied == expected_versions, f"schema_migrations records exactly {sorted(expected_versions)}, got {sorted(applied)}")


def scenario_b_rerun_idempotent() -> None:
    print("\n[Scenario B] Re-run init is idempotent")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg = DatabaseConfig(db_path=db_path)

        rc1 = run_init(db_config=cfg, print_fn=lambda _text: None)
        tables_after_first = _table_names(db_path)
        con = sqlite3.connect(str(db_path))
        rows_after_first = con.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        con.close()

        rc2 = run_init(db_config=cfg, print_fn=lambda _text: None)
        tables_after_second = _table_names(db_path)
        con = sqlite3.connect(str(db_path))
        rows_after_second = con.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        con.close()

        check(rc1 == 0 and rc2 == 0, "both first and second init runs exit 0")
        check(tables_after_first == tables_after_second, "no duplicate/changed tables after second run")
        check(rows_after_first == rows_after_second, "no duplicate/changed schema_migrations rows after second run")


def scenario_c_partial_migration() -> None:
    print("\n[Scenario C] Partial migration state")
    from Database.database_config import DatabaseConfig
    from Database.migrations import MigrationRunner
    from Database.migration_registry import all_migrations
    from Database.sqlite_database import SQLiteDatabase
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg = DatabaseConfig(db_path=db_path)

        entries = all_migrations()
        first_three = [m for m, _domain in entries if m.version in (1, 2, 3)]

        db = SQLiteDatabase(cfg)
        db.connect()
        MigrationRunner(db).apply(first_three)
        db.disconnect()

        applied_before = _table_names(db_path)
        check(set(applied_before) == {"schema_migrations", "watchlist", "accounts", "positions"},
              "only watchlist/accounts/positions tables exist before init")

        rc = run_init(db_config=cfg, print_fn=lambda _text: None)

        check(rc == 0, f"init exits 0 when resuming a partial migration state, got {rc}")
        tables_after = set(_table_names(db_path))
        check(
            tables_after == {"schema_migrations", "watchlist", "accounts", "positions", "orders", "trades", "ranking_snapshots", "order_idempotency_keys", "portfolio_snapshots", "order_approvals"},
            "remaining pending migrations (orders/trades/snapshots/idempotency/portfolio_snapshots/order_approvals) applied, existing ones untouched",
        )


def scenario_d_forced_failure() -> None:
    print("\n[Scenario D] Forced migration failure")
    from Database.database_config import DatabaseConfig
    from Database.migrations import Migration
    from Database.migration_registry import all_migrations
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg = DatabaseConfig(db_path=db_path)

        real = all_migrations()
        bad = Migration(
            version=999,
            name="forced_failure_for_test",
            up_statements=["SELECT * FROM this_table_does_not_exist_for_test"],
        )
        # Inserted mid-list on purpose: MigrationRunner sorts by version
        # internally regardless of caller order, so this also proves
        # init's failure attribution does not depend on list position.
        entries = [(m, d) for m, d in real if m.version <= 3]
        entries.append((bad, "test"))
        entries += [(m, d) for m, d in real if m.version in (4, 5, 10)]

        captured: List[str] = []
        rc = run_init(db_config=cfg, migrations=entries, print_fn=captured.append)
        output = captured[0] if captured else ""

        check(rc != 0, f"init exits non-zero on a forced migration failure, got {rc}")
        check("INIT FAILED" in output, "report says INIT FAILED")
        check("test:v999" in output, "the actually-failing migration (test:v999) is correctly identified, not a different one")
        check("Rollback: SUCCESS" in output, "report claims rollback SUCCESS")

        # Prove the rollback claim against real database state: the
        # whole batch (including watchlist/accounts/positions, which
        # were ordered *before* the forced failure) must be rolled
        # back too, since MigrationRunner.apply() treats one call as
        # fully atomic.
        tables = _table_names(db_path)
        check(tables == ["schema_migrations"], f"no domain table persisted after rollback, got {tables}")

        con = sqlite3.connect(str(db_path))
        try:
            applied = con.execute("SELECT version FROM schema_migrations").fetchall()
        finally:
            con.close()
        check(applied == [], "schema_migrations has zero rows after full-batch rollback")


def scenario_e_recovery() -> None:
    print("\n[Scenario E] Recovery after a fix")
    from Database.database_config import DatabaseConfig
    from Database.migrations import Migration
    from Database.migration_registry import all_migrations
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg = DatabaseConfig(db_path=db_path)

        real = all_migrations()
        bad = Migration(version=999, name="forced_failure_for_test", up_statements=["NOT VALID SQL AT ALL"])
        broken_entries = [(m, d) for m, d in real if m.version <= 3]
        broken_entries.append((bad, "test"))
        broken_entries += [(m, d) for m, d in real if m.version in (4, 5, 10)]

        rc_failed = run_init(db_config=cfg, migrations=broken_entries, print_fn=lambda _t: None)
        check(rc_failed != 0, "first (broken) init run fails as expected")

        rc_fixed = run_init(db_config=cfg, print_fn=lambda _t: None)
        check(rc_fixed == 0, f"rerun with the bad migration removed succeeds, got {rc_fixed}")

        tables = set(_table_names(db_path))
        check(
            tables == {"schema_migrations", "watchlist", "accounts", "positions", "orders", "trades", "ranking_snapshots", "order_idempotency_keys", "portfolio_snapshots", "order_approvals"},
            "final schema is complete and consistent after recovery",
        )
        expected_versions = {m.version for m, _domain in real}
        con = sqlite3.connect(str(db_path))
        try:
            applied = {row[0] for row in con.execute("SELECT version FROM schema_migrations").fetchall()}
        finally:
            con.close()
        check(applied == expected_versions, "no duplicate migration records after recovery")


def scenario_f_shared_database_path() -> None:
    print("\n[Scenario F] init and doctor read the same database path")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        with _EnvSandbox(DB_PATH=str(db_path)):
            import Core.doctor as doctor
            import Core.init_command as init_command

            rc = init_command.run_init(print_fn=lambda _t: None)
            check(rc == 0, "init succeeds against DB_PATH from the environment")

            report = doctor.run_doctor()
            db_section = next(s for s in report.sections if s.name == "Database")
            mig_section = next(s for s in report.sections if s.name == "Migrations")

            check(db_section.status == doctor.READY, "doctor sees the database as READY after init")
            check(mig_section.status == doctor.READY, "doctor sees migrations as current (READY) after init")
            file_check = next(c for c in db_section.checks if c.label == "Database file")
            check(str(db_path) in file_check.detail, "doctor's database-file check references the exact same path init wrote to")


def scenario_g_provider_independence() -> None:
    print("\n[Scenario G] Provider independence -- init needs no LLM/Telegram/data-provider credentials")
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        env = dict(os.environ)
        for key in (
            "ACTIVE_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL",
            "OLLAMA_HOST", "OLLAMA_MODEL", "OLLAMA_TIMEOUT",
            "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
        ):
            env.pop(key, None)
        env["DB_PATH"] = str(db_path)

        result = subprocess.run(
            [sys.executable, "main.py", "init"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        check(result.returncode == 0, f"'python main.py init' exits 0 with no provider credentials configured, got {result.returncode}")
        check("INIT SUCCESS" in result.stdout, "'python main.py init' reports INIT SUCCESS")
        check("Traceback" not in result.stdout and "Traceback" not in result.stderr,
              "'python main.py init' does not crash with an unhandled traceback")
        check(db_path.is_file(), "database file was actually created by the subprocess run")


def scenario_h_regression() -> None:
    print("\n[Scenario H] Existing command regression")
    import subprocess

    env = dict(os.environ)
    for key in (
        "ACTIVE_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL",
        "OLLAMA_HOST", "OLLAMA_MODEL", "OLLAMA_TIMEOUT",
        "DB_PATH", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    ):
        env.pop(key, None)

    # H1: "python main.py doctor" is unaffected by the new "init" branch.
    result_doctor = subprocess.run(
        [sys.executable, "main.py", "doctor"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    check(result_doctor.returncode == 1, f"'python main.py doctor' still exits 1 on a blocked core-only environment, got {result_doctor.returncode}")
    check("AIOS DOCTOR" in result_doctor.stdout, "'python main.py doctor' still prints its own report unaffected by the init branch")

    # H2: plain "python main.py" (no argv) is unaffected by the "init"
    # branch itself. (Activation 1.5 LOCKED DECISION OVERRIDE: validation
    # now happens at the command boundary, not at startup -- an
    # empty-stdin session that never types a command no longer crashes
    # with ConfigurationError; it builds the app and exits cleanly on
    # EOF. This supersedes the pre-Activation-1.5 assertion that this
    # crashed with a missing-provider error.)
    result_plain = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(ROOT), env=env, input="", capture_output=True, text=True, timeout=30,
    )
    check(
        result_plain.returncode == 0 and "Traceback" not in result_plain.stderr,
        "'python main.py' (no argv, no REPL input) builds the app and exits cleanly "
        "-- validation is deferred to the command boundary (Activation 1.5), not raised at startup",
    )

    # H3: init is importable and callable as a library entry point too.
    import Core.init_command as init_command
    check(callable(init_command.run_init), "Core.init_command.run_init is callable")
    check(callable(init_command.main), "Core.init_command.main is callable")


# ---------------------------------------------------------------------------
# Activation 1.4 -- application bootstrap proof scenarios (Section 17).
#
# Every scenario below uses its own tempfile.TemporaryDirectory() for both
# the database path AND config_template_path, so none of them touch the
# real project's .env.example -- unlike scenario_a..h above (which predate
# Activation 1.4 and intentionally use run_init()'s real default
# config_template_path, matching production behavior).
# ---------------------------------------------------------------------------


def _accounts_rows(db_path: Path) -> List[tuple]:
    con = sqlite3.connect(str(db_path))
    try:
        return con.execute("SELECT * FROM accounts ORDER BY account_id").fetchall()
    finally:
        con.close()


def scenario_i_fresh_bootstrap() -> None:
    print("\n[Scenario I] Fresh init produces bootstrap data")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init
    from Core.bootstrap import (
        DEFAULT_PAPER_ACCOUNT_ID, DEFAULT_PAPER_ACCOUNT_NAME,
        DEFAULT_PAPER_ACCOUNT_MODE, DEFAULT_PAPER_ACCOUNT_ASSET_CLASS,
        DEFAULT_PAPER_ACCOUNT_CURRENCY,
    )

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg_path = Path(tmp) / ".env.example"
        cfg = DatabaseConfig(db_path=db_path)

        rc = run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
        check(rc == 0, f"fresh init with bootstrap exits 0, got {rc}")

        rows = _accounts_rows(db_path)
        check(len(rows) == 1, f"exactly one account exists after fresh init, got {len(rows)}")
        (account_id, account_name, mode, currency, asset_class, cash, equity, buying_power, *_rest) = rows[0]
        check(account_id == DEFAULT_PAPER_ACCOUNT_ID, f"default account_id is {DEFAULT_PAPER_ACCOUNT_ID!r}, got {account_id!r}")
        check(account_name == DEFAULT_PAPER_ACCOUNT_NAME, f"default account_name is {DEFAULT_PAPER_ACCOUNT_NAME!r}, got {account_name!r}")
        check(mode == DEFAULT_PAPER_ACCOUNT_MODE, f"default mode is {DEFAULT_PAPER_ACCOUNT_MODE!r}, got {mode!r}")
        check(asset_class == DEFAULT_PAPER_ACCOUNT_ASSET_CLASS, f"default asset_class is {DEFAULT_PAPER_ACCOUNT_ASSET_CLASS!r}, got {asset_class!r}")
        check(currency == DEFAULT_PAPER_ACCOUNT_CURRENCY, f"default currency is {DEFAULT_PAPER_ACCOUNT_CURRENCY!r}, got {currency!r}")
        check(cash > 0 and equity > 0 and buying_power > 0, "default account has a positive starting balance")

        from Repository.persistence.watchlist_repository import WatchlistRepository
        from Database.database_manager import DatabaseManager
        from Database.sqlite_database import SQLiteDatabase
        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            symbols = WatchlistRepository(DatabaseManager(db, cfg)).list_all()
        finally:
            db.disconnect()
        check(symbols == [], f"watchlist has zero symbols after fresh init, got {symbols}")

        check(cfg_path.exists(), "safe config template exists after fresh init")


def scenario_j_rerun_no_duplicate() -> None:
    print("\n[Scenario J] Re-run init does not duplicate bootstrap data")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg_path = Path(tmp) / ".env.example"
        cfg = DatabaseConfig(db_path=db_path)

        run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
        rows_first = _accounts_rows(db_path)
        config_mtime_first = cfg_path.stat().st_mtime_ns

        rc2 = run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
        rows_second = _accounts_rows(db_path)
        config_mtime_second = cfg_path.stat().st_mtime_ns

        check(rc2 == 0, f"second init run exits 0, got {rc2}")
        check(len(rows_second) == 1, f"still exactly one account after rerun, got {len(rows_second)}")
        check(rows_first == rows_second, "account row is byte-identical after rerun (same identity, no reset)")
        check(config_mtime_first == config_mtime_second, "config template file was not rewritten on rerun")


def scenario_k_existing_account_preserved() -> None:
    print("\n[Scenario K] Existing account balance/identity preserved across rerun")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg_path = Path(tmp) / ".env.example"
        cfg = DatabaseConfig(db_path=db_path)

        run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)

        con = sqlite3.connect(str(db_path))
        con.execute("UPDATE accounts SET cash = 12345.0, equity = 12345.0, buying_power = 6789.0 WHERE account_id = 'paper'")
        con.commit()
        con.close()

        rc = run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
        check(rc == 0, f"init exits 0 with a pre-existing user-modified account, got {rc}")

        rows = _accounts_rows(db_path)
        check(len(rows) == 1, "still exactly one account, no duplicate created alongside the existing one")
        (_id, _name, _mode, _currency, _asset_class, cash, equity, buying_power, *_rest) = rows[0]
        check(cash == 12345.0 and equity == 12345.0 and buying_power == 6789.0, "existing account balance was not reset by init")


def scenario_l_existing_watchlist_preserved() -> None:
    print("\n[Scenario L] Existing watchlist symbols preserved across rerun")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init
    from Repository.persistence.watchlist_repository import WatchlistRepository
    from Database.database_manager import DatabaseManager
    from Database.sqlite_database import SQLiteDatabase

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg_path = Path(tmp) / ".env.example"
        cfg = DatabaseConfig(db_path=db_path)

        run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)

        db = SQLiteDatabase(cfg)
        db.connect()
        WatchlistRepository(DatabaseManager(db, cfg)).add("BBCA")
        WatchlistRepository(DatabaseManager(db, cfg)).add("BMRI")
        db.disconnect()

        rc = run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
        check(rc == 0, f"init exits 0 with a pre-existing non-empty watchlist, got {rc}")

        db2 = SQLiteDatabase(cfg)
        db2.connect()
        symbols = WatchlistRepository(DatabaseManager(db2, cfg)).list_all()
        db2.disconnect()
        check(set(symbols) == {"BBCA", "BMRI"}, f"watchlist not reset to empty, got {symbols}")


def scenario_m_existing_config_preserved() -> None:
    print("\n[Scenario M] Existing config template modification preserved")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg_path = Path(tmp) / ".env.example"
        cfg = DatabaseConfig(db_path=db_path)

        run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
        cfg_path.write_text(cfg_path.read_text() + "\nCUSTOM_USER_VAR=my-value\n")

        rc = run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
        check(rc == 0, f"init exits 0 with a user-modified config template present, got {rc}")
        check("CUSTOM_USER_VAR=my-value" in cfg_path.read_text(), "user's config template modification was not overwritten")


def scenario_n_no_secret_leakage() -> None:
    print("\n[Scenario N] Config template contains no real secrets")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg_path = Path(tmp) / ".env.example"
        cfg = DatabaseConfig(db_path=db_path)
        run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)

        content = cfg_path.read_text()
        credential_shaped_keys = {"GEMINI_API_KEY", "OLLAMA_HOST", "OLLAMA_MODEL", "GEMINI_MODEL",
                                   "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key in credential_shaped_keys:
                check(value.strip() == "", f"'{key}' has no real value baked into the template (empty placeholder)")
        check("TELEGRAM_BOT_TOKEN=" not in [ln.strip() for ln in content.splitlines() if not ln.strip().startswith("#")],
              "TELEGRAM_BOT_TOKEN is not written as a live (uncommented) line -- no confirmed contract yet")


def scenario_o_bootstrap_failure_and_recovery() -> None:
    print("\n[Scenario O] Bootstrap failure is reported distinctly, and is recoverable")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg = DatabaseConfig(db_path=db_path)

        # Force a real config_template failure: point at a path whose
        # parent is a plain file, not a directory, so mkdir/write raises
        # a genuine OSError -- no mocked/injected failure.
        blocker_file = Path(tmp) / "blocker"
        blocker_file.write_text("not a directory")
        bad_cfg_path = blocker_file / ".env.example"

        captured: List[str] = []
        rc = run_init(db_config=cfg, config_template_path=bad_cfg_path, print_fn=captured.append)
        output = captured[0] if captured else ""

        check(rc != 0, f"init exits non-zero when a bootstrap step fails, got {rc}")
        check("Migration: SUCCESS" in output, "report distinguishes Migration: SUCCESS")
        check("Bootstrap: FAILED" in output, "report distinguishes Bootstrap: FAILED")
        check("Overall: FAILED" in output, "report distinguishes Overall: FAILED")
        check("INIT FAILED" in output, "overall result is reported as INIT FAILED, never INIT SUCCESS")
        check("INIT SUCCESS" not in output, "INIT SUCCESS never appears when bootstrap failed")
        check("config_template" in output, "the specific failing bootstrap step is named in the report")

        rows_after_failure = _accounts_rows(db_path)
        check(len(rows_after_failure) == 1, "the account step, which ran before the failing step, still completed exactly once")

        good_cfg_path = Path(tmp) / ".env.example"
        rc_recovery = run_init(db_config=cfg, config_template_path=good_cfg_path, print_fn=lambda _t: None)
        check(rc_recovery == 0, f"rerun with the blocker removed from the path recovers successfully, got {rc_recovery}")
        rows_after_recovery = _accounts_rows(db_path)
        check(len(rows_after_recovery) == 1, "recovery run does not create a duplicate account")
        check(good_cfg_path.exists(), "recovery run creates the config template once the path is writable")


def scenario_p_doctor_integration() -> None:
    print("\n[Scenario P] Doctor integration after bootstrap")
    from Database.database_config import DatabaseConfig
    from Core.init_command import run_init
    from Repository.persistence.account_repository import AccountRepository
    from Repository.persistence.watchlist_repository import WatchlistRepository
    from Database.database_manager import DatabaseManager
    from Database.sqlite_database import SQLiteDatabase

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "aios.db"
        cfg_path = Path(tmp) / ".env.example"
        cfg = DatabaseConfig(db_path=db_path)

        with _EnvSandbox(DB_PATH=str(db_path)):
            rc = run_init(db_config=cfg, config_template_path=cfg_path, print_fn=lambda _t: None)
            check(rc == 0, f"init with bootstrap exits 0, got {rc}")

            import Core.doctor as doctor
            report = doctor.run_doctor()
            db_section = next(s for s in report.sections if s.name == "Database")
            mig_section = next(s for s in report.sections if s.name == "Migrations")
            check(db_section.status == doctor.READY, "doctor still sees Database READY after bootstrap runs")
            check(mig_section.status == doctor.READY, "doctor still sees Migrations READY after bootstrap runs")

        db = SQLiteDatabase(cfg)
        db.connect()
        try:
            dm = DatabaseManager(db, cfg)
            account = AccountRepository(dm).get_by_id("paper")
            symbols = WatchlistRepository(dm).list_all()
        finally:
            db.disconnect()
        check(account is not None, "default paper account can be found back via AccountRepository (doctor-level evidence)")
        check(symbols == [], "watchlist can be read back via WatchlistRepository (doctor-level evidence)")


if __name__ == "__main__":
    scenario_a_fresh_database()
    scenario_b_rerun_idempotent()
    scenario_c_partial_migration()
    scenario_d_forced_failure()
    scenario_e_recovery()
    scenario_f_shared_database_path()
    scenario_g_provider_independence()
    scenario_h_regression()
    scenario_i_fresh_bootstrap()
    scenario_j_rerun_no_duplicate()
    scenario_k_existing_account_preserved()
    scenario_l_existing_watchlist_preserved()
    scenario_m_existing_config_preserved()
    scenario_n_no_secret_leakage()
    scenario_o_bootstrap_failure_and_recovery()
    scenario_p_doctor_integration()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 1.3 + 1.4 INIT/BOOTSTRAP TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    sys.exit(0 if _FAIL == 0 else 1)