"""
Stage L25 proof suite -- Portfolio Engine (Stage L25, additive component).

Scope: dedicated regression suite for
``Orchestration.portfolio_engine.PortfolioEngineError``,
``Orchestration.portfolio_engine.PortfolioEngineResult``, and
``Orchestration.portfolio_engine.PortfolioEngine`` only. No
Composition Root wiring assertions beyond a plain
construction/attribute smoke check, no automatic invocation from
StockAgent/RuntimeAnalysisPipeline/DecisionEngine/DecisionPolicy/
PolicyGuard/ExecutionIntent/ExecutionPlanner/ExecutionCoordinator, no
real order placement, allocation change, or persistence -- all
explicitly out of scope for L25.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py`` through
``test_stage_l24_execution_coordinator.py``: a global pass/fail
counter, plain fixtures, and a ``main()`` runner. No ``unittest``
module is used, matching the existing convention.

Invariant coverage:
    I1  -- a coordinated execution coordinator result produces
           approved=True.
    I2  -- an approved result's allocation_weight and exposure equal
           the input's position_size.
    I3  -- a not-coordinated execution coordinator result produces
           approved=False.
    I4  -- a not-approved result's allocation_weight and exposure are
           both 0.0.
    I5  -- notes contains the action name for both approved and
           not-approved results.
    I6  -- an execution coordinator result missing a required
           attribute raises PortfolioEngineError (not AttributeError).
    I7  -- PortfolioEngineResult is a frozen dataclass.
    I8  -- PortfolioEngineResult declares exactly four fields.
    I9  -- PortfolioEngineError subclasses Core.exceptions.AgentError.
    I10 -- PortfolioEngine holds no instance attributes (stateless)
           and is deterministic across repeated calls with the same
           input.
    I11 -- behavior is consistent across BUY/HOLD/SELL-shaped inputs,
           both coordinated and not-coordinated, for every action.
    I12 -- Core.composition_root.build_application() exposes a
           PortfolioEngine instance on ApplicationGraph.portfolio_engine.
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
from Orchestration.portfolio_engine import (
    PortfolioEngine,
    PortfolioEngineError,
    PortfolioEngineResult,
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


class _FakeExecutionCoordinatorResult:
    """Minimal stand-in for
    Orchestration.execution_coordinator.ExecutionCoordinatorResult.

    PortfolioEngine.evaluate() only reads ``coordinated``, ``action``,
    ``risk_level``, and ``position_size`` off its argument, so a
    lightweight plain object is sufficient and keeps this suite
    independent of ExecutionCoordinator.
    """

    def __init__(
        self,
        coordinated: bool = True,
        action: str = "BUY",
        risk_level: str = "NORMAL",
        position_size: float = 1.0,
    ) -> None:
        self.coordinated = coordinated
        self.action = action
        self.risk_level = risk_level
        self.position_size = position_size


class _ExecutionCoordinatorResultMissingField:
    """Stand-in coordinator result object deliberately missing 'position_size'."""

    def __init__(self) -> None:
        self.coordinated = True
        self.action = "BUY"
        self.risk_level = "NORMAL"


# ---------------------------------------------------------------------------
# Group 1 -- PortfolioEngineError
# ---------------------------------------------------------------------------
def scenario_portfolio_engine_error_is_agent_error() -> None:
    check(
        issubclass(PortfolioEngineError, AgentError),
        "I9: PortfolioEngineError subclasses Core.exceptions.AgentError, "
        "same convention as ExecutionCoordinatorError/ExecutionPlannerError/"
        "ExecutionIntentError/PolicyGuardError/DecisionPolicyError/"
        "DecisionEngineError/ReflectionError",
    )
    err = PortfolioEngineError("boom")
    check(isinstance(err, Exception), "PortfolioEngineError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- PortfolioEngineResult (value shape) -- I7, I8
# ---------------------------------------------------------------------------
def scenario_result_is_frozen_dataclass() -> None:
    result = PortfolioEngine().evaluate(_FakeExecutionCoordinatorResult())

    check(dataclasses.is_dataclass(result), "PortfolioEngineResult is a dataclass")

    frozen = False
    try:
        result.approved = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I7: PortfolioEngineResult is frozen -- field reassignment "
        "raises FrozenInstanceError",
    )


def scenario_result_has_expected_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(PortfolioEngineResult)}
    check(
        field_names == {"approved", "allocation_weight", "exposure", "notes"},
        "I8: PortfolioEngineResult declares exactly four fields "
        "(approved, allocation_weight, exposure, notes)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- coordinated result -- I1, I2
# ---------------------------------------------------------------------------
def scenario_coordinated_buy_is_approved() -> None:
    result = PortfolioEngine().evaluate(
        _FakeExecutionCoordinatorResult(coordinated=True, action="BUY", position_size=1.0)
    )
    check(
        result.approved is True,
        "I1: a coordinated BUY execution coordinator result produces approved=True",
    )


def scenario_approved_allocation_and_exposure_match_position_size() -> None:
    result = PortfolioEngine().evaluate(
        _FakeExecutionCoordinatorResult(coordinated=True, action="HOLD", position_size=0.5)
    )
    check(
        result.allocation_weight == 0.5 and result.exposure == 0.5,
        "I2: an approved result's allocation_weight and exposure equal "
        "the input's position_size",
    )


# ---------------------------------------------------------------------------
# Group 4 -- not-coordinated result -- I3, I4
# ---------------------------------------------------------------------------
def scenario_not_coordinated_result_is_not_approved() -> None:
    result = PortfolioEngine().evaluate(
        _FakeExecutionCoordinatorResult(coordinated=False)
    )
    check(
        result.approved is False,
        "I3: a not-coordinated execution coordinator result produces approved=False",
    )


def scenario_not_approved_allocation_and_exposure_are_zero() -> None:
    result = PortfolioEngine().evaluate(
        _FakeExecutionCoordinatorResult(coordinated=False, action="SELL", position_size=0.75)
    )
    check(
        result.allocation_weight == 0.0 and result.exposure == 0.0,
        "I4: a not-approved result's allocation_weight and exposure are both 0.0",
    )


# ---------------------------------------------------------------------------
# Group 5 -- notes content -- I5
# ---------------------------------------------------------------------------
def scenario_notes_contains_action_name_when_approved() -> None:
    result = PortfolioEngine().evaluate(
        _FakeExecutionCoordinatorResult(coordinated=True, action="BUY")
    )
    check(
        "BUY" in result.notes,
        "I5: notes contains the action name ('BUY') for an approved result",
    )


def scenario_notes_contains_action_name_when_not_approved() -> None:
    result = PortfolioEngine().evaluate(
        _FakeExecutionCoordinatorResult(coordinated=False, action="SELL")
    )
    check(
        "SELL" in result.notes,
        "I5: notes contains the action name ('SELL') for a not-approved result",
    )


# ---------------------------------------------------------------------------
# Group 6 -- missing attribute -- I6
# ---------------------------------------------------------------------------
def scenario_missing_attribute_raises_portfolio_engine_error() -> None:
    raised_type = None
    try:
        PortfolioEngine().evaluate(_ExecutionCoordinatorResultMissingField())
    except PortfolioEngineError:
        raised_type = PortfolioEngineError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is PortfolioEngineError,
        "I6: PortfolioEngine.evaluate() raises PortfolioEngineError (not "
        "AttributeError) when the execution coordinator result object is "
        "missing a required attribute ('position_size')",
    )


# ---------------------------------------------------------------------------
# Group 7 -- statelessness / determinism -- I10
# ---------------------------------------------------------------------------
def scenario_portfolio_engine_has_no_instance_attributes() -> None:
    engine = PortfolioEngine()
    check(
        vars(engine) == {},
        "I10: a PortfolioEngine instance holds no instance attributes "
        "(vars() is empty), confirming it is safe to reuse across calls",
    )


def scenario_portfolio_engine_is_deterministic() -> None:
    engine = PortfolioEngine()
    first = engine.evaluate(_FakeExecutionCoordinatorResult(coordinated=True, action="HOLD", position_size=0.5))
    second = engine.evaluate(_FakeExecutionCoordinatorResult(coordinated=True, action="HOLD", position_size=0.5))

    check(
        first == second,
        "I10: PortfolioEngine.evaluate() is deterministic -- the same "
        "input execution coordinator result always produces an equal "
        "PortfolioEngineResult",
    )


# ---------------------------------------------------------------------------
# Group 8 -- consistency across actions -- I11
# ---------------------------------------------------------------------------
def scenario_all_actions_approved_when_coordinated() -> None:
    engine = PortfolioEngine()
    all_approved = all(
        engine.evaluate(_FakeExecutionCoordinatorResult(coordinated=True, action=action)).approved is True
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_approved,
        "I11: BUY, HOLD, and SELL all produce approved=True when coordinated",
    )


def scenario_all_actions_not_approved_when_not_coordinated() -> None:
    engine = PortfolioEngine()
    all_not_approved = all(
        engine.evaluate(_FakeExecutionCoordinatorResult(coordinated=False, action=action)).approved is False
        for action in ("BUY", "HOLD", "SELL")
    )
    check(
        all_not_approved,
        "I11: BUY, HOLD, and SELL all produce approved=False when not coordinated",
    )


# ---------------------------------------------------------------------------
# Group 9 -- composition root wiring smoke check -- I12
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_portfolio_engine() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.portfolio_engine, PortfolioEngine),
        "I12: Core.composition_root.build_application() exposes a "
        "PortfolioEngine instance on ApplicationGraph.portfolio_engine",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_portfolio_engine_error_is_agent_error,
        # Group 2
        scenario_result_is_frozen_dataclass,
        scenario_result_has_expected_fields,
        # Group 3
        scenario_coordinated_buy_is_approved,
        scenario_approved_allocation_and_exposure_match_position_size,
        # Group 4
        scenario_not_coordinated_result_is_not_approved,
        scenario_not_approved_allocation_and_exposure_are_zero,
        # Group 5
        scenario_notes_contains_action_name_when_approved,
        scenario_notes_contains_action_name_when_not_approved,
        # Group 6
        scenario_missing_attribute_raises_portfolio_engine_error,
        # Group 7
        scenario_portfolio_engine_has_no_instance_attributes,
        scenario_portfolio_engine_is_deterministic,
        # Group 8
        scenario_all_actions_approved_when_coordinated,
        scenario_all_actions_not_approved_when_not_coordinated,
        # Group 9
        scenario_composition_root_exposes_portfolio_engine,
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
    print(f"STAGE L25 PORTFOLIO ENGINE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())