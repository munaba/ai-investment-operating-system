"""Phase 8 Sprint 98 (Architecture Correction): ToolContext no longer
rejects task=None. task remains unconstrained Any; parameters/
metadata validation, freezing, equality, hashing unchanged. Table-
driven, no pytest, global counter + main().
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.task import Task
from Orchestration.tool_context import ToolContext, ToolContextError

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
def _catch(fn):
    try:
        fn()
        return None
    except Exception as e:  # noqa: BLE001
        return e
# --- V1-V6: task=None is now accepted ---------------------------------------
def scenario_task_none_accepted() -> None:
    exc = _catch(lambda: ToolContext(task=None, parameters={}, metadata={}))
    check(exc is None, f"V1: ToolContext(task=None, ...) no longer raises; got {exc!r}")
    ctx = ToolContext(task=None, parameters={}, metadata={})
    check(ctx.task is None, "V2: constructed instance has task=None")
    check(dict(ctx.parameters) == {}, "V3: parameters still empty")
    check(dict(ctx.metadata) == {}, "V4: metadata still empty")
    ctx2 = ToolContext(task=None)
    check(ctx2.task is None, "V5: task=None works with defaulted parameters/metadata too")
    check(dict(ctx2.parameters) == {} and dict(ctx2.metadata) == {}, "V6: defaults still apply with task=None")
# --- V7-V11: Task object and other previously-valid values still accepted --
def scenario_other_task_values_still_accepted() -> None:
    real_task = Task(name="n", description="d")
    exc1 = _catch(lambda: ToolContext(task=real_task, parameters={}, metadata={}))
    check(exc1 is None, "V7: a real Task instance is still accepted")
    check(ToolContext(task=real_task).task is real_task, "V8: Task instance preserved by identity")
    exc2 = _catch(lambda: ToolContext(task="a string task", parameters={}, metadata={}))
    check(exc2 is None, "V9: a plain string is still accepted (task remains unconstrained Any)")
    exc3 = _catch(lambda: ToolContext(task=42, parameters={}, metadata={}))
    check(exc3 is None, "V10: an int is still accepted")
    exc4 = _catch(lambda: ToolContext(task=["x"], parameters={}, metadata={}))
    check(exc4 is None, "V11: a list is still accepted")
# --- V12-V16: parameters validation unchanged -------------------------------
def scenario_parameters_validation_unchanged() -> None:
    exc = _catch(lambda: ToolContext(task=None, parameters=[], metadata={}))
    check(isinstance(exc, ToolContextError), "V12: non-Mapping parameters ([]) still raises ToolContextError")
    exc2 = _catch(lambda: ToolContext(task=None, parameters="nope", metadata={}))
    check(isinstance(exc2, ToolContextError), "V13: non-Mapping parameters (str) still raises ToolContextError")
    exc3 = _catch(lambda: ToolContext(task=None, parameters=123, metadata={}))
    check(isinstance(exc3, ToolContextError), "V14: non-Mapping parameters (int) still raises ToolContextError")
    ctx = ToolContext(task=None, parameters={"a": 1}, metadata={})
    check(dict(ctx.parameters) == {"a": 1}, "V15: valid Mapping parameters still accepted and preserved")
    exc4 = _catch(lambda: ToolContext(task=None, parameters=None, metadata={}))
    check(isinstance(exc4, ToolContextError), "V16: parameters=None still raises (parameters itself not relaxed)")
# --- V17-V21: metadata validation unchanged ---------------------------------
def scenario_metadata_validation_unchanged() -> None:
    exc = _catch(lambda: ToolContext(task=None, parameters={}, metadata=[]))
    check(isinstance(exc, ToolContextError), "V17: non-Mapping metadata ([]) still raises ToolContextError")
    exc2 = _catch(lambda: ToolContext(task=None, parameters={}, metadata="nope"))
    check(isinstance(exc2, ToolContextError), "V18: non-Mapping metadata (str) still raises ToolContextError")
    exc3 = _catch(lambda: ToolContext(task=None, parameters={}, metadata=123))
    check(isinstance(exc3, ToolContextError), "V19: non-Mapping metadata (int) still raises ToolContextError")
    ctx = ToolContext(task=None, parameters={}, metadata={"k": "v"})
    check(dict(ctx.metadata) == {"k": "v"}, "V20: valid Mapping metadata still accepted and preserved")
    exc4 = _catch(lambda: ToolContext(task=None, parameters={}, metadata=None))
    check(isinstance(exc4, ToolContextError), "V21: metadata=None still raises (metadata itself not relaxed)")
# --- V22-V25: parameters/metadata still frozen (MappingProxyType) ----------
def scenario_frozen_mappings() -> None:
    src_params = {"a": 1}
    src_meta = {"b": 2}
    ctx = ToolContext(task=None, parameters=src_params, metadata=src_meta)
    src_params["a"] = 999
    src_meta["b"] = 999
    check(dict(ctx.parameters) == {"a": 1}, "V22: mutating the original parameters dict does not affect the instance")
    check(dict(ctx.metadata) == {"b": 2}, "V23: mutating the original metadata dict does not affect the instance")
    exc_p = _catch(lambda: ctx.parameters.__setitem__("a", 0))
    check(exc_p is not None, "V24: ctx.parameters itself is immutable (MappingProxyType)")
    exc_m = _catch(lambda: ctx.metadata.__setitem__("b", 0))
    check(exc_m is not None, "V25: ctx.metadata itself is immutable (MappingProxyType)")
# --- V26-V28: task field itself remains frozen (dataclass-level) -----------
def scenario_task_field_frozen() -> None:
    ctx = ToolContext(task=None, parameters={}, metadata={})
    exc = _catch(lambda: setattr(ctx, "task", "reassigned"))
    check(exc is not None, "V26: reassigning ctx.task raises (frozen dataclass)")
    check(ctx.task is None, "V27: task unchanged after the failed reassignment attempt")
    ctx2 = ToolContext(task="x")
    exc2 = _catch(lambda: setattr(ctx2, "task", None))
    check(exc2 is not None, "V28: reassigning a non-None task to None also raises (frozen dataclass, not a task rule)")
# --- V29-V32: equality unchanged --------------------------------------------
def scenario_equality_unchanged() -> None:
    ctx_a = ToolContext(task=None, parameters={"x": 1}, metadata={"y": 2})
    ctx_b = ToolContext(task=None, parameters={"x": 1}, metadata={"y": 2})
    check(ctx_a == ctx_b, "V29: two ToolContext(task=None, ...) instances with equal fields compare equal")
    ctx_c = ToolContext(task=None, parameters={"x": 1}, metadata={"y": 3})
    check(ctx_a != ctx_c, "V30: differing metadata makes instances unequal")
    ctx_d = ToolContext(task="t", parameters={}, metadata={})
    ctx_e = ToolContext(task="t", parameters={}, metadata={})
    check(ctx_d == ctx_e, "V31: equality for non-None task still works as before")
    ctx_f = ToolContext(task=None, parameters={}, metadata={})
    ctx_g = ToolContext(task="t", parameters={}, metadata={})
    check(ctx_f != ctx_g, "V32: task=None vs task='t' are unequal")
# --- V33-V36: hashing unchanged (hash by id(task)) --------------------------
def scenario_hashing_unchanged() -> None:
    ctx1 = ToolContext(task=None, parameters={}, metadata={})
    ctx2 = ToolContext(task=None, parameters={"x": 1}, metadata={})
    check(hash(ctx1) == hash(ctx2), "V33: two task=None instances share a hash (hash(id(None)) is constant)")
    check(hash(ctx1) == hash(id(None)), "V34: hash equals hash(id(task)) exactly, task=None included")
    shared = object()
    ctx3 = ToolContext(task=shared)
    ctx4 = ToolContext(task=shared, parameters={"z": 1})
    check(hash(ctx3) == hash(ctx4), "V35: shared non-None task identity still produces the same hash")
    exc = _catch(lambda: hash(ToolContext(task=None, parameters={}, metadata={})))
    check(exc is None, "V36: hashing a task=None instance never raises")
# --- V37-V39: public API / namespace unchanged ------------------------------
def scenario_public_api_unchanged() -> None:
    public_members = {n for n in dir(ToolContext) if not n.startswith("_")}
    check(public_members == set(), f"V37: ToolContext exposes no public methods/attrs beyond dataclass fields; got {public_members}")
    fields = {f for f in ToolContext.__dataclass_fields__}
    check(fields == {"task", "parameters", "metadata"}, f"V38: exactly the same three fields; got {fields}")
    methods = {n for n in dir(ToolContext) if callable(getattr(ToolContext, n, None)) and not n.startswith("__")}
    check(methods == set(), f"V39: no new public method introduced; got {methods}")
# --- V40-V43: AST verification of __post_init__ -----------------------------
def scenario_ast_verification() -> None:
    source = inspect.getsource(ToolContext.__post_init__)
    tree = ast.parse(source.strip() if not source.startswith((" ", "\t")) else __import__("textwrap").dedent(source))
    fn = tree.body[0]
    compares = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)]
    task_is_none_checks = [
        c for c in compares
        if any(isinstance(op, ast.Is) for op in c.ops)
        and isinstance(c.left, ast.Attribute) and c.left.attr == "task"
    ]
    check(len(task_is_none_checks) == 0, "V40: no 'self.task is None' comparison remains in __post_init__")
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
    check(len(raises) == 2, f"V41: exactly two raise statements remain (parameters, metadata); got {len(raises)}")
    isinstance_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "isinstance"
    ]
    checked_attrs = {
        c.args[0].attr for c in isinstance_calls
        if c.args and isinstance(c.args[0], ast.Attribute)
    }
    check(checked_attrs == {"parameters", "metadata"}, f"V42: only parameters/metadata are isinstance-checked; got {checked_attrs}")
    forbidden = {"Runtime", "Workflow", "Planner", "Registry", "Manager", "cache", "logging", "logger", "retry"}
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    check(forbidden.isdisjoint(referenced), f"V43: no forbidden name referenced (overlap {forbidden & referenced})")
# --- V44-V46: module imports / namespace verification -----------------------
def scenario_module_imports_and_namespace() -> None:
    module_tree = ast.parse((ROOT / "Orchestration" / "tool_context.py").read_text())
    imported_names = {
        n.name.split(".")[0]
        for node in ast.walk(module_tree)
        if isinstance(node, ast.Import)
        for n in node.names
    } | {
        n.module for n in ast.walk(module_tree) if isinstance(n, ast.ImportFrom)
    }
    check(
        imported_names == {"__future__", "dataclasses", "types", "typing", "Core.exceptions"},
        f"V44: only the LOCKED dependency set is imported; got {imported_names}",
    )
    forbidden_modules = {
        "Orchestration.base_tool", "Orchestration.base_skill",
        "Orchestration.executor", "Orchestration.workflow_runtime",
        "Orchestration.workflow_engine", "Agents.planner",
        "Orchestration.task", "Orchestration.workflow", "Services",
        "Repository", "Providers", "Database", "Agents", "Core.composition_root",
    }
    check(forbidden_modules.isdisjoint(imported_names), f"V45: no forbidden module imported (overlap {forbidden_modules & imported_names})")
    classes = {n.name for n in ast.walk(module_tree) if isinstance(n, ast.ClassDef)}
    check(classes == {"ToolContextError", "ToolContext"}, f"V46: module still defines exactly these two classes; got {classes}")
def main() -> int:
    for scenario in [
        scenario_task_none_accepted,
        scenario_other_task_values_still_accepted,
        scenario_parameters_validation_unchanged,
        scenario_metadata_validation_unchanged,
        scenario_frozen_mappings,
        scenario_task_field_frozen,
        scenario_equality_unchanged,
        scenario_hashing_unchanged,
        scenario_public_api_unchanged,
        scenario_ast_verification,
        scenario_module_imports_and_namespace,
    ]:
        print(f"\n[{scenario.__name__}]")
        scenario()
    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"PHASE 8 SPRINT 98 TOOLCONTEXT-OPTIONAL-TASK RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {total})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1
if __name__ == "__main__":
    sys.exit(main())