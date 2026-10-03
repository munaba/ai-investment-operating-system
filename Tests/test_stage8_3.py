"""
Stage 8.3 proof suite -- BaseAgent lazy Actor genesis/reuse via
Executor.execute(actor_id=...), race-hardened with a dedicated
``_actor_lock`` (separate from ``_state_lock``).

Cakupan (disepakati sebagai minimal set sebelum Stage 8.3 boleh di-freeze):
  1. Lazy creation -- dua kali run() TANPA tool -> _actor_id tetap None.
  2. Reuse -- dua tool call lewat BaseAgent yang sama -> Actor yang sama
     dipakai (satu genesis, bukan dua).
  3. Default path regression (Stage 8.2, LOCKED) -- Executor.execute()
     TANPA actor_id tetap membuat Actor baru di setiap panggilan; reuse
     BaseAgent tidak mengubah default itu.
  4. Concurrent lazy creation -- dua thread memanggil run() bersamaan
     pada BaseAgent yang sama, race-condition harus TIDAK terjadi:
       - hanya SATU create_actor() yang benar-benar dieksekusi
       - kedua thread memakai ActorID yang sama
       - tidak ada orphan Actor
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
import sys
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Agents.base_agent import BaseAgent
from Agents.executor import Executor
from Agents.memory import ConversationMemory
from Agents.planner import Plan
from Agents.tool_registry import Tool, ToolRegistry
from Providers import Message, MessageRole, ProviderResponse


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
# Test doubles -- minimal, duck-typed to what BaseAgent actually calls.
# ---------------------------------------------------------------------------
class FakeProvider:
    """Satisfies BaseProvider's call surface used by BaseAgent (.generate())."""

    def generate(self, messages, **kwargs) -> ProviderResponse:
        return ProviderResponse(text="ok")


class FixedPlan:
    """Planner stand-in: returns a pre-baked Plan, ignores message content."""

    def __init__(self, use_tool: bool, tool_name: Optional[str], provider: FakeProvider) -> None:
        self._plan = Plan(use_tool=use_tool, provider=provider, tool_name=tool_name)

    def plan(self, message: Message, provider_name: Optional[str] = None, requirement: Optional[object] = None) -> Plan:
        return self._plan

    def select_provider(self, provider_name: Optional[str] = None) -> FakeProvider:
        return self._plan.provider


class DummyAgent(BaseAgent):
    """Minimal concrete BaseAgent -- only supplies the abstract `name`."""

    @property
    def name(self) -> str:
        return "dummy-agent"


def _echo_handler(*args, **kwargs) -> str:
    return "echo-result"


def _build_executor() -> Executor:
    ToolRegistry.reset()
    registry = ToolRegistry()
    registry.register(Tool(name="echo", description="Echoes back a fixed result.", handler=_echo_handler))
    return Executor(registry)


def _build_agent(executor: Executor, use_tool: bool, tool_name: Optional[str] = "echo") -> DummyAgent:
    provider = FakeProvider()
    planner = FixedPlan(use_tool=use_tool, tool_name=tool_name, provider=provider)
    memory = ConversationMemory()
    return DummyAgent(planner=planner, memory=memory, executor=executor)


# ---------------------------------------------------------------------------
# 1. Lazy creation -- no tool use ever -> _actor_id stays None
# ---------------------------------------------------------------------------
def scenario_lazy_creation_no_tool() -> None:
    executor = _build_executor()
    agent = _build_agent(executor, use_tool=False, tool_name=None)

    agent.run(Message(role=MessageRole.USER, content="hello"))
    check(agent.actor_id is None, "actor_id stays None after run() #1 with no tool use")

    agent.run(Message(role=MessageRole.USER, content="hello again"))
    check(agent.actor_id is None, "actor_id stays None after run() #2 with no tool use")


# ---------------------------------------------------------------------------
# 2. Reuse -- two tool calls through the same BaseAgent share one Actor
# ---------------------------------------------------------------------------
def scenario_reuse_same_actor_across_calls() -> None:
    executor = _build_executor()
    agent = _build_agent(executor, use_tool=True)

    agent.run(Message(role=MessageRole.USER, content="use echo"))
    first_actor_id = agent.actor_id
    check(first_actor_id is not None, "actor_id populated after first tool call")

    agent.run(Message(role=MessageRole.USER, content="use echo again"))
    second_actor_id = agent.actor_id
    check(
        second_actor_id == first_actor_id,
        "actor_id unchanged (same Actor reused) after second tool call",
    )

    # Trajectory-level proof, not just identity: the same Actor stream now
    # has two full INTENT/DECISION/EFFECT_COMPLETED cycles from the two
    # execute() calls above (genesis + 2*3 = 7 events).
    events, _state = executor._runtime.replay(first_actor_id)
    check(
        len(events) == 7,
        f"reused Actor stream carries both tool calls' events (got {len(events)}, expected 7)",
    )


# ---------------------------------------------------------------------------
# 3. Default path regression (Stage 8.2 LOCKED) -- actor_id omitted ->
#    fresh Actor every Executor.execute() call, unaffected by Stage 8.3.
# ---------------------------------------------------------------------------
def scenario_default_path_still_fresh_actor_per_call() -> None:
    executor = _build_executor()

    result1 = executor.execute("echo", "call-1")
    result2 = executor.execute("echo", "call-2")

    check(result1 == "echo-result" and result2 == "echo-result", "both calls succeed")

    # Executor doesn't return the actor_id it minted internally when
    # actor_id is omitted, so we prove freshness structurally: the
    # Runtime's bookkeeping must show two distinct Actors, each with
    # exactly one genesis-derived tool-call trajectory (4 events:
    # genesis + INTENT + DECISION + EFFECT_COMPLETED).
    all_actor_ids = list(executor._runtime._cursors.keys())
    check(len(all_actor_ids) == 2, f"two distinct Actors exist (got {len(all_actor_ids)})")
    for actor_id in all_actor_ids:
        events, _state = executor._runtime.replay(actor_id)
        check(
            len(events) == 4,
            f"Actor {actor_id} has exactly one tool-call trajectory (got {len(events)} events)",
        )


# ---------------------------------------------------------------------------
# 4. Concurrent lazy creation -- two threads racing BaseAgent.run() must
#    resolve to exactly one Actor, with no orphan.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 5. Stage 8.3.1 -- reset() severs the owned Actor (Option B, LOCKED)
# ---------------------------------------------------------------------------
def scenario_reset_severs_actor() -> None:
    executor = _build_executor()
    agent = _build_agent(executor, use_tool=True)

    agent.run(Message(role=MessageRole.USER, content="use echo"))
    pre_reset_actor_id = agent.actor_id
    check(pre_reset_actor_id is not None, "actor_id populated before reset()")

    agent.reset()
    check(agent.actor_id is None, "actor_id is None immediately after reset()")

    agent.run(Message(role=MessageRole.USER, content="use echo after reset"))
    post_reset_actor_id = agent.actor_id
    check(post_reset_actor_id is not None, "actor_id populated again after post-reset tool call")
    check(
        post_reset_actor_id != pre_reset_actor_id,
        f"post-reset Actor is a NEW Actor, not the pre-reset one "
        f"(pre={pre_reset_actor_id!r}, post={post_reset_actor_id!r})",
    )

    # Pre-reset Actor's own trajectory is untouched (abandoned, not
    # mutated/terminated -- Runtime has no dispose path exposed here;
    # Stage 8.3.1 only decided identity should not be reused, not that
    # the old Actor gets cleaned up).
    old_events, _old_state = executor._runtime.replay(pre_reset_actor_id)
    check(
        len(old_events) == 4,
        f"pre-reset Actor's trajectory is untouched by reset() (got {len(old_events)} events, expected 4)",
    )
    new_events, _new_state = executor._runtime.replay(post_reset_actor_id)
    check(
        len(new_events) == 4,
        f"post-reset Actor has its own fresh trajectory (got {len(new_events)} events, expected 4)",
    )


def scenario_concurrent_lazy_creation_no_race() -> None:
    executor = _build_executor()
    agent = _build_agent(executor, use_tool=True)

    # Slow down create_actor() just enough that, WITHOUT the _actor_lock
    # fix, two threads calling run() near-simultaneously would both
    # observe self._actor_id as None before either writes it.
    original_create_actor = executor.create_actor
    created_ids: List[str] = []
    create_call_count = {"n": 0}
    count_lock = threading.Lock()

    def slow_create_actor(task: bytes):
        with count_lock:
            create_call_count["n"] += 1
        time.sleep(0.05)
        actor_id = original_create_actor(task)
        created_ids.append(actor_id)
        return actor_id

    executor.create_actor = slow_create_actor  # type: ignore[method-assign]

    results: dict[str, Optional[str]] = {"A": None, "B": None}
    errors: list[BaseException] = []

    def worker(tag: str) -> None:
        try:
            agent.run(Message(role=MessageRole.USER, content=f"use echo from {tag}"))
            results[tag] = agent.actor_id
        except BaseException as exc:  # noqa: BLE001 -- surface any failure to the check() below
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    check(not errors, f"no exceptions raised by either thread (got {errors!r})")
    check(create_call_count["n"] == 1, f"create_actor() invoked exactly once (got {create_call_count['n']})")
    check(len(set(created_ids)) == 1, f"exactly one Actor created, no orphan (got {created_ids!r})")
    check(
        results["A"] == results["B"] == agent.actor_id,
        f"both threads observed the same actor_id as the agent's final actor_id "
        f"(A={results['A']!r}, B={results['B']!r}, agent={agent.actor_id!r})",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def main() -> int:
    print("1. Lazy creation (no tool use)")
    scenario_lazy_creation_no_tool()

    print("\n2. Reuse across multiple tool calls")
    scenario_reuse_same_actor_across_calls()

    print("\n3. Default path regression (Stage 8.2 LOCKED, actor_id omitted)")
    scenario_default_path_still_fresh_actor_per_call()

    print("\n4. Concurrent lazy creation (race check)")
    scenario_concurrent_lazy_creation_no_race()

    print("\n5. reset() severs the owned Actor (Stage 8.3.1, Option B)")
    scenario_reset_severs_actor()

    print("\n" + "=" * 60)
    print(f"STAGE 8.3 TEST RESULTS: {_PASS} PASS / {_FAIL} FAIL (total {_PASS + _FAIL})")
    print("=" * 60)
    if _FAILURES:
        print("Failures:")
        for f in _FAILURES:
            print(f"  - {f}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())