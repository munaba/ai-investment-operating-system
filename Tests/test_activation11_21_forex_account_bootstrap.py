"""Standalone regression checks for Activation 11.21 -- Forex paper
account bootstrap.

Covers both layers, mirroring the existing US/Crypto pair of test
files exactly, merged into one file for this Activation:

* direct Python API (``Core.bootstrap.ensure_default_forex_account``)
  -- mirrors ``Tests/test_bootstrap_us_account.py`` /
  ``Tests/test_bootstrap_crypto_account.py``;
* real CLI subprocess dispatch (``python main.py init-forex``) --
  mirrors ``Tests/test_init_us_cli_dispatch.py``.

Scope, matching Activation 11.21 exactly:

* first call/run creates exactly one account row with
  ``account_id="forex-usd"``, ``mode="paper"``, ``asset_class="forex"``,
  ``currency="USD"`` -- no schema change, reuses the existing
  ``accounts`` table (``Database.migrations_accounts.ACCOUNTS_MIGRATIONS``,
  version=2) and the existing ``AccountRepository``;
* second call/run is idempotent -- no duplicate row, existing row
  returned unchanged;
* the pre-existing default IDR paper account, USD crypto account, and
  USD US-stocks account are all unaffected -- proving this is purely
  additive (a fourth, independent account), not a replacement;
* plain ``python main.py init`` never auto-creates the Forex account;
* ``init-us``/``init-crypto`` remain unaffected by this addition.

This file does NOT test Forex paper BUY/SELL, ``--market forex``
routing, or Forex analysis -- those are out of scope for Activation
11.21 and are expected to still fail/reject after this step (see the
Activation 11.21 roadmap document).

Run directly with
``python Tests/test_activation11_21_forex_account_bootstrap.py`` -- no
external test framework required, matching every other
``Tests/test_*.py`` file in this suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.bootstrap import (  # noqa: E402
    DEFAULT_CRYPTO_ACCOUNT_ID,
    DEFAULT_FOREX_ACCOUNT_ASSET_CLASS,
    DEFAULT_FOREX_ACCOUNT_BALANCE,
    DEFAULT_FOREX_ACCOUNT_CURRENCY,
    DEFAULT_FOREX_ACCOUNT_ID,
    DEFAULT_FOREX_ACCOUNT_MODE,
    DEFAULT_PAPER_ACCOUNT_ID,
    DEFAULT_US_ACCOUNT_ID,
    ensure_default_crypto_account,
    ensure_default_forex_account,
    ensure_default_paper_account,
    ensure_default_us_account,
)
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402

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


# --- Part A: direct Python API (Core.bootstrap.ensure_default_forex_account) --


def _fresh_account_repository(tmp: str) -> AccountRepository:
    cfg = DatabaseConfig(db_path=Path(tmp) / "bootstrap_forex.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    return AccountRepository(db)


def scenario_a_direct_bootstrap_creates_usd_forex_paper_account():
    print("\n[Scenario A] direct bootstrap: first call creates the default Forex USD paper account")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        account, created = ensure_default_forex_account(repo)

        check(created is True, "created=True on first call")
        check(account.account_id == DEFAULT_FOREX_ACCOUNT_ID, "account_id == 'forex-usd'")
        check(account.mode == DEFAULT_FOREX_ACCOUNT_MODE, "mode == 'paper'")
        check(account.asset_class == DEFAULT_FOREX_ACCOUNT_ASSET_CLASS, "asset_class == 'forex'")
        check(account.currency == DEFAULT_FOREX_ACCOUNT_CURRENCY, "currency == 'USD'")
        check(account.cash == DEFAULT_FOREX_ACCOUNT_BALANCE, "cash == DEFAULT_FOREX_ACCOUNT_BALANCE")
        check(account.equity == DEFAULT_FOREX_ACCOUNT_BALANCE, "equity == DEFAULT_FOREX_ACCOUNT_BALANCE")
        check(
            account.buying_power == DEFAULT_FOREX_ACCOUNT_BALANCE,
            "buying_power == DEFAULT_FOREX_ACCOUNT_BALANCE",
        )

        persisted = repo.get_by_id(DEFAULT_FOREX_ACCOUNT_ID)
        check(persisted is not None, "account is actually persisted (readable via get_by_id)")


def scenario_b_direct_bootstrap_idempotent_on_rerun():
    print("\n[Scenario B] direct bootstrap: second call is idempotent -- no duplicate row")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        first_account, first_created = ensure_default_forex_account(repo)
        second_account, second_created = ensure_default_forex_account(repo)

        check(first_created is True, "first call reports created=True")
        check(second_created is False, "second call reports created=False (no-op)")
        check(
            second_account.created_at == first_account.created_at,
            "created_at unchanged on rerun (existing row returned, not re-inserted)",
        )

        all_forex_rows = [a for a in repo.list_all() if a.account_id == DEFAULT_FOREX_ACCOUNT_ID]
        check(len(all_forex_rows) == 1, "exactly one 'forex-usd' row exists after two calls")


def scenario_does_not_disturb_other_default_accounts():
    print("\n[Scenario] pre-existing IDR/crypto/US accounts are unaffected -- additive only")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        paper_account, paper_created = ensure_default_paper_account(repo)
        crypto_account, crypto_created = ensure_default_crypto_account(repo)
        us_account, us_created = ensure_default_us_account(repo)
        forex_account, forex_created = ensure_default_forex_account(repo)

        check(paper_created is True, "default IDR paper account still created normally")
        check(crypto_created is True, "crypto USD account still created independently")
        check(us_created is True, "US USD account still created independently")
        check(forex_created is True, "Forex USD account created independently")

        ids = {paper_account.account_id, crypto_account.account_id, us_account.account_id, forex_account.account_id}
        check(len(ids) == 4, "all four account_id values are distinct")
        check(
            ids == {DEFAULT_PAPER_ACCOUNT_ID, DEFAULT_CRYPTO_ACCOUNT_ID, DEFAULT_US_ACCOUNT_ID, DEFAULT_FOREX_ACCOUNT_ID},
            "expected id set",
        )

        check(paper_account.currency == "IDR", "paper account currency unchanged (IDR)")
        check(crypto_account.currency == "USD", "crypto account currency unchanged (USD)")
        check(us_account.currency == "USD", "US account currency unchanged (USD)")
        check(forex_account.currency == "USD", "Forex account currency is USD (no FX conversion applied)")
        check(paper_account.asset_class == "stock_id", "paper account asset_class unchanged (stock_id)")
        check(crypto_account.asset_class == "crypto", "crypto account asset_class unchanged (crypto)")
        check(us_account.asset_class == "stock_us", "US account asset_class unchanged (stock_us)")
        check(forex_account.asset_class == "forex", "Forex account asset_class is forex")

        all_accounts = repo.list_all()
        check(
            len(all_accounts) == 4,
            "exactly four accounts exist -- paper, crypto, us, and forex -- nothing extra",
        )


# --- Part B: real CLI subprocess dispatch (python main.py init-forex) --


def _run_cli(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke the real ``python main.py <args>`` as a subprocess against
    ``db_path``, via the same ``DB_PATH`` env var
    ``DatabaseConfig.from_env()`` reads -- no second config mechanism.
    """
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=str(_PROJECT_ROOT),
        env={**os.environ, "DB_PATH": str(db_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _accounts(db_path: Path):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    try:
        repo = AccountRepository(DatabaseManager(db, cfg))
        return repo.list_all()
    finally:
        db.disconnect()


def scenario_c_cli_creates_forex_account():
    print("\n[Scenario C] python main.py init-forex creates forex-usd via real CLI dispatch")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_forex.db"

        init_result = _run_cli(db_path, "init")
        check(init_result.returncode == 0, f"'init' exited 0 (stderr: {init_result.stderr[-300:]})")

        init_forex_result = _run_cli(db_path, "init-forex")
        check(
            init_forex_result.returncode == 0,
            f"'init-forex' exited 0 (stdout: {init_forex_result.stdout[-300:]} "
            f"stderr: {init_forex_result.stderr[-300:]})",
        )
        check("INIT-FOREX SUCCESS" in init_forex_result.stdout, "'init-forex' output reports INIT-FOREX SUCCESS")

        accounts = {a.account_id: a for a in _accounts(db_path)}
        check(DEFAULT_FOREX_ACCOUNT_ID in accounts, "'forex-usd' account exists after CLI init-forex")
        forex_account = accounts.get(DEFAULT_FOREX_ACCOUNT_ID)
        check(forex_account is not None and forex_account.currency == "USD", "currency == 'USD'")
        check(forex_account is not None and forex_account.asset_class == "forex", "asset_class == 'forex'")
        check(forex_account is not None and forex_account.mode == "paper", "mode == 'paper'")


def scenario_d_cli_idempotent():
    print("\n[Scenario D] python main.py init-forex run twice is idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_forex_idempotent.db"
        _run_cli(db_path, "init")

        first = _run_cli(db_path, "init-forex")
        second = _run_cli(db_path, "init-forex")

        check(first.returncode == 0, "first CLI init-forex run exits 0")
        check(second.returncode == 0, "second CLI init-forex run also exits 0 (not an error)")
        check("already_exists" in second.stdout, "second run reports Status: already_exists")

        forex_rows = [a for a in _accounts(db_path) if a.account_id == DEFAULT_FOREX_ACCOUNT_ID]
        check(len(forex_rows) == 1, f"exactly one 'forex-usd' row after two CLI init-forex runs (found {len(forex_rows)})")


def scenario_e_plain_init_does_not_create_forex_account():
    print("\n[Scenario E] python main.py init alone never creates forex-usd")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_only_forex.db"

        init_result = _run_cli(db_path, "init")
        check(init_result.returncode == 0, "'init' exited 0")

        accounts = {a.account_id for a in _accounts(db_path)}
        check(
            DEFAULT_FOREX_ACCOUNT_ID not in accounts,
            "'forex-usd' does NOT exist after plain CLI 'init' alone (opt-in only)",
        )
        check(DEFAULT_PAPER_ACCOUNT_ID in accounts, "default IDR 'paper' account exists as before")


def scenario_f_init_us_does_not_create_forex_account():
    print("\n[Scenario F] python main.py init-us does not unexpectedly create forex-usd")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_us_isolation.db"

        _run_cli(db_path, "init")
        init_us_result = _run_cli(db_path, "init-us")
        check(init_us_result.returncode == 0, "'init-us' exited 0")

        accounts = {a.account_id for a in _accounts(db_path)}
        check(DEFAULT_US_ACCOUNT_ID in accounts, "'us-usd' account exists after init-us")
        check(
            DEFAULT_FOREX_ACCOUNT_ID not in accounts,
            "'forex-usd' does NOT exist after init-us alone (isolated, additive only)",
        )


def scenario_g_init_crypto_does_not_create_forex_account():
    print("\n[Scenario G] init-crypto does not unexpectedly create forex-usd")
    # Note: unlike "init-us"/"init-forex", "init-crypto" is NOT wired
    # into main.py's argv dispatch (confirmed by source inspection --
    # Tests/test_init_crypto_command.py itself only ever calls
    # Core.init_crypto_command.run_init_crypto() directly, never
    # "python main.py init-crypto" as a subprocess). Invoking it via
    # _run_cli would fall through to the REPL loop and hang on stdin,
    # not exercise init-crypto at all. This scenario therefore uses
    # the same direct-Python-API path the existing crypto test suite
    # already relies on, applied on top of a real CLI "init" run so
    # the isolation check still runs against a canonical, migrated DB.
    from Core.init_crypto_command import run_init_crypto  # noqa: E402 (local import, test-only)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_crypto_isolation.db"

        init_result = _run_cli(db_path, "init")
        check(init_result.returncode == 0, "'init' exited 0")

        cfg = DatabaseConfig(db_path=db_path)
        init_crypto_rc = run_init_crypto(db_config=cfg, print_fn=lambda s: None)
        check(init_crypto_rc == 0, "'init-crypto' (direct API) exited 0")

        accounts = {a.account_id for a in _accounts(db_path)}
        check(DEFAULT_CRYPTO_ACCOUNT_ID in accounts, "'crypto-usd' account exists after init-crypto")
        check(
            DEFAULT_FOREX_ACCOUNT_ID not in accounts,
            "'forex-usd' does NOT exist after init-crypto alone (isolated, additive only)",
        )


def scenario_h_account_metadata_exact():
    print("\n[Scenario H] forex-usd account metadata matches expected exact values")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_metadata_forex.db"
        _run_cli(db_path, "init")
        _run_cli(db_path, "init-forex")

        accounts = {a.account_id: a for a in _accounts(db_path)}
        forex_account = accounts.get(DEFAULT_FOREX_ACCOUNT_ID)
        check(forex_account is not None, "'forex-usd' account row exists")
        if forex_account is not None:
            check(forex_account.account_id == "forex-usd", "account_id == 'forex-usd'")
            check(forex_account.account_name == "Forex USD", "account_name == 'Forex USD'")
            check(forex_account.asset_class == "forex", "asset_class == 'forex'")
            check(forex_account.currency == "USD", "currency == 'USD'")
            check(forex_account.mode == "paper", "mode == 'paper'")
            check(forex_account.cash == DEFAULT_FOREX_ACCOUNT_BALANCE, "cash == DEFAULT_FOREX_ACCOUNT_BALANCE")
            check(forex_account.equity == DEFAULT_FOREX_ACCOUNT_BALANCE, "equity == DEFAULT_FOREX_ACCOUNT_BALANCE")
            check(
                forex_account.buying_power == DEFAULT_FOREX_ACCOUNT_BALANCE,
                "buying_power == DEFAULT_FOREX_ACCOUNT_BALANCE",
            )
            check(forex_account.created_at, "created_at is populated")
            check(forex_account.updated_at, "updated_at is populated")


def main() -> int:
    scenario_a_direct_bootstrap_creates_usd_forex_paper_account()
    scenario_b_direct_bootstrap_idempotent_on_rerun()
    scenario_does_not_disturb_other_default_accounts()
    scenario_c_cli_creates_forex_account()
    scenario_d_cli_idempotent()
    scenario_e_plain_init_does_not_create_forex_account()
    scenario_f_init_us_does_not_create_forex_account()
    scenario_g_init_crypto_does_not_create_forex_account()
    scenario_h_account_metadata_exact()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 11.21 FOREX ACCOUNT BOOTSTRAP RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())