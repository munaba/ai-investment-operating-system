"""
Stage 9.4 proof suite -- Startup / Runtime Environment Validation.

Scope (per this session's LOCKED design decision):
  - Core.composition_root.build_application() -- untouched. Stage 9.0's
    hermetic contract (succeeds with no secrets, no network, no external
    package) is NOT modified. This suite explicitly re-proves that
    contract still holds, so a future stage cannot silently erode it.
  - Core.runtime, Agents.executor, Agents.base_agent, Core.approval,
    Core.approval_config, Database.* -- untouched, out of scope.
  - Core/startup_validation.py (new): validate_runtime_environment(),
    a presence-only check over REQUIRED_RUNTIME_ENV_VARS via the
    existing (previously-unused) Core.config.config.validate(). No new
    ApprovalPort/ConfigurationError subclass is defined here.
  - main.py: Activation 1.5 LOCKED DECISION OVERRIDE (supersedes this
    suite's original scenario 7 contract) -- validation now occurs at
    the *command boundary*, not at application startup.
    build_application() is called unconditionally, first, every time
    main() runs. validate_runtime_environment() is no longer called
    once up front; it is called only immediately before the two REPL
    branches that actually reach the active provider ("auto <ticker>"
    and the fallback chat branch). The "scan" REPL command never calls
    it, because ManualScanService has no provider dependency (see
    Tests/test_manual_scan_command.py). This is a deliberate,
    authorized contract change, not a regression -- see Activation 1.5
    deliverable report.

Cakupan skenario:
  1. Both GEMINI_API_KEY and GEMINI_MODEL set -> no exception raised.
  2. GEMINI_API_KEY missing -> ConfigurationError, details name it.
  3. GEMINI_MODEL missing -> ConfigurationError, details name it.
  4. Both missing -> ConfigurationError, details name both.
  5. validate_runtime_environment() never calls build_application() or
     touches tool_registry/provider_manager/agent_registry/service_registry
     (proven by monkeypatching build_application to a trap that fails
     the test if invoked).
  6. build_application() itself still succeeds with GEMINI_API_KEY/
     GEMINI_MODEL both unset -- Stage 9.0 hermeticity is unaffected by
     the existence of this new module.
  7. (Activation 1.5) main.py's main() calls build_application() first,
     unconditionally, then calls validate_runtime_environment() only
     when the REPL dispatches a provider-requiring command (chat) --
     proven via call-order instrumentation, not by reading source text.
  8. (Activation 1.5) main.py's main() does NOT call
     validate_runtime_environment() at all when the only REPL command
     typed is "scan" -- proven via the same instrumentation.

All os.environ mutation is wrapped in try/finally to avoid leaking state
into other scenarios or other test files run in the same process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.exceptions import ConfigurationError
from Core.startup_validation import REQUIRED_RUNTIME_ENV_VARS, validate_runtime_environment
import Core.composition_root as composition_root_module

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


_RUNTIME_ENV_KEYS = ("GEMINI_API_KEY", "GEMINI_MODEL")


class _EnvSandbox:
    """Context manager: set the given env vars, always restore the
    previous values (including "was unset") on exit -- regardless of
    whether the scenario body raises. Only touches the two Stage 9.4
    runtime-env keys, never any other env var. Same pattern as
    Tests/test_stage9_3_production_configuration.py::_EnvSandbox.
    """

    def __init__(self, **overrides: Optional[str]) -> None:
        self._overrides = overrides
        self._previous: dict[str, Optional[str]] = {}

    def __enter__(self) -> "_EnvSandbox":
        for key in _RUNTIME_ENV_KEYS:
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


# ---------------------------------------------------------------------------
# 1. Both required vars set -> no exception.
# ---------------------------------------------------------------------------
def scenario_both_present_passes() -> None:
    print("\nscenario_both_present_passes")
    with _EnvSandbox(GEMINI_API_KEY="fake-key", GEMINI_MODEL="gemini-2.0-flash"):
        raised: Optional[BaseException] = None
        try:
            validate_runtime_environment()
        except BaseException as exc:  # noqa: BLE001 - captured for assertion, not swallowed
            raised = exc
        check(raised is None, "both GEMINI_API_KEY and GEMINI_MODEL set -> no exception raised")


# ---------------------------------------------------------------------------
# 2. GEMINI_API_KEY missing -> ConfigurationError naming it.
# ---------------------------------------------------------------------------
def scenario_api_key_missing() -> None:
    print("\nscenario_api_key_missing")
    with _EnvSandbox(GEMINI_API_KEY=None, GEMINI_MODEL="gemini-2.0-flash"):
        raised: Optional[BaseException] = None
        try:
            validate_runtime_environment()
        except ConfigurationError as exc:
            raised = exc
        check(isinstance(raised, ConfigurationError), "missing GEMINI_API_KEY -> ConfigurationError")
        check(
            isinstance(raised, ConfigurationError) and "GEMINI_API_KEY" in raised.details.get("missing_keys", []),
            "ConfigurationError.details['missing_keys'] names GEMINI_API_KEY",
        )


# ---------------------------------------------------------------------------
# 3. GEMINI_MODEL missing -> ConfigurationError naming it.
# ---------------------------------------------------------------------------
def scenario_model_missing() -> None:
    print("\nscenario_model_missing")
    with _EnvSandbox(GEMINI_API_KEY="fake-key", GEMINI_MODEL=None):
        raised: Optional[BaseException] = None
        try:
            validate_runtime_environment()
        except ConfigurationError as exc:
            raised = exc
        check(isinstance(raised, ConfigurationError), "missing GEMINI_MODEL -> ConfigurationError")
        check(
            isinstance(raised, ConfigurationError) and "GEMINI_MODEL" in raised.details.get("missing_keys", []),
            "ConfigurationError.details['missing_keys'] names GEMINI_MODEL",
        )


# ---------------------------------------------------------------------------
# 4. Both missing -> ConfigurationError naming both.
# ---------------------------------------------------------------------------
def scenario_both_missing() -> None:
    print("\nscenario_both_missing")
    with _EnvSandbox(GEMINI_API_KEY=None, GEMINI_MODEL=None):
        raised: Optional[BaseException] = None
        try:
            validate_runtime_environment()
        except ConfigurationError as exc:
            raised = exc
        check(isinstance(raised, ConfigurationError), "both missing -> ConfigurationError")
        missing = raised.details.get("missing_keys", []) if isinstance(raised, ConfigurationError) else []
        check("GEMINI_API_KEY" in missing and "GEMINI_MODEL" in missing, "ConfigurationError names both missing keys")


# ---------------------------------------------------------------------------
# 5. validate_runtime_environment() never touches build_application()/registries.
# ---------------------------------------------------------------------------
def scenario_no_object_graph_construction() -> None:
    print("\nscenario_no_object_graph_construction")

    called = {"build_application": False}
    original = composition_root_module.build_application

    def _trap(*args, **kwargs):
        called["build_application"] = True
        return original(*args, **kwargs)

    composition_root_module.build_application = _trap
    try:
        with _EnvSandbox(GEMINI_API_KEY="fake-key", GEMINI_MODEL="gemini-2.0-flash"):
            validate_runtime_environment()
        with _EnvSandbox(GEMINI_API_KEY=None, GEMINI_MODEL=None):
            try:
                validate_runtime_environment()
            except ConfigurationError:
                pass
        check(
            called["build_application"] is False,
            "validate_runtime_environment() never calls build_application(), pass or fail",
        )
    finally:
        composition_root_module.build_application = original


# ---------------------------------------------------------------------------
# 6. build_application() itself remains hermetic -- unaffected by this stage.
# ---------------------------------------------------------------------------
def scenario_build_application_still_hermetic() -> None:
    print("\nscenario_build_application_still_hermetic")
    with _EnvSandbox(GEMINI_API_KEY=None, GEMINI_MODEL=None):
        raised: Optional[BaseException] = None
        try:
            composition_root_module.build_application(
                agent_name="stage9-4-hermetic-check",
            )
        except BaseException as exc:  # noqa: BLE001 - captured for assertion, not swallowed
            raised = exc
        check(
            raised is None,
            "build_application() still succeeds with GEMINI_API_KEY/GEMINI_MODEL both unset "
            "(Stage 9.0 hermetic contract unaffected by Stage 9.4)",
        )


# ---------------------------------------------------------------------------
# 7. (Activation 1.5 LOCKED DECISION OVERRIDE) main.py's main() calls
#    build_application() first, unconditionally, then calls
#    validate_runtime_environment() only when the REPL dispatches a
#    provider-requiring command (plain chat input) -- proven via
#    call-order instrumentation, not by reading source text.
#
# This supersedes the original scenario 7
# ("validate_runtime_environment() before build_application(),
# unconditionally"), which encoded the pre-Activation-1.5 contract of
# validating the whole runtime before any command was even chosen. See
# the Activation 1.5 deliverable report for the explicit authorization
# to change this contract.
# ---------------------------------------------------------------------------
class _FakeAgent:
    """Stands in for the real agent -- .chat() must never be reached for
    real (no network access in this sandbox); it only needs to exist so
    main()'s fallback branch has something to call after
    validate_runtime_environment() passes."""

    def chat(self, user_input: str) -> str:
        return "fake-reply"


class _FakeReport:
    """Minimal stand-in for Business.report_service.Report -- only the
    attribute _print_manual_scan_report() reads for an empty watchlist."""

    total_symbols = 0
    recommendations: List[str] = []


class _FakeManualScanService:
    """Stands in for Business.manual_scan_service.ManualScanService."""

    def run_scan(self, generated_at: str) -> _FakeReport:
        return _FakeReport()


class _FakeApp:
    """Stands in for Core.composition_root.ApplicationGraph -- only the
    attributes main() actually reads."""

    def __init__(self) -> None:
        self.agent_name = "fake-agent"
        self.provider_name = "fake-provider"
        self.agent = _FakeAgent()
        self.manual_scan_service = _FakeManualScanService()


def _instrumented_main_run(scripted_inputs: List[str]) -> List[str]:
    """Run main.main() with build_application()/validate_runtime_environment()
    instrumented to record call order, and a scripted sequence of REPL
    inputs (EOFError raised once the script is exhausted, exiting the
    loop). Returns the recorded call order.
    """
    import importlib
    import main as main_module

    importlib.reload(main_module)

    call_order: List[str] = []

    def _validate_trap():
        call_order.append("validate_runtime_environment")

    def _build_trap(*args, **kwargs):
        call_order.append("build_application")
        return _FakeApp()

    main_module.validate_runtime_environment = _validate_trap
    main_module.build_application = _build_trap

    inputs = iter(scripted_inputs)

    def _scripted_input(*args, **kwargs):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    import builtins

    original_input = builtins.input
    builtins.input = _scripted_input
    try:
        main_module.main()
    finally:
        builtins.input = original_input

    return call_order


def scenario_main_calls_build_then_validates_only_for_chat() -> None:
    print("\nscenario_main_calls_build_then_validates_only_for_chat")

    call_order = _instrumented_main_run(["hello"])

    check(
        call_order == ["build_application", "validate_runtime_environment"],
        f"main() calls build_application() first, then validate_runtime_environment() "
        f"only when dispatching plain chat input (got {call_order})",
    )


def scenario_main_scan_command_never_validates() -> None:
    print("\nscenario_main_scan_command_never_validates")

    call_order = _instrumented_main_run(["scan"])

    check(
        call_order == ["build_application"],
        f"main() never calls validate_runtime_environment() for a scan-only "
        f"session, since ManualScanService has no provider dependency (got {call_order})",
    )


if __name__ == "__main__":
    scenario_both_present_passes()
    scenario_api_key_missing()
    scenario_model_missing()
    scenario_both_missing()
    scenario_no_object_graph_construction()
    scenario_build_application_still_hermetic()
    scenario_main_calls_build_then_validates_only_for_chat()
    scenario_main_scan_command_never_validates()

    print("\n" + "=" * 60)
    print(f"STAGE 9.4 STARTUP VALIDATION TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("\nFailures:")
        for description in _FAILURES:
            print(f"  - {description}")
        sys.exit(1)