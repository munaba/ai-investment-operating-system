"""PortfolioAlertSkill -- the project's live-portfolio alert
formatter (Phase 10, Sprint 133).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``PortfolioAlertSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["performance"]`` (the exact
     ``PortfolioPerformanceSkill``-shaped list of ``{"symbol": ...,
     "capital": ..., "status": ..., "monitor_status": ...,
     "performance": ...}`` mappings) and converts it, entry by entry
     and in order, into an ``{"alerts": [...]}`` output. That is the
     entire behavior.

This Skill does NOT write to a database, does NOT persist anything
to disk, does NOT call a Tool, and does NOT call a network of any
kind. It only reads an already-produced portfolio-performance
snapshot and derives an alert from it -- a pure, read-only,
in-memory transformation.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``alert``, ``convert``, ``normalize``, or
``notify`` anywhere on this class; the single per-entry loop lives
entirely inline inside ``execute()`` itself.

``context.parameters`` is read defensively, exactly the same
never-raise ``isinstance()``/``.get()`` style already used by
``Orchestration.portfolio_performance_skill.PortfolioPerformanceSkill``:

  * if ``context.parameters`` is not a ``Mapping`` at all, or its
    ``"performance"`` value is missing or not a ``list``, this method
    behaves as though ``"performance"`` were an empty list -- never
    raising, and producing ``{"alerts": []}``.
  * each entry is read via ``entry.get(...)`` only if ``entry`` is a
    ``dict``; any other entry shape (``None``, a ``str``, an ``int``,
    a ``list``, ...) becomes a single safe default entry with
    ``symbol=None``, ``capital=None``, ``status=None``,
    ``monitor_status=None``, ``performance=None``,
    ``alert="UNKNOWN"``, never raising.

Rule table (LOCKED, applied to ``performance`` only):

    TRACKING  -> "WATCH"
    COMPLETED -> "ARCHIVE"
    IDLE      -> "HOLD"
    UNKNOWN   -> "UNKNOWN"
    (anything else, including missing/malformed) -> "UNKNOWN"

``symbol``, ``capital``, ``status``, ``monitor_status``, and
``performance`` are preserved exactly as received -- never
normalized, coerced, or otherwise transformed. Input order is
maintained on the output ``"alerts"`` list. No calculation,
percentage, pnl, market price, profit, or loss of any kind is
computed anywhere in this module -- only ``performance`` decides
``alert``.

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
``Orchestration.portfolio_monitor_skill.PortfolioMonitorSkill``,
``Orchestration.portfolio_update_skill.PortfolioUpdateSkill``,
``Orchestration.portfolio_performance_skill.PortfolioPerformanceSkill``,
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


class PortfolioAlertSkill(BaseSkill):
    """Derives an alert from an already-produced portfolio-performance
    snapshot.

    This Skill does not write to a database and does not perform any
    persistence of its own -- it only reads an already-produced
    portfolio-performance snapshot and derives an alert from it, in
    memory. No state, no ``__init__`` of its own, no helper methods
    beyond what ``BaseSkill`` already supplies. Every method beyond
    the three ``BaseSkill``-required members is deliberately absent --
    there is no ``alert``, ``convert``, ``normalize``, or ``notify``
    anywhere on this class; the per-entry loop lives entirely inline
    inside ``execute()`` itself. This Skill never connects to a
    broker, never touches a network, and never touches persistence of
    any kind. No calculation, percentage, pnl, market price, profit,
    or loss is ever computed here.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"portfolio_alert"``.
        """
        return "portfolio_alert"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Report an alert derived from a portfolio performance snapshot."``.
        """
        return "Report an alert derived from a portfolio performance snapshot."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["performance"]``
        and convert every entry, in order, into an
        ``{"alerts": [...]}`` output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never writes to a database, never persists anything to disk,
        and never makes any network call. It consumes a ``list`` of
        already-produced portfolio-performance entries (each an
        already-produced ``PortfolioPerformanceSkill``-shaped
        ``{"symbol": ..., "capital": ..., "status": ...,
        "monitor_status": ..., "performance": ...}`` mapping) and
        converts each one, in order, onto the output ``"alerts"``
        list.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"performance"`` value is missing
        or not a ``list``, this method behaves as though
        ``"performance"`` were an empty list -- never raising, and
        producing ``{"alerts": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``PortfolioPerformanceSkill``:

            * ``symbol``/``capital``/``status``/``monitor_status``/
              ``performance`` are read from ``entry.get(...)`` if
              ``entry`` is a ``dict``, else ``None``. None of them is
              ever normalized, reordered, or otherwise transformed --
              each value is copied through unchanged.
            * ``performance`` is mapped to an ``"alert"`` value via
              the locked rule table: ``"TRACKING" -> "WATCH"``,
              ``"COMPLETED" -> "ARCHIVE"``, ``"IDLE" -> "HOLD"``,
              ``"UNKNOWN" -> "UNKNOWN"``, and anything else
              (including ``None`` or an unrecognized string) ->
              ``"UNKNOWN"``.
            * any entry that is not a ``dict`` at all (``None``, a
              ``str``, an ``int``, a ``list``, ...) becomes a single
              safe default entry with ``symbol=None``,
              ``capital=None``, ``status=None``,
              ``monitor_status=None``, ``performance=None``,
              ``alert="UNKNOWN"`` -- never raising.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"performance"`` list, in the shape
                documented above. Read through defensively -- never
                copied, never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"alerts": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        performance_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_performance = parameters.get("performance")
            if isinstance(raw_performance, list):
                performance_entries = raw_performance

        alerts = []
        for entry in performance_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            capital = entry.get("capital") if isinstance(entry, dict) else None
            status = entry.get("status") if isinstance(entry, dict) else None
            monitor_status = entry.get("monitor_status") if isinstance(entry, dict) else None
            performance = entry.get("performance") if isinstance(entry, dict) else None

            if performance == "TRACKING":
                alert = "WATCH"
            elif performance == "COMPLETED":
                alert = "ARCHIVE"
            elif performance == "IDLE":
                alert = "HOLD"
            elif performance == "UNKNOWN":
                alert = "UNKNOWN"
            else:
                alert = "UNKNOWN"

            alerts.append({
                "symbol": symbol,
                "capital": capital,
                "status": status,
                "monitor_status": monitor_status,
                "performance": performance,
                "alert": alert,
            })

        return SkillResult(
            success=True,
            output={"alerts": alerts},
            error=None,
            metadata={},
        )