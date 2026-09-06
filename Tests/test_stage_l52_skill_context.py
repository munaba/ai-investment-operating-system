"""
Phase 5 Sprint 52 proof suite -- the ``SkillContext`` value object.

Scope: dedicated regression suite for
``Orchestration.skill_context.SkillContext``/``SkillContextError``
only. Nothing else exists in this module to test -- no serialization,
no builders, no helper/convenience methods.
``Orchestration.base_skill.BaseSkill``, ``Orchestration.base_tool.
BaseTool``, ``Orchestration.skill_registry.SkillRegistry``,
``Orchestration.skill_resolver.SkillResolver``, and
``Orchestration.executor.Executor`` are all untouched by this sprint
and are not exercised here -- nothing about this sprint wires
``SkillContext`` into any of them.

``SkillContext`` is a pure, minimal, frozen ``dataclass`` value
object: exactly four fields (``task``, ``parameters``, ``metadata``,
``tool_context_factory``), no methods beyond
``__post_init__``/``__hash__``, and no additional public surface of
any kind. This suite proves the *absence* of that extra surface area
as much as it proves the presence of the documented fields, and uses
AST inspection (rather than mere substring search) to verify the
module's import statements precisely.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites: a global pass/fail counter,
plain fixtures, and a ``main()`` runner.

Invariant coverage:
    V1  -- Construction: a valid task, valid parameters, valid
           metadata, and a valid callable factory construct
           successfully and are stored exactly.
    V2  -- Validation: task=None is rejected with SkillContextError.
    V3  -- Validation: a non-Mapping 'parameters' is rejected with
           SkillContextError.
    V4  -- Validation: a non-Mapping 'metadata' is rejected with
           SkillContextError.
    V5  -- Validation: a non-callable, non-None
           'tool_context_factory' is rejected with SkillContextError.
    V6  -- Immutability: parameters is a frozen types.MappingProxyType
           -- mutating it directly raises TypeError.
    V7  -- Immutability: metadata is a frozen types.MappingProxyType
           -- mutating it directly raises TypeError.
    V8  -- Immutability: mutating the original dict passed in as
           'parameters' after construction has no effect on
           SkillContext.parameters.
    V9  -- Immutability: mutating the original dict passed in as
           'metadata' after construction has no effect on
           SkillContext.metadata.
    V10 -- Identity: the exact 'task' object identity is preserved
           (context.task is original_task), never copied or
           transformed.
    V11 -- tool_context_factory: a callable is accepted and stored
           (by identity), and None is accepted as the default.
    V12 -- Hash: two SkillContext instances sharing the same task
           object (by identity) share the same hash, even with
           differing parameters/metadata/tool_context_factory.
    V13 -- Hash: two SkillContext instances with different task
           object identities need not share a hash (and typically do
           not); hash(context) does not raise despite
           parameters/metadata being unhashable and task itself being
           unhashable.
    V14 -- Public API: the dataclass's fields are exactly {'task',
           'parameters', 'metadata', 'tool_context_factory'} --
           nothing else.
    V15 -- Public API: SkillContext exposes no public (non-dunder)
           methods.
    V16 -- Frozen dataclass: reassigning any field after construction
           raises FrozenInstanceError.
    V17 -- SkillContextError subclasses Core.exceptions.AgentError.
    V18 -- Forbidden surface absent: no workflow, workflow_id,
           execution_id, session, session_id, runtime, executor,
           scheduler, memory, reflection, learning, event_bus,
           provider, database, repository, service, agent, host,
           planner, logger, result, status, priority, retry, or
           timeout field/attribute anywhere on the class or an
           instance.
    V19 -- Imports: AST inspection confirms the module imports only
           dataclasses, types.MappingProxyType-equivalent (types),
           typing, and Core.exceptions.AgentError -- nothing else.
    V20 -- Independence: Orchestration/skill_context.py contains no
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
from Orchestration.skill_context import SkillContext, SkillContextError

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
# V1 -- construction with valid task/parameters/metadata/factory
# ---------------------------------------------------------------------------
def scenario_valid_construction() -> None:
    sentinel_task = {"symbol": "AAPL"}

    def sentinel_factory(**kwargs):
        return kwargs

    context = SkillContext(
        task=sentinel_task,
        parameters={"window": 14},
        metadata={"requested_by": "unit-test"},
        tool_context_factory=sentinel_factory,
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
    check(
        context.tool_context_factory is sentinel_factory,
        "V1: valid tool_context_factory is stored (by identity)",
    )


def scenario_valid_construction_with_defaults() -> None:
    context = SkillContext(task="simple-task")

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
    check(
        context.tool_context_factory is None,
        "V1: tool_context_factory defaults to None",
    )


# ---------------------------------------------------------------------------
# V2 -- task None rejected
# ---------------------------------------------------------------------------
def scenario_task_none_rejected() -> None:
    raised = False
    try:
        SkillContext(task=None)
    except SkillContextError:
        raised = True
    check(raised, "V2: task=None raises SkillContextError")


# ---------------------------------------------------------------------------
# V3 -- parameters non-mapping rejected
# ---------------------------------------------------------------------------
def scenario_parameters_non_mapping_rejected() -> None:
    for value in ("not-a-mapping", 123, ["a", "b"], None, object()):
        raised = False
        try:
            SkillContext(task="x", parameters=value)  # type: ignore[arg-type]
        except SkillContextError:
            raised = True
        check(
            raised,
            f"V3: parameters={value!r} (not a Mapping) raises "
            f"SkillContextError",
        )


# ---------------------------------------------------------------------------
# V4 -- metadata non-mapping rejected
# ---------------------------------------------------------------------------
def scenario_metadata_non_mapping_rejected() -> None:
    for value in ("not-a-mapping", 123, ["a", "b"], None, object()):
        raised = False
        try:
            SkillContext(task="x", metadata=value)  # type: ignore[arg-type]
        except SkillContextError:
            raised = True
        check(
            raised,
            f"V4: metadata={value!r} (not a Mapping) raises "
            f"SkillContextError",
        )


# ---------------------------------------------------------------------------
# V5 -- tool_context_factory non-callable, non-None rejected
# ---------------------------------------------------------------------------
def scenario_factory_non_callable_rejected() -> None:
    for value in ("not-callable", 123, ["a", "b"], {"k": "v"}, object()):
        raised = False
        try:
            SkillContext(
                task="x", tool_context_factory=value
            )  # type: ignore[arg-type]
        except SkillContextError:
            raised = True
        check(
            raised,
            f"V5: tool_context_factory={value!r} (not callable, not "
            f"None) raises SkillContextError",
        )


def scenario_factory_none_accepted() -> None:
    raised = False
    try:
        context = SkillContext(task="x", tool_context_factory=None)
    except SkillContextError:
        raised = True
    check(not raised, "V5: tool_context_factory=None is accepted")


def scenario_factory_callable_accepted() -> None:
    raised = False
    try:
        SkillContext(task="x", tool_context_factory=lambda **kw: kw)
    except SkillContextError:
        raised = True
    check(not raised, "V5: a callable tool_context_factory is accepted")


# ---------------------------------------------------------------------------
# V6 -- parameters frozen
# ---------------------------------------------------------------------------
def scenario_parameters_frozen() -> None:
    context = SkillContext(task="x", parameters={"k": "v"})

    check(
        isinstance(context.parameters, MappingProxyType),
        "V6: parameters is stored as a types.MappingProxyType",
    )

    raised = False
    try:
        context.parameters["k"] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "V6: mutating context.parameters directly raises TypeError")


# ---------------------------------------------------------------------------
# V7 -- metadata frozen
# ---------------------------------------------------------------------------
def scenario_metadata_frozen() -> None:
    context = SkillContext(task="x", metadata={"k": "v"})

    check(
        isinstance(context.metadata, MappingProxyType),
        "V7: metadata is stored as a types.MappingProxyType",
    )

    raised = False
    try:
        context.metadata["k"] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(raised, "V7: mutating context.metadata directly raises TypeError")


# ---------------------------------------------------------------------------
# V8 -- original parameters dict mutation has no effect
# ---------------------------------------------------------------------------
def scenario_parameters_copied_not_aliased() -> None:
    original = {"k": "v"}
    context = SkillContext(task="x", parameters=original)
    original["k"] = "mutated-outside"
    original["new_key"] = "added-outside"

    check(
        dict(context.parameters) == {"k": "v"},
        "V8: mutating the original parameters dict after construction "
        "does not affect SkillContext.parameters",
    )


# ---------------------------------------------------------------------------
# V9 -- original metadata dict mutation has no effect
# ---------------------------------------------------------------------------
def scenario_metadata_copied_not_aliased() -> None:
    original = {"k": "v"}
    context = SkillContext(task="x", metadata=original)
    original["k"] = "mutated-outside"
    original["new_key"] = "added-outside"

    check(
        dict(context.metadata) == {"k": "v"},
        "V9: mutating the original metadata dict after construction "
        "does not affect SkillContext.metadata",
    )


# ---------------------------------------------------------------------------
# V10 -- task identity preserved
# ---------------------------------------------------------------------------
def scenario_task_identity_preserved() -> None:
    class Unhashable:
        def __hash__(self):
            raise TypeError("unhashable")

    original_task = Unhashable()
    context = SkillContext(task=original_task)

    check(
        context.task is original_task,
        "V10: task object identity is preserved exactly",
    )


# ---------------------------------------------------------------------------
# V11 -- tool_context_factory storage
# ---------------------------------------------------------------------------
def scenario_factory_identity_preserved() -> None:
    def factory(**kwargs):
        return kwargs

    context = SkillContext(task="x", tool_context_factory=factory)
    check(
        context.tool_context_factory is factory,
        "V11: a callable tool_context_factory is stored by identity",
    )

    context_default = SkillContext(task="x")
    check(
        context_default.tool_context_factory is None,
        "V11: tool_context_factory defaults to None when omitted",
    )


# ---------------------------------------------------------------------------
# V12 -- hash with shared task reference
# ---------------------------------------------------------------------------
def scenario_hash_equal_task_reference() -> None:
    shared_task = {"symbol": "MSFT"}
    context_a = SkillContext(task=shared_task, parameters={"a": 1})
    context_b = SkillContext(
        task=shared_task,
        parameters={"b": 2},
        metadata={"c": 3},
        tool_context_factory=lambda **kw: kw,
    )

    check(
        hash(context_a) == hash(context_b),
        "V12: two SkillContext instances sharing the same task "
        "reference share the same hash",
    )
    check(
        context_a != context_b,
        "V12: instances with the same task but different "
        "parameters/metadata/factory are not equal",
    )


# ---------------------------------------------------------------------------
# V13 -- hash with different task reference / unhashable contents
# ---------------------------------------------------------------------------
def scenario_hash_different_task_reference() -> None:
    context_a = SkillContext(task={"symbol": "AAPL"})
    context_b = SkillContext(task={"symbol": "AAPL"})

    check(
        hash(context_a) != hash(context_b),
        "V13: two SkillContext instances with different task object "
        "identities (even with equal-by-value contents) do not share "
        "a hash",
    )


def scenario_hash_does_not_raise_with_unhashable_task() -> None:
    unhashable_task = {"nested": ["list", "of", "things"]}
    context = SkillContext(
        task=unhashable_task,
        parameters={"a": [1, 2, 3]},
        metadata={"b": {"nested": "dict"}},
    )

    raised = False
    try:
        hash(context)
    except TypeError:
        raised = True
    check(
        not raised,
        "V13: hash(context) does not raise despite an unhashable task "
        "and unhashable parameters/metadata contents",
    )


# ---------------------------------------------------------------------------
# V14 -- exact dataclass fields
# ---------------------------------------------------------------------------
def scenario_exact_dataclass_fields() -> None:
    field_names = {f.name for f in fields(SkillContext)}
    check(
        field_names == {"task", "parameters", "metadata", "tool_context_factory"},
        f"V14: SkillContext has exactly the four documented fields; "
        f"got {sorted(field_names)!r}",
    )


# ---------------------------------------------------------------------------
# V15 -- no extra public methods
# ---------------------------------------------------------------------------
def scenario_no_extra_public_methods() -> None:
    # Only genuinely public (non-dunder) names should be the declared
    # dataclass fields themselves -- no helper/convenience methods.
    public_non_dunder = [
        name for name in vars(SkillContext) if not name.startswith("_")
    ]
    check(
        set(public_non_dunder).issubset(
            {"task", "parameters", "metadata", "tool_context_factory"}
        ),
        f"V15: SkillContext exposes no public (non-dunder) methods "
        f"beyond its declared fields; found {public_non_dunder!r}",
    )


# ---------------------------------------------------------------------------
# V16 -- frozen dataclass
# ---------------------------------------------------------------------------
def scenario_frozen_dataclass() -> None:
    context = SkillContext(task="x")

    for attr, value in (
        ("task", "y"),
        ("parameters", {"a": 1}),
        ("metadata", {"b": 2}),
        ("tool_context_factory", lambda **kw: kw),
    ):
        raised = False
        try:
            setattr(context, attr, value)
        except FrozenInstanceError:
            raised = True
        check(
            raised,
            f"V16: reassigning '{attr}' after construction raises "
            f"FrozenInstanceError",
        )


# ---------------------------------------------------------------------------
# V17 -- SkillContextError subclasses AgentError
# ---------------------------------------------------------------------------
def scenario_skill_context_error_is_agent_error_subclass() -> None:
    check(
        issubclass(SkillContextError, AgentError),
        "V17: SkillContextError subclasses Core.exceptions.AgentError",
    )


# ---------------------------------------------------------------------------
# V18 -- forbidden surface absent
# ---------------------------------------------------------------------------
def scenario_forbidden_surface_absent() -> None:
    context = SkillContext(task="x")

    forbidden_attrs = [
        "workflow",
        "workflow_id",
        "execution_id",
        "session",
        "session_id",
        "runtime",
        "executor",
        "scheduler",
        "memory",
        "reflection",
        "learning",
        "event_bus",
        "provider",
        "database",
        "repository",
        "service",
        "agent",
        "host",
        "planner",
        "logger",
        "result",
        "status",
        "priority",
        "retry",
        "timeout",
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(SkillContext, attr) and not hasattr(context, attr),
            f"V18: SkillContext has no '{attr}' field/attribute",
        )


# ---------------------------------------------------------------------------
# V19 / V20 -- AST import inspection
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
    import Orchestration.skill_context as skill_context_module

    source = Path(skill_context_module.__file__).read_text(encoding="utf-8")
    roots = _collect_imported_module_roots(source)

    allowed_roots = {"dataclasses", "types", "typing", "Core", "__future__"}
    unexpected_roots = {root for root in roots if root not in allowed_roots}

    check(
        unexpected_roots == set(),
        f"V19: Orchestration/skill_context.py's imports (AST-verified) "
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
        "V19: the only 'Core' import is 'from Core.exceptions import "
        "AgentError'",
    )


def scenario_ast_no_orchestration_runtime_component_referenced() -> None:
    import Orchestration.skill_context as skill_context_module

    source = Path(skill_context_module.__file__).read_text(encoding="utf-8")
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
            f"V20: Orchestration/skill_context.py's AST-parsed import "
            f"names do not include '{symbol}'",
        )
        check(
            not hasattr(skill_context_module, symbol),
            f"V20: Orchestration.skill_context's module namespace does "
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
        scenario_factory_non_callable_rejected,
        scenario_factory_none_accepted,
        scenario_factory_callable_accepted,
        scenario_parameters_frozen,
        scenario_metadata_frozen,
        scenario_parameters_copied_not_aliased,
        scenario_metadata_copied_not_aliased,
        scenario_task_identity_preserved,
        scenario_factory_identity_preserved,
        scenario_hash_equal_task_reference,
        scenario_hash_different_task_reference,
        scenario_hash_does_not_raise_with_unhashable_task,
        scenario_exact_dataclass_fields,
        scenario_no_extra_public_methods,
        scenario_frozen_dataclass,
        scenario_skill_context_error_is_agent_error_subclass,
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
    print(f"PHASE 5 SPRINT 52 SKILL CONTEXT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())