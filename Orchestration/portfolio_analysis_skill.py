"""PortfolioAnalysisSkill -- the project's first portfolio-level
Skill (Phase 11, Sprint 115).

Where ``Orchestration.text_analysis_skill.TextAnalysisSkill`` analyzes
exactly one stock by orchestrating three Tools, this Skill takes
multiple *already-analyzed* stocks (each carrying the
``"recommendation"``/``"confidence"`` pair a prior
``TextAnalysisSkill.execute()`` call already produced) and produces a
single, deterministic ranking -- which analyzed opportunities look
more attractive than others.

This is not AI, not an LLM, not Ollama, not a scoring engine, not an
optimization algorithm, and not portfolio mathematics of any kind:
the entire ranking is one fixed, LOCKED lookup table (recommendation
priority, then confidence priority, then original input order),
applied via Python's own stable ``sorted()`` -- there is no numeric
score, no probability, no weighting, and no formula anywhere in this
file.

Input shape (read from ``context.parameters["stocks"]``, a ``list``):

    {
        "stocks": [
            {
                "symbol": "...",
                "analysis": {
                    "recommendation": "...",
                    "confidence": "...",
                },
            },
            ...
        ]
    }

Only ``"symbol"`` and ``analysis["recommendation"]``/
``analysis["confidence"]`` are ever read. ``"price"``, ``"news"``,
``"fundamental"``, and ``analysis["reason"]``/``["strengths"]``/
``["risks"]``/``["summary"]`` -- everything else a
``TextAnalysisSkill`` result may carry -- is deliberately never
inspected; this Skill knows nothing about them and would behave
identically if they were absent entirely.

Ranking rules (LOCKED), applied in this fixed priority order:

    1. Recommendation priority: ``BUY`` ranks above ``WAIT``, which
       ranks above ``SELL``.
    2. Confidence priority (within the same recommendation group):
       ``HIGH`` ranks above ``MEDIUM``, which ranks above ``LOW``.
    3. Stable ordering: if recommendation and confidence are both
       identical, the original input order (the order the stocks
       appeared in ``context.parameters["stocks"]``) is preserved.
       There is no further, additional tie-breaker of any kind --
       this is achieved purely by relying on Python's ``sorted()``
       being a stable sort, never by adding an explicit index or any
       other extra sort key.

Any unrecognized, missing, or malformed value is normalized before
the table above is applied, using the exact same never-raise
``isinstance()``/``.get()`` style already used throughout
``TextAnalysisSkill``:

    * a ``"recommendation"`` value that is not exactly one of
      ``"BUY"``/``"WAIT"``/``"SELL"`` (including ``None``, a missing
      key, or any other string) is treated as ``"SELL"``.
    * a ``"confidence"`` value that is not exactly one of
      ``"HIGH"``/``"MEDIUM"``/``"LOW"`` is treated as ``"LOW"``.
    * a stock entry with a missing, non-``dict`` ``"analysis"``, or a
      missing/non-``dict`` stock entry itself, is treated as though
      both ``"recommendation"`` and ``"confidence"`` were absent --
      i.e. ``"SELL"``/``"LOW"`` -- and never raises.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=True,
        output={"ranking": [
            {"rank": 1, "symbol": "...", "recommendation": "...",
             "confidence": "..."},
            ...
        ]},
        error=None,
        metadata={},
    )

Each ranking entry carries exactly ``"rank"``, ``"symbol"``,
``"recommendation"``, and ``"confidence"`` -- nothing more (no
``"reason"``, no ``"strengths"``/``"risks"``/``"summary"``, and no
score of any kind). ``"rank"`` is always a 1-based position matching
this entry's index in the final, ordered ``"ranking"`` list. The
``"recommendation"``/``"confidence"`` an entry carries are always the
already-normalized values used to rank it (i.e. ``"SELL"``/``"LOW"``
for anything unrecognized or missing) -- never the original, raw
value a malformed input happened to contain. This keeps every entry
internally consistent with its own position in the ranking: an entry
never shows a value that contradicts the priority it was actually
ranked by, and a genuinely missing analysis (which has no "original"
value to preserve at all) is rendered exactly the same way as an
explicitly unrecognized one.
``success`` is unconditionally ``True`` and ``error`` is
unconditionally ``None`` -- this Skill calls no Tool and has no
failure mode of its own; malformed input is normalized rather than
treated as a failure.

No new abstraction of any kind was introduced to build the ranking:
no ``PortfolioManager``, ``RankingEngine``, ``ScoreCalculator``,
``Optimizer``, ``PortfolioEngine``, ``Strategy``, ``Analyzer``,
``Factory``, ``Registry``, ``Pipeline``, ``Helper``, or utility
module. The normalization loop, the two fixed priority lookup
mappings, and the single ``sorted(...)`` call all live directly
inline inside ``execute()``.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private) beyond the three
``BaseSkill``-required members, and any of ``rank()``, ``score()``,
``optimize()``, ``compare()``, or ``sort_stocks()``. No AI, no LLM
calls (including Ollama), no provider calls, no service calls, no
repository calls, no Tool calls of any kind (this Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` -- it consumes
already-computed analyses, it does not produce them), and no
scoring, probability, or fuzzy logic anywhere in this file.

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In
particular it does NOT import ``Orchestration.text_analysis_skill.
TextAnalysisSkill``, any Tool, ``Orchestration.tool_resolver.
ToolResolver``, ``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.executor.Executor``, ``Agents.planner.Planner``,
``Orchestration.memory``, ``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, ``Orchestration.event_bus.EventBus``,
``requests``, ``google.genai``, ``anthropic``, ``openai``,
``ollama``, ``sqlite3``, ``pandas``, ``numpy``, or ``yfinance``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class PortfolioAnalysisSkill(BaseSkill):
    """The project's first portfolio-level Skill: ranks multiple
    already-analyzed stocks by a fixed, deterministic
    recommendation/confidence priority table.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``rank``, ``score``, ``optimize``, ``compare``, or
    ``sort_stocks`` anywhere on this class; the normalization and
    ranking both live entirely inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"portfolio_analysis"``.
        """
        return "portfolio_analysis"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Rank multiple analyzed stocks by recommendation and confidence."``.
        """
        return "Rank multiple analyzed stocks by recommendation and confidence."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["stocks"]`` and
        produce one deterministic ranking.

        This Skill calls no Tool -- it never calls
        ``self.execute_tool()`` or ``self.execute_tool_result()``. It
        consumes a ``list`` of already-analyzed stocks (each an
        already-produced ``TextAnalysisSkill``-shaped
        ``{"symbol": ..., "analysis": {"recommendation": ...,
        "confidence": ...}}`` mapping) and reorders them.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"stocks"`` value is missing or
        not a ``list``, this method behaves as though ``"stocks"``
        were an empty list -- never raising, and producing
        ``{"ranking": []}``.

        Each stock entry is normalized independently, using the same
        never-raise ``isinstance()``/``.get()`` style already used
        throughout ``TextAnalysisSkill``:

            * ``symbol`` is read from ``stock.get("symbol")`` if
              ``stock`` is a ``dict``, else ``None``.
            * ``recommendation``/``confidence`` are read from
              ``stock["analysis"].get("recommendation")``/
              ``.get("confidence")`` only if both ``stock`` and
              ``stock["analysis"]`` are ``dict`` -- else both are
              treated as missing.
            * a ``recommendation`` that is not exactly one of
              ``"BUY"``/``"WAIT"``/``"SELL"`` is normalized to
              ``"SELL"``; a ``confidence`` that is not exactly one of
              ``"HIGH"``/``"MEDIUM"``/``"LOW"`` is normalized to
              ``"LOW"``. This single normalization step is what
              implements the LOCKED "unknown recommendation ->
              SELL", "unknown confidence -> LOW", and "missing
              analysis -> SELL/LOW" rules simultaneously -- a missing
              analysis simply yields ``None`` for both, which matches
              neither allowed set and so normalizes exactly the same
              way an explicitly unrecognized value would.

        The normalized entries are then ordered with exactly one
        ``sorted(...)`` call, keyed on
        ``(recommendation_priority, confidence_priority)`` from the
        two LOCKED priority tables (``BUY`` < ``WAIT`` < ``SELL``;
        ``HIGH`` < ``MEDIUM`` < ``LOW``) -- relying on ``sorted()``'s
        guaranteed stability for the "preserve original input order"
        rule, with no additional tie-breaker key of any kind.

        Args:
            context: Expected to expose a ``.parameters`` mapping
                containing a ``"stocks"`` list, in the shape
                documented above. Passed through defensively --
                never copied, never mutated, and this method never
                raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``success=True``, ``output={"ranking": [...]}``,
            ``error=None``, and ``metadata={}``.
        """
        stocks = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_stocks = parameters.get("stocks")
            if isinstance(raw_stocks, list):
                stocks = raw_stocks

        normalized = []
        for stock in stocks:
            symbol = None
            recommendation = None
            confidence = None
            if isinstance(stock, dict):
                symbol = stock.get("symbol")
                analysis = stock.get("analysis")
                if isinstance(analysis, dict):
                    recommendation = analysis.get("recommendation")
                    confidence = analysis.get("confidence")

            if recommendation not in ("BUY", "WAIT", "SELL"):
                recommendation = "SELL"
            if confidence not in ("HIGH", "MEDIUM", "LOW"):
                confidence = "LOW"

            normalized.append((symbol, recommendation, confidence))

        recommendation_priority = {"BUY": 0, "WAIT": 1, "SELL": 2}
        confidence_priority = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

        ordered = sorted(
            normalized,
            key=lambda entry: (
                recommendation_priority[entry[1]],
                confidence_priority[entry[2]],
            ),
        )

        ranking = []
        for position, (symbol, recommendation, confidence) in enumerate(ordered, start=1):
            ranking.append({
                "rank": position,
                "symbol": symbol,
                "recommendation": recommendation,
                "confidence": confidence,
            })

        return SkillResult(
            success=True,
            output={"ranking": ranking},
            error=None,
            metadata={},
        )