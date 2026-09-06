"""
Stage 9.3 proof suite -- Production Configuration (config-based ApprovalPort
selection).

Scope (per this session's LOCKED design decision):
  - Core.runtime, Agents.executor, Agents.base_agent, Agents.planner,
    Agents.sandbox, Core.approval, Core.exceptions, Core.event,
    Core.event_store -- all untouched.
  - Core/approval_config.py (new): build_approval_port() reads
    APPROVAL_POLICY / APPROVAL_TOOL_WHITELIST / APPROVAL_TOOL_BLACKLIST
    via Core.config.config and constructs one of the four ApprovalPort
    implementations Stage 9.2 already provides. No new ApprovalPort
    class is defined here or in Core/approval_config.py.
  - Core/composition_root.py: single wiring change -- Executor(...) now
    passes approval_port=build_approval_port() instead of relying on
    Executor's own AlwaysApproveApprovalPort default. Nothing else in
    composition_root.py changed.
  - PredicateApprovalPort is intentionally not selectable via env --
    not tested here as a config path (by design, not an oversight).

Cakupan skenario:
  1. No env var set -> build_approval_port() returns AlwaysApproveApprovalPort.
  2. APPROVAL_POLICY=deny_all -> DenyAllApprovalPort; through the real
     Executor, a tool call raises ApprovalDenied.
  3. APPROVAL_POLICY=tool_whitelist + APPROVAL_TOOL_WHITELIST -> listed
     tool succeeds, unlisted tool raises ApprovalDenied.
  4. APPROVAL_POLICY=tool_whitelist with empty/unset whitelist ->
     ConfigurationError (fail-fast, never silently deny-all).
  5. APPROVAL_POLICY=tool_blacklist + APPROVAL_TOOL_BLACKLIST -> listed
     tool raises ApprovalDenied, unlisted tool succeeds.
  6. APPROVAL_POLICY=<unknown> -> ConfigurationError.
  7. Case-insensitivity + whitespace tolerance for APPROVAL_POLICY and
     for individual entries in the comma-separated tool lists.
  8. Core.composition_root.build_application() genuinely wires the
     ApprovalPort produced by build_approval_port() -- proven
     functionally (a deny_all policy makes the real graph's Executor
     deny every tool call), not just structurally.
  9. Backward compatibility: build_application() with no env var set
     still produces AlwaysApproveApprovalPort (same as before Stage 9.3).

All os.environ mutation is wrapped in try/finally to avoid leaking
state into other scenarios or other test files run in the same process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Core.approval import (
    AlwaysApproveApprovalPort,
    DenyAllApprovalPort,
    ToolBlacklistApprovalPort,
    ToolWhitelistApprovalPort,
)
from Core.approval_config import build_approval_port
from Core.exceptions import ApprovalDenied, ConfigurationError
from Agents.executor import Executor
from Agents.tool_registry import Tool, ToolRegistry


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


_APPROVAL_ENV_KEYS = ("APPROVAL_POLICY", "APPROVAL_TOOL_WHITELIST", "APPROVAL_TOOL_BLACKLIST")


class _EnvSandbox:
    """Context manager: set the given env vars, always restore the
    previous values (including "was unset") on exit -- regardless of
    whether the scenario body raises. Only touches the three
    Stage 9.3 approval-related keys, never any other env var.
    """

    def __init__(self, **overrides: Optional[str]) -> None:
        self._overrides = overrides
        self._previous: dict[str, Optional[str]] = {}

    def __enter__(self) -> "_EnvSandbox":
        for key in _APPROVAL_ENV_KEYS:
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


def _fresh_registry_with_tools() -> ToolRegistry:
    """A fresh, isolated ToolRegistry with two trivial tools registered.

    Same reasoning as Tests/test_stage9_1_executor.py and
    Tests/test_stage9_2_approval_policies.py -- ToolRegistry is a
    process-wide singleton, each scenario here needs a clean slate.
    """
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="echo", description="echoes its input", handler=lambda x: x))
    registry.register(Tool(name="shout", description="uppercases its input", handler=lambda x: x.upper()))
    return registry


# ---------------------------------------------------------------------------
# 1. No env var set -> AlwaysApproveApprovalPort.
# ---------------------------------------------------------------------------
def scenario_default_is_always_approve() -> None:
    with _EnvSandbox(APPROVAL_POLICY=None, APPROVAL_TOOL_WHITELIST=None, APPROVAL_TOOL_BLACKLIST=None):
        port = build_approval_port()
    check(isinstance(port, AlwaysApproveApprovalPort), "no env var set -> build_approval_port() returns AlwaysApproveApprovalPort")


# ---------------------------------------------------------------------------
# 2. deny_all -> DenyAllApprovalPort, Executor raises ApprovalDenied.
# ---------------------------------------------------------------------------
def scenario_deny_all_policy() -> None:
    with _EnvSandbox(APPROVAL_POLICY="deny_all"):
        port = build_approval_port()
        check(isinstance(port, DenyAllApprovalPort), "APPROVAL_POLICY=deny_all -> DenyAllApprovalPort")

        registry = _fresh_registry_with_tools()
        executor = Executor(registry, approval_port=port)
        raised = None
        try:
            executor.execute("echo", "hello")
        except ApprovalDenied as exc:
            raised = exc
        check(isinstance(raised, ApprovalDenied), "deny_all policy: real Executor call raises ApprovalDenied")


# ---------------------------------------------------------------------------
# 3. tool_whitelist -> listed tool succeeds, unlisted tool denied.
# ---------------------------------------------------------------------------
def scenario_tool_whitelist_policy() -> None:
    with _EnvSandbox(APPROVAL_POLICY="tool_whitelist", APPROVAL_TOOL_WHITELIST="echo"):
        port = build_approval_port()
        check(isinstance(port, ToolWhitelistApprovalPort), "APPROVAL_POLICY=tool_whitelist -> ToolWhitelistApprovalPort")

        registry = _fresh_registry_with_tools()
        executor = Executor(registry, approval_port=port)

        result = executor.execute("echo", "hello")
        check(result == "hello", "tool_whitelist policy: whitelisted tool ('echo') succeeds")

        raised = None
        try:
            executor.execute("shout", "hello")
        except ApprovalDenied as exc:
            raised = exc
        check(isinstance(raised, ApprovalDenied), "tool_whitelist policy: non-whitelisted tool ('shout') raises ApprovalDenied")


# ---------------------------------------------------------------------------
# 4. tool_whitelist with empty/unset whitelist -> ConfigurationError.
# ---------------------------------------------------------------------------
def scenario_tool_whitelist_empty_is_configuration_error() -> None:
    with _EnvSandbox(APPROVAL_POLICY="tool_whitelist", APPROVAL_TOOL_WHITELIST=None):
        raised = None
        try:
            build_approval_port()
        except ConfigurationError as exc:
            raised = exc
        check(isinstance(raised, ConfigurationError), "tool_whitelist with unset APPROVAL_TOOL_WHITELIST -> ConfigurationError (fail-fast)")

    with _EnvSandbox(APPROVAL_POLICY="tool_whitelist", APPROVAL_TOOL_WHITELIST="   ,  ,"):
        raised = None
        try:
            build_approval_port()
        except ConfigurationError as exc:
            raised = exc
        check(isinstance(raised, ConfigurationError), "tool_whitelist with whitespace/commas-only APPROVAL_TOOL_WHITELIST -> ConfigurationError (fail-fast, not silently deny-all)")


# ---------------------------------------------------------------------------
# 5. tool_blacklist -> listed tool denied, unlisted tool succeeds.
# ---------------------------------------------------------------------------
def scenario_tool_blacklist_policy() -> None:
    with _EnvSandbox(APPROVAL_POLICY="tool_blacklist", APPROVAL_TOOL_BLACKLIST="shout"):
        port = build_approval_port()
        check(isinstance(port, ToolBlacklistApprovalPort), "APPROVAL_POLICY=tool_blacklist -> ToolBlacklistApprovalPort")

        registry = _fresh_registry_with_tools()
        executor = Executor(registry, approval_port=port)

        raised = None
        try:
            executor.execute("shout", "hello")
        except ApprovalDenied as exc:
            raised = exc
        check(isinstance(raised, ApprovalDenied), "tool_blacklist policy: blacklisted tool ('shout') raises ApprovalDenied")

        result = executor.execute("echo", "hello")
        check(result == "hello", "tool_blacklist policy: non-blacklisted tool ('echo') succeeds")

    # Empty blacklist is valid (not an error) -- everything is allowed.
    with _EnvSandbox(APPROVAL_POLICY="tool_blacklist", APPROVAL_TOOL_BLACKLIST=None):
        port = build_approval_port()
        check(isinstance(port, ToolBlacklistApprovalPort), "tool_blacklist with unset APPROVAL_TOOL_BLACKLIST is valid (no ConfigurationError)")


# ---------------------------------------------------------------------------
# 6. Unknown policy -> ConfigurationError.
# ---------------------------------------------------------------------------
def scenario_unknown_policy_is_configuration_error() -> None:
    with _EnvSandbox(APPROVAL_POLICY="totally_made_up_policy"):
        raised = None
        try:
            build_approval_port()
        except ConfigurationError as exc:
            raised = exc
        check(isinstance(raised, ConfigurationError), "unknown APPROVAL_POLICY -> ConfigurationError")
        check(
            raised is not None and "totally_made_up_policy" in str(raised),
            "ConfigurationError message names the offending policy value",
        )


# ---------------------------------------------------------------------------
# 7. Case-insensitivity + whitespace tolerance.
# ---------------------------------------------------------------------------
def scenario_case_and_whitespace_tolerance() -> None:
    with _EnvSandbox(APPROVAL_POLICY="  Deny_ALL  "):
        port = build_approval_port()
        check(isinstance(port, DenyAllApprovalPort), "APPROVAL_POLICY tolerates surrounding whitespace and mixed case")

    with _EnvSandbox(APPROVAL_POLICY="tool_whitelist", APPROVAL_TOOL_WHITELIST=" echo , shout ,, "):
        port = build_approval_port()
        check(isinstance(port, ToolWhitelistApprovalPort), "whitelist parsing tolerates whitespace/blank entries")

        registry = _fresh_registry_with_tools()
        executor = Executor(registry, approval_port=port)
        result_echo = executor.execute("echo", "a")
        result_shout = executor.execute("shout", "b")
        check(result_echo == "a" and result_shout == "B", "both whitespace-trimmed whitelist entries ('echo', 'shout') are actually honored")


# ---------------------------------------------------------------------------
# 8. build_application() genuinely wires the configured ApprovalPort.
# ---------------------------------------------------------------------------
def scenario_composition_root_uses_configured_policy() -> None:
    from Core.composition_root import build_application

    with _EnvSandbox(APPROVAL_POLICY="deny_all"):
        graph = build_application(
            provider_name="gemini-stage9-3-configured-policy-check",
            agent_name="stock_agent-stage9-3-configured-policy-check",
        )
        approval_port = graph.executor._runtime._approval  # noqa: SLF001 -- deliberate white-box check
        check(isinstance(approval_port, DenyAllApprovalPort), "build_application() wires the DenyAllApprovalPort selected via APPROVAL_POLICY=deny_all")

        raised = None
        try:
            graph.executor.execute("some_tool_name_that_need_not_even_exist")
        except ApprovalDenied as exc:
            raised = exc
        check(
            isinstance(raised, ApprovalDenied),
            "build_application()'s real Executor denies a tool call under the configured deny_all policy (approval runs before tool lookup)",
        )


# ---------------------------------------------------------------------------
# 9. Backward compatibility: no env var -> build_application() still uses
#    AlwaysApproveApprovalPort, same as before Stage 9.3.
# ---------------------------------------------------------------------------
def scenario_composition_root_backward_compatible() -> None:
    from Core.composition_root import build_application

    with _EnvSandbox(APPROVAL_POLICY=None, APPROVAL_TOOL_WHITELIST=None, APPROVAL_TOOL_BLACKLIST=None):
        graph = build_application(
            provider_name="gemini-stage9-3-backward-compat-check",
            agent_name="stock_agent-stage9-3-backward-compat-check",
        )
        approval_port = graph.executor._runtime._approval  # noqa: SLF001 -- deliberate white-box check
        check(
            isinstance(approval_port, AlwaysApproveApprovalPort),
            f"build_application() with no env var set still wires AlwaysApproveApprovalPort (got {type(approval_port).__name__}) -- backward compatible with pre-Stage-9.3 behavior",
        )


def main() -> int:
    scenarios = [
        scenario_default_is_always_approve,
        scenario_deny_all_policy,
        scenario_tool_whitelist_policy,
        scenario_tool_whitelist_empty_is_configuration_error,
        scenario_tool_blacklist_policy,
        scenario_unknown_policy_is_configuration_error,
        scenario_case_and_whitespace_tolerance,
        scenario_composition_root_uses_configured_policy,
        scenario_composition_root_backward_compatible,
    ]

    import traceback

    for scenario in scenarios:
        print(f"\n{scenario.__name__}")
        try:
            scenario()
        except Exception:  # noqa: BLE001
            global _FAIL
            _FAIL += 1
            _FAILURES.append(f"{scenario.__name__} raised an unexpected exception")
            print(f"  ERROR - {scenario.__name__} raised an unexpected exception:")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"STAGE 9.3 PRODUCTION CONFIGURATION TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())