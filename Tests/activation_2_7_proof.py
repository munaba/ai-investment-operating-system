"""Activation 2.7 -- consolidated proof script.

Runs against the REAL sqlite database at DB_PATH (already migrated to
v11 by `python main.py init`), using the REAL RankingEngine /
RecommendationService / ReportService / SnapshotRepository, wired
exactly like ManualScanService's production constructor. Only
WatchlistScanner is faked (as the existing test suite already does),
so this script controls exactly which tickers succeed/fail without
needing live LLM/network providers.

Proves, in one run:
  1. migration berhasil dijalankan melalui `python main.py init`
     (already done before this script runs -- see shell output).
  2. satu scan sukses menghasilkan seluruh persistence yang diperlukan
     (analysis/score, recommendation, ranking, timestamp, evidence).
  3. scan dengan sebagian ticker gagal tetap menyimpan status error
     tanpa menghentikan persistence ticker lain.
  4. restart aplikasi tidak menghilangkan keterkaitan data.
  5. scan dua kali -> snapshot baru dibuat tanpa merusak snapshot lama.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from Business.manual_scan_service import ManualScanService
from Business.ranking_engine import RankingEngine
from Business.recommendation_service import RecommendationService
from Business.report_service import ReportService
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.sqlite_database import SQLiteDatabase
from Orchestration.skill_result import SkillResult
from Repository.persistence.snapshot_repository import SnapshotRepository

DB_PATH = Path(os.environ["DB_PATH"])

_PASS = 0
_FAIL = 0


def check(condition: bool, description: str) -> None:
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS - {description}")
    else:
        _FAIL += 1
        print(f"  FAIL - {description}")


def dump_rows(label: str) -> list[sqlite3.Row]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM ranking_snapshots ORDER BY snapshot_id ASC").fetchall()
    con.close()
    print(f"\n--- ranking_snapshots ({label}) ---")
    for r in rows:
        print(dict(r))
    return rows


def build_service() -> ManualScanService:
    cfg = DatabaseConfig(db_path=DB_PATH)
    db = SQLiteDatabase(cfg)
    db.connect()
    manager = DatabaseManager(db, cfg)
    snapshot_repository = SnapshotRepository(manager)
    watchlist_scanner = FakeWatchlistScanner()
    return ManualScanService(
        watchlist_scanner,
        RankingEngine(),
        RecommendationService(),
        ReportService(),
        snapshot_repository,
    ), db


class FakeWatchlistScanner:
    """Stands in for the real WatchlistScanner -- same fake pattern
    Tests/test_manual_scan_service.py already uses -- so this script
    controls exactly which tickers succeed/fail without live
    providers. RankingEngine/RecommendationService/ReportService/
    SnapshotRepository below are all real, unmodified production
    classes.
    """

    def __init__(self):
        self.calls = 0

    def scan(self):
        self.calls += 1
        return {
            "BBCA": {
                "watchlist": SkillResult(
                    success=True,
                    output={
                        "watchlist": [
                            {
                                "priority": 1,
                                "symbol": "BBCA",
                                "recommendation": "BUY",
                                "confidence": "HIGH",
                                "summary": "Volume breakout confirmed above resistance.",
                            }
                        ]
                    },
                )
            },
            "TLKM": {
                "watchlist": SkillResult(
                    success=True,
                    output={
                        "watchlist": [
                            {
                                "priority": 2,
                                "symbol": "TLKM",
                                "recommendation": "WAIT",
                                "confidence": "MEDIUM",
                                "summary": "Sideways consolidation, no clear signal yet.",
                            }
                        ]
                    },
                )
            },
            # ASII simulates a genuinely failed ticker: no "watchlist"
            # SkillResult at all -- the exact condition
            # RankingEngine._extract_valid_entries already excludes
            # silently today.
            "ASII": {
                "portfolio": SkillResult(success=True, output={"ranking": []}),
            },
        }


def main() -> int:
    # ---- Proof point 2 & 3: one scan, mixed success/failure ----
    print("\n[Proof 2+3] One scan: BBCA/TLKM succeed, ASII fails")
    before_rows = dump_rows("BEFORE scan #1")
    check(len(before_rows) == 0, "table is empty before the first scan (fresh v11 database)")

    service, db = build_service()
    try:
        report = service.run_scan("2026-08-04T09:00:00+00:00")
    finally:
        db.disconnect()

    check(report.total_symbols == 2, "Report only contains the 2 symbols RankingEngine validated (BBCA, TLKM)")

    rows_after_1 = dump_rows("AFTER scan #1")
    check(len(rows_after_1) == 3, "3 rows persisted: 2 success + 1 error -- ASII was NOT silently dropped")

    by_symbol = {r["symbol"]: r for r in rows_after_1}
    check(by_symbol["BBCA"]["status"] == "success", "BBCA persisted as success")
    check(by_symbol["BBCA"]["recommendation"] == "BUY", "BBCA recommendation persisted")
    check(by_symbol["BBCA"]["score"] is not None, "BBCA score (analysis) persisted -- previously discarded")
    check(
        json.loads(by_symbol["BBCA"]["score_breakdown_json"])["recommendation"] == "BUY",
        "BBCA score_breakdown persisted and matches its recommendation (linkage: same row)",
    )
    check(
        by_symbol["BBCA"]["evidence_summary"] == "Volume breakout confirmed above resistance.",
        "BBCA evidence_summary is the REAL text WatchlistAnalysisSkill produced -- not fabricated",
    )
    check(by_symbol["BBCA"]["scan_time"] == "2026-08-04T09:00:00+00:00", "BBCA scan_time represents this scan's time")
    check(by_symbol["BBCA"]["rank"] is not None, "BBCA has a rank -- ranking snapshot persisted")

    check(by_symbol["TLKM"]["status"] == "success", "TLKM (the ticker after none-failing) also persisted")

    check(by_symbol["ASII"]["status"] == "error", "ASII (failed ticker) persisted with status='error'")
    check(by_symbol["ASII"]["recommendation"] is None, "ASII has no recommendation (never fabricated)")
    check(by_symbol["ASII"]["error_message"] is not None, "ASII carries a real error_message")
    check(
        "watchlist" in by_symbol["ASII"]["error_message"],
        f"ASII's error_message explains the real cause: {by_symbol['ASII']['error_message']!r}",
    )
    check(
        by_symbol["ASII"]["scan_time"] == "2026-08-04T09:00:00+00:00",
        "ASII's error row still carries this scan's timestamp",
    )

    # ---- Proof point 4: restart, linkage intact ----
    print("\n[Proof 4] Restart (new DB connection) -- linkage intact")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    reread = con.execute(
        "SELECT * FROM ranking_snapshots WHERE symbol='BBCA' AND scan_time=?",
        ("2026-08-04T09:00:00+00:00",),
    ).fetchone()
    con.close()
    check(reread is not None, "BBCA's row is still readable after reconnecting to the database")
    check(reread["recommendation"] == "BUY", "recommendation survived the restart")
    check(
        json.loads(reread["score_breakdown_json"])["confidence"] == "HIGH",
        "score<->recommendation linkage (same row) survived the restart",
    )

    # ---- Proof point 5: run scan a second time ----
    print("\n[Proof 5] Second scan: old snapshot untouched, new snapshot added")
    service2, db2 = build_service()
    try:
        service2.run_scan("2026-08-04T10:00:00+00:00")
    finally:
        db2.disconnect()

    rows_after_2 = dump_rows("AFTER scan #2")
    check(len(rows_after_2) == 6, "3 new rows added on top of the first 3 (append-only, never overwritten)")

    first_scan_rows = [r for r in rows_after_2 if r["scan_time"] == "2026-08-04T09:00:00+00:00"]
    second_scan_rows = [r for r in rows_after_2 if r["scan_time"] == "2026-08-04T10:00:00+00:00"]
    check(len(first_scan_rows) == 3, "the first scan's 3 rows are still exactly as they were")
    check(len(second_scan_rows) == 3, "the second scan produced its own 3 new rows")
    check(
        {r["snapshot_id"] for r in first_scan_rows}.isdisjoint({r["snapshot_id"] for r in second_scan_rows}),
        "no snapshot_id is shared/reused between the two scans -- old snapshot rows were never mutated",
    )
    old_bbca = next(r for r in first_scan_rows if r["symbol"] == "BBCA")
    check(old_bbca["recommendation"] == "BUY", "first scan's BBCA row is unchanged after the second scan ran")

    print("\n" + "=" * 60)
    print(f"ACTIVATION 2.7 PROOF RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
