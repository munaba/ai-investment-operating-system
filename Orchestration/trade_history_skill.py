"""TradeHistorySkill -- the project's first execution-history
formatter (Phase 11, Sprint 129).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``TradeHistorySkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["executions"]`` (the exact
     ``PaperTradingSkill``-shaped list of ``{"symbol": ..., "action":
     ..., "capital": ..., "execution_status": ..., "message": ...}``
     mappings, Phase 11 Sprint 128) and copies every entry, unchanged
     and in order, into a ``{"history": [...]}`` output. That is the
     entire behavior.

This Skill does NOT write to a database, does NOT persist anything
to disk, does NOT call a Tool, and does NOT call a network of any
kind. It only formats already-produced execution history -- a pure,
read-only reshaping of one list into another.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``record``, ``format``, ``normalize``, or
``append`` anywhere on this class; the single per-entry loop lives
entirely inline inside ``execute()`` itself.

``context.parameters`` is read defensively, exactly the same
never-raise ``isinstance()``/``.get()`` style already used by
``Orchestration.paper_trading_skill.PaperTradingSkill``:

  * if ``context.parameters`` is not a ``Mapping`` at all, or its
    ``"executions"`` value is missing or not a ``list``, this method
    behaves as though ``"executions"`` were an empty list -- never
    raising, and producing ``{"history": []}``.
  * each entry is read via ``entry.get(...)`` only if ``entry`` is a
    ``dict``; any other entry shape (``None``, a ``str``, an ``int``,
    a ``list``, ...) becomes a single safe default entry with every
    field ``None``, never raising.

Dependencies (LOCKED): this module imports only
``collections.abc.Mapping``, ``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib ``typing`` --
nothing else. In particular it does NOT import ``Providers``,
``Services``, ``Repository``, ``Database``, ``Agents``,
``Orchestration.executor.Executor``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_context.ToolContext``,
``Orchestration.base_tool.BaseTool``,
``Orchestration.paper_trading_skill.PaperTradingSkill``, ``requests``,
``sqlite3``, ``pandas``, ``numpy``, ``yfinance``, ``websocket``,
``asyncio``, or ``threading``. This Skill never calls
``self.execute_tool()`` or ``self.execute_tool_result()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class TradeHistorySkill(BaseSkill):
    """Records every paper-trade execution into a normalized history
    structure.

    This Skill does not write to a database and does not perform any
    persistence of its own -- it only formats execution history. No
    state, no ``__init__`` of its own, no helper methods beyond what
    ``BaseSkill`` already supplies. Every method beyond the three
    ``BaseSkill``-required members is deliberately absent -- there is
    no ``record``, ``format``, ``normalize``, or ``append`` anywhere
    on this class; the per-entry loop lives entirely inline inside
    ``execute()`` itself. This Skill never connects to a broker,
    never touches a network, and never touches persistence of any
    kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"trade_history"``.
        """
        return "trade_history"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Record every paper-trade execution into a normalized history structure."``.
        """
        return "Record every paper-trade execution into a normalized history structure."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read
        ``context.parameters["executions"]`` and copy every entry,
        unchanged and in order, into a ``{"history": [...]}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never writes to a database, never persists anything to disk,
        and never makes any network call. It consumes a ``list`` of
        already-produced execution entries (each an already-produced
        ``PaperTradingSkill``-shaped ``{"symbol": ..., "action": ...,
        "capital": ..., "execution_status": ..., "message": ...}``
        mapping) and copies each one, exactly and in order, onto the
        output ``"history"`` list.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"executions"`` value is missing
        or not a ``list``, this method behaves as though
        ``"executions"`` were an empty list -- never raising, and
        producing ``{"history": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``PaperTradingSkill``:

            * ``symbol``/``action``/``capital``/``execution_status``/
              ``message`` are read from ``entry.get(...)`` if
              ``entry`` is a ``dict``, else ``None``. None of these
              are ever normalized, reordered, or otherwise
              transformed -- each value is copied through unchanged.
            * any entry that is not a ``dict`` at all (``None``, a
              ``str``, an ``int``, a ``list``, ...) becomes a single
              safe default entry with every one of the five fields
              ``None`` -- never raising.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing an ``"executions"`` list, in the shape
                documented above. Read through defensively -- never
                copied, never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"history": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        execution_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_executions = parameters.get("executions")
            if isinstance(raw_executions, list):
                execution_entries = raw_executions

        history = []
        for entry in execution_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            action = entry.get("action") if isinstance(entry, dict) else None
            capital = entry.get("capital") if isinstance(entry, dict) else None
            execution_status = entry.get("execution_status") if isinstance(entry, dict) else None
            message = entry.get("message") if isinstance(entry, dict) else None

            history.append({
                "symbol": symbol,
                "action": action,
                "capital": capital,
                "execution_status": execution_status,
                "message": message,
            })

        return SkillResult(
            success=True,
            output={"history": history},
            error=None,
            metadata={},
        )