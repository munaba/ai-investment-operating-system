"""Metric ratchet test — baseline.json enforcement.

Item 4 spec: metrik tidak boleh lebih buruk dari baseline. L2 golden +
property harus sama persis (tidak ada regresi yang diterima); recall
naik/tetap; FPR turun/tetap; gap tidak naik. Perbaikan boleh —
`Evaluation/update_baseline.py` script eksplisit (bukan otomatis) memperbarui baseline.

baseline.json berisi nilai metrik AKTUAL dari run terbaru (bukan
ambang), beserta tanggal dan commit. Test ini memuat run_eval_report.json
dan membandingkan dengan baseline.json, menegaskan tidak ada kemunduran.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parent.parent
_PY = sys.executable


def test_metrics_do_not_regress_from_baseline():
    """Metrics tidak boleh memburuk dari baseline.json."""
    baseline_path = _PROJ / "Evaluation" / "baseline.json"
    assert baseline_path.exists(), "baseline.json not found"
    
    baseline = json.loads(baseline_path.read_text())
    
    # Run eval
    result = subprocess.run(
        [_PY, str(_PROJ / "Evaluation" / "run_eval.py")],
        cwd=_PROJ,
        capture_output=True,
        text=True,
    )
    
    report_path = _PROJ / "Evaluation" / "run_eval_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text())
    details = report["details"]
    
    # L2 golden: harus sama persis (passed/failed)
    l2_golden_keys = [
        "L2_expectancy_golden",
        "L2_max_drawdown_golden",
        "L2_forex_max_loss_golden",
        "L2_position_performance_golden",
        "L2_profit_factor_golden",
    ]
    for key in l2_golden_keys:
        assert details[key]["passed"] == baseline[key]["passed"], (
            f"{key}: passed regressed {details[key]['passed']} != {baseline[key]['passed']}"
        )
        assert details[key]["failed"] == baseline[key]["failed"], (
            f"{key}: failed regressed {details[key]['failed']} != {baseline[key]['failed']}"
        )
    
    # L2 property: sama persis
    l2_prop_keys = [
        "L2_expectancy_property",
        "L2_max_drawdown_property",
        "L2_position_performance_property",
        "L2_profit_factor_property",
    ]
    for key in l2_prop_keys:
        assert details[key]["passed"] == baseline[key]["passed"], (
            f"{key}: passed regressed {details[key]['passed']} != {baseline[key]['passed']}"
        )
        assert details[key]["failed"] == baseline[key]["failed"], (
            f"{key}: failed regressed {details[key]['failed']} != {baseline[key]['failed']}"
        )
    
    # L1 gap: tidak boleh naik
    current_gap = details["L1_data"]["failed"]
    baseline_gap = baseline["L1_gap_count"]
    assert current_gap <= baseline_gap, (
        f"L1 gap count increased: {current_gap} > {baseline_gap}"
    )
    
    # L4 recall/FPR: recall >= baseline (jika ada), FPR <= baseline
    # (saat ini null karena DATA_TIDAK_CUKUP)
    if baseline["L4_recall"] is not None:
        # recall naik atau tetap
        assert details.get("L4_recall") is not None
        assert details["L4_recall"] >= baseline["L4_recall"], (
            f"L4 recall dropped: {details['L4_recall']} < {baseline['L4_recall']}"
        )
    if baseline["L4_fpr"] is not None:
        # FPR turun atau tetap
        assert details.get("L4_fpr") is not None
        assert details["L4_fpr"] <= baseline["L4_fpr"], (
            f"L4 FPR increased: {details['L4_fpr']} > {baseline['L4_fpr']}"
        )
    
    # L3 abstain synthetic: sama persis
    assert details["L3_abstain_calibration_synthetic"]["passed"] == baseline["L3_abstain_synthetic"]["passed"]
    assert details["L3_abstain_calibration_synthetic"]["failed"] == baseline["L3_abstain_synthetic"]["failed"]


def test_degraded_baseline_fails_ratchet():
    """Ubah baseline agar metrik tampak memburuk, test GAGAL."""
    baseline_path = _PROJ / "Evaluation" / "baseline.json"
    baseline = json.loads(baseline_path.read_text())
    
    # Mutasi: expectancy golden passed jadi 7 (asli 6), failed 0
    # Ini lebih baik, bukan lebih buruk — tidak boleh gagal. 
    # Mutasi lain: gap_count jadi 0 (asli 1), lebih baik — tidak gagal.
    # Mutasi buruk: expectancy_property failed jadi 1 (asli 0).
    degraded = baseline.copy()
    degraded["L2_expectancy_property"] = {"passed": 999, "failed": 1}
    
    # Tulis baseline palsu
    backup = baseline_path.read_text()
    baseline_path.write_text(json.dumps(degraded, indent=2))
    
    try:
        # Re-run test (akan gagal karena current failed=0 tapi baseline failed=1 → tidak regress, tapi ini bukan constraint arah yg benar)
        # Tunggu, spec: "L2 harus sama persis" — jadi current=0 baseline=1 → current lebih baik, pass. Tapi current=1 baseline=0 → regress, fail.
        # Kita ingin test current yg buruk. Mutasi: baseline passed=1000 failed=0, tapi run asli passed=1000 failed=0 → sama. 
        # Mutasi lain: baseline L1_gap=0, current=1 → gap naik → FAIL.
        degraded2 = baseline.copy()
        degraded2["L1_gap_count"] = 0  # baseline gap 0, current 1 → gap naik → FAIL
        baseline_path.write_text(json.dumps(degraded2, indent=2))
        
        result = subprocess.run(
            [_PY, "-m", "pytest", str(_PROJ / "Tests" / "test_evaluation_ratchet_baseline.py::test_metrics_do_not_regress_from_baseline"), "-q"],
            cwd=_PROJ,
            capture_output=True,
            text=True,
        )
        # Expect FAILED
        assert result.returncode != 0, "ratchet test should FAIL when gap increases"
        assert "L1 gap count increased" in result.stdout or "AssertionError" in result.stdout
    finally:
        # Restore
        baseline_path.write_text(backup)
