"""CopilotRuntime -- Phase F, Task 10: the smallest real runtime /
orchestration layer that makes the existing copilot behave like a
controlled agent.

Phase F Tasks 1-9 are already complete and are used here exactly as
built -- this module wires them together and adds no new decision
logic, no new registry, and no new permission mechanism of its own.

Scope note (LOCKED for this task): this module introduces exactly two
things.

  1. ``CopilotRuntimeResult`` -- a small, frozen, typed result every
     ``CopilotRuntime.handle()`` call returns.
  2. ``CopilotRuntime`` -- a thin orchestrator that: classifies an
     utterance with the existing, deterministic
     ``Orchestration.copilot_intent_classifier.CopilotIntentClassifier``;
     resolves the existing registered ``"copilot"`` tool through the
     existing canonical ``Orchestration.tool_resolver.ToolResolver``;
     authorizes it through the existing
     ``Orchestration.tool_permission_enforcer.authorize_tool`` /
     ``Orchestration.permission_context.PermissionContext`` boundary;
     and, if authorized, executes it -- returning whatever the
     existing ``Services.copilot_service.CopilotService`` (reached via
     ``Orchestration.copilot_tool.CopilotTool``) already decided.

This module computes nothing new. Every one of the five intents
(``EXPLAIN_DECISION``, ``RECALL_PREFERENCE``, ``SUMMARIZE_PORTFOLIO``,
``ASK_STATUS``, ``UNSUPPORTED``) is still resolved entirely inside
``CopilotService.handle()`` (Task 7) exactly as it already is; LLM
narration (``EXPLAIN_DECISION`` only) and its provider-failure
fallback are still entirely ``CopilotService``'s/``narrate_explanation``'s
own responsibility (Tasks 6-7) -- this runtime never calls a provider,
never checks provider health itself, and never re-implements that
fallback. This runtime's own job is strictly narrower: give the
existing, already-built copilot pipeline a single, auditable entry
point that classifies, then authorizes, then executes -- and nothing
more.

Hard boundaries (LOCKED for this task, enforced by this module in
addition to -- never instead of -- the existing enforcement in
``Orchestration.tool_permission_enforcer``):

  * READ_ONLY only. Before ever calling ``tool.execute()``, this
    runtime checks ``Orchestration.tool_permission_enforcer.
    permission_for_tool`` on the resolved tool (unwrapping one
    ``Orchestration.permissioned_tool.PermissionedTool`` layer via its
    ``wrapped_tool`` property if present) and refuses -- with an
    explicit, auditable denial result, never an exception, never a
    silent no-op -- to proceed if that declared permission is not
    exactly ``ToolPermission.READ_ONLY``. This is a belt-and-braces
    scope lock specific to *this* runtime: the copilot capability this
    task wires up is READ_ONLY by construction (Task 8's
    ``CopilotTool.permission`` is always ``READ_ONLY``), so this check
    should never actually trigger in practice -- it exists so that a
    future misconfiguration (e.g. this runtime accidentally pointed at
    the wrong tool name) fails loudly and safely rather than silently
    executing something with elevated permission.
  * No PAPER_EXECUTION, LIVE_EXECUTION, or DESTRUCTIVE_ADMIN path
    exists anywhere in this module. It does not import
    ``Orchestration.paper_execution_tool``, does not construct an
    ``Orchestration.execution_intent.ExecutionIntent``, and does not
    call any broker, order, trade, or position API.
  * No permission mutation. The ``PermissionContext`` this runtime is
    given (if any) is stored once, at construction, by identity, and
    is never rebuilt, copied-with-changes, or swapped between calls.
    Every ``handle()`` call authorizes against the exact same
    ``PermissionContext`` instance -- there is no retry-with-a-
    different-context path anywhere in this module.
  * No permission retry/escalation. ``authorize_tool`` is called
    exactly once per ``handle()`` call. A denial is returned to the
    caller immediately as an explicit ``CopilotRuntimeResult`` with
    ``denied=True`` -- this runtime never re-authorizes with a
    stronger declared permission, never re-authorizes with a
    different/upgraded ``PermissionContext``, and never falls back to
    calling the tool's ``execute()`` anyway.
  * No autonomous action. ``handle()`` only ever runs in direct
    response to a caller-supplied ``utterance`` -- there is no loop,
    no scheduler hook, no timer, and no self-triggered call anywhere
    in this module.

Statelessness (LOCKED for this task): ``CopilotRuntime`` holds exactly
two collaborators set once at construction -- the injected
``ToolResolver`` and the injected, optional ``PermissionContext`` --
and nothing else. It creates no database table, persists no
conversation, starts no scheduler, and makes no Telegram change. Every
``handle()`` call is independent of every other; nothing is cached or
remembered between calls.

Dependency direction (LOCKED): this module imports only
``Orchestration.copilot_intent.CopilotIntent``,
``Orchestration.copilot_intent_classifier.CopilotIntentClassifier``,
``Orchestration.permission_context.PermissionContext``,
``Orchestration.tool_context.ToolContext``,
``Orchestration.tool_permission.ToolPermission``,
``Orchestration.tool_permission_enforcer`` (``authorize_tool``,
``permission_for_tool``, ``ToolPermissionDenied``),
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_result.ToolResult``, and stdlib
``dataclasses``/``typing``. It does not import
``Orchestration.copilot_tool``, ``Services.copilot_service``, any
provider module, ``Orchestration.tool_registry``,
``Core.composition_root``, any Telegram module, any broker/execution
module, or ``Orchestration.paper_execution_tool`` -- the concrete
``"copilot"`` tool this runtime resolves and executes is reached
purely through the injected ``ToolResolver``, never imported or
constructed directly by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from Orchestration.copilot_intent import CopilotIntent
from Orchestration.copilot_intent_classifier import CopilotIntentClassifier
from Orchestration.permission_context import PermissionContext
from Orchestration.tool_context import ToolContext
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_permission_enforcer import (
    ToolPermissionDenied,
    authorize_tool,
    permission_for_tool,
)
from Orchestration.tool_resolver import ToolResolver
from Orchestration.tool_result import ToolResult

#: The single tool name this runtime ever resolves and executes --
#: the existing registered READ_ONLY ``"copilot"`` tool (Task 8/9).
#: LOCKED for this task: no other tool name is ever looked up here.
COPILOT_TOOL_NAME = "copilot"

#: Fixed status labels this runtime itself introduces, for outcomes
#: the underlying Task 7 ``CopilotService``/Task 8 ``CopilotTool`` have
#: no status for (a tool-resolution failure, a permission denial, or
#: an unexpected execution failure at this orchestration layer).
#: Mirrors the plain-string-constant convention already used by
#: ``Services.copilot_service.STATUS_*``.
STATUS_DENIED = "PERMISSION_DENIED"
STATUS_RESOLUTION_FAILED = "TOOL_RESOLUTION_FAILED"
STATUS_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"

#: Fixed, deterministic text for a permission denial. Never computed,
#: never templated with fabricated values -- a plain constant string,
#: mirroring ``Services.copilot_service._TEXT_*`` constants.
_TEXT_DENIED = (
    "This request requires a permission that is not currently granted. "
    "The copilot runtime never retries with an escalated or different "
    "permission."
)


@dataclass(frozen=True)
class CopilotRuntimeResult:
    """Immutable, typed result returned by every
    ``CopilotRuntime.handle`` call, regardless of outcome.

    Attributes:
        success: Whether this call produced a usable, non-denied
            answer. ``False`` for a permission denial, a tool
            resolution failure, or an unexpected execution failure --
            ``True`` for every outcome ``CopilotService.handle``
            itself already treats as a fully-answered, explicit
            outcome (including ``MISSING_CONTEXT``/
            ``NOT_IMPLEMENTED``/``UNSUPPORTED``, which are not
            failures -- see ``Services.copilot_service.
            CopilotResponse.success``).
        intent: The ``CopilotIntent`` this utterance was classified
            into by the existing, deterministic
            ``CopilotIntentClassifier`` -- always populated, even when
            ``success`` is ``False``, so a denial/failure is still
            auditable against the intent that produced it.
        status: A short status label. Either the status the
            underlying ``CopilotResponse`` already carried, or one of
            this module's own ``STATUS_DENIED`` /
            ``STATUS_RESOLUTION_FAILED`` / ``STATUS_EXECUTION_FAILED``
            labels.
        text: The natural-language answer for this call, when one
            exists. ``None`` for a resolution/execution failure with
            no underlying response to draw from.
        source: ``"deterministic"`` unless the underlying
            ``CopilotResponse`` reports ``"llm"`` (``EXPLAIN_DECISION``
            narration only -- see ``Services.copilot_service``).
        denied: ``True`` only when this call was rejected by the
            permission boundary (either this runtime's own READ_ONLY
            scope check or ``authorize_tool`` itself). ``False`` for
            every other outcome, including ``UNSUPPORTED``/
            ``MISSING_CONTEXT``/``NOT_IMPLEMENTED``, which are
            explicit answers, not denials.
        response: The exact underlying ``Services.copilot_service.
            CopilotResponse`` instance the resolved tool returned,
            verbatim -- never re-serialized, summarized, or otherwise
            transformed. ``None`` when no such response exists (a
            resolution failure, a permission denial, or an unexpected
            execution failure).
        error: Human-readable explanation of why ``success`` is
            ``False``. ``None`` whenever ``success`` is ``True``.
    """

    success: bool
    intent: CopilotIntent
    status: Optional[str]
    text: Optional[str] = None
    source: str = "deterministic"
    denied: bool = False
    response: Any = None
    error: Optional[str] = None


class CopilotRuntime:
    """Thin orchestrator: classify, resolve, authorize, execute --
    nothing else.

    Holds exactly two collaborators, both supplied by the caller at
    construction and never rebuilt or replaced afterward: the
    ``ToolResolver`` to resolve the ``"copilot"`` tool through, and an
    optional ``PermissionContext`` to authorize against. Stateless
    across calls -- every ``handle()`` invocation depends only on its
    own arguments and these two fixed collaborators.
    """

    def __init__(
        self,
        tool_resolver: ToolResolver,
        permission_context: Optional[PermissionContext] = None,
        tool_name: str = COPILOT_TOOL_NAME,
    ) -> None:
        """Wire up the runtime via dependency injection only.

        Args:
            tool_resolver: The already-constructed, canonical
                ``ToolResolver`` to resolve the copilot tool through.
                Never constructed here. Stored by identity.
            permission_context: Optional ``PermissionContext`` this
                runtime authorizes every ``handle()`` call against.
                Stored once, by identity, and never mutated, rebuilt,
                or swapped for a different instance afterward.
                Defaults to ``None`` (fail-closed for anything other
                than READ_ONLY, per ``authorize_tool``'s own
                contract -- READ_ONLY itself is unaffected either
                way).
            tool_name: The registry name to resolve on every call.
                Defaults to ``COPILOT_TOOL_NAME`` (``"copilot"``) --
                overridable only for a test double registered under a
                different name; this task never resolves any other
                tool in production use.
        """
        self._tool_resolver = tool_resolver
        self._permission_context = permission_context
        self._tool_name = tool_name

    def handle(
        self,
        utterance: str,
        context_parameters: Optional[Mapping[str, Any]] = None,
    ) -> CopilotRuntimeResult:
        """Classify ``utterance``, resolve and authorize the copilot
        tool, and -- if authorized -- execute it exactly once.

        Args:
            utterance: Free-form caller text. Forwarded verbatim (see
                ``CopilotIntentClassifier.classify`` and
                ``Orchestration.copilot_tool.CopilotTool.execute`` for
                their own normalization/fallback rules on non-``str``
                or empty input).
            context_parameters: Optional caller-supplied context --
                any of the keys ``Orchestration.copilot_tool.
                CopilotTool`` already documents (``memory_store``,
                ``memory_query``, ``decision_brief``, ``provider``,
                ``portfolio_summary``, ``status_text``). Forwarded by
                identity into the ``ToolContext`` this runtime builds
                -- never copied, transformed, or invented. A ``None``
                or non-``Mapping`` value is treated as empty.

        Returns:
            A ``CopilotRuntimeResult`` describing the outcome. Never
            raises: a tool-resolution failure, a permission denial, or
            an unexpected execution failure are all returned as an
            explicit, ``success=False`` result rather than propagated
            as an exception -- with the single, deliberate exception
            of a genuinely invalid constructor argument, which fails
            at construction time, not here.
        """
        intent = CopilotIntentClassifier().classify(utterance)

        parameters = dict(context_parameters) if isinstance(context_parameters, Mapping) else {}
        parameters["utterance"] = utterance if isinstance(utterance, str) else ""

        try:
            tool = self._tool_resolver.resolve(self._tool_name)
        except Exception as exc:  # noqa: BLE001 -- resolution failure is an explicit, returned outcome, never a crash.
            return CopilotRuntimeResult(
                success=False,
                intent=intent,
                status=STATUS_RESOLUTION_FAILED,
                error=str(exc),
            )

        # Unwrap exactly one PermissionedTool layer (if present) to
        # find the declared permission this runtime's own READ_ONLY
        # scope check and `authorize_tool` call both evaluate against
        # -- mirroring `Orchestration.tool_permission_enforcer.
        # permission_for_tool`'s own `getattr(tool, "permission", ...)`
        # convention, which already treats an undeclared tool as
        # READ_ONLY.
        declared_tool = getattr(tool, "wrapped_tool", tool)
        declared_permission = permission_for_tool(declared_tool)

        if declared_permission is not ToolPermission.READ_ONLY:
            # Hard boundary (LOCKED): this runtime never proceeds past
            # this point for anything other than a READ_ONLY-declared
            # tool, regardless of what `authorize_tool`/
            # `self._permission_context` would otherwise allow.
            return CopilotRuntimeResult(
                success=False,
                intent=intent,
                status=STATUS_DENIED,
                text=_TEXT_DENIED,
                denied=True,
                error=(
                    f"CopilotRuntime only ever executes a READ_ONLY tool; "
                    f"'{self._tool_name}' declares {declared_permission.value!r}."
                ),
            )

        try:
            authorize_tool(declared_tool, self._permission_context)
        except ToolPermissionDenied as exc:
            # Explicit, auditable denial -- never retried, never
            # re-authorized with a stronger/different permission, and
            # the tool's own `execute()` is never reached.
            return CopilotRuntimeResult(
                success=False,
                intent=intent,
                status=STATUS_DENIED,
                text=_TEXT_DENIED,
                denied=True,
                error=str(exc),
            )

        tool_context = ToolContext(task=None, parameters=parameters)

        try:
            tool_result: ToolResult = tool.execute(tool_context)
        except ToolPermissionDenied as exc:
            # Defense in depth: if `tool` is itself a PermissionedTool
            # bound to a different PermissionContext than the one this
            # runtime just authorized against, its own internal
            # `authorize_tool` call may still deny here. Surfaced
            # identically to the case above -- never retried, never
            # escalated.
            return CopilotRuntimeResult(
                success=False,
                intent=intent,
                status=STATUS_DENIED,
                text=_TEXT_DENIED,
                denied=True,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 -- an unexpected execution failure is an explicit, returned outcome, never a crash.
            # Note: an unhealthy/unavailable LLM provider is already
            # handled *inside* `Services.copilot_service.CopilotService`
            # (Task 7's own `_provider_is_healthy` guard) and never
            # raises out of `tool.execute()` in the first place -- this
            # branch exists only for a genuinely unexpected failure at
            # the tool layer itself, not for the documented
            # provider-unavailable case.
            return CopilotRuntimeResult(
                success=False,
                intent=intent,
                status=STATUS_EXECUTION_FAILED,
                error=str(exc),
            )

        response = tool_result.output

        return CopilotRuntimeResult(
            success=bool(tool_result.success),
            intent=getattr(response, "intent", intent),
            status=getattr(response, "status", None),
            text=getattr(response, "text", None),
            source=getattr(response, "source", "deterministic"),
            denied=False,
            response=response,
            error=tool_result.error,
        )