"""FileSystemSkill -- the project's first concrete Skill (Phase 5,
Sprint 48).

Scope note (LOCKED baseline): this module introduces exactly one
concrete class and nothing more.

  1. ``FileSystemSkill(BaseSkill)`` -- implements the three abstract
     members ``BaseSkill`` requires (``name``, ``description``,
     ``execute(context)``) and nothing else.

This sprint is interface-level only. ``FileSystemSkill`` performs NO
real file operations of any kind -- no reading, writing, copying,
moving, deleting, listing, checking existence, creating directories,
renaming, touching, globbing, searching, or watching files. Its
``execute()`` simply raises ``NotImplementedError``. The actual
implementation of file I/O belongs to a later sprint.

Explicitly NOT part of this milestone: an ``__init__`` of its own, any
attribute, any cache, any configuration, any dependency injection, any
path/root-directory/sandbox notion, any helper method beyond the three
required members, and any of the file-operation methods listed above.

Dependencies (LOCKED): this module imports only
``Orchestration.base_skill.BaseSkill``, ``Orchestration.skill_result.
SkillResult``, and stdlib ``typing`` -- nothing else. In particular it
does NOT import ``os``, ``pathlib``, ``glob``, ``shutil``,
``tempfile``, ``zipfile``, ``json``, ``yaml``, ``sqlite3``,
``requests``, ``subprocess``, ``Orchestration.skill_registry.
SkillRegistry``, ``Orchestration.skill_resolver.SkillResolver``,
``Orchestration.executor.Executor``, or any Runtime/Workflow/Planner/
Memory/Reflection/LearningLoop/EventBus/CompositionRoot module.

Phase 9, Sprint 103 update (Second Real Skill Implementation):
``execute()`` no longer raises. It now returns a real, deterministic
``SkillResult``:

    SkillResult(
        success=True,
        output=None,
        error=None,
        metadata={},
    )

unconditionally, on every call, regardless of ``context``. This
mirrors ``Orchestration.market_price_tool.MarketPriceTool``'s Sprint
99 change and ``Orchestration.text_analysis_skill.TextAnalysisSkill``'s
Sprint 102 change: still no filesystem access of any kind -- no
``open()``, no ``Path()``, no ``os.*``, no ``shutil.*``, no
``tempfile.*`` -- and no network, database, Service, Repository,
Provider, AI, Runtime, Workflow, or Tool involvement. ``context`` is
accepted only to satisfy the ``BaseSkill`` contract -- it is never
read, inspected, or mutated, so the value returned is identical on
every call regardless of what ``context`` is. The one new import
(``Orchestration.skill_result.SkillResult``) exists solely to
construct this literal return value.
"""

from __future__ import annotations

from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class FileSystemSkill(BaseSkill):
    """The first concrete Skill: an interface-only stand-in for file
    read/write capability.

    No state, no ``__init__`` of its own, no helper methods. Every
    method beyond the three ``BaseSkill`` requires is deliberately
    absent -- there is no ``read``, ``write``, ``copy``, ``move``,
    ``delete``, ``list``, ``exists``, ``mkdir``, ``rename``,
    ``touch``, ``glob``, ``search``, or ``watch`` anywhere on this
    class.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"filesystem"``.
        """
        return "filesystem"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string ``"Read and write files."``.
        """
        return "Read and write files."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill.

        Phase 9, Sprint 103 (Second Real Skill Implementation): this
        is the second concrete, non-raising behavior across the
        project's Skills. It performs no filesystem access of any
        kind -- no ``open()``, no ``Path()``, no ``os.*``, no
        ``shutil.*``, no ``tempfile.*`` -- and no network, database,
        Service, Repository, Provider, AI, Runtime, Workflow, or Tool
        involvement. It always returns the same literal,
        deterministic ``SkillResult``:

            SkillResult(
                success=True,
                output=None,
                error=None,
                metadata={},
            )

        ``context`` is accepted only to satisfy the ``BaseSkill``
        contract -- it is never read, inspected, or mutated, so the
        value returned is identical on every call regardless of what
        ``context`` is.

        Args:
            context: Unused in this sprint. Accepted only to satisfy
                the ``BaseSkill`` contract; never read or mutated.

        Returns:
            The literal ``SkillResult`` described above,
            unconditionally, on every call.
        """
        return SkillResult(
            success=True,
            output=None,
            error=None,
            metadata={},
        )