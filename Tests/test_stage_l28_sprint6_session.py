"""
Phase 2 Sprint 6 proof suite -- AutonomousAgent session metadata
(start_session()/end_session()).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgent.start_session`` and
``AutonomousAgent.end_session`` only. Constructor/validation/
lifecycle-state-shape behavior for the ten L18-L27 dependencies plus
the Sprint 3 constructor-injected ``runtime_analysis_pipeline`` is
already covered by ``Tests/test_stage_l28_autonomous_agent.py``,
``step()``'s own dedicated behavior by
``Tests/test_stage_l28_sprint2_step.py``, ``run()``'s own dedicated
behavior by ``Tests/test_stage_l28_sprint4_run.py``, and goal
ownership by ``Tests/test_stage_l28_sprint5_goal.py`` -- none of that
is re-verified here beyond what session metadata itself needs. No
real ``RuntimeAnalysisPipeline`` is built -- a plain fake object
exposing ``run(context)`` stands in for it, constructor-injected
exactly like the ten L18-L27 dependencies. No persistence, no
scheduling, no GoalPlanner integration of any kind -- all explicitly
out of scope for Sprint 6.

Follows the same scenario-based, no-pytest, no-external-mocks style
as the other Stage L1x-L2x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    SS1  -- session_id and session_started_at are both None by
            default on a freshly constructed agent.
    SS2  -- start_session() returns a session id, and session_id
            reflects that same value afterward.
    SS3  -- the returned/stored session_id is a valid UUID string
            (parses via uuid.UUID(...), and str(uuid.UUID(x)) == x).
    SS4  -- session_started_at is populated with a timezone-aware
            UTC datetime after start_session().
    SS5  -- calling start_session() a second time while a session is
            already active raises AutonomousAgentError, and does not
            change the existing session_id/session_started_at.
    SS6  -- end_session() clears session_id back to None.
    SS7  -- end_session() called twice in a row is not an error.
    SS8  -- session_started_at is cleared back to None by
            end_session().
    SS9  -- start_session()/end_session() never change goal.
    SS10 -- start_session()/end_session() never change
            iteration_count.
    SS11 -- start_session()/end_session() never change status.
    SS12 -- start_session()/end_session() never call the injected
            RuntimeAnalysisPipeline's run().
    SS13 -- run() still works normally after start_session()/
            end_session() have been called, and session state is
            unaffected by run() itself.
    SS14 -- step() still works normally after start_session()/
            end_session() have been called, and session state is
            unaffected by step() itself.
    SS15 -- starting a new session after ending a previous one
            produces a different session_id (fresh identity each
            time).
"""

from __future__ import annotations

import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.autonomous_agent import (
    AutonomousAgent,
    AutonomousAgentError,
    AutonomousAgentStatus,
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
    Neither step(), run(), start_session(), nor end_session() ever
    touches these."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeContext:
    """Stand-in for a ServiceContext. Treated as opaque and passed
    through unchanged."""

    def __init__(self, tag: str = "ctx") -> None:
        self.tag = tag


class _FakeRuntimeAnalysisPipeline:
    """Stand-in for RuntimeAnalysisPipeline. Records every call --
    never itself runs AnalysisPipeline or any real stage. Used here
    only to prove start_session()/end_session() never reach it, and
    that run()/step() still work unchanged after session mutation."""

    def __init__(self) -> None:
        self.calls: List[object] = []

    def run(self, context: object) -> str:
        self.calls.append(context)
        return "ok"


def _make_agent(pipeline: _FakeRuntimeAnalysisPipeline) -> AutonomousAgent:
    return AutonomousAgent(
        runtime_analysis_pipeline=pipeline,
        # Phase 2, Sprint 7: goal_planner is now a required 12th
        # constructor argument. start_session()/end_session() never
        # touch it -- see Tests/test_stage_l28_sprint7_goalplanner.py.
        goal_planner=_FakeComponent("goal_planner"),
        **{name: _FakeComponent(name) for name in _FIELD_NAMES},
    )


def _make_agent_and_pipeline():
    pipeline = _FakeRuntimeAnalysisPipeline()
    agent = _make_agent(pipeline)
    return agent, pipeline


# ---------------------------------------------------------------------------
# SS1 -- defaults
# ---------------------------------------------------------------------------
def scenario_default_session_is_none() -> None:
    agent, _ = _make_agent_and_pipeline()
    check(agent.session_id is None, "SS1: session_id is None on a fresh agent")
    check(
        agent.session_started_at is None,
        "SS1: session_started_at is None on a fresh agent",
    )


# ---------------------------------------------------------------------------
# SS2 -- start_session() stores and returns the id
# ---------------------------------------------------------------------------
def scenario_start_session_returns_and_stores_id() -> None:
    agent, _ = _make_agent_and_pipeline()
    returned = agent.start_session()
    check(
        isinstance(returned, str) and returned == agent.session_id,
        "SS2: start_session() returns a session id equal to the "
        "stored session_id",
    )


# ---------------------------------------------------------------------------
# SS3 -- UUID format
# ---------------------------------------------------------------------------
def scenario_session_id_is_valid_uuid() -> None:
    agent, _ = _make_agent_and_pipeline()
    session_id = agent.start_session()
    valid = False
    try:
        parsed = uuid.UUID(session_id)
        valid = str(parsed) == session_id
    except (ValueError, AttributeError, TypeError):
        valid = False
    check(valid, "SS3: session_id is a valid, canonically-formatted UUID string")


# ---------------------------------------------------------------------------
# SS4 -- timestamp populated
# ---------------------------------------------------------------------------
def scenario_session_started_at_populated() -> None:
    agent, _ = _make_agent_and_pipeline()
    before = datetime.now(timezone.utc)
    agent.start_session()
    after = datetime.now(timezone.utc)

    check(
        isinstance(agent.session_started_at, datetime),
        "SS4: session_started_at is a datetime after start_session()",
    )
    check(
        agent.session_started_at.tzinfo is not None,
        "SS4: session_started_at is timezone-aware (UTC)",
    )
    check(
        before <= agent.session_started_at <= after,
        "SS4: session_started_at falls within the window surrounding "
        "the start_session() call",
    )


# ---------------------------------------------------------------------------
# SS5 -- second start while active raises
# ---------------------------------------------------------------------------
def scenario_second_start_while_active_raises() -> None:
    agent, _ = _make_agent_and_pipeline()
    first_id = agent.start_session()
    first_started_at = agent.session_started_at

    raised = False
    try:
        agent.start_session()
    except AutonomousAgentError:
        raised = True
    except Exception:  # noqa: BLE001
        raised = False

    check(
        raised,
        "SS5: start_session() while a session is already active "
        "raises AutonomousAgentError",
    )
    check(
        agent.session_id == first_id,
        "SS5: session_id is unchanged after the rejected second "
        "start_session() call",
    )
    check(
        agent.session_started_at == first_started_at,
        "SS5: session_started_at is unchanged after the rejected "
        "second start_session() call",
    )


# ---------------------------------------------------------------------------
# SS6/SS8 -- end_session() clears id and timestamp
# ---------------------------------------------------------------------------
def scenario_end_session_clears_id_and_timestamp() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.start_session()
    agent.end_session()
    check(agent.session_id is None, "SS6: end_session() clears session_id to None")
    check(
        agent.session_started_at is None,
        "SS8: end_session() clears session_started_at to None",
    )


# ---------------------------------------------------------------------------
# SS7 -- end twice is not an error
# ---------------------------------------------------------------------------
def scenario_end_session_twice_is_idempotent() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.start_session()
    agent.end_session()
    raised = False
    try:
        agent.end_session()
    except Exception:  # noqa: BLE001
        raised = True
    check(not raised, "SS7: calling end_session() twice does not raise")
    check(agent.session_id is None, "SS7: session_id is still None after ending twice")


# ---------------------------------------------------------------------------
# SS9/SS10/SS11 -- goal/iteration_count/status untouched
# ---------------------------------------------------------------------------
def scenario_session_mutation_leaves_other_state_untouched() -> None:
    agent, _ = _make_agent_and_pipeline()
    agent.set_goal("Monitor BBCA")

    goal_before = agent.goal
    iteration_before = agent.iteration_count
    status_before = agent.status

    agent.start_session()
    check(agent.goal == goal_before, "SS9: goal unchanged immediately after start_session()")
    check(
        agent.iteration_count == iteration_before,
        "SS10: iteration_count unchanged immediately after start_session()",
    )
    check(
        agent.status == status_before,
        "SS11: status unchanged immediately after start_session()",
    )

    agent.end_session()
    check(agent.goal == goal_before, "SS9: goal unchanged immediately after end_session()")
    check(
        agent.iteration_count == iteration_before,
        "SS10: iteration_count unchanged immediately after end_session()",
    )
    check(
        agent.status == status_before,
        "SS11: status unchanged immediately after end_session()",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "SS11: status remains the initial IDLE value throughout",
    )


# ---------------------------------------------------------------------------
# SS12 -- pipeline never called
# ---------------------------------------------------------------------------
def scenario_session_mutation_never_calls_pipeline() -> None:
    agent, pipeline = _make_agent_and_pipeline()

    agent.start_session()
    agent.end_session()
    agent.end_session()
    agent.start_session()
    try:
        agent.start_session()
    except AutonomousAgentError:
        pass

    check(
        pipeline.calls == [],
        "SS12: start_session()/end_session() never call the injected "
        "RuntimeAnalysisPipeline's run()",
    )


# ---------------------------------------------------------------------------
# SS13 -- run() still works after session mutation
# ---------------------------------------------------------------------------
def scenario_run_still_works_after_session_mutation() -> None:
    agent, pipeline = _make_agent_and_pipeline()

    session_id = agent.start_session()
    results = agent.run(_FakeContext("ss13"), max_iterations=2)

    check(
        len(results) == 2 and all(r.success for r in results),
        "SS13: run() still completes normally after start_session() "
        "was called earlier",
    )
    check(
        agent.session_id == session_id,
        "SS13: run() does not modify the active session_id",
    )
    check(
        len(pipeline.calls) == 2,
        "SS13: run() still delegates to the injected pipeline exactly "
        "as before",
    )

    agent.end_session()
    check(
        agent.session_id is None,
        "SS13: end_session() after run() still clears the session normally",
    )


# ---------------------------------------------------------------------------
# SS14 -- step() still works after session mutation
# ---------------------------------------------------------------------------
def scenario_step_still_works_after_session_mutation() -> None:
    agent, pipeline = _make_agent_and_pipeline()

    session_id = agent.start_session()
    result = agent.step(_FakeContext("ss14"))

    check(result.success is True, "SS14: step() still succeeds after start_session()")
    check(
        agent.session_id == session_id,
        "SS14: step() does not modify the active session_id",
    )
    check(
        agent.iteration_count == 1,
        "SS14: step() still increments iteration_count normally",
    )

    agent.end_session()
    result2 = agent.step(_FakeContext("ss14-b"))
    check(
        result2.success is True,
        "SS14: step() still succeeds after end_session()",
    )
    check(
        agent.session_id is None,
        "SS14: session_id remains None after a further successful step()",
    )
    check(
        len(pipeline.calls) == 2,
        "SS14: both step() calls reached the injected pipeline",
    )


# ---------------------------------------------------------------------------
# SS15 -- fresh identity per session
# ---------------------------------------------------------------------------
def scenario_new_session_gets_fresh_identity() -> None:
    agent, _ = _make_agent_and_pipeline()

    first_id = agent.start_session()
    agent.end_session()
    second_id = agent.start_session()

    check(
        first_id != second_id,
        "SS15: starting a new session after ending a previous one "
        "produces a different session_id",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_default_session_is_none,
        scenario_start_session_returns_and_stores_id,
        scenario_session_id_is_valid_uuid,
        scenario_session_started_at_populated,
        scenario_second_start_while_active_raises,
        scenario_end_session_clears_id_and_timestamp,
        scenario_end_session_twice_is_idempotent,
        scenario_session_mutation_leaves_other_state_untouched,
        scenario_session_mutation_never_calls_pipeline,
        scenario_run_still_works_after_session_mutation,
        scenario_step_still_works_after_session_mutation,
        scenario_new_session_gets_fresh_identity,
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
    print(f"PHASE 2 SPRINT 6 SESSION METADATA RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())