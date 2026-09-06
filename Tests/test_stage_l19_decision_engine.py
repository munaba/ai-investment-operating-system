"""
Stage L19 proof suite -- Decision Engine (Phase 1, additive component).

Scope: dedicated regression suite for
``Orchestration.decision_engine.DecisionEngineError``,
``Orchestration.decision_engine.Decision``, and
``Orchestration.decision_engine.DecisionEngine`` only. No Composition
Root wiring assertions beyond field presence, no automatic invocation
from StockAgent/RuntimeAnalysisPipeline, no real trading logic -- all
explicitly out of scope for L19 Phase 1.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py``: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    I1 -- Decision is frozen (field reassignment raises FrozenInstanceError).
    I2 -- DecisionEngine.decide() raises DecisionEngineError (not some
          other exception) for a non-numeric input.
    I3 -- score >= 70 -> BUY.
    I4 -- 45 <= score < 70 -> HOLD.
    I5 -- score < 45 -> SELL.
    I6 -- boundary values (45, 70) resolve to the documented side of the
          threshold.
    I7 -- confidence is always within [0.0, 1.0], including for
          out-of-range scores.
    I8 -- DecisionEngine is stateless (no instance attributes, reusable
          across calls with independent results).
    I9 -- DecisionEngineError subclasses Core.exceptions.AgentError.
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
from Orchestration.decision_engine import Decision, DecisionEngine, DecisionEngineError

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


# ---------------------------------------------------------------------------
# Group 1 -- DecisionEngineError
# ---------------------------------------------------------------------------
def scenario_decision_engine_error_is_agent_error() -> None:
    check(
        issubclass(DecisionEngineError, AgentError),
        "I9: DecisionEngineError subclasses Core.exceptions.AgentError, "
        "same convention as ReflectionError/ObservationError",
    )
    err = DecisionEngineError("boom")
    check(isinstance(err, Exception), "DecisionEngineError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- Decision (value shape) -- I1
# ---------------------------------------------------------------------------
def scenario_decision_is_frozen_dataclass() -> None:
    decision = DecisionEngine().decide(score=80.0)

    check(dataclasses.is_dataclass(decision), "Decision is a dataclass")

    frozen = False
    try:
        decision.action = "SELL"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I1: Decision is frozen -- field reassignment raises "
        "FrozenInstanceError",
    )


def scenario_decision_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(Decision)}
    check(
        field_names == {"action", "confidence", "score", "rationale"},
        "Decision declares exactly four fields (action, confidence, "
        "score, rationale)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- decide() type validation -- I2
# ---------------------------------------------------------------------------
def scenario_decide_rejects_string_with_decision_engine_error() -> None:
    raised_type = None
    try:
        DecisionEngine().decide(score="80")  # type: ignore[arg-type]
    except DecisionEngineError:
        raised_type = DecisionEngineError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is DecisionEngineError,
        "I2: DecisionEngine.decide() raises DecisionEngineError (not "
        "TypeError) when given a string instead of a float",
    )


def scenario_decide_rejects_none_with_decision_engine_error() -> None:
    raised_type = None
    try:
        DecisionEngine().decide(score=None)  # type: ignore[arg-type]
    except DecisionEngineError:
        raised_type = DecisionEngineError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is DecisionEngineError,
        "I2: DecisionEngine.decide() raises DecisionEngineError when "
        "given None",
    )


def scenario_decide_rejects_bool_with_decision_engine_error() -> None:
    # bool is technically a subclass of int in Python -- explicitly
    # excluded so True/False can never silently pass as scores 1/0.
    raised_type = None
    try:
        DecisionEngine().decide(score=True)  # type: ignore[arg-type]
    except DecisionEngineError:
        raised_type = DecisionEngineError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is DecisionEngineError,
        "I2: DecisionEngine.decide() raises DecisionEngineError when "
        "given a bool (excluded despite bool being an int subclass)",
    )


def scenario_decide_accepts_int_score() -> None:
    decision = DecisionEngine().decide(score=80)
    check(
        decision.action == "BUY",
        "DecisionEngine.decide() accepts a plain int score",
    )


# ---------------------------------------------------------------------------
# Group 4 -- deterministic mapping -- I3, I4, I5, I6
# ---------------------------------------------------------------------------
def scenario_high_score_maps_to_buy() -> None:
    decision = DecisionEngine().decide(score=85.0)
    check(decision.action == "BUY", "I3: score=85.0 (>= 70) maps to BUY")


def scenario_mid_score_maps_to_hold() -> None:
    decision = DecisionEngine().decide(score=55.0)
    check(decision.action == "HOLD", "I4: score=55.0 (45 <= score < 70) maps to HOLD")


def scenario_low_score_maps_to_sell() -> None:
    decision = DecisionEngine().decide(score=20.0)
    check(decision.action == "SELL", "I5: score=20.0 (< 45) maps to SELL")


def scenario_buy_lower_boundary_is_inclusive() -> None:
    decision = DecisionEngine().decide(score=70.0)
    check(
        decision.action == "BUY",
        "I6: score=70.0 (exact BUY threshold) maps to BUY (inclusive)",
    )


def scenario_hold_lower_boundary_is_inclusive() -> None:
    decision = DecisionEngine().decide(score=45.0)
    check(
        decision.action == "HOLD",
        "I6: score=45.0 (exact HOLD threshold) maps to HOLD (inclusive)",
    )


def scenario_just_below_buy_threshold_is_hold() -> None:
    decision = DecisionEngine().decide(score=69.999)
    check(
        decision.action == "HOLD",
        "I6: score=69.999 (just below BUY threshold) maps to HOLD",
    )


def scenario_just_below_hold_threshold_is_sell() -> None:
    decision = DecisionEngine().decide(score=44.999)
    check(
        decision.action == "SELL",
        "I6: score=44.999 (just below HOLD threshold) maps to SELL",
    )


# ---------------------------------------------------------------------------
# Group 5 -- confidence range -- I7
# ---------------------------------------------------------------------------
def scenario_confidence_within_range_for_typical_scores() -> None:
    engine = DecisionEngine()
    all_within_range = all(
        0.0 <= engine.decide(score=s).confidence <= 1.0
        for s in (0.0, 20.0, 44.999, 45.0, 55.0, 69.999, 70.0, 85.0, 100.0)
    )
    check(
        all_within_range,
        "I7: confidence is within [0.0, 1.0] across the full nominal "
        "0-100 score range",
    )


def scenario_confidence_matches_expected_normalization() -> None:
    decision = DecisionEngine().decide(score=70.0)
    check(
        abs(decision.confidence - 0.70) < 1e-9,
        "I7: confidence for score=70.0 normalizes to 0.70 (score/100)",
    )


def scenario_confidence_clamped_for_out_of_range_high_score() -> None:
    decision = DecisionEngine().decide(score=150.0)
    check(
        decision.confidence == 1.0,
        "I7: confidence for an out-of-range score (150.0) clamps to 1.0, "
        "never exceeding the 0.0-1.0 range",
    )
    check(
        decision.action == "BUY",
        "an out-of-range high score (150.0) still maps to BUY",
    )


def scenario_confidence_clamped_for_out_of_range_negative_score() -> None:
    decision = DecisionEngine().decide(score=-30.0)
    check(
        decision.confidence == 0.0,
        "I7: confidence for an out-of-range score (-30.0) clamps to 0.0, "
        "never going below the 0.0-1.0 range",
    )
    check(
        decision.action == "SELL",
        "an out-of-range negative score (-30.0) still maps to SELL",
    )


# ---------------------------------------------------------------------------
# Group 6 -- statelessness -- I8
# ---------------------------------------------------------------------------
def scenario_decision_engine_has_no_instance_attributes() -> None:
    engine = DecisionEngine()
    check(
        vars(engine) == {},
        "I8: a DecisionEngine instance holds no instance attributes "
        "(vars() is empty), confirming it is safe to reuse across calls",
    )


def scenario_decision_engine_repeated_calls_do_not_affect_each_other() -> None:
    engine = DecisionEngine()
    engine.decide(score=90.0)
    decision = engine.decide(score=10.0)

    check(
        decision.action == "SELL" and decision.score == 10.0,
        "I8: a prior call does not leak into or influence a subsequent "
        "call's result on the same DecisionEngine instance",
    )


def scenario_decision_engine_is_deterministic() -> None:
    engine = DecisionEngine()
    first = engine.decide(score=63.5)
    second = engine.decide(score=63.5)

    check(
        (first.action, first.confidence, first.score) == (second.action, second.confidence, second.score),
        "DecisionEngine.decide() is deterministic -- the same score "
        "always produces the same action/confidence/score",
    )


# ---------------------------------------------------------------------------
# Group 7 -- rationale presence
# ---------------------------------------------------------------------------
def scenario_rationale_is_a_non_empty_string() -> None:
    decision = DecisionEngine().decide(score=55.0)
    check(
        isinstance(decision.rationale, str) and len(decision.rationale) > 0,
        "Decision.rationale is a non-empty string",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_decision_engine_error_is_agent_error,
        # Group 2
        scenario_decision_is_frozen_dataclass,
        scenario_decision_has_expected_fields,
        # Group 3
        scenario_decide_rejects_string_with_decision_engine_error,
        scenario_decide_rejects_none_with_decision_engine_error,
        scenario_decide_rejects_bool_with_decision_engine_error,
        scenario_decide_accepts_int_score,
        # Group 4
        scenario_high_score_maps_to_buy,
        scenario_mid_score_maps_to_hold,
        scenario_low_score_maps_to_sell,
        scenario_buy_lower_boundary_is_inclusive,
        scenario_hold_lower_boundary_is_inclusive,
        scenario_just_below_buy_threshold_is_hold,
        scenario_just_below_hold_threshold_is_sell,
        # Group 5
        scenario_confidence_within_range_for_typical_scores,
        scenario_confidence_matches_expected_normalization,
        scenario_confidence_clamped_for_out_of_range_high_score,
        scenario_confidence_clamped_for_out_of_range_negative_score,
        # Group 6
        scenario_decision_engine_has_no_instance_attributes,
        scenario_decision_engine_repeated_calls_do_not_affect_each_other,
        scenario_decision_engine_is_deterministic,
        # Group 7
        scenario_rationale_is_a_non_empty_string,
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
    print(f"STAGE L19 DECISION ENGINE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())