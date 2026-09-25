"""
Phase I Gate 1 proof suite -- Decision Copilot Skill.

Scope:
  - Orchestration.decision_copilot.DecisionCopilotSkill (new)
  - Boundary guarantees (BaseSkill inheritance, no create/record_outcome calls)
  - Explicit non-action statuses (INSUFFICIENT_DATA, DATA_ERROR)
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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

class StubJournalEntry:
    def __init__(self, decided_at: str, decision: str, symbol: str):
        self.decided_at = decided_at
        self.decision = decision
        self.symbol = symbol

class StubJournalRepository:
    def __init__(self, entries=None, should_raise=False):
        self._entries = entries or []
        self._should_raise = should_raise

    def list_all(self):
        if self._should_raise:
            raise RuntimeError("DB unreachable")
        return self._entries

class StubContext:
    def __init__(self, parameters):
        self.parameters = parameters


def run_cases():
    print("\n[Case 1] Subclass of BaseSkill, correct name/description")
    from Orchestration.base_skill import BaseSkill
    from Orchestration.decision_copilot import DecisionCopilotSkill
    
    repo = StubJournalRepository()
    skill = DecisionCopilotSkill(repo)
    check(isinstance(skill, BaseSkill), "inherits from BaseSkill")
    check(skill.name == "decision_copilot", "correct name")
    check("read-only" in skill.description.lower(), "description states read-only")

    print("\n[Case 2] Happy path -> success=True, counts reconcile, read_only=True")
    repo_data = [
        StubJournalEntry("2026-09-01T10:00:00", "TAKE", "BBCA"),
        StubJournalEntry("2026-09-02T10:00:00", "SKIP", "BBCA"),
        StubJournalEntry("2026-09-03T10:00:00", "TAKE", "BMRI"),
    ]
    skill = DecisionCopilotSkill(StubJournalRepository(repo_data))
    res = skill.analyze_historical_patterns("ACC123", "2026-08-30T00:00:00", "2026-09-05T00:00:00")
    check(res.success is True, "success is True")
    check(res.error is None, "error is None")
    
    out = res.output
    check(out is not None, "output is not None")
    check(out["read_only"] is True, "read_only flag in output")
    check(out["entry_count"] == 3, "entry_count is 3")
    check(out["symbol_count"] == 2, "symbol_count is 2 (BBCA, BMRI)")
    check(out["decision_counts"] == {"TAKE": 2, "SKIP": 1}, "decision_counts match")
    check(sum(out["decision_counts"].values()) == out["entry_count"], "counts sum to total")

    print("\n[Case 3] account_id empty / None / non-str -> INSUFFICIENT_DATA")
    for bad_acc in ["", "   ", None, 123]:
        r = skill.analyze_historical_patterns(bad_acc, "2026-09-01T00:00:00", "2026-09-05T00:00:00")
        check(r.success is False and r.error == "INSUFFICIENT_DATA", f"bad account {repr(bad_acc)}")

    print("\n[Case 4] since / until unparseable -> DATA_ERROR")
    for bad_date in ["not-a-date", None, ""]:
        r = skill.analyze_historical_patterns("ACC", bad_date, "2026-09-05T00:00:00")
        check(r.success is False and r.error == "DATA_ERROR", f"bad since {repr(bad_date)}")
        r2 = skill.analyze_historical_patterns("ACC", "2026-09-01T00:00:00", bad_date)
        check(r2.success is False and r2.error == "DATA_ERROR", f"bad until {repr(bad_date)}")

    print("\n[Case 5] since > until -> DATA_ERROR")
    r = skill.analyze_historical_patterns("ACC", "2026-09-05T00:00:00", "2026-09-01T00:00:00")
    check(r.success is False and r.error == "DATA_ERROR", "since > until fails")

    print("\n[Case 6] repository raises -> DATA_ERROR")
    bad_skill = DecisionCopilotSkill(StubJournalRepository(should_raise=True))
    r = bad_skill.analyze_historical_patterns("ACC", "2026-09-01T00:00:00", "2026-09-05T00:00:00")
    check(r.success is False and r.error == "DATA_ERROR", "repo exception caught")

    print("\n[Case 7] zero entries in range -> INSUFFICIENT_DATA")
    empty_skill = DecisionCopilotSkill(StubJournalRepository([]))
    r = empty_skill.analyze_historical_patterns("ACC", "2026-09-01T00:00:00", "2026-09-05T00:00:00")
    check(r.success is False and r.error == "INSUFFICIENT_DATA", "empty range")

    print("\n[Case 8] output contains no forbidden keys")
    forbidden = ["action", "plan", "recommendation", "signal", "order", "trade", 
                 "entry_price", "stop_loss", "take_profit", "position_size"]
    for word in forbidden:
        check(all(word not in k for k in out.keys()), f"no {word} key in output")

    print("\n[Case 9] distinct_decisions sorted and genuine")
    check(out["distinct_decisions"] == ["SKIP", "TAKE"], "distinct_decisions is sorted list of genuine values")

    print("\n[Case 10] execute() adapter behaves correctly")
    r = skill.execute(StubContext({"account_id": "ACC", "since": "2026-09-01T00:00:00", "until": "2026-09-05T00:00:00"}))
    check(r.success is True, "execute() delegates correctly")
    
    r2 = skill.execute(StubContext(None))
    check(r2.success is False and r2.error == "INSUFFICIENT_DATA", "execute() missing parameters")

    print("\n[Case 11 & 12] Boundary proofs by source inspection")
    source = (ROOT / "Orchestration" / "decision_copilot.py").read_text(encoding="utf-8")
    
    import_checks = ["import Orchestration.capability", "from Orchestration.capability", 
                     "import Core.providers", "import copilot_runtime", "authorize_tool"]
    for bad_imp in import_checks:
        check(bad_imp not in source, f"Does not contain '{bad_imp}'")
        
    write_checks = [".create(", ".record_outcome("]
    for bad_write in write_checks:
        check(bad_write not in source, f"Does not contain '{bad_write}'")

if __name__ == "__main__":
    run_cases()
    print(f"\nTotal: {_PASS + _FAIL}, Passed: {_PASS}, Failed: {_FAIL}")
    sys.exit(0 if _FAIL == 0 else 1)
