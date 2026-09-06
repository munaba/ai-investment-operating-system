"""Phase 8 Sprint 86 proof suite -- ``ToolResult`` + the
``BaseTool.execute()`` contract update.

Scope: ``Orchestration.tool_result.ToolResult``/``ToolResultError``
and ``Orchestration.base_tool.BaseTool.execute``'s annotation/doc
only. No concrete Tool, registry, resolver, or runtime is touched.

Mirrors ``Orchestration.skill_result.SkillResult``: a frozen,
four-field dataclass (success/output/error/metadata), no methods
beyond __post_init__/__hash__, no extra public surface. Table-driven,
no pytest, global pass/fail counter + main() runner (same style as
the other Stage L4x/L5x/L8x proof suites).

Invariants (T1-T15): construction/no-coercion; no defaults; frozen
instance + frozen/copied metadata; success/metadata validation
(output/error unconstrained); hash(success)-only hashing; full-field
equality; exact field set + absence of forbidden attrs; no extra
methods; ToolResultError is a bare AgentError subclass; AST-verified
imports; forbidden-symbol absence; module namespace exactness; and
the BaseTool.execute contract (return annotation + docstring mention
ToolResult; everything else about BaseTool unchanged).
"""

from __future__ import annotations

import ast
import inspect
import sys
import traceback
from dataclasses import MISSING, FrozenInstanceError, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.tool_result import ToolResult, ToolResultError
from Orchestration.base_tool import BaseTool

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

def mk(**kw):
    base = dict(success=True, output=None, error=None, metadata={})
    base.update(kw)
    return ToolResult(**base)

# T1 -- construction stores fields exactly, uncoerced
def scenario_construction() -> None:
    out, err = {"rows": [1, 2]}, ValueError("boom")
    r = ToolResult(success=False, output=out, error=err, metadata={"a": 2})
    check(r.success is False, "T1: success stored exactly")
    check(r.output == out, "T1: output stored exactly, uncoerced")
    check(r.error is err, "T1: error stored exactly, uncoerced (identity)")
    check(dict(r.metadata) == {"a": 2}, "T1: metadata stored exactly")
    for value in (None, 0, False, "", [], object(), 3.14):
        check(mk(output=value) is not None, f"T1: output={value!r} unconstrained")
        check(mk(error=value) is not None, f"T1: error={value!r} unconstrained")

# T2 -- frozen instance
def scenario_frozen() -> None:
    r = mk()
    for attr, val in (("success", False), ("output", "x"), ("error", "e"), ("metadata", {})):
        raised = False
        try:
            setattr(r, attr, val)
        except FrozenInstanceError:
            raised = True
        check(raised, f"T2: reassigning '{attr}' raises FrozenInstanceError")

# T3 -- no default values on any field
def scenario_no_defaults() -> None:
    for kwargs in ({}, {"success": True}, {"success": True, "output": None}):
        raised = False
        try:
            ToolResult(**kwargs)  # type: ignore[arg-type]
        except TypeError:
            raised = True
        check(raised, f"T3: ToolResult(**{kwargs}) raises TypeError (missing fields)")
    for f in fields(ToolResult):
        check(
            f.default is MISSING and f.default_factory is MISSING,
            f"T3: field '{f.name}' has neither default nor default_factory",
        )

# T4 -- validation: success/metadata checked, output/error are not
def scenario_validation() -> None:
    for bad in (None, 0, 1, "true", [], {}, 1.0):
        raised = False
        try:
            mk(success=bad)
        except ToolResultError:
            raised = True
        check(raised, f"T4: success={bad!r} (non-bool) raises ToolResultError")
    for good in (True, False):
        check(mk(success=good) is not None, f"T4: success={good!r} does not raise")
    for bad in ("nope", 123, ["a"], None, object()):
        raised = False
        try:
            mk(metadata=bad)
        except ToolResultError:
            raised = True
        check(raised, f"T4: metadata={bad!r} (not a Mapping) raises ToolResultError")
    for good in ({}, {"k": "v"}, MappingProxyType({"k": "v"})):
        check(mk(metadata=good) is not None, f"T4: metadata={good!r} does not raise")

    try:
        mk(success="bad")
        agent_error_caught = False
    except AgentError:
        agent_error_caught = True
    check(agent_error_caught, "T4/T6: ToolResultError catchable as AgentError")
    check(issubclass(ToolResultError, AgentError), "T6: ToolResultError subclasses AgentError")
    check(ToolResultError.__bases__ == (AgentError,), "T6: no intermediate exception layer")
    check(not is_dataclass(ToolResultError), "T6: ToolResultError is not a dataclass")
    check(
        ToolResultError.__dict__.keys() <= {"__doc__", "__module__"},
        "T6: ToolResultError adds no members beyond its docstring",
    )

# T5 -- metadata frozen + copied, not aliased
def scenario_metadata_frozen_and_copied() -> None:
    original = {"k": "v"}
    r = mk(metadata=original)
    check(isinstance(r.metadata, MappingProxyType), "T5: metadata is a MappingProxyType")
    for key, val, label in (("k", "x", "mutate existing key"), ("new", 1, "add new key")):
        raised = False
        try:
            r.metadata[key] = val  # type: ignore[index]
        except TypeError:
            raised = True
        check(raised, f"T5: attempting to {label} on result.metadata raises TypeError")
    original["k"] = "changed"
    original["new"] = "added"
    check(dict(r.metadata) == {"k": "v"}, "T5: mutating the original dict does not affect result.metadata")

# T7 -- hashing: hash(success) only
def scenario_hashing() -> None:
    a = mk(success=True, output=[1, 2], error={"x": 1}, metadata={"k": 1})
    b = mk(success=True, output="other", error=None, metadata={})
    raised = False
    try:
        hash(a)
    except TypeError:
        raised = True
    check(not raised, "T7: hash() does not raise despite unhashable output/error/metadata")
    check(hash(a) == hash(True) == hash(b), "T7: hash depends only on 'success'")
    check(hash(mk(success=False)) == hash(False), "T7: hash(success=False) == hash(False)")
    same = mk(success=True, output=[1, 2], error={"x": 1}, metadata={"k": 1})
    check(same == a and same in {a}, "T7: an equal instance is a valid set member")
    check({a: "found"}.get(same) == "found", "T7: hash/eq contract holds for dict lookup")

# T8 -- equality: all four fields must match
def scenario_equality() -> None:
    a = mk(output="x", metadata={"k": 1})
    check(a == mk(output="x", metadata={"k": 1}), "T8: identical-field instances are equal")
    variants = {
        "success": mk(success=False, output="x", metadata={"k": 1}),
        "output": mk(output="y", metadata={"k": 1}),
        "error": mk(output="x", error="oops", metadata={"k": 1}),
        "metadata value": mk(output="x", metadata={"k": 2}),
        "metadata absent": mk(output="x", metadata={}),
    }
    for label, variant in variants.items():
        check(a != variant, f"T8: changing only '{label}' breaks equality")
    same_success_only = mk(output="different", error="also-different", metadata={"z": True})
    check(
        hash(a) == hash(same_success_only) and a != same_success_only,
        "T8: sharing only 'success' hashes equal without being equal",
    )

# T9 -- exact field set, forbidden attrs absent
def scenario_field_set_and_forbidden_attrs() -> None:
    r = mk()
    check(
        {f.name for f in fields(ToolResult)} == {"success", "output", "error", "metadata"},
        "T9: dataclass fields are exactly success/output/error/metadata",
    )
    for attr in (
        "duration", "latency", "token_usage", "cost", "provider", "trace", "logs",
        "stacktrace", "retry", "warnings", "events", "memory", "workflow", "executor",
        "scheduler", "runtime", "reflection", "learning", "agent", "host",
    ):
        check(not hasattr(ToolResult, attr) and not hasattr(r, attr), f"T9: no '{attr}' attribute")

# T10 -- no methods beyond dataclass machinery + __post_init__/__hash__
def scenario_no_extra_methods() -> None:
    allowed = {
        "__init__", "__repr__", "__eq__", "__hash__", "__setattr__", "__delattr__",
        "__post_init__", "__class__", "__dict__", "__doc__", "__module__", "__weakref__",
        "__dataclass_fields__", "__dataclass_params__", "__match_args__",
    }
    field_names = {f.name for f in fields(ToolResult)}
    own = set(vars(ToolResult).keys())
    unexpected = {
        n for n in own
        if n not in allowed and n not in field_names and not (n.startswith("__") and n.endswith("__"))
    }
    check(unexpected == set(), f"T10: no unexpected members; got {sorted(unexpected)!r}")
    check(callable(ToolResult.__dict__.get("__post_init__")), "T10: defines its own __post_init__")
    check(callable(ToolResult.__dict__.get("__hash__")), "T10: defines its own __hash__")
    public = {n for n in dir(ToolResult) if not n.startswith("_") and callable(getattr(ToolResult, n, None))}
    check(public == set(), f"T10: no public methods; got {sorted(public)!r}")

# T11 -- AST-verified imports (Orchestration/tool_result.py)
def scenario_ast_imports() -> None:
    import Orchestration.tool_result as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    top_modules, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top_modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_modules.add(node.module.split(".")[0])
            names.update(a.name for a in node.names)
    check(
        top_modules == {"__future__", "dataclasses", "types", "typing", "Core"},
        f"T11: top-level imported modules exactly as expected; got {top_modules!r}",
    )
    check(
        names == {"annotations", "dataclass", "MappingProxyType", "Any", "Mapping", "AgentError"},
        f"T11: imported names exactly as expected; got {names!r}",
    )

# T12 -- forbidden symbols absent (source text + module namespace)
def scenario_forbidden_symbols() -> None:
    import Orchestration.tool_result as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    for symbol in (
        "BaseTool", "BaseSkill", "SkillResult", "ToolRegistry", "ToolResolver",
        "Executor", "WorkflowRuntime", "WorkflowEngine", "Planner", "Runtime", "composition_root",
    ):
        check(
            f"import {symbol}" not in source and f"{symbol}(" not in source,
            f"T12: source has no reference to '{symbol}'",
        )
        check(not hasattr(mod, symbol), f"T12: module namespace has no '{symbol}' symbol")

# T13 -- module namespace exactness
def scenario_namespace() -> None:
    import Orchestration.tool_result as mod

    public = {
        n for n in dir(mod)
        if not n.startswith("_") and getattr(mod, n).__module__ == "Orchestration.tool_result"
    }
    check(public == {"ToolResult", "ToolResultError"}, f"T13: public symbols exactly as expected; got {public!r}")
    check(not issubclass(ToolResult, Exception), "T13: ToolResult is not an Exception")
    check(is_dataclass(ToolResult), "T13: ToolResult is a dataclass")

# T14 -- BaseTool.execute contract: return annotation + docstring
def scenario_base_tool_execute_contract() -> None:
    ann = inspect.signature(BaseTool.execute).return_annotation
    ok = ann == "ToolResult" or ann is ToolResult
    check(ok, f"T14: execute()'s return annotation refers to ToolResult; got {ann!r}")
    check("ToolResult" in (BaseTool.execute.__doc__ or ""), "T14: execute()'s docstring mentions ToolResult")

# T15 -- everything else about BaseTool is unchanged
def scenario_base_tool_otherwise_unchanged() -> None:
    check(
        BaseTool.__abstractmethods__ == frozenset({"name", "description", "execute"}),
        "T15: abstract members still exactly name/description/execute",
    )
    raised = False
    try:
        BaseTool()  # type: ignore[abstract]
    except TypeError:
        raised = True
    check(raised, "T15: BaseTool() still cannot be instantiated")
    check("__init__" not in vars(BaseTool), "T15: BaseTool still defines no __init__ of its own")

    class _MinimalTool(BaseTool):
        @property
        def name(self) -> str:
            return "minimal"

        @property
        def description(self) -> str:
            return "a minimal tool"

        def execute(self, context):
            return ToolResult(success=True, output=context, error=None, metadata={})

    tool = _MinimalTool()
    check(isinstance(tool, BaseTool), "T15: minimal subclass still constructs")
    outcome = tool.execute("ctx")
    check(
        isinstance(outcome, ToolResult) and outcome.output == "ctx",
        "T15: a concrete Tool can now return a ToolResult per the updated contract",
    )
    for attr in (
        "metadata", "priority", "tags", "category", "permissions", "config", "schema",
        "registry", "tool_id", "aliases", "requirements", "dependencies", "execute_async",
        "capability", "timeout", "retry",
    ):
        check(not hasattr(BaseTool, attr), f"T15: BaseTool still has no '{attr}' attribute/method")

def main() -> int:
    scenarios = [
        scenario_construction,
        scenario_frozen,
        scenario_no_defaults,
        scenario_validation,
        scenario_metadata_frozen_and_copied,
        scenario_hashing,
        scenario_equality,
        scenario_field_set_and_forbidden_attrs,
        scenario_no_extra_methods,
        scenario_ast_imports,
        scenario_forbidden_symbols,
        scenario_namespace,
        scenario_base_tool_execute_contract,
        scenario_base_tool_otherwise_unchanged,
    ]
    for scenario in scenarios:
        print(f"\n[{scenario.__name__}]")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 86 TOOL RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())