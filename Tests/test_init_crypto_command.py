"""Standalone regression checks for
``Core.init_crypto_command.run_init_crypto`` (``python main.py init-crypto``).

Minimal, additive-only coverage:

* creation -- after normal ``init`` (schema migrations applied), a
  first ``init-crypto`` run creates the ``crypto-usd`` account and
  returns exit code 0;
* idempotency -- a second ``init-crypto`` run on the same database is
  a no-op (exit code 0, "already_exists", no duplicate row);
* normal ``init`` is unaffected -- ``run_init`` still creates only the
  default IDR paper account (``account_id="paper"``) on its own, with
  no crypto account appearing unless ``init-crypto`` is explicitly run.

Run directly with ``python Tests/test_init_crypto_command.py`` -- no
external test framework required, matching ``test_init_command.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.bootstrap import DEFAULT_CRYPTO_ACCOUNT_ID, DEFAULT_PAPER_ACCOUNT_ID  # noqa: E402
from Core.init_command import run_init  # noqa: E402
from Core.init_crypto_command import run_init_crypto  # noqa: E402
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
    print("\n[Scenario 1] init-crypto creates crypto-usd after normal init")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")

        init_rc = run_init(db_config=cfg, print_fn=lambda s: None)
        check(init_rc == 0, "normal init succeeds first")

        crypto_rc = run_init_crypto(db_config=cfg, print_fn=lambda s: None)
        check(crypto_rc == 0, "init-crypto exits 0 on first run")

        accounts = _accounts(cfg)
        account_ids = {a.account_id for a in accounts}
        check(DEFAULT_CRYPTO_ACCOUNT_ID in account_ids, "'crypto-usd' account exists after init-crypto")
        check(DEFAULT_PAPER_ACCOUNT_ID in account_ids, "default IDR 'paper' account still exists (from init)")

        crypto_account = next(a for a in accounts if a.account_id == DEFAULT_CRYPTO_ACCOUNT_ID)
        check(crypto_account.asset_class == "crypto", "asset_class == 'crypto'")
        check(crypto_account.currency == "USD", "currency == 'USD'")
        check(crypto_account.mode == "paper", "mode == 'paper'")


def scenario_idempotent_on_rerun():
    print("\n[Scenario 2] init-crypto is idempotent on rerun")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")
        run_init(db_config=cfg, print_fn=lambda s: None)

        first_rc = run_init_crypto(db_config=cfg, print_fn=lambda s: None)
        second_rc = run_init_crypto(db_config=cfg, print_fn=lambda s: None)

        check(first_rc == 0, "first init-crypto run exits 0")
        check(second_rc == 0, "second init-crypto run also exits 0 (not an error)")

        accounts = _accounts(cfg)
        crypto_rows = [a for a in accounts if a.account_id == DEFAULT_CRYPTO_ACCOUNT_ID]
        check(len(crypto_rows) == 1, "exactly one crypto-usd row after two init-crypto runs")


def scenario_normal_init_alone_does_not_create_crypto_account():
    print("\n[Scenario 3] normal init alone never creates the crypto account")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")

        init_rc = run_init(db_config=cfg, print_fn=lambda s: None)
        check(init_rc == 0, "normal init succeeds")

        accounts = _accounts(cfg)
        account_ids = {a.account_id for a in accounts}
        check(
            DEFAULT_CRYPTO_ACCOUNT_ID not in account_ids,
            "'crypto-usd' does NOT exist after plain init (opt-in only, unchanged init behavior)",
        )
        check(DEFAULT_PAPER_ACCOUNT_ID in account_ids, "default IDR 'paper' account exists as before")


def scenario_fails_cleanly_without_prior_init():
    print("\n[Scenario 4] init-crypto fails cleanly if accounts table does not exist yet")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "aios.db")
        # No run_init() call -- database file/table does not exist.
        rc = run_init_crypto(db_config=cfg, print_fn=lambda s: None)
        check(rc == 1, "init-crypto exits 1 when 'accounts' table is missing (no silent migration)")


def main() -> int:
    scenario_creation_after_init()
    scenario_idempotent_on_rerun()
    scenario_normal_init_alone_does_not_create_crypto_account()
    scenario_fails_cleanly_without_prior_init()

    print("\n" + "=" * 60)
    print(f"INIT-CRYPTO COMMAND TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())