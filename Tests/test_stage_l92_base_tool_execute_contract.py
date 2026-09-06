"""Phase 8 Sprint 92 -- ``BaseTool.execute()`` explicit ``ToolResult``
contract restatement.

Scope: touches only ``execute()``'s docstring (prose restatement:
no validation, no wrapping, no execution). Signature/annotation
(``-> ToolResult``) and the ``ToolResult`` import already existed
since Sprint 86, unchanged. ``execute()`` stays ``@abstractmethod``,
body still exactly ``raise NotImplementedError``, no return. No
constructor/helper/attribute/state/cache/retry/logging/validation
added. Compact, table-driven, no-pytest style.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_tool import BaseTool
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


# T1 -- execute()'s signature/annotation
def scenario_return_annotation() -> None:
    ann = inspect.signature(BaseTool.execute).return_annotation
    ok = ann == "ToolResult" or ann is ToolResult
    check(ok, f"T1: execute()'s return annotation is ToolResult; got {ann!r}")

    params = inspect.signature(BaseTool.execute).parameters
    check(list(params) == ["self", "context"], "T1: parameter list unchanged (self, context)")
    ctx_ann = params["context"].annotation
    check(ctx_ann in ("Any", Any), "T1: parameter 'context' annotation unchanged (Any)")

    doc = BaseTool.execute.__doc__ or ""
    for phrase in ("ToolResult", "no validation", "no wrapping", "no execution"):
        check(phrase in doc, f"T1: execute()'s docstring states '{phrase}'")


# T2 -- execute() remains abstract, still raises NotImplementedError, no default
def scenario_execute_remains_abstract() -> None:
    check("execute" in BaseTool.__abstractmethods__, "T2: 'execute' is still listed in BaseTool.__abstractmethods__")
    check(
        getattr(BaseTool.execute, "__isabstractmethod__", False) is True,
        "T2: BaseTool.execute is still marked __isabstractmethod__ == True",
    )

    class _Incomplete(BaseTool):
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

    class _Complete(BaseTool):
        @property
        def name(self) -> str:
            return "complete"

        @property
        def description(self) -> str:
            return "implements execute()"

        def execute(self, context: Any) -> ToolResult:
            return ToolResult(success=True, output=context)

    raised2 = False
    try:
        BaseTool.execute(_Complete(), "ctx")  # calls the base body directly
    except NotImplementedError:
        raised2 = True
    check(raised2, "T2: calling BaseTool.execute() directly still raises NotImplementedError")


# T3 -- BaseTool's abstract members unchanged; subclasses still required to implement execute()
def scenario_abstract_members_unchanged() -> None:
    check(
        BaseTool.__abstractmethods__ == frozenset({"name", "description", "execute"}),
        "T3: BaseTool's abstract members are unchanged",
    )
    raised = False
    try:
        BaseTool()  # type: ignore[abstract]
    except TypeError:
        raised = True
    check(raised, "T3: BaseTool() still cannot be instantiated")

    class _MissingExecute(BaseTool):
        @property
        def name(self) -> str:
            return "n"

        @property
        def description(self) -> str:
            return "d"

    raised2 = False
    try:
        _MissingExecute()  # type: ignore[abstract]
    except TypeError:
        raised2 = True
    check(raised2, "T3: a subclass omitting execute() is still rejected at instantiation")

    check(
        getattr(BaseTool.name.fget, "__isabstractmethod__", False) is True,
        "T3: 'name' property is still abstract",
    )
    check(
        getattr(BaseTool.description.fget, "__isabstractmethod__", False) is True,
        "T3: 'description' property is still abstract",
    )
    name_doc = BaseTool.name.fget.__doc__ or ""
    check("Tool's name" in name_doc, "T3: 'name' property docstring is unchanged")
    desc_doc = BaseTool.description.fget.__doc__ or ""
    check("Tool's description" in desc_doc, "T3: 'description' property docstring is unchanged")


# T4 -- no constructor, no attributes, no helpers, no class variables, stateless
def scenario_no_constructor_no_helpers() -> None:
    check("__init__" not in vars(BaseTool), "T4: BaseTool still defines no __init__ of its own")

    public_members = {
        n for n in dir(BaseTool)
        if not n.startswith("_")
        and (callable(vars(BaseTool).get(n) or getattr(BaseTool, n, None))
             or isinstance(vars(BaseTool).get(n), property))
    }
    check(
        public_members == {"name", "description", "execute"},
        f"T4: public surface unchanged -- exactly name/description/execute; got {public_members!r}",
    )
    check(
        not any(
            k for k in vars(BaseTool)
            if not k.startswith("__") and k not in ("name", "description", "execute", "_abc_impl")
        ),
        "T4: no additional class variable was added to BaseTool",
    )
    check(
        not hasattr(BaseTool, "cache") and not hasattr(BaseTool, "_cache")
        and not hasattr(BaseTool, "retry") and not hasattr(BaseTool, "validate"),
        "T4: no cache/retry/validate helper was added to BaseTool",
    )


# T5 -- AST verification: exactly one ToolResult import, no forbidden tokens
def scenario_ast_verification() -> None:
    import Orchestration.base_tool as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    top_modules, names = set(), set()
    tool_result_import_count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top_modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_modules.add(node.module.split(".")[0])
            names.update(a.name for a in node.names)
            if node.module == "Orchestration.tool_result":
                tool_result_import_count += sum(1 for a in node.names if a.name == "ToolResult")

    check(
        top_modules == {"__future__", "abc", "typing", "Orchestration"},
        f"T5: top-level imported modules exactly as expected; got {top_modules!r}",
    )
    check(
        names == {"annotations", "ABC", "abstractmethod", "Any", "ToolResult"},
        f"T5: imported names exactly as expected; got {names!r}",
    )
    check(tool_result_import_count == 1, "T5: ToolResult is imported exactly once")

    imported_tokens = top_modules | names
    architecture_tokens = (
        "Runtime", "Workflow", "Executor", "Planner", "Registry",
        "Resolver", "ToolManager", "Service", "Repository", "Provider",
    )
    check(
        not any(any(tok in t for t in imported_tokens) for tok in architecture_tokens),
        f"T5: no import statement references any architecture token {architecture_tokens!r}",
    )

    docstring_spans = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant
            ) and isinstance(body[0].value.value, str):
                docstring_spans.add((body[0].lineno, body[0].end_lineno))

    code_lines = [
        line for i, line in enumerate(source.splitlines(), start=1)
        if not any(start <= i <= end for start, end in docstring_spans)
    ]
    non_docstring_source = "\n".join(code_lines)

    operational_tokens = ("isinstance(", "logging", "logger", "retry", "cache")
    check(
        not any(tok in non_docstring_source for tok in operational_tokens),
        f"T5: non-docstring source contains none of the forbidden operational tokens {operational_tokens!r}",
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
    check("return" not in code_only, "T5: execute()'s code body contains no return statement")

    decorator_names = {
        d.id if isinstance(d, ast.Name) else getattr(d, "attr", None)
        for d in execute_node.decorator_list
    }
    check(
        decorator_names == {"abstractmethod"},
        f"T5: execute()'s decorators are unchanged -- exactly @abstractmethod; got {decorator_names!r}",
    )


# T6 -- namespace verification
def scenario_namespace_verification() -> None:
    import Orchestration.base_tool as mod

    check(hasattr(mod, "ToolResult"), "T6: module namespace exposes ToolResult")
    check(mod.ToolResult is ToolResult, "T6: mod.ToolResult is the same object as Orchestration.tool_result.ToolResult")
    check(hasattr(mod, "BaseTool"), "T6: module namespace exposes BaseTool")


def main() -> int:
    scenarios = [
        scenario_return_annotation,
        scenario_execute_remains_abstract,
        scenario_abstract_members_unchanged,
        scenario_no_constructor_no_helpers,
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
    print(f"PHASE 8 SPRINT 92 BASE TOOL EXECUTE CONTRACT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())