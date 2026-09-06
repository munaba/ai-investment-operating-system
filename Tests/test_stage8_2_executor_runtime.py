"""
Stage 8.2 proof suite -- Executor rewritten atop Runtime (error-as-data
GenericSandbox), no direct ToolRegistry/handler calls left in Executor.

Cakupan:
  1. GenericSandbox.execute() -- semua kegagalan (decode/tool_not_found/
     execution_error) sekarang error-as-data (bytes {"status":"error", ...}),
     tidak pernah exception. (Regresi ringkas -- detail penuh ada di
     test_stage8_1_sandbox_approval.py yang sudah diperbarui.)
  2. Executor.execute() -- happy path lewat Runtime asli: create_actor ->
     ingest(INTENT) -> drain step() -> replay() -> return value mentah.
  3. Executor.execute() -- tool tidak terdaftar -> ToolNotFoundError
     (API publik lama dipertahankan meski sekarang datang dari error-as-data
     payload, bukan propagasi langsung dari ToolRegistry).
  4. Executor.execute() -- handler tool melempar exception -> ToolExecutionError,
     __cause__ TIDAK dipreservasi (None), tapi metadata original_exception_class
     dan original_message dipreservasi di .details.
  5. Executor -- setiap execute() memakai Actor baru (isolasi antar panggilan);
     dua execute() sukses berturut-turut tidak saling mengganggu.
  6. Executor -- args/kwargs diteruskan dengan benar ke handler lewat Runtime
     (bukan lagi panggilan langsung).
  7. Regression check: Executor tidak lagi mengimpor/menggunakan
     ToolRegistry.get()/tool.handler() secara langsung (arsitektur ingest ->
     step -> replay, bukan call langsung).
"""

from __future__ import annotations

import inspect
from pathlib import Path
import sys
import traceback
from typing import List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.executor import Executor, ToolExecutionError
from Agents.sandbox import GenericSandbox
from Agents.tool_registry import Tool, ToolNotFoundError, ToolRegistry
from Core.runtime import Runtime


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
# 1. GenericSandbox -- error-as-data smoke check (full detail in 8.1 suite)
# ---------------------------------------------------------------------------
def scenario_sandbox_error_as_data_smoke() -> None:
    import json
    from Core.event import Event, EventID, EventType

    ToolRegistry.reset()
    registry = ToolRegistry()
    sandbox = GenericSandbox(registry)

    ev = Event(
        causal_scope_id="actor-x",
        type=EventType.INTENT,
        payload=json.dumps({"tool_name": "missing"}).encode("utf-8"),
        causal_refs=[],
        id=EventID(causal_scope_id="actor-x", seq=1),
    )

    result_bytes = sandbox.execute(ev)
    decoded = json.loads(result_bytes.decode("utf-8"))
    check(decoded.get("status") == "error", "GenericSandbox.execute() never raises for unregistered tool_name")
    check(decoded.get("error_type") == "tool_not_found", "error_type is 'tool_not_found'")
    registry.reset()


# ---------------------------------------------------------------------------
# 2. Executor.execute() happy path through real Runtime
# ---------------------------------------------------------------------------
def scenario_executor_happy_path() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="add", description="adds two numbers", handler=lambda a, b: a + b))

    executor = Executor(registry)
    result = executor.execute("add", 10, 32)

    check(result == 42, "Executor.execute() returns the raw tool return value via Runtime")
    check(isinstance(executor._runtime, Runtime), "Executor drives a real Core.runtime.Runtime instance")
    registry.reset()


# ---------------------------------------------------------------------------
# 3. Executor.execute() -- unregistered tool -> ToolNotFoundError
# ---------------------------------------------------------------------------
def scenario_executor_tool_not_found() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    executor = Executor(registry)

    try:
        executor.execute("this_tool_was_never_registered")
        check(False, "Executor.execute() raises ToolNotFoundError for an unregistered tool")
    except ToolNotFoundError as exc:
        check(True, "Executor.execute() raises ToolNotFoundError for an unregistered tool")
        check(exc.details.get("tool_name") == "this_tool_was_never_registered", "ToolNotFoundError carries tool_name in details")
    registry.reset()


# ---------------------------------------------------------------------------
# 4. Executor.execute() -- handler raises -> ToolExecutionError, no __cause__,
#    metadata preserved instead (LOCKED).
# ---------------------------------------------------------------------------
def scenario_executor_execution_error_metadata_not_cause() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()

    def boom():
        raise RuntimeError("kaboom from stage 8.2")

    registry.register(Tool(name="boom", description="always fails", handler=boom))
    executor = Executor(registry)

    try:
        executor.execute("boom")
        check(False, "Executor.execute() raises ToolExecutionError when handler raises")
    except ToolExecutionError as exc:
        check(True, "Executor.execute() raises ToolExecutionError when handler raises")
        check(exc.__cause__ is None, "ToolExecutionError.__cause__ is NOT preserved across Runtime (LOCKED)")
        check(
            exc.details.get("original_exception_class") == "RuntimeError",
            "ToolExecutionError.details preserves original_exception_class",
        )
        check(
            exc.details.get("original_message") == "kaboom from stage 8.2",
            "ToolExecutionError.details preserves original_message",
        )
    registry.reset()


# ---------------------------------------------------------------------------
# 5. Isolation across calls -- fresh Actor per execute(), no cross-talk
# ---------------------------------------------------------------------------
def scenario_executor_isolation_across_calls() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="double", description="doubles a number", handler=lambda n: n * 2))

    executor = Executor(registry)
    first = executor.execute("double", 3)
    second = executor.execute("double", 21)

    check(first == 6, "first execute() call returns correct result")
    check(second == 42, "second execute() call returns correct result, unaffected by the first")
    registry.reset()


# ---------------------------------------------------------------------------
# 6. args/kwargs forwarding through Runtime
# ---------------------------------------------------------------------------
def scenario_executor_args_kwargs_forwarding() -> None:
    ToolRegistry.reset()
    registry = ToolRegistry()
    calls = []

    def handler(*args, **kwargs):
        calls.append((args, kwargs))
        return {"echo": True}

    registry.register(Tool(name="echo", description="records call", handler=handler))
    executor = Executor(registry)

    result = executor.execute("echo", "x", y=1)

    check(result == {"echo": True}, "Executor.execute() returns tool result unchanged")
    check(calls == [(("x",), {"y": 1})], "Executor forwards args/kwargs verbatim through Runtime to the handler")
    registry.reset()


# ---------------------------------------------------------------------------
# 7. Regression: Executor no longer calls ToolRegistry.get()/handler directly
# ---------------------------------------------------------------------------
def scenario_executor_source_no_direct_registry_call() -> None:
    import Agents.executor as executor_module

    source = inspect.getsource(executor_module.Executor.execute)
    check(
        "_tool_registry.get(" not in source,
        "Executor.execute() no longer calls self._tool_registry.get() directly",
    )
    check(
        ".handler(" not in source,
        "Executor.execute() no longer calls tool.handler() directly",
    )
    check(
        "self._runtime.ingest(" in source and "self._runtime.replay(" in inspect.getsource(executor_module.Executor),
        "Executor drives Runtime via ingest() and replay() (ingest -> step loop -> replay)",
    )


def main() -> int:
    scenarios = [
        scenario_sandbox_error_as_data_smoke,
        scenario_executor_happy_path,
        scenario_executor_tool_not_found,
        scenario_executor_execution_error_metadata_not_cause,
        scenario_executor_isolation_across_calls,
        scenario_executor_args_kwargs_forwarding,
        scenario_executor_source_no_direct_registry_call,
    ]

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
    print(f"STAGE 8.2 EXECUTOR/RUNTIME TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failed checks:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())