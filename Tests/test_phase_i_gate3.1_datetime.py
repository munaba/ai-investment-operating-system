"""
Phase I Gate 3.1 proof suite — UTC-Aware Datetime Normalization (Bugfix).

PURPOSE
-------
This file proves the bug BEFORE the fix (Phase A — RED), then proves it is
gone AFTER the fix (same assertions, Phase B — GREEN).  The file itself is
never edited between runs; only ``Orchestration/decision_copilot.py`` changes.

SCOPE
-----
- Class A (hard crash): naive ``since``/``until`` against aware DB rows in
  ``analyze_evidence_profile`` → ``TypeError`` escaping to the caller.
- Class B (silent wrong answer): naive bounds against aware ``decided_at``
  in ``analyze_historical_patterns`` → ``TypeError`` swallowed by
  ``except (ValueError, TypeError, AttributeError): continue``
  → ``INSUFFICIENT_DATA`` returned even when matching data exists.
- Phase C: regression that the fix must not break (naive+naive still works,
  unparseable still → DATA_ERROR, etc.).
- Phase D: boundary proof by source inspection (no write SQL, no broker refs,
  ``timezone`` only new import, ``fromisoformat`` consolidated into helper).

Run:
    python Tests/test_phase_i_gate3.1_datetime.py

Expected pre-fix  (RED):  Phase A: ~5 FAIL, Phase C+D: all PASS.
Expected post-fix (GREEN): every case PASS.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PASS = 0
_FAIL = 0
_FAILURES: list[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# Stubs — minimal, no real DB
# ---------------------------------------------------------------------------

class _Entry:
    """Stub JournalEntry with aware or naive decided_at."""
    def __init__(self, decided_at: str, decision: str = "TAKE", symbol: str = "BBCA"):
        self.decided_at = decided_at
        self.decision = decision
        self.symbol = symbol


class _JRepo:
    def __init__(self, entries):
        self._e = entries

    def list_all(self):
        return self._e


class _Snap:
    """Stub RankingSnapshot with aware or naive scan_time."""
    def __init__(self, scan_time: str, symbol: str = "BBCA",
                 status: str = "success", recommendation: str = "WAIT",
                 confidence: str = "MEDIUM", score_breakdown_json=None):
        self.scan_time = scan_time
        self.symbol = symbol
        self.status = status
        self.recommendation = recommendation
        self.confidence = confidence
        self.score_breakdown_json = score_breakdown_json


class _PRepo:
    def __init__(self, snaps):
        self._s = snaps

    def get_all_snapshots(self):
        return self._s


# Aware UTC timestamps (as written by journal_service.py and the real DB)
_AWARE_INSIDE  = "2026-09-05T08:06:26.024842+00:00"   # inside any Sept range
_AWARE_OUTSIDE = "2026-08-22T08:06:26.024842+00:00"   # outside a Sept-onwards range

# Naive timestamps (as used by all existing Gate 1/2 test fixtures)
_NAIVE_INSIDE  = "2026-09-05T10:00:00"
_NAIVE_OUTSIDE = "2026-08-22T10:00:00"

# Bound values
_NAIVE_SINCE  = "2026-09-01"                           # no offset — THE trigger
_NAIVE_UNTIL  = "2026-12-31"
_AWARE_SINCE  = "2026-09-01T00:00:00+00:00"
_AWARE_UNTIL  = "2026-12-31T23:59:59+00:00"


def _skill_evidence(snaps):
    from Orchestration.decision_copilot import DecisionCopilotSkill
    return DecisionCopilotSkill(_JRepo([]), _PRepo(snaps))


def _skill_patterns(entries):
    from Orchestration.decision_copilot import DecisionCopilotSkill
    return DecisionCopilotSkill(_JRepo(entries))


def _no_exception(fn) -> bool:
    """Return True if fn() returns without raising. False if it raises."""
    try:
        fn()
        return True
    except Exception:
        return False


def _result(fn):
    """Return SkillResult if fn() returns normally; None if it raises."""
    try:
        return fn()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase A — RED (these FAIL pre-fix, GREEN post-fix)
# ---------------------------------------------------------------------------

def run_phase_a():
    print("\n[Phase A] Bug reproduction — FAIL pre-fix, PASS post-fix")

    print("\n[A1] evidence: naive since + aware row INSIDE range → must not crash")
    # Pre-fix: TypeError at L183 escapes; _result() returns None.
    # Post-fix: returns SkillResult(success=True, snapshot_count=1).
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        _NAIVE_SINCE, None))
    check(r is not None, "A1: returns SkillResult (not None/crash)")
    check(r is not None and r.success is True, "A1: success=True (row in range)")
    check(r is not None and r.success and r.output.get("snapshot_count") == 1,
          "A1: snapshot_count==1")

    print("\n[A2] evidence: naive until + aware row INSIDE range → must not crash")
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        None, _NAIVE_UNTIL))
    check(r is not None, "A2: returns SkillResult (not None/crash)")
    check(r is not None and r.success is True, "A2: success=True (row in range)")
    check(r is not None and r.success and r.output.get("snapshot_count") == 1,
          "A2: snapshot_count==1")

    print("\n[A3] evidence: mixed bounds (naive since, aware until) → must not crash")
    # Pre-fix: TypeError at L168 (comparing naive since_dt > aware until_dt).
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        _NAIVE_SINCE, _AWARE_UNTIL))
    check(r is not None, "A3: returns SkillResult (not None/crash)")
    check(r is not None and r.success is True, "A3: success=True (row in range)")

    print("\n[A4] patterns: naive bounds + aware decided_at INSIDE range → must return SUCCESS")
    # Pre-fix (Class B): TypeError at L101 swallowed by except → row skipped →
    #   filtered_entries empty → INSUFFICIENT_DATA.  entry_count is lost.
    # Post-fix: SUCCESS, entry_count==1.
    r = _result(lambda: _skill_patterns([_Entry(_AWARE_INSIDE)]).analyze_historical_patterns(
        "ACC", _NAIVE_SINCE, _NAIVE_UNTIL))
    check(r is not None, "A4: returns SkillResult (not None/crash)")
    check(r is not None and r.success is True,
          "A4: success=True (row should be in range)")
    check(r is not None and r.success and (r.output or {}).get("entry_count") == 1,
          "A4: entry_count==1 (not silently dropped)")

    print("\n[A5] evidence: naive since > naive until → DATA_ERROR (not crash)")
    # Pre-fix: TypeError at L168 (naive since_dt > aware until_dt cannot be compared
    #   when until is aware).  Here both are naive so the comparison works, but
    #   since > until — the guard at L168 should catch it cleanly.
    # Actual pre-fix issue: the guard at L168 compares since_dt > until_dt where
    #   since_dt is naive but until_dt is *also* naive → same-type comparison works →
    #   returns DATA_ERROR cleanly.  So A5 should PASS both pre and post-fix.
    # We include it anyway because it verifies the guard still works post-fix
    # when both become aware (same semantics, just different types).
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        _NAIVE_UNTIL, _NAIVE_SINCE))  # since="2026-12-31" > until="2026-09-01"
    check(r is not None and r.success is False and r.error == "DATA_ERROR",
          "A5: since>until → DATA_ERROR (not crash)")


# ---------------------------------------------------------------------------
# Phase C — Regression (must PASS both pre- and post-fix)
# ---------------------------------------------------------------------------

def run_phase_c():
    print("\n[Phase C] Regression — must PASS both before and after fix")

    print("\n[C1] Unparseable bound → DATA_ERROR (not TypeError)")
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        "not-a-date", None))
    check(r is not None and r.success is False and r.error == "DATA_ERROR",
          "C1: evidence 'not-a-date' → DATA_ERROR")

    r = _result(lambda: _skill_patterns([_Entry(_NAIVE_INSIDE)]).analyze_historical_patterns(
        "ACC", "not-a-date", _NAIVE_UNTIL))
    check(r is not None and r.success is False and r.error == "DATA_ERROR",
          "C1: patterns 'not-a-date' → DATA_ERROR")

    print("\n[C2] evidence: no bounds → SUCCESS (existing Gate 3 manual run)")
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE), _Snap(_AWARE_OUTSIDE)])
                .analyze_evidence_profile())
    check(r is not None and r.success is True, "C2: no bounds → SUCCESS")
    check(r is not None and r.success and r.output.get("snapshot_count") == 2,
          "C2: snapshot_count==2 (all rows returned with no filter)")

    print("\n[C3] patterns: naive bounds + NAIVE decided_at (existing test fixtures)")
    # All existing Gate 1/2 fixtures use naive+naive. Must still work.
    r = _result(lambda: _skill_patterns([
        _Entry(_NAIVE_INSIDE), _Entry(_NAIVE_INSIDE)
    ]).analyze_historical_patterns("ACC", _NAIVE_SINCE, _NAIVE_UNTIL))
    check(r is not None and r.success is True, "C3: naive+naive → SUCCESS (existing fixtures)")
    check(r is not None and r.success and r.output.get("entry_count") == 2,
          "C3: entry_count==2")

    print("\n[C4] since > until → DATA_ERROR (aware+aware)")
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        _AWARE_UNTIL, _AWARE_SINCE))
    check(r is not None and r.success is False and r.error == "DATA_ERROR",
          "C4: aware since>until → DATA_ERROR")

    print("\n[C5] evidence: output[\"since\"] echoes normalized aware value")
    # Post-fix: naive "2026-09-01" becomes "2026-09-01T00:00:00+00:00" in output.
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        _NAIVE_SINCE, None))
    if r is not None and r.success and r.output:
        echoed = r.output.get("since", "")
        check("+00:00" in echoed or "UTC" in echoed or echoed.endswith("Z"),
              f"C5: output[\"since\"] is aware/normalized (got {echoed!r})")
    else:
        check(False, "C5: cannot check — result was not SUCCESS")

    print("\n[C6] Malformed inputs never escape as unhandled exception")
    bad_inputs = [
        ("", None), (None, None),           # None is allowed (no filter)
        ("2026-13-45", None),               # month 13
        ("null", None),                     # JSON-ish string
        (0, None), (True, None),            # wrong type
        ([], None), ({}, None),             # collections
        ("2026-09-01T", None),              # truncated ISO
        ("2026-09-01 00:00:00", None),      # space separator (NOT ISO in Python < 3.11 str)
        (_NAIVE_SINCE, "bad-until"),        # one good, one bad
        ("bad-since", _NAIVE_UNTIL),        # one bad, one good
    ]
    for since_val, until_val in bad_inputs:
        returned = _no_exception(
            lambda s=since_val, u=until_val:
                _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(s, u)
        )
        label = f"C6: evidence({since_val!r}, {until_val!r}) returns (no crash)"
        # None since/until is valid (no filter); everything else should be DATA_ERROR or SUCCESS
        check(returned, label)

    # same for patterns
    bad_pattern_inputs = [
        ("ACC", "2026-13-45", _NAIVE_UNTIL),
        ("ACC", "null", _NAIVE_UNTIL),
        ("ACC", _NAIVE_SINCE, "bad-until"),
        ("ACC", 0, _NAIVE_UNTIL),
    ]
    for acc, since_val, until_val in bad_pattern_inputs:
        returned = _no_exception(
            lambda a=acc, s=since_val, u=until_val:
                _skill_patterns([_Entry(_NAIVE_INSIDE)]).analyze_historical_patterns(a, s, u)
        )
        check(returned, f"C6: patterns({since_val!r}, {until_val!r}) returns (no crash)")

    print("\n[C7] aware bounds + aware rows (workaround confirmed still works)")
    r = _result(lambda: _skill_evidence([_Snap(_AWARE_INSIDE)]).analyze_evidence_profile(
        _AWARE_SINCE, _AWARE_UNTIL))
    check(r is not None and r.success is True and r.output.get("snapshot_count") == 1,
          "C7: evidence aware+aware → SUCCESS snapshot_count==1")

    r = _result(lambda: _skill_patterns([_Entry(_AWARE_INSIDE)]).analyze_historical_patterns(
        "ACC", _AWARE_SINCE, _AWARE_UNTIL))
    check(r is not None and r.success is True and r.output.get("entry_count") == 1,
          "C7: patterns aware+aware → SUCCESS entry_count==1")


# ---------------------------------------------------------------------------
# Phase D — Boundary proof (source inspection)
# ---------------------------------------------------------------------------

def run_phase_d():
    print("\n[Phase D] Boundary proof — source inspection")

    src = (ROOT / "Orchestration" / "decision_copilot.py").read_text(encoding="utf-8")

    print("\n[D1] Helper is pure — no write-SQL, no broker/engine/permission refs")
    # Find the helper block
    helper_start = src.find("def _parse_utc_aware")
    if helper_start == -1:
        check(False, "D1: _parse_utc_aware helper exists in source")
        helper_src = ""
    else:
        check(True, "D1: _parse_utc_aware helper exists in source")
        # Helper ends at the next top-level def or class (not indented)
        helper_end = len(src)
        for kw in ["def ", "class "]:
            idx = src.find("\n" + kw, helper_start + 1)
            if idx != -1 and idx < helper_end:
                helper_end = idx
        helper_src = src[helper_start:helper_end]
    banned = ["INSERT", "UPDATE", "DELETE", "DROP",
              "submit_order", "authorize_tool", "PermissionContext",
              "RankingEngine", "PaperTradingEngine", "Broker"]
    for token in banned:
        check(token not in helper_src,
              f"D1: helper does not reference {token!r}")

    print("\n[D2] Only new import is 'timezone' from stdlib 'datetime'")
    import_line = None
    for line in src.splitlines():
        if "from datetime import" in line:
            import_line = line
            break
    check(import_line is not None, "D2: 'from datetime import' line present")
    check(import_line is not None and "timezone" in import_line,
          "D2: 'timezone' in datetime import")
    # No new third-party import
    new_third_party = [
        ln for ln in src.splitlines()
        if ln.startswith("import ") or ln.startswith("from ")
        if "pytz" in ln or "dateutil" in ln or "arrow" in ln or "pendulum" in ln
    ]
    check(len(new_third_party) == 0,
          "D2: no new third-party timezone library imported")

    print("\n[D3] Existing imports still present (nothing orphaned)")
    for name in ["json", "Any", "Optional", "defaultdict",
                 "BaseSkill", "SkillResult",
                 "JournalRepository", "PerformanceRepository",
                 "JournalEntry", "RankingSnapshot"]:
        check(name in src, f"D3: {name!r} still imported/used in source")

    print("\n[D4] Helper is module-level and private (_-prefixed)")
    check("def _parse_utc_aware" in src, "D4: helper is private (_-prefixed)")
    # Must appear BEFORE the class definition (module-level)
    helper_pos = src.find("def _parse_utc_aware")
    class_pos = src.find("class DecisionCopilotSkill")
    check(helper_pos != -1 and class_pos != -1 and helper_pos < class_pos,
          "D4: helper defined before class (module-level)")

    print("\n[D5] All fromisoformat calls consolidated into helper (helper body only)")
    iso_hits = [
        (i + 1, ln.strip())
        for i, ln in enumerate(src.splitlines())
        if "fromisoformat" in ln
    ]
    print(f"       fromisoformat lines: {len(iso_hits)}")
    for lineno, text in iso_hits:
        print(f"         L{lineno}: {text}")
    # Post-fix: only 1 (inside the helper).  Pre-fix: 7.
    check(len(iso_hits) == 1,
          f"D5: exactly 1 fromisoformat call (in helper body); found {len(iso_hits)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_all():
    run_phase_a()
    run_phase_c()
    run_phase_d()

    print(f"\n{'='*60}")
    print(f"Total: {_PASS + _FAIL}, Passed: {_PASS}, Failed: {_FAIL}")
    if _FAILURES:
        print("\nFailed cases:")
        for f in _FAILURES:
            print(f"  FAIL - {f}")
    print("=" * 60)
    return _FAIL == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
