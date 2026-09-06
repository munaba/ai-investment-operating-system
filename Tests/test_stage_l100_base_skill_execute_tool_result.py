"""Phase 9 Sprint 100 proof suite -- Skill / Tool Integration.

BaseSkill gains exactly one new concrete public method,
execute_tool_result(tool_name, context). It reuses self.execute_tool()
exactly once and constructs exactly one SkillResult, forwarding
success/output/error/metadata by identity -- no copy, inspection,
validation, transform, wrapping, caching, logging, or retry. Any
exception from execute_tool() propagates unchanged. Compact,
table-driven, no-pytest style.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_skill import BaseSkill, SkillError
from Orchestration.skill_result import SkillResult
from Orchestration.tool_result import ToolResult

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

# --- Fixtures ------------------------------------------------------
class _ConcreteSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "concrete"

    @property
    def description(self) -> str:
        return "a minimal concrete skill for testing execute_tool_result()"

    def execute(self, context: Any) -> Any:
        return context

class _Tool:
    def __init__(self, result=None, exc=None):
        self.calls: List[Any] = []
        self.result, self.exc = result, exc
    def execute(self, context):
        self.calls.append(context)
        if self.exc is not None:
            raise self.exc
        return self.result

class _Resolver:
    def __init__(self, tool):
        self.calls: List[Any] = []
        self.tool = tool
    def __call__(self, tool_name):
        self.calls.append(tool_name)
        return self.tool

def _skill_with_tool(tool_result=None, exc=None):
    skill = _ConcreteSkill()
    skill._resolve_tool = _Resolver(_Tool(result=tool_result, exc=exc))
    return skill

# T1 -- execute_tool() reused exactly once, args forwarded unexamined
def scenario_execute_tool_called_once() -> None:
    skill = _skill_with_tool(ToolResult(success=True, output=1, error=None, metadata={}))
    calls: List[Any] = []
    original = skill.execute_tool
    skill.execute_tool = lambda *a, **kw: (calls.append((a, kw)), original(*a, **kw))[1]
    skill.execute_tool_result("price", "ctx")
    check(len(calls) == 1, f"T1: execute_tool() called exactly once; got {len(calls)}")
    check(calls[0] == (("price", "ctx"), {}), f"T1: called with (tool_name, context) unexamined; got {calls[0]}")
    skill.execute_tool_result("news", "ctx2")
    check(len(calls) == 2, "T1: a second execute_tool_result() call adds exactly one more execute_tool() call")

# T2 -- SkillResult constructed exactly once
def scenario_skill_result_constructed_once() -> None:
    import Orchestration.base_skill as mod

    skill = _skill_with_tool(ToolResult(success=True, output=1, error=None, metadata={}))
    build_calls: List[Any] = []
    original_cls = mod.SkillResult

    class _CountingSkillResult(original_cls):
        def __init__(self, *a, **kw):
            build_calls.append((a, kw))
            super().__init__(*a, **kw)

    mod.SkillResult = _CountingSkillResult
    try:
        result = skill.execute_tool_result("price", "ctx")
    finally:
        mod.SkillResult = original_cls
    check(len(build_calls) == 1, f"T2: SkillResult constructed exactly once; got {len(build_calls)}")
    check(isinstance(result, original_cls), "T2: execute_tool_result() returns a SkillResult")
    check(build_calls[0][1] == {"success": True, "output": 1, "error": None, "metadata": {}}, "T2: constructed via keyword args")

# T3 -- fields forwarded (success/output/error/metadata)
def scenario_fields_forwarded() -> None:
    out_sentinel = object()
    tr = ToolResult(success=True, output=out_sentinel, error=None, metadata={"k": "v"})
    r = _skill_with_tool(tr).execute_tool_result("price", "ctx")

    check(r.success == tr.success, "T3: success forwarded")
    check(r.output is tr.output, "T3: output forwarded by identity")
    check(dict(r.metadata) == dict(tr.metadata), "T3: metadata contents forwarded")
    check(r.error is None, "T3: error=None forwarded")
    err_sentinel = "boom"
    tr2 = ToolResult(success=False, output=None, error=err_sentinel, metadata={})
    r2 = _skill_with_tool(tr2).execute_tool_result("price", "ctx")
    check(r2.success is False, "T3: success=False forwarded")
    check(r2.error is err_sentinel, "T3: error forwarded by identity")
    check(r2.output is None, "T3: output=None forwarded")

# T4 -- exception propagation, unchanged
def scenario_exception_propagates() -> None:
    class _CustomError(Exception):
        pass

    exc = _CustomError("tool failed")
    caught = None
    try:
        _skill_with_tool(exc=exc).execute_tool_result("price", "ctx")
    except _CustomError as e:  # noqa: BLE001
        caught = e
    check(caught is exc, "T4: the exact same exception instance propagates from a failing Tool")
    raised = False
    try:
        _ConcreteSkill().execute_tool_result("price", "ctx")
    except SkillError:
        raised = True
    check(raised, "T4: missing resolver still raises SkillError via execute_tool()")

# T5 -- AST verification: method body, forbidden tokens, imports
def scenario_ast_verification() -> None:
    import Orchestration.base_skill as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "execute_tool_result")
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(
        getattr(body[0], "value", None), ast.Constant
    ) and isinstance(body[0].value.value, str):
        body = body[1:]
    code_only = "\n".join(ast.get_source_segment(source, s) or "" for s in body)

    check(code_only.count("self.execute_tool(") == 1, "T5: calls self.execute_tool() exactly once")
    check(code_only.count("SkillResult(") == 1, "T5: constructs SkillResult exactly once")
    forbidden = (
        "Runtime", "Workflow", "Planner", "Executor", "Registry", "Manager",
        "Repository", "Provider", "cache", "retry", "logging", "logger",
        "isinstance(", "dict(tool_result", "copy(", "deepcopy",
    )
    check(not any(t in code_only for t in forbidden), f"T5: no forbidden token in method body {forbidden!r}")
    top_modules, names = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            top_modules.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            top_modules.add(n.module.split(".")[0])
            names.update(a.name for a in n.names)
    check(top_modules == {"__future__", "abc", "typing", "Core", "Orchestration"}, f"T5: imports unchanged; got {top_modules!r}")
    check(
        names == {"annotations", "ABC", "abstractmethod", "Any", "AgentError", "SkillResult", "ToolInvocation", "ToolResult"},
        f"T5: imported names unchanged; got {names!r}",
    )

# T6 -- namespace verification
def scenario_namespace_verification() -> None:
    import Orchestration.base_skill as mod
    check(mod.SkillResult is SkillResult, "T6: mod.SkillResult is the real SkillResult")
    check(mod.ToolResult is ToolResult, "T6: mod.ToolResult is the real ToolResult")
    check(hasattr(BaseSkill, "execute_tool_result"), "T6: BaseSkill exposes execute_tool_result")
    check(hasattr(BaseSkill, "execute_tool"), "T6: BaseSkill still exposes execute_tool")
    check(not getattr(BaseSkill.execute_tool_result, "__isabstractmethod__", False), "T6: execute_tool_result() is concrete")

def main() -> int:
    scenarios = [
        scenario_execute_tool_called_once,
        scenario_skill_result_constructed_once,
        scenario_fields_forwarded,
        scenario_exception_propagates,
        scenario_ast_verification,
        scenario_namespace_verification,
    ]
    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            import traceback
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"PHASE 9 SPRINT 100 BASE SKILL EXECUTE TOOL RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())