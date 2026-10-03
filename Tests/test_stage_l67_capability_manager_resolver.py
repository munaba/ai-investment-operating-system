"""
Phase 5 Sprint 67 proof suite -- ``CapabilityManager`` upgraded to a
facade over both ``CapabilityRegistry`` and ``CapabilityResolver``.

Scope: dedicated regression suite for the Sprint 67 addition only --
``Orchestration.capability_manager.CapabilityManager``, now a
six-method facade that delegates directly to an injected
``CapabilityRegistry`` (``register``/``get``/``has``/``list``/
``unregister``) and an injected ``CapabilityResolver`` (``resolve``),
plus its own ``CapabilityManagerError`` exception type. This is a
facade only: no caching, no normalization, no lowercasing, no
trimming, no sorting, no deduplication, no filtering, no wrapping of
exceptions, no creation of registries or resolvers, no instantiation
of capabilities or skills, and no access to ``SkillRegistry``,
``SkillResolver``, ``ToolRegistry``, ``ToolResolver``, ``Planner``,
``Executor``, ``Workflow``, ``Runtime``, ``Memory``, or ``EventBus``.
``Orchestration.capability_registry.CapabilityRegistry`` (Sprint 63)
and ``Orchestration.capability_resolver.CapabilityResolver`` (Sprint
66) are unchanged by this sprint -- this suite does not re-verify
their own internal behavior beyond confirming Sprint 67 introduces no
regression to it.

``CapabilityManager`` never imports, constructs, or references
``Capability``, ``Planner``, ``SkillRegistry``, ``SkillResolver``,
``ToolRegistry``, ``ToolResolver``, ``ToolManager``,
``Workflow``/``WorkflowEngine``/``WorkflowRuntime``/
``WorkflowExecutionCoordinator``, ``Runtime``, ``Executor``,
``Memory``, ``Reflection``, ``LearningLoop``, ``EventBus``,
``Providers``, ``Services``, ``Repository``, ``Database``, or
``Core.composition_root`` (proven both by module-namespace inspection
and by AST-level import inspection of the module's own source file).
``Orchestration.capability_manager`` imports only
``Core.exceptions.AgentError``,
``Orchestration.capability_registry.CapabilityRegistry``,
``Orchestration.capability_resolver.CapabilityResolver``, and the
stdlib ``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x proof suites (mirroring
``Tests.test_stage_l59_tool_manager`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- constructor validation (valid collaborators): a valid
           (CapabilityRegistry, CapabilityResolver) pair constructs
           successfully.
    S2  -- constructor validation (invalid registry): every invalid
           value passed as capability_registry raises
           CapabilityManagerError, with a valid capability_resolver.
    S3  -- constructor validation (invalid resolver): every invalid
           value passed as capability_resolver raises
           CapabilityManagerError, with a valid capability_registry.
    S4  -- constructor validation (both invalid / None): both
           arguments invalid or None raises CapabilityManagerError.
    S5  -- identity preservation (registry): the exact
           CapabilityRegistry instance passed in is stored by
           identity -- mutating it directly (register/unregister) is
           visible through the manager.
    S6  -- identity preservation (resolver): the exact
           CapabilityResolver instance passed in is stored by
           identity -- resolving through the manager matches
           resolving through the resolver directly.
    S7  -- register() delegation: CapabilityManager.register(name,
           capability) stores the capability in the underlying
           CapabilityRegistry, visible via registry.get()/has()
           directly.
    S8  -- get() delegation: CapabilityManager.get(name) returns the
           exact same object CapabilityRegistry.get(name) would
           return.
    S9  -- has() delegation: CapabilityManager.has(name) matches
           CapabilityRegistry.has(name) exactly, before and after
           registration.
    S10 -- list() delegation: CapabilityManager.list() matches
           CapabilityRegistry.list() exactly, including insertion
           order.
    S11 -- unregister() delegation: CapabilityManager.unregister(name)
           removes the capability from the underlying
           CapabilityRegistry -- a subsequent has()/get() reflects
           the removal.
    S12 -- resolve() delegation: CapabilityManager.resolve(name)
           returns the exact same tuple CapabilityResolver.resolve(
           name) returns.
    S13 -- exception propagation (register): a duplicate/invalid
           register() call raises CapabilityRegistryError unmodified,
           not CapabilityManagerError.
    S14 -- exception propagation (get): get() of a missing name
           raises CapabilityRegistryError unmodified, not
           CapabilityManagerError.
    S15 -- exception propagation (unregister): unregister() of a
           missing name raises CapabilityRegistryError unmodified,
           not CapabilityManagerError.
    S16 -- exception propagation (resolve, resolver-level): resolve()
           with an invalid capability_name raises
           CapabilityResolverError unmodified, not
           CapabilityManagerError.
    S17 -- exception propagation (resolve, registry-level miss):
           resolve() of a capability_name with no declared skill
           names raises CapabilitySkillRegistryError unmodified, not
           CapabilityManagerError.
    S18 -- no wrapping: registering a capability through the manager
           and getting it back returns the identical object (no
           copy, no wrapper class introduced by CapabilityManager).
    S19 -- no business logic: CapabilityManager performs no
           normalization (case/whitespace) beyond what
           CapabilityRegistry/CapabilityResolver themselves already
           do.
    S20 -- public API exactness: exactly six public (non-dunder)
           methods exist on CapabilityManager -- register, get, has,
           list, unregister, resolve -- nothing else.
    S21 -- forbidden methods absent: no execute/run/invoke/dispatch/
           call/plan/route/match method exists on CapabilityManager.
    S22 -- AST import verification: Orchestration.capability_manager's
           own source file imports only Core.exceptions,
           Orchestration.capability_registry,
           Orchestration.capability_resolver, and typing -- no
           forbidden import anywhere in the file.
    S23 -- namespace verification: Orchestration.capability_manager's
           module namespace contains no Capability/Planner/
           SkillRegistry/SkillResolver/ToolRegistry/ToolResolver/
           ToolManager/Workflow*/Runtime*/Executor/Memory/Reflection/
           LearningLoop/EventBus/Providers/Services/Repository/
           Database/CompositionRoot symbol.
    S24 -- multiple CapabilityManager independence: two
           CapabilityManager instances built over two independent
           collaborator sets never cross-resolve into each other's
           capabilities.
    S25 -- no hidden state: a CapabilityManager instance holds only
           '_capability_registry' and '_capability_resolver' as
           instance attributes (no caches, no extra state).
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
from Orchestration.capability_registry import CapabilityRegistry, CapabilityRegistryError
from Orchestration.capability_skill_registry import (
    CapabilitySkillRegistry,
    CapabilitySkillRegistryError,
)
from Orchestration.capability_resolver import CapabilityResolver, CapabilityResolverError
from Orchestration.capability_manager import CapabilityManager, CapabilityManagerError

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


def _make_stack():
    """Return a fresh (CapabilityRegistry, CapabilitySkillRegistry,
    CapabilityResolver) triple, all independent."""
    registry = CapabilityRegistry()
    skill_registry = CapabilitySkillRegistry()
    resolver = CapabilityResolver(skill_registry)
    return registry, skill_registry, resolver


# ---------------------------------------------------------------------------
# S1 -- constructor validation (valid collaborators)
# ---------------------------------------------------------------------------
def scenario_constructor_valid() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)
    check(
        isinstance(manager, CapabilityManager),
        "S1: CapabilityManager(CapabilityRegistry(), CapabilityResolver(...)) constructs successfully",
    )


# ---------------------------------------------------------------------------
# S2 -- constructor validation (invalid registry)
# ---------------------------------------------------------------------------
def scenario_constructor_invalid_registry() -> None:
    _registry, _skill_registry, resolver = _make_stack()
    bad_values = (None, "not-a-registry", 123, object(), {}, [])

    for value in bad_values:
        raised = False
        try:
            CapabilityManager(value, resolver)  # type: ignore[arg-type]
        except CapabilityManagerError:
            raised = True
        check(
            raised,
            f"S2: CapabilityManager({value!r}, <resolver>) raises CapabilityManagerError",
        )


# ---------------------------------------------------------------------------
# S3 -- constructor validation (invalid resolver)
# ---------------------------------------------------------------------------
def scenario_constructor_invalid_resolver() -> None:
    registry, _skill_registry, _resolver = _make_stack()
    bad_values = (None, "not-a-resolver", 123, object(), {}, [])

    for value in bad_values:
        raised = False
        try:
            CapabilityManager(registry, value)  # type: ignore[arg-type]
        except CapabilityManagerError:
            raised = True
        check(
            raised,
            f"S3: CapabilityManager(<registry>, {value!r}) raises CapabilityManagerError",
        )


# ---------------------------------------------------------------------------
# S4 -- constructor validation (both invalid / None)
# ---------------------------------------------------------------------------
def scenario_constructor_both_invalid() -> None:
    raised = False
    try:
        CapabilityManager(None, None)  # type: ignore[arg-type]
    except CapabilityManagerError:
        raised = True
    check(raised, "S4: CapabilityManager(None, None) raises CapabilityManagerError")

    raised = False
    try:
        CapabilityManager("bad", "also-bad")  # type: ignore[arg-type]
    except CapabilityManagerError:
        raised = True
    check(raised, "S4: CapabilityManager('bad', 'also-bad') raises CapabilityManagerError")


# ---------------------------------------------------------------------------
# S5 -- identity preservation (registry)
# ---------------------------------------------------------------------------
def scenario_identity_preservation_registry() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    capability = object()
    manager.register("alpha", capability)
    check(
        registry.get("alpha") is capability,
        "S5: registering via the manager mutates the exact injected CapabilityRegistry instance",
    )

    registry.register("beta", "direct")
    check(
        manager.get("beta") == "direct",
        "S5: mutating the injected CapabilityRegistry directly is visible through the manager (no copy)",
    )


# ---------------------------------------------------------------------------
# S6 -- identity preservation (resolver)
# ---------------------------------------------------------------------------
def scenario_identity_preservation_resolver() -> None:
    registry, skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    skill_registry.register("cap_x", ("skill_a", "skill_b"))
    check(
        manager.resolve("cap_x") == resolver.resolve("cap_x") == ("skill_a", "skill_b"),
        "S6: resolving via the manager matches resolving via the exact injected CapabilityResolver instance",
    )


# ---------------------------------------------------------------------------
# S7 -- register() delegation
# ---------------------------------------------------------------------------
def scenario_register_delegation() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    capability = object()
    manager.register("stock_lookup", capability)
    check(
        registry.get("stock_lookup") is capability,
        "S7: CapabilityManager.register() stores the capability in the underlying CapabilityRegistry",
    )
    check(
        registry.has("stock_lookup"),
        "S7: CapabilityManager.register() result is visible via CapabilityRegistry.has() directly",
    )


# ---------------------------------------------------------------------------
# S8 -- get() delegation
# ---------------------------------------------------------------------------
def scenario_get_delegation() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    capability = object()
    registry.register("news_capability", capability)
    check(
        manager.get("news_capability") is registry.get("news_capability"),
        "S8: CapabilityManager.get() returns the exact same object CapabilityRegistry.get() returns",
    )
    check(
        manager.get("news_capability") is capability,
        "S8: CapabilityManager.get() returns the exact registered object",
    )


# ---------------------------------------------------------------------------
# S9 -- has() delegation
# ---------------------------------------------------------------------------
def scenario_has_delegation() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    check(
        manager.has("nope") == registry.has("nope"),
        "S9: CapabilityManager.has() matches CapabilityRegistry.has() before registration",
    )

    registry.register("nope", object())
    check(
        manager.has("nope") == registry.has("nope") == True,
        "S9: CapabilityManager.has() matches CapabilityRegistry.has() after registration",
    )


# ---------------------------------------------------------------------------
# S10 -- list() delegation
# ---------------------------------------------------------------------------
def scenario_list_delegation() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    for name in ("z_cap", "a_cap", "m_cap"):
        registry.register(name, object())

    check(
        manager.list() == registry.list(),
        "S10: CapabilityManager.list() matches CapabilityRegistry.list() exactly",
    )
    check(
        manager.list() == ("z_cap", "a_cap", "m_cap"),
        "S10: CapabilityManager.list() preserves insertion order",
    )


# ---------------------------------------------------------------------------
# S11 -- unregister() delegation
# ---------------------------------------------------------------------------
def scenario_unregister_delegation() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    registry.register("temp_cap", object())
    manager.unregister("temp_cap")
    check(
        not registry.has("temp_cap"),
        "S11: CapabilityManager.unregister() removes the capability from the underlying CapabilityRegistry",
    )

    raised = False
    try:
        manager.get("temp_cap")
    except CapabilityRegistryError:
        raised = True
    check(
        raised,
        "S11: getting an unregistered capability after CapabilityManager.unregister() raises CapabilityRegistryError",
    )


# ---------------------------------------------------------------------------
# S12 -- resolve() delegation
# ---------------------------------------------------------------------------
def scenario_resolve_delegation() -> None:
    registry, skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    skill_registry.register("market_analysis", ("price_skill", "risk_skill"))
    check(
        manager.resolve("market_analysis") is resolver.resolve("market_analysis"),
        "S12: CapabilityManager.resolve() returns the exact same object CapabilityResolver.resolve() returns",
    )
    check(
        manager.resolve("market_analysis") == ("price_skill", "risk_skill"),
        "S12: CapabilityManager.resolve() returns the exact resolved tuple",
    )


# ---------------------------------------------------------------------------
# S13 -- exception propagation (register)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_register() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    manager.register("dup", object())
    raised_type = None
    try:
        manager.register("dup", object())
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is CapabilityRegistryError,
        f"S13: duplicate register() via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )

    raised_type = None
    try:
        manager.register("", object())
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilityRegistryError,
        f"S13: invalid-name register() via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S14 -- exception propagation (get)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_get() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    raised_type = None
    try:
        manager.get("missing_name")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilityRegistryError,
        f"S14: get() of a missing name via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S15 -- exception propagation (unregister)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_unregister() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    raised_type = None
    try:
        manager.unregister("never_registered")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilityRegistryError,
        f"S15: unregister() of a missing name via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S16 -- exception propagation (resolve, resolver-level)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_resolve_resolver_level() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    for value in ("", "   ", None, 123):
        raised_type = None
        try:
            manager.resolve(value)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
        check(
            raised_type is CapabilityResolverError,
            f"S16: resolve({value!r}) via manager raises CapabilityResolverError unmodified; got {raised_type!r}",
        )


# ---------------------------------------------------------------------------
# S17 -- exception propagation (resolve, registry-level miss)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_resolve_registry_level() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    raised_type = None
    try:
        manager.resolve("never_declared_capability")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilitySkillRegistryError,
        f"S17: resolve() of an undeclared capability_name via manager raises CapabilitySkillRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S18 -- no wrapping
# ---------------------------------------------------------------------------
def scenario_no_wrapping() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    class _CustomCapability:
        pass

    capability_instance = _CustomCapability()
    manager.register("custom", capability_instance)
    fetched = manager.get("custom")
    check(
        fetched is capability_instance,
        "S18: round-tripping a capability through the manager returns the identical object, no wrapping",
    )
    check(
        type(fetched) is _CustomCapability,
        "S18: the fetched object's type is unchanged -- no wrapper class introduced",
    )


# ---------------------------------------------------------------------------
# S19 -- no business logic (no normalization beyond collaborators')
# ---------------------------------------------------------------------------
def scenario_no_business_logic() -> None:
    registry, skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    manager.register("MixedCase", object())
    check(
        not manager.has("mixedcase"),
        "S19: CapabilityManager performs no case normalization on register/has -- 'mixedcase' does not match 'MixedCase'",
    )

    skill_registry.register("MixedResolve", ("skill_a",))
    raised = False
    try:
        manager.resolve("mixedresolve")
    except CapabilitySkillRegistryError:
        raised = True
    check(
        raised,
        "S19: CapabilityManager performs no case normalization on resolve -- 'mixedresolve' does not match 'MixedResolve'",
    )

    raised = False
    try:
        manager.get("  MixedCase  ")
    except CapabilityRegistryError:
        raised = True
    check(
        raised,
        "S19: CapabilityManager performs no whitespace trimming -- padded name does not resolve",
    )


# ---------------------------------------------------------------------------
# S20 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in dir(CapabilityManager)
        if not name.startswith("_") and callable(getattr(CapabilityManager, name))
    }
    check(
        public_methods == {"register", "get", "has", "list", "unregister", "resolve"},
        f"S20: CapabilityManager exposes exactly the six specified public methods; got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# S21 -- forbidden methods absent
# ---------------------------------------------------------------------------
def scenario_forbidden_methods_absent() -> None:
    forbidden = (
        "execute",
        "run",
        "invoke",
        "dispatch",
        "call",
        "plan",
        "route",
        "match",
        "cache",
        "publish",
        "subscribe",
        "remember",
        "reflect",
        "learn",
    )
    for method_name in forbidden:
        check(
            not hasattr(CapabilityManager, method_name),
            f"S21: CapabilityManager has no '{method_name}' method",
        )


# ---------------------------------------------------------------------------
# S22 -- AST import verification
# ---------------------------------------------------------------------------
def scenario_ast_import_verification() -> None:
    source_path = ROOT / "Orchestration" / "capability_manager.py"
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
        "Orchestration.capability_registry",
        "Orchestration.capability_resolver",
    }

    unexpected = [mod for mod in imported_modules if mod not in allowed]
    check(
        not unexpected,
        f"S22: Orchestration.capability_manager imports only allowed modules; unexpected={unexpected!r}",
    )
    check(
        "Orchestration.capability_registry" in imported_modules,
        "S22: Orchestration.capability_manager imports Orchestration.capability_registry",
    )
    check(
        "Orchestration.capability_resolver" in imported_modules,
        "S22: Orchestration.capability_manager imports Orchestration.capability_resolver",
    )
    check(
        "Core.exceptions" in imported_modules,
        "S22: Orchestration.capability_manager imports Core.exceptions",
    )


# ---------------------------------------------------------------------------
# S23 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_namespace_verification() -> None:
    import Orchestration.capability_manager as capability_manager_module

    forbidden_symbols = (
        "Capability",
        "Planner",
        "SkillRegistry",
        "SkillResolver",
        "ToolRegistry",
        "ToolResolver",
        "ToolManager",
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
        "Providers",
        "Services",
        "Repository",
        "Database",
        "CompositionRoot",
    )
    for symbol in forbidden_symbols:
        check(
            not hasattr(capability_manager_module, symbol),
            f"S23: Orchestration.capability_manager's module namespace contains no {symbol} symbol",
        )


# ---------------------------------------------------------------------------
# S24 -- multiple CapabilityManager independence
# ---------------------------------------------------------------------------
def scenario_multiple_manager_independence() -> None:
    registry_a, skill_registry_a, resolver_a = _make_stack()
    registry_b, skill_registry_b, resolver_b = _make_stack()

    manager_a = CapabilityManager(registry_a, resolver_a)
    manager_b = CapabilityManager(registry_b, resolver_b)

    capability_a = object()
    capability_b = object()
    manager_a.register("shared_name", capability_a)
    manager_b.register("shared_name", capability_b)

    check(
        manager_a.get("shared_name") is capability_a,
        "S24: manager_a fetches its own capability under a shared name",
    )
    check(
        manager_b.get("shared_name") is capability_b,
        "S24: manager_b fetches its own (different) capability under the same shared name",
    )
    check(
        manager_a.get("shared_name") is not manager_b.get("shared_name"),
        "S24: two independent CapabilityManager instances never cross-resolve on get()",
    )

    skill_registry_a.register("shared_capability", ("skill_from_a",))
    skill_registry_b.register("shared_capability", ("skill_from_b",))
    check(
        manager_a.resolve("shared_capability") == ("skill_from_a",),
        "S24: manager_a resolves its own registry's mapping under a shared capability name",
    )
    check(
        manager_b.resolve("shared_capability") == ("skill_from_b",),
        "S24: manager_b resolves its own (different) registry's mapping under the same shared capability name",
    )


# ---------------------------------------------------------------------------
# S25 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    registry, _skill_registry, resolver = _make_stack()
    manager = CapabilityManager(registry, resolver)

    instance_attrs = {name for name in vars(manager) if not name.startswith("__")}
    check(
        instance_attrs == {"_capability_registry", "_capability_resolver"},
        f"S25: a CapabilityManager instance holds only '_capability_registry' and '_capability_resolver' as state; got {sorted(instance_attrs)!r}",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_valid,
        scenario_constructor_invalid_registry,
        scenario_constructor_invalid_resolver,
        scenario_constructor_both_invalid,
        scenario_identity_preservation_registry,
        scenario_identity_preservation_resolver,
        scenario_register_delegation,
        scenario_get_delegation,
        scenario_has_delegation,
        scenario_list_delegation,
        scenario_unregister_delegation,
        scenario_resolve_delegation,
        scenario_exception_propagation_register,
        scenario_exception_propagation_get,
        scenario_exception_propagation_unregister,
        scenario_exception_propagation_resolve_resolver_level,
        scenario_exception_propagation_resolve_registry_level,
        scenario_no_wrapping,
        scenario_no_business_logic,
        scenario_public_api_exactness,
        scenario_forbidden_methods_absent,
        scenario_ast_import_verification,
        scenario_namespace_verification,
        scenario_multiple_manager_independence,
        scenario_no_hidden_state,
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
    print(f"PHASE 5 SPRINT 67 CAPABILITY MANAGER + RESOLVER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())