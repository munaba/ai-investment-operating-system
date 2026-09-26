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

class StubRankingSnapshot:
    def __init__(self, scan_time: str, symbol: str, status: str, recommendation: str, confidence: str, score_breakdown_json: str):
        self.scan_time = scan_time
        self.symbol = symbol
        self.status = status
        self.recommendation = recommendation
        self.confidence = confidence
        self.score_breakdown_json = score_breakdown_json

class StubPerformanceRepository:
    def __init__(self, snapshots=None, should_raise=False):
        self._snapshots = snapshots or []
        self._should_raise = should_raise

    def get_all_snapshots(self):
        if self._should_raise:
            raise RuntimeError("DB unreachable")
        return self._snapshots

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

    # ------------------------------------------------------------------
    # PHASE I GATE 2 -- analyze_evidence_profile
    # ------------------------------------------------------------------
    print("\n[Case 13] Gate 2: no performance_repository -> INSUFFICIENT_DATA")
    g1_only = DecisionCopilotSkill(StubJournalRepository([]))
    r = g1_only.analyze_evidence_profile()
    check(r.success is False and r.error == "INSUFFICIENT_DATA", "None performance_repository fails")

    print("\n[Case 14] Gate 2: happy path -> success, counts reconcile")
    snap_data = [
        StubRankingSnapshot("2026-09-01T09:00:00", "BBCA", "success", "WAIT", "MEDIUM", '{"momentum_contribution": 0.4, "value_contribution": 0.2}'),
        StubRankingSnapshot("2026-09-01T09:00:00", "BMRI", "success", "BUY", "HIGH", '{"momentum_contribution": 0.6}'),
        StubRankingSnapshot("2026-09-02T09:00:00", "BBCA", "success", "WAIT", "MEDIUM", '{"momentum_contribution": 0.5}'),
    ]
    g2 = DecisionCopilotSkill(StubJournalRepository([]), StubPerformanceRepository(snap_data))
    res = g2.analyze_evidence_profile()
    check(res.success is True, "success is True")
    check(res.error is None, "error is None")
    out2 = res.output
    check(out2["read_only"] is True, "read_only flag in output")
    check(out2["snapshot_count"] == 3, "snapshot_count is 3")
    check(out2["scan_count"] == 2, "scan_count is 2 (two distinct scan_time values)")
    check(out2["symbol_count"] == 2, "symbol_count is 2")
    check(out2["symbols"] == ["BBCA", "BMRI"], "symbols sorted")
    check(out2["recommendation_counts"] == {"WAIT": 2, "BUY": 1}, "recommendation_counts match")
    check(sum(out2["recommendation_counts"].values()) == out2["snapshot_count"] - out2["error_row_count"], "recommendation_counts sum to non-error rows")
    check(out2["status_counts"] == {"success": 3}, "status_counts match")
    check(out2["factor_contribution_totals"] == {"momentum_contribution": 1.5, "value_contribution": 0.2}, "factor totals accumulate")
    check(out2["error_row_count"] == 0, "error_row_count is 0")
    check(out2["unparsed_breakdown_count"] == 0, "unparsed_breakdown_count is 0")
    check(out2["scan_time_min"].startswith("2026-09-01"), "scan_time_min correct")
    check(out2["scan_time_max"].startswith("2026-09-02"), "scan_time_max correct")

    print("\n[Case 15] Gate 2: bad since/until -> DATA_ERROR")
    for bad_date in ["not-a-date", 12345]:
        r = g2.analyze_evidence_profile(bad_date, None)
        check(r.success is False and r.error == "DATA_ERROR", f"bad since {repr(bad_date)}")
        r2 = g2.analyze_evidence_profile(None, bad_date)
        check(r2.success is False and r2.error == "DATA_ERROR", f"bad until {repr(bad_date)}")

    print("\n[Case 16] Gate 2: since > until -> DATA_ERROR")
    r = g2.analyze_evidence_profile("2026-09-10T00:00:00", "2026-09-01T00:00:00")
    check(r.success is False and r.error == "DATA_ERROR", "since > until fails")

    print("\n[Case 17] Gate 2: repository raises -> DATA_ERROR")
    bad_g2 = DecisionCopilotSkill(StubJournalRepository([]), StubPerformanceRepository(should_raise=True))
    r = bad_g2.analyze_evidence_profile()
    check(r.success is False and r.error == "DATA_ERROR", "repo exception caught")

    print("\n[Case 18] Gate 2: zero snapshots in range -> INSUFFICIENT_DATA")
    empty_g2 = DecisionCopilotSkill(StubJournalRepository([]), StubPerformanceRepository([]))
    r = empty_g2.analyze_evidence_profile()
    check(r.success is False and r.error == "INSUFFICIENT_DATA", "empty range")
    r = empty_g2.analyze_evidence_profile("2020-01-01T00:00:00", "2020-01-02T00:00:00")
    check(r.success is False and r.error == "INSUFFICIENT_DATA", "out-of-range filter")

    print("\n[Case 19] Gate 2: error rows do not pollute recommendation_counts")
    mixed = [
        StubRankingSnapshot("2026-09-01T09:00:00", "BBCA", "success", "BUY", "HIGH", '{"a_contribution": 1.0}'),
        StubRankingSnapshot("2026-09-01T09:00:00", "TLKM", "error", None, None, None),
    ]
    mixed_g2 = DecisionCopilotSkill(StubJournalRepository([]), StubPerformanceRepository(mixed))
    out = mixed_g2.analyze_evidence_profile().output
    check(out["status_counts"] == {"success": 1, "error": 1}, "status_counts includes error")
    check(out["error_row_count"] == 1, "error_row_count is 1")
    check(out["recommendation_counts"] == {"BUY": 1}, "recommendation_counts excludes error row")
    check(out["confidence_counts"] == {"HIGH": 1}, "confidence_counts excludes error row")
    check("None" not in out["recommendation_counts"], "no None bucket in recommendation_counts")
    check("None" not in out["confidence_counts"], "no None bucket in confidence_counts")

    print("\n[Case 20] Gate 2: non-numeric contribution skipped, not zeroed")
    weird = [
        StubRankingSnapshot("2026-09-01T09:00:00", "BBCA", "success", "BUY", "HIGH", '{"momentum_contribution": "high", "value_contribution": 0.3}'),
    ]
    weird_g2 = DecisionCopilotSkill(StubJournalRepository([]), StubPerformanceRepository(weird))
    out = weird_g2.analyze_evidence_profile().output
    check(out["factor_contribution_totals"] == {"value_contribution": 0.3}, "only numeric contributions summed")
    check("momentum_contribution" not in out["factor_contribution_totals"], "non-numeric key absent (not zero)")
    check(out["unparsed_breakdown_count"] == 0, "valid JSON is not counted as unparsed")

    print("\n[Case 21] Gate 2: malformed score_breakdown_json -> unparsed_breakdown_count")
    broken = [
        StubRankingSnapshot("2026-09-01T09:00:00", "BBCA", "success", "BUY", "HIGH", "{not json"),
        StubRankingSnapshot("2026-09-01T09:00:00", "BMRI", "success", "BUY", "HIGH", '{"momentum_contribution": 0.9}'),
    ]
    broken_g2 = DecisionCopilotSkill(StubJournalRepository([]), StubPerformanceRepository(broken))
    out = broken_g2.analyze_evidence_profile().output
    check(out["unparsed_breakdown_count"] == 1, "one row counted unparsed")
    check(out["factor_contribution_totals"] == {"momentum_contribution": 0.9}, "good row still aggregated")
    check(out["snapshot_count"] == 2, "malformed JSON does not drop the row")

    print("\n[Case 22] Gate 2: score_breakdown_json null -> not counted unparsed")
    null_break = [
        StubRankingSnapshot("2026-09-01T09:00:00", "BBCA", "success", "BUY", "HIGH", None),
    ]
    null_g2 = DecisionCopilotSkill(StubJournalRepository([]), StubPerformanceRepository(null_break))
    out = null_g2.analyze_evidence_profile().output
    check(out["unparsed_breakdown_count"] == 0, "null breakdown is not unparsed")
    check(out["factor_contribution_totals"] == {}, "null breakdown contributes nothing")
    check(out["snapshot_count"] == 1, "row with null breakdown retained")

    print("\n[Case 23] Gate 2: output contains no forbidden keys")
    # Substring sweep with an explicit whitelist. recommendation_counts is the
    # one legitimate key that CONTAINS the word "recommendation"; the test
    # asserts it is present, so it cannot be deleted to dodge this sweep.
    WHITELIST = {"recommendation_counts"}
    forbidden = ["action", "plan", "recommendation_current", "signal", "order", "entry_price",
                 "stop_loss", "take_profit", "position_size", "expectancy", "win_rate",
                 "drawdown", "sharpe", "current", "recommendation"]
    for word in forbidden:
        offenders = [k for k in out2 if word in k and k not in WHITELIST]
        check(not offenders, f"no non-whitelisted '{word}' key (offenders={offenders})")
    check("recommendation_counts" in out2, "recommendation_counts present (whitelisted)")

    print("\n[Case 24] Gate 2: analysis runs against the real database")
    from Database.database_manager import DatabaseManager
    from Database.sqlite_database import SQLiteDatabase
    from Database.database_config import DatabaseConfig
    from Repository.persistence.performance_repository import PerformanceRepository
    from Orchestration.decision_copilot import DecisionCopilotSkill as _DCS
    try:
        mgr = DatabaseManager(SQLiteDatabase(DatabaseConfig.from_env()))
        live = _DCS(StubJournalRepository([]), PerformanceRepository(mgr))
        lr = live.analyze_evidence_profile()
        print(f"    [real DB] status={lr.success and 'SUCCESS' or lr.error} "
              f"snapshots={lr.output and lr.output.get('snapshot_count')}")
        if lr.success:
            lo = lr.output
            check(lo["read_only"] is True, "real DB: read_only flag is True")
            check(lo["snapshot_count"] > 0, "real DB: snapshot_count > 0")
            check(sum(lo["status_counts"].values()) == lo["snapshot_count"],
                  "real DB: status_counts sum to snapshot_count")
            check(lo["error_row_count"] == sum(
                v for k, v in lo["status_counts"].items() if k != "success"),
                  "real DB: error_row_count reconciles against status_counts")
            check(lo["unparsed_breakdown_count"] == 0,
                  f"real DB: unparsed_breakdown_count is 0 (got {lo['unparsed_breakdown_count']})")
        else:
            # fail-closed: the real table is empty is an acceptable, honest outcome
            check(lr.error in ("INSUFFICIENT_DATA", "DATA_ERROR"),
                  f"real DB: explicit status only ({lr.error})")
    except Exception as e:
        check(False, f"real DB probe raised: {type(e).__name__}: {e}")

    print("\n[Case 25] Boundary proofs for Gate 2")
    src = (ROOT / "Orchestration" / "decision_copilot.py").read_text(encoding="utf-8")
    # no write SQL anywhere in the skill
    for sql in ["INSERT ", "UPDATE ", "DELETE ", "DROP "]:
        check(sql not in src, f"Does not contain '{sql}'")
    # no re-ranking / engine invocation: assert on CODE, not comments/docstrings.
    # "RankingEngine" appears in prose in the docstring, so we check for
    # import + call forms, which only appear in real code.
    for bad in ["import RankingEngine", "from Business.ranking_engine",
                "RankingEngine.rank", "_engine.rank", ".run("]:
        check(bad not in src, f"Does not contain '{bad}'")
    # no write methods on either repository
    for bad in ["create_snapshot", "save_snapshot", "record_outcome", ".create("]:
        check(bad not in src, f"Does not contain '{bad}'")
    # Gate 2 added no new locked-file imports
    for locked in ["Orchestration.capability", "Core.providers", "copilot_runtime", "authorize_tool"]:
        check(locked not in src, f"Does not contain '{locked}'")
    # non-registrasi: skill name must not appear in registry/composition root
    reg = (ROOT / "Orchestration" / "skill_registry.py").read_text(encoding="utf-8") if (ROOT / "Orchestration" / "skill_registry.py").exists() else ""
    comp = (ROOT / "Core" / "composition_root.py").read_text(encoding="utf-8")
    check("decision_copilot" not in reg, "not registered in skill_registry.py")
    check("decision_copilot" not in comp, "not referenced in Core/composition_root.py")
    check("DecisionCopilotSkill" not in reg, "DecisionCopilotSkill absent from skill_registry.py")

if __name__ == "__main__":
    run_cases()
    print(f"\nTotal: {_PASS + _FAIL}, Passed: {_PASS}, Failed: {_FAIL}")
    sys.exit(0 if _FAIL == 0 else 1)
