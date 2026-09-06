"""
Phase 5 Sprint 65 proof suite -- ``CapabilitySkillRegistry``
(Capability -> Skill name declaration catalog).

Scope: dedicated regression suite for the Sprint 65 addition only --
``Orchestration.capability_skill_registry.CapabilitySkillRegistry``, a
pure in-memory catalog mapping a capability name (``str``) to a tuple
of skill names (``Tuple[str, ...]``), plus its own
``CapabilitySkillRegistryError`` exception type. This is metadata
declaration only: no execution, no resolution, no instantiation of
capabilities or skills, no existence validation, no
manager/executor/resolver/planner/runtime built on top of it, no
singleton, no global registry instance, and no wiring into
``Capability``, ``CapabilityRegistry``, ``CapabilityManager``,
``SkillRegistry``, ``SkillResolver``, ``SkillDescriptor``,
``BaseSkill``, ``ToolRegistry``, ``ToolResolver``, ``ToolManager``,
``Planner``, ``Workflow*``, ``Runtime*``, ``Executor``, ``Memory``,
``Reflection``, ``LearningLoop``, ``EventBus``, ``Repository``,
``Services``, ``Providers``, ``Database``, or
``Core.composition_root``.

``CapabilitySkillRegistry`` never imports, constructs, or references
any of those (proven both by module-namespace inspection and by
AST-level import inspection of the module's own source file).
``Orchestration.capability_skill_registry`` imports only
``Core.exceptions.AgentError`` and the stdlib ``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x proof suites (mirroring
``Tests.test_stage_l58_skill_tool_registry`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- constructor: CapabilitySkillRegistry() constructs
           successfully with no arguments, starting with an empty
           mapping.
    S2  -- register success: register(capability_name, skill_names)
           succeeds; has(capability_name) becomes True and
           get(capability_name) returns the exact tuple registered.
    S3  -- duplicate capability rejection: registering the same
           capability_name twice raises CapabilitySkillRegistryError;
           the original mapping is left untouched (no overwrite).
    S4  -- invalid capability_name: register() rejects None, "",
           "   ", and non-str capability_name values.
    S5  -- invalid skill_names (not a tuple): register() rejects a
           list, str, None, dict, or set passed as skill_names.
    S6  -- invalid skill_names entries: register() rejects a
           skill_names tuple containing a non-str element or an
           empty-string element.
    S7  -- duplicate skill names rejected: register() rejects a
           skill_names tuple containing the same skill name twice.
    S8  -- tuple identity: the exact tuple object passed as
           skill_names is stored and returned by get() (never
           copied, reordered, or transformed).
    S9  -- insertion order: list() preserves the order capability
           names were first registered, including after an
           unregister/re-register cycle.
    S10 -- snapshot independence: list() returns a fresh, independent
           tuple -- mutating the registry after calling list() never
           changes the already-returned tuple; item assignment on the
           returned tuple raises TypeError.
    S11 -- has: has(capability_name) returns True/False correctly and
           never raises, before and after register/unregister.
    S12 -- get: get(capability_name) returns the exact registered
           tuple; get() on a missing capability_name raises
           CapabilitySkillRegistryError.
    S13 -- unregister: unregister(capability_name) removes a
           registered mapping -- has(capability_name) becomes False
           and it disappears from list(); unregister() on a missing
           capability_name raises CapabilitySkillRegistryError.
    S14 -- error hierarchy: CapabilitySkillRegistryError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    S15 -- public API exactness: register/unregister/get/has/list are
           the *only* five public (non-dunder) methods exposed by
           CapabilitySkillRegistry.
    S16 -- forbidden methods absent: no run/execute/invoke/dispatch/
           resolve/call/plan/schedule method (or any other
           execution-shaped name) exists on CapabilitySkillRegistry.
    S17 -- forbidden imports absent / AST verification:
           Orchestration/capability_skill_registry.py's own source
           file imports only Core.exceptions and typing (AST-level
           import inspection) -- no Capability/CapabilityRegistry/
           CapabilityManager/SkillRegistry/SkillResolver/
           SkillDescriptor/BaseSkill/ToolRegistry/ToolResolver/
           ToolManager/Planner/Workflow*/Runtime*/Executor/Memory/
           Reflection/LearningLoop/EventBus/Repository/Services/
           Providers/Database/CompositionRoot import anywhere in the
           file.
    S18 -- namespace verification:
           Orchestration.capability_skill_registry's module namespace
           contains no Capability/CapabilityRegistry/
           CapabilityManager/SkillRegistry/SkillResolver/
           SkillDescriptor/BaseSkill/ToolRegistry/ToolResolver/
           ToolManager/Planner/Workflow*/Runtime*/Executor/Memory/
           Reflection/LearningLoop/EventBus/Repository/Services/
           Providers/Database/CompositionRoot symbol.
    S19 -- multiple registry independence: two
           CapabilitySkillRegistry instances never share state --
           registering into one never affects the other.
    S20 -- no singleton: two CapabilitySkillRegistry() calls produce
           two distinct instances with independent internal
           dictionaries.
    S21 -- opaque string storage only: capability_name and every
           skill_names element are stored purely as strings -- no
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
from Orchestration.capability_skill_registry import (
    CapabilitySkillRegistry,
    CapabilitySkillRegistryError,
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
# S1 -- constructor
# ---------------------------------------------------------------------------
def scenario_constructor() -> None:
    registry = CapabilitySkillRegistry()
    check(isinstance(registry, CapabilitySkillRegistry), "S1: CapabilitySkillRegistry() constructs successfully")
    check(registry.list() == (), "S1: a fresh CapabilitySkillRegistry starts with list() == ()")
    check(registry.has("anything") is False, "S1: has(name) is False on a fresh registry")


# ---------------------------------------------------------------------------
# S2 -- register success
# ---------------------------------------------------------------------------
def scenario_register_success() -> None:
    registry = CapabilitySkillRegistry()
    registry.register(
        "market_analysis_capability",
        ("price_lookup_skill", "news_summary_skill", "risk_scoring_skill"),
    )
    check(
        registry.has("market_analysis_capability") is True,
        "S2: has() is True after register",
    )
    check(
        registry.get("market_analysis_capability")
        == ("price_lookup_skill", "news_summary_skill", "risk_scoring_skill"),
        "S2: get() returns the exact registered tuple",
    )


# ---------------------------------------------------------------------------
# S3 -- duplicate capability rejection
# ---------------------------------------------------------------------------
def scenario_duplicate_capability_rejected() -> None:
    registry = CapabilitySkillRegistry()
    registry.register("x", ("skill_a",))

    raised = False
    try:
        registry.register("x", ("skill_b",))
    except CapabilitySkillRegistryError:
        raised = True
    check(raised, "S3: registering a duplicate capability_name raises CapabilitySkillRegistryError")
    check(
        registry.get("x") == ("skill_a",),
        "S3: the original mapping is left untouched after a rejected duplicate registration (no overwrite)",
    )


# ---------------------------------------------------------------------------
# S4 -- invalid capability_name
# ---------------------------------------------------------------------------
def scenario_invalid_capability_name_rejected() -> None:
    registry = CapabilitySkillRegistry()
    for value in (None, "", "   ", "\t", 123, ["a"], {"k": "v"}, object()):
        raised = False
        try:
            registry.register(value, ("skill_a",))  # type: ignore[arg-type]
        except CapabilitySkillRegistryError:
            raised = True
        check(
            raised,
            f"S4: register(capability_name={value!r}, ...) raises CapabilitySkillRegistryError",
        )


# ---------------------------------------------------------------------------
# S5 -- invalid skill_names (not a tuple)
# ---------------------------------------------------------------------------
def scenario_invalid_skill_names_type_rejected() -> None:
    registry = CapabilitySkillRegistry()
    for value in (["a", "b"], "ab", None, {"a": 1}, {"a", "b"}, 123):
        raised = False
        try:
            registry.register("x", value)  # type: ignore[arg-type]
        except CapabilitySkillRegistryError:
            raised = True
        check(
            raised,
            f"S5: register(capability_name='x', skill_names={value!r}) (not a tuple) raises CapabilitySkillRegistryError",
        )
        # Ensure the rejected attempt did not partially register.
        check(
            registry.has("x") is False,
            f"S5: a rejected register() with skill_names={value!r} leaves no partial registration",
        )


# ---------------------------------------------------------------------------
# S6 -- invalid skill_names entries
# ---------------------------------------------------------------------------
def scenario_invalid_skill_names_entries_rejected() -> None:
    registry = CapabilitySkillRegistry()
    for bad_skills in (("a", 1), (None,), (1, 2, 3), ("a", ["b"]), ("",), ("a", "")):
        raised = False
        try:
            registry.register("x", bad_skills)  # type: ignore[arg-type]
        except CapabilitySkillRegistryError:
            raised = True
        check(
            raised,
            f"S6: register(capability_name='x', skill_names={bad_skills!r}) raises CapabilitySkillRegistryError",
        )
    check(registry.has("x") is False, "S6: no partial registration occurred from any rejected attempt")


# ---------------------------------------------------------------------------
# S7 -- duplicate skill names rejected
# ---------------------------------------------------------------------------
def scenario_duplicate_skill_names_rejected() -> None:
    registry = CapabilitySkillRegistry()
    raised = False
    try:
        registry.register("x", ("skill_a", "skill_b", "skill_a"))
    except CapabilitySkillRegistryError:
        raised = True
    check(
        raised,
        "S7: register() rejects a skill_names tuple containing duplicate entries",
    )
    check(registry.has("x") is False, "S7: no partial registration occurred from a duplicate-skill rejection")


# ---------------------------------------------------------------------------
# S8 -- tuple identity
# ---------------------------------------------------------------------------
def scenario_tuple_identity_preserved() -> None:
    registry = CapabilitySkillRegistry()
    original_skills = ("skill_a", "skill_b", "skill_c")
    registry.register("x", original_skills)
    check(
        registry.get("x") is original_skills,
        "S8: the exact tuple object passed to register() is stored and returned by get() (identity preserved)",
    )


# ---------------------------------------------------------------------------
# S9 -- insertion order
# ---------------------------------------------------------------------------
def scenario_insertion_order() -> None:
    registry = CapabilitySkillRegistry()
    registry.register("gamma", ("s1",))
    registry.register("alpha", ("s2",))
    registry.register("beta", ("s3",))
    check(
        registry.list() == ("gamma", "alpha", "beta"),
        "S9: list() preserves insertion order",
    )

    registry.unregister("alpha")
    registry.register("alpha", ("s2-new",))
    check(
        registry.list() == ("gamma", "beta", "alpha"),
        "S9: re-registering after unregister appends to the end of insertion order",
    )


# ---------------------------------------------------------------------------
# S10 -- snapshot independence
# ---------------------------------------------------------------------------
def scenario_snapshot_independence() -> None:
    registry = CapabilitySkillRegistry()
    registry.register("x", ("s1",))
    snapshot = registry.list()

    raised = False
    try:
        snapshot[0] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "S10: list() returns a real tuple -- item assignment raises TypeError")

    registry.register("y", ("s2",))
    check(
        snapshot == ("x",),
        "S10: mutating the registry after calling list() never changes the already-returned tuple",
    )


# ---------------------------------------------------------------------------
# S11 -- has
# ---------------------------------------------------------------------------
def scenario_has() -> None:
    registry = CapabilitySkillRegistry()
    check(registry.has("x") is False, "S11: has() returns False before registration")
    registry.register("x", ("s1",))
    check(registry.has("x") is True, "S11: has() returns True after registration")
    registry.unregister("x")
    check(registry.has("x") is False, "S11: has() returns False after unregistration")

    raised = False
    try:
        registry.has("does_not_exist_either")
    except CapabilitySkillRegistryError:
        raised = True
    check(raised is False, "S11: has() never raises, even for a name never registered")


# ---------------------------------------------------------------------------
# S12 -- get
# ---------------------------------------------------------------------------
def scenario_get() -> None:
    registry = CapabilitySkillRegistry()
    registry.register("x", ("s1", "s2"))
    check(registry.get("x") == ("s1", "s2"), "S12: get() returns the exact registered tuple")

    raised = False
    try:
        registry.get("does_not_exist")
    except CapabilitySkillRegistryError:
        raised = True
    check(raised, "S12: get() on a missing capability_name raises CapabilitySkillRegistryError")


# ---------------------------------------------------------------------------
# S13 -- unregister
# ---------------------------------------------------------------------------
def scenario_unregister() -> None:
    registry = CapabilitySkillRegistry()
    registry.register("x", ("s1",))
    registry.unregister("x")
    check(registry.has("x") is False, "S13: has() is False after unregister")
    check("x" not in registry.list(), "S13: capability_name disappears from list() after unregister")

    raised = False
    try:
        registry.unregister("x")
    except CapabilitySkillRegistryError:
        raised = True
    check(raised, "S13: unregister() on an already-removed capability_name raises CapabilitySkillRegistryError")

    raised_missing = False
    try:
        registry.unregister("never_registered")
    except CapabilitySkillRegistryError:
        raised_missing = True
    check(raised_missing, "S13: unregister() on a name never registered raises CapabilitySkillRegistryError")


# ---------------------------------------------------------------------------
# S14 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(CapabilitySkillRegistryError, AgentError),
        "S14: CapabilitySkillRegistryError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(AgentError, Exception),
        "S14: Core.exceptions.AgentError subclasses Exception",
    )


# ---------------------------------------------------------------------------
# S15 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in vars(CapabilitySkillRegistry)
        if not name.startswith("_") and callable(getattr(CapabilitySkillRegistry, name))
    }
    check(
        public_methods == {"register", "unregister", "get", "has", "list"},
        f"S15: CapabilitySkillRegistry exposes exactly {{'register', 'unregister', 'get', 'has', 'list'}}; "
        f"got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# S16 -- forbidden methods absent
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
        "route",
        "match",
    ]
    for name in forbidden:
        check(
            not hasattr(CapabilitySkillRegistry, name),
            f"S16: CapabilitySkillRegistry has no '{name}' method",
        )


# ---------------------------------------------------------------------------
# S17 -- AST import verification
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
    import Orchestration.capability_skill_registry as capability_skill_registry_module

    source = Path(capability_skill_registry_module.__file__).read_text(encoding="utf-8")
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"typing", "Core", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}
    check(
        unexpected_roots == set(),
        f"S17: Orchestration/capability_skill_registry.py's imports (AST-verified) are limited to "
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
        "S17: the only 'Core' import is 'from Core.exceptions import AgentError'",
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
        "Capability",
        "CapabilityRegistry",
        "CapabilityManager",
        "SkillRegistry",
        "SkillResolver",
        "SkillDescriptor",
        "BaseSkill",
        "ToolRegistry",
        "ToolResolver",
        "ToolManager",
        "Planner",
        "Workflow",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "WorkflowManager",
        "Runtime",
        "Executor",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "Repository",
        "Services",
        "Providers",
        "Database",
        "CompositionRoot",
    ]
    for symbol in forbidden_symbols:
        check(
            symbol not in imported_names,
            f"S17: Orchestration/capability_skill_registry.py's AST-parsed import names do not include '{symbol}'",
        )


# ---------------------------------------------------------------------------
# S18 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_namespace_verification() -> None:
    import Orchestration.capability_skill_registry as capability_skill_registry_module

    forbidden_symbols = [
        "Capability",
        "CapabilityRegistry",
        "CapabilityManager",
        "SkillRegistry",
        "SkillResolver",
        "SkillDescriptor",
        "BaseSkill",
        "ToolRegistry",
        "ToolResolver",
        "ToolManager",
        "Planner",
        "Workflow",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "WorkflowManager",
        "Runtime",
        "Executor",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "Repository",
        "Services",
        "Providers",
        "Database",
        "CompositionRoot",
    ]
    for symbol in forbidden_symbols:
        check(
            not hasattr(capability_skill_registry_module, symbol),
            f"S18: Orchestration.capability_skill_registry's module namespace does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# S19 -- multiple registry independence
# ---------------------------------------------------------------------------
def scenario_multiple_registry_independence() -> None:
    registry_a = CapabilitySkillRegistry()
    registry_b = CapabilitySkillRegistry()

    registry_a.register("x", ("s1",))
    check(
        registry_b.has("x") is False,
        "S19: registering into one CapabilitySkillRegistry does not affect another instance",
    )
    check(
        registry_b.list() == (),
        "S19: a second CapabilitySkillRegistry instance remains empty and independent",
    )


# ---------------------------------------------------------------------------
# S20 -- no singleton
# ---------------------------------------------------------------------------
def scenario_no_singleton() -> None:
    registry_1 = CapabilitySkillRegistry()
    registry_2 = CapabilitySkillRegistry()
    check(
        registry_1 is not registry_2,
        "S20: two CapabilitySkillRegistry() calls produce two distinct instances",
    )
    check(
        registry_1._mapping is not registry_2._mapping,
        "S20: two CapabilitySkillRegistry instances hold independent internal dictionaries",
    )


# ---------------------------------------------------------------------------
# S21 -- opaque string storage only
# ---------------------------------------------------------------------------
def scenario_opaque_string_storage_only() -> None:
    registry = CapabilitySkillRegistry()
    # Names for capabilities/skills that do not exist anywhere else --
    # no registry, resolver, or class is imported/consulted to
    # validate them, and none is used at all.
    registry.register(
        "a_totally_made_up_capability_name",
        ("a_totally_made_up_skill_name", "another_fictitious_skill"),
    )
    check(
        registry.get("a_totally_made_up_capability_name")
        == ("a_totally_made_up_skill_name", "another_fictitious_skill"),
        "S21: CapabilitySkillRegistry stores and returns plain opaque strings with no existence validation",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor,
        scenario_register_success,
        scenario_duplicate_capability_rejected,
        scenario_invalid_capability_name_rejected,
        scenario_invalid_skill_names_type_rejected,
        scenario_invalid_skill_names_entries_rejected,
        scenario_duplicate_skill_names_rejected,
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
    print(f"PHASE 5 SPRINT 65 CAPABILITY SKILL REGISTRY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())