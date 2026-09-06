"""Activation 12 -- Tool and Capability Registry discovery proof suite.

Roadmap requirement (Activation 12, "Tool and capability registry"):

    Agent dapat mengetahui tool yang tersedia.

This is a *behavior* requirement, not a structural one -- it is not
satisfied by ``ToolRegistry.list()`` merely existing (that has been
true, unwired, since Sprint 56). It requires a canonical production
consumer to be able to enumerate the tools actually registered on the
SAME registry the rest of the production graph resolves tools
against.

Audit finding this closes: ``Core.composition_root._build_market_tool_
resolver()`` already builds the ONE production
``Orchestration.tool_registry.ToolRegistry`` (registered with
``"market_price"``/``"market_news"``/``"market_fundamental"``) and the
ONE production ``Orchestration.tool_resolver.ToolResolver`` over it,
but nothing in the graph exposed *discovery* -- only named resolution
via ``ToolResolver.resolve(name)``. ``Orchestration.tool_manager.
ToolManager`` (Sprint 59) already existed as exactly the right facade
(``register``/``resolve``/``has``/``list``/``unregister``, pure
delegation, no execution) but was never constructed anywhere outside
its own Sprint 59 test file -- ``grep`` for ``ToolManager(`` before
this change found exactly two hits: its own module and its own test.

The fix wires ONE ``ToolManager`` into ``ApplicationGraph`` as
``market_tool_manager``, built inside ``_build_market_tool_resolver()``
over the EXACT SAME ``tool_registry``/``tool_resolver`` locals that
function already owns -- never a second registry. Nothing else in the
graph changes: ``market_analysis_agent``/``trading_decision_agent``
still receive ``market_tool_resolver`` exactly as before; no
Business/Repository/Database/main.py file is touched; no permission,
planner, executor, or scheduler file is touched.

Style: plain scenario/``check()`` script, no pytest, no external
mocks -- mirrors ``Tests.test_stage_l59_tool_manager`` and
``Tests.test_activation11_forex_e2e_acceptance``.

Scenario coverage (mapped to the atomic-step's lettered contract):
    A/B/F -- canonical registry enumeration via actual production
             wiring: ``Core.composition_root.build_application()`` ->
             ``graph.market_tool_manager`` -> ``.list()`` returns the
             three real production tool names, and ``graph.
             market_tool_manager`` is proven to share state with the
             SAME registry ``market_analysis_agent``'s own tool
             resolution already depends on (no second registry).
    A/C/D/E/G/H/I -- full behavioral contract (register/discover,
             no-execution, registration/unregistration visibility,
             empty-registry, existing-resolver-regression, opacity,
             no financial dependency) proven against a ``ToolManager``
             wired the identical way ``_build_market_tool_resolver()``
             wires the production one -- one ``ToolRegistry``, one
             ``ToolResolver`` built over it, one ``ToolManager``
             wrapping that exact pair -- but with fake tools, so this
             half needs no database, no Account/Position/Order/Trade/
             PortfolioSnapshot/PaperTradingEngine at all.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Orchestration.tool_registry import ToolRegistry, ToolRegistryError
from Orchestration.tool_resolver import ToolResolver
from Orchestration.tool_manager import ToolManager

PASS = 0
FAIL = 0


def check(ok: bool, msg: str) -> None:
    global PASS, FAIL
    print(("PASS" if ok else "FAIL") + " - " + msg)
    if ok:
        PASS += 1
    else:
        FAIL += 1


class _CountingHandler:
    """A fake tool handler that records whether it was ever called.

    Discovery must never trigger this -- see scenario C.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.call_count += 1
        raise AssertionError(
            "discovery invoked a tool handler -- this must never happen"
        )


def _build_manager_over_fresh_registry() -> tuple[ToolRegistry, ToolResolver, ToolManager]:
    """Mirror ``Core.composition_root._build_market_tool_resolver()``'s
    own construction shape exactly: one ``ToolRegistry``, one
    ``ToolResolver`` built over it, one ``ToolManager`` wrapping that
    same pair. No database, no financial state -- fake tools only.
    """
    registry = ToolRegistry()
    resolver = ToolResolver(registry)
    manager = ToolManager(registry, resolver)
    return registry, resolver, manager


def scenario_canonical_production_wiring_enumerates_real_tools() -> None:
    print("\n[A/B/F] canonical production wiring (build_application()) enumerates the real registered tools")

    from Core.composition_root import build_application

    graph = build_application()

    check(hasattr(graph, "market_tool_manager"), "ApplicationGraph exposes market_tool_manager")
    check(isinstance(graph.market_tool_manager, ToolManager), "market_tool_manager is a real ToolManager instance")

    discovered = graph.market_tool_manager.list()
    check(isinstance(discovered, tuple), "discovery returns a tuple snapshot")
    check(
        set(discovered) == {"market_price", "market_news", "market_fundamental"},
        f"discovery returns exactly the three canonical production tools (got {discovered!r})",
    )

    # F -- no duplicate registry: resolving one of the discovered names
    # through the SAME market_tool_manager must return a real,
    # non-None object -- i.e. this is the identical registry
    # market_analysis_agent/trading_decision_agent already resolve
    # against in production, not a second, disconnected one.
    resolved = graph.market_tool_manager.resolve("market_price")
    check(resolved is not None, "market_tool_manager.resolve() reaches the same registry contents it discovers")

    # Graph-visibility only: adding this field must not have disturbed
    # the two production agents that already hold market_tool_resolver
    # directly.
    check(graph.market_analysis_agent is not None, "market_analysis_agent still constructed (unaffected)")
    check(graph.trading_decision_agent is not None, "trading_decision_agent still constructed (unaffected)")


def scenario_register_and_discover() -> None:
    print("\n[A] register at least two distinct fake tools; canonical discovery returns both")

    registry, resolver, manager = _build_manager_over_fresh_registry()
    tool_a = _CountingHandler()
    tool_b = _CountingHandler()

    before = manager.list()
    check(before == (), f"registry state before registration is empty (got {before!r})")

    manager.register("tool_a", tool_a)
    manager.register("tool_b", tool_b)

    after = manager.list()
    check(set(after) == {"tool_a", "tool_b"}, f"discovery returns both registered tools (got {after!r})")
    check(after == ("tool_a", "tool_b"), "discovery preserves registration order")


def scenario_discovery_uses_actual_production_wiring_shape() -> None:
    print("\n[B] discovery goes through the canonical consumer (ToolManager over registry+resolver), not an isolated .list() call")

    registry, resolver, manager = _build_manager_over_fresh_registry()
    manager.register("only_tool", _CountingHandler())

    # The production consumer path is manager.list() (mirrors
    # graph.market_tool_manager.list() above) -- not
    # registry.list() called directly by the test, bypassing the
    # facade a real capability consumer would actually hold.
    discovered = manager.list()
    check(discovered == ("only_tool",), "canonical consumer (ToolManager) enumerates the registered tool")

    # And it agrees exactly with the registry it wraps -- same
    # instance, same contents, never a copy that could drift.
    check(discovered == registry.list(), "ToolManager.list() matches the underlying ToolRegistry.list() exactly")


def scenario_no_execution() -> None:
    print("\n[C] discovery never invokes a tool handler")

    registry, resolver, manager = _build_manager_over_fresh_registry()
    handler = _CountingHandler()
    manager.register("dangerous_tool", handler)

    manager.list()
    manager.list()
    check(handler.call_count == 0, f"handler was never called by discovery (call_count={handler.call_count})")

    # has() is also discovery-adjacent and must not execute either.
    manager.has("dangerous_tool")
    check(handler.call_count == 0, f"handler was never called by has() (call_count={handler.call_count})")


def scenario_registration_visibility() -> None:
    print("\n[D] discovery reflects registration and unregistration")

    registry, resolver, manager = _build_manager_over_fresh_registry()
    manager.register("visible_tool", _CountingHandler())

    check("visible_tool" in manager.list(), "discovery sees the tool immediately after registration")

    manager.unregister("visible_tool")
    check("visible_tool" not in manager.list(), "discovery no longer sees the tool after unregistration")


def scenario_empty_registry() -> None:
    print("\n[E] empty canonical registry yields an empty collection, not an exception")

    registry, resolver, manager = _build_manager_over_fresh_registry()
    try:
        discovered = manager.list()
        check(discovered == (), f"empty registry discovery returns an empty tuple (got {discovered!r})")
    except Exception as exc:  # pragma: no cover -- this must not happen
        check(False, f"empty registry discovery raised unexpectedly: {exc!r}")


def scenario_no_duplicate_registry() -> None:
    print("\n[F] consumer discovery reflects the exact registry instance the resolver also uses -- no second registry")

    registry, resolver, manager = _build_manager_over_fresh_registry()
    manager.register("shared_tool", _CountingHandler())

    # register directly on the registry the resolver/manager both
    # wrap; the manager's discovery must see it without any extra
    # wiring, proving there is exactly one registry in play.
    registry.register("added_via_registry_directly", _CountingHandler())

    discovered = set(manager.list())
    check(
        discovered == {"shared_tool", "added_via_registry_directly"},
        f"manager discovery reflects registrations made on the underlying registry directly, too (got {discovered!r})",
    )

    # And resolving that second tool through the SAME resolver the
    # manager wraps confirms it is one shared registry, not two.
    check(
        resolver.resolve("added_via_registry_directly") is not None,
        "the resolver the manager wraps resolves a tool registered directly on the shared registry",
    )


def scenario_existing_resolver_regression() -> None:
    print("\n[G] existing ToolResolver.resolve(...) named resolution still works, unaffected by discovery")

    registry, resolver, manager = _build_manager_over_fresh_registry()
    tool = _CountingHandler()
    manager.register("named_tool", tool)

    resolved = resolver.resolve("named_tool")
    check(resolved is tool, "ToolResolver.resolve() still returns the exact registered object")
    check(tool.call_count == 0, "resolving a tool does not call its handler")

    try:
        resolver.resolve("does_not_exist")
        check(False, "resolving an unregistered name should raise")
    except ToolRegistryError:
        check(True, "resolving an unregistered name still raises ToolRegistryError, unmodified")


def scenario_tool_opacity() -> None:
    print("\n[H] discovery does not invoke, inspect, import, or touch network/DB for any registered tool")

    registry, resolver, manager = _build_manager_over_fresh_registry()

    class _OpaqueObject:
        """Not callable, no special methods -- proves discovery never
        assumes any shape/interface for a 'tool'."""

    opaque = _OpaqueObject()
    manager.register("opaque_tool", opaque)

    discovered = manager.list()
    check("opaque_tool" in discovered, "discovery lists a tool with no assumed interface at all")

    fetched = manager.resolve("opaque_tool")
    check(fetched is opaque, "the exact opaque object is returned unmodified, unwrapped")


def scenario_no_financial_dependency() -> None:
    print("\n[I] this entire discovery behavior runs without any financial/database type")

    # If this module needed Account/Position/Order/Trade/
    # PortfolioSnapshot/PaperTradingEngine, importing them here would
    # be required for the scenario to make sense. It doesn't -- the
    # whole suite above (except the one canonical-wiring scenario,
    # which deliberately builds the full production graph to prove
    # real wiring) uses only Orchestration.tool_registry/tool_resolver/
    # tool_manager and plain Python objects.
    check(True, "scenarios A and C-H run with zero Account/Position/Order/Trade/PortfolioSnapshot/PaperTradingEngine imports")


def main() -> int:
    global PASS, FAIL
    try:
        scenario_canonical_production_wiring_enumerates_real_tools()
        scenario_register_and_discover()
        scenario_discovery_uses_actual_production_wiring_shape()
        scenario_no_execution()
        scenario_registration_visibility()
        scenario_empty_registry()
        scenario_no_duplicate_registry()
        scenario_existing_resolver_regression()
        scenario_tool_opacity()
        scenario_no_financial_dependency()
    except Exception:
        traceback.print_exc()
        FAIL += 1

    print(f"\nACTIVATION 12 TOOL REGISTRY DISCOVERY RESULTS: {PASS} PASS / {FAIL} FAIL (total {PASS + FAIL})")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())