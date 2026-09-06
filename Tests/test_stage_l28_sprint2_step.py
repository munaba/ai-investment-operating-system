"""
Phase 2 Sprint 2 proof suite -- AutonomousAgent.step() (one
deterministic autonomous cycle, delegated to RuntimeAnalysisPipeline).
Updated in Phase 2 Sprint 3 (Dependency Injection Cleanup) for the new
constructor-injection call shape: ``step(context)`` rather than
Sprint 2's ``step(runtime_analysis_pipeline, context)``.

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.step`` and
``Orchestration.autonomous_agent.AutonomousCycleResult`` only.
Constructor/validation/lifecycle-state-shape behavior for the ten
L18-L27 dependencies is already covered by
``Tests/test_stage_l28_autonomous_agent.py`` and is not re-verified
here. No real ``RuntimeAnalysisPipeline`` is built -- per ``step()``'s
own duck-typed contract, a plain fake object exposing ``run(context)``
stands in for it, constructor-injected exactly like the ten L18-L27
dependencies. No loop, no scheduling, no threads/async, no
retry/recovery -- all explicitly out of scope.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- step(context) with a successful, constructor-injected
           pipeline: returns AutonomousCycleResult(success=True, ...),
           increments iteration_count by exactly 1, sets
           last_cycle_at, and leaves status as IDLE afterward.
    S2  -- step(context) delegates to the constructor-injected
           runtime_analysis_pipeline.run(context) exactly once,
           passing context through unchanged -- no reimplementation of
           AnalysisPipeline/RuntimeAnalysisPipeline logic.
    S3  -- step(context) with a failing pipeline (run() raises):
           returns AutonomousCycleResult(success=False, ...), does NOT
           increment iteration_count, does NOT update last_cycle_at,
           and leaves status as ERROR.
    S4  -- calling step(context) again while status is ERROR raises
           AutonomousAgentError (no retry/recovery) and does not add
           any further call to the fake pipeline's recorded calls.
    S5  -- constructing an AutonomousAgent with
           runtime_analysis_pipeline=None raises AutonomousAgentError
           (constructor-level validation, Sprint 3); step(None)
           (missing context) also raises AutonomousAgentError without
           calling the pipeline.
    S6  -- AutonomousCycleResult is immutable (frozen) and carries
           only success/timestamp/iteration -- no DecisionEngine/
           DecisionPolicy/PortfolioEngine/LearningLoop internals.
    S7  -- step() never loops: exactly one call to the fake pipeline's
           run() per step() call, no matter how many times step() is
           called across separate agent instances.
    S8  -- AutonomousAgent still defines no run/pause/resume/cancel
           method (step() is the sole new public method).
"""

from __future__ import annotations

import dataclasses
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_agent import (
    AutonomousAgent,
    AutonomousAgentError,
    AutonomousAgentStatus,
    AutonomousCycleResult,
)

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []

_FIELD_NAMES = (
    "reflection",
    "decision_engine",
    "decision_policy",
    "policy_guard",
    "execution_intent",
    "execution_planner",
    "execution_coordinator",
    "portfolio_engine",
    "portfolio_risk",
    "learning_loop",
)


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


class _FakeComponent:
    """Stand-in for one of the ten L18-L27 constructor dependencies.
    AutonomousAgent.step() never touches these, so an empty class with
    an identity is sufficient (same fixture shape as Sprint 1's
    suite)."""

    def __init__(self, name: str) -> None:
        self.name = name


def _make_agent(runtime_analysis_pipeline: object) -> AutonomousAgent:
    return AutonomousAgent(
        runtime_analysis_pipeline=runtime_analysis_pipeline,
        # Phase 2, Sprint 7: goal_planner is now a required 12th
        # constructor argument (same validation pattern as
        # runtime_analysis_pipeline above). step() itself never
        # touches it -- see Tests/test_stage_l28_sprint7_goalplanner.py
        # for its own dedicated regression suite.
        goal_planner=_FakeComponent("goal_planner"),
        **{name: _FakeComponent(name) for name in _FIELD_NAMES},
    )


class _FakeContext:
    """Stand-in for a ServiceContext. AutonomousAgent.step() treats it
    as an opaque object and passes it straight through."""

    def __init__(self, tag: str = "ctx") -> None:
        self.tag = tag


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records exactly what it
    was called with, and either returns a fixed string or raises,
    depending on construction -- never itself runs AnalysisPipeline or
    any real stage."""

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: List[object] = []

    def run(self, context: object) -> str:
        self.calls.append(context)
        if self.should_fail:
            raise RuntimeError("simulated RuntimeAnalysisPipeline failure")
        return "ok"


# ---------------------------------------------------------------------------
# S1/S2 -- successful cycle
# ---------------------------------------------------------------------------
def scenario_successful_step_advances_state_and_delegates() -> None:
    pipeline = _FakeRuntimeAnalysisPipeline(should_fail=False)
    agent = _make_agent(pipeline)
    context = _FakeContext("first")

    result = agent.step(context)

    check(
        isinstance(result, AutonomousCycleResult) and result.success is True,
        "S1: step() returns AutonomousCycleResult(success=True) on a "
        "successful pipeline run",
    )
    check(
        agent.iteration_count == 1,
        "S1: iteration_count is incremented by exactly 1 on success",
    )
    check(
        result.iteration == agent.iteration_count,
        "S1: the returned result's iteration matches agent.iteration_count",
    )
    check(
        agent.last_cycle_at is not None and agent.last_cycle_at == result.timestamp,
        "S1: last_cycle_at is set and matches the result's timestamp",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "S1: status returns to IDLE after a successful cycle",
    )
    check(
        pipeline.calls == [context],
        "S2: step() delegated to runtime_analysis_pipeline.run() exactly "
        "once, passing the same context object through unchanged",
    )


# ---------------------------------------------------------------------------
# S3 -- failing cycle
# ---------------------------------------------------------------------------
def scenario_failing_step_sets_error_without_advancing() -> None:
    pipeline = _FakeRuntimeAnalysisPipeline(should_fail=True)
    agent = _make_agent(pipeline)
    context = _FakeContext("will-fail")

    result = agent.step(context)

    check(
        isinstance(result, AutonomousCycleResult) and result.success is False,
        "S3: step() returns AutonomousCycleResult(success=False) when "
        "the pipeline raises",
    )
    check(
        agent.iteration_count == 0,
        "S3: iteration_count is NOT incremented when the cycle fails",
    )
    check(
        agent.last_cycle_at is None,
        "S3: last_cycle_at is NOT updated when the cycle fails",
    )
    check(
        agent.status is AutonomousAgentStatus.ERROR,
        "S3: status becomes ERROR after a failed cycle",
    )
    check(
        result.iteration == 0,
        "S3: the returned result's iteration reflects the unchanged "
        "iteration_count (0)",
    )


# ---------------------------------------------------------------------------
# S4 -- no retry/recovery
# ---------------------------------------------------------------------------
def scenario_step_refuses_when_in_error_status() -> None:
    failing_pipeline = _FakeRuntimeAnalysisPipeline(should_fail=True)
    agent = _make_agent(failing_pipeline)
    agent.step(_FakeContext("first-failure"))
    check(
        agent.status is AutonomousAgentStatus.ERROR,
        "S4 precondition: agent is in ERROR status after the first "
        "failed cycle",
    )

    raised = False
    try:
        agent.step(_FakeContext("retry-attempt"))
    except AutonomousAgentError:
        raised = True
    check(
        raised,
        "S4: calling step() again while status is ERROR raises "
        "AutonomousAgentError (no retry/recovery)",
    )
    check(
        len(failing_pipeline.calls) == 1,
        "S4: the refused step() call never reached the pipeline's "
        "run() a second time",
    )
    check(
        agent.iteration_count == 0 and agent.last_cycle_at is None,
        "S4: iteration_count/last_cycle_at are untouched by the "
        "refused call",
    )


# ---------------------------------------------------------------------------
# S5 -- None-argument validation
# ---------------------------------------------------------------------------
def scenario_step_rejects_none_arguments() -> None:
    # Constructor-level check (Sprint 3): runtime_analysis_pipeline=None
    # is now rejected at construction time, not at step() call time.
    raised_for_none_pipeline = False
    try:
        AutonomousAgent(
            runtime_analysis_pipeline=None,
            goal_planner=_FakeComponent("goal_planner"),
            **{name: _FakeComponent(name) for name in _FIELD_NAMES},
        )
    except AutonomousAgentError:
        raised_for_none_pipeline = True
    check(
        raised_for_none_pipeline,
        "S5: constructing with runtime_analysis_pipeline=None raises "
        "AutonomousAgentError",
    )

    # step()-level check: context=None is still rejected by step()
    # itself.
    pipeline = _FakeRuntimeAnalysisPipeline(should_fail=False)
    agent = _make_agent(pipeline)
    raised_for_none_context = False
    try:
        agent.step(None)
    except AutonomousAgentError:
        raised_for_none_context = True
    check(
        raised_for_none_context,
        "S5: step(None) raises AutonomousAgentError",
    )
    check(
        pipeline.calls == [],
        "S5: neither None-argument case reached the pipeline's run()",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "S5: rejecting a None context does not change status away "
        "from IDLE",
    )


# ---------------------------------------------------------------------------
# S6 -- AutonomousCycleResult shape
# ---------------------------------------------------------------------------
def scenario_cycle_result_is_frozen_and_minimal() -> None:
    pipeline = _FakeRuntimeAnalysisPipeline(should_fail=False)
    agent = _make_agent(pipeline)
    result = agent.step(_FakeContext())

    check(
        dataclasses.is_dataclass(result),
        "S6: AutonomousCycleResult is a dataclass",
    )
    frozen = False
    try:
        result.success = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(frozen, "S6: AutonomousCycleResult is frozen/immutable")

    field_names = {f.name for f in dataclasses.fields(result)}
    check(
        field_names == {"success", "timestamp", "iteration"},
        "S6: AutonomousCycleResult exposes exactly success/timestamp/"
        "iteration -- no DecisionEngine/DecisionPolicy/PortfolioEngine/"
        "LearningLoop internals",
    )


# ---------------------------------------------------------------------------
# S7 -- exactly one delegated call per step(), no looping
# ---------------------------------------------------------------------------
def scenario_step_never_loops() -> None:
    pipeline = _FakeRuntimeAnalysisPipeline(should_fail=False)
    agent_a = _make_agent(pipeline)
    agent_b = _make_agent(pipeline)

    agent_a.step(_FakeContext("a"))
    agent_b.step(_FakeContext("b"))

    check(
        len(pipeline.calls) == 2,
        "S7: two separate step() calls produced exactly two delegated "
        "run() calls -- one per step(), no internal looping",
    )
    check(
        agent_a.iteration_count == 1 and agent_b.iteration_count == 1,
        "S7: each agent's own iteration_count advanced by exactly 1 "
        "for its own single step() call",
    )


# ---------------------------------------------------------------------------
# S8 -- still no run/pause/resume/cancel
# ---------------------------------------------------------------------------
def scenario_still_defines_no_other_execution_methods() -> None:
    # 'run' removed from this forbidden list in Phase 2 Sprint 4,
    # which adds it as a sanctioned second public method -- see
    # Tests/test_stage_l28_sprint4_run.py for its dedicated coverage.
    # 'pause'/'resume' removed in Phase 2 Sprint 9, which adds them as
    # sanctioned lifecycle-control methods -- see
    # Tests/test_stage_l28_sprint9_pause_resume.py for its dedicated
    # coverage.
    forbidden = ("execute", "start", "loop", "invoke", "cancel")
    none_present = all(not hasattr(AutonomousAgent, name) for name in forbidden)
    check(
        none_present,
        "S8: AutonomousAgent still defines no execute/start/loop/"
        "invoke/cancel method -- step() (Sprint 2), run() (Sprint 4), "
        "and pause()/resume() (Sprint 9) are the only public methods "
        "added so far",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_successful_step_advances_state_and_delegates,
        scenario_failing_step_sets_error_without_advancing,
        scenario_step_refuses_when_in_error_status,
        scenario_step_rejects_none_arguments,
        scenario_cycle_result_is_frozen_and_minimal,
        scenario_step_never_loops,
        scenario_still_defines_no_other_execution_methods,
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
    print(f"PHASE 2 SPRINT 2 STEP() RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())