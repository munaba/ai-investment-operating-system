"""MarketAnalysisSkill -- the project's first multi-stock orchestrator
Skill (Phase 11, Sprint 117).

Activation 7 (Crypto Validation Profile) update: for each symbol,
this Skill now picks between two parallel per-symbol Skills instead
of always running ``TextAnalysisSkill`` --
``Orchestration.text_analysis_skill.TextAnalysisSkill`` for every
stock symbol (byte-for-byte the same call as before this Activation),
or ``Orchestration.crypto_analysis_skill.CryptoAnalysisSkill`` for a
symbol recognized by ``Core.market_config.is_crypto_symbol()``
(currently ``BTC-USD``/``ETH-USD`` only). This is the ONE routing
decision added anywhere in this file -- everything else (the
per-symbol loop shape, the ``SkillContext`` construction, the
``_resolve_tool`` forwarding, the failure handling, the output shape)
is unchanged. See ``CryptoAnalysisSkill``'s own module docstring for
why crypto needs a separate decision table rather than a modification
of ``TextAnalysisSkill``'s.

Where ``Orchestration.text_analysis_skill.TextAnalysisSkill`` analyzes
exactly one stock, and ``Orchestration.portfolio_analysis_skill.
PortfolioAnalysisSkill``/``Orchestration.watchlist_analysis_skill.
WatchlistAnalysisSkill`` only reorder *already-analyzed* stocks, no
existing Skill accepted many stocks at once and actually ran the
analysis for each of them. This Skill closes that gap: it reads a
list of symbols from ``context.parameters["symbols"]`` and, for each
symbol, runs the exact same, already-frozen
``Orchestration.text_analysis_skill.TextAnalysisSkill.execute()`` --
never a copy of its logic.

Input shape (read from ``context.parameters["symbols"]``, a ``list``):

    {"symbols": ["BBCA", "BBRI", "BMRI", "ASII"]}

Execution rules (LOCKED):

    For each symbol, a new ``Orchestration.skill_context.
    SkillContext`` is constructed that changes only ``parameters`` to
    ``{"symbol": symbol}`` -- ``task``, ``metadata``, and
    ``tool_context_factory`` are carried through from the incoming
    ``context``, unchanged. A fresh ``TextAnalysisSkill`` instance is
    then run against that per-symbol context via
    ``TextAnalysisSkill.execute(...)`` -- the same public method every
    other caller uses, never inlined or reimplemented here. Because
    ``TextAnalysisSkill.execute()`` calls ``self.execute_tool_result()``
    internally (which requires ``self._resolve_tool`` to have been
    injected by an ``Executor``), this Skill forwards its own
    ``self._resolve_tool`` -- if an ``Executor`` injected one onto
    *this* Skill instance -- onto each per-symbol ``TextAnalysisSkill``
    instance before calling it. That is the only thing forwarded; no
    other attribute is copied, and no Tool is ever resolved or called
    directly by this module.

Per-symbol output shape -- taken directly from the ``TextAnalysisSkill``
result, forwarded by identity, never transformed:

    {"symbol": symbol, "analysis": result.output["analysis"]}

``"analysis"`` is never inspected, reshaped, filtered, or otherwise
modified -- it is exactly the same object
``TextAnalysisSkill.execute()`` placed under its own ``"analysis"``
key.

Failure handling (LOCKED): if running one symbol fails -- whether
``TextAnalysisSkill.execute()`` returns a ``SkillResult`` with
``success=False``, or raises an exception outright -- this Skill
still continues with the remaining symbols. Every symbol requested
always appears exactly once in the final ``"stocks"`` list, in the
original input order. A symbol whose ``TextAnalysisSkill`` call
raised an exception (so no ``SkillResult``/``"analysis"`` was ever
produced at all) is recorded with ``"analysis": None`` -- there is
nothing else this Skill could forward by identity for that symbol,
since no output was ever returned. A symbol whose ``TextAnalysisSkill``
call returned a ``SkillResult`` with ``success=False`` (e.g. one or
more of its own three Tool calls failed) still forwards whatever
``"analysis"`` that ``SkillResult`` produced, exactly as for a
successful symbol -- ``TextAnalysisSkill.execute()`` always computes
an ``"analysis"`` dict regardless of its own ``combined_success``
value, so there is a real value to forward by identity in that case.

The overall ``SkillResult.success`` this Skill returns is ``True``
only if every symbol succeeded; it becomes ``False`` as soon as at
least one symbol failed (again, whether by a ``success=False`` result
or a raised exception). ``error`` is ``None`` when every symbol
succeeded, otherwise a single ``str`` joining one message per failed
symbol.

Output shape -- always exactly one ``SkillResult``:

    SkillResult(
        success=...,
        output={"stocks": [
            {"symbol": "BBCA", "analysis": {...}},
            ...
        ]},
        error=...,
        metadata={},
    )

No other top-level output key exists, and no other key exists on
each stock entry beyond ``"symbol"``/``"analysis"``.

No new abstraction of any kind was introduced to build this
orchestration: no ``MarketAnalysisManager``, ``MarketAnalysisEngine``,
``MarketAnalysisCoordinator``, ``MarketAnalysisWorkflow``,
``MarketAnalysisPipeline``, ``Strategy``, ``Helper``, ``Factory``,
``Analyzer``, ``Registry``, ``Service``, ``Adapter``, or utility
module. The per-symbol loop, the ``SkillContext`` construction, the
``TextAnalysisSkill()`` instantiation, and the result-combination
logic all live directly inline inside ``execute()``.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection beyond the single ``_resolve_tool`` forward described
above, any helper method (public or private) beyond the three
``BaseSkill``-required members, and any of ``analyze_many()``,
``run_all()``, ``batch()``, or ``fan_out()``. This Skill never calls
``self.execute_tool()``/``self.execute_tool_result()`` itself, and
never copies any logic out of ``TextAnalysisSkill`` -- it only ever
calls ``TextAnalysisSkill.execute()``, exactly as it already exists.

Dependencies (LOCKED): this module imports
``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_context.SkillContext``,
``Orchestration.skill_result.SkillResult``,
``Orchestration.text_analysis_skill.TextAnalysisSkill``, and stdlib
``collections.abc.Mapping``/``typing`` -- nothing else. In particular
it does NOT import ``Orchestration.portfolio_analysis_skill.
PortfolioAnalysisSkill``, ``Orchestration.watchlist_analysis_skill.
WatchlistAnalysisSkill``, any Tool, ``Orchestration.tool_resolver.
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

from Core.market_config import is_crypto_symbol, is_forex_pair
from Orchestration.base_skill import BaseSkill
from Orchestration.crypto_analysis_skill import CryptoAnalysisSkill
from Orchestration.forex_analysis_skill import ForexAnalysisSkill
from Orchestration.skill_context import SkillContext
from Orchestration.skill_result import SkillResult
from Orchestration.text_analysis_skill import TextAnalysisSkill


class MarketAnalysisSkill(BaseSkill):
    """The project's first multi-stock orchestrator Skill: runs
    ``TextAnalysisSkill.execute()`` once per symbol in
    ``context.parameters["symbols"]`` and collects the results.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``analyze_many``, ``run_all``, ``batch``, or ``fan_out``
    anywhere on this class; the per-symbol loop lives entirely inline
    inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"market_analysis"``.
        """
        return "market_analysis"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string
            ``"Analyze multiple stocks by running TextAnalysisSkill for each symbol."``.
        """
        return "Analyze multiple stocks by running TextAnalysisSkill for each symbol."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: read ``context.parameters["symbols"]`` and
        run ``TextAnalysisSkill.execute()`` once per symbol.

        ``context.parameters`` is read defensively: if it is not a
        ``Mapping`` at all, or its ``"symbols"`` value is missing or
        not a ``list``, this method behaves as though ``"symbols"``
        were an empty list -- never raising, and producing
        ``{"stocks": []}``.

        For each symbol, a new ``SkillContext`` is built that changes
        only ``parameters`` to ``{"symbol": symbol}``; ``task``,
        ``metadata``, and ``tool_context_factory`` are carried
        through from the incoming ``context`` unchanged. A fresh
        ``TextAnalysisSkill`` instance is run against that per-symbol
        context, with this Skill's own ``self._resolve_tool`` (if any
        was injected by an ``Executor``) forwarded onto it first, so
        that instance's own ``self.execute_tool_result()`` calls can
        resolve Tools exactly as they would for any other caller.

        Args:
            context: Expected to expose ``.task``, ``.parameters``,
                ``.metadata``, and ``.tool_context_factory`` -- the
                same shape ``SkillContext`` itself has. Passed
                through defensively -- never mutated, and this method
                never raises regardless of its shape.

        Returns:
            A single, freshly constructed ``SkillResult`` with
            ``output={"stocks": [...]}``, ``success`` reflecting
            whether every symbol's analysis succeeded, and ``error``
            summarizing any symbol(s) that failed. As of Activation
            2.3.2/2.3.3, each ``stocks[i]`` entry also carries a
            ``"status"`` sibling key alongside ``"symbol"``/
            ``"analysis"`` -- one of ``"SUCCESS"``, ``"DATA_ERROR"``,
            ``"INSUFFICIENT_DATA"`` (taken by identity from
            ``analysis["status"]``), or ``"ANALYSIS_FAILED"`` (set
            here directly when this symbol raised an uncaught
            exception, in which case ``"analysis"`` is still
            ``None`` exactly as before).
        """
        symbols = []
        parameters = getattr(context, "parameters", None)
        if isinstance(parameters, Mapping):
            raw_symbols = parameters.get("symbols")
            if isinstance(raw_symbols, list):
                symbols = raw_symbols

        task = getattr(context, "task", None)
        metadata = getattr(context, "metadata", None)
        if not isinstance(metadata, Mapping):
            metadata = {}
        tool_context_factory = getattr(context, "tool_context_factory", None)

        stocks = []
        failures = []

        for symbol in symbols:
            per_symbol_context = SkillContext(
                task=task,
                parameters={"symbol": symbol},
                metadata=metadata,
                tool_context_factory=tool_context_factory,
            )

            # Activation 7 (Crypto Validation Profile): the one
            # routing decision added to this method. Every stock
            # symbol -- i.e. every symbol NOT in
            # Core.market_config.CRYPTO_SYMBOLS -- takes exactly the
            # same TextAnalysisSkill() path as before this Activation,
            # byte-for-byte unchanged. A recognized crypto symbol
            # takes the parallel CryptoAnalysisSkill() path instead
            # (price+news only, no fundamental valuation -- see that
            # module's own docstring for why). Both branches forward
            # this Skill's own self._resolve_tool the same way; the
            # only difference is which Skill class is instantiated.
            if is_crypto_symbol(symbol):
                analysis_skill = CryptoAnalysisSkill()
            else:
                if is_forex_pair(symbol):
                    analysis_skill = ForexAnalysisSkill()
                else:
                    analysis_skill = TextAnalysisSkill()
            if hasattr(self, "_resolve_tool"):
                analysis_skill._resolve_tool = self._resolve_tool

            try:
                result = analysis_skill.execute(per_symbol_context)
            except Exception as exc:  # noqa: BLE001
                # Activation 2.3.2/2.3.3: an uncaught exception while
                # processing this symbol has no analysis dict to draw
                # a status from (TextAnalysisSkill.execute() never
                # ran to completion), so it is labeled explicitly here
                # as "ANALYSIS_FAILED" -- distinct from the
                # "DATA_ERROR"/"INSUFFICIENT_DATA" statuses that come
                # from a completed analysis dict below. "analysis"
                # itself is left as None, exactly as before.
                failures.append(f"{symbol}: {exc}")
                stocks.append(
                    {"symbol": symbol, "analysis": None, "status": "ANALYSIS_FAILED"}
                )
                continue

            if not result.success:
                failures.append(f"{symbol}: {result.error}")

            analysis = None
            price_evidence = None
            news_evidence = None
            fundamental_evidence = None
            if isinstance(result.output, dict):
                analysis = result.output.get("analysis")
                # Activation 2.4 (Evidence Minimum): forward the
                # price/news/fundamental evidence TextAnalysisSkill
                # already produced, instead of discarding it here.
                # Taken by identity, never recomputed or invented.
                price_evidence = result.output.get("price")
                news_evidence = result.output.get("news")
                fundamental_evidence = result.output.get("fundamental")

            # Activation 2.3.2/2.3.3: surface the same per-symbol
            # status TextAnalysisSkill.execute() already computed
            # (SUCCESS/DATA_ERROR/INSUFFICIENT_DATA) as a sibling of
            # "analysis" on this stocks[i] entry, for callers that
            # want it without reaching into "analysis" itself. Not
            # derived or recomputed here -- taken by identity from
            # the analysis dict.
            status = None
            if isinstance(analysis, dict):
                status = analysis.get("status")

            stocks.append(
                {
                    "symbol": symbol,
                    "analysis": analysis,
                    "status": status,
                    "price": price_evidence,
                    "news": news_evidence,
                    "fundamental": fundamental_evidence,
                }
            )

        combined_success = not failures
        combined_error = "; ".join(failures) if failures else None

        return SkillResult(
            success=combined_success,
            output={"stocks": stocks},
            error=combined_error,
            metadata={},
        )