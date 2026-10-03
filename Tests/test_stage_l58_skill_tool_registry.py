"""
Phase 5 Sprint 58 proof suite -- ``SkillToolRegistry`` (Skill -> Tool
name declaration catalog).

Scope: dedicated regression suite for the Sprint 58 addition only --
``Orchestration.skill_tool_registry.SkillToolRegistry``, a pure
in-memory catalog mapping a skill name (``str``) to a tuple of tool
names (``Tuple[str, ...]``), plus its own
``SkillToolRegistryError`` exception type. This is metadata
declaration only: no execution, no resolution, no instantiation of
skills or tools, no existence validation, no manager/executor/resolver
built on top of it, no singleton, no global registry instance, and no
wiring into ``BaseSkill``, ``BaseTool``, ``SkillRegistry``,
``ToolRegistry``, ``SkillResolver``, ``ToolResolver``, ``Planner``,
``Executor``, ``WorkflowRuntime``/``Engine``/``ExecutionCoordinator``,
``EventBus``, ``Memory``, ``Reflection``, or ``LearningLoop``.

``SkillToolRegistry`` never imports, constructs, or references any of
those (proven both by module-namespace inspection and by AST-level
import inspection of the module's own source file).
``Orchestration.skill_tool_registry`` imports only
``Core.exceptions.AgentError`` and the stdlib ``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites (mirroring
``Tests.test_stage_l56_tool_registry`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    T1  -- constructor: SkillToolRegistry() constructs successfully
           with no arguments, starting with an empty mapping.
    T2  -- register success: register(skill_name, tool_names)
           succeeds; has(skill_name) becomes True and get(skill_name)
           returns the exact tuple registered.
    T3  -- duplicate skill rejection: registering the same
           skill_name twice raises SkillToolRegistryError; the
           original mapping is left untouched (no overwrite).
    T4  -- invalid skill_name: register() rejects None, "", "   ",
           and non-str skill_name values.
    T5  -- invalid tool_names (not a tuple): register() rejects a
           list, str, None, dict, or set passed as tool_names.
    T6  -- invalid tool_names entries: register() rejects a
           tool_names tuple containing a non-str element or an
           empty-string element.
    T7  -- duplicate tool names rejected: register() rejects a
           tool_names tuple containing the same tool name twice.
    T8  -- tuple identity: the exact tuple object passed as
           tool_names is stored and returned by get() (never copied,
           reordered, or transformed).
    T9  -- insertion order: list() preserves the order skill names
           were first registered, including after an
           unregister/re-register cycle.
    T10 -- snapshot independence: list() returns a fresh, independent
           tuple -- mutating the registry after calling list() never
           changes the already-returned tuple; item assignment on the
           returned tuple raises TypeError.
    T11 -- has: has(skill_name) returns True/False correctly and
           never raises, before and after register/unregister.
    T12 -- get: get(skill_name) returns the exact registered tuple;
           get() on a missing skill_name raises
           SkillToolRegistryError.
    T13 -- unregister: unregister(skill_name) removes a registered
           mapping -- has(skill_name) becomes False and it disappears
           from list(); unregister() on a missing skill_name raises
           SkillToolRegistryError.
    T14 -- error hierarchy: SkillToolRegistryError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    T15 -- public API exactness: register/unregister/get/has/list are
           the *only* five public (non-dunder) methods exposed by
           SkillToolRegistry.
    T16 -- forbidden methods absent: no run/execute/invoke/dispatch/
           resolve/call method (or any other execution-shaped name)
           exists on SkillToolRegistry.
    T17 -- forbidden imports absent / AST verification:
           Orchestration/skill_tool_registry.py's own source file
           imports only Core.exceptions and typing (AST-level import
           inspection) -- no BaseSkill/BaseTool/SkillRegistry/
           ToolRegistry/SkillResolver/ToolResolver/Planner/Executor/
           Workflow*/EventBus/Memory/Reflection/LearningLoop import
           anywhere in the file.
    T18 -- namespace verification: Orchestration.skill_tool_registry's
           module namespace contains no BaseSkill/BaseTool/
           SkillRegistry/ToolRegistry/SkillResolver/ToolResolver/
           Planner/Executor/WorkflowRuntime/WorkflowEngine/
           WorkflowExecutionCoordinator/EventBus/Memory/Reflection/
           LearningLoop symbol.
    T19 -- multiple registry independence: two SkillToolRegistry
           instances never share state -- registering into one never
           affects the other.
    T20 -- no singleton: two SkillToolRegistry() calls produce two
           distinct instances with independent internal dictionaries.
    T21 -- opaque string storage only: skill_name and every
           tool_names element are stored purely as strings -- no
           existence check, resolution, or instantiation is performed
           against any other registry/class (there being none
           imported at all).
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
from Orchestration.skill_tool_registry import (
    SkillToolRegistry,
    SkillToolRegistryError,
)

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
# T1 -- constructor
# ---------------------------------------------------------------------------
def scenario_constructor() -> None:
    registry = SkillToolRegistry()
    check(isinstance(registry, SkillToolRegistry), "T1: SkillToolRegistry() constructs successfully")
    check(registry.list() == (), "T1: a fresh SkillToolRegistry starts with list() == ()")
    check(registry.has("anything") is False, "T1: has(name) is False on a fresh registry")


# ---------------------------------------------------------------------------
# T2 -- register success
# ---------------------------------------------------------------------------
def scenario_register_success() -> None:
    registry = SkillToolRegistry()
    registry.register(
        "market_analysis_skill",
        ("yahoo_finance_tool", "polygon_tool", "sec_edgar_tool"),
    )
    check(
        registry.has("market_analysis_skill") is True,
        "T2: has() is True after register",
    )
    check(
        registry.get("market_analysis_skill")
        == ("yahoo_finance_tool", "polygon_tool", "sec_edgar_tool"),
        "T2: get() returns the exact registered tuple",
    )


# ---------------------------------------------------------------------------
# T3 -- duplicate skill rejection
# ---------------------------------------------------------------------------
def scenario_duplicate_skill_rejected() -> None:
    registry = SkillToolRegistry()
    registry.register("x", ("tool_a",))

    raised = False
    try:
        registry.register("x", ("tool_b",))
    except SkillToolRegistryError:
        raised = True
    check(raised, "T3: registering a duplicate skill_name raises SkillToolRegistryError")
    check(
        registry.get("x") == ("tool_a",),
        "T3: the original mapping is left untouched after a rejected duplicate registration (no overwrite)",
    )


# ---------------------------------------------------------------------------
# T4 -- invalid skill_name
# ---------------------------------------------------------------------------
def scenario_invalid_skill_name_rejected() -> None:
    registry = SkillToolRegistry()
    for value in (None, "", "   ", "\t", 123, ["a"], {"k": "v"}, object()):
        raised = False
        try:
            registry.register(value, ("tool_a",))  # type: ignore[arg-type]
        except SkillToolRegistryError:
            raised = True
        check(
            raised,
            f"T4: register(skill_name={value!r}, ...) raises SkillToolRegistryError",
        )


# ---------------------------------------------------------------------------
# T5 -- invalid tool_names (not a tuple)
# ---------------------------------------------------------------------------
def scenario_invalid_tool_names_type_rejected() -> None:
    registry = SkillToolRegistry()
    for value in (["a", "b"], "ab", None, {"a": 1}, {"a", "b"}, 123):
        raised = False
        try:
            registry.register("x", value)  # type: ignore[arg-type]
        except SkillToolRegistryError:
            raised = True
        check(
            raised,
            f"T5: register(skill_name='x', tool_names={value!r}) (not a tuple) raises SkillToolRegistryError",
        )
        # Ensure the rejected attempt did not partially register.
        check(
            registry.has("x") is False,
            f"T5: a rejected register() with tool_names={value!r} leaves no partial registration",
        )


# ---------------------------------------------------------------------------
# T6 -- invalid tool_names entries
# ---------------------------------------------------------------------------
def scenario_invalid_tool_names_entries_rejected() -> None:
    registry = SkillToolRegistry()
    for bad_tools in (("a", 1), (None,), (1, 2, 3), ("a", ["b"]), ("",), ("a", "")):
        raised = False
        try:
            registry.register("x", bad_tools)  # type: ignore[arg-type]
        except SkillToolRegistryError:
            raised = True
        check(
            raised,
            f"T6: register(skill_name='x', tool_names={bad_tools!r}) raises SkillToolRegistryError",
        )
    check(registry.has("x") is False, "T6: no partial registration occurred from any rejected attempt")


# ---------------------------------------------------------------------------
# T7 -- duplicate tool names rejected
# ---------------------------------------------------------------------------
def scenario_duplicate_tool_names_rejected() -> None:
    registry = SkillToolRegistry()
    raised = False
    try:
        registry.register("x", ("tool_a", "tool_b", "tool_a"))
    except SkillToolRegistryError:
        raised = True
    check(
        raised,
        "T7: register() rejects a tool_names tuple containing duplicate entries",
    )
    check(registry.has("x") is False, "T7: no partial registration occurred from a duplicate-tool rejection")


# ---------------------------------------------------------------------------
# T8 -- tuple identity
# ---------------------------------------------------------------------------
def scenario_tuple_identity_preserved() -> None:
    registry = SkillToolRegistry()
    original_tools = ("tool_a", "tool_b", "tool_c")
    registry.register("x", original_tools)
    check(
        registry.get("x") is original_tools,
        "T8: the exact tuple object passed to register() is stored and returned by get() (identity preserved)",
    )


# ---------------------------------------------------------------------------
# T9 -- insertion order
# ---------------------------------------------------------------------------
def scenario_insertion_order() -> None:
    registry = SkillToolRegistry()
    registry.register("gamma", ("t1",))
    registry.register("alpha", ("t2",))
    registry.register("beta", ("t3",))
    check(
        registry.list() == ("gamma", "alpha", "beta"),
        "T9: list() preserves insertion order",
    )

    registry.unregister("alpha")
    registry.register("alpha", ("t2-new",))
    check(
        registry.list() == ("gamma", "beta", "alpha"),
        "T9: re-registering after unregister appends to the end of insertion order",
    )


# ---------------------------------------------------------------------------
# T10 -- snapshot independence
# ---------------------------------------------------------------------------
def scenario_snapshot_independence() -> None:
    registry = SkillToolRegistry()
    registry.register("x", ("t1",))
    snapshot = registry.list()

    raised = False
    try:
        snapshot[0] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "T10: list() returns a real tuple -- item assignment raises TypeError")

    registry.register("y", ("t2",))
    check(
        snapshot == ("x",),
        "T10: mutating the registry after calling list() never changes the already-returned tuple",
    )


# ---------------------------------------------------------------------------
# T11 -- has
# ---------------------------------------------------------------------------
def scenario_has() -> None:
    registry = SkillToolRegistry()
    check(registry.has("x") is False, "T11: has() returns False before registration")
    registry.register("x", ("t1",))
    check(registry.has("x") is True, "T11: has() returns True after registration")
    registry.unregister("x")
    check(registry.has("x") is False, "T11: has() returns False after unregistration")

    raised = False
    try:
        registry.has("does_not_exist_either")
    except SkillToolRegistryError:
        raised = True
    check(raised is False, "T11: has() never raises, even for a name never registered")


# ---------------------------------------------------------------------------
# T12 -- get
# ---------------------------------------------------------------------------
def scenario_get() -> None:
    registry = SkillToolRegistry()
    registry.register("x", ("t1", "t2"))
    check(registry.get("x") == ("t1", "t2"), "T12: get() returns the exact registered tuple")

    raised = False
    try:
        registry.get("does_not_exist")
    except SkillToolRegistryError:
        raised = True
    check(raised, "T12: get() on a missing skill_name raises SkillToolRegistryError")


# ---------------------------------------------------------------------------
# T13 -- unregister
# ---------------------------------------------------------------------------
def scenario_unregister() -> None:
    registry = SkillToolRegistry()
    registry.register("x", ("t1",))
    registry.unregister("x")
    check(registry.has("x") is False, "T13: has() is False after unregister")
    check("x" not in registry.list(), "T13: skill_name disappears from list() after unregister")

    raised = False
    try:
        registry.unregister("x")
    except SkillToolRegistryError:
        raised = True
    check(raised, "T13: unregister() on an already-removed skill_name raises SkillToolRegistryError")

    raised_missing = False
    try:
        registry.unregister("never_registered")
    except SkillToolRegistryError:
        raised_missing = True
    check(raised_missing, "T13: unregister() on a name never registered raises SkillToolRegistryError")


# ---------------------------------------------------------------------------
# T14 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(SkillToolRegistryError, AgentError),
        "T14: SkillToolRegistryError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(AgentError, Exception),
        "T14: Core.exceptions.AgentError subclasses Exception",
    )


# ---------------------------------------------------------------------------
# T15 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in vars(SkillToolRegistry)
        if not name.startswith("_") and callable(getattr(SkillToolRegistry, name))
    }
    check(
        public_methods == {"register", "unregister", "get", "has", "list"},
        f"T15: SkillToolRegistry exposes exactly {{'register', 'unregister', 'get', 'has', 'list'}}; "
        f"got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# T16 -- forbidden methods absent
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
            not hasattr(SkillToolRegistry, name),
            f"T16: SkillToolRegistry has no '{name}' method",
        )


# ---------------------------------------------------------------------------
# T17 -- AST import verification
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
    import Orchestration.skill_tool_registry as skill_tool_registry_module

    source = Path(skill_tool_registry_module.__file__).read_text(encoding="utf-8")
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"typing", "Core", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}
    check(
        unexpected_roots == set(),
        f"T17: Orchestration/skill_tool_registry.py's imports (AST-verified) are limited to "
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
        "T17: the only 'Core' import is 'from Core.exceptions import AgentError'",
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
        "BaseSkill",
        "BaseTool",
        "SkillRegistry",
        "ToolRegistry",
        "SkillResolver",
        "ToolResolver",
        "Planner",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "EventBus",
        "Memory",
        "Reflection",
        "LearningLoop",
    ]
    for symbol in forbidden_symbols:
        check(
            symbol not in imported_names,
            f"T17: Orchestration/skill_tool_registry.py's AST-parsed import names do not include '{symbol}'",
        )


# ---------------------------------------------------------------------------
# T18 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_namespace_verification() -> None:
    import Orchestration.skill_tool_registry as skill_tool_registry_module

    forbidden_symbols = [
        "BaseSkill",
        "BaseTool",
        "SkillRegistry",
        "ToolRegistry",
        "SkillResolver",
        "ToolResolver",
        "Planner",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "EventBus",
        "Memory",
        "Reflection",
        "LearningLoop",
    ]
    for symbol in forbidden_symbols:
        check(
            not hasattr(skill_tool_registry_module, symbol),
            f"T18: Orchestration.skill_tool_registry's module namespace does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# T19 -- multiple registry independence
# ---------------------------------------------------------------------------
def scenario_multiple_registry_independence() -> None:
    registry_a = SkillToolRegistry()
    registry_b = SkillToolRegistry()

    registry_a.register("x", ("t1",))
    check(
        registry_b.has("x") is False,
        "T19: registering into one SkillToolRegistry does not affect another instance",
    )
    check(
        registry_b.list() == (),
        "T19: a second SkillToolRegistry instance remains empty and independent",
    )


# ---------------------------------------------------------------------------
# T20 -- no singleton
# ---------------------------------------------------------------------------
def scenario_no_singleton() -> None:
    registry_1 = SkillToolRegistry()
    registry_2 = SkillToolRegistry()
    check(
        registry_1 is not registry_2,
        "T20: two SkillToolRegistry() calls produce two distinct instances",
    )
    check(
        registry_1._mapping is not registry_2._mapping,
        "T20: two SkillToolRegistry instances hold independent internal dictionaries",
    )


# ---------------------------------------------------------------------------
# T21 -- opaque string storage only
# ---------------------------------------------------------------------------
def scenario_opaque_string_storage_only() -> None:
    registry = SkillToolRegistry()
    # Names for skills/tools that do not exist anywhere else -- no
    # registry, resolver, or class is imported/consulted to validate
    # them, and none is used at all.
    registry.register(
        "a_totally_made_up_skill_name",
        ("a_totally_made_up_tool_name", "another_fictitious_tool"),
    )
    check(
        registry.get("a_totally_made_up_skill_name")
        == ("a_totally_made_up_tool_name", "another_fictitious_tool"),
        "T21: SkillToolRegistry stores and returns plain opaque strings with no existence validation",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor,
        scenario_register_success,
        scenario_duplicate_skill_rejected,
        scenario_invalid_skill_name_rejected,
        scenario_invalid_tool_names_type_rejected,
        scenario_invalid_tool_names_entries_rejected,
        scenario_duplicate_tool_names_rejected,
        scenario_tuple_identity_preserved,
        scenario_insertion_order,
        scenario_snapshot_independence,
        scenario_has,
        scenario_get,
        scenario_unregister,
        scenario_error_hierarchy,
        scenario_public_api_exactness,
        scenario_forbidden_methods_absent,
        scenario_ast_import_verification,
        scenario_namespace_verification,
        scenario_multiple_registry_independence,
        scenario_no_singleton,
        scenario_opaque_string_storage_only,
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
    print(f"PHASE 5 SPRINT 58 SKILL TOOL REGISTRY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())