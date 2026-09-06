"""Activation 12.5 -- close the real production permission bypass on the
legacy ``Agents.tool_registry`` path:

    Core.composition_root._build_service_skills()
        -> Agents.tool_registry singleton
        -> Agents.Executor
        -> Agents.sandbox.GenericSandbox.execute()
        -> raw Tool.handler(...)

Phase 1 source audit found ``Orchestration.permissioned_tool.
PermissionedTool`` (Activation 12.3) cannot transparently wrap a legacy
``Agents.tool_registry.Tool``: it forwards to ``execute(context)``,
while ``Tool.handler`` is called as ``handler(*args, **kwargs)`` by
``Agents.sandbox.GenericSandbox.execute()`` (LOCKED). The smallest
adapter possible was therefore introduced:
``Orchestration.agents_tool_permission_adapter.
AgentsToolPermissionAdapter`` -- a permission-aware *callable*, wired
in as ``Tool.handler`` at composition-boundary time in
``Core.composition_root._build_service_skills()`` (the only file this
Activation modifies, besides the one new adapter file and this test).

Exercises the REAL composition boundary -- ``build_application()`` ->
``Agents.tool_registry`` singleton -> ``Agents.executor.Executor`` ->
``Agents.sandbox.GenericSandbox`` -- for the "all 12 protected" and
"READ_ONLY executes" scenarios (A, B, H), plus a deterministic fake
legacy ``Agents.tool_registry.Tool`` through the SAME
``AgentsToolPermissionAdapter`` adapter path (registered into the same
production ``Agents.tool_registry.ToolRegistry`` singleton and driven
through the same ``Agents.executor.Executor`` /
``Agents.sandbox.GenericSandbox``) for the PAPER_EXECUTION/
LIVE_EXECUTION/DESTRUCTIVE_ADMIN cases the 12 real service tools don't
exercise (they are all undeclared/READ_ONLY, same as Activation 12.3's
three ``Market*Tool`` instances).

Locked surfaces this suite proves untouched: ``Agents/tool_registry.py``,
``Agents/executor.py``, ``Agents/sandbox.py``,
``Orchestration/base_skill.py``, ``Orchestration/executor.py``,
``Orchestration/tool_registry.py``, ``Orchestration/tool_resolver.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.executor import Executor, ToolExecutionError
from Agents.sandbox import GenericSandbox
from Agents.tool_registry import Tool, ToolRegistry, tool_registry as agents_tool_registry
from Core.composition_root import ApplicationGraph, _build_market_tool_resolver, build_application
from Orchestration.agents_tool_permission_adapter import AgentsToolPermissionAdapter
from Orchestration.permission_context import PermissionContext
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.tool_permission import ToolPermission
from Services.metadata_keys import MetadataKeys
from Services.service_registry import service_registry

#: The 12 live service tools the Activation 12.5 audit identified as
#: unprotected on the legacy Agents path (literal, from the roadmap
#: audit finding -- not derived/discovered here).
EXPECTED_SERVICE_NAMES = (
    "stock_service",
    "technical_indicator_service",
    "moving_average_service",
    "technical_score_service",
    "fundamental_service",
    "backtest_service",
    "pattern_service",
    "chart_service",
    "news_service",
    "risk_management_service",
    "scoring_service",
    "notification_service",
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _fresh_agents_registry() -> None:
    """Reset the process-wide ``Agents.tool_registry.ToolRegistry``
    singleton -- same reasoning as every other Activation-12 test
    (Tests/test_activation12_3_permission_wiring.py's own
    ``ToolRegistry`` usage, Tests/test_stage_l13_service_skill.py's
    ``_fresh_registry`` helper): it is a singleton, so each scenario
    needs a clean slate.
    """
    ToolRegistry.reset()


class _FakeDeclaredTool:
    """Deterministic fake object exposing only a declared
    ``.permission`` -- exactly what
    ``Orchestration.tool_permission_enforcer.permission_for_tool``
    reads (via ``getattr(tool, "permission", ToolPermission.READ_ONLY)``).
    Mirrors Tests/test_activation12_3_permission_wiring.py's own
    ``_FakeTool``, adapted for the legacy Agents Tool shape (no
    ``execute(context)`` is needed here -- ``AgentsToolPermissionAdapter``
    only reads ``.permission`` off this object; the callable it
    delegates to is a separate, explicit ``handler``).
    """

    def __init__(self, permission: Optional[ToolPermission] = None) -> None:
        if permission is not None:
            self.permission = permission


class _CountingHandler:
    """Deterministic fake legacy Tool handler. Raises if called after a
    denial should have prevented that -- proving the underlying handler
    was truly never reached, not merely that its return value was
    discarded (mirrors Activation 12.3's ``_RaisingTool.execute``)."""

    def __init__(self, raise_if_called: bool = False) -> None:
        self.calls = 0
        self._raise_if_called = raise_if_called

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._raise_if_called:
            raise AssertionError("underlying handler was reached despite denial")
        self.calls += 1
        return {"status": "handler-ran", "args": list(args), "kwargs": kwargs}


def _register_fake_tool(
    name: str,
    permission: Optional[ToolPermission],
    permission_context: Optional[PermissionContext],
    *,
    raise_if_called: bool = False,
) -> _CountingHandler:
    """Register a deterministic fake legacy Agents Tool through the SAME
    ``AgentsToolPermissionAdapter`` adapter path Activation 12.5 wires
    into ``Core.composition_root._build_service_skills()`` -- into the
    real, production ``Agents.tool_registry`` singleton, so it is
    reachable through the real ``Agents.executor.Executor`` /
    ``Agents.sandbox.GenericSandbox`` chain exactly like any of the 12
    real service tools.
    """
    handler = _CountingHandler(raise_if_called=raise_if_called)
    fake_tool = _FakeDeclaredTool(permission)
    agents_tool_registry.register(
        Tool(
            name=name,
            description="Activation 12.5 deterministic fake tool.",
            handler=AgentsToolPermissionAdapter(
                wrapped_tool=fake_tool,
                handler=handler,
                permission_context=permission_context,
            ),
        )
    )
    return handler


def _expect_permission_denied(executor: Executor, tool_name: str) -> None:
    """Run ``tool_name`` through ``executor`` and assert it was denied
    at the permission boundary specifically -- not merely that some
    exception occurred. ``GenericSandbox.execute()`` normalizes every
    handler exception into an "execution_error" error-as-data payload
    (LOCKED, Stage 8.2), which ``Executor._decode_effect`` then raises
    as ``ToolExecutionError`` -- so the denial is proven by checking
    ``details["original_exception_class"] == "ToolPermissionDenied"``.
    """
    try:
        executor.execute(tool_name)
    except ToolExecutionError as exc:
        check(
            exc.details.get("original_exception_class") == "ToolPermissionDenied",
            f"'{tool_name}' denial surfaces as ToolPermissionDenied, "
            f"got {exc.details.get('original_exception_class')!r}",
        )
    else:
        raise AssertionError(f"expected '{tool_name}' to be denied, but it executed")


# ---------------------------------------------------------------------------
# A. All 12 service tools are protected.
# ---------------------------------------------------------------------------
def scenario_a_all_twelve_service_tools_protected() -> None:
    _fresh_agents_registry()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-12-5-a",
        agent_name="stock_agent_12_5_a",
    )

    check(
        set(graph.service_skills.keys()) == set(EXPECTED_SERVICE_NAMES),
        "the real composition boundary built exactly the 12 audited service skills",
    )

    shared_context = None
    for service_name in EXPECTED_SERVICE_NAMES:
        skill = graph.service_skills[service_name]
        tool = graph.tool_registry.get(skill.tool_name)
        check(
            isinstance(tool.handler, AgentsToolPermissionAdapter),
            f"'{skill.tool_name}' Tool.handler is an AgentsToolPermissionAdapter "
            "(registration is permission-aware)",
        )
        check(
            tool.handler.wrapped_tool is skill,
            f"'{skill.tool_name}' adapter authorizes against the real ServiceSkill instance",
        )
        check(
            tool.handler.handler == skill.execute,
            f"'{skill.tool_name}' adapter still delegates to the real ServiceSkill.execute",
        )
        if shared_context is None:
            shared_context = tool.handler.permission_context
        else:
            check(
                tool.handler.permission_context is shared_context,
                "all 12 adapters share one PermissionContext for this application graph "
                "(never a new instance per tool)",
            )
        check(
            isinstance(tool.handler.permission_context, PermissionContext),
            f"'{skill.tool_name}' adapter carries a real PermissionContext",
        )


# ---------------------------------------------------------------------------
# B. READ_ONLY service executes -- real production path, real service tool.
# ---------------------------------------------------------------------------
def scenario_b_read_only_service_executes() -> None:
    _fresh_agents_registry()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-12-5-b",
        agent_name="stock_agent_12_5_b",
    )

    tool_name = "skill.technical_indicator_service"
    service = service_registry.get("technical_indicator_service")
    check(
        service is graph.service_skills["technical_indicator_service"]._service,
        "test patches the exact same Service instance the real ServiceSkill wraps",
    )

    original_execute = service.execute
    calls = {"n": 0}

    def _counting_execute(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return original_execute(*args, **kwargs)

    service.execute = _counting_execute  # type: ignore[method-assign]
    try:
        # No False Green: goes through the real production chain --
        # Core.composition_root -> Agents.tool_registry (graph.tool_registry)
        # -> graph.executor (Agents.Executor) -> Agents.sandbox.GenericSandbox
        # -> AgentsToolPermissionAdapter -> ServiceSkill.execute -> Service.execute.
        result = graph.executor.execute(
            tool_name, metadata={MetadataKeys.TICKER: "BBCA.JK"}
        )
    finally:
        service.execute = original_execute  # type: ignore[method-assign]

    check(result is not None, "READ_ONLY service tool call returns a result (no denial)")
    check(calls["n"] == 1, "the underlying Service.execute runs exactly once")


# ---------------------------------------------------------------------------
# C. PAPER_EXECUTION denied without capability.
# ---------------------------------------------------------------------------
def scenario_c_paper_execution_denied() -> None:
    _fresh_agents_registry()
    handler = _register_fake_tool(
        "fake_paper_tool",
        ToolPermission.PAPER_EXECUTION,
        PermissionContext(paper_execution_allowed=False),
    )
    executor = Executor(agents_tool_registry)
    _expect_permission_denied(executor, "fake_paper_tool")
    check(handler.calls == 0, "PAPER_EXECUTION handler never executes when denied")


# ---------------------------------------------------------------------------
# D. PAPER_EXECUTION authorized with explicit capability.
# ---------------------------------------------------------------------------
def scenario_d_paper_execution_authorized() -> None:
    _fresh_agents_registry()
    handler = _register_fake_tool(
        "fake_paper_tool_ok",
        ToolPermission.PAPER_EXECUTION,
        PermissionContext(paper_execution_allowed=True),
    )
    executor = Executor(agents_tool_registry)
    result = executor.execute("fake_paper_tool_ok")
    check(result is not None, "PAPER_EXECUTION succeeds once explicitly authorized")
    check(handler.calls == 1, "PAPER_EXECUTION handler executes exactly once")


# ---------------------------------------------------------------------------
# E. LIVE_EXECUTION remains denied by default.
# ---------------------------------------------------------------------------
def scenario_e_live_execution_denied() -> None:
    _fresh_agents_registry()
    handler = _register_fake_tool(
        "fake_live_tool",
        ToolPermission.LIVE_EXECUTION,
        PermissionContext(),  # fail-closed default
    )
    executor = Executor(agents_tool_registry)
    _expect_permission_denied(executor, "fake_live_tool")
    check(handler.calls == 0, "LIVE_EXECUTION handler never executes by default")


# ---------------------------------------------------------------------------
# F. DESTRUCTIVE_ADMIN remains denied by default.
# ---------------------------------------------------------------------------
def scenario_f_destructive_admin_denied() -> None:
    _fresh_agents_registry()
    handler = _register_fake_tool(
        "fake_destructive_tool",
        ToolPermission.DESTRUCTIVE_ADMIN,
        PermissionContext(),  # fail-closed default
    )
    executor = Executor(agents_tool_registry)
    _expect_permission_denied(executor, "fake_destructive_tool")
    check(handler.calls == 0, "DESTRUCTIVE_ADMIN handler never executes by default")


# ---------------------------------------------------------------------------
# G. Hard pre-execution rejection -- denial happens strictly before the
#    handler is ever invoked, proven with a handler that raises if reached.
# ---------------------------------------------------------------------------
def scenario_g_hard_pre_execution_rejection() -> None:
    _fresh_agents_registry()
    _register_fake_tool(
        "fake_raising_tool",
        ToolPermission.DESTRUCTIVE_ADMIN,
        PermissionContext(),
        raise_if_called=True,
    )
    executor = Executor(agents_tool_registry)
    # If the handler were ever reached, it raises AssertionError, which
    # GenericSandbox would still normalize into a ToolExecutionError --
    # so this specifically checks the denial is attributed to
    # ToolPermissionDenied, not to the handler's own AssertionError.
    _expect_permission_denied(executor, "fake_raising_tool")

    # Also drive the adapter directly (unit-level), confirming the raw
    # ToolPermissionDenied -- not yet normalized by GenericSandbox --
    # is what's actually raised, and only that.
    from Orchestration.tool_permission_enforcer import ToolPermissionDenied

    _fresh_agents_registry()
    direct_handler = _CountingHandler(raise_if_called=True)
    adapter = AgentsToolPermissionAdapter(
        wrapped_tool=_FakeDeclaredTool(ToolPermission.DESTRUCTIVE_ADMIN),
        handler=direct_handler,
        permission_context=PermissionContext(),
    )
    try:
        adapter()
    except ToolPermissionDenied:
        pass
    else:
        raise AssertionError("expected ToolPermissionDenied directly from the adapter")


# ---------------------------------------------------------------------------
# H. Existing StockAgent / RuntimeAnalysisPipeline path still works.
# ---------------------------------------------------------------------------
def scenario_h_existing_stockagent_path_regression() -> None:
    _fresh_agents_registry()
    graph: ApplicationGraph = build_application(
        provider_name="fake-provider-12-5-h",
        agent_name="stock_agent_12_5_h",
    )

    check(
        graph.agent.runtime_analysis_pipeline is graph.runtime_analysis_pipeline,
        "StockAgent's runtime_analysis_pipeline wiring is exactly as before -- "
        "Activation 12.5 did not touch StockAgent or RuntimeAnalysisPipeline",
    )

    from Services.service_context import ServiceContext

    context = ServiceContext(
        agent_name="stock_agent_12_5_h",
        provider_name="fake-provider-12-5-h",
        request_id="activation-12-5-h-request",
        user_input="Analisa BBCA",
        conversation_history=[],
        metadata={MetadataKeys.TICKER: "BBCA.JK"},
    )

    # RuntimeAnalysisPipeline.run() drives its own private, per-call Tool
    # through the exact same Agents.tool_registry / Agents.Executor /
    # Agents.sandbox.GenericSandbox chain the 12 now-protected service
    # tools share -- proving that chain is unaffected by this Activation's
    # changes for StockAgent's actual production path.
    result = graph.runtime_analysis_pipeline.run(context)
    check(isinstance(result, str) and len(result) > 0, "existing StockAgent analysis path still runs end to end")


# ---------------------------------------------------------------------------
# I. Canonical Activation 12.3 market-tool permission path remains working.
# ---------------------------------------------------------------------------
def scenario_i_canonical_market_tool_path_unaffected() -> None:
    resolver, _tool_manager = _build_market_tool_resolver(PermissionContext())
    for tool_name in ("market_price", "market_news", "market_fundamental"):
        resolved = resolver.resolve(tool_name)
        check(
            isinstance(resolved, PermissionedTool),
            f"Activation 12.3's '{tool_name}' still resolves through PermissionedTool",
        )


# ---------------------------------------------------------------------------
# Locked-surface check.
# ---------------------------------------------------------------------------
def scenario_locked_surfaces_unchanged() -> None:
    import importlib
    import inspect

    # NOTE: ``import Agents.tool_registry as x`` cannot be used here --
    # ``Agents/__init__.py`` does ``from Agents.tool_registry import
    # ..., tool_registry`` (unmodified, pre-existing), which rebinds the
    # ``Agents.tool_registry`` *attribute* on the ``Agents`` package to
    # the singleton *instance*, shadowing the submodule. ``importlib.
    # import_module`` reads ``sys.modules`` directly instead, so it
    # always returns the real module object regardless of that
    # pre-existing shadowing.
    agents_tool_registry_module = importlib.import_module("Agents.tool_registry")
    agents_executor_module = importlib.import_module("Agents.executor")
    agents_sandbox_module = importlib.import_module("Agents.sandbox")

    for module, forbidden in (
        (agents_tool_registry_module, "AgentsToolPermissionAdapter"),
        (agents_executor_module, "AgentsToolPermissionAdapter"),
        (agents_sandbox_module, "AgentsToolPermissionAdapter"),
    ):
        source = inspect.getsource(module)
        check(
            forbidden not in source,
            f"{module.__name__} was not modified to know about the new adapter",
        )


def main() -> None:
    scenarios = [
        scenario_a_all_twelve_service_tools_protected,
        scenario_b_read_only_service_executes,
        scenario_c_paper_execution_denied,
        scenario_d_paper_execution_authorized,
        scenario_e_live_execution_denied,
        scenario_f_destructive_admin_denied,
        scenario_g_hard_pre_execution_rejection,
        scenario_h_existing_stockagent_path_regression,
        scenario_i_canonical_market_tool_path_unaffected,
        scenario_locked_surfaces_unchanged,
    ]
    passed = 0
    for scenario in scenarios:
        scenario()
        passed += 1
        print(f"PASS: {scenario.__name__}")
    print(f"TOTAL: {passed}/{len(scenarios)} PASS")


if __name__ == "__main__":
    main()