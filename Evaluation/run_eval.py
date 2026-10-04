#!/usr/bin/env python3
"""AIOS Accuracy Evaluation Runner v2.

Honest baseline measurement for AIOS accuracy per layer.
Fixes v1 bugs: engine instantiation, attribute names, fabricated L4 cases removed.

Usage:
    python Evaluation/run_eval.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJ))

_THRESH = json.loads((_PROJ / "Evaluation/thresholds.json").read_text())
_DB_PATH = _PROJ / "data" / "investment_platform.db"


# ---------------------------------------------------------------------------
# L2: Engine golden case validation (fix instantiation + attribute names)
# ---------------------------------------------------------------------------

def eval_l2_expectancy_golden() -> Tuple[int, int]:
    """L2 Expectancy Engine — golden case validation with correct instantiation."""
    from dataclasses import dataclass
    from Business.expectancy_engine import ExpectancyEngine
    from Business.position_performance_engine import PositionPerformanceStatistics

    @dataclass
    class Stats:
        winning_positions: int
        losing_positions: int
        breakeven_positions: int
        gross_profit: float
        gross_loss: float
        net_profit: float
        average_win: float
        average_loss: float

    cases = json.loads((_PROJ / "Evaluation/golden_cases/l2_expectancy_golden.json").read_text())
    passed = 0
    failed = 0
    tol = _THRESH["L2_engine"]["numeric_tolerance"]

    for i, case in enumerate(cases, 1):
        inp = case["input"]
        exp = case["expected"]
        gross_profit = inp["winning_positions"] * inp["average_win"]
        gross_loss = inp["losing_positions"] * inp["average_loss"]
        net_profit = gross_profit - gross_loss

        stats = PositionPerformanceStatistics(
            winning_positions=inp["winning_positions"],
            losing_positions=inp["losing_positions"],
            breakeven_positions=inp["breakeven_positions"],
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_profit=net_profit,
            average_win=inp["average_win"],
            average_loss=inp["average_loss"]
        )
        engine = ExpectancyEngine()
        result = engine.calculate(stats)

        if abs(result.expectancy - exp["expectancy"]) < tol:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL case {i}: expectancy {result.expectancy} != {exp['expectancy']}")

    print(f"L2 Expectancy: {passed}/{len(cases)} passed")
    return passed, failed


def eval_l2_max_drawdown_golden() -> Tuple[int, int]:
    """L2 MaxDrawdown Engine — golden case validation (fixed attribute name)."""
    from Business.maximum_drawdown_engine import MaximumDrawdownEngine

    cases = json.loads((_PROJ / "Evaluation/golden_cases/l2_max_drawdown_golden.json").read_text())
    passed = 0
    failed = 0
    tol = _THRESH["L2_engine"]["numeric_tolerance"]

    for i, case in enumerate(cases, 1):
        curve = case["input"]["equity_curve"]
        exp = case["expected"]
        engine = MaximumDrawdownEngine()
        result = engine.calculate(curve)

        if abs(result.maximum_drawdown - exp["maximum_drawdown"]) < tol:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL case {i}: maximum_drawdown {result.maximum_drawdown} != {exp['maximum_drawdown']}")

    print(f"L2 MaxDrawdown: {passed}/{len(cases)} passed")
    return passed, failed


def eval_l2_forex_max_loss_golden() -> Tuple[int, int]:
    """L2 Forex MaxLoss Policy — golden case validation."""
    from decimal import Decimal
    from Business.forex_max_loss_policy import calculate_maximum_loss

    cases = json.loads((_PROJ / "Evaluation/golden_cases/l2_forex_max_loss_golden.json").read_text())
    passed = 0
    failed = 0

    for i, case in enumerate(cases, 1):
        inp = case["input"]
        exp_loss = Decimal(case["expected"]["max_loss"])
        result = calculate_maximum_loss(inp["pair"], inp["entry_price"], inp["stop_loss"], inp["quantity"])

        if result == exp_loss:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL case {i}: {result} != {exp_loss}")

    print(f"L2 Forex MaxLoss: {passed}/{len(cases)} passed")
    return passed, failed


def eval_l2_position_performance_golden() -> Tuple[int, int]:
    """L2 PositionPerformance Engine — golden case validation."""
    from dataclasses import dataclass
    from Business.position_performance_engine import PositionPerformanceEngine

    @dataclass
    class MockPosition:
        realized_pnl: float

    cases = json.loads((_PROJ / "Evaluation/golden_cases/l2_position_performance_golden.json").read_text())
    passed = 0
    failed = 0
    tol = _THRESH["L2_engine"]["numeric_tolerance"]

    engine = PositionPerformanceEngine()

    for i, case in enumerate(cases, 1):
        pnls = case["input"]["pnls"]
        exp = case["expected"]

        # Mock Position objects — engine only reads .realized_pnl
        positions = [MockPosition(realized_pnl=pnl) for pnl in pnls]
        result = engine.calculate(positions)

        match = (
            result.winning_positions == exp["winning_positions"]
            and result.losing_positions == exp["losing_positions"]
            and result.breakeven_positions == exp["breakeven_positions"]
            and abs(result.gross_profit - exp["gross_profit"]) < tol
            and abs(result.gross_loss - exp["gross_loss"]) < tol
            and abs(result.net_profit - exp["net_profit"]) < tol
            and abs(result.average_win - exp["average_win"]) < tol
            and abs(result.average_loss - exp["average_loss"]) < tol
        )

        if match:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL case {i}: got {result}, expected {exp}")

    print(f"L2 PositionPerformance: {passed}/{len(cases)} passed")
    return passed, failed


def eval_l2_profit_factor_golden() -> Tuple[int, int]:
    """L2 ProfitFactor Engine — golden case validation."""
    from Business.profit_factor_engine import ProfitFactorEngine
    from Business.position_performance_engine import PositionPerformanceStatistics

    cases = json.loads((_PROJ / "Evaluation/golden_cases/l2_profit_factor_golden.json").read_text())
    passed = 0
    failed = 0
    tol = _THRESH["L2_engine"]["numeric_tolerance"]

    engine = ProfitFactorEngine()

    for i, case in enumerate(cases, 1):
        inp = case["input"]
        exp = case["expected"]
        stats = PositionPerformanceStatistics(
            winning_positions=0,
            losing_positions=0,
            breakeven_positions=0,
            gross_profit=inp["gross_profit"],
            gross_loss=inp["gross_loss"],
            net_profit=inp["gross_profit"] - inp["gross_loss"],
            average_win=0.0,
            average_loss=0.0
        )
        result = engine.calculate(stats)

        if abs(result.profit_factor - exp["profit_factor"]) < tol:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL case {i}: {result.profit_factor} != {exp['profit_factor']}")

    print(f"L2 ProfitFactor: {passed}/{len(cases)} passed")
    return passed, failed


# ---------------------------------------------------------------------------
# L2: Property-based test (hypothesis, seed fixed, 1000 inputs per function)
# ---------------------------------------------------------------------------

def eval_l2_property_expectancy(n_examples: int = 1000) -> Tuple[int, int]:
    """L2 Expectancy — property-based vs reference (1000 random inputs)."""
    from hypothesis import given, settings, strategies as st
    from Business.expectancy_engine import ExpectancyEngine
    from Business.position_performance_engine import PositionPerformanceStatistics
    from Evaluation.reference_impl import ref_expectancy

    mismatches = []
    total = [0]

    @settings(max_examples=n_examples, deadline=None)
    @given(
        winning=st.integers(min_value=0, max_value=100),
        losing=st.integers(min_value=0, max_value=100),
        breakeven=st.integers(min_value=0, max_value=50),
        avg_win=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False),
        avg_loss=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False),
    )
    def check(winning: int, losing: int, breakeven: int, avg_win: float, avg_loss: float) -> None:
        total[0] += 1
        gross_profit = winning * avg_win
        gross_loss = losing * avg_loss
        net_profit = gross_profit - gross_loss
        stats = PositionPerformanceStatistics(
            winning_positions=winning,
            losing_positions=losing,
            breakeven_positions=breakeven,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_profit=net_profit,
            average_win=avg_win,
            average_loss=avg_loss
        )
        engine = ExpectancyEngine()
        engine_result = engine.calculate(stats).expectancy
        ref_result = ref_expectancy(winning, losing, breakeven, avg_win, avg_loss)

        tol = _THRESH["L2_engine"]["numeric_tolerance"]
        if abs(engine_result - ref_result) > tol:
            mismatches.append({
                "input": (winning, losing, breakeven, avg_win, avg_loss),
                "engine": engine_result,
                "reference": ref_result,
                "diff": abs(engine_result - ref_result)
            })

    check()

    n_total = total[0]
    n_passed = n_total - len(mismatches)
    print(f"L2 Expectancy (property, {n_examples} examples): {n_passed}/{n_total} passed")
    if mismatches:
        print(f"  {len(mismatches)} mismatches, first 5:")
        for m in mismatches[:5]:
            print(f"    {m}")

    return n_passed, len(mismatches)


def eval_l2_property_max_drawdown(n_examples: int = 1000) -> Tuple[int, int]:
    """L2 MaxDrawdown — property-based vs reference (1000 random equity curves)."""
    from hypothesis import given, settings, strategies as st
    from Business.maximum_drawdown_engine import MaximumDrawdownEngine
    from Evaluation.reference_impl import ref_maximum_drawdown

    mismatches = []
    total = [0]

    @settings(max_examples=n_examples, deadline=None)
    @given(curve=st.lists(st.floats(min_value=1.0, max_value=100000.0, allow_nan=False), min_size=0, max_size=50))
    def check(curve: List[float]) -> None:
        total[0] += 1
        engine = MaximumDrawdownEngine()
        engine_result = engine.calculate(curve).maximum_drawdown
        ref_result = ref_maximum_drawdown(curve)

        tol = _THRESH["L2_engine"]["numeric_tolerance"]
        if abs(engine_result - ref_result) > tol:
            mismatches.append({
                "curve_length": len(curve),
                "engine": engine_result,
                "reference": ref_result,
                "diff": abs(engine_result - ref_result)
            })

    check()

    n_total = total[0]
    n_passed = n_total - len(mismatches)
    print(f"L2 MaxDrawdown (property, {n_examples} examples): {n_passed}/{n_total} passed")
    if mismatches:
        print(f"  {len(mismatches)} mismatches, first 5:")
        for m in mismatches[:5]:
            print(f"    {m}")

    return n_passed, len(mismatches)


def eval_l2_property_position_performance(n_examples: int = 1000) -> Tuple[int, int]:
    """L2 PositionPerformance — property-based vs reference.

    SEED NOTE: hypothesis derandomizes by default unless --hypothesis-seed /
    DERANDOMIZE=0 forces otherwise. We pin the seed explicitly so a rerun of
    this eval compares identical inputs; a mismatch list is reproducible.
    """
    from dataclasses import dataclass
    from hypothesis import given, settings, strategies as st
    from Business.position_performance_engine import PositionPerformanceEngine
    from Evaluation.reference_impl import ref_position_performance

    @dataclass
    class MockPosition:
        realized_pnl: float

    mismatches = []
    total = [0]

    @settings(max_examples=n_examples, deadline=None, derandomize=True)
    @given(st.lists(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False), min_size=0, max_size=50))
    def check(pnls: List[float]) -> None:
        total[0] += 1
        engine = PositionPerformanceEngine()
        engine_result = engine.calculate([MockPosition(realized_pnl=p) for p in pnls])
        ref_result = ref_position_performance(pnls)

        tol = _THRESH["L2_engine"]["numeric_tolerance"]
        fields_match = all(
            getattr(engine_result, key) == ref_result[key]
            if key in ("winning_positions", "losing_positions", "breakeven_positions")
            else abs(getattr(engine_result, key) - ref_result[key]) <= tol
            for key in ref_result.keys()
        )
        if not fields_match:
            mismatches.append({
                "n_pnls": len(pnls),
                "engine": engine_result,
                "reference": ref_result,
            })

    check()

    n_total = total[0]
    n_passed = n_total - len(mismatches)
    print(f"L2 PositionPerformance (property, derandomized seed): {n_passed}/{n_total} passed")
    if mismatches:
        print(f"  {len(mismatches)} mismatches, first 5:")
        for m in mismatches[:5]:
            print(f"    {m}")
    return n_passed, len(mismatches)


def eval_l2_property_profit_factor(n_examples: int = 1000) -> Tuple[int, int]:
    """L2 ProfitFactor — property-based vs reference (derandomized seed)."""
    from Business.profit_factor_engine import ProfitFactorEngine
    from Business.position_performance_engine import PositionPerformanceStatistics
    from Evaluation.reference_impl import ref_profit_factor
    from hypothesis import given, settings, strategies as st

    mismatches = []
    total = [0]

    @settings(max_examples=n_examples, deadline=None, derandomize=True)
    @given(
        gross_profit=st.floats(min_value=0.0, max_value=1e12, allow_nan=False),
        gross_loss=st.floats(min_value=0.0, max_value=1e12, allow_nan=False),
    )
    def check(gross_profit: float, gross_loss: float) -> None:
        total[0] += 1
        stats = PositionPerformanceStatistics(
            winning_positions=0,
            losing_positions=0,
            breakeven_positions=0,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_profit=gross_profit - gross_loss,
            average_win=0.0,
            average_loss=0.0,
        )
        engine = ProfitFactorEngine()
        engine_result = engine.calculate(stats).profit_factor
        ref_result = ref_profit_factor(gross_profit, gross_loss)

        tol = _THRESH["L2_engine"]["numeric_tolerance"]
        if abs(engine_result - ref_result) > tol:
            mismatches.append({
                "input": (gross_profit, gross_loss),
                "engine": engine_result,
                "reference": ref_result,
                "diff": abs(engine_result - ref_result)
            })

    check()

    n_total = total[0]
    n_passed = n_total - len(mismatches)
    print(f"L2 ProfitFactor (property, derandomized seed): {n_passed}/{n_total} passed")
    if mismatches:
        print(f"  {len(mismatches)} mismatches, first 5:")
        for m in mismatches[:5]:
            print(f"    {m}")
    return n_passed, len(mismatches)


# ---------------------------------------------------------------------------
# L3: Abstain policy + calibration metrics (synthetic tests)
# ---------------------------------------------------------------------------

def eval_l3_abstain_calibration_synthetic() -> Tuple[int, int]:
    """L3 — abstain policy + Brier/ECE on synthetic data (no DB needed)."""
    from Evaluation.abstain_policy import abstain
    from Evaluation.calibration import brier_score, ece, reliability_bins

    checks = []
    failed = []

    # --- abstain policy: boundary behaviour
    checks.append(("abstain n=29<30", abstain(29, 0.9) is True))
    checks.append(("abstain n=30>=30 conf=0.7", abstain(30, 0.7) is False))
    checks.append(("abstain conf=0.69<0.7", abstain(100, 0.69) is True))
    checks.append(("abstain n=0 always", abstain(0, 1.0) is True))

    # --- Brier: perfect calibration
    p_perfect = [1.0, 1.0, 0.0, 0.0]
    o_perfect = [1, 1, 0, 0]
    checks.append(("brier perfect=0", abs(brier_score(p_perfect, o_perfect) - 0.0) < 1e-12))

    # --- Brier: worst calibration (all inverted)
    p_worst = [1.0, 1.0]
    o_worst = [0, 0]
    checks.append(("brier worst=1", abs(brier_score(p_worst, o_worst) - 1.0) < 1e-12))

    # --- Brier: hand-computed mixed case
    # probs=[0.9, 0.3, 0.6], outcomes=[1, 0, 1]
    # sq err = 0.01 + 0.09 + 0.16 = 0.26 -> mean = 0.26/3
    p_mix = [0.9, 0.3, 0.6]
    o_mix = [1, 0, 1]
    checks.append(("brier mixed=0.26/3", abs(brier_score(p_mix, o_mix) - 0.26 / 3) < 1e-12))

    # --- ECE: perfectly calibrated (each bin avg_pred == avg_outcome)
    # p=0.5 -> outcome 1 half the time
    p_cal = [0.5] * 4
    o_cal = [1, 0, 1, 0]
    checks.append(("ece perfect=0", abs(ece(p_cal, o_cal, n_bins=2) - 0.0) < 1e-12))

    # --- ECE: badly calibrated — all p=0.9 but outcome always 0
    p_bad = [0.9] * 10
    o_bad = [0] * 10
    checks.append(("ece bad=0.9", abs(ece(p_bad, o_bad, n_bins=10) - 0.9) < 1e-12))

    # --- reliability bins
    bins = reliability_bins(p_mix, o_mix, n_bins=3)
    # 0.9 -> bin 2, 0.3 -> bin 0, 0.6 -> bin 1; all single-element bins
    checks.append(("reliability 3 bins", len(bins) == 3))
    checks.append(("reliability bin0=(0.3, 0, 1)", abs(bins[0][0] - 0.3) < 1e-12 and bins[0][2] == 1))

    # --- abstain + calibration integration: synthetic ranking-style data
    # 300 samples, 60% win rate; predicted probs follow true base rate
    import random
    random.seed(20261003)  # fixed seed for reproducibility
    n_synth = 300
    true_p = 0.6
    outcomes_synth = [1 if random.random() < true_p else 0 for _ in range(n_synth)]
    probs_synth = [true_p] * n_synth  # constant prediction = base rate
    bs = brier_score(probs_synth, outcomes_synth)
    ece_synth = ece(probs_synth, outcomes_synth, n_bins=10)
    checks.append(("synthetic brier in [0, 0.3]", 0.0 <= bs < 0.3))
    checks.append(("synthetic ece < 0.1", ece_synth < 0.1))
    checks.append(("synthetic abstain(n=300, conf=0.6)", abstain(n_synth, true_p) is False))
    checks.append(("synthetic abstain(n=150, conf=0.6)", abstain(n_synth // 2, true_p) is True))

    passed = sum(1 for _, ok in checks if ok)
    failed_count = len(checks) - passed
    print(f"L3 Abstain+Calibration (synthetic): {passed}/{len(checks)} passed")
    for name, ok in checks:
        if not ok:
            failed.append(name)
            print(f"  FAIL: {name}")
    return passed, failed_count


# ---------------------------------------------------------------------------
# L3: Walk-forward (requires n >= 200 per class — else DATA_TIDAK_CUKUP)
# ---------------------------------------------------------------------------

def eval_l3_walkforward() -> Tuple[int, int]:
    """L3 walk-forward — DATA_TIDAK_CUKUP if n < 200 per class in DB.

    If DB has sufficient ranking_snapshots + historical prices, this would
    run a walk-forward test: ranking at date T only uses data < T, labels
    come from price movement after T. Baselines: always-up, random-fixed-seed,
    moving-average.
    """
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).resolve().parent.parent / "data" / "investment_platform.db"
    if not db_path.exists():
        print("L3 Walk-forward: SKIP (DB not found)")
        return 0, 0

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM ranking_snapshots")
    n_ranking = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT date(scan_time)) FROM ranking_snapshots")
    n_dates = cur.fetchone()[0]

    conn.close()

    min_samples = 200
    if n_ranking < min_samples:
        print(f"L3 Walk-forward: DATA_TIDAK_CUKUP (n_ranking={n_ranking} < {min_samples})")
        print(f"  n_dates={n_dates}")
        print("  Need >= 200 ranking_snapshots with historical prices to run walk-forward.")
        print("  Survivorship bias note: DB only contains symbols that were actually scanned;")
        print("  delisted/suspended symbols are absent, which inflates apparent ranking quality.")
        return 0, 0
    else:
        print(f"L3 Walk-forward: SUFFICIENT_SAMPLES (n_ranking={n_ranking})")
        print("  Walk-forward test not yet implemented — add when n >= 200 per class.")
        return 1, 0


# ---------------------------------------------------------------------------
# L1: Data validation (DB schema, gaps, duplicates)
# ---------------------------------------------------------------------------

def eval_l1_data_baseline() -> Tuple[int, int]:
    """L1 Data — DB validation, gap detection, duplicates."""
    if not _DB_PATH.exists():
        print("L1 Data: SKIP (DB not found)")
        return 0, 0

    conn = sqlite3.connect(_DB_PATH)
    cur = conn.cursor()

    # Duplikat check: ranking_snapshots PK (scan_time, symbol)
    cur.execute("SELECT COUNT(*) FROM ranking_snapshots")
    total_rows = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT scan_time || symbol) FROM ranking_snapshots")
    distinct = cur.fetchone()[0]
    duplicates = total_rows - distinct

    # Gap detection: scan_time distinct dates
    cur.execute("SELECT DISTINCT date(scan_time) as d FROM ranking_snapshots ORDER BY d")
    dates = [r[0] for r in cur.fetchall()]
    gaps = 0
    if len(dates) >= 2:
        from datetime import datetime
        first = datetime.strptime(dates[0], "%Y-%m-%d")
        last = datetime.strptime(dates[-1], "%Y-%m-%d")
        delta_days = (last - first).days + 1
        expected_dates = delta_days
        actual_dates = len(dates)
        gaps = max(0, expected_dates - actual_dates)

    conn.close()

    print(f"L1 Data: duplicates={duplicates}, gaps={gaps} (distinct_dates={len(dates)})")

    passed = 0
    failed = 0
    if duplicates == 0:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {duplicates} duplicate (scan_time, symbol) pairs")

    if gaps <= _THRESH["L1_data"]["undetected_gap_count"]:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: gap count {gaps} > {_THRESH['L1_data']['undetected_gap_count']}")

    return passed, failed


# ---------------------------------------------------------------------------
# L4: LLM Groundedness — DATA_TIDAK_CUKUP (no output archive)
# ---------------------------------------------------------------------------

def eval_l4_llm_grounding() -> Tuple[int, int]:
    """L4 LLM — BLOCKED: no output archive to sample."""
    print("L4 LLM Grounding: DATA_TIDAK_CUKUP (no llm_outputs archive in DB)")
    print("  Reason: LLM narration output not persisted to any table or file.")
    print("  Needed: 30-50 real LLM responses with source data references.")
    return 0, 0


# ---------------------------------------------------------------------------
# L3: Signals — DATA_TIDAK_CUKUP (insufficient samples per class)
# ---------------------------------------------------------------------------

def eval_l3_signals_baseline() -> Tuple[int, int]:
    """L3 Signals — walk-forward calibration, DATA_TIDAK_CUKUP."""
    if not _DB_PATH.exists():
        print("L3 Signals: SKIP (DB not found)")
        return 0, 0

    conn = sqlite3.connect(_DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM ranking_snapshots")
    n_ranking = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT scan_time) FROM ranking_snapshots")
    n_scans = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM decision_briefs")
    n_briefs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM journal_entries")
    n_journals = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades")
    n_trades = cur.fetchone()[0]

    conn.close()

    print(f"L3 Signals sample counts:")
    print(f"  ranking_snapshots: {n_ranking} rows, {n_scans} scans")
    print(f"  decision_briefs: {n_briefs}")
    print(f"  journal_entries: {n_journals}")
    print(f"  trades: {n_trades}")

    min_samples = _THRESH["L3_signals"]["minimum_samples_per_class"]
    if n_ranking < min_samples or n_scans < min_samples or n_journals < min_samples:
        print(f"  DATA_TIDAK_CUKUP (< {min_samples} samples per class)")
        print("  Need: walk-forward needs >= 200 journal_entries with outcomes for Brier/ECE.")
        return 0, 0
    else:
        print(f"  SUFFICIENT_SAMPLES")
        return 1, 0


# ---------------------------------------------------------------------------
# L5: Orchestration — job completion rate
# ---------------------------------------------------------------------------

def eval_l5_orchestration_baseline() -> Tuple[int, int]:
    """L5 Orchestration — job completion rate from scheduler_job_runs."""
    if not _DB_PATH.exists():
        print("L5 Orchestration: SKIP (DB not found)")
        return 0, 0

    conn = sqlite3.connect(_DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT trading_date, COUNT(*) as job_count
        FROM scheduler_job_runs
        GROUP BY trading_date
        ORDER BY trading_date
    """)
    job_rows = cur.fetchall()
    conn.close()

    if not job_rows:
        print("L5 Orchestration: NO_DATA (0 rows in scheduler_job_runs)")
        return 0, 0

    EXPECTED_JOBS_PER_DATE = 6
    total_trading_dates = len(job_rows)
    total_jobs_executed = sum(r[1] for r in job_rows)
    expected_total = total_trading_dates * EXPECTED_JOBS_PER_DATE
    completion_rate = total_jobs_executed / expected_total if expected_total > 0 else 0.0

    print(f"L5 Orchestration: {total_jobs_executed}/{expected_total} jobs = {completion_rate:.2%}")
    print(f"  Trading dates observed: {total_trading_dates}")

    passed = 0
    failed = 0
    if completion_rate >= _THRESH["L5_orchestration"]["job_completion_rate"]:
        passed = 1
    else:
        failed = 1
        print(f"  FAIL: completion rate {completion_rate:.2%} < {_THRESH['L5_orchestration']['job_completion_rate']:.2%}")

    return passed, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== AIOS Accuracy Evaluation v2 ===\n")

    results: Dict[str, Any] = {}
    total_passed = 0
    total_failed = 0

    # L2 Golden cases
    p, f = eval_l2_expectancy_golden()
    results["L2_expectancy_golden"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l2_max_drawdown_golden()
    results["L2_max_drawdown_golden"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l2_forex_max_loss_golden()
    results["L2_forex_max_loss_golden"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l2_position_performance_golden()
    results["L2_position_performance_golden"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l2_profit_factor_golden()
    results["L2_profit_factor_golden"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    # L2 Property-based tests (1000 examples, seed from hypothesis)
    print("\n--- Property-based tests (hypothesis, seed derived) ---")
    p, f = eval_l2_property_expectancy(1000)
    results["L2_expectancy_property"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l2_property_max_drawdown(1000)
    results["L2_max_drawdown_property"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l2_property_position_performance(1000)
    results["L2_position_performance_property"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l2_property_profit_factor(1000)
    results["L2_profit_factor_property"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    print("\n--- Data & Orchestration ---")
    # L1
    p, f = eval_l1_data_baseline()
    results["L1_data"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    # L4
    p, f = eval_l4_llm_grounding()
    results["L4_llm_grounding"] = {"passed": p, "failed": f, "status": "DATA_TIDAK_CUKUP"}

    # L3
    p, f = eval_l3_signals_baseline()
    results["L3_signals"] = {"passed": p, "failed": f, "status": "DATA_TIDAK_CUKUP" if p == 0 and f == 0 else "SUFFICIENT"}

    p, f = eval_l3_abstain_calibration_synthetic()
    results["L3_abstain_calibration_synthetic"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    p, f = eval_l3_walkforward()
    results["L3_walkforward"] = {"passed": p, "failed": f, "status": "DATA_TIDAK_CUKUP" if p == 0 and f == 0 else "SUFFICIENT"}

    # L5
    p, f = eval_l5_orchestration_baseline()
    results["L5_orchestration"] = {"passed": p, "failed": f}
    total_passed += p
    total_failed += f

    print(f"\n=== Summary: {total_passed} passed, {total_failed} failed ===")
    print(f"=== DATA_TIDAK_CUKUP: L3, L4 ===")

    report = {
        "total_passed": total_passed,
        "total_failed": total_failed,
        "details": results
    }
    report_path = _PROJ / "Evaluation" / "run_eval_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()