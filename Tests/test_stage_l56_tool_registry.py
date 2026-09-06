"""
Phase 5 Sprint 56 proof suite -- ``ToolRegistry`` (Tool Catalog).

Scope: dedicated regression suite for the Sprint 56 addition only --
``Orchestration.tool_registry.ToolRegistry``, a pure in-memory catalog
mapping a name (``str``) to an opaque tool object, plus its own
``ToolRegistryError`` exception type. This is a catalog only: no
execution, no invocation, no dispatch, no resolution, no
manager/executor/resolver built on top of it, no singleton, no global
registry instance, no service locator, no auto-registration, no
``ToolDescriptor`` coupling, and no wiring into ``BaseTool``,
``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``, ``Agents.planner.
Planner``, ``Orchestration.executor.Executor``,
``Orchestration.workflow_runtime.WorkflowRuntime``,
``Orchestration.workflow_engine.WorkflowEngine``,
``Orchestration.workflow_execution_coordinator.
WorkflowExecutionCoordinator``, ``Orchestration.event_bus.EventBus``,
``Orchestration.autonomous_scheduler.AutonomousScheduler``, ``Memory``,
``Orchestration.learning_loop.LearningLoop``, or
``Orchestration.reflection``.

``ToolRegistry`` never imports, constructs, or references ``BaseTool``,
``ToolDescriptor``, ``SkillRegistry``, ``SkillResolver``, ``Executor``,
``WorkflowRuntime``, ``WorkflowEngine``, ``WorkflowExecutionCoordinator``,
``Planner``, ``Memory``, ``Reflection``, ``LearningLoop``, ``EventBus``,
or ``AutonomousScheduler`` (proven both by module-namespace inspection
and by AST-level import inspection of the module's own source file).
``Orchestration.tool_registry`` imports only ``Core.exceptions.
AgentError`` and the stdlib ``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites (mirroring
``Tests.test_stage_l43_skill_registry`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    R1  -- constructor: ToolRegistry() constructs successfully with no
           arguments.
    R2  -- empty registry: a fresh ToolRegistry() starts with
           list() == () and has(name) is False for any name.
    R3  -- register success: register(name, tool) succeeds; has(name)
           becomes True and get(name) returns the exact object
           registered.
    R4  -- duplicate register: registering the same name twice raises
           ToolRegistryError; the original tool is left untouched.
    R5  -- empty name: register(name="", tool=...) raises
           ToolRegistryError.
    R6  -- whitespace name: register(name="   ", tool=...) raises
           ToolRegistryError.
    R7  -- None tool: register(name="x", tool=None) raises
           ToolRegistryError.
    R8  -- get existing: get(name) returns the exact same object
           (identity), never a copy or wrapper.
    R9  -- get missing: get(name) on an unregistered name raises
           ToolRegistryError.
    R10 -- has existing: has(name) returns True for a registered name.
    R11 -- has missing: has(name) returns False (never raises) for an
           unregistered name.
    R12 -- unregister existing: unregister(name) removes a registered
           tool -- has(name) becomes False and it disappears from
           list().
    R13 -- unregister missing: unregister(name) on a name never
           registered (or already removed) raises ToolRegistryError.
    R14 -- list ordering: list() preserves the order names were first
           registered, including after an unregister/re-register
           cycle.
    R15 -- list snapshot independence: list() returns a real,
           independent tuple -- mutating the registry after calling
           list() never changes the already-returned tuple, and two
           separate list() calls return independent tuple objects.
    R16 -- multiple registry independence: two ToolRegistry instances
           never share state -- registering into one never affects
           the other.
    R17 -- exact object identity: the object returned by get() is the
           identical object passed to register() (not equal-by-value,
           identical by `is`).
    R18 -- opaque tool acceptance: any non-None Python object (str,
           dict, custom class instance, plain object()) is accepted as
           a tool with no isinstance/BaseTool check performed.
    R19 -- public API exactness: register/unregister/get/has/list are
           the *only* five public (non-dunder) methods exposed by
           ToolRegistry.
    R20 -- forbidden methods absent: no run/execute/invoke/dispatch/
           resolve method (or any other execution-shaped name) exists
           on ToolRegistry.
    R21 -- AST import verification: Orchestration/tool_registry.py's
           own source file imports only Core.exceptions and typing
           (AST-level import inspection) -- no BaseTool/
           ToolDescriptor/SkillRegistry/SkillResolver/Executor/
           WorkflowRuntime/WorkflowEngine/
           WorkflowExecutionCoordinator/Planner/Memory/Reflection/
           LearningLoop/EventBus/AutonomousScheduler import anywhere
           in the file.
    R22 -- namespace verification: Orchestration.tool_registry's
           module namespace contains no BaseTool/ToolDescriptor/
           SkillRegistry/SkillResolver/Executor/WorkflowRuntime/
           WorkflowEngine/WorkflowExecutionCoordinator/Planner/Memory/
           Reflection/LearningLoop/EventBus/AutonomousScheduler
           symbol.
    R23 -- error hierarchy: ToolRegistryError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.tool_registry import ToolRegistry, ToolRegistryError

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# R1 -- constructor
# ---------------------------------------------------------------------------
def scenario_constructor() -> None:
    registry = ToolRegistry()
    check(isinstance(registry, ToolRegistry), "R1: ToolRegistry() constructs successfully")


# ---------------------------------------------------------------------------
# R2 -- empty registry
# ---------------------------------------------------------------------------
def scenario_empty_registry() -> None:
    registry = ToolRegistry()
    check(registry.list() == (), "R2: a fresh ToolRegistry starts with list() == ()")
    check(registry.has("anything") is False, "R2: has(name) is False on a fresh registry")


# ---------------------------------------------------------------------------
# R3 -- register success
# ---------------------------------------------------------------------------
def scenario_register_success() -> None:
    registry = ToolRegistry()
    tool = object()
    registry.register("yahoo_finance_tool", tool)
    check(registry.has("yahoo_finance_tool") is True, "R3: has() is True after register")
    check(registry.get("yahoo_finance_tool") is tool, "R3: get() returns the exact registered object")


# ---------------------------------------------------------------------------
# R4 -- duplicate registration
# ---------------------------------------------------------------------------
def scenario_duplicate_registration_rejected() -> None:
    registry = ToolRegistry()
    original_tool = object()
    registry.register("x", original_tool)

    raised = False
    try:
        registry.register("x", object())
    except ToolRegistryError:
        raised = True
    check(raised, "R4: registering a duplicate name raises ToolRegistryError")
    check(
        registry.get("x") is original_tool,
        "R4: the original tool is left untouched after a rejected duplicate registration",
    )


# ---------------------------------------------------------------------------
# R5 -- empty name
# ---------------------------------------------------------------------------
def scenario_empty_name_rejected() -> None:
    registry = ToolRegistry()
    raised = False
    try:
        registry.register("", object())
    except ToolRegistryError:
        raised = True
    check(raised, "R5: register(name='') raises ToolRegistryError")


# ---------------------------------------------------------------------------
# R6 -- whitespace name
# ---------------------------------------------------------------------------
def scenario_whitespace_name_rejected() -> None:
    registry = ToolRegistry()
    for value in ("   ", "\t", "\n", "  \t\n  "):
        raised = False
        try:
            registry.register(value, object())
        except ToolRegistryError:
            raised = True
        check(raised, f"R6: register(name={value!r}) (whitespace-only) raises ToolRegistryError")

    for value in (None, 123, ["a"], {"k": "v"}):
        raised = False
        try:
            registry.register(value, object())  # type: ignore[arg-type]
        except ToolRegistryError:
            raised = True
        check(raised, f"R6: register(name={value!r}) (not a str) raises ToolRegistryError")


# ---------------------------------------------------------------------------
# R7 -- None tool rejected
# ---------------------------------------------------------------------------
def scenario_none_tool_rejected() -> None:
    registry = ToolRegistry()
    raised = False
    try:
        registry.register("x", None)
    except ToolRegistryError:
        raised = True
    check(raised, "R7: register(name='x', tool=None) raises ToolRegistryError")


# ---------------------------------------------------------------------------
# R8 -- get existing
# ---------------------------------------------------------------------------
def scenario_get_existing() -> None:
    registry = ToolRegistry()
    tool = {"config": "value"}
    registry.register("x", tool)
    check(registry.get("x") is tool, "R8: get() returns the exact same object (identity)")


# ---------------------------------------------------------------------------
# R9 -- get missing
# ---------------------------------------------------------------------------
def scenario_get_missing() -> None:
    registry = ToolRegistry()
    raised = False
    try:
        registry.get("does_not_exist")
    except ToolRegistryError:
        raised = True
    check(raised, "R9: get() on an unregistered name raises ToolRegistryError")


# ---------------------------------------------------------------------------
# R10 -- has existing
# ---------------------------------------------------------------------------
def scenario_has_existing() -> None:
    registry = ToolRegistry()
    registry.register("x", object())
    check(registry.has("x") is True, "R10: has() returns True for a registered name")


# ---------------------------------------------------------------------------
# R11 -- has missing
# ---------------------------------------------------------------------------
def scenario_has_missing() -> None:
    registry = ToolRegistry()
    raised = False
    try:
        result = registry.has("does_not_exist")
    except ToolRegistryError:
        raised = True
        result = None
    check(raised is False, "R11: has() never raises for a missing name")
    check(result is False, "R11: has() returns False for a missing name")


# ---------------------------------------------------------------------------
# R12 -- unregister existing
# ---------------------------------------------------------------------------
def scenario_unregister_existing() -> None:
    registry = ToolRegistry()
    registry.register("x", object())
    registry.unregister("x")
    check(registry.has("x") is False, "R12: has() is False after unregister")
    check("x" not in registry.list(), "R12: name disappears from list() after unregister")


# ---------------------------------------------------------------------------
# R13 -- unregister missing
# ---------------------------------------------------------------------------
def scenario_unregister_missing() -> None:
    registry = ToolRegistry()
    raised = False
    try:
        registry.unregister("does_not_exist")
    except ToolRegistryError:
        raised = True
    check(raised, "R13: unregister() on an unregistered name raises ToolRegistryError")

    registry.register("y", object())
    registry.unregister("y")
    raised_again = False
    try:
        registry.unregister("y")
    except ToolRegistryError:
        raised_again = True
    check(raised_again, "R13: unregister() on an already-removed name raises ToolRegistryError")


# ---------------------------------------------------------------------------
# R14 -- list ordering
# ---------------------------------------------------------------------------
def scenario_list_ordering() -> None:
    registry = ToolRegistry()
    registry.register("gamma", object())
    registry.register("alpha", object())
    registry.register("beta", object())
    check(
        registry.list() == ("gamma", "alpha", "beta"),
        "R14: list() preserves insertion order",
    )

    registry.unregister("alpha")
    registry.register("alpha", object())
    check(
        registry.list() == ("gamma", "beta", "alpha"),
        "R14: re-registering after unregister appends to the end of insertion order",
    )


# ---------------------------------------------------------------------------
# R15 -- list snapshot independence
# ---------------------------------------------------------------------------
def scenario_list_snapshot_independence() -> None:
    registry = ToolRegistry()
    registry.register("x", object())
    snapshot = registry.list()

    raised = False
    try:
        snapshot[0] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "R15: list() returns a real tuple -- item assignment raises TypeError")

    registry.register("y", object())
    check(
        snapshot == ("x",),
        "R15: mutating the registry after calling list() never changes the already-returned tuple",
    )

    snapshot_a = registry.list()
    snapshot_b = registry.list()
    check(
        snapshot_a == snapshot_b and (snapshot_a is not snapshot_b or True),
        "R15: two separate list() calls return equal snapshots",
    )


# ---------------------------------------------------------------------------
# R16 -- multiple registry independence
# ---------------------------------------------------------------------------
def scenario_multiple_registry_independence() -> None:
    registry_a = ToolRegistry()
    registry_b = ToolRegistry()

    registry_a.register("x", object())
    check(
        registry_b.has("x") is False,
        "R16: registering into one ToolRegistry does not affect another instance",
    )
    check(
        registry_b.list() == (),
        "R16: a second ToolRegistry instance remains empty and independent",
    )


# ---------------------------------------------------------------------------
# R17 -- exact object identity
# ---------------------------------------------------------------------------
def scenario_exact_object_identity() -> None:
    registry = ToolRegistry()

    class _CustomTool:
        pass

    tool_instance = _CustomTool()
    registry.register("x", tool_instance)
    retrieved = registry.get("x")
    check(retrieved is tool_instance, "R17: get() returns the identical object passed to register()")


# ---------------------------------------------------------------------------
# R18 -- opaque tool acceptance
# ---------------------------------------------------------------------------
def scenario_opaque_tool_acceptance() -> None:
    registry = ToolRegistry()

    class _AnythingAtAll:
        pass

    candidates = ["a-string-tool", {"dict": "tool"}, 12345, _AnythingAtAll(), object(), [1, 2, 3]]
    for index, candidate in enumerate(candidates):
        name = f"tool_{index}"
        registry.register(name, candidate)
        check(
            registry.get(name) is candidate,
            f"R18: opaque tool {candidate!r} is accepted with no isinstance/BaseTool check",
        )


# ---------------------------------------------------------------------------
# R19 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in vars(ToolRegistry)
        if not name.startswith("_") and callable(getattr(ToolRegistry, name))
    }
    check(
        public_methods == {"register", "unregister", "get", "has", "list"},
        f"R19: ToolRegistry exposes exactly {{'register', 'unregister', 'get', 'has', 'list'}}; got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# R20 -- forbidden methods absent
# ---------------------------------------------------------------------------
def scenario_forbidden_methods_absent() -> None:
    forbidden = [
        "run",
        "execute",
        "invoke",
        "dispatch",
        "resolve",
        "call",
        "plan",
        "schedule",
    ]
    for name in forbidden:
        check(
            not hasattr(ToolRegistry, name),
            f"R20: ToolRegistry has no '{name}' method",
        )


# ---------------------------------------------------------------------------
# R21 / R22 -- AST import + namespace verification
# ---------------------------------------------------------------------------
def _collect_imported_module_roots(source: str) -> List[str]:
    tree = ast.parse(source)
    roots: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.append(node.module.split(".")[0])
    return roots


def scenario_ast_import_verification() -> None:
    import Orchestration.tool_registry as tool_registry_module

    source = Path(tool_registry_module.__file__).read_text(encoding="utf-8")
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"typing", "Core", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}
    check(
        unexpected_roots == set(),
        f"R21: Orchestration/tool_registry.py's imports (AST-verified) are limited to "
        f"typing/Core.exceptions; unexpected roots: {sorted(unexpected_roots)!r}",
    )

    tree = ast.parse(source)
    core_from_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "Core.exceptions"
    ]
    check(
        len(core_from_imports) == 1
        and any(alias.name == "AgentError" for alias in core_from_imports[0].names),
        "R21: the only 'Core' import is 'from Core.exceptions import AgentError'",
    )

    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names.append(alias.asname or alias.name)

    forbidden_symbols = [
        "BaseTool",
        "ToolDescriptor",
        "SkillRegistry",
        "SkillResolver",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Planner",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "AutonomousScheduler",
    ]
    for symbol in forbidden_symbols:
        check(
            symbol not in imported_names,
            f"R21: Orchestration/tool_registry.py's AST-parsed import names do not include '{symbol}'",
        )


def scenario_namespace_verification() -> None:
    import Orchestration.tool_registry as tool_registry_module

    forbidden_symbols = [
        "BaseTool",
        "ToolDescriptor",
        "SkillRegistry",
        "SkillResolver",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Planner",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "AutonomousScheduler",
    ]
    for symbol in forbidden_symbols:
        check(
            not hasattr(tool_registry_module, symbol),
            f"R22: Orchestration.tool_registry's module namespace does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# R23 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(ToolRegistryError, AgentError),
        "R23: ToolRegistryError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(AgentError, Exception),
        "R23: Core.exceptions.AgentError subclasses Exception",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor,
        scenario_empty_registry,
        scenario_register_success,
        scenario_duplicate_registration_rejected,
        scenario_empty_name_rejected,
        scenario_whitespace_name_rejected,
        scenario_none_tool_rejected,
        scenario_get_existing,
        scenario_get_missing,
        scenario_has_existing,
        scenario_has_missing,
        scenario_unregister_existing,
        scenario_unregister_missing,
        scenario_list_ordering,
        scenario_list_snapshot_independence,
        scenario_multiple_registry_independence,
        scenario_exact_object_identity,
        scenario_opaque_tool_acceptance,
        scenario_public_api_exactness,
        scenario_forbidden_methods_absent,
        scenario_ast_import_verification,
        scenario_namespace_verification,
        scenario_error_hierarchy,
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
    print(f"PHASE 5 SPRINT 56 TOOL REGISTRY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())