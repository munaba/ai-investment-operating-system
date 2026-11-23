"""
Phase 8 Sprint 81 proof suite -- ``Executor.invoke_current_skill()``
filling ``SkillContext.tool_context_factory`` with a real, local,
zero-argument callable that immediately raises ``NotImplementedError``
(SkillContext Tool Discovery), instead of the prior ``None``
placeholder. No ``ToolContext`` is built, no ``Tool`` is looked up, no
``ToolRegistry``/``ToolResolver``/``ToolManager`` is touched, and the
factory is never invoked by ``Executor`` itself.

Compact, table-driven, no-pytest style (55+ invariants in ~350 LOC).
Reuses the Sprint 79/80 stand-in conventions (a permissive
``SkillContext`` replacement patched onto the module, since the real
``SkillContext`` rejects ``task=None`` at construction time) but
consolidates duplicated setup into a handful of helpers and tables.
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
    """Captures whatever ``SkillContext`` (or stand-in) it receives,
    without ever reading ``tool_context_factory`` off it itself --
    proving Executor never calls the factory on the skill's behalf."""

    def __init__(self):
        self.received_context = None
        self.calls = 0

    def execute(self, context):
        self.calls += 1
        self.received_context = context
        return context


class _RaisingSkill:
    """Raises a fixed exception instance from execute()."""

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
    """Non-validating stand-in for SkillContext -- the real
    SkillContext (Sprint 52, unchanged) rejects task=None, so reaching
    skill.execute() at all (to inspect what was passed in) requires
    patching the module-level name invoke_current_skill() actually
    calls. Same technique already used in the Sprint 79/80 suites.
    Unlike those suites' minimal stand-in, this one records every
    keyword it received so tests can inspect
    ``tool_context_factory`` afterward."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _patched_skill_context:
    def __enter__(self):
        self._original = executor_module.SkillContext
        executor_module.SkillContext = _PermissiveContext
        return self

    def __exit__(self, exc_type, exc, tb):
        executor_module.SkillContext = self._original
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
# V4-V10 -- context carries a real, callable factory
# ---------------------------------------------------------------------------
def scenario_context_carries_factory() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context():
        result = executor.invoke_current_skill()

    context = skill.received_context
    check(context is result, "V4: captured context is the same object returned (opaque propagation unaffected)")
    check(hasattr(context, "tool_context_factory"), "V5: context exposes a 'tool_context_factory' attribute")
    factory = context.tool_context_factory
    check(factory is not None, "V6: tool_context_factory is not None")
    check(callable(factory), "V7: callable(context.tool_context_factory) is True")
    check(inspect.isfunction(factory), "V8: tool_context_factory is a plain local function object")
    check(factory.__name__ == "tool_context_factory", "V9: factory's __name__ is 'tool_context_factory'")
    check(len(inspect.signature(factory).parameters) == 0, "V10: factory accepts no arguments")


# ---------------------------------------------------------------------------
# V11-V16 -- factory behavior: raises NotImplementedError, cleanly
# ---------------------------------------------------------------------------
def scenario_factory_raises_cleanly() -> None:
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
    check(caught is not None, "V11: calling the factory raises")
    check(type(caught) is NotImplementedError, "V12: raised exception's exact type is NotImplementedError (no wrapping)")
    check(str(caught) == "", "V13: raised with no message (bare 'raise NotImplementedError')")
    check(caught.__cause__ is None, "V14: no explicit exception chaining ('raise ... from ...')")
    raised_on_args = False
    try:
        factory("unexpected")
    except TypeError:
        raised_on_args = True
    except NotImplementedError:
        raised_on_args = False
    check(raised_on_args, "V15: calling factory with an argument raises TypeError (zero-arg signature enforced), not NotImplementedError")


# ---------------------------------------------------------------------------
# V17-V22 -- fresh factory identity, never reused
# ---------------------------------------------------------------------------
def scenario_factory_identity() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context():
        executor.invoke_current_skill()
        factory_1 = skill.received_context.tool_context_factory
        executor.invoke_current_skill()
        factory_2 = skill.received_context.tool_context_factory
        executor.invoke_current_skill()
        factory_3 = skill.received_context.tool_context_factory

    check(factory_1 is not factory_2, "V17: 2nd call builds a brand-new factory object (not reused)")
    check(factory_2 is not factory_3, "V18: 3rd call builds yet another brand-new factory object")
    check(factory_1 is not factory_3, "V19: 1st and 3rd factories are distinct objects too")
    check(len({id(factory_1), id(factory_2), id(factory_3)}) == 3, "V20: three calls -> three distinct identities")

    skill_a = _ContextCapturingSkill()
    executor_a = _running_executor(skill_a)
    skill_b = _ContextCapturingSkill()
    executor_b = _running_executor(skill_b)
    with _patched_skill_context():
        executor_a.invoke_current_skill()
        executor_b.invoke_current_skill()
    check(
        skill_a.received_context.tool_context_factory is not skill_b.received_context.tool_context_factory,
        "V21: two different Executor instances never share a factory object",
    )
    check(executor_a is not executor_b, "V22: distinct Executor instances, no singleton")


# ---------------------------------------------------------------------------
# V23-V27 -- Executor never invokes the factory itself; no Tool wiring
# ---------------------------------------------------------------------------
def scenario_no_self_invocation_and_no_tool_wiring() -> None:
    skill = _ContextCapturingSkill()
    executor = _running_executor(skill)
    raised = False
    try:
        with _patched_skill_context():
            executor.invoke_current_skill()
    except NotImplementedError:
        raised = True
    check(raised is False, "V23: invoke_current_skill() completes normally -- Executor never calls the factory itself")

    for name in ("ToolContext", "BaseTool", "ToolRegistry", "ToolResolver", "ToolManager"):
        check(not hasattr(executor_module, name), f"V24-28 [{name}]: not present in Orchestration.executor namespace")


# ---------------------------------------------------------------------------
# V29-V34 -- exception propagation, unwrapped and unaltered
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
        check(caught is exc, f"V29-34 [{type(exc).__name__}]: exact exception instance propagates unchanged")
        check(skill.calls == 1, f"V29-34 [{type(exc).__name__}]: execute() was actually called once before raising")


# ---------------------------------------------------------------------------
# V35-V40 -- no mutation of session/cursor/state/metadata/tools
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
    check(result is skill_a.received_context, "V35: invoke_current_skill() succeeds with guarded metadata/tools untouched")
    check(executor._current_plan is session_before, "V36: session object identity unchanged")
    check(executor._current_plan.state == "running", "V37: state unchanged ('running')")
    check(executor._current_plan.current_skill_index == 0, "V38: cursor unchanged after one call")

    with _patched_skill_context():
        for _ in range(3):
            executor.invoke_current_skill()
    check(executor._current_plan.current_skill_index == 0, "V39: cursor still unchanged after several calls")
    check(skill_a.calls == 4 and skill_b.calls == 0, "V40: same skill invoked every time; no advance, no caching of stale results")


# ---------------------------------------------------------------------------
# V41 -- SkillResult propagation regression (Sprint 80 unaffected)
# ---------------------------------------------------------------------------
def scenario_skill_result_regression() -> None:
    skill_result = SkillResult(success=True, output="done", error=None, metadata={"k": "v"})

    class _ReturningSkill:
        def execute(self, context):
            return skill_result

    executor = _running_executor(_ReturningSkill())
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result is skill_result, "V41: SkillResult still propagated unchanged, by identity")


# ---------------------------------------------------------------------------
# V42-V49 -- AST verification of invoke_current_skill()
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
    check(call_names == {"current_skill", "SkillContext", "execute"}, f"V42: only sanctioned calls present (got {call_names})")
    check("tool_context_factory" not in call_names, "V43: local factory is never called inside invoke_current_skill()")

    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    inner = [f for f in nested_funcs if f is not function_def]
    check(len(inner) == 1, "V44: exactly one local function definition")
    check(inner[0].name == "tool_context_factory", "V45: local function is named 'tool_context_factory'")
    check(len(inner[0].args.args) == 0, "V46: local function takes no arguments")
    check(
        len(inner[0].body) == 1 and isinstance(inner[0].body[0], ast.Raise),
        "V47: local function body is exactly one bare raise statement",
    )

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V48: no loop or try/except of any kind")

    forbidden = {
        "Runtime", "Workflow", "ToolContext", "ToolResolver", "Planner",
        "EventBus", "ToolManager", "ToolRegistry", "BaseTool", "Service",
        "Repository", "Provider",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), "V49: no reference to any forbidden Tool/Runtime/Workflow name")


# ---------------------------------------------------------------------------
# V50-V53 -- structural presence checks (current_skill/SkillContext/execute)
# ---------------------------------------------------------------------------
def scenario_structural_presence() -> None:
    source = inspect.getsource(Executor.invoke_current_skill)
    check("current_skill()" in source, "V50: source contains a current_skill() call")
    check("SkillContext(" in source, "V51: source contains a SkillContext(...) construction")
    check("execute(context)" in source, "V52: source contains an execute(context) call")
    check("def tool_context_factory()" in source, "V53: source defines a local, zero-arg tool_context_factory()")


# ---------------------------------------------------------------------------
# V54 -- namespace/import verification (no new imports this sprint)
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
        "__future__",
    }
    check(imported == expected, f"V54: no new top-level import introduced this sprint (got {imported})")


# ---------------------------------------------------------------------------
# V55-V58 -- signature & pre-existing behavior spot checks
# ---------------------------------------------------------------------------
def scenario_signature_and_regressions() -> None:
    params = [p for p in inspect.signature(Executor.invoke_current_skill).parameters if p != "self"]
    check(params == [], "V55: invoke_current_skill() takes no arguments beyond self")

    skill_a, skill_b = _ContextCapturingSkill(), _ContextCapturingSkill()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=(), metadata={})
    executor = _make_executor()
    executor.execute_plan(plan)
    executor.prepare_session()
    executor.start_session()
    check(executor.current_skill() is skill_a, "V56: current_skill() unaffected, still returns by identity")
    with _patched_skill_context():
        executor.invoke_current_skill()
    executor.advance_skill()
    check(executor.current_skill() is skill_b, "V57: advance_skill() still works, unaffected by this sprint")
    check(executor.has_pending_tasks() is False, "V58: has_pending_tasks() unaffected")
    check(executor.execute(context="ctx") == 0, "V59: execute() unaffected, still returns 0 on empty queue")


def main() -> int:
    for scenario in [
        scenario_lifecycle_gating,
        scenario_context_carries_factory,
        scenario_factory_raises_cleanly,
        scenario_factory_identity,
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
    print(f"PHASE 8 SPRINT 81 EXECUTOR-TOOL-CONTEXT-FACTORY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())