

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Iterator

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.exceptions import AgentError, ProviderError, ToolError  # noqa: E402

from Providers.base_provider import BaseProvider  # noqa: E402
from Providers.message import Message, MessageRole  # noqa: E402
from Providers.response import ProviderResponse, Usage  # noqa: E402
from Providers.provider_manager import provider_manager  # noqa: E402

from Agents.state import AgentState  # noqa: E402
from Agents.memory import ConversationMemory  # noqa: E402
from Agents.tool_registry import Tool, tool_registry, ToolNotFoundError  # noqa: E402
from Agents.executor import Executor, ToolExecutionError  # noqa: E402
from Agents.planner import Planner, Plan, PlannerError  # noqa: E402
from Agents.base_agent import BaseAgent, AgentStateError  # noqa: E402

from Services.base_service import BaseService  # noqa: E402
from Services.service_context import ServiceContext  # noqa: E402
from Services.service_result import ServiceResult  # noqa: E402




class MockProvider(BaseProvider):
    """Concrete BaseProvider test double. Never touches the network."""

    def __init__(self, provider_name: str = "mock_provider", reply_text: Optional[str] = None) -> None:
        super().__init__()
        self._name = provider_name
        self._reply_text = reply_text
        self._connected = False
        self.generate_call_count = 0
        self.health_check_call_count = 0
        self.last_messages: List[Message] = []

    @property
    def name(self) -> str:
        return self._name

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        self.generate_call_count += 1
        self.last_messages = list(messages)
        last_content = messages[-1].content if messages else ""
        text = self._reply_text if self._reply_text is not None else f"mock-response: {last_content}"
        return ProviderResponse(
            text=text,
            finish_reason="stop",
            model=self._name,
            usage=Usage(input_tokens=len(messages), output_tokens=1, total_tokens=len(messages) + 1),
        )

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        raise NotImplementedError("MockProvider does not implement streaming.")

    def count_tokens(self, messages: List[Message]) -> int:
        return sum(len(m.content.split()) for m in messages)

    def health_check(self) -> bool:
        self.health_check_call_count += 1
        self._record_health_check(healthy=True)
        return True


class FailingMockProvider(MockProvider):
    """A MockProvider whose generate() always fails, to drive negative tests."""

    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        self.generate_call_count += 1
        self.last_messages = list(messages)
        raise ProviderError("FailingMockProvider deliberately failed to generate a response.")

    def health_check(self) -> bool:
        self.health_check_call_count += 1
        self._record_health_check(healthy=False, error="deliberate failure")
        return False


class DummyService(BaseService):
    """Concrete BaseService test double standing in for a real service."""

    def __init__(self, service_name: str = "dummy_service", fail: bool = False) -> None:
        self._name = service_name
        self._fail = fail
        self.execute_call_count = 0
        self.last_context: Optional[ServiceContext] = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Test double standing in for a real BaseService implementation."

    @property
    def category(self) -> str:
        return "test"

    def execute(self, context: ServiceContext) -> ServiceResult:
        self.execute_call_count += 1
        self.last_context = context
        if self._fail:
            return ServiceResult.fail(
                RuntimeError("DummyService deliberately failed"),
                message=f"DummyService '{self._name}' deliberately failed.",
            )
        query = context.get_metadata("query", context.user_input)
        return ServiceResult.ok(
            data={"echo": query, "handled_by": self._name},
            message=f"DummyService '{self._name}' handled '{query}'.",
        )

    def health_check(self) -> bool:
        return not self._fail


def make_service_tool_handler(
    service: BaseService,
    agent_name: str,
    provider_name: str,
    raise_on_service_failure: bool = True,
):
    """Build a Tool handler that wraps a Service call -- the pattern every
    real Tool in this framework is expected to follow (Executor only
    forwards ``message.content`` to the handler; the handler is
    responsible for building the ``ServiceContext`` a service needs --
    see Architecture Notes at the bottom of this file).
    """

    def handler(user_text: str) -> Any:
        context = ServiceContext(
            agent_name=agent_name,
            provider_name=provider_name,
            request_id=str(uuid.uuid4()),
            user_input=user_text,
            metadata={"query": user_text},
        )
        result = service.execute(context)
        if not result.success:
            if raise_on_service_failure:
                raise RuntimeError(f"Service '{service.name}' failed: {result.message}")
            return result
        return result.data

    return handler


def broken_tool_handler(user_text: str) -> Any:
    """A tool handler that always raises, to drive Executor-level failure tests."""
    raise ValueError("broken_tool_handler always raises.")


class DummyAgent(BaseAgent):
    """Minimal concrete BaseAgent, built purely on the real, unmodified engine.

    Overrides only ``_set_state`` (a non-abstract hook already meant to be
    called by subclasses via the normal state-machine flow) to record the
    transition history for verification -- this does not change what
    state values exist or when they fire, it only observes them.
    """

    def __init__(self, planner: Planner, memory: ConversationMemory, executor: Executor, agent_name: str) -> None:
        super().__init__(planner, memory, executor)
        self._agent_name = agent_name
        self.state_transitions: List[Tuple[Optional[AgentState], AgentState]] = []

    @property
    def name(self) -> str:
        return self._agent_name

    def _set_state(self, new_state: AgentState) -> None:
        old_state = self.state
        super()._set_state(new_state)
        self.state_transitions.append((old_state, new_state))


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


_RESULTS: List[CheckResult] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    _RESULTS.append(CheckResult(name=name, passed=bool(condition), detail=detail))


def run_no_leak(name: str, fn: Any) -> Any:
    """Run fn(); fail the check if ANY exception escapes.

    Used for calls that, per the framework's own documented contracts,
    must never raise (Service.execute/health_check, Provider.generate on
    a healthy provider, Executor.execute against a valid tool, etc).
    """
    try:
        result = fn()
        check(f"{name}: no exception leaked", True)
        return result
    except Exception as exc:  # noqa: BLE001 - this IS the thing under test
        check(f"{name}: no exception leaked", False, f"{type(exc).__name__}: {exc}")
        return None


def run_expect_raise(name: str, exception_types: Tuple[type, ...], fn: Any) -> Optional[Exception]:
    """Run fn(); PASS only if it raises one of exception_types (nothing else, nothing missing).

    This is how negative tests confirm a failure is classified into the
    framework's own exception hierarchy rather than leaking an
    unclassified/unexpected error.
    """
    try:
        fn()
        check(name, False, "expected an exception but none was raised")
        return None
    except exception_types as exc:
        check(name, True, f"raised {type(exc).__name__}: {exc}")
        return exc
    except Exception as exc:  # noqa: BLE001 - wrong exception type is itself a failure
        check(name, False, f"raised unexpected {type(exc).__name__} instead of {exception_types}: {exc}")
        return exc


def make_context(**metadata: Any) -> ServiceContext:
    return ServiceContext(
        agent_name="e2e_test",
        provider_name="none",
        request_id=str(uuid.uuid4()),
        user_input="e2e test run",
        metadata=metadata,
    )

PROVIDER_OK_NAME = "mock_provider_ok_e2e"
PROVIDER_FAILING_NAME = "mock_provider_failing_e2e"


@dataclass
class Fixtures:
    provider_ok: MockProvider
    provider_failing: FailingMockProvider
    service_ok: DummyService
    service_failing: DummyService
    tool_ok: Tool
    tool_failing: Tool
    tool_broken: Tool


def setup_fixtures() -> Fixtures:
    provider_ok = MockProvider(provider_name=PROVIDER_OK_NAME)
    provider_failing = FailingMockProvider(provider_name=PROVIDER_FAILING_NAME)

    # 1. Register Provider ke ProviderManager.
    run_no_leak(
        "provider_manager.register(provider_ok)",
        lambda: provider_manager.register(PROVIDER_OK_NAME, provider_ok, overwrite=True),
    )
    run_no_leak(
        "provider_manager.register(provider_failing)",
        lambda: provider_manager.register(PROVIDER_FAILING_NAME, provider_failing, overwrite=True),
    )
    check("provider_manager.exists(provider_ok)", provider_manager.exists(PROVIDER_OK_NAME))
    check("provider_manager.exists(provider_failing)", provider_manager.exists(PROVIDER_FAILING_NAME))
    check("provider_manager.get returns the same instance", provider_manager.get(PROVIDER_OK_NAME) is provider_ok)

    service_ok = DummyService(service_name="dummy_service_ok_e2e", fail=False)
    service_failing = DummyService(service_name="dummy_service_failing_e2e", fail=True)

    # 2 & 3. Register Service sebagai Tool, lalu register Tool ke ToolRegistry.
    tool_ok = Tool(
        name="dummy_lookup_ok_e2e",
        description="Looks something up via DummyService (always succeeds).",
        handler=make_service_tool_handler(
            service_ok, agent_name="agent_ok_e2e", provider_name=PROVIDER_OK_NAME, raise_on_service_failure=True
        ),
    )
    tool_failing = Tool(
        name="dummy_lookup_failing_e2e",
        description="Looks something up via DummyService (always fails).",
        handler=make_service_tool_handler(
            service_failing,
            agent_name="agent_service_fail_e2e",
            provider_name=PROVIDER_OK_NAME,
            raise_on_service_failure=True,
        ),
    )
    tool_broken = Tool(
        name="broken_tool_direct_e2e",
        description="A tool whose handler always raises, regardless of any service.",
        handler=broken_tool_handler,
    )

    for tool in (tool_ok, tool_failing, tool_broken):
        run_no_leak(f"tool_registry.register({tool.name})", lambda t=tool: tool_registry.register(t))
        check(f"tool_registry.exists({tool.name})", tool_registry.exists(tool.name))
        check(f"tool_registry.get({tool.name}) returns the same instance", tool_registry.get(tool.name) is tool)

    return Fixtures(
        provider_ok=provider_ok,
        provider_failing=provider_failing,
        service_ok=service_ok,
        service_failing=service_failing,
        tool_ok=tool_ok,
        tool_failing=tool_failing,
        tool_broken=tool_broken,
    )


def test_unit_level_positive(fx: Fixtures) -> None:
    """Exercise Planner / Executor / Service / Provider individually before
    trusting the full agent pipeline -- isolates *where* a failure would be
    if the full run later misbehaves.
    """
    planner = Planner(provider_manager, tool_registry)

    # 6. Planner menghasilkan plan.
    message = Message(role=MessageRole.USER, content=f"please use {fx.tool_ok.name} for BBCA")
    plan = run_no_leak("planner.plan(message)", lambda: planner.plan(message, provider_name=PROVIDER_OK_NAME))
    check("planner produced a Plan instance", isinstance(plan, Plan))
    if isinstance(plan, Plan):
        check("plan.use_tool is True (tool name present in message)", plan.use_tool is True)
        check("plan.tool_name matches the registered tool", plan.tool_name == fx.tool_ok.name)
        check("plan.provider resolved to the registered MockProvider", plan.provider is fx.provider_ok)

    # 7 & 8. Executor mengambil tool -> Tool memanggil Service.
    executor = Executor(tool_registry)
    calls_before = fx.service_ok.execute_call_count
    tool_result = run_no_leak(
        "executor.execute(tool_ok.name, ...)", lambda: executor.execute(fx.tool_ok.name, "unit level BBCA query")
    )
    check("executor.execute returned the tool's data", isinstance(tool_result, dict) and "echo" in tool_result)

    # 9. Service mengembalikan ServiceResult (checked directly + indirectly).
    check(
        "service_ok.execute() was actually invoked by the tool handler",
        fx.service_ok.execute_call_count == calls_before + 1,
    )
    direct_context = make_context(query="direct call")
    direct_result = run_no_leak("service_ok.execute(direct_context)", lambda: fx.service_ok.execute(direct_context))
    check("service_ok.execute returns a ServiceResult", isinstance(direct_result, ServiceResult))
    if isinstance(direct_result, ServiceResult):
        check("service_ok direct call succeeded", direct_result.success is True)
        check("service_ok direct call payload contains echo", direct_result.data.get("echo") == "direct call")

    # 10. Provider menghasilkan ProviderResponse.
    provider_response = run_no_leak(
        "provider_ok.generate([message])", lambda: fx.provider_ok.generate([message])
    )
    check("provider_ok.generate returns a ProviderResponse", isinstance(provider_response, ProviderResponse))
    if isinstance(provider_response, ProviderResponse):
        check("ProviderResponse.text is a non-empty string", bool(provider_response.text))


def test_full_pipeline_positive(fx: Fixtures) -> Dict[str, Any]:
    """Full pipeline through a real, concrete BaseAgent (DummyAgent).

    Covers points 1-11 of the task end-to-end, plus state-transition and
    "no leaked exception" verification.
    """
    planner = Planner(provider_manager, tool_registry)
    memory = ConversationMemory()
    executor = Executor(tool_registry)
    agent = DummyAgent(planner, memory, executor, agent_name="agent_full_pipeline_e2e")

    check("agent.state starts as IDLE", agent.state == AgentState.IDLE)

    message = Message(role=MessageRole.USER, content=f"please use {fx.tool_ok.name} for BBCA history")
    provider_calls_before = fx.provider_ok.generate_call_count
    service_calls_before = fx.service_ok.execute_call_count

    # 5. Jalankan agent.run().
    response = run_no_leak("agent.run(message)", lambda: agent.run(message, provider_name=PROVIDER_OK_NAME))

    check("agent.run() returned a non-empty string", isinstance(response, str) and bool(response))
    check(
        "final response text came from the provider (contains mock-response marker)",
        isinstance(response, str) and response.startswith("mock-response:"),
    )

    # 8/9/10 (call-count evidence): tool -> service -> provider were each invoked exactly once.
    check("executor invoked the tool -> service exactly once", fx.service_ok.execute_call_count == service_calls_before + 1)
    check("provider.generate() was invoked exactly once", fx.provider_ok.generate_call_count == provider_calls_before + 1)
    check(
        "provider received the tool result folded into conversation history",
        any(m.role == MessageRole.TOOL for m in fx.provider_ok.last_messages),
    )

    # 11. Agent mengembalikan response akhir; agent settles back to IDLE.
    check("agent.state returns to IDLE after a successful run", agent.state == AgentState.IDLE)

    # State machine: IDLE -> ... -> IDLE. The framework has no literal
    # "RUNNING" state (see Architecture Notes) -- verify the real granular
    # transitions instead.
    transition_sequence = [new for _old, new in agent.state_transitions]
    check(
        "state transitions include THINKING, CALLING_TOOL, WAITING_PROVIDER, RESPONDING, IDLE in order",
        transition_sequence
        == [
            AgentState.THINKING,
            AgentState.CALLING_TOOL,
            AgentState.WAITING_PROVIDER,
            AgentState.RESPONDING,
            AgentState.IDLE,
        ],
        detail=str(transition_sequence),
    )
    check("agent.state_transitions starts from IDLE", agent.state_transitions[0][0] == AgentState.IDLE if agent.state_transitions else False)

    # Memory actually recorded both turns.
    history = memory.history()
    check("conversation memory recorded the user message", len(history) >= 1 and history[0].message.role == MessageRole.USER)
    check(
        "conversation memory recorded the assistant reply",
        len(history) >= 2 and history[-1].message.role == MessageRole.ASSISTANT,
    )

    return {"agent": agent, "response": response}


# =========================================================================
# Section C -- negative tests
# =========================================================================


def test_provider_not_found(fx: Fixtures) -> None:
    """Provider tidak ditemukan -- both at Planner level and full-pipeline level."""
    planner = Planner(provider_manager, tool_registry)

    run_expect_raise(
        "planner.select_provider raises ProviderError for an unregistered name",
        (ProviderError,),
        lambda: planner.select_provider("totally_unknown_provider_xyz"),
    )

    memory = ConversationMemory()
    executor = Executor(tool_registry)
    agent = DummyAgent(planner, memory, executor, agent_name="agent_provider_missing_e2e")
    message = Message(role=MessageRole.USER, content="hello, no tool trigger in here")

    run_expect_raise(
        "agent.run() propagates ProviderError when provider_name is unknown",
        (ProviderError,),
        lambda: agent.run(message, provider_name="totally_unknown_provider_xyz"),
    )
    check("agent state is ERROR after provider-not-found failure", agent.state == AgentState.ERROR)

    run_expect_raise(
        "agent.run() raises AgentStateError while stuck in ERROR state",
        (AgentStateError,),
        lambda: agent.run(message, provider_name=PROVIDER_OK_NAME),
    )
    agent.reset()
    check("agent.state returns to IDLE after reset()", agent.state == AgentState.IDLE)


def test_tool_not_found(fx: Fixtures) -> None:
    """Tool tidak ditemukan -- both at Executor level and full-pipeline level."""
    executor = Executor(tool_registry)
    run_expect_raise(
        "executor.execute raises ToolNotFoundError for an unregistered tool",
        (ToolNotFoundError,),
        lambda: executor.execute("this_tool_was_never_registered_xyz", "text"),
    )
    run_expect_raise(
        "tool_registry.get raises ToolNotFoundError directly",
        (ToolNotFoundError,),
        lambda: tool_registry.get("this_tool_was_never_registered_xyz"),
    )

    def always_missing_tool_strategy(_message, _registry):
        return "this_tool_was_never_registered_xyz"

    planner = Planner(provider_manager, tool_registry, tool_trigger_strategy=always_missing_tool_strategy)
    memory = ConversationMemory()
    agent = DummyAgent(planner, memory, executor, agent_name="agent_tool_missing_e2e")
    message = Message(role=MessageRole.USER, content="anything at all")

    run_expect_raise(
        "agent.run() propagates ToolNotFoundError when Planner selects an unregistered tool",
        (ToolNotFoundError,),
        lambda: agent.run(message, provider_name=PROVIDER_OK_NAME),
    )
    check("agent state is ERROR after tool-not-found failure", agent.state == AgentState.ERROR)
    agent.reset()
    check("agent.state returns to IDLE after reset()", agent.state == AgentState.IDLE)


def test_service_failure(fx: Fixtures) -> None:
    """Service gagal -- direct ServiceResult.fail, then full pipeline via the tool wrapper."""
    direct_context = make_context(query="force failure")
    direct_result = run_no_leak(
        "service_failing.execute(direct_context)", lambda: fx.service_failing.execute(direct_context)
    )
    check("service_failing.execute returns a ServiceResult", isinstance(direct_result, ServiceResult))
    if isinstance(direct_result, ServiceResult):
        check("service_failing direct call reports success == False", direct_result.success is False)
        check("service_failing direct call carries an error", direct_result.error is not None)

    planner = Planner(provider_manager, tool_registry)
    memory = ConversationMemory()
    executor = Executor(tool_registry)
    agent = DummyAgent(planner, memory, executor, agent_name="agent_service_fail_e2e")
    message = Message(role=MessageRole.USER, content=f"please use {fx.tool_failing.name} now")

    calls_before = fx.service_failing.execute_call_count
    exc = run_expect_raise(
        "agent.run() propagates ToolExecutionError when the wrapped Service fails",
        (ToolExecutionError,),
        lambda: agent.run(message, provider_name=PROVIDER_OK_NAME),
    )
    check("service_failing.execute() was called even though it failed", fx.service_failing.execute_call_count == calls_before + 1)
    check("ToolExecutionError wraps the original RuntimeError as its cause", isinstance(exc.__cause__, RuntimeError) if exc else False)
    check("agent state is ERROR after service failure", agent.state == AgentState.ERROR)
    agent.reset()
    check("agent.state returns to IDLE after reset()", agent.state == AgentState.IDLE)


def test_executor_failure(fx: Fixtures) -> None:
    """Executor gagal -- a tool handler that raises unconditionally (unrelated to any service)."""
    executor = Executor(tool_registry)
    exc = run_expect_raise(
        "executor.execute wraps a raising handler into ToolExecutionError",
        (ToolExecutionError,),
        lambda: executor.execute(fx.tool_broken.name, "irrelevant"),
    )
    check("ToolExecutionError wraps the original ValueError as its cause", isinstance(exc.__cause__, ValueError) if exc else False)


def test_planner_failure(fx: Fixtures) -> None:
    """Planner gagal -- PlannerError is only raised when NO provider can be
    resolved at all. Temporarily empties the (real, shared) ProviderManager
    singleton and restores it afterwards so later checks are unaffected.
    """
    registered_names = provider_manager.list()
    backup: Dict[str, Any] = {name: provider_manager.get(name) for name in registered_names}
    for name in registered_names:
        provider_manager.unregister(name)
    check("provider_manager is empty for the planner-failure test", provider_manager.list() == [])

    try:
        empty_planner = Planner(provider_manager, tool_registry)
        message = Message(role=MessageRole.USER, content="hello")
        run_expect_raise(
            "planner.plan raises PlannerError when no providers are registered at all",
            (PlannerError,),
            lambda: empty_planner.plan(message),
        )
    finally:
        for name, provider in backup.items():
            provider_manager.register(name, provider, overwrite=True)

    check(
        "all providers were restored after the planner-failure test",
        set(provider_manager.list()) == set(registered_names),
    )


def test_provider_failure(fx: Fixtures) -> None:
    """Provider gagal -- tool/service succeed, but Provider.generate() raises."""
    planner = Planner(provider_manager, tool_registry)
    memory = ConversationMemory()
    executor = Executor(tool_registry)
    agent = DummyAgent(planner, memory, executor, agent_name="agent_provider_fail_e2e")
    message = Message(role=MessageRole.USER, content=f"please use {fx.tool_ok.name} for BBCA")

    service_calls_before = fx.service_ok.execute_call_count
    generate_calls_before = fx.provider_failing.generate_call_count

    exc = run_expect_raise(
        "agent.run() propagates ProviderError when the selected Provider fails",
        (ProviderError,),
        lambda: agent.run(message, provider_name=PROVIDER_FAILING_NAME),
    )
    check("the tool/service still ran before the provider failed", fx.service_ok.execute_call_count == service_calls_before + 1)
    check("provider_failing.generate() was invoked", fx.provider_failing.generate_call_count == generate_calls_before + 1)
    check("agent state is ERROR after provider failure", agent.state == AgentState.ERROR)

    transition_sequence = [new for _old, new in agent.state_transitions]
    check(
        "state transitions reached WAITING_PROVIDER then ERROR (not RESPONDING/IDLE)",
        transition_sequence == [AgentState.THINKING, AgentState.CALLING_TOOL, AgentState.WAITING_PROVIDER, AgentState.ERROR],
        detail=str(transition_sequence),
    )

    agent.reset()
    check("agent.state returns to IDLE after reset()", agent.state == AgentState.IDLE)


# =========================================================================
# Runner / report
# =========================================================================


def _print_report() -> bool:
    passed = [r for r in _RESULTS if r.passed]
    failed = [r for r in _RESULTS if not r.passed]

    print("\n" + "=" * 70)
    print("END-TO-END TEST REPORT - Full Pipeline")
    print("=" * 70)
    for result in _RESULTS:
        status = "PASS" if result.passed else "FAIL"
        line = f"[{status}] {result.name}"
        if result.detail and not result.passed:
            line += f"  -- {result.detail}"
        print(line)

    print("-" * 70)
    print(f"TOTAL: {len(_RESULTS)}  PASSED: {len(passed)}  FAILED: {len(failed)}")
    print("=" * 70)

    overall = "PASS" if not failed else "FAIL"
    print(f"OVERALL RESULT: {overall}")
    print("=" * 70 + "\n")
    return not failed


def main() -> int:
    fx = setup_fixtures()
    test_unit_level_positive(fx)
    test_full_pipeline_positive(fx)
    test_provider_not_found(fx)
    test_tool_not_found(fx)
    test_service_failure(fx)
    test_executor_failure(fx)
    test_planner_failure(fx)
    test_provider_failure(fx)
    success = _print_report()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())