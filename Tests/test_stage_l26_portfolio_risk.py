"""
Stage L26 proof suite -- Portfolio Risk (Stage L26, additive component).

Scope: dedicated regression suite for
``Orchestration.portfolio_risk.PortfolioRiskError``,
``Orchestration.portfolio_risk.PortfolioRiskResult``, and
``Orchestration.portfolio_risk.PortfolioRisk`` only. No Composition
Root wiring assertions beyond a plain construction/attribute smoke
check, no automatic invocation from StockAgent/RuntimeAnalysisPipeline/
DecisionEngine/DecisionPolicy/PolicyGuard/ExecutionIntent/
ExecutionPlanner/ExecutionCoordinator/PortfolioEngine, no real order
placement, allocation change, or persistence -- all explicitly out of
scope for L26.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py`` through
``test_stage_l25_portfolio_engine.py``: a global pass/fail counter,
plain fixtures, and a ``main()`` runner. No ``unittest`` module is
used, matching the existing convention.

Invariant coverage:
    I1  -- a not-approved portfolio engine result produces
           approved=False, exposure_level="NONE",
           diversification_level="NONE", and no violations.
    I2  -- an approved, in-range, non-concentrated portfolio engine
           result produces approved=True and no violations.
    I3  -- exposure outside [0.0, 1.0] produces a violation and
           exposure_level="INVALID".
    I4  -- allocation_weight outside [0.0, 1.0] produces a violation.
    I5  -- allocation_weight above the concentration threshold (0.5)
           produces a violation and diversification_level="CONCENTRATED".
    I6  -- any violation makes the result approved=False, even when
           the upstream portfolio engine result was approved=True.
    I7  -- exposure is bucketed into NONE/LOW/MODERATE/HIGH correctly
           at representative boundary values.
    I8  -- notes reflects the not-evaluated reason when not approved
           upstream, and reflects rejection reasons when violations
           exist.
    I9  -- a portfolio engine result missing a required attribute
           raises PortfolioRiskError (not AttributeError).
    I10 -- PortfolioRiskResult is a frozen dataclass.
    I11 -- PortfolioRiskResult declares exactly five fields.
    I12 -- PortfolioRiskError subclasses Core.exceptions.AgentError.
    I13 -- PortfolioRisk holds no instance attributes (stateless) and
           is deterministic across repeated calls with the same input.
    I14 -- Core.composition_root.build_application() exposes a
           PortfolioRisk instance on ApplicationGraph.portfolio_risk.
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
from Orchestration.portfolio_risk import (
    PortfolioRisk,
    PortfolioRiskError,
    PortfolioRiskResult,
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


class _FakePortfolioEngineResult:
    """Minimal stand-in for
    Orchestration.portfolio_engine.PortfolioEngineResult.

    PortfolioRisk.assess() only reads ``approved``,
    ``allocation_weight``, and ``exposure`` off its argument, so a
    lightweight plain object is sufficient and keeps this suite
    independent of PortfolioEngine.
    """

    def __init__(
        self,
        approved: bool = True,
        allocation_weight: float = 0.3,
        exposure: float = 0.3,
        notes: str = "",
    ) -> None:
        self.approved = approved
        self.allocation_weight = allocation_weight
        self.exposure = exposure
        self.notes = notes


class _PortfolioEngineResultMissingField:
    """Stand-in engine result object deliberately missing 'exposure'."""

    def __init__(self) -> None:
        self.approved = True
        self.allocation_weight = 0.3


# ---------------------------------------------------------------------------
# Group 1 -- PortfolioRiskError
# ---------------------------------------------------------------------------
def scenario_portfolio_risk_error_is_agent_error() -> None:
    check(
        issubclass(PortfolioRiskError, AgentError),
        "I12: PortfolioRiskError subclasses Core.exceptions.AgentError, "
        "same convention as PortfolioEngineError/ExecutionCoordinatorError/"
        "ExecutionPlannerError/ExecutionIntentError/PolicyGuardError/"
        "DecisionPolicyError/DecisionEngineError/ReflectionError",
    )
    err = PortfolioRiskError("boom")
    check(isinstance(err, Exception), "PortfolioRiskError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- PortfolioRiskResult (value shape) -- I10, I11
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = PortfolioRisk().assess(_FakePortfolioEngineResult())

    check(dataclasses.is_dataclass(result), "PortfolioRiskResult is a dataclass")

    frozen = False
    try:
        result.approved = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I10: PortfolioRiskResult is frozen -- field reassignment "
        "raises FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(PortfolioRiskResult)}
    check(
        field_names
        == {
            "approved",
            "exposure_level",
            "diversification_level",
            "violations",
            "notes",
        },
        "I11: PortfolioRiskResult declares exactly five fields "
        "(approved, exposure_level, diversification_level, "
        "violations, notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- not-approved upstream result -- I1
# ---------------------------------------------------------------------------
def scenario_not_approved_upstream_short_circuits() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=False, allocation_weight=0.9, exposure=0.9)
    )
    check(
        result.approved is False
        and result.exposure_level == "NONE"
        and result.diversification_level == "NONE"
        and result.violations == tuple(),
        "I1: a not-approved portfolio engine result produces "
        "approved=False, exposure_level='NONE', "
        "diversification_level='NONE', and no violations",
    )


# ---------------------------------------------------------------------------
# Group 4 -- valid, approved, non-concentrated result -- I2
# ---------------------------------------------------------------------------
def scenario_valid_result_is_approved_with_no_violations() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.3, exposure=0.3)
    )
    check(
        result.approved is True and result.violations == tuple(),
        "I2: an approved, in-range, non-concentrated portfolio engine "
        "result produces approved=True and no violations",
    )


# ---------------------------------------------------------------------------
# Group 5 -- exposure out of range -- I3
# ---------------------------------------------------------------------------
def scenario_exposure_above_upper_bound_is_a_violation() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.3, exposure=1.5)
    )
    check(
        len(result.violations) > 0 and result.exposure_level == "INVALID",
        "I3: exposure above 1.0 produces a violation and "
        "exposure_level='INVALID'",
    )


def scenario_exposure_below_lower_bound_is_a_violation() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.3, exposure=-0.1)
    )
    check(
        len(result.violations) > 0 and result.exposure_level == "INVALID",
        "I3: exposure below 0.0 produces a violation and "
        "exposure_level='INVALID'",
    )


# ---------------------------------------------------------------------------
# Group 6 -- allocation_weight out of range -- I4
# ---------------------------------------------------------------------------
def scenario_allocation_weight_above_upper_bound_is_a_violation() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=1.2, exposure=0.3)
    )
    check(
        len(result.violations) > 0,
        "I4: allocation_weight above 1.0 produces a violation",
    )


def scenario_allocation_weight_below_lower_bound_is_a_violation() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=-0.2, exposure=0.3)
    )
    check(
        len(result.violations) > 0,
        "I4: allocation_weight below 0.0 produces a violation",
    )


# ---------------------------------------------------------------------------
# Group 7 -- concentration -- I5
# ---------------------------------------------------------------------------
def scenario_concentrated_allocation_is_a_violation() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.75, exposure=0.5)
    )
    check(
        len(result.violations) > 0 and result.diversification_level == "CONCENTRATED",
        "I5: allocation_weight above the concentration threshold (0.5) "
        "produces a violation and diversification_level='CONCENTRATED'",
    )


def scenario_non_concentrated_allocation_is_diversified() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.4, exposure=0.4)
    )
    check(
        result.diversification_level == "DIVERSIFIED",
        "I5: allocation_weight at or below the concentration threshold "
        "produces diversification_level='DIVERSIFIED'",
    )


# ---------------------------------------------------------------------------
# Group 8 -- violation overrides upstream approval -- I6
# ---------------------------------------------------------------------------
def scenario_violation_forces_not_approved_even_if_upstream_approved() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.9, exposure=0.9)
    )
    check(
        result.approved is False,
        "I6: any violation makes the result approved=False, even when "
        "the upstream portfolio engine result was approved=True",
    )


# ---------------------------------------------------------------------------
# Group 9 -- exposure bucketing -- I7
# ---------------------------------------------------------------------------
def scenario_zero_exposure_is_none_level() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.0, exposure=0.0)
    )
    check(result.exposure_level == "NONE", "I7: exposure=0.0 buckets to exposure_level='NONE'")


def scenario_low_exposure_buckets_correctly() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.2, exposure=0.2)
    )
    check(result.exposure_level == "LOW", "I7: exposure=0.2 buckets to exposure_level='LOW'")


def scenario_moderate_exposure_buckets_correctly() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.5, exposure=0.5)
    )
    check(result.exposure_level == "MODERATE", "I7: exposure=0.5 buckets to exposure_level='MODERATE'")


def scenario_high_exposure_buckets_correctly() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.5, exposure=0.9)
    )
    check(result.exposure_level == "HIGH", "I7: exposure=0.9 buckets to exposure_level='HIGH'")


# ---------------------------------------------------------------------------
# Group 10 -- notes content -- I8
# ---------------------------------------------------------------------------
def scenario_notes_states_not_evaluated_when_not_approved_upstream() -> None:
    result = PortfolioRisk().assess(_FakePortfolioEngineResult(approved=False))
    check(
        "not evaluated" in result.notes and "not approved" in result.notes,
        "I8: notes states risk was not evaluated when the upstream "
        "result was not approved",
    )


def scenario_notes_states_rejection_reason_when_violations_exist() -> None:
    result = PortfolioRisk().assess(
        _FakePortfolioEngineResult(approved=True, allocation_weight=0.3, exposure=5.0)
    )
    check(
        "rejected" in result.notes and "exposure" in result.notes,
        "I8: notes contains the rejection reason when violations exist",
    )


# ---------------------------------------------------------------------------
# Group 11 -- missing attribute -- I9
# ---------------------------------------------------------------------------
def scenario_missing_attribute_raises_portfolio_risk_error() -> None:
    raised_type = None
    try:
        PortfolioRisk().assess(_PortfolioEngineResultMissingField())
    except PortfolioRiskError:
        raised_type = PortfolioRiskError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is PortfolioRiskError,
        "I9: PortfolioRisk.assess() raises PortfolioRiskError (not "
        "AttributeError) when the portfolio engine result object is "
        "missing a required attribute ('exposure')",
    )


# ---------------------------------------------------------------------------
# Group 12 -- statelessness / determinism -- I13
# ---------------------------------------------------------------------------
def scenario_portfolio_risk_has_no_instance_attributes() -> None:
    risk = PortfolioRisk()
    check(
        vars(risk) == {},
        "I13: a PortfolioRisk instance holds no instance attributes "
        "(vars() is empty), confirming it is safe to reuse across calls",
    )


def scenario_portfolio_risk_is_deterministic() -> None:
    risk = PortfolioRisk()
    first = risk.assess(_FakePortfolioEngineResult(approved=True, allocation_weight=0.4, exposure=0.4))
    second = risk.assess(_FakePortfolioEngineResult(approved=True, allocation_weight=0.4, exposure=0.4))

    check(
        first == second,
        "I13: PortfolioRisk.assess() is deterministic -- the same input "
        "portfolio engine result always produces an equal "
        "PortfolioRiskResult",
    )


# ---------------------------------------------------------------------------
# Group 13 -- composition root wiring smoke check -- I14
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_portfolio_risk() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.portfolio_risk, PortfolioRisk),
        "I14: Core.composition_root.build_application() exposes a "
        "PortfolioRisk instance on ApplicationGraph.portfolio_risk",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_portfolio_risk_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_not_approved_upstream_short_circuits,
        # Group 4
        scenario_valid_result_is_approved_with_no_violations,
        # Group 5
        scenario_exposure_above_upper_bound_is_a_violation,
        scenario_exposure_below_lower_bound_is_a_violation,
        # Group 6
        scenario_allocation_weight_above_upper_bound_is_a_violation,
        scenario_allocation_weight_below_lower_bound_is_a_violation,
        # Group 7
        scenario_concentrated_allocation_is_a_violation,
        scenario_non_concentrated_allocation_is_diversified,
        # Group 8
        scenario_violation_forces_not_approved_even_if_upstream_approved,
        # Group 9
        scenario_zero_exposure_is_none_level,
        scenario_low_exposure_buckets_correctly,
        scenario_moderate_exposure_buckets_correctly,
        scenario_high_exposure_buckets_correctly,
        # Group 10
        scenario_notes_states_not_evaluated_when_not_approved_upstream,
        scenario_notes_states_rejection_reason_when_violations_exist,
        # Group 11
        scenario_missing_attribute_raises_portfolio_risk_error,
        # Group 12
        scenario_portfolio_risk_has_no_instance_attributes,
        scenario_portfolio_risk_is_deterministic,
        # Group 13
        scenario_composition_root_exposes_portfolio_risk,
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
    print(f"STAGE L26 PORTFOLIO RISK RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())