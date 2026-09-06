"""PortfolioReportSkill -- the project's live-portfolio report
formatter (Phase 10, Sprint 134).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``PortfolioReportSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["alerts"]`` (the exact
     ``PortfolioAlertSkill``-shaped list of ``{"symbol": ...,
     "capital": ..., "status": ..., "monitor_status": ...,
     "performance": ..., "alert": ...}`` mappings) and converts it,
     entry by entry and in order, into a ``{"report": [...]}``
     output. That is the entire behavior.

This Skill does NOT write to a database, does NOT persist anything
to disk, does NOT call a Tool, and does NOT call a network of any
kind. It only reads an already-produced portfolio-alert snapshot and
derives a report status from it -- a pure, read-only, in-memory
transformation.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``report``, ``convert``, ``normalize``, or
``summarize`` anywhere on this class; the single per-entry loop lives
entirely inline inside ``execute()`` itself.

``context.parameters`` is read defensively, exactly the same
never-raise ``isinstance()``/``.get()`` style already used by
``Orchestration.portfolio_alert_skill.PortfolioAlertSkill``:

  * if ``context.parameters`` is not a ``Mapping`` at all, or its
    ``"alerts"`` value is missing or not a ``list``, this method
    behaves as though ``"alerts"`` were an empty list -- never
    raising, and producing ``{"report": []}``.
  * each entry is read via ``entry.get(...)`` only if ``entry`` is a
    ``dict``; any other entry shape (``None``, a ``str``, an ``int``,
    a ``list``, ...) becomes a single safe default entry with
    ``symbol=None``, ``capital=None``, ``status=None``,
    ``monitor_status=None``, ``performance=None``, ``alert=None``,
    ``report_status="UNKNOWN"``, never raising.

Rule table (LOCKED, applied to ``alert`` only):

    WATCH   -> "READY"
    ARCHIVE -> "STORED"
    HOLD    -> "WAIT"
    UNKNOWN -> "UNKNOWN"
    (anything else, including missing/malformed) -> "UNKNOWN"

``symbol``, ``capital``, ``status``, ``monitor_status``,
``performance``, and ``alert`` are preserved exactly as received --
never normalized, coerced, or otherwise transformed. Input order is
maintained on the output ``"report"`` list. No calculation,
percentage, pnl, market price, profit, or loss of any kind is
computed anywhere in this module -- only ``alert`` decides
``report_status``.

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
``Orchestration.portfolio_alert_skill.PortfolioAlertSkill``,
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


class PortfolioReportSkill(BaseSkill):
    """Derives a report status from an already-produced portfolio-alert
    snapshot.

    This Skill does not write to a database and does not perform any
    persistence of its own -- it only reads an already-produced
    portfolio-alert snapshot and derives a report status from it, in
    memory. No state, no ``__init__`` of its own, no helper methods
    beyond what ``BaseSkill`` already supplies. Every method beyond
    the three ``BaseSkill``-required members is deliberately absent --
    there is no ``report``, ``convert``, ``normalize``, or
    ``summarize`` anywhere on this class; the per-entry loop lives
    entirely inline inside ``execute()`` itself. This Skill never
    connects to a broker, never touches a network, and never touches
    persistence of any kind. No calculation, percentage, pnl, market
    price, profit, or loss is ever computed here.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"portfolio_report"``.
        """
        return "portfolio_report"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Report a report status derived from a portfolio alert snapshot."``.
        """
        return "Report a report status derived from a portfolio alert snapshot."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["alerts"]`` and
        convert every entry, in order, into a ``{"report": [...]}``
        output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never writes to a database, never persists anything to disk,
        and never makes any network call. It consumes a ``list`` of
        already-produced portfolio-alert entries (each an
        already-produced ``PortfolioAlertSkill``-shaped ``{"symbol":
        ..., "capital": ..., "status": ..., "monitor_status": ...,
        "performance": ..., "alert": ...}`` mapping) and converts
        each one, in order, onto the output ``"report"`` list.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"alerts"`` value is missing or
        not a ``list``, this method behaves as though ``"alerts"``
        were an empty list -- never raising, and producing
        ``{"report": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``PortfolioAlertSkill``:

            * ``symbol``/``capital``/``status``/``monitor_status``/
              ``performance``/``alert`` are read from
              ``entry.get(...)`` if ``entry`` is a ``dict``, else
              ``None``. None of them is ever normalized, reordered,
              or otherwise transformed -- each value is copied
              through unchanged.
            * ``alert`` is mapped to a ``"report_status"`` value via
              the locked rule table: ``"WATCH" -> "READY"``,
              ``"ARCHIVE" -> "STORED"``, ``"HOLD" -> "WAIT"``,
              ``"UNKNOWN" -> "UNKNOWN"``, and anything else
              (including ``None`` or an unrecognized string) ->
              ``"UNKNOWN"``.
            * any entry that is not a ``dict`` at all (``None``, a
              ``str``, an ``int``, a ``list``, ...) becomes a single
              safe default entry with ``symbol=None``,
              ``capital=None``, ``status=None``,
              ``monitor_status=None``, ``performance=None``,
              ``alert=None``, ``report_status="UNKNOWN"`` -- never
              raising.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing an ``"alerts"`` list, in the shape
                documented above. Read through defensively -- never
                copied, never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"report": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        alert_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_alerts = parameters.get("alerts")
            if isinstance(raw_alerts, list):
                alert_entries = raw_alerts

        report = []
        for entry in alert_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            capital = entry.get("capital") if isinstance(entry, dict) else None
            status = entry.get("status") if isinstance(entry, dict) else None
            monitor_status = entry.get("monitor_status") if isinstance(entry, dict) else None
            performance = entry.get("performance") if isinstance(entry, dict) else None
            alert = entry.get("alert") if isinstance(entry, dict) else None

            if alert == "WATCH":
                report_status = "READY"
            elif alert == "ARCHIVE":
                report_status = "STORED"
            elif alert == "HOLD":
                report_status = "WAIT"
            elif alert == "UNKNOWN":
                report_status = "UNKNOWN"
            else:
                report_status = "UNKNOWN"

            report.append({
                "symbol": symbol,
                "capital": capital,
                "status": status,
                "monitor_status": monitor_status,
                "performance": performance,
                "alert": alert,
                "report_status": report_status,
            })

        return SkillResult(
            success=True,
            output={"report": report},
            error=None,
            metadata={},
        )