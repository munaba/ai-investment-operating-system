"""CLI-level regression checks for ``python main.py init-us``
(Activation 9.3 STEP 3).

``Tests/test_init_us_command.py`` already covers the direct Python
API (``Core.init_us_command.run_init_us(db_config=...)``) thoroughly
and exclusively -- it never invokes ``main.py`` as a process, so it
cannot prove the CLI dispatch itself exists or is wired correctly.
This file is the narrowly-scoped complement: it proves the real
``python main.py init-us`` subprocess path --

    CLI parser (``sys.argv[1] == "init-us"``)
    -> main.py dispatch
    -> Core.init_us_command.run_init_us()
    -> real DB/account creation

-- reaches the exact same production account-creation path, using the
same ``DB_PATH``-driven canonical config mechanism
(``Database.database_config.DatabaseConfig.from_env()``) every other
one-shot CLI command (``init``, ``scan --market us``, etc.) already
uses. The dispatch function itself is never mocked; only the
subprocess's ``DB_PATH`` environment variable is set, to point at a
temporary database instead of a real one.

Covers, at the CLI/process level:

* a first ``python main.py init-us`` run creates the ``us-usd``
  account (currency=USD, asset_class=stock_us, mode=paper) and exits
  0;
* a second run is idempotent -- exit 0, no duplicate account row;
* plain ``python main.py init`` (no ``init-us``) never creates
  ``us-usd`` on its own -- opt-in behavior is unchanged.

Run directly with ``python Tests/test_init_us_cli_dispatch.py`` -- no
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

from Core.bootstrap import DEFAULT_PAPER_ACCOUNT_ID, DEFAULT_US_ACCOUNT_ID  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
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


def scenario_cli_creates_us_account():
    print("\n[Scenario A] python main.py init-us creates us-usd via real CLI dispatch")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_us.db"

        init_result = _run_cli(db_path, "init")
        check(init_result.returncode == 0, f"'init' exited 0 (stderr: {init_result.stderr[-300:]})")

        init_us_result = _run_cli(db_path, "init-us")
        check(
            init_us_result.returncode == 0,
            f"'init-us' exited 0 (stdout: {init_us_result.stdout[-300:]} stderr: {init_us_result.stderr[-300:]})",
        )
        check("INIT-US SUCCESS" in init_us_result.stdout, "'init-us' output reports INIT-US SUCCESS")

        accounts = {a.account_id: a for a in _accounts(db_path)}
        check(DEFAULT_US_ACCOUNT_ID in accounts, "'us-usd' account exists after CLI init-us")
        us_account = accounts.get(DEFAULT_US_ACCOUNT_ID)
        check(us_account is not None and us_account.currency == "USD", "currency == 'USD'")
        check(us_account is not None and us_account.asset_class == "stock_us", "asset_class == 'stock_us'")
        check(us_account is not None and us_account.mode == "paper", "mode == 'paper'")


def scenario_cli_idempotent():
    print("\n[Scenario B] python main.py init-us run twice is idempotent")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_us_idempotent.db"
        _run_cli(db_path, "init")

        first = _run_cli(db_path, "init-us")
        second = _run_cli(db_path, "init-us")

        check(first.returncode == 0, "first CLI init-us run exits 0")
        check(second.returncode == 0, "second CLI init-us run also exits 0 (not an error)")
        check("already_exists" in second.stdout, "second run reports Status: already_exists")

        us_rows = [a for a in _accounts(db_path) if a.account_id == DEFAULT_US_ACCOUNT_ID]
        check(len(us_rows) == 1, f"exactly one 'us-usd' row after two CLI init-us runs (found {len(us_rows)})")


def scenario_plain_init_does_not_create_us_account():
    print("\n[Scenario C] python main.py init alone never creates us-usd")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_init_only.db"

        init_result = _run_cli(db_path, "init")
        check(init_result.returncode == 0, "'init' exited 0")

        accounts = {a.account_id for a in _accounts(db_path)}
        check(
            DEFAULT_US_ACCOUNT_ID not in accounts,
            "'us-usd' does NOT exist after plain CLI 'init' alone (opt-in only, unchanged)",
        )
        check(DEFAULT_PAPER_ACCOUNT_ID in accounts, "default IDR 'paper' account exists as before")


def main() -> int:
    scenario_cli_creates_us_account()
    scenario_cli_idempotent()
    scenario_plain_init_does_not_create_us_account()

    print("\n" + "=" * 60)
    print(f"INIT-US CLI DISPATCH TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
