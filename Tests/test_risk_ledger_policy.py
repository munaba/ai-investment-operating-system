"""Standalone regression checks for
``Business.risk_ledger_policy.RiskLedgerPolicy``.

Covers Phase C ("Personal Risk Ledger + Decision Journal") gate rules:

* SKIP/WAIT always resolve ACCEPTED regardless of limits/stats;
* no limits configured -> RISK_REJECTED;
* allowed-symbols allowlist enforcement;
* only a SUCCESS brief with a real priced plan may be TAKEn;
* max risk per trade (percent of reference capital) enforcement;
* max daily loss enforcement;
* max trades/day enforcement;
* loss-streak cooldown enforcement;
* a TAKE that violates nothing is ACCEPTED;
* this policy is pure -- no Database/Service dependency, deterministic.

Run directly with ``python Tests/test_risk_ledger_policy.py`` -- no
external test framework required, matching
``test_decision_brief_policy.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Business.risk_ledger_policy import (  # noqa: E402
    RiskLedgerPolicy,
    RiskLedgerStats,
    STATUS_ACCEPTED,
    STATUS_RISK_REJECTED,
)
from Database.models import DecisionBrief, RiskLimits  # noqa: E402

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


def _brief(**overrides) -> DecisionBrief:
    defaults = dict(
        brief_id=1,
        symbol="BBCA",
        generated_at="2026-08-22T09:00:00+00:00",
        status="SUCCESS",
        source_snapshot_id=None,
        reason=None,
        entry_price=9000.0,
        stop_loss_price=8820.0,
        take_profit_price=9360.0,
        risk_amount=1000.0,
        position_size=555.5,
        risk_reward_ratio=2.0,
    )
    defaults.update(overrides)
    return DecisionBrief(**defaults)


def _limits(**overrides) -> RiskLimits:
    defaults = dict(
        id="default",
        reference_capital=100000.0,
        max_risk_per_trade_percent=2.0,  # -> max_risk_dollars = 2000.0
        max_daily_loss=5000.0,
        max_trades_per_day=5,
        loss_streak_cooldown=3,
        allowed_symbols=None,
        updated_at="2026-08-22T08:00:00+00:00",
    )
    defaults.update(overrides)
    return RiskLimits(**defaults)


def _stats(**overrides) -> RiskLedgerStats:
    defaults = dict(trades_taken_today=0, realized_loss_today=0.0, current_loss_streak=0)
    defaults.update(overrides)
    return RiskLedgerStats(**defaults)


def scenario_skip_and_wait_always_accepted():
    print("\n[Scenario 1] SKIP/WAIT always resolve ACCEPTED regardless of limits/stats")
    policy = RiskLedgerPolicy()
    brief = _brief(status="DATA_STALE", entry_price=None, stop_loss_price=None, risk_amount=None)
    # Deliberately hostile limits/stats -- must not matter for SKIP/WAIT.
    limits = _limits(max_trades_per_day=0, loss_streak_cooldown=0)
    stats = _stats(trades_taken_today=99, current_loss_streak=99, realized_loss_today=999999.0)

    skip_result = policy.evaluate("SKIP", brief, limits, stats)
    wait_result = policy.evaluate("WAIT", brief, limits, stats)
    skip_result_no_limits = policy.evaluate("SKIP", brief, None, stats)

    check(skip_result.status == STATUS_ACCEPTED, "SKIP resolves ACCEPTED even under hostile limits/stats")
    check(wait_result.status == STATUS_ACCEPTED, "WAIT resolves ACCEPTED even under hostile limits/stats")
    check(skip_result.reason is None, "SKIP has no rejection reason")
    check(skip_result_no_limits.status == STATUS_ACCEPTED, "SKIP resolves ACCEPTED even with no limits configured")


def scenario_no_limits_configured_rejects_take():
    print("\n[Scenario 2] TAKE with no RiskLimits configured -> RISK_REJECTED")
    policy = RiskLedgerPolicy()
    brief = _brief()
    result = policy.evaluate("TAKE", brief, None, _stats())
    check(result.status == STATUS_RISK_REJECTED, "TAKE with limits=None is RISK_REJECTED")
    check(result.reason is not None and "risk limits" in result.reason.lower(), "reason mentions missing risk limits")


def scenario_allowed_symbols_allowlist():
    print("\n[Scenario 3] allowed_symbols allowlist enforcement")
    policy = RiskLedgerPolicy()
    limits = _limits(allowed_symbols=["TLKM", "BMRI"])
    brief = _brief(symbol="BBCA")
    result = policy.evaluate("TAKE", brief, limits, _stats())
    check(result.status == STATUS_RISK_REJECTED, "TAKE on a symbol outside the allowlist is RISK_REJECTED")
    check("BBCA" in (result.reason or ""), "reason names the rejected symbol")

    allowed_brief = _brief(symbol="TLKM")
    allowed_result = policy.evaluate("TAKE", allowed_brief, limits, _stats())
    check(allowed_result.status == STATUS_ACCEPTED, "TAKE on an allowlisted symbol is not rejected by the allowlist rule")


def scenario_only_success_brief_with_real_plan_may_be_taken():
    print("\n[Scenario 4] only a SUCCESS brief with a real priced plan may be TAKEn")
    policy = RiskLedgerPolicy()
    limits = _limits()

    non_success = _brief(status="POLICY_BLOCKED", entry_price=None, stop_loss_price=None, risk_amount=None)
    result_non_success = policy.evaluate("TAKE", non_success, limits, _stats())
    check(result_non_success.status == STATUS_RISK_REJECTED, "TAKE against a non-SUCCESS brief is RISK_REJECTED")

    missing_entry = _brief(entry_price=None)
    result_missing_entry = policy.evaluate("TAKE", missing_entry, limits, _stats())
    check(result_missing_entry.status == STATUS_RISK_REJECTED, "TAKE against a brief missing entry_price is RISK_REJECTED")

    missing_stop = _brief(stop_loss_price=None)
    result_missing_stop = policy.evaluate("TAKE", missing_stop, limits, _stats())
    check(result_missing_stop.status == STATUS_RISK_REJECTED, "TAKE against a brief missing stop_loss_price is RISK_REJECTED")

    zero_risk = _brief(risk_amount=0.0)
    result_zero_risk = policy.evaluate("TAKE", zero_risk, limits, _stats())
    check(result_zero_risk.status == STATUS_RISK_REJECTED, "TAKE against a brief with non-positive risk_amount is RISK_REJECTED")


def scenario_max_risk_per_trade():
    print("\n[Scenario 5] max risk per trade (percent of reference capital) enforcement")
    policy = RiskLedgerPolicy()
    # reference_capital=100000, max_risk_per_trade_percent=2.0 -> max_risk_dollars=2000.0
    limits = _limits(reference_capital=100000.0, max_risk_per_trade_percent=2.0)

    within_limit = _brief(risk_amount=1999.0)
    result_within = policy.evaluate("TAKE", within_limit, limits, _stats())
    check(result_within.status == STATUS_ACCEPTED, "risk_amount just under the dollar cap is ACCEPTED")

    at_limit_brief = _brief(risk_amount=2000.0)
    result_at_limit = policy.evaluate("TAKE", at_limit_brief, limits, _stats())
    check(result_at_limit.status == STATUS_ACCEPTED, "risk_amount exactly at the dollar cap is ACCEPTED (not strictly greater)")

    over_limit = _brief(risk_amount=2000.01)
    result_over = policy.evaluate("TAKE", over_limit, limits, _stats())
    check(result_over.status == STATUS_RISK_REJECTED, "risk_amount over the dollar cap is RISK_REJECTED")
    check(result_over.reason is not None and "max risk per trade" in result_over.reason.lower(), "reason names the max-risk-per-trade rule")


def scenario_max_daily_loss():
    print("\n[Scenario 6] max daily loss enforcement")
    policy = RiskLedgerPolicy()
    limits = _limits(max_daily_loss=5000.0)
    brief = _brief()

    under = policy.evaluate("TAKE", brief, limits, _stats(realized_loss_today=4999.99))
    check(under.status == STATUS_ACCEPTED, "realized loss just under the daily cap does not block a TAKE")

    at_cap = policy.evaluate("TAKE", brief, limits, _stats(realized_loss_today=5000.0))
    check(at_cap.status == STATUS_RISK_REJECTED, "realized loss at the daily cap blocks a TAKE")

    over_cap = policy.evaluate("TAKE", brief, limits, _stats(realized_loss_today=5000.01))
    check(over_cap.status == STATUS_RISK_REJECTED, "realized loss over the daily cap blocks a TAKE")
    check(over_cap.reason is not None and "daily loss" in over_cap.reason.lower(), "reason names the max-daily-loss rule")


def scenario_max_trades_per_day():
    print("\n[Scenario 7] max trades/day enforcement")
    policy = RiskLedgerPolicy()
    limits = _limits(max_trades_per_day=3)
    brief = _brief()

    under = policy.evaluate("TAKE", brief, limits, _stats(trades_taken_today=2))
    check(under.status == STATUS_ACCEPTED, "trades_taken_today under the daily cap does not block a TAKE")

    at_cap = policy.evaluate("TAKE", brief, limits, _stats(trades_taken_today=3))
    check(at_cap.status == STATUS_RISK_REJECTED, "trades_taken_today at the daily cap blocks a TAKE")

    over_cap = policy.evaluate("TAKE", brief, limits, _stats(trades_taken_today=4))
    check(over_cap.status == STATUS_RISK_REJECTED, "trades_taken_today over the daily cap blocks a TAKE")
    check(over_cap.reason is not None and "trades" in over_cap.reason.lower(), "reason names the max-trades-per-day rule")


def scenario_loss_streak_cooldown():
    print("\n[Scenario 8] loss-streak cooldown enforcement")
    policy = RiskLedgerPolicy()
    limits = _limits(loss_streak_cooldown=3)
    brief = _brief()

    under = policy.evaluate("TAKE", brief, limits, _stats(current_loss_streak=2))
    check(under.status == STATUS_ACCEPTED, "loss streak under the cooldown threshold does not block a TAKE")

    at_threshold = policy.evaluate("TAKE", brief, limits, _stats(current_loss_streak=3))
    check(at_threshold.status == STATUS_RISK_REJECTED, "loss streak at the cooldown threshold blocks a TAKE")

    over_threshold = policy.evaluate("TAKE", brief, limits, _stats(current_loss_streak=4))
    check(over_threshold.status == STATUS_RISK_REJECTED, "loss streak over the cooldown threshold blocks a TAKE")
    check(over_threshold.reason is not None and "cooldown" in over_threshold.reason.lower(), "reason names the loss-streak cooldown rule")

    disabled = _limits(loss_streak_cooldown=0)
    disabled_result = policy.evaluate("TAKE", brief, disabled, _stats(current_loss_streak=10))
    check(disabled_result.status == STATUS_ACCEPTED, "loss_streak_cooldown=0 disables the cooldown rule entirely")


def scenario_clean_take_is_accepted():
    print("\n[Scenario 9] a TAKE that violates nothing is ACCEPTED")
    policy = RiskLedgerPolicy()
    limits = _limits()
    brief = _brief()
    result = policy.evaluate("TAKE", brief, limits, _stats())
    check(result.status == STATUS_ACCEPTED, "a fully compliant TAKE is ACCEPTED")
    check(result.reason is None, "ACCEPTED carries no rejection reason")


def scenario_policy_is_pure_and_stateless():
    print("\n[Scenario 10] RiskLedgerPolicy has no Database/Service dependency, deterministic")
    policy = RiskLedgerPolicy()
    brief = _brief()
    limits = _limits()
    stats = _stats()
    first = policy.evaluate("TAKE", brief, limits, stats)
    second = policy.evaluate("TAKE", brief, limits, stats)
    check(first.status == second.status, "same inputs always produce the same status (deterministic)")
    check(first.reason == second.reason, "same inputs always produce the same reason (deterministic)")
    check(not hasattr(policy, "_database_manager"), "policy holds no database_manager attribute")
    check(not hasattr(policy, "_repository"), "policy holds no repository attribute")


def main() -> int:
    scenario_skip_and_wait_always_accepted()
    scenario_no_limits_configured_rejects_take()
    scenario_allowed_symbols_allowlist()
    scenario_only_success_brief_with_real_plan_may_be_taken()
    scenario_max_risk_per_trade()
    scenario_max_daily_loss()
    scenario_max_trades_per_day()
    scenario_loss_streak_cooldown()
    scenario_clean_take_is_accepted()
    scenario_policy_is_pure_and_stateless()

    print("\n" + "=" * 60)
    print(f"RISK LEDGER POLICY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())