"""Phase 8 Sprint 93 proof suite -- ``ToolInvocation``, the immutable
boundary contract between Skill and Tool execution.

Scope: ``Orchestration.tool_invocation.ToolInvocation``/
``ToolInvocationError`` only. This sprint does not execute tools; no
Runtime, Executor, Planner, ToolResolver, ToolManager, or
ToolRegistry is touched or referenced.

Table-driven, no pytest, global pass/fail counter + main() runner
(same style as the other Stage L8x/L9x proof suites).

Invariants (T1-T15, ~40 checks): valid construction; invalid
tool_name; metadata is a Mapping; metadata frozen; context identity
preserved; metadata copied not aliased; equality; hashing;
immutability; exact field set; no extra methods; public API +
ToolInvocationError hierarchy; AST-verified imports; forbidden
symbols/execution semantics absent; multi-instance independence.
"""

from __future__ import annotations

import ast
import sys
import traceback
from dataclasses import MISSING, FrozenInstanceError, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.tool_invocation import ToolInvocation, ToolInvocationError

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
    base = dict(tool_name="market_price_tool", context=None, metadata={})
    base.update(kw)
    return ToolInvocation(**base)

def raises(fn, exc) -> bool:
    try:
        fn()
        return False
    except exc:
        return True

# T1 -- valid construction stores fields exactly, uncoerced
def scenario_valid_construction() -> None:
    ctx = {"symbol": "AAPL"}
    inv = ToolInvocation(tool_name="price_tool", context=ctx, metadata={"a": 1})
    check(inv.tool_name == "price_tool", "T1: tool_name stored exactly")
    check(inv.context is ctx, "T1: context stored exactly (identity)")
    check(dict(inv.metadata) == {"a": 1}, "T1: metadata stored exactly")
    for name in (" a ", "x", "a-b_c.d", "Tool123"):
        check(mk(tool_name=name).tool_name == name, f"T1: tool_name={name!r} accepted verbatim")

# T2 -- invalid tool_name (type + emptiness + whitespace)
def scenario_invalid_tool_name() -> None:
    for bad in (None, 0, 1, 3.14, [], {}, ("t",), object(), True, False):
        ok = raises(lambda bad=bad: mk(tool_name=bad), ToolInvocationError)
        check(ok, f"T2: tool_name={bad!r} (non-str) raises ToolInvocationError")
    for bad in ("", " ", "\t", "\n", "   \t\n  "):
        ok = raises(lambda bad=bad: mk(tool_name=bad), ToolInvocationError)
        check(ok, f"T2: tool_name={bad!r} (empty/whitespace) raises ToolInvocationError")
    for good in ("t", " t ", "tool_name"):
        check(mk(tool_name=good) is not None, f"T2: tool_name={good!r} does not raise")

# T3 -- metadata must be a Mapping
def scenario_metadata_is_mapping() -> None:
    for bad in ("nope", 123, ["a"], None, object(), (1, 2)):
        ok = raises(lambda bad=bad: mk(metadata=bad), ToolInvocationError)
        check(ok, f"T3: metadata={bad!r} (not a Mapping) raises ToolInvocationError")
    for good in ({}, {"k": "v"}, MappingProxyType({"k": "v"})):
        check(mk(metadata=good) is not None, f"T3: metadata={good!r} does not raise")

# T4 -- metadata frozen (external view is immutable)
def scenario_metadata_frozen() -> None:
    inv = mk(metadata={"k": "v"})
    check(isinstance(inv.metadata, MappingProxyType), "T4: metadata is a MappingProxyType")
    def _set(key, val):
        inv.metadata[key] = val
    for key, val, label in (("k", "x", "mutate existing key"), ("new", 1, "add new key")):
        ok = raises(lambda key=key, val=val: _set(key, val), TypeError)
        check(ok, f"T4: attempting to {label} on invocation.metadata raises TypeError")
    def _del():
        del inv.metadata["k"]
    ok = raises(_del, TypeError)
    check(ok, "T4: attempting to delete a key from invocation.metadata raises TypeError")

# T5 -- context identity preserved (unconstrained, uncopied)
def scenario_context_identity() -> None:
    for ctx in (None, 0, "", [], {}, object(), [1, 2, 3], {"nested": {"x": 1}}):
        inv = mk(context=ctx)
        check(inv.context is ctx, f"T5: context={ctx!r} identity preserved")
    mutable_ctx = {"x": 1}
    inv = mk(context=mutable_ctx)
    mutable_ctx["x"] = 2
    check(inv.context is mutable_ctx and inv.context["x"] == 2, "T5: context is not copied/frozen")

# T6 -- metadata copied then frozen, not aliased
def scenario_metadata_copied_then_frozen() -> None:
    original = {"k": "v"}
    inv = mk(metadata=original)
    check(inv.metadata is not original, "T6: metadata is not the same object as the input dict")
    original["k"] = "changed"
    original["new"] = "added"
    check(dict(inv.metadata) == {"k": "v"}, "T6: mutating the original dict after construction has no effect")

# T7 -- equality: all three fields must match
def scenario_equality() -> None:
    ctx = object()
    a = mk(tool_name="t1", context=ctx, metadata={"k": 1})
    check(a == mk(tool_name="t1", context=ctx, metadata={"k": 1}), "T7: identical-field instances are equal")
    variants = {
        "tool_name": mk(tool_name="t2", context=ctx, metadata={"k": 1}),
        "context": mk(tool_name="t1", context=object(), metadata={"k": 1}),
        "metadata value": mk(tool_name="t1", context=ctx, metadata={"k": 2}),
        "metadata absent": mk(tool_name="t1", context=ctx, metadata={}),
    }
    for label, variant in variants.items():
        check(a != variant, f"T7: changing only '{label}' breaks equality")
    check(a != "not an invocation", "T7: not equal to a non-ToolInvocation value")

# T8 -- hashing: hash(tool_name) only
def scenario_hashing() -> None:
    a = mk(tool_name="t1", context=[1, 2], metadata={"k": 1})
    b = mk(tool_name="t1", context="other", metadata={})
    ok = raises(lambda: hash(a), TypeError)
    check(not ok, "T8: hash() does not raise despite unhashable context/metadata")
    check(hash(a) == hash("t1") == hash(b), "T8: hash depends only on 'tool_name'")
    same = mk(tool_name="t1", context=[1, 2], metadata={"k": 1})
    check(same == a and same in {a}, "T8: an equal instance is a valid set member")
    check({a: "found"}.get(same) == "found", "T8: hash/eq contract holds for dict lookup")

# T9 -- immutability: frozen instance
def scenario_immutability() -> None:
    inv = mk()
    for attr, val in (("tool_name", "other"), ("context", "x"), ("metadata", {})):
        ok = raises(lambda attr=attr, val=val: setattr(inv, attr, val), FrozenInstanceError)
        check(ok, f"T9: reassigning '{attr}' raises FrozenInstanceError")
    ok = raises(lambda: delattr(inv, "tool_name"), (FrozenInstanceError, AttributeError))
    check(ok, "T9: deleting 'tool_name' raises")
    for kwargs in ({}, {"tool_name": "t"}, {"tool_name": "t", "context": None}):
        ok = raises(lambda kwargs=kwargs: ToolInvocation(**kwargs), TypeError)  # type: ignore[arg-type]
        check(ok, f"T9: ToolInvocation(**{kwargs}) raises TypeError (missing fields, no defaults)")
    for f in fields(ToolInvocation):
        ok = f.default is MISSING and f.default_factory is MISSING
        check(ok, f"T9: field '{f.name}' has neither default nor default_factory")

# T10 -- exact field set, no extra fields
def scenario_field_set() -> None:
    check(
        {f.name for f in fields(ToolInvocation)} == {"tool_name", "context", "metadata"},
        "T10: dataclass fields are exactly tool_name/context/metadata",
    )
    inv = mk()
    for attr in (
        "duration", "latency", "timeout", "retry", "priority", "cache", "logs",
        "trace", "events", "memory", "workflow", "executor", "scheduler",
        "runtime", "reflection", "learning", "agent", "host", "result", "output",
    ):
        check(not hasattr(ToolInvocation, attr) and not hasattr(inv, attr), f"T10: no '{attr}' attribute")

# T11 -- no methods beyond dataclass machinery + __post_init__/__hash__
def scenario_no_extra_methods() -> None:
    allowed = {
        "__init__", "__repr__", "__eq__", "__hash__", "__setattr__", "__delattr__",
        "__post_init__", "__class__", "__dict__", "__doc__", "__module__", "__weakref__",
        "__dataclass_fields__", "__dataclass_params__", "__match_args__",
    }
    field_names = {f.name for f in fields(ToolInvocation)}
    own = set(vars(ToolInvocation).keys())
    unexpected = {
        n for n in own
        if n not in allowed and n not in field_names and not (n.startswith("__") and n.endswith("__"))
    }
    check(unexpected == set(), f"T11: no unexpected members; got {sorted(unexpected)!r}")
    check(callable(ToolInvocation.__dict__.get("__post_init__")), "T11: defines its own __post_init__")
    check(callable(ToolInvocation.__dict__.get("__hash__")), "T11: defines its own __hash__")
    public = {n for n in dir(ToolInvocation) if not n.startswith("_") and callable(getattr(ToolInvocation, n, None))}
    check(public == set(), f"T11: no public methods; got {sorted(public)!r}")

# T12 -- public API exact + ToolInvocationError hierarchy
def scenario_public_api_and_error_hierarchy() -> None:
    import Orchestration.tool_invocation as mod
    public = {
        n for n in dir(mod)
        if not n.startswith("_") and getattr(mod, n).__module__ == "Orchestration.tool_invocation"
    }
    check(public == {"ToolInvocation", "ToolInvocationError"}, f"T12: public symbols exactly as expected; got {public!r}")
    check(issubclass(ToolInvocationError, AgentError), "T12: ToolInvocationError subclasses AgentError")
    check(ToolInvocationError.__bases__ == (AgentError,), "T12: no intermediate exception layer")
    check(not is_dataclass(ToolInvocationError), "T12: ToolInvocationError is not a dataclass")
    no_extra = ToolInvocationError.__dict__.keys() <= {"__doc__", "__module__"}
    check(no_extra, "T12: ToolInvocationError adds no members beyond its docstring")
    ok = raises(lambda: mk(tool_name=""), AgentError)
    check(ok, "T12: ToolInvocationError catchable as AgentError")
    check(not issubclass(ToolInvocation, Exception), "T12: ToolInvocation is not an Exception")
    check(is_dataclass(ToolInvocation), "T12: ToolInvocation is a dataclass")

# T13 -- AST-verified imports (Orchestration/tool_invocation.py)
def scenario_ast_imports() -> None:
    import Orchestration.tool_invocation as mod
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    top_modules, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            top_modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_modules.add(node.module.split(".")[0])
            names.update(a.name for a in node.names)
    exp_mods = {"__future__", "dataclasses", "types", "typing", "Core"}
    check(top_modules == exp_mods, f"T13: top-level imported modules exactly as expected; got {top_modules!r}")
    exp_names = {"annotations", "dataclass", "MappingProxyType", "Any", "Mapping", "AgentError"}
    check(names == exp_names, f"T13: imported names exactly as expected; got {names!r}")

# T14 -- forbidden symbols absent (source text + module namespace):
# no Runtime, Workflow, Executor, Planner, Registry, Resolver,
# ToolManager, ToolRegistry, or execution semantics of any kind.
def scenario_forbidden_symbols_and_no_execution() -> None:
    import Orchestration.tool_invocation as mod
    source = Path(mod.__file__).read_text(encoding="utf-8")
    forbidden = (
        "BaseTool", "BaseSkill", "ToolResult", "SkillResult",
        "ToolRegistry", "ToolResolver", "ToolManager", "SkillRegistry",
        "SkillResolver", "Executor", "WorkflowRuntime", "WorkflowEngine",
        "Workflow", "Planner", "Runtime", "composition_root",
    )
    for symbol in forbidden:
        clean = f"import {symbol}" not in source and f"{symbol}(" not in source
        check(clean, f"T14: source has no reference to '{symbol}'")
        check(not hasattr(mod, symbol), f"T14: module namespace has no '{symbol}' symbol")
    for verb in ("def execute", "def run(", "def invoke(", "def call(", ".execute(", "import logging", "import time", "@lru_cache"):
        check(verb not in source, f"T14: source has no execution/caching/logging construct '{verb}'")
    check(not hasattr(ToolInvocation, "execute"), "T14: ToolInvocation has no execute() method")

# T15 -- multi-instance independence, no singleton/shared state
def scenario_multi_instance_independence() -> None:
    a = mk(tool_name="t1", context={"x": 1}, metadata={"m": 1})
    b = mk(tool_name="t2", context={"x": 2}, metadata={"m": 2})
    check(a is not b, "T15: two constructions produce distinct instances")
    check(a.tool_name != b.tool_name and a.context != b.context, "T15: instances hold independent field values")
    check(a.metadata is not b.metadata, "T15: instances hold independent metadata mappings")
    c = mk(tool_name="t1", context={"x": 1}, metadata={"m": 1})
    check(a is not c and a == c, "T15: equal-but-distinct instances remain separate objects")
    import Orchestration.tool_invocation as mod
    check(
        not hasattr(mod, "_instance") and not hasattr(mod, "instance"),
        "T15: module defines no singleton-style instance holder",
    )

def main() -> int:
    scenarios = [
        scenario_valid_construction,
        scenario_invalid_tool_name,
        scenario_metadata_is_mapping,
        scenario_metadata_frozen,
        scenario_context_identity,
        scenario_metadata_copied_then_frozen,
        scenario_equality,
        scenario_hashing,
        scenario_immutability,
        scenario_field_set,
        scenario_no_extra_methods,
        scenario_public_api_and_error_hierarchy,
        scenario_ast_imports,
        scenario_forbidden_symbols_and_no_execution,
        scenario_multi_instance_independence,
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
    print(f"PHASE 8 SPRINT 93 TOOL INVOCATION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())