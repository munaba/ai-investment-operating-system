"""PortfolioMonitorSkill -- the project's live-portfolio monitoring
status formatter (Phase 10, Sprint 131).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``PortfolioMonitorSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["portfolio"]`` (the exact
     ``PortfolioUpdateSkill``-shaped list of ``{"symbol": ...,
     "capital": ..., "status": ...}`` mappings) and converts it,
     entry by entry and in order, into a ``{"monitor": [...]}``
     output. That is the entire behavior.

This Skill does NOT write to a database, does NOT persist anything
to disk, does NOT call a Tool, and does NOT call a network of any
kind. It only reads an already-produced portfolio snapshot and
derives a monitoring status from it -- a pure, read-only, in-memory
transformation.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``monitor``, ``convert``, ``normalize``, or
``update`` anywhere on this class; the single per-entry loop lives
entirely inline inside ``execute()`` itself.

``context.parameters`` is read defensively, exactly the same
never-raise ``isinstance()``/``.get()`` style already used by
``Orchestration.portfolio_update_skill.PortfolioUpdateSkill``:

  * if ``context.parameters`` is not a ``Mapping`` at all, or its
    ``"portfolio"`` value is missing or not a ``list``, this method
    behaves as though ``"portfolio"`` were an empty list -- never
    raising, and producing ``{"monitor": []}``.
  * each entry is read via ``entry.get(...)`` only if ``entry`` is a
    ``dict``; any other entry shape (``None``, a ``str``, an ``int``,
    a ``list``, ...) becomes a single safe default entry with
    ``symbol=None``, ``capital=None``, ``status=None``,
    ``monitor_status="UNKNOWN"``, never raising.

Rule table (LOCKED, applied to ``status`` only):

    OPEN   -> "ACTIVE"
    CLOSED -> "FINISHED"
    NONE   -> "INACTIVE"
    (anything else, including missing/malformed) -> "UNKNOWN"

``symbol``, ``capital``, and ``status`` are preserved exactly as
received -- never normalized, coerced, or otherwise transformed.
Input order is maintained on the output ``"monitor"`` list.

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
``Orchestration.portfolio_update_skill.PortfolioUpdateSkill``,
``Orchestration.portfolio_engine``, ``requests``, ``sqlite3``,
``pandas``, ``numpy``, ``yfinance``, ``websocket``, ``asyncio``, or
``threading``. This Skill never calls ``self.execute_tool()`` or
``self.execute_tool_result()``. This Skill does not reuse, extend, or
depend on the legacy ``Orchestration.portfolio_engine`` architecture
in any way -- it belongs entirely to the modern Skill pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class PortfolioMonitorSkill(BaseSkill):
    """Derives a monitoring status from an already-produced portfolio
    snapshot.

    This Skill does not write to a database and does not perform any
    persistence of its own -- it only reads an already-produced
    portfolio snapshot and derives a monitoring status from it, in
    memory. No state, no ``__init__`` of its own, no helper methods
    beyond what ``BaseSkill`` already supplies. Every method beyond
    the three ``BaseSkill``-required members is deliberately absent --
    there is no ``monitor``, ``convert``, ``normalize``, or ``update``
    anywhere on this class; the per-entry loop lives entirely inline
    inside ``execute()`` itself. This Skill never connects to a
    broker, never touches a network, and never touches persistence of
    any kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"portfolio_monitor"``.
        """
        return "portfolio_monitor"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Monitor a live portfolio snapshot and report its status."``.
        """
        return "Monitor a live portfolio snapshot and report its status."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["portfolio"]`` and
        convert every entry, in order, into a ``{"monitor": [...]}``
        output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never writes to a database, never persists anything to disk,
        and never makes any network call. It consumes a ``list`` of
        already-produced portfolio entries (each an already-produced
        ``PortfolioUpdateSkill``-shaped ``{"symbol": ..., "capital":
        ..., "status": ...}`` mapping) and converts each one, in
        order, onto the output ``"monitor"`` list.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"portfolio"`` value is missing or
        not a ``list``, this method behaves as though ``"portfolio"``
        were an empty list -- never raising, and producing
        ``{"monitor": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``PortfolioUpdateSkill``:

            * ``symbol``/``capital``/``status`` are read from
              ``entry.get(...)`` if ``entry`` is a ``dict``, else
              ``None``. None of them is ever normalized, reordered, or
              otherwise transformed -- each value is copied through
              unchanged.
            * ``status`` is mapped to a ``"monitor_status"`` value via
              the locked rule table: ``"OPEN" -> "ACTIVE"``,
              ``"CLOSED" -> "FINISHED"``, ``"NONE" -> "INACTIVE"``, and
              anything else (including ``None`` or an unrecognized
              string) -> ``"UNKNOWN"``.
            * any entry that is not a ``dict`` at all (``None``, a
              ``str``, an ``int``, a ``list``, ...) becomes a single
              safe default entry with ``symbol=None``,
              ``capital=None``, ``status=None``,
              ``monitor_status="UNKNOWN"`` -- never raising.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"portfolio"`` list, in the shape
                documented above. Read through defensively -- never
                copied, never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"monitor": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        portfolio_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_portfolio = parameters.get("portfolio")
            if isinstance(raw_portfolio, list):
                portfolio_entries = raw_portfolio

        monitor = []
        for entry in portfolio_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            capital = entry.get("capital") if isinstance(entry, dict) else None
            status = entry.get("status") if isinstance(entry, dict) else None

            if status == "OPEN":
                monitor_status = "ACTIVE"
            elif status == "CLOSED":
                monitor_status = "FINISHED"
            elif status == "NONE":
                monitor_status = "INACTIVE"
            else:
                monitor_status = "UNKNOWN"

            monitor.append({
                "symbol": symbol,
                "capital": capital,
                "status": status,
                "monitor_status": monitor_status,
            })

        return SkillResult(
            success=True,
            output={"monitor": monitor},
            error=None,
            metadata={},
        )