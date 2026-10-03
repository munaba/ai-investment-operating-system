"""Section 2.8 CLI scanner -- acceptance-gate proof script.

Calls the REAL argv-dispatch code added to ``main.py``
(``_run_watchlist_command`` / ``_run_scan_command``) against the REAL
sqlite database at DB_PATH, built through the REAL
``Core.composition_root.build_application()`` graph -- same
``ManualScanService`` / ``RankingEngine`` / ``RecommendationService`` /
``ReportService`` / ``SnapshotRepository`` the production CLI uses.

Only one substitution is made, at the same boundary the project's own
``activation_2_7_proof.py`` already established as its accepted
"production proof" pattern: ``app.manual_scan_service``'s private
``_watchlist_scanner`` is swapped for a fake that returns distinct,
realistic per-ticker evidence for BBCA/BMRI/TLKM and a genuine failure
for ASII (no "watchlist" SkillResult at all -- the same condition a
real provider outage for one ticker would produce, and the same
condition ``WatchlistScanner``/``RankingEngine`` already handle in
production). This substitution exists ONLY because the current
production ``MarketPriceTool``/``MarketNewsTool``/``MarketFundamentalTool``
chain has no real per-ticker market-data source wired yet (confirmed
separately: a live ``python main.py scan --market idx`` run currently
returns identical INSUFFICIENT_DATA/SELL/LOW for every ticker, since
only ``symbol`` is ever passed through ``Task.metadata``, never a real
price/news feed) -- that gap is pre-existing and outside this CLI
task's scope. Everything downstream of ``WatchlistScanner.scan()`` in
this script is the unmodified production pipeline, reached through the
unmodified production CLI functions.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from Core.composition_root import build_application
from Orchestration.skill_result import SkillResult
import main as cli

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


class FakeWatchlistScanner:
    """Same fake-data pattern as ``activation_2_7_proof.py``: three
    tickers with distinct, realistic evidence, one (ASII) simulating a
    genuine provider failure (no "watchlist" SkillResult at all).
    """

    def scan(self):
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
            "BMRI": {
                "watchlist": SkillResult(
                    success=True,
                    output={
                        "watchlist": [
                            {
                                "priority": 2,
                                "symbol": "BMRI",
                                "recommendation": "WAIT",
                                "confidence": "MEDIUM",
                                "summary": "Sideways consolidation, no clear signal yet.",
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
                                "priority": 3,
                                "symbol": "TLKM",
                                "recommendation": "SELL",
                                "confidence": "LOW",
                                "summary": "Bearish divergence on weakening subscriber growth.",
                            }
                        ]
                    },
                )
            },
            "ASII": {
                "portfolio": SkillResult(success=True, output={"ranking": []}),
            },
        }


def main() -> int:
    print("=" * 70)
    print("[Setup] watchlist add BBCA BMRI TLKM ASII (real CLI function)")
    print("=" * 70)
    app = build_application()
    rc = cli._run_watchlist_command(app, ["add", "BBCA", "BMRI", "TLKM", "ASII"])
    check(rc == 0, "watchlist add exited 0")
    tickers = app.watchlist_repository.list_all()
    check(tickers == ["BBCA", "BMRI", "TLKM", "ASII"], f"watchlist persisted: {tickers}")

    print("\n" + "=" * 70)
    print("[Success + Failure case] real _run_scan_command(), scanner boundary faked")
    print("=" * 70)
    app.manual_scan_service._watchlist_scanner = FakeWatchlistScanner()
    rc = cli._run_scan_command(app, ["--market", "idx"])
    check(rc == 0, "scan --market idx exited 0")

    rows = {
        r.symbol: r
        for r in app.snapshot_repository.list_all()
    }
    check(len(rows) == 4, f"4 snapshot rows persisted (3 success + 1 error): {list(rows)}")

    scores = {rows[s].score for s in ("BBCA", "BMRI", "TLKM")}
    check(len(scores) == 3, f"score berbeda for the 3 successful tickers: {scores}")
    evidence = {rows[s].evidence_summary for s in ("BBCA", "BMRI", "TLKM")}
    check(len(evidence) == 3, "evidence berbeda for the 3 successful tickers")
    ranks = sorted(rows[s].rank for s in ("BBCA", "BMRI", "TLKM"))
    check(ranks == [1, 2, 3], f"rank unik dan hasil terurut: {ranks}")
    check(
        [rows[s].rank for s in ("BBCA", "BMRI", "TLKM")] == sorted(
            [rows[s].rank for s in ("BBCA", "BMRI", "TLKM")]
        ),
        "BUY > WAIT > SELL ordering reflected in rank (score descending)",
    )

    check(rows["ASII"].status == "error", "ASII (failing ticker) persisted with status='error' (-> DATA_ERROR)")
    check(rows["ASII"].recommendation is None, "ASII never became BUY/SELL/WAIT")
    check(rows["ASII"].rank is None, "ASII carries no rank (not in valid ranking)")
    check(
        rows["BBCA"].status == "success" and rows["BMRI"].status == "success" and rows["TLKM"].status == "success",
        "BBCA/BMRI/TLKM all still processed despite ASII failing",
    )

    print("\n" + "=" * 70)
    print("[Restart case] fresh OS process re-reads via the real CLI")
    print("=" * 70)
    result = subprocess.run(
        [sys.executable, "main.py", "watchlist", "list"],
        cwd=str(Path(__file__).resolve().parent),
        env={**os.environ},
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    check("BBCA" in result.stdout and "ASII" in result.stdout, "watchlist survives a brand-new process (fresh build_application())")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    reread = con.execute(
        "SELECT * FROM ranking_snapshots WHERE symbol = 'ASII' ORDER BY snapshot_id DESC LIMIT 1"
    ).fetchone()
    con.close()
    check(reread is not None, "ASII's DATA_ERROR snapshot row is still readable after 'restart' (new connection)")
    check(reread["status"] == "error", "status still 'error' after restart")

    print("\n" + "=" * 70)
    print(f"SECTION 2.8 PROOF RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 70)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())