"""Standalone regression checks for
``Core.init_us_command.run_init_us`` (``python main.py init-us``,
Activation 9.1).

Minimal, additive-only coverage, mirroring
``Tests/test_init_crypto_command.py`` exactly for the US account:

* creation -- after normal ``init`` (schema migrations applied), a
  first ``init-us`` run creates the ``us-usd`` account and returns
  exit code 0;
* idempotency -- a second ``init-us`` run on the same database is a
  no-op (exit code 0, no duplicate row);
* normal ``init`` is unaffected -- ``run_init`` still creates only the
  default IDR paper account on its own, with no US account appearing
  unless ``init-us`` is explicitly run;
* ``init-us`` fails cleanly (exit code 1) if run before ``init`` has
  ever created the ``accounts`` table;
* ``init-us`` and ``init-crypto`` are independent -- running one does
  not create or disturb the other's account.

Run directly with ``python Tests/test_init_us_command.py`` -- no
external test framework required, matching
``test_init_crypto_command.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.bootstrap import DEFAULT_CRYPTO_ACCOUNT_ID, DEFAULT_PAPER_ACCOUNT_ID, DEFAULT_US_ACCOUNT_ID  # noqa: E402
from Core.init_command import run_init  # noqa: E402
from Core.init_crypto_command import run_init_crypto  # noqa: E402
from Core.init_us_command import run_init_us  # noqa: E402
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


def _accounts(db_config: DatabaseConfig):
    """Read back every account row via a fresh connection (doctor-level evidence)."""
    db = SQLiteDatabase(db_config)
    db.connect()
    try:
        repo = AccountRepository(DatabaseManager(db, db_config))
        return repo.list_all()
    finally:
        db.disconnect()


def scenario_creation_after_init():
    print("\n[Scenario 1] init-us creates us-usd after normal init")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")

        init_rc = run_init(db_config=cfg, print_fn=lambda s: None)
        check(init_rc == 0, "normal init succeeds first")

        us_rc = run_init_us(db_config=cfg, print_fn=lambda s: None)
        check(us_rc == 0, "init-us exits 0 on first run")

        accounts = _accounts(cfg)
        account_ids = {a.account_id for a in accounts}
        check(DEFAULT_US_ACCOUNT_ID in account_ids, "'us-usd' account exists after init-us")
        check(DEFAULT_PAPER_ACCOUNT_ID in account_ids, "default IDR 'paper' account still exists (from init)")

        us_account = next(a for a in accounts if a.account_id == DEFAULT_US_ACCOUNT_ID)
        check(us_account.asset_class == "stock_us", "asset_class == 'stock_us'")
        check(us_account.currency == "USD", "currency == 'USD'")
        check(us_account.mode == "paper", "mode == 'paper'")


def scenario_idempotent_on_rerun():
    print("\n[Scenario 2] init-us is idempotent on rerun")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")
        run_init(db_config=cfg, print_fn=lambda s: None)

        first_rc = run_init_us(db_config=cfg, print_fn=lambda s: None)
        second_rc = run_init_us(db_config=cfg, print_fn=lambda s: None)

        check(first_rc == 0, "first init-us run exits 0")
        check(second_rc == 0, "second init-us run also exits 0 (not an error)")

        accounts = _accounts(cfg)
        us_rows = [a for a in accounts if a.account_id == DEFAULT_US_ACCOUNT_ID]
        check(len(us_rows) == 1, "exactly one us-usd row after two init-us runs")


def scenario_normal_init_alone_does_not_create_us_account():
    print("\n[Scenario 3] normal init alone never creates the US account")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")

        init_rc = run_init(db_config=cfg, print_fn=lambda s: None)
        check(init_rc == 0, "normal init succeeds")

        accounts = _accounts(cfg)
        account_ids = {a.account_id for a in accounts}
        check(
            DEFAULT_US_ACCOUNT_ID not in account_ids,
            "'us-usd' does NOT exist after plain init (opt-in only, unchanged init behavior)",
        )
        check(DEFAULT_PAPER_ACCOUNT_ID in account_ids, "default IDR 'paper' account exists as before")


def scenario_fails_cleanly_without_prior_init():
    print("\n[Scenario 4] init-us fails cleanly if accounts table does not exist yet")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")
        # No run_init() call -- database file/table does not exist.
        rc = run_init_us(db_config=cfg, print_fn=lambda s: None)
        check(rc == 1, "init-us exits 1 when 'accounts' table is missing (no silent migration)")


def scenario_independent_from_init_crypto():
    print("\n[Scenario 5] init-us and init-crypto are independent of each other")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")
        run_init(db_config=cfg, print_fn=lambda s: None)

        us_rc = run_init_us(db_config=cfg, print_fn=lambda s: None)
        check(us_rc == 0, "init-us succeeds on its own")

        accounts_after_us_only = {a.account_id for a in _accounts(cfg)}
        check(
            DEFAULT_CRYPTO_ACCOUNT_ID not in accounts_after_us_only,
            "running init-us alone does not create the crypto account",
        )

        crypto_rc = run_init_crypto(db_config=cfg, print_fn=lambda s: None)
        check(crypto_rc == 0, "init-crypto also succeeds afterwards")

        accounts_after_both = {a.account_id for a in _accounts(cfg)}
        check(
            {DEFAULT_PAPER_ACCOUNT_ID, DEFAULT_US_ACCOUNT_ID, DEFAULT_CRYPTO_ACCOUNT_ID} == accounts_after_both,
            "all three accounts (paper, us-usd, crypto-usd) coexist with no interference",
        )


def main() -> int:
    scenario_creation_after_init()
    scenario_idempotent_on_rerun()
    scenario_normal_init_alone_does_not_create_us_account()
    scenario_fails_cleanly_without_prior_init()
    scenario_independent_from_init_crypto()

    print("\n" + "=" * 60)
    print(f"INIT-US COMMAND TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())