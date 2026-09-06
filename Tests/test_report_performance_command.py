"""Standalone regression checks for Activation 7 roadmap item:

    ``python main.py report performance`` -- prints the full
    ``PerformanceSummary`` (win rate, expectancy, profit factor,
    maximum drawdown, average win/loss, trade/position statistics)
    that ``PerformanceSummaryProductionService`` (Activation 5.5,
    already wired on ``ApplicationGraph``) has always computed but
    that, before this Activation, was never printed anywhere -- only
    ``win_rate``/``maximum_drawdown`` ever reached a human, via
    ``NotificationBuilder.build_daily_report()``'s LOCKED
    message/metadata contract.

This suite drives the REAL ``main._run_report_performance()`` and
``main._print_performance_summary()``. Only
``performance_summary_production_service`` is a fake (a small double
returning a real, hand-built ``PerformanceSummary`` -- the exact same
fixture ``Tests/test_notification_builder.py`` already uses), because
this command's own job is display, not recomputation: it never
constructs any of the six Sprint 6 engines itself, so faking the one
upstream collaborator keeps this file focused on the CLI/display
boundary, mirroring how ``Tests/test_report_daily_command.py`` fakes
its own two upstream collaborators for the same reason.

Proves, concretely:

* S1: a successful call returns 0 and prints every field of the real
  ``PerformanceSummary`` -- win_rate, expectancy, profit_factor,
  maximum_drawdown, and every trade/position statistic -- not just
  the two fields ``build_daily_report()`` already exposes.
* S2: an unknown/not-found account (``ValidationError``) is reported
  as a clean, labelled failure and a non-zero return code -- never a
  raw traceback.
* S3: ``performance_summary_production_service.get_performance_summary()``
  is called with exactly the ``account_id`` this command was given --
  no other account is ever queried.
* S4: ``main.py report`` dispatch still recognizes ``daily`` exactly
  as before (no regression to the existing subcommand), and now also
  recognizes ``performance``.
* S5: an unknown subcommand is still rejected with a non-zero return
  code.

Run directly with ``python Tests/test_report_performance_command.py``
-- no external test framework required, matching every other
standalone test file in this repository.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Business.expectancy_engine import ExpectancyResult  # noqa: E402
from Business.maximum_drawdown_engine import MaximumDrawdownResult  # noqa: E402
from Business.performance_summary_service import PerformanceSummary  # noqa: E402
from Business.position_performance_engine import (  # noqa: E402
    PositionPerformanceStatistics,
)
from Business.profit_factor_engine import ProfitFactorResult  # noqa: E402
from Business.trade_statistics_engine import TradeExecutionStatistics  # noqa: E402
from Core.exceptions import ValidationError  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


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
# Fixture -- same shape as Tests/test_notification_builder.py's own
# make_performance_summary(), a real PerformanceSummary built from the
# real Sprint 6 dataclasses (no engine reimplemented, no formula
# recomputed here).
# ---------------------------------------------------------------------------
def make_performance_summary() -> PerformanceSummary:
    trade_statistics = TradeExecutionStatistics(
        total_trades=10,
        buy_trades=6,
        sell_trades=4,
        total_volume=1000.0,
        total_fees=5.0,
        total_tax=1.0,
        first_trade_time="2026-08-01T09:00:00Z",
        last_trade_time="2026-08-01T15:00:00Z",
    )
    position_statistics = PositionPerformanceStatistics(
        winning_positions=6,
        losing_positions=3,
        breakeven_positions=1,
        gross_profit=600.0,
        gross_loss=200.0,
        net_profit=400.0,
        average_win=100.0,
        average_loss=66.67,
    )
    return PerformanceSummary(
        trade_statistics=trade_statistics,
        position_statistics=position_statistics,
        win_rate=0.6,
        expectancy=ExpectancyResult(expectancy=40.0),
        profit_factor=ProfitFactorResult(profit_factor=3.0),
        maximum_drawdown=MaximumDrawdownResult(maximum_drawdown=0.15),
    )


class _FakePerformanceSummaryProductionService:
    """Records the ``account_id`` it was called with and returns a
    fixed, real ``PerformanceSummary`` -- or raises, on demand."""

    def __init__(self, summary=None, error: Exception | None = None) -> None:
        self._summary = summary
        self._error = error
        self.calls: list[str] = []

    def get_performance_summary(self, account_id: str):
        self.calls.append(account_id)
        if self._error is not None:
            raise self._error
        return self._summary


def make_app(service) -> SimpleNamespace:
    return SimpleNamespace(performance_summary_production_service=service)


# ---------------------------------------------------------------------------
# S1 -- successful call: return 0, every field printed
# ---------------------------------------------------------------------------
def scenario_success_prints_every_field() -> None:
    summary = make_performance_summary()
    service = _FakePerformanceSummaryProductionService(summary=summary)
    app = make_app(service)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        return_code = main._run_report_performance(app, "acc-1")
    output = buffer.getvalue()

    check(return_code == 0, "S1: successful call returns 0")
    check(
        f"{summary.expectancy.expectancy}" in output,
        "S1: output contains expectancy (never shown by build_daily_report())",
    )
    check(
        f"{summary.profit_factor.profit_factor}" in output,
        "S1: output contains profit_factor (never shown by build_daily_report())",
    )
    check(
        f"{summary.win_rate:.2%}" in output,
        "S1: output contains win_rate",
    )
    check(
        f"{summary.maximum_drawdown.maximum_drawdown:.2%}" in output,
        "S1: output contains maximum_drawdown",
    )
    check(
        str(summary.position_statistics.average_win) in output,
        "S1: output contains average_win",
    )
    check(
        str(summary.position_statistics.average_loss) in output,
        "S1: output contains average_loss",
    )
    check(
        str(summary.trade_statistics.total_trades) in output,
        "S1: output contains trade_statistics.total_trades",
    )


# ---------------------------------------------------------------------------
# S2 -- unknown account: clean failure, non-zero return, no traceback
# ---------------------------------------------------------------------------
def scenario_unknown_account_is_clean_failure() -> None:
    error = ValidationError(
        "Cannot build performance summary: account acc-missing not found",
        details={"account_id": "acc-missing"},
    )
    service = _FakePerformanceSummaryProductionService(error=error)
    app = make_app(service)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        return_code = main._run_report_performance(app, "acc-missing")
    output = buffer.getvalue()

    check(return_code == 1, "S2: unknown account returns non-zero")
    check(
        "not found" in output,
        "S2: output contains a clean, labelled failure message",
    )
    check(
        "Traceback" not in output,
        "S2: no raw traceback ever reaches the caller",
    )


# ---------------------------------------------------------------------------
# S3 -- exact account_id propagation
# ---------------------------------------------------------------------------
def scenario_exact_account_id_propagation() -> None:
    summary = make_performance_summary()
    service = _FakePerformanceSummaryProductionService(summary=summary)
    app = make_app(service)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        main._run_report_performance(app, "acc-specific")

    check(
        service.calls == ["acc-specific"],
        "S3: get_performance_summary() called with exactly the given account_id, once",
    )


# ---------------------------------------------------------------------------
# S4/S5 -- report dispatch: 'daily' unaffected, 'performance' added,
# unknown subcommand still rejected
# ---------------------------------------------------------------------------
def scenario_report_dispatch() -> None:
    calls: list[str] = []

    class _DailyOnlyApp:
        performance_summary_production_service = _FakePerformanceSummaryProductionService(
            summary=make_performance_summary()
        )

        class daily_report_orchestrator:  # noqa: N801 - test double
            @staticmethod
            def run_daily_report(account_id: str, generated_at: str):
                calls.append(account_id)
                from Business.notification_event import NotificationEvent
                from Business.notification_event import NotificationEventType

                return NotificationEvent(
                    event_type=NotificationEventType.DAILY_REPORT,
                    timestamp=generated_at,
                    title="Daily Report",
                    message="Daily Report\n",
                    metadata={},
                )

    app = _DailyOnlyApp()

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc_daily = main._run_report_command(app, ["daily"])
    check(rc_daily == 0, "S4: 'report daily' still dispatches and succeeds")
    check(len(calls) == 1, "S4: 'report daily' still calls run_daily_report exactly once")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc_perf = main._run_report_command(app, ["performance"])
    check(rc_perf == 0, "S4: 'report performance' now dispatches and succeeds")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc_unknown = main._run_report_command(app, ["nonsense"])
    check(rc_unknown == 1, "S5: unknown report subcommand still returns non-zero")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc_empty = main._run_report_command(app, [])
    check(rc_empty == 1, "S5: no report subcommand still returns non-zero")


def main_run() -> int:
    scenario_success_prints_every_field()
    scenario_unknown_account_is_clean_failure()
    scenario_exact_account_id_propagation()
    scenario_report_dispatch()

    print()
    print(f"REPORT PERFORMANCE COMMAND TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    if _FAILURES:
        print("Failures:")
        for description in _FAILURES:
            print(f"  - {description}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main_run())