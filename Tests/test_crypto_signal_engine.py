"""Focused proof suite -- ``Business.crypto_signal_engine``.

Unit-level coverage of the LOCKED expanded crypto decision table in
isolation from ``Orchestration.crypto_analysis_skill.CryptoAnalysisSkill``.
Same global-counter-plus-``main()`` style as every other test file in
this project -- no pytest, no mocking framework.

Table under test:
    bullish + positive    -> BUY     / MEDIUM
    bullish + neutral     -> BUY     / LOW
    bearish + negative    -> SELL    / MEDIUM
    bearish + neutral     -> SELL    / LOW
    bullish + negative    -> UNKNOWN / LOW / "contradictory signal"
    bearish + positive    -> UNKNOWN / LOW / "contradictory signal"
    anything else          -> UNKNOWN / LOW / "insufficient data"

Run directly with ``python Tests/test_crypto_signal_engine.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Business.crypto_signal_engine import (
    CRYPTO_CONFIDENCE_KEYS,
    CRYPTO_RECOMMENDATION_KEYS,
    CryptoSignalDecision,
    evaluate_crypto_signal,
)

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(description)
    print(f"  {'PASS' if condition else 'FAIL'} - {description}")


def scenario_buy_rows():
    print("\n[BUY] bullish + positive/neutral")
    d1 = evaluate_crypto_signal("bullish", "positive")
    check(isinstance(d1, CryptoSignalDecision), "returns a CryptoSignalDecision")
    check(d1.recommendation == "BUY", "bullish+positive -> BUY")
    check(d1.confidence == "MEDIUM", "bullish+positive -> MEDIUM confidence")
    check(d1.reason == "bullish price, positive news", "bullish+positive -> fixed reason string")

    d2 = evaluate_crypto_signal("bullish", "neutral")
    check(d2.recommendation == "BUY", "bullish+neutral -> BUY")
    check(d2.confidence == "LOW", "bullish+neutral -> LOW confidence (weaker than exact agreement)")
    check(d2.reason == "bullish price, neutral news", "bullish+neutral -> fixed reason string")


def scenario_sell_rows():
    print("\n[SELL] bearish + negative/neutral")
    d1 = evaluate_crypto_signal("bearish", "negative")
    check(d1.recommendation == "SELL", "bearish+negative -> SELL")
    check(d1.confidence == "MEDIUM", "bearish+negative -> MEDIUM confidence")
    check(d1.reason == "bearish price, negative news", "bearish+negative -> fixed reason string")

    d2 = evaluate_crypto_signal("bearish", "neutral")
    check(d2.recommendation == "SELL", "bearish+neutral -> SELL")
    check(d2.confidence == "LOW", "bearish+neutral -> LOW confidence (weaker than exact agreement)")
    check(d2.reason == "bearish price, neutral news", "bearish+neutral -> fixed reason string")


def scenario_contradictory_rows():
    print("\n[UNKNOWN] contradictory sentiment")
    d1 = evaluate_crypto_signal("bullish", "negative")
    check(d1.recommendation == "UNKNOWN", "bullish+negative (contradictory) -> UNKNOWN, not BUY")
    check(d1.confidence == "LOW", "bullish+negative -> LOW confidence")
    check(d1.reason == "contradictory signal", "bullish+negative -> reason == contradictory signal")

    d2 = evaluate_crypto_signal("bearish", "positive")
    check(d2.recommendation == "UNKNOWN", "bearish+positive (contradictory) -> UNKNOWN, not SELL")
    check(d2.confidence == "LOW", "bearish+positive -> LOW confidence")
    check(d2.reason == "contradictory signal", "bearish+positive -> reason == contradictory signal")


def scenario_insufficient_data_rows():
    print("\n[UNKNOWN] insufficient data (non-directional or unrecognized price trend)")
    trends = ["neutral", None, "", "garbage"]
    sentiments = ["positive", "negative", "neutral", None, "", "garbage"]
    all_ok = True
    combinations_checked = 0
    for trend in trends:
        for sentiment in sentiments:
            combinations_checked += 1
            decision = evaluate_crypto_signal(trend, sentiment)
            if not (
                decision.recommendation == "UNKNOWN"
                and decision.confidence == "LOW"
                and decision.reason == "insufficient data"
            ):
                all_ok = False
    check(combinations_checked > 0, "sanity: at least one non-directional combination was actually checked")
    check(all_ok, "any non-bullish/bearish price_trend -> UNKNOWN/LOW/insufficient data regardless of sentiment")

    # A directional trend paired with an unrecognized sentiment also
    # falls through to insufficient data, not a locked BUY/SELL row.
    d1 = evaluate_crypto_signal("bullish", "garbage")
    check(d1.reason == "insufficient data", "bullish + unrecognized sentiment -> insufficient data, not BUY")
    d2 = evaluate_crypto_signal("bearish", None)
    check(d2.reason == "insufficient data", "bearish + missing sentiment -> insufficient data, not SELL")


def scenario_no_guessing():
    print("\n[No guessing] case is never normalized")
    decision = evaluate_crypto_signal("Bullish", "Positive")
    check(decision.recommendation == "UNKNOWN", "case is never normalized (Bullish != bullish)")
    check(decision.reason == "insufficient data", "unrecognized-case trend -> insufficient data")


def scenario_purity():
    print("\n[Purity] repeated calls with the same inputs are stable and independent")
    d1 = evaluate_crypto_signal("bullish", "positive")
    d2 = evaluate_crypto_signal("bullish", "positive")
    check(d1 is not d2, "each call returns a fresh CryptoSignalDecision instance")
    check(
        (d1.recommendation, d1.confidence, d1.reason) == (d2.recommendation, d2.confidence, d2.reason),
        "repeated calls with identical inputs produce identical output",
    )


def scenario_vocabulary_constants():
    print("\n[Vocabulary] exported key constants unchanged by the expansion")
    check(set(CRYPTO_RECOMMENDATION_KEYS) == {"BUY", "SELL", "UNKNOWN"}, "CRYPTO_RECOMMENDATION_KEYS == {BUY, SELL, UNKNOWN}")
    check("WAIT" not in CRYPTO_RECOMMENDATION_KEYS, "WAIT is never a crypto outcome (stock-only, needs fundamentals)")
    check(set(CRYPTO_CONFIDENCE_KEYS) == {"MEDIUM", "LOW"}, "CRYPTO_CONFIDENCE_KEYS == {MEDIUM, LOW}")
    check("HIGH" not in CRYPTO_CONFIDENCE_KEYS, "HIGH is never a crypto confidence (reserved for 3-input stock agreement)")


def main() -> int:
    scenario_buy_rows()
    scenario_sell_rows()
    scenario_contradictory_rows()
    scenario_insufficient_data_rows()
    scenario_no_guessing()
    scenario_purity()
    scenario_vocabulary_constants()

    print("\n" + "=" * 60)
    print(f"CRYPTO-SIGNAL-ENGINE RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())