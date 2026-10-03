"""
Phase 5 Sprint 59 proof suite -- ``ToolManager`` (facade over
``ToolRegistry`` + ``ToolResolver``).

Scope: dedicated regression suite for the Sprint 59 addition only --
``Orchestration.tool_manager.ToolManager``, a five-method facade that
delegates directly to an injected ``ToolRegistry`` and ``ToolResolver``,
plus its own ``ToolManagerError`` exception type. This is a facade
only: no execution, no caching, no invocation, no dispatch, no
routing, no planner logic, no runtime logic, no workflow logic, no
event publishing, no memory, no reflection, no learning, no
capability matching, no metadata lookup, no alias lookup, no
normalization, no fuzzy matching, no auto registration, and no
singleton. ``Orchestration.tool_registry.ToolRegistry`` (Sprint 56)
and ``Orchestration.tool_resolver.ToolResolver`` (Sprint 57) are
unchanged by this sprint -- this suite does not re-verify their own
internal behavior beyond confirming Sprint 59 introduces no
regression to it.

``ToolManager`` never imports, constructs, or references ``BaseTool``,
``BaseSkill``, ``SkillRegistry``, ``SkillResolver``, ``Planner``,
``Executor``, ``Workflow``/``WorkflowEngine``/``WorkflowRuntime``/
``WorkflowExecutionCoordinator``, ``Memory``, ``Reflection``,
``LearningLoop``, ``EventBus``, ``Services``, ``Repositories``,
``Providers``, ``Database``, or ``Core.composition_root`` (proven both
by module-namespace inspection and by AST-level import inspection of
the module's own source file). ``Orchestration.tool_manager`` imports
only ``Core.exceptions.AgentError``,
``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_resolver.ToolResolver``, and the stdlib
``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites (mirroring
``Tests.test_stage_l57_tool_resolver`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- constructor validation: ToolManager(<bad>, <bad>) raises
           ToolManagerError for every combination of an invalid
           tool_registry and/or tool_resolver; a valid pair
           constructs successfully.
    S2  -- identity preservation: the exact ToolRegistry and
           ToolResolver instances passed in are stored by identity --
           never copied, never rebuilt (verified indirectly via
           cross-mutation visibility, since ToolManager exposes no
           public accessor for its collaborators).
    S3  -- register() delegation: ToolManager.register(name, tool)
           stores the tool in the underlying ToolRegistry, visible via
           registry.get()/registry.has() directly.
    S4  -- resolve() delegation: ToolManager.resolve(name) returns the
           exact same object ToolResolver.resolve(name) would return.
    S5  -- has() delegation: ToolManager.has(name) matches
           ToolRegistry.has(name) exactly, both before and after
           registration.
    S6  -- list() delegation: ToolManager.list() matches
           ToolRegistry.list() exactly, including insertion order.
    S7  -- unregister() delegation: ToolManager.unregister(name)
           removes the tool from the underlying ToolRegistry -- a
           subsequent has()/resolve() reflects the removal.
    S8  -- exception propagation (register): a duplicate/invalid
           register() call raises ToolRegistryError unmodified, not
           ToolManagerError.
    S9  -- exception propagation (resolve): resolve() of a missing
           name raises ToolRegistryError unmodified (via
           ToolResolver), not ToolManagerError; an invalid tool_name
           raises ToolResolverError unmodified, not ToolManagerError.
    S10 -- exception propagation (unregister): unregister() of a
           missing name raises ToolRegistryError unmodified, not
           ToolManagerError.
    S11 -- no wrapping: registering a tool through the manager and
           resolving it back returns the identical object (no copy,
           no wrapper class introduced by ToolManager).
    S12 -- no business logic: ToolManager performs no normalization
           (case/whitespace) beyond what ToolRegistry/ToolResolver
           themselves already do.
    S13 -- public API exactness: exactly five public (non-dunder)
           methods exist on ToolManager -- register, resolve, has,
           list, unregister -- nothing else.
    S14 -- forbidden methods absent: no execute/run/invoke/dispatch/
           call/plan/route method exists on ToolManager.
    S15 -- AST import verification: Orchestration.tool_manager's own
           source file imports only Core.exceptions,
           Orchestration.tool_registry, Orchestration.tool_resolver,
           and typing -- no forbidden import anywhere in the file.
    S16 -- namespace verification: Orchestration.tool_manager's module
           namespace contains no BaseTool/BaseSkill/SkillRegistry/
           SkillResolver/Planner/Executor/Workflow*/Memory/Reflection/
           LearningLoop/EventBus/Services/Repositories/Providers/
           Database/CompositionRoot symbol.
    S17 -- multiple ToolManager independence: two ToolManager
           instances built over two independent ToolRegistry/
           ToolResolver pairs never cross-resolve into each other's
           tools.
    S18 -- no singleton: repeated ToolManager(...) construction with
           fresh collaborators yields distinct instances holding
           distinct state.
    S19 -- no hidden state: a ToolManager instance holds only
           '_tool_registry' and '_tool_resolver' as instance
           attributes.
    S20 -- zero execution semantics: registering a callable object and
           resolving it back returns the callable itself, unexecuted
           -- ToolManager never calls, invokes, or executes anything
           it manages.
    S21 -- error hierarchy: ToolManagerError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    S22 -- repr stability: repr() of a ToolManagerError is stable
           across repeated calls and mentions the class name.
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
from Orchestration.tool_resolver import ToolResolver, ToolResolverError
from Orchestration.tool_manager import ToolManager, ToolManagerError

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


def _make_pair():
    """Return a fresh (ToolRegistry, ToolResolver) pair."""
    registry = ToolRegistry()
    resolver = ToolResolver(registry)
    return registry, resolver


# ---------------------------------------------------------------------------
# S1 -- constructor validation
# ---------------------------------------------------------------------------
def scenario_constructor_validation() -> None:
    registry, resolver = _make_pair()
    bad_values = (None, "not-a-registry", 123, object(), {}, [])

    for value in bad_values:
        raised = False
        try:
            ToolManager(value, resolver)  # type: ignore[arg-type]
        except ToolManagerError:
            raised = True
        check(
            raised,
            f"S1: ToolManager({value!r}, <resolver>) raises ToolManagerError",
        )

    for value in bad_values:
        raised = False
        try:
            ToolManager(registry, value)  # type: ignore[arg-type]
        except ToolManagerError:
            raised = True
        check(
            raised,
            f"S1: ToolManager(<registry>, {value!r}) raises ToolManagerError",
        )

    raised = False
    try:
        ToolManager(None, None)  # type: ignore[arg-type]
    except ToolManagerError:
        raised = True
    check(raised, "S1: ToolManager(None, None) raises ToolManagerError")

    manager = ToolManager(registry, resolver)
    check(
        isinstance(manager, ToolManager),
        "S1: ToolManager(ToolRegistry(), ToolResolver(...)) constructs successfully",
    )

    # cross-wired: a resolver bound to a *different* registry than the one
    # passed as tool_registry is still a structurally valid construction
    # (ToolManager performs no cross-consistency check between the two).
    other_registry = ToolRegistry()
    manager2 = ToolManager(other_registry, resolver)
    check(
        isinstance(manager2, ToolManager),
        "S1: ToolManager accepts a registry/resolver pair without cross-checking consistency",
    )


# ---------------------------------------------------------------------------
# S2 -- identity preservation
# ---------------------------------------------------------------------------
def scenario_identity_preservation() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    tool = object()
    manager.register("alpha", tool)
    check(
        registry.get("alpha") is tool,
        "S2: registering via the manager mutates the exact injected ToolRegistry instance",
    )

    registry.register("beta", "direct")
    check(
        manager.resolve("beta") == "direct",
        "S2: mutating the injected ToolRegistry directly is visible through the manager (no copy)",
    )


# ---------------------------------------------------------------------------
# S3 -- register() delegation
# ---------------------------------------------------------------------------
def scenario_register_delegation() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    tool = object()
    manager.register("yahoo_finance_tool", tool)
    check(
        registry.get("yahoo_finance_tool") is tool,
        "S3: ToolManager.register() stores the tool in the underlying ToolRegistry",
    )
    check(
        registry.has("yahoo_finance_tool"),
        "S3: ToolManager.register() result is visible via ToolRegistry.has() directly",
    )


# ---------------------------------------------------------------------------
# S4 -- resolve() delegation
# ---------------------------------------------------------------------------
def scenario_resolve_delegation() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    tool = object()
    registry.register("news_tool", tool)
    check(
        manager.resolve("news_tool") is resolver.resolve("news_tool"),
        "S4: ToolManager.resolve() returns the exact same object ToolResolver.resolve() returns",
    )
    check(
        manager.resolve("news_tool") is tool,
        "S4: ToolManager.resolve() returns the exact registered object",
    )


# ---------------------------------------------------------------------------
# S5 -- has() delegation
# ---------------------------------------------------------------------------
def scenario_has_delegation() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    check(
        manager.has("nope") == registry.has("nope"),
        "S5: ToolManager.has() matches ToolRegistry.has() before registration",
    )

    registry.register("nope", object())
    check(
        manager.has("nope") == registry.has("nope") == True,
        "S5: ToolManager.has() matches ToolRegistry.has() after registration",
    )


# ---------------------------------------------------------------------------
# S6 -- list() delegation
# ---------------------------------------------------------------------------
def scenario_list_delegation() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    for name in ("z_tool", "a_tool", "m_tool"):
        registry.register(name, object())

    check(
        manager.list() == registry.list(),
        "S6: ToolManager.list() matches ToolRegistry.list() exactly",
    )
    check(
        manager.list() == ("z_tool", "a_tool", "m_tool"),
        "S6: ToolManager.list() preserves insertion order",
    )


# ---------------------------------------------------------------------------
# S7 -- unregister() delegation
# ---------------------------------------------------------------------------
def scenario_unregister_delegation() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    registry.register("temp_tool", object())
    manager.unregister("temp_tool")
    check(
        not registry.has("temp_tool"),
        "S7: ToolManager.unregister() removes the tool from the underlying ToolRegistry",
    )

    raised = False
    try:
        manager.resolve("temp_tool")
    except ToolRegistryError:
        raised = True
    check(
        raised,
        "S7: resolving an unregistered tool after ToolManager.unregister() raises ToolRegistryError",
    )


# ---------------------------------------------------------------------------
# S8 -- exception propagation (register)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_register() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    manager.register("dup", object())
    raised_type = None
    try:
        manager.register("dup", object())
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is ToolRegistryError,
        f"S8: duplicate register() via manager raises ToolRegistryError unmodified; got {raised_type!r}",
    )

    raised_type = None
    try:
        manager.register("", object())
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is ToolRegistryError,
        f"S8: invalid-name register() via manager raises ToolRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S9 -- exception propagation (resolve)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_resolve() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    raised_type = None
    try:
        manager.resolve("missing_name")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is ToolRegistryError,
        f"S9: resolve() of a missing name via manager raises ToolRegistryError unmodified; got {raised_type!r}",
    )

    raised_type = None
    try:
        manager.resolve("")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is ToolResolverError,
        f"S9: resolve('') via manager raises ToolResolverError unmodified; got {raised_type!r}",
    )

    raised_type = None
    try:
        manager.resolve(None)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is ToolResolverError,
        f"S9: resolve(None) via manager raises ToolResolverError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S10 -- exception propagation (unregister)
# ---------------------------------------------------------------------------
def scenario_exception_propagation_unregister() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    raised_type = None
    try:
        manager.unregister("never_registered")
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)
    check(
        raised_type is ToolRegistryError,
        f"S10: unregister() of a missing name via manager raises ToolRegistryError unmodified; got {raised_type!r}",
    )


# ---------------------------------------------------------------------------
# S11 -- no wrapping
# ---------------------------------------------------------------------------
def scenario_no_wrapping() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    class _CustomTool:
        pass

    tool_instance = _CustomTool()
    manager.register("custom", tool_instance)
    resolved = manager.resolve("custom")
    check(
        resolved is tool_instance,
        "S11: round-tripping a tool through the manager returns the identical object, no wrapping",
    )
    check(
        type(resolved) is _CustomTool,
        "S11: the resolved object's type is unchanged -- no wrapper class introduced",
    )


# ---------------------------------------------------------------------------
# S12 -- no business logic (no normalization beyond collaborators')
# ---------------------------------------------------------------------------
def scenario_no_business_logic() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    manager.register("MixedCase", object())
    check(
        not manager.has("mixedcase"),
        "S12: ToolManager performs no case normalization -- 'mixedcase' does not match 'MixedCase'",
    )

    raised = False
    try:
        manager.resolve("  MixedCase  ")
    except ToolRegistryError:
        raised = True
    check(
        raised,
        "S12: ToolManager performs no whitespace trimming -- padded name does not resolve",
    )


# ---------------------------------------------------------------------------
# S13 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in dir(ToolManager)
        if not name.startswith("_") and callable(getattr(ToolManager, name))
    }
    check(
        public_methods == {"register", "resolve", "has", "list", "unregister"},
        f"S13: ToolManager exposes exactly the five specified public methods; got {sorted(public_methods)!r}",
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
        "cache",
        "publish",
        "subscribe",
        "remember",
        "reflect",
        "learn",
    )
    for method_name in forbidden:
        check(
            not hasattr(ToolManager, method_name),
            f"S14: ToolManager has no '{method_name}' method",
        )


# ---------------------------------------------------------------------------
# S15 -- AST import verification
# ---------------------------------------------------------------------------
def scenario_ast_import_verification() -> None:
    source_path = ROOT / "Orchestration" / "tool_manager.py"
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
        "Orchestration.tool_registry",
        "Orchestration.tool_resolver",
    }

    unexpected = [mod for mod in imported_modules if mod not in allowed]
    check(
        not unexpected,
        f"S15: Orchestration.tool_manager imports only allowed modules; unexpected={unexpected!r}",
    )
    check(
        "Orchestration.tool_registry" in imported_modules,
        "S15: Orchestration.tool_manager imports Orchestration.tool_registry",
    )
    check(
        "Orchestration.tool_resolver" in imported_modules,
        "S15: Orchestration.tool_manager imports Orchestration.tool_resolver",
    )
    check(
        "Core.exceptions" in imported_modules,
        "S15: Orchestration.tool_manager imports Core.exceptions",
    )


# ---------------------------------------------------------------------------
# S16 -- namespace verification
# ---------------------------------------------------------------------------
def scenario_namespace_verification() -> None:
    import Orchestration.tool_manager as tool_manager_module

    forbidden_symbols = (
        "BaseTool",
        "BaseSkill",
        "SkillRegistry",
        "SkillResolver",
        "Planner",
        "Executor",
        "Workflow",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "Services",
        "Repositories",
        "Providers",
        "Database",
        "CompositionRoot",
    )
    for symbol in forbidden_symbols:
        check(
            not hasattr(tool_manager_module, symbol),
            f"S16: Orchestration.tool_manager's module namespace contains no {symbol} symbol",
        )


# ---------------------------------------------------------------------------
# S17 -- multiple ToolManager independence
# ---------------------------------------------------------------------------
def scenario_multiple_manager_independence() -> None:
    registry_a, resolver_a = _make_pair()
    registry_b, resolver_b = _make_pair()

    manager_a = ToolManager(registry_a, resolver_a)
    manager_b = ToolManager(registry_b, resolver_b)

    tool_a = object()
    tool_b = object()
    manager_a.register("shared_name", tool_a)
    manager_b.register("shared_name", tool_b)

    check(
        manager_a.resolve("shared_name") is tool_a,
        "S17: manager_a resolves its own tool under a shared name",
    )
    check(
        manager_b.resolve("shared_name") is tool_b,
        "S17: manager_b resolves its own (different) tool under the same shared name",
    )
    check(
        manager_a.resolve("shared_name") is not manager_b.resolve("shared_name"),
        "S17: two independent ToolManager instances never cross-resolve",
    )


# ---------------------------------------------------------------------------
# S18 -- no singleton
# ---------------------------------------------------------------------------
def scenario_no_singleton() -> None:
    registry1, resolver1 = _make_pair()
    registry2, resolver2 = _make_pair()

    manager1 = ToolManager(registry1, resolver1)
    manager2 = ToolManager(registry2, resolver2)

    check(
        manager1 is not manager2,
        "S18: repeated ToolManager(...) construction yields distinct instances",
    )

    manager1.register("only_in_one", object())
    check(
        not manager2.has("only_in_one"),
        "S18: state registered in one ToolManager is not visible in another (no singleton/shared state)",
    )


# ---------------------------------------------------------------------------
# S19 -- no hidden state
# ---------------------------------------------------------------------------
def scenario_no_hidden_state() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    instance_attrs = {name for name in vars(manager) if not name.startswith("__")}
    check(
        instance_attrs == {"_tool_registry", "_tool_resolver"},
        f"S19: a ToolManager instance holds only '_tool_registry' and '_tool_resolver' as state; got {sorted(instance_attrs)!r}",
    )


# ---------------------------------------------------------------------------
# S20 -- zero execution semantics
# ---------------------------------------------------------------------------
def scenario_zero_execution_semantics() -> None:
    registry, resolver = _make_pair()
    manager = ToolManager(registry, resolver)

    calls: List[str] = []

    def _tool_callable() -> str:
        calls.append("called")
        return "should never run"

    manager.register("callable_tool", _tool_callable)
    resolved = manager.resolve("callable_tool")

    check(
        resolved is _tool_callable,
        "S20: resolving a callable tool returns the callable itself, unexecuted",
    )
    check(
        calls == [],
        "S20: ToolManager never calls/invokes/executes the tool it registers or resolves",
    )


# ---------------------------------------------------------------------------
# S21 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(ToolManagerError, AgentError),
        "S21: ToolManagerError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(ToolManagerError, Exception),
        "S21: ToolManagerError (transitively) subclasses Exception",
    )


# ---------------------------------------------------------------------------
# S22 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_stability() -> None:
    err = ToolManagerError("boom")
    r1 = repr(err)
    r2 = repr(err)
    check(r1 == r2, "S22: repr(ToolManagerError(...)) is stable across repeated calls")
    check(
        "ToolManagerError" in r1,
        "S22: repr(ToolManagerError(...)) mentions the class name",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_validation,
        scenario_identity_preservation,
        scenario_register_delegation,
        scenario_resolve_delegation,
        scenario_has_delegation,
        scenario_list_delegation,
        scenario_unregister_delegation,
        scenario_exception_propagation_register,
        scenario_exception_propagation_resolve,
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
    print(f"PHASE 5 SPRINT 59 TOOL MANAGER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())