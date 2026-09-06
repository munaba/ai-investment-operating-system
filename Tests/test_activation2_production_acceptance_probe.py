"""Activation 2 production acceptance probe.

Read-only diagnostic: searches a broad IDX universe using the existing
real market-data helpers, applies the LOCKED TextAnalysis decision table,
and shows candidates that can actually produce BUY/SELL/WAIT.

This probe does not modify production logic, the watchlist, or the DB.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Orchestration.market_fundamental_tool import _fetch_real_fundamentals
from Orchestration.market_news_tool import _classify_headline, _fetch_real_headlines
from Orchestration.market_price_tool import _fetch_real_prices

IDX_UNIVERSE = (
    "BBCA BMRI BBRI BRIS BBNI BNGA BBTN BBKP NISP PNBN MEGA BTPS TLKM EXCL ISAT TOWR "
    "ASII UNTR AUTO ICBP INDF MYOR AMRT JPFA CPIN MAIN KLBF SIDO GGRM HMSP "
    "ANTM MDKA INCO TINS PTBA ITMG ADRO PGAS AKRA MEDC ELSA "
    "SMGR INTP PTPP WIKA WSKT ADHI "
    "UNVR ACES ERAA MAPI HRUM "
    "BSDE CTRA PWON "
).split()


def _overall_sentiment(headlines: Iterable[str]) -> tuple[str, int]:
    labels = [_classify_headline(h)[0] for h in headlines]
    positive = labels.count("positive")
    negative = labels.count("negative")
    neutral = labels.count("neutral")
    if positive > negative and positive > neutral:
        return "positive", positive - negative
    if negative > positive and negative > neutral:
        return "negative", positive - negative
    return "neutral", positive - negative


def _decision(trend: str, sentiment: str, valuation: str) -> tuple[str, str] | None:
    """Mirrors the Activation 2 analysis-logic fix now used by
    ``Orchestration.text_analysis_skill.TextAnalysisSkill.execute()``:
    a deterministic bullish/bearish/neutral vote count across the
    three real signals, instead of the old exact 4-row lookup that
    left every ordinary "fair"/agreeing-trend-and-sentiment case (and
    every neutral value) unrecognized. Returns ``None`` only when one
    of the three inputs is not a recognized value at all (missing or
    invalid critical evidence) -- callers already guard against that
    via the ``current``/``previous``/``pe`` ``None`` checks above.
    """
    axis = {
        "bullish": "bullish", "bearish": "bearish", "neutral": "neutral",
        "positive": "bullish", "negative": "bearish",
        "undervalued": "bullish", "overvalued": "bearish", "fair": "neutral",
    }
    if trend not in axis or sentiment not in axis or valuation not in axis:
        return None
    signals = (axis[trend], axis[sentiment], axis[valuation])
    bulls = signals.count("bullish")
    bears = signals.count("bearish")
    if bulls >= 2 and bears == 0:
        return "BUY", "HIGH" if bulls == 3 else "MEDIUM"
    if bears >= 2 and bulls == 0:
        return "SELL", "HIGH" if bears == 3 else "MEDIUM"
    return "WAIT", "MEDIUM" if bulls and bears else "LOW"


def main() -> int:
    matches = []
    checked = 0
    for symbol in IDX_UNIVERSE:
        try:
            current, previous = _fetch_real_prices(symbol)
            pe, _roe = _fetch_real_fundamentals(symbol)
            headlines = _fetch_real_headlines(symbol)
            checked += 1
            if current is None or previous is None or pe is None:
                continue
            if current > previous:
                trend = "bullish"
            elif current < previous:
                trend = "bearish"
            else:
                trend = "neutral"
            if pe < 15:
                valuation = "undervalued"
            elif pe <= 25:
                valuation = "fair"
            else:
                valuation = "overvalued"
            sentiment, sentiment_score = _overall_sentiment(headlines)
            decision = _decision(trend, sentiment, valuation)
            if decision is None:
                continue
            recommendation, confidence = decision
            score = {"BUY": 3, "WAIT": 2, "SELL": 1}[recommendation] + {
                "HIGH": 3, "MEDIUM": 2, "LOW": 1
            }[confidence]
            matches.append((symbol, recommendation, confidence, score, current, previous, pe, sentiment, sentiment_score))
        except Exception as exc:  # diagnostic probe; keep scanning
            print(f"ERROR {symbol}: {exc}")

    matches.sort(key=lambda row: (-row[3], row[0]))
    print(f"Checked: {checked} | Matches: {len(matches)}")
    print("symbol recommendation confidence score trend sentiment valuation")
    for rank, row in enumerate(matches, start=1):
        symbol, recommendation, confidence, score, current, previous, pe, sentiment, sentiment_score = row
        trend = "bullish" if current > previous else "bearish" if current < previous else "neutral"
        valuation = "undervalued" if pe < 15 else "fair" if pe <= 25 else "overvalued"
        print(f"{rank:>2} {symbol:<6} {recommendation:<14} {confidence:<10} {score:<5} {trend:<8} {sentiment:<9} {valuation:<12} sentiment_score={sentiment_score}")

    if len(matches) >= 3:
        print("ACCEPTANCE PROBE: PASS (>=3 real production candidates)")
        return 0
    print("ACCEPTANCE PROBE: BLOCKED (<3 real production candidates)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())