"""
Phase I Gate 3 proof suite -- Decision Copilot CLI Bridge.

Scope:
  - End-to-end invocation of the REAL ``python main.py decision-copilot
    ...`` CLI as an actual subprocess (not a function-call shortcut),
    against a real, on-disk, freshly-migrated SQLite database.
  - The two-part stdout contract (STATUS glance line + JSON payload).
  - Fail-closed statuses surfaced verbatim (INSUFFICIENT_DATA, DATA_ERROR).
  - EMPIRICAL read-only proof: real row counts in ``ranking_snapshots`` and
    ``journal_entries`` are compared before and after every CLI run.
  - Boundary proofs by source inspection of the new ``main.py`` code block.

Run directly with
``python Tests/test_phase_i_gate3_cli_bridge.py`` -- no external test
framework required, matching every other standalone test file in this
repository.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASS = 0
_FAIL = 0
_FAILURES: list[str] = []


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        _FAILURES.append(description)
        print(f"  FAIL - {description}")


# ---------------------------------------------------------------------------
# Real temp database: fresh file, real migrations applied.
# ---------------------------------------------------------------------------


def _build_db(db_path: Path) -> None:
    """Create a brand-new SQLite file with the two tables this CLI reads.

    Only the migrations that own ``ranking_snapshots`` and ``journal_entries``
    are applied -- this command reads nothing else.
    """
    from Database.database_config import DatabaseConfig
    from Database.migrations import MigrationRunner
    from Database.migrations_risk_ledger import RISK_LEDGER_MIGRATIONS
    from Database.migrations_snapshots import SNAPSHOTS_MIGRATIONS
    from Database.sqlite_database import SQLiteDatabase

    db = SQLiteDatabase(DatabaseConfig(db_path=db_path))
    db.connect()
    for migration_set in (SNAPSHOTS_MIGRATIONS, RISK_LEDGER_MIGRATIONS):
        MigrationRunner(db).apply(migration_set)
    db.disconnect()


def _seed_snapshots(db_path: Path, rows: int) -> None:
    """Insert ``rows`` real ranking_snapshots rows directly via SQL.

    Column list taken verbatim from
    ``Database/migrations_snapshots.py`` v11: ``priority``/``rank`` are the
    five columns ranking reads supply unchanged: ``evidence_summary`` is
    populated here so the row is complete, but the CLI never reinterprets
    any of these columns -- it only counts and sums ``*_contribution``
    values inside ``score_breakdown_json``.
    ``score`` here is INTEGER, per that DDL.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        for i in range(rows):
            conn.execute(
                "INSERT INTO ranking_snapshots "
                "(scan_time, symbol, status, recommendation, confidence, "
                "priority, rank, score, score_breakdown_json, "
                "evidence_summary) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f"2026-09-{(i % 5) + 1:02d}T09:00:00",
                    ["BBCA", "BMRI", "TLKM"][i % 3],
                    "success",
                    ["BUY", "WATCH", "HOLD"][i % 3],
                    ["HIGH", "MEDIUM", "LOW"][i % 3],
                    i,
                    i + 1,
                    50 + i,
                    '{"momentum_contribution": 0.%d}' % (i % 10),
                    "seeded evidence",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_journal(db_path: Path, rows: int) -> None:
    """Insert ``rows`` real journal_entries rows directly via SQL.

    Column list and CHECK constraints taken verbatim from
    ``Database/migrations_risk_ledger.py`` migration v21: ``entry_id`` and
    ``brief_id`` are INTEGER, ``risk_policy_status`` must be one of
    ``('ACCEPTED','RISK_REJECTED')``, ``decision`` one of
    ``('TAKE','SKIP','WAIT')``. ``brief_id`` values are orphans by design
    (this test migrates only the journal table, not ``decision_briefs``) --
    sqlite3 does not enable ``PRAGMA foreign_keys``, verified before this
    seed was written, so the reference is stored, never resolved.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        for i in range(rows):
            conn.execute(
                "INSERT INTO journal_entries "
                "(brief_id, symbol, decision, decided_at, "
                "risk_policy_status, created_at) VALUES (?,?,?,?,?,?)",
                (
                    9000 + i,
                    ["BBCA", "BMRI"][i % 2],
                    ["TAKE", "SKIP", "WAIT"][i % 3],
                    f"2026-09-{(i % 5) + 1:02d}T10:00:00",
                    "ACCEPTED",
                    f"2026-09-{(i % 5) + 1:02d}T10:00:00",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _row_counts(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            "ranking_snapshots": conn.execute(
                "SELECT COUNT(*) FROM ranking_snapshots"
            ).fetchone()[0],
            "journal_entries": conn.execute(
                "SELECT COUNT(*) FROM journal_entries"
            ).fetchone()[0],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Real CLI invocation.
# ---------------------------------------------------------------------------


def _run_cli(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke the REAL ``python main.py decision-copilot ...`` CLI as an
    actual subprocess against ``db_path`` -- exactly as an operator would.
    """
    env = dict(os.environ)
    env["DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, "main.py", "decision-copilot", *args],
        cwd=str(_PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _split_status_line(stdout: str) -> tuple[str, str]:
    """Locate the STATUS: glance line in stdout (may be preceded by
    logging output on stdout from ``Core.logger``'s
    ``StreamHandler(stream=sys.stdout)``) and return (status_value, json_text).
    """
    status_prefix = "STATUS: "
    for i, line in enumerate(stdout.splitlines()):
        if line.startswith(status_prefix):
            # JSON payload ends at the last line that starts with `}`.
            # Any logging after that is noise from Core.logger (which
            # writes to stdout, not stderr).
            rest = stdout.splitlines()[i + 1 :]
            json_lines = []
            for jl in rest:
                json_lines.append(jl)
                if jl.strip() == "}":
                    break
            return (line[len(status_prefix) :], "\n".join(json_lines))
    return ("", stdout)


def run_cases() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        seeded = tmpdir / "seeded.db"
        empty = tmpdir / "empty.db"

        _build_db(seeded)
        _build_db(empty)
        _seed_snapshots(seeded, rows=7)
        _seed_journal(seeded, rows=4)

        counts_before = _row_counts(seeded)
        print(f"[setup] seeded db counts before any CLI run: {counts_before}")
        print(f"[setup] empty db counts: {_row_counts(empty)}")

        # ---------------- Case 1: no subcommand ----------------
        print("\n[Case 1] no subcommand -> usage, exit 1")
        r = _run_cli(seeded)
        check(r.returncode == 1, "exit code 1")
        check(
            "Usage: python main.py decision-copilot" in r.stdout,
            "usage line printed",
        )
        check(
            "analyze_historical_patterns" in r.stdout
            and "analyze_evidence_profile" in r.stdout,
            "usage names both capabilities",
        )

        # ---------------- Case 2: unknown subcommand ----------------
        print("\n[Case 2] unknown subcommand -> error, exit 1")
        r = _run_cli(seeded, "bogus")
        check(r.returncode == 1, "exit code 1")
        check(
            "Unknown decision-copilot subcommand: 'bogus'" in r.stdout,
            "unknown-subcommand message printed",
        )
        check(
            "(expected 'patterns' or 'evidence')" in r.stdout,
            "expected-list printed",
        )

        # ---------------- Case 3: evidence, real rows ----------------
        print("\n[Case 3] evidence on real seeded db -> SUCCESS + valid JSON")
        r = _run_cli(seeded, "evidence")
        status, json_text = _split_status_line(r.stdout)
        check(r.returncode == 0, "exit code 0")
        check(status == "SUCCESS", f"line 1 is 'STATUS: SUCCESS' (got {status!r})")
        try:
            payload = json.loads(json_text)
            parsed = True
        except json.JSONDecodeError as exc:
            payload = {}
            parsed = False
            print(f"    [json error] {exc}")
        check(parsed, "lines 2.. are valid JSON")
        if parsed:
            check(payload["status"] == "SUCCESS", "JSON status is SUCCESS")
            check(payload["status"] == status, "glance line and JSON status agree")
            check(payload["command"] == "evidence", "command echoed")
            check(payload["skill"] == "decision_copilot", "skill name echoed")
            check(payload["read_only"] is True, "CLI-level read_only is True")
            out = payload["output"]
            check(out["read_only"] is True, "skill-level read_only is True")
            check(
                out["snapshot_count"] == counts_before["ranking_snapshots"],
                f"snapshot_count reconciles with real rows "
                f"({out['snapshot_count']} vs {counts_before['ranking_snapshots']})",
            )
            check(
                sum(out["status_counts"].values()) == out["snapshot_count"],
                "status_counts sum to snapshot_count",
            )
            check(
                sum(out["recommendation_counts"].values())
                == out["snapshot_count"] - out["error_row_count"],
                "recommendation_counts sum to non-error rows",
            )
            check(
                sum(out["confidence_counts"].values())
                == out["snapshot_count"] - out["error_row_count"],
                "confidence_counts sum to non-error rows",
            )
            check(out["error_row_count"] == 0, "no error rows seeded")
            check(out["unparsed_breakdown_count"] == 0, "no unparsed breakdowns")
            check(
                out["factor_contribution_totals"].get("momentum_contribution")
                is not None,
                "factor contributions aggregated",
            )
            print(f"    [evidence] {out['symbols']} scans={out['scan_count']}")

        # ---------------- Case 4: patterns, real rows ----------------
        print("\n[Case 4] patterns on real seeded db -> SUCCESS + valid JSON")
        r = _run_cli(seeded, "patterns", "MY-ACC", "2026-09-01", "2026-09-30")
        status, json_text = _split_status_line(r.stdout)
        check(r.returncode == 0, "exit code 0")
        check(status == "SUCCESS", f"line 1 is 'STATUS: SUCCESS' (got {status!r})")
        payload = json.loads(json_text)
        check(payload["status"] == "SUCCESS", "JSON status is SUCCESS")
        out = payload["output"]
        check(out["account_id"] == "MY-ACC", "account_id echoed verbatim")
        check(out["read_only"] is True, "skill-level read_only is True")
        check(
            out["entry_count"] == counts_before["journal_entries"],
            f"entry_count reconciles with real rows "
            f"({out['entry_count']} vs {counts_before['journal_entries']})",
        )
        check(
            sum(out["decision_counts"].values()) == out["entry_count"],
            "decision_counts sum to entry_count",
        )
        check(
            "single-account by design (AGENTS.md)" in out["filter_semantics"],
            "filter_semantics carries the Gate 1 fix verbatim",
        )
        check(
            "NOT used to filter rows" in out["filter_semantics"],
            "filter_semantics states account_id does not filter",
        )
        print(f"    [patterns] {out['decision_counts']} symbols={out['symbol_count']}")

        # ---------------- Case 4b: patterns with no account_id ----------------
        print("\n[Case 4b] patterns without account_id -> INSUFFICIENT_DATA")
        r = _run_cli(seeded, "patterns")
        status, json_text = _split_status_line(r.stdout)
        check(r.returncode == 1, "exit code 1")
        check(status == "INSUFFICIENT_DATA", f"status is INSUFFICIENT_DATA ({status!r})")
        payload = json.loads(json_text)
        check(
            payload["status"] == "INSUFFICIENT_DATA",
            "JSON status is INSUFFICIENT_DATA",
        )
        check(payload["output"] is None, "no fabricated output on failure")

        # ---------------- Case 5: empty db -> fail-closed ----------------
        print("\n[Case 5] evidence on EMPTY db -> INSUFFICIENT_DATA (fail-closed)")
        r = _run_cli(empty, "evidence")
        status, json_text = _split_status_line(r.stdout)
        check(r.returncode == 1, "exit code 1")
        check(
            status == "INSUFFICIENT_DATA",
            f"status is INSUFFICIENT_DATA ({status!r})",
        )
        payload = json.loads(json_text)
        check(payload["status"] == "INSUFFICIENT_DATA", "JSON status matches")
        check(payload["output"] is None, "no fabricated output")
        check(
            _row_counts(empty) == {"ranking_snapshots": 0, "journal_entries": 0},
            "empty db still has 0 rows after the run",
        )

        # ---------------- Case 6: bad date -> DATA_ERROR ----------------
        print("\n[Case 6] patterns with unparseable since -> DATA_ERROR")
        r = _run_cli(seeded, "patterns", "MY-ACC", "not-a-date", "2026-09-30")
        status, json_text = _split_status_line(r.stdout)
        check(r.returncode == 1, "exit code 1")
        check(status == "DATA_ERROR", f"status is DATA_ERROR ({status!r})")
        payload = json.loads(json_text)
        check(payload["status"] == "DATA_ERROR", "JSON status is DATA_ERROR")
        check(payload["output"] is None, "no fabricated output")

        # ---------------- Case 7: EMPIRICAL read-only proof ----------------
        print("\n[Case 7] EMPIRICAL read-only: row counts unchanged after all runs")
        counts_after = _row_counts(seeded)
        print(f"[setup] seeded db counts after  all CLI runs: {counts_after}")
        check(
            counts_after == counts_before,
            f"ranking_snapshots and journal_entries counts identical "
            f"({counts_before} -> {counts_after})",
        )
        empty_after = _row_counts(empty)
        check(
            empty_after == {"ranking_snapshots": 0, "journal_entries": 0},
            f"empty db still empty after CLI run ({empty_after})",
        )

        # ---------------- Case 8: boundary scan of new main.py code ----------------
        print("\n[Case 8] Boundary proofs by source inspection of main.py")
        main_src = (_PROJECT_ROOT / "main.py").read_text(encoding="utf-8")

        # Isolate the new command function + its dispatch block.
        fn_start = main_src.index("def _run_decision_copilot_command")
        fn_end = main_src.index("def _latest_snapshot_for_symbol")
        fn_block = main_src[fn_start:fn_end]
        disp_start = main_src.index('sys.argv[1] == "decision-copilot"')
        disp_block = main_src[disp_start - 2000 : disp_start + 200]
        new_code = fn_block + disp_block

        for write_call in [
            ".create(",
            ".record_outcome(",
            ".save(",
            ".update(",
            ".delete(",
            ".submit_order(",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
        ]:
            check(
                write_call not in new_code,
                f"new code does not contain write call {write_call!r}",
            )

        for write_service in [
            "PaperTradingEngine",
            "ExecutionService",
            "BriefApprovalService",
            "JournalService",
            "OrderRepository",
            "TradeRepository",
            "PositionRepository",
            "RiskLimitsRepository",
            "OrderApprovalRepository",
        ]:
            check(
                write_service not in new_code,
                f"new code does not import {write_service}",
            )

        for perm in ["authorize_tool", "PermissionContext", "ToolPermission"]:
            check(perm not in new_code, f"new code does not reference {perm}")

        # No apply/confirm/write/fix/decide/submit flag exists in any form.
        # Scanned as literal argv-parsing constructs and as bare double-dash
        # flags, so prose in the docstring ("no apply/confirm/... flag")
        # cannot mask a real one and a real one cannot hide in prose.
        for flag in [
            "--apply",
            "--confirm",
            "--write",
            "--fix",
            "--decide",
            "--submit",
            "--execute",
            "--commit",
            "--set",
        ]:
            check(flag not in new_code, f"no {flag} flag in new code")
        # A real flag would be *compared against* argv, e.g.
        # `argv[0] == "--apply"`. Literal help text that merely starts with
        # "--" (e.g. "  patterns  ... -- all three required") is not a flag.
        flag_comparisons = [
            ln.strip()
            for ln in new_code.splitlines()
            if not ln.strip().startswith("#")
            and any(cmp_op in ln for cmp_op in ['== "--', "startswith(\"--"])
        ]
        check(
            not flag_comparisons,
            f"new code never compares argv against a double-dash flag "
            f"({flag_comparisons})",
        )

        # Non-registration: skill still absent from DI surfaces.
        for path, label in [
            ("Core/composition_root.py", "Core/composition_root.py"),
            ("Orchestration/skill_registry.py", "Orchestration/skill_registry.py"),
        ]:
            p = _PROJECT_ROOT / path
            if p.exists():
                check(
                    "DecisionCopilotSkill" not in p.read_text(encoding="utf-8"),
                    f"DecisionCopilotSkill absent from {label}",
                )
        check(
            'from Orchestration.decision_copilot import DecisionCopilotSkill'
            in new_code,
            "skill imported locally inside the handler (not via DI)",
        )
        check(
            "DecisionCopilotSkill" not in main_src.split("def _run_decision_copilot_command")[0],
            "no module-scope import of DecisionCopilotSkill in main.py",
        )
        # Shared manager, not a second one.
        check(
            "DatabaseManager(" not in new_code
            and "SQLiteDatabase(" not in new_code
            and "DatabaseConfig" not in new_code,
            "handler builds no second DatabaseManager (reuses app.database_manager)",
        )
        check(
            "app.database_manager" in new_code,
            "handler explicitly reuses app.database_manager",
        )


if __name__ == "__main__":
    run_cases()
    print(f"\nTotal: {_PASS + _FAIL}, Passed: {_PASS}, Failed: {_FAIL}")
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    sys.exit(0 if _FAIL == 0 else 1)
