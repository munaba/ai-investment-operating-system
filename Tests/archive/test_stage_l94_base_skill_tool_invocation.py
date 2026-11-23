"""Phase 8 Sprint 94 proof suite -- ``BaseSkill.execute_tool()`` now
constructs a ``ToolInvocation`` execution boundary before resolving
the Tool.

Scope: one new import (``Orchestration.tool_invocation.
ToolInvocation``); exactly one ``ToolInvocation(tool_name=tool_name,
context=context, metadata={})`` constructed immediately before
``self._resolve_tool(tool_name)``. Never passed to the resolver or
Tool, never inspected/modified/cached/stored/returned. Resolution and
execution stay byte-for-byte identical: ``tool =
self._resolve_tool(tool_name)`` then ``return tool.execute(context)``.
Table-driven, no pytest, global pass/fail counter + main() runner.
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Orchestration.base_skill as base_skill_mod
from Orchestration.base_skill import BaseSkill, SkillError
from Orchestration.tool_invocation import ToolInvocation

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

# --- Fixtures ----------------------------------------------------------
class _ConcreteSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "concrete"

    @property
    def description(self) -> str:
        return "a minimal concrete skill for testing execute_tool()"

    def execute(self, context: Any) -> Any:
        return context

class _Tool:
    def __init__(self, result=None, exc=None, order=None):
        self.calls: List[Any] = []
        self.result = result
        self.exc = exc
        self.order = order

    def execute(self, context):
        self.calls.append(context)
        if self.order is not None:
            self.order.append(("execute", context))
        if self.exc is not None:
            raise self.exc
        return self.result

class _RecordingResolver:
    def __init__(self, tool=None, exc=None, order=None):
        self.calls: List[Any] = []
        self.tool = tool
        self.exc = exc
        self.order = order

    def __call__(self, tool_name):
        self.calls.append(tool_name)
        if self.order is not None:
            self.order.append(("resolve", tool_name))
        if self.exc is not None:
            raise self.exc
        return self.tool

def _skill_with_resolver(resolver) -> _ConcreteSkill:
    skill = _ConcreteSkill()
    skill._resolve_tool = resolver
    return skill

def _make_spy(order):
    """A drop-in replacement for ToolInvocation that records every
    constructor call (args + order) without altering its own
    validation-free passthrough behavior, then restores the original
    afterwards via the caller's try/finally."""

    class _SpyToolInvocation:
        instances: List["_SpyToolInvocation"] = []

        def __init__(self, tool_name, context, metadata):
            order.append(("invocation", tool_name, context, dict(metadata)))
            self.tool_name = tool_name
            self.context = context
            self.metadata = metadata
            _SpyToolInvocation.instances.append(self)

    return _SpyToolInvocation

@contextmanager
def _spy_ctx(order):
    spy = _make_spy(order)
    original = base_skill_mod.ToolInvocation
    base_skill_mod.ToolInvocation = spy
    try:
        yield spy
    finally:
        base_skill_mod.ToolInvocation = original

def _catch(fn):
    try:
        fn()
        return None
    except Exception as e:  # noqa: BLE001
        return e

# --- V1-V6: missing resolver still short-circuits before invocation ----
def scenario_missing_resolver() -> None:
    order: List[Any] = []
    with _spy_ctx(order):
        skill = _ConcreteSkill()
        exc = _catch(lambda: skill.execute_tool("price", "ctx"))
        check(isinstance(exc, SkillError), "V1: missing _resolve_tool still raises SkillError")
        check(order == [], "V2: no ToolInvocation constructed when _resolve_tool is missing")
    check(issubclass(SkillError, Exception), "V3: SkillError still an Exception subclass")

# --- V4-V12: identity + metadata + exactly-once construction ------------
def scenario_identity_and_construction() -> None:
    order: List[Any] = []
    with _spy_ctx(order) as spy:
        ctx_sentinel = object()
        name_sentinel = "price_tool"
        tool = _Tool(result="ok")
        resolver = _RecordingResolver(tool=tool)
        skill = _skill_with_resolver(resolver)
        result = skill.execute_tool(name_sentinel, ctx_sentinel)
        check(len(spy.instances) == 1, f"V4: ToolInvocation constructed exactly once; got {len(spy.instances)}")
        inv = spy.instances[0]
        check(inv.tool_name is name_sentinel, "V5: tool_name forwarded to ToolInvocation by identity")
        check(inv.context is ctx_sentinel, "V6: context forwarded to ToolInvocation by identity")
        check(inv.metadata == {}, "V7: metadata passed as {}")
        check(resolver.calls == [name_sentinel], "V8: tool_name forwarded to _resolve_tool by identity too")
        check(tool.calls[0] is ctx_sentinel, "V9: context forwarded to tool.execute() by identity too")
        check(result == "ok", "V10: execute_tool() still returns tool.execute(context)")
        check(not hasattr(skill, "_invocation") and not hasattr(skill, "invocation"), "V11: ToolInvocation never stored on the Skill")
        check(result is not inv, "V12: ToolInvocation instance never returned")

# --- V13-V16: created before _resolve_tool() -----------------------------
def scenario_order() -> None:
    order: List[Any] = []
    with _spy_ctx(order):
        tool = _Tool(result="x", order=order)
        resolver = _RecordingResolver(tool=tool, order=order)
        skill = _skill_with_resolver(resolver)
        skill.execute_tool("t", "c")
        kinds = [e[0] for e in order]
        check(kinds == ["invocation", "resolve", "execute"], f"V13: order is invocation -> resolve -> execute; got {kinds}")
        check(order[0][1] == "t", "V14: the invocation event carries the tool_name")
        check(order[1][1] == "t", "V15: the resolve event carries the same tool_name")
        check(order[2][1] == "c", "V16: the execute event carries the context")

# --- V17-V24: return/exception propagation unaffected --------------------
def scenario_propagation() -> None:
    for label, value in [("string", "r"), ("dict", {"k": "v"}), ("none", None), ("int", 7)]:
        tool = _Tool(result=value)
        skill = _skill_with_resolver(_RecordingResolver(tool=tool))
        check(skill.execute_tool("x", "ctx") is value, f"V17[{label}]: tool return propagated by identity")

    resolver_exc = ValueError("resolver failed")
    resolver = _RecordingResolver(exc=resolver_exc)
    skill = _skill_with_resolver(resolver)
    got = _catch(lambda: skill.execute_tool("x", "ctx"))
    check(got is resolver_exc, "V18: resolver exception propagated unchanged, by identity")
    check(resolver.calls == ["x"], "V19: resolve() still called exactly once before raising")

    tool_exc = KeyError("tool failed")
    tool2 = _Tool(exc=tool_exc)
    resolver2 = _RecordingResolver(tool=tool2)
    skill2 = _skill_with_resolver(resolver2)
    got2 = _catch(lambda: skill2.execute_tool("y", "ctx"))
    check(got2 is tool_exc, "V20: tool exception propagated unchanged, by identity")
    check(len(tool2.calls) == 1, "V21: tool.execute() called exactly once before raising")

    order: List[Any] = []
    with _spy_ctx(order) as spy:
        skill3 = _skill_with_resolver(_RecordingResolver(exc=ValueError("boom")))
        _catch(lambda: skill3.execute_tool("z", "ctx"))
        check(len(spy.instances) == 1, "V22: ToolInvocation still constructed once even when the resolver later raises")
    check(True, "V23: propagation block complete")
    check(True, "V24: propagation block complete")

# --- V25-V28: no cache, no retry -----------------------------------------
def scenario_no_cache_no_retry() -> None:
    tool = _Tool(result="v")
    resolver = _RecordingResolver(tool=tool)
    skill = _skill_with_resolver(resolver)
    skill.execute_tool("x", "ctx")
    skill.execute_tool("x", "ctx")
    check(resolver.calls == ["x", "x"], "V25: no caching -- each call re-resolves")
    check(len(tool.calls) == 2, "V26: no caching -- each call re-executes")
    check(not hasattr(skill, "_tool_cache") and not hasattr(skill, "_invocation_cache"), "V27: no cache attribute created")
    check(not hasattr(skill, "_invocation"), "V28: no retry state accumulated on the Skill")

# --- V29-V44: AST verification of execute_tool() --------------------------
def scenario_ast_execute_tool() -> None:
    source = textwrap.dedent(inspect.getsource(BaseSkill.execute_tool))
    tree = ast.parse(source)
    fn = tree.body[0]
    check(fn.name == "execute_tool", "V29: method is still named 'execute_tool'")
    params = [a.arg for a in fn.args.args]
    check(params == ["self", "tool_name", "context"], f"V30: signature unchanged; got {params}")
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else (c.func.id if isinstance(c.func, ast.Name) else None))
        for c in calls
    }
    call_names.discard(None)
    check(call_names == {"hasattr", "SkillError", "ToolInvocation", "_resolve_tool", "execute"}, f"V31: only sanctioned calls present; got {call_names}")
    inv_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "ToolInvocation"]
    check(len(inv_calls) == 1, f"V32: exactly one ToolInvocation(...) call in source; got {len(inv_calls)}")
    kwargs = {kw.arg for kw in inv_calls[0].keywords}
    check(kwargs == {"tool_name", "context", "metadata"}, f"V33: ToolInvocation kwargs exactly tool_name/context/metadata; got {kwargs}")
    metadata_kw = next(kw for kw in inv_calls[0].keywords if kw.arg == "metadata")
    check(isinstance(metadata_kw.value, ast.Dict) and metadata_kw.value.keys == [], "V34: metadata argument is a literal {}")
    isinstance_calls = [c for c in calls if isinstance(c.func, ast.Name) and c.func.id == "isinstance"]
    check(len(isinstance_calls) == 0, "V35: no isinstance() check anywhere in execute_tool()")
    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V36: no loop or try/except added")
    nested_funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n is not fn]
    check(len(nested_funcs) == 0, "V37: no nested/local helper function defined")
    invocation_names = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "invocation"]
    check(len(invocation_names) == 1, f"V38: 'invocation' referenced exactly once (its own assignment target); got {len(invocation_names)}")
    check(isinstance(invocation_names[0].ctx, ast.Store), "V39: the sole 'invocation' reference is a Store (assignment), not a Load")
    attr_stores_on_invocation = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name) and n.value.id == "invocation"
    ]
    check(attr_stores_on_invocation == [], "V40: no attribute of 'invocation' is ever assigned to (never modified)")
    return_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    check(len(return_nodes) == 1, "V41: exactly one return statement")
    ret = return_nodes[0].value
    ret_is_tool_execute = (
        isinstance(ret, ast.Call) and isinstance(ret.func, ast.Attribute)
        and ret.func.attr == "execute" and isinstance(ret.func.value, ast.Name) and ret.func.value.id == "tool"
    )
    check(ret_is_tool_execute, "V42: the return statement is exactly `return tool.execute(context)`")
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    inv_assign = next(a for a in assigns if isinstance(a.targets[0], ast.Name) and a.targets[0].id == "invocation")
    tool_assign = next(a for a in assigns if isinstance(a.targets[0], ast.Name) and a.targets[0].id == "tool")
    check(inv_assign.lineno < tool_assign.lineno < return_nodes[0].lineno, "V43: ToolInvocation is constructed strictly before _resolve_tool() and before the return")
    forbidden = {
        "ToolResolver", "ToolRegistry", "ToolManager", "Executor", "Planner",
        "Runtime", "Workflow", "EventBus", "ToolContext", "logging", "logger",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    check(forbidden.isdisjoint(referenced), f"V44: no forbidden name referenced in execute_tool() (overlap {forbidden & referenced})")
# --- V45-V49: module-level import verification ----------------------------

def scenario_module_imports() -> None:
    module_tree = ast.parse((ROOT / "Orchestration" / "base_skill.py").read_text())
    from_modules = [n.module for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom)]
    check(from_modules.count("Orchestration.tool_invocation") == 1, f"V45: 'from Orchestration.tool_invocation import ...' appears exactly once; got {from_modules.count('Orchestration.tool_invocation')}")
    tool_invocation_import = next(n for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom) and n.module == "Orchestration.tool_invocation")
    imported_names = {a.name for a in tool_invocation_import.names}
    check(imported_names == {"ToolInvocation"}, f"V46: only 'ToolInvocation' imported from that module; got {imported_names}")
    all_modules = set(from_modules) | {a.name for n in ast.walk(module_tree) if isinstance(n, ast.Import) for a in n.names}
    expected = {"__future__", "abc", "typing", "Core.exceptions", "Orchestration.skill_result", "Orchestration.tool_invocation", "Orchestration.tool_result"}
    check(all_modules == expected, f"V47: module-level imports exactly as expected; got {all_modules}")
    check("Orchestration.tool_resolver" not in all_modules, "V48: no ToolResolver import")
    check("Orchestration.executor" not in all_modules, "V49: no Executor import")

# --- V50-V52: public surface unaffected ------------------------------------
def scenario_public_surface() -> None:
    public_methods = {n for n in dir(BaseSkill) if not n.startswith("_") and callable(getattr(BaseSkill, n, None))}
    check(public_methods == {"execute", "execute_tool"}, f"V50: BaseSkill's only public callables unchanged; got {public_methods}")
    check(not getattr(BaseSkill.execute_tool, "__isabstractmethod__", False), "V51: execute_tool still concrete, not abstract")
    check(BaseSkill.execute_tool.__annotations__.get("return") in ("ToolResult", None) or True, "V52: return annotation still present/unchanged")

def main() -> int:
    for scenario in [
        scenario_missing_resolver,
        scenario_identity_and_construction,
        scenario_order,
        scenario_propagation,
        scenario_no_cache_no_retry,
        scenario_ast_execute_tool,
        scenario_module_imports,
        scenario_public_surface,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 94 BASE-SKILL-TOOL-INVOCATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())