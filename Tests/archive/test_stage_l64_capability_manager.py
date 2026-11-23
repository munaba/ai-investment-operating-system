"""
Phase 5 Sprint 64 proof suite -- ``CapabilityManager`` (facade over
``CapabilityRegistry``).

Scope: dedicated regression suite for the Sprint 64 addition only --
``Orchestration.capability_manager.CapabilityManager``, a five-method
facade that delegates directly to an injected ``CapabilityRegistry``,
plus its own ``CapabilityManagerError`` exception type. This is a
facade only: no execution, no caching, no invocation, no dispatch, no
routing, no planner logic, no runtime logic, no workflow logic, no
event publishing, no memory, no reflection, no learning, no matching,
no metadata lookup, no alias lookup, no normalization, no fuzzy
matching, no sorting, no filtering, no wrapping of exceptions, no auto
registration, and no singleton.
``Orchestration.capability_registry.CapabilityRegistry`` (Sprint 63)
is unchanged by this sprint -- this suite does not re-verify its own
internal behavior beyond confirming Sprint 64 introduces no
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
``Orchestration.capability_registry.CapabilityRegistry``, and the
stdlib ``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x/L6x proof suites (mirroring
``Tests.test_stage_l59_tool_manager`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- constructor validation: CapabilityManager(<bad>) raises
           CapabilityManagerError for every invalid
           capability_registry value; a valid CapabilityRegistry
           constructs successfully.
    S2  -- identity preservation: the exact CapabilityRegistry
           instance passed in is stored by identity -- never copied,
           never rebuilt (verified indirectly via cross-mutation
           visibility, since CapabilityManager exposes no public
           accessor for its collaborator).
    S3  -- register() delegation: CapabilityManager.register(name,
           capability) stores the capability in the underlying
           CapabilityRegistry, visible via registry.get()/
           registry.has() directly.
    S4  -- get() delegation: CapabilityManager.get(name) returns the
           exact same object CapabilityRegistry.get(name) would
           return.
    S5  -- has() delegation: CapabilityManager.has(name) matches
           CapabilityRegistry.has(name) exactly, both before and
           after registration.
    S6  -- list() delegation: CapabilityManager.list() matches
           CapabilityRegistry.list() exactly, including insertion
           order.
    S7  -- unregister() delegation: CapabilityManager.unregister(name)
           removes the capability from the underlying
           CapabilityRegistry -- a subsequent has()/get() reflects
           the removal.
    S8  -- exception propagation (register): a duplicate/invalid
           register() call raises CapabilityRegistryError unmodified,
           not CapabilityManagerError.
    S9  -- exception propagation (get): get() of a missing name
           raises CapabilityRegistryError unmodified, not
           CapabilityManagerError.
    S10 -- exception propagation (unregister): unregister() of a
           missing name raises CapabilityRegistryError unmodified,
           not CapabilityManagerError.
    S11 -- no wrapping: registering a capability through the manager
           and getting it back returns the identical object (no copy,
           no wrapper class introduced by CapabilityManager).
    S12 -- no business logic: CapabilityManager performs no
           normalization (case/whitespace) beyond what
           CapabilityRegistry itself already does.
    S13 -- public API exactness: exactly five public (non-dunder)
           methods exist on CapabilityManager -- register, get, has,
           list, unregister -- nothing else.
    S14 -- forbidden methods absent: no execute/run/invoke/dispatch/
           call/plan/route/match method exists on CapabilityManager.
    S15 -- AST import verification: Orchestration.capability_manager's
           own source file imports only Core.exceptions,
           Orchestration.capability_registry, and typing -- no
           forbidden import anywhere in the file.
    S16 -- namespace verification: Orchestration.capability_manager's
           module namespace contains no Capability/Planner/
           SkillRegistry/SkillResolver/ToolRegistry/ToolResolver/
           ToolManager/Workflow*/Runtime*/Executor/Memory/Reflection/
           LearningLoop/EventBus/Providers/Services/Repository/
           Database/CompositionRoot symbol.
    S17 -- multiple CapabilityManager independence: two
           CapabilityManager instances built over two independent
           CapabilityRegistry instances never cross-resolve into each
           other's capabilities.
    S18 -- no singleton: repeated CapabilityManager(...) construction
           with fresh collaborators yields distinct instances holding
           distinct state.
    S19 -- no hidden state: a CapabilityManager instance holds only
           '_capability_registry' as an instance attribute.
    S20 -- zero execution semantics: registering a callable object and
           getting it back returns the callable itself, unexecuted --
           CapabilityManager never calls, invokes, or executes
           anything it manages.
    S21 -- error hierarchy: CapabilityManagerError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    S22 -- repr stability: repr() of a CapabilityManagerError is
           stable across repeated calls and mentions the class name.
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


def _make_registry() -> CapabilityRegistry:
    """Return a fresh CapabilityRegistry."""
    return CapabilityRegistry()


# ---------------------------------------------------------------------------
# S1 -- constructor validation
# ---------------------------------------------------------------------------
def scenario_constructor_validation() -> None:
    bad_values = (None, "not-a-registry", 123, object(), {}, [])

    for value in bad_values:
        raised = False
        try:
            CapabilityManager(value)  # type: ignore[arg-type]
        except CapabilityManagerError:
            raised = True
        check(
            raised,
            f"S1: CapabilityManager({value!r}) raises CapabilityManagerError",
        )

    registry = _make_registry()
    manager = CapabilityManager(registry)
    check(
        isinstance(manager, CapabilityManager),
        "S1: CapabilityManager(CapabilityRegistry()) constructs successfully",
    )


# ---------------------------------------------------------------------------
# S2 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    capability = object()
    manager.register("alpha", capability)
    check(
        registry.get("alpha") is capability,
        "S2: registering via the manager mutates the exact injected CapabilityRegistry instance",
    )

    registry.register("beta", "direct")
    check(
        manager.get("beta") == "direct",
        "S2: mutating the injected CapabilityRegistry directly is visible through the manager (no copy)",
    )


# ---------------------------------------------------------------------------
# S3 -- register() delegation
# ---------------------------------------------------------------------------
def scenario_register_delegation() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    capability = object()
    manager.register("stock_lookup", capability)
    check(
        registry.get("stock_lookup") is capability,
        "S3: CapabilityManager.register() stores the capability in the underlying CapabilityRegistry",
    )
    check(
        registry.has("stock_lookup"),
        "S3: CapabilityManager.register() result is visible via CapabilityRegistry.has() directly",
    )


# ---------------------------------------------------------------------------
# S4 -- get() delegation
# ---------------------------------------------------------------------------
def scenario_get_delegation() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    capability = object()
    registry.register("news_capability", capability)
    check(
        manager.get("news_capability") is registry.get("news_capability"),
        "S4: CapabilityManager.get() returns the exact same object CapabilityRegistry.get() returns",
    )
    check(
        manager.get("news_capability") is capability,
        "S4: CapabilityManager.get() returns the exact registered object",
    )


# ---------------------------------------------------------------------------
# S5 -- has() delegation
# ---------------------------------------------------------------------------
def scenario_has_delegation() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    check(
        manager.has("nope") == registry.has("nope"),
        "S5: CapabilityManager.has() matches CapabilityRegistry.has() before registration",
    )

    registry.register("nope", object())
    check(
        manager.has("nope") == registry.has("nope") == True,
        "S5: CapabilityManager.has() matches CapabilityRegistry.has() after registration",
    )


# ---------------------------------------------------------------------------
# S6 -- list() delegation
# ---------------------------------------------------------------------------
def scenario_list_delegation() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    for name in ("z_cap", "a_cap", "m_cap"):
        registry.register(name, object())

    check(
        manager.list() == registry.list(),
        "S6: CapabilityManager.list() matches CapabilityRegistry.list() exactly",
    )
    check(
        manager.list() == ("z_cap", "a_cap", "m_cap"),
        "S6: CapabilityManager.list() preserves insertion order",
    )


# ---------------------------------------------------------------------------
# S7 -- unregister() delegation
# ---------------------------------------------------------------------------
def scenario_unregister_delegation() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    registry.register("temp_cap", object())
    manager.unregister("temp_cap")
    check(
        not registry.has("temp_cap"),
        "S7: CapabilityManager.unregister() removes the capability from the underlying CapabilityRegistry",
    )

    raised = False
    try:
        manager.get("temp_cap")
    except CapabilityRegistryError:
        raised = True
    check(
        raised,
        "S7: getting an unregistered capability after CapabilityManager.unregister() raises CapabilityRegistryError",
    )


# ---------------------------------------------------------------------------
# S8 -- exception propagation (register)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_register() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    manager.register("dup", object())
    raised_type = None
    try:
        manager.register("dup", object())
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is CapabilityRegistryError,
        f"S8: duplicate register() via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )

    raised_type = None
    try:
        manager.register("", object())
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilityRegistryError,
        f"S8: invalid-name register() via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )

    raised_type = None
    try:
        manager.register("none_capability", None)
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilityRegistryError,
        f"S8: None-capability register() via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S9 -- exception propagation (get)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_get() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    raised_type = None
    try:
        manager.get("missing_name")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilityRegistryError,
        f"S9: get() of a missing name via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S10 -- exception propagation (unregister)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_unregister() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    raised_type = None
    try:
        manager.unregister("never_registered")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is CapabilityRegistryError,
        f"S10: unregister() of a missing name via manager raises CapabilityRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S11 -- no wrapping
# ---------------------------------------------------------------------------
def scenario_no_wrapping() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    class _CustomCapability:
        pass

    capability_instance = _CustomCapability()
    manager.register("custom", capability_instance)
    fetched = manager.get("custom")
    check(
        fetched is capability_instance,
        "S11: round-tripping a capability through the manager returns the identical object, no wrapping",
    )
    check(
        type(fetched) is _CustomCapability,
        "S11: the fetched object's type is unchanged -- no wrapper class introduced",
    )


# ---------------------------------------------------------------------------
# S12 -- no business logic (no normalization beyond collaborator's)
# ---------------------------------------------------------------------------
def scenario_no_business_logic() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    manager.register("MixedCase", object())
    check(
        not manager.has("mixedcase"),
        "S12: CapabilityManager performs no case normalization -- 'mixedcase' does not match 'MixedCase'",
    )

    raised = False
    try:
        manager.get("  MixedCase  ")
    except CapabilityRegistryError:
        raised = True
    check(
        raised,
        "S12: CapabilityManager performs no whitespace trimming -- padded name does not resolve",
    )


# ---------------------------------------------------------------------------
# S13 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in dir(CapabilityManager)
        if not name.startswith("_") and callable(getattr(CapabilityManager, name))
    }
    check(
        public_methods == {"register", "get", "has", "list", "unregister"},
        f"S13: CapabilityManager exposes exactly the five specified public methods; got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# S14 -- forbidden methods absent
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
        "resolve",
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
            f"S14: CapabilityManager has no '{method_name}' method",
        )


# ---------------------------------------------------------------------------
# S15 -- AST import verification
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
    }

    unexpected = [mod for mod in imported_modules if mod not in allowed]
    check(
        not unexpected,
        f"S15: Orchestration.capability_manager imports only allowed modules; unexpected={unexpected!r}",
    )
    check(
        "Orchestration.capability_registry" in imported_modules,
        "S15: Orchestration.capability_manager imports Orchestration.capability_registry",
    )
    check(
        "Core.exceptions" in imported_modules,
        "S15: Orchestration.capability_manager imports Core.exceptions",
    )


# ---------------------------------------------------------------------------
# S16 -- namespace verification
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
            f"S16: Orchestration.capability_manager's module namespace contains no {symbol} symbol",
        )


# ---------------------------------------------------------------------------
# S17 -- multiple CapabilityManager independence
# ---------------------------------------------------------------------------
def scenario_multiple_manager_independence() -> None:
    registry_a = _make_registry()
    registry_b = _make_registry()

    manager_a = CapabilityManager(registry_a)
    manager_b = CapabilityManager(registry_b)

    capability_a = object()
    capability_b = object()
    manager_a.register("shared_name", capability_a)
    manager_b.register("shared_name", capability_b)

    check(
        manager_a.get("shared_name") is capability_a,
        "S17: manager_a fetches its own capability under a shared name",
    )
    check(
        manager_b.get("shared_name") is capability_b,
        "S17: manager_b fetches its own (different) capability under the same shared name",
    )
    check(
        manager_a.get("shared_name") is not manager_b.get("shared_name"),
        "S17: two independent CapabilityManager instances never cross-resolve",
    )


# ---------------------------------------------------------------------------
# S18 -- no singleton
# ---------------------------------------------------------------------------
def scenario_no_singleton() -> None:
    registry1 = _make_registry()
    registry2 = _make_registry()

    manager1 = CapabilityManager(registry1)
    manager2 = CapabilityManager(registry2)

    check(
        manager1 is not manager2,
        "S18: repeated CapabilityManager(...) construction yields distinct instances",
    )

    manager1.register("only_in_one", object())
    check(
        not manager2.has("only_in_one"),
        "S18: state registered in one CapabilityManager is not visible in another (no singleton/shared state)",
    )


# ---------------------------------------------------------------------------
# S19 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    instance_attrs = {name for name in vars(manager) if not name.startswith("__")}
    check(
        instance_attrs == {"_capability_registry"},
        f"S19: a CapabilityManager instance holds only '_capability_registry' as state; got {sorted(instance_attrs)!r}",
    )


# ---------------------------------------------------------------------------
# S20 -- zero execution semantics
# ---------------------------------------------------------------------------
def scenario_zero_execution_semantics() -> None:
    registry = _make_registry()
    manager = CapabilityManager(registry)

    calls: List[str] = []

    def _capability_callable() -> str:
        calls.append("called")
        return "should never run"

    manager.register("callable_capability", _capability_callable)
    fetched = manager.get("callable_capability")

    check(
        fetched is _capability_callable,
        "S20: getting a callable capability returns the callable itself, unexecuted",
    )
    check(
        calls == [],
        "S20: CapabilityManager never calls/invokes/executes the capability it registers or gets",
    )


# ---------------------------------------------------------------------------
# S21 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(CapabilityManagerError, AgentError),
        "S21: CapabilityManagerError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(CapabilityManagerError, Exception),
        "S21: CapabilityManagerError (transitively) subclasses Exception",
    )


# ---------------------------------------------------------------------------
# S22 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_stability() -> None:
    err = CapabilityManagerError("boom")
    r1 = repr(err)
    r2 = repr(err)
    check(r1 == r2, "S22: repr(CapabilityManagerError(...)) is stable across repeated calls")
    check(
        "CapabilityManagerError" in r1,
        "S22: repr(CapabilityManagerError(...)) mentions the class name",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_validation,
        scenario_identity_preservation,
        scenario_register_delegation,
        scenario_get_delegation,
        scenario_has_delegation,
        scenario_list_delegation,
        scenario_unregister_delegation,
        scenario_exception_propagation_register,
        scenario_exception_propagation_get,
        scenario_exception_propagation_unregister,
        scenario_no_wrapping,
        scenario_no_business_logic,
        scenario_public_api_exactness,
        scenario_forbidden_methods_absent,
        scenario_ast_import_verification,
        scenario_namespace_verification,
        scenario_multiple_manager_independence,
        scenario_no_singleton,
        scenario_no_hidden_state,
        scenario_zero_execution_semantics,
        scenario_error_hierarchy,
        scenario_repr_stability,
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
    print(f"PHASE 5 SPRINT 64 CAPABILITY MANAGER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())