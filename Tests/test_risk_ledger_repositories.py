"""Standalone regression checks for
``Repository.persistence.risk_limits_repository.RiskLimitsRepository``
and ``Repository.persistence.journal_repository.JournalRepository``.

Covers Phase C ("Personal Risk Ledger + Decision Journal") persistence:

* RiskLimitsRepository is a mutable singleton row (insert-if-absent,
  update-in-place thereafter) -- never a second row;
* RiskLimitsRepository computes nothing -- persists exactly what the
  caller supplies, including allowed_symbols round-tripping and the
  None/"no restriction" case;
* a saved RiskLimits row survives a fresh repository instance over the
  same on-disk database file (restart survival);
* JournalRepository.create() is append-only (decision fields never
  change after creation);
* JournalRepository.record_outcome() only ever updates the five
  outcome columns of an existing row, never the decision fields;
* journal_entries.brief_id is FK-enforced against decision_briefs;
* list_by_symbol/list_by_brief_id/list_all ordering;
* a journal entry survives a fresh repository instance (restart
  survival);
* neither repository has any method that writes to orders/trades/
  positions (structural: no such collaborator even exists here).

Run directly with ``python Tests/test_risk_ledger_repositories.py`` --
no external test framework required, matching
``test_decision_brief_repository.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.exceptions import RepositoryError  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS  # noqa: E402
from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.models import JournalEntry, RiskLimits  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
from Repository.persistence.journal_repository import JournalRepository  # noqa: E402
from Repository.persistence.risk_limits_repository import RiskLimitsRepository  # noqa: E402

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


def _build_managers(db_path: Path) -> DatabaseManager:
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(DECISION_BRIEFS_MIGRATIONS)
    MigrationRunner(db).apply(RISK_LEDGER_MIGRATIONS)
    return DatabaseManager(db, cfg)


def _make_brief_id(brief_repo: DecisionBriefRepository, symbol: str = "BBCA") -> int:
    brief = brief_repo.create(
        symbol=symbol,
        generated_at="2026-08-22T09:00:00+00:00",
        status="SUCCESS",
        entry_price=9000.0,
        stop_loss_price=8820.0,
        take_profit_price=9360.0,
        risk_amount=1000.0,
        position_size=555.5,
        risk_reward_ratio=2.0,
    )
    return brief.brief_id


def scenario_risk_limits_singleton_insert_then_update():
    print("\n[Scenario 1] RiskLimitsRepository is a mutable singleton row")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_managers(Path(tmp) / "ledger.db")
        repo = RiskLimitsRepository(manager)

        check(repo.get_current() is None, "no risk_limits row before the first save()")

        first = repo.save(
            reference_capital=100000.0,
            max_risk_per_trade_percent=2.0,
            max_daily_loss=5000.0,
            max_trades_per_day=5,
            loss_streak_cooldown=3,
            updated_at="2026-08-22T08:00:00+00:00",
        )
        check(isinstance(first, RiskLimits), "save() returns a RiskLimits instance")
        check(first.id == "default", "the singleton row id is always 'default'")

        second = repo.save(
            reference_capital=150000.0,
            max_risk_per_trade_percent=1.5,
            max_daily_loss=6000.0,
            max_trades_per_day=4,
            loss_streak_cooldown=2,
            updated_at="2026-08-22T09:00:00+00:00",
        )
        current = repo.get_current()
        check(current.reference_capital == 150000.0, "a second save() overwrites the same row in place")
        check(current.max_trades_per_day == 4, "second save()'s values are what get_current() returns")

        # Confirm there is genuinely only ever one row.
        raw = manager.execute("SELECT COUNT(*) as n FROM risk_limits")
        check(raw.rows[0]["n"] == 1, "risk_limits table has exactly one row after two saves")


def scenario_risk_limits_allowed_symbols_round_trip():
    print("\n[Scenario 2] RiskLimitsRepository persists exactly what the caller supplies")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_managers(Path(tmp) / "ledger.db")
        repo = RiskLimitsRepository(manager)

        saved = repo.save(
            reference_capital=100000.0,
            max_risk_per_trade_percent=2.0,
            max_daily_loss=5000.0,
            max_trades_per_day=5,
            loss_streak_cooldown=3,
            updated_at="2026-08-22T08:00:00+00:00",
            allowed_symbols=["bbca", "tlkm"],
        )
        check(saved.allowed_symbols == ["BBCA", "TLKM"], "allowed_symbols is upper-cased exactly as supplied")

        reloaded = repo.get_current()
        check(reloaded.allowed_symbols == ["BBCA", "TLKM"], "allowed_symbols round-trips through get_current()")

        no_restriction = repo.save(
            reference_capital=100000.0,
            max_risk_per_trade_percent=2.0,
            max_daily_loss=5000.0,
            max_trades_per_day=5,
            loss_streak_cooldown=3,
            updated_at="2026-08-22T10:00:00+00:00",
            allowed_symbols=None,
        )
        check(no_restriction.allowed_symbols is None, "allowed_symbols=None round-trips as None (no restriction)")
        check(repo.get_current().allowed_symbols is None, "get_current() also reports None after clearing the allowlist")


def scenario_risk_limits_survives_restart():
    print("\n[Scenario 3] a saved RiskLimits row survives a fresh repository instance (restart survival)")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ledger.db"
        manager = _build_managers(db_path)
        repo = RiskLimitsRepository(manager)
        repo.save(
            reference_capital=250000.0,
            max_risk_per_trade_percent=1.0,
            max_daily_loss=3000.0,
            max_trades_per_day=6,
            loss_streak_cooldown=4,
            updated_at="2026-08-22T08:00:00+00:00",
            allowed_symbols=["BBCA"],
        )

        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg2)
        repo2 = RiskLimitsRepository(manager2)

        reloaded = repo2.get_current()
        check(reloaded is not None, "risk_limits row is still present after reconnecting to the same database file")
        check(reloaded.reference_capital == 250000.0, "reference_capital survives restart")
        check(reloaded.allowed_symbols == ["BBCA"], "allowed_symbols survives restart")


def scenario_journal_create_is_append_only():
    print("\n[Scenario 4] JournalRepository.create() is append-only")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_managers(Path(tmp) / "ledger.db")
        brief_repo = DecisionBriefRepository(manager)
        journal_repo = JournalRepository(manager)
        brief_id = _make_brief_id(brief_repo)

        entry = journal_repo.create(
            brief_id=brief_id,
            symbol="BBCA",
            decision="TAKE",
            decided_at="2026-08-22T09:00:00+00:00",
            risk_policy_status="ACCEPTED",
            created_at="2026-08-22T09:00:00+00:00",
            note="initial call",
            planned_r=2.0,
        )
        check(isinstance(entry, JournalEntry), "create() returns a JournalEntry instance")
        check(entry.entry_id is not None, "created entry has a repository-assigned entry_id")
        check(entry.decision == "TAKE", "decision persisted exactly as supplied")
        check(entry.risk_policy_status == "ACCEPTED", "risk_policy_status persisted exactly as supplied")
        check(entry.outcome_status is None, "outcome fields are NULL immediately after create()")
        check(entry.realized_r is None, "realized_r is NULL immediately after create()")

        repo_methods = {
            name
            for name in dir(JournalRepository)
            if not name.startswith("_") and callable(getattr(JournalRepository, name))
        }
        check("update" not in repo_methods, "JournalRepository has no update() method")
        check("delete" not in repo_methods, "JournalRepository has no delete() method")
        check("replace" not in repo_methods, "JournalRepository has no replace() method")


def scenario_journal_record_outcome_only_touches_outcome_columns():
    print("\n[Scenario 5] record_outcome() only updates the five outcome columns")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_managers(Path(tmp) / "ledger.db")
        brief_repo = DecisionBriefRepository(manager)
        journal_repo = JournalRepository(manager)
        brief_id = _make_brief_id(brief_repo)

        entry = journal_repo.create(
            brief_id=brief_id,
            symbol="BBCA",
            decision="TAKE",
            decided_at="2026-08-22T09:00:00+00:00",
            risk_policy_status="ACCEPTED",
            created_at="2026-08-22T09:00:00+00:00",
            note="initial note",
            planned_r=2.0,
        )

        updated = journal_repo.record_outcome(
            entry.entry_id,
            outcome_status="CLOSED_WIN",
            closed_at="2026-08-22T15:00:00+00:00",
            exit_price=9360.0,
            realized_r=2.0,
        )
        check(updated is not None, "record_outcome() returns the updated entry")
        check(updated.outcome_status == "CLOSED_WIN", "outcome_status is updated")
        check(updated.exit_price == 9360.0, "exit_price is updated")
        check(updated.realized_r == 2.0, "realized_r is updated")
        check(updated.closed_at == "2026-08-22T15:00:00+00:00", "closed_at is updated")

        # Decision fields set at create() time must be untouched.
        check(updated.decision == "TAKE", "decision field is unchanged by record_outcome()")
        check(updated.risk_policy_status == "ACCEPTED", "risk_policy_status field is unchanged by record_outcome()")
        check(updated.note == "initial note", "note field is unchanged by record_outcome()")
        check(updated.planned_r == 2.0, "planned_r field is unchanged by record_outcome()")
        check(updated.decided_at == "2026-08-22T09:00:00+00:00", "decided_at field is unchanged by record_outcome()")

        check(journal_repo.record_outcome(999999, outcome_status="OPEN", closed_at="x") is None, "record_outcome() returns None for a nonexistent entry_id")


def scenario_journal_brief_id_is_fk_enforced():
    print("\n[Scenario 6] journal_entries.brief_id is FK-enforced against decision_briefs")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_managers(Path(tmp) / "ledger.db")
        journal_repo = JournalRepository(manager)

        raised = False
        try:
            journal_repo.create(
                brief_id=999999,
                symbol="BBCA",
                decision="TAKE",
                decided_at="2026-08-22T09:00:00+00:00",
                risk_policy_status="ACCEPTED",
                created_at="2026-08-22T09:00:00+00:00",
            )
        except RepositoryError:
            raised = True
        check(raised, "creating a journal entry with a nonexistent brief_id raises RepositoryError (FK enforced)")


def scenario_journal_listing_and_ordering():
    print("\n[Scenario 7] list_by_symbol/list_by_brief_id/list_all ordering")
    with tempfile.TemporaryDirectory() as tmp:
        manager = _build_managers(Path(tmp) / "ledger.db")
        brief_repo = DecisionBriefRepository(manager)
        journal_repo = JournalRepository(manager)

        bbca_brief_id = _make_brief_id(brief_repo, "BBCA")
        tlkm_brief_id = _make_brief_id(brief_repo, "TLKM")

        e1 = journal_repo.create(
            brief_id=bbca_brief_id, symbol="BBCA", decision="TAKE",
            decided_at="2026-08-22T09:00:00+00:00", risk_policy_status="ACCEPTED",
            created_at="2026-08-22T09:00:00+00:00",
        )
        e2 = journal_repo.create(
            brief_id=tlkm_brief_id, symbol="TLKM", decision="SKIP",
            decided_at="2026-08-22T09:05:00+00:00", risk_policy_status="ACCEPTED",
            created_at="2026-08-22T09:05:00+00:00",
        )
        e3 = journal_repo.create(
            brief_id=bbca_brief_id, symbol="BBCA", decision="WAIT",
            decided_at="2026-08-22T10:00:00+00:00", risk_policy_status="ACCEPTED",
            created_at="2026-08-22T10:00:00+00:00",
        )

        bbca_entries = journal_repo.list_by_symbol("BBCA")
        check(len(bbca_entries) == 2, "list_by_symbol() returns only that symbol's rows")
        check([e.entry_id for e in bbca_entries] == [e1.entry_id, e3.entry_id], "list_by_symbol() ordered by entry_id ascending")

        by_brief = journal_repo.list_by_brief_id(bbca_brief_id)
        check(len(by_brief) == 2, "list_by_brief_id() returns only entries linked to that brief_id")

        every_entry = journal_repo.list_all()
        check(len(every_entry) == 3, "list_all() returns every entry across symbols")
        check(
            [e.entry_id for e in every_entry] == [e1.entry_id, e2.entry_id, e3.entry_id],
            "list_all() ordered by entry_id ascending",
        )
        check(journal_repo.get_by_id(999999) is None, "get_by_id() returns None for a nonexistent entry_id")


def scenario_journal_entry_survives_restart():
    print("\n[Scenario 8] a journal entry survives a fresh repository instance (restart survival)")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ledger.db"
        manager = _build_managers(db_path)
        brief_repo = DecisionBriefRepository(manager)
        journal_repo = JournalRepository(manager)
        brief_id = _make_brief_id(brief_repo)

        created = journal_repo.create(
            brief_id=brief_id,
            symbol="BBCA",
            decision="TAKE",
            decided_at="2026-08-22T09:00:00+00:00",
            risk_policy_status="ACCEPTED",
            created_at="2026-08-22T09:00:00+00:00",
            planned_r=2.0,
        )
        journal_repo.record_outcome(
            created.entry_id,
            outcome_status="CLOSED_LOSS",
            closed_at="2026-08-22T14:00:00+00:00",
            exit_price=8820.0,
            realized_r=-1.0,
        )

        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg2)
        journal_repo2 = JournalRepository(manager2)

        reloaded = journal_repo2.get_by_id(created.entry_id)
        check(reloaded is not None, "journal entry is still present after reconnecting to the same database file")
        check(reloaded.decision == "TAKE", "decision survives restart")
        check(reloaded.outcome_status == "CLOSED_LOSS", "outcome_status survives restart")
        check(reloaded.realized_r == -1.0, "realized_r survives restart")


def scenario_no_paper_order_collaborators():
    print("\n[Scenario 9] neither repository can write to orders/trades/positions")
    check(
        not any("order" in name.lower() for name in dir(RiskLimitsRepository) if not name.startswith("_")),
        "RiskLimitsRepository has no order-related method",
    )
    check(
        not any("order" in name.lower() for name in dir(JournalRepository) if not name.startswith("_")),
        "JournalRepository has no order-related method",
    )
    check(
        not any("trade" in name.lower() or "position" in name.lower() for name in dir(JournalRepository) if not name.startswith("_")),
        "JournalRepository has no trade/position-related method",
    )


def main() -> int:
    scenario_risk_limits_singleton_insert_then_update()
    scenario_risk_limits_allowed_symbols_round_trip()
    scenario_risk_limits_survives_restart()
    scenario_journal_create_is_append_only()
    scenario_journal_record_outcome_only_touches_outcome_columns()
    scenario_journal_brief_id_is_fk_enforced()
    scenario_journal_listing_and_ordering()
    scenario_journal_entry_survives_restart()
    scenario_no_paper_order_collaborators()

    print("\n" + "=" * 60)
    print(f"RISK LEDGER REPOSITORIES TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())