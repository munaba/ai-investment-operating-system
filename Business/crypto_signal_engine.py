"""crypto_signal_engine -- Activation 7 Crypto Validation Profile.

The crypto counterpart to the deterministic decision table already
inlined in ``Orchestration.text_analysis_skill.TextAnalysisSkill``.
Unlike that stock table (LOCKED four-row: price + news + fundamental),
crypto has no fundamental-valuation input at all, so this module
implements a separate, LOCKED table over exactly two inputs -- price
trend and news sentiment:

    bullish + positive -> BUY     / MEDIUM
    bullish + neutral   -> BUY     / LOW
    bearish + negative  -> SELL    / MEDIUM
    bearish + neutral   -> SELL    / LOW
    bullish + negative  -> UNKNOWN / LOW / "contradictory signal"
    bearish + positive  -> UNKNOWN / LOW / "contradictory signal"
    anything else        -> UNKNOWN / LOW / "insufficient data"

"Anything else" covers a ``price_trend`` that is itself not
``"bullish"``/``"bearish"`` (e.g. ``"neutral"``, ``None``, or an
unrecognized string), regardless of ``news_sentiment`` -- price trend
is the primary signal here, and news only confirms, softens, or
contradicts it once a directional trend exists.

This mirrors the stock table's own style (a flat, literal
``if``/``elif``/``else`` chain, no dynamic dispatch, no guessing or
inferring of missing/unrecognized values) but is a genuinely separate
table -- crypto never claims ``"HIGH"`` confidence, because it is
missing one of the three inputs (fundamentals) the stock table's own
``"HIGH"`` rows require.

Public API (LOCKED): a single pure function, ``evaluate_crypto_signal()``,
plus the ``CryptoSignalDecision`` dataclass it returns and two
vocabulary constants, ``CRYPTO_RECOMMENDATION_KEYS`` and
``CRYPTO_CONFIDENCE_KEYS``, documenting the fixed set of values this
table can ever produce. No class, no state, no dependency on any
Tool, Skill, or repository -- this module is called directly by
``Orchestration.crypto_analysis_skill.CryptoAnalysisSkill`` with
already-extracted ``price_trend``/``news_sentiment`` strings (or
``None``) and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fixed vocabulary this table can ever produce (LOCKED). Crypto never
# produces "WAIT" (that is a stock-only outcome requiring a third,
# fundamental input this profile does not have) and never produces
# "HIGH" confidence (reserved, on the stock table, for the
# all-three-inputs-agree rows).
CRYPTO_RECOMMENDATION_KEYS = ("BUY", "SELL", "UNKNOWN")
CRYPTO_CONFIDENCE_KEYS = ("MEDIUM", "LOW")


@dataclass
class CryptoSignalDecision:
    """The single decision this table produces.

    Attributes:
        recommendation: One of ``CRYPTO_RECOMMENDATION_KEYS``.
        confidence: One of ``CRYPTO_CONFIDENCE_KEYS``.
        reason: One of the fixed, LOCKED reason strings the table
            below produces -- always exactly one of
            ``"bullish price, positive news"``,
            ``"bullish price, neutral news"``,
            ``"bearish price, negative news"``,
            ``"bearish price, neutral news"``,
            ``"contradictory signal"``, or ``"insufficient data"``.
    """

    recommendation: str
    confidence: str
    reason: str


def evaluate_crypto_signal(price_trend: object, news_sentiment: object) -> CryptoSignalDecision:
    """Apply the LOCKED crypto decision table.

    No value is guessed, inferred, or defaulted: any unrecognized or
    missing (``None``) ``price_trend`` (i.e. not exactly ``"bullish"``
    or ``"bearish"``) falls straight through to the ``"insufficient
    data"`` row, exactly like the stock table's own fallback. A
    directional ``price_trend`` paired with the opposite-direction
    ``news_sentiment`` is treated as a genuine contradiction, not a
    lack of data, and is reported as such.

    Args:
        price_trend: Expected to be ``"bullish"``, ``"bearish"``, or
            some other/missing value. Compared with ``==`` only --
            never coerced, normalized, or case-folded.
        news_sentiment: Expected to be ``"positive"``, ``"negative"``,
            ``"neutral"``, or some other/missing value. Compared with
            ``==`` only.

    Returns:
        A :class:`CryptoSignalDecision`:

        * ``price_trend == "bullish"`` and ``news_sentiment ==
          "positive"`` -> ``BUY`` / ``MEDIUM`` / ``"bullish price,
          positive news"``.
        * ``price_trend == "bullish"`` and ``news_sentiment ==
          "neutral"`` -> ``BUY`` / ``LOW`` / ``"bullish price, neutral
          news"``.
        * ``price_trend == "bearish"`` and ``news_sentiment ==
          "negative"`` -> ``SELL`` / ``MEDIUM`` / ``"bearish price,
          negative news"``.
        * ``price_trend == "bearish"`` and ``news_sentiment ==
          "neutral"`` -> ``SELL`` / ``LOW`` / ``"bearish price,
          neutral news"``.
        * ``price_trend == "bullish"`` and ``news_sentiment ==
          "negative"``, or ``price_trend == "bearish"`` and
          ``news_sentiment == "positive"`` (contradictory) ->
          ``UNKNOWN`` / ``LOW`` / ``"contradictory signal"``.
        * Every other combination (``price_trend`` not exactly
          ``"bullish"``/``"bearish"``, including ``None`` or an
          unrecognized string) -> ``UNKNOWN`` / ``LOW`` /
          ``"insufficient data"``.
    """
    if price_trend == "bullish" and news_sentiment == "positive":
        return CryptoSignalDecision(
            recommendation="BUY",
            confidence="MEDIUM",
            reason="bullish price, positive news",
        )

    if price_trend == "bullish" and news_sentiment == "neutral":
        return CryptoSignalDecision(
            recommendation="BUY",
            confidence="LOW",
            reason="bullish price, neutral news",
        )

    if price_trend == "bearish" and news_sentiment == "negative":
        return CryptoSignalDecision(
            recommendation="SELL",
            confidence="MEDIUM",
            reason="bearish price, negative news",
        )

    if price_trend == "bearish" and news_sentiment == "neutral":
        return CryptoSignalDecision(
            recommendation="SELL",
            confidence="LOW",
            reason="bearish price, neutral news",
        )

    if price_trend == "bullish" and news_sentiment == "negative":
        return CryptoSignalDecision(
            recommendation="UNKNOWN",
            confidence="LOW",
            reason="contradictory signal",
        )

    if price_trend == "bearish" and news_sentiment == "positive":
        return CryptoSignalDecision(
            recommendation="UNKNOWN",
            confidence="LOW",
            reason="contradictory signal",
        )

    return CryptoSignalDecision(
        recommendation="UNKNOWN",
        confidence="LOW",
        reason="insufficient data",
    )