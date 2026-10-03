"""Standalone regression checks for
``Services.journal_service.JournalService``.

Covers Phase C ("Personal Risk Ledger + Decision Journal") orchestration:

* reuses the existing, LOCKED ``DecisionBriefRepository`` and the one
  new ``RiskLedgerPolicy`` -- never a second risk engine;
* TAKE is policy-checked against persisted RiskLimits + real journal
  history; SKIP/WAIT are always accepted;
* planned_r is recorded only for a TAKE against a SUCCESS brief, never
  fabricated for SKIP/WAIT or a non-SUCCESS brief;
* realized_r is computed only when genuinely calculable (real
  exit_price AND a real entry_price/stop_loss_price with positive
  risk-per-unit) -- otherwise stays None;
* record_outcome() only allowed on an ACCEPTED TAKE;
* invalid decision / missing brief_id / missing entry_id raise
  ValueError (caller errors), never silently accepted;
* daily loss / trade count / loss-streak stats are derived fresh from
  real persisted journal rows on every call -- restart-safe by
  construction (no in-memory cache);
* recording ANY journal decision -- including an ACCEPTED TAKE --
  never creates a paper order / Trade / Position: this service holds
  no such collaborator at all (structural, not just a runtime check).

Run directly with ``python Tests/test_journal_service.py`` -- no
external test framework required, matching
``test_decision_brief_service.py``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.risk_ledger_policy import RiskLedgerPolicy  # noqa: E402
from Database.database_config import DatabaseConfig  # noqa: E402
from Database.database_manager import DatabaseManager  # noqa: E402
from Database.migrations import MigrationRunner  # noqa: E402
from Database.migrations_decision_briefs import DECISION_BRIEFS_MIGRATIONS  # noqa: E402
from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS  # noqa: E402
from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS  # noqa: E402
from Database.sqlite_database import SQLiteDatabase  # noqa: E402
from Repository.persistence.decision_brief_repository import DecisionBriefRepository  # noqa: E402
from Repository.persistence.journal_repository import JournalRepository  # noqa: E402
from Repository.persistence.risk_limits_repository import RiskLimitsRepository  # noqa: E402
from Services.journal_service import JournalService  # noqa: E402

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


def _build(db_path: Path):
    cfg = DatabaseConfig(db_path=db_path)
    db = SQLiteDatabase(cfg)
    db.connect()
    MigrationRunner(db).apply(SNAPSHOTS_MIGRATIONS)
    MigrationRunner(db).apply(DECISION_BRIEFS_MIGRATIONS)
    MigrationRunner(db).apply(RISK_LEDGER_MIGRATIONS)
    manager = DatabaseManager(db, cfg)
    brief_repo = DecisionBriefRepository(manager)
    limits_repo = RiskLimitsRepository(manager)
    journal_repo = JournalRepository(manager)
    service = JournalService(
        brief_repository=brief_repo,
        risk_limits_repository=limits_repo,
        journal_repository=journal_repo,
        risk_ledger_policy=RiskLedgerPolicy(),
    )
    return manager, brief_repo, limits_repo, journal_repo, service


def _success_brief(brief_repo: DecisionBriefRepository, symbol: str = "BBCA", **overrides):
    defaults = dict(
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
    defaults.update(overrides)
    return brief_repo.create(**defaults)


def _set_limits(limits_repo: RiskLimitsRepository, **overrides):
    defaults = dict(
        reference_capital=100000.0,
        max_risk_per_trade_percent=2.0,
        max_daily_loss=5000.0,
        max_trades_per_day=5,
        loss_streak_cooldown=3,
        updated_at="2026-08-22T08:00:00+00:00",
    )
    defaults.update(overrides)
    return limits_repo.save(**defaults)


def scenario_take_accepted_within_limits():
    print("\n[Scenario 1] TAKE within limits is ACCEPTED and records planned_r")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo)
        brief = _success_brief(brief_repo)

        entry = service.record_decision(brief.brief_id, "take")
        check(entry.risk_policy_status == "ACCEPTED", "compliant TAKE resolves ACCEPTED")
        check(entry.decision == "TAKE", "decision persisted as upper-cased TAKE")
        check(entry.planned_r == 2.0, "planned_r is the brief's risk_reward_ratio for a TAKE against SUCCESS")
        check(entry.risk_policy_reason is None, "ACCEPTED entry has no rejection reason")


def scenario_take_rejected_exceeds_limits():
    print("\n[Scenario 2] TAKE exceeding max risk per trade is RISK_REJECTED")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo, reference_capital=100000.0, max_risk_per_trade_percent=0.5)  # cap = 500.0
        brief = _success_brief(brief_repo, risk_amount=1000.0)

        entry = service.record_decision(brief.brief_id, "TAKE")
        check(entry.risk_policy_status == "RISK_REJECTED", "TAKE exceeding the risk cap is RISK_REJECTED")
        check(entry.risk_policy_reason is not None, "RISK_REJECTED entry carries a reason")
        # planned_r is keyed off (decision == TAKE and brief.status == SUCCESS)
        # only -- it is the brief's own risk_reward_ratio, verbatim, and is
        # independent of whether the risk-ledger gate itself ACCEPTED or
        # RISK_REJECTED this particular TAKE.
        check(entry.planned_r == 2.0, "planned_r still reflects the SUCCESS brief's risk_reward_ratio even when RISK_REJECTED")


def scenario_skip_and_wait_always_accepted():
    print("\n[Scenario 3] SKIP/WAIT are always ACCEPTED, never carry planned_r")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        # No limits configured at all -- would RISK_REJECT any TAKE.
        brief = _success_brief(brief_repo)

        skip_entry = service.record_decision(brief.brief_id, "skip", note="not confident")
        wait_entry = service.record_decision(brief.brief_id, "wait")

        check(skip_entry.risk_policy_status == "ACCEPTED", "SKIP is ACCEPTED even with no risk limits configured")
        check(wait_entry.risk_policy_status == "ACCEPTED", "WAIT is ACCEPTED even with no risk limits configured")
        check(skip_entry.planned_r is None, "SKIP never records planned_r")
        check(wait_entry.planned_r is None, "WAIT never records planned_r")
        check(skip_entry.note == "not confident", "note is persisted verbatim")


def scenario_take_against_non_success_brief_rejected():
    print("\n[Scenario 4] TAKE against a non-SUCCESS brief is RISK_REJECTED, no planned_r")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo)
        brief = brief_repo.create(
            symbol="TLKM",
            generated_at="2026-08-22T09:00:00+00:00",
            status="POLICY_BLOCKED",
            reason="no risk inputs supplied",
        )
        entry = service.record_decision(brief.brief_id, "TAKE")
        check(entry.risk_policy_status == "RISK_REJECTED", "TAKE against a POLICY_BLOCKED brief is RISK_REJECTED")
        check(entry.planned_r is None, "no planned_r for a rejected TAKE against a non-SUCCESS brief")


def scenario_invalid_decision_and_brief_id_raise_value_error():
    print("\n[Scenario 5] invalid decision / missing brief_id raise ValueError")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo)
        brief = _success_brief(brief_repo)

        raised_bad_decision = False
        try:
            service.record_decision(brief.brief_id, "MAYBE")
        except ValueError:
            raised_bad_decision = True
        check(raised_bad_decision, "an invalid decision value raises ValueError")

        raised_missing_brief = False
        try:
            service.record_decision(999999, "TAKE")
        except ValueError:
            raised_missing_brief = True
        check(raised_missing_brief, "a nonexistent brief_id raises ValueError")


def scenario_max_trades_per_day_enforced_via_real_history():
    print("\n[Scenario 6] max trades/day is enforced against real, persisted journal history")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo, max_trades_per_day=2)

        b1 = _success_brief(brief_repo, symbol="BBCA")
        b2 = _success_brief(brief_repo, symbol="TLKM")
        b3 = _success_brief(brief_repo, symbol="BMRI")

        e1 = service.record_decision(b1.brief_id, "TAKE")
        e2 = service.record_decision(b2.brief_id, "TAKE")
        e3 = service.record_decision(b3.brief_id, "TAKE")

        check(e1.risk_policy_status == "ACCEPTED", "1st TAKE of the day is ACCEPTED")
        check(e2.risk_policy_status == "ACCEPTED", "2nd TAKE of the day is ACCEPTED (at the cap)")
        check(e3.risk_policy_status == "RISK_REJECTED", "3rd TAKE of the day is RISK_REJECTED (over the cap)")


def scenario_loss_streak_cooldown_enforced_via_real_outcomes():
    print("\n[Scenario 7] loss-streak cooldown is enforced against real recorded outcomes")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, journal_repo, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo, loss_streak_cooldown=2, max_trades_per_day=10)

        # Two losing TAKEs, both closed CLOSED_LOSS.
        b1 = _success_brief(brief_repo, symbol="BBCA")
        e1 = service.record_decision(b1.brief_id, "TAKE")
        service.record_outcome(e1.entry_id, outcome_status="CLOSED_LOSS", exit_price=8820.0, closed_at="2026-08-22T10:00:00+00:00")

        b2 = _success_brief(brief_repo, symbol="TLKM")
        e2 = service.record_decision(b2.brief_id, "TAKE")
        service.record_outcome(e2.entry_id, outcome_status="CLOSED_LOSS", exit_price=8820.0, closed_at="2026-08-22T11:00:00+00:00")

        # A third TAKE should now be blocked by the 2-loss cooldown.
        b3 = _success_brief(brief_repo, symbol="BMRI")
        e3 = service.record_decision(b3.brief_id, "TAKE")
        check(e3.risk_policy_status == "RISK_REJECTED", "TAKE is RISK_REJECTED after hitting the loss-streak cooldown")
        check(e3.risk_policy_reason is not None and "cooldown" in e3.risk_policy_reason.lower(), "rejection reason names the cooldown")


def scenario_realized_r_only_when_genuinely_calculable():
    print("\n[Scenario 8] realized_r is computed only when genuinely calculable")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo)

        # Case A: real exit_price, real entry/stop -> real realized_r.
        brief_a = _success_brief(brief_repo, symbol="BBCA", entry_price=9000.0, stop_loss_price=8820.0)
        entry_a = service.record_decision(brief_a.brief_id, "TAKE")
        updated_a = service.record_outcome(entry_a.entry_id, outcome_status="CLOSED_WIN", exit_price=9360.0)
        check(updated_a.realized_r == 2.0, "realized_r = (exit - entry) / (entry - stop) when genuinely calculable")

        # Case B: no exit_price supplied -> realized_r stays None, never guessed.
        brief_b = _success_brief(brief_repo, symbol="TLKM")
        entry_b = service.record_decision(brief_b.brief_id, "TAKE")
        updated_b = service.record_outcome(entry_b.entry_id, outcome_status="OPEN", exit_price=None)
        check(updated_b.realized_r is None, "realized_r stays None when no exit_price is supplied")

        # Case C: exit_price supplied but linked brief has no real stop -> stays None (never fabricated).
        brief_c = brief_repo.create(
            symbol="BMRI",
            generated_at="2026-08-22T09:00:00+00:00",
            status="SUCCESS",
            entry_price=5000.0,
            stop_loss_price=5000.0,  # zero risk-per-unit -- degenerate on purpose
            take_profit_price=5200.0,
            risk_amount=100.0,
            position_size=10.0,
            risk_reward_ratio=1.0,
        )
        entry_c = service.record_decision(brief_c.brief_id, "TAKE")
        updated_c = service.record_outcome(entry_c.entry_id, outcome_status="CLOSED_BREAKEVEN", exit_price=5000.0)
        check(updated_c.realized_r is None, "realized_r stays None when risk-per-unit is non-positive (never guessed)")


def scenario_outcome_only_allowed_on_accepted_take():
    print("\n[Scenario 9] record_outcome() only allowed on an ACCEPTED TAKE")
    with tempfile.TemporaryDirectory() as tmp:
        _, brief_repo, limits_repo, _, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo)
        brief = _success_brief(brief_repo)

        skip_entry = service.record_decision(brief.brief_id, "SKIP")
        raised_on_skip = False
        try:
            service.record_outcome(skip_entry.entry_id, outcome_status="CLOSED_WIN")
        except ValueError:
            raised_on_skip = True
        check(raised_on_skip, "record_outcome() on a SKIP entry raises ValueError")

        rejected_limits = _set_limits(limits_repo, reference_capital=100.0, max_risk_per_trade_percent=0.01)
        brief2 = _success_brief(brief_repo, symbol="TLKM", risk_amount=1000.0)
        rejected_entry = service.record_decision(brief2.brief_id, "TAKE")
        check(rejected_entry.risk_policy_status == "RISK_REJECTED", "setup: this TAKE is indeed RISK_REJECTED")
        raised_on_rejected = False
        try:
            service.record_outcome(rejected_entry.entry_id, outcome_status="CLOSED_WIN")
        except ValueError:
            raised_on_rejected = True
        check(raised_on_rejected, "record_outcome() on a RISK_REJECTED TAKE raises ValueError")

        raised_on_missing = False
        try:
            service.record_outcome(999999, outcome_status="CLOSED_WIN")
        except ValueError:
            raised_on_missing = True
        check(raised_on_missing, "record_outcome() on a nonexistent entry_id raises ValueError")

        raised_on_bad_status = False
        try:
            _set_limits(limits_repo)
            brief3 = _success_brief(brief_repo, symbol="BMRI")
            accepted_entry = service.record_decision(brief3.brief_id, "TAKE")
            service.record_outcome(accepted_entry.entry_id, outcome_status="NOT_A_REAL_STATUS")
        except ValueError:
            raised_on_bad_status = True
        check(raised_on_bad_status, "record_outcome() with an invalid outcome_status raises ValueError")


def scenario_restart_safety_of_stats_and_history():
    print("\n[Scenario 10] restart persistence: stats/history are derived fresh from real, persisted rows")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "svc.db"
        manager, brief_repo, limits_repo, journal_repo, service = _build(db_path)
        _set_limits(limits_repo, max_trades_per_day=2)
        b1 = _success_brief(brief_repo, symbol="BBCA")
        b2 = _success_brief(brief_repo, symbol="TLKM")
        service.record_decision(b1.brief_id, "TAKE")
        service.record_decision(b2.brief_id, "TAKE")

        # Simulate a full process restart: fresh connection, fresh
        # repositories/service instances over the SAME on-disk file.
        cfg2 = DatabaseConfig(db_path=db_path)
        db2 = SQLiteDatabase(cfg2)
        db2.connect()
        manager2 = DatabaseManager(db2, cfg2)
        brief_repo2 = DecisionBriefRepository(manager2)
        limits_repo2 = RiskLimitsRepository(manager2)
        journal_repo2 = JournalRepository(manager2)
        service2 = JournalService(
            brief_repository=brief_repo2,
            risk_limits_repository=limits_repo2,
            journal_repository=journal_repo2,
            risk_ledger_policy=RiskLedgerPolicy(),
        )

        check(limits_repo2.get_current() is not None, "risk limits survive restart")
        check(len(journal_repo2.list_all()) == 2, "both journal entries survive restart")

        b3 = _success_brief(brief_repo2, symbol="BMRI")
        e3 = service2.record_decision(b3.brief_id, "TAKE")
        check(
            e3.risk_policy_status == "RISK_REJECTED",
            "max-trades-per-day cap is still enforced correctly against a fresh service instance after restart",
        )


def scenario_recording_any_decision_never_creates_paper_order():
    print("\n[Scenario 11] recording a journal decision -- of any kind -- never creates a paper order")
    with tempfile.TemporaryDirectory() as tmp:
        manager, brief_repo, limits_repo, journal_repo, service = _build(Path(tmp) / "svc.db")
        _set_limits(limits_repo)
        brief = _success_brief(brief_repo)

        # Structural guarantee: this service holds no reference to any
        # order/trade/position-writing collaborator at all.
        collaborator_attrs = vars(service)
        check(len(collaborator_attrs) == 4, "JournalService holds exactly its four declared collaborators")
        for attr_name, attr_value in collaborator_attrs.items():
            type_name = type(attr_value).__name__
            check(
                "Order" not in type_name and "Trade" not in type_name and "Position" not in type_name and "PaperTrading" not in type_name,
                f"collaborator '{attr_name}' ({type_name}) is not an order/trade/position/paper-trading component",
            )

        # Runtime guarantee: an ACCEPTED TAKE leaves the orders/trades/
        # positions tables (if present in this schema) completely
        # untouched -- journal_entries has no FK to any of them and no
        # code path writes to them.
        service.record_decision(brief.brief_id, "TAKE")
        service.record_decision(brief.brief_id, "SKIP")
        service.record_decision(brief.brief_id, "WAIT")

        for table_name in ("orders", "trades", "positions"):
            exists = manager.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            if exists.rows:
                count = manager.execute(f"SELECT COUNT(*) as n FROM {table_name}")
                check(count.rows[0]["n"] == 0, f"'{table_name}' table has zero rows after TAKE/SKIP/WAIT")

        check(len(journal_repo.list_all()) == 3, "exactly three journal_entries rows were written (one per decision)")


def main() -> int:
    scenario_take_accepted_within_limits()
    scenario_take_rejected_exceeds_limits()
    scenario_skip_and_wait_always_accepted()
    scenario_take_against_non_success_brief_rejected()
    scenario_invalid_decision_and_brief_id_raise_value_error()
    scenario_max_trades_per_day_enforced_via_real_history()
    scenario_loss_streak_cooldown_enforced_via_real_outcomes()
    scenario_realized_r_only_when_genuinely_calculable()
    scenario_outcome_only_allowed_on_accepted_take()
    scenario_restart_safety_of_stats_and_history()
    scenario_recording_any_decision_never_creates_paper_order()

    print("\n" + "=" * 60)
    print(f"JOURNAL SERVICE TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())