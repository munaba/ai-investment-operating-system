"""Activation 12 Scheduler -- market-close recap wiring proof.

Direct executable proof suite; intentionally not pytest-discoverable, matching
this repository's existing Activation 12 proof-script convention.
"""
from __future__ import annotations

import contextlib
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from Core.bootstrap import DEFAULT_PAPER_ACCOUNT_ID  # noqa: E402


@dataclass
class _FakeOrchestrator:
    calls: list

    def run_daily_report(self, account_id: str, generated_at: str):
        self.calls.append((account_id, generated_at))
        return "market-close-event"


@dataclass
class _FakeApp:
    daily_report_orchestrator: _FakeOrchestrator


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def test_reuses_existing_scan_and_performance_capabilities():
    calls = []

    class FakeScan:
        def run_scan(self, generated_at):
            calls.append(("scan", generated_at))
            return "scan-report"

    class FakePerf:
        def get_performance_summary(self, account_id):
            calls.append(("performance", account_id))
            return "performance-summary"

    class FakeApp:
        manual_scan_service = FakeScan()
        performance_summary_production_service = FakePerf()

    with patch.object(main, "_print_manual_scan_report", lambda report: None), patch.object(
        main, "_print_performance_summary", lambda performance: None
    ):
        result = main._scheduler_market_close_recap_job(FakeApp())

    check(result["report"] == "scan-report", "recap returns the exact scan result")
    check(result["performance"] == "performance-summary", "recap returns the exact performance result")
    check([kind for kind, _ in calls] == ["scan", "performance"],
          "recap uses existing scan then performance capabilities")
    check(calls[1][1] == DEFAULT_PAPER_ACCOUNT_ID, "default paper account is reused")
    check(calls[0][1].endswith("+00:00"), "scheduler supplies a UTC ISO-8601 timestamp")


def test_no_second_or_new_report_implementation():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    marker = "def _scheduler_market_close_recap_job"
    start = source.index(marker)
    end = source.index("def _scheduler_health_job", start)
    block = source[start:end]
    check("DailyReportOrchestrator" not in block, "recap does not depend on Telegram notification orchestration")
    check("ManualScanService(" not in block, "job does not construct a new scan service")
    check("PerformanceSummaryProductionService(" not in block, "job does not construct a new performance service")


def test_tick_schedules_four_fifo_jobs():
    scheduled = []
    executed = []

    class FakeScheduler:
        def schedule(self, host, agents, context, iterations):
            scheduled.extend(agents)
        def tick(self):
            return tuple(agent.run(object(), 1) for agent in scheduled)

    class Scan:
        def run_scan(self, generated_at):
            executed.append("scan")
            return "scan"

    class Perf:
        def get_performance_summary(self, account_id):
            executed.append("performance")
            return "performance"

    class Daily:
        def run_daily_report(self, account_id, generated_at):
            executed.append("recap")
            return "daily"

    class FakeApp:
        scheduler = FakeScheduler()
        manual_scan_service = Scan()
        performance_summary_production_service = Perf()
        daily_report_orchestrator = Daily()

    with patch.object(main, "run_doctor_command", lambda: executed.append("doctor")), patch.object(
        main, "_print_manual_scan_report", lambda report: None
    ), patch.object(main, "_print_performance_summary", lambda performance: None):
        app = FakeApp()
        rc = main._run_scheduler_tick_command(app, ["tick"])

    check(rc == 0, "scheduler tick command returns success")
    check(len(scheduled) == 4, "scheduler tick schedules exactly four jobs")
    check(executed == ["scan", "performance", "doctor", "scan", "performance"],
          "jobs execute FIFO: scan -> performance -> doctor -> market-close recap (scan + performance)")


if __name__ == "__main__":
    tests = (
        test_reuses_existing_scan_and_performance_capabilities,
        test_no_second_or_new_report_implementation,
        test_tick_schedules_four_fifo_jobs,
    )
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL: {test.__name__}: {exc}")
    print(f"ACTIVATION 12 MARKET-CLOSE RECAP: {passed} scenario(s) PASS / {failed} FAIL")
    raise SystemExit(0 if failed == 0 else 1)
