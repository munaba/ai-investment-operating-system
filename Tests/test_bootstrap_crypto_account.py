"""Standalone regression checks for
``Core.bootstrap.ensure_default_crypto_account`` (crypto prototype).

Minimal, additive-only coverage:

* first call creates exactly one account row with
  ``account_id="crypto-usd"``, ``mode="paper"``, ``asset_class="crypto"``,
  ``currency="USD"`` -- no schema change, reuses the existing
  ``accounts`` table (``Database.migrations_accounts.ACCOUNTS_MIGRATIONS``,
  version=2) and the existing ``AccountRepository``;
* second call is idempotent -- no duplicate row, existing row returned
  unchanged;
* the pre-existing default paper account (``ensure_default_paper_account``,
  ``account_id="paper"``, ``currency="IDR"``) is unaffected -- proving
  this is purely additive, not a replacement, and that no FX/currency
  conversion happens between the two accounts.

Run directly with ``python Tests/test_bootstrap_crypto_account.py`` --
no external test framework required, matching
``test_account_migration.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.bootstrap import (  # noqa: E402
    DEFAULT_CRYPTO_ACCOUNT_ASSET_CLASS,
    DEFAULT_CRYPTO_ACCOUNT_BALANCE,
    DEFAULT_CRYPTO_ACCOUNT_CURRENCY,
    DEFAULT_CRYPTO_ACCOUNT_ID,
    DEFAULT_CRYPTO_ACCOUNT_MODE,
    ensure_default_crypto_account,
    ensure_default_paper_account,
)
from Database.database_config import DatabaseConfig  # noqa: E402
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


def _fresh_account_repository(tmp: str) -> AccountRepository:
    cfg = DatabaseConfig(db_path=Path(tmp) / "bootstrap_crypto.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    return AccountRepository(db)


def scenario_creates_usd_crypto_paper_account():
    print("\n[Scenario 1] first call creates the default crypto USD paper account")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        account, created = ensure_default_crypto_account(repo)

        check(created is True, "created=True on first call")
        check(account.account_id == DEFAULT_CRYPTO_ACCOUNT_ID, "account_id == 'crypto-usd'")
        check(account.mode == DEFAULT_CRYPTO_ACCOUNT_MODE, "mode == 'paper'")
        check(account.asset_class == DEFAULT_CRYPTO_ACCOUNT_ASSET_CLASS, "asset_class == 'crypto'")
        check(account.currency == DEFAULT_CRYPTO_ACCOUNT_CURRENCY, "currency == 'USD'")
        check(account.cash == DEFAULT_CRYPTO_ACCOUNT_BALANCE, "cash == DEFAULT_CRYPTO_ACCOUNT_BALANCE")
        check(account.equity == DEFAULT_CRYPTO_ACCOUNT_BALANCE, "equity == DEFAULT_CRYPTO_ACCOUNT_BALANCE")
        check(
            account.buying_power == DEFAULT_CRYPTO_ACCOUNT_BALANCE,
            "buying_power == DEFAULT_CRYPTO_ACCOUNT_BALANCE",
        )

        persisted = repo.get_by_id(DEFAULT_CRYPTO_ACCOUNT_ID)
        check(persisted is not None, "account is actually persisted (readable via get_by_id)")


def scenario_idempotent_on_rerun():
    print("\n[Scenario 2] second call is idempotent -- no duplicate row")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        first_account, first_created = ensure_default_crypto_account(repo)
        second_account, second_created = ensure_default_crypto_account(repo)

        check(first_created is True, "first call reports created=True")
        check(second_created is False, "second call reports created=False (no-op)")
        check(
            second_account.created_at == first_account.created_at,
            "created_at unchanged on rerun (existing row returned, not re-inserted)",
        )

        all_crypto_rows = [a for a in repo.list_all() if a.account_id == DEFAULT_CRYPTO_ACCOUNT_ID]
        check(len(all_crypto_rows) == 1, "exactly one 'crypto-usd' row exists after two calls")


def scenario_does_not_disturb_default_paper_account():
    print("\n[Scenario 3] pre-existing IDR paper account is unaffected -- additive only")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        paper_account, paper_created = ensure_default_paper_account(repo)
        crypto_account, crypto_created = ensure_default_crypto_account(repo)

        check(paper_created is True, "default IDR paper account still created normally")
        check(crypto_created is True, "crypto USD account created independently")
        check(paper_account.account_id != crypto_account.account_id, "distinct account_id values")
        check(paper_account.currency == "IDR", "paper account currency unchanged (IDR)")
        check(crypto_account.currency == "USD", "crypto account currency is USD (no FX conversion applied)")

        all_accounts = repo.list_all()
        check(len(all_accounts) == 2, "exactly two accounts exist -- paper and crypto, nothing extra")


def main() -> int:
    scenario_creates_usd_crypto_paper_account()
    scenario_idempotent_on_rerun()
    scenario_does_not_disturb_default_paper_account()

    print("\n" + "=" * 60)
    print(f"BOOTSTRAP CRYPTO ACCOUNT TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())