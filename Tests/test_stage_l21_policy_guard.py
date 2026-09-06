"""
Stage L21 proof suite -- Policy Guard (Stage L21, additive component).

Scope: dedicated regression suite for
``Orchestration.policy_guard.PolicyGuardError``,
``Orchestration.policy_guard.PolicyGuardResult``, and
``Orchestration.policy_guard.PolicyGuard`` only. No Composition Root
wiring assertions beyond a plain construction/attribute smoke check, no
automatic invocation from StockAgent/RuntimeAnalysisPipeline/DecisionPolicy,
no real trading logic -- all explicitly out of scope for L21.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py``, ``test_stage_l19_decision_engine.py``,
and ``test_stage_l20_decision_policy.py``: a global pass/fail counter,
plain fixtures, and a ``main()`` runner. No ``unittest`` module is used,
matching the existing convention.

Invariant coverage:
    I1  -- a policy result with allow_entry=True, allow_exit=False,
           position_size in [0.0, 1.0], and a recognized risk_level is
           approved with zero violations.
    I2  -- allow_entry=True and allow_exit=True together produces a
           conflicting entry/exit violation and approved=False.
    I3  -- a position_size outside [0.0, 1.0] (above 1.0) produces a
           position_size violation and approved=False.
    I4  -- a position_size outside [0.0, 1.0] (below 0.0) produces a
           position_size violation and approved=False.
    I5  -- position_size boundary values 0.0 and 1.0 are both valid
           (no violation) on their own.
    I6  -- an unrecognized risk_level produces a risk_level violation
           and approved=False.
    I7  -- more than one violation can be reported simultaneously for a
           single policy result.
    I8  -- action, risk_level, and position_size on the input policy
           result are preserved unchanged on the returned
           PolicyGuardResult.
    I9  -- notes contains the action name for both approved and
           rejected results.
    I10 -- a policy result missing a required attribute raises
           PolicyGuardError (not AttributeError).
    I11 -- PolicyGuardResult is a frozen dataclass.
    I12 -- PolicyGuardError subclasses Core.exceptions.AgentError.
    I13 -- PolicyGuard holds no instance attributes (stateless) and is
           deterministic across repeated calls with the same input.
    I14 -- Core.composition_root.build_application() exposes a
           PolicyGuard instance on ApplicationGraph.policy_guard.
"""

from __future__ import annotations

import dataclasses
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.policy_guard import (
    PolicyGuard,
    PolicyGuardError,
    PolicyGuardResult,
)

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _FakePolicyResult:
    """Minimal stand-in for Orchestration.decision_policy.DecisionPolicyResult.

    PolicyGuard.evaluate() only reads ``action``, ``position_size``,
    ``allow_entry``, ``allow_exit``, and ``risk_level`` off its
    argument, so a lightweight plain object is sufficient and keeps
    this suite independent of DecisionPolicy.
    """

    def __init__(
        self,
        action: str = "BUY",
        position_size: float = 1.0,
        allow_entry: bool = True,
        allow_exit: bool = False,
        risk_level: str = "NORMAL",
    ) -> None:
        self.action = action
        self.position_size = position_size
        self.allow_entry = allow_entry
        self.allow_exit = allow_exit
        self.risk_level = risk_level


class _PolicyResultMissingField:
    """Stand-in policy result object deliberately missing 'risk_level'."""

    def __init__(self) -> None:
        self.action = "BUY"
        self.position_size = 1.0
        self.allow_entry = True
        self.allow_exit = False


# ---------------------------------------------------------------------------
# Group 1 -- PolicyGuardError
# ---------------------------------------------------------------------------
def scenario_policy_guard_error_is_agent_error() -> None:
    check(
        issubclass(PolicyGuardError, AgentError),
        "I12: PolicyGuardError subclasses Core.exceptions.AgentError, "
        "same convention as DecisionPolicyError/DecisionEngineError/"
        "ReflectionError",
    )
    err = PolicyGuardError("boom")
    check(isinstance(err, Exception), "PolicyGuardError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- PolicyGuardResult (value shape) -- I11
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = PolicyGuard().evaluate(_FakePolicyResult())

    check(dataclasses.is_dataclass(result), "PolicyGuardResult is a dataclass")

    frozen = False
    try:
        result.approved = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I11: PolicyGuardResult is frozen -- field reassignment raises "
        "FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(PolicyGuardResult)}
    check(
        field_names
        == {
            "approved",
            "action",
            "risk_level",
            "position_size",
            "violations",
            "notes",
        },
        "PolicyGuardResult declares exactly six fields (approved, action, "
        "risk_level, position_size, violations, notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- valid policy result -- I1
# ---------------------------------------------------------------------------
def scenario_valid_buy_is_approved_with_no_violations() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(action="BUY", position_size=1.0, allow_entry=True, allow_exit=False, risk_level="NORMAL")
    )
    check(
        result.approved is True and result.violations == (),
        "I1: a valid BUY policy result is approved with zero violations",
    )


def scenario_valid_hold_is_approved_with_no_violations() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(action="HOLD", position_size=0.5, allow_entry=False, allow_exit=False, risk_level="LOW")
    )
    check(
        result.approved is True and result.violations == (),
        "I1: a valid HOLD policy result is approved with zero violations",
    )


def scenario_valid_sell_is_approved_with_no_violations() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(action="SELL", position_size=0.0, allow_entry=False, allow_exit=True, risk_level="HIGH")
    )
    check(
        result.approved is True and result.violations == (),
        "I1: a valid SELL policy result is approved with zero violations",
    )


# ---------------------------------------------------------------------------
# Group 4 -- conflicting entry/exit flags -- I2
# ---------------------------------------------------------------------------
def scenario_conflicting_entry_exit_is_rejected() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(allow_entry=True, allow_exit=True)
    )
    check(
        result.approved is False and len(result.violations) == 1,
        "I2: allow_entry=True and allow_exit=True together produces "
        "exactly one violation and approved=False",
    )


def scenario_conflicting_entry_exit_violation_mentions_flags() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(allow_entry=True, allow_exit=True)
    )
    check(
        any("allow_entry" in v and "allow_exit" in v for v in result.violations),
        "I2: the conflicting entry/exit violation message references "
        "both allow_entry and allow_exit",
    )


# ---------------------------------------------------------------------------
# Group 5 -- position_size out of range -- I3, I4, I5
# ---------------------------------------------------------------------------
def scenario_position_size_above_one_is_rejected() -> None:
    result = PolicyGuard().evaluate(_FakePolicyResult(position_size=1.5))
    check(
        result.approved is False
        and any("position_size" in v for v in result.violations),
        "I3: position_size=1.5 (above 1.0) produces a position_size "
        "violation and approved=False",
    )


def scenario_position_size_below_zero_is_rejected() -> None:
    result = PolicyGuard().evaluate(_FakePolicyResult(position_size=-0.1))
    check(
        result.approved is False
        and any("position_size" in v for v in result.violations),
        "I4: position_size=-0.1 (below 0.0) produces a position_size "
        "violation and approved=False",
    )


def scenario_position_size_boundary_zero_is_valid() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(position_size=0.0, allow_entry=False, allow_exit=True)
    )
    check(
        not any("position_size" in v for v in result.violations),
        "I5: position_size=0.0 (lower boundary) alone produces no "
        "position_size violation",
    )


def scenario_position_size_boundary_one_is_valid() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(position_size=1.0, allow_entry=True, allow_exit=False)
    )
    check(
        not any("position_size" in v for v in result.violations),
        "I5: position_size=1.0 (upper boundary) alone produces no "
        "position_size violation",
    )


# ---------------------------------------------------------------------------
# Group 6 -- unrecognized risk_level -- I6
# ---------------------------------------------------------------------------
def scenario_unrecognized_risk_level_is_rejected() -> None:
    result = PolicyGuard().evaluate(_FakePolicyResult(risk_level="EXTREME"))
    check(
        result.approved is False
        and any("risk_level" in v for v in result.violations),
        "I6: risk_level='EXTREME' (unrecognized) produces a risk_level "
        "violation and approved=False",
    )


def scenario_lowercase_risk_level_is_rejected() -> None:
    # Risk-level matching is case-sensitive -- 'normal' is not the same
    # value as 'NORMAL', and must not silently pass through.
    result = PolicyGuard().evaluate(_FakePolicyResult(risk_level="normal"))
    check(
        result.approved is False
        and any("risk_level" in v for v in result.violations),
        "I6: risk_level='normal' (lowercase) produces a risk_level "
        "violation, confirming case-sensitive matching",
    )


# ---------------------------------------------------------------------------
# Group 7 -- multiple simultaneous violations -- I7
# ---------------------------------------------------------------------------
def scenario_multiple_violations_are_all_reported() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(
            position_size=2.0,
            allow_entry=True,
            allow_exit=True,
            risk_level="EXTREME",
        )
    )
    check(
        result.approved is False and len(result.violations) == 3,
        "I7: a policy result violating all three rules simultaneously "
        "reports exactly three violations",
    )


# ---------------------------------------------------------------------------
# Group 8 -- field preservation -- I8
# ---------------------------------------------------------------------------
def scenario_action_risk_level_position_size_are_preserved() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(
            action="HOLD", position_size=0.5, allow_entry=False, allow_exit=False, risk_level="LOW"
        )
    )
    check(
        result.action == "HOLD" and result.risk_level == "LOW" and result.position_size == 0.5,
        "I8: action, risk_level, and position_size on the input policy "
        "result are preserved unchanged on the PolicyGuardResult",
    )


# ---------------------------------------------------------------------------
# Group 9 -- notes contains action name -- I9
# ---------------------------------------------------------------------------
def scenario_notes_contains_action_name_when_approved() -> None:
    result = PolicyGuard().evaluate(_FakePolicyResult(action="BUY"))
    check(
        "BUY" in result.notes,
        "I9: notes contains the action name ('BUY') for an approved result",
    )


def scenario_notes_contains_action_name_when_rejected() -> None:
    result = PolicyGuard().evaluate(
        _FakePolicyResult(action="SELL", allow_entry=True, allow_exit=True)
    )
    check(
        "SELL" in result.notes,
        "I9: notes contains the action name ('SELL') for a rejected result",
    )


# ---------------------------------------------------------------------------
# Group 10 -- missing attribute -- I10
# ---------------------------------------------------------------------------
def scenario_missing_attribute_raises_policy_guard_error() -> None:
    raised_type = None
    try:
        PolicyGuard().evaluate(_PolicyResultMissingField())
    except PolicyGuardError:
        raised_type = PolicyGuardError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is PolicyGuardError,
        "I10: PolicyGuard.evaluate() raises PolicyGuardError (not "
        "AttributeError) when the policy result object is missing a "
        "required attribute ('risk_level')",
    )


# ---------------------------------------------------------------------------
# Group 11 -- statelessness / determinism -- I13
# ---------------------------------------------------------------------------
def scenario_policy_guard_has_no_instance_attributes() -> None:
    guard = PolicyGuard()
    check(
        vars(guard) == {},
        "I13: a PolicyGuard instance holds no instance attributes "
        "(vars() is empty), confirming it is safe to reuse across calls",
    )


def scenario_policy_guard_is_deterministic() -> None:
    guard = PolicyGuard()
    first = guard.evaluate(_FakePolicyResult(action="HOLD", position_size=0.5, risk_level="LOW"))
    second = guard.evaluate(_FakePolicyResult(action="HOLD", position_size=0.5, risk_level="LOW"))

    check(
        first == second,
        "I13: PolicyGuard.evaluate() is deterministic -- the same input "
        "policy result always produces an equal PolicyGuardResult",
    )


# ---------------------------------------------------------------------------
# Group 12 -- composition root wiring smoke check -- I14
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_policy_guard() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.policy_guard, PolicyGuard),
        "I14: Core.composition_root.build_application() exposes a "
        "PolicyGuard instance on ApplicationGraph.policy_guard",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_policy_guard_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_valid_buy_is_approved_with_no_violations,
        scenario_valid_hold_is_approved_with_no_violations,
        scenario_valid_sell_is_approved_with_no_violations,
        # Group 4
        scenario_conflicting_entry_exit_is_rejected,
        scenario_conflicting_entry_exit_violation_mentions_flags,
        # Group 5
        scenario_position_size_above_one_is_rejected,
        scenario_position_size_below_zero_is_rejected,
        scenario_position_size_boundary_zero_is_valid,
        scenario_position_size_boundary_one_is_valid,
        # Group 6
        scenario_unrecognized_risk_level_is_rejected,
        scenario_lowercase_risk_level_is_rejected,
        # Group 7
        scenario_multiple_violations_are_all_reported,
        # Group 8
        scenario_action_risk_level_position_size_are_preserved,
        # Group 9
        scenario_notes_contains_action_name_when_approved,
        scenario_notes_contains_action_name_when_rejected,
        # Group 10
        scenario_missing_attribute_raises_policy_guard_error,
        # Group 11
        scenario_policy_guard_has_no_instance_attributes,
        scenario_policy_guard_is_deterministic,
        # Group 12
        scenario_composition_root_exposes_policy_guard,
    ]

    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE L21 POLICY GUARD RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())