"""
Stage L18 proof suite -- Reflection (Phase 1, milestone: regression suite).

Scope: dedicated regression suite for ``Orchestration.reflection.ReflectionError``,
``Orchestration.reflection.ReflectionRecord``, and
``Orchestration.reflection.Reflector`` only. Verifies the implementation
already shipped in ``Orchestration/reflection.py`` -- this suite does not
add, extend, or change any Reflection behavior. No real analysis logic, no
``ReflectionStore``, no Composition Root wiring, no automatic invocation,
no cross-Skill reflection -- all explicitly out of scope for L18 (locked,
see ``Docs/l18_handover.md`` and
``Docs/l18_closure_implementation_spec.md``).

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l11_runtime_analysis_pipeline.py`` through
``test_stage_l17_memory.py``: a global pass/fail counter, plain
``MemoryRecord``/``Observation`` fixtures built directly (no
``MemoryStore``/``MemoryRecorder`` -- see the dependency-direction note
below), and a ``main()`` runner.

Invariant coverage (I1-I8, per the frozen implementation spec):
    I1 -- ReflectionRecord is frozen (field reassignment raises
          FrozenInstanceError).
    I2 -- Reflector.reflect() raises ReflectionError (not some other
          exception) for a non-tuple input.
    I3 -- ReflectionRecord.source_record_count == len(records) for a
          non-trivial batch (0, 1, many).
    I4 -- Reflector is genuinely stateless across repeated calls.
    I5 -- Reflector never imports/constructs/references MemoryStore
          (static/architectural guard -- see the explicit epistemic
          limitation noted on that scenario below).
    I6 -- An unexpected exception during construction is wrapped as
          ReflectionError with the original chained via `from exc`.
    I7 -- records=() is a valid input (source_record_count == 0, no
          error) -- strict on type, not on emptiness.
    I8 -- ReflectionRecord retains no reference to the input MemoryRecord
          tuple -- only source_record_count/reflected_at exist as fields.

Explicitly NOT tested here (belongs to other stages / other milestones,
or is out of scope for L18 Phase 1): Runtime, Executor, Sandbox,
ToolRegistry, StockAgent, RuntimeAnalysisPipeline, AnalysisPipeline,
GoalPlanner, ObservationRecorder's own behavior (covered by
test_stage_l16_observation.py), MemoryRecord/MemoryStore/MemoryRecorder's
own behavior (covered by test_stage_l17_memory.py -- this file only uses
MemoryRecord as a plain fixture value, it never exercises MemoryStore or
MemoryRecorder). No real reflection/analysis logic, no persistence, no
Composition Root wiring, no retrieval/ranking/search API.

Dependency-direction note (LOCKED, mirrors the same pattern already
governing Observation -> Memory): scenarios here import ``MemoryRecord``
directly from ``Orchestration.memory`` only to build fixture input for
``Reflector.reflect()``. They deliberately never import or construct
``MemoryStore``/``MemoryRecorder`` -- doing so would defeat the very
decoupling that invariant I5 exists to prove.
"""

from __future__ import annotations

import dataclasses
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import AgentError
from Orchestration.memory import MemoryRecord
from Orchestration.observation import Observation
from Orchestration.reflection import ReflectionError, ReflectionRecord, Reflector

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


def _empty_observation() -> Observation:
    return Observation(
        goal_metadata={},
        plan_step_names=(),
        steps=(),
        aggregated_outputs={},
    )


def _memory_record() -> MemoryRecord:
    return MemoryRecord(observation=_empty_observation())


def _memory_records(count: int) -> tuple:
    return tuple(_memory_record() for _ in range(count))


# ---------------------------------------------------------------------------
# Group 1 -- ReflectionError
# ---------------------------------------------------------------------------
def scenario_reflection_error_is_agent_error() -> None:
    check(
        issubclass(ReflectionError, AgentError),
        "ReflectionError subclasses Core.exceptions.AgentError, same "
        "convention as GoalPlannerError/ObservationError/MemoryError",
    )

    err = ReflectionError("boom")
    check(isinstance(err, Exception), "ReflectionError is constructible with a plain message")


# ---------------------------------------------------------------------------
# Group 2 -- ReflectionRecord (value shape) -- I1, I8
# ---------------------------------------------------------------------------
def scenario_reflection_record_is_frozen_dataclass() -> None:
    # I1: ReflectionRecord must be immutable -- field reassignment raises
    # FrozenInstanceError, not silently succeed.
    record = Reflector().reflect(())

    check(dataclasses.is_dataclass(record), "ReflectionRecord is a dataclass")

    frozen = False
    try:
        record.source_record_count = 999  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        frozen = True
    check(
        frozen,
        "I1: ReflectionRecord is frozen -- field reassignment raises "
        "FrozenInstanceError",
    )


def scenario_reflection_record_holds_only_two_fields() -> None:
    # I8: ReflectionRecord must not retain the input MemoryRecord tuple (or
    # any other storage-shaped copy of it) -- only source_record_count and
    # reflected_at exist as fields on the instance.
    field_names = {f.name for f in dataclasses.fields(ReflectionRecord)}
    check(
        field_names == {"source_record_count", "reflected_at"},
        "I8: ReflectionRecord declares exactly two fields "
        "(source_record_count, reflected_at) -- no field retains the "
        "input MemoryRecord tuple",
    )


def scenario_reflection_record_does_not_expose_input_records() -> None:
    # I8, behavioral half: even via __dict__, no attribute on a constructed
    # ReflectionRecord holds anything MemoryRecord-shaped.
    records = _memory_records(3)
    record = Reflector().reflect(records)

    check(
        not any(isinstance(v, MemoryRecord) for v in vars(record).values()),
        "I8: a constructed ReflectionRecord holds no attribute referencing "
        "any MemoryRecord from its input batch",
    )
    check(
        not any(isinstance(v, tuple) and v == records for v in vars(record).values()),
        "I8: a constructed ReflectionRecord does not retain a copy of the "
        "input records tuple under any attribute",
    )


# ---------------------------------------------------------------------------
# Group 3 -- Reflector.reflect() type validation -- I2, I7
# ---------------------------------------------------------------------------
def scenario_reflect_rejects_list_with_reflection_error() -> None:
    # I2: a non-tuple input must raise ReflectionError specifically, not
    # TypeError or any other exception type.
    raised_type = None
    try:
        Reflector().reflect([_memory_record()])  # type: ignore[arg-type]
    except ReflectionError:
        raised_type = ReflectionError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is ReflectionError,
        "I2: Reflector.reflect() raises ReflectionError (not TypeError or "
        "any other exception) when given a list instead of a tuple",
    )


def scenario_reflect_rejects_none_with_reflection_error() -> None:
    raised_type = None
    try:
        Reflector().reflect(None)  # type: ignore[arg-type]
    except ReflectionError:
        raised_type = ReflectionError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is ReflectionError,
        "I2: Reflector.reflect() raises ReflectionError when given None",
    )


def scenario_reflect_rejects_generator_with_reflection_error() -> None:
    raised_type = None
    try:
        Reflector().reflect((r for r in _memory_records(2)))  # type: ignore[arg-type]
    except ReflectionError:
        raised_type = ReflectionError
    except Exception as exc:  # noqa: BLE001
        raised_type = type(exc)

    check(
        raised_type is ReflectionError,
        "I2: Reflector.reflect() raises ReflectionError when given a "
        "generator instead of a tuple",
    )


def scenario_reflect_accepts_empty_tuple_as_valid_input() -> None:
    # I7: strict on type, not on emptiness -- records=() is valid, not an
    # error, and yields source_record_count == 0.
    record = Reflector().reflect(())

    check(
        isinstance(record, ReflectionRecord),
        "I7: Reflector.reflect(()) succeeds -- an empty tuple is not "
        "rejected",
    )
    check(
        record.source_record_count == 0,
        "I7: Reflector.reflect(()) yields source_record_count == 0",
    )


# ---------------------------------------------------------------------------
# Group 4 -- Reflector.reflect() count correctness -- I3
# ---------------------------------------------------------------------------
def scenario_reflect_count_matches_single_record_batch() -> None:
    record = Reflector().reflect(_memory_records(1))
    check(
        record.source_record_count == 1,
        "I3: source_record_count == len(records) for a one-record batch",
    )


def scenario_reflect_count_matches_multi_record_batch() -> None:
    record = Reflector().reflect(_memory_records(5))
    check(
        record.source_record_count == 5,
        "I3: source_record_count == len(records) for a five-record batch",
    )


def scenario_reflect_reflected_at_is_timezone_aware_datetime() -> None:
    import datetime as _dt

    record = Reflector().reflect(())
    check(
        isinstance(record.reflected_at, _dt.datetime) and record.reflected_at.tzinfo is not None,
        "reflected_at is a timezone-aware datetime (UTC), matching the "
        "module's stated construction via datetime.now(timezone.utc)",
    )


# ---------------------------------------------------------------------------
# Group 5 -- Reflector statelessness -- I4
# ---------------------------------------------------------------------------
def scenario_reflector_is_reusable_across_calls_with_independent_results() -> None:
    reflector = Reflector()

    record1 = reflector.reflect(_memory_records(2))
    record2 = reflector.reflect(_memory_records(7))

    check(
        record1.source_record_count == 2 and record2.source_record_count == 7,
        "I4: the same Reflector instance produces independent, correct "
        "ReflectionRecords across repeated calls with different batch sizes",
    )


def scenario_reflector_has_no_instance_attributes() -> None:
    # I4: Reflector must be genuinely stateless -- no instance attribute
    # leaking across calls. A freshly constructed instance should carry no
    # per-instance state at all.
    reflector = Reflector()
    check(
        vars(reflector) == {},
        "I4: a Reflector instance holds no instance attributes (vars() is "
        "empty), confirming it is safe to reuse across calls",
    )


def scenario_reflector_repeated_calls_do_not_affect_each_other() -> None:
    # I4: calling reflect() with a large batch must not influence the
    # result of a subsequent call with a different batch on the same
    # instance (no accumulation, no caching of prior input).
    reflector = Reflector()
    reflector.reflect(_memory_records(50))
    record = reflector.reflect(_memory_records(3))

    check(
        record.source_record_count == 3,
        "I4: a prior large-batch call does not leak into or influence a "
        "subsequent call's result on the same Reflector instance",
    )


# ---------------------------------------------------------------------------
# Group 6 -- Reflector never touches MemoryStore -- I5
# ---------------------------------------------------------------------------
def scenario_reflection_module_does_not_import_memory_store() -> None:
    # I5 (architectural guard against the current shape of the code --
    # NOT a formal proof that this coupling can never be introduced in the
    # future; see Docs/l18_closure_implementation_spec.md Section 2 for the
    # explicit epistemic limitation of this check). This proves that, on
    # this commit, Orchestration.reflection does not import, construct, or
    # reference MemoryStore anywhere in its module namespace. A future
    # change that adds such an import will only be caught the next time
    # this test is run -- it is a regression check, not a runtime-enforced
    # structural guarantee.
    import Orchestration.reflection as reflection_module

    module_symbols = vars(reflection_module)
    check(
        "MemoryStore" not in module_symbols,
        "I5 (architectural guard, not a formal future-proof guarantee): "
        "Orchestration.reflection's module namespace does not contain a "
        "MemoryStore symbol",
    )


def scenario_reflector_has_no_store_attribute_or_method() -> None:
    # I5, continued (same epistemic limitation as above): Reflector itself
    # exposes no attribute or method that could hold or accept a
    # MemoryStore. As of Sprint 39, Reflector also exposes attach()
    # (subscribing to an EventBus) -- that is not a store/get/add-shaped
    # method either (it takes an EventBus, not a MemoryStore, and stores
    # nothing on self; see test_stage_l39_reflection_events.py for its
    # own dedicated coverage). Only reflect and attach are public; the
    # event handler _on_runtime_event stays private.
    reflector = Reflector()
    public_members = [name for name in dir(reflector) if not name.startswith("_")]

    check(
        sorted(public_members) == ["attach", "reflect"],
        "I5 (architectural guard, not a formal future-proof guarantee): "
        "Reflector exposes exactly two public members (reflect, attach) "
        "-- no store/get/add-shaped method that could reference "
        "MemoryStore",
    )


# ---------------------------------------------------------------------------
# Group 7 -- Exception wrapping for unexpected failures -- I6
# ---------------------------------------------------------------------------
def scenario_unexpected_construction_failure_is_wrapped_as_reflection_error() -> None:
    # I6: an unexpected exception during construction of the
    # ReflectionRecord (outside the explicit type-check path) must be
    # caught and re-raised as ReflectionError, chained via `from exc`, never
    # propagated raw. We force this by monkeypatching the `datetime` class
    # used inside the module to raise on .now(), then restoring it
    # unconditionally.
    import datetime as _dt

    class _ExplodingDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            raise RuntimeError("simulated clock failure")

    import Orchestration.reflection as reflection_module

    original_datetime = reflection_module.datetime
    raised_type = None
    raised_cause = None
    try:
        reflection_module.datetime = _ExplodingDatetime
        try:
            Reflector().reflect(())
        except ReflectionError as exc:
            raised_type = ReflectionError
            raised_cause = exc.__cause__
        except Exception as exc:  # noqa: BLE001
            raised_type = type(exc)
    finally:
        reflection_module.datetime = original_datetime

    check(
        raised_type is ReflectionError,
        "I6: an unexpected failure during ReflectionRecord construction is "
        "wrapped as ReflectionError, not propagated raw",
    )
    check(
        isinstance(raised_cause, RuntimeError),
        "I6: the wrapped ReflectionError chains the original exception via "
        "`from exc` (accessible as __cause__)",
    )


def scenario_reflector_still_works_after_a_prior_wrapped_failure() -> None:
    # I4 + I6 combined sanity check: a Reflector instance that previously
    # raised a wrapped ReflectionError must still behave correctly on a
    # subsequent, ordinary call -- no lingering broken state.
    reflector = Reflector()

    try:
        reflector.reflect([_memory_record()])  # type: ignore[arg-type]  # triggers I2 path
    except ReflectionError:
        pass

    record = reflector.reflect(_memory_records(4))
    check(
        record.source_record_count == 4,
        "a Reflector instance recovers cleanly and produces a correct "
        "result after a prior call raised ReflectionError",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_reflection_error_is_agent_error,
        # Group 2
        scenario_reflection_record_is_frozen_dataclass,
        scenario_reflection_record_holds_only_two_fields,
        scenario_reflection_record_does_not_expose_input_records,
        # Group 3
        scenario_reflect_rejects_list_with_reflection_error,
        scenario_reflect_rejects_none_with_reflection_error,
        scenario_reflect_rejects_generator_with_reflection_error,
        scenario_reflect_accepts_empty_tuple_as_valid_input,
        # Group 4
        scenario_reflect_count_matches_single_record_batch,
        scenario_reflect_count_matches_multi_record_batch,
        scenario_reflect_reflected_at_is_timezone_aware_datetime,
        # Group 5
        scenario_reflector_is_reusable_across_calls_with_independent_results,
        scenario_reflector_has_no_instance_attributes,
        scenario_reflector_repeated_calls_do_not_affect_each_other,
        # Group 6
        scenario_reflection_module_does_not_import_memory_store,
        scenario_reflector_has_no_store_attribute_or_method,
        # Group 7
        scenario_unexpected_construction_failure_is_wrapped_as_reflection_error,
        scenario_reflector_still_works_after_a_prior_wrapped_failure,
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
    print(f"STAGE L18 REFLECTION RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())