"""Standalone regression checks for Activation 8.4's four new
kill-switch config resolver functions in ``Core.composition_root``:

* ``_halted_markets()``   -- ``MARKET_KILL_SWITCH_MARKETS``
* ``_halted_symbols()``   -- ``SYMBOL_KILL_SWITCH_SYMBOLS``
* ``_max_daily_loss()``   -- ``RISK_MAX_DAILY_LOSS``
* ``_max_position_value()`` -- ``RISK_MAX_POSITION_VALUE``

These mirror the already-LOCKED ``_kill_switch_engaged()``/
``_max_order_value()`` pattern (read once, live, from ``Core.config``
at graph-build time) -- this suite proves each new function:

* defaults to "no restriction" (empty set / ``None``) when its env
  var is unset, so ``build_application()`` behaves identically to
  before Activation 8.4 for any deployment that has not opted in;
* parses a configured value correctly (comma-separated
  markets/symbols, normalized to lower/upper case respectively; a
  plain float for the two ceilings);
* never falls back to a guessed non-``None`` numeric default for the
  two ceilings -- an unset ceiling must disable its gate, not silently
  activate at some invented number.

Does NOT re-test ``PaperTradingEngine``'s own gate behavior (already
covered by ``Tests/test_paper_trading_engine.py``) and does NOT call
``build_application()`` (construction-only wiring is already covered
by ``Tests/test_stage_sprint4_step9_paper_trading_engine_wiring.py``)
-- this suite is scoped to the four resolver functions in isolation.

Run directly with
``python Tests/test_composition_root_kill_switch_config.py`` -- no
external test framework required, matching every other test file in
this suite.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Core.composition_root import (  # noqa: E402
    _halted_markets,
    _halted_symbols,
    _max_daily_loss,
    _max_position_value,
)

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


@contextmanager
def _env(**overrides):
    """Temporarily set/clear env vars, restoring the prior state on exit.

    A ``None`` value means "ensure the var is unset for the duration
    of this block" -- mirrors how ``Core.config.Config`` reads
    straight off ``os.environ`` with no caching layer to invalidate.
    """
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def scenario_halted_markets_default_empty():
    print("\n[Scenario 1] _halted_markets() defaults to empty set when unset")
    with _env(MARKET_KILL_SWITCH_MARKETS=None):
        result = _halted_markets()
        check(result == frozenset(), "unset MARKET_KILL_SWITCH_MARKETS -> frozenset() (no market halted)")


def scenario_halted_markets_parses_and_normalizes():
    print("\n[Scenario 2] _halted_markets() parses comma-separated, normalizes case/whitespace")
    with _env(MARKET_KILL_SWITCH_MARKETS=" IDX, us ,,crypto"):
        result = _halted_markets()
        check(
            result == frozenset({"idx", "us", "crypto"}),
            "'  IDX, us ,,crypto' -> {'idx', 'us', 'crypto'} (lower-cased, trimmed, empty entries dropped)",
        )


def scenario_halted_markets_single_value():
    print("\n[Scenario 3] _halted_markets() handles a single market")
    with _env(MARKET_KILL_SWITCH_MARKETS="idx"):
        result = _halted_markets()
        check(result == frozenset({"idx"}), "'idx' -> {'idx'}")


def scenario_halted_symbols_default_empty():
    print("\n[Scenario 4] _halted_symbols() defaults to empty set when unset")
    with _env(SYMBOL_KILL_SWITCH_SYMBOLS=None):
        result = _halted_symbols()
        check(result == frozenset(), "unset SYMBOL_KILL_SWITCH_SYMBOLS -> frozenset() (no symbol halted)")


def scenario_halted_symbols_parses_and_normalizes():
    print("\n[Scenario 5] _halted_symbols() parses comma-separated, normalizes case/whitespace")
    with _env(SYMBOL_KILL_SWITCH_SYMBOLS=" bbca, TLKM ,,bmri"):
        result = _halted_symbols()
        check(
            result == frozenset({"BBCA", "TLKM", "BMRI"}),
            "' bbca, TLKM ,,bmri' -> {'BBCA', 'TLKM', 'BMRI'} (upper-cased, trimmed, empty entries dropped)",
        )


def scenario_max_daily_loss_default_none():
    print("\n[Scenario 6] _max_daily_loss() defaults to None when unset (gate disabled, no guessed ceiling)")
    with _env(RISK_MAX_DAILY_LOSS=None):
        result = _max_daily_loss()
        check(result is None, "unset RISK_MAX_DAILY_LOSS -> None (never falls back to a numeric default)")


def scenario_max_daily_loss_empty_string_treated_as_unset():
    print("\n[Scenario 7] _max_daily_loss() treats an empty string the same as unset")
    with _env(RISK_MAX_DAILY_LOSS=""):
        result = _max_daily_loss()
        check(result is None, "RISK_MAX_DAILY_LOSS='' -> None")


def scenario_max_daily_loss_parses_configured_value():
    print("\n[Scenario 8] _max_daily_loss() parses a configured float")
    with _env(RISK_MAX_DAILY_LOSS="5000000"):
        result = _max_daily_loss()
        check(result == 5_000_000.0, "RISK_MAX_DAILY_LOSS='5000000' -> 5000000.0")


def scenario_max_position_value_default_none():
    print("\n[Scenario 9] _max_position_value() defaults to None when unset (gate disabled, no guessed ceiling)")
    with _env(RISK_MAX_POSITION_VALUE=None):
        result = _max_position_value()
        check(result is None, "unset RISK_MAX_POSITION_VALUE -> None (never falls back to a numeric default)")


def scenario_max_position_value_empty_string_treated_as_unset():
    print("\n[Scenario 10] _max_position_value() treats an empty string the same as unset")
    with _env(RISK_MAX_POSITION_VALUE=""):
        result = _max_position_value()
        check(result is None, "RISK_MAX_POSITION_VALUE='' -> None")


def scenario_max_position_value_parses_configured_value():
    print("\n[Scenario 11] _max_position_value() parses a configured float")
    with _env(RISK_MAX_POSITION_VALUE="25000000"):
        result = _max_position_value()
        check(result == 25_000_000.0, "RISK_MAX_POSITION_VALUE='25000000' -> 25000000.0")


def main() -> int:
    scenario_halted_markets_default_empty()
    scenario_halted_markets_parses_and_normalizes()
    scenario_halted_markets_single_value()
    scenario_halted_symbols_default_empty()
    scenario_halted_symbols_parses_and_normalizes()
    scenario_max_daily_loss_default_none()
    scenario_max_daily_loss_empty_string_treated_as_unset()
    scenario_max_daily_loss_parses_configured_value()
    scenario_max_position_value_default_none()
    scenario_max_position_value_empty_string_treated_as_unset()
    scenario_max_position_value_parses_configured_value()

    print("\n" + "=" * 60)
    print(f"ACTIVATION 8.4 CONFIG TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")

    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
