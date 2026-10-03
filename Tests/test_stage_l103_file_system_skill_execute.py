"""Phase 9 Sprint 103: FileSystemSkill.execute() -- the second real,
deterministic Skill implementation. Always returns
SkillResult(success=True, output=None, error=None, metadata={}),
regardless of context -- no filesystem access, no I/O, no Tool, no
Runtime/Workflow/Provider/Repository/Service involvement, no context
inspection or mutation. Table-driven, no pytest.
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

from Orchestration.file_system_skill import FileSystemSkill
from Orchestration.skill_result import SkillResult

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


class _AngryContext:
    """Raises on any attribute access/mutation -- proves context is
    never inspected or mutated."""

    def __getattr__(self, name):
        raise AssertionError(f"execute() must never read context.{name}")

    def __setattr__(self, name, value):
        raise AssertionError(f"execute() must never mutate context.{name}")


# === GROUP A: behavior =======================================================
def scenario_returns_skill_result() -> None:
    result = FileSystemSkill().execute(None)
    check(isinstance(result, SkillResult), "V1: returns a SkillResult instance")


def scenario_success_true() -> None:
    result = FileSystemSkill().execute(None)
    check(result.success is True, "V2: success is True")


def scenario_error_none() -> None:
    result = FileSystemSkill().execute(None)
    check(result.error is None, "V3: error is None")


def scenario_output_generic() -> None:
    result = FileSystemSkill().execute(None)
    check(result.output is None, "V4: output is generic (None)")


def scenario_metadata_empty() -> None:
    result = FileSystemSkill().execute(None)
    check(dict(result.metadata) == {}, "V5: metadata == {}")


def scenario_deterministic_across_calls() -> None:
    skill = FileSystemSkill()
    r1 = skill.execute(None)
    r2 = skill.execute("anything")
    r3 = skill.execute({"a": 1})
    check(r1 == r2 == r3, "V6: deterministic across repeated calls with varying context")


def scenario_deterministic_across_instances() -> None:
    r1 = FileSystemSkill().execute(None)
    r2 = FileSystemSkill().execute(None)
    check(r1 == r2, "V7: deterministic across separate instances")


def scenario_context_never_inspected_or_mutated() -> None:
    angry = _AngryContext()
    result = FileSystemSkill().execute(angry)
    check(isinstance(result, SkillResult), "V8: succeeds with an angry context, unread and unmutated")
    check(result.success is True, "V9: result unaffected by the context object")


def scenario_no_exception_raised() -> None:
    exc = None
    try:
        FileSystemSkill().execute(None)
    except Exception as e:  # noqa: BLE001
        exc = e
    check(exc is None, f"V10: execute() never raises; got {exc!r}")


def scenario_name_and_description_untouched() -> None:
    skill = FileSystemSkill()
    check(skill.name == "filesystem", "V11: name unchanged")
    check(skill.description == "Read and write files.", "V12: description unchanged")


# === GROUP B: AST / namespace / import verification =========================
def scenario_ast_verification() -> None:
    src = textwrap.dedent(inspect.getsource(FileSystemSkill.execute))
    tree = ast.parse(src)
    fn = tree.body[0]
    check(fn.name == "execute", "V13: method named 'execute'")
    params = [a.arg for a in fn.args.args]
    check(params == ["self", "context"], f"V14: signature is (self, context); got {params}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    call_names = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", None))
        for c in calls
    }
    call_names.discard(None)
    check(call_names == {"SkillResult"}, f"V15: only SkillResult(...) is called; got {call_names}")

    forbidden = {
        "os", "pathlib", "Path", "shutil", "open", "glob", "tempfile",
        "json", "yaml", "sqlite3", "requests", "subprocess",
        "Runtime", "Workflow", "Planner", "Provider", "Repository",
        "Service", "logging", "logger", "cache", "retry", "context",
    }
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    # 'context' appears only as the unused parameter name, never referenced
    # in the body -- excluded from the forbidden-name check above and
    # verified separately below.
    forbidden.discard("context")
    check(forbidden.isdisjoint(referenced), f"V16: no forbidden name referenced (overlap {forbidden & referenced})")

    body_names = {
        n.id
        for node in fn.body
        for n in ast.walk(node)
        if isinstance(n, ast.Name)
    }
    check("context" not in body_names, "V17: 'context' parameter never referenced inside the body")

    has_loop_or_try = any(
        isinstance(n, (ast.For, ast.While, ast.Try, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for n in ast.walk(tree)
    )
    check(has_loop_or_try is False, "V18: no loop or try/except in the method body")

    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    check(len(returns) == 1, "V19: exactly one return statement")
    check(
        isinstance(returns[0].value, ast.Call)
        and isinstance(returns[0].value.func, ast.Name)
        and returns[0].value.func.id == "SkillResult",
        "V20: returns a SkillResult(...) constructed inline",
    )

    sr_call = returns[0].value
    kwargs = {kw.arg: kw.value for kw in sr_call.keywords}
    check(set(kwargs.keys()) == {"success", "output", "error", "metadata"}, f"V21: exactly the four fields; got {set(kwargs.keys())}")
    check(isinstance(kwargs["success"], ast.Constant) and kwargs["success"].value is True, "V22: success=True")
    check(isinstance(kwargs["output"], ast.Constant) and kwargs["output"].value is None, "V23: output=None")
    check(isinstance(kwargs["error"], ast.Constant) and kwargs["error"].value is None, "V24: error=None")
    check(isinstance(kwargs["metadata"], ast.Dict) and len(kwargs["metadata"].keys) == 0, "V25: metadata={}")

    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    check(len(assigns) == 0, "V26: no assignment/caching inside the method")


def scenario_module_imports_and_surface() -> None:
    module_tree = ast.parse((ROOT / "Orchestration" / "file_system_skill.py").read_text())
    from_modules = {n.module for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom)}
    imported = {n.module for n in ast.walk(module_tree) if isinstance(n, ast.Import)}
    stdlib_imports = {alias.name for n in ast.walk(module_tree) if isinstance(n, ast.Import) for alias in n.names}

    check(from_modules == {"__future__", "typing", "Orchestration.base_skill", "Orchestration.skill_result"}, f"V27: only sanctioned from-imports; got {from_modules}")
    check(not imported, f"V28: no bare 'import X' statements; got {imported}")
    check(stdlib_imports == set(), "V29: no stray stdlib imports")

    forbidden_modules = {
        "os", "pathlib", "glob", "shutil", "tempfile", "zipfile", "json",
        "yaml", "sqlite3", "requests", "subprocess",
        "Orchestration.skill_registry", "Orchestration.skill_resolver",
        "Orchestration.executor", "Core.runtime", "Orchestration.workflow",
        "Orchestration.planner", "Providers", "Repository",
    }
    check(forbidden_modules.isdisjoint(from_modules), f"V30: no forbidden module imported (overlap {forbidden_modules & from_modules})")

    public_methods = {n for n in dir(FileSystemSkill) if not n.startswith("_") and callable(getattr(FileSystemSkill, n, None))}
    check(public_methods == {"execute", "execute_tool", "execute_tool_result"}, f"V31: no new public callable added beyond BaseSkill's own; got {public_methods}")

    signature = inspect.signature(FileSystemSkill.execute)
    params = [p for p in signature.parameters if p != "self"]
    check(params == ["context"], "V32: execute(context) takes exactly one argument beyond self")


def main() -> int:
    for scenario in [
        scenario_returns_skill_result,
        scenario_success_true,
        scenario_error_none,
        scenario_output_generic,
        scenario_metadata_empty,
        scenario_deterministic_across_calls,
        scenario_deterministic_across_instances,
        scenario_context_never_inspected_or_mutated,
        scenario_no_exception_raised,
        scenario_name_and_description_untouched,
        scenario_ast_verification,
        scenario_module_imports_and_surface,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()

    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 9 SPRINT 103 FILESYSTEM-SKILL-EXECUTE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())