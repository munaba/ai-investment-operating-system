"""Standalone regression checks for the Sprint 5 STEP 7 manual scan
command (``main.py``'s ``scan`` REPL command).

Covers (LOCKED DECISION):

* ``_run_manual_scan(app)`` calls ``app.manual_scan_service.run_scan()``
  exactly once -- never ``WatchlistScanner``/``RankingEngine``/
  ``RecommendationService``/``ReportService``/``SnapshotRepository``
  directly (LOCKED DECISION 1);
* ``generated_at`` is created in the command layer (a plausible,
  ``datetime.fromisoformat``-parseable string) and passed through to
  ``run_scan()`` unchanged (LOCKED DECISION 3);
* the returned ``Report`` is printed to the console (LOCKED DECISION 4);
* an empty watchlist (``total_symbols == 0``) prints exactly
  ``"No symbols found."`` and does not raise (LOCKED DECISION 6);
* many recommendations are all printed, with correct BUY/WAIT/SELL
  counts (LOCKED DECISION 4);
* an exception raised by ``ManualScanService.run_scan()`` propagates
  unchanged out of ``_run_manual_scan()`` -- no wrapper, no custom
  error type (LOCKED DECISION 7);
* ``main()``'s REPL loop calls ``build_application()`` exactly once
  and dispatches a typed ``"scan"`` command to ``_run_manual_scan()``,
  reusing the one already-built ``app`` -- the same dispatch
  mechanism already used by the existing ``"auto "`` command (LOCKED
  DECISION 2, "Gunakan mekanisme command existing project").

Run directly with ``python Tests/test_manual_scan_command.py`` -- no
external test framework required, matching
``test_manual_scan_service.py``. Uses only the stdlib
``unittest.mock`` for patching ``input()``/``build_application()``/
``validate_runtime_environment()`` at the ``main()`` boundary.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import main  # noqa: E402
from Business.recommendation_service import Recommendation  # noqa: E402
from Business.report_service import Report  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES: List[str] = []


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
# Fakes
# ---------------------------------------------------------------------------


class FakeManualScanService:
    """Stands in for ``Business.manual_scan_service.ManualScanService``.

    Records every ``run_scan(generated_at)`` call's argument, and
    either returns a caller-supplied ``Report`` or raises a
    caller-supplied exception.
    """

    def __init__(self, report: Report | None = None, raises: Exception | None = None) -> None:
        self._report = report
        self._raises = raises
        self.calls: List[str] = []

    def run_scan(self, generated_at: str) -> Report:
        self.calls.append(generated_at)
        if self._raises is not None:
            raise self._raises
        assert self._report is not None
        return self._report


class FakeApp:
    """Stands in for ``Core.composition_root.ApplicationGraph`` -- only
    the one attribute ``_run_manual_scan``/``main()`` actually read.
    """

    def __init__(self, manual_scan_service: FakeManualScanService) -> None:
        self.manual_scan_service = manual_scan_service
        self.agent_name = "fake-agent"
        self.provider_name = "fake-provider"


def _report(recommendations: List[Recommendation], generated_at: str = "irrelevant") -> Report:
    return Report(
        generated_at=generated_at,
        recommendations=recommendations,
        total_symbols=len(recommendations),
    )


class BoomError(Exception):
    """A distinct, unwrapped exception type used to prove propagation."""


# ---------------------------------------------------------------------------
# Scenarios -- _run_manual_scan() directly
# ---------------------------------------------------------------------------


def scenario_manual_scan_service_called_exactly_once():
    print("\n[Scenario 1] app.manual_scan_service.run_scan() is called exactly once")
    service = FakeManualScanService(report=_report([]))
    app = FakeApp(service)

    with redirect_stdout(io.StringIO()):
        main._run_manual_scan(app)

    check(len(service.calls) == 1, "run_scan() was called exactly once")


def scenario_generated_at_created_in_command_layer_and_passed_through():
    print("\n[Scenario 2] generated_at is created here and passed through to run_scan()")
    service = FakeManualScanService(report=_report([]))
    app = FakeApp(service)

    with redirect_stdout(io.StringIO()):
        main._run_manual_scan(app)

    check(len(service.calls) == 1, "exactly one generated_at value was recorded")
    generated_at = service.calls[0]
    check(isinstance(generated_at, str), "generated_at passed to run_scan() is a str")
    from datetime import datetime as _dt

    parsed = None
    try:
        parsed = _dt.fromisoformat(generated_at)
    except ValueError:
        pass
    check(parsed is not None, "generated_at is a plausible, parseable ISO-8601 timestamp")


def scenario_report_is_displayed():
    print("\n[Scenario 3] the returned Report is displayed on the console")
    recs = [Recommendation(symbol="BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1)]
    service = FakeManualScanService(report=_report(recs))
    app = FakeApp(service)

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_manual_scan(app)
    output = buf.getvalue()

    check("Manual Scan Completed" in output, "output announces scan completion")
    check("Total Symbols : 1" in output, "output reports the correct total symbol count")
    check("BBCA" in output, "output includes the recommendation's symbol")
    check("BUY" in output, "output includes the recommendation's recommendation label")
    check("HIGH" in output, "output includes the recommendation's confidence")


def scenario_empty_watchlist_prints_no_symbols_found():
    print("\n[Scenario 4] empty watchlist prints 'No symbols found.' and does not raise")
    service = FakeManualScanService(report=_report([]))
    app = FakeApp(service)

    buf = io.StringIO()
    raised = False
    try:
        with redirect_stdout(buf):
            main._run_manual_scan(app)
    except Exception:  # noqa: BLE001
        raised = True
    output = buf.getvalue()

    check(not raised, "an empty watchlist does not raise")
    check(output.strip() == "No symbols found.", "output is exactly 'No symbols found.' for an empty watchlist")
    check("Manual Scan Completed" not in output, "the normal report header is not printed for an empty watchlist")


def scenario_many_recommendations_all_displayed():
    print("\n[Scenario 5] many recommendations are all printed with correct counts")
    recs = [
        Recommendation(symbol="BBCA", recommendation="BUY", confidence="HIGH", priority=1, rank=1),
        Recommendation(symbol="TLKM", recommendation="WAIT", confidence="MEDIUM", priority=2, rank=2),
        Recommendation(symbol="BMRI", recommendation="SELL", confidence="LOW", priority=3, rank=3),
        Recommendation(symbol="ASII", recommendation="BUY", confidence="MEDIUM", priority=4, rank=4),
    ]
    service = FakeManualScanService(report=_report(recs))
    app = FakeApp(service)

    buf = io.StringIO()
    with redirect_stdout(buf):
        main._run_manual_scan(app)
    output = buf.getvalue()

    check("Total Symbols : 4" in output, "output reports total_symbols == 4")
    check("BUY  : 2" in output, "output reports the correct BUY count")
    check("WAIT : 1" in output, "output reports the correct WAIT count")
    check("SELL : 1" in output, "output reports the correct SELL count")
    for symbol in ("BBCA", "TLKM", "BMRI", "ASII"):
        check(symbol in output, f"output includes symbol {symbol}")


def scenario_exception_propagates_unchanged():
    print("\n[Scenario 6] an exception from run_scan() propagates unchanged, no wrapper")
    boom = BoomError("watchlist repository exploded")
    service = FakeManualScanService(raises=boom)
    app = FakeApp(service)

    raised_exc = None
    try:
        with redirect_stdout(io.StringIO()):
            main._run_manual_scan(app)
    except Exception as exc:  # noqa: BLE001
        raised_exc = exc

    check(raised_exc is boom, "the exact same exception instance propagates out of _run_manual_scan()")
    check(type(raised_exc) is BoomError, "the exception type is not wrapped or replaced")


# ---------------------------------------------------------------------------
# Scenario -- main()'s REPL dispatch
# ---------------------------------------------------------------------------


def scenario_main_builds_application_once_and_dispatches_scan():
    print("\n[Scenario 7] main() calls build_application() once and dispatches 'scan' to _run_manual_scan()")
    service = FakeManualScanService(report=_report([]))
    fake_app = FakeApp(service)

    inputs = iter(["scan"])

    def fake_input(prompt: str = "") -> str:
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError()

    with patch.object(main, "validate_runtime_environment") as mock_validate, patch.object(
        main, "build_application", return_value=fake_app
    ) as mock_build, patch("builtins.input", side_effect=fake_input):
        with redirect_stdout(io.StringIO()):
            main.main()

    # Activation 1.5 LOCKED DECISION OVERRIDE (supersedes this scenario's
    # original "still calls validate_runtime_environment() once"
    # assertion): validation now happens at the command boundary, not at
    # application startup. "scan" has no provider dependency (see this
    # module's FakeApp/ManualScanService collaborators -- no provider
    # anywhere in that chain), so a scan-only REPL session must call
    # validate_runtime_environment() zero times.
    check(
        mock_validate.call_count == 0,
        "main() does NOT call validate_runtime_environment() for a scan-only session (Activation 1.5)",
    )
    check(mock_build.call_count == 1, "main() calls build_application() exactly once")
    check(len(service.calls) == 1, "typing 'scan' dispatches to manual_scan_service.run_scan() exactly once")


def main_test() -> int:
    scenario_manual_scan_service_called_exactly_once()
    scenario_generated_at_created_in_command_layer_and_passed_through()
    scenario_report_is_displayed()
    scenario_empty_watchlist_prints_no_symbols_found()
    scenario_many_recommendations_all_displayed()
    scenario_exception_propagates_unchanged()
    scenario_main_builds_application_once_and_dispatches_scan()

    print("\n" + "=" * 60)
    print(f"SPRINT 5 STEP 7 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main_test())