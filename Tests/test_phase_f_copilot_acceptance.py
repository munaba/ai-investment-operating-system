"""Phase F -- final acceptance-gate proof suite for the "controlled
copilot" capability (Tasks 1-10, all already COMPLETE).

This file does not audit, redesign, or extend the copilot. It proves,
against the real production components -- ``Orchestration.
copilot_runtime.CopilotRuntime`` (Task 10) as the single entry point,
routing through a real ``Orchestration.tool_registry.ToolRegistry`` /
``Orchestration.tool_resolver.ToolResolver`` pair, a real
``Orchestration.permissioned_tool.PermissionedTool``-wrapped
``Orchestration.copilot_tool.CopilotTool`` (Task 8/9), the real
``Services.copilot_service.CopilotService`` (Task 7), and real
``Database.models.DecisionBrief`` / ``Orchestration.memory.MemoryStore``
instances -- that the eight Phase-F acceptance items below hold.

Per this task's own instruction: real Ollama availability is not
required for a unit-level acceptance proof. Scenarios 3 and 8 exercise
the real ``Providers.base_provider.BaseProvider`` interface via a
fully-implemented fake provider (health-check-raises for "unavailable",
health-check-True + deterministic ``generate()`` for "healthy") -- no
live Ollama call is made or claimed anywhere in this file.

Acceptance items (as specified for this closeout) and the scenario
that proves each:

  1. Stored DecisionBrief explanation           -> scenario_1
  2. Stored rejection explanation                -> scenario_2
  3. LLM unavailable fallback                    -> scenario_3
  4. READ_ONLY permission boundary               -> scenario_4
  5. No financial mutation                       -> scenario_5
  6. Memory retrieval                            -> scenario_6
  7. Deterministic fallback (UNSUPPORTED)        -> scenario_7
  8. Provider-backed explanation                 -> scenario_8

Every scenario is a standalone function using this codebase's existing
``check()``/``_PASS``/``_FAIL`` convention (see
``Tests/test_phase_a_decision_copilot.py``,
``Tests/test_phase_f_task8_copilot_tool_permission_boundary.py``), run
via ``if __name__ == "__main__"`` -- no pytest dependency, matching
every other Phase test file in this repository.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Database.models import DecisionBrief
from Orchestration.copilot_intent import CopilotIntent
from Orchestration.copilot_runtime import (
    STATUS_DENIED,
    CopilotRuntime,
    CopilotRuntimeResult,
)
from Orchestration.copilot_tool import CopilotTool
from Orchestration.memory import (
    LessonRecord,
    MemoryStore,
    PreferenceRecord,
    PreviousDecisionRecord,
)
from Orchestration.permission_context import PermissionContext
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_registry import ToolRegistry
from Orchestration.tool_resolver import ToolResolver
from Orchestration.tool_result import ToolResult
from Providers.base_provider import BaseProvider
from Providers.message import Message
from Services.copilot_memory_service import CopilotMemoryService

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


# ---------------------------------------------------------------------
# Shared fixtures/helpers
# ---------------------------------------------------------------------


def _build_copilot_runtime(
    permission_context: Optional[PermissionContext] = None,
) -> CopilotRuntime:
    """Build a real ``CopilotRuntime`` over a real ``ToolRegistry``/
    ``ToolResolver`` pair with the real ``CopilotTool`` registered
    behind a real ``PermissionedTool`` -- exactly the shape
    ``Core.composition_root`` wires in production (Task 9), just built
    locally rather than through the full application graph, per this
    task's "unit-level acceptance proof" allowance.
    """
    registry = ToolRegistry()
    registry.register("copilot", PermissionedTool(CopilotTool(), PermissionContext()))
    resolver = ToolResolver(registry)
    return CopilotRuntime(resolver, permission_context or PermissionContext())


def _build_registry_with_fake_tool(fake_tool: Any) -> ToolResolver:
    registry = ToolRegistry()
    registry.register("copilot", fake_tool)
    return ToolResolver(registry)


class _FakeDeclaredPermissionTool:
    """Deterministic fake tool declaring an arbitrary
    ``ToolPermission``. Tracks call count so a test can prove the
    underlying callable was never reached on denial."""

    def __init__(self, permission: ToolPermission) -> None:
        self.permission = permission
        self.calls = 0

    @property
    def name(self) -> str:
        return "copilot"

    @property
    def description(self) -> str:
        return "fake tool for permission-boundary proof"

    def execute(self, context: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, output="SHOULD NOT RUN", error=None, metadata={})


class _FakeHealthyProvider(BaseProvider):
    """Fully-implements ``BaseProvider``; ``health_check()`` reports
    healthy and ``generate()`` returns a fixed, deterministic
    rephrasing -- used to prove the LLM-narration path (Task 6/7)
    without any live network/Ollama call."""

    def __init__(self, narrated_text: str) -> None:
        super().__init__()
        self._narrated_text = narrated_text

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def generate(self, messages: List[Message], **kwargs: Any) -> Any:
        class _Response:
            pass

        response = _Response()
        response.text = self._narrated_text
        return response

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        yield self._narrated_text

    def count_tokens(self, messages: List[Message]) -> int:
        return 0

    @property
    def name(self) -> str:
        return "fake-healthy-provider"


class _FakeFailingProvider(BaseProvider):
    """Fully-implements ``BaseProvider``; ``health_check()`` raises,
    simulating a genuinely unavailable/misbehaving provider -- used to
    prove the deterministic fallback path never crashes and never
    reaches ``generate()``."""

    def __init__(self) -> None:
        super().__init__()
        self.generate_calls = 0

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health_check(self) -> bool:
        raise RuntimeError("simulated provider outage")

    def generate(self, messages: List[Message], **kwargs: Any) -> Any:
        self.generate_calls += 1
        raise RuntimeError("generate() must never be reached when unhealthy")

    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        raise RuntimeError("stream() must never be reached when unhealthy")

    def count_tokens(self, messages: List[Message]) -> int:
        return 0

    @property
    def name(self) -> str:
        return "fake-failing-provider"


def _success_brief(**overrides: Any) -> DecisionBrief:
    fields = dict(
        brief_id=101,
        symbol="BBCA",
        generated_at="2026-02-01T09:30:00Z",
        status="SUCCESS",
        source_snapshot_id=555,
        reason="Momentum breakout confirmed by volume filter.",
        entry_price=9500.0,
        stop_loss_price=9300.0,
        take_profit_price=9900.0,
        position_size=100.0,
        risk_reward_ratio=2.0,
    )
    fields.update(overrides)
    return DecisionBrief(**fields)


def _rejected_brief(status: str, reason: str, **overrides: Any) -> DecisionBrief:
    fields = dict(
        brief_id=202,
        symbol="TLKM",
        generated_at="2026-02-01T09:31:00Z",
        status=status,
        source_snapshot_id=556,
        reason=reason,
    )
    fields.update(overrides)
    return DecisionBrief(**fields)


# ---------------------------------------------------------------------
# 1. Stored DecisionBrief explanation
# ---------------------------------------------------------------------


def scenario_1_stored_decision_brief_explanation() -> None:
    print("\n[1] Stored DecisionBrief explanation")
    runtime = _build_copilot_runtime()
    brief = _success_brief()

    result = runtime.handle(
        "why did the system make that trade?",
        {"decision_brief": brief},
    )

    check(isinstance(result, CopilotRuntimeResult), "handle() returns a CopilotRuntimeResult")
    check(result.success, "explanation call succeeds")
    check(result.intent is CopilotIntent.EXPLAIN_DECISION, "utterance classified as EXPLAIN_DECISION")
    check(not result.denied, "READ_ONLY explanation call is not denied")
    check(brief.symbol in (result.text or ""), "runtime's text mentions the brief's own symbol")

    explanation = result.response.data
    check(explanation.symbol == brief.symbol, "explanation.symbol matches the brief verbatim")
    check(explanation.status == brief.status, "explanation.status matches the brief verbatim")
    check(explanation.reason == brief.reason, "explanation.reason matches the brief verbatim")
    check(explanation.brief_id == brief.brief_id, "explanation traces the exact brief_id")
    check(
        explanation.source_snapshot_id == brief.source_snapshot_id,
        "explanation traces the exact source_snapshot_id",
    )


# ---------------------------------------------------------------------
# 2. Stored rejection explanation
# ---------------------------------------------------------------------


def scenario_2_stored_rejection_explanation() -> None:
    print("\n[2] Stored rejection explanation (DATA_STALE / RISK_REJECTED / POLICY_BLOCKED)")
    runtime = _build_copilot_runtime()

    cases = [
        ("DATA_STALE", "Market data for TLKM was older than the freshness threshold.", "stale data"),
        ("RISK_REJECTED", "Position size would exceed the account's risk limit.", "risk policy"),
        ("POLICY_BLOCKED", "Decision policy disallows new entries during the cooldown window.", "decision policy"),
    ]

    for status, reason, expected_blocked_by in cases:
        brief = _rejected_brief(status, reason)
        result = runtime.handle("why was that blocked?", {"decision_brief": brief})

        check(result.success, f"{status} explanation call succeeds")
        check(result.intent is CopilotIntent.EXPLAIN_DECISION, f"{status} utterance classified as EXPLAIN_DECISION")

        explanation = result.response.data
        check(explanation.status == status, f"{status}: explanation.status carried through verbatim")
        check(explanation.reason == reason, f"{status}: explanation.reason carried through verbatim, unmodified")
        check(
            explanation.blocked_by == expected_blocked_by,
            f"{status}: blocked_by correctly identifies the blocking category ({expected_blocked_by!r})",
        )
        # No new decision is invented: a blocked brief carries no plan,
        # and the explanation text never mentions a fabricated entry/
        # stop/target for it.
        check(
            brief.entry_price is None and brief.stop_loss_price is None,
            f"{status}: the underlying DecisionBrief itself carries no fabricated plan fields",
        )
        check(
            "entry" not in (result.text or "").lower(),
            f"{status}: rendered explanation text does not invent an entry/plan",
        )


# ---------------------------------------------------------------------
# 3. LLM unavailable fallback
# ---------------------------------------------------------------------


def scenario_3_llm_unavailable_fallback() -> None:
    print("\n[3] LLM unavailable fallback")
    runtime = _build_copilot_runtime()
    brief = _success_brief()
    failing_provider = _FakeFailingProvider()

    result = runtime.handle(
        "why did the system make that trade?",
        {"decision_brief": brief, "provider": failing_provider},
    )

    check(result.success, "call succeeds even though the injected provider is unavailable (no crash)")
    check(result.source == "deterministic", "text source falls back to deterministic, not llm")
    check(brief.symbol in (result.text or ""), "fallback text is the deterministic summary referencing the brief")
    check(failing_provider.generate_calls == 0, "generate() is never called once health_check() fails")
    check(not result.denied, "provider failure is not treated as a permission denial")
    # No financial action: the response is a text/status explanation
    # only, never an Order/Trade/Position/paper-execution result.
    check(
        not hasattr(result.response, "order") and not hasattr(result.response, "trade"),
        "response object carries no order/trade attribute of any kind",
    )


# ---------------------------------------------------------------------
# 4. READ_ONLY permission boundary
# ---------------------------------------------------------------------


def scenario_4_read_only_permission_boundary() -> None:
    print("\n[4] READ_ONLY permission boundary")

    # READ_ONLY succeeds.
    ro_runtime = _build_copilot_runtime()
    ro_result = ro_runtime.handle("what is the status?", {"status_text": "All systems nominal."})
    check(ro_result.success, "READ_ONLY copilot call succeeds")
    check(not ro_result.denied, "READ_ONLY copilot call is not denied")

    # PAPER_EXECUTION denied.
    paper_tool = _FakeDeclaredPermissionTool(ToolPermission.PAPER_EXECUTION)
    paper_resolver = _build_registry_with_fake_tool(paper_tool)
    paper_runtime = CopilotRuntime(paper_resolver, PermissionContext(paper_execution_allowed=True))
    paper_result = paper_runtime.handle("what is the status?")
    check(paper_result.denied, "PAPER_EXECUTION-declared tool is denied even with capability granted")
    check(paper_result.status == STATUS_DENIED, "PAPER_EXECUTION denial status is STATUS_DENIED")
    check(paper_tool.calls == 0, "PAPER_EXECUTION tool's execute() is never reached")

    # LIVE_EXECUTION denied.
    live_tool = _FakeDeclaredPermissionTool(ToolPermission.LIVE_EXECUTION)
    live_resolver = _build_registry_with_fake_tool(live_tool)
    live_runtime = CopilotRuntime(live_resolver, PermissionContext(live_execution_allowed=True))
    live_result = live_runtime.handle("what is the status?")
    check(live_result.denied, "LIVE_EXECUTION-declared tool is denied even with capability granted")
    check(live_tool.calls == 0, "LIVE_EXECUTION tool's execute() is never reached")

    # DESTRUCTIVE_ADMIN denied.
    admin_tool = _FakeDeclaredPermissionTool(ToolPermission.DESTRUCTIVE_ADMIN)
    admin_resolver = _build_registry_with_fake_tool(admin_tool)
    admin_runtime = CopilotRuntime(admin_resolver, PermissionContext(destructive_admin_allowed=True))
    admin_result = admin_runtime.handle("what is the status?")
    check(admin_result.denied, "DESTRUCTIVE_ADMIN-declared tool is denied even with capability granted")
    check(admin_tool.calls == 0, "DESTRUCTIVE_ADMIN tool's execute() is never reached")

    # No retry/escalation: calling the same denied runtime again never
    # succeeds, and the runtime's own PermissionContext instance is
    # never rebuilt/replaced between calls.
    permission_context_before = paper_runtime._permission_context
    second_paper_result = paper_runtime.handle("what is the status?")
    permission_context_after = paper_runtime._permission_context
    check(second_paper_result.denied, "repeated call against the same runtime is denied again, never escalated")
    check(paper_tool.calls == 0, "underlying tool still never reached after a second attempt")
    check(
        permission_context_before is permission_context_after,
        "the runtime's PermissionContext instance is never replaced/upgraded between calls",
    )


# ---------------------------------------------------------------------
# 5. No financial mutation
# ---------------------------------------------------------------------


def scenario_5_no_financial_mutation() -> None:
    print("\n[5] No financial mutation")

    forbidden_modules = (
        "Orchestration.paper_execution_tool",
        "Orchestration.execution_intent",
        "Business.risk_ledger_policy",
        "Repository.persistence.risk_limits_repository",
        "Repository.persistence.journal_repository",
        "Services.journal_service",
    )
    copilot_stack_files = (
        ROOT / "Orchestration" / "copilot_runtime.py",
        ROOT / "Orchestration" / "copilot_tool.py",
        ROOT / "Services" / "copilot_service.py",
        ROOT / "Services" / "copilot_explanation_service.py",
        ROOT / "Services" / "copilot_memory_service.py",
        ROOT / "Services" / "copilot_explanation_llm_narrator.py",
    )
    for file_path in copilot_stack_files:
        source = file_path.read_text(encoding="utf-8")
        import_lines = [
            line for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        found = [m for m in forbidden_modules if any(m in line for line in import_lines)]
        check(
            len(found) == 0,
            f"{file_path.name} imports no financial-mutation module (found={found})",
        )

    # Functional proof: an EXPLAIN_DECISION call never mutates the
    # DecisionBrief it was given (financial data is read-only input).
    runtime = _build_copilot_runtime()
    brief = _success_brief()
    snapshot_before = (
        brief.brief_id, brief.symbol, brief.status, brief.reason,
        brief.entry_price, brief.stop_loss_price, brief.take_profit_price,
        brief.position_size, brief.risk_reward_ratio, brief.source_snapshot_id,
    )
    runtime.handle("why did the system make that trade?", {"decision_brief": brief})
    snapshot_after = (
        brief.brief_id, brief.symbol, brief.status, brief.reason,
        brief.entry_price, brief.stop_loss_price, brief.take_profit_price,
        brief.position_size, brief.risk_reward_ratio, brief.source_snapshot_id,
    )
    check(snapshot_before == snapshot_after, "the DecisionBrief's own fields are unchanged after explanation")

    # PermissionContext is a frozen dataclass -- mutation is structurally
    # impossible, not merely avoided by convention.
    permission_context = PermissionContext()
    try:
        permission_context.paper_execution_allowed = True  # type: ignore[misc]
        mutation_blocked = False
    except Exception:
        mutation_blocked = True
    check(mutation_blocked, "PermissionContext is frozen -- attempted mutation raises rather than succeeding")


# ---------------------------------------------------------------------
# 6. Memory retrieval
# ---------------------------------------------------------------------


def scenario_6_memory_retrieval() -> None:
    print("\n[6] Memory retrieval")

    store = MemoryStore()
    preference = PreferenceRecord(key="analysis_style", value="concise")
    lesson = LessonRecord(text="Avoid entering after a gap-up without confirmation.")
    previous_decision = PreviousDecisionRecord(
        decision="Reduced BBCA position by half.",
        rationale="Earnings missed consensus and momentum turned negative.",
    )
    store.add(preference)
    store.add(lesson)
    store.add(previous_decision)
    length_before = len(store)

    # (a) Preference retrieval through the actual wired copilot runtime
    # entry point (RECALL_PREFERENCE intent).
    runtime = _build_copilot_runtime()
    pref_result = runtime.handle(
        "what is my preference for analysis_style?",
        {"memory_store": store, "memory_query": "analysis_style"},
    )
    check(pref_result.success, "RECALL_PREFERENCE call succeeds")
    check(pref_result.intent is CopilotIntent.RECALL_PREFERENCE, "utterance classified as RECALL_PREFERENCE")
    check(pref_result.response.data.latest is preference, "returned record is the exact stored PreferenceRecord")
    check(pref_result.response.data.latest.value == "concise", "returned preference value is verbatim")

    # (b) Lesson and previous-decision retrieval through the underlying
    # Task 5 CopilotMemoryService component the copilot's memory
    # capability is built on (the currently wired RECALL_PREFERENCE
    # intent branch exercises PreferenceRecord specifically; lesson/
    # previous-decision retrieval is proven directly against the same
    # read-only service, with no additional wiring required).
    memory_service = CopilotMemoryService()

    lesson_lookup = memory_service.get_lesson(store)
    check(lesson_lookup.status == "FOUND", "stored LessonRecord is retrievable")
    check(lesson_lookup.latest is lesson, "returned lesson is the exact stored LessonRecord")

    decision_lookup = memory_service.get_previous_decision(store)
    check(decision_lookup.status == "FOUND", "stored PreviousDecisionRecord is retrievable")
    check(decision_lookup.latest is previous_decision, "returned record is the exact stored PreviousDecisionRecord")

    # (c) No memory write occurs during ordinary copilot queries.
    runtime.handle("what is the status?", {"status_text": "nominal"})
    runtime.handle("summarize my portfolio", {"portfolio_summary": "flat"})
    runtime.handle("play some music please")
    runtime.handle(
        "what is my preference for analysis_style?",
        {"memory_store": store, "memory_query": "analysis_style"},
    )
    check(len(store) == length_before, "MemoryStore length is unchanged after several ordinary copilot queries")


# ---------------------------------------------------------------------
# 7. Deterministic fallback (UNSUPPORTED)
# ---------------------------------------------------------------------


def scenario_7_deterministic_unsupported_fallback() -> None:
    print("\n[7] Deterministic fallback for unsupported/ambiguous requests")
    runtime = _build_copilot_runtime()

    unrecognized_result = runtime.handle("play some music please")
    check(unrecognized_result.intent is CopilotIntent.UNSUPPORTED, "unrecognized utterance classified UNSUPPORTED")
    check(unrecognized_result.success, "UNSUPPORTED is still a successful, explicit response (not a failure)")
    check(not unrecognized_result.denied, "UNSUPPORTED is not a permission denial")
    check(
        "couldn't classify" in (unrecognized_result.text or ""),
        "UNSUPPORTED returns the fixed, deterministic message",
    )

    # An utterance matching keywords from two distinct categories at
    # once (EXPLAIN_DECISION's "why did" and SUMMARIZE_PORTFOLIO's
    # "summarize my portfolio") is genuinely ambiguous -- the
    # classifier resolves ambiguity to UNSUPPORTED rather than
    # guessing.
    ambiguous_result = runtime.handle("why did you summarize my portfolio")
    check(ambiguous_result.intent is CopilotIntent.UNSUPPORTED, "ambiguous (multi-category) utterance also resolves UNSUPPORTED")
    check(ambiguous_result.success, "ambiguous UNSUPPORTED is still a successful, explicit response")

    # Empty utterance also resolves UNSUPPORTED, never a crash.
    empty_result = runtime.handle("")
    check(empty_result.intent is CopilotIntent.UNSUPPORTED, "empty utterance resolves UNSUPPORTED")
    check(empty_result.success, "empty utterance is still a successful, explicit response")


# ---------------------------------------------------------------------
# 8. Provider-backed explanation
# ---------------------------------------------------------------------


def scenario_8_provider_backed_explanation() -> None:
    print("\n[8] Provider-backed explanation")
    runtime = _build_copilot_runtime()
    brief = _success_brief()
    narrated_text = "In short: BBCA triggered a momentum breakout, confirmed by volume, so a trade plan was created."
    healthy_provider = _FakeHealthyProvider(narrated_text)

    result = runtime.handle(
        "why did the system make that trade?",
        {"decision_brief": brief, "provider": healthy_provider},
    )

    check(result.success, "provider-backed explanation call succeeds")
    check(result.source == "llm", "text source is 'llm' when a healthy provider is injected")
    check(result.text == narrated_text, "rendered text is the fake provider's narration")

    # The deterministic source remains traceable alongside the
    # narrated text -- the underlying CopilotExplanationResult (Task 4)
    # is still attached, unchanged, on `response.data`.
    explanation = result.response.data
    check(explanation.summary is not None, "deterministic summary remains present on the underlying explanation")
    check(explanation.summary != result.text, "deterministic summary and LLM-narrated text are distinct, both traceable")
    check(explanation.symbol == brief.symbol, "deterministic explanation data still traces back to the real brief")


def main() -> int:
    scenario_1_stored_decision_brief_explanation()
    scenario_2_stored_rejection_explanation()
    scenario_3_llm_unavailable_fallback()
    scenario_4_read_only_permission_boundary()
    scenario_5_no_financial_mutation()
    scenario_6_memory_retrieval()
    scenario_7_deterministic_unsupported_fallback()
    scenario_8_provider_backed_explanation()

    print("\n" + "=" * 60)
    print(f"PHASE F COPILOT ACCEPTANCE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for description in _FAILURES:
            print(f"  - {description}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())