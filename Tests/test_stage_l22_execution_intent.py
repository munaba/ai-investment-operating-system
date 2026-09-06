"""
Stage L22 proof suite -- Execution Intent (Stage L22, additive component).

Scope: dedicated regression suite for
``Orchestration.execution_intent.ExecutionIntentError``,
``Orchestration.execution_intent.ExecutionIntentResult``, and
``Orchestration.execution_intent.ExecutionIntent`` only. No Composition
Root wiring assertions beyond a plain construction/attribute smoke
check, no automatic invocation from
StockAgent/RuntimeAnalysisPipeline/PolicyGuard, no real order placement
or execution -- all explicitly out of scope for L22.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py``, ``test_stage_l19_decision_engine.py``,
``test_stage_l20_decision_policy.py``, and
``test_stage_l21_policy_guard.py``: a global pass/fail counter, plain
fixtures, and a ``main()`` runner. No ``unittest`` module is used,
matching the existing convention.

Invariant coverage:
    I1  -- an approved policy guard result produces ready=True and an
           empty denial_reason.
    I2  -- an approved result's action/risk_level/position_size are
           carried through unchanged.
    I3  -- a rejected policy guard result produces ready=False.
    I4  -- a rejected result's denial_reason is built from the guard's
           violations (joined).
    I5  -- a rejected result's action/risk_level/position_size are
           still carried through unchanged (never zeroed/substituted).
    I6  -- a rejected result with an empty violations tuple falls back
           to a generic denial_reason rather than an empty string.
    I7  -- notes contains the action name for both ready and denied
           results.
    I8  -- notes contains the denial_reason text for a denied result.
    I9  -- a policy guard result missing a required attribute raises
           ExecutionIntentError (not AttributeError).
    I10 -- ExecutionIntentResult is a frozen dataclass.
    I11 -- ExecutionIntentResult declares exactly six fields.
    I12 -- ExecutionIntentError subclasses Core.exceptions.AgentError.
    I13 -- ExecutionIntent holds no instance attributes (stateless) and
           is deterministic across repeated calls with the same input.
    I14 -- behavior is consistent across BUY/HOLD/SELL-shaped inputs,
           both approved and denied, for every action.
    I15 -- Core.composition_root.build_application() exposes an
           ExecutionIntent instance on ApplicationGraph.execution_intent.
"""

from __future__ import annotations

import dataclasses
import sys
import traceback
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.execution_intent import (
    ExecutionIntent,
    ExecutionIntentError,
    ExecutionIntentResult,
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


class _FakePolicyGuardResult:
    """Minimal stand-in for Orchestration.policy_guard.PolicyGuardResult.

    ExecutionIntent.build() only reads ``approved``, ``action``,
    ``risk_level``, ``position_size``, and ``violations`` off its
    argument, so a lightweight plain object is sufficient and keeps
    this suite independent of PolicyGuard.
    """

    def __init__(
        self,
        approved: bool = True,
        action: str = "BUY",
        risk_level: str = "NORMAL",
        position_size: float = 1.0,
        violations: Tuple[str, ...] = (),
    ) -> None:
        self.approved = approved
        self.action = action
        self.risk_level = risk_level
        self.position_size = position_size
        self.violations = violations


class _PolicyGuardResultMissingField:
    """Stand-in policy guard result object deliberately missing 'violations'."""

    def __init__(self) -> None:
        self.approved = False
        self.action = "BUY"
        self.risk_level = "NORMAL"
        self.position_size = 1.0


# ---------------------------------------------------------------------------
# Group 1 -- ExecutionIntentError
# ---------------------------------------------------------------------------
def scenario_execution_intent_error_is_agent_error() -> None:
    check(
        issubclass(ExecutionIntentError, AgentError),
        "I12: ExecutionIntentError subclasses Core.exceptions.AgentError, "
        "same convention as PolicyGuardError/DecisionPolicyError/"
        "DecisionEngineError/ReflectionError",
    )
    err = ExecutionIntentError("boom")
    check(isinstance(err, Exception), "ExecutionIntentError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- ExecutionIntentResult (value shape) -- I10, I11
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = ExecutionIntent().build(_FakePolicyGuardResult())

    check(dataclasses.is_dataclass(result), "ExecutionIntentResult is a dataclass")

    frozen = False
    try:
        result.ready = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I10: ExecutionIntentResult is frozen -- field reassignment "
        "raises FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(ExecutionIntentResult)}
    check(
        field_names
        == {
            "ready",
            "action",
            "risk_level",
            "position_size",
            "denial_reason",
            "notes",
        },
        "I11: ExecutionIntentResult declares exactly six fields (ready, "
        "action, risk_level, position_size, denial_reason, notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- approved policy guard result -- I1, I2
# ---------------------------------------------------------------------------
def scenario_approved_buy_is_ready_with_empty_denial_reason() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=True, action="BUY", risk_level="NORMAL", position_size=1.0)
    )
    check(
        result.ready is True and result.denial_reason == "",
        "I1: an approved BUY policy guard result produces ready=True "
        "and an empty denial_reason",
    )


def scenario_approved_fields_are_preserved() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=True, action="HOLD", risk_level="LOW", position_size=0.5)
    )
    check(
        result.action == "HOLD" and result.risk_level == "LOW" and result.position_size == 0.5,
        "I2: an approved result's action/risk_level/position_size are "
        "carried through unchanged",
    )


# ---------------------------------------------------------------------------
# Group 4 -- rejected policy guard result -- I3, I4
# ---------------------------------------------------------------------------
def scenario_rejected_result_is_not_ready() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=False, violations=("some violation",))
    )
    check(result.ready is False, "I3: a rejected policy guard result produces ready=False")


def scenario_rejected_denial_reason_joins_violations() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(
            approved=False,
            violations=("violation one", "violation two"),
        )
    )
    check(
        result.denial_reason == "violation one; violation two",
        "I4: a rejected result's denial_reason joins the guard's "
        "violations with '; '",
    )


def scenario_rejected_denial_reason_single_violation() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=False, violations=("only violation",))
    )
    check(
        result.denial_reason == "only violation",
        "I4: a rejected result with a single violation uses that "
        "violation text unchanged as denial_reason",
    )


# ---------------------------------------------------------------------------
# Group 5 -- rejected result preserves fields -- I5
# ---------------------------------------------------------------------------
def scenario_rejected_fields_are_still_preserved() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(
            approved=False,
            action="SELL",
            risk_level="HIGH",
            position_size=0.0,
            violations=("conflicting entry/exit flags",),
        )
    )
    check(
        result.action == "SELL" and result.risk_level == "HIGH" and result.position_size == 0.0,
        "I5: a rejected result's action/risk_level/position_size are "
        "still carried through unchanged, never zeroed or substituted",
    )


# ---------------------------------------------------------------------------
# Group 6 -- empty violations fallback -- I6
# ---------------------------------------------------------------------------
def scenario_rejected_with_empty_violations_uses_generic_fallback() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=False, violations=())
    )
    check(
        result.denial_reason == "policy guard result was not approved",
        "I6: a rejected result with an empty violations tuple falls "
        "back to a generic denial_reason rather than an empty string",
    )


def scenario_empty_violations_fallback_is_not_blank() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=False, violations=())
    )
    check(
        len(result.denial_reason) > 0,
        "I6: the generic fallback denial_reason is non-empty",
    )


# ---------------------------------------------------------------------------
# Group 7 -- notes content -- I7, I8
# ---------------------------------------------------------------------------
def scenario_notes_contains_action_name_when_ready() -> None:
    result = ExecutionIntent().build(_FakePolicyGuardResult(approved=True, action="BUY"))
    check(
        "BUY" in result.notes,
        "I7: notes contains the action name ('BUY') for a ready result",
    )


def scenario_notes_contains_action_name_when_denied() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=False, action="SELL", violations=("bad",))
    )
    check(
        "SELL" in result.notes,
        "I7: notes contains the action name ('SELL') for a denied result",
    )


def scenario_notes_contains_denial_reason_when_denied() -> None:
    result = ExecutionIntent().build(
        _FakePolicyGuardResult(approved=False, violations=("specific reason",))
    )
    check(
        "specific reason" in result.notes,
        "I8: notes contains the denial_reason text for a denied result",
    )


# ---------------------------------------------------------------------------
# Group 8 -- missing attribute -- I9
# ---------------------------------------------------------------------------
def scenario_missing_attribute_raises_execution_intent_error() -> None:
    raised_type = None
    try:
        ExecutionIntent().build(_PolicyGuardResultMissingField())
    except ExecutionIntentError:
        raised_type = ExecutionIntentError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is ExecutionIntentError,
        "I9: ExecutionIntent.build() raises ExecutionIntentError (not "
        "AttributeError) when the policy guard result object is "
        "missing a required attribute ('violations')",
    )


# ---------------------------------------------------------------------------
# Group 9 -- statelessness / determinism -- I13
# ---------------------------------------------------------------------------
def scenario_execution_intent_has_no_instance_attributes() -> None:
    intent = ExecutionIntent()
    check(
        vars(intent) == {},
        "I13: an ExecutionIntent instance holds no instance attributes "
        "(vars() is empty), confirming it is safe to reuse across calls",
    )


def scenario_execution_intent_is_deterministic() -> None:
    intent = ExecutionIntent()
    first = intent.build(_FakePolicyGuardResult(approved=True, action="HOLD", position_size=0.5))
    second = intent.build(_FakePolicyGuardResult(approved=True, action="HOLD", position_size=0.5))

    check(
        first == second,
        "I13: ExecutionIntent.build() is deterministic -- the same "
        "input policy guard result always produces an equal "
        "ExecutionIntentResult",
    )


# ---------------------------------------------------------------------------
# Group 10 -- consistency across actions -- I14
# ---------------------------------------------------------------------------
def scenario_all_actions_ready_when_approved() -> None:
    intent = ExecutionIntent()
    all_ready = all(
        intent.build(_FakePolicyGuardResult(approved=True, action=action)).ready is True
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_ready,
        "I14: BUY, HOLD, and SELL all produce ready=True when approved",
    )


def scenario_all_actions_denied_when_rejected() -> None:
    intent = ExecutionIntent()
    all_denied = all(
        intent.build(
            _FakePolicyGuardResult(approved=False, action=action, violations=("x",))
        ).ready
        is False
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_denied,
        "I14: BUY, HOLD, and SELL all produce ready=False when rejected",
    )


# ---------------------------------------------------------------------------
# Group 11 -- composition root wiring smoke check -- I15
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_execution_intent() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.execution_intent, ExecutionIntent),
        "I15: Core.composition_root.build_application() exposes an "
        "ExecutionIntent instance on ApplicationGraph.execution_intent",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_execution_intent_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_approved_buy_is_ready_with_empty_denial_reason,
        scenario_approved_fields_are_preserved,
        # Group 4
        scenario_rejected_result_is_not_ready,
        scenario_rejected_denial_reason_joins_violations,
        scenario_rejected_denial_reason_single_violation,
        # Group 5
        scenario_rejected_fields_are_still_preserved,
        # Group 6
        scenario_rejected_with_empty_violations_uses_generic_fallback,
        scenario_empty_violations_fallback_is_not_blank,
        # Group 7
        scenario_notes_contains_action_name_when_ready,
        scenario_notes_contains_action_name_when_denied,
        scenario_notes_contains_denial_reason_when_denied,
        # Group 8
        scenario_missing_attribute_raises_execution_intent_error,
        # Group 9
        scenario_execution_intent_has_no_instance_attributes,
        scenario_execution_intent_is_deterministic,
        # Group 10
        scenario_all_actions_ready_when_approved,
        scenario_all_actions_denied_when_rejected,
        # Group 11
        scenario_composition_root_exposes_execution_intent,
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
    print(f"STAGE L22 EXECUTION INTENT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())