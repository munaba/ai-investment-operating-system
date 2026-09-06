from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from Core.self_diagnostic import run_self_diagnostic
from Database.database_config import DatabaseConfig


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_db(path: Path, scan_time: str, account_id: str = "acct-1") -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE ranking_snapshots (scan_time TEXT NOT NULL);
        CREATE TABLE accounts (
            account_id TEXT PRIMARY KEY,
            account_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            currency TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            cash REAL NOT NULL,
            equity REAL NOT NULL,
            buying_power REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
            side TEXT NOT NULL, quantity REAL NOT NULL, requested_price REAL,
            status TEXT NOT NULL, filled_price REAL, filled_quantity REAL, filled_at TEXT,
            created_at TEXT NOT NULL, idempotency_key TEXT
        );
        CREATE TABLE trades (
            trade_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, account_id TEXT NOT NULL,
            symbol TEXT NOT NULL, side TEXT NOT NULL, quantity REAL NOT NULL,
            fill_price REAL NOT NULL, fee REAL NOT NULL, tax REAL NOT NULL,
            executed_at TEXT NOT NULL
        );
        CREATE TABLE positions (
            position_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, symbol TEXT NOT NULL,
            quantity REAL NOT NULL, average_price REAL NOT NULL, realized_pnl REAL NOT NULL,
            buy_fee_accumulated REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    now = "2026-08-20T00:00:00+00:00"
    conn.execute("INSERT INTO ranking_snapshots(scan_time) VALUES (?)", (scan_time,))
    conn.execute(
        "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?)",
        (account_id, "Test", "paper", "IDR", "IDX", 1000, 1000, 1000, now, now),
    )
    conn.commit()
    conn.close()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="a12_diag_") as tmp:
        db = Path(tmp) / "diag.db"
        make_db(db, "2026-08-20T00:00:00+00:00")
        cfg = DatabaseConfig(db_path=db)
        os.environ["AIOS_DATA_STALE_AFTER_HOURS"] = "24"
        sections = run_self_diagnostic(cfg)
        names = {s.name: s for s in sections}
        check(names["Data Freshness"].status == "READY", "fresh data is READY")
        check(names["Account Reconciliation"].status == "READY", "clean account is READY")
        check(names["Notifications"].status == "OPTIONAL MISSING", "unconfigured notifications are optional")

        stale = Path(tmp) / "stale.db"
        make_db(stale, "2026-08-18T00:00:00+00:00")
        stale_sections = run_self_diagnostic(DatabaseConfig(db_path=stale))
        stale_map = {s.name: s for s in stale_sections}
        check(stale_map["Data Freshness"].status == "BLOCKED", "stale data is BLOCKED")

    print("Activation 12 Self-Diagnostic: 4/4 PASS")


if __name__ == "__main__":
    main()
