"""Phase 8 Sprint 88 -- ``BaseSkill.execute()`` ``SkillResult`` contract.

Scope: return annotation (``Any`` -> ``SkillResult``) + docstring on
``execute()``, plus the one new import that annotation requires.
``execute()`` stays abstract: no implementation, no default return,
no decorator change. ``execute_tool()`` untouched. Compact,
table-driven, no-pytest style, mirroring
``Tests/test_stage_l87_base_skill_tool_result.py``.
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


# --- Fixtures ----------------------------------------------------------------
class _ConcreteSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "concrete"

    @property
    def description(self) -> str:
        return "a minimal concrete skill for testing the SkillResult contract"

    def execute(self, context: Any) -> SkillResult:
        return SkillResult(success=True, output=context)


class _Tool:
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


def _skill_with_resolver(resolver) -> _ConcreteSkill:
    skill = _ConcreteSkill()
    skill._resolve_tool = resolver
    return skill


# T1 -- execute()'s return annotation is SkillResult
def scenario_return_annotation() -> None:
    ann = inspect.signature(BaseSkill.execute).return_annotation
    ok = ann == "SkillResult" or ann is SkillResult
    check(ok, f"T1: execute()'s return annotation refers to SkillResult; got {ann!r}")

    doc = BaseSkill.execute.__doc__ or ""
    check("SkillResult" in doc, "T1: execute()'s docstring mentions SkillResult")

    params = inspect.signature(BaseSkill.execute).parameters
    check(list(params) == ["self", "context"], "T1: parameter list unchanged (self, context)")
    ctx_ann = params["context"].annotation
    check(ctx_ann in ("Any", Any), "T1: parameter 'context' annotation unchanged (Any)")


# T2 -- execute() remains abstract, still raises NotImplementedError, no default
def scenario_execute_remains_abstract() -> None:
    check(
        "execute" in BaseSkill.__abstractmethods__,
        "T2: 'execute' is still listed in BaseSkill.__abstractmethods__",
    )
    check(
        getattr(BaseSkill.execute, "__isabstractmethod__", False) is True,
        "T2: BaseSkill.execute is still marked __isabstractmethod__ == True",
    )

    class _Incomplete(BaseSkill):
        @property
        def name(self) -> str:
            return "incomplete"

        @property
        def description(self) -> str:
            return "missing execute()"

    raised = False
    try:
        _Incomplete()  # type: ignore[abstract]
    except TypeError:
        raised = True
    check(raised, "T2: a subclass that omits execute() still cannot be instantiated")

    raised2 = False
    try:
        BaseSkill.execute(_ConcreteSkill(), "ctx")  # bypasses override, calls base body
    except NotImplementedError:
        raised2 = True
    check(raised2, "T2: calling BaseSkill.execute() directly still raises NotImplementedError")


# T3 -- a concrete subclass may freely return SkillResult; execute() itself
# does not construct, validate, or touch it in any way (nothing to check
# behaviorally since the base method has no implementation -- verified via T2).
def scenario_concrete_subclass_returns_skill_result() -> None:
    skill = _ConcreteSkill()
    outcome = skill.execute("payload")
    check(isinstance(outcome, SkillResult), "T3: a concrete subclass's execute() may return a SkillResult")
    check(outcome.success is True, "T3: the SkillResult produced by the subclass is unchanged")
    check(outcome.output == "payload", "T3: the SkillResult's output matches what the subclass produced")


# T4 -- execute_tool() is completely unchanged by this sprint
def scenario_execute_tool_unchanged() -> None:
    ann = inspect.signature(BaseSkill.execute_tool).return_annotation
    ok = ann == "ToolResult" or ann is ToolResult
    check(ok, f"T4: execute_tool()'s return annotation is still ToolResult; got {ann!r}")

    params = inspect.signature(BaseSkill.execute_tool).parameters
    check(list(params) == ["self", "tool_name", "context"], "T4: execute_tool()'s parameter list unchanged")

    sentinel = ToolResult(success=True, output=[1, 2, 3], error=None, metadata={"k": 1})
    tool = _Tool(result=sentinel)
    skill = _skill_with_resolver(_RecordingResolver(tool=tool))
    outcome = skill.execute_tool("some_tool", "ctx")
    check(outcome is sentinel, "T4: execute_tool() still propagates a ToolResult by identity")
    check(len(tool.calls) == 1, "T4: execute_tool() still calls tool.execute() exactly once")

    raised = False
    try:
        _ConcreteSkill().execute_tool("t", "c")
    except SkillError:
        raised = True
    check(raised, "T4: execute_tool() still raises SkillError when no resolver is injected")


# T5 -- AST verification: exactly the expected new import, source-level checks
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
        f"T5: top-level imported modules exactly as expected; got {top_modules!r}",
    )
    check(
        names == {"annotations", "ABC", "abstractmethod", "Any", "AgentError", "SkillResult", "ToolResult"},
        f"T5: imported names exactly as expected; got {names!r}",
    )

    # Isolate execute()'s code (excluding its docstring) so token checks test behavior, not wording.
    execute_node = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "execute"
    )
    body_stmts = execute_node.body
    if body_stmts and isinstance(body_stmts[0], ast.Expr) and isinstance(
        getattr(body_stmts[0], "value", None), ast.Constant
    ) and isinstance(body_stmts[0].value.value, str):
        body_stmts = body_stmts[1:]  # drop the docstring statement
    code_only = "\n".join(
        ast.get_source_segment(source, stmt) or "" for stmt in body_stmts
    )

    check(
        code_only.strip() == "raise NotImplementedError",
        f"T5: execute()'s code body is exactly 'raise NotImplementedError'; got {code_only!r}",
    )

    for token in (
        "isinstance(", ".copy(", "deepcopy", "cache", "logging", "logger",
        "retry", ".transform(", "Runtime", "Workflow", "Planner",
        "Registry", "Resolver(", "ToolContext", "SkillContext",
        "SkillResult(",
    ):
        check(token not in code_only, f"T5: execute()'s code body contains no '{token}'")

    # execute() still has exactly the @abstractmethod decorator.
    decorator_names = {
        d.id if isinstance(d, ast.Name) else getattr(d, "attr", None)
        for d in execute_node.decorator_list
    }
    check(
        decorator_names == {"abstractmethod"},
        f"T5: execute()'s decorators are unchanged -- exactly @abstractmethod; got {decorator_names!r}",
    )


# T6 -- namespace / public API verification
def scenario_namespace_and_public_api() -> None:
    import Orchestration.base_skill as mod

    check(hasattr(mod, "SkillResult"), "T6: module namespace exposes the new SkillResult import")
    check(
        mod.SkillResult is SkillResult,
        "T6: mod.SkillResult is the same object as Orchestration.skill_result.SkillResult",
    )
    check(hasattr(mod, "ToolResult"), "T6: module namespace still exposes ToolResult (Sprint 87)")

    check(
        BaseSkill.__abstractmethods__ == frozenset({"name", "description", "execute"}),
        "T6: BaseSkill's abstract members are unchanged",
    )
    check("execute_tool" in vars(BaseSkill), "T6: execute_tool remains a concrete method on BaseSkill")
    check("__init__" not in vars(BaseSkill), "T6: BaseSkill still defines no __init__ of its own")

    public_members = {
        n for n in dir(BaseSkill)
        if not n.startswith("_")
        and (callable(vars(BaseSkill).get(n) or getattr(BaseSkill, n, None))
             or isinstance(vars(BaseSkill).get(n), property))
    }
    check(
        public_members == {"name", "description", "execute", "execute_tool"},
        f"T6: public surface unchanged -- exactly name/description/execute/execute_tool; got {public_members!r}",
    )
    check(
        not hasattr(BaseSkill, "_result_cache") and not hasattr(BaseSkill, "cache"),
        "T6: no new class variable or cache attribute was added",
    )
    check(
        not hasattr(BaseSkill, "skill_result") and not hasattr(BaseSkill, "SkillResult"),
        "T6: SkillResult was not added as a class attribute of BaseSkill itself",
    )

    raised = False
    try:
        BaseSkill()  # type: ignore[abstract]
    except TypeError:
        raised = True
    check(raised, "T6: BaseSkill() still cannot be instantiated")

    check(
        BaseSkill.name.fget is not None and getattr(BaseSkill.name, "__isabstractmethod__", False),
        "T6: 'name' property is still abstract",
    )
    check(
        BaseSkill.description.fget is not None and getattr(BaseSkill.description, "__isabstractmethod__", False),
        "T6: 'description' property is still abstract",
    )


# T7 -- SkillError and SkillResult are independent -- no cross-wiring introduced
def scenario_no_cross_wiring() -> None:
    check(not hasattr(SkillResult, "_resolve_tool"), "T7: SkillResult was not given a _resolve_tool attribute")
    check(SkillError.__module__ == "Orchestration.base_skill", "T7: SkillError still lives in Orchestration.base_skill, unmoved")
    check(SkillResult.__module__ == "Orchestration.skill_result", "T7: SkillResult still lives in Orchestration.skill_result, unmoved")


def main() -> int:
    scenarios = [
        scenario_return_annotation,
        scenario_execute_remains_abstract,
        scenario_concrete_subclass_returns_skill_result,
        scenario_execute_tool_unchanged,
        scenario_ast_verification,
        scenario_namespace_and_public_api,
        scenario_no_cross_wiring,
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
    print(f"PHASE 8 SPRINT 88 BASE SKILL SKILL RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())