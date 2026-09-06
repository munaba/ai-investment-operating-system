"""
Stage L13 proof suite -- Granular Skills (Phase 1: give Runtime the
*capability* to call any one of the 11 Services individually).

Scope (per the LOCKED Stage L13 baseline / approved Diff-Level Plan
FINAL):
  - Orchestration/service_skill.py (NEW):
      * SkillMetadata -- purely declarative dataclass (service_name,
        required_inputs, optional_inputs, produced_outputs). No methods,
        no validation, no behavior.
      * SKILL_METADATA_BY_SERVICE -- literal transcription of the L13
        audit's per-Service dependency graph, one entry per Service.
      * ServiceSkill -- one generic, non-specialized wrapper class (used
        11 times, never subclassed): builds a ServiceContext, calls
        service.execute(context), passthrough health_check(), exposes
        metadata/tool_name. No merging, no dependency resolution, no
        output transformation, no validation.
  - Core/composition_root.py (additive only):
      * ApplicationGraph gains one new field, `service_skills`.
      * New `_build_service_skills()` factory, called from
        `build_application()` after `_build_analysis_pipeline()`.
      * Wraps the SAME Service instances already held by
        `service_registry` (no new Service instance constructed) and
        registers each as a standing Tool under `"skill.<service_name>"`.
      * Nothing about `agent`'s own construction/call path changes --
        StockAgent still runs through RuntimeAnalysisPipeline exactly as
        Stage L12 left it, unchanged.

Explicitly NOT changed by this stage (locked):
Core/analysis_pipeline.py, Core/runtime.py, Agents/executor.py,
Agents/sandbox.py, Agents/tool_registry.py,
Orchestration/runtime_analysis_pipeline.py, Agents/stock_agent.py,
every one of the 11 Service implementations, Services/base_service.py,
Services/service_context.py, Services/service_result.py.

Cakupan skenario:
  1. Parity: ServiceSkill.execute(...) produces byte-for-byte the same
     ServiceResult a direct service.execute(context) call would, for an
     equivalent ServiceContext.
  2. health_check() is pure passthrough to the wrapped Service.
  3. Tool registration: composition root registers exactly one standing
     Tool per Service under a stable "skill.<service_name>" name, and
     that Tool's handler actually runs the wrapped Service when invoked
     the way ToolRegistry/GenericSandbox invoke any Tool handler
     (positional/keyword call, no Runtime detour required for this
     proof).
  4. Composition wiring: `ApplicationGraph.service_skills` wraps the
     exact same Service *instances* already in `service_registry` (no
     duplicate construction), and the production StockAgent call path
     (`agent.analysis_pipeline` / `agent.runtime_analysis_pipeline`) is
     untouched by this stage.
  5. Debt R3 (GenericSandbox's str(result) fallback) is unchanged and
     still reachable: a ServiceSkill's Tool handler returns a
     ServiceResult, which is not JSON-serializable -- proven here by
     actually running it through GenericSandbox and observing the
     stringified fallback, not just asserted by comment.
  6. Debt R4 (no context accumulation) is unchanged: two independent
     ServiceSkill.execute() calls never share state, and a Service that
     depends on a prior step's output (e.g. technical_score_service
     needing "harga") still fails when called standalone via its skill
     without that key explicitly supplied -- proving ServiceSkill does
     NOT reimplement AnalysisPipeline's SS5 context-accumulation.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.tool_registry import Tool, ToolRegistry
from Core.composition_root import ApplicationGraph, build_application
from Orchestration.service_skill import (
    SKILL_METADATA_BY_SERVICE,
    ServiceSkill,
    SkillMetadata,
)
from Agents.sandbox import GenericSandbox
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
# Fixtures
# ---------------------------------------------------------------------------
class _FakeService(BaseService):
    """Minimal BaseService: returns a fixed ServiceResult, no I/O.

    Mirrors technical_score_service's real shape closely enough to prove
    R4 (§6 below): it requires MetadataKeys.PRICE ("harga") to succeed,
    exactly like the real TechnicalScoreService.
    """

    def __init__(self, name: str, *, fail: bool = False, require_price: bool = False) -> None:
        self._name = name
        self._fail = fail
        self._require_price = require_price

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
        if self._fail:
            raise RuntimeError(f"Simulated failure in {self._name}")
        if self._require_price and context.get_metadata(MetadataKeys.PRICE, None) is None:
            return ServiceResult.fail(
                error=ValueError("Missing required 'harga' in context metadata"),
                message="No price was provided.",
            )
        ticker = context.get_metadata(MetadataKeys.TICKER, "UNKNOWN")
        return ServiceResult.ok(data={MetadataKeys.TICKER: ticker, "value": f"{self._name}-ok"})

    def health_check(self) -> bool:
        return not self._fail


_FAKE_METADATA = SkillMetadata(
    service_name="fake_service",
    required_inputs=(MetadataKeys.TICKER,),
    optional_inputs=(),
    produced_outputs=(MetadataKeys.TICKER, "value"),
)


# ---------------------------------------------------------------------------
# 1. Parity: ServiceSkill.execute(...) vs. calling the Service directly.
# ---------------------------------------------------------------------------
def scenario_parity_wrapper_vs_direct_service() -> None:
    service = _FakeService("fake_service")
    skill = ServiceSkill(service=service, metadata=_FAKE_METADATA)

    direct_context = ServiceContext(
        agent_name="agent-x",
        provider_name="provider-x",
        request_id="req-1",
        user_input="hello",
        metadata={MetadataKeys.TICKER: "BBCA.JK"},
    )
    direct_result = service.execute(direct_context)

    skill_result = skill.execute(
        user_input="hello",
        metadata={MetadataKeys.TICKER: "BBCA.JK"},
        agent_name="agent-x",
        provider_name="provider-x",
        request_id="req-1",
    )

    check(
        skill_result.success == direct_result.success and skill_result.data == direct_result.data,
        "ServiceSkill.execute() produces the same ServiceResult.data as calling service.execute() directly",
    )
    check(
        skill_result.message == direct_result.message,
        "ServiceSkill.execute() produces the same ServiceResult.message as calling service.execute() directly",
    )

    failing_service = _FakeService("fake_service", fail=True)
    failing_skill = ServiceSkill(service=failing_service, metadata=_FAKE_METADATA)
    try:
        failing_skill.execute(metadata={MetadataKeys.TICKER: "BBCA.JK"})
        raised = False
    except RuntimeError:
        raised = True
    check(
        raised,
        "ServiceSkill.execute() does not swallow an exception the wrapped Service raises (no try/except added)",
    )


def scenario_execute_defaults_request_id_when_omitted() -> None:
    service = _FakeService("fake_service")
    skill = ServiceSkill(service=service, metadata=_FAKE_METADATA)
    result_one = skill.execute(metadata={MetadataKeys.TICKER: "BBCA.JK"})
    result_two = skill.execute(metadata={MetadataKeys.TICKER: "BBCA.JK"})
    check(
        result_one.success and result_two.success,
        "ServiceSkill.execute() succeeds with only 'metadata' supplied (agent_name/provider_name/request_id all optional)",
    )


# ---------------------------------------------------------------------------
# 2. health_check() passthrough.
# ---------------------------------------------------------------------------
def scenario_health_check_passthrough() -> None:
    healthy = ServiceSkill(service=_FakeService("fake_service"), metadata=_FAKE_METADATA)
    unhealthy = ServiceSkill(service=_FakeService("fake_service", fail=True), metadata=_FAKE_METADATA)

    check(healthy.health_check() is True, "ServiceSkill.health_check() returns True when the wrapped Service is healthy")
    check(
        unhealthy.health_check() is False,
        "ServiceSkill.health_check() returns False when the wrapped Service reports unhealthy (pure passthrough, no aggregation)",
    )


# ---------------------------------------------------------------------------
# 3. Tool registration: composition root registers one stable Tool per
#    Service, and that Tool's handler actually runs the wrapped Service.
# ---------------------------------------------------------------------------
def scenario_tool_registration_and_invocation() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-l13-test",
        provider_kind="gemini",
        agent_name="stock_agent_l13_test",
    )

    # L13 baseline was 11 (one per AnalysisPipeline Service). Task 3
    # ("Second Skill / Cross-Skill Reflection Foundation") registered a
    # 12th, independent Service (notification_service, outside
    # AnalysisPipeline) and gave it its own SKILL_METADATA_BY_SERVICE
    # entry -- this count is updated to match, per Task 3's own
    # regression update; the assertion just below (set equality against
    # SKILL_METADATA_BY_SERVICE) is unchanged and still the real proof
    # that every registered Service with metadata gets wrapped.
    check(
        len(graph.service_skills) == 12,
        "Exactly 12 ServiceSkill instances are built (11 pipeline Services + Task 3's notification_service)",
    )
    check(
        set(graph.service_skills) == set(SKILL_METADATA_BY_SERVICE),
        "graph.service_skills is keyed by exactly the Service names covered by SKILL_METADATA_BY_SERVICE",
    )

    for service_name, skill in graph.service_skills.items():
        expected_tool_name = f"skill.{service_name}"
        check(
            skill.tool_name == expected_tool_name,
            f"ServiceSkill.tool_name for '{service_name}' is the stable name '{expected_tool_name}'",
        )
        check(
            graph.tool_registry.exists(expected_tool_name),
            f"Tool '{expected_tool_name}' is registered in the shared tool_registry",
        )

    tool: Tool = graph.tool_registry.get("skill.stock_service")
    result = tool.handler(metadata={MetadataKeys.TICKER: "BBCA.JK", MetadataKeys.PERIOD: "1y"})
    check(
        isinstance(result, ServiceResult),
        "Invoking the registered 'skill.stock_service' Tool's handler runs the real StockService and returns a ServiceResult",
    )


def scenario_idempotent_across_repeated_build_application_calls() -> None:
    ToolRegistry.reset()
    build_application(provider_name="fake-provider-l13-idem-1", agent_name="stock_agent_l13_idem_1")
    try:
        build_application(provider_name="fake-provider-l13-idem-2", agent_name="stock_agent_l13_idem_2")
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    check(
        not raised,
        "Calling build_application() twice in the same process does not raise ToolAlreadyRegisteredError for skill Tools",
    )


# ---------------------------------------------------------------------------
# 4. Composition wiring: same Service instances, StockAgent path untouched.
# ---------------------------------------------------------------------------
def scenario_composition_wiring_shares_instances_and_leaves_stockagent_untouched() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-l13-wiring",
        agent_name="stock_agent_l13_wiring",
    )

    for service_name, skill in graph.service_skills.items():
        registry_instance = graph.service_registry.get(service_name)
        check(
            skill._service is registry_instance,  # noqa: SLF001 -- deliberate white-box check
            f"ServiceSkill for '{service_name}' wraps the SAME instance already in ServiceRegistry (no new Service constructed)",
        )

    check(
        graph.agent.runtime_analysis_pipeline is graph.runtime_analysis_pipeline,
        "StockAgent's runtime_analysis_pipeline wiring is exactly as Stage L12 left it (L13 did not touch it)",
    )
    check(
        type(graph.agent.analysis_pipeline).__name__ == "AnalysisPipeline",
        "graph.agent.analysis_pipeline is still the bare AnalysisPipeline (StockAgent's own path is untouched by L13)",
    )
    check(
        not hasattr(graph.agent, "service_skills"),
        "StockAgent itself has no service_skills attribute -- L13 did not modify StockAgent's constructor",
    )


def scenario_skill_metadata_is_declarative_only() -> None:
    metadata = SKILL_METADATA_BY_SERVICE["technical_score_service"]
    check(
        MetadataKeys.PRICE in metadata.required_inputs,
        "SkillMetadata for technical_score_service literally lists 'harga' (PRICE) as a required_input, per the L13 audit",
    )
    check(
        set(metadata.produced_outputs) == {MetadataKeys.TECHNICAL_SCORE},
        "SkillMetadata for technical_score_service literally lists 'technical_score' as its only produced_output",
    )
    public_attrs = [attr for attr in dir(SkillMetadata) if not attr.startswith("_")]
    behavioral_attrs = [
        attr
        for attr in public_attrs
        if attr not in ("service_name", "required_inputs", "optional_inputs", "produced_outputs")
    ]
    check(
        behavioral_attrs == [],
        "SkillMetadata exposes no attributes/methods beyond its four declarative fields (no validator/resolver/scheduler)",
    )


# ---------------------------------------------------------------------------
# 5. Debt R3 -- GenericSandbox's str(result) fallback is unchanged and
#    still reachable through a skill Tool's handler.
# ---------------------------------------------------------------------------
def scenario_debt_r3_generic_sandbox_fallback_still_applies() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-l13-r3",
        agent_name="stock_agent_l13_r3",
    )
    sandbox = GenericSandbox(tool_registry=graph.tool_registry)

    intent_payload = {
        "tool_name": "skill.stock_service",
        "args": [],
        "kwargs": {"metadata": {MetadataKeys.TICKER: "BBCA.JK"}},
    }

    class _FakeIntentEvent:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

    import json

    intent_event = _FakeIntentEvent(json.dumps(intent_payload).encode("utf-8"))
    encoded = sandbox.execute(intent_event)
    decoded = json.loads(encoded.decode("utf-8"))

    check(
        decoded.get("status") == "ok",
        "GenericSandbox.execute() runs the 'skill.stock_service' Tool successfully",
    )
    check(
        isinstance(decoded.get("result"), str) and decoded["result"].startswith("ServiceResult("),
        "R3 (unfixed, LOCKED as debt): a ServiceResult returned by a skill Tool is not JSON-serializable, "
        "so GenericSandbox's existing str(result) fallback still applies -- proven, not just asserted",
    )


# ---------------------------------------------------------------------------
# 6. Debt R4 -- no context accumulation across independent skill calls.
# ---------------------------------------------------------------------------
def scenario_debt_r4_no_context_accumulation() -> None:
    price_dependent_service = _FakeService("price_dependent_service", require_price=True)
    price_dependent_metadata = SkillMetadata(
        service_name="price_dependent_service",
        required_inputs=(MetadataKeys.PRICE,),
        optional_inputs=(),
        produced_outputs=(),
    )
    skill = ServiceSkill(service=price_dependent_service, metadata=price_dependent_metadata)

    result_without_price = skill.execute(metadata={MetadataKeys.TICKER: "BBCA.JK"})
    check(
        result_without_price.success is False,
        "R4 (unfixed, LOCKED as debt): calling a skill standalone without a prior step's output "
        "(e.g. 'harga') fails exactly like calling the Service directly -- ServiceSkill does not "
        "reimplement AnalysisPipeline's SS5 context accumulation",
    )

    producer_skill = ServiceSkill(service=_FakeService("stock_service"), metadata=_FAKE_METADATA)
    producer_result = producer_skill.execute(metadata={MetadataKeys.TICKER: "BBCA.JK"})
    check(producer_result.success, "sanity: the producer skill call itself succeeds")

    result_after_unrelated_call = skill.execute(metadata={MetadataKeys.TICKER: "BBCA.JK"})
    check(
        result_after_unrelated_call.success is False,
        "R4 (unfixed, LOCKED as debt): a prior, unrelated ServiceSkill.execute() call leaves no trace -- "
        "no shared/accumulated context exists between independent skill calls",
    )


def main() -> int:
    scenarios = [
        scenario_parity_wrapper_vs_direct_service,
        scenario_execute_defaults_request_id_when_omitted,
        scenario_health_check_passthrough,
        scenario_tool_registration_and_invocation,
        scenario_idempotent_across_repeated_build_application_calls,
        scenario_composition_wiring_shares_instances_and_leaves_stockagent_untouched,
        scenario_skill_metadata_is_declarative_only,
        scenario_debt_r3_generic_sandbox_fallback_still_applies,
        scenario_debt_r4_no_context_accumulation,
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
    print(f"STAGE L13 SERVICE SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())