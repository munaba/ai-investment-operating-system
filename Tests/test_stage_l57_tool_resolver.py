"""
Phase 5 Sprint 57 proof suite -- ``ToolResolver`` (name -> tool
resolution).

Scope: dedicated regression suite for the Sprint 57 addition only --
``Orchestration.tool_resolver.ToolResolver``, a single-method class
that resolves a plain ``tool_name: str`` to a registered tool via
exact ``ToolRegistry`` key match, plus its own ``ToolResolverError``
exception type. This is resolution only: no execution, no routing
engine, no fuzzy/alias/metadata/tag/description-based/scored/
normalized matching, no ``BaseTool`` validation, no Planner
integration, no ``ToolManager``/``ToolExecutor``/``ToolPipeline``, and
no wiring into ``BaseSkill``, ``Executor``, ``WorkflowRuntime``,
``WorkflowEngine``, ``WorkflowExecutionCoordinator``, ``Planner``,
``Memory``, ``Reflection``, ``LearningLoop``, ``AutonomousScheduler``,
or ``EventBus``. ``Orchestration.tool_registry.ToolRegistry`` (Sprint
56, exercised in full by ``Tests/test_stage_l56_tool_registry.py``) is
unchanged by this sprint -- this suite does not re-verify its own
behavior beyond confirming Sprint 57 introduces no regression to it.

Unlike ``Orchestration.skill_resolver.SkillResolver`` (Sprint 44,
which resolves a ``Task`` via ``task.name``), ``ToolResolver`` takes a
plain ``tool_name: str`` directly -- there is no ``Task`` dependency
anywhere in this module.

``ToolResolver`` never imports, constructs, or references ``BaseTool``,
``BaseSkill``, ``Executor``, ``Workflow``/``WorkflowEngine``/
``WorkflowRuntime``/``WorkflowExecutionCoordinator``, ``Planner``,
``Memory``, ``Reflection``, ``LearningLoop``, ``AutonomousScheduler``,
or ``EventBus`` (proven both by module-namespace inspection and by
AST-level import inspection of the module's own source file).
``Orchestration.tool_resolver`` imports only
``Core.exceptions.AgentError``,
``Orchestration.tool_registry.ToolRegistry``, and the stdlib
``typing`` module.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites (mirroring
``Tests.test_stage_l44_skill_resolver`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- constructor validation: ToolResolver(None) and
           ToolResolver(<non-registry>) both raise
           ToolResolverError; ToolResolver(ToolRegistry()) succeeds.
    S2  -- resolve success: resolve(tool_name) returns the tool
           registered under that exact name.
    S3  -- resolve returns identical object (identity preservation):
           the returned object is the exact same instance that was
           registered, never a copy or wrapper.
    S4  -- multiple tools: distinct names resolve to their own
           distinct, correctly matched tools out of a registry
           holding several.
    S5  -- multi-instance independence: two ToolResolver instances
           built over two independent ToolRegistry instances never
           cross-resolve into each other's tools.
    S6  -- missing tool propagation: resolve(name) for a name not in
           the registry raises ToolRegistryError (not
           ToolResolverError), unmodified/unwrapped from
           ToolRegistry.get() -- never wrapped or converted.
    S7  -- invalid tool_name (non-str): resolve(<non-str>) raises
           ToolResolverError for a variety of non-str objects,
           including None.
    S8  -- empty/whitespace-only tool_name: resolve("") and
           resolve("   ") both raise ToolResolverError.
    S9  -- whitespace sensitivity: a registered name with surrounding
           whitespace does not match the trimmed (or padded) lookup
           key -- exact string match only, no stripping performed by
           ToolResolver itself.
    S10 -- case sensitivity: a name differing only by case does not
           resolve -- it raises ToolRegistryError exactly like any
           other miss (no case-insensitive/fuzzy matching).
    S11 -- opaque tool objects: any non-None Python object (str,
           dict, custom class instance) registered under a name is
           returned exactly as-is by resolve(), with no
           inspection/validation of its shape.
    S12 -- insertion order irrelevant: registering tools in a
           different order does not change which tool a given
           tool_name resolves to.
    S13 -- identity preservation of the registry itself: ToolResolver
           stores the exact ToolRegistry instance passed in (no
           copying) -- mutating the original registry after
           construction (e.g. registering a new tool) is reflected in
           subsequent resolve() calls.
    S14 -- no execution semantics: resolve() never calls, invokes, or
           executes the object it returns -- resolving a callable
           object returns the callable itself, unexecuted.
    S15 -- public API exactness: resolve() is the *only* public
           (non-dunder) method exposed by ToolResolver -- no execute/
           invoke/dispatch/call method exists.
    S16 -- forbidden imports: Orchestration.tool_resolver's own source
           file imports only Core.exceptions, Orchestration.tool_registry,
           and typing (AST-level import inspection) -- no BaseTool/
           BaseSkill/Executor/Workflow*/Planner/Memory/Reflection/
           LearningLoop/Scheduler/EventBus import anywhere in the file.
    S17 -- repr stability: repr() of a ToolResolverError is stable
           across repeated calls and mentions the class name.
    S18 -- error hierarchy: ToolResolverError subclasses
           Core.exceptions.AgentError, which subclasses Exception.
    S19 -- no planner knowledge: Orchestration.tool_resolver's module
           namespace contains no Planner symbol.
    S20 -- no workflow knowledge: Orchestration.tool_resolver's module
           namespace contains no Workflow/WorkflowEngine/
           WorkflowRuntime/WorkflowExecutionCoordinator symbol.
    S21 -- no runtime knowledge: Orchestration.tool_resolver's module
           namespace contains no Executor symbol, and a ToolResolver
           instance is never given (and exposes no attribute holding)
           an Executor-shaped object.
    S22 -- no scheduler/EventBus knowledge: Orchestration.tool_resolver's
           module namespace contains no AutonomousScheduler/Scheduler/
           EventBus symbol; a ToolResolver instance exposes no
           publish/subscribe/attach-shaped method.
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
# S1 -- constructor validation
# ---------------------------------------------------------------------------
def scenario_constructor_validation() -> None:
    for value in (None, "not-a-registry", 123, object(), {}, []):
        raised = False
        try:
            ToolResolver(value)  # type: ignore[arg-type]
        except ToolResolverError:
            raised = True
        check(
            raised,
            f"S1: ToolResolver({value!r}) raises ToolResolverError",
        )

    resolver = ToolResolver(ToolRegistry())
    check(
        isinstance(resolver, ToolResolver),
        "S1: ToolResolver(ToolRegistry()) constructs successfully",
    )


# ---------------------------------------------------------------------------
# S2 -- resolve success
# ---------------------------------------------------------------------------
def scenario_resolve_success() -> None:
    registry = ToolRegistry()
    tool = object()
    registry.register("yahoo_finance_tool", tool)
    resolver = ToolResolver(registry)
    check(
        resolver.resolve("yahoo_finance_tool") is tool,
        "S2: resolve() returns the tool registered under the exact name",
    )


# ---------------------------------------------------------------------------
# S3 -- resolve returns identical object
# ---------------------------------------------------------------------------
def scenario_resolve_returns_identical_object() -> None:
    registry = ToolRegistry()

    class _CustomTool:
        pass

    tool_instance = _CustomTool()
    registry.register("x", tool_instance)
    resolver = ToolResolver(registry)
    check(
        resolver.resolve("x") is tool_instance,
        "S3: resolve() returns the identical object (never a copy or wrapper)",
    )


# ---------------------------------------------------------------------------
# S4 -- multiple tools
# ---------------------------------------------------------------------------
def scenario_multiple_tools() -> None:
    registry = ToolRegistry()
    tool_a = object()
    tool_b = object()
    tool_c = object()
    registry.register("tool_a", tool_a)
    registry.register("tool_b", tool_b)
    registry.register("tool_c", tool_c)
    resolver = ToolResolver(registry)

    check(resolver.resolve("tool_a") is tool_a, "S4: resolve('tool_a') matches tool_a")
    check(resolver.resolve("tool_b") is tool_b, "S4: resolve('tool_b') matches tool_b")
    check(resolver.resolve("tool_c") is tool_c, "S4: resolve('tool_c') matches tool_c")


# ---------------------------------------------------------------------------
# S5 -- multi-instance independence
# ---------------------------------------------------------------------------
def scenario_multi_instance_independence() -> None:
    registry_a = ToolRegistry()
    registry_b = ToolRegistry()
    tool_a = object()
    tool_b = object()
    registry_a.register("x", tool_a)
    registry_b.register("x", tool_b)

    resolver_a = ToolResolver(registry_a)
    resolver_b = ToolResolver(registry_b)

    check(resolver_a.resolve("x") is tool_a, "S5: resolver_a resolves its own registry's tool")
    check(resolver_b.resolve("x") is tool_b, "S5: resolver_b resolves its own registry's tool")
    check(
        resolver_a.resolve("x") is not resolver_b.resolve("x"),
        "S5: two resolvers over independent registries never cross-resolve",
    )


# ---------------------------------------------------------------------------
# S6 -- missing tool propagation
# ---------------------------------------------------------------------------
def scenario_missing_tool_propagation() -> None:
    registry = ToolRegistry()
    resolver = ToolResolver(registry)

    raised_registry_error = False
    raised_resolver_error = False
    try:
        resolver.resolve("does_not_exist")
    except ToolRegistryError:
        raised_registry_error = True
    except ToolResolverError:
        raised_resolver_error = True

    check(
        raised_registry_error,
        "S6: resolve() for a missing name raises ToolRegistryError (propagated, unwrapped)",
    )
    check(
        not raised_resolver_error,
        "S6: resolve() for a missing name does NOT raise ToolResolverError",
    )


# ---------------------------------------------------------------------------
# S7 -- invalid tool_name (non-str)
# ---------------------------------------------------------------------------
def scenario_invalid_tool_name_rejected() -> None:
    registry = ToolRegistry()
    resolver = ToolResolver(registry)

    for value in (None, 123, ["a"], {"k": "v"}, object()):
        raised = False
        try:
            resolver.resolve(value)  # type: ignore[arg-type]
        except ToolResolverError:
            raised = True
        check(
            raised,
            f"S7: resolve({value!r}) (not a str) raises ToolResolverError",
        )


# ---------------------------------------------------------------------------
# S8 -- empty / whitespace-only tool_name
# ---------------------------------------------------------------------------
def scenario_empty_and_whitespace_tool_name_rejected() -> None:
    registry = ToolRegistry()
    resolver = ToolResolver(registry)

    for value in ("", "   ", "\t", "\n"):
        raised = False
        try:
            resolver.resolve(value)
        except ToolResolverError:
            raised = True
        check(
            raised,
            f"S8: resolve({value!r}) (empty/whitespace-only) raises ToolResolverError",
        )


# ---------------------------------------------------------------------------
# S9 -- whitespace sensitivity
# ---------------------------------------------------------------------------
def scenario_whitespace_sensitivity() -> None:
    registry = ToolRegistry()
    tool = object()
    registry.register(" padded_tool ", tool)
    resolver = ToolResolver(registry)

    check(
        resolver.resolve(" padded_tool ") is tool,
        "S9: resolve() matches the exact registered name including surrounding whitespace",
    )

    raised = False
    try:
        resolver.resolve("padded_tool")
    except ToolRegistryError:
        raised = True
    check(
        raised,
        "S9: resolve() with the trimmed name does not match a padded registered name (no stripping)",
    )


# ---------------------------------------------------------------------------
# S10 -- case sensitivity
# ---------------------------------------------------------------------------
def scenario_case_sensitivity() -> None:
    registry = ToolRegistry()
    tool = object()
    registry.register("MarketTool", tool)
    resolver = ToolResolver(registry)

    check(
        resolver.resolve("MarketTool") is tool,
        "S10: resolve() matches the exact case of the registered name",
    )

    raised = False
    try:
        resolver.resolve("markettool")
    except ToolRegistryError:
        raised = True
    check(
        raised,
        "S10: resolve() with a different case raises ToolRegistryError (no case-insensitive matching)",
    )


# ---------------------------------------------------------------------------
# S11 -- opaque tool objects
# ---------------------------------------------------------------------------
def scenario_opaque_tool_objects() -> None:
    registry = ToolRegistry()

    class _AnythingAtAll:
        pass

    candidates = ["a-string-tool", {"dict": "tool"}, 12345, _AnythingAtAll(), [1, 2, 3]]
    resolver = ToolResolver(registry)
    for index, candidate in enumerate(candidates):
        name = f"tool_{index}"
        registry.register(name, candidate)
        check(
            resolver.resolve(name) is candidate,
            f"S11: resolve() returns opaque tool {candidate!r} exactly, with no shape inspection",
        )


# ---------------------------------------------------------------------------
# S12 -- insertion order irrelevant
# ---------------------------------------------------------------------------
def scenario_insertion_order_irrelevant() -> None:
    registry_1 = ToolRegistry()
    tool_x = object()
    tool_y = object()
    registry_1.register("x", tool_x)
    registry_1.register("y", tool_y)

    registry_2 = ToolRegistry()
    registry_2.register("y", tool_y)
    registry_2.register("x", tool_x)

    resolver_1 = ToolResolver(registry_1)
    resolver_2 = ToolResolver(registry_2)

    check(
        resolver_1.resolve("x") is tool_x and resolver_2.resolve("x") is tool_x,
        "S12: insertion order does not affect which tool a given name resolves to",
    )
    check(
        resolver_1.resolve("y") is tool_y and resolver_2.resolve("y") is tool_y,
        "S12: insertion order does not affect which tool a given name resolves to (second name)",
    )


# ---------------------------------------------------------------------------
# S13 -- registry stored by identity, mutation reflected
# ---------------------------------------------------------------------------
def scenario_registry_stored_by_identity() -> None:
    registry = ToolRegistry()
    resolver = ToolResolver(registry)

    raised = False
    try:
        resolver.resolve("late_tool")
    except ToolRegistryError:
        raised = True
    check(raised, "S13: resolve() before registration raises ToolRegistryError")

    late_tool = object()
    registry.register("late_tool", late_tool)
    check(
        resolver.resolve("late_tool") is late_tool,
        "S13: ToolResolver holds the registry by identity -- registering after construction is reflected",
    )


# ---------------------------------------------------------------------------
# S14 -- no execution semantics
# ---------------------------------------------------------------------------
def scenario_no_execution_semantics() -> None:
    registry = ToolRegistry()
    calls: List[str] = []

    def _callable_tool():
        calls.append("executed")
        return "should-not-run"

    registry.register("callable_tool", _callable_tool)
    resolver = ToolResolver(registry)

    resolved = resolver.resolve("callable_tool")
    check(
        resolved is _callable_tool,
        "S14: resolve() returns the callable object itself, unexecuted",
    )
    check(
        calls == [],
        "S14: resolve() never calls/invokes/executes the resolved object",
    )


# ---------------------------------------------------------------------------
# S15 -- public API exactness
# ---------------------------------------------------------------------------
def scenario_public_api_exactness() -> None:
    public_methods = {
        name
        for name in vars(ToolResolver)
        if not name.startswith("_") and callable(getattr(ToolResolver, name))
    }
    check(
        public_methods == {"resolve"},
        f"S15: ToolResolver exposes exactly {{'resolve'}}; got {sorted(public_methods)!r}",
    )

    forbidden = ["execute", "invoke", "dispatch", "call", "run"]
    for name in forbidden:
        check(
            not hasattr(ToolResolver, name),
            f"S15: ToolResolver has no '{name}' method",
        )


# ---------------------------------------------------------------------------
# S16 -- AST import verification
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
    import Orchestration.tool_resolver as tool_resolver_module

    source = Path(tool_resolver_module.__file__).read_text(encoding="utf-8")
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"typing", "Core", "Orchestration", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}
    check(
        unexpected_roots == set(),
        f"S16: Orchestration/tool_resolver.py's imports (AST-verified) are "
        f"limited to typing/Core.exceptions/Orchestration.tool_registry; "
        f"unexpected roots: {sorted(unexpected_roots)!r}",
    )

    tree = ast.parse(source)
    orchestration_from_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "Orchestration.tool_registry"
    ]
    check(
        len(orchestration_from_imports) == 1
        and any(alias.name == "ToolRegistry" for alias in orchestration_from_imports[0].names),
        "S16: the only 'Orchestration' import is 'from Orchestration.tool_registry import ToolRegistry'",
    )

    core_from_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "Core.exceptions"
    ]
    check(
        len(core_from_imports) == 1
        and any(alias.name == "AgentError" for alias in core_from_imports[0].names),
        "S16: the only 'Core' import is 'from Core.exceptions import AgentError'",
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
        "BaseSkill",
        "Task",
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
            f"S16: Orchestration/tool_resolver.py's AST-parsed import names do not include '{symbol}'",
        )


# ---------------------------------------------------------------------------
# S17 -- repr stability
# ---------------------------------------------------------------------------
def scenario_repr_stability() -> None:
    error = ToolResolverError("something went wrong")
    first_repr = repr(error)
    second_repr = repr(error)
    check(first_repr == second_repr, "S17: repr(ToolResolverError) is stable across repeated calls")
    check("ToolResolverError" in first_repr, "S17: repr(ToolResolverError) mentions the class name")


# ---------------------------------------------------------------------------
# S18 -- error hierarchy
# ---------------------------------------------------------------------------
def scenario_error_hierarchy() -> None:
    check(
        issubclass(ToolResolverError, AgentError),
        "S18: ToolResolverError subclasses Core.exceptions.AgentError",
    )
    check(
        issubclass(AgentError, Exception),
        "S18: Core.exceptions.AgentError subclasses Exception",
    )


# ---------------------------------------------------------------------------
# S19 -- no planner knowledge
# ---------------------------------------------------------------------------
def scenario_no_planner_knowledge() -> None:
    import Orchestration.tool_resolver as tool_resolver_module

    check(
        not hasattr(tool_resolver_module, "Planner"),
        "S19: Orchestration.tool_resolver's module namespace contains no Planner symbol",
    )


# ---------------------------------------------------------------------------
# S20 -- no workflow knowledge
# ---------------------------------------------------------------------------
def scenario_no_workflow_knowledge() -> None:
    import Orchestration.tool_resolver as tool_resolver_module

    for symbol in ("Workflow", "WorkflowEngine", "WorkflowRuntime", "WorkflowExecutionCoordinator"):
        check(
            not hasattr(tool_resolver_module, symbol),
            f"S20: Orchestration.tool_resolver's module namespace contains no {symbol} symbol",
        )


# ---------------------------------------------------------------------------
# S21 -- no runtime knowledge
# ---------------------------------------------------------------------------
def scenario_no_runtime_knowledge() -> None:
    import Orchestration.tool_resolver as tool_resolver_module

    check(
        not hasattr(tool_resolver_module, "Executor"),
        "S21: Orchestration.tool_resolver's module namespace contains no Executor symbol",
    )

    registry = ToolRegistry()
    resolver = ToolResolver(registry)
    instance_attrs = {
        name for name in vars(resolver) if not name.startswith("__")
    }
    check(
        instance_attrs == {"_tool_registry"},
        f"S21: a ToolResolver instance holds only '_tool_registry' as state; got {sorted(instance_attrs)!r}",
    )


# ---------------------------------------------------------------------------
# S22 -- no scheduler/EventBus knowledge
# ---------------------------------------------------------------------------
def scenario_no_scheduler_or_eventbus_knowledge() -> None:
    import Orchestration.tool_resolver as tool_resolver_module

    for symbol in ("AutonomousScheduler", "Scheduler", "EventBus"):
        check(
            not hasattr(tool_resolver_module, symbol),
            f"S22: Orchestration.tool_resolver's module namespace contains no {symbol} symbol",
        )

    for method_name in ("publish", "subscribe", "attach"):
        check(
            not hasattr(ToolResolver, method_name),
            f"S22: ToolResolver has no '{method_name}' method",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_constructor_validation,
        scenario_resolve_success,
        scenario_resolve_returns_identical_object,
        scenario_multiple_tools,
        scenario_multi_instance_independence,
        scenario_missing_tool_propagation,
        scenario_invalid_tool_name_rejected,
        scenario_empty_and_whitespace_tool_name_rejected,
        scenario_whitespace_sensitivity,
        scenario_case_sensitivity,
        scenario_opaque_tool_objects,
        scenario_insertion_order_irrelevant,
        scenario_registry_stored_by_identity,
        scenario_no_execution_semantics,
        scenario_public_api_exactness,
        scenario_ast_import_verification,
        scenario_repr_stability,
        scenario_error_hierarchy,
        scenario_no_planner_knowledge,
        scenario_no_workflow_knowledge,
        scenario_no_runtime_knowledge,
        scenario_no_scheduler_or_eventbus_knowledge,
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
    print(f"PHASE 5 SPRINT 57 TOOL RESOLVER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())