"""
Phase 5 Sprint 47 proof suite -- the ``SkillResult`` value object.

Scope: dedicated regression suite for
``Orchestration.skill_result.SkillResult``/``SkillResultError`` only.
Nothing else exists in this module to test -- no serialization, no
builders, no helper/convenience methods.
``Orchestration.base_skill.BaseSkill`` (covered by
``Tests/test_stage_l46_base_skill.py``),
``Orchestration.skill_registry.SkillRegistry`` (covered by
``Tests/test_stage_l43_skill_registry.py``),
``Orchestration.skill_resolver.SkillResolver`` (covered by
``Tests/test_stage_l44_skill_resolver.py``), and
``Orchestration.executor.Executor`` (covered by
``Tests/test_stage_l28_sprint30_executor.py`` and
``Tests/test_stage_l45_executor_skill_resolution.py``) are all
untouched by this sprint and are not exercised here -- nothing about
this sprint wires ``SkillResult`` into any of them.

``SkillResult`` is a pure, minimal, frozen ``dataclass`` value object:
exactly four fields (``success``, ``output``, ``error``, ``metadata``),
no methods beyond ``__post_init__``/``__hash__``, and no additional
public surface of any kind. This suite proves the *absence* of that
extra surface area as much as it proves the presence of the
documented fields.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.

Invariant coverage:
    S1  -- SkillResult is a frozen dataclass -- reassigning any field
           after construction raises (dataclasses.FrozenInstanceError,
           a subclass of AttributeError).
    S2  -- default values: SkillResult(success=True) has output=None,
           error=None, and an empty metadata mapping.
    S3  -- explicit values: every field, when supplied explicitly, is
           stored and observable exactly as given (output and error
           are never coerced or transformed).
    S4  -- metadata is frozen: SkillResult.metadata is a
           types.MappingProxyType, and attempting to mutate it
           directly raises TypeError.
    S5  -- metadata is copied, not aliased: mutating the original dict
           passed in as 'metadata' after construction has no effect
           on SkillResult.metadata.
    S6  -- equality: two SkillResult instances are == only when all
           four fields match; changing any single field breaks
           equality.
    S7  -- hashing: two equal SkillResult instances share the same
           hash; hash(SkillResult(...)) does not raise despite
           metadata being unhashable; SkillResult is usable as a dict
           key / set member.
    S8  -- repr: repr(result) contains all four field names and their
           values in a readable, non-empty form.
    S9  -- validation: success must be a bool (non-bool -- including
           None, 0, 1, "true" -- raises SkillResultError); error must
           be None or a str (raises for non-str/non-None); metadata
           must be a Mapping (raises for non-Mapping); output is never
           validated (any value at all is accepted).
    S10 -- forbidden members absent: no duration, latency,
           token_usage, cost, provider, trace, logs, stacktrace,
           retry, warnings, events, memory, workflow, executor,
           scheduler, runtime, reflection, learning, agent, or host
           field/attribute anywhere on the class or an instance.
    S11 -- forbidden imports absent: Orchestration/skill_result.py
           contains no reference to BaseSkill, SkillRegistry,
           SkillResolver, Executor, WorkflowRuntime, WorkflowEngine,
           WorkflowExecutionCoordinator, Planner, Workflow, Task,
           Memory, LearningLoop, Reflection, AutonomousScheduler,
           AutonomousHost, AutonomousAgent, EventBus, or
           composition_root.
    S12 -- no runtime/workflow/execution knowledge: neither the class
           nor an instance carries any runtime-, workflow-, or
           execution-shaped attribute (no run/execute/start/tick
           method, no runtime/workflow/executor/host/scheduler
           attribute).
    S13 -- SkillResult defines no methods beyond __post_init__,
           __hash__, and the dataclass-generated dunder methods
           (__init__, __eq__, __repr__, __setattr__/__delattr__
           overrides from frozen=True) -- no helper, convenience,
           serialization, or builder method of any kind.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import MappingProxyType
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.skill_result import SkillResult, SkillResultError

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
# S1 -- frozen dataclass
# ---------------------------------------------------------------------------
def scenario_frozen_dataclass() -> None:
    result = SkillResult(success=True)

    for attr, value in (
        ("success", False),
        ("output", "something else"),
        ("error", "oops"),
        ("metadata", {"a": 1}),
    ):
        raised = False
        try:
            setattr(result, attr, value)
        except FrozenInstanceError:
            raised = True
        check(
            raised,
            f"S1: reassigning '{attr}' after construction raises "
            f"FrozenInstanceError",
        )


# ---------------------------------------------------------------------------
# S2 -- default values
# ---------------------------------------------------------------------------
def scenario_default_values() -> None:
    result = SkillResult(success=True)

    check(result.success is True, "S2: success stores the given value")
    check(result.output is None, "S2: output defaults to None")
    check(result.error is None, "S2: error defaults to None")
    check(
        isinstance(result.metadata, MappingProxyType) and len(result.metadata) == 0,
        "S2: metadata defaults to an empty (frozen) mapping",
    )


# ---------------------------------------------------------------------------
# S3 -- explicit values
# ---------------------------------------------------------------------------
def scenario_explicit_values() -> None:
    sentinel_output = {"rows": [1, 2, 3]}
    result = SkillResult(
        success=False,
        output=sentinel_output,
        error="something went wrong",
        metadata={"attempt": 2, "source": "unit-test"},
    )

    check(result.success is False, "S3: explicit success is stored exactly")
    check(
        result.output == sentinel_output,
        "S3: explicit output is stored exactly, uncoerced",
    )
    check(
        result.error == "something went wrong",
        "S3: explicit error is stored exactly",
    )
    check(
        dict(result.metadata) == {"attempt": 2, "source": "unit-test"},
        "S3: explicit metadata is stored exactly (as a frozen snapshot)",
    )


def scenario_output_accepts_any_value() -> None:
    for value in (None, 0, False, "", [], {}, (), object(), 3.14, [1, "a", None]):
        raised = False
        try:
            SkillResult(success=True, output=value)
        except SkillResultError:
            raised = True
        check(
            not raised,
            f"S3: output={value!r} is accepted without validation "
            f"(output is unconstrained)",
        )


# ---------------------------------------------------------------------------
# S4 -- metadata frozen
# ---------------------------------------------------------------------------
def scenario_metadata_is_frozen_mappingproxy() -> None:
    result = SkillResult(success=True, metadata={"k": "v"})

    check(
        isinstance(result.metadata, MappingProxyType),
        "S4: metadata is stored as a types.MappingProxyType",
    )

    raised = False
    try:
        result.metadata["k"] = "mutated"  # type: ignore[index]
    except TypeError:
        raised = True
    check(
        raised,
        "S4: attempting to mutate result.metadata directly raises "
        "TypeError",
    )

    raised_new_key = False
    try:
        result.metadata["new"] = 1  # type: ignore[index]
    except TypeError:
        raised_new_key = True
    check(
        raised_new_key,
        "S4: attempting to add a new key to result.metadata raises "
        "TypeError",
    )


# ---------------------------------------------------------------------------
# S5 -- metadata copied, not aliased
# ---------------------------------------------------------------------------
def scenario_metadata_is_copied_not_aliased() -> None:
    original = {"k": "v"}
    result = SkillResult(success=True, metadata=original)

    original["k"] = "changed-after-construction"
    original["new-key"] = "added-after-construction"

    check(
        dict(result.metadata) == {"k": "v"},
        "S5: mutating the original dict after construction has no "
        "effect on result.metadata",
    )


# ---------------------------------------------------------------------------
# S6 -- equality
# ---------------------------------------------------------------------------
def scenario_equality() -> None:
    a = SkillResult(success=True, output="x", error=None, metadata={"k": 1})
    b = SkillResult(success=True, output="x", error=None, metadata={"k": 1})
    check(a == b, "S6: two SkillResults with identical fields are equal")

    variants = [
        SkillResult(success=False, output="x", error=None, metadata={"k": 1}),
        SkillResult(success=True, output="y", error=None, metadata={"k": 1}),
        SkillResult(success=True, output="x", error="oops", metadata={"k": 1}),
        SkillResult(success=True, output="x", error=None, metadata={"k": 2}),
        SkillResult(success=True, output="x", error=None, metadata={}),
    ]
    labels = ["success", "output", "error", "metadata value", "metadata absent"]
    for variant, label in zip(variants, labels):
        check(
            a != variant,
            f"S6: changing only '{label}' breaks equality with the "
            f"original",
        )


# ---------------------------------------------------------------------------
# S7 -- hashing
# ---------------------------------------------------------------------------
def scenario_hashing() -> None:
    a = SkillResult(success=True, output="x", error=None, metadata={"k": 1})
    b = SkillResult(success=True, output="x", error=None, metadata={"k": 1})

    raised = False
    try:
        hash(a)
    except TypeError:
        raised = True
    check(
        not raised,
        "S7: hash(SkillResult(...)) does not raise, despite metadata "
        "being an unhashable MappingProxyType",
    )

    check(
        hash(a) == hash(b),
        "S7: two equal SkillResult instances share the same hash",
    )

    check(
        a in {a}, "S7: a SkillResult instance is usable as a set member"
    )

    lookup = {a: "found"}
    check(
        lookup.get(b) == "found",
        "S7: an equal-but-distinct SkillResult instance retrieves the "
        "same dict entry (hash/eq contract holds)",
    )


# ---------------------------------------------------------------------------
# S8 -- repr
# ---------------------------------------------------------------------------
def scenario_repr() -> None:
    result = SkillResult(
        success=True, output="payload", error=None, metadata={"a": 1}
    )
    text = repr(result)

    check(
        text.startswith("SkillResult("),
        "S8: repr(result) starts with 'SkillResult('",
    )
    for field_name in ("success", "output", "error", "metadata"):
        check(
            field_name in text,
            f"S8: repr(result) contains the field name '{field_name}'",
        )
    check(
        "True" in text and "payload" in text,
        "S8: repr(result) contains the actual field values",
    )


# ---------------------------------------------------------------------------
# S9 -- validation
# ---------------------------------------------------------------------------
def scenario_success_validation() -> None:
    for bad_value in (None, 0, 1, "true", "false", [], {}, 1.0):
        raised = False
        try:
            SkillResult(success=bad_value)  # type: ignore[arg-type]
        except SkillResultError:
            raised = True
        check(
            raised,
            f"S9: success={bad_value!r} (non-bool) raises "
            f"SkillResultError",
        )

    for good_value in (True, False):
        raised = False
        try:
            SkillResult(success=good_value)
        except SkillResultError:
            raised = True
        check(
            not raised,
            f"S9: success={good_value!r} (a real bool) does not raise",
        )


def scenario_error_validation() -> None:
    for bad_value in (123, 1.5, [], {}, object(), True):
        raised = False
        try:
            SkillResult(success=True, error=bad_value)  # type: ignore[arg-type]
        except SkillResultError:
            raised = True
        check(
            raised,
            f"S9: error={bad_value!r} (neither None nor str) raises "
            f"SkillResultError",
        )

    for good_value in (None, "", "an error message"):
        raised = False
        try:
            SkillResult(success=True, error=good_value)
        except SkillResultError:
            raised = True
        check(
            not raised,
            f"S9: error={good_value!r} (None or str) does not raise",
        )


def scenario_metadata_validation() -> None:
    for bad_value in ("not-a-mapping", 123, ["a", "b"], None, object()):
        raised = False
        try:
            SkillResult(success=True, metadata=bad_value)  # type: ignore[arg-type]
        except SkillResultError:
            raised = True
        check(
            raised,
            f"S9: metadata={bad_value!r} (not a Mapping) raises "
            f"SkillResultError",
        )

    for good_value in ({}, {"k": "v"}, MappingProxyType({"k": "v"})):
        raised = False
        try:
            SkillResult(success=True, metadata=good_value)
        except SkillResultError:
            raised = True
        check(
            not raised,
            f"S9: metadata={good_value!r} (a real Mapping) does not "
            f"raise",
        )


def scenario_skill_result_error_is_agent_error_subclass() -> None:
    raised_as_agent_error = False
    try:
        SkillResult(success="not-a-bool")  # type: ignore[arg-type]
    except AgentError:
        raised_as_agent_error = True

    check(
        raised_as_agent_error,
        "S9: a SkillResultError from invalid construction can be "
        "caught as AgentError",
    )


# ---------------------------------------------------------------------------
# S10 -- forbidden members absent
# ---------------------------------------------------------------------------
def scenario_forbidden_members_absent() -> None:
    result = SkillResult(success=True)

    forbidden_attrs = [
        "duration",
        "latency",
        "token_usage",
        "cost",
        "provider",
        "trace",
        "logs",
        "stacktrace",
        "retry",
        "warnings",
        "events",
        "memory",
        "workflow",
        "executor",
        "scheduler",
        "runtime",
        "reflection",
        "learning",
        "agent",
        "host",
    ]
    for attr in forbidden_attrs:
        check(
            not hasattr(SkillResult, attr) and not hasattr(result, attr),
            f"S10: SkillResult has no '{attr}' field/attribute",
        )

    field_names = {f.name for f in fields(SkillResult)}
    check(
        field_names == {"success", "output", "error", "metadata"},
        f"S10: SkillResult's dataclass fields are exactly "
        f"{{'success', 'output', 'error', 'metadata'}}; got "
        f"{field_names!r}",
    )


# ---------------------------------------------------------------------------
# S11 -- forbidden imports absent
# ---------------------------------------------------------------------------
def scenario_forbidden_imports_absent() -> None:
    import Orchestration.skill_result as skill_result_module

    source = Path(skill_result_module.__file__).read_text(encoding="utf-8")

    forbidden_symbols = [
        "BaseSkill",
        "SkillRegistry",
        "SkillResolver",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "WorkflowExecutionCoordinator",
        "Planner",
        "Workflow",
        "Task",
        "Memory",
        "LearningLoop",
        "Reflection",
        "AutonomousScheduler",
        "AutonomousHost",
        "AutonomousAgent",
        "EventBus",
        "composition_root",
    ]
    for symbol in forbidden_symbols:
        check(
            f"import {symbol}" not in source and f"{symbol}(" not in source,
            f"S11: Orchestration/skill_result.py contains no reference "
            f"to '{symbol}'",
        )

    for symbol in (
        "BaseSkill",
        "SkillRegistry",
        "SkillResolver",
        "Executor",
    ):
        check(
            not hasattr(skill_result_module, symbol),
            f"S11: Orchestration.skill_result's module namespace does "
            f"not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# S12 -- no runtime / workflow / execution knowledge
# ---------------------------------------------------------------------------
def scenario_no_runtime_workflow_execution_knowledge() -> None:
    result = SkillResult(success=True)

    for attr in (
        "run",
        "execute",
        "start",
        "tick",
        "runtime",
        "workflow",
        "workflow_engine",
        "executor",
        "host",
        "scheduler",
        "agent",
        "event_bus",
    ):
        check(
            not hasattr(SkillResult, attr) and not hasattr(result, attr),
            f"S12: neither SkillResult nor an instance carries a "
            f"'{attr}' attribute/method",
        )


# ---------------------------------------------------------------------------
# S13 -- no methods beyond __post_init__/__hash__ (+ dataclass-generated)
# ---------------------------------------------------------------------------
def scenario_no_extra_methods() -> None:
    allowed_dunders = {
        "__init__",
        "__repr__",
        "__eq__",
        "__hash__",
        "__setattr__",
        "__delattr__",
        "__post_init__",
        # standard object/dataclass machinery every class carries
        "__class__",
        "__dict__",
        "__doc__",
        "__module__",
        "__weakref__",
        "__dataclass_fields__",
        "__dataclass_params__",
        "__match_args__",
    }

    field_names = {f.name for f in fields(SkillResult)}
    own_members = set(vars(SkillResult).keys())
    unexpected = {
        name
        for name in own_members
        if name not in allowed_dunders
        and name not in field_names
        and not (name.startswith("__") and name.endswith("__"))
    }

    check(
        unexpected == set(),
        f"S13: SkillResult defines no members beyond dataclass "
        f"machinery and __post_init__/__hash__; unexpected: "
        f"{sorted(unexpected)!r}",
    )

    check(
        callable(SkillResult.__dict__.get("__post_init__")),
        "S13: SkillResult defines its own __post_init__",
    )
    check(
        callable(SkillResult.__dict__.get("__hash__")),
        "S13: SkillResult defines its own __hash__",
    )

    public_methods = {
        name
        for name in dir(SkillResult)
        if not name.startswith("_")
        and callable(getattr(SkillResult, name, None))
    }
    check(
        public_methods == set(),
        f"S13: SkillResult exposes no public (non-dunder) methods; "
        f"got {sorted(public_methods)!r}",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_frozen_dataclass,
        scenario_default_values,
        scenario_explicit_values,
        scenario_output_accepts_any_value,
        scenario_metadata_is_frozen_mappingproxy,
        scenario_metadata_is_copied_not_aliased,
        scenario_equality,
        scenario_hashing,
        scenario_repr,
        scenario_success_validation,
        scenario_error_validation,
        scenario_metadata_validation,
        scenario_skill_result_error_is_agent_error_subclass,
        scenario_forbidden_members_absent,
        scenario_forbidden_imports_absent,
        scenario_no_runtime_workflow_execution_knowledge,
        scenario_no_extra_methods,
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
    print(f"PHASE 5 SPRINT 47 SKILL RESULT RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())