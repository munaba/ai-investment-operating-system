# Activation 2 — Production Acceptance Probe

Read-only probe for the final Activation 2 gate.

It uses the existing real market-data helpers and the current locked analysis decision table. It does not modify the production scanner, decision table, watchlist, or database.

Run from the project root:

```powershell
python Tests/test_activation2_production_acceptance_probe.py
```

The probe scans a broad IDX ticker universe and reports only candidates that satisfy one of the existing production combinations:

- bullish + positive + undervalued → BUY / HIGH
- bearish + negative + overvalued → SELL / HIGH
- bullish + negative + fair → WAIT / MEDIUM
- bearish + positive + fair → WAIT / MEDIUM

It then applies the existing default ranking weights:

- BUY=3, WAIT=2, SELL=1
- HIGH=3, MEDIUM=2, LOW=1

Exit `0` means at least 3 real candidates were found. Exit `2` means the current live market snapshot produced fewer than 3 candidates; this is a diagnostic result, not a change to production logic.
