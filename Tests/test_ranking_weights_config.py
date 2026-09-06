"""
Activation 2.6 proof suite -- RankingEngine weight configurability
and score transparency.

Scope (per Activation 2.6's Acceptance Gate):

  1. Hasil ranking sebelum dan sesudah refactor tetap identik --
     ``RankingEngine()`` (no argument, default weights) reproduces
     Activation 2.5's exact scores/order for the same input.
  2. Bobot tidak lagi hardcode di ``RankingEngine`` -- weights live in
     ``Business.ranking_weights_config.RankingWeights``, not as
     module-level constants in ``Business.ranking_engine``.
  3. Perubahan bobot mengubah hasil score tanpa mengubah kode
     ``RankingEngine`` -- injecting a different ``RankingWeights``
     changes ``score`` (and can change ordering), no
     ``Business/ranking_engine.py`` edit required.
  4. Setiap hasil ranking memiliki breakdown yang menjelaskan asal
     score -- every ``RankedSymbol.score_breakdown`` explains
     ``score`` exactly, using only components actually read
     (``recommendation``/``confidence``), no fabricated component.
  5. Tidak ada perubahan pada algoritma analisis maupun urutan
     ranking selain akibat perubahan bobot -- failure filtering,
     sort stability, and rank assignment are unchanged.
  6. Env-var loading (``load_ranking_weights()``): defaults match
     Activation 2.5 exactly; per-key override works; unrelated keys
     stay at their default when only one is overridden.

Uses hand-built ``SkillResult`` fixtures, same shape as
``Tests/test_ranking_engine.py`` -- no real ``WatchlistScanner``,
database, or Tool involved. Purely hermetic, no I/O.

Run directly: ``python Tests/test_ranking_weights_config.py``
-- no external test framework required, matching every other
``Tests/test_*.py`` file in this project.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Business.ranking_engine import RankingEngine, ScoreBreakdown  # noqa: E402
from Business.ranking_weights_config import (  # noqa: E402
    RankingWeights,
    load_ranking_weights,
)
from Core.config import config  # noqa: E402
from Orchestration.skill_result import SkillResult  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []

_ENV_KEYS = (
    "RANKING_WEIGHT_RECOMMENDATION_BUY",
    "RANKING_WEIGHT_RECOMMENDATION_WAIT",
    "RANKING_WEIGHT_RECOMMENDATION_SELL",
    "RANKING_WEIGHT_CONFIDENCE_HIGH",
    "RANKING_WEIGHT_CONFIDENCE_MEDIUM",
    "RANKING_WEIGHT_CONFIDENCE_LOW",
)


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


def _clear_env() -> Dict[str, Optional[str]]:
    """Remove all RANKING_WEIGHT_* env vars, returning the previous
    values so the caller can restore them afterwards."""
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    return previous


def _restore_env(previous: Dict[str, Optional[str]]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _watchlist_success(
    symbol: str,
    recommendation: str,
    confidence: str,
    priority: int,
) -> SkillResult:
    return SkillResult(
        success=True,
        output={
            "watchlist": [
                {
                    "priority": priority,
                    "symbol": symbol,
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "summary": None,
                }
            ]
        },
        error=None,
        metadata={},
    )


def _agent_result(
    symbol: str,
    recommendation: str,
    confidence: str,
    priority: int,
) -> Dict[str, SkillResult]:
    return {
        "market": SkillResult(success=False, output=None, error="missing resolver", metadata={}),
        "watchlist": _watchlist_success(symbol, recommendation, confidence, priority),
    }


def scenario_weights_not_hardcoded_in_ranking_engine_module() -> None:
    print("\n[Scenario 1] weights are not module-level constants in ranking_engine.py")
    import Business.ranking_engine as ranking_engine_module

    check(
        not hasattr(ranking_engine_module, "RECOMMENDATION_WEIGHT"),
        "Business.ranking_engine no longer defines a module-level RECOMMENDATION_WEIGHT",
    )
    check(
        not hasattr(ranking_engine_module, "CONFIDENCE_WEIGHT"),
        "Business.ranking_engine no longer defines a module-level CONFIDENCE_WEIGHT",
    )
    check(
        hasattr(ranking_engine_module, "RankingWeights"),
        "Business.ranking_engine imports RankingWeights from the canonical config module (re-exported by import)",
    )


def scenario_default_weights_match_activation_2_5_exactly() -> None:
    print("\n[Scenario 2] default RankingWeights reproduce Activation 2.5's original hardcoded values")
    previous = _clear_env()
    try:
        weights = load_ranking_weights()
        check(
            weights.recommendation_weight == {"BUY": 3, "WAIT": 2, "SELL": 1},
            "default recommendation_weight == Activation 2.5's {'BUY':3,'WAIT':2,'SELL':1}",
        )
        check(
            weights.confidence_weight == {"HIGH": 3, "MEDIUM": 2, "LOW": 1},
            "default confidence_weight == Activation 2.5's {'HIGH':3,'MEDIUM':2,'LOW':1}",
        )
    finally:
        _restore_env(previous)


def scenario_unconfigured_ranking_identical_to_activation_2_5() -> None:
    print("\n[Scenario 3] hasil ranking sebelum/sesudah refactor tetap identik (no env override)")
    previous = _clear_env()
    try:
        engine = RankingEngine()  # no argument -- same call site as before
        scan_result = {
            "BBCA": _agent_result("BBCA", "SELL", "LOW", 1),
            "TLKM": _agent_result("TLKM", "BUY", "HIGH", 1),
            "ASII": _agent_result("ASII", "WAIT", "MEDIUM", 1),
        }
        result = engine.rank(scan_result)
        by_symbol = {r.symbol: r for r in result}

        # Activation 2.5's exact formula: weight[rec]*10 + weight[conf]
        check(by_symbol["TLKM"].score == 3 * 10 + 3, "TLKM (BUY/HIGH) score == 33, exactly Activation 2.5's formula")
        check(by_symbol["ASII"].score == 2 * 10 + 2, "ASII (WAIT/MEDIUM) score == 22, exactly Activation 2.5's formula")
        check(by_symbol["BBCA"].score == 1 * 10 + 1, "BBCA (SELL/LOW) score == 11, exactly Activation 2.5's formula")
        check(
            [r.symbol for r in result] == ["TLKM", "ASII", "BBCA"],
            "ranking order identical to Activation 2.5 (TLKM > ASII > BBCA)",
        )
        check([r.rank for r in result] == [1, 2, 3], "rank assignment identical to Activation 2.5 (1,2,3)")
    finally:
        _restore_env(previous)


def scenario_changing_weights_changes_score_without_editing_ranking_engine() -> None:
    print("\n[Scenario 4] perubahan bobot mengubah score tanpa mengubah kode RankingEngine")
    default_weights_score = RankingEngine().rank(
        {"X": _agent_result("X", "BUY", "LOW", 1)}
    )[0].score

    custom_weights = RankingWeights(
        recommendation_weight={"BUY": 100, "WAIT": 50, "SELL": 1},
        confidence_weight={"HIGH": 3, "MEDIUM": 2, "LOW": 1},
    )
    engine = RankingEngine(weights=custom_weights)  # constructor argument only -- no source edit
    result = engine.rank({"X": _agent_result("X", "BUY", "LOW", 1)})

    check(result[0].score == 100 * 10 + 1, "custom RankingWeights changes the resulting score (1001)")
    check(
        result[0].score != default_weights_score,
        "custom-weight score differs from default-weight score for the same (recommendation, confidence)",
    )


def scenario_changing_weights_can_reorder_ranking() -> None:
    print("\n[Scenario 5] a weight change can flip ordering, purely via configuration")
    scan_result = {
        "SELL_HIGH_CONF": _agent_result("SELL_HIGH_CONF", "SELL", "HIGH", 1),
        "WAIT_LOW_CONF": _agent_result("WAIT_LOW_CONF", "WAIT", "LOW", 1),
    }

    default_result = RankingEngine().rank(scan_result)
    check(
        [r.symbol for r in default_result] == ["WAIT_LOW_CONF", "SELL_HIGH_CONF"],
        "with default weights, WAIT beats SELL regardless of confidence",
    )

    # A configuration that makes SELL's per-point weight dominate WAIT's.
    inverted_weights = RankingWeights(
        recommendation_weight={"BUY": 3, "WAIT": 1, "SELL": 5},
        confidence_weight={"HIGH": 3, "MEDIUM": 2, "LOW": 1},
    )
    inverted_result = RankingEngine(weights=inverted_weights).rank(scan_result)
    check(
        [r.symbol for r in inverted_result] == ["SELL_HIGH_CONF", "WAIT_LOW_CONF"],
        "with a different RankingWeights config, ordering changes -- no RankingEngine code touched",
    )


def scenario_score_breakdown_present_and_explains_score() -> None:
    print("\n[Scenario 6] setiap hasil ranking memiliki breakdown yang menjelaskan asal score")
    engine = RankingEngine()
    result = engine.rank({"BBCA": _agent_result("BBCA", "BUY", "HIGH", 1)})
    ranked = result[0]

    check(isinstance(ranked.score_breakdown, ScoreBreakdown), "RankedSymbol.score_breakdown is a ScoreBreakdown instance")
    check(ranked.score_breakdown.recommendation == "BUY", "breakdown.recommendation matches the symbol's recommendation")
    check(ranked.score_breakdown.confidence == "HIGH", "breakdown.confidence matches the symbol's confidence")
    check(
        ranked.score_breakdown.recommendation_contribution
        + ranked.score_breakdown.confidence_contribution
        == ranked.score,
        "breakdown's two contributions sum exactly to RankedSymbol.score",
    )
    check(
        ranked.score_breakdown.recommendation_contribution == ranked.score_breakdown.recommendation_weight * 10,
        "recommendation_contribution == recommendation_weight * 10 (the LOCKED formula's weight term)",
    )
    check(
        ranked.score_breakdown.confidence_contribution == ranked.score_breakdown.confidence_weight,
        "confidence_contribution == confidence_weight (the LOCKED formula's confidence term)",
    )


def scenario_breakdown_has_no_fabricated_components() -> None:
    print("\n[Scenario 7] no fabricated component in ScoreBreakdown (technical/fundamental/sentiment/risk/completeness)")
    breakdown_fields = set(ScoreBreakdown.__dataclass_fields__.keys())
    forbidden = {
        "technical_score",
        "fundamental_score",
        "sentiment_score",
        "risk_penalty",
        "data_completeness_penalty",
    }
    check(
        breakdown_fields.isdisjoint(forbidden),
        f"ScoreBreakdown fields {sorted(breakdown_fields)} contain none of the unavailable components {sorted(forbidden)}",
    )


def scenario_env_var_override_changes_default_weights() -> None:
    print("\n[Scenario 8] RANKING_WEIGHT_* env vars override individual weights, others keep their default")
    previous = _clear_env()
    try:
        os.environ["RANKING_WEIGHT_RECOMMENDATION_BUY"] = "9"
        config.reload()
        weights = load_ranking_weights()

        check(weights.recommendation_weight["BUY"] == 9, "RANKING_WEIGHT_RECOMMENDATION_BUY=9 overrides just BUY's weight")
        check(weights.recommendation_weight["WAIT"] == 2, "WAIT keeps its Activation 2.5 default (2) when unset")
        check(weights.recommendation_weight["SELL"] == 1, "SELL keeps its Activation 2.5 default (1) when unset")
        check(weights.confidence_weight == {"HIGH": 3, "MEDIUM": 2, "LOW": 1}, "confidence_weight entirely unaffected by a recommendation-only override")
    finally:
        _restore_env(previous)
        config.reload()


def scenario_failure_filtering_and_sort_stability_unchanged() -> None:
    print("\n[Scenario 9] tidak ada perubahan pada failure filtering / sort stability selain akibat bobot")
    engine = RankingEngine()
    failed = SkillResult(success=False, output=None, error="boom", metadata={})
    scan_result = {
        "BBCA": {"market": SkillResult(success=False, output=None, error=None, metadata={}), "watchlist": failed},
        "TLKM": _agent_result("TLKM", "BUY", "HIGH", 1),
        "ASII": _agent_result("ASII", "BUY", "HIGH", 1),  # same score as TLKM -- tie
    }

    result = engine.rank(scan_result)

    check(len(result) == 2, "failed 'watchlist' symbol is still excluded (unchanged behavior)")
    check(
        [r.symbol for r in result] == ["TLKM", "ASII"],
        "tied scores still preserve original scan_result order (stable sort unchanged)",
    )


def main() -> int:
    scenarios = [
        scenario_weights_not_hardcoded_in_ranking_engine_module,
        scenario_default_weights_match_activation_2_5_exactly,
        scenario_unconfigured_ranking_identical_to_activation_2_5,
        scenario_changing_weights_changes_score_without_editing_ranking_engine,
        scenario_changing_weights_can_reorder_ranking,
        scenario_score_breakdown_present_and_explains_score,
        scenario_breakdown_has_no_fabricated_components,
        scenario_env_var_override_changes_default_weights,
        scenario_failure_filtering_and_sort_stability_unchanged,
    ]
    for scenario in scenarios:
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 2.6 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
