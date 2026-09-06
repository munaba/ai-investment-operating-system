"""
Task 3 proof suite -- Second Skill / Cross-Skill Reflection Foundation.

Scope (per the approved Task 3 objective, additive only, no new
abstraction): ``Services.notification_service.NotificationService`` --
already fully implemented and independently tested
(``Tests/integration_test.py``), but previously unregistered/unwired
(see the L13-era note in ``Orchestration/service_skill.py`` and
``Services/metadata_keys.py``) -- is now:

  1. Constructed and registered into the shared ``ServiceRegistry``
     (``Core.composition_root._build_notification_service``), separately
     from and without modifying ``_build_analysis_pipeline`` or
     ``AnalysisPipeline``.
  2. Given a declarative ``SkillMetadata`` entry in the existing
     ``SKILL_METADATA_BY_SERVICE`` dict (``Orchestration/service_skill.py``),
     exactly the same shape as the 11 pipeline entries.
  3. Wrapped into a ``ServiceSkill`` and registered as a standing
     ``"skill.notification_service"`` Tool by the existing, *unmodified*
     ``_build_service_skills()`` -- it discovers the new Service/metadata
     pair purely because both are now present, with no new branch or
     special case added for it.
  4. Automatically included in ``ApplicationGraph.goal_planner``'s
     ``service_skills`` mapping -- ``_build_goal_planner()`` is also
     unmodified; ``GoalPlanner`` itself gained no new code for this.

This is the entire scope of Task 3: no ``BaseSkill``, no second registry,
no new field on ``ApplicationGraph``, no change to
``GoalPlanner``/``Reflector``/``ObservationRecorder``/``MemoryStore``, no
change to ``StockAgent``/``RuntimeAnalysisPipeline``/``AnalysisPipeline``.
This file proves the wiring only -- it does not re-test
``NotificationService``'s own business logic (already covered by
``Tests/integration_test.py``) or re-audit any closed stage.

Follows the same scenario-based, no-pytest, no-external-mocks style as
``test_stage_l11_runtime_analysis_pipeline.py`` through
``test_stage_l18_reflection.py``: a global pass/fail counter, real
``build_application()`` graphs, and a ``main()`` runner.

Network note: every scenario here that invokes
``NotificationService.execute()`` (directly or through its Tool/Skill)
does so only via the metadata-validation failure paths (missing
``channel``/``message``), which fail before any HTTP client is resolved
or any network call is attempted -- this suite performs no network I/O,
matching the hermetic construction guarantee ``build_application()``
itself already documents.
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
from Orchestration.service_skill import SKILL_METADATA_BY_SERVICE, ServiceSkill
from Services.metadata_keys import MetadataKeys
from Services.notification_service import NotificationService
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
# 1. SkillMetadata: declarative entry exists and matches the wrapped
#    Service's own execute() contract, same shape as the 11 pipeline
#    entries (no new fields, no new semantics).
# ---------------------------------------------------------------------------
def scenario_skill_metadata_entry_is_declarative_and_matches_service() -> None:
    metadata = SKILL_METADATA_BY_SERVICE.get("notification_service")
    check(metadata is not None, "SKILL_METADATA_BY_SERVICE has an entry for 'notification_service'")
    assert metadata is not None  # narrows type for the checks below

    check(
        metadata.service_name == "notification_service",
        "notification_service's SkillMetadata.service_name matches its own key",
    )
    check(
        set(metadata.required_inputs) == {MetadataKeys.CHANNEL, MetadataKeys.MESSAGE},
        "required_inputs is exactly {CHANNEL, MESSAGE} -- the two fields NotificationService.execute() "
        "always validates regardless of channel",
    )
    check(
        {MetadataKeys.WEBHOOK_URL, MetadataKeys.TELEGRAM_BOT_TOKEN, MetadataKeys.TELEGRAM_CHAT_ID}.issubset(
            set(metadata.optional_inputs)
        ),
        "channel-specific credentials (webhook_url/telegram_bot_token/telegram_chat_id) are listed as "
        "optional_inputs, not required_inputs -- same 'conditional requirement is not encoded' nuance "
        "already documented for fundamental_service/pattern_service",
    )
    check(
        metadata.produced_outputs == (MetadataKeys.CHANNEL, "status", "response"),
        "produced_outputs matches NotificationService.execute()'s actual ServiceResult.data shape "
        "({'channel', 'status', 'response'})",
    )
    check(
        len(SKILL_METADATA_BY_SERVICE) == 12,
        "SKILL_METADATA_BY_SERVICE now has 12 entries: the 11 L13 pipeline Services + notification_service",
    )


# ---------------------------------------------------------------------------
# 2. Composition Root: NotificationService is registered into
#    ServiceRegistry, independent of AnalysisPipeline/_build_analysis_pipeline.
# ---------------------------------------------------------------------------
def scenario_notification_service_registered_independently_of_pipeline() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-task3-registration",
        provider_kind="gemini",
        agent_name="stock_agent_task3_registration",
    )

    check(
        graph.service_registry.exists("notification_service"),
        "NotificationService is registered in the shared ServiceRegistry",
    )
    registered = graph.service_registry.get("notification_service")
    check(
        isinstance(registered, NotificationService),
        "the registered 'notification_service' entry is a real NotificationService instance",
    )

    # AnalysisPipeline itself is untouched: it still only knows its
    # original 11 constructor arguments, and StockAgent's own call path
    # (agent.analysis_pipeline) does not expose notification_service.
    pipeline = graph.agent.analysis_pipeline
    check(
        not hasattr(pipeline, "notification_service"),
        "AnalysisPipeline gained no 'notification_service' attribute -- it remains the unmodified 11-step pipeline",
    )


# ---------------------------------------------------------------------------
# 3. Composition Root: the existing, unmodified _build_service_skills()
#    wraps notification_service exactly like the 11 pipeline Services,
#    and registers its standing Tool.
# ---------------------------------------------------------------------------
def scenario_notification_service_wrapped_and_registered_as_skill_tool() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-task3-skill",
        provider_kind="gemini",
        agent_name="stock_agent_task3_skill",
    )

    check(
        "notification_service" in graph.service_skills,
        "graph.service_skills contains a 'notification_service' entry",
    )
    skill = graph.service_skills["notification_service"]
    check(isinstance(skill, ServiceSkill), "the 'notification_service' entry is a real ServiceSkill")
    check(
        skill.tool_name == "skill.notification_service",
        "ServiceSkill.tool_name for notification_service is the stable name 'skill.notification_service'",
    )
    check(
        graph.tool_registry.exists("skill.notification_service"),
        "Tool 'skill.notification_service' is registered in the shared tool_registry",
    )

    tool: Tool = graph.tool_registry.get("skill.notification_service")
    result = tool.handler(metadata={})
    check(isinstance(result, ServiceResult), "invoking the Tool handler returns a real ServiceResult")
    check(
        result.success is False,
        "calling the notification skill with no metadata fails via NotificationService's own validation "
        "(missing 'channel') -- proving the Tool handler actually reaches NotificationService.execute(), "
        "with no network call attempted",
    )

    check(
        len(graph.service_skills) == 12,
        "graph.service_skills now has 12 entries total (11 pipeline Services + notification_service)",
    )
    check(
        set(graph.service_skills) == set(SKILL_METADATA_BY_SERVICE),
        "graph.service_skills is still keyed by exactly the Service names covered by SKILL_METADATA_BY_SERVICE",
    )


# ---------------------------------------------------------------------------
# 4. GoalPlanner (unmodified): automatically sees notification_service
#    through the same service_skills mapping -- no GoalPlanner code
#    change was needed or made for this.
# ---------------------------------------------------------------------------
def scenario_goal_planner_sees_notification_service_with_no_planner_change() -> None:
    ToolRegistry.reset()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-task3-planner",
        provider_kind="gemini",
        agent_name="stock_agent_task3_planner",
    )

    check(
        graph.goal_planner._service_skills is graph.service_skills,  # noqa: SLF001 -- deliberate white-box check
        "GoalPlanner still stores the exact same service_skills mapping object built on the graph "
        "(unchanged Stage L15 wiring contract) -- notification_service reaches it with no GoalPlanner edit",
    )
    check(
        "notification_service" in graph.goal_planner._service_skills,  # noqa: SLF001
        "notification_service is reachable from GoalPlanner's own service_skills view",
    )


# ---------------------------------------------------------------------------
# 5. Cross-Skill Reflection Foundation: notification_service is a
#    genuinely second, independent domain -- it shares no
#    required/produced metadata key with any of the 11 pipeline Services,
#    so it cannot be silently pulled into an unrelated stock-analysis
#    plan by build_plan()'s forward-chaining closure.
# ---------------------------------------------------------------------------
def scenario_notification_service_is_a_genuinely_independent_second_domain() -> None:
    notification_metadata = SKILL_METADATA_BY_SERVICE["notification_service"]
    notification_keys = set(notification_metadata.required_inputs) | set(
        notification_metadata.optional_inputs
    ) | set(notification_metadata.produced_outputs)

    pipeline_keys: set = set()
    for service_name, metadata in SKILL_METADATA_BY_SERVICE.items():
        if service_name == "notification_service":
            continue
        pipeline_keys |= set(metadata.required_inputs)
        pipeline_keys |= set(metadata.optional_inputs)
        pipeline_keys |= set(metadata.produced_outputs)

    # "status"/"response" are notification_service's own literal output
    # keys (see its SkillMetadata entry's own docstring comment) and are
    # not meaningful to compare for overlap. MetadataKeys.IMAGE_PATH is
    # also excluded: chart_service already produces it (a chart image
    # file path) and notification_service optionally accepts it (an
    # attachment file path) -- the same generic key name reused for two
    # unrelated file-path concepts, not a required coupling (it is only
    # an *optional* input here, so build_plan()'s forward-chaining,
    # which only connects on required_inputs per Stage L15, never forces
    # this connection). This is pre-existing key-naming overlap, not
    # something Task 3 introduced or needs to resolve.
    meaningful_notification_keys = notification_keys - {
        "status",
        "response",
        MetadataKeys.CHANNEL,
        MetadataKeys.IMAGE_PATH,
    }
    overlap = meaningful_notification_keys & pipeline_keys
    check(
        overlap == set(),
        "notification_service's metadata/message/credential keys share no key with any of the 11 "
        f"AnalysisPipeline-Service SkillMetadata entries (overlap found: {overlap}) -- confirming it is a "
        "genuinely second, independent Skill domain, not a variant of the existing stock-analysis chain",
    )


def main() -> int:
    scenarios = [
        scenario_skill_metadata_entry_is_declarative_and_matches_service,
        scenario_notification_service_registered_independently_of_pipeline,
        scenario_notification_service_wrapped_and_registered_as_skill_tool,
        scenario_goal_planner_sees_notification_service_with_no_planner_change,
        scenario_notification_service_is_a_genuinely_independent_second_domain,
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
    print(f"TASK 3 SECOND SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())