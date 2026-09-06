"""
Stage L28A proof suite -- AutonomousAgent Foundation (Stage L28A,
additive component).

Scope: dedicated regression suite for
``Orchestration.autonomous_agent.AutonomousAgentError`` and
``Orchestration.autonomous_agent.AutonomousAgent`` only. No
Composition Root wiring assertions beyond a plain
construction/attribute smoke check, no automatic invocation from
StockAgent/RuntimeAnalysisPipeline, no execution of any aggregated
component, no threads, no loops -- all explicitly out of scope for
L28A.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l18_reflection.py`` through
``test_stage_l27_learning_loop.py``: a global pass/fail counter, plain
fixtures, and a ``main()`` runner. No ``unittest`` module is used,
matching the existing convention.

Invariant coverage:
    I1  -- [Updated, Phase 2 Sprint 1] AutonomousAgent is a normal,
           mutable class (no longer a frozen dataclass). Field
           reassignment succeeds rather than raising
           FrozenInstanceError. Superseded per the approved Phase 2
           Architecture, which requires converting AutonomousAgent
           into the future autonomous runtime's base class.
    I2  -- AutonomousAgent exposes exactly ten dependency attributes,
           one per aggregated stage (L18-L27), set from the
           constructor arguments. (Checked via instance attributes
           rather than ``dataclasses.fields`` now that the class is
           no longer a dataclass; the underlying guarantee -- exactly
           these ten dependencies, injected as given -- is unchanged.)
    I3  -- each field, once constructed, holds the exact same object
           reference that was passed in (no copying/wrapping).
    I4  -- constructing with any single field set to None raises
           AutonomousAgentError.
    I5  -- AutonomousAgentError subclasses Core.exceptions.AgentError.
    I6  -- [Updated, Phase 2 Sprint 2] AutonomousAgent defines no
           run/execute/start/loop/invoke/pause/resume/cancel method.
           ``step()`` (Sprint 2) is the sole, explicitly-scoped
           exception -- one deterministic cycle, delegated to
           RuntimeAnalysisPipeline; see
           Tests/test_stage_l28_sprint2_step.py for its own dedicated
           regression suite.
    I7  -- [Updated, Phase 2 Sprint 1] AutonomousAgent now owns
           internal lifecycle state in addition to its ten declared
           dependency attributes (a ``status`` of type
           AutonomousAgentStatus, starting at IDLE, plus the other
           minimal Sprint 1 state). It no longer holds *only* the ten
           dependency attributes. Superseded per the approved Phase 2
           Architecture, which requires introducing minimal internal
           lifecycle state.
    I8  -- constructing an AutonomousAgent performs no observable side
           effect on the components it references (they are untouched
           plain objects after construction).
    I9  -- Core.composition_root.build_application() exposes an
           AutonomousAgent instance on ApplicationGraph.autonomous_agent.
    I10 -- each field on the composition-root-built AutonomousAgent is
           the exact same instance as the corresponding standalone
           ApplicationGraph field (e.g. autonomous_agent.decision_engine
           is graph.decision_engine).

Note (Phase 2, Sprint 1): I1 and I7 above were rewritten from their
Stage L28A form because the approved Phase 2 Architecture (Sprint 1)
explicitly requires converting AutonomousAgent from a frozen dataclass
into a normal class carrying minimal internal lifecycle state, which
is mutually exclusive with the original "frozen" / "no attributes
beyond declared fields" wording. All other invariants (constructor
signature, dependency validation, dependency injection/identity,
composition_root wiring, absence of run/execute/start/step/loop/
invoke/pause/resume/cancel methods) are unchanged and still enforced
below.
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
from Orchestration.autonomous_agent import AutonomousAgent, AutonomousAgentError

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

# Phase 2, Sprint 3: runtime_analysis_pipeline is now an 11th
# constructor-injected dependency, validated the same way as the ten
# above, but held privately (self._runtime_analysis_pipeline) rather
# than as a public dependency attribute -- so it is listed separately
# from _FIELD_NAMES (which still enumerates only the ten public
# stage-component attributes checked by I2/I3). Phase 2, Sprint 7:
# goal_planner is a 12th constructor-injected dependency, added the
# same way -- held privately (self._goal_planner), validated non-None
# identically, and likewise listed here rather than in _FIELD_NAMES.
_ALL_CONSTRUCTOR_ARGS = _FIELD_NAMES + ("runtime_analysis_pipeline", "goal_planner")


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
    """A plain marker object standing in for one aggregated stage
    component. AutonomousAgent never calls into it, so an empty class
    with an identity is sufficient."""

    def __init__(self, name: str) -> None:
        self.name = name


def _make_components() -> dict:
    return {name: _FakeComponent(name) for name in _ALL_CONSTRUCTOR_ARGS}


# ---------------------------------------------------------------------------
# Group 1 -- AutonomousAgentError -- I5
# ---------------------------------------------------------------------------
def scenario_autonomous_agent_error_is_agent_error() -> None:
    check(
        issubclass(AutonomousAgentError, AgentError),
        "I5: AutonomousAgentError subclasses Core.exceptions.AgentError, "
        "same convention as LearningLoopError/PortfolioRiskError/"
        "PortfolioEngineError/ExecutionCoordinatorError/"
        "ExecutionPlannerError/ExecutionIntentError/PolicyGuardError/"
        "DecisionPolicyError/DecisionEngineError/ReflectionError",
    )
    err = AutonomousAgentError("boom")
    check(isinstance(err, Exception), "AutonomousAgentError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- AutonomousAgent (value shape) -- I1, I2 [Phase 2 Sprint 1]
# ---------------------------------------------------------------------------
def scenario_is_mutable_class() -> None:
    agent = AutonomousAgent(**_make_components())

    check(
        not dataclasses.is_dataclass(agent),
        "I1: AutonomousAgent is no longer a dataclass (Phase 2 Sprint 1 "
        "converted it to a normal class)",
    )

    reassigned = False
    try:
        agent.reflection = _FakeComponent("other")  # type: ignore[misc]
        reassigned = agent.reflection.name == "other"
    except Exception:  # noqa: BLE001
        reassigned = False
    check(
        reassigned,
        "I1: AutonomousAgent is mutable -- field reassignment succeeds "
        "(no FrozenInstanceError), per Phase 2 Sprint 1",
    )


def scenario_has_expected_fields() -> None:
    agent = AutonomousAgent(**_make_components())
    field_names = {
        name for name in _FIELD_NAMES if hasattr(agent, name)
    }
    check(
        field_names == set(_FIELD_NAMES),
        "I2: AutonomousAgent exposes exactly ten dependency attributes, "
        "one per aggregated stage (reflection, decision_engine, "
        "decision_policy, policy_guard, execution_intent, "
        "execution_planner, execution_coordinator, portfolio_engine, "
        "portfolio_risk, learning_loop)",
    )


# ---------------------------------------------------------------------------
# Group 3 -- reference identity -- I3
# ---------------------------------------------------------------------------
def scenario_fields_hold_exact_same_references() -> None:
    components = _make_components()
    agent = AutonomousAgent(**components)
    all_identical = all(
        getattr(agent, name) is components[name] for name in _FIELD_NAMES
    )
    check(
        all_identical,
        "I3: each field, once constructed, holds the exact same "
        "object reference that was passed in (no copying/wrapping)",
    )


# ---------------------------------------------------------------------------
# Group 4 -- None-field validation -- I4
# ---------------------------------------------------------------------------
def scenario_none_component_raises_autonomous_agent_error() -> None:
    all_raised = True
    for missing_field in _ALL_CONSTRUCTOR_ARGS:
        components = _make_components()
        components[missing_field] = None
        raised = False
        try:
            AutonomousAgent(**components)
        except AutonomousAgentError:
            raised = True
        except Exception:  # noqa: BLE001
            raised = False
        if not raised:
            all_raised = False
            break
    check(
        all_raised,
        "I4: constructing with any single field set to None raises "
        "AutonomousAgentError -- including the Phase 2 Sprint 3 "
        "constructor-injected 'runtime_analysis_pipeline' argument",
    )


# ---------------------------------------------------------------------------
# Group 5 -- no execution-shaped methods -- I6
# ---------------------------------------------------------------------------
def scenario_defines_no_execution_methods() -> None:
    # Phase 2 Sprint 2 implements step() (one deterministic cycle,
    # delegated to RuntimeAnalysisPipeline -- see
    # Tests/test_stage_l28_sprint2_step.py for its dedicated
    # regression suite), Phase 2 Sprint 4 implements run() (a
    # deterministic driver around repeated step() calls -- see
    # Tests/test_stage_l28_sprint4_run.py), and Phase 2 Sprint 9
    # implements pause()/resume() (lifecycle control only -- see
    # Tests/test_stage_l28_sprint9_pause_resume.py), so none of the
    # three is any longer in this forbidden list. execute/start/loop/
    # invoke/cancel and friends remain out of scope for future
    # sprints.
    forbidden = ("execute", "start", "loop", "invoke", "cancel")
    none_present = all(not hasattr(AutonomousAgent, name) for name in forbidden)
    check(
        none_present,
        "I6: AutonomousAgent defines no execute/start/loop/invoke/"
        "cancel method -- step() (Sprint 2), run() (Sprint 4), and "
        "pause()/resume() (Sprint 9) are the sole exceptions, and "
        "none of them invokes the ten aggregated L18-L27 components "
        "directly, only delegates to RuntimeAnalysisPipeline (step()), "
        "step() itself (run()), or pure status transitions "
        "(pause()/resume())",
    )
    check(
        hasattr(AutonomousAgent, "step"),
        "I6b: AutonomousAgent defines exactly the one public method "
        "added in Phase 2 Sprint 2, step()",
    )


# ---------------------------------------------------------------------------
# Group 6 -- owns internal lifecycle state -- I7 [Phase 2 Sprint 1]
# ---------------------------------------------------------------------------
def scenario_instance_owns_lifecycle_state() -> None:
    from Orchestration.autonomous_agent import AutonomousAgentStatus

    agent = AutonomousAgent(**_make_components())
    instance_dict_keys = set(vars(agent).keys())

    still_has_all_dependencies = set(_FIELD_NAMES).issubset(instance_dict_keys)
    has_extra_state = len(instance_dict_keys - set(_FIELD_NAMES)) > 0
    check(
        still_has_all_dependencies and has_extra_state,
        "I7: AutonomousAgent now owns internal state beyond its ten "
        "dependency attributes (Phase 2 Sprint 1 lifecycle state), "
        "while still holding all ten dependencies",
    )

    check(
        hasattr(agent, "status") and isinstance(agent.status, AutonomousAgentStatus),
        "I7: AutonomousAgent exposes a 'status' of type "
        "AutonomousAgentStatus",
    )
    check(
        agent.status is AutonomousAgentStatus.IDLE,
        "I7: a freshly constructed AutonomousAgent starts in the IDLE "
        "lifecycle status",
    )


# ---------------------------------------------------------------------------
# Group 7 -- no side effects on components -- I8
# ---------------------------------------------------------------------------
def scenario_construction_has_no_side_effect_on_components() -> None:
    components = _make_components()
    snapshot = {name: vars(comp).copy() for name, comp in components.items()}
    AutonomousAgent(**components)
    unchanged = all(
        vars(components[name]) == snapshot[name] for name in _FIELD_NAMES
    )
    check(
        unchanged,
        "I8: constructing an AutonomousAgent performs no observable "
        "side effect on the components it references",
    )


# ---------------------------------------------------------------------------
# Group 8 -- composition root wiring smoke check -- I9, I10
# ---------------------------------------------------------------------------
def scenario_composition_root_exposes_autonomous_agent() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    check(
        isinstance(graph.autonomous_agent, AutonomousAgent),
        "I9: Core.composition_root.build_application() exposes an "
        "AutonomousAgent instance on ApplicationGraph.autonomous_agent",
    )


def scenario_autonomous_agent_fields_match_graph_fields() -> None:
    from Core.composition_root import build_application

    graph = build_application()
    agent = graph.autonomous_agent
    check(
        agent.reflection is graph.reflector
        and agent.decision_engine is graph.decision_engine
        and agent.decision_policy is graph.decision_policy
        and agent.policy_guard is graph.policy_guard
        and agent.execution_intent is graph.execution_intent
        and agent.execution_planner is graph.execution_planner
        and agent.execution_coordinator is graph.execution_coordinator
        and agent.portfolio_engine is graph.portfolio_engine
        and agent.portfolio_risk is graph.portfolio_risk
        and agent.learning_loop is graph.learning_loop,
        "I10: each field on the composition-root-built AutonomousAgent "
        "is the exact same instance as the corresponding standalone "
        "ApplicationGraph field",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_autonomous_agent_error_is_agent_error,
        # Group 2
        scenario_is_mutable_class,
        scenario_has_expected_fields,
        # Group 3
        scenario_fields_hold_exact_same_references,
        # Group 4
        scenario_none_component_raises_autonomous_agent_error,
        # Group 5
        scenario_defines_no_execution_methods,
        # Group 6
        scenario_instance_owns_lifecycle_state,
        # Group 7
        scenario_construction_has_no_side_effect_on_components,
        # Group 8
        scenario_composition_root_exposes_autonomous_agent,
        scenario_autonomous_agent_fields_match_graph_fields,
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
    print(f"STAGE L28A AUTONOMOUS AGENT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())