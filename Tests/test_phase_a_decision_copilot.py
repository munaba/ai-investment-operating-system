"""
Phase A proof suite -- ``decision_copilot`` product mode.

Scope:
  - Core.product_mode (new): active_product_mode_name(),
    resolve_product_mode(), ProductModeStatus.
  - Core.doctor (extended): _check_product_mode(), _check_scheduler(),
    and their wiring into run_doctor().
  - main.py: regression proof that no "live"/broker CLI dispatch
    branch exists (Phase A must not fabricate a kill-switch for a code
    path that was never built).

Cakupan skenario:
  A. Default mode (no AIOS_PRODUCT_MODE set) resolves to
     'decision_copilot', recognized, live execution disabled, broker
     credentials not required.
  B. Explicit AIOS_PRODUCT_MODE=decision_copilot resolves identically
     to the default.
  C. Unrecognized AIOS_PRODUCT_MODE value -> recognized=False, but
     fails closed (live_execution_disabled=True,
     broker_credentials_required=True) -- never silently treated as
     safe/permissive.
  D. doctor's new "Product Mode" section reports the three expected
     checks and is READY on a decision_copilot environment.
  E. doctor's new "Product Mode" section reports BLOCKED (not a
     silent pass-through) when AIOS_PRODUCT_MODE is unrecognized.
  F. doctor's new "Scheduler" section is present, READY, and does not
     raise even though there is no persisted scheduler state.
  G. run_doctor() output still contains every pre-existing section
     (regression -- Phase A is additive, not a replacement).
  H. main.py has no "live"/broker CLI dispatch branch (confirms the
     "disabled" claim reflects the actual absence of that code path,
     not merely a config flag layered on top of a live path that still
     exists).
  I. Real CLI proof: "python main.py doctor" runs end-to-end with no
     AIOS_PRODUCT_MODE / no broker-shaped env vars set, exits without
     an unhandled traceback, and its stdout contains the "Product Mode"
     and "Scheduler" sections.

All os.environ mutation is wrapped in try/finally (via _EnvSandbox) so
no scenario leaks state into another test file run in the same
process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


class _EnvSandbox:
    """Set the given env vars for the block, always restoring the exact
    previous state (including "was unset") on exit."""

    def __init__(self, **overrides: Optional[str]) -> None:
        self._overrides = overrides
        self._previous: Dict[str, Optional[str]] = {}

    def __enter__(self) -> "_EnvSandbox":
        for key in self._overrides:
            self._previous[key] = os.environ.get(key)
        for key, value in self._overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def scenario_a_default_mode() -> None:
    print("\n[Scenario A] Default mode (AIOS_PRODUCT_MODE unset) -> decision_copilot")
    import Core.product_mode as product_mode

    with _EnvSandbox(AIOS_PRODUCT_MODE=None):
        status = product_mode.resolve_product_mode()

    check(status.mode == "decision_copilot", "default mode is 'decision_copilot'")
    check(status.recognized is True, "default mode is recognized")
    check(status.live_execution_disabled is True, "default mode disables live execution")
    check(status.broker_credentials_required is False, "default mode does not require broker credentials")


def scenario_b_explicit_decision_copilot() -> None:
    print("\n[Scenario B] Explicit AIOS_PRODUCT_MODE=decision_copilot")
    import Core.product_mode as product_mode

    with _EnvSandbox(AIOS_PRODUCT_MODE="decision_copilot"):
        status = product_mode.resolve_product_mode()

    check(status.mode == "decision_copilot", "explicit mode round-trips as 'decision_copilot'")
    check(status.recognized is True, "explicit decision_copilot is recognized")
    check(status.live_execution_disabled is True, "explicit decision_copilot disables live execution")
    check(status.broker_credentials_required is False, "explicit decision_copilot does not require broker credentials")


def scenario_c_unrecognized_mode_fails_closed() -> None:
    print("\n[Scenario C] Unrecognized AIOS_PRODUCT_MODE fails closed")
    import Core.product_mode as product_mode

    with _EnvSandbox(AIOS_PRODUCT_MODE="full_auto_live_trading"):
        status = product_mode.resolve_product_mode()

    check(status.mode == "full_auto_live_trading", "unrecognized mode value is reported verbatim")
    check(status.recognized is False, "unrecognized mode is NOT silently accepted")
    check(status.live_execution_disabled is True, "unrecognized mode still reports live execution disabled (fail-closed)")
    check(status.broker_credentials_required is True, "unrecognized mode conservatively reports broker credentials as required")


def scenario_d_doctor_product_mode_section_ready() -> None:
    print("\n[Scenario D] doctor's Product Mode section is READY under decision_copilot")
    import Core.doctor as doctor

    with _EnvSandbox(AIOS_PRODUCT_MODE="decision_copilot"):
        section = doctor._check_product_mode()

    check(section.name == "Product Mode", "section is named 'Product Mode'")
    check(section.status == doctor.READY, "section is READY under decision_copilot")
    labels = {c.label for c in section.checks}
    check(
        labels == {"Active mode", "Broker/live execution", "Broker credentials"},
        f"section has exactly the three expected checks, got {labels}",
    )
    for c in section.checks:
        check(c.status == doctor.READY, f"'{c.label}' is READY")


def scenario_e_doctor_product_mode_section_blocked_on_unknown_mode() -> None:
    print("\n[Scenario E] doctor's Product Mode section is BLOCKED on an unrecognized mode")
    import Core.doctor as doctor

    with _EnvSandbox(AIOS_PRODUCT_MODE="not_a_real_mode"):
        section = doctor._check_product_mode()

    check(section.status == doctor.BLOCKED, "section is BLOCKED (not silently passed through) on an unrecognized mode")
    active_mode_check = next(c for c in section.checks if c.label == "Active mode")
    check(active_mode_check.status == doctor.BLOCKED, "'Active mode' check itself is BLOCKED")
    check("not_a_real_mode" in active_mode_check.detail, "detail names the offending value")


def scenario_f_doctor_scheduler_section() -> None:
    print("\n[Scenario F] doctor's Scheduler section is present and READY")
    import Core.doctor as doctor

    section = doctor._check_scheduler()
    check(section.name == "Scheduler", "section is named 'Scheduler'")
    check(section.status == doctor.READY, "Scheduler section is READY (module imports cleanly)")
    check(len(section.checks) >= 1, "Scheduler section has at least one concrete check (no empty/silent section)")


def scenario_g_run_doctor_regression() -> None:
    print("\n[Scenario G] run_doctor() still contains every pre-existing section (additive only)")
    import Core.doctor as doctor

    with _EnvSandbox(AIOS_PRODUCT_MODE="decision_copilot"):
        report = doctor.run_doctor()

    names = [s.name for s in report.sections]
    expected_preexisting = [
        "Python",
        "Required Dependencies",
        "Database",
        "Migrations",
        "Telegram",
        "Market Data Provider",
        "Data Freshness",
        "Account Reconciliation",
        "Notifications",
        "Tool Availability",
    ]
    for name in expected_preexisting:
        check(name in names, f"pre-existing section '{name}' is still present")
    check("Product Mode" in names, "new 'Product Mode' section is present")
    check("Scheduler" in names, "new 'Scheduler' section is present")
    check(names[0] == "Product Mode", "'Product Mode' is the first section reported")


def scenario_h_no_live_cli_dispatch() -> None:
    print("\n[Scenario H] main.py has no 'live'/broker CLI dispatch branch")
    main_source = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")

    check('sys.argv[1] == "live"' not in main_source, "no 'live' dispatch branch in main.py")
    check('sys.argv[1] == "broker"' not in main_source, "no 'broker' dispatch branch in main.py")
    check(
        "BROKER_API_KEY" not in main_source and "BROKER_SECRET" not in main_source,
        "no broker-credential env var referenced in main.py",
    )


def scenario_i_real_cli_proof() -> None:
    print("\n[Scenario I] Real CLI proof: 'python main.py doctor' with no broker-shaped env")
    env = dict(os.environ)
    for key in ("AIOS_PRODUCT_MODE", "BROKER_API_KEY", "BROKER_SECRET", "BROKER_ACCOUNT_ID"):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, "main.py", "doctor"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    check(result.returncode in (0, 1), f"'python main.py doctor' exits 0 or 1 (BLOCKED), got {result.returncode}")
    check("Product Mode" in result.stdout, "'Product Mode' section appears in real CLI stdout")
    check("Scheduler" in result.stdout, "'Scheduler' section appears in real CLI stdout")
    check("decision_copilot" in result.stdout, "'decision_copilot' mode name appears in real CLI stdout")
    check("Traceback" not in result.stdout and "Traceback" not in result.stderr, "no unhandled traceback")


if __name__ == "__main__":
    scenario_a_default_mode()
    scenario_b_explicit_decision_copilot()
    scenario_c_unrecognized_mode_fails_closed()
    scenario_d_doctor_product_mode_section_ready()
    scenario_e_doctor_product_mode_section_blocked_on_unknown_mode()
    scenario_f_doctor_scheduler_section()
    scenario_g_run_doctor_regression()
    scenario_h_no_live_cli_dispatch()
    scenario_i_real_cli_proof()

    print("\n" + "=" * 60)
    print(f"PHASE A DECISION_COPILOT TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for description in _FAILURES:
            print(f"  - {description}")
        sys.exit(1)
