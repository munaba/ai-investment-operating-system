"""
Phase 8 Sprint 82 proof suite -- ``Executor.invoke_current_skill()``'s
local ``tool_context_factory`` now constructs and returns a real
``Orchestration.tool_context.ToolContext`` (``ToolContext(task=None,
parameters={}, metadata={})``) instead of raising
``NotImplementedError`` (Sprint 81's stand-in body). No ``Tool`` is
looked up or executed, and no ``ToolRegistry``/``ToolResolver``/
``ToolManager`` is touched -- this is a pure value-object build.

Compact, table-driven, no-pytest style (55+ invariants in ~350 LOC).
Reuses the Sprint 79/80/81 stand-in conventions: the real
``SkillContext`` rejects ``task=None`` at construction time, so
reaching ``skill.execute()`` at all requires patching the module-level
name ``invoke_current_skill()`` calls (same technique as before). A
second, analogous patch is used for ``ToolContext`` itself: the real
``ToolContext`` (Sprint 51, unchanged) *also* rejects ``task=None`` --
so the factory as specified always raises ``ToolContextError`` when
actually exercised against the real class. This suite verifies both
truths: (a) with the real, unpatched ``ToolContext``, calling the
factory faithfully raises ``ToolContextError`` (proving the factory
body really does attempt ``ToolContext(task=None, parameters={},
metadata={})`` and nothing else); and (b) with a patched, permissive
``ToolContext`` stand-in, the factory's call shape and values
(``task=None``, ``parameters={}``, ``metadata={}``) and its "always a
fresh instance, never cached" contract are verified precisely, per the
sprint's specification.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Orchestration.executor as executor_module
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.execution_session import ExecutionSession, ExecutionSessionError
from Orchestration.executor import Executor, ExecutorError
from Orchestration.skill_context import SkillContextError
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.skill_result import SkillResult
from Orchestration.task_manager import TaskManager
from Orchestration.task_queue import TaskQueue
from Orchestration.tool_context import ToolContext, ToolContextError

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
    print(f"  {'PASS' if condition else 'FAIL'} - {description}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
class _ContextCapturingSkill:
    """Captures whatever SkillContext (or stand-in) it receives,
    without ever calling ``tool_context_factory`` itself -- proving
    Executor never calls the factory on the skill's behalf either."""

    def __init__(self):
        self.received_context = None
        self.calls = 0

    def execute(self, context):
        self.calls += 1
        self.received_context = context
        return context


class _RaisingSkill:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def execute(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


class _RaisingMapping(dict):
    def __getitem__(self, item):
        raise AssertionError("must never read metadata")

    def get(self, *args, **kwargs):
        raise AssertionError("must never read metadata via get()")


class _RaisingTuple(tuple):
    def __iter__(self):
        raise AssertionError("must never iterate")

    def __len__(self):
        raise AssertionError("must never call len()")


class _PermissiveContext:
    """Non-validating stand-in for SkillContext -- records every
    keyword it received so tests can inspect
    ``tool_context_factory`` afterward, exactly as the Sprint 80/81
    suites already do."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _StubToolContext:
    """Non-validating stand-in for ToolContext -- unlike the real
    class, accepts ``task=None`` without raising, so the factory's
    exact call shape (arguments, freshness, non-caching) can be
    verified independent of ``ToolContext``'s own unrelated
    ``task is not None`` validation rule."""

    _constructions = 0

    def __init__(self, task, parameters, metadata):
        type(self)._constructions += 1
        self.task = task
        self.parameters = parameters
        self.metadata = metadata


class _patched_skill_context:
    def __enter__(self):
        self._original = executor_module.SkillContext
        executor_module.SkillContext = _PermissiveContext
        return self

    def __exit__(self, exc_type, exc, tb):
        executor_module.SkillContext = self._original
        return False


class _patched_tool_context:
    def __enter__(self):
        self._original = executor_module.ToolContext
        _StubToolContext._constructions = 0
        executor_module.ToolContext = _StubToolContext
        return self

    def __exit__(self, exc_type, exc, tb):
        executor_module.ToolContext = self._original
        return False


def _make_executor(cls=Executor) -> Executor:
    return cls(task_manager=TaskManager(TaskQueue()), host=AutonomousHost())


def _running_executor(skill, tools=(), cls=Executor) -> Executor:
    plan = SkillExecutionPlan(skills=(skill,), tools=tools, metadata={})
    executor = _make_executor(cls=cls)
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    return executor


class _CustomError(Exception):
    pass


# ---------------------------------------------------------------------------
# V1-V3 -- lifecycle gating unaffected (missing/pending/ready)
# ---------------------------------------------------------------------------
def scenario_lifecycle_gating() -> None:
    executor = _make_executor()
    raised = False
    try:
        executor.invoke_current_skill()
    except ExecutorError:
        raised = True
    check(raised, "V1: missing session raises ExecutorError")

    skill = _ContextCapturingSkill()
    plan = SkillExecutionPlan(skills=(skill,), tools=(), metadata={})
    pending_executor = _make_executor()
    pending_executor.execute_plan(plan)
    raised = False
    try:
        pending_executor.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V2: 'pending' session raises ExecutionSessionError, no execute() call")
    check(skill.calls == 0, "V2b: skill.execute() never called while pending")

    pending_executor.prepare_session()
    raised = False
    try:
        pending_executor.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V3: 'ready' session raises ExecutionSessionError, no execute() call")


# ---------------------------------------------------------------------------
# V4-V7 -- factory is present and callable
# ---------------------------------------------------------------------------
def scenario_factory_is_callable() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context():
        executor.invoke_current_skill()
    factory = skill.received_context.tool_context_factory
    check(factory is not None, "V4: tool_context_factory is not None")
    check(callable(factory), "V5: callable(context.tool_context_factory) is True")
    check(inspect.isfunction(factory), "V6: factory is a plain local function object")
    check(len(inspect.signature(factory).parameters) == 0, "V7: factory accepts no arguments")


# ---------------------------------------------------------------------------
# V8-V13 -- factory call shape, values, freshness (patched stub ToolContext)
# ---------------------------------------------------------------------------
def scenario_factory_builds_tool_context_stub() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context(), _patched_tool_context():
        executor.invoke_current_skill()
        factory = skill.received_context.tool_context_factory
        ctx_1 = factory()
        ctx_2 = factory()

    check(isinstance(ctx_1, _StubToolContext), "V8: factory() returns a ToolContext(-shaped) instance")
    check(ctx_1.task is None, "V9: ctx.task is None")
    check(ctx_1.parameters == {}, "V10: ctx.parameters == {}")
    check(ctx_1.metadata == {}, "V11: ctx.metadata == {}")
    check(ctx_1 is not ctx_2, "V12: two calls to the same factory return two distinct instances (never cached)")
    check(_StubToolContext._constructions == 2, "V13: ToolContext was actually constructed once per factory() call (no reuse)")


# ---------------------------------------------------------------------------
# V14-V17 -- fresh factory identity across invoke_current_skill() calls
# ---------------------------------------------------------------------------
def scenario_factory_identity() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context():
        executor.invoke_current_skill()
        factory_1 = skill.received_context.tool_context_factory
        executor.invoke_current_skill()
        factory_2 = skill.received_context.tool_context_factory
    check(factory_1 is not factory_2, "V14: each invoke_current_skill() call builds a brand-new factory object")

    skill_a = _ContextCapturingSkill()
    executor_a = _running_executor(skill_a)
    skill_b = _ContextCapturingSkill()
    executor_b = _running_executor(skill_b)
    with _patched_skill_context():
        executor_a.invoke_current_skill()
        executor_b.invoke_current_skill()
    check(
        skill_a.received_context.tool_context_factory is not skill_b.received_context.tool_context_factory,
        "V15: two different Executor instances never share a factory object",
    )
    check(executor_a is not executor_b, "V16: distinct Executor instances, no singleton")
    check(executor is not executor_a, "V17: no cross-test executor reuse (sanity)")


# ---------------------------------------------------------------------------
# V18-V21 -- real (unpatched) ToolContext: factory faithfully raises
# ToolContextError, since ToolContext(task=None, ...) itself rejects it
# ---------------------------------------------------------------------------
def scenario_factory_against_real_tool_context() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context():
        executor.invoke_current_skill()
    factory = skill.received_context.tool_context_factory

    caught = None
    try:
        factory()
    except Exception as e:  # noqa: BLE001
        caught = e
    check(caught is not None, "V18: calling the factory against the real ToolContext raises")
    check(type(caught) is ToolContextError, "V19: raised exception's exact type is ToolContextError")
    check("task" in str(caught), "V20: error message reflects ToolContext's own 'task' validation rule")
    check(isinstance(caught, ToolContextError), "V21: is-a ToolContextError (AgentError subclass), not wrapped/rewrapped")


# ---------------------------------------------------------------------------
# V22-V27 -- Executor never invokes the factory itself; no Tool wiring
# ---------------------------------------------------------------------------
def scenario_no_self_invocation_and_no_tool_wiring() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    raised = False
    try:
        with _patched_skill_context():
            executor.invoke_current_skill()
    except (ToolContextError, NotImplementedError):
        raised = True
    check(raised is False, "V22: invoke_current_skill() completes normally -- Executor never calls the factory itself")

    for name in ("BaseTool", "ToolRegistry", "ToolResolver", "ToolManager"):
        check(not hasattr(executor_module, name), f"V23-27 [{name}]: not present in Orchestration.executor namespace")
    check(hasattr(executor_module, "ToolContext"), "V27: ToolContext IS present (the one sanctioned new import)")


# ---------------------------------------------------------------------------
# V28-V33 -- exception propagation, unwrapped and unaltered
# ---------------------------------------------------------------------------
def scenario_exception_propagation_table() -> None:
    exceptions = [
        RuntimeError("boom"),
        ValueError("bad value"),
        SkillContextError("context invalid"),
        _CustomError("custom"),
    ]
    for exc in exceptions:
        skill = _RaisingSkill(exc)
        executor = _running_executor(skill)
        caught = None
        try:
            with _patched_skill_context():
                executor.invoke_current_skill()
        except Exception as e:  # noqa: BLE001
            caught = e
        check(caught is exc, f"V28-33 [{type(exc).__name__}]: exact exception instance propagates unchanged")
        check(skill.calls == 1, f"V28-33 [{type(exc).__name__}]: execute() was actually called once before raising")


# ---------------------------------------------------------------------------
# V34-V39 -- no mutation of session/cursor/state/metadata/tools
# ---------------------------------------------------------------------------
def scenario_no_mutation() -> None:
    tools = _RaisingTuple(("t",))
    skill_a, skill_b = _ContextCapturingSkill(), _ContextCapturingSkill()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=tools, metadata={})
    guarded_session = ExecutionSession(plan=plan, state="pending", metadata=_RaisingMapping())
    guarded_session = guarded_session.with_state("ready").start()
    executor = _make_executor()
    executor._current_plan = guarded_session

    session_before = executor._current_plan
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result is skill_a.received_context, "V34: invoke_current_skill() succeeds with guarded metadata/tools untouched")
    check(executor._current_plan is session_before, "V35: session object identity unchanged")
    check(executor._current_plan.state == "running", "V36: state unchanged ('running')")
    check(executor._current_plan.current_skill_index == 0, "V37: cursor unchanged after one call")

    with _patched_skill_context():
        for _ in range(3):
            executor.invoke_current_skill()
    check(executor._current_plan.current_skill_index == 0, "V38: cursor still unchanged after several calls")
    check(skill_a.calls == 4 and skill_b.calls == 0, "V39: same skill invoked every time; no advance, no caching of stale results")


# ---------------------------------------------------------------------------
# V40 -- SkillResult propagation regression (Sprint 80 unaffected)
# ---------------------------------------------------------------------------
def scenario_skill_result_regression() -> None:
    skill_result = SkillResult(success=True, output="done", error=None, metadata={"k": "v"})

    class _ReturningSkill:
        def execute(self, context):
            return skill_result

    executor = _running_executor(_ReturningSkill())
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result is skill_result, "V40: SkillResult still propagated unchanged, by identity")


# ---------------------------------------------------------------------------
# V41-V49 -- AST verification of invoke_current_skill()
# ---------------------------------------------------------------------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(Executor.invoke_current_skill))
    tree = ast.parse(source)
    function_def = tree.body[0]

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else c.func.id)
        for c in calls
        if isinstance(c.func, (ast.Attribute, ast.Name))
    }
    check(
        call_names == {"current_skill", "SkillContext", "ToolContext", "execute"},
        f"V41: only sanctioned calls present (got {call_names})",
    )
    check("tool_context_factory" not in call_names, "V42: local factory is never called inside invoke_current_skill()")

    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    inner = [f for f in nested_funcs if f is not function_def]
    check(len(inner) == 1, "V43: exactly one local function definition")
    check(inner[0].name == "tool_context_factory", "V44: local function is named 'tool_context_factory'")
    check(len(inner[0].args.args) == 0, "V45: local function takes no arguments")

    inner_calls = [n for n in ast.walk(inner[0]) if isinstance(n, ast.Call)]
    inner_call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else c.func.id)
        for c in inner_calls
        if isinstance(c.func, (ast.Attribute, ast.Name))
    }
    check(inner_call_names == {"ToolContext"}, f"V46: local function body only calls ToolContext(...) (got {inner_call_names})")
    check(
        len(inner[0].body) == 1 and isinstance(inner[0].body[0], ast.Return),
        "V47: local function body is exactly one return statement",
    )

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V48: no loop or try/except of any kind")

    forbidden = {
        "Runtime", "Workflow", "ToolResolver", "Planner",
        "EventBus", "ToolManager", "ToolRegistry", "BaseTool", "Service",
        "Repository", "Provider",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), "V49: no reference to any forbidden Tool/Runtime/Workflow name")


# ---------------------------------------------------------------------------
# V50-V53 -- structural presence checks
# ---------------------------------------------------------------------------
def scenario_structural_presence() -> None:
    source = inspect.getsource(Executor.invoke_current_skill)
    check("current_skill()" in source, "V50: source contains a current_skill() call")
    check("def tool_context_factory()" in source, "V51: source defines a local, zero-arg tool_context_factory()")
    check("ToolContext(" in source, "V52: source contains a ToolContext(...) construction")
    check("SkillContext(" in source, "V53: source contains a SkillContext(...) construction")
    check("execute(context)" in source, "V54: source contains an execute(context) call")


# ---------------------------------------------------------------------------
# V55 -- namespace/import verification (exactly one new import this sprint)
# ---------------------------------------------------------------------------
def scenario_import_verification() -> None:
    tree = ast.parse((ROOT / "Orchestration" / "executor.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    expected = {
        "Core.exceptions",
        "Orchestration.autonomous_host",
        "Orchestration.execution_session",
        "Orchestration.skill_context",
        "Orchestration.skill_execution_plan",
        "Orchestration.skill_resolver",
        "Orchestration.task_manager",
        "Orchestration.tool_context",
        "__future__",
    }
    check(imported == expected, f"V55: exactly one new top-level import this sprint (got {imported})")


# ---------------------------------------------------------------------------
# V56-V59 -- signature & pre-existing behavior spot checks
# ---------------------------------------------------------------------------
def scenario_signature_and_regressions() -> None:
    params = [p for p in inspect.signature(Executor.invoke_current_skill).parameters if p != "self"]
    check(params == [], "V56: invoke_current_skill() takes no arguments beyond self")

    skill_a, skill_b = _ContextCapturingSkill(), _ContextCapturingSkill()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    check(executor.current_skill() is skill_a, "V57: current_skill() unaffected, still returns by identity")
    with _patched_skill_context():
        executor.invoke_current_skill()
    executor.advance_skill()
    check(executor.current_skill() is skill_b, "V58: advance_skill() still works, unaffected by this sprint")
    check(executor.execute(context="ctx") == 0, "V59: execute() unaffected, still returns 0 on empty queue")


def main() -> int:
    for scenario in [
        scenario_lifecycle_gating,
        scenario_factory_is_callable,
        scenario_factory_builds_tool_context_stub,
        scenario_factory_identity,
        scenario_factory_against_real_tool_context,
        scenario_no_self_invocation_and_no_tool_wiring,
        scenario_exception_propagation_table,
        scenario_no_mutation,
        scenario_skill_result_regression,
        scenario_ast_verification,
        scenario_structural_presence,
        scenario_import_verification,
        scenario_signature_and_regressions,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 82 TOOL-CONTEXT-FACTORY-BUILD RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())