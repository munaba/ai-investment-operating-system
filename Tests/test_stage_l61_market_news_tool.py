"""
Phase 5 Sprint 61 proof suite -- ``MarketNewsTool``, the project's
second concrete Tool.

Scope: dedicated regression suite for
``Orchestration.market_news_tool.MarketNewsTool`` only. This sprint
is interface-level only -- no real news-retrieval operation exists to
test, and this suite spends most of its effort proving the *absence*
of any such operation (network/API/scraping/Service/Repository/
Provider/Database access, and any runtime/workflow/executor/registry
knowledge) just as much as it proves the presence of the three
required ``BaseTool`` members.

Invariant coverage:
    M1  -- MarketNewsTool is a subclass of BaseTool.
    M2  -- MarketNewsTool satisfies BaseTool's abstract contract --
           it constructs with zero arguments and does not raise
           TypeError.
    M3  -- MarketNewsTool().name == "market_news".
    M4  -- MarketNewsTool().description ==
           "Retrieve market news." (exact match).
    M5  -- MarketNewsTool().execute(context) raises
           NotImplementedError for any context value (None, a string,
           a dict, an arbitrary object).
    M6  -- MarketNewsTool defines no __init__ of its own -- it
           inherits object's/BaseTool's, and two independently
           constructed instances carry no distinguishing state.
    M7  -- a constructed instance has no instance __dict__ entries
           (no per-instance state of any kind).
    M8  -- none of the forbidden domain methods (fetch, download,
           query, search, rss, scrape, crawl, headline, articles,
           news, provider, request, refresh, stream, connect,
           disconnect, parse, summarize, classify) exist on the class
           or an instance.
    M9  -- Orchestration/market_news_tool.py's source contains no
           reference to any forbidden import (requests, httpx,
           aiohttp, feedparser, beautifulsoup4, selenium, playwright,
           newspaper, lxml, pandas, numpy, sqlite3, Repository,
           Services, Providers, Database, Planner, Executor, Workflow,
           Runtime, EventBus, Memory, LearningLoop, Reflection,
           CompositionRoot, ToolRegistry, ToolResolver, ToolManager)
           -- verified both by substring scan and AST-level import
           inspection.
    M10 -- the module's own namespace does not contain any of those
           forbidden symbols.
    M11 -- calling execute() never touches the filesystem and never
           opens a network connection -- no file, directory, or
           socket is created as a side effect of construction or of a
           (failing) execute() call.
    M12 -- MarketNewsTool carries no runtime/workflow/executor/
           registry/skill/capability attribute of any kind (e.g.
           .runtime, .workflow, .executor, .registry, .resolver,
           .skill, .capability, .cache, .client, .session).
    M13 -- isinstance/issubclass relationships hold as expected:
           isinstance(tool, BaseTool) is True; the relationship
           between MarketNewsTool and BaseTool is not symmetric.
    M14 -- MarketNewsTool defines no public attribute/method beyond
           the three BaseTool-required members (name, description,
           execute).
    M15 -- no class variables of any kind (MarketNewsTool's own
           __dict__ contains no non-callable, non-descriptor class
           attribute besides the three required members' descriptors
           and dunder/documentation machinery).
    M16 -- multiple instances independent: two MarketNewsTool
           instances are distinct objects that never share mutable
           state (there is none to share).
    M17 -- side-effect free: constructing MarketNewsTool and reading
           name/description repeatedly is idempotent and produces no
           observable side effects.
    M18 -- AST import verification: Orchestration/market_news_tool.py
           imports only Orchestration.base_tool and typing (plus
           __future__) -- nothing else, at the AST level.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x/L5x proof suites (mirroring
``Tests.test_stage_l48_file_system_skill`` in particular): a global
pass/fail counter, plain fixtures, and a ``main()`` runner.
"""

from __future__ import annotations

import ast
import os
import socket
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_tool import BaseTool
from Orchestration.market_news_tool import MarketNewsTool

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
# M1 -- inherits BaseTool
# ---------------------------------------------------------------------------
def scenario_inherits_base_tool() -> None:
    check(
        issubclass(MarketNewsTool, BaseTool),
        "M1: MarketNewsTool subclasses BaseTool",
    )


# ---------------------------------------------------------------------------
# M2 -- abstract contract satisfied
# ---------------------------------------------------------------------------
def scenario_abstract_contract_satisfied() -> None:
    try:
        tool = MarketNewsTool()
        constructed = True
    except TypeError:
        constructed = False
        tool = None  # type: ignore[assignment]

    check(
        constructed,
        "M2: MarketNewsTool() constructs without TypeError -- the "
        "abstract contract (name, description, execute) is fully "
        "satisfied",
    )
    check(
        isinstance(tool, BaseTool),
        "M2: the constructed instance is a BaseTool",
    )


# ---------------------------------------------------------------------------
# M3 -- name == "market_news"
# ---------------------------------------------------------------------------
def scenario_name_is_market_news() -> None:
    tool = MarketNewsTool()
    check(
        tool.name == "market_news",
        f"M3: MarketNewsTool().name == 'market_news'; got {tool.name!r}",
    )


# ---------------------------------------------------------------------------
# M4 -- description exact match
# ---------------------------------------------------------------------------
def scenario_description_exact_match() -> None:
    tool = MarketNewsTool()
    check(
        tool.description == "Retrieve market news.",
        f"M4: MarketNewsTool().description == 'Retrieve market "
        f"news.'; got {tool.description!r}",
    )


# ---------------------------------------------------------------------------
# M5 -- execute() raises NotImplementedError for any context
# ---------------------------------------------------------------------------
def scenario_execute_raises_not_implemented() -> None:
    tool = MarketNewsTool()

    for context, label in (
        (None, "None"),
        ("AAPL", "a string"),
        ({"symbol": "AAPL"}, "a dict"),
        (object(), "an arbitrary object"),
    ):
        raised = False
        try:
            tool.execute(context)
        except NotImplementedError:
            raised = True
        except Exception:  # noqa: BLE001
            raised = False

        check(
            raised,
            f"M5: execute({label}) raises NotImplementedError",
        )


# ---------------------------------------------------------------------------
# M6 -- no __init__ of its own
# ---------------------------------------------------------------------------
def scenario_no_init_of_its_own() -> None:
    check(
        "__init__" not in MarketNewsTool.__dict__,
        "M6: MarketNewsTool does not define its own __init__",
    )

    a = MarketNewsTool()
    b = MarketNewsTool()
    check(
        a is not b,
        "M6: two independently constructed instances are distinct objects",
    )
    check(
        a.name == b.name and a.description == b.description,
        "M6: both instances report identical name/description -- no "
        "per-instance divergence",
    )


# ---------------------------------------------------------------------------
# M7 -- no instance state
# ---------------------------------------------------------------------------
def scenario_no_instance_state() -> None:
    tool = MarketNewsTool()
    check(
        not hasattr(tool, "__dict__") or tool.__dict__ == {},
        "M7: a constructed MarketNewsTool instance carries no "
        "per-instance __dict__ state",
    )


# ---------------------------------------------------------------------------
# M8 -- forbidden domain methods absent
# ---------------------------------------------------------------------------
def scenario_forbidden_methods_absent() -> None:
    tool = MarketNewsTool()
    forbidden_methods = (
        "fetch",
        "download",
        "query",
        "search",
        "rss",
        "scrape",
        "crawl",
        "headline",
        "articles",
        "news",
        "provider",
        "request",
        "refresh",
        "stream",
        "connect",
        "disconnect",
        "parse",
        "summarize",
        "classify",
    )
    for method in forbidden_methods:
        check(
            not hasattr(MarketNewsTool, method) and not hasattr(tool, method),
            f"M8: neither the class nor an instance defines a '{method}' method",
        )


# ---------------------------------------------------------------------------
# M9 / M10 -- forbidden imports / forbidden symbols in module namespace
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import Orchestration.market_news_tool as mnt_module

    source = Path(mnt_module.__file__).read_text(encoding="utf-8")

    forbidden_import_modules = [
        "requests",
        "httpx",
        "aiohttp",
        "feedparser",
        "beautifulsoup4",
        "selenium",
        "playwright",
        "newspaper",
        "lxml",
        "pandas",
        "numpy",
        "sqlite3",
    ]
    for forbidden in forbidden_import_modules:
        check(
            f"import {forbidden}" not in source,
            f"M9: Orchestration/market_news_tool.py contains no "
            f"'import {forbidden}' statement",
        )

    forbidden_symbols = [
        "Repository",
        "Services",
        "Providers",
        "Database",
        "Planner",
        "Executor",
        "Workflow",
        "Runtime",
        "EventBus",
        "Memory",
        "LearningLoop",
        "Reflection",
        "CompositionRoot",
        "ToolRegistry",
        "ToolResolver",
        "ToolManager",
    ]
    for symbol in forbidden_symbols:
        check(
            f"import {symbol}" not in source and f"{symbol}(" not in source,
            f"M9: Orchestration/market_news_tool.py contains no "
            f"reference to '{symbol}'",
        )
        check(
            not hasattr(mnt_module, symbol),
            f"M10: Orchestration.market_news_tool's module namespace "
            f"does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# M11 -- no filesystem or network side effects
# ---------------------------------------------------------------------------
def scenario_no_filesystem_or_network_side_effects() -> None:
    before = set(os.listdir("."))

    original_socket = socket.socket
    socket_called = False

    def _blocked_socket(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        nonlocal socket_called
        socket_called = True
        raise AssertionError("MarketNewsTool attempted to open a network socket")

    socket.socket = _blocked_socket  # type: ignore[assignment]
    try:
        tool = MarketNewsTool()
        try:
            tool.execute("anything")
        except NotImplementedError:
            pass
    finally:
        socket.socket = original_socket  # type: ignore[assignment]

    after = set(os.listdir("."))
    check(
        before == after,
        "M11: constructing MarketNewsTool and calling its (failing) "
        "execute() creates no file or directory as a side effect",
    )
    check(
        not socket_called,
        "M11: constructing MarketNewsTool and calling its (failing) "
        "execute() never attempts to open a network socket",
    )


# ---------------------------------------------------------------------------
# M12 -- no runtime/workflow/executor/registry/skill knowledge
# ---------------------------------------------------------------------------
def scenario_no_runtime_workflow_executor_registry_knowledge() -> None:
    tool = MarketNewsTool()
    for attr in (
        "runtime",
        "workflow",
        "workflow_engine",
        "scheduler",
        "event_bus",
        "events",
        "host",
        "executor",
        "registry",
        "resolver",
        "agent",
        "skill",
        "capability",
        "cache",
        "client",
        "session",
        "api_key",
        "config",
    ):
        check(
            not hasattr(MarketNewsTool, attr) and not hasattr(tool, attr),
            f"M12: neither MarketNewsTool nor an instance carries a "
            f"'{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# M13 -- isinstance / issubclass relationships
# ---------------------------------------------------------------------------
def scenario_isinstance_issubclass_relationships() -> None:
    tool = MarketNewsTool()
    check(
        isinstance(tool, BaseTool),
        "M13: isinstance(MarketNewsTool(), BaseTool) is True",
    )
    check(
        issubclass(MarketNewsTool, BaseTool),
        "M13: issubclass(MarketNewsTool, BaseTool) is True",
    )
    check(
        not issubclass(BaseTool, MarketNewsTool),
        "M13: BaseTool is not a subclass of MarketNewsTool -- the "
        "relationship is not symmetric",
    )


# ---------------------------------------------------------------------------
# M14 -- no public surface beyond the three required members
# ---------------------------------------------------------------------------
def scenario_no_extra_public_surface() -> None:
    allowed = {"name", "description", "execute"}
    public_class_members = {
        member for member in vars(MarketNewsTool) if not member.startswith("_")
    }
    check(
        public_class_members == allowed,
        f"M14: MarketNewsTool's own public class namespace is exactly "
        f"{allowed}; got {public_class_members!r}",
    )


# ---------------------------------------------------------------------------
# M15 -- no class variables
# ---------------------------------------------------------------------------
def scenario_no_class_variables() -> None:
    allowed_names = {"name", "description", "execute"}
    for key, value in vars(MarketNewsTool).items():
        if key.startswith("_"):
            # Skip dunder attributes and ABCMeta-injected bookkeeping
            # (e.g. '_abc_impl') -- these are machinery from `abc.ABC`
            # itself, not a class variable MarketNewsTool defines.
            continue
        check(
            key in allowed_names,
            f"M15: MarketNewsTool's class namespace has no extra "
            f"class variable beyond the three required members; found {key!r}",
        )
        check(
            isinstance(value, (property, type(MarketNewsTool.execute))) or callable(value),
            f"M15: class attribute {key!r} is a method/property descriptor, "
            f"not a plain data class variable",
        )


# ---------------------------------------------------------------------------
# M16 -- multiple instances independent
# ---------------------------------------------------------------------------
def scenario_multiple_instances_independent() -> None:
    a = MarketNewsTool()
    b = MarketNewsTool()
    check(a is not b, "M16: two MarketNewsTool instances are distinct objects")
    check(
        a.name == b.name and a.description == b.description,
        "M16: two independent instances report identical name/description",
    )
    # There is no mutable state to diverge, but confirm neither instance's
    # __dict__ is shared with the other (each is its own empty mapping).
    check(
        (not hasattr(a, "__dict__") or a.__dict__ == {})
        and (not hasattr(b, "__dict__") or b.__dict__ == {}),
        "M16: neither instance carries any per-instance state to share",
    )


# ---------------------------------------------------------------------------
# M17 -- side-effect free / idempotent
# ---------------------------------------------------------------------------
def scenario_side_effect_free() -> None:
    tool = MarketNewsTool()
    first_name = tool.name
    first_description = tool.description
    for _ in range(5):
        check(
            tool.name == first_name,
            "M17: repeated .name access returns the same value every time",
        )
        check(
            tool.description == first_description,
            "M17: repeated .description access returns the same value every time",
        )


# ---------------------------------------------------------------------------
# M18 -- AST import verification
# ---------------------------------------------------------------------------
def scenario_ast_import_verification() -> None:
    source_path = ROOT / "Orchestration" / "market_news_tool.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.append(node.module)

    allowed = {
        "typing",
        "__future__",
        "Orchestration.base_tool",
    }

    unexpected = [mod for mod in imported_modules if mod not in allowed]
    check(
        not unexpected,
        f"M18: Orchestration.market_news_tool imports only allowed "
        f"modules; unexpected={unexpected!r}",
    )
    check(
        "Orchestration.base_tool" in imported_modules,
        "M18: Orchestration.market_news_tool imports Orchestration.base_tool",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_inherits_base_tool,
        scenario_abstract_contract_satisfied,
        scenario_name_is_market_news,
        scenario_description_exact_match,
        scenario_execute_raises_not_implemented,
        scenario_no_init_of_its_own,
        scenario_no_instance_state,
        scenario_forbidden_methods_absent,
        scenario_no_forbidden_imports,
        scenario_no_filesystem_or_network_side_effects,
        scenario_no_runtime_workflow_executor_registry_knowledge,
        scenario_isinstance_issubclass_relationships,
        scenario_no_extra_public_surface,
        scenario_no_class_variables,
        scenario_multiple_instances_independent,
        scenario_side_effect_free,
        scenario_ast_import_verification,
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
    print(f"PHASE 5 SPRINT 61 MARKET NEWS TOOL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())