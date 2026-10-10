# Proof Scripts

These executable scripts prove end-to-end behavior against real SQLite databases, not mocks. They are **not** collected by pytest. Run each with `PYTHONPATH=.`.

## Scripts and Requirements

| Script | What It Proves | Requirements |
|--------|----------------|--------------|
| `activation_2_7_proof.py` | Scan persistence, ranking, restart survives | `DB_PATH=data/investment_platform.db` (real DB) |
| `activation_3_2_independent_proof.py` | Paper trading engine independent behavior | `tempfile.TemporaryDirectory` (auto) |
| `activation_3_5_step1_proof.py` | Order lifecycle, execution, balance update | `tempfile.TemporaryDirectory` (auto) |
| `activation_3_5_step3_proof.py` | Available cash gate matches fee+tax formula | `tempfile.TemporaryDirectory` (auto; Windows: PermissionError on cleanup is benign) |
| `activation_3_6_step3_proof.py` | Position manager restart persistence | `tempfile.TemporaryDirectory` (auto) |
| `activation_3_7_step2_proof.py` | Fee/tax in realized P/L on SELL | `tempfile.TemporaryDirectory` (auto) |
| `activation_3_7_step4_proof.py` | Unrealized P/L engine correctness | `tempfile.TemporaryDirectory` (auto) |
| `activation4_session2_acceptance_proof.py` | Full CLI flow: init → scan → paper → portfolio → restart → sell | `tempfile.TemporaryDirectory` (auto) |
| `activation5_5_acceptance_proof.py` | Performance summary survives restart | `tempfile.TemporaryDirectory` (auto; "Reclaimed and closed leaked connection" log from prior run is expected) |
| `activation5_6_acceptance_proof.py` | Trade attribution survives restart | `tempfile.TemporaryDirectory` (auto) |
| `activation6_telegram_real_send_proof.py` | Real Telegram delivery | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` env vars |
| `proof_activation_3_4_step2.py` | Orphaned Trade row on partial failure | `tempfile.TemporaryDirectory` (auto) |
| `section_2_8_proof.py` | CLI scanner ranking, error handling, restart | `DB_PATH=data/investment_platform.db` (real DB; subprocess stdout race may cause intermittent "watchlist survives" FAIL, but persistence checks pass) |

## Running

```bash
# Example: activation_3_2_independent_proof.py
PYTHONPATH=. python Tests/activation_3_2_independent_proof.py

# Example: activation_2_7_proof.py (needs real DB)
PYTHONPATH=. DB_PATH=data/investment_platform.db python Tests/activation_2_7_proof.py
```

## Windows Notes

- `activation_3_5_step3_proof.py`: `PermissionError` on temp file cleanup is a Windows + SQLite file lock issue. The test logic passes; the error occurs during `tempfile.TemporaryDirectory` cleanup after the test completes.
- `section_2_8_proof.py`: The "watchlist survives a brand-new process" check may intermittently report FAIL due to subprocess PIPE timing. The key persistence assertions (ASII DATA_ERROR, ranking order) pass reliably.

## Do Not Rename

These scripts are deliberately `*_proof.py`, not `test_*.py`. They are acceptance proofs, not unit tests, and should not be collected by pytest. They are not refactored into pytest because they intentionally:
1. Run against real DB files (not `:memory:`).
2. Perform process restarts (new OS process, not just new connection).
3. Use network services (Telegram) for real delivery proofs.
