"""
Phase 8 Sprint 83 proof suite -- ``Executor.invoke_current_skill()``
giving the currently selected Skill access to the tool names its
``SkillExecutionPlan`` was built with, via ``setattr(skill,
"_tool_names", tool_names)`` immediately before ``skill.execute(context)``
(Skill Tool Discovery). ``tool_names`` is read once from
``self._current_plan.plan.tools`` and passed through by exact object
identity -- never iterated, indexed, copied, deduplicated, or
normalized by ``Executor``. No ``Tool`` is looked up, resolved, or
executed; no ``ToolRegistry``/``ToolResolver``/``ToolManager`` is
introduced. ``SkillContext`` itself is unchanged and still constructed
exactly once; the tool list is deliberately NOT threaded through it.

Compact, table-driven, no-pytest style (55+ invariants in ~350 LOC).
Reuses the Sprint 79-82 stand-in conventions (the real ``SkillContext``
rejects ``task=None``, so reaching ``skill.execute()`` at all requires
patching the module-level name ``invoke_current_skill()`` calls).
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
from Orchestration.tool_context import ToolContext

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
class _ToolNamesCapturingSkill:
    """Records ``self._tool_names`` (if present) at the moment
    execute() is called -- proving the attribute is set *before*
    invocation, not after -- and captures the received context too."""

    def __init__(self):
        self.calls = 0
        self.tool_names_at_execute = "UNSET"
        self.received_context = None

    def execute(self, context):
        self.calls += 1
        self.tool_names_at_execute = getattr(self, "_tool_names", "MISSING")
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


class _PoisonedTuple(tuple):
    """A tuple that raises if ever iterated, indexed, or measured --
    proving Executor passes it through by identity alone."""

    def __iter__(self):
        raise AssertionError("tool_names must never be iterated by Executor")

    def __getitem__(self, item):
        raise AssertionError("tool_names must never be indexed by Executor")

    def __len__(self):
        raise AssertionError("tool_names must never have len() called on it by Executor")


class _PermissiveContext:
    """Non-validating stand-in for SkillContext -- records every
    keyword it received, exactly as the Sprint 79-82 suites do."""

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

    skill = _ToolNamesCapturingSkill()
    plan = SkillExecutionPlan(skills=(skill,), tools=("x",), metadata={})
    pending_executor = _make_executor()
    pending_executor.execute_plan(plan)
    raised = False
    try:
        pending_executor.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V2: 'pending' session raises ExecutionSessionError, no execute() call")
    check(skill.calls == 0, "V2b: skill.execute() never called while pending")
    check(not hasattr(skill, "_tool_names"), "V2c: _tool_names not set while pending")

    pending_executor.prepare_session()
    raised = False
    try:
        pending_executor.invoke_current_skill()
    except ExecutionSessionError:
        raised = True
    check(raised, "V3: 'ready' session raises ExecutionSessionError, no execute() call")


# ---------------------------------------------------------------------------
# V4-V10 -- skill receives _tool_names before execute(), by identity
# ---------------------------------------------------------------------------
def scenario_tool_names_identity_table() -> None:
    tables = [
        ("empty", ()),
        ("single", ("alpha",)),
        ("multi_ordered", ("alpha", "beta", "gamma")),
        ("duplicates", ("alpha", "alpha", "beta")),
    ]
    for label, tools in tables:
        skill = _ToolNamesCapturingSkill()
        executor = _running_executor(skill, tools=tools)
        plan_tools = executor._current_plan.plan.tools
        with _patched_skill_context():
            executor.invoke_current_skill()
        check(hasattr(skill, "_tool_names"), f"V4-10 [{label}]: skill._tool_names attribute exists after invoke")
        check(skill._tool_names is plan_tools, f"V4-10 [{label}]: skill._tool_names IS self._current_plan.plan.tools (same object)")
        check(skill.tool_names_at_execute is plan_tools, f"V4-10 [{label}]: _tool_names already set at the moment execute() ran")
        check(tuple(skill._tool_names) == tools, f"V4-10 [{label}]: contents/order preserved exactly")


# ---------------------------------------------------------------------------
# V11-V14 -- order and duplicates preserved unchanged (no dedup/sort)
# ---------------------------------------------------------------------------
def scenario_order_and_duplicates_preserved() -> None:
    tools = ("z", "a", "z", "m", "a")
    skill = _ToolNamesCapturingSkill()
    executor = _running_executor(skill, tools=tools)
    with _patched_skill_context():
        executor.invoke_current_skill()
    check(skill._tool_names == tools, "V11: exact order preserved, no sorting")
    check(len(skill._tool_names) == len(tools), "V12: no deduplication -- length matches original")
    check(skill._tool_names.count("z") == 2, "V13: duplicate 'z' entries both remain")
    check(skill._tool_names.count("a") == 2, "V14: duplicate 'a' entries both remain")


# ---------------------------------------------------------------------------
# V15-V17 -- empty tuple supported
# ---------------------------------------------------------------------------
def scenario_empty_tuple_supported() -> None:
    skill = _ToolNamesCapturingSkill()
    executor = _running_executor(skill, tools=())
    with _patched_skill_context():
        executor.invoke_current_skill()
    check(skill._tool_names == (), "V15: empty tuple supported")
    check(isinstance(skill._tool_names, tuple), "V16: type is tuple")
    check(len(skill._tool_names) == 0, "V17: length is zero")


# ---------------------------------------------------------------------------
# V18-V21 -- Executor never iterates/indexes/measures tool_names itself
# ---------------------------------------------------------------------------
def scenario_executor_never_touches_tool_names() -> None:
    poisoned = _PoisonedTuple(("t1", "t2"))
    skill = _ToolNamesCapturingSkill()
    executor = _running_executor(skill, tools=poisoned)
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result is not None, "V18: invoke_current_skill() succeeds with a poisoned tools tuple")
    check(skill._tool_names is poisoned, "V19: poisoned tuple passed through by identity, untouched")
    caught = False
    try:
        for _ in skill._tool_names:
            pass
    except AssertionError:
        caught = True
    check(caught, "V20: the poison is real -- iterating it (ourselves, not Executor) still raises")
    check(skill.calls == 1, "V21: skill.execute() called exactly once")


# ---------------------------------------------------------------------------
# V22-V25 -- SkillContext still built exactly once; factory untouched
# ---------------------------------------------------------------------------
def scenario_skill_context_and_factory_unaffected() -> None:
    skill = _ToolNamesCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context():
        executor.invoke_current_skill()
    context = skill.received_context
    check(context is not None, "V22: SkillContext (stand-in) was constructed and passed to execute()")
    factory = context.tool_context_factory
    check(callable(factory), "V23: tool_context_factory is still callable")
    from Orchestration.tool_context import ToolContextError
    caught = None
    try:
        factory()
    except ToolContextError as e:
        caught = e
    check(
        type(caught) is ToolContextError,
        "V24: factory still attempts a real ToolContext(task=None, ...) build (raises ToolContextError, per Sprint 82's established behavior)",
    )
    check("task" in str(caught), "V25: error reflects ToolContext's own 'task' validation rule, unaffected by this sprint")


# ---------------------------------------------------------------------------
# V26-V29 -- fresh tool_context_factory identity, unaffected by this sprint
# ---------------------------------------------------------------------------
def scenario_factory_identity_unaffected() -> None:
    skill = _ToolNamesCapturingSkill()
    executor = _running_executor(skill)
    with _patched_skill_context():
        executor.invoke_current_skill()
        factory_1 = skill.received_context.tool_context_factory
        executor.invoke_current_skill()
        factory_2 = skill.received_context.tool_context_factory
    check(factory_1 is not factory_2, "V26: each invoke_current_skill() call still builds a brand-new factory")
    check(skill._tool_names is executor._current_plan.plan.tools, "V27: _tool_names still points at the same plan.tools object")
    check(skill.calls == 2, "V28: execute() called twice across the two invocations")
    check(inspect.isfunction(factory_1) and inspect.isfunction(factory_2), "V29: both factories remain plain callables (each independently still attempts a ToolContext build)")


# ---------------------------------------------------------------------------
# V30-V35 -- exception propagation, unwrapped and unaltered
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
        executor = _running_executor(skill, tools=("t",))
        caught = None
        try:
            with _patched_skill_context():
                executor.invoke_current_skill()
        except Exception as e:  # noqa: BLE001
            caught = e
        check(caught is exc, f"V30-35 [{type(exc).__name__}]: exact exception instance propagates unchanged")
        check(skill.calls == 1, f"V30-35 [{type(exc).__name__}]: execute() was actually called once before raising")
        check(getattr(skill, "_tool_names", "MISSING") == ("t",), f"V30-35 [{type(exc).__name__}]: _tool_names was still set before the raising execute() call")


# ---------------------------------------------------------------------------
# V36-V41 -- no mutation of session/cursor/state/metadata
# ---------------------------------------------------------------------------
def scenario_no_mutation() -> None:
    skill_a, skill_b = _ToolNamesCapturingSkill(), _ToolNamesCapturingSkill()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=("t1", "t2"), metadata={})
    guarded_session = ExecutionSession(plan=plan, state="pending", metadata=_RaisingMapping())
    guarded_session = guarded_session.with_state("ready").start()
    executor = _make_executor()
    executor._current_plan = guarded_session

    session_before = executor._current_plan
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result is skill_a.received_context, "V36: invoke_current_skill() succeeds with guarded metadata untouched")
    check(executor._current_plan is session_before, "V37: session object identity unchanged")
    check(executor._current_plan.state == "running", "V38: state unchanged ('running')")
    check(executor._current_plan.current_skill_index == 0, "V39: cursor unchanged after one call")

    with _patched_skill_context():
        for _ in range(3):
            executor.invoke_current_skill()
    check(executor._current_plan.current_skill_index == 0, "V40: cursor still unchanged after several calls")
    check(skill_a.calls == 4 and skill_b.calls == 0, "V41: same skill invoked every time; no advance")


# ---------------------------------------------------------------------------
# V42 -- SkillResult propagation regression (Sprint 80 unaffected)
# ---------------------------------------------------------------------------
def scenario_skill_result_regression() -> None:
    skill_result = SkillResult(success=True, output="done", error=None, metadata={"k": "v"})

    class _ReturningSkill:
        def execute(self, context):
            return skill_result

    executor = _running_executor(_ReturningSkill(), tools=("t",))
    with _patched_skill_context():
        result = executor.invoke_current_skill()
    check(result is skill_result, "V42: SkillResult still propagated unchanged, by identity")


# ---------------------------------------------------------------------------
# V43-V51 -- AST verification of invoke_current_skill()
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
        call_names == {"current_skill", "SkillContext", "ToolContext", "execute", "setattr"},
        f"V43: only sanctioned calls present (got {call_names})",
    )
    check("execute_tool" not in call_names, "V44: no execute_tool call")

    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    inner = [f for f in nested_funcs if f is not function_def]
    check(len(inner) == 1, "V45: exactly one local function definition (tool_context_factory)")
    check(inner[0].name == "tool_context_factory", "V46: local function is named 'tool_context_factory'")

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V47: no loop or try/except of any kind")

    forbidden = {
        "Runtime", "Workflow", "ToolResolver", "Planner",
        "EventBus", "ToolManager", "ToolRegistry", "BaseTool", "Service",
        "Repository", "Provider",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), "V48: no reference to any forbidden Tool/Runtime/Workflow name")

    setattr_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "setattr"]
    check(len(setattr_calls) == 1, "V49: exactly one setattr(...) call")
    sa = setattr_calls[0]
    check(
        len(sa.args) == 3
        and isinstance(sa.args[0], ast.Name) and sa.args[0].id == "skill"
        and isinstance(sa.args[1], ast.Constant) and sa.args[1].value == "_tool_names"
        and isinstance(sa.args[2], ast.Name) and sa.args[2].id == "tool_names",
        "V50: setattr(skill, '_tool_names', tool_names) called with exact expected arguments",
    )

    assign_targets = {
        t.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    check("tool_names" in assign_targets, "V51: 'tool_names' is assigned as a local variable")


# ---------------------------------------------------------------------------
# V52-V54 -- structural presence / ordering checks (source text)
# ---------------------------------------------------------------------------
def scenario_structural_presence() -> None:
    source = inspect.getsource(Executor.invoke_current_skill)
    check("tool_names = self._current_plan.plan.tools" in source, "V52: source reads tool_names from plan.tools")
    check('setattr(skill, "_tool_names", tool_names)' in source, "V53: source calls setattr(skill, '_tool_names', tool_names)")
    idx_setattr = source.index('setattr(skill, "_tool_names", tool_names)')
    idx_execute = source.rindex("skill.execute(context)")
    check(idx_setattr < idx_execute, "V54: setattr(...) appears before skill.execute(context) in source order")


# ---------------------------------------------------------------------------
# V55 -- namespace/import verification (no new imports this sprint)
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
    check(imported == expected, f"V55: no new top-level import introduced this sprint (got {imported})")


# ---------------------------------------------------------------------------
# V56-V59 -- signature & pre-existing behavior spot checks
# ---------------------------------------------------------------------------
def scenario_signature_and_regressions() -> None:
    params = [p for p in inspect.signature(Executor.invoke_current_skill).parameters if p != "self"]
    check(params == [], "V56: invoke_current_skill() takes no arguments beyond self")

    skill_a, skill_b = _ToolNamesCapturingSkill(), _ToolNamesCapturingSkill()
    plan = SkillExecutionPlan(skills=(skill_a, skill_b), tools=("x",), metadata={})
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
        scenario_tool_names_identity_table,
        scenario_order_and_duplicates_preserved,
        scenario_empty_tuple_supported,
        scenario_executor_never_touches_tool_names,
        scenario_skill_context_and_factory_unaffected,
        scenario_factory_identity_unaffected,
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
    print(f"PHASE 8 SPRINT 83 EXECUTOR-SKILL-TOOLS RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())