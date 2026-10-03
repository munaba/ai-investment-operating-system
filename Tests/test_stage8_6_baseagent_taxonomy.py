"""
Stage 8.6 proof suite -- BaseAgent Runtime Integration (taxonomy-aware
except clause, Option A: additive, no behavior change).

Scope (per this session's design decision, Option A):
  - BaseAgent.run()'s single ``except Exception`` is split into explicit
    branches for ApprovalDenied, ApprovalPending, ActorTerminatedError, and
    the remaining generic Exception -- but every branch still does exactly
    the same thing: ``self._set_state(AgentState.ERROR); raise``.
  - AgentState gains NO new values. The guard clause in run() (raise
    AgentStateError while in ERROR) is untouched. The exception itself is
    still propagated unchanged (bare ``raise``), exactly as before Stage 8.6.
  - Runtime and Executor are untouched by this stage (Stage 8.5 already
    proved Runtime -> Executor taxonomy correctness in
    test_stage8_5_approval_taxonomy.py). This suite proves the BaseAgent
    layer on top of that, using minimal Executor test doubles that raise
    each taxonomy exception directly -- BaseAgent only depends on
    Executor's public ``execute()``/``create_actor()`` surface (duck
    typed), so a test double is the correct isolation boundary here,
    exactly as ``FakeProvider``/``FixedPlan`` are used in
    Tests/test_stage8_3.py.

Cakupan:
  1. ApprovalDenied raised by Executor.execute() during CALLING_TOOL ->
     propagates through BaseAgent.run() unchanged, state ends ERROR.
  2. ApprovalPending -- same shape as #1.
  3. ActorTerminatedError -- same shape as #1.
  4. Plain, unrelated Exception (regression: the generic branch still
     works exactly as before Stage 8.6).
  5. reset() recovers from ERROR after each of the three new branches,
     exactly like it already does for generic exceptions (Stage 8.3.1
     semantics unchanged: memory cleared, _actor_id severed, back to IDLE).
  6. AgentStateError guard still fires while stuck in ERROR, regardless of
     which branch put the agent there.
  7. No new AgentState value was introduced (explicit negative check).
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import ApprovalDenied, ApprovalPending
from Core.runtime import ActorTerminatedError
from Agents.base_agent import AgentStateError, BaseAgent
from Agents.executor import Executor
from Agents.memory import ConversationMemory
from Agents.planner import Plan
from Agents.state import AgentState
from Providers import Message, MessageRole, ProviderResponse


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
# Test doubles -- minimal, duck-typed to what BaseAgent actually calls.
# ---------------------------------------------------------------------------
class FakeProvider:
    def generate(self, messages, **kwargs) -> ProviderResponse:
        return ProviderResponse(text="ok")


class FixedPlan:
    def __init__(self, tool_name: str, provider: FakeProvider) -> None:
        self._plan = Plan(use_tool=True, provider=provider, tool_name=tool_name)

    def plan(self, message: Message, provider_name: Optional[str] = None, requirement: Optional[object] = None) -> Plan:
        return self._plan

    def select_provider(self, provider_name: Optional[str] = None) -> FakeProvider:
        return self._plan.provider


class _RaisingExecutorDouble:
    """Executor test double: create_actor() succeeds trivially,
    execute() always raises a pre-set exception instance. BaseAgent only
    ever calls these two methods on its ``_executor`` -- this double
    satisfies exactly that surface, nothing more (no real Runtime
    involved; Runtime/Executor correctness is Stage 8.1-8.5's proof, not
    this suite's)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.create_actor_calls = 0
        self.execute_calls = 0

    def create_actor(self, task: bytes) -> str:
        self.create_actor_calls += 1
        return "fake-actor-id"

    def execute(self, tool_name, *args, actor_id=None, **kwargs):
        self.execute_calls += 1
        raise self._exc


class DummyAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "stage8-6-dummy-agent"


def _build_agent(executor) -> DummyAgent:
    provider = FakeProvider()
    planner = FixedPlan(tool_name="whatever", provider=provider)
    memory = ConversationMemory()
    return DummyAgent(planner=planner, memory=memory, executor=executor)


def _run_and_capture(agent: DummyAgent):
    """Run once, return the exception instance actually raised (or None)."""
    try:
        agent.run(Message(role=MessageRole.USER, content="do the thing"))
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


# ---------------------------------------------------------------------------
# 1. ApprovalDenied propagates, state ends ERROR
# ---------------------------------------------------------------------------
def scenario_approval_denied_propagates() -> None:
    original = ApprovalDenied("denied by policy", details={"tool_name": "whatever"})
    executor = _RaisingExecutorDouble(original)
    agent = _build_agent(executor)

    raised = _run_and_capture(agent)

    check(raised is original, "ApprovalDenied instance propagates through BaseAgent.run() unchanged (same object, bare `raise`)")
    check(agent.state == AgentState.ERROR, "AgentState is ERROR after ApprovalDenied (unchanged: still the ERROR branch)")
    check(executor.execute_calls == 1, "Executor.execute() was called exactly once")


# ---------------------------------------------------------------------------
# 2. ApprovalPending propagates, state ends ERROR
# ---------------------------------------------------------------------------
def scenario_approval_pending_propagates() -> None:
    original = ApprovalPending("awaiting approval", details={"tool_name": "whatever"})
    executor = _RaisingExecutorDouble(original)
    agent = _build_agent(executor)

    raised = _run_and_capture(agent)

    check(raised is original, "ApprovalPending instance propagates through BaseAgent.run() unchanged")
    check(agent.state == AgentState.ERROR, "AgentState is ERROR after ApprovalPending")


# ---------------------------------------------------------------------------
# 3. ActorTerminatedError propagates, state ends ERROR
# ---------------------------------------------------------------------------
def scenario_actor_terminated_propagates() -> None:
    original = ActorTerminatedError("fake-actor-id")
    executor = _RaisingExecutorDouble(original)
    agent = _build_agent(executor)

    raised = _run_and_capture(agent)

    check(raised is original, "ActorTerminatedError instance propagates through BaseAgent.run() unchanged")
    check(agent.state == AgentState.ERROR, "AgentState is ERROR after ActorTerminatedError")


# ---------------------------------------------------------------------------
# 4. Regression: an unrelated, generic exception still works exactly the
#    same (the final `except Exception` branch, unchanged from pre-8.6).
# ---------------------------------------------------------------------------
def scenario_generic_exception_regression() -> None:
    original = RuntimeError("some unrelated tool crash")
    executor = _RaisingExecutorDouble(original)
    agent = _build_agent(executor)

    raised = _run_and_capture(agent)

    check(raised is original, "A plain RuntimeError still propagates unchanged (generic except Exception branch untouched)")
    check(agent.state == AgentState.ERROR, "AgentState is ERROR after a generic exception (unchanged)")


# ---------------------------------------------------------------------------
# 5. reset() recovers identically after each of the three new branches
# ---------------------------------------------------------------------------
def scenario_reset_recovers_after_each_branch() -> None:
    for exc_factory, label in [
        (lambda: ApprovalDenied("denied", details={}), "ApprovalDenied"),
        (lambda: ApprovalPending("pending", details={}), "ApprovalPending"),
        (lambda: ActorTerminatedError("fake-actor-id"), "ActorTerminatedError"),
    ]:
        executor = _RaisingExecutorDouble(exc_factory())
        agent = _build_agent(executor)
        _run_and_capture(agent)
        check(agent.state == AgentState.ERROR, f"[{label}] state is ERROR before reset()")

        agent.reset()

        check(agent.state == AgentState.IDLE, f"[{label}] state returns to IDLE after reset()")
        check(agent.actor_id is None, f"[{label}] _actor_id severed after reset() (Stage 8.3.1 semantics unchanged)")


# ---------------------------------------------------------------------------
# 6. AgentStateError guard still fires while stuck in ERROR, regardless of
#    which branch produced it.
# ---------------------------------------------------------------------------
def scenario_agent_state_error_guard_still_fires() -> None:
    executor = _RaisingExecutorDouble(ApprovalDenied("denied", details={}))
    agent = _build_agent(executor)
    _run_and_capture(agent)
    check(agent.state == AgentState.ERROR, "Agent is in ERROR after ApprovalDenied, precondition for this scenario")

    raised = None
    try:
        agent.run(Message(role=MessageRole.USER, content="try again"))
    except Exception as exc:  # noqa: BLE001
        raised = exc

    check(isinstance(raised, AgentStateError), "run() raises AgentStateError while stuck in ERROR (from an ApprovalDenied-caused ERROR), guard clause unchanged")


# ---------------------------------------------------------------------------
# 7. No new AgentState value was introduced (Option A explicit guarantee)
# ---------------------------------------------------------------------------
def scenario_no_new_agent_state_values() -> None:
    names = {member.name for member in AgentState}
    expected = {"IDLE", "THINKING", "CALLING_TOOL", "WAITING_PROVIDER", "RESPONDING", "ERROR"}
    check(names == expected, f"AgentState still has exactly the original six values, no AWAITING_APPROVAL/DENIED added (got {sorted(names)})")


def main() -> int:
    scenarios = [
        scenario_approval_denied_propagates,
        scenario_approval_pending_propagates,
        scenario_actor_terminated_propagates,
        scenario_generic_exception_regression,
        scenario_reset_recovers_after_each_branch,
        scenario_agent_state_error_guard_still_fires,
        scenario_no_new_agent_state_values,
    ]

    import traceback

    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE 8.6 BASEAGENT TAXONOMY TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())