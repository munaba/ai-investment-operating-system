"""Standalone regression checks for
``Core.bootstrap.ensure_default_us_account`` (US stocks prototype,
Activation 9.1).

Minimal, additive-only coverage, mirroring
``Tests/test_bootstrap_crypto_account.py`` exactly for the US account:

* first call creates exactly one account row with
  ``account_id="us-usd"``, ``mode="paper"``, ``asset_class="stock_us"``,
  ``currency="USD"`` -- no schema change, reuses the existing
  ``accounts`` table (``Database.migrations_accounts.ACCOUNTS_MIGRATIONS``,
  version=2) and the existing ``AccountRepository``;
* second call is idempotent -- no duplicate row, existing row returned
  unchanged;
* the pre-existing default IDR paper account and the pre-existing USD
  crypto account are both unaffected -- proving this is purely
  additive (a third, independent account), not a replacement, and
  that no FX/currency conversion happens between any of the three.

Run directly with ``python Tests/test_bootstrap_us_account.py`` -- no
external test framework required, matching
``test_bootstrap_crypto_account.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.bootstrap import (  # noqa: E402
    DEFAULT_CRYPTO_ACCOUNT_ID,
    DEFAULT_PAPER_ACCOUNT_ID,
    DEFAULT_US_ACCOUNT_ASSET_CLASS,
    DEFAULT_US_ACCOUNT_BALANCE,
    DEFAULT_US_ACCOUNT_CURRENCY,
    DEFAULT_US_ACCOUNT_ID,
    DEFAULT_US_ACCOUNT_MODE,
    ensure_default_crypto_account,
    ensure_default_paper_account,
    ensure_default_us_account,
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
    cfg = DatabaseConfig(db_path=Path(tmp) / "bootstrap_us.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    return AccountRepository(db)


def scenario_creates_usd_us_paper_account():
    print("\n[Scenario 1] first call creates the default US-stocks USD paper account")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        account, created = ensure_default_us_account(repo)

        check(created is True, "created=True on first call")
        check(account.account_id == DEFAULT_US_ACCOUNT_ID, "account_id == 'us-usd'")
        check(account.mode == DEFAULT_US_ACCOUNT_MODE, "mode == 'paper'")
        check(account.asset_class == DEFAULT_US_ACCOUNT_ASSET_CLASS, "asset_class == 'stock_us'")
        check(account.currency == DEFAULT_US_ACCOUNT_CURRENCY, "currency == 'USD'")
        check(account.cash == DEFAULT_US_ACCOUNT_BALANCE, "cash == DEFAULT_US_ACCOUNT_BALANCE")
        check(account.equity == DEFAULT_US_ACCOUNT_BALANCE, "equity == DEFAULT_US_ACCOUNT_BALANCE")
        check(
            account.buying_power == DEFAULT_US_ACCOUNT_BALANCE,
            "buying_power == DEFAULT_US_ACCOUNT_BALANCE",
        )

        persisted = repo.get_by_id(DEFAULT_US_ACCOUNT_ID)
        check(persisted is not None, "account is actually persisted (readable via get_by_id)")


def scenario_idempotent_on_rerun():
    print("\n[Scenario 2] second call is idempotent -- no duplicate row")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        first_account, first_created = ensure_default_us_account(repo)
        second_account, second_created = ensure_default_us_account(repo)

        check(first_created is True, "first call reports created=True")
        check(second_created is False, "second call reports created=False (no-op)")
        check(
            second_account.created_at == first_account.created_at,
            "created_at unchanged on rerun (existing row returned, not re-inserted)",
        )

        all_us_rows = [a for a in repo.list_all() if a.account_id == DEFAULT_US_ACCOUNT_ID]
        check(len(all_us_rows) == 1, "exactly one 'us-usd' row exists after two calls")


def scenario_does_not_disturb_other_default_accounts():
    print("\n[Scenario 3] pre-existing IDR paper account and USD crypto account are unaffected -- additive only")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _fresh_account_repository(tmp)

        paper_account, paper_created = ensure_default_paper_account(repo)
        crypto_account, crypto_created = ensure_default_crypto_account(repo)
        us_account, us_created = ensure_default_us_account(repo)

        check(paper_created is True, "default IDR paper account still created normally")
        check(crypto_created is True, "crypto USD account still created independently")
        check(us_created is True, "US USD account created independently")

        ids = {paper_account.account_id, crypto_account.account_id, us_account.account_id}
        check(len(ids) == 3, "all three account_id values are distinct")
        check(ids == {DEFAULT_PAPER_ACCOUNT_ID, DEFAULT_CRYPTO_ACCOUNT_ID, DEFAULT_US_ACCOUNT_ID}, "expected id set")

        check(paper_account.currency == "IDR", "paper account currency unchanged (IDR)")
        check(crypto_account.currency == "USD", "crypto account currency unchanged (USD)")
        check(us_account.currency == "USD", "US account currency is USD (no FX conversion applied)")
        check(paper_account.asset_class == "stock_id", "paper account asset_class unchanged (stock_id)")
        check(crypto_account.asset_class == "crypto", "crypto account asset_class unchanged (crypto)")
        check(us_account.asset_class == "stock_us", "US account asset_class is stock_us")

        all_accounts = repo.list_all()
        check(len(all_accounts) == 3, "exactly three accounts exist -- paper, crypto, and us -- nothing extra")


def main() -> int:
    scenario_creates_usd_us_paper_account()
    scenario_idempotent_on_rerun()
    scenario_does_not_disturb_other_default_accounts()

    print("\n" + "=" * 60)
    print(f"BOOTSTRAP US ACCOUNT TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())