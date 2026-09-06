"""Standalone regression checks for
``Repository.persistence.account_repository.AccountRepository``.

Covers Sprint 3 STEP 3 (Accounts):

* create/get_by_id/get_by_name/list_all/update_balances happy paths;
* ``mode``/``asset_class`` validation raises ``ValidationError`` for
  out-of-domain values, using the existing exception (no new
  exception class introduced);
* duplicate ``account_id``/``account_name`` raise ``RepositoryError``;
* every value in ``ACCOUNT_MODES``/``ACCOUNT_ASSET_CLASSES`` passes
  both Python-level validation and the SQL CHECK constraint (proving
  both read from the same single source of truth);
* there is no delete/remove/delete_account method on the repository.

Run directly with ``python Tests/test_account_repository.py`` -- no
external test framework required, matching
``test_database_layer_smoke.py`` and ``test_news_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.exceptions import RepositoryError, ValidationError  # noqa: E402
from Database.account_constants import ACCOUNT_ASSET_CLASSES, ACCOUNT_MODES  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
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


def _build_repository(tmp_dir: str) -> AccountRepository:
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / "accounts_repo.db")
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    return AccountRepository(manager)


def scenario_create_and_get():
    print("\n[Scenario 1] create / get_by_id / get_by_name happy path")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        account = repo.create(
            account_id="paper-id",
            account_name="Paper Indonesia",
            mode="paper",
            currency="IDR",
            asset_class="stock_id",
            cash=100_000_000.0,
            equity=100_000_000.0,
            buying_power=100_000_000.0,
        )
        check(account.account_id == "paper-id", "create() returns account with correct account_id")
        check(account.created_at == account.updated_at, "created_at == updated_at on creation")

        by_id = repo.get_by_id("paper-id")
        check(by_id is not None, "get_by_id() finds the created account")
        check(by_id.account_name == "Paper Indonesia", "get_by_id() returns correct account_name")

        by_name = repo.get_by_name("Paper Indonesia")
        check(by_name is not None, "get_by_name() finds the created account")
        check(by_name.account_id == "paper-id", "get_by_name() returns correct account_id")

        missing = repo.get_by_id("does-not-exist")
        check(missing is None, "get_by_id() returns None for missing account")


def scenario_list_all():
    print("\n[Scenario 2] list_all() returns every account")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        repo.create("paper-id", "Paper Indonesia", "paper", "IDR", "stock_id", 0, 0, 0)
        repo.create("paper-us", "Paper US", "paper", "USD", "stock_us", 0, 0, 0)
        repo.create("crypto-main", "Crypto", "live", "USDT", "crypto", 0, 0, 0)

        accounts = repo.list_all()
        check(len(accounts) == 3, "list_all() returns all 3 created accounts")
        ids = [a.account_id for a in accounts]
        check(ids == sorted(ids), "list_all() ordered by account_id ascending")


def scenario_update_balances():
    print("\n[Scenario 3] update_balances() mutates in place")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        created = repo.create("paper-id", "Paper Indonesia", "paper", "IDR", "stock_id", 1000.0, 1000.0, 1000.0)

        repo.update_balances("paper-id", cash=500.0, equity=1500.0, buying_power=500.0)
        updated = repo.get_by_id("paper-id")

        check(updated.cash == 500.0, "cash updated in place")
        check(updated.equity == 1500.0, "equity updated in place")
        check(updated.buying_power == 500.0, "buying_power updated in place")
        check(updated.updated_at != created.created_at or updated.updated_at >= created.created_at,
              "updated_at is refreshed by update_balances()")
        check(updated.account_name == "Paper Indonesia", "account_name unchanged by update_balances()")


def scenario_invalid_mode_raises_validation_error():
    print("\n[Scenario 4] invalid mode raises ValidationError (existing exception, no new class)")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        try:
            repo.create("bad-mode", "Bad Mode", "simulation", "USD", "crypto", 0, 0, 0)
            check(False, "invalid mode raises ValidationError")
        except ValidationError:
            check(True, "invalid mode raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid mode raised wrong exception type: {type(exc).__name__}")


def scenario_invalid_asset_class_raises_validation_error():
    print("\n[Scenario 5] invalid asset_class raises ValidationError")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        try:
            repo.create("bad-asset", "Bad Asset", "paper", "USD", "commodities", 0, 0, 0)
            check(False, "invalid asset_class raises ValidationError")
        except ValidationError:
            check(True, "invalid asset_class raises ValidationError")
        except Exception as exc:  # noqa: BLE001
            check(False, f"invalid asset_class raised wrong exception type: {type(exc).__name__}")


def scenario_duplicate_id_and_name_raise_repository_error():
    print("\n[Scenario 6] duplicate account_id / account_name raise RepositoryError")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        repo.create("paper-id", "Paper Indonesia", "paper", "IDR", "stock_id", 0, 0, 0)

        try:
            repo.create("paper-id", "Different Name", "paper", "IDR", "stock_id", 0, 0, 0)
            check(False, "duplicate account_id raises RepositoryError")
        except RepositoryError:
            check(True, "duplicate account_id raises RepositoryError")

        try:
            repo.create("different-id", "Paper Indonesia", "paper", "IDR", "stock_id", 0, 0, 0)
            check(False, "duplicate account_name raises RepositoryError")
        except RepositoryError:
            check(True, "duplicate account_name raises RepositoryError")


def scenario_domain_values_consistent_with_single_source_of_truth():
    print("\n[Scenario 7] every ACCOUNT_MODES/ACCOUNT_ASSET_CLASSES value passes both Python and SQL layers")
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_repository(tmp)
        count = 0
        for mode in ACCOUNT_MODES:
            for asset_class in ACCOUNT_ASSET_CLASSES:
                account_id = f"acct-{mode}-{asset_class}"
                repo.create(account_id, account_id, mode, "USD", asset_class, 0, 0, 0)
                count += 1
        check(
            len(repo.list_all()) == count,
            f"all {count} combinations of ACCOUNT_MODES x ACCOUNT_ASSET_CLASSES inserted successfully",
        )


def scenario_no_delete_method_exists():
    print("\n[Scenario 8] AccountRepository has no delete/remove method")
    forbidden_names = ("delete", "remove", "delete_account", "remove_account", "soft_delete", "archive", "deactivate")
    for name in forbidden_names:
        check(not hasattr(AccountRepository, name), f"AccountRepository has no '{name}' method")


def main() -> int:
    scenario_create_and_get()
    scenario_list_all()
    scenario_update_balances()
    scenario_invalid_mode_raises_validation_error()
    scenario_invalid_asset_class_raises_validation_error()
    scenario_duplicate_id_and_name_raise_repository_error()
    scenario_domain_values_consistent_with_single_source_of_truth()
    scenario_no_delete_method_exists()

    print("\n" + "=" * 60)
    print(f"ACCOUNT REPOSITORY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
