"""Phase 8 Sprint 87 proof suite -- the ``BaseSkill.execute_tool()``
``ToolResult`` contract update.

Scope: this sprint changes exactly one thing --
``execute_tool()``'s return annotation (``Any`` -> ``ToolResult``)
and its docstring, plus the one new import
(``Orchestration.tool_result.ToolResult``) that annotation requires.
Implementation/control-flow are byte-for-byte identical to Sprint 85:
``self._resolve_tool(tool_name)`` exactly once, then
``tool.execute(context)`` exactly once, returned completely
unexamined -- no isinstance(), no inspection, no copy, no wrap, no
cache, no log, no retry, no transform. No Runtime/Workflow/Executor/
Planner/Registry/Resolver/Tool/SkillResult/ToolContext change.

Compact, table-driven, no-pytest style (~55 invariants), mirroring
``Tests/test_stage_l85_base_skill_execute_tool.py`` and
``Tests/test_stage_l86_tool_result.py``.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_skill import BaseSkill, SkillError
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

# --- Fixtures ----------------------------------------------------------------
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
    """Records every execute() call's argument (by identity) and
    returns a fixed sentinel ToolResult (or raises a fixed exc)."""

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

# T1 -- execute_tool's return annotation is ToolResult
def scenario_return_annotation() -> None:
    ann = inspect.signature(BaseSkill.execute_tool).return_annotation
    ok = ann == "ToolResult" or ann is ToolResult
    check(ok, f"T1: execute_tool()'s return annotation refers to ToolResult; got {ann!r}")
    doc = BaseSkill.execute_tool.__doc__ or ""
    check("ToolResult" in doc, "T1: execute_tool()'s docstring mentions ToolResult")
    params = inspect.signature(BaseSkill.execute_tool).parameters
    check(list(params) == ["self", "tool_name", "context"], "T1: parameter list unchanged (self, tool_name, context)")
    for pname in ("tool_name", "context"):
        ann_p = params[pname].annotation
        check(ann_p in ("Any", Any), f"T1: parameter '{pname}' annotation unchanged (Any)")

# T2 -- ToolResult propagated by identity, no wrap/copy/inspect
def scenario_result_propagated_by_identity() -> None:
    sentinel = ToolResult(success=True, output=[1, 2, 3], error="oops", metadata={"k": 1})
    tool = _Tool(result=sentinel)
    skill = _skill_with_resolver(_RecordingResolver(tool=tool))

    outcome = skill.execute_tool("some_tool", "ctx")
    check(outcome is sentinel, "T2: the returned object is the exact ToolResult by identity")
    check(id(outcome) == id(sentinel), "T2: id(outcome) == id(sentinel) -- no copy")
    check(type(outcome) is ToolResult, "T2: type is unchanged -- no wrapper type introduced")
    check(not isinstance(outcome, (list, tuple, dict)), "T2: outcome is not wrapped in a container")

def scenario_non_tool_result_also_propagated_unexamined() -> None:
    # execute_tool() never inspects the result -- it must propagate
    # anything the Tool returns, not only a real ToolResult.
    for value in (None, "raw-string", 42, {"not": "a ToolResult"}, object()):
        tool = _Tool(result=value)
        skill = _skill_with_resolver(_RecordingResolver(tool=tool))
        outcome = skill.execute_tool("t", "c")
        check(outcome is value, f"T2: non-ToolResult value {value!r} is still propagated by identity (unexamined)")

# T3 -- resolver called exactly once, tool_name forwarded by identity
def scenario_resolve_call_shape() -> None:
    sentinel_name = object()
    resolver = _RecordingResolver(tool=_Tool(result=ToolResult(success=True, output=None, error=None, metadata={})))
    skill = _skill_with_resolver(resolver)

    skill.execute_tool(sentinel_name, "ctx")
    check(len(resolver.calls) == 1, "T3: _resolve_tool() called exactly once")
    check(resolver.calls[0] is sentinel_name, "T3: tool_name forwarded to _resolve_tool() by identity")

# T4 -- tool.execute() called exactly once, context forwarded by identity
def scenario_execute_call_shape() -> None:
    sentinel_ctx = object()
    tool = _Tool(result=ToolResult(success=True, output=None, error=None, metadata={}))
    skill = _skill_with_resolver(_RecordingResolver(tool=tool))

    skill.execute_tool("t", sentinel_ctx)
    check(len(tool.calls) == 1, "T4: tool.execute() called exactly once")
    check(tool.calls[0] is sentinel_ctx, "T4: context forwarded to tool.execute() by identity")

# T5 -- exceptions propagate unchanged, unwrapped
def scenario_exception_propagation() -> None:
    resolver_exc = _CustomResolverError("resolver blew up")
    never_called_tool = _Tool(result=ToolResult(success=True, output=None, error=None, metadata={}))
    resolver = _RecordingResolver(tool=never_called_tool, exc=resolver_exc)
    skill = _skill_with_resolver(resolver)
    raised = None
    try:
        skill.execute_tool("t", "c")
    except Exception as e:  # noqa: BLE001
        raised = e
    check(raised is resolver_exc, "T5: a resolver exception propagates unchanged, by identity")
    check(len(never_called_tool.calls) == 0, "T5: tool.execute() is never called when the resolver itself raises")

    tool_exc = _CustomToolError("tool blew up")
    tool = _Tool(exc=tool_exc)
    skill2 = _skill_with_resolver(_RecordingResolver(tool=tool))
    raised2 = None
    try:
        skill2.execute_tool("t", "c")
    except Exception as e:  # noqa: BLE001
        raised2 = e
    check(raised2 is tool_exc, "T5: a Tool exception propagates unchanged, by identity")

    raised3 = False
    try:
        _ConcreteSkill().execute_tool("t", "c")
    except SkillError:
        raised3 = True
    check(raised3, "T5: missing '_resolve_tool' still raises SkillError, unchanged")

def scenario_result_never_inspected() -> None:
    # A result that raises if any attribute is accessed -- proves
    # execute_tool() truly never inspects/isinstance-checks it.
    class _PoisonResult:
        def __getattr__(self, item):
            raise AssertionError(f"execute_tool() inspected the result via '.{item}'")

        def __eq__(self, other):
            raise AssertionError("execute_tool() compared the result via ==")

        def __len__(self):
            raise AssertionError("execute_tool() inspected the result via len()")

    poison = _PoisonResult()
    skill = _skill_with_resolver(_RecordingResolver(tool=_Tool(result=poison)))
    outcome = skill.execute_tool("t", "c")
    check(outcome is poison, "T2/T5: a result that raises on inspection is still returned untouched")

# T6 -- AST verification: exactly one new import, source-level checks
def scenario_ast_verification() -> None:
    import Orchestration.base_skill as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_modules, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top_modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_modules.add(node.module.split(".")[0])
            names.update(a.name for a in node.names)

    check(
        top_modules == {"__future__", "abc", "typing", "Core", "Orchestration"},
        f"T6: top-level imported modules exactly as expected; got {top_modules!r}",
    )
    check(
        names == {"annotations", "ABC", "abstractmethod", "Any", "AgentError", "ToolResult"},
        f"T6: imported names exactly as expected; got {names!r}",
    )

    # Isolate execute_tool()'s *code* (not its docstring, which
    # legitimately narrates "no isinstance()/logging/retry/..." in
    # prose) so forbidden-token checks test behavior, not wording.
    execute_tool_node = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "execute_tool"
    )
    body_stmts = execute_tool_node.body
    if body_stmts and isinstance(body_stmts[0], ast.Expr) and isinstance(
        getattr(body_stmts[0], "value", None), ast.Constant
    ) and isinstance(body_stmts[0].value.value, str):
        body_stmts = body_stmts[1:]  # drop the docstring statement
    code_only = "\n".join(
        ast.get_source_segment(source, stmt) or "" for stmt in body_stmts
    )

    for token in (
        "isinstance(", ".copy(", "deepcopy", "cache", "logging", "logger",
        "retry", ".transform(", "Runtime", "Workflow", "Planner",
        "Registry", "Resolver(", "SkillResult", "ToolContext",
    ):
        check(token not in code_only, f"T6: execute_tool()'s code body contains no '{token}'")
    check(
        "import Executor" not in code_only and "Executor(" not in code_only and "Executor." not in code_only,
        "T6: execute_tool()'s code body has no Executor dependency (the "
        "pre-existing SkillError message's prose mention of 'Executor' "
        "is not a code reference)",
    )

    check(
        "tool = self._resolve_tool(tool_name)" in code_only,
        "T6: execute_tool() still resolves via self._resolve_tool(tool_name)",
    )
    check(
        "return tool.execute(context)" in code_only,
        "T6: execute_tool() still returns tool.execute(context) directly",
    )
    check(
        code_only.count("self._resolve_tool(") == 1,
        "T6: self._resolve_tool(...) appears exactly once in the code body",
    )
    check(
        code_only.count(".execute(") == 1,
        "T6: .execute(...) appears exactly once in the code body",
    )

# T7 -- namespace / public API verification
def scenario_namespace_and_public_api() -> None:
    import Orchestration.base_skill as mod

    check(hasattr(mod, "ToolResult"), "T7: module namespace exposes the new ToolResult import")
    check(mod.ToolResult is ToolResult, "T7: mod.ToolResult is the same object as Orchestration.tool_result.ToolResult")

    check(
        BaseSkill.__abstractmethods__ == frozenset({"name", "description", "execute"}),
        "T7: BaseSkill's abstract members are unchanged",
    )
    check("execute_tool" in vars(BaseSkill), "T7: execute_tool remains a concrete method on BaseSkill")
    check("__init__" not in vars(BaseSkill), "T7: BaseSkill still defines no __init__ of its own")

    public_members = {
        n for n in dir(BaseSkill)
        if not n.startswith("_")
        and (callable(vars(BaseSkill).get(n) or getattr(BaseSkill, n, None))
             or isinstance(vars(BaseSkill).get(n), property))
    }
    check(
        public_members == {"name", "description", "execute", "execute_tool"},
        f"T7: public surface unchanged -- exactly name/description/execute/execute_tool; got {public_members!r}",
    )
    check(
        not hasattr(BaseSkill, "_result_cache") and not hasattr(BaseSkill, "cache"),
        "T7: no new class variable or cache attribute was added",
    )

    raised = False
    try:
        BaseSkill()  # type: ignore[abstract]
    except TypeError:
        raised = True
    check(raised, "T7: BaseSkill() still cannot be instantiated")

def main() -> int:
    scenarios = [
        scenario_return_annotation,
        scenario_result_propagated_by_identity,
        scenario_non_tool_result_also_propagated_unexamined,
        scenario_resolve_call_shape,
        scenario_execute_call_shape,
        scenario_exception_propagation,
        scenario_result_never_inspected,
        scenario_ast_verification,
        scenario_namespace_and_public_api,
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
    print(f"PHASE 8 SPRINT 87 BASE SKILL TOOL RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())