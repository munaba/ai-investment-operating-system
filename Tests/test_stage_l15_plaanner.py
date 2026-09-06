"""
Stage L15 proof suite -- Planner Test Suite (Phase 1, Step 8).

Scope (per the Step 8 briefing): this is a dedicated regression suite for
``Orchestration.planner.GoalPlanner`` only. It verifies the implementation
already completed in Steps 1-7 (constructor, ``Goal``/``PlanStep``/
``ExecutionPlan``, ``build_plan``, ``execute_plan``, ``accumulate_context``,
``translate_metadata``). No new Planner features and no architectural
changes are introduced here -- production code is touched only if a test
exposes a genuine implementation bug.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l11_runtime_analysis_pipeline.py``,
``test_stage_l12_production_runtime_activation.py``, and
``test_stage_l13_service_skill.py``: tiny fake ``ServiceSkill``-compatible
objects (a fake ``BaseService`` wrapped by the real ``ServiceSkill``, or a
bare object exposing the same ``metadata``/``execute`` shape), a global
pass/fail counter, and a ``main()`` runner.

Explicitly NOT tested here (belongs to previous/other stages): Runtime,
Executor, Sandbox, ToolRegistry, Observation, Memory, Reflection,
StockAgent, RuntimeAnalysisPipeline, AnalysisPipeline.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.planner import (
    ExecutionPlan,
    Goal,
    GoalPlanner,
    GoalPlannerError,
    PlanStep,
)
from Orchestration.service_skill import ServiceSkill, SkillMetadata
from Services.base_service import BaseService
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult

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
# Fixtures -- tiny fake ServiceSkill objects, exactly like previous stages.
# ---------------------------------------------------------------------------
class _FakeService(BaseService):
    """Minimal BaseService: configurable success/failure/exception, and an
    optional callback so a test can inspect exactly what metadata it
    received (proving accumulation/translation actually reached it).
    """

    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        raise_exc: bool = False,
        data: Optional[Dict[str, Any]] = None,
        data_fn=None,
        non_dict_data: bool = False,
    ) -> None:
        self._name = name
        self._fail = fail
        self._raise_exc = raise_exc
        self._data = data if data is not None else {}
        self._data_fn = data_fn
        self._non_dict_data = non_dict_data
        self.received_metadata: Optional[Dict[str, Any]] = None
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"fake {self._name}"

    @property
    def category(self) -> str:
        return "test"

    def execute(self, context: ServiceContext) -> ServiceResult:
        self.call_count += 1
        self.received_metadata = dict(context.metadata)

        if self._raise_exc:
            raise RuntimeError(f"Simulated unexpected exception in {self._name}")

        if self._fail:
            return ServiceResult.fail(
                error=ValueError(f"Simulated business failure in {self._name}"),
                message=f"{self._name} failed",
            )

        if self._non_dict_data:
            return ServiceResult.ok(data="not-a-dict")

        data = self._data_fn(context) if self._data_fn is not None else self._data
        return ServiceResult.ok(data=data, message=f"{self._name} ok")

    def health_check(self) -> bool:
        return not self._fail


def _make_skill(
    name: str,
    *,
    required_inputs=(),
    optional_inputs=(),
    produced_outputs=(),
    fail: bool = False,
    raise_exc: bool = False,
    data: Optional[Dict[str, Any]] = None,
    data_fn=None,
    non_dict_data: bool = False,
) -> "tuple[ServiceSkill, _FakeService]":
    """Build a real ``ServiceSkill`` wrapping a tiny ``_FakeService`` --
    the same pattern ``test_stage_l13_service_skill.py`` uses. Returns the
    skill plus the underlying fake so a test can inspect
    ``received_metadata`` / ``call_count``.
    """
    fake = _FakeService(
        name,
        fail=fail,
        raise_exc=raise_exc,
        data=data,
        data_fn=data_fn,
        non_dict_data=non_dict_data,
    )
    metadata = SkillMetadata(
        service_name=name,
        required_inputs=required_inputs,
        optional_inputs=optional_inputs,
        produced_outputs=produced_outputs,
    )
    return ServiceSkill(service=fake, metadata=metadata), fake


# ---------------------------------------------------------------------------
# Group 1 -- Construction
# ---------------------------------------------------------------------------
def scenario_construction() -> None:
    skill_a, _ = _make_skill("service_a", produced_outputs=("out_a",))
    skill_b, _ = _make_skill("service_b", required_inputs=("out_a",))
    service_skills = {"service_a": skill_a, "service_b": skill_b}

    planner = GoalPlanner(service_skills)
    check(isinstance(planner, GoalPlanner), "GoalPlanner constructs successfully")

    check(
        planner._service_skills is service_skills,  # noqa: SLF001 -- deliberate white-box check
        "GoalPlanner stores the exact service_skills mapping (same object, not a copy)",
    )

    check(
        planner._service_skills["service_a"] is skill_a  # noqa: SLF001
        and planner._service_skills["service_b"] is skill_b,  # noqa: SLF001
        "GoalPlanner does not duplicate ServiceSkill objects -- same instances held",
    )


# ---------------------------------------------------------------------------
# Group 2 -- build_plan()
# ---------------------------------------------------------------------------
def scenario_build_plan_empty_metadata_zero_input_only() -> None:
    zero_input_skill, _ = _make_skill("zero_input", produced_outputs=("zi_out",))
    needs_input_skill, _ = _make_skill("needs_input", required_inputs=("something_else",))
    planner = GoalPlanner({"zero_input": zero_input_skill, "needs_input": needs_input_skill})

    plan = planner.build_plan(Goal(metadata={}))
    step_names = [s.service_name for s in plan.steps]

    check(
        step_names == ["zero_input"],
        "build_plan: empty metadata produces only reachable zero-input skills",
    )


def scenario_build_plan_dependency_expansion() -> None:
    a, _ = _make_skill("a", produced_outputs=("x",))
    b, _ = _make_skill("b", required_inputs=("x",), produced_outputs=("y",))
    c, _ = _make_skill("c", required_inputs=("y",), produced_outputs=("z",))
    planner = GoalPlanner({"a": a, "b": b, "c": c})

    plan = planner.build_plan(Goal(metadata={}))
    step_names = [s.service_name for s in plan.steps]

    check(
        step_names == ["a", "b", "c"],
        "build_plan: dependency expansion works across multiple fixed-point rounds",
    )


def scenario_build_plan_deterministic_ordering() -> None:
    # Two skills satisfied in the very same round must come out in
    # service_name sort order, not insertion/dict order.
    zebra, _ = _make_skill("zebra_service", produced_outputs=("z_out",))
    alpha, _ = _make_skill("alpha_service", produced_outputs=("a_out",))
    planner = GoalPlanner({"zebra_service": zebra, "alpha_service": alpha})

    plan = planner.build_plan(Goal(metadata={}))
    step_names = [s.service_name for s in plan.steps]

    check(
        step_names == ["alpha_service", "zebra_service"],
        "build_plan: skills satisfied in the same round are ordered deterministically "
        "by service_name, not by dict insertion order",
    )


def scenario_build_plan_unreachable_skills_excluded() -> None:
    reachable, _ = _make_skill("reachable", produced_outputs=("r_out",))
    unreachable, _ = _make_skill("unreachable", required_inputs=("never_produced",))
    planner = GoalPlanner({"reachable": reachable, "unreachable": unreachable})

    plan = planner.build_plan(Goal(metadata={}))
    step_names = [s.service_name for s in plan.steps]

    check(
        "unreachable" not in step_names and step_names == ["reachable"],
        "build_plan: unreachable skills (never-satisfiable required_inputs) are excluded, "
        "not raised",
    )


def scenario_build_plan_identical_goal_identical_plan() -> None:
    a, _ = _make_skill("a", produced_outputs=("x",))
    b, _ = _make_skill("b", required_inputs=("x",))
    planner = GoalPlanner({"a": a, "b": b})

    goal = Goal(metadata={MetadataKeys.TICKER: "BBCA.JK"})
    plan1 = planner.build_plan(goal)
    plan2 = planner.build_plan(goal)

    check(
        plan1.steps == plan2.steps,
        "build_plan: identical Goal -> identical ExecutionPlan (same steps, repeatably)",
    )
    check(
        plan1 is not plan2,
        "build_plan: repeated calls return distinct ExecutionPlan objects, not a cached one",
    )


def scenario_build_plan_plan_step_stores_service_name_only() -> None:
    a, _ = _make_skill("a", required_inputs=("in1", "in2"))
    planner = GoalPlanner({"a": a})

    plan = planner.build_plan(Goal(metadata={"in1": 1, "in2": 2}))

    check(len(plan.steps) == 1, "sanity: exactly one step planned")
    step = plan.steps[0]
    check(
        isinstance(step, PlanStep) and step.service_name == "a",
        "build_plan: PlanStep.service_name is the skill's service_name",
    )
    check(
        step.inputs == ("in1", "in2"),
        "build_plan: PlanStep stores the skill's required_inputs verbatim",
    )


def scenario_build_plan_execution_plan_is_frozen() -> None:
    a, _ = _make_skill("a", produced_outputs=("x",))
    planner = GoalPlanner({"a": a})
    plan = planner.build_plan(Goal(metadata={}))

    frozen_plan_error = False
    try:
        plan.steps = ()  # type: ignore[misc]
    except Exception:  # noqa: BLE001 -- dataclass(frozen=True) raises FrozenInstanceError
        frozen_plan_error = True
    check(frozen_plan_error, "build_plan: ExecutionPlan is frozen -- cannot reassign .steps")

    frozen_goal_error = False
    try:
        plan.goal.metadata = {}  # type: ignore[misc]
    except Exception:  # noqa: BLE001
        frozen_goal_error = True
    check(frozen_goal_error, "build_plan: Goal (nested in ExecutionPlan) is also frozen")

    frozen_step_error = False
    a2, _ = _make_skill("a2", produced_outputs=("y",))
    planner2 = GoalPlanner({"a2": a2})
    plan2 = planner2.build_plan(Goal(metadata={}))
    try:
        plan2.steps[0].service_name = "changed"  # type: ignore[misc]
    except Exception:  # noqa: BLE001
        frozen_step_error = True
    check(frozen_step_error, "build_plan: PlanStep (nested in ExecutionPlan) is also frozen")


# ---------------------------------------------------------------------------
# Group 3 -- execute_plan()
# ---------------------------------------------------------------------------
def scenario_execute_plan_order() -> None:
    call_order: List[str] = []

    def _tracker(name: str):
        def _fn(context: ServiceContext) -> Dict[str, Any]:
            call_order.append(name)
            return {}
        return _fn

    a, fake_a = _make_skill("a", produced_outputs=("x",), data_fn=_tracker("a"))
    b, fake_b = _make_skill("b", required_inputs=("x",), data_fn=_tracker("b"))
    planner = GoalPlanner({"a": a, "b": b})

    plan = planner.build_plan(Goal(metadata={}))
    planner.execute_plan(plan)

    check(call_order == ["a", "b"], "execute_plan: executes steps in plan order")


def scenario_execute_plan_returns_list_of_service_results() -> None:
    a, _ = _make_skill("a", produced_outputs=("x",))
    planner = GoalPlanner({"a": a})
    plan = planner.build_plan(Goal(metadata={}))

    results = planner.execute_plan(plan)

    check(isinstance(results, list), "execute_plan: returns a List")
    check(
        len(results) == 1 and isinstance(results[0], ServiceResult),
        "execute_plan: each element is a ServiceResult",
    )


def scenario_execute_plan_business_failures_do_not_abort() -> None:
    a, fake_a = _make_skill("a", produced_outputs=("x",), fail=True)
    b, fake_b = _make_skill("b", required_inputs=("x",))
    planner = GoalPlanner({"a": a, "b": b})

    # "a" fails its business logic but still declares produced_outputs, so
    # static build_plan satisfiability for "b" is unaffected (build_plan
    # never executes anything -- see Group 2).
    plan = ExecutionPlan(
        goal=Goal(metadata={}),
        steps=(PlanStep(service_name="a"), PlanStep(service_name="b")),
    )

    results = planner.execute_plan(plan)

    check(
        len(results) == 2 and results[0].success is False,
        "execute_plan: a business failure (ServiceResult.fail()) is collected, not raised",
    )
    check(
        fake_b.call_count == 1,
        "execute_plan: a business failure does NOT abort execution -- the next step still runs",
    )
    check(
        results[1].success is True,
        "execute_plan: the step after a business failure still executes normally",
    )


def scenario_execute_plan_missing_service_skill_raises() -> None:
    planner = GoalPlanner({})
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="ghost"),))

    raised = False
    try:
        planner.execute_plan(plan)
    except GoalPlannerError:
        raised = True
    check(
        raised,
        "execute_plan: a PlanStep with no corresponding ServiceSkill raises GoalPlannerError",
    )


def scenario_execute_plan_unexpected_exception_wrapped() -> None:
    a, _ = _make_skill("a", raise_exc=True)
    planner = GoalPlanner({"a": a})
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=(PlanStep(service_name="a"),))

    raised_as_planner_error = False
    raised_as_raw_runtime_error = False
    try:
        planner.execute_plan(plan)
    except GoalPlannerError:
        raised_as_planner_error = True
    except RuntimeError:
        raised_as_raw_runtime_error = True

    check(
        raised_as_planner_error and not raised_as_raw_runtime_error,
        "execute_plan: an unexpected exception from ServiceSkill.execute() is wrapped as "
        "GoalPlannerError, not left to propagate raw",
    )


def scenario_execute_plan_empty_plan_returns_empty_list() -> None:
    planner = GoalPlanner({})
    plan = ExecutionPlan(goal=Goal(metadata={}), steps=())

    results = planner.execute_plan(plan)

    check(results == [], "execute_plan: an empty plan returns []")


# ---------------------------------------------------------------------------
# Group 4 -- accumulate_context()
# ---------------------------------------------------------------------------
def scenario_accumulate_context_successful_dict_merges() -> None:
    planner = GoalPlanner({})
    ctx = {"a": 1}
    result = ServiceResult.ok(data={"b": 2})

    merged = planner.accumulate_context(ctx, result)

    check(merged == {"a": 1, "b": 2}, "accumulate_context: successful dict result merges in")


def scenario_accumulate_context_failed_result_ignored() -> None:
    planner = GoalPlanner({})
    ctx = {"a": 1}
    result = ServiceResult.fail(error=ValueError("nope"))

    merged = planner.accumulate_context(ctx, result)

    check(merged == {"a": 1}, "accumulate_context: a failed ServiceResult is ignored (no-op)")


def scenario_accumulate_context_non_dict_ignored() -> None:
    planner = GoalPlanner({})
    ctx = {"a": 1}
    result = ServiceResult.ok(data="not-a-dict")

    merged = planner.accumulate_context(ctx, result)

    check(merged == {"a": 1}, "accumulate_context: non-dict data is ignored (no-op)")


def scenario_accumulate_context_later_key_wins() -> None:
    planner = GoalPlanner({})
    ctx = {"a": 1, "shared": "old"}
    result = ServiceResult.ok(data={"shared": "new", "b": 2})

    merged = planner.accumulate_context(ctx, result)

    check(
        merged == {"a": 1, "shared": "new", "b": 2},
        "accumulate_context: merge is later-key-wins (result.data overwrites same-named keys)",
    )


def scenario_accumulate_context_original_never_mutated() -> None:
    planner = GoalPlanner({})
    ctx = {"a": 1}
    ctx_copy = dict(ctx)
    result = ServiceResult.ok(data={"a": 999, "b": 2})

    merged = planner.accumulate_context(ctx, result)

    check(ctx == ctx_copy, "accumulate_context: the original context dict is never mutated")
    check(merged is not ctx, "accumulate_context: a new dict is returned, not the same object")


# ---------------------------------------------------------------------------
# Group 5 -- translate_metadata()
# ---------------------------------------------------------------------------
def scenario_translate_metadata_price_to_entry_price_only_for_risk_service() -> None:
    planner = GoalPlanner({})
    ctx = {MetadataKeys.PRICE: 15000}

    risk_step = PlanStep(service_name="risk_management_service")
    translated = planner.translate_metadata(risk_step, ctx)

    check(
        translated.get(MetadataKeys.ENTRY_PRICE) == 15000,
        "translate_metadata: PRICE -> ENTRY_PRICE copy applies for risk_management_service",
    )

    other_step = PlanStep(service_name="some_other_service")
    translated_other = planner.translate_metadata(other_step, ctx)

    check(
        MetadataKeys.ENTRY_PRICE not in translated_other,
        "translate_metadata: PRICE -> ENTRY_PRICE copy only applies to risk_management_service, "
        "never other services",
    )


def scenario_translate_metadata_price_preserved() -> None:
    planner = GoalPlanner({})
    ctx = {MetadataKeys.PRICE: 15000}
    step = PlanStep(service_name="risk_management_service")

    translated = planner.translate_metadata(step, ctx)

    check(
        translated.get(MetadataKeys.PRICE) == 15000,
        "translate_metadata: PRICE itself is preserved (both keys present after translation)",
    )


def scenario_translate_metadata_entry_price_never_overwritten() -> None:
    planner = GoalPlanner({})
    ctx = {MetadataKeys.PRICE: 15000, MetadataKeys.ENTRY_PRICE: 14000}
    step = PlanStep(service_name="risk_management_service")

    translated = planner.translate_metadata(step, ctx)

    check(
        translated.get(MetadataKeys.ENTRY_PRICE) == 14000,
        "translate_metadata: an already-present ENTRY_PRICE is never overwritten by PRICE",
    )


def scenario_translate_metadata_other_services_unchanged() -> None:
    planner = GoalPlanner({})
    ctx = {MetadataKeys.PRICE: 15000, "some_key": "some_value"}
    step = PlanStep(service_name="stock_service")

    translated = planner.translate_metadata(step, ctx)

    check(
        translated == ctx,
        "translate_metadata: for a non-risk_management_service step, the dict is passed "
        "through unchanged (aside from being a copy)",
    )


def scenario_translate_metadata_returns_new_dict() -> None:
    planner = GoalPlanner({})
    ctx = {MetadataKeys.PRICE: 15000}
    step = PlanStep(service_name="risk_management_service")

    translated = planner.translate_metadata(step, ctx)

    check(translated is not ctx, "translate_metadata: returned dict is always a new object")


def scenario_translate_metadata_input_never_mutated() -> None:
    planner = GoalPlanner({})
    ctx = {MetadataKeys.PRICE: 15000}
    ctx_copy = dict(ctx)
    step = PlanStep(service_name="risk_management_service")

    planner.translate_metadata(step, ctx)

    check(ctx == ctx_copy, "translate_metadata: the input accumulated_context is never mutated")


# ---------------------------------------------------------------------------
# Group 6 -- Integration (tiny fake graph: stock_service -> risk_management_service
#             -> dummy_service)
# ---------------------------------------------------------------------------
def _build_integration_graph():
    stock_skill, fake_stock = _make_skill(
        "stock_service",
        required_inputs=(),
        produced_outputs=(MetadataKeys.PRICE,),
        data={MetadataKeys.PRICE: 15000},
    )

    def _risk_data_fn(context: ServiceContext) -> Dict[str, Any]:
        entry_price = context.get_metadata(MetadataKeys.ENTRY_PRICE, None)
        return {
            MetadataKeys.ENTRY_PRICE: entry_price,
            MetadataKeys.STOP_LOSS_PRICE: entry_price - 500 if entry_price else None,
        }

    risk_skill, fake_risk = _make_skill(
        "risk_management_service",
        required_inputs=(MetadataKeys.PRICE,),
        produced_outputs=(MetadataKeys.ENTRY_PRICE, MetadataKeys.STOP_LOSS_PRICE),
        data_fn=_risk_data_fn,
    )

    def _dummy_data_fn(context: ServiceContext) -> Dict[str, Any]:
        return {"dummy_saw_stop_loss_price": context.get_metadata(MetadataKeys.STOP_LOSS_PRICE)}

    dummy_skill, fake_dummy = _make_skill(
        "dummy_service",
        required_inputs=(MetadataKeys.STOP_LOSS_PRICE,),
        produced_outputs=("dummy_saw_stop_loss_price",),
        data_fn=_dummy_data_fn,
    )

    planner = GoalPlanner(
        {
            "stock_service": stock_skill,
            "risk_management_service": risk_skill,
            "dummy_service": dummy_skill,
        }
    )
    return planner, fake_stock, fake_risk, fake_dummy


def scenario_integration_full_graph() -> None:
    planner, fake_stock, fake_risk, fake_dummy = _build_integration_graph()

    goal = Goal(metadata={})
    original_metadata_snapshot = dict(goal.metadata)

    plan = planner.build_plan(goal)
    step_names = [s.service_name for s in plan.steps]
    check(
        step_names == ["stock_service", "risk_management_service", "dummy_service"],
        "integration: tiny fake graph plans in dependency order "
        "(stock -> risk_management -> dummy)",
    )

    results = planner.execute_plan(plan)
    check(
        all(r.success for r in results) and len(results) == 3,
        "integration: all three steps execute successfully",
    )

    check(
        fake_risk.received_metadata is not None
        and fake_risk.received_metadata.get(MetadataKeys.ENTRY_PRICE) == 15000,
        "integration: translation works -- risk_management_service actually received "
        "ENTRY_PRICE translated from PRICE",
    )

    check(
        fake_dummy.received_metadata is not None
        and fake_dummy.received_metadata.get(MetadataKeys.STOP_LOSS_PRICE) == 14500,
        "integration: accumulation works -- downstream dummy_service receives the "
        "accumulated context (STOP_LOSS_PRICE produced two steps earlier)",
    )
    check(
        results[-1].data == {"dummy_saw_stop_loss_price": 14500},
        "integration: downstream service's own output reflects the accumulated context "
        "it received",
    )

    check(
        goal.metadata == original_metadata_snapshot,
        "integration: goal.metadata is never changed by build_plan or execute_plan",
    )


# ---------------------------------------------------------------------------
# Group 7 -- Regression
# ---------------------------------------------------------------------------
def scenario_regression_build_plan_deterministic() -> None:
    planner, _, _, _ = _build_integration_graph()
    goal = Goal(metadata={})

    plan1 = planner.build_plan(goal)
    plan2 = planner.build_plan(goal)

    check(
        [s.service_name for s in plan1.steps] == [s.service_name for s in plan2.steps],
        "regression: build_plan still produces the same deterministic output across repeated "
        "calls",
    )


def scenario_regression_execute_plan_collects_all_results() -> None:
    planner, _, _, _ = _build_integration_graph()
    plan = planner.build_plan(Goal(metadata={}))

    results = planner.execute_plan(plan)

    check(
        len(results) == len(plan.steps),
        "regression: execute_plan still collects exactly one ServiceResult per plan step",
    )


def scenario_regression_translate_metadata_unrelated_services() -> None:
    planner = GoalPlanner({})
    ctx = {MetadataKeys.PRICE: 15000}

    unrelated_step = PlanStep(service_name="stock_service")
    translated = planner.translate_metadata(unrelated_step, ctx)

    check(
        MetadataKeys.ENTRY_PRICE not in translated,
        "regression: translate_metadata still does not affect unrelated (non-risk) services",
    )


def scenario_regression_accumulate_context_identical_behavior() -> None:
    planner = GoalPlanner({})
    ctx = {"a": 1}
    result = ServiceResult.ok(data={"b": 2})

    merged1 = planner.accumulate_context(ctx, result)
    merged2 = planner.accumulate_context(ctx, result)

    check(
        merged1 == merged2 == {"a": 1, "b": 2},
        "regression: accumulate_context still behaves identically across repeated calls",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        # Group 1
        scenario_construction,
        # Group 2
        scenario_build_plan_empty_metadata_zero_input_only,
        scenario_build_plan_dependency_expansion,
        scenario_build_plan_deterministic_ordering,
        scenario_build_plan_unreachable_skills_excluded,
        scenario_build_plan_identical_goal_identical_plan,
        scenario_build_plan_plan_step_stores_service_name_only,
        scenario_build_plan_execution_plan_is_frozen,
        # Group 3
        scenario_execute_plan_order,
        scenario_execute_plan_returns_list_of_service_results,
        scenario_execute_plan_business_failures_do_not_abort,
        scenario_execute_plan_missing_service_skill_raises,
        scenario_execute_plan_unexpected_exception_wrapped,
        scenario_execute_plan_empty_plan_returns_empty_list,
        # Group 4
        scenario_accumulate_context_successful_dict_merges,
        scenario_accumulate_context_failed_result_ignored,
        scenario_accumulate_context_non_dict_ignored,
        scenario_accumulate_context_later_key_wins,
        scenario_accumulate_context_original_never_mutated,
        # Group 5
        scenario_translate_metadata_price_to_entry_price_only_for_risk_service,
        scenario_translate_metadata_price_preserved,
        scenario_translate_metadata_entry_price_never_overwritten,
        scenario_translate_metadata_other_services_unchanged,
        scenario_translate_metadata_returns_new_dict,
        scenario_translate_metadata_input_never_mutated,
        # Group 6
        scenario_integration_full_graph,
        # Group 7
        scenario_regression_build_plan_deterministic,
        scenario_regression_execute_plan_collects_all_results,
        scenario_regression_translate_metadata_unrelated_services,
        scenario_regression_accumulate_context_identical_behavior,
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
    print(f"STAGE L15 PLANNER RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())