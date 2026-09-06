"""
Stage L20C proof suite -- Decision Policy (Stage L20A, additive component).

Scope: dedicated regression suite for
``Orchestration.decision_policy.DecisionPolicyError``,
``Orchestration.decision_policy.DecisionPolicyResult``, and
``Orchestration.decision_policy.DecisionPolicy`` only. No Composition
Root wiring assertions, no automatic invocation from
StockAgent/RuntimeAnalysisPipeline, no real trading logic -- all
explicitly out of scope for L20C.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py`` and ``test_stage_l19_decision_engine.py``:
a global pass/fail counter, plain fixtures, and a ``main()`` runner. No
``unittest`` module is used, matching the existing convention.

Invariant coverage:
    I1 -- BUY action maps to allow_entry=True, allow_exit=False,
          position_size=1.0, risk_level="NORMAL".
    I2 -- HOLD action maps to allow_entry=False, allow_exit=False,
          position_size=0.5, risk_level="LOW".
    I3 -- SELL action maps to allow_entry=False, allow_exit=True,
          position_size=0.0, risk_level="HIGH".
    I4 -- confidence from the input decision is preserved unchanged on
          the returned DecisionPolicyResult.
    I5 -- notes contains the action name.
    I6 -- an unrecognized/invalid action raises DecisionPolicyError.
    I7 -- a decision object missing an 'action' attribute raises
          DecisionPolicyError.
    I8 -- DecisionPolicyResult is a frozen dataclass.
    I9 -- DecisionPolicyError subclasses Core.exceptions.AgentError.
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
from Orchestration.decision_policy import (
    DecisionPolicy,
    DecisionPolicyError,
    DecisionPolicyResult,
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


class _FakeDecision:
    """Minimal stand-in for Orchestration.decision_engine.Decision.

    DecisionPolicy.apply() only reads ``action`` and (optionally)
    ``confidence`` off its argument, so a lightweight plain object is
    sufficient and keeps this suite independent of DecisionEngine.
    """

    def __init__(self, action: str, confidence: float = 0.0) -> None:
        self.action = action
        self.confidence = confidence


class _DecisionMissingAction:
    """Stand-in decision object that deliberately has no 'action' attribute."""

    def __init__(self, confidence: float = 0.5) -> None:
        self.confidence = confidence


# ---------------------------------------------------------------------------
# Group 1 -- DecisionPolicyError
# ---------------------------------------------------------------------------
def scenario_decision_policy_error_is_agent_error() -> None:
    check(
        issubclass(DecisionPolicyError, AgentError),
        "I9: DecisionPolicyError subclasses Core.exceptions.AgentError, "
        "same convention as DecisionEngineError/ReflectionError",
    )
    err = DecisionPolicyError("boom")
    check(isinstance(err, Exception), "DecisionPolicyError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- DecisionPolicyResult (value shape) -- I8
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = DecisionPolicy().apply(_FakeDecision("BUY", confidence=0.8))

    check(dataclasses.is_dataclass(result), "DecisionPolicyResult is a dataclass")

    frozen = False
    try:
        result.action = "SELL"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I8: DecisionPolicyResult is frozen -- field reassignment raises "
        "FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(DecisionPolicyResult)}
    check(
        field_names
        == {
            "action",
            "confidence",
            "position_size",
            "allow_entry",
            "allow_exit",
            "risk_level",
            "notes",
        },
        "DecisionPolicyResult declares exactly seven fields (action, "
        "confidence, position_size, allow_entry, allow_exit, risk_level, "
        "notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- BUY policy -- I1
# ---------------------------------------------------------------------------
def scenario_buy_allows_entry_not_exit() -> None:
    result = DecisionPolicy().apply(_FakeDecision("BUY"))
    check(
        result.allow_entry is True and result.allow_exit is False,
        "I1: BUY maps to allow_entry=True, allow_exit=False",
    )


def scenario_buy_position_size_is_full() -> None:
    result = DecisionPolicy().apply(_FakeDecision("BUY"))
    check(result.position_size == 1.0, "I1: BUY maps to position_size=1.0")


def scenario_buy_risk_level_is_normal() -> None:
    result = DecisionPolicy().apply(_FakeDecision("BUY"))
    check(result.risk_level == "NORMAL", "I1: BUY maps to risk_level='NORMAL'")


# ---------------------------------------------------------------------------
# Group 4 -- HOLD policy -- I2
# ---------------------------------------------------------------------------
def scenario_hold_disallows_entry_and_exit() -> None:
    result = DecisionPolicy().apply(_FakeDecision("HOLD"))
    check(
        result.allow_entry is False and result.allow_exit is False,
        "I2: HOLD maps to allow_entry=False, allow_exit=False",
    )


def scenario_hold_position_size_is_half() -> None:
    result = DecisionPolicy().apply(_FakeDecision("HOLD"))
    check(result.position_size == 0.5, "I2: HOLD maps to position_size=0.5")


def scenario_hold_risk_level_is_low() -> None:
    result = DecisionPolicy().apply(_FakeDecision("HOLD"))
    check(result.risk_level == "LOW", "I2: HOLD maps to risk_level='LOW'")


# ---------------------------------------------------------------------------
# Group 5 -- SELL policy -- I3
# ---------------------------------------------------------------------------
def scenario_sell_allows_exit_not_entry() -> None:
    result = DecisionPolicy().apply(_FakeDecision("SELL"))
    check(
        result.allow_entry is False and result.allow_exit is True,
        "I3: SELL maps to allow_entry=False, allow_exit=True",
    )


def scenario_sell_position_size_is_zero() -> None:
    result = DecisionPolicy().apply(_FakeDecision("SELL"))
    check(result.position_size == 0.0, "I3: SELL maps to position_size=0.0")


def scenario_sell_risk_level_is_high() -> None:
    result = DecisionPolicy().apply(_FakeDecision("SELL"))
    check(result.risk_level == "HIGH", "I3: SELL maps to risk_level='HIGH'")


# ---------------------------------------------------------------------------
# Group 6 -- confidence preservation -- I4
# ---------------------------------------------------------------------------
def scenario_confidence_is_preserved_for_buy() -> None:
    result = DecisionPolicy().apply(_FakeDecision("BUY", confidence=0.73))
    check(
        result.confidence == 0.73,
        "I4: confidence=0.73 on the input decision is preserved unchanged "
        "on the DecisionPolicyResult for BUY",
    )


def scenario_confidence_is_preserved_for_hold() -> None:
    result = DecisionPolicy().apply(_FakeDecision("HOLD", confidence=0.41))
    check(
        result.confidence == 0.41,
        "I4: confidence=0.41 on the input decision is preserved unchanged "
        "on the DecisionPolicyResult for HOLD",
    )


def scenario_confidence_is_preserved_for_sell() -> None:
    result = DecisionPolicy().apply(_FakeDecision("SELL", confidence=0.05))
    check(
        result.confidence == 0.05,
        "I4: confidence=0.05 on the input decision is preserved unchanged "
        "on the DecisionPolicyResult for SELL",
    )


# ---------------------------------------------------------------------------
# Group 7 -- notes contains action name -- I5
# ---------------------------------------------------------------------------
def scenario_notes_contains_action_name_for_each_action() -> None:
    policy = DecisionPolicy()
    all_contain_action = all(
        action in policy.apply(_FakeDecision(action)).notes
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_contain_action,
        "I5: notes contains the action name for BUY, HOLD, and SELL",
    )


# ---------------------------------------------------------------------------
# Group 8 -- invalid / missing action -- I6, I7
# ---------------------------------------------------------------------------
def scenario_invalid_action_raises_decision_policy_error() -> None:
    raised_type = None
    try:
        DecisionPolicy().apply(_FakeDecision("WAIT"))
    except DecisionPolicyError:
        raised_type = DecisionPolicyError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is DecisionPolicyError,
        "I6: DecisionPolicy.apply() raises DecisionPolicyError for an "
        "unrecognized action ('WAIT')",
    )


def scenario_empty_string_action_raises_decision_policy_error() -> None:
    raised_type = None
    try:
        DecisionPolicy().apply(_FakeDecision(""))
    except DecisionPolicyError:
        raised_type = DecisionPolicyError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is DecisionPolicyError,
        "I6: DecisionPolicy.apply() raises DecisionPolicyError for an "
        "empty-string action",
    )


def scenario_lowercase_action_raises_decision_policy_error() -> None:
    # Action matching is case-sensitive -- 'buy' is not the same key as
    # 'BUY' in the policy table, and must not silently fall through.
    raised_type = None
    try:
        DecisionPolicy().apply(_FakeDecision("buy"))
    except DecisionPolicyError:
        raised_type = DecisionPolicyError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is DecisionPolicyError,
        "I6: DecisionPolicy.apply() raises DecisionPolicyError for a "
        "lowercase action ('buy'), confirming case-sensitive matching",
    )


def scenario_missing_action_attribute_raises_decision_policy_error() -> None:
    raised_type = None
    try:
        DecisionPolicy().apply(_DecisionMissingAction())
    except DecisionPolicyError:
        raised_type = DecisionPolicyError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is DecisionPolicyError,
        "I7: DecisionPolicy.apply() raises DecisionPolicyError (not "
        "AttributeError) when the decision object has no 'action' "
        "attribute",
    )


# ---------------------------------------------------------------------------
# Group 9 -- statelessness / determinism (mirrors L19 conventions)
# ---------------------------------------------------------------------------
def scenario_decision_policy_has_no_instance_attributes() -> None:
    policy = DecisionPolicy()
    check(
        vars(policy) == {},
        "a DecisionPolicy instance holds no instance attributes (vars() "
        "is empty), confirming it is safe to reuse across calls",
    )


def scenario_decision_policy_is_deterministic() -> None:
    policy = DecisionPolicy()
    first = policy.apply(_FakeDecision("HOLD", confidence=0.6))
    second = policy.apply(_FakeDecision("HOLD", confidence=0.6))

    check(
        first == second,
        "DecisionPolicy.apply() is deterministic -- the same input "
        "decision always produces an equal DecisionPolicyResult",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_decision_policy_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_buy_allows_entry_not_exit,
        scenario_buy_position_size_is_full,
        scenario_buy_risk_level_is_normal,
        # Group 4
        scenario_hold_disallows_entry_and_exit,
        scenario_hold_position_size_is_half,
        scenario_hold_risk_level_is_low,
        # Group 5
        scenario_sell_allows_exit_not_entry,
        scenario_sell_position_size_is_zero,
        scenario_sell_risk_level_is_high,
        # Group 6
        scenario_confidence_is_preserved_for_buy,
        scenario_confidence_is_preserved_for_hold,
        scenario_confidence_is_preserved_for_sell,
        # Group 7
        scenario_notes_contains_action_name_for_each_action,
        # Group 8
        scenario_invalid_action_raises_decision_policy_error,
        scenario_empty_string_action_raises_decision_policy_error,
        scenario_lowercase_action_raises_decision_policy_error,
        scenario_missing_action_attribute_raises_decision_policy_error,
        # Group 9
        scenario_decision_policy_has_no_instance_attributes,
        scenario_decision_policy_is_deterministic,
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
    print(f"STAGE L20 DECISION POLICY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())