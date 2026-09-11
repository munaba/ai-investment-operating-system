"""CopilotService -- Phase F, Task 7: one deterministic facade over the
already-built Phase-F copilot components.

Scope note (LOCKED for this task): this module introduces exactly
three things.

  1. ``CopilotRequestContext`` -- an immutable bundle of the read-only,
     caller-supplied inputs a single ``CopilotService.handle`` call may
     need (a ``MemoryStore``, a ``DecisionBrief``, an already-computed
     portfolio summary string, an already-computed status string, and
     an optional injected ``BaseProvider``).
  2. ``CopilotResponse`` -- an immutable, typed result every
     ``CopilotService.handle`` call returns, regardless of intent.
  3. ``CopilotService`` -- the facade itself: classifies the utterance
     (Task 3), then dispatches to exactly one of five deterministic
     branches built from the components already delivered in Tasks
     2--6.

This module composes existing components; it computes nothing new.
Every branch either (a) calls an already-built deterministic service
and returns its result, optionally reworded by the already-built
optional narrator when a healthy provider is injected, or (b) returns
an explicit, fixed, deterministic response when the caller did not
supply what that branch needs. There is no path in this module that
falls back to a financial action, a paper order, a risk-limit change,
a permission change, a memory write, or a Telegram side effect --
none of those capabilities are imported here at all.

Per-intent responsibilities (LOCKED to exactly what this task lists):

  - ``EXPLAIN_DECISION`` -- ``CopilotExplanationService.explain`` (Task
    4) over ``context.decision_brief``. If ``context.provider`` is
    supplied and reports healthy, the deterministic
    ``explanation.summary`` is optionally reworded via
    ``narrate_explanation`` (Task 6); on any provider failure that
    function already falls back to ``explanation.summary`` unchanged
    -- this facade adds one more guard on top (a health check before
    even attempting narration) but never removes that fallback.
  - ``RECALL_PREFERENCE`` -- ``CopilotMemoryService.get_preference``
    (Task 5) over ``context.memory_store``, deterministic only -- no
    narrator is invoked for this branch, per this task's requirements.
  - ``SUMMARIZE_PORTFOLIO`` -- returns an explicit ``NOT_IMPLEMENTED``
    result unless ``context.portfolio_summary`` (an already-existing
    summary payload the caller computed elsewhere, e.g. via
    ``Services.report_service``/``PortfolioReportSkill``) is supplied
    directly. This module never computes a portfolio summary itself
    and never constructs a new summary engine.
  - ``ASK_STATUS`` -- returns ``context.status_text`` verbatim
    (already-computed by the caller) when supplied, else an explicit
    ``MISSING_CONTEXT`` result. This module never queries a scheduler,
    a database, or any live system for status itself.
  - ``UNSUPPORTED`` -- a fixed, deterministic response. No classifier
    branch, provider, or fallback path in this module can silently
    turn an unsupported utterance into a financial action.

Dependency direction: this module imports only the stdlib
``dataclasses``/``typing`` modules, ``Database.models.DecisionBrief``
(type annotation only), ``Orchestration.memory.MemoryStore`` (type
annotation only), ``Providers.base_provider.BaseProvider`` (type
annotation only), and the five Phase-F modules already delivered in
Tasks 2--6 (``Orchestration.copilot_intent``,
``Orchestration.copilot_intent_classifier``,
``Services.copilot_explanation_service``,
``Services.copilot_explanation_llm_narrator``,
``Services.copilot_memory_service``). It does not import
``Core.composition_root``, any Telegram module, any tool/skill module,
``Orchestration.tool_permission``/``permission_context``, or
``Orchestration.memory.MemoryRecorder`` (no write path exists here).
It is additive-only, standing on its own until a future task wires it
behind a real entry point (CLI command, chat handler, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from Database.models import DecisionBrief
from Orchestration.copilot_intent import CopilotIntent
from Orchestration.copilot_intent_classifier import CopilotIntentClassifier
from Orchestration.memory import MemoryStore
from Providers.base_provider import BaseProvider
from Services.copilot_explanation_llm_narrator import narrate_explanation
from Services.copilot_explanation_service import (
    CopilotExplanationResult,
    CopilotExplanationService,
)
from Services.copilot_memory_service import CopilotMemoryLookupResult, CopilotMemoryService

#: Fixed status labels this facade itself introduces, for outcomes the
#: underlying Task 4/5 components have no status for (missing input to
#: this facade, or a capability this task explicitly scopes out).
#: Mirrors the plain-string-constant convention already used by
#: ``Services.decision_brief_service.STATUS_*`` and
#: ``Services.copilot_memory_service.STATUS_*`` rather than
#: introducing a new ``Enum``.
STATUS_MISSING_CONTEXT = "MISSING_CONTEXT"
STATUS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
STATUS_UNSUPPORTED = "UNSUPPORTED"

#: Fixed, deterministic text for branches with no caller-supplied data
#: to work from. Never computed, never templated with fabricated
#: values -- plain constant strings.
_TEXT_UNSUPPORTED = (
    "I couldn't classify that as something I can help with. Try asking "
    "about a specific decision, your portfolio summary, a preference "
    "you've stated, or system status."
)
_TEXT_SUMMARY_NOT_SUPPLIED = (
    "No portfolio summary was supplied for this request. Portfolio "
    "summarization is not computed by the copilot itself in this "
    "version -- an already-computed summary must be passed in."
)
_TEXT_STATUS_NOT_SUPPLIED = (
    "No status information was supplied for this request. The copilot "
    "does not query system status itself in this version -- "
    "already-computed status text must be passed in."
)
_TEXT_MISSING_DECISION_BRIEF = (
    "No decision brief was supplied to explain."
)
_TEXT_MISSING_MEMORY_STORE = (
    "No memory store was supplied to search."
)


@dataclass(frozen=True)
class CopilotRequestContext:
    """Immutable bundle of read-only, caller-supplied inputs for a
    single ``CopilotService.handle`` call.

    Every field is optional and defaults to ``None`` -- a caller
    supplies only what the intent they expect actually needs.
    ``CopilotService`` never constructs any of these itself: not a
    ``MemoryStore``, not a ``DecisionBrief``, not a provider, and not
    a summary/status string. All are handed in by the caller, exactly
    as already fetched/computed elsewhere.

    Attributes:
        memory_store: An already-populated ``MemoryStore``, used by
            the ``RECALL_PREFERENCE`` branch. ``None`` if not
            available.
        memory_query: Optional preference ``key`` to filter by, passed
            straight through to ``CopilotMemoryService.get_preference``.
            ``None`` returns every stored preference.
        decision_brief: An already-fetched ``DecisionBrief``, used by
            the ``EXPLAIN_DECISION`` branch. ``None`` if none exists
            for the query this call is answering.
        provider: An optional, already-constructed, injected
            ``BaseProvider`` (e.g. an ``OllamaProvider`` resolved by
            the caller via ``provider_manager.get("ollama")``). Never
            constructed or looked up by this module. ``None`` means
            no LLM narration is attempted -- the deterministic
            explanation is returned as-is.
        portfolio_summary: An already-computed portfolio summary
            string (e.g. from ``Services.report_service`` or
            ``PortfolioReportSkill``), used by the
            ``SUMMARIZE_PORTFOLIO`` branch. ``None`` if not supplied.
        status_text: An already-computed system status string, used by
            the ``ASK_STATUS`` branch. ``None`` if not supplied.
    """

    memory_store: Optional[MemoryStore] = None
    memory_query: Optional[str] = None
    decision_brief: Optional[DecisionBrief] = None
    provider: Optional[BaseProvider] = None
    portfolio_summary: Optional[str] = None
    status_text: Optional[str] = None


@dataclass(frozen=True)
class CopilotResponse:
    """Immutable, typed result returned by every
    ``CopilotService.handle`` call, regardless of intent.

    Attributes:
        success: Whether this call could be fully answered. ``False``
            only for a genuine facade-level error (an unrecognized
            intent value, which ``CopilotIntent`` itself already
            prevents in practice) -- ``MISSING_CONTEXT``/
            ``NOT_IMPLEMENTED``/``UNSUPPORTED`` are all ``True``:
            fully-answered, explicit outcomes, not failures.
        intent: The ``CopilotIntent`` this utterance was classified
            into (Task 3), carried through unchanged.
        status: A short status label. Either a status string already
            produced by the underlying Task 4/5 component
            (e.g. ``"SUCCESS"``, ``"NO_TRADE"``, ``"FOUND"``,
            ``"EMPTY"``) or one of this module's own
            ``STATUS_MISSING_CONTEXT`` / ``STATUS_NOT_IMPLEMENTED`` /
            ``STATUS_UNSUPPORTED`` labels.
        text: The natural-language answer for this call. Always a
            fixed/deterministic string unless a healthy injected
            provider produced a reworded version via
            ``narrate_explanation`` for ``EXPLAIN_DECISION`` -- never
            ``None`` when ``success`` is ``True``.
        source: ``"deterministic"`` if ``text`` came directly from an
            existing deterministic component or a fixed constant in
            this module, or ``"llm"`` if ``text`` was produced by the
            optional narrator (``EXPLAIN_DECISION`` only, and only
            when it actually changed the text).
        data: The underlying Task 4/5 result object this response was
            built from (a ``CopilotExplanationResult`` or
            ``CopilotMemoryLookupResult``), verbatim, for a future
            caller that wants the structured detail rather than just
            ``text``. ``None`` for branches with no underlying
            component result (``SUMMARIZE_PORTFOLIO``, ``ASK_STATUS``,
            ``UNSUPPORTED``, or any ``MISSING_CONTEXT`` outcome).
        error: Human-readable explanation of why ``success`` is
            ``False``. ``None`` whenever ``success`` is ``True``.
    """

    success: bool
    intent: CopilotIntent
    status: str
    text: Optional[str] = None
    source: str = "deterministic"
    data: Any = None
    error: Optional[str] = None


class CopilotService:
    """Deterministic facade dispatching a classified utterance to the
    already-built Phase-F components.

    Holds no state and no collaborators of its own -- construction
    takes no arguments. Every ``handle`` call is a pure function of
    its ``utterance`` and ``context`` arguments: it constructs
    ``CopilotIntentClassifier``/``CopilotExplanationService``/
    ``CopilotMemoryService`` fresh (all three are themselves stateless,
    per their own docstrings) rather than caching them, and never
    persists anything between calls.
    """

    def handle(self, utterance: str, context: CopilotRequestContext) -> CopilotResponse:
        """Classify ``utterance`` and dispatch to the matching
        deterministic branch.

        Args:
            utterance: Free-form user text (see
                ``CopilotIntentClassifier.classify`` for its
                normalization/ambiguity rules).
            context: The caller-supplied ``CopilotRequestContext``
                for this call. Never mutated.

        Returns:
            A ``CopilotResponse`` for exactly one of the five
            ``CopilotIntent`` branches.
        """
        intent = CopilotIntentClassifier().classify(utterance)

        if intent is CopilotIntent.EXPLAIN_DECISION:
            return self._handle_explain_decision(context)
        if intent is CopilotIntent.RECALL_PREFERENCE:
            return self._handle_recall_preference(context)
        if intent is CopilotIntent.SUMMARIZE_PORTFOLIO:
            return self._handle_summarize_portfolio(context)
        if intent is CopilotIntent.ASK_STATUS:
            return self._handle_ask_status(context)

        # CopilotIntent.UNSUPPORTED, and the fail-safe default for any
        # future CopilotIntent member this facade does not yet branch
        # on -- both resolve to the same fixed, deterministic response
        # rather than ever falling through to a financial action.
        return self._handle_unsupported(intent)

    def _handle_explain_decision(self, context: CopilotRequestContext) -> CopilotResponse:
        """Build the ``EXPLAIN_DECISION`` response.

        Args:
            context: The caller-supplied ``CopilotRequestContext``.

        Returns:
            A ``CopilotResponse`` wrapping ``CopilotExplanationService.
            explain``'s result, optionally reworded by
            ``narrate_explanation`` when ``context.provider`` is
            supplied and reports healthy.
        """
        if context.decision_brief is None:
            return CopilotResponse(
                success=True,
                intent=CopilotIntent.EXPLAIN_DECISION,
                status=STATUS_MISSING_CONTEXT,
                text=_TEXT_MISSING_DECISION_BRIEF,
            )

        explanation: CopilotExplanationResult = CopilotExplanationService().explain(
            context.decision_brief
        )

        if not explanation.success:
            return CopilotResponse(
                success=False,
                intent=CopilotIntent.EXPLAIN_DECISION,
                status=STATUS_MISSING_CONTEXT,
                data=explanation,
                error=explanation.error,
            )

        text = explanation.summary
        source = "deterministic"

        if context.provider is not None:
            healthy = self._provider_is_healthy(context.provider)
            if healthy:
                narrated = narrate_explanation(explanation, context.provider)
                if narrated != explanation.summary:
                    text = narrated
                    source = "llm"

        return CopilotResponse(
            success=True,
            intent=CopilotIntent.EXPLAIN_DECISION,
            status=explanation.status,
            text=text,
            source=source,
            data=explanation,
        )

    def _handle_recall_preference(self, context: CopilotRequestContext) -> CopilotResponse:
        """Build the ``RECALL_PREFERENCE`` response.

        Deterministic only -- no narrator is invoked for this branch,
        per this task's requirements.

        Args:
            context: The caller-supplied ``CopilotRequestContext``.

        Returns:
            A ``CopilotResponse`` wrapping ``CopilotMemoryService.
            get_preference``'s result.
        """
        if context.memory_store is None:
            return CopilotResponse(
                success=True,
                intent=CopilotIntent.RECALL_PREFERENCE,
                status=STATUS_MISSING_CONTEXT,
                text=_TEXT_MISSING_MEMORY_STORE,
            )

        lookup: CopilotMemoryLookupResult = CopilotMemoryService().get_preference(
            context.memory_store, key=context.memory_query
        )

        if not lookup.success:
            return CopilotResponse(
                success=False,
                intent=CopilotIntent.RECALL_PREFERENCE,
                status=STATUS_MISSING_CONTEXT,
                data=lookup,
                error=lookup.error,
            )

        text = self._render_preference_lookup(lookup)

        return CopilotResponse(
            success=True,
            intent=CopilotIntent.RECALL_PREFERENCE,
            status=lookup.status,
            text=text,
            data=lookup,
        )

    def _handle_summarize_portfolio(self, context: CopilotRequestContext) -> CopilotResponse:
        """Build the ``SUMMARIZE_PORTFOLIO`` response.

        Never computes a summary itself -- returns
        ``context.portfolio_summary`` verbatim when supplied, else an
        explicit ``NOT_IMPLEMENTED`` result.

        Args:
            context: The caller-supplied ``CopilotRequestContext``.

        Returns:
            A ``CopilotResponse`` with ``status`` either ``"SUCCESS"``
            (a payload was supplied) or ``STATUS_NOT_IMPLEMENTED``.
        """
        if context.portfolio_summary is not None:
            return CopilotResponse(
                success=True,
                intent=CopilotIntent.SUMMARIZE_PORTFOLIO,
                status="SUCCESS",
                text=context.portfolio_summary,
            )

        return CopilotResponse(
            success=True,
            intent=CopilotIntent.SUMMARIZE_PORTFOLIO,
            status=STATUS_NOT_IMPLEMENTED,
            text=_TEXT_SUMMARY_NOT_SUPPLIED,
        )

    def _handle_ask_status(self, context: CopilotRequestContext) -> CopilotResponse:
        """Build the ``ASK_STATUS`` response.

        Never queries a live system itself -- returns
        ``context.status_text`` verbatim when supplied, else an
        explicit ``MISSING_CONTEXT`` result.

        Args:
            context: The caller-supplied ``CopilotRequestContext``.

        Returns:
            A ``CopilotResponse`` with ``status`` either ``"SUCCESS"``
            (status text was supplied) or ``STATUS_MISSING_CONTEXT``.
        """
        if context.status_text is not None:
            return CopilotResponse(
                success=True,
                intent=CopilotIntent.ASK_STATUS,
                status="SUCCESS",
                text=context.status_text,
            )

        return CopilotResponse(
            success=True,
            intent=CopilotIntent.ASK_STATUS,
            status=STATUS_MISSING_CONTEXT,
            text=_TEXT_STATUS_NOT_SUPPLIED,
        )

    def _handle_unsupported(self, intent: CopilotIntent) -> CopilotResponse:
        """Build the fixed, deterministic ``UNSUPPORTED`` response.

        Args:
            intent: The classified (or otherwise unbranched)
                ``CopilotIntent``, carried through unchanged.

        Returns:
            A ``CopilotResponse`` with ``status=STATUS_UNSUPPORTED``
            and a fixed, non-financial, non-invented message.
        """
        return CopilotResponse(
            success=True,
            intent=intent,
            status=STATUS_UNSUPPORTED,
            text=_TEXT_UNSUPPORTED,
        )

    @staticmethod
    def _provider_is_healthy(provider: BaseProvider) -> bool:
        """Check ``provider.health_check()``, treating any exception as
        unhealthy.

        ``BaseProvider.health_check()`` is documented to never raise,
        but an injected test double or a future provider implementation
        might not honor that -- this facade never lets a provider
        health check itself take down the deterministic fallback path.

        Args:
            provider: The injected ``BaseProvider`` to check.

        Returns:
            ``True`` only if ``health_check()`` both returns and
            returns ``True``.
        """
        try:
            return bool(provider.health_check())
        except Exception:
            return False

    @staticmethod
    def _render_preference_lookup(lookup: CopilotMemoryLookupResult) -> str:
        """Build a fixed-template text answer from a preference lookup.

        Never invents a preference: ``lookup.latest`` (when present) is
        rendered using only its own ``key``/``value`` fields, already
        verbatim from the ``MemoryStore``.

        Args:
            lookup: The ``CopilotMemoryLookupResult`` from
                ``CopilotMemoryService.get_preference``.

        Returns:
            A fixed-template string reflecting ``lookup.status``.
        """
        if lookup.status == "FOUND" and lookup.latest is not None:
            return f"You stated a preference for '{lookup.latest.key}': {lookup.latest.value}."
        if lookup.status == "NOT_FOUND":
            return "No stored preference matches that query."
        # STATUS_EMPTY
        return "No preferences have been recorded yet."