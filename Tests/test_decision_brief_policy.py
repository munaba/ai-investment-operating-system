"""Standalone regression checks for
``Business.decision_brief_policy.DecisionBriefPolicy``.

Covers Phase B ("Decision Copilot") gating logic:

* no snapshot -> INSUFFICIENT_DATA;
* status="error" snapshot -> DATA_ERROR;
* unparseable scan_time -> DATA_ERROR;
* stale snapshot -> DATA_STALE;
* missing recommendation/confidence -> INSUFFICIENT_DATA;
* non-BUY recommendation -> NO_TRADE;
* fresh BUY snapshot -> gate passes (blocked_status is None);
* pure/stateless: same inputs always produce the same result, no I/O.

Run directly with ``python Tests/test_decision_brief_policy.py`` --
no external test framework required, matching
``test_snapshot_repository.py``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.decision_brief_policy import DecisionBriefPolicy  # noqa: E402
from Database.models import RankingSnapshot  # noqa: E402

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


_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def _fresh_buy_snapshot() -> RankingSnapshot:
    return RankingSnapshot(
        snapshot_id=1,
        scan_time=(_NOW - timedelta(hours=1)).isoformat(),
        symbol="BBCA",
        recommendation="BUY",
        confidence="HIGH",
        priority=1,
        rank=1,
        status="success",
    )


def scenario_no_snapshot_is_insufficient_data():
    print("\n[Scenario 1] no snapshot -> INSUFFICIENT_DATA")
    policy = DecisionBriefPolicy()
    result = policy.evaluate(None, now=_NOW)
    check(result.blocked_status == "INSUFFICIENT_DATA", "None snapshot resolves to INSUFFICIENT_DATA")
    check(result.reason is not None, "INSUFFICIENT_DATA carries a human-readable reason")


def scenario_error_status_is_data_error():
    print("\n[Scenario 2] snapshot status='error' -> DATA_ERROR")
    policy = DecisionBriefPolicy()
    snapshot = RankingSnapshot(
        snapshot_id=2,
        scan_time=(_NOW - timedelta(hours=1)).isoformat(),
        symbol="TLKM",
        status="error",
        error_message="Symbol excluded: insufficient history.",
    )
    result = policy.evaluate(snapshot, now=_NOW)
    check(result.blocked_status == "DATA_ERROR", "error-status snapshot resolves to DATA_ERROR")
    check(
        result.reason == "Symbol excluded: insufficient history.",
        "DATA_ERROR reason forwards the snapshot's real error_message verbatim",
    )


def scenario_unparseable_scan_time_is_data_error():
    print("\n[Scenario 3] unparseable scan_time -> DATA_ERROR")
    policy = DecisionBriefPolicy()
    snapshot = RankingSnapshot(
        snapshot_id=3,
        scan_time="not-a-timestamp",
        symbol="ASII",
        recommendation="BUY",
        confidence="HIGH",
        priority=1,
        rank=1,
        status="success",
    )
    result = policy.evaluate(snapshot, now=_NOW)
    check(result.blocked_status == "DATA_ERROR", "unparseable scan_time resolves to DATA_ERROR")


def scenario_stale_snapshot_is_data_stale():
    print("\n[Scenario 4] snapshot older than stale_after -> DATA_STALE")
    policy = DecisionBriefPolicy()
    snapshot = RankingSnapshot(
        snapshot_id=4,
        scan_time=(_NOW - timedelta(hours=12)).isoformat(),
        symbol="BBCA",
        recommendation="BUY",
        confidence="HIGH",
        priority=1,
        rank=1,
        status="success",
    )
    result = policy.evaluate(snapshot, now=_NOW, stale_after=timedelta(hours=6))
    check(result.blocked_status == "DATA_STALE", "12h-old snapshot with a 6h staleness window resolves to DATA_STALE")


def scenario_missing_recommendation_is_insufficient_data():
    print("\n[Scenario 5] snapshot missing recommendation/confidence -> INSUFFICIENT_DATA")
    policy = DecisionBriefPolicy()
    snapshot = RankingSnapshot(
        snapshot_id=5,
        scan_time=(_NOW - timedelta(hours=1)).isoformat(),
        symbol="BBCA",
        recommendation=None,
        confidence=None,
        status="success",
    )
    result = policy.evaluate(snapshot, now=_NOW)
    check(result.blocked_status == "INSUFFICIENT_DATA", "missing recommendation/confidence resolves to INSUFFICIENT_DATA")


def scenario_non_buy_recommendation_is_no_trade():
    print("\n[Scenario 6] non-BUY recommendation -> NO_TRADE")
    policy = DecisionBriefPolicy()
    for rec in ("SELL", "HOLD"):
        snapshot = RankingSnapshot(
            snapshot_id=6,
            scan_time=(_NOW - timedelta(hours=1)).isoformat(),
            symbol="BBCA",
            recommendation=rec,
            confidence="HIGH",
            priority=1,
            rank=1,
            status="success",
        )
        result = policy.evaluate(snapshot, now=_NOW)
        check(result.blocked_status == "NO_TRADE", f"recommendation={rec!r} resolves to NO_TRADE")


def scenario_fresh_buy_snapshot_passes_gate():
    print("\n[Scenario 7] fresh BUY snapshot -> gate passes (blocked_status is None)")
    policy = DecisionBriefPolicy()
    result = policy.evaluate(_fresh_buy_snapshot(), now=_NOW)
    check(result.blocked_status is None, "fresh BUY snapshot is not blocked by the policy gate")
    check(result.reason is None, "no reason is attached when the gate passes")


def scenario_deterministic_and_pure():
    print("\n[Scenario 8] same inputs always produce the same result (pure/stateless)")
    policy = DecisionBriefPolicy()
    snapshot = _fresh_buy_snapshot()
    first = policy.evaluate(snapshot, now=_NOW)
    second = policy.evaluate(snapshot, now=_NOW)
    check(first.blocked_status == second.blocked_status, "evaluate() is deterministic across repeated calls")
    check(
        not vars(policy),
        "DecisionBriefPolicy holds no instance state (empty __dict__)",
    )


def main() -> int:
    scenario_no_snapshot_is_insufficient_data()
    scenario_error_status_is_data_error()
    scenario_unparseable_scan_time_is_data_error()
    scenario_stale_snapshot_is_data_stale()
    scenario_missing_recommendation_is_insufficient_data()
    scenario_non_buy_recommendation_is_no_trade()
    scenario_fresh_buy_snapshot_passes_gate()
    scenario_deterministic_and_pure()

    print("\n" + "=" * 60)
    print(f"DECISION BRIEF POLICY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())