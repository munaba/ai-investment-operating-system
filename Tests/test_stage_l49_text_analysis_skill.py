"""
Phase 5 Sprint 49 proof suite -- ``TextAnalysisSkill``, the project's
first "capability" Skill.

Scope: dedicated regression suite for
``Orchestration.text_analysis_skill.TextAnalysisSkill`` only. This
sprint is interface-level only -- no real text analysis exists to
test, and this suite spends most of its effort proving the *absence*
of any AI/LLM/provider/service/repository/database/network/runtime
knowledge, just as much as it proves the presence of the three
required ``BaseSkill`` members. Mirrors
``Tests/test_stage_l48_file_system_skill.py`` in style and structure.

Invariant coverage:
    T1  -- TextAnalysisSkill is a subclass of BaseSkill.
    T2  -- TextAnalysisSkill satisfies BaseSkill's abstract contract --
           it constructs with zero arguments and does not raise
           TypeError.
    T3  -- TextAnalysisSkill().name == "text_analysis".
    T4  -- TextAnalysisSkill().description ==
           "Analyze textual information." (exact match).
    T5  -- TextAnalysisSkill().execute(context) raises
           NotImplementedError for any context value (None, a string,
           a dict, a list, an arbitrary object).
    T6  -- TextAnalysisSkill defines no __init__ of its own -- it
           inherits object's/BaseSkill's, and two independently
           constructed instances carry no distinguishing state.
    T7  -- a constructed instance has no instance __dict__ entries
           (no per-instance state of any kind).
    T8  -- none of the forbidden convenience methods (parse,
           summarize, classify, analyze, tokenize, extract, sentiment,
           read, load, fetch) exist on the class or an instance.
    T9  -- Orchestration/text_analysis_skill.py's source contains no
           reference to any forbidden import (Providers, Services,
           Repository, Database, Agents, WorkflowRuntime,
           WorkflowEngine, Executor, Planner, Memory, LearningLoop,
           Reflection, EventBus, requests, google.genai, anthropic,
           openai, ollama, sqlite3, pandas, numpy, yfinance).
    T10 -- the module's own namespace does not contain any of those
           forbidden symbols.
    T11 -- calling execute() never performs any AI/LLM/provider call,
           never touches the filesystem, and never touches the
           network -- no file or directory is created as a side
           effect of construction or of a (failing) execute() call.
    T12 -- TextAnalysisSkill carries no runtime/workflow/executor/
           planner/provider/service/repository attribute of any kind.
    T13 -- isinstance/issubclass relationships hold as expected:
           isinstance(skill, BaseSkill) is True; the relationship
           between TextAnalysisSkill and BaseSkill is not symmetric.
    T14 -- TextAnalysisSkill defines no public attribute/method beyond
           the three BaseSkill-required members (name, description,
           execute).
    T15 -- TextAnalysisSkill and FileSystemSkill (the project's other
           concrete Skill) are fully independent -- distinct classes,
           distinct instances, no cross-contamination.

Follows the same scenario-based, no-pytest, no-external-mocks style as
the other Stage L4x proof suites: a global pass/fail counter, plain
fixtures, and a ``main()`` runner.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Orchestration.base_skill import BaseSkill
from Orchestration.text_analysis_skill import TextAnalysisSkill

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
# T1 -- inherits BaseSkill
# ---------------------------------------------------------------------------
def scenario_inherits_base_skill() -> None:
    check(
        issubclass(TextAnalysisSkill, BaseSkill),
        "T1: TextAnalysisSkill subclasses BaseSkill",
    )


# ---------------------------------------------------------------------------
# T2 -- abstract contract satisfied
# ---------------------------------------------------------------------------
def scenario_abstract_contract_satisfied() -> None:
    try:
        skill = TextAnalysisSkill()
        constructed = True
    except TypeError:
        constructed = False
        skill = None  # type: ignore[assignment]

    check(
        constructed,
        "T2: TextAnalysisSkill() constructs without TypeError -- the "
        "abstract contract (name, description, execute) is fully "
        "satisfied",
    )
    check(
        isinstance(skill, BaseSkill),
        "T2: the constructed instance is a BaseSkill",
    )


# ---------------------------------------------------------------------------
# T3 -- name == "text_analysis"
# ---------------------------------------------------------------------------
def scenario_name_is_text_analysis() -> None:
    skill = TextAnalysisSkill()
    check(
        skill.name == "text_analysis",
        f"T3: TextAnalysisSkill().name == 'text_analysis'; got "
        f"{skill.name!r}",
    )


# ---------------------------------------------------------------------------
# T4 -- description exact match
# ---------------------------------------------------------------------------
def scenario_description_exact_match() -> None:
    skill = TextAnalysisSkill()
    check(
        skill.description == "Analyze textual information.",
        f"T4: TextAnalysisSkill().description == 'Analyze textual "
        f"information.'; got {skill.description!r}",
    )


# ---------------------------------------------------------------------------
# T5 -- execute() raises NotImplementedError for any context
# ---------------------------------------------------------------------------
def scenario_execute_raises_not_implemented() -> None:
    skill = TextAnalysisSkill()

    for context, label in (
        (None, "None"),
        ("some raw text to analyze", "a string"),
        ({"text": "x"}, "a dict"),
        (["a", "b"], "a list"),
        (object(), "an arbitrary object"),
    ):
        raised = False
        try:
            skill.execute(context)
        except NotImplementedError:
            raised = True
        except Exception:  # noqa: BLE001
            raised = False

        check(
            raised,
            f"T5: execute({label}) raises NotImplementedError",
        )


# ---------------------------------------------------------------------------
# T6 -- no __init__ of its own
# ---------------------------------------------------------------------------
def scenario_no_init_of_its_own() -> None:
    check(
        "__init__" not in TextAnalysisSkill.__dict__,
        "T6: TextAnalysisSkill does not define its own __init__",
    )

    a = TextAnalysisSkill()
    b = TextAnalysisSkill()
    check(
        a is not b,
        "T6: two independently constructed instances are distinct "
        "objects",
    )
    check(
        a.name == b.name and a.description == b.description,
        "T6: both instances report identical name/description -- no "
        "per-instance divergence",
    )


# ---------------------------------------------------------------------------
# T7 -- no instance state
# ---------------------------------------------------------------------------
def scenario_no_instance_state() -> None:
    skill = TextAnalysisSkill()
    check(
        not hasattr(skill, "__dict__") or skill.__dict__ == {},
        "T7: a constructed TextAnalysisSkill instance carries no "
        "per-instance __dict__ state",
    )


# ---------------------------------------------------------------------------
# T8 -- forbidden convenience methods absent
# ---------------------------------------------------------------------------
def scenario_forbidden_methods_absent() -> None:
    skill = TextAnalysisSkill()
    forbidden_methods = (
        "parse",
        "summarize",
        "classify",
        "analyze",
        "tokenize",
        "extract",
        "sentiment",
        "read",
        "load",
        "fetch",
    )
    for method in forbidden_methods:
        check(
            not hasattr(TextAnalysisSkill, method) and not hasattr(skill, method),
            f"T8: neither the class nor an instance defines a "
            f"'{method}' method",
        )


# ---------------------------------------------------------------------------
# T9 / T10 -- forbidden imports / forbidden symbols in module namespace
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import Orchestration.text_analysis_skill as tas_module

    source = Path(tas_module.__file__).read_text(encoding="utf-8")

    forbidden_modules = [
        "import Providers",
        "from Providers",
        "import Services",
        "from Services",
        "import Repository",
        "from Repository",
        "import Database",
        "from Database",
        "import Agents",
        "from Agents",
        "import requests",
        "import google.genai",
        "from google",
        "import anthropic",
        "import openai",
        "import ollama",
        "import sqlite3",
        "import pandas",
        "import numpy",
        "import yfinance",
    ]
    for forbidden in forbidden_modules:
        check(
            forbidden not in source,
            f"T9: Orchestration/text_analysis_skill.py contains no "
            f"'{forbidden}' statement",
        )

    forbidden_symbols = [
        "WorkflowRuntime",
        "WorkflowEngine",
        "Executor",
        "Planner",
        "Memory",
        "LearningLoop",
        "Reflection",
        "EventBus",
    ]
    for symbol in forbidden_symbols:
        check(
            f"import {symbol}" not in source and f"{symbol}(" not in source,
            f"T9: Orchestration/text_analysis_skill.py contains no "
            f"reference to '{symbol}'",
        )
        check(
            not hasattr(tas_module, symbol),
            f"T10: Orchestration.text_analysis_skill's module "
            f"namespace does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# T11 -- no AI / filesystem / network side effects
# ---------------------------------------------------------------------------
def scenario_no_side_effects() -> None:
    before = set(os.listdir("."))

    skill = TextAnalysisSkill()
    try:
        skill.execute("anything")
    except NotImplementedError:
        pass

    after = set(os.listdir("."))
    check(
        before == after,
        "T11: constructing TextAnalysisSkill and calling its "
        "(failing) execute() creates no file or directory as a side "
        "effect",
    )


# ---------------------------------------------------------------------------
# T12 -- no runtime/workflow/executor/planner/provider/service/repository
# knowledge
# ---------------------------------------------------------------------------
def scenario_no_runtime_provider_service_repository_knowledge() -> None:
    skill = TextAnalysisSkill()
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
        "planner",
        "provider",
        "service",
        "repository",
        "memory",
        "reflection",
        "learning_loop",
    ):
        check(
            not hasattr(TextAnalysisSkill, attr) and not hasattr(skill, attr),
            f"T12: neither TextAnalysisSkill nor an instance carries "
            f"a '{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# T13 -- isinstance / issubclass relationships
# ---------------------------------------------------------------------------
def scenario_isinstance_issubclass_relationships() -> None:
    skill = TextAnalysisSkill()
    check(
        isinstance(skill, BaseSkill),
        "T13: isinstance(TextAnalysisSkill(), BaseSkill) is True",
    )
    check(
        issubclass(TextAnalysisSkill, BaseSkill),
        "T13: issubclass(TextAnalysisSkill, BaseSkill) is True",
    )
    check(
        not issubclass(BaseSkill, TextAnalysisSkill),
        "T13: BaseSkill is not a subclass of TextAnalysisSkill -- the "
        "relationship is not symmetric",
    )


# ---------------------------------------------------------------------------
# T14 -- no public surface beyond the three required members
# ---------------------------------------------------------------------------
def scenario_no_extra_public_surface() -> None:
    allowed = {"name", "description", "execute"}
    public_class_members = {
        member
        for member in vars(TextAnalysisSkill)
        if not member.startswith("_")
    }
    check(
        public_class_members == allowed,
        f"T14: TextAnalysisSkill's own public class namespace is "
        f"exactly {allowed}; got {public_class_members!r}",
    )


# ---------------------------------------------------------------------------
# T15 -- independence from FileSystemSkill (the project's other Skill)
# ---------------------------------------------------------------------------
def scenario_independent_from_file_system_skill() -> None:
    from Orchestration.file_system_skill import FileSystemSkill

    text_skill = TextAnalysisSkill()
    fs_skill = FileSystemSkill()

    check(
        not isinstance(text_skill, FileSystemSkill)
        and not isinstance(fs_skill, TextAnalysisSkill),
        "T15: TextAnalysisSkill and FileSystemSkill instances are not "
        "instances of one another",
    )
    check(
        text_skill.name != fs_skill.name,
        "T15: TextAnalysisSkill and FileSystemSkill report distinct "
        "names",
    )
    check(
        text_skill.description != fs_skill.description,
        "T15: TextAnalysisSkill and FileSystemSkill report distinct "
        "descriptions",
    )

    raised_text, raised_fs = False, False
    try:
        text_skill.execute("x")
    except NotImplementedError:
        raised_text = True
    try:
        fs_skill.execute("x")
    except NotImplementedError:
        raised_fs = True
    check(
        raised_text and raised_fs,
        "T15: both skills independently raise NotImplementedError "
        "from execute() -- no cross-contamination",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_inherits_base_skill,
        scenario_abstract_contract_satisfied,
        scenario_name_is_text_analysis,
        scenario_description_exact_match,
        scenario_execute_raises_not_implemented,
        scenario_no_init_of_its_own,
        scenario_no_instance_state,
        scenario_forbidden_methods_absent,
        scenario_no_forbidden_imports,
        scenario_no_side_effects,
        scenario_no_runtime_provider_service_repository_knowledge,
        scenario_isinstance_issubclass_relationships,
        scenario_no_extra_public_surface,
        scenario_independent_from_file_system_skill,
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
    print(f"PHASE 5 SPRINT 49 TEXT ANALYSIS SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())