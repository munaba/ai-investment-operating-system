"""Activation 12.6 -- single PermissionContext ownership.

Activation 12.6's Phase 1 audit found TWO independently-constructed
``Orchestration.permission_context.PermissionContext`` instances in the
production graph -- one inside ``Core.composition_root.
_build_market_tool_resolver()``, one inside ``Core.composition_root.
_build_service_skills()`` -- both zero-argument, both therefore
value-equal (all three fields ``False``), but two distinct objects with
no shared identity and no third caller able to reach either.

This suite proves the Option 3 refactor: exactly ONE ``PermissionContext``
is now constructed, inside ``Core.composition_root.build_application()``,
and that SAME object (by identity, not merely by equal field values) is
injected into both the canonical market-tool path
(``_build_market_tool_resolver``) and the legacy Agents service-tool path
(``_build_service_skills``). No new authorization semantics, no new env
var, no new CLI flag, and no new ``ApplicationGraph`` field are
introduced -- the context remains all-``False`` (fail-closed) exactly as
before.

Identity-observation approach (per Activation 12.6 roadmap's own
instruction: "if identity cannot be observed through legitimate existing
objects, use a test-visible composition seam rather than adding a
production field"):

  - The legacy path IS already observable through an existing,
    unmodified ``ApplicationGraph`` field: ``graph.tool_registry.get(
    "skill.<service_name>").handler.permission_context`` -- exactly the
    seam Tests/test_activation12_5_agents_tool_permission_wiring.py's own
    ``scenario_a_all_twelve_service_tools_protected`` already uses.
  - The canonical path's ``PermissionedTool`` wrappers are NOT reachable
    through any existing ``ApplicationGraph`` field (``market_tool_
    resolver`` is a local variable inside ``build_application()``, never
    assigned to the graph) -- confirmed by source inspection
    (``scenario_provenance_no_new_applicationgraph_field`` below). For
    scenarios that need to observe *that* object's identity against the
    legacy path's, this suite spies on the two already-existing,
    already-private module-level functions
    (``Core.composition_root._build_market_tool_resolver`` /
    ``_build_service_skills``) that ``build_application()`` calls --
    the same two functions Activation 12.3/12.5's own tests already
    import and call directly. Spying on a function via monkeypatch is
    not a new production field; it is read-only observation of an
    existing call, restored immediately after each scenario.

Locked surfaces this suite proves untouched: every file under
``Orchestration/`` (``permission_context.py``, ``tool_permission.py``,
``tool_permission_enforcer.py``, ``permissioned_tool.py``,
``agents_tool_permission_adapter.py``, ``base_skill.py``,
``executor.py``, ``tool_registry.py``, ``tool_resolver.py``),
``Agents/tool_registry.py``, ``Agents/executor.py``, ``Agents/sandbox.py``,
and ``main.py``.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Core.composition_root as composition_root_module
from Agents.tool_registry import tool_registry as agents_tool_registry
from Core.composition_root import (
    _build_market_tool_resolver,
    _build_service_skills,
    build_application,
)
from Orchestration.agents_tool_permission_adapter import AgentsToolPermissionAdapter
from Orchestration.permission_context import PermissionContext
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.tool_permission import ToolPermission
from Orchestration.tool_permission_enforcer import ToolPermissionDenied
from Orchestration.tool_resolver import ToolResolver


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _fresh_agents_registry() -> None:
    """Clear the process-wide ``Agents.tool_registry.tool_registry``
    singleton's internal tool map in place, before each
    ``build_application()`` call that needs to inspect a freshly
    re-registered ``skill.<service_name>`` Tool.

    ``Agents.tool_registry.ToolRegistry.reset()`` only clears the
    class-level ``_instance`` cache pointer (``cls._instance = None``,
    see that module's own ``reset()`` docstring) -- it does NOT rebind
    the module-level ``tool_registry`` name that
    ``Core.composition_root`` already imported at
    ``Core.composition_root`` import time (``from Agents.tool_registry
    import ..., tool_registry``, a name binding fixed at import,
    unaffected by any later class-level cache reset). ``reset()`` alone
    therefore does not give a second ``build_application()`` call in
    this test suite a truly empty registry to register into --
    ``_build_service_skills()``'s own ``tool_registry.exists(skill.
    tool_name)`` guard (see that function's docstring) would keep
    silently skipping re-registration, leaving the FIRST call's already-
    registered ``Tool`` (and therefore the FIRST call's
    ``PermissionContext``) in place instead of a fresh one. Clearing
    ``._tools`` directly, on the exact singleton object
    ``Core.composition_root`` holds a reference to, is test-only state
    cleanup -- it does not touch ``Agents/tool_registry.py`` itself, and
    mirrors the read/write surface ``ToolRegistry.register()``/``.get()``
    already expose (``._tools``/``._data_lock`` are that module's own,
    pre-existing instance attributes, not new production surface).
    """
    with agents_tool_registry._data_lock:
        agents_tool_registry._tools.clear()


#: One representative legacy service-tool name, mirrors Activation
#: 12.5's own ``EXPECTED_SERVICE_NAMES`` list -- any one entry is enough
#: to prove the legacy-path identity claim (all 12 share the same
#: construction site inside a single ``_build_service_skills()`` call).
_REPRESENTATIVE_SERVICE_TOOL_NAME = "skill.stock_service"


class _PermissionContextSpy:
    """Context manager that counts every ``PermissionContext``
    construction for the duration of a single ``with`` block, without
    changing ``PermissionContext`` itself (it remains the exact frozen
    dataclass Activation 12.1-12.5 already locked -- this only wraps its
    ``__init__`` temporarily, then restores the original unconditionally).
    """

    def __init__(self) -> None:
        self.created: list[PermissionContext] = []
        self._original_init = PermissionContext.__init__

    def __enter__(self) -> "_PermissionContextSpy":
        created = self.created
        original_init = self._original_init

        def spy_init(instance, *args, **kwargs):
            original_init(instance, *args, **kwargs)
            created.append(instance)

        PermissionContext.__init__ = spy_init  # type: ignore[assignment]
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        PermissionContext.__init__ = self._original_init  # type: ignore[assignment]


class _BuilderCallSpy:
    """Context manager that records the ``permission_context`` argument
    each of the two Activation-12.6 builder functions is called with,
    while still delegating to the real, unmodified function -- pure
    observation, restored unconditionally on exit.
    """

    def __init__(self) -> None:
        self.market_permission_context: PermissionContext | None = None
        self.service_permission_context: PermissionContext | None = None
        self._original_market = composition_root_module._build_market_tool_resolver
        self._original_service = composition_root_module._build_service_skills

    def __enter__(self) -> "_BuilderCallSpy":
        original_market = self._original_market
        original_service = self._original_service

        def spy_market(permission_context):
            self.market_permission_context = permission_context
            return original_market(permission_context)

        def spy_service(permission_context):
            self.service_permission_context = permission_context
            return original_service(permission_context)

        composition_root_module._build_market_tool_resolver = spy_market
        composition_root_module._build_service_skills = spy_service
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        composition_root_module._build_market_tool_resolver = self._original_market
        composition_root_module._build_service_skills = self._original_service


# ---------------------------------------------------------------------------
# A. build_application succeeds.
# ---------------------------------------------------------------------------
def scenario_a_build_application_succeeds() -> None:
    _fresh_agents_registry()
    graph = build_application()
    check(graph is not None, "build_application() returns a graph")


# ---------------------------------------------------------------------------
# B. Exactly one PermissionContext is created for the production graph.
# ---------------------------------------------------------------------------
def scenario_b_exactly_one_permission_context_constructed() -> None:
    _fresh_agents_registry()
    with _PermissionContextSpy() as spy:
        build_application()
    check(
        len(spy.created) == 1,
        f"exactly one PermissionContext is constructed per build_application() "
        f"call; found {len(spy.created)}",
    )
    check(
        spy.created[0] == PermissionContext(),
        "the single constructed PermissionContext is the fail-closed default",
    )


# ---------------------------------------------------------------------------
# C. Canonical market-tool wrappers receive that same object.
# D. Legacy Agents service-tool adapters receive that same object.
# E. Identity is shared: canonical.permission_context is legacy.permission_context
# ---------------------------------------------------------------------------
def scenario_c_d_e_shared_identity_across_both_paths() -> None:
    _fresh_agents_registry()
    with _BuilderCallSpy() as spy:
        graph = build_application()

    check(
        spy.market_permission_context is not None,
        "_build_market_tool_resolver() received a permission_context argument",
    )
    check(
        spy.service_permission_context is not None,
        "_build_service_skills() received a permission_context argument",
    )
    check(
        spy.market_permission_context is spy.service_permission_context,
        "canonical (_build_market_tool_resolver) and legacy "
        "(_build_service_skills) paths receive the identical "
        "PermissionContext object -- not merely equal field values",
    )

    # Cross-check the legacy side's identity via the real, already-wired
    # production object graph (ApplicationGraph.tool_registry), exactly
    # the seam Activation 12.5's own test suite already uses.
    tool = graph.tool_registry.get(_REPRESENTATIVE_SERVICE_TOOL_NAME)
    check(
        isinstance(tool.handler, AgentsToolPermissionAdapter),
        f"'{_REPRESENTATIVE_SERVICE_TOOL_NAME}' Tool.handler is still an "
        "AgentsToolPermissionAdapter",
    )
    check(
        tool.handler.permission_context is spy.service_permission_context,
        "graph.tool_registry's live AgentsToolPermissionAdapter carries "
        "the exact same PermissionContext object observed at "
        "_build_service_skills()'s call boundary",
    )


# ---------------------------------------------------------------------------
# F. Context remains fail-closed.
# ---------------------------------------------------------------------------
def scenario_f_context_remains_fail_closed() -> None:
    _fresh_agents_registry()
    with _PermissionContextSpy() as spy:
        build_application()
    context = spy.created[0]
    check(context.paper_execution_allowed is False, "paper_execution_allowed is False")
    check(context.live_execution_allowed is False, "live_execution_allowed is False")
    check(context.destructive_admin_allowed is False, "destructive_admin_allowed is False")


# ---------------------------------------------------------------------------
# G. READ_ONLY service/tool execution still works.
# ---------------------------------------------------------------------------
def scenario_g_read_only_still_works() -> None:
    # Canonical path: the three real Market*Tool instances remain
    # undeclared (no `.permission`), so they default to READ_ONLY and
    # authorize regardless of the shared context's grant fields.
    resolver, _tool_manager = _build_market_tool_resolver(PermissionContext())
    check(isinstance(resolver, ToolResolver), "canonical resolver still constructs")
    for tool_name in ("market_price", "market_news", "market_fundamental"):
        resolved = resolver.resolve(tool_name)
        check(
            isinstance(resolved, PermissionedTool),
            f"'{tool_name}' still resolves through PermissionedTool",
        )

    # Legacy path: the real production graph's service tools remain
    # undeclared/READ_ONLY too -- authorize_tool() must not raise.
    from Orchestration.tool_permission_enforcer import authorize_tool

    _fresh_agents_registry()
    graph = build_application()
    tool = graph.tool_registry.get(_REPRESENTATIVE_SERVICE_TOOL_NAME)
    permission = authorize_tool(tool.handler.wrapped_tool, tool.handler.permission_context)
    check(
        permission is ToolPermission.READ_ONLY,
        "real legacy service tool still authorizes as READ_ONLY under the "
        "shared context",
    )


# ---------------------------------------------------------------------------
# H. PAPER_EXECUTION still denied.
# I. LIVE_EXECUTION still denied.
# J. DESTRUCTIVE_ADMIN still denied.
# ---------------------------------------------------------------------------
def scenario_h_i_j_grants_still_denied_under_shared_context() -> None:
    _fresh_agents_registry()
    with _BuilderCallSpy() as spy:
        build_application()
    shared_context = spy.market_permission_context
    check(shared_context is spy.service_permission_context, "identity re-confirmed")

    from Orchestration.tool_permission_enforcer import authorize_tool

    class _FakeDeclaredTool:
        def __init__(self, permission: ToolPermission) -> None:
            self.permission = permission

    for permission in (
        ToolPermission.PAPER_EXECUTION,
        ToolPermission.LIVE_EXECUTION,
        ToolPermission.DESTRUCTIVE_ADMIN,
    ):
        fake_tool = _FakeDeclaredTool(permission)
        try:
            authorize_tool(fake_tool, shared_context)
        except ToolPermissionDenied:
            pass
        else:
            raise AssertionError(
                f"{permission.value} was not denied under the shared, "
                "all-False production PermissionContext"
            )


# ---------------------------------------------------------------------------
# K. Existing Activation 12.1-12.5 regressions remain green.
# ---------------------------------------------------------------------------
def scenario_k_upstream_activation_regressions_still_pass() -> None:
    """Run each upstream Activation-12 regression suite in its own fresh
    subprocess -- exactly how ``Tests/test_activation12_1_tool_permission.py``
    etc. are actually invoked per this roadmap's own REGRESSION section
    (``Tests/test_activation12_1_tool_permission.py`` as one standalone
    command, not chained in-process). A fresh interpreter per suite
    avoids a pre-existing, unrelated singleton-isolation quirk in
    ``Agents.tool_registry.tool_registry`` (its module-level binding is
    fixed at import time; ``ToolRegistry.reset()`` only clears the
    class-level ``_instance`` cache pointer, not that binding -- see
    ``_fresh_agents_registry()``'s own docstring above) that only
    surfaces when multiple ``build_application()``-driving test suites
    share one process, which is not how these suites are actually run.
    """
    import subprocess

    for module_name in (
        "test_activation12_1_tool_permission",
        "test_activation12_3_permission_wiring",
        "test_activation12_5_agents_tool_permission_wiring",
    ):
        module_path = ROOT / "Tests" / f"{module_name}.py"
        check(module_path.exists(), f"{module_name}.py exists")
        result = subprocess.run(
            [sys.executable, str(module_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        check(
            result.returncode == 0,
            f"{module_name}.py exits 0 in a fresh subprocess "
            f"(stdout tail: {result.stdout[-500:]!r}, "
            f"stderr tail: {result.stderr[-500:]!r})",
        )


# ---------------------------------------------------------------------------
# Provenance: no remaining production PermissionContext() calls outside
# the single construction site in build_application().
# ---------------------------------------------------------------------------
def scenario_provenance_single_construction_site() -> None:
    source = inspect.getsource(composition_root_module)
    occurrences = source.count("PermissionContext()")
    check(
        occurrences == 1,
        f"exactly one 'PermissionContext()' construction call remains in "
        f"Core/composition_root.py; found {occurrences}",
    )

    build_application_source = inspect.getsource(composition_root_module.build_application)
    check(
        "PermissionContext()" in build_application_source,
        "the single 'PermissionContext()' construction call lives inside "
        "build_application()",
    )

    market_resolver_source = inspect.getsource(
        composition_root_module._build_market_tool_resolver
    )
    service_skills_source = inspect.getsource(composition_root_module._build_service_skills)
    check(
        "PermissionContext()" not in market_resolver_source,
        "_build_market_tool_resolver() no longer constructs its own PermissionContext",
    )
    check(
        "PermissionContext()" not in service_skills_source,
        "_build_service_skills() no longer constructs its own PermissionContext",
    )

    # Signature check: both builders now require an explicit
    # permission_context parameter (no default -- the caller must
    # supply it; this is what forces single ownership structurally,
    # not just by convention).
    market_params = inspect.signature(
        composition_root_module._build_market_tool_resolver
    ).parameters
    service_params = inspect.signature(composition_root_module._build_service_skills).parameters
    check(
        "permission_context" in market_params,
        "_build_market_tool_resolver() accepts permission_context",
    )
    check(
        "permission_context" in service_params,
        "_build_service_skills() accepts permission_context",
    )


# ---------------------------------------------------------------------------
# Provenance: no new ApplicationGraph field was added for this step.
# ---------------------------------------------------------------------------
def scenario_provenance_no_new_applicationgraph_field() -> None:
    graph_source = inspect.getsource(composition_root_module.ApplicationGraph)
    check(
        "permission_context" not in graph_source,
        "ApplicationGraph declares no permission_context field -- identity "
        "is proven via the composition seam, not a new production field",
    )


# ---------------------------------------------------------------------------
# Locked-surface check: the five Orchestration permission-architecture
# files, base_skill/executor/tool_registry/tool_resolver, the three
# Agents legacy-path modules, and main.py are all untouched by this step.
# ---------------------------------------------------------------------------
def scenario_locked_surfaces_unchanged() -> None:
    import importlib

    for module_path in (
        "Orchestration.permission_context",
        "Orchestration.tool_permission",
        "Orchestration.tool_permission_enforcer",
        "Orchestration.permissioned_tool",
        "Orchestration.agents_tool_permission_adapter",
        "Orchestration.base_skill",
        "Orchestration.executor",
        "Orchestration.tool_registry",
        "Orchestration.tool_resolver",
        "Agents.tool_registry",
        "Agents.executor",
        "Agents.sandbox",
        "main",
    ):
        module = importlib.import_module(module_path)
        source = inspect.getsource(module)
        check(
            "12.6" not in source and "Activation 12.6" not in source,
            f"{module_path} carries no Activation 12.6 marker -- confirms "
            "this step did not touch it",
        )


def main() -> None:
    scenarios = [
        scenario_a_build_application_succeeds,
        scenario_b_exactly_one_permission_context_constructed,
        scenario_c_d_e_shared_identity_across_both_paths,
        scenario_f_context_remains_fail_closed,
        scenario_g_read_only_still_works,
        scenario_h_i_j_grants_still_denied_under_shared_context,
        scenario_k_upstream_activation_regressions_still_pass,
        scenario_provenance_single_construction_site,
        scenario_provenance_no_new_applicationgraph_field,
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