"""PortfolioUpdateSkill -- the project's first live-portfolio
snapshot formatter (Phase 11, Sprint 130).

Scope note (LOCKED baseline): this module introduces exactly one
concrete Skill and nothing more.

  1. ``PortfolioUpdateSkill`` -- a ``BaseSkill`` subclass that reads
     ``context.parameters["history"]`` (the exact
     ``TradeHistorySkill``-shaped list of ``{"symbol": ..., "action":
     ..., "capital": ..., "execution_status": ..., "message": ...}``
     mappings, Phase 11 Sprint 129) and converts it, entry by entry
     and in order, into a ``{"portfolio": [...]}`` output. That is
     the entire behavior.

This Skill does NOT write to a database, does NOT persist anything
to disk, does NOT call a Tool, and does NOT call a network of any
kind. It only converts already-produced trade history into a live
portfolio snapshot -- a pure, read-only, in-memory transformation.

No state, no ``__init__`` of its own, no helper methods, no nested
functions, beyond what ``BaseSkill`` already supplies. Every method
beyond the three ``BaseSkill``-required members is deliberately
absent -- there is no ``update``, ``convert``, ``normalize``, or
``append`` anywhere on this class; the single per-entry loop lives
entirely inline inside ``execute()`` itself.

``context.parameters`` is read defensively, exactly the same
never-raise ``isinstance()``/``.get()`` style already used by
``Orchestration.trade_history_skill.TradeHistorySkill``:

  * if ``context.parameters`` is not a ``Mapping`` at all, or its
    ``"history"`` value is missing or not a ``list``, this method
    behaves as though ``"history"`` were an empty list -- never
    raising, and producing ``{"portfolio": []}``.
  * each entry is read via ``entry.get(...)`` only if ``entry`` is a
    ``dict``; any other entry shape (``None``, a ``str``, an ``int``,
    a ``list``, ...) becomes a single safe default entry with
    ``symbol=None``, ``position="NONE"``, ``capital=None``, never
    raising.

Rule table (LOCKED, applied to ``execution_status`` only):

    EXECUTED -> "OPEN"
    CLOSED   -> "CLOSED"
    (anything else, including missing/malformed) -> "NONE"

``symbol`` and ``capital`` are preserved exactly as received --
never normalized, coerced, or otherwise transformed. Input order is
maintained on the output ``"portfolio"`` list.

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
``Orchestration.trade_history_skill.TradeHistorySkill``,
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


class PortfolioUpdateSkill(BaseSkill):
    """Converts a trade history into a live portfolio snapshot.

    This Skill does not write to a database and does not perform any
    persistence of its own -- it only converts an already-produced
    trade history into a portfolio snapshot, in memory. No state, no
    ``__init__`` of its own, no helper methods beyond what
    ``BaseSkill`` already supplies. Every method beyond the three
    ``BaseSkill``-required members is deliberately absent -- there is
    no ``update``, ``convert``, ``normalize``, or ``append`` anywhere
    on this class; the per-entry loop lives entirely inline inside
    ``execute()`` itself. This Skill never connects to a broker,
    never touches a network, and never touches persistence of any
    kind.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"portfolio_update"``.
        """
        return "portfolio_update"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Convert trade history into a live portfolio snapshot."``.
        """
        return "Convert trade history into a live portfolio snapshot."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["history"]`` and
        convert every entry, in order, into a ``{"portfolio": [...]}``
        output.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        never writes to a database, never persists anything to disk,
        and never makes any network call. It consumes a ``list`` of
        already-produced history entries (each an already-produced
        ``TradeHistorySkill``-shaped ``{"symbol": ..., "action": ...,
        "capital": ..., "execution_status": ..., "message": ...}``
        mapping) and converts each one, in order, onto the output
        ``"portfolio"`` list.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"history"`` value is missing or
        not a ``list``, this method behaves as though ``"history"``
        were an empty list -- never raising, and producing
        ``{"portfolio": []}``.

        Each entry is read defensively, using the same never-raise
        ``isinstance()``/``.get()`` style already used throughout
        ``TradeHistorySkill``:

            * ``symbol``/``capital`` are read from ``entry.get(...)``
              if ``entry`` is a ``dict``, else ``None``. Neither is
              ever normalized, reordered, or otherwise transformed --
              each value is copied through unchanged.
            * ``execution_status`` is read from ``entry.get(...)`` if
              ``entry`` is a ``dict``, else ``None``, and mapped to a
              ``"position"`` value via the locked rule table:
              ``"EXECUTED" -> "OPEN"``, ``"CLOSED" -> "CLOSED"``, and
              anything else (including ``None`` or an unrecognized
              string) -> ``"NONE"``.
            * any entry that is not a ``dict`` at all (``None``, a
              ``str``, an ``int``, a ``list``, ...) becomes a single
              safe default entry with ``symbol=None``,
              ``position="NONE"``, ``capital=None`` -- never raising.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"history"`` list, in the shape
                documented above. Read through defensively -- never
                copied, never mutated, and this method never raises
                regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"portfolio": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        history_entries = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_history = parameters.get("history")
            if isinstance(raw_history, list):
                history_entries = raw_history

        portfolio = []
        for entry in history_entries:
            symbol = entry.get("symbol") if isinstance(entry, dict) else None
            capital = entry.get("capital") if isinstance(entry, dict) else None
            execution_status = entry.get("execution_status") if isinstance(entry, dict) else None

            if execution_status == "EXECUTED":
                position = "OPEN"
            elif execution_status == "CLOSED":
                position = "CLOSED"
            else:
                position = "NONE"

            portfolio.append({
                "symbol": symbol,
                "position": position,
                "capital": capital,
            })

        return SkillResult(
            success=True,
            output={"portfolio": portfolio},
            error=None,
            metadata={},
        )