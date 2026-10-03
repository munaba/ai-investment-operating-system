"""Standalone regression checks for
``Repository.persistence.portfolio_snapshot_repository.
PortfolioSnapshotRepository`` (Activation 5.2).

Covers:

* create() happy path returns a PortfolioSnapshot with exact field
  values (not just a truthy/row-count check);
* snapshot_id is repository-generated (autoincrement), never
  caller-supplied;
* exposure defaults to None (NULL) when not supplied;
* list_by_account/list_all/get_latest_by_account/get_by_id;
* round-trip read after a real reconnect (restart persistence);
* PortfolioSnapshotRepository is append-only: no update/delete/
  replace/modify method exists at all.

Run directly with ``python Tests/test_portfolio_snapshot_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_accounts import ACCOUNTS_MIGRATIONS  # noqa: E402
from Database.migrations_portfolio_snapshots import PORTFOLIO_SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.models import PortfolioSnapshot  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.account_repository import AccountRepository  # noqa: E402
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository  # noqa: E402

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


def _build(tmp_dir: str, db_name: str = "pf_snapshots_repo.db"):
    cfg = DatabaseConfig(db_path=Path(tmp_dir) / db_name)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
    MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    account_repo = AccountRepository(manager)
    account_repo.create(
        account_id="paper-id",
        account_name="Paper Indonesia",
        mode="paper",
        currency="IDR",
        asset_class="stock_id",
        cash=100_000_000.0,
        equity=100_000_000.0,
        buying_power=100_000_000.0,
    )
    return db, PortfolioSnapshotRepository(manager)


def scenario_create_returns_exact_values():
    print("\n[Scenario 1] create() happy path returns exact field values")
    with tempfile.TemporaryDirectory() as tmp:
        db, repo = _build(tmp)
        try:
            snapshot = repo.create(
                account_id="paper-id",
                cash=95_000_000.0,
                market_value=5_200_000.0,
                equity=100_200_000.0,
                realized_pnl=150_000.0,
                unrealized_pnl=200_000.0,
                drawdown=0.0,
                timestamp="2026-08-11T09:00:00+00:00",
            )
            check(isinstance(snapshot, PortfolioSnapshot), "create() returns a PortfolioSnapshot instance")
            check(snapshot.snapshot_id is not None, "created snapshot has a repository-assigned snapshot_id")
            check(snapshot.account_id == "paper-id", "account_id persisted exactly as supplied")
            check(snapshot.cash == 95_000_000.0, "cash persisted exactly as supplied")
            check(snapshot.market_value == 5_200_000.0, "market_value persisted exactly as supplied")
            check(snapshot.equity == 100_200_000.0, "equity persisted exactly as supplied")
            check(snapshot.realized_pnl == 150_000.0, "realized_pnl persisted exactly as supplied")
            check(snapshot.unrealized_pnl == 200_000.0, "unrealized_pnl persisted exactly as supplied")
            check(snapshot.drawdown == 0.0, "drawdown persisted exactly as supplied")
            check(snapshot.timestamp == "2026-08-11T09:00:00+00:00", "timestamp persisted exactly as supplied")
            check(snapshot.exposure is None, "exposure defaults to None when not supplied (GAP, not fabricated)")
        finally:
            db.disconnect()


def scenario_snapshot_id_is_repository_generated():
    print("\n[Scenario 2] snapshot_id is autoincrement, never caller-supplied")
    with tempfile.TemporaryDirectory() as tmp:
        db, repo = _build(tmp)
        try:
            s1 = repo.create(
                account_id="paper-id", cash=1.0, market_value=0.0, equity=1.0,
                realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                timestamp="2026-08-11T09:00:00+00:00",
            )
            s2 = repo.create(
                account_id="paper-id", cash=2.0, market_value=0.0, equity=2.0,
                realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                timestamp="2026-08-11T10:00:00+00:00",
            )
            check(s2.snapshot_id == s1.snapshot_id + 1, "second create() gets the next autoincrement id")
        finally:
            db.disconnect()


def scenario_list_and_get_methods():
    print("\n[Scenario 3] list_by_account / list_all / get_latest_by_account / get_by_id")
    with tempfile.TemporaryDirectory() as tmp:
        db, repo = _build(tmp)
        try:
            for i in range(3):
                repo.create(
                    account_id="paper-id", cash=float(i), market_value=0.0, equity=float(i),
                    realized_pnl=0.0, unrealized_pnl=0.0, drawdown=0.0,
                    timestamp=f"2026-08-11T0{i}:00:00+00:00",
                )
            by_account = repo.list_by_account("paper-id")
            check(len(by_account) == 3, "list_by_account returns all 3 snapshots for the account")
            check([s.equity for s in by_account] == [0.0, 1.0, 2.0], "list_by_account is ordered by snapshot_id ascending")

            all_snapshots = repo.list_all()
            check(len(all_snapshots) == 3, "list_all returns all snapshots")

            latest = repo.get_latest_by_account("paper-id")
            check(latest is not None and latest.equity == 2.0, "get_latest_by_account returns the most recent row")

            fetched = repo.get_by_id(by_account[0].snapshot_id)
            check(fetched is not None and fetched.equity == 0.0, "get_by_id returns the correct row")

            none_for_other_account = repo.list_by_account("nonexistent")
            check(none_for_other_account == [], "list_by_account returns empty list for unknown account")

            none_for_missing_id = repo.get_by_id(999999)
            check(none_for_missing_id is None, "get_by_id returns None for a missing snapshot_id")
        finally:
            db.disconnect()


def scenario_round_trip_after_restart():
    print("\n[Scenario 4] round-trip read survives a real reconnect (restart persistence)")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = DatabaseConfig(db_path=Path(tmp) / "pf_snapshots_restart.db")
        db = SQLiteDatabase(cfg)
        db.connect()
        MigrationRunner(db).apply(ACCOUNTS_MIGRATIONS)
        MigrationRunner(db).apply(PORTFOLIO_SNAPSHOTS_MIGRATIONS)
        manager = DatabaseManager(db, cfg)
        AccountRepository(manager).create(
            account_id="paper-id", account_name="Paper Indonesia", mode="paper",
            currency="IDR", asset_class="stock_id",
            cash=100_000_000.0, equity=100_000_000.0, buying_power=100_000_000.0,
        )
        repo = PortfolioSnapshotRepository(manager)
        created = repo.create(
            account_id="paper-id", cash=42.0, market_value=8.0, equity=50.0,
            realized_pnl=1.0, unrealized_pnl=2.0, drawdown=0.1,
            timestamp="2026-08-11T12:00:00+00:00",
        )
        db.disconnect()

        db2 = SQLiteDatabase(DatabaseConfig(db_path=cfg.db_path))
        db2.connect()
        try:
            manager2 = DatabaseManager(db2, cfg)
            repo2 = PortfolioSnapshotRepository(manager2)
            reread = repo2.get_by_id(created.snapshot_id)
            check(reread is not None, "snapshot readable from a brand-new process/connection")
            check(reread.cash == 42.0, "cash survives restart")
            check(reread.market_value == 8.0, "market_value survives restart")
            check(reread.equity == 50.0, "equity survives restart")
            check(reread.realized_pnl == 1.0, "realized_pnl survives restart")
            check(reread.unrealized_pnl == 2.0, "unrealized_pnl survives restart")
            check(reread.drawdown == 0.1, "drawdown survives restart")
            check(reread.timestamp == "2026-08-11T12:00:00+00:00", "timestamp survives restart")
        finally:
            db2.disconnect()


def scenario_append_only_no_mutation_methods():
    print("\n[Scenario 5] PortfolioSnapshotRepository is append-only")
    forbidden = ("update", "delete", "replace", "modify", "remove")
    for name in forbidden:
        check(not hasattr(PortfolioSnapshotRepository, name), f"PortfolioSnapshotRepository has no '{name}' method")


def main() -> int:
    scenario_create_returns_exact_values()
    scenario_snapshot_id_is_repository_generated()
    scenario_list_and_get_methods()
    scenario_round_trip_after_restart()
    scenario_append_only_no_mutation_methods()

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {_PASS} passed, {_FAIL} failed")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
