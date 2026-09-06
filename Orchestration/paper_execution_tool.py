"""PaperExecutionTool -- Activation 12.8's PAPER_EXECUTION-classified
Tool.

This module gives the existing, LOCKED financial state machine --

    PaperTradingEngine.submit_order()
        -> 19 pre-trade gates (Activation 3.2 + 8.4 + 9.4 + 10.5 +
           10.6 + 11.14/11.15, all read-only, in order)
        -> OrderLifecycleService.create_order()
        -> ExecutionService.execute_order()
        -> AccountBalanceService.apply_trade() /
           PositionManager.apply_trade()
        -> OrderIdempotencyRepository.create()
        -> Trade

-- a Tool-shaped front door that Activation 12's permission
architecture (``Orchestration.permissioned_tool.PermissionedTool`` /
``Orchestration.agents_tool_permission_adapter.
AgentsToolPermissionAdapter``, both calling ``Orchestration.
tool_permission_enforcer.authorize_tool`` and only that function) can
gate before it is ever reached. This module does not add a second
financial execution path: every submitted order still runs through
the exact same ``PaperTradingEngine.submit_order()`` entry point the
existing CLI ``paper buy``/``paper sell`` commands already call
directly (``main.py``, unmodified by this Activation).

Scope (LOCKED for this Activation): this class does exactly one
thing. It reads the nine ``PaperTradingEngine.submit_order()``
arguments out of a caller-supplied ``Orchestration.tool_context.
ToolContext``-shaped object's ``.parameters`` mapping (the same
duck-typed, never-raising extraction convention already used by
``Orchestration.market_price_tool.MarketPriceTool`` and
``Orchestration.market_news_tool.MarketNewsTool``), calls
``PaperTradingEngine.submit_order(**those_arguments)`` on the one
instance it was constructed with, and returns an ``Orchestration.
tool_result.ToolResult`` wrapping whatever ``Trade`` that call
produced -- unchanged, uninterpreted, and unwrapped a second time.

It deliberately does NOT:

  * perform risk validation, user-approval decisions, kill-switch
    checks, account checks, margin checks, stop-loss checks, or
    quantity validation -- every one of those is already an
    authoritative, LOCKED ``PaperTradingEngine.submit_order()`` gate
    (see that module's own docstring for the full, numbered list).
    Duplicating even one of them here would create a second,
    divergent copy of a financial gate the roadmap explicitly forbids.
  * catch, suppress, reinterpret, or translate any exception
    ``submit_order()`` raises (e.g. ``Core.exceptions.ValidationError``
    for a failed pre-trade gate) -- it propagates straight out of
    ``execute()`` unchanged, exactly like every other gate rejection
    already does for the existing CLI path.
  * perform its own permission check. ``PaperExecutionTool`` never
    imports or calls ``Orchestration.tool_permission_enforcer.
    authorize_tool`` -- that call belongs solely to whichever wrapper
    (``PermissionedTool``/``AgentsToolPermissionAdapter``) this Tool
    is composed behind. This class declares its own required
    permission (see ``permission`` below) and nothing more; enforcing
    that declaration is the wrapper's job, not this class's.
  * construct, cache, or hold a second ``PaperTradingEngine``,
    ``OrderLifecycleService``, ``ExecutionService``, or any other
    Business/Repository collaborator -- the one ``PaperTradingEngine``
    instance passed into ``__init__`` (the same, already-fully-wired
    production instance ``Core.composition_root.
    _build_paper_trading_engine`` constructs) is the sole collaborator
    this class ever holds.

Permission declaration (LOCKED mechanism, Activation 12.1): a plain
class attribute, ``permission = ToolPermission.PAPER_EXECUTION``,
read via ``Orchestration.tool_permission_enforcer.
permission_for_tool``'s existing ``getattr(tool, "permission",
ToolPermission.READ_ONLY)`` convention -- the identical mechanism
``Tests/test_activation12_3_permission_wiring.py``'s own ``_FakeTool``
already exercises for PAPER_EXECUTION/LIVE_EXECUTION/
DESTRUCTIVE_ADMIN. No new declaration mechanism, decorator, registry,
or metadata object is introduced.

Context contract (LOCKED, Activation 12.8 Phase 1 audit): this class
reads ``context.parameters`` -- a ``typing.Mapping[str, Any]`` --
exactly as ``Orchestration.tool_context.ToolContext`` already defines
it. No new context shape (``context.order``, ``context.arguments``,
``context.payload``, or similar) is invented. Any object exposing a
``.parameters`` mapping with the nine keys below works identically;
anything else (a missing ``.parameters``, or a ``.parameters`` that is
not a ``Mapping``) is treated as an empty mapping, mirroring
``MarketPriceTool.execute()``'s own defensive extraction -- the
resulting ``None``/missing values are then handled entirely by
``PaperTradingEngine.submit_order()``'s own gates (e.g. a missing
``signal_evidence`` fails gate 2; a missing ``user_approval`` fails
gate 3), never by a check this class performs itself.

Recognized ``context.parameters`` keys, forwarded to
``PaperTradingEngine.submit_order()`` by identical name (LOCKED,
matching that method's own signature exactly -- see its docstring for
each argument's full meaning):

    ``account_id``, ``symbol``, ``action``, ``quantity``,
    ``requested_price``, ``executed_at``, ``signal_evidence``,
    ``user_approval``, ``idempotency_key``, and the optional
    ``stop_loss`` (defaults to ``None`` when absent, identical to
    ``submit_order()``'s own default).

Return shape: a ``ToolResult`` with ``success=True``, ``error=None``,
``metadata={}``, and ``output`` set to the exact ``Business.
paper_trading_engine.Trade``-typed object ``submit_order()`` returned
-- never re-serialized, summarized, or otherwise transformed. Nothing
about the returned ``Trade`` is inspected by this class.

Dependencies (LOCKED): this module imports only ``Business.
paper_trading_engine.PaperTradingEngine`` (for the constructor's type
annotation and to call ``.submit_order()`` on the injected instance --
never to construct one), ``Orchestration.base_tool.BaseTool``,
``Orchestration.tool_permission.ToolPermission``, ``Orchestration.
tool_result.ToolResult``, and stdlib ``typing``. It does not import
``Orchestration.tool_permission_enforcer``, ``Orchestration.
permissioned_tool``, ``Orchestration.agents_tool_permission_adapter``,
``Orchestration.permission_context``, ``Orchestration.tool_registry``,
``Orchestration.tool_resolver``, ``Agents.tool_registry``,
``Agents.executor``, ``Agents.sandbox``, or ``Core.composition_root``
-- wiring this class into any of those belongs solely to the
Composition Root (see ``Core.composition_root.
_build_paper_execution_tool_resolver``), never to this module itself.
"""

from __future__ import annotations

from typing import Any, Mapping

from Business.paper_trading_engine import PaperTradingEngine
from Orchestration.base_tool import BaseTool
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_result import ToolResult


class PaperExecutionTool(BaseTool):
    """A thin, PAPER_EXECUTION-classified Tool that delegates directly
    to an already-constructed ``PaperTradingEngine.submit_order()``.

    Holds exactly one collaborator -- the injected
    ``PaperTradingEngine`` instance -- and nothing else. Never
    constructs, copies, or mutates it. No other state, no cache, no
    retry, no logging.
    """

    #: LOCKED permission declaration (Activation 12.1's ``ToolPermission``
    #: vocabulary, Activation 12.3's ``getattr(tool, "permission", ...)``
    #: convention). A plain class attribute is sufficient -- the same
    #: mechanism ``Tests/test_activation12_3_permission_wiring.py``'s own
    #: ``_FakeTool`` already relies on for every non-READ_ONLY case.
    permission = ToolPermission.PAPER_EXECUTION

    def __init__(self, paper_trading_engine: PaperTradingEngine) -> None:
        """Wire up this Tool via dependency injection only.

        Args:
            paper_trading_engine: The already-constructed
                ``Business.paper_trading_engine.PaperTradingEngine``
                instance to delegate every ``execute()`` call to.
                Never constructed here, never copied. Stored by
                identity -- this class calls exactly one method on it,
                ``submit_order(...)``, and nothing else.
        """
        self._paper_trading_engine = paper_trading_engine

    @property
    def name(self) -> str:
        """This Tool's stable name.

        Returns:
            The literal string ``"paper_execution"``.
        """
        return "paper_execution"

    @property
    def description(self) -> str:
        """This Tool's human-readable description.

        Returns:
            A description naming the exact production capability this
            Tool exposes -- the existing ``PaperTradingEngine.
            submit_order()`` financial state machine, unchanged.
        """
        return (
            "Submit a single paper trading order through the existing "
            "PaperTradingEngine.submit_order() financial state "
            "machine (19 pre-trade gates, then order creation and "
            "execution). This Tool performs no validation of its "
            "own -- every gate remains owned by PaperTradingEngine."
        )

    def execute(self, context: Any) -> ToolResult:
        """Extract ``PaperTradingEngine.submit_order()``'s arguments
        from ``context.parameters`` and delegate to it exactly once.

        Performs no validation, no permission check, and no gate of
        its own -- every value read from ``context.parameters`` is
        forwarded to ``submit_order()`` exactly as given (including
        ``None`` for anything missing), and any exception
        ``submit_order()`` raises (e.g. ``Core.exceptions.
        ValidationError`` for a failed pre-trade gate) propagates out
        of this method unchanged -- never caught, suppressed, or
        reinterpreted here.

        Args:
            context: Expected to be a ``Orchestration.tool_context.
                ToolContext``-shaped object exposing a
                ``.parameters`` mapping with the nine
                ``PaperTradingEngine.submit_order()`` keys documented
                in this module's own docstring (``stop_loss``
                optional). Any other shape (``None``, a plain string,
                an object with no ``.parameters``, or a
                ``.parameters`` that is not a ``Mapping``) is treated
                as if no parameters were supplied -- mirroring
                ``Orchestration.market_price_tool.MarketPriceTool.
                execute()``'s own defensive extraction -- which then
                surfaces as whichever ``PaperTradingEngine`` gate
                first rejects the resulting missing/``None`` argument.

        Returns:
            A ``ToolResult`` with ``success=True``, ``error=None``,
            ``metadata={}``, and ``output`` set to the exact
            ``Business.paper_trading_engine.Trade``-typed object
            ``PaperTradingEngine.submit_order()`` returned --
            unchanged.
        """
        parameters = getattr(context, "parameters", None)
        if not isinstance(parameters, Mapping):
            parameters = {}

        trade = self._paper_trading_engine.submit_order(
            account_id=parameters.get("account_id"),
            symbol=parameters.get("symbol"),
            action=parameters.get("action"),
            quantity=parameters.get("quantity"),
            requested_price=parameters.get("requested_price"),
            executed_at=parameters.get("executed_at"),
            signal_evidence=parameters.get("signal_evidence"),
            user_approval=parameters.get("user_approval"),
            idempotency_key=parameters.get("idempotency_key"),
            stop_loss=parameters.get("stop_loss"),
        )

        return ToolResult(success=True, output=trade, error=None, metadata={})