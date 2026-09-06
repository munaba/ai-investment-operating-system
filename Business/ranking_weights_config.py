"""RankingWeights -- Activation 2.6 (LOCKED DECISION component),
extended by Activation 2.9 (Ranking Score Differentiation).

Single source of truth for the weight tables ``Business.
ranking_engine.RankingEngine`` uses to score a symbol. Extracted out
of ``RankingEngine`` itself so that changing a weight is a
*configuration* change, not a code change to ``RankingEngine`` --
this is the whole point of Activation 2.6's acceptance gate
("perubahan bobot mengubah hasil score tanpa mengubah kode
RankingEngine").

Scope discipline (Activation 2.6 audit, since narrowed by Activation
2.9 -- read both reports before touching this file): the Activation
2.6 audit found exactly one scoring formula in production, consuming
exactly two components -- ``recommendation`` and ``confidence``, both
read by ``RankingEngine`` from the ``"watchlist"`` SkillResult entry.
At that time, four further components (technical score, fundamental
score, sentiment score, quality) were confirmed NOT to exist anywhere
in the path ``RankingEngine`` read from, so this module did not
introduce them.

Activation 2.9 finding: that premise changed under this module's own
feet, without this module (or ``RankingEngine``) ever being updated
to match. Activation 2.4 ("Evidence Minimum") already made
``MarketAnalysisSkill`` forward each symbol's real price/news/
fundamental evidence -- ``trend``, ``overall_sentiment``,
``valuation``, ``quality`` -- into the ``"market"`` SkillResult entry
of ``WatchlistScanner.scan()``'s own return value, the exact
``scan_result`` ``RankingEngine.rank()`` already receives as its only
argument. ``RankingEngine`` simply never looked at that key -- it
read only ``"watchlist"``. That is the entire reason every symbol
that shares a (recommendation, confidence) bucket (which, empirically,
is most of a real IDX scan -- see ``AIOS_Activation2.9_Ranking_Score_
Differentiation_Report.md``) received byte-for-byte the same score:
the two-component formula had no other input to differ on, even
though differentiating evidence was sitting one dict-key away the
entire time. This is not the "jangan mengarang" violation Activation
2.6 was raised to prevent -- fabricating a value is inventing data a
source never produced; this is reading a value a source (Activation
2.4) has been producing all along.

Activation 2.9 therefore adds four more weight tables --
``technical_weight`` (keyed by price ``trend``), ``sentiment_weight``
(keyed by news ``overall_sentiment``), ``fundamental_valuation_weight``
and ``fundamental_quality_weight`` (each keyed by the fundamental
Tool's respective field) -- alongside the original two, unchanged.
Each new table's domain includes the real value set its source Tool
already documents to produce (see ``Orchestration.market_price_tool``,
``Orchestration.market_news_tool``, ``Orchestration.
market_fundamental_tool``); any value outside that domain (missing
evidence, a failed Tool call, an ``"unknown"`` value) contributes
exactly ``0`` -- looked up with ``dict.get(value, 0)``, never
``dict[value]`` -- so absent evidence is scored as neutral, never
guessed. Defaults are chosen so that a deployment with no
``RANKING_WEIGHT_*`` override still reproduces Activation 2.5's
recommendation/confidence-only score whenever the ``"market"`` entry
carries no usable evidence (e.g. every hermetic test fixture in this
codebase, none of which populates ``"market"``'s ``"price"``/
``"news"``/``"fundamental"`` keys) -- see ``Tests/
test_ranking_weights_config.py`` Scenario 3 for the exact contract
this preserves.

``recommendation_weight``/``confidence_weight`` and their formula
(``recommendation_weight * 10 + confidence_weight``, still the
LOCKED dominant term -- see ``Business.ranking_engine``'s own module
docstring) are completely unchanged by this Activation; the four new
tables are purely additive on top of that existing score, never a
replacement for it.

Values are read from environment variables via the existing
``Core.config.config`` singleton -- the same pattern
``Core.approval_config.build_approval_port`` and
``Database.database_config.DatabaseConfig.from_env`` already use in
this codebase, not a new configuration mechanism. Defaults exactly
reproduce Activation 2.5's original hardcoded values, so a deployment
that sets no ``RANKING_WEIGHT_*`` env var behaves byte-for-byte
identically to before this Activation (Acceptance Gate: "hasil
ranking sebelum dan sesudah refactor tetap identik").

This module intentionally does NOT read a database row, a JSON/YAML
file, or any other persisted store -- ``Core.config`` (``.env`` +
process environment) is this codebase's one existing configuration
mechanism, and Activation 2.6 asks for "satu lokasi kanonik", not a
second one alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from Core.config import config

#: Activation 2.5's original hardcoded values (see
#: ``Business.ranking_engine`` module docstring, "Score source") --
#: kept here, once, as the documented defaults. ``RankingEngine`` no
#: longer defines these itself.
_DEFAULT_RECOMMENDATION_WEIGHT: Dict[str, int] = {"BUY": 3, "WAIT": 2, "SELL": 1}
_DEFAULT_CONFIDENCE_WEIGHT: Dict[str, int] = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

#: Activation 2.9 defaults -- deliberately small relative to the
#: recommendation term's ``* 10`` multiplier, so evidence *breaks
#: ties and differentiates within* a (recommendation, confidence)
#: bucket without overturning that bucket's own ordering by default.
#: A deployment that wants evidence to dominate instead can still set
#: these arbitrarily large via env var -- nothing here is LOCKED
#: except the lookup being additive and defaulting to 0 for an
#: unrecognized/missing value.
_DEFAULT_TECHNICAL_WEIGHT: Dict[str, int] = {"bullish": 2, "neutral": 0, "bearish": -2}
_DEFAULT_SENTIMENT_WEIGHT: Dict[str, int] = {"positive": 2, "neutral": 0, "negative": -2}
_DEFAULT_FUNDAMENTAL_VALUATION_WEIGHT: Dict[str, int] = {
    "undervalued": 2,
    "fair": 0,
    "overvalued": -2,
}
_DEFAULT_FUNDAMENTAL_QUALITY_WEIGHT: Dict[str, int] = {"strong": 2, "weak": -2}

#: Fixed domains. These are *not* configurable -- they are the set of
#: values ``WatchlistAnalysisSkill`` is documented to produce, and
#: ``RankingEngine._extract_valid_entries`` uses exactly this key set
#: (regardless of the *weight* assigned to each key) to decide whether
#: a symbol's recommendation/confidence is recognized at all. Making
#: this set itself configurable would change failure-filtering
#: behaviour, which is explicitly out of scope for Activation 2.6
#: ("jangan mengubah algoritma analisis").
RECOMMENDATION_KEYS: Tuple[str, ...] = ("BUY", "WAIT", "SELL")
CONFIDENCE_KEYS: Tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")

#: Activation 2.9 domains -- the real value sets ``Orchestration.
#: market_price_tool``/``market_news_tool``/``market_fundamental_tool``
#: are already documented to produce (excluding each Tool's own
#: ``"unknown"`` sentinel, which -- like any other unrecognized value
#: -- is looked up with ``dict.get(value, 0)`` and contributes 0,
#: never guessed). Unlike ``RECOMMENDATION_KEYS``/``CONFIDENCE_KEYS``
#: these are not used as a failure gate anywhere -- evidence being
#: absent never excludes a symbol from ranking, it only withholds that
#: symbol's evidence-based score contribution.
TECHNICAL_KEYS: Tuple[str, ...] = ("bullish", "neutral", "bearish")
SENTIMENT_KEYS: Tuple[str, ...] = ("positive", "neutral", "negative")
FUNDAMENTAL_VALUATION_KEYS: Tuple[str, ...] = ("undervalued", "fair", "overvalued")
FUNDAMENTAL_QUALITY_KEYS: Tuple[str, ...] = ("strong", "weak")


@dataclass(frozen=True)
class RankingWeights:
    """The weight tables ``RankingEngine._score`` consumes.

    Immutable (``frozen=True``): a ``RankingWeights`` instance is a
    value snapshot handed to one ``RankingEngine`` at construction
    time, not a live, mutable settings object other code can reach in
    and change out from under an in-flight ``rank()`` call.

    Attributes:
        recommendation_weight: Maps ``"BUY"``/``"WAIT"``/``"SELL"`` to
            its configured integer weight.
        confidence_weight: Maps ``"HIGH"``/``"MEDIUM"``/``"LOW"`` to
            its configured integer weight.
        technical_weight: Maps price ``trend``
            (``"bullish"``/``"neutral"``/``"bearish"``) to its
            configured integer weight (Activation 2.9).
        sentiment_weight: Maps news ``overall_sentiment``
            (``"positive"``/``"neutral"``/``"negative"``) to its
            configured integer weight (Activation 2.9).
        fundamental_valuation_weight: Maps fundamental ``valuation``
            (``"undervalued"``/``"fair"``/``"overvalued"``) to its
            configured integer weight (Activation 2.9).
        fundamental_quality_weight: Maps fundamental ``quality``
            (``"strong"``/``"weak"``) to its configured integer
            weight (Activation 2.9).
    """

    recommendation_weight: Dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_RECOMMENDATION_WEIGHT)
    )
    confidence_weight: Dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_CONFIDENCE_WEIGHT)
    )
    technical_weight: Dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_TECHNICAL_WEIGHT)
    )
    sentiment_weight: Dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_SENTIMENT_WEIGHT)
    )
    fundamental_valuation_weight: Dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_FUNDAMENTAL_VALUATION_WEIGHT)
    )
    fundamental_quality_weight: Dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_FUNDAMENTAL_QUALITY_WEIGHT)
    )


def _read_weight_table(
    env_prefix: str,
    keys: Tuple[str, ...],
    defaults: Dict[str, int],
) -> Dict[str, int]:
    """Build one weight table from ``{env_prefix}_{KEY}`` env vars.

    Each key falls back *independently* to its default if its own env
    var is unset, so a deployment can override a single weight (e.g.
    only ``RANKING_WEIGHT_RECOMMENDATION_BUY``) without also having to
    set every other one. The env var name is always built from the
    *uppercased* key (``RECOMMENDATION_KEYS``/``CONFIDENCE_KEYS`` are
    already uppercase, so this is a no-op for them; the Activation 2.9
    tables' keys are lowercase, e.g. ``"bullish"`` ->
    ``RANKING_WEIGHT_TECHNICAL_BULLISH``).
    """
    return {
        key: config.get_int(f"{env_prefix}_{key.upper()}", defaults[key])
        for key in keys
    }


def load_ranking_weights() -> RankingWeights:
    """Load ``RankingWeights`` from environment configuration.

    This is the one canonical place ``RankingEngine`` (via its
    constructor default) and any operator/deployment reads/sets
    ranking weights from -- "satu lokasi kanonik" (Activation 2.6
    Ketentuan 3).

    Env vars read (all optional; each key falls back independently to
    its own default if unset):

        RANKING_WEIGHT_RECOMMENDATION_BUY          (default 3)
        RANKING_WEIGHT_RECOMMENDATION_WAIT         (default 2)
        RANKING_WEIGHT_RECOMMENDATION_SELL         (default 1)
        RANKING_WEIGHT_CONFIDENCE_HIGH             (default 3)
        RANKING_WEIGHT_CONFIDENCE_MEDIUM           (default 2)
        RANKING_WEIGHT_CONFIDENCE_LOW              (default 1)
        RANKING_WEIGHT_TECHNICAL_BULLISH           (default 2)   (Activation 2.9)
        RANKING_WEIGHT_TECHNICAL_NEUTRAL           (default 0)   (Activation 2.9)
        RANKING_WEIGHT_TECHNICAL_BEARISH           (default -2)  (Activation 2.9)
        RANKING_WEIGHT_SENTIMENT_POSITIVE          (default 2)   (Activation 2.9)
        RANKING_WEIGHT_SENTIMENT_NEUTRAL           (default 0)   (Activation 2.9)
        RANKING_WEIGHT_SENTIMENT_NEGATIVE          (default -2)  (Activation 2.9)
        RANKING_WEIGHT_FUNDAMENTAL_VALUATION_UNDERVALUED  (default 2)   (Activation 2.9)
        RANKING_WEIGHT_FUNDAMENTAL_VALUATION_FAIR         (default 0)   (Activation 2.9)
        RANKING_WEIGHT_FUNDAMENTAL_VALUATION_OVERVALUED   (default -2)  (Activation 2.9)
        RANKING_WEIGHT_FUNDAMENTAL_QUALITY_STRONG  (default 2)   (Activation 2.9)
        RANKING_WEIGHT_FUNDAMENTAL_QUALITY_WEAK    (default -2)  (Activation 2.9)

    Returns:
        A ``RankingWeights`` instance.

    Raises:
        ConfigurationError: propagated unchanged from
            ``Core.config.Config.get_int`` if one of the env vars
            above is set to a non-integer value.
    """
    return RankingWeights(
        recommendation_weight=_read_weight_table(
            "RANKING_WEIGHT_RECOMMENDATION",
            RECOMMENDATION_KEYS,
            _DEFAULT_RECOMMENDATION_WEIGHT,
        ),
        confidence_weight=_read_weight_table(
            "RANKING_WEIGHT_CONFIDENCE",
            CONFIDENCE_KEYS,
            _DEFAULT_CONFIDENCE_WEIGHT,
        ),
        technical_weight=_read_weight_table(
            "RANKING_WEIGHT_TECHNICAL",
            TECHNICAL_KEYS,
            _DEFAULT_TECHNICAL_WEIGHT,
        ),
        sentiment_weight=_read_weight_table(
            "RANKING_WEIGHT_SENTIMENT",
            SENTIMENT_KEYS,
            _DEFAULT_SENTIMENT_WEIGHT,
        ),
        fundamental_valuation_weight=_read_weight_table(
            "RANKING_WEIGHT_FUNDAMENTAL_VALUATION",
            FUNDAMENTAL_VALUATION_KEYS,
            _DEFAULT_FUNDAMENTAL_VALUATION_WEIGHT,
        ),
        fundamental_quality_weight=_read_weight_table(
            "RANKING_WEIGHT_FUNDAMENTAL_QUALITY",
            FUNDAMENTAL_QUALITY_KEYS,
            _DEFAULT_FUNDAMENTAL_QUALITY_WEIGHT,
        ),
    )