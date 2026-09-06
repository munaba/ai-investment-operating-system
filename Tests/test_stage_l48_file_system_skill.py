"""
Phase 5 Sprint 48 proof suite -- ``FileSystemSkill``, the project's
first concrete Skill.

Scope: dedicated regression suite for
``Orchestration.file_system_skill.FileSystemSkill`` only. This sprint
is interface-level only -- no real file operation exists to test, and
this suite spends most of its effort proving the *absence* of any such
operation (and of any runtime/workflow/executor/registry knowledge)
just as much as it proves the presence of the three required
``BaseSkill`` members.

Invariant coverage:
    F1  -- FileSystemSkill is a subclass of BaseSkill.
    F2  -- FileSystemSkill satisfies BaseSkill's abstract contract --
           it constructs with zero arguments and does not raise
           TypeError.
    F3  -- FileSystemSkill().name == "filesystem".
    F4  -- FileSystemSkill().description == "Read and write files."
           (exact match).
    F5  -- FileSystemSkill().execute(context) raises
           NotImplementedError for any context value (None, a string,
           a dict, an arbitrary object).
    F6  -- FileSystemSkill defines no __init__ of its own -- it
           inherits object's/BaseSkill's, and two independently
           constructed instances carry no distinguishing state.
    F7  -- a constructed instance has no instance __dict__ entries
           (no per-instance state of any kind).
    F8  -- none of the forbidden convenience methods (read, write,
           copy, move, delete, list, exists, mkdir, rename, touch,
           glob, search, watch) exist on the class or an instance.
    F9  -- Orchestration/file_system_skill.py's source contains no
           reference to any forbidden import (os, pathlib, glob,
           shutil, tempfile, zipfile, json, yaml, sqlite3, requests,
           subprocess, SkillRegistry, SkillResolver, Executor,
           WorkflowRuntime, WorkflowEngine, Planner, Memory,
           Reflection, LearningLoop, EventBus, CompositionRoot).
    F10 -- the module's own namespace does not contain any of those
           forbidden symbols.
    F11 -- calling execute() never touches the filesystem -- no file
           or directory is created as a side effect of construction
           or of a (failing) execute() call.
    F12 -- FileSystemSkill carries no runtime/workflow/executor/
           registry attribute of any kind (e.g. .runtime, .workflow,
           .executor, .registry, .resolver).
    F13 -- isinstance/issubclass relationships hold as expected:
           isinstance(skill, BaseSkill) is True; the relationship
           between FileSystemSkill and BaseSkill is not symmetric.
    F14 -- FileSystemSkill defines no public attribute/method beyond
           the three BaseSkill-required members (name, description,
           execute).

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
from Orchestration.file_system_skill import FileSystemSkill

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
# F1 -- inherits BaseSkill
# ---------------------------------------------------------------------------
def scenario_inherits_base_skill() -> None:
    check(
        issubclass(FileSystemSkill, BaseSkill),
        "F1: FileSystemSkill subclasses BaseSkill",
    )


# ---------------------------------------------------------------------------
# F2 -- abstract contract satisfied
# ---------------------------------------------------------------------------
def scenario_abstract_contract_satisfied() -> None:
    try:
        skill = FileSystemSkill()
        constructed = True
    except TypeError:
        constructed = False
        skill = None  # type: ignore[assignment]

    check(
        constructed,
        "F2: FileSystemSkill() constructs without TypeError -- the "
        "abstract contract (name, description, execute) is fully "
        "satisfied",
    )
    check(
        isinstance(skill, BaseSkill),
        "F2: the constructed instance is a BaseSkill",
    )


# ---------------------------------------------------------------------------
# F3 -- name == "filesystem"
# ---------------------------------------------------------------------------
def scenario_name_is_filesystem() -> None:
    skill = FileSystemSkill()
    check(
        skill.name == "filesystem",
        f"F3: FileSystemSkill().name == 'filesystem'; got {skill.name!r}",
    )


# ---------------------------------------------------------------------------
# F4 -- description exact match
# ---------------------------------------------------------------------------
def scenario_description_exact_match() -> None:
    skill = FileSystemSkill()
    check(
        skill.description == "Read and write files.",
        f"F4: FileSystemSkill().description == 'Read and write "
        f"files.'; got {skill.description!r}",
    )


# ---------------------------------------------------------------------------
# F5 -- execute() raises NotImplementedError for any context
# ---------------------------------------------------------------------------
def scenario_execute_raises_not_implemented() -> None:
    skill = FileSystemSkill()

    for context, label in (
        (None, "None"),
        ("some/path.txt", "a string"),
        ({"path": "x"}, "a dict"),
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
            f"F5: execute({label}) raises NotImplementedError",
        )


# ---------------------------------------------------------------------------
# F6 -- no __init__ of its own
# ---------------------------------------------------------------------------
def scenario_no_init_of_its_own() -> None:
    check(
        "__init__" not in FileSystemSkill.__dict__,
        "F6: FileSystemSkill does not define its own __init__",
    )

    a = FileSystemSkill()
    b = FileSystemSkill()
    check(
        a is not b,
        "F6: two independently constructed instances are distinct "
        "objects",
    )
    check(
        a.name == b.name and a.description == b.description,
        "F6: both instances report identical name/description -- no "
        "per-instance divergence",
    )


# ---------------------------------------------------------------------------
# F7 -- no instance state
# ---------------------------------------------------------------------------
def scenario_no_instance_state() -> None:
    skill = FileSystemSkill()
    check(
        not hasattr(skill, "__dict__") or skill.__dict__ == {},
        "F7: a constructed FileSystemSkill instance carries no "
        "per-instance __dict__ state",
    )


# ---------------------------------------------------------------------------
# F8 -- forbidden convenience methods absent
# ---------------------------------------------------------------------------
def scenario_forbidden_methods_absent() -> None:
    skill = FileSystemSkill()
    forbidden_methods = (
        "read",
        "write",
        "copy",
        "move",
        "delete",
        "list",
        "exists",
        "mkdir",
        "rename",
        "touch",
        "glob",
        "search",
        "watch",
    )
    for method in forbidden_methods:
        check(
            not hasattr(FileSystemSkill, method) and not hasattr(skill, method),
            f"F8: neither the class nor an instance defines a "
            f"'{method}' method",
        )


# ---------------------------------------------------------------------------
# F9 / F10 -- forbidden imports / forbidden symbols in module namespace
# ---------------------------------------------------------------------------
def scenario_no_forbidden_imports() -> None:
    import Orchestration.file_system_skill as fss_module

    source = Path(fss_module.__file__).read_text(encoding="utf-8")

    forbidden_modules = [
        "import os",
        "import pathlib",
        "import glob",
        "import shutil",
        "import tempfile",
        "import zipfile",
        "import json",
        "import yaml",
        "import sqlite3",
        "import requests",
        "import subprocess",
    ]
    for forbidden in forbidden_modules:
        check(
            forbidden not in source,
            f"F9: Orchestration/file_system_skill.py contains no "
            f"'{forbidden}' statement",
        )

    forbidden_symbols = [
        "SkillRegistry",
        "SkillResolver",
        "Executor",
        "WorkflowRuntime",
        "WorkflowEngine",
        "Planner",
        "Memory",
        "Reflection",
        "LearningLoop",
        "EventBus",
        "CompositionRoot",
    ]
    for symbol in forbidden_symbols:
        check(
            f"import {symbol}" not in source and f"{symbol}(" not in source,
            f"F9: Orchestration/file_system_skill.py contains no "
            f"reference to '{symbol}'",
        )
        check(
            not hasattr(fss_module, symbol),
            f"F10: Orchestration.file_system_skill's module namespace "
            f"does not contain a '{symbol}' symbol",
        )


# ---------------------------------------------------------------------------
# F11 -- no filesystem side effects
# ---------------------------------------------------------------------------
def scenario_no_filesystem_side_effects() -> None:
    before = set(os.listdir("."))

    skill = FileSystemSkill()
    try:
        skill.execute("anything")
    except NotImplementedError:
        pass

    after = set(os.listdir("."))
    check(
        before == after,
        "F11: constructing FileSystemSkill and calling its (failing) "
        "execute() creates no file or directory as a side effect",
    )


# ---------------------------------------------------------------------------
# F12 -- no runtime/workflow/executor/registry knowledge
# ---------------------------------------------------------------------------
def scenario_no_runtime_workflow_executor_registry_knowledge() -> None:
    skill = FileSystemSkill()
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
    ):
        check(
            not hasattr(FileSystemSkill, attr) and not hasattr(skill, attr),
            f"F12: neither FileSystemSkill nor an instance carries a "
            f"'{attr}' attribute",
        )


# ---------------------------------------------------------------------------
# F13 -- isinstance / issubclass relationships
# ---------------------------------------------------------------------------
def scenario_isinstance_issubclass_relationships() -> None:
    skill = FileSystemSkill()
    check(
        isinstance(skill, BaseSkill),
        "F13: isinstance(FileSystemSkill(), BaseSkill) is True",
    )
    check(
        issubclass(FileSystemSkill, BaseSkill),
        "F13: issubclass(FileSystemSkill, BaseSkill) is True",
    )
    check(
        not issubclass(BaseSkill, FileSystemSkill),
        "F13: BaseSkill is not a subclass of FileSystemSkill -- the "
        "relationship is not symmetric",
    )


# ---------------------------------------------------------------------------
# F14 -- no public surface beyond the three required members
# ---------------------------------------------------------------------------
def scenario_no_extra_public_surface() -> None:
    allowed = {"name", "description", "execute"}
    public_class_members = {
        member
        for member in vars(FileSystemSkill)
        if not member.startswith("_")
    }
    check(
        public_class_members == allowed,
        f"F14: FileSystemSkill's own public class namespace is exactly "
        f"{allowed}; got {public_class_members!r}",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    scenarios = [
        scenario_inherits_base_skill,
        scenario_abstract_contract_satisfied,
        scenario_name_is_filesystem,
        scenario_description_exact_match,
        scenario_execute_raises_not_implemented,
        scenario_no_init_of_its_own,
        scenario_no_instance_state,
        scenario_forbidden_methods_absent,
        scenario_no_forbidden_imports,
        scenario_no_filesystem_side_effects,
        scenario_no_runtime_workflow_executor_registry_knowledge,
        scenario_isinstance_issubclass_relationships,
        scenario_no_extra_public_surface,
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
    print(f"PHASE 5 SPRINT 48 FILE SYSTEM SKILL RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())