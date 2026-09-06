"""
Phase 2 Sprint 4 proof suite -- AutonomousAgent.run() (a deterministic
driver around repeated step() calls).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.run`` only.
Constructor/validation/lifecycle-state-shape behavior for the ten
L18-L27 dependencies plus the Sprint 3 constructor-injected
``runtime_analysis_pipeline`` is already covered by
``Tests/test_stage_l28_autonomous_agent.py``, and ``step()``'s own
dedicated behavior is already covered by
``Tests/test_stage_l28_sprint2_step.py`` -- neither is re-verified
here beyond what run() itself needs. No real ``RuntimeAnalysisPipeline``
is built -- a plain fake object exposing ``run(context)`` stands in
for it, constructor-injected exactly like the ten L18-L27 dependencies.
No loop-internal sleep, no scheduling, no threads/async, no retry, no
approval handling, no pause/resume/cancel -- all explicitly out of
scope for Sprint 4.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    R1  -- AutonomousAgent's constructor signature is unchanged from
           Sprint 3 (still exactly the ten L18-L27 dependencies plus
           ``runtime_analysis_pipeline``, no new constructor
           parameter was added for run()).
    R2  -- run(context, max_iterations=1) with an all-succeeding
           pipeline: returns a 1-tuple of AutonomousCycleResult(
           success=True).
    R3  -- run(context, max_iterations=5) with an all-succeeding
           pipeline: returns a 5-tuple, every element success=True.
    R4  -- iteration_count increments by exactly max_iterations across
           a single successful run() call.
    R5  -- the returned value's length always equals max_iterations
           for an all-succeeding run.
    R6  -- every element of the returned tuple is an
           AutonomousCycleResult instance.
    R7  -- run() rejects max_iterations < 1 (0, negative, and
           non-int) with AutonomousAgentError, without calling the
           pipeline at all.
    R8  -- run() rejects context=None with AutonomousAgentError,
           without calling the pipeline at all.
    R9  -- while a step() call is in progress inside run(), status is
           RUNNING (observed via the fake pipeline capturing
           agent.status at call time).
    R10 -- status is IDLE after a fully successful run() call
           completes.
    R11 -- when a delegated step() call raises (because a prior
           iteration in the same run already left status ERROR),
           status is (re-)confirmed as ERROR.
    R12 -- that same raised exception propagates out of run()
           unchanged -- never swallowed, never replaced with a
           different exception type.
    R13 -- calling run() multiple times on the same agent accumulates
           iteration_count cumulatively across calls.
    R14 -- across every step() call inside a single run(), the exact
           same RuntimeAnalysisPipeline instance is delegated to --
           run() never constructs a new one.
    R15 -- the RuntimeAnalysisPipeline instance used by run() is the
           exact same singleton object that was passed into the
           agent's constructor (identity check), confirming
           run()/step() reuse the injected singleton rather than
           building their own.
    R16 -- return type is a tuple, not a list.
"""

from __future__ import annotations

import inspect
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

# Phase 2, Sprint 7: goal_planner is now a 12th constructor-injected
# dependency (unrelated to run() itself -- see GoalPlanner integration
# regression suite, Tests/test_stage_l28_sprint7_goalplanner.py). R1
# below still checks that run() itself introduced no constructor
# parameter; the tuple is kept in sync with whatever the constructor
# currently accepts.
_EXPECTED_CONSTRUCTOR_PARAMS = _FIELD_NAMES + ("runtime_analysis_pipeline", "goal_planner")


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
    Neither step() nor run() ever touches these."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeContext:
    """Stand-in for a ServiceContext. Treated as opaque and passed
    through unchanged."""

    def __init__(self, tag: str = "ctx") -> None:
        self.tag = tag


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call
    (including a snapshot of the agent's status at call time, for
    R9), and either returns a fixed string or raises depending on
    construction -- never itself runs AnalysisPipeline or any real
    stage."""

    def __init__(self, agent_holder: List[AutonomousAgent], should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: List[object] = []
        self.statuses_at_call: List[AutonomousAgentStatus] = []
        # agent is set after construction (see _make_agent) since the
        # fake pipeline must exist before the agent it is injected
        # into -- a one-element list is used as a simple settable box.
        self._agent_holder = agent_holder

    def run(self, context: object) -> str:
        self.calls.append(context)
        agent = self._agent_holder[0] if self._agent_holder else None
        if agent is not None:
            self.statuses_at_call.append(agent.status)
        if self.should_fail:
            raise RuntimeError("simulated RuntimeAnalysisPipeline failure")
        return "ok"


def _make_agent(pipeline: _FakeRuntimeAnalysisPipeline) -> AutonomousAgent:
    agent = AutonomousAgent(
        runtime_analysis_pipeline=pipeline,
        # Phase 2, Sprint 7: goal_planner is now a required 12th
        # constructor argument. run()/step() never touch it -- see
        # Tests/test_stage_l28_sprint7_goalplanner.py.
        goal_planner=_FakeComponent("goal_planner"),
        **{name: _FakeComponent(name) for name in _FIELD_NAMES},
    )
    return agent


def _make_agent_and_pipeline(should_fail: bool = False):
    holder: List[AutonomousAgent] = []
    pipeline = _FakeRuntimeAnalysisPipeline(holder, should_fail=should_fail)
    agent = _make_agent(pipeline)
    holder.append(agent)
    return agent, pipeline


# ---------------------------------------------------------------------------
# R1 -- constructor unchanged from Sprint 3
# ---------------------------------------------------------------------------
def scenario_constructor_signature_unchanged() -> None:
    params = list(inspect.signature(AutonomousAgent.__init__).parameters.keys())
    params_without_self = tuple(params[1:])
    check(
        params_without_self == _EXPECTED_CONSTRUCTOR_PARAMS,
        "R1: AutonomousAgent.__init__ signature carries no constructor "
        "parameter of run()'s own -- still exactly the ten L18-L27 "
        "dependencies plus 'runtime_analysis_pipeline' and (Phase 2 "
        "Sprint 7) 'goal_planner', neither of which run() itself added",
    )


# ---------------------------------------------------------------------------
# R2 -- run(1)
# ---------------------------------------------------------------------------
def scenario_run_single_iteration() -> None:
    agent, pipeline = _make_agent_and_pipeline(should_fail=False)
    result = agent.run(_FakeContext("r2"), max_iterations=1)
    check(
        isinstance(result, tuple) and len(result) == 1,
        "R2: run(context, max_iterations=1) returns a 1-tuple",
    )
    check(
        result[0].success is True,
        "R2: the single result reports success=True for an "
        "all-succeeding pipeline",
    )


# ---------------------------------------------------------------------------
# R3/R4/R5/R6 -- run(5)
# ---------------------------------------------------------------------------
def scenario_run_five_iterations() -> None:
    agent, pipeline = _make_agent_and_pipeline(should_fail=False)
    result = agent.run(_FakeContext("r3"), max_iterations=5)

    check(
        isinstance(result, tuple) and len(result) == 5,
        "R3/R5: run(context, max_iterations=5) returns a 5-tuple",
    )
    check(
        all(r.success is True for r in result),
        "R3: every collected result reports success=True",
    )
    check(
        agent.iteration_count == 5,
        "R4: iteration_count increments by exactly max_iterations "
        "(5) across the run() call",
    )
    check(
        all(isinstance(r, AutonomousCycleResult) for r in result),
        "R6: every element of the returned tuple is an "
        "AutonomousCycleResult instance",
    )
    check(
        isinstance(result, tuple) and not isinstance(result, list),
        "R16: run() returns a tuple, not a list",
    )
    check(
        len(pipeline.calls) == 5,
        "R14: the same pipeline instance was delegated to exactly 5 "
        "times, once per step()",
    )


# ---------------------------------------------------------------------------
# R7 -- invalid max_iterations
# ---------------------------------------------------------------------------
def scenario_run_rejects_invalid_max_iterations() -> None:
    for bad_value in (0, -1, -5, 1.5, "3", None):
        agent, pipeline = _make_agent_and_pipeline(should_fail=False)
        raised = False
        try:
            agent.run(_FakeContext("r7"), max_iterations=bad_value)
        except AutonomousAgentError:
            raised = True
        except Exception:  # noqa: BLE001
            raised = False
        check(
            raised,
            f"R7: run(context, max_iterations={bad_value!r}) raises "
            "AutonomousAgentError",
        )
        check(
            pipeline.calls == [],
            f"R7: the rejected max_iterations={bad_value!r} call "
            "never reached the pipeline's run()",
        )


# ---------------------------------------------------------------------------
# R8 -- None context
# ---------------------------------------------------------------------------
def scenario_run_rejects_none_context() -> None:
    agent, pipeline = _make_agent_and_pipeline(should_fail=False)
    raised = False
    try:
        agent.run(None, max_iterations=3)
    except AutonomousAgentError:
        raised = True
    check(raised, "R8: run(None, max_iterations=3) raises AutonomousAgentError")
    check(
        pipeline.calls == [],
        "R8: the rejected None-context call never reached the "
        "pipeline's run()",
    )


# ---------------------------------------------------------------------------
# R9/R10 -- status RUNNING during execution, IDLE afterward
# ---------------------------------------------------------------------------
def scenario_status_running_during_and_idle_after() -> None:
    agent, pipeline = _make_agent_and_pipeline(should_fail=False)
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "R10 precondition: agent starts IDLE before run()",
    )

    agent.run(_FakeContext("r9"), max_iterations=3)

    check(
        len(pipeline.statuses_at_call) == 3
        and all(s is AutonomousAgentStatus.RUNNING for s in pipeline.statuses_at_call),
        "R9: status observed as RUNNING at the moment of every "
        "delegated pipeline.run() call inside run()",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "R10: status is IDLE after a fully successful run() call "
        "completes",
    )


# ---------------------------------------------------------------------------
# R11/R12 -- ERROR transition and exception propagation
# ---------------------------------------------------------------------------
def scenario_run_propagates_exception_and_sets_error() -> None:
    agent, pipeline = _make_agent_and_pipeline(should_fail=True)

    raised = False
    try:
        agent.run(_FakeContext("r11"), max_iterations=3)
    except AutonomousAgentError:
        raised = True
    except Exception:  # noqa: BLE001
        raised = False

    check(
        raised,
        "R12: when a delegated step() call raises (guarded re-entry "
        "after a prior failed iteration), that AutonomousAgentError "
        "propagates out of run() unchanged -- not swallowed, not "
        "replaced",
    )
    check(
        agent.status is AutonomousAgentStatus.ERROR,
        "R11: status is (re-)confirmed as ERROR when run() re-raises",
    )
    check(
        len(pipeline.calls) == 1,
        "R11/R12: only the first iteration actually reached the "
        "pipeline (it failed and set status=ERROR internally); the "
        "second iteration's step() call raised before calling the "
        "pipeline again -- run() never retries",
    )


# ---------------------------------------------------------------------------
# R13 -- multiple runs accumulate
# ---------------------------------------------------------------------------
def scenario_multiple_runs_accumulate() -> None:
    agent, pipeline = _make_agent_and_pipeline(should_fail=False)

    agent.run(_FakeContext("first-run"), max_iterations=3)
    check(
        agent.iteration_count == 3,
        "R13: iteration_count is 3 after the first run(3)",
    )

    agent.run(_FakeContext("second-run"), max_iterations=2)
    check(
        agent.iteration_count == 5,
        "R13: iteration_count accumulates to 5 after a second run(2) "
        "on the same agent",
    )
    check(
        len(pipeline.calls) == 5,
        "R13: the same injected pipeline recorded all 5 delegated "
        "calls across both run() calls",
    )


# ---------------------------------------------------------------------------
# R14/R15 -- no pipeline reconstruction, injected singleton reused
# ---------------------------------------------------------------------------
def scenario_run_reuses_injected_singleton_pipeline() -> None:
    agent, pipeline = _make_agent_and_pipeline(should_fail=False)

    check(
        agent._runtime_analysis_pipeline is pipeline,
        "R15: the agent's held pipeline reference is the exact same "
        "object passed into the constructor",
    )

    agent.run(_FakeContext("r15-a"), max_iterations=2)
    pipeline_ref_after_first_run = agent._runtime_analysis_pipeline

    agent.run(_FakeContext("r15-b"), max_iterations=2)
    pipeline_ref_after_second_run = agent._runtime_analysis_pipeline

    check(
        pipeline_ref_after_first_run is pipeline
        and pipeline_ref_after_second_run is pipeline,
        "R14/R15: across every step() call in every run(), the exact "
        "same constructor-injected RuntimeAnalysisPipeline singleton "
        "is reused -- run() never constructs a new one",
    )
    check(
        len(pipeline.calls) == 4,
        "R14: all 4 delegated calls (2 runs x 2 iterations) landed "
        "on that single pipeline instance",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_signature_unchanged,
        scenario_run_single_iteration,
        scenario_run_five_iterations,
        scenario_run_rejects_invalid_max_iterations,
        scenario_run_rejects_none_context,
        scenario_status_running_during_and_idle_after,
        scenario_run_propagates_exception_and_sets_error,
        scenario_multiple_runs_accumulate,
        scenario_run_reuses_injected_singleton_pipeline,
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
    print(f"PHASE 2 SPRINT 4 RUN() RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())