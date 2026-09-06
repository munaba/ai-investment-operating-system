"""RankingEngine -- Activation 2.5 (LOCKED DECISION, supersedes
Sprint 5 STEP 2's normalization-only contract), weights and score
transparency extracted per Activation 2.6.

``RankingEngine`` does exactly what its name says: it turns
``WatchlistScanner.scan()``'s raw ``Dict[str, Dict[str, SkillResult]]``
return shape into a flat, cross-watchlist ``List[RankedSymbol]``, in
five steps, always in this order --

    1. filter out failed per-symbol analysis results
    2. compute a deterministic score (and its breakdown) per
       surviving symbol
    3. sort surviving symbols by that score
    4. assign a unique, sequential, cross-watchlist rank
    5. return the sorted, ranked list

SUPERSEDED LOCKED DECISION (Sprint 5 STEP 2): that STEP's "pure
normalization layer, no score, no sorting, output order == input
order" contract is explicitly overridden by this Activation. The old
``rank`` field (read verbatim from ``portfolio_entry["rank"]``, a
per-symbol-only, always-identical-across-symbols value -- see Sprint
5 STEP 1's known-state note) is retired. ``RankedSymbol.rank`` is now
this class's own computed cross-watchlist rank.

Score source (LOCKED DECISION core, extended additively by Activation
2.9, no fabricated data): score is a deterministic function of fields
this pipeline already produces per symbol. The LOCKED core is exactly
two fields -- ``recommendation`` (``"BUY"``/``"WAIT"``/``"SELL"``) and
``confidence`` (``"HIGH"``/``"MEDIUM"``/``"LOW"``), both read from the
``"watchlist"`` SkillResult entry (the same entry STEP 2 already read
them from):

    core_score = weights.recommendation_weight[recommendation] * 10
               + weights.confidence_weight[confidence]

The ``* 10`` term makes ``recommendation`` strictly dominate
``confidence`` within this core whenever both weight tables use their
Activation 2.5 default magnitudes -- a "BUY" outranks every "WAIT",
which outranks every "SELL", regardless of confidence; confidence
only breaks ties *within* the same recommendation bucket. This is the
one LOCKED scoring *formula* for this core; a future Activation may
replace it, but must replace this whole block, not patch it
piecemeal. (The *weight values* plugged into this formula are, as of
Activation 2.6, configurable -- see "Weights (Activation 2.6)" below.
The formula's structure is not.)

Activation 2.9 (Ranking Score Differentiation) adds four further,
purely additive terms on top of ``core_score`` -- ``technical``
(price ``trend``), ``sentiment`` (news ``overall_sentiment``), and
``fundamental_valuation``/``fundamental_quality`` (fundamental
``valuation``/``quality``), each read from the ``"market"`` SkillResult
entry's already-existing ``"price"``/``"news"``/``"fundamental"``
evidence (Activation 2.4, "Evidence Minimum") this class previously
never looked at:

    score = core_score
          + weights.technical_weight.get(trend, 0)
          + weights.sentiment_weight.get(sentiment, 0)
          + weights.fundamental_valuation_weight.get(valuation, 0)
          + weights.fundamental_quality_weight.get(quality, 0)

This is why real IDX scans previously produced the exact same score
for every symbol that happened to land in the same (recommendation,
confidence) bucket -- the core formula had no other input to differ
on. These four evidence terms give symbols in the same bucket a
differentiated, still fully deterministic and explainable score
(see ``ScoreBreakdown``), without changing which bucket dominates:
Activation 2.9's default weight magnitudes are deliberately small
relative to the core's ``* 10`` recommendation term, so evidence
differentiates *within* a bucket rather than silently overturning
core's own BUY > WAIT > SELL ordering by default (a deployment can
still choose to make evidence dominate, via ``RANKING_WEIGHT_*`` env
vars -- see ``Business.ranking_weights_config``). Any of the four
evidence values that is missing, unrecognized, or backed by an absent/
malformed ``"market"`` entry contributes exactly ``0`` (looked up with
``.get(value, 0)``, never a bare key lookup) -- never guessed, never
invented, and never used to exclude a symbol from ranking.

Weights (Activation 2.6, LOCKED DECISION): ``RECOMMENDATION_WEIGHT``
and ``CONFIDENCE_WEIGHT`` are no longer hardcoded module-level
constants in this file. They now live in exactly one canonical place,
``Business.ranking_weights_config.RankingWeights`` (loaded via
``load_ranking_weights()``), which reads them from environment
configuration through the existing ``Core.config.config`` singleton
-- the same mechanism ``Core.approval_config`` already uses elsewhere
in this codebase. ``RankingEngine`` takes a ``RankingWeights`` value
as an optional constructor argument and defaults to
``load_ranking_weights()`` when the caller does not supply one, so
``RankingEngine()`` still requires no argument (composition_root.py's
existing wiring is unaffected), while a caller (or a future
``Core.composition_root`` wiring change, or an env var) can supply or
override the weights without ever editing this file. Changing a
weight is therefore a configuration change, not a code change to this
class. Defaults reproduce Activation 2.5's original values exactly,
so an unconfigured deployment's ranking is unchanged.

Score breakdown (Activation 2.6, LOCKED DECISION): every
``RankedSymbol`` now also carries a ``score_breakdown``
(``ScoreBreakdown``) recording exactly which components were read and
how each contributed to ``score`` -- ``recommendation``/
``recommendation_weight``/``recommendation_contribution`` and
``confidence``/``confidence_weight``/``confidence_contribution``.
These are the *only* two components ``RankingEngine`` reads today
(Activation 2.6 audit); ``ScoreBreakdown`` deliberately has no
technical/fundamental/sentiment/risk-penalty/data-completeness-penalty
field, because no source this class reads produces any of those --
adding one here would be fabricated data, not transparency.

Sort (LOCKED DECISION): surviving ``RankedSymbol`` entries are sorted
by ``score`` descending (highest score first). The sort is stable
(Python's ``list.sort()``/``sorted()`` guarantee), and the input to
the sort is already in ``scan_result``'s own watchlist order, so ties
(equal score) are broken by original watchlist order -- deterministic,
never arbitrary, never re-derived from anything not already in the
data.

Rank (LOCKED DECISION): after sorting, ``rank`` is assigned as each
entry's 1-based position in the sorted list -- ``1`` is the top
(highest-score) symbol, unique and sequential with no gaps, computed
across the *entire* surviving watchlist, not per-symbol.

Failure filtering (LOCKED DECISION, "keluarkan hasil gagal"): a
symbol is excluded from the returned list -- silently, no exception,
no partial entry -- if any of the following is true for its
``scan_result[symbol]`` entry:

    * the ``"watchlist"`` key is missing;
    * ``scan_result[symbol]["watchlist"].success`` is not ``True``;
    * ``.output`` is not a mapping, or has no ``"watchlist"`` key, or
      that value is not a non-empty list, or its first element is not
      a mapping;
    * that mapping's ``"recommendation"`` is not one of
      ``Business.ranking_weights_config.RECOMMENDATION_KEYS``, or
      ``"confidence"`` is not one of
      ``Business.ranking_weights_config.CONFIDENCE_KEYS``.

These two key sets (LOCKED, not configurable -- see
``ranking_weights_config`` module docstring) are the same recognized
domains Activation 2.5 used (previously expressed as the *keys* of
the old hardcoded weight dicts); only the *weight value* attached to
each key became configurable in Activation 2.6, not which values are
recognized at all. So this failure-filtering behaviour is byte-for-
byte unchanged from Activation 2.5.

Only the ``"watchlist"`` SkillResult is used as the failure gate,
because it is the *only* SkillResult this class reads data from (see
"Score source" above) -- checking a SkillResult this class never
consumes (``"portfolio"``, ``"market"``) would filter symbols for
reasons unrelated to what is actually computed here. In particular,
``"market"``'s own, already-documented, separate failure mode (STEP 1
known state: ``MarketAnalysisSkill`` has no ``_resolve_tool``
injected yet, so ``market_result.success`` is currently ``False`` for
every symbol) is deliberately NOT used as a failure criterion --
using it would exclude every symbol, every run, which is not this
Activation's intent and is out of scope ("jangan mengubah algoritma
analisis"). That pre-existing gap remains open for a future
Activation to address at its source.

No exception is raised by ``rank()`` on account of a malformed or
failed per-symbol entry -- that entry is simply excluded. An
exception still propagates unchanged only if ``scan_result`` itself is
not iterable as a mapping (a caller contract violation, not a
per-symbol analysis failure).

Constructor (Activation 2.6, LOCKED): ``RankingEngine(weights:
Optional[RankingWeights] = None)`` -- still no *required* argument;
``weights`` defaults to ``load_ranking_weights()`` (Activation 2.5's
"no dependency" constructor, extended, not broken).

Public API (LOCKED, unchanged): exactly one public method, ``rank()``.

Dependencies (Activation 2.6, updated): this module imports
``dataclasses.dataclass``, ``typing``,
``Orchestration.skill_result.SkillResult`` (for the type annotation
only -- never constructed here), and, new in Activation 2.6,
``Business.ranking_weights_config`` (the canonical weights source --
still no database, Repository, Tool, Skill, Pipeline, or Agent
import). It still does NOT import
``Repository.persistence.watchlist_repository.WatchlistRepository``,
``Orchestration.market_analysis_agent.MarketAnalysisAgent``,
``Orchestration.watchlist_scanner.WatchlistScanner``, any Tool, any
Skill, any Pipeline, ``Business.paper_trading_engine.PaperTradingEngine``,
``Business.position_manager.PositionManager``, or
``Business.account_balance_service.AccountBalanceService``. It no
longer reads the ``"portfolio"`` SkillResult entry at all (superseded
-- see "Score source" above).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from Business.ranking_weights_config import RankingWeights, load_ranking_weights
from Orchestration.skill_result import SkillResult

#: The four explicit non-success status sentinels
#: ``Orchestration.watchlist_analysis_skill.WatchlistAnalysisSkill`` may
#: write into a watchlist entry's ``"recommendation"`` field in place of
#: a real ``"BUY"``/``"WAIT"``/``"SELL"`` value (see that Skill's own
#: "ONLY FIX" comments). None of these is ever a member of
#: ``RankingWeights.recommendation_weight`` by design; used only by
#: ``RankingEngine._diagnose_failure`` to report the real reason a
#: symbol was excluded, never to change ``_extract_valid_entries``'s
#: own filtering.
_FAILURE_STATUS_VALUES = ("DATA_ERROR", "ANALYSIS_FAILED", "INSUFFICIENT_DATA", "SKIPPED")


@dataclass(frozen=True)
class ScoreBreakdown:
    """Explains exactly how one ``RankedSymbol.score`` was computed.

    Activation 2.6 fields (unchanged): ``recommendation``/
    ``recommendation_weight``/``recommendation_contribution`` and
    ``confidence``/``confidence_weight``/``confidence_contribution``,
    read from the ``"watchlist"`` SkillResult entry, still the
    dominant term in ``score`` (see module docstring, "Score source").

    Activation 2.9 fields (additive, new): ``technical_trend``/
    ``technical_contribution``, ``sentiment``/``sentiment_contribution``,
    ``fundamental_valuation``/``fundamental_valuation_contribution``,
    and ``fundamental_quality``/``fundamental_quality_contribution`` --
    read from the ``"market"`` SkillResult entry's already-existing
    ``"price"``/``"news"``/``"fundamental"`` evidence (Activation 2.4,
    "Evidence Minimum"), which ``RankingEngine`` did not previously
    consume. These are not a fabricated component: every one of these
    four values is produced today by a source this pipeline already
    runs (``Orchestration.market_price_tool``/``market_news_tool``/
    ``market_fundamental_tool``, via ``TextAnalysisSkill`` and
    forwarded by ``MarketAnalysisSkill``) -- see ``Business.
    ranking_weights_config`` module docstring, "Activation 2.9
    finding". When evidence for one of these four is missing,
    unrecognized, or the whole ``"market"`` entry is absent/malformed,
    that field is ``None`` and its contribution is exactly ``0`` --
    never guessed, never defaulted to a nonzero value.

    ``recommendation_contribution + confidence_contribution +
    technical_contribution + sentiment_contribution +
    fundamental_valuation_contribution +
    fundamental_quality_contribution`` always equals the ``score`` on
    the same ``RankedSymbol``.

    Attributes:
        recommendation: The recommendation value this component was
            computed from (``"BUY"``/``"WAIT"``/``"SELL"``).
        recommendation_weight: The configured weight applied to
            ``recommendation`` (from the ``RankingWeights`` this
            engine run used).
        recommendation_contribution: ``recommendation_weight * 10`` --
            this component's contribution to ``score``.
        confidence: The confidence value this component was computed
            from (``"HIGH"``/``"MEDIUM"``/``"LOW"``).
        confidence_weight: The configured weight applied to
            ``confidence``.
        confidence_contribution: ``confidence_weight * 1`` -- this
            component's contribution to ``score``.
        technical_trend: The price trend this component was computed
            from (``"bullish"``/``"neutral"``/``"bearish"``), or
            ``None`` if unavailable.
        technical_contribution: The configured
            ``technical_weight[technical_trend]``, or ``0`` when
            ``technical_trend`` is ``None`` or unrecognized.
        sentiment: The news sentiment this component was computed
            from (``"positive"``/``"neutral"``/``"negative"``), or
            ``None`` if unavailable.
        sentiment_contribution: The configured
            ``sentiment_weight[sentiment]``, or ``0`` when
            ``sentiment`` is ``None`` or unrecognized.
        fundamental_valuation: The fundamental valuation this
            component was computed from (``"undervalued"``/
            ``"fair"``/``"overvalued"``), or ``None`` if unavailable.
        fundamental_valuation_contribution: The configured
            ``fundamental_valuation_weight[fundamental_valuation]``,
            or ``0`` when ``fundamental_valuation`` is ``None`` or
            unrecognized.
        fundamental_quality: The fundamental quality this component
            was computed from (``"strong"``/``"weak"``), or ``None``
            if unavailable.
        fundamental_quality_contribution: The configured
            ``fundamental_quality_weight[fundamental_quality]``, or
            ``0`` when ``fundamental_quality`` is ``None`` or
            unrecognized.
    """

    recommendation: str
    recommendation_weight: int
    recommendation_contribution: int
    confidence: str
    confidence_weight: int
    confidence_contribution: int
    technical_trend: Optional[str] = None
    technical_contribution: int = 0
    sentiment: Optional[str] = None
    sentiment_contribution: int = 0
    fundamental_valuation: Optional[str] = None
    fundamental_valuation_contribution: int = 0
    fundamental_quality: Optional[str] = None
    fundamental_quality_contribution: int = 0


@dataclass
class RankedSymbol:
    """One symbol's ranking outcome after cross-watchlist scoring,
    sorting, and rank assignment.

    Seven fields: the original four (``symbol``/``recommendation``/
    ``confidence``/``priority``, unchanged in meaning), ``score`` and
    ``rank`` (unchanged in meaning since Activation 2.5), plus a new
    Activation 2.6 field, ``score_breakdown``, explaining ``score``'s
    provenance.

    Attributes:
        symbol: The ticker this entry describes.
        recommendation: Read from the ``"watchlist"`` SkillResult's
            entry -- one of ``"BUY"``/``"WAIT"``/``"SELL"``.
        confidence: Read from the ``"watchlist"`` SkillResult's
            entry -- one of ``"HIGH"``/``"MEDIUM"``/``"LOW"``.
        priority: Read from the ``"watchlist"`` SkillResult's entry --
            a 1-based position from ``WatchlistAnalysisSkill``'s own
            internal ordering. Unrelated to ``rank``; carried through
            unchanged.
        score: Computed from this same symbol's ``recommendation``/
            ``confidence`` and the ``RankingWeights`` in effect for
            this ``rank()`` call -- see module docstring.
        rank: This symbol's 1-based position after sorting all
            surviving symbols by ``score`` descending -- unique and
            sequential across the entire watchlist, ``1`` is the
            top-scored symbol.
        score_breakdown: The ``ScoreBreakdown`` explaining exactly how
            ``score`` was computed. ``None`` only when a
            ``RankedSymbol`` is constructed directly by other code
            (e.g. existing test fixtures) without supplying one --
            every ``RankedSymbol`` ``RankingEngine.rank()`` itself
            returns always has this populated.
    """

    symbol: str
    recommendation: str
    confidence: str
    priority: int
    score: int
    rank: int
    score_breakdown: Optional[ScoreBreakdown] = None


class RankingEngine:
    """Filters, scores, sorts, and ranks ``WatchlistScanner.scan()``'s
    raw per-symbol ``SkillResult`` mapping into a flat, cross-watchlist
    ``List[RankedSymbol]``.

    Constructor takes one optional argument, ``weights`` -- the
    ``RankingWeights`` to score with. When omitted, it is loaded from
    ``Business.ranking_weights_config.load_ranking_weights()`` (the
    canonical, environment-configurable source), so
    ``RankingEngine()`` still works exactly as before Activation 2.6
    for any caller that does not need to override weights explicitly.
    Five private helper methods, one per pipeline step, called in
    fixed order from ``rank()``.
    """

    def __init__(self, weights: Optional[RankingWeights] = None) -> None:
        """
        Args:
            weights: The ``RankingWeights`` to score with. Defaults to
                ``load_ranking_weights()`` (reads ``RANKING_WEIGHT_*``
                env vars via ``Core.config``, falling back to
                Activation 2.5's original values for any unset one)
                when not supplied.
        """
        self._weights: RankingWeights = weights if weights is not None else load_ranking_weights()

    def rank(
        self,
        scan_result: Dict[str, Dict[str, SkillResult]],
    ) -> List[RankedSymbol]:
        """Filter, score, sort, and rank ``scan_result`` into a
        ``List[RankedSymbol]``.

        Pipeline (LOCKED DECISION, always this order):

            1. ``_extract_valid_entries`` -- drop any symbol whose
               ``"watchlist"`` SkillResult is missing, unsuccessful,
               or malformed (see module docstring, "Failure
               filtering").
            2. ``_extract_evidence`` (Activation 2.9, additive) --
               best-effort read of this same symbol's already-produced
               technical/sentiment/fundamental evidence from the
               ``"market"`` SkillResult entry (Activation 2.4,
               "Evidence Minimum"). Never gates failure, never raises;
               any missing/malformed evidence simply yields ``None``
               for that component.
            3. ``_score`` -- compute a deterministic score (and its
               ``ScoreBreakdown``) for each surviving symbol from its
               ``recommendation``/``confidence`` (LOCKED, dominant
               term) plus its technical/sentiment/fundamental evidence
               (Activation 2.9, additive differentiation), using this
               engine's ``RankingWeights``.
            4. sort surviving symbols by score, descending, stable.
            5. assign ``rank`` = 1-based position in the sorted list.

        Args:
            scan_result: The exact dict
                ``WatchlistScanner.scan()`` returns -- one entry per
                symbol, each a dict with (at least) a ``"watchlist"``
                key holding a ``SkillResult``.

        Returns:
            A ``List[RankedSymbol]``, one per symbol that passed the
            failure filter, sorted by score descending, each with a
            unique 1-based ``rank`` and a populated
            ``score_breakdown``. Symbols that failed analysis are
            silently excluded -- never raise on their account. Returns
            an empty list if every symbol failed, or if
            ``scan_result`` is empty.
        """
        valid_entries = self._extract_valid_entries(scan_result)

        scored = []
        for symbol, recommendation, confidence, priority in valid_entries:
            trend, sentiment, valuation, quality = self._extract_evidence(
                scan_result.get(symbol), symbol
            )
            score, breakdown = self._score(
                recommendation, confidence, trend, sentiment, valuation, quality
            )
            scored.append(
                RankedSymbol(
                    symbol=symbol,
                    recommendation=recommendation,
                    confidence=confidence,
                    priority=priority,
                    score=score,
                    rank=0,  # placeholder, assigned below after sort
                    score_breakdown=breakdown,
                )
            )

        scored.sort(key=lambda ranked_symbol: ranked_symbol.score, reverse=True)

        for position, ranked_symbol in enumerate(scored, start=1):
            ranked_symbol.rank = position

        return scored

    def _extract_valid_entries(
        self,
        scan_result: Dict[str, Dict[str, SkillResult]],
    ):
        """Yield ``(symbol, recommendation, confidence, priority)``
        for every symbol whose ``"watchlist"`` SkillResult is present,
        successful, and well-formed -- silently skipping any symbol
        that fails that check (LOCKED DECISION, "keluarkan hasil
        gagal"; see module docstring for the exact criteria).
        """
        valid = []

        for symbol, agent_result in scan_result.items():
            watchlist_result = agent_result.get("watchlist")

            if watchlist_result is None or watchlist_result.success is not True:
                continue

            output = watchlist_result.output
            if not isinstance(output, dict):
                continue

            watchlist_list = output.get("watchlist")
            if not isinstance(watchlist_list, list) or not watchlist_list:
                continue

            watchlist_entry = watchlist_list[0]
            if not isinstance(watchlist_entry, dict):
                continue

            recommendation = watchlist_entry.get("recommendation")
            confidence = watchlist_entry.get("confidence")
            priority = watchlist_entry.get("priority")

            if recommendation not in self._weights.recommendation_weight:
                continue
            if confidence not in self._weights.confidence_weight:
                continue

            valid.append((symbol, recommendation, confidence, priority))

        return valid

    def extract_failures(
        self,
        scan_result: Dict[str, Dict[str, SkillResult]],
    ) -> List[Tuple[str, str]]:
        """Return ``(symbol, reason)`` for every symbol ``rank()`` would
        silently exclude (Activation 2.7, purely additive).

        Does not change ``rank()``'s own output or algorithm in any
        way -- it calls the existing, untouched
        ``_extract_valid_entries`` once to find the same "valid" set
        that method already computes, then reports the complement
        (every symbol in ``scan_result`` that is NOT in that set)
        together with a human-readable reason from
        ``_diagnose_failure``. This exists so a caller (Activation
        2.7's ``ManualScanService``) can persist a ``status="error"``
        row for a failed symbol instead of losing it the moment
        ``rank()`` filters it out -- the filtering criteria themselves
        are unchanged, LOCKED, and not duplicated here in a way that
        could diverge (this method delegates to the real filter).

        Args:
            scan_result: The exact dict ``WatchlistScanner.scan()``
                returns -- same shape ``rank()`` itself accepts.

        Returns:
            A list of ``(symbol, reason)`` pairs, in ``scan_result``'s
            own iteration order. Empty if every symbol is valid.
        """
        valid_symbols = {entry[0] for entry in self._extract_valid_entries(scan_result)}
        failures: List[Tuple[str, str]] = []
        for symbol, agent_result in scan_result.items():
            if symbol in valid_symbols:
                continue
            failures.append((symbol, self._diagnose_failure(agent_result)))
        return failures

    def _diagnose_failure(self, agent_result: Dict[str, SkillResult]) -> str:
        """Human-readable reason one symbol failed
        ``_extract_valid_entries``'s filter (Activation 2.7, read-only
        diagnostic -- mirrors that method's own checks in the same
        order, but never raises and never changes what counts as
        valid).
        """
        watchlist_result = agent_result.get("watchlist") if isinstance(agent_result, dict) else None

        if watchlist_result is None:
            return "missing 'watchlist' SkillResult"
        if watchlist_result.success is not True:
            return watchlist_result.error or "'watchlist' SkillResult was not successful"

        output = watchlist_result.output
        if not isinstance(output, dict):
            return "'watchlist' SkillResult.output is not a dict"

        watchlist_list = output.get("watchlist")
        if not isinstance(watchlist_list, list) or not watchlist_list:
            return "'watchlist' output has no watchlist entries"

        entry = watchlist_list[0]
        if not isinstance(entry, dict):
            return "watchlist entry is not a dict"

        recommendation = entry.get("recommendation")
        confidence = entry.get("confidence")

        # Activation IDX-scan-status fix: WatchlistAnalysisSkill already
        # normalizes a non-SUCCESS MarketAnalysisSkill result into one
        # of these four explicit failure-status sentinels (see that
        # Skill's own "ONLY FIX" comments) instead of a real
        # BUY/WAIT/SELL recommendation. None of them is a member of
        # ``self._weights.recommendation_weight`` by design -- that is
        # exactly why ``_extract_valid_entries`` already excludes them
        # from ranking, unchanged. Previously this method reported
        # that exclusion as "unrecognized recommendation: <value>",
        # which is misleading for these four values specifically: they
        # are not unrecognized garbage, they are the deliberate,
        # already-known upstream status. Report that status verbatim
        # instead, so a caller (``ManualScanService``) persists and
        # displays the real reason a symbol has no recommendation,
        # rather than turning it into a confusing "DATA_ERROR" for
        # every one of these four different outcomes.
        if recommendation in _FAILURE_STATUS_VALUES:
            return recommendation
        if recommendation not in self._weights.recommendation_weight:
            return f"unrecognized recommendation: {recommendation!r}"
        if confidence not in self._weights.confidence_weight:
            return f"unrecognized confidence: {confidence!r}"

        return "unknown"

    def _extract_evidence(
        self,
        agent_result: Optional[Dict[str, SkillResult]],
        symbol: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Best-effort, read-only extraction of one symbol's
        technical/sentiment/fundamental evidence from its ``"market"``
        SkillResult entry (Activation 2.9, purely additive).

        This evidence -- price ``trend``, news ``overall_sentiment``,
        fundamental ``valuation``/``quality`` -- is already produced
        by ``TextAnalysisSkill`` and forwarded onto each stock entry
        by ``MarketAnalysisSkill`` (Activation 2.4, "Evidence
        Minimum"); this method reads it, it computes nothing new and
        invents nothing. It never gates failure (only
        ``_extract_valid_entries``'s own ``"watchlist"``-based check
        does that -- unchanged) and never raises: any missing key,
        wrong type, unsuccessful ``SkillResult``, or symbol not found
        in the ``"market"`` entry's ``"stocks"`` list simply yields
        ``None`` for the affected component(s).

        Args:
            agent_result: ``scan_result[symbol]`` -- the same mapping
                ``_extract_valid_entries`` already reads the
                ``"watchlist"`` key from -- or ``None``/anything else
                if that symbol has no entry at all.
            symbol: The ticker being scored, used to find the matching
                stock entry inside ``"market"``'s own ``"stocks"``
                list (falling back to that list's first entry if no
                exact match is found -- ``WatchlistScanner`` only ever
                scans one symbol per ``MarketAnalysisAgent.execute()``
                call, so that list normally holds exactly one entry).

        Returns:
            ``(trend, sentiment, valuation, quality)`` -- each either
            the real string value produced by its source Tool, or
            ``None`` when unavailable.
        """
        market_result = (
            agent_result.get("market") if isinstance(agent_result, dict) else None
        )
        output = getattr(market_result, "output", None)
        if not isinstance(output, dict):
            return None, None, None, None

        stocks = output.get("stocks")
        if not isinstance(stocks, list) or not stocks:
            return None, None, None, None

        entry = next(
            (s for s in stocks if isinstance(s, dict) and s.get("symbol") == symbol),
            None,
        )
        if entry is None and isinstance(stocks[0], dict):
            entry = stocks[0]
        if not isinstance(entry, dict):
            return None, None, None, None

        price = entry.get("price")
        trend = price.get("trend") if isinstance(price, dict) else None

        news = entry.get("news")
        sentiment = news.get("overall_sentiment") if isinstance(news, dict) else None

        fundamental = entry.get("fundamental")
        valuation = fundamental.get("valuation") if isinstance(fundamental, dict) else None
        quality = fundamental.get("quality") if isinstance(fundamental, dict) else None

        return trend, sentiment, valuation, quality

    def _score(
        self,
        recommendation: str,
        confidence: str,
        trend: Optional[str] = None,
        sentiment: Optional[str] = None,
        valuation: Optional[str] = None,
        quality: Optional[str] = None,
    ) -> Tuple[int, ScoreBreakdown]:
        """Deterministic score (and its breakdown) for one symbol,
        using this engine's ``RankingWeights``.

        ``recommendation``/``confidence`` (LOCKED formula, see module
        docstring, "Score source") remain the dominant term -- both
        inputs are guaranteed valid keys by
        ``_extract_valid_entries``'s own filtering, so no default or
        fallback is needed for them.

        ``trend``/``sentiment``/``valuation``/``quality`` (Activation
        2.9, additive) are looked up with ``dict.get(value, 0)``, not
        ``dict[value]`` -- unlike recommendation/confidence, these are
        NOT guaranteed to be valid keys (evidence may be entirely
        absent, or carry an ``"unknown"`` sentinel), so an
        unrecognized or ``None`` value contributes exactly ``0``,
        never a guessed default.
        """
        recommendation_weight = self._weights.recommendation_weight[recommendation]
        confidence_weight = self._weights.confidence_weight[confidence]

        recommendation_contribution = recommendation_weight * 10
        confidence_contribution = confidence_weight

        technical_contribution = self._weights.technical_weight.get(trend, 0)
        sentiment_contribution = self._weights.sentiment_weight.get(sentiment, 0)
        fundamental_valuation_contribution = self._weights.fundamental_valuation_weight.get(
            valuation, 0
        )
        fundamental_quality_contribution = self._weights.fundamental_quality_weight.get(
            quality, 0
        )

        breakdown = ScoreBreakdown(
            recommendation=recommendation,
            recommendation_weight=recommendation_weight,
            recommendation_contribution=recommendation_contribution,
            confidence=confidence,
            confidence_weight=confidence_weight,
            confidence_contribution=confidence_contribution,
            technical_trend=trend,
            technical_contribution=technical_contribution,
            sentiment=sentiment,
            sentiment_contribution=sentiment_contribution,
            fundamental_valuation=valuation,
            fundamental_valuation_contribution=fundamental_valuation_contribution,
            fundamental_quality=quality,
            fundamental_quality_contribution=fundamental_quality_contribution,
        )

        total_score = (
            recommendation_contribution
            + confidence_contribution
            + technical_contribution
            + sentiment_contribution
            + fundamental_valuation_contribution
            + fundamental_quality_contribution
        )

        return total_score, breakdown