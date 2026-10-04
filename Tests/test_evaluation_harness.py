"""Test suite for Evaluation harness acceptance (TAHAP 3).

Membuktikan run_eval.py dapat dijalankan, exit code benar, dan report JSON valid.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parent.parent
_PY = sys.executable


def test_run_eval_executes_and_produces_report():
    """run_eval.py berjalan sampai selesai dan menghasilkan report JSON valid."""
    result = subprocess.run(
        [_PY, str(_PROJ / "Evaluation" / "run_eval.py")],
        cwd=_PROJ,
        capture_output=True,
        text=True,
    )
    
    # Exit code 1 expected (L1/L5 fail)
    assert result.returncode == 1
    
    # Report file exists
    report_path = _PROJ / "Evaluation" / "run_eval_report.json"
    assert report_path.exists()
    
    # Report is valid JSON
    report = json.loads(report_path.read_text())
    assert "total_passed" in report
    assert "total_failed" in report
    assert "details" in report
    
    # L2 should pass (golden + property)
    assert report["details"]["L2_expectancy_golden"]["passed"] > 0
    assert report["details"]["L2_expectancy_golden"]["failed"] == 0
    assert report["details"]["L2_max_drawdown_golden"]["passed"] > 0
    assert report["details"]["L2_max_drawdown_golden"]["failed"] == 0
    assert report["details"]["L2_forex_max_loss_golden"]["passed"] > 0
    assert report["details"]["L2_forex_max_loss_golden"]["failed"] == 0
    
    # Property-based should have 1000 passed each
    assert report["details"]["L2_expectancy_property"]["passed"] == 1000
    assert report["details"]["L2_expectancy_property"]["failed"] == 0
    assert report["details"]["L2_max_drawdown_property"]["passed"] == 1000
    assert report["details"]["L2_max_drawdown_property"]["failed"] == 0
    
    # L1 should fail (gap count > 0)
    assert report["details"]["L1_data"]["failed"] > 0
    
    # L5: fewer than 5 IDX trading days observed -> DATA_TIDAK_CUKUP, not FAIL.
    # Rationale: completion rate over 1-2 trading days is statistical noise,
    # so the gate reports insufficient data rather than a scheduler failure.
    assert report["details"]["L5_orchestration"]["status"] == "DATA_TIDAK_CUKUP"
    assert report["details"]["L5_orchestration"]["failed"] == 0
    
    # L3/L4 should be DATA_TIDAK_CUKUP (not counted as failures)
    assert report["details"]["L3_signals"]["status"] == "DATA_TIDAK_CUKUP"
    assert report["details"]["L4_llm_grounding"]["status"] == "DATA_TIDAK_CUKUP"


def test_golden_cases_exist():
    """Golden case files generated from reference exist and are valid JSON."""
    golden_dir = _PROJ / "Evaluation" / "golden_cases"
    
    expectancy_path = golden_dir / "l2_expectancy_golden.json"
    assert expectancy_path.exists()
    expectancy = json.loads(expectancy_path.read_text())
    assert len(expectancy) >= 5
    assert all("input" in c and "expected" in c for c in expectancy)
    
    drawdown_path = golden_dir / "l2_max_drawdown_golden.json"
    assert drawdown_path.exists()
    drawdown = json.loads(drawdown_path.read_text())
    assert len(drawdown) >= 5
    
    forex_path = golden_dir / "l2_forex_max_loss_golden.json"
    assert forex_path.exists()
    forex = json.loads(forex_path.read_text())
    assert len(forex) >= 5


def test_reference_impl_importable():
    """reference_impl.py importable and has required functions."""
    from Evaluation.reference_impl import (
        ref_expectancy,
        ref_forex_maximum_loss,
        ref_maximum_drawdown,
        ref_profit_factor,
    )
    
    # Smoke test
    assert ref_expectancy(7, 3, 0, 100.0, 50.0) == 55.0
    assert ref_maximum_drawdown([100.0, 90.0, 80.0, 70.0]) == 0.3
    assert ref_profit_factor(1500.0, 500.0) == 3.0


def test_thresholds_json_valid():
    """thresholds.json valid dan memuat target untuk semua layer."""
    thresh_path = _PROJ / "Evaluation" / "thresholds.json"
    assert thresh_path.exists()
    
    thresh = json.loads(thresh_path.read_text())
    assert "L1_data" in thresh
    assert "L2_engine" in thresh
    assert "L3_signals" in thresh
    assert "L4_llm" in thresh
    assert "L5_orchestration" in thresh
    
    # L2 tolerance
    assert thresh["L2_engine"]["numeric_tolerance"] <= 1e-6
    
    # L5 completion rate target
    assert thresh["L5_orchestration"]["job_completion_rate"] >= 0.99
