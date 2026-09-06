# Phase 1 vs Streamlit — Parity Comparison

> Sumber: sesi Hermes 25 Aug 2026. Perbandingan row count & kolom antara query Python (representasi Streamlit) dan render C# Phase 1, terhadap DB yang sama.

## Row counts

| Table / Query | Streamlit (Python) | C# Phase 1 (Blazor) | Match |
|---|---|---|---|
| `journal_entries` | 0 rows | 0 rows | ✅ |
| `decision_briefs` | 5 rows | 5 rows (via BriefId join) | ✅ |

## Joined query result (what Streamlit would show)

```
=== JOINED DATA (what Streamlit would show) ===
Row count: 0
=== DECISION BRIEFS (5 rows) ===
(1, 'ANTM', 'POLICY_BLOCKED', None)
(2, 'ANTM', 'SUCCESS', 2.0)
(3, 'ANTM', 'POLICY_BLOCKED', None)
(4, 'ANTM', 'SUCCESS', 2.0)
(5, 'ANTM', 'SUCCESS', 2.0)
```

## Key columns compared

`symbol`, `decision`/`status`, `planned_r`/`risk_reward_ratio` — nilai identik untuk kelima briefs di kedua implementasi.

**Catatan:** mapping kolom `decision_briefs.risk_reward_ratio` (DB) vs `planned_r` (model) dipetakan eksplisit di `OnModelCreating` — jangan rename salah satu pihak tanpa cek mapping ini.
