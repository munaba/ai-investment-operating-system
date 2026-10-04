"""Mutation-proven L2 regression gate.

Item 3 spec: setiap test memutasi SATU engine di memori (monkeypatch,
tanpa menyentuh file) lalu memaksa ``Evaluation/run_eval.py``'s
``eval_l2_*`` golden DAN property untuk berjalan, dan MENEGASKAN
``failed > 0`` — artinya gerbang L2 gagal tepat ketika engine rusak.

Kontradiksi lama yang dijawab test ini ("property tetap 100% tapi
4 golden failures"): harness historis hanya meng-assert 3 engine golden
+ 2 property (lihat ``Tests/test_evaluation_harness.py`` baris 41-52).
Mutasi ke profit_factor / position_performance tercatat di report tapi
tidak pernah di-assert, sehingga pytest tetap hijau. Test ini
menutup celah itu: semua 5 engine digerakkan melalui jalur emas dan
property-nya masing-masing.

Bukti file-mutation round-trip (di luar test ini, lihat laporan):
expectancy/drawdown/forex → harness FAILED; profit_factor/position_perf
→ harness passed TAPI report menunjukkan golden+property gagal (bukti
coverage gap yang sekarang ditutup).
"""
from __future__ import annotations

from Evaluation import run_eval


def _assert_gate_closes(golden_failed: int, property_failed: int, label: str) -> None:
    """Gerbang L2 harus gagal pada golden dan property di bawah mutasi."""
    assert golden_failed > 0, (
        f"{label}: golden gate stayed green under mutation (failed=0)"
    )
    assert property_failed > 0, (
        f"{label}: property gate stayed green under mutation (failed=0)"
    )


def test_mutated_expectancy_engine_fails_gate(monkeypatch):
    import Business.expectancy_engine as mod

    original = mod.ExpectancyEngine.calculate

    def mutated(self, statistics):
        result = original(self, statistics)
        result.expectancy = -result.expectancy
        return result

    monkeypatch.setattr(mod.ExpectancyEngine, "calculate", mutated)
    _, golden_failed = run_eval.eval_l2_expectancy_golden()
    _, prop_failed = run_eval.eval_l2_property_expectancy(200)
    _assert_gate_closes(golden_failed, prop_failed, "expectancy")


def test_mutated_drawdown_engine_fails_gate(monkeypatch):
    import Business.maximum_drawdown_engine as mod

    original = mod.MaximumDrawdownEngine.calculate

    def mutated(self, equity_curve):
        result = original(self, equity_curve)
        result.maximum_drawdown *= 2.0
        return result

    monkeypatch.setattr(mod.MaximumDrawdownEngine, "calculate", mutated)
    _, golden_failed = run_eval.eval_l2_max_drawdown_golden()
    _, prop_failed = run_eval.eval_l2_property_max_drawdown(200)
    _assert_gate_closes(golden_failed, prop_failed, "max_drawdown")


def test_mutated_forex_policy_fails_gate(monkeypatch):
    import Business.forex_max_loss_policy as mod

    original = mod.calculate_maximum_loss

    def mutated(pair, entry_price, stop_loss, quantity):
        return original(pair, entry_price, stop_loss, quantity) + mod.Decimal("1000")

    monkeypatch.setattr(mod, "calculate_maximum_loss", mutated)
    # forex punya golden cases, tidak ada property suite — gate golden saja.
    _, golden_failed = run_eval.eval_l2_forex_max_loss_golden()
    assert golden_failed > 0, (
        "forex: golden gate stayed green under mutation (failed=0)"
    )


def test_mutated_profit_factor_engine_fails_gate(monkeypatch):
    """Profit factor: coverage gap historis (harness tidak meng-assert
    engine ini) — mutasi sebelumnya lolos pytest tanpa gagal."""
    import Business.profit_factor_engine as mod

    original = mod.ProfitFactorEngine.calculate

    def mutated(self, statistics):
        result = original(self, statistics)
        result.profit_factor *= 2.0
        return result

    monkeypatch.setattr(mod.ProfitFactorEngine, "calculate", mutated)
    _, golden_failed = run_eval.eval_l2_profit_factor_golden()
    _, prop_failed = run_eval.eval_l2_property_profit_factor(200)
    _assert_gate_closes(golden_failed, prop_failed, "profit_factor")


def test_mutated_position_performance_engine_fails_gate(monkeypatch):
    """Position performance: coverage gap historis sama seperti di atas."""
    import Business.position_performance_engine as mod

    original = mod.PositionPerformanceEngine.calculate

    def mutated(self, positions):
        result = original(self, positions)
        result.net_profit = result.gross_profit + result.gross_loss
        return result

    monkeypatch.setattr(mod.PositionPerformanceEngine, "calculate", mutated)
    _, golden_failed = run_eval.eval_l2_position_performance_golden()
    _, prop_failed = run_eval.eval_l2_property_position_performance(200)
    _assert_gate_closes(golden_failed, prop_failed, "position_performance")


def test_unmutated_engines_pass_gate():
    """Kontrol: tanpa mutasi, kelima jalur emas + property hijau —
    membuktikan mutasi, bukan harness yang rusak, yang memicu kegagalan."""
    _, g1 = run_eval.eval_l2_expectancy_golden()
    _, g2 = run_eval.eval_l2_max_drawdown_golden()
    _, g3 = run_eval.eval_l2_forex_max_loss_golden()
    _, g4 = run_eval.eval_l2_position_performance_golden()
    _, g5 = run_eval.eval_l2_profit_factor_golden()
    assert (g1, g2, g3, g4, g5) == (0, 0, 0, 0, 0), (
        f"unmutated golden failures: {(g1, g2, g3, g4, g5)}"
    )

    _, p1 = run_eval.eval_l2_property_expectancy(200)
    _, p2 = run_eval.eval_l2_property_max_drawdown(200)
    _, p3 = run_eval.eval_l2_property_position_performance(200)
    _, p4 = run_eval.eval_l2_property_profit_factor(200)
    assert (p1, p2, p3, p4) == (0, 0, 0, 0), (
        f"unmutated property failures: {(p1, p2, p3, p4)}"
    )
