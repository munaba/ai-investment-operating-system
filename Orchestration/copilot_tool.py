"""CopilotTool -- Phase F, Task 8: connects the existing
``Services.copilot_service.CopilotService`` to the existing AIOS
tool/permission model (``Orchestration.base_tool.BaseTool`` /
``Orchestration.tool_permission.ToolPermission`` /
``Orchestration.tool_permission_enforcer.authorize_tool`` /
``Orchestration.permissioned_tool.PermissionedTool``), giving the
copilot a real, Hermes/OpenClaw-like capability boundary.

Scope note (LOCKED for this task): this module introduces exactly two
things.

  1. ``COPILOT_TOOL_DESCRIPTOR`` -- a single ``Orchestration.
     tool_descriptor.ToolDescriptor`` describing this Tool's identity
     and capability set, using the existing descriptor shape and
     nothing new.
  2. ``CopilotTool`` -- a thin ``BaseTool`` that delegates every
     ``execute(context)`` call to exactly one already-built
     ``Services.copilot_service.CopilotService.handle()`` call, and
     nothing else.

Why one Tool, not four: ``CopilotService.handle()`` (Task 7) already
classifies the utterance and dispatches to exactly one of its five
deterministic branches (``EXPLAIN_DECISION``, ``RECALL_PREFERENCE``,
``SUMMARIZE_PORTFOLIO``, ``ASK_STATUS``, ``UNSUPPORTED``) -- every one
of which is read-only by construction (see that module's own
docstring: "There is no path in this module that falls back to a
financial action, a paper order, a risk-limit change, a permission
change, a memory write, or a Telegram side effect"). Wrapping that one
facade in one READ_ONLY-declared ``BaseTool`` already gives the
copilot exactly the four read capabilities this task requires --
explain a decision, read a portfolio/report summary, read a stored
memory/preference, and read status -- without inventing a second
dispatch mechanism, a second set of Tool classes, or a second
permission system. This is the narrowest possible integration: this
module contains no business logic of its own.

Permission declaration (LOCKED mechanism, Activation 12.1, identical
to ``Orchestration.paper_execution_tool.PaperExecutionTool``'s own
convention): a plain class attribute, ``permission = ToolPermission.
READ_ONLY``, read via ``Orchestration.tool_permission_enforcer.
permission_for_tool``'s existing ``getattr(tool, "permission",
ToolPermission.READ_ONLY)`` mechanism. ``CopilotTool`` never declares
PAPER_EXECUTION, LIVE_EXECUTION, or DESTRUCTIVE_ADMIN, and never will
-- every capability ``CopilotService.handle()`` exposes is read-only,
so no other declaration is ever correct for this class.

This module deliberately does NOT:

  * perform its own permission check. ``CopilotTool`` never imports or
    calls ``Orchestration.tool_permission_enforcer.authorize_tool`` --
    that call belongs solely to whichever wrapper (``PermissionedTool``
    / ``Orchestration.agents_tool_permission_adapter.
    AgentsToolPermissionAdapter``) this Tool is composed behind. This
    class declares its own required permission and nothing more;
    enforcing that declaration is the wrapper's job.
  * construct a ``MemoryStore``, a ``DecisionBrief``, a portfolio
    summary, a status string, or a provider. Every one of those is
    read straight out of ``context.parameters`` (the same duck-typed,
    never-raising extraction convention already used by
    ``Orchestration.market_price_tool.MarketPriceTool`` and
    ``Orchestration.paper_execution_tool.PaperExecutionTool``) and
    forwarded to ``CopilotRequestContext`` by identity -- never
    copied, transformed, or invented.
  * add a second permission system, a second facade, or a second copy
    of any Task 2--7 component. It imports exactly
    ``Services.copilot_service.CopilotService``/
    ``CopilotRequestContext`` and constructs one ``CopilotService()``
    per ``execute()`` call, mirroring ``CopilotService`` itself being
    documented as stateless/cheap to construct fresh.

Context contract (LOCKED for this task): ``context.parameters`` is
expected to expose the following optional keys, forwarded by identity
to ``CopilotRequestContext`` with identical names -- ``utterance``
(required; falls back to the empty string, which
``CopilotIntentClassifier`` already classifies as ``UNSUPPORTED``),
``memory_store``, ``memory_query``, ``decision_brief``, ``provider``,
``portfolio_summary``, ``status_text``. Any object exposing a
``.parameters`` mapping with these keys works identically; a missing
``.parameters`` or a ``.parameters`` that is not a ``Mapping`` is
treated as empty, mirroring every existing Tool's own defensive
extraction -- the resulting call then flows through
``CopilotService.handle()``'s own explicit ``MISSING_CONTEXT``/
``NOT_IMPLEMENTED``/``UNSUPPORTED`` branches exactly as it already
does for any other caller.

Return shape: a ``ToolResult`` with ``success=response.success``,
``output=response`` (the exact ``Services.copilot_service.
CopilotResponse`` instance ``CopilotService.handle()`` returned --
never re-serialized, summarized, or otherwise transformed),
``error=response.error``, and ``metadata={}``. Denial (a permission
rejection) never reaches this method at all -- it is raised by the
wrapping ``PermissionedTool``/``AgentsToolPermissionAdapter`` before
``execute()`` is ever called, exactly as ``Orchestration.
tool_permission_enforcer.authorize_tool`` already documents.

Dependencies (LOCKED): this module imports only
``Orchestration.base_tool.BaseTool``,
``Orchestration.tool_descriptor.ToolDescriptor``,
``Orchestration.tool_permission.ToolPermission``,
``Orchestration.tool_result.ToolResult``,
``Services.copilot_service.CopilotRequestContext``/``CopilotService``,
and stdlib ``typing``. It does not import
``Orchestration.tool_permission_enforcer``,
``Orchestration.permissioned_tool``,
``Orchestration.agents_tool_permission_adapter``,
``Orchestration.permission_context``, ``Orchestration.tool_registry``,
``Orchestration.tool_resolver``, ``Agents.tool_registry``,
``Agents.executor``, any Telegram module, or
``Core.composition_root`` -- wiring this class into any of those
belongs solely to a future Composition Root change, not to this
module itself (out of scope for this task).
"""

from __future__ import annotations

from typing import Any, Mapping

from Orchestration.base_tool import BaseTool
from Orchestration.tool_descriptor import ToolDescriptor
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_result import ToolResult
from Services.copilot_service import CopilotRequestContext, CopilotService

#: Passive metadata layer describing this Tool's identity and
#: capability set, using the existing ``ToolDescriptor`` shape only.
#: Never constructed, registered, or consulted by ``CopilotTool``
#: itself -- available for a future registry/composition-root caller
#: that wants a descriptor without instantiating the Tool.
COPILOT_TOOL_DESCRIPTOR = ToolDescriptor(
    name="copilot",
    description=(
        "Read-only copilot capability boundary: explain an existing "
        "DecisionBrief, read an already-computed portfolio/report "
        "summary, read a stored memory/preference, or read "
        "already-computed status text. Delegates every call to the "
        "existing CopilotService -- never executes a paper or live "
        "order, never mutates a risk limit or permission, and never "
        "invents a fact not already present in persisted/service "
        "data."
    ),
    metadata={},
    tags=("copilot", "read-only"),
)


class CopilotTool(BaseTool):
    """A thin, READ_ONLY-classified Tool that delegates directly to an
    already-constructed ``CopilotService.handle()`` call.

    Holds no collaborators and no state of its own -- construction
    takes no arguments, mirroring ``CopilotService`` itself.
    """

    #: LOCKED permission declaration (Activation 12.1's
    #: ``ToolPermission`` vocabulary, Activation 12.3's
    #: ``getattr(tool, "permission", ...)`` convention). Every
    #: capability this Tool exposes is read-only; this declaration is
    #: never anything other than ``READ_ONLY``.
    permission = ToolPermission.READ_ONLY

    @property
    def name(self) -> str:
        """This Tool's stable name.

        Returns:
            The literal string ``"copilot"``.
        """
        return "copilot"

    @property
    def description(self) -> str:
        """This Tool's human-readable description.

        Returns:
            ``COPILOT_TOOL_DESCRIPTOR.description``, the single
            source of truth for this Tool's description.
        """
        return COPILOT_TOOL_DESCRIPTOR.description

    def execute(self, context: Any) -> ToolResult:
        """Extract ``CopilotService.handle()``'s inputs from
        ``context.parameters`` and delegate to it exactly once.

        Performs no validation, no classification, no permission
        check, and no computation of its own -- every value read from
        ``context.parameters`` is forwarded to ``CopilotRequestContext``
        exactly as given (``None`` for anything missing), and the
        resulting ``CopilotResponse`` is wrapped, unchanged, in a
        ``ToolResult``.

        Args:
            context: Expected to be a ``Orchestration.tool_context.
                ToolContext``-shaped object exposing a ``.parameters``
                mapping with the keys documented in this module's own
                docstring. Any other shape (``None``, a plain string,
                an object with no ``.parameters``, or a ``.parameters``
                that is not a ``Mapping``) is treated as if no
                parameters were supplied -- mirroring
                ``Orchestration.market_price_tool.MarketPriceTool.
                execute()``'s own defensive extraction -- which then
                surfaces as ``CopilotService.handle()``'s own
                ``UNSUPPORTED`` classification of the empty-string
                fallback utterance.

        Returns:
            A ``ToolResult`` with ``success=response.success``,
            ``output=response`` (the exact ``CopilotResponse``
            ``CopilotService.handle()`` returned, unchanged),
            ``error=response.error``, and ``metadata={}``.
        """
        parameters = getattr(context, "parameters", None)
        if not isinstance(parameters, Mapping):
            parameters = {}

        utterance = parameters.get("utterance")
        if not isinstance(utterance, str):
            utterance = ""

        request_context = CopilotRequestContext(
            memory_store=parameters.get("memory_store"),
            memory_query=parameters.get("memory_query"),
            decision_brief=parameters.get("decision_brief"),
            provider=parameters.get("provider"),
            portfolio_summary=parameters.get("portfolio_summary"),
            status_text=parameters.get("status_text"),
        )

        response = CopilotService().handle(utterance, request_context)

        return ToolResult(
            success=response.success,
            output=response,
            error=response.error,
            metadata={},
        )