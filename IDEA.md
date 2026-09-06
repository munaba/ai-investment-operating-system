Project:
AIOS / Autonomous Investment Operating System

Current state:
Phase A–G complete
Phase H implementation complete
Phase H observation window active
Observation period:
2026-08-24 → 2026-09-23
Timezone:
Asia/Jakarta

Critical rules:
- no broker/live execution
- no autonomous paper orders
- risk policy is deterministic
- copilot default READ_ONLY
- do not fabricate evidence
- do not alter active observation window
- real DB is data/investment_platform.db
- migrations are domain-specific/manual in this repo
- preserve existing architecture/conventions

Current provider:
Ollama Qwen3 8B
9Router installed/configured separately, not yet adopted as primary

Working style:
- inspect before editing
- smallest additive change
- standalone tests
- run relevant regressions
- never claim a file was modified unless actually modified
