"""Export a public, read-only snapshot of the AIOS database for the dashboard.

Run from the repository root with the AIOS virtualenv:

    python Dashboard/export_snapshot.py            # reads data/investment_platform.db
    python Dashboard/export_snapshot.py --db PATH   # any other copy

The live database is opened with SQLite's read-only URI mode, so this script
can never modify it. Only the tables listed in ``EXPORTED_TABLES`` are
written; Telegram state (chat ids), raw audit payloads and free-text
operator feedback are deliberately left out.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "investment_platform.db"
DEFAULT_OUT = Path(__file__).resolve().parent / "data" / "snapshot.json"

#: table -> (ORDER BY clause, exported columns). Allowlist only: a table or
#: column not listed here is never exported, so a new column added by a
#: future migration stays private until it is reviewed and added. Operator
#: free text (notes, decision notes, names) is deliberately absent.
EXPORTED_TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ranking_snapshots": ("scan_time, rank", (
        "snapshot_id", "scan_time", "symbol", "status", "recommendation", "confidence", "priority",
        "rank", "score", "score_breakdown_json", "evidence_summary", "error_message",
    )),
    "decision_briefs": ("generated_at", (
        "brief_id", "symbol", "generated_at", "status", "source_snapshot_id", "reason", "entry_price",
        "stop_loss_price", "take_profit_price", "risk_amount", "position_size", "risk_reward_ratio",
    )),
    "scheduler_job_runs": ("started_at", (
        "job_type", "trading_date", "status", "attempt", "started_at", "finished_at", "next_retry_at", "detail",
    )),
    "watchlist": ("ticker", ("ticker", "added_at")),
    "accounts": ("account_id", (
        "account_id", "mode", "currency", "asset_class", "cash", "equity", "buying_power", "created_at", "updated_at",
    )),
    "positions": ("created_at", (
        "position_id", "symbol", "direction", "quantity", "average_price", "realized_pnl", "status",
        "stop_loss", "take_profit", "created_at", "updated_at",
    )),
    "orders": ("created_at", (
        "order_id", "symbol", "action", "quantity", "requested_price", "filled_price", "filled_quantity",
        "status", "created_at", "updated_at", "filled_at",
    )),
    "trades": ("executed_at", (
        "trade_id", "order_id", "symbol", "action", "quantity", "fill_price", "fee", "tax", "executed_at",
    )),
    "portfolio_snapshots": ("timestamp", (
        "snapshot_id", "cash", "market_value", "equity", "realized_pnl", "unrealized_pnl", "exposure",
        "drawdown", "timestamp",
    )),
    "daily_performance": ("timestamp", (
        "start_timestamp", "end_timestamp", "starting_equity", "ending_equity", "realized_result",
        "unrealized_result", "fees", "tax", "net_result", "drawdown", "number_of_signals",
        "number_of_executions", "timestamp",
    )),
    "journal_entries": ("decided_at", (
        "entry_id", "brief_id", "symbol", "decision", "decided_at", "risk_policy_status", "planned_r",
        "outcome_status", "exit_price", "realized_r", "closed_at",
    )),
    "risk_limits": ("id", (
        "reference_capital", "max_risk_per_trade_percent", "max_daily_loss", "max_trades_per_day",
        "loss_streak_cooldown", "allowed_symbols", "updated_at",
    )),
    "operator_observation_windows": ("start_at", (
        "window_id", "start_at", "end_at", "timezone", "status", "created_at", "closed_at",
    )),
    "final_review_records": ("reviewed_at", (
        "review_id", "observation_window_id", "reviewed_at", "evidence_status", "human_decision", "decided_at",
    )),
}


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from Core.redaction import redact_secrets  # noqa: E402 -- needs REPO_ROOT on sys.path


def _scrub(row: dict) -> dict:
    """Redact credential-looking text in every string value (error messages
    from network calls can quote URLs that carry tokens)."""
    return {k: redact_secrets(v) if isinstance(v, str) else v for k, v in row.items()}


def _expected_migration_versions() -> list[int]:
    """Versions declared in the canonical registry (empty if unavailable)."""
    try:
        from Database.migration_registry import all_migrations
    except Exception:  # noqa: BLE001 -- export still works without it
        return []
    return [m.version for m, _domain in all_migrations()]


def _market_holidays() -> list[str]:
    """IDX non-trading weekdays known to the scheduler's calendar, so the
    dashboard's staleness count skips them (it does not import AIOS code)."""
    try:
        from Business.idx_market_calendar import load_idx_market_calendar
    except Exception:  # noqa: BLE001 -- export still works without it
        return []
    return sorted(d.isoformat() for d in load_idx_market_calendar().holiday_dates)


def _signal_evaluation(db_path: Path) -> dict:
    """Pre-registered signal evaluation (needs Yahoo prices); never fails the export."""
    try:
        from Evaluation.signal_evaluation import evaluate, load_signals

        return {"status": "OK", **evaluate(load_signals(db_path))}
    except Exception as exc:  # noqa: BLE001 -- offline, Yahoo down, missing deps
        return {"status": "UNAVAILABLE", "error": redact_secrets(f"{type(exc).__name__}: {exc}")}


def export(db_path: Path, out_path: Path, with_evaluation: bool = True) -> dict:
    if not db_path.is_file():
        raise SystemExit(f"Database not found: {db_path}")

    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables: dict[str, list[dict]] = {}
        for table, (order_by, wanted) in EXPORTED_TABLES.items():
            if table not in existing:
                tables[table] = []
                continue
            present = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            columns = ", ".join(f'"{c}"' for c in wanted if c in present)
            rows = conn.execute(f'SELECT {columns} FROM "{table}" ORDER BY {order_by}').fetchall()
            tables[table] = [_scrub(dict(row)) for row in rows]
        applied = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]

    snapshot = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "migrations": {"applied": applied, "expected": _expected_migration_versions()},
        "market_holidays": _market_holidays(),
        "tables": tables,
    }
    if with_evaluation:
        snapshot["signal_evaluation"] = _signal_evaluation(db_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False), encoding="utf-8")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database to read (read-only)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON file to write")
    parser.add_argument("--no-evaluation", action="store_true", help="skip the signal evaluation (no network)")
    args = parser.parse_args()

    snapshot = export(args.db, args.out, with_evaluation=not args.no_evaluation)
    counts = ", ".join(f"{name}={len(rows)}" for name, rows in snapshot["tables"].items() if rows)
    print(f"Wrote {args.out} ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
