"""
Phase 5 Sprint 53 proof suite -- the ``Capability`` value object.

Scope: dedicated regression suite for
``Orchestration.capability.Capability``/``CapabilityError`` only.
Nothing else exists in this module to test -- no registration, no
discovery, no serialization, no helper/convenience methods.
``Orchestration.base_skill.BaseSkill``, ``Orchestration.base_tool.
BaseTool``, ``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``, ``Agents.planner.
Planner``, and ``Orchestration.executor.Executor`` are all untouched
by this sprint and are not exercised here -- nothing about this
sprint wires ``Capability`` into any of them.

``Capability`` is a pure, minimal, frozen ``dataclass`` value object:
exactly four fields (``name``, ``description``, ``metadata``,
``tags``), no methods beyond ``__post_init__``/``__hash__``, and no
additional public surface of any kind. This suite proves the
*absence* of that extra surface area as much as it proves the
presence of the documented fields, and uses AST inspection (rather
than mere substring search) to verify the module's import statements
precisely.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    V1  -- Construction: valid name/description/metadata/tags
           construct successfully and are stored exactly.
    V2  -- Construction: empty metadata ({}) is accepted.
    V3  -- Construction: empty tags (()) is accepted.
    V4  -- Construction: populated tags are stored exactly, in order.
    V5  -- Validation: an empty-string name is rejected.
    V6  -- Validation: a whitespace-only name is rejected.
    V7  -- Validation: a non-str name is rejected.
    V8  -- Validation: an empty-string description is rejected.
    V9  -- Validation: a non-Mapping metadata is rejected.
    V10 -- Validation: a non-tuple tags is rejected.
    V11 -- Validation: a tags tuple containing a non-str element is
           rejected.
    V12 -- Validation: a tags tuple containing an empty string is
           rejected.
    V13 -- Immutability: metadata is a frozen types.MappingProxyType
           -- mutating it directly raises TypeError.
    V14 -- Immutability: mutating the original dict passed in as
           'metadata' after construction has no effect on
           Capability.metadata.
    V15 -- Immutability: tags remain unchanged / are stored exactly
           as given (tuples are already immutable).
    V16 -- Identity: two Capability instances with equal names
           produce equal hashes.
    V17 -- Identity: two Capability instances with different names
           produce (typically) different hashes.
    V18 -- Public API: the dataclass's fields are exactly {'name',
           'description', 'metadata', 'tags'} -- nothing else.
    V19 -- Public API: Capability exposes no public (non-dunder)
           methods beyond its declared fields.
    V20 -- Frozen dataclass: reassigning any field after construction
           raises FrozenInstanceError.
    V21 -- CapabilityError subclasses Core.exceptions.AgentError.
    V22 -- Forbidden surface absent: no priority, version, cost,
           provider, executor, runtime, planner, workflow, scheduler,
           memory, reflection, learning, event_bus, permissions,
           requirements, dependencies, parent, children, implements,
           tool, skill, registry, or resolver field/attribute
           anywhere on the class or an instance.
    V23 -- Imports: AST inspection confirms the module imports only
           dataclasses, types.MappingProxyType-equivalent (types),
           typing, and Core.exceptions.AgentError -- nothing else.
    V24 -- Independence: Orchestration/capability.py contains no
           reference (via AST import inspection) to any orchestration
           runtime component (BaseTool, BaseSkill, SkillRegistry,
           SkillResolver, Executor, WorkflowRuntime, WorkflowEngine,
           WorkflowExecutionCoordinator, Planner, Task, Workflow,
           Memory, LearningLoop, Reflection, EventBus, Services,
           Repository, Providers, Database, Agents, CompositionRoot).
"""

from __future__ import annotations

import ast
import sys
import traceback
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import MappingProxyType
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.capability import Capability, CapabilityError

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
# V1 -- valid construction
# ---------------------------------------------------------------------------
def scenario_valid_construction() -> None:
    capability = Capability(
        name="market_analysis",
        description="Analyzes market data for trading signals.",
        metadata={"domain": "trading"},
        tags=("analysis", "market"),
    )

    check(capability.name == "market_analysis", "V1: name is stored exactly")
    check(
        capability.description
        == "Analyzes market data for trading signals.",
        "V1: description is stored exactly",
    )
    check(
        dict(capability.metadata) == {"domain": "trading"},
        "V1: metadata is stored exactly",
    )
    check(
        capability.tags == ("analysis", "market"),
        "V1: tags are stored exactly",
    )


# ---------------------------------------------------------------------------
# V2 -- empty metadata accepted
# ---------------------------------------------------------------------------
def scenario_empty_metadata_accepted() -> None:
    capability = Capability(
        name="x", description="d", metadata={}, tags=()
    )
    check(
        isinstance(capability.metadata, MappingProxyType)
        and len(capability.metadata) == 0,
        "V2: empty metadata ({}) is accepted and stored as an empty "
        "frozen mapping",
    )


# ---------------------------------------------------------------------------
# V3 -- empty tags accepted
# ---------------------------------------------------------------------------
def scenario_empty_tags_accepted() -> None:
    capability = Capability(
        name="x", description="d", metadata={}, tags=()
    )
    check(
        capability.tags == (),
        "V3: empty tags (()) is accepted and stored exactly",
    )


# ---------------------------------------------------------------------------
# V4 -- populated tags stored exactly, in order
# ---------------------------------------------------------------------------
def scenario_populated_tags_stored_in_order() -> None:
    capability = Capability(
        name="x",
        description="d",
        metadata={},
        tags=("gamma", "alpha", "beta"),
    )
    check(
        capability.tags == ("gamma", "alpha", "beta"),
        "V4: populated tags are stored exactly and in the given order "
        "(no sorting/dedup)",
    )


# ---------------------------------------------------------------------------
# V5 -- empty name rejected
# ---------------------------------------------------------------------------
def scenario_empty_name_rejected() -> None:
    raised = False
    try:
        Capability(name="", description="d", metadata={}, tags=())
    except CapabilityError:
        raised = True
    check(raised, "V5: name='' raises CapabilityError")


# ---------------------------------------------------------------------------
# V6 -- whitespace-only name rejected
# ---------------------------------------------------------------------------
def scenario_whitespace_name_rejected() -> None:
    for value in ("   ", "\t", "\n", "  \t\n  "):
        raised = False
        try:
            Capability(name=value, description="d", metadata={}, tags=())
        except CapabilityError:
            raised = True
        check(
            raised,
            f"V6: name={value!r} (whitespace-only) raises CapabilityError",
        )


# ---------------------------------------------------------------------------
# V7 -- non-str name rejected
# ---------------------------------------------------------------------------
def scenario_non_str_name_rejected() -> None:
    for value in (123, None, ["a"], {"k": "v"}, object()):
        raised = False
        try:
            Capability(
                name=value, description="d", metadata={}, tags=()
            )  # type: ignore[arg-type]
        except CapabilityError:
            raised = True
        check(
            raised,
            f"V7: name={value!r} (not a str) raises CapabilityError",
        )


# ---------------------------------------------------------------------------
# V8 -- empty description rejected
# ---------------------------------------------------------------------------
def scenario_empty_description_rejected() -> None:
    raised = False
    try:
        Capability(name="x", description="", metadata={}, tags=())
    except CapabilityError:
        raised = True
    check(raised, "V8: description='' raises CapabilityError")

    raised = False
    try:
        Capability(name="x", description="   ", metadata={}, tags=())
    except CapabilityError:
        raised = True
    check(
        raised,
        "V8: description='   ' (whitespace-only) raises CapabilityError",
    )


# ---------------------------------------------------------------------------
# V9 -- non-Mapping metadata rejected
# ---------------------------------------------------------------------------
def scenario_non_mapping_metadata_rejected() -> None:
    for value in ("not-a-mapping", 123, ["a", "b"], None, object()):
        raised = False
        try:
            Capability(
                name="x", description="d", metadata=value, tags=()
            )  # type: ignore[arg-type]
        except CapabilityError:
            raised = True
        check(
            raised,
            f"V9: metadata={value!r} (not a Mapping) raises "
            f"CapabilityError",
        )


# ---------------------------------------------------------------------------
# V10 -- non-tuple tags rejected
# ---------------------------------------------------------------------------
def scenario_non_tuple_tags_rejected() -> None:
    for value in (["a", "b"], "ab", 123, None, {"a"}, object()):
        raised = False
        try:
            Capability(
                name="x", description="d", metadata={}, tags=value
            )  # type: ignore[arg-type]
        except CapabilityError:
            raised = True
        check(
            raised,
            f"V10: tags={value!r} (not a tuple) raises CapabilityError",
        )


# ---------------------------------------------------------------------------
# V11 -- tags containing non-str element rejected
# ---------------------------------------------------------------------------
def scenario_tags_non_str_element_rejected() -> None:
    for bad_tags in (("a", 1), (None,), (1, 2, 3), ("a", ["b"])):
        raised = False
        try:
            Capability(
                name="x", description="d", metadata={}, tags=bad_tags
            )  # type: ignore[arg-type]
        except CapabilityError:
            raised = True
        check(
            raised,
            f"V11: tags={bad_tags!r} (containing a non-str element) "
            f"raises CapabilityError",
        )


# ---------------------------------------------------------------------------
# V12 -- tags containing empty string rejected
# ---------------------------------------------------------------------------
def scenario_tags_empty_string_element_rejected() -> None:
    for bad_tags in (("",), ("a", ""), ("", "b")):
        raised = False
        try:
            Capability(
                name="x", description="d", metadata={}, tags=bad_tags
            )
        except CapabilityError:
            raised = True
        check(
            raised,
            f"V12: tags={bad_tags!r} (containing an empty string) "
            f"raises CapabilityError",
        )


# ---------------------------------------------------------------------------
# V13 -- metadata frozen
# ---------------------------------------------------------------------------
def scenario_metadata_frozen() -> None:
    capability = Capability(
        name="x", description="d", metadata={"k": "v"}, tags=()
    )

    check(
        isinstance(capability.metadata, MappingProxyType),
        "V13: metadata is stored as a types.MappingProxyType",
    )

    raised = False
    try:
        capability.metadata["k"] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(
        raised, "V13: mutating capability.metadata directly raises TypeError"
    )


# ---------------------------------------------------------------------------
# V14 -- original metadata dict mutation has no effect
# ---------------------------------------------------------------------------
def scenario_metadata_copied_not_aliased() -> None:
    original = {"k": "v"}
    capability = Capability(
        name="x", description="d", metadata=original, tags=()
    )
    original["k"] = "mutated-outside"
    original["new_key"] = "added-outside"

    check(
        dict(capability.metadata) == {"k": "v"},
        "V14: mutating the original metadata dict after construction "
        "does not affect Capability.metadata",
    )


# ---------------------------------------------------------------------------
# V15 -- tags remain unchanged
# ---------------------------------------------------------------------------
def scenario_tags_remain_unchanged() -> None:
    original_tags = ("z", "a", "m")
    capability = Capability(
        name="x", description="d", metadata={}, tags=original_tags
    )
    check(
        capability.tags is original_tags or capability.tags == original_tags,
        "V15: tags are stored exactly as given (no sorting/mutation)",
    )
    check(
        isinstance(capability.tags, tuple),
        "V15: tags remain a tuple (inherently immutable)",
    )


# ---------------------------------------------------------------------------
# V16 -- equal names produce equal hashes
# ---------------------------------------------------------------------------
def scenario_equal_names_equal_hashes() -> None:
    capability_a = Capability(
        name="market_analysis",
        description="desc-a",
        metadata={"x": 1},
        tags=("a",),
    )
    capability_b = Capability(
        name="market_analysis",
        description="desc-b (different)",
        metadata={"y": 2},
        tags=("b", "c"),
    )

    check(
        hash(capability_a) == hash(capability_b),
        "V16: two Capability instances with equal names produce equal "
        "hashes, even with differing description/metadata/tags",
    )
    check(
        capability_a != capability_b,
        "V16: instances with the same name but different other fields "
        "are not equal",
    )


# ---------------------------------------------------------------------------
# V17 -- different names produce different hashes
# ---------------------------------------------------------------------------
def scenario_different_names_different_hashes() -> None:
    capability_a = Capability(
        name="market_analysis", description="d", metadata={}, tags=()
    )
    capability_b = Capability(
        name="order_execution", description="d", metadata={}, tags=()
    )

    check(
        hash(capability_a) != hash(capability_b),
        "V17: two Capability instances with different names produce "
        "different hashes",
    )


# ---------------------------------------------------------------------------
# V18 -- exact dataclass fields
# ---------------------------------------------------------------------------
def scenario_exact_dataclass_fields() -> None:
    field_names = {f.name for f in fields(Capability)}
    check(
        field_names == {"name", "description", "metadata", "tags"},
        f"V18: Capability has exactly the four documented fields; got "
        f"{sorted(field_names)!r}",
    )


# ---------------------------------------------------------------------------
# V19 -- no extra public methods
# ---------------------------------------------------------------------------
def scenario_no_extra_public_methods() -> None:
    public_non_dunder = [
        name for name in vars(Capability) if not name.startswith("_")
    ]
    check(
        set(public_non_dunder).issubset(
            {"name", "description", "metadata", "tags"}
        ),
        f"V19: Capability exposes no public (non-dunder) methods "
        f"beyond its declared fields; found {public_non_dunder!r}",
    )


# ---------------------------------------------------------------------------
# V20 -- frozen dataclass
# ---------------------------------------------------------------------------
def scenario_frozen_dataclass() -> None:
    capability = Capability(
        name="x", description="d", metadata={}, tags=()
    )

    for attr, value in (
        ("name", "y"),
        ("description", "other"),
        ("metadata", {"a": 1}),
        ("tags", ("b",)),
    ):
        raised = False
        try:
            setattr(capability, attr, value)
        except FrozenInstanceError:
            raised = True
        check(
            raised,
            f"V20: reassigning '{attr}' after construction raises "
            f"FrozenInstanceError",
        )


# ---------------------------------------------------------------------------
# V21 -- CapabilityError subclasses AgentError
# ---------------------------------------------------------------------------
def scenario_capability_error_is_agent_error_subclass() -> None:
    check(
        issubclass(CapabilityError, AgentError),
        "V21: CapabilityError subclasses Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# V22 -- forbidden surface absent
# ---------------------------------------------------------------------------
def scenario_forbidden_surface_absent() -> None:
    capability = Capability(
        name="x", description="d", metadata={}, tags=()
    )

    forbidden_attrs = [
        "priority",
        "version",
        "cost",
        "provider",
        "executor",
        "runtime",
        "planner",
        "workflow",
        "scheduler",
        "memory",
        "reflection",
        "learning",
        "event_bus",
        "permissions",
        "requirements",
        "dependencies",
        "parent",
        "children",
        "implements",
        "tool",
        "skill",
        "registry",
        "resolver",
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(Capability, attr) and not hasattr(capability, attr),
            f"V22: Capability has no '{attr}' field/attribute",
        )


# ---------------------------------------------------------------------------
# V23 / V24 -- AST import inspection
# ---------------------------------------------------------------------------
def _collect_imported_module_roots(source: str) -> List[str]:
    """Return the top-level module name for every import statement in
    ``source`` (e.g. 'dataclasses', 'types', 'typing', 'Core')."""
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


def scenario_ast_imports_are_exactly_the_allowed_set() -> None:
    import Orchestration.capability as capability_module

    source = Path(capability_module.__file__).read_text(encoding="utf-8")
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"dataclasses", "types", "typing", "Core", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}

    check(
        unexpected_roots == set(),
        f"V23: Orchestration/capability.py's imports (AST-verified) "
        f"are limited to dataclasses/types/typing/Core.exceptions; "
        f"unexpected roots: {sorted(unexpected_roots)!r}",
    )

    # Confirm the Core import is specifically Core.exceptions (AgentError).
    tree = ast.parse(source)
    core_from_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "Core.exceptions"
    ]
    check(
        len(core_from_imports) == 1
        and any(alias.name == "AgentError" for alias in core_from_imports[0].names),
        "V23: the only 'Core' import is 'from Core.exceptions import "
        "AgentError'",
    )


def scenario_ast_no_orchestration_runtime_component_referenced() -> None:
    import Orchestration.capability as capability_module

    source = Path(capability_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

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
        "SkillRegistry",
        "SkillResolver",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Planner",
        "Task",
        "Workflow",
        "Memory",
        "LearningLoop",
        "Reflection",
        "EventBus",
        "Services",
        "Repository",
        "Providers",
        "Database",
        "Agents",
        "CompositionRoot",
    ]
    for symbol in forbidden_symbols:
        check(
            symbol not in imported_names,
            f"V24: Orchestration/capability.py's AST-parsed import "
            f"names do not include '{symbol}'",
        )
        check(
            not hasattr(capability_module, symbol),
            f"V24: Orchestration.capability's module namespace does "
            f"not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_valid_construction,
        scenario_empty_metadata_accepted,
        scenario_empty_tags_accepted,
        scenario_populated_tags_stored_in_order,
        scenario_empty_name_rejected,
        scenario_whitespace_name_rejected,
        scenario_non_str_name_rejected,
        scenario_empty_description_rejected,
        scenario_non_mapping_metadata_rejected,
        scenario_non_tuple_tags_rejected,
        scenario_tags_non_str_element_rejected,
        scenario_tags_empty_string_element_rejected,
        scenario_metadata_frozen,
        scenario_metadata_copied_not_aliased,
        scenario_tags_remain_unchanged,
        scenario_equal_names_equal_hashes,
        scenario_different_names_different_hashes,
        scenario_exact_dataclass_fields,
        scenario_no_extra_public_methods,
        scenario_frozen_dataclass,
        scenario_capability_error_is_agent_error_subclass,
        scenario_forbidden_surface_absent,
        scenario_ast_imports_are_exactly_the_allowed_set,
        scenario_ast_no_orchestration_runtime_component_referenced,
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
    print(f"PHASE 5 SPRINT 53 CAPABILITY RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())