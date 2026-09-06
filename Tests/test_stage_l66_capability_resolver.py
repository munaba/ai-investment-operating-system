"""
Phase 5 Sprint 66 proof suite -- ``CapabilityResolver`` (capability
name -> tuple(skill names) resolution).

Scope: dedicated regression suite for the Sprint 66 addition only --
``Orchestration.capability_resolver.CapabilityResolver``, a
single-method class that resolves a plain
``capability_name: str`` to the ``Tuple[str, ...]`` of skill names
registered for it via exact ``CapabilitySkillRegistry`` key match,
plus its own ``CapabilityResolverError`` exception type. This is
resolution only: no execution, no routing engine, no fuzzy/alias/
metadata/tag/description-based/scored/normalized matching, no
``Capability``/``BaseSkill``/``BaseTool`` validation, no Planner
integration, no ``CapabilityManager``/``CapabilityRegistry``/
``SkillRegistry``/``SkillResolver``/``ToolRegistry``/``ToolResolver``,
and no wiring into ``Executor``, ``WorkflowRuntime``,
``WorkflowEngine``, ``WorkflowExecutionCoordinator``, ``Planner``,
``Memory``, ``Reflection``, ``LearningLoop``, ``EventBus``,
``Services``, ``Repository``, ``Providers``, ``Database``, or
``Agents``.
``Orchestration.capability_skill_registry.CapabilitySkillRegistry``
(Sprint 65, exercised in full by
``Tests/test_stage_l65_capability_skill_registry.py``) is unchanged
by this sprint -- this suite does not re-verify its own behavior
beyond confirming Sprint 66 introduces no regression to it.

``CapabilityResolver`` resolves to the declared *metadata* -- a tuple
of skill names -- never to an actual skill object. This is the
missing bridge between ``CapabilityRegistry``/``CapabilityManager``
(which store capability objects) and ``CapabilitySkillRegistry``
(which declares which skill names implement a capability); it does
not import or reference either side of that boundary.

``CapabilityResolver`` never imports, constructs, or references
``Capability``, ``CapabilityRegistry``, ``CapabilityManager``,
``SkillRegistry``, ``SkillResolver``, ``BaseSkill``, ``ToolRegistry``,
``ToolResolver``, ``BaseTool``, ``Executor``, ``Workflow``/
``WorkflowEngine``/``WorkflowRuntime``/
``WorkflowExecutionCoordinator``, ``Planner``, ``Memory``,
``Reflection``, ``LearningLoop``, ``EventBus``, ``Services``,
``Repository``, ``Providers``, ``Database``, or ``Agents`` (proven
both by module-namespace inspection and by AST-level import
inspection of the module's own source file).
``Orchestration.capability_resolver`` imports only
``Core.exceptions.AgentError``,
``Orchestration.capability_skill_registry.CapabilitySkillRegistry``,
and the stdlib ``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x proof suites (mirroring
``Tests.test_stage_l57_tool_resolver`` and
``Tests.test_stage_l44_skill_resolver`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- constructor validation: CapabilityResolver(None) and
           CapabilityResolver(<non-registry>) both raise
           CapabilityResolverError; CapabilityResolver
           (CapabilitySkillRegistry()) succeeds.
    S2  -- identity preservation: CapabilityResolver stores the exact
           CapabilitySkillRegistry instance passed in (no copying) --
           mutating the original registry after construction (e.g.
           registering a new capability) is reflected in subsequent
           resolve() calls.
    S3  -- resolve success: resolve(capability_name) returns the tuple
           of skill names registered under that exact name.
    S4  -- resolve returns identical object (tuple identity): the
           returned tuple is the exact same instance that was
           registered, never a copy.
    S5  -- multiple capabilities: distinct names resolve to their own
           distinct, correctly matched skill-name tuples out of a
           registry holding several.
    S6  -- multi-instance independence: two CapabilityResolver
           instances built over two independent
           CapabilitySkillRegistry instances never cross-resolve into
           each other's mappings.
    S7  -- missing capability propagation: resolve(name) for a name
           not in the registry raises CapabilitySkillRegistryError
           (not CapabilityResolverError), unmodified/unwrapped from
           CapabilitySkillRegistry.get() -- never wrapped or
           converted.
    S8  -- invalid capability_name (non-str): resolve(<non-str>)
           raises CapabilityResolverError for a variety of non-str
           objects, including None.
    S9  -- empty/whitespace-only capability_name: resolve("") and
           resolve("   ") both raise CapabilityResolverError.
    S10 -- whitespace sensitivity: a registered name with surrounding
           whitespace does not match the trimmed (or padded) lookup
           key -- exact string match only, no stripping performed by
           CapabilityResolver itself.
    S11 -- case sensitivity: a name differing only by case does not
           resolve -- it raises CapabilitySkillRegistryError exactly
           like any other miss (no case-insensitive/fuzzy matching).
    S12 -- opaque skill-name handling: the tuple returned by
           resolve() consists of plain opaque strings, returned
           exactly as registered, with no inspection/validation of
           their shape or existence.
    S13 -- insertion order irrelevant: registering capabilities in a
           different order does not change which skill-name tuple a
           given capability_name resolves to.
    S14 -- no execution semantics: resolve() never calls, invokes, or
           executes anything -- it returns a plain tuple of strings,
           nothing callable is ever produced or invoked.
    S15 -- public API exactness: resolve() is the *only* public
           (non-dunder) method exposed by CapabilityResolver -- no
           get/has/list/register/unregister/execute/invoke/dispatch/
           call method exists.
    S16 -- forbidden imports: Orchestration.capability_resolver's own
           source file imports only Core.exceptions,
           Orchestration.capability_skill_registry, and typing
           (AST-level import inspection) -- no Capability/
           CapabilityRegistry/CapabilityManager/SkillRegistry/
           SkillResolver/BaseSkill/ToolRegistry/ToolResolver/
           BaseTool/Executor/Workflow*/Planner/Memory/Reflection/
           LearningLoop/EventBus/Services/Repository/Providers/
           Database/Agents import anywhere in the file.
    S17 -- repr stability: repr() of a CapabilityResolverError is
           stable across repeated calls and mentions the class name.
    S18 -- error hierarchy: CapabilityResolverError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    S19 -- namespace verification: Orchestration.capability_resolver's
           module namespace contains no Capability/CapabilityRegistry/
           CapabilityManager/SkillRegistry/SkillResolver/BaseSkill/
           ToolRegistry/ToolResolver/BaseTool/Executor/Workflow*/
           Planner/Memory/Reflection/LearningLoop/EventBus/Services/
           Repository/Providers/Database/Agents symbol.
    S20 -- no hidden state: a CapabilityResolver instance holds only
           '_capability_skill_registry' as an instance attribute.
    S21 -- no singleton: repeated CapabilityResolver(...) construction
           with fresh collaborators yields distinct instances holding
           distinct state.
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
from Orchestration.capability_resolver import (
    CapabilityResolver,
    CapabilityResolverError,
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


def _make_registry() -> CapabilitySkillRegistry:
    """Return a fresh CapabilitySkillRegistry."""
    return CapabilitySkillRegistry()


# ---------------------------------------------------------------------------
# S1 -- constructor validation
# ---------------------------------------------------------------------------
def scenario_constructor_validation() -> None:
    bad_values = (None, "not-a-registry", 123, object(), {}, [])

    for value in bad_values:
        raised = False
        try:
            CapabilityResolver(value)  # type: ignore[arg-type]
        except CapabilityResolverError:
            raised = True
        check(
            raised,
            f"S1: CapabilityResolver({value!r}) raises CapabilityResolverError",
        )

    registry = _make_registry()
    resolver = CapabilityResolver(registry)
    check(
        isinstance(resolver, CapabilityResolver),
        "S1: CapabilityResolver(CapabilitySkillRegistry()) constructs successfully",
    )


# ---------------------------------------------------------------------------
# S2 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    registry.register("market_analysis", ("price_lookup_skill",))
    check(
        resolver.resolve("market_analysis") == ("price_lookup_skill",),
        "S2: mutating the injected CapabilitySkillRegistry directly (post-construction) is visible through the resolver (no copy)",
    )


# ---------------------------------------------------------------------------
# S3 -- resolve success
# ---------------------------------------------------------------------------
def scenario_resolve_success() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    registry.register("news_capability", ("news_summary_skill", "sentiment_skill"))
    check(
        resolver.resolve("news_capability") == ("news_summary_skill", "sentiment_skill"),
        "S3: resolve() returns the tuple of skill names registered under that exact name",
    )


# ---------------------------------------------------------------------------
# S4 -- tuple identity
# ---------------------------------------------------------------------------
def scenario_tuple_identity_preserved() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    original_skills = ("skill_a", "skill_b")
    registry.register("x", original_skills)
    check(
        resolver.resolve("x") is original_skills,
        "S4: resolve() returns the exact same tuple object that was registered (no copy)",
    )
    check(
        resolver.resolve("x") is registry.get("x"),
        "S4: resolve() returns the exact same object CapabilitySkillRegistry.get() returns",
    )


# ---------------------------------------------------------------------------
# S5 -- multiple capabilities
# ---------------------------------------------------------------------------
def scenario_multiple_capabilities() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    registry.register("cap_alpha", ("skill_1",))
    registry.register("cap_beta", ("skill_2", "skill_3"))
    registry.register("cap_gamma", ("skill_4", "skill_5", "skill_6"))

    check(resolver.resolve("cap_alpha") == ("skill_1",), "S5: cap_alpha resolves to its own tuple")
    check(resolver.resolve("cap_beta") == ("skill_2", "skill_3"), "S5: cap_beta resolves to its own tuple")
    check(
        resolver.resolve("cap_gamma") == ("skill_4", "skill_5", "skill_6"),
        "S5: cap_gamma resolves to its own tuple",
    )


# ---------------------------------------------------------------------------
# S6 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    registry_a = _make_registry()
    registry_b = _make_registry()

    resolver_a = CapabilityResolver(registry_a)
    resolver_b = CapabilityResolver(registry_b)

    registry_a.register("shared_name", ("skill_from_a",))
    registry_b.register("shared_name", ("skill_from_b",))

    check(
        resolver_a.resolve("shared_name") == ("skill_from_a",),
        "S6: resolver_a resolves its own registry's mapping under a shared name",
    )
    check(
        resolver_b.resolve("shared_name") == ("skill_from_b",),
        "S6: resolver_b resolves its own (different) registry's mapping under the same shared name",
    )
    check(
        resolver_a.resolve("shared_name") != resolver_b.resolve("shared_name"),
        "S6: two independent CapabilityResolver instances never cross-resolve",
    )


# ---------------------------------------------------------------------------
# S7 -- missing capability propagation
# ---------------------------------------------------------------------------
def scenario_missing_capability_propagation() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    raised_type = None
    try:
        resolver.resolve("never_registered")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilitySkillRegistryError,
        f"S7: resolve() of a missing capability_name raises CapabilitySkillRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S8 -- invalid capability_name (non-str)
# ---------------------------------------------------------------------------
def scenario_invalid_capability_name_rejected() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    for value in (None, 123, 1.5, ["a"], {"k": "v"}, {"a"}, object(), True):
        raised_type = None
        try:
            resolver.resolve(value)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is CapabilityResolverError,
            f"S8: resolve({value!r}) raises CapabilityResolverError unmodified; got {raised_type!r}",
        )


# ---------------------------------------------------------------------------
# S9 -- empty/whitespace-only capability_name
# ---------------------------------------------------------------------------
def scenario_empty_whitespace_capability_name_rejected() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    for value in ("", "   ", "\t", "\n"):
        raised_type = None
        try:
            resolver.resolve(value)
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is CapabilityResolverError,
            f"S9: resolve({value!r}) raises CapabilityResolverError unmodified; got {raised_type!r}",
        )


# ---------------------------------------------------------------------------
# S10 -- whitespace sensitivity
# ---------------------------------------------------------------------------
def scenario_whitespace_sensitivity() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    registry.register("padded_name", ("skill_a",))

    raised_type = None
    try:
        resolver.resolve("  padded_name  ")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilitySkillRegistryError,
        f"S10: resolve() performs no whitespace trimming -- padded name misses exactly like any other name; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S11 -- case sensitivity
# ---------------------------------------------------------------------------
def scenario_case_sensitivity() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    registry.register("MixedCaseCapability", ("skill_a",))

    raised_type = None
    try:
        resolver.resolve("mixedcasecapability")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilitySkillRegistryError,
        f"S11: resolve() performs no case-insensitive matching -- differing case misses exactly like any other name; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S12 -- opaque skill-name handling
# ---------------------------------------------------------------------------
def scenario_opaque_skill_name_handling() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    registry.register(
        "a_totally_made_up_capability",
        ("a_totally_made_up_skill", "another_fictitious_skill"),
    )
    check(
        resolver.resolve("a_totally_made_up_capability")
        == ("a_totally_made_up_skill", "another_fictitious_skill"),
        "S12: resolve() returns plain opaque strings exactly as registered, with no existence validation",
    )


# ---------------------------------------------------------------------------
# S13 -- insertion order irrelevant
# ---------------------------------------------------------------------------
def scenario_insertion_order_irrelevant() -> None:
    registry_forward = _make_registry()
    registry_forward.register("first", ("a",))
    registry_forward.register("second", ("b",))

    registry_reverse = _make_registry()
    registry_reverse.register("second", ("b",))
    registry_reverse.register("first", ("a",))

    resolver_forward = CapabilityResolver(registry_forward)
    resolver_reverse = CapabilityResolver(registry_reverse)

    check(
        resolver_forward.resolve("first") == resolver_reverse.resolve("first") == ("a",),
        "S13: registration order does not affect which tuple 'first' resolves to",
    )
    check(
        resolver_forward.resolve("second") == resolver_reverse.resolve("second") == ("b",),
        "S13: registration order does not affect which tuple 'second' resolves to",
    )


# ---------------------------------------------------------------------------
# S14 -- no execution semantics
# ---------------------------------------------------------------------------
def scenario_no_execution_semantics() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    registry.register("cap", ("skill_x", "skill_y"))
    result = resolver.resolve("cap")

    check(
        isinstance(result, tuple),
        "S14: resolve() returns a plain tuple, never a callable or executable object",
    )
    check(
        all(isinstance(item, str) for item in result),
        "S14: every element of the resolved tuple is a plain str -- nothing invoked or instantiated",
    )


# ---------------------------------------------------------------------------
# S15 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in dir(CapabilityResolver)
        if not name.startswith("_") and callable(getattr(CapabilityResolver, name))
    }
    check(
        public_methods == {"resolve"},
        f"S15: CapabilityResolver exposes exactly {{'resolve'}}; got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# S16 -- AST import verification
# ---------------------------------------------------------------------------
def scenario_ast_import_verification() -> None:
    source_path = ROOT / "Orchestration" / "capability_resolver.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.append(node.module)

    allowed = {
        "typing",
        "__future__",
        "Core.exceptions",
        "Orchestration.capability_skill_registry",
    }

    unexpected = [mod for mod in imported_modules if mod not in allowed]
    check(
        not unexpected,
        f"S16: Orchestration.capability_resolver imports only allowed modules; unexpected={unexpected!r}",
    )
    check(
        "Orchestration.capability_skill_registry" in imported_modules,
        "S16: Orchestration.capability_resolver imports Orchestration.capability_skill_registry",
    )
    check(
        "Core.exceptions" in imported_modules,
        "S16: Orchestration.capability_resolver imports Core.exceptions",
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
        "BaseSkill",
        "ToolRegistry",
        "ToolResolver",
        "BaseTool",
        "Executor",
        "Workflow",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Planner",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "Services",
        "Repository",
        "Providers",
        "Database",
        "Agents",
    ]
    for symbol in forbidden_symbols:
        check(
            symbol not in imported_names,
            f"S16: Orchestration/capability_resolver.py's AST-parsed import names do not include '{symbol}'",
        )


# ---------------------------------------------------------------------------
# S17 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_stability() -> None:
    err = CapabilityResolverError("boom")
    r1 = repr(err)
    r2 = repr(err)
    check(r1 == r2, "S17: repr(CapabilityResolverError(...)) is stable across repeated calls")
    check(
        "CapabilityResolverError" in r1,
        "S17: repr(CapabilityResolverError(...)) mentions the class name",
    )


# ---------------------------------------------------------------------------
# S18 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(CapabilityResolverError, AgentError),
        "S18: CapabilityResolverError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(CapabilityResolverError, Exception),
        "S18: CapabilityResolverError (transitively) subclasses Exception",
    )


# ---------------------------------------------------------------------------
# S19 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_namespace_verification() -> None:
    import Orchestration.capability_resolver as capability_resolver_module

    forbidden_symbols = (
        "Capability",
        "CapabilityRegistry",
        "CapabilityManager",
        "SkillRegistry",
        "SkillResolver",
        "BaseSkill",
        "ToolRegistry",
        "ToolResolver",
        "BaseTool",
        "Executor",
        "Workflow",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Planner",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "Services",
        "Repository",
        "Providers",
        "Database",
        "Agents",
    )
    for symbol in forbidden_symbols:
        check(
            not hasattr(capability_resolver_module, symbol),
            f"S19: Orchestration.capability_resolver's module namespace contains no {symbol} symbol",
        )


# ---------------------------------------------------------------------------
# S20 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    registry = _make_registry()
    resolver = CapabilityResolver(registry)

    instance_attrs = {name for name in vars(resolver) if not name.startswith("__")}
    check(
        instance_attrs == {"_capability_skill_registry"},
        f"S20: a CapabilityResolver instance holds only '_capability_skill_registry' as state; got {sorted(instance_attrs)!r}",
    )


# ---------------------------------------------------------------------------
# S21 -- no singleton
# ---------------------------------------------------------------------------
def scenario_no_singleton() -> None:
    registry1 = _make_registry()
    registry2 = _make_registry()

    resolver1 = CapabilityResolver(registry1)
    resolver2 = CapabilityResolver(registry2)

    check(
        resolver1 is not resolver2,
        "S21: repeated CapabilityResolver(...) construction yields distinct instances",
    )

    registry1.register("only_in_one", ("skill_only_here",))
    raised = False
    try:
        resolver2.resolve("only_in_one")
    except CapabilitySkillRegistryError:
        raised = True
    check(
        raised,
        "S21: state registered in one CapabilityResolver's registry is not visible in another (no singleton/shared state)",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_validation,
        scenario_identity_preservation,
        scenario_resolve_success,
        scenario_tuple_identity_preserved,
        scenario_multiple_capabilities,
        scenario_multi_instance_independence,
        scenario_missing_capability_propagation,
        scenario_invalid_capability_name_rejected,
        scenario_empty_whitespace_capability_name_rejected,
        scenario_whitespace_sensitivity,
        scenario_case_sensitivity,
        scenario_opaque_skill_name_handling,
        scenario_insertion_order_irrelevant,
        scenario_no_execution_semantics,
        scenario_public_api_exactness,
        scenario_ast_import_verification,
        scenario_repr_stability,
        scenario_error_hierarchy,
        scenario_namespace_verification,
        scenario_no_hidden_state,
        scenario_no_singleton,
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
    print(f"PHASE 5 SPRINT 66 CAPABILITY RESOLVER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())