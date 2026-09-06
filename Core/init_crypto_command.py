from __future__ import annotations

"""Crypto prototype -- ``python main.py init-crypto``.

Explicit, opt-in-only CLI command that creates the default USD crypto
paper account (``account_id="crypto-usd"``) via the existing
``Core.bootstrap.ensure_default_crypto_account`` -- introduced instead
of wiring that function into ``Core.bootstrap.run_bootstrap`` /
``python main.py init`` (see that function's own docstring for why:
wiring it into the default bootstrap sequence would silently create a
second account for every user on every ``init`` run, a decision this
command defers to an explicit, separate invocation instead).

Scope boundary, deliberately narrow:

  * Does NOT modify ``Core.init_command.run_init`` or
    ``Core.bootstrap.run_bootstrap`` in any way -- normal ``init``
    behavior (schema migrations + default IDR paper account +
    watchlist check + config template) is completely unchanged.
  * Does NOT apply schema migrations itself -- the ``accounts`` table
    is already part of the canonical migration plan
    (``Database.migration_registry.all_migrations()``) that ``init``
    applies. This command assumes ``init`` has already been run at
    least once; if the ``accounts`` table does not exist yet, it fails
    with a clear message rather than silently migrating on the user's
    behalf.
  * Does NOT touch orders, positions, trades, or any crypto strategy
    code -- account/bootstrap scope only, mirroring
    ``ensure_default_crypto_account`` itself.

Reuses the same database-opening pattern as
``Core.init_command.run_init`` (``DatabaseConfig.from_env()``,
``SQLiteDatabase``, ``DatabaseManager``, ``AccountRepository``) -- no
second way of reaching the database is introduced.
"""

import sys
from pathlib import Path
from typing import Callable, Optional

from Core.exceptions import RepositoryError
from Core.bootstrap import ensure_default_crypto_account
from Core.logger import get_logger
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.sqlite_database import SQLiteDatabase
from Repository.persistence.account_repository import AccountRepository

logger = get_logger(__name__)


def run_init_crypto(
    db_config: Optional[DatabaseConfig] = None,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Create (or confirm) the default USD crypto paper account.

    Idempotent: safe to run more than once. Delegates entirely to
    ``Core.bootstrap.ensure_default_crypto_account`` for the actual
    create-if-absent logic -- this function only owns the CLI-level
    concerns (opening the database, formatting output, exit code).

    Args:
        db_config: Database configuration to use. Defaults to
            ``DatabaseConfig.from_env()`` -- the same source
            ``python main.py init``/``doctor`` already use.
        print_fn: Injection point for tests to capture output instead
            of writing to real stdout. Defaults to the builtin
            ``print``, mirroring ``Core.init_command.run_init``.

    Returns:
        ``0`` on success (whether newly created or already existed).
        ``1`` if the database could not be opened, the ``accounts``
        table does not exist yet (``init`` has not been run), or the
        repository call otherwise failed.
    """
    config = db_config or DatabaseConfig.from_env()
    db_path = Path(config.db_path)

    lines = ["AIOS INIT-CRYPTO", "=" * len("AIOS INIT-CRYPTO")]

    database = SQLiteDatabase(config)
    try:
        database.connect()
    except Exception as exc:  # noqa: BLE001 -- reported below, not swallowed
        logger.error(f"init-crypto: failed to open database at '{db_path}': {exc}")
        lines += [
            "",
            "Database",
            f"  Path: {db_path}",
            f"  Error: {exc}",
            "",
            "Result",
            "  INIT-CRYPTO FAILED",
        ]
        print_fn("\n".join(lines))
        return 1

    try:
        lines += ["", "Database", f"  Path: {db_path}"]

        database_manager = DatabaseManager(database, config)
        account_repository = AccountRepository(database_manager)

        try:
            account, created = ensure_default_crypto_account(account_repository)
        except RepositoryError as exc:
            logger.error(f"init-crypto: could not create/read crypto account: {exc}")
            lines += [
                "",
                "Bootstrap Failed",
                f"  Reason: {exc}",
                "  Hint: run 'python main.py init' first to create the 'accounts' table.",
                "",
                "Result",
                "  INIT-CRYPTO FAILED",
            ]
            print_fn("\n".join(lines))
            return 1

        lines += [
            "",
            "Crypto Account",
            f"  account_id={account.account_id!r} account_name={account.account_name!r} "
            f"mode={account.mode!r} asset_class={account.asset_class!r} "
            f"currency={account.currency!r} cash={account.cash}",
            f"  Status: {'created' if created else 'already_exists'}",
            "",
            "Result",
            "  INIT-CRYPTO SUCCESS",
        ]
        print_fn("\n".join(lines))
        return 0
    finally:
        database.disconnect()


def main() -> int:
    return run_init_crypto()


if __name__ == "__main__":
    sys.exit(main())