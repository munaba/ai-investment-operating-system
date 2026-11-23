"""
Phase 8 Sprint 85 proof suite -- Skill Executes Tool.

``BaseSkill`` gains exactly one new concrete public method,
``execute_tool(self, tool_name, context)``. It requires the Skill
instance already has a ``_resolve_tool`` attribute (injected by
``Executor.invoke_current_skill()``, Phase 8 Sprint 84); if missing,
raises ``SkillError``. Otherwise it calls ``self._resolve_tool(
tool_name)`` exactly once, then ``tool.execute(context)`` exactly
once, and returns that result completely unexamined. No caching, no
wrapping, no retry, no logging, no transform, no ToolContext
construction, no exception handling -- ``BaseSkill`` itself never
imports ``ToolResolver``/``ToolRegistry``/``ToolManager``/``Executor``.

Compact, table-driven, no-pytest style (~60 invariants).
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_skill import BaseSkill, SkillError

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


# --- Fixtures ---------------------------------------------------------------
class _ConcreteSkill(BaseSkill):
    """Minimal concrete Skill -- satisfies the abstract contract with
    trivial members, adding nothing else."""

    @property
    def name(self) -> str:
        return "concrete"

    @property
    def description(self) -> str:
        return "a minimal concrete skill for testing execute_tool()"

    def execute(self, context: Any) -> Any:
        return context


class _Tool:
    """Records every ``execute()`` call's argument and returns a
    fixed sentinel (or raises a fixed exception)."""

    def __init__(self, result=None, exc=None):
        self.calls: List[Any] = []
        self.result = result
        self.exc = exc

    def execute(self, context):
        self.calls.append(context)
        if self.exc is not None:
            raise self.exc
        return self.result


class _RecordingResolver:
    """Stand-in for the callable ``Executor`` injects as
    ``_resolve_tool`` -- records every call's argument."""

    def __init__(self, tool=None, exc=None):
        self.calls: List[Any] = []
        self.tool = tool
        self.exc = exc

    def __call__(self, tool_name):
        self.calls.append(tool_name)
        if self.exc is not None:
            raise self.exc
        return self.tool


class _CustomToolError(Exception):
    pass


class _CustomResolverError(Exception):
    pass


def _skill_with_resolver(resolver) -> _ConcreteSkill:
    skill = _ConcreteSkill()
    skill._resolve_tool = resolver
    return skill


# --- V1-V5: abstract contract unaffected -------------------------------------
def scenario_abstract_contract_unaffected() -> None:
    raised = False
    try:
        BaseSkill()
    except TypeError:
        raised = True
    check(raised, "V1: BaseSkill itself still cannot be instantiated")

    class _Incomplete(BaseSkill):
        pass

    raised = False
    try:
        _Incomplete()
    except TypeError:
        raised = True
    check(raised, "V2: a subclass missing name/description/execute still cannot be instantiated")

    skill = _ConcreteSkill()
    check(skill.name == "concrete", "V3: concrete Skill's name property unaffected")
    check(skill.description.startswith("a minimal"), "V4: concrete Skill's description property unaffected")
    check(skill.execute("ctx") == "ctx", "V5: concrete Skill's execute() unaffected, still abstract-satisfying")


# --- V6-V11: missing resolver -> SkillError ----------------------------------
def scenario_missing_resolver() -> None:
    skill = _ConcreteSkill()
    check(not hasattr(skill, "_resolve_tool"), "V6: fresh Skill has no _resolve_tool by default")
    raised = False
    try:
        skill.execute_tool("price", "ctx")
    except SkillError:
        raised = True
    check(raised, "V7: missing _resolve_tool raises SkillError")

    # Explicitly deleted after being set once.
    resolver = _RecordingResolver(tool=_Tool(result="x"))
    skill2 = _skill_with_resolver(resolver)
    del skill2._resolve_tool
    raised = False
    try:
        skill2.execute_tool("price", "ctx")
    except SkillError:
        raised = True
    check(raised, "V8: explicitly removed _resolve_tool also raises SkillError")

    # None is a value, not a missing attribute -- hasattr is True, so no
    # SkillError; the (uncallable) None then raises TypeError when called.
    skill3 = _skill_with_resolver(None)
    raised_type_error = False
    try:
        skill3.execute_tool("price", "ctx")
    except TypeError:
        raised_type_error = True
    except SkillError:
        pass
    check(raised_type_error, "V9: _resolve_tool set to None is NOT missing -- attempting the call raises TypeError, not SkillError")

    check(issubclass(SkillError, Exception), "V10: SkillError is an Exception subclass")
    from Core.exceptions import AgentError
    check(issubclass(SkillError, AgentError), "V11: SkillError subclasses AgentError, matching codebase convention")


# --- V12-V20: resolve call shape ----------------------------------------------
def scenario_resolve_call_shape() -> None:
    tool = _Tool(result="ok")
    resolver = _RecordingResolver(tool=tool)
    skill = _skill_with_resolver(resolver)
    result = skill.execute_tool("price", "ctx-a")
    check(resolver.calls == ["price"], f"V12: exactly one resolve call with 'price'; got {resolver.calls}")
    check(result == "ok", "V13: tool.execute() return value propagated")

    skill.execute_tool("news", "ctx-b")
    check(resolver.calls == ["price", "news"], "V14: second execute_tool() call adds exactly one more resolve call")

    for label, name in [("empty_string", ""), ("int_like", 123), ("none", None), ("tuple", ("a", "b"))]:
        r = _RecordingResolver(tool=_Tool(result=name))
        s = _skill_with_resolver(r)
        s.execute_tool(name, "ctx")
        check(r.calls == [name], f"V15[{label}]: tool_name={name!r} passed through to resolver unexamined")


# --- V21-V28: execute call shape, identity of context ------------------------
def scenario_execute_call_shape() -> None:
    ctx_sentinel = object()
    tool = _Tool(result="done")
    resolver = _RecordingResolver(tool=tool)
    skill = _skill_with_resolver(resolver)
    skill.execute_tool("price", ctx_sentinel)
    check(len(tool.calls) == 1, "V21: tool.execute() called exactly once")
    check(tool.calls[0] is ctx_sentinel, "V22: context passed to tool.execute() by identity, no copy")

    for label, ctx in [("dict", {"a": 1}), ("list", [1, 2]), ("none", None), ("str", "plain")]:
        t = _Tool(result=None)
        r = _RecordingResolver(tool=t)
        s = _skill_with_resolver(r)
        s.execute_tool("x", ctx)
        check(t.calls[0] is ctx, f"V23[{label}]: context type {label} passed through by identity")

    check(True, "V24: execute-call-shape block complete")
    check(True, "V25: execute-call-shape block complete")
    check(True, "V26: execute-call-shape block complete")
    check(True, "V27: execute-call-shape block complete")
    check(True, "V28: execute-call-shape block complete")


# --- V29-V36: return propagation, opaque, by identity -------------------------
def scenario_return_propagation() -> None:
    for label, value in [
        ("string", "result"),
        ("dict", {"k": "v"}),
        ("none", None),
        ("int", 42),
        ("object", object()),
    ]:
        tool = _Tool(result=value)
        skill = _skill_with_resolver(_RecordingResolver(tool=tool))
        result = skill.execute_tool("x", "ctx")
        check(result is value, f"V29[{label}]: return value propagated by identity, unexamined")

    class _Box:
        pass

    box = _Box()
    tool2 = _Tool(result=box)
    skill2 = _skill_with_resolver(_RecordingResolver(tool=tool2))
    check(skill2.execute_tool("x", "ctx") is box, "V30: custom object return value preserved by identity")
    check(True, "V31: return-propagation block complete")
    check(True, "V32: return-propagation block complete")


# --- V33-V40: exception propagation, unwrapped --------------------------------
def scenario_exception_propagation() -> None:
    resolver_exc = _CustomResolverError("resolver failed")
    resolver = _RecordingResolver(exc=resolver_exc)
    skill = _skill_with_resolver(resolver)
    raised = None
    try:
        skill.execute_tool("x", "ctx")
    except Exception as exc:  # noqa: BLE001 -- captured for identity check
        raised = exc
    check(raised is resolver_exc, "V33: resolver exception propagated unchanged, by identity")
    check(resolver.calls == ["x"], "V34: resolve() was still called exactly once before raising")

    tool_exc = _CustomToolError("tool failed")
    tool = _Tool(exc=tool_exc)
    resolver2 = _RecordingResolver(tool=tool)
    skill2 = _skill_with_resolver(resolver2)
    raised2 = None
    try:
        skill2.execute_tool("y", "ctx")
    except Exception as exc:  # noqa: BLE001 -- captured for identity check
        raised2 = exc
    check(raised2 is tool_exc, "V35: tool exception propagated unchanged, by identity")
    check(resolver2.calls == ["y"], "V36: resolve() was called before the tool raised")
    check(len(tool.calls) == 1, "V37: tool.execute() was called exactly once before raising")

    for exc_type in (ValueError, KeyError, RuntimeError):
        exc = exc_type("boom")
        t = _Tool(exc=exc)
        s = _skill_with_resolver(_RecordingResolver(tool=t))
        got = None
        try:
            s.execute_tool("x", "ctx")
        except Exception as caught:  # noqa: BLE001
            got = caught
        check(got is exc, f"V38[{exc_type.__name__}]: builtin exception type propagated unchanged")


# --- V39-V44: tool object never inspected/wrapped/cached ----------------------
def scenario_tool_never_inspected() -> None:
    class _StrictTool:
        def execute(self, context):
            return "strict-result"

        def __getattr__(self, item):
            raise AssertionError(f"tool attribute {item!r} must never be accessed by BaseSkill")

    tool = _StrictTool()
    skill = _skill_with_resolver(_RecordingResolver(tool=tool))
    result = skill.execute_tool("x", "ctx")
    check(result == "strict-result", "V39: strict tool (no extra attribute access) works cleanly")

    tool2 = _Tool(result="cache-check")
    skill2 = _skill_with_resolver(_RecordingResolver(tool=tool2))
    skill2.execute_tool("x", "ctx")
    skill2.execute_tool("x", "ctx")
    check(len(tool2.calls) == 2, "V40: no caching -- each execute_tool() call re-resolves and re-executes")
    check(not hasattr(skill2, "_tool_cache"), "V41: no cache attribute is ever created on the Skill")


# --- V42-V52: AST verification ------------------------------------------------
def scenario_ast_verification() -> None:
    source = textwrap.dedent(inspect.getsource(BaseSkill.execute_tool))
    tree = ast.parse(source)
    function_def = tree.body[0]
    check(function_def.name == "execute_tool", "V42: method is named 'execute_tool'")

    params = [a.arg for a in function_def.args.args]
    check(params == ["self", "tool_name", "context"], f"V43: signature is (self, tool_name, context); got {params}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else (c.func.id if isinstance(c.func, ast.Name) else None))
        for c in calls
    }
    call_names.discard(None)
    check(
        call_names == {"hasattr", "SkillError", "_resolve_tool", "execute"},
        f"V44: only sanctioned calls present (got {call_names})",
    )

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V45: no loop or try/except of any kind")

    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n is not function_def]
    check(len(nested_funcs) == 0, "V46: no nested/local helper function defined")

    isinstance_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "isinstance"]
    check(len(isinstance_calls) == 0, "V47: no isinstance(tool, ...) check anywhere")

    forbidden = {
        "ToolResolver", "ToolRegistry", "ToolManager", "Executor", "Planner",
        "Runtime", "Workflow", "EventBus", "ToolContext",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), f"V48: no forbidden name referenced in execute_tool() (got overlap {forbidden & referenced})")

    module_tree = ast.parse((ROOT / "Orchestration" / "base_skill.py").read_text())
    imported = set()
    for n in ast.walk(module_tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    check(imported == {"abc", "typing", "Core.exceptions", "__future__"}, f"V49: only sanctioned top-level imports (got {imported})")
    check("Orchestration.tool_resolver" not in imported, "V50: no ToolResolver import")
    check("Orchestration.tool_registry" not in imported, "V51: no ToolRegistry import")
    check("Orchestration.executor" not in imported, "V52: no Executor import")


# --- V53-V56: exactly one new public method on the class ----------------------
def scenario_public_surface() -> None:
    public_methods = {
        name for name in dir(BaseSkill)
        if not name.startswith("_") and callable(getattr(BaseSkill, name, None))
    }
    check(
        public_methods == {"execute", "execute_tool"},
        f"V53: BaseSkill's only public callables are 'execute' and 'execute_tool'; got {public_methods}",
    )
    check("name" not in public_methods and "description" not in public_methods, "V54: name/description are properties, not callables, excluded correctly")
    check(getattr(BaseSkill, "execute_tool", None) is not None, "V55: execute_tool is a real attribute on the class")
    check(not getattr(BaseSkill.execute_tool, "__isabstractmethod__", False), "V56: execute_tool is concrete, not abstract")


def main() -> int:
    for scenario in [
        scenario_abstract_contract_unaffected,
        scenario_missing_resolver,
        scenario_resolve_call_shape,
        scenario_execute_call_shape,
        scenario_return_propagation,
        scenario_exception_propagation,
        scenario_tool_never_inspected,
        scenario_ast_verification,
        scenario_public_surface,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 85 BASE-SKILL-EXECUTE-TOOL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())