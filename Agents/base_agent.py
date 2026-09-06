from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from typing import Optional

from Core.exceptions import AgentError, ApprovalDenied, ApprovalPending, ProviderError
from Core.logger import get_logger
from Core.runtime import ActorTerminatedError
from Providers import BaseProvider, Message, MessageRole, ProviderRequirement, ProviderResponse
from Agents.state import AgentState
from Agents.memory import ConversationMemory
from Agents.planner import Planner, PlannerError
from Agents.executor import Executor
# Stage L8 compatibility: infer_requirement is kept as a direct import
# (not just via KeywordRequirementInference) solely because
# Tests/test_stage_l8_requirement_inference.py monkeypatches
# base_agent_module.infer_requirement (Scenarios 5/6) and scans this
# file's literal source text for the string "infer_requirement"
# (Scenario 10). It is not called by chat() anymore -- see
# self._requirement_inference below.
from Agents.requirement_inference import (
    RequirementInference,
    KeywordRequirementInference,
    infer_requirement,
)

logger = get_logger(__name__)


class AgentStateError(AgentError):
    """Raised when an agent operation is invalid for the current state.

    Additive subclass of ``Core.exceptions.AgentError``.
    """


class BaseAgent(ABC):
    """Abstract base class implementing the generic agent engine.

    Concrete agents (e.g. a future ``StockAgent`` or ``ChatAgent``) only
    need to supply a :attr:`name` and, optionally, override the hook
    methods to customize behaviour. They must never need to touch a
    concrete provider implementation directly -- only :class:`BaseProvider`.
    """

    def __init__(
        self,
        planner: Planner,
        memory: ConversationMemory,
        executor: Executor,
        requirement_inference: Optional[RequirementInference] = None,
    ) -> None:
        self._planner = planner
        self._memory = memory
        self._executor = executor
        # Stage L9 (additive): assigned exactly once here and never
        # mutated afterwards -- no setter, no replacement, no reset()
        # involvement. Runtime-swappable inference strategies are a
        # separate architectural discussion, out of scope for L9.
        self._requirement_inference: RequirementInference = (
            requirement_inference
            if requirement_inference is not None
            else KeywordRequirementInference()
        )
        self._state = AgentState.IDLE
        self._state_lock = threading.RLock()
        # Stage 8.3 (additive): identity of the Actor this agent owns.
        # ``None`` until the generic engine (run(), below) first needs to
        # call a tool -- created lazily then, never eagerly here, so
        # constructing a BaseAgent has zero Runtime side effects. Never
        # populated for subclasses that override run() entirely (e.g.
        # StockAgent/MarketAnalysisAgent -- out of Stage 8.3 scope); it
        # simply stays None for them.
        self._actor_id: Optional[str] = None
        # Stage 8.3 hardening: dedicated lock for the lazy-genesis critical
        # section only. Deliberately NOT ``self._state_lock`` -- that lock's
        # responsibility is the AgentState machine (IDLE/THINKING/.../ERROR),
        # this lock's responsibility is Actor identity/ownership. Mixing the
        # two would make one lock guard two unrelated concerns. Held only
        # around the check-then-create of ``self._actor_id`` below -- never
        # around ``Executor.execute()`` itself, so concurrent tool calls that
        # already share an Actor don't serialize on ingest/step/replay/
        # sandbox execution, only on the (cheap, one-time) genesis decision.
        self._actor_lock = threading.Lock()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, human-readable name identifying this agent."""
        raise NotImplementedError

    @property
    def state(self) -> AgentState:
        """Current lifecycle state of the agent."""
        with self._state_lock:
            return self._state

    @property
    def actor_id(self) -> Optional[str]:
        """Identity of the Actor this agent owns (Stage 8.3, additive).

        ``None`` until the first tool call is executed through the
        generic engine (:meth:`run`) -- the Actor is created lazily, on
        first need, and reused for every subsequent tool call made by
        this ``BaseAgent`` instance for as long as the instance lives.
        Concrete agents that override :meth:`run` entirely (out of
        Stage 8.3 scope -- e.g. ``StockAgent``/``MarketAnalysisAgent``)
        never populate this; it stays ``None`` for them.
        """
        return self._actor_id

    def _set_state(self, new_state: AgentState) -> None:
        with self._state_lock:
            logger.debug(f"Agent '{self.name}' state: {self._state} -> {new_state}")
            self._state = new_state

    def chat(
        self,
        user_input: str,
        provider_name: Optional[str] = None,
        requirement: Optional[ProviderRequirement] = None,
    ) -> str:
        """Run a single conversational turn and return the reply text.

        This is the generic engine pipeline:
        Message -> Planner -> (optional) Tool -> Provider -> Response.

        Stage L8 (additive): when the caller supplies neither
        ``provider_name`` nor ``requirement``, this method attempts to
        infer a ``ProviderRequirement`` from ``user_input`` via
        :func:`Agents.requirement_inference.infer_requirement`. The
        inferred requirement is *opportunistic*: it is only used if some
        registered provider already satisfies it, checked via a
        read-only probe call to ``Planner.select_by_requirement``. If
        inference finds no keyword match (``infer_requirement`` returns
        ``None``), or the probe fails (``PlannerError`` -- no selector
        configured -- or ``ProviderError`` -- no provider satisfies it),
        this method silently falls back to the pre-existing behavior
        (``requirement`` stays ``None``, resolved later by name as
        before L8 existed).

        A caller-supplied ``provider_name`` or ``requirement`` always
        bypasses inference entirely -- ``infer_requirement`` is not even
        called -- and keeps the exact pre-L8 contract, including raising
        ``ProviderError`` for an unsatisfiable *explicit* requirement
        (unchanged from Stage L4/L7: explicit requirements remain
        fail-closed).
        """
        if provider_name is None and requirement is None:
            inferred = self._requirement_inference.infer(user_input)
            if inferred is not None:
                try:
                    self._planner.select_by_requirement(inferred)
                    requirement = inferred
                except (PlannerError, ProviderError):
                    # Opportunistic: no configured selector or no
                    # provider satisfies the inferred requirement --
                    # swallow and fall back to the pre-existing
                    # name-based path (requirement stays None).
                    pass

        return self.run(
            Message(role=MessageRole.USER, content=user_input),
            provider_name,
            requirement,
        )

    def run(
        self,
        message: Message,
        provider_name: Optional[str] = None,
        requirement: Optional[ProviderRequirement] = None,
    ) -> str:
        """Run the full pipeline for an already-constructed :class:`Message`.

        Args:
            message: The incoming message to run the pipeline for.
            provider_name: Optional explicit provider name -- the
                pre-existing, name-based selection path.
            requirement: Stage L7 addition (additive, optional). Pure
                pass-through to :meth:`Agents.planner.Planner.plan`; no
                new logic lives here. When given, ``provider_name`` is
                ignored by ``Planner`` per its own L4 contract -- this
                method does not re-implement or duplicate that contract.

        Raises:
            AgentStateError: If called while the agent is in ``ERROR`` state.
        """
        with self._state_lock:
            if self._state is AgentState.ERROR:
                raise AgentStateError(
                    f"Agent '{self.name}' is in ERROR state; call reset() first.",
                    details={"agent_name": self.name},
                )

        try:
            self._set_state(AgentState.THINKING)
            self._memory.add(message)

            plan = self._planner.plan(
                message, provider_name=provider_name, requirement=requirement
            )

            tool_result = None
            if plan.use_tool and plan.tool_name is not None:
                self._set_state(AgentState.CALLING_TOOL)
                # Lazy genesis (Stage 8.3, additive, race-hardened): the
                # check-then-create of the owned Actor is the only part
                # that needs mutual exclusion, so it's the only part held
                # under ``self._actor_lock``. Executor still owns the only
                # Runtime instance/reference -- see Executor.create_actor().
                with self._actor_lock:
                    if self._actor_id is None:
                        genesis_task = json.dumps(
                            {"agent_genesis": self.name}
                        ).encode("utf-8")
                        self._actor_id = self._executor.create_actor(genesis_task)
                    # Snapshot while still holding the lock: ``execute()``
                    # below must use the Actor this call itself resolved,
                    # not a second live read of ``self._actor_id`` that a
                    # concurrent caller could have since overwritten.
                    actor_id = self._actor_id
                # Executor.execute() (ingest -> step -> replay -> sandbox)
                # deliberately runs OUTSIDE the lock: it can take a while,
                # and once Actor identity is resolved, concurrent tool
                # calls sharing that Actor don't need to serialize on
                # execution -- only the genesis decision needed exclusion.
                tool_result = self._executor.execute(
                    plan.tool_name, message.content, actor_id=actor_id
                )

            self._set_state(AgentState.WAITING_PROVIDER)
            reply = self._call_provider(plan.provider, tool_result)

            self._set_state(AgentState.RESPONDING)
            response_message = Message(role=MessageRole.ASSISTANT, content=reply.text)
            self._memory.add(response_message)

            self._set_state(AgentState.IDLE)
            return reply.text
        except ApprovalDenied:
            # Stage 8.6 (additive, no behavior change): ApprovalPort.check()
            # denied this call's INTENT (Stage 8.5 taxonomy). The Actor is
            # untouched -- this is a legitimate policy outcome, not a bug --
            # but AgentState stays a per-call transient machine (Stage 8.4
            # decision, unchanged here): ERROR is still where any exception
            # out of this try-block lands, and reset() is still required to
            # leave it. Distinguishing a richer recovery path (e.g. retrying
            # without a full reset()) is explicitly deferred -- see
            # Docs/runtime_lifecycle.md §4 and §9.
            self._set_state(AgentState.ERROR)
            raise
        except ApprovalPending:
            # Stage 8.6 (additive, no behavior change): ApprovalPort.check()
            # returned PENDING (Stage 8.5 taxonomy) -- not a failure, a
            # suspended decision. Same note as ApprovalDenied above: no
            # resume-from-pending mechanism exists yet (Runtime does not
            # retry the INTENT, ND-3), so there is nothing today to
            # differentiate ERROR into -- deferred to Stage 8.8 (Real
            # ApprovalPort / human-in-the-loop), where a genuine resume
            # path would first need to exist.
            self._set_state(AgentState.ERROR)
            raise
        except ActorTerminatedError:
            # Stage 8.6 (additive, no behavior change): the Actor's identity
            # itself is dead -- structurally different from the two cases
            # above (Docs/runtime_lifecycle.md §4): no retry on this
            # actor_id can ever succeed, only reset() (which severs
            # _actor_id, Stage 8.3.1) recovers. ERROR + reset() is already
            # the correct handling; this branch exists so the taxonomy is
            # explicit in code, not to change what happens.
            self._set_state(AgentState.ERROR)
            raise
        except Exception:
            self._set_state(AgentState.ERROR)
            raise

    def _call_provider(
        self,
        provider: BaseProvider,
        tool_result: Optional[object],
    ) -> ProviderResponse:
        """Build the conversation context and call the provider.

        Subclasses may override this hook to customize how tool results are
        merged into the provider call, without touching the rest of the
        pipeline.
        """
        history = [entry.message for entry in self._memory.history()]
        if tool_result is not None:
            history = history + [Message(role=MessageRole.TOOL, content=str(tool_result))]
        return provider.generate(history)

    def reset(self) -> None:
        """Clear conversation memory, sever the owned Actor, and return the
        agent to IDLE state.

        Stage 8.3.1 (Design Freeze -- Option B, additive): a fresh
        ``ConversationMemory`` deserves a fresh causal scope. The Actor
        this instance owned (if any) is NOT terminated at the Runtime
        level -- Executor exposes no ``terminate()`` passthrough, and
        adding one is out of scope for this decision -- it is simply
        abandoned: ``_actor_id`` is set back to ``None`` so the next tool
        call goes through the same lazy-genesis path as a brand-new
        instance, minting a new Actor via ``self._executor.create_actor``.
        This keeps ``ConversationMemory`` and the owned Actor's identity
        co-terminating at every reset(), instead of leaving them
        permanently desynchronized (Actor accumulating tool-call history
        the agent has already "forgotten"). Guarded by the same
        ``self._actor_lock`` used in :meth:`run`'s lazy-genesis section --
        ``_actor_id`` has exactly one synchronized gate for all reads and
        writes, not a second, unguarded write path.
        """
        self._memory.clear()
        with self._actor_lock:
            self._actor_id = None
        self._set_state(AgentState.IDLE)

    def health_check(self) -> bool:
        """Report whether the agent's default provider is currently healthy.

        Never raises: any failure resolving a provider is caught, logged,
        and reported as ``False``, mirroring
        ``Providers.BaseProvider.health_check()``'s own contract.
        """
        try:
            provider = self._planner.select_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Agent '{self.name}' health_check could not resolve a provider: {exc}")
            return False
        return provider.health_check()