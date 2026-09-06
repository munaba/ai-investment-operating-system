"""
Phase 5 Sprint 51 proof suite -- the ``ToolContext`` value object.

Scope: dedicated regression suite for
``Orchestration.tool_context.ToolContext``/``ToolContextError`` only.
Nothing else exists in this module to test -- no serialization, no
builders, no helper/convenience methods.
``Orchestration.base_tool.BaseTool``, ``Orchestration.base_skill.
BaseSkill``, ``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``, and
``Orchestration.executor.Executor`` are all untouched by this sprint
and are not exercised here -- nothing about this sprint wires
``ToolContext`` into any of them.

``ToolContext`` is a pure, minimal, frozen ``dataclass`` value object:
exactly three fields (``task``, ``parameters``, ``metadata``), no
methods beyond ``__post_init__``/``__hash__``, and no additional
public surface of any kind. This suite proves the *absence* of that
extra surface area as much as it proves the presence of the
documented fields, and uses AST inspection (rather than mere
substring search) to verify the module's import statements precisely.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    V1  -- Construction: a valid task, valid parameters, and valid
           metadata construct successfully and are stored exactly.
    V2  -- Validation: task=None is rejected with ToolContextError.
    V3  -- Validation: a non-Mapping 'parameters' is rejected with
           ToolContextError.
    V4  -- Validation: a non-Mapping 'metadata' is rejected with
           ToolContextError.
    V5  -- Immutability: parameters is a frozen types.MappingProxyType
           -- mutating it directly raises TypeError.
    V6  -- Immutability: metadata is a frozen types.MappingProxyType
           -- mutating it directly raises TypeError.
    V7  -- Immutability: mutating the original dict passed in as
           'parameters' after construction has no effect on
           ToolContext.parameters.
    V8  -- Immutability: mutating the original dict passed in as
           'metadata' after construction has no effect on
           ToolContext.metadata.
    V9  -- Identity: the exact 'task' object identity is preserved
           (context.task is original_task), never copied or
           transformed.
    V10 -- Hash: two ToolContext instances sharing the same task
           object (by identity) share the same hash, even with
           differing parameters/metadata.
    V11 -- Hash: two ToolContext instances with different task object
           identities need not share a hash (and typically do not);
           hash(context) does not raise despite parameters/metadata
           being unhashable and task itself being unhashable.
    V12 -- Public API: the dataclass's fields are exactly {'task',
           'parameters', 'metadata'} -- nothing else.
    V13 -- Public API: ToolContext exposes no public (non-dunder)
           methods.
    V14 -- Frozen dataclass: reassigning any field after construction
           raises FrozenInstanceError.
    V15 -- ToolContextError subclasses Core.exceptions.AgentError.
    V16 -- Forbidden surface absent: no execution_id, workflow_id,
           session_id, runtime, planner, memory, event, reflection,
           learning, scheduler, executor, provider, database,
           tool_id, tool_name, timestamp, logger, service, repository,
           or agent field/attribute anywhere on the class or an
           instance.
    V17 -- Imports: AST inspection confirms the module imports only
           dataclasses, types.MappingProxyType-equivalent (types),
           typing, and Core.exceptions.AgentError -- nothing else.
    V18 -- Independence: Orchestration/tool_context.py contains no
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
from Orchestration.tool_context import ToolContext, ToolContextError

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
# V1 -- construction with valid task/parameters/metadata
# ---------------------------------------------------------------------------
def scenario_valid_construction() -> None:
    sentinel_task = {"symbol": "AAPL"}
    context = ToolContext(
        task=sentinel_task,
        parameters={"window": 14},
        metadata={"requested_by": "unit-test"},
    )

    check(
        context.task is sentinel_task,
        "V1: a valid task is stored (by identity)",
    )
    check(
        dict(context.parameters) == {"window": 14},
        "V1: valid parameters are stored exactly",
    )
    check(
        dict(context.metadata) == {"requested_by": "unit-test"},
        "V1: valid metadata is stored exactly",
    )


def scenario_valid_construction_with_defaults() -> None:
    context = ToolContext(task="simple-task")

    check(context.task == "simple-task", "V1: task stores the given value")
    check(
        isinstance(context.parameters, MappingProxyType)
        and len(context.parameters) == 0,
        "V1: parameters defaults to an empty (frozen) mapping",
    )
    check(
        isinstance(context.metadata, MappingProxyType)
        and len(context.metadata) == 0,
        "V1: metadata defaults to an empty (frozen) mapping",
    )


# ---------------------------------------------------------------------------
# V2 -- task None rejected
# ---------------------------------------------------------------------------
def scenario_task_none_rejected() -> None:
    raised = False
    try:
        ToolContext(task=None)
    except ToolContextError:
        raised = True
    check(raised, "V2: task=None raises ToolContextError")


# ---------------------------------------------------------------------------
# V3 -- parameters non-mapping rejected
# ---------------------------------------------------------------------------
def scenario_parameters_non_mapping_rejected() -> None:
    for value in ("not-a-mapping", 123, ["a", "b"], None, object()):
        raised = False
        try:
            ToolContext(task="x", parameters=value)  # type: ignore[arg-type]
        except ToolContextError:
            raised = True
        check(
            raised,
            f"V3: parameters={value!r} (not a Mapping) raises "
            f"ToolContextError",
        )


# ---------------------------------------------------------------------------
# V4 -- metadata non-mapping rejected
# ---------------------------------------------------------------------------
def scenario_metadata_non_mapping_rejected() -> None:
    for value in ("not-a-mapping", 123, ["a", "b"], None, object()):
        raised = False
        try:
            ToolContext(task="x", metadata=value)  # type: ignore[arg-type]
        except ToolContextError:
            raised = True
        check(
            raised,
            f"V4: metadata={value!r} (not a Mapping) raises "
            f"ToolContextError",
        )


# ---------------------------------------------------------------------------
# V5 -- parameters frozen
# ---------------------------------------------------------------------------
def scenario_parameters_frozen() -> None:
    context = ToolContext(task="x", parameters={"k": "v"})

    check(
        isinstance(context.parameters, MappingProxyType),
        "V5: parameters is stored as a types.MappingProxyType",
    )

    raised = False
    try:
        context.parameters["k"] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(
        raised,
        "V5: attempting to mutate context.parameters directly raises "
        "TypeError",
    )


# ---------------------------------------------------------------------------
# V6 -- metadata frozen
# ---------------------------------------------------------------------------
def scenario_metadata_frozen() -> None:
    context = ToolContext(task="x", metadata={"k": "v"})

    check(
        isinstance(context.metadata, MappingProxyType),
        "V6: metadata is stored as a types.MappingProxyType",
    )

    raised = False
    try:
        context.metadata["k"] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(
        raised,
        "V6: attempting to mutate context.metadata directly raises "
        "TypeError",
    )


# ---------------------------------------------------------------------------
# V7 -- parameters copied, not aliased
# ---------------------------------------------------------------------------
def scenario_parameters_copied_not_aliased() -> None:
    original = {"k": "v"}
    context = ToolContext(task="x", parameters=original)

    original["k"] = "mutated-after-construction"
    original["new_key"] = "should-not-appear"

    check(
        dict(context.parameters) == {"k": "v"},
        "V7: mutating the original 'parameters' dict after "
        "construction has no effect on context.parameters",
    )


# ---------------------------------------------------------------------------
# V8 -- metadata copied, not aliased
# ---------------------------------------------------------------------------
def scenario_metadata_copied_not_aliased() -> None:
    original = {"k": "v"}
    context = ToolContext(task="x", metadata=original)

    original["k"] = "mutated-after-construction"
    original["new_key"] = "should-not-appear"

    check(
        dict(context.metadata) == {"k": "v"},
        "V8: mutating the original 'metadata' dict after "
        "construction has no effect on context.metadata",
    )


# ---------------------------------------------------------------------------
# V9 -- task identity preserved
# ---------------------------------------------------------------------------
def scenario_task_identity_preserved() -> None:
    class SomeTask:
        pass

    original_task = SomeTask()
    context = ToolContext(task=original_task)

    check(
        context.task is original_task,
        "V9: ToolContext.task preserves the exact object identity of "
        "the task it was constructed with",
    )


# ---------------------------------------------------------------------------
# V10 / V11 -- hash by id(task)
# ---------------------------------------------------------------------------
def scenario_hash_equal_task_reference() -> None:
    class SomeTask:
        pass

    shared_task = SomeTask()
    a = ToolContext(task=shared_task, parameters={"x": 1})
    b = ToolContext(task=shared_task, parameters={"x": 2})

    check(
        hash(a) == hash(b),
        "V10: two ToolContext instances sharing the same task object "
        "(by identity) share the same hash, even with differing "
        "parameters",
    )
    check(
        a != b,
        "V10: those two instances are nonetheless not equal (they "
        "differ in 'parameters')",
    )


def scenario_hash_different_task_reference() -> None:
    class SomeTask:
        pass

    task_one = SomeTask()
    task_two = SomeTask()
    a = ToolContext(task=task_one)
    b = ToolContext(task=task_two)

    check(
        hash(a) != hash(b),
        "V11: two ToolContext instances with different task object "
        "identities have different hashes",
    )


def scenario_hash_does_not_raise_with_unhashable_task() -> None:
    unhashable_task = {"cannot": "hash", "a": "dict"}
    context = ToolContext(
        task=unhashable_task,
        parameters={"p": [1, 2, 3]},
        metadata={"m": {"nested": "dict"}},
    )

    raised = False
    try:
        hash(context)
    except TypeError:
        raised = True
    check(
        not raised,
        "V11: hash(context) does not raise despite an unhashable "
        "'task' and unhashable parameters/metadata (hashing is by "
        "id(task) only)",
    )

    try:
        {context}
        used_as_set_member = True
    except TypeError:
        used_as_set_member = False
    check(
        used_as_set_member,
        "V11: ToolContext is usable as a set member",
    )


# ---------------------------------------------------------------------------
# V12 / V13 -- public API
# ---------------------------------------------------------------------------
def scenario_exact_dataclass_fields() -> None:
    field_names = {f.name for f in fields(ToolContext)}
    check(
        field_names == {"task", "parameters", "metadata"},
        f"V12: ToolContext's dataclass fields are exactly "
        f"{{'task', 'parameters', 'metadata'}}; got {field_names!r}",
    )


def scenario_no_extra_public_methods() -> None:
    public_methods = {
        name
        for name in dir(ToolContext)
        if not name.startswith("_")
        and callable(getattr(ToolContext, name, None))
    }
    check(
        public_methods == set(),
        f"V13: ToolContext exposes no public (non-dunder) methods; "
        f"got {sorted(public_methods)!r}",
    )

    allowed_dunders = {
        "__init__",
        "__repr__",
        "__eq__",
        "__hash__",
        "__setattr__",
        "__delattr__",
        "__post_init__",
        "__class__",
        "__dict__",
        "__doc__",
        "__module__",
        "__weakref__",
        "__dataclass_fields__",
        "__dataclass_params__",
        "__match_args__",
    }
    field_names = {f.name for f in fields(ToolContext)}
    own_members = set(vars(ToolContext).keys())
    unexpected = {
        name
        for name in own_members
        if name not in allowed_dunders
        and name not in field_names
        and not (name.startswith("__") and name.endswith("__"))
    }
    check(
        unexpected == set(),
        f"V13: ToolContext defines no members beyond dataclass "
        f"machinery and __post_init__/__hash__; unexpected: "
        f"{sorted(unexpected)!r}",
    )


# ---------------------------------------------------------------------------
# V14 -- frozen dataclass
# ---------------------------------------------------------------------------
def scenario_frozen_dataclass() -> None:
    context = ToolContext(task="x")

    for attr, value in (
        ("task", "y"),
        ("parameters", {"a": 1}),
        ("metadata", {"b": 2}),
    ):
        raised = False
        try:
            setattr(context, attr, value)
        except FrozenInstanceError:
            raised = True
        check(
            raised,
            f"V14: reassigning '{attr}' after construction raises "
            f"FrozenInstanceError",
        )


# ---------------------------------------------------------------------------
# V15 -- ToolContextError subclasses AgentError
# ---------------------------------------------------------------------------
def scenario_tool_context_error_is_agent_error_subclass() -> None:
    check(
        issubclass(ToolContextError, AgentError),
        "V15: ToolContextError subclasses Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# V16 -- forbidden surface absent
# ---------------------------------------------------------------------------
def scenario_forbidden_surface_absent() -> None:
    context = ToolContext(task="x")

    forbidden_attrs = [
        "execution_id",
        "workflow_id",
        "session_id",
        "runtime",
        "planner",
        "memory",
        "event",
        "reflection",
        "learning",
        "scheduler",
        "executor",
        "provider",
        "database",
        "tool_id",
        "tool_name",
        "timestamp",
        "logger",
        "service",
        "repository",
        "agent",
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(ToolContext, attr) and not hasattr(context, attr),
            f"V16: ToolContext has no '{attr}' field/attribute",
        )


# ---------------------------------------------------------------------------
# V17 / V18 -- AST import inspection
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
    import Orchestration.tool_context as tool_context_module

    source = Path(tool_context_module.__file__).read_text(encoding="utf-8")
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"dataclasses", "types", "typing", "Core", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}

    check(
        unexpected_roots == set(),
        f"V17: Orchestration/tool_context.py's imports (AST-verified) "
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
        "V17: the only 'Core' import is 'from Core.exceptions import "
        "AgentError'",
    )


def scenario_ast_no_orchestration_runtime_component_referenced() -> None:
    import Orchestration.tool_context as tool_context_module

    source = Path(tool_context_module.__file__).read_text(encoding="utf-8")
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
            f"V18: Orchestration/tool_context.py's AST-parsed import "
            f"names do not include '{symbol}'",
        )
        check(
            not hasattr(tool_context_module, symbol),
            f"V18: Orchestration.tool_context's module namespace does "
            f"not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_valid_construction,
        scenario_valid_construction_with_defaults,
        scenario_task_none_rejected,
        scenario_parameters_non_mapping_rejected,
        scenario_metadata_non_mapping_rejected,
        scenario_parameters_frozen,
        scenario_metadata_frozen,
        scenario_parameters_copied_not_aliased,
        scenario_metadata_copied_not_aliased,
        scenario_task_identity_preserved,
        scenario_hash_equal_task_reference,
        scenario_hash_different_task_reference,
        scenario_hash_does_not_raise_with_unhashable_task,
        scenario_exact_dataclass_fields,
        scenario_no_extra_public_methods,
        scenario_frozen_dataclass,
        scenario_tool_context_error_is_agent_error_subclass,
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
    print(f"PHASE 5 SPRINT 51 TOOL CONTEXT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())