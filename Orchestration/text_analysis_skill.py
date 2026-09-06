"""TextAnalysisSkill -- the project's first "capability" Skill slot
(Phase 5, Sprint 49).

Phase 10, Sprint 114 update (Executive Summary): ``execute()``'s
``"analysis"`` dict gains one further key, ``"summary"`` -- a single
deterministic ``str`` built entirely from fixed string templates and
the ``recommendation``/``confidence``/``reason``/``strengths``/
``risks`` values already computed earlier in this same method. No
AI, no LLM, no Ollama call, and no natural-language generation of
any kind is involved: the string is assembled with plain f-strings
and ``"\\n".join(...)`` from a fixed list of lines, in this exact,
LOCKED order --

    Recommendation: <recommendation>
    Confidence: <confidence>
    <blank line>
    Strengths:
    - <each strength, one per line, in existing list order>
    <blank line>
    Risks:
    - <each risk, one per line, in existing list order>
    <blank line>
    Reason: <reason>

``strengths``/``risks`` are iterated in the exact order the Sprint
113 logic already produced them (including the "No major .../
detected" single-item fallback lists) -- never sorted, filtered, or
reordered. ``"recommendation"``, ``"confidence"``, ``"reason"``,
``"strengths"``, and ``"risks"`` themselves are completely unchanged
by this addition; ``"summary"`` is purely an additional, derived
rendering of those same five values, appended as a sixth key inside
the same ``"analysis"`` dict.

No new abstraction of any kind was introduced to build it: no
``SummaryGenerator``, ``Formatter``, ``Builder``, ``TemplateEngine``,
``Renderer``, ``Manager``, ``Pipeline``, ``Strategy``, ``Helper``, or
utility module -- the line list and the two ``for`` loops over
``strengths``/``risks`` live directly inline inside ``execute()``,
immediately after the existing Sprint 113 strengths/risks
construction and immediately before the ``SkillResult(...)``
construction.

Phase 10, Sprint 113 update (Investment Thesis): ``execute()``'s
``"analysis"`` dict gains two new, purely deterministic keys,
``"strengths"`` and ``"risks"`` -- an explicit, literal-only
investment thesis laid on top of the Sprint 112 three-Tool
combination, so a future LLM (Ollama or otherwise) is handed the
supporting evidence directly instead of having to reconstruct it.
Both are plain ``list`` values built from the very same
``price_trend``/``news_sentiment``/``fundamental_valuation`` values
already extracted for the recommendation table, plus one further
extraction, ``fundamental_result.output.get("quality")`` (again only
if that output is a ``dict``):

    Strengths (each appended independently, in this fixed order):
        price_trend == "bullish"              -> "bullish price trend"
        news_sentiment == "positive"          -> "positive market sentiment"
        fundamental_valuation == "undervalued" -> "undervalued fundamentals"
        fundamental_quality == "strong"       -> "strong company quality"
        (none of the above matched)           -> ["No major strength detected"]

    Risks (each appended independently, in this fixed order):
        price_trend == "bearish"              -> "bearish price trend"
        news_sentiment == "negative"          -> "negative market sentiment"
        fundamental_valuation == "overvalued" -> "overvalued valuation"
        fundamental_quality == "weak"         -> "weak company quality"
        (none of the above matched)           -> ["No major risk detected"]

Each of the eight conditions above is its own independent ``if``
(not ``elif``) -- unlike the recommendation table, more than one
strength/risk can and does apply simultaneously (e.g. a bullish trend
AND undervalued fundamentals both append their own string to the
same ``"strengths"`` list). Order is fixed exactly as written above
and never reordered, sorted, ranked, or scored -- there is no
priority among strengths/risks, only literal append order. Both
lists are built independently of the recommendation/confidence/reason
values and independently of ``combined_success`` -- exactly like the
Sprint 109/112 reasoning, they are derived unconditionally from
whatever the three Tool outputs turned out to be, including when one
or more Tool calls failed (a non-``dict`` output simply yields
``None`` for that field, which matches none of the four conditions
for that list, same never-raise ``isinstance``/``.get()`` style
already used throughout this method). No scoring, ranking, dynamic
reordering, inference, or free-form text generation of any kind is
involved -- every entry is one of exactly ten fixed string literals
(four strengths, four risks, and the two "No major .../detected"
fallbacks). ``"recommendation"``, ``"confidence"``, and ``"reason"``
are completely unchanged by this addition.

Phase 10, Sprint 112 update (Fundamental Integration): on top of the
Sprint 108 multi-Tool combination (``price``/``news`` keys, identity
-forwarded outputs, AND-combined ``success``, joined ``error``) and
the Sprint 109 deterministic reasoning, ``execute()`` now also calls
a THIRD production Tool -- ``"market_fundamental"`` -- through the
exact same, already-frozen ``BaseSkill.execute_tool_result()`` API
used for the first two, adds its output to the combined result under
a new ``"fundamental"`` key, and folds its ``"valuation"`` value into
the deterministic decision table as a third input alongside price
``"trend"`` and news ``"overall_sentiment"``:

    Price     News       Fundamental    Recommendation   Confidence
    bullish   positive   undervalued    BUY              HIGH
    bearish   negative   overvalued     SELL             HIGH
    bullish   negative   fair           WAIT             MEDIUM
    bearish   positive   fair           WAIT             MEDIUM
    (any other combination)             UNKNOWN          LOW

Historical (Sprint 112) table, superseded by the Activation 2
analysis-logic fix below.

Activation 2 update (analysis-logic fix): the four-row table above
recognized only 4 of the 27 valid (trend, sentiment, valuation)
combinations and routed every other one -- including the common
real-world case where trend and sentiment agree but the fundamental
is merely "fair" -- into the same UNKNOWN/"insufficient data" branch
used for genuinely missing or invalid evidence. A production probe
across real IDX symbols found 0 candidates as a direct result, even
though price/fundamental/news retrieval all worked correctly. This
was a false negative in the decision logic, not a data problem.

The table is now a deterministic, literal vote count -- still not AI,
not an LLM, not Ollama, and not any form of inference beyond a fixed
lookup: each of the three signals is first mapped onto the
bullish/bearish/neutral axis it already conceptually represents
(price ``trend`` as-is; news ``positive``/``negative``/``neutral`` ->
``bullish``/``bearish``/``neutral``; fundamental
``undervalued``/``overvalued``/``fair`` -> ``bullish``/``bearish``/
``neutral``). A value outside its axis's three recognized literals --
a missing field, ``None``, or any unrecognized/"unknown" string,
including a failed Tool call whose output isn't a dict at all -- is
genuinely missing or invalid critical evidence, and is the ONLY thing
that still falls through to the "insufficient data" branch:
``recommendation="UNKNOWN"``, ``confidence="LOW"``,
``reason="insufficient data"``. No value is guessed, inferred, or
recovered.

Once all three signals are valid:

    2-3 bullish signals, 0 bearish  -> BUY  (HIGH if 3/3, else MEDIUM)
    2-3 bearish signals, 0 bullish  -> SELL (HIGH if 3/3, else MEDIUM)
    anything else valid             -> WAIT (MEDIUM if signals
                                        actually conflict, else LOW)

``reason`` is a deterministic string built only from the same
``price_trend``/``news_sentiment``/``fundamental_valuation`` values
already used for the decision itself (plus the fixed "insufficient
data" string) -- never free-form or generated text. No new
abstraction of any kind was introduced for this fix: the vote-count
logic is written directly as plain ``if``/``elif``/``else`` branches
inside ``execute()``, in exactly the same place the historical
four-row table lived.

``fundamental`` is read from ``fundamental_result.output["valuation"]``,
looked up only if that output is a ``dict`` (the same
``isinstance``/``.get()`` check already used for ``price``/``news``
-- no ``try``/``except``). This reasoning is computed unconditionally,
from whatever the three Tool outputs turned out to be -- including
when one or more Tool calls failed (``combined_success`` is
``False``): a failed ``ToolResult``'s ``output`` is typically not a
``dict`` shaped like ``{"valuation": ...}``, so it naturally falls
into the same "insufficient data" branch without any extra
failure-specific branching being written.

Combination logic (extended this sprint), performed entirely inline
in ``execute()``:

  * ``success`` -- ``True`` only if ALL THREE Tool calls succeeded
    (logical AND of the three ``SkillResult.success`` values).
  * ``output`` -- ``{"price": ..., "news": ..., "fundamental": ...,
    "analysis": ...}``. The ``"price"``/``"news"``/``"fundamental"``
    values are taken by identity from the corresponding
    ``SkillResult.output``, never copied or transformed;
    ``"analysis"`` is the deterministic decision dict described
    above.
  * ``error`` -- ``None`` when all three succeeded; otherwise a
    single deterministic ``str`` built only from whichever
    sub-result(s) actually failed (never a dict, since
    ``SkillResult.error`` is constrained to ``Optional[str]``).
  * ``metadata`` -- ``{}``, matching the required output shape.

No new abstraction of any kind was introduced to add this third Tool
call or the extended reasoning: no ``DecisionEngine``, ``Strategy``,
``Analyzer``, ``RuleEngine``, ``Engine``, ``Pipeline``, ``Manager``,
``Helper``, ``Factory``, or ``Registry`` -- the third
``self.execute_tool_result("market_fundamental", context)`` call is a
plain, additional statement alongside the two Sprint 108 calls, and
the extended decision table is still written directly as ``if``/
``elif``/``else`` branches inside ``execute()`` itself, using only
literals and the three values already extracted from the three
``SkillResult.output`` mappings ``execute_tool_result()`` returns.

Likewise, no new abstraction of any kind was introduced for the
Sprint 113 investment thesis: no ``InvestmentThesis`` class, no
``Analyzer``, ``DecisionEngine``, ``Strategy``, ``RuleEngine``,
``Manager``, ``Pipeline``, ``Factory``, ``Registry``, ``Helper``, or
utility module. The ``"strengths"``/``"risks"`` lists are built with
eight plain, independent ``if`` statements directly inside
``execute()``, immediately alongside the existing recommendation
``if``/``elif``/``else`` chain -- nothing beyond that.

Phase 10, Sprint 109 update (First Deterministic Reasoning):
introduced the two-input (price/news) deterministic decision table
described above, superseded this sprint by the three-input table.

Phase 10, Sprint 108 update (Multi-Tool Skill Orchestration): this
Skill first called TWO Tools -- ``"market_price"`` and
``"market_news"`` -- through ``BaseSkill.execute_tool_result()`` and
combined their two ``SkillResult`` outputs into exactly one
``SkillResult``.

Phase 9, Sprint 106 update (First Real Skill -> Tool Pipeline):
``execute()`` first stopped raising and began delegating to a single
Tool (``"market_price"``) via ``BaseSkill.execute_tool_result()``.

Explicitly NOT part of this milestone: an ``__init__`` of its own,
any attribute, any cache, any configuration, any dependency
injection, any helper method (public or private) beyond the three
``BaseSkill``-required members, and any of ``parse()``,
``summarize()``, ``classify()``, ``analyze()``, ``combine()``,
``merge()``, or ``aggregate()``. No AI, no LLM calls (including
Ollama), no provider calls, no service calls, no repository calls,
no file reading, no parsing, no summarizing, and no classifying of
its own -- all of that remains each Tool's own responsibility, never
this Skill's. No scoring, no probability, and no fuzzy logic anywhere
in this file -- every branch is a deterministic ``if``/``elif``
comparison against fixed string literals.

Dependencies (LOCKED, unchanged since Sprint 106): this module
imports ``Orchestration.base_skill.BaseSkill``,
``Orchestration.skill_result.SkillResult``, and stdlib ``typing`` --
nothing else. In particular it does NOT import ``Providers``,
``Services``, ``Repository``, ``Database``, ``Agents``,
``Orchestration.workflow_runtime.WorkflowRuntime``,
``Orchestration.workflow_engine.WorkflowEngine``,
``Orchestration.executor.Executor``, ``Agents.planner.Planner``,
``Orchestration.memory``, ``Orchestration.learning_loop.LearningLoop``,
``Orchestration.reflection``, ``Orchestration.event_bus.EventBus``,
``Orchestration.tool_resolver.ToolResolver``,
``Orchestration.tool_registry.ToolRegistry``,
``Orchestration.tool_context.ToolContext``,
``Orchestration.market_price_tool.MarketPriceTool``,
``Orchestration.market_news_tool.MarketNewsTool``,
``Orchestration.market_fundamental_tool.MarketFundamentalTool``
(this Skill never resolves or instantiates any Tool itself -- it
only ever asks for one by name string, through
``execute_tool_result()``), ``requests``, ``google.genai``,
``anthropic``, ``openai``, ``ollama``, ``sqlite3``, ``pandas``,
``numpy``, or ``yfinance``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Orchestration.base_skill import BaseSkill
from Orchestration.skill_result import SkillResult


class TextAnalysisSkill(BaseSkill):
    """The second concrete Skill: the project's first Skill that
    orchestrates more than one Tool (``MarketPriceTool``,
    ``MarketNewsTool``, and, as of Sprint 112,
    ``MarketFundamentalTool``) through the existing
    ``BaseSkill.execute_tool_result()`` integration point, combines
    their results into one ``SkillResult``, derives one deterministic,
    rule-based business decision from those combined results, and (as
    of Sprint 113) an accompanying deterministic investment thesis
    (``"strengths"``/``"risks"``) explaining that decision.

    No state, no ``__init__`` of its own, no helper methods beyond
    what ``BaseSkill`` already supplies. Every method beyond the
    three ``BaseSkill`` requires is deliberately absent -- there is
    no ``parse``, ``summarize``, ``classify``, ``analyze``,
    ``combine``, ``merge``, or ``aggregate`` anywhere on this class;
    the decision table and the investment thesis both live entirely
    inline inside ``execute()`` itself.
    """

    @property
    def name(self) -> str:
        """This Skill's stable name.

        Returns:
            The literal string ``"text_analysis"``.
        """
        return "text_analysis"

    @property
    def description(self) -> str:
        """This Skill's human-readable description.

        Returns:
            The literal string ``"Analyze textual information."``.
        """
        return "Analyze textual information."

    def execute(self, context: Any) -> SkillResult:
        """Run this Skill: orchestrate the ``market_price``,
        ``market_news``, and ``market_fundamental`` Tools and combine
        their results.

        Phase 10, Sprint 112 (Fundamental Integration): calls
        ``self.execute_tool_result("market_price", context)``,
        ``self.execute_tool_result("market_news", context)``, and
        ``self.execute_tool_result("market_fundamental", context)`` --
        the same, already-frozen integration method used since
        Sprint 106, called three times, each against a real,
        registered Tool name. Every call receives the exact same
        ``context`` object this method itself received -- never
        copied, wrapped, or reshaped between calls. This Skill never
        resolves or instantiates any Tool itself; it only asks for
        each by name string through ``execute_tool_result()``, which
        is itself backed by ``BaseSkill.execute_tool()`` and the
        injected ``ToolResolver`` -- never bypassed.

        The three resulting ``SkillResult`` values are then combined,
        entirely inline, into exactly one ``SkillResult``: ``success``
        is the logical AND of all three; ``output`` is
        ``{"price": ..., "news": ..., "fundamental": ...,
        "analysis": ...}`` with ``"price"``/``"news"``/
        ``"fundamental"`` each taken by identity from their
        ``SkillResult.output``; ``error`` is ``None`` if all three
        succeeded, otherwise a single ``str`` summarizing whichever
        sub-call(s) failed; ``metadata`` is ``{}``.

        ``"analysis"`` is a ``dict`` with exactly
        ``"recommendation"``, ``"confidence"``, and ``"reason"``
        keys, derived from the price Tool's ``"trend"`` output value,
        the news Tool's ``"overall_sentiment"`` output value, and the
        fundamental Tool's ``"valuation"`` output value via the
        Activation 2 vote-count decision table (see the module
        docstring for the full derivation):

            2-3 bullish signals, 0 bearish -> BUY  / HIGH or MEDIUM
            2-3 bearish signals, 0 bullish -> SELL / HIGH or MEDIUM
            any other valid combination    -> WAIT / MEDIUM or LOW

        Any missing or unrecognized trend/sentiment/valuation value --
        including any Tool output not being a ``dict`` at all -- yields
        ``{"recommendation": "UNKNOWN", "confidence": "LOW",
        "reason": "insufficient data"}``. No value is guessed or
        inferred beyond this literal lookup; there is no scoring, no
        probability, and no fuzzy logic anywhere in this method.

        As of Sprint 113, ``"analysis"`` also carries two further
        keys, ``"strengths"`` and ``"risks"``, each a ``list`` of
        fixed strings built from independent ``if`` checks (not
        mutually exclusive with each other) against
        ``price_trend``, ``news_sentiment``, ``fundamental_valuation``,
        and a fourth extracted value, the fundamental Tool's
        ``"quality"`` output: bullish trend / positive sentiment /
        undervalued valuation / strong quality each append their own
        fixed string to ``"strengths"``; bearish trend / negative
        sentiment / overvalued valuation / weak quality each append
        their own fixed string to ``"risks"``. If none of a list's
        four conditions match, that list is instead exactly
        ``["No major strength detected"]`` or
        ``["No major risk detected"]``. Order is fixed, never sorted
        or ranked; both lists are independent of
        ``recommendation``/``confidence``/``reason``.

        As of Sprint 114, ``"analysis"`` also carries a sixth key,
        ``"summary"`` -- a single deterministic, template-built
        ``str`` rendering ``recommendation``/``confidence``/
        ``strengths``/``risks``/``reason`` in the fixed, LOCKED
        layout described in the module docstring. No AI, no LLM, and
        no free-form text generation is involved; it is built with
        plain f-strings and ``"\\n".join(...)`` over a fixed line
        list, directly inline in this method.

        As of Activation 2.3.2/2.3.3, ``"analysis"`` also carries a
        seventh key, ``"status"``, one of ``"SUCCESS"``,
        ``"DATA_ERROR"``, or ``"INSUFFICIENT_DATA"`` -- derived only
        from ``combined_success`` and whether the decision table above
        fell through to its "insufficient data" else-branch, with no
        change to that table or to any other business logic. Per the
        Activation 2.3.3 acceptance gate, ``"recommendation"`` is
        ``None`` whenever ``"status"`` is not ``"SUCCESS"``;
        ``"confidence"``, ``"reason"``, ``"strengths"``, ``"risks"``,
        and ``"summary"`` are unchanged for every status.

        Args:
            context: Passed straight through, unexamined, to all
                three ``self.execute_tool_result(...)`` calls -- the
                exact same object, never copied or wrapped.

        Returns:
            A single, freshly constructed ``SkillResult`` combining
            all three Tools' outputs as described above.

        Raises:
            Exception: any exception raised by any
                ``self.execute_tool_result()`` call (including a
                missing-resolver ``SkillError``, an unresolvable-tool
                ``ToolResolverError``, or any Tool-side failure)
                propagates unchanged -- never caught, never wrapped.
                A raise from an earlier call means the later call(s)
                are never made, exactly as a plain, un-guarded
                sequence of statements behaves.
        """
        price_result = self.execute_tool_result("market_price", context)
        news_result = self.execute_tool_result("market_news", context)
        fundamental_result = self.execute_tool_result("market_fundamental", context)

        # Activation 2.4 (Evidence Minimum): surface the symbol this
        # analysis was actually run for, taken by identity from
        # context.parameters["symbol"] -- the same value already
        # forwarded unchanged to all three Tool calls above. Read
        # defensively; no value is guessed or invented if it is
        # missing.
        evidence_symbol = None
        context_parameters = getattr(context, "parameters", None)
        if isinstance(context_parameters, Mapping):
            evidence_symbol = context_parameters.get("symbol")

        combined_success = (
            price_result.success
            and news_result.success
            and fundamental_result.success
        )

        combined_error = None
        if not combined_success:
            failures = []
            if not price_result.success:
                failures.append(f"market_price: {price_result.error}")
            if not news_result.success:
                failures.append(f"market_news: {news_result.error}")
            if not fundamental_result.success:
                failures.append(f"market_fundamental: {fundamental_result.error}")
            combined_error = "; ".join(failures)

        price_trend = None
        if isinstance(price_result.output, dict):
            price_trend = price_result.output.get("trend")

        news_sentiment = None
        if isinstance(news_result.output, dict):
            news_sentiment = news_result.output.get("overall_sentiment")

        fundamental_valuation = None
        if isinstance(fundamental_result.output, dict):
            fundamental_valuation = fundamental_result.output.get("valuation")

        fundamental_quality = None
        if isinstance(fundamental_result.output, dict):
            fundamental_quality = fundamental_result.output.get("quality")

        # Activation 2 fix (analysis logic): the previous table only
        # recognized 4 of the 27 valid (trend, sentiment, valuation)
        # combinations and sent every other one -- including the
        # common real-world case where trend and sentiment agree but
        # the fundamental is merely "fair" -- into the same
        # UNKNOWN/"insufficient data" branch used for genuinely
        # missing/invalid evidence. That conflated "the evidence is
        # mixed" with "the evidence doesn't exist", which is why a
        # production probe across real IDX symbols found 0 candidates
        # even though price/fundamental/news retrieval all worked.
        #
        # Fixed rule (still a pure, deterministic literal lookup --
        # no scoring, no probability, no fuzzy logic): each of the
        # three signals is first mapped onto the bullish/bearish/
        # neutral axis it already conceptually represents --
        #     price_trend           : bullish / bearish / neutral (as-is)
        #     news_sentiment        : positive->bullish, negative->bearish, neutral->neutral
        #     fundamental_valuation : undervalued->bullish, overvalued->bearish, fair->neutral
        # A value outside its axis's three recognized literals (a
        # missing field, ``None``, or any unrecognized/"unknown"
        # string -- including a failed Tool call, whose output is not
        # shaped like the expected dict at all) is genuinely missing
        # or invalid critical evidence, and is the ONLY thing that
        # still falls through to UNKNOWN/"insufficient data". Once all
        # three signals are valid:
        #   * 2 or 3 bullish signals and 0 bearish -> BUY
        #       (HIGH confidence when all 3 agree, MEDIUM for 2-of-3)
        #   * 2 or 3 bearish signals and 0 bullish -> SELL
        #       (HIGH confidence when all 3 agree, MEDIUM for 2-of-3)
        #   * anything else valid -- a genuine conflict between a
        #     bullish and a bearish signal, or no signal strong enough
        #     either way -> WAIT (MEDIUM confidence when the signals
        #     actually conflict, LOW confidence when they are simply
        #     flat/neutral). No evidence is invented anywhere in this
        #     branch; every input is exactly what the three Tools
        #     already produced.
        _trend_axis = {"bullish": "bullish", "bearish": "bearish", "neutral": "neutral"}
        _sentiment_axis = {"positive": "bullish", "negative": "bearish", "neutral": "neutral"}
        _valuation_axis = {"undervalued": "bullish", "overvalued": "bearish", "fair": "neutral"}

        trend_signal = _trend_axis.get(price_trend)
        sentiment_signal = _sentiment_axis.get(news_sentiment)
        valuation_signal = _valuation_axis.get(fundamental_valuation)

        if trend_signal is None or sentiment_signal is None or valuation_signal is None:
            recommendation = "UNKNOWN"
            confidence = "LOW"
            reason = "insufficient data"
        else:
            signals = (trend_signal, sentiment_signal, valuation_signal)
            bullish_votes = signals.count("bullish")
            bearish_votes = signals.count("bearish")

            if bullish_votes >= 2 and bearish_votes == 0:
                recommendation = "BUY"
                confidence = "HIGH" if bullish_votes == 3 else "MEDIUM"
                reason = (
                    f"aligned bullish evidence: price={price_trend}, "
                    f"news={news_sentiment}, fundamental={fundamental_valuation}"
                )
            elif bearish_votes >= 2 and bullish_votes == 0:
                recommendation = "SELL"
                confidence = "HIGH" if bearish_votes == 3 else "MEDIUM"
                reason = (
                    f"aligned bearish evidence: price={price_trend}, "
                    f"news={news_sentiment}, fundamental={fundamental_valuation}"
                )
            else:
                recommendation = "WAIT"
                confidence = "MEDIUM" if bullish_votes and bearish_votes else "LOW"
                reason = (
                    f"mixed evidence: price={price_trend}, "
                    f"news={news_sentiment}, fundamental={fundamental_valuation}"
                )

        strengths = []
        if price_trend == "bullish":
            strengths.append("bullish price trend")
        if news_sentiment == "positive":
            strengths.append("positive market sentiment")
        if fundamental_valuation == "undervalued":
            strengths.append("undervalued fundamentals")
        if fundamental_quality == "strong":
            strengths.append("strong company quality")
        if not strengths:
            strengths = ["No major strength detected"]

        risks = []
        if price_trend == "bearish":
            risks.append("bearish price trend")
        if news_sentiment == "negative":
            risks.append("negative market sentiment")
        if fundamental_valuation == "overvalued":
            risks.append("overvalued valuation")
        if fundamental_quality == "weak":
            risks.append("weak company quality")
        if not risks:
            risks = ["No major risk detected"]

        summary_lines = [
            f"Recommendation: {recommendation}",
            f"Confidence: {confidence}",
            "",
            "Strengths:",
        ]
        for strength in strengths:
            summary_lines.append(f"- {strength}")
        summary_lines.append("")
        summary_lines.append("Risks:")
        for risk in risks:
            summary_lines.append(f"- {risk}")
        summary_lines.append("")
        summary_lines.append(f"Reason: {reason}")
        summary = "\n".join(summary_lines)

        # Activation 2.3.2/2.3.3 (status), extended by the Activation 2
        # analysis-logic fix above: explicit status for this
        # per-symbol analysis result, derived only from state already
        # computed above. Precedence, checked in this fixed order:
        #   1. DATA_ERROR         -- combined_success is False, i.e.
        #                            one or more of the three Tool
        #                            calls failed.
        #   2. INSUFFICIENT_DATA  -- all three Tool calls succeeded,
        #                            but at least one of trend/
        #                            sentiment/valuation was missing
        #                            or unrecognized, so the decision
        #                            logic above fell through to its
        #                            "insufficient data" branch
        #                            (identified here purely by that
        #                            branch's own fixed, unique output
        #                            signature -- no separate flag or
        #                            new state).
        #   3. SUCCESS            -- all three Tool calls succeeded
        #                            and all three signals were valid,
        #                            producing BUY, SELL, or WAIT.
        # Per the Activation 2.3.3 acceptance gate, only
        # "recommendation" is gated on this status: it is emitted
        # as-is for SUCCESS and as None for the other two statuses.
        # "confidence"/"reason"/"strengths"/"risks"/"summary" are left
        # completely unchanged for every status.
        if not combined_success:
            status = "DATA_ERROR"
        elif (
            recommendation == "UNKNOWN"
            and confidence == "LOW"
            and reason == "insufficient data"
        ):
            status = "INSUFFICIENT_DATA"
        else:
            status = "SUCCESS"

        recommendation_for_output = recommendation if status == "SUCCESS" else None

        return SkillResult(
            success=combined_success,
            output={
                "symbol": evidence_symbol,
                "price": price_result.output,
                "news": news_result.output,
                "fundamental": fundamental_result.output,
                "analysis": {
                    "recommendation": recommendation_for_output,
                    "confidence": confidence,
                    "reason": reason,
                    "strengths": strengths,
                    "risks": risks,
                    "summary": summary,
                    "status": status,
                },
            },
            error=combined_error,
            metadata={},
        )