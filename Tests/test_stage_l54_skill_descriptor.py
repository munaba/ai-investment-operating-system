"""
Phase 5 Sprint 54 proof suite -- the ``SkillDescriptor`` value object.

Scope: dedicated regression suite for
``Orchestration.skill_descriptor.SkillDescriptor``/
``SkillDescriptorError`` only. Nothing else exists in this module to
test -- no registration, no discovery, no serialization, no
helper/convenience methods. ``Orchestration.base_skill.BaseSkill``,
``Orchestration.base_tool.BaseTool``,
``Orchestration.capability.Capability``,
``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``, ``Agents.planner.
Planner``, and ``Orchestration.executor.Executor`` are all untouched
by this sprint and are not exercised here -- nothing about this
sprint wires ``SkillDescriptor`` into any of them, and
``SkillDescriptor`` does not even import ``Capability``.

``SkillDescriptor`` is a pure, minimal, frozen ``dataclass`` value
object: exactly five fields (``name``, ``description``,
``capabilities``, ``metadata``, ``tags``), no methods beyond
``__post_init__``/``__hash__``, and no additional public surface of
any kind. This suite proves the *absence* of that extra surface area
as much as it proves the presence of the documented fields, and uses
AST inspection (rather than mere substring search) to verify the
module's import statements precisely.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    V1  -- Construction: a valid descriptor (name, description,
           capabilities, metadata, tags) constructs successfully and
           is stored exactly.
    V2  -- Construction: empty metadata ({}) is accepted.
    V3  -- Construction: empty capabilities (()) is accepted.
    V4  -- Construction: populated capabilities are stored exactly,
           by identity, in order -- no validation of element type,
           no Capability import required.
    V5  -- Construction: populated tags are stored exactly, in order.
    V6  -- Validation: an empty-string name is rejected.
    V7  -- Validation: a whitespace-only name is rejected.
    V8  -- Validation: a non-str name is rejected.
    V9  -- Validation: an empty-string description is rejected.
    V10 -- Validation: a non-Mapping metadata is rejected.
    V11 -- Validation: a non-tuple capabilities is rejected.
    V12 -- Validation: a non-tuple tags is rejected.
    V13 -- Validation: a tags tuple containing a non-str element is
           rejected.
    V14 -- Validation: a tags tuple containing an empty string is
           rejected.
    V15 -- Immutability: metadata is a frozen types.MappingProxyType
           -- mutating it directly raises TypeError.
    V16 -- Immutability: metadata is copied (not aliased) -- mutating
           the original dict passed in after construction has no
           effect on SkillDescriptor.metadata.
    V17 -- Immutability: capabilities identity is preserved -- the
           exact tuple/elements passed in are stored, untouched.
    V18 -- Immutability: tags are preserved exactly as given.
    V19 -- Hash: two SkillDescriptor instances with the same name
           produce the same hash.
    V20 -- Hash: two SkillDescriptor instances with different names
           produce different hashes.
    V21 -- Public API: the dataclass's fields are exactly {'name',
           'description', 'capabilities', 'metadata', 'tags'} --
           nothing else.
    V22 -- Public API: SkillDescriptor exposes no public (non-dunder)
           methods beyond its declared fields.
    V23 -- Frozen dataclass: reassigning any field after construction
           raises FrozenInstanceError.
    V24 -- SkillDescriptorError subclasses Core.exceptions.AgentError.
    V25 -- Forbidden surface absent: no skill, skill_class, executor,
           planner, provider, runtime, workflow, priority, cost,
           memory, reflection, learning, scheduler, registry,
           resolver, tool, service, repository, database, agent, or
           event_bus field/attribute anywhere on the class or an
           instance.
    V26 -- Imports: AST inspection confirms the module imports only
           dataclasses, types.MappingProxyType-equivalent (types),
           typing, and Core.exceptions.AgentError -- nothing else,
           and specifically NOT Capability/BaseSkill/BaseTool.
    V27 -- Independence: Orchestration/skill_descriptor.py contains
           no reference (via AST import inspection) to any
           orchestration runtime component (BaseTool, BaseSkill,
           Capability, SkillRegistry, SkillResolver, Executor,
           WorkflowRuntime, WorkflowEngine,
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
from Orchestration.skill_descriptor import SkillDescriptor, SkillDescriptorError

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
    sentinel_capability = object()
    descriptor = SkillDescriptor(
        name="market_analysis_skill",
        description="Performs market analysis over price series.",
        capabilities=(sentinel_capability,),
        metadata={"domain": "trading"},
        tags=("analysis", "market"),
    )

    check(
        descriptor.name == "market_analysis_skill",
        "V1: name is stored exactly",
    )
    check(
        descriptor.description
        == "Performs market analysis over price series.",
        "V1: description is stored exactly",
    )
    check(
        descriptor.capabilities == (sentinel_capability,),
        "V1: capabilities are stored exactly",
    )
    check(
        dict(descriptor.metadata) == {"domain": "trading"},
        "V1: metadata is stored exactly",
    )
    check(
        descriptor.tags == ("analysis", "market"),
        "V1: tags are stored exactly",
    )


# ---------------------------------------------------------------------------
# V2 -- empty metadata accepted
# ---------------------------------------------------------------------------
def scenario_empty_metadata_accepted() -> None:
    descriptor = SkillDescriptor(
        name="x", description="d", capabilities=(), metadata={}, tags=()
    )
    check(
        isinstance(descriptor.metadata, MappingProxyType)
        and len(descriptor.metadata) == 0,
        "V2: empty metadata ({}) is accepted and stored as an empty "
        "frozen mapping",
    )


# ---------------------------------------------------------------------------
# V3 -- empty capabilities accepted
# ---------------------------------------------------------------------------
def scenario_empty_capabilities_accepted() -> None:
    descriptor = SkillDescriptor(
        name="x", description="d", capabilities=(), metadata={}, tags=()
    )
    check(
        descriptor.capabilities == (),
        "V3: empty capabilities (()) is accepted and stored exactly",
    )


# ---------------------------------------------------------------------------
# V4 -- populated capabilities stored exactly, by identity, in order
# ---------------------------------------------------------------------------
def scenario_populated_capabilities_stored_by_identity() -> None:
    cap_a = object()
    cap_b = "just-a-string-capability-placeholder"
    cap_c = {"name": "a-dict-capability-placeholder"}

    descriptor = SkillDescriptor(
        name="x",
        description="d",
        capabilities=(cap_a, cap_b, cap_c),
        metadata={},
        tags=(),
    )

    check(
        descriptor.capabilities[0] is cap_a
        and descriptor.capabilities[1] is cap_b
        and descriptor.capabilities[2] is cap_c,
        "V4: populated capabilities are stored exactly, by identity, "
        "in order (no validation of element type, no Capability "
        "import required)",
    )


# ---------------------------------------------------------------------------
# V5 -- populated tags stored exactly, in order
# ---------------------------------------------------------------------------
def scenario_populated_tags_stored_in_order() -> None:
    descriptor = SkillDescriptor(
        name="x",
        description="d",
        capabilities=(),
        metadata={},
        tags=("gamma", "alpha", "beta"),
    )
    check(
        descriptor.tags == ("gamma", "alpha", "beta"),
        "V5: populated tags are stored exactly and in the given order "
        "(no sorting/dedup)",
    )


# ---------------------------------------------------------------------------
# V6 -- empty name rejected
# ---------------------------------------------------------------------------
def scenario_empty_name_rejected() -> None:
    raised = False
    try:
        SkillDescriptor(
            name="", description="d", capabilities=(), metadata={}, tags=()
        )
    except SkillDescriptorError:
        raised = True
    check(raised, "V6: name='' raises SkillDescriptorError")


# ---------------------------------------------------------------------------
# V7 -- whitespace-only name rejected
# ---------------------------------------------------------------------------
def scenario_whitespace_name_rejected() -> None:
    for value in ("   ", "\t", "\n", "  \t\n  "):
        raised = False
        try:
            SkillDescriptor(
                name=value,
                description="d",
                capabilities=(),
                metadata={},
                tags=(),
            )
        except SkillDescriptorError:
            raised = True
        check(
            raised,
            f"V7: name={value!r} (whitespace-only) raises "
            f"SkillDescriptorError",
        )


# ---------------------------------------------------------------------------
# V8 -- non-str name rejected
# ---------------------------------------------------------------------------
def scenario_non_str_name_rejected() -> None:
    for value in (123, None, ["a"], {"k": "v"}, object()):
        raised = False
        try:
            SkillDescriptor(
                name=value,
                description="d",
                capabilities=(),
                metadata={},
                tags=(),
            )  # type: ignore[arg-type]
        except SkillDescriptorError:
            raised = True
        check(
            raised,
            f"V8: name={value!r} (not a str) raises SkillDescriptorError",
        )


# ---------------------------------------------------------------------------
# V9 -- empty description rejected
# ---------------------------------------------------------------------------
def scenario_empty_description_rejected() -> None:
    raised = False
    try:
        SkillDescriptor(
            name="x", description="", capabilities=(), metadata={}, tags=()
        )
    except SkillDescriptorError:
        raised = True
    check(raised, "V9: description='' raises SkillDescriptorError")

    raised = False
    try:
        SkillDescriptor(
            name="x",
            description="   ",
            capabilities=(),
            metadata={},
            tags=(),
        )
    except SkillDescriptorError:
        raised = True
    check(
        raised,
        "V9: description='   ' (whitespace-only) raises "
        "SkillDescriptorError",
    )


# ---------------------------------------------------------------------------
# V10 -- non-Mapping metadata rejected
# ---------------------------------------------------------------------------
def scenario_non_mapping_metadata_rejected() -> None:
    for value in ("not-a-mapping", 123, ["a", "b"], None, object()):
        raised = False
        try:
            SkillDescriptor(
                name="x",
                description="d",
                capabilities=(),
                metadata=value,
                tags=(),
            )  # type: ignore[arg-type]
        except SkillDescriptorError:
            raised = True
        check(
            raised,
            f"V10: metadata={value!r} (not a Mapping) raises "
            f"SkillDescriptorError",
        )


# ---------------------------------------------------------------------------
# V11 -- non-tuple capabilities rejected
# ---------------------------------------------------------------------------
def scenario_non_tuple_capabilities_rejected() -> None:
    for value in (["a", "b"], "ab", 123, None, {"a"}, object()):
        raised = False
        try:
            SkillDescriptor(
                name="x",
                description="d",
                capabilities=value,
                metadata={},
                tags=(),
            )  # type: ignore[arg-type]
        except SkillDescriptorError:
            raised = True
        check(
            raised,
            f"V11: capabilities={value!r} (not a tuple) raises "
            f"SkillDescriptorError",
        )


# ---------------------------------------------------------------------------
# V12 -- non-tuple tags rejected
# ---------------------------------------------------------------------------
def scenario_non_tuple_tags_rejected() -> None:
    for value in (["a", "b"], "ab", 123, None, {"a"}, object()):
        raised = False
        try:
            SkillDescriptor(
                name="x",
                description="d",
                capabilities=(),
                metadata={},
                tags=value,
            )  # type: ignore[arg-type]
        except SkillDescriptorError:
            raised = True
        check(
            raised,
            f"V12: tags={value!r} (not a tuple) raises "
            f"SkillDescriptorError",
        )


# ---------------------------------------------------------------------------
# V13 -- tags containing non-str element rejected
# ---------------------------------------------------------------------------
def scenario_tags_non_str_element_rejected() -> None:
    for bad_tags in (("a", 1), (None,), (1, 2, 3), ("a", ["b"])):
        raised = False
        try:
            SkillDescriptor(
                name="x",
                description="d",
                capabilities=(),
                metadata={},
                tags=bad_tags,
            )  # type: ignore[arg-type]
        except SkillDescriptorError:
            raised = True
        check(
            raised,
            f"V13: tags={bad_tags!r} (containing a non-str element) "
            f"raises SkillDescriptorError",
        )


# ---------------------------------------------------------------------------
# V14 -- tags containing empty string rejected
# ---------------------------------------------------------------------------
def scenario_tags_empty_string_element_rejected() -> None:
    for bad_tags in (("",), ("a", ""), ("", "b")):
        raised = False
        try:
            SkillDescriptor(
                name="x",
                description="d",
                capabilities=(),
                metadata={},
                tags=bad_tags,
            )
        except SkillDescriptorError:
            raised = True
        check(
            raised,
            f"V14: tags={bad_tags!r} (containing an empty string) "
            f"raises SkillDescriptorError",
        )


# ---------------------------------------------------------------------------
# V15 -- metadata frozen
# ---------------------------------------------------------------------------
def scenario_metadata_frozen() -> None:
    descriptor = SkillDescriptor(
        name="x",
        description="d",
        capabilities=(),
        metadata={"k": "v"},
        tags=(),
    )

    check(
        isinstance(descriptor.metadata, MappingProxyType),
        "V15: metadata is stored as a types.MappingProxyType",
    )

    raised = False
    try:
        descriptor.metadata["k"] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(
        raised, "V15: mutating descriptor.metadata directly raises TypeError"
    )


# ---------------------------------------------------------------------------
# V16 -- metadata copied, original mutation has no effect
# ---------------------------------------------------------------------------
def scenario_metadata_copied_not_aliased() -> None:
    original = {"k": "v"}
    descriptor = SkillDescriptor(
        name="x", description="d", capabilities=(), metadata=original, tags=()
    )
    original["k"] = "mutated-outside"
    original["new_key"] = "added-outside"

    check(
        dict(descriptor.metadata) == {"k": "v"},
        "V16: mutating the original metadata dict after construction "
        "does not affect SkillDescriptor.metadata",
    )


# ---------------------------------------------------------------------------
# V17 -- capabilities identity preserved
# ---------------------------------------------------------------------------
def scenario_capabilities_identity_preserved() -> None:
    cap = object()
    original_capabilities = (cap,)
    descriptor = SkillDescriptor(
        name="x",
        description="d",
        capabilities=original_capabilities,
        metadata={},
        tags=(),
    )
    check(
        descriptor.capabilities is original_capabilities
        and descriptor.capabilities[0] is cap,
        "V17: capabilities tuple/elements are preserved by identity, "
        "never copied or transformed",
    )


# ---------------------------------------------------------------------------
# V18 -- tags preserved
# ---------------------------------------------------------------------------
def scenario_tags_preserved() -> None:
    original_tags = ("z", "a", "m")
    descriptor = SkillDescriptor(
        name="x",
        description="d",
        capabilities=(),
        metadata={},
        tags=original_tags,
    )
    check(
        descriptor.tags is original_tags or descriptor.tags == original_tags,
        "V18: tags are stored exactly as given (no sorting/mutation)",
    )
    check(
        isinstance(descriptor.tags, tuple),
        "V18: tags remain a tuple (inherently immutable)",
    )


# ---------------------------------------------------------------------------
# V19 -- same name, same hash
# ---------------------------------------------------------------------------
def scenario_same_name_same_hash() -> None:
    descriptor_a = SkillDescriptor(
        name="market_analysis_skill",
        description="desc-a",
        capabilities=("cap-a",),
        metadata={"x": 1},
        tags=("a",),
    )
    descriptor_b = SkillDescriptor(
        name="market_analysis_skill",
        description="desc-b (different)",
        capabilities=("cap-b", "cap-c"),
        metadata={"y": 2},
        tags=("b", "c"),
    )

    check(
        hash(descriptor_a) == hash(descriptor_b),
        "V19: two SkillDescriptor instances with the same name produce "
        "the same hash, even with differing "
        "description/capabilities/metadata/tags",
    )
    check(
        descriptor_a != descriptor_b,
        "V19: instances with the same name but different other fields "
        "are not equal",
    )


# ---------------------------------------------------------------------------
# V20 -- different name, different hash
# ---------------------------------------------------------------------------
def scenario_different_name_different_hash() -> None:
    descriptor_a = SkillDescriptor(
        name="market_analysis_skill",
        description="d",
        capabilities=(),
        metadata={},
        tags=(),
    )
    descriptor_b = SkillDescriptor(
        name="order_execution_skill",
        description="d",
        capabilities=(),
        metadata={},
        tags=(),
    )

    check(
        hash(descriptor_a) != hash(descriptor_b),
        "V20: two SkillDescriptor instances with different names "
        "produce different hashes",
    )


# ---------------------------------------------------------------------------
# V21 -- exact dataclass fields
# ---------------------------------------------------------------------------
def scenario_exact_dataclass_fields() -> None:
    field_names = {f.name for f in fields(SkillDescriptor)}
    check(
        field_names
        == {"name", "description", "capabilities", "metadata", "tags"},
        f"V21: SkillDescriptor has exactly the five documented fields; "
        f"got {sorted(field_names)!r}",
    )


# ---------------------------------------------------------------------------
# V22 -- no extra public methods
# ---------------------------------------------------------------------------
def scenario_no_extra_public_methods() -> None:
    public_non_dunder = [
        name for name in vars(SkillDescriptor) if not name.startswith("_")
    ]
    check(
        set(public_non_dunder).issubset(
            {"name", "description", "capabilities", "metadata", "tags"}
        ),
        f"V22: SkillDescriptor exposes no public (non-dunder) methods "
        f"beyond its declared fields; found {public_non_dunder!r}",
    )


# ---------------------------------------------------------------------------
# V23 -- frozen dataclass
# ---------------------------------------------------------------------------
def scenario_frozen_dataclass() -> None:
    descriptor = SkillDescriptor(
        name="x", description="d", capabilities=(), metadata={}, tags=()
    )

    for attr, value in (
        ("name", "y"),
        ("description", "other"),
        ("capabilities", ("c",)),
        ("metadata", {"a": 1}),
        ("tags", ("b",)),
    ):
        raised = False
        try:
            setattr(descriptor, attr, value)
        except FrozenInstanceError:
            raised = True
        check(
            raised,
            f"V23: reassigning '{attr}' after construction raises "
            f"FrozenInstanceError",
        )


# ---------------------------------------------------------------------------
# V24 -- SkillDescriptorError subclasses AgentError
# ---------------------------------------------------------------------------
def scenario_skill_descriptor_error_is_agent_error_subclass() -> None:
    check(
        issubclass(SkillDescriptorError, AgentError),
        "V24: SkillDescriptorError subclasses Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# V25 -- forbidden surface absent
# ---------------------------------------------------------------------------
def scenario_forbidden_surface_absent() -> None:
    descriptor = SkillDescriptor(
        name="x", description="d", capabilities=(), metadata={}, tags=()
    )

    forbidden_attrs = [
        "skill",
        "skill_class",
        "executor",
        "planner",
        "provider",
        "runtime",
        "workflow",
        "priority",
        "cost",
        "memory",
        "reflection",
        "learning",
        "scheduler",
        "registry",
        "resolver",
        "tool",
        "service",
        "repository",
        "database",
        "agent",
        "event_bus",
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(SkillDescriptor, attr)
            and not hasattr(descriptor, attr),
            f"V25: SkillDescriptor has no '{attr}' field/attribute",
        )


# ---------------------------------------------------------------------------
# V26 / V27 -- AST import inspection
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
    import Orchestration.skill_descriptor as skill_descriptor_module

    source = Path(skill_descriptor_module.__file__).read_text(
        encoding="utf-8"
    )
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"dataclasses", "types", "typing", "Core", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}

    check(
        unexpected_roots == set(),
        f"V26: Orchestration/skill_descriptor.py's imports "
        f"(AST-verified) are limited to "
        f"dataclasses/types/typing/Core.exceptions; unexpected roots: "
        f"{sorted(unexpected_roots)!r}",
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
        "V26: the only 'Core' import is 'from Core.exceptions import "
        "AgentError'",
    )

    # Explicitly confirm Capability/BaseSkill/BaseTool are not imported.
    imported_names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names.append(alias.asname or alias.name)

    for symbol in ("Capability", "BaseSkill", "BaseTool"):
        check(
            symbol not in imported_names,
            f"V26: Orchestration/skill_descriptor.py does not import "
            f"'{symbol}'",
        )


def scenario_ast_no_orchestration_runtime_component_referenced() -> None:
    import Orchestration.skill_descriptor as skill_descriptor_module

    source = Path(skill_descriptor_module.__file__).read_text(
        encoding="utf-8"
    )
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
        "Capability",
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
            f"V27: Orchestration/skill_descriptor.py's AST-parsed "
            f"import names do not include '{symbol}'",
        )
        check(
            not hasattr(skill_descriptor_module, symbol),
            f"V27: Orchestration.skill_descriptor's module namespace "
            f"does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_valid_construction,
        scenario_empty_metadata_accepted,
        scenario_empty_capabilities_accepted,
        scenario_populated_capabilities_stored_by_identity,
        scenario_populated_tags_stored_in_order,
        scenario_empty_name_rejected,
        scenario_whitespace_name_rejected,
        scenario_non_str_name_rejected,
        scenario_empty_description_rejected,
        scenario_non_mapping_metadata_rejected,
        scenario_non_tuple_capabilities_rejected,
        scenario_non_tuple_tags_rejected,
        scenario_tags_non_str_element_rejected,
        scenario_tags_empty_string_element_rejected,
        scenario_metadata_frozen,
        scenario_metadata_copied_not_aliased,
        scenario_capabilities_identity_preserved,
        scenario_tags_preserved,
        scenario_same_name_same_hash,
        scenario_different_name_different_hash,
        scenario_exact_dataclass_fields,
        scenario_no_extra_public_methods,
        scenario_frozen_dataclass,
        scenario_skill_descriptor_error_is_agent_error_subclass,
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
    print(f"PHASE 5 SPRINT 54 SKILL DESCRIPTOR RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())