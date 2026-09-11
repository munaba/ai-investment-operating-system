from __future__ import annotations

import uuid
from abc import ABC
from typing import Any, Dict, Optional, Tuple

from Agents.base_agent import AgentStateError, BaseAgent
from Agents.executor import Executor
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.state import AgentState
from Core.logger import get_logger
from Providers import BaseProvider, Message, MessageRole, ProviderRequirement
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext

logger = get_logger(__name__)


class MarketAnalysisAgent(BaseAgent, ABC):
    """Abstract base for agents that analyze market instruments via a pipeline.

    ``MarketAnalysisAgent`` is the shared foundation for concrete agents
    that analyze a specific class of market instrument -- for example
    ``IDXStockAgent``, and future ``CryptoAgent``, ``ForexAgent``, or
    ``CommodityAgent`` -- each of which runs its own service pipeline over
    an extracted instrument identifier (a ticker, a symbol pair, a
    commodity code, and so on).

    This class holds the dependencies that are common across every such
    agent -- a provider manager for resolving providers, a tool-context
    builder for turning pipeline results into a provider-facing message,
    an instrument extractor for pulling the instrument identifier out of
    a message, and a service pipeline that performs the actual analysis
    -- so that concrete agents do not each need to wire these themselves.

    Unlike the previous version of this class, ``run()`` here IS the
    Template Method for every market-analysis agent: it is implemented
    once, in full, and is not meant to be overridden by concrete
    subclasses. What concrete subclasses may customize are the four
    hooks below -- :meth:`create_pipeline`, :meth:`build_context`,
    :meth:`execute_pipeline`, and :meth:`render_context` -- each of which
    has a sensible default here, so a subclass that needs no
    customization (e.g. ``IDXStockAgent``) does not need to override
    anything at all beyond :attr:`name`.

    :class:`~Agents.base_agent.BaseAgent` itself is untouched by this
    class: its own ``run()`` (the generic keyword-triggered tool engine)
    remains available, unchanged, for any agent that is not a
    market-analysis agent.

    Attributes:
        _provider_manager: Shared provider manager used to resolve
            providers by name.
        _tool_context_builder: Builder that turns pipeline results into
            a single provider-facing message.
        _instrument_extractor: Extracts an instrument identifier (e.g. a
            ticker or symbol) from an incoming message.
        _service_pipeline: The pipeline of services that performs the
            instrument analysis.
        _default_provider_name: Optional default provider name to use
            when none is specified for a given call.
    """

    def __init__(
        self,
        planner: Planner,
        memory: ConversationMemory,
        executor: Executor,
        provider_manager: object,
        tool_context_builder: object,
        instrument_extractor: object,
        service_pipeline: object,
        default_provider_name: Optional[str] = None,
    ) -> None:
        """Store shared dependencies for market-analysis agents.

        Args:
            planner: Planner used for provider selection and (in the
                generic engine) tool planning.
            memory: Conversation memory shared with the base agent
                engine.
            executor: Executor used to run registered tools.
            provider_manager: Shared provider manager used to resolve
                providers by name.
            tool_context_builder: Builder that turns pipeline results
                into a single provider-facing message.
            instrument_extractor: Extracts an instrument identifier
                (e.g. a ticker or symbol) from an incoming message.
            service_pipeline: The pipeline of services that performs the
                instrument analysis.
            default_provider_name: Optional default provider name to use
                when none is specified for a given call.
        """
        super().__init__(planner, memory, executor)
        self._provider_manager = provider_manager
        self._tool_context_builder = tool_context_builder
        self._instrument_extractor = instrument_extractor
        self._service_pipeline = service_pipeline
        self._default_provider_name = default_provider_name

    # ------------------------------------------------------------------
    # Template Method -- final. Concrete subclasses must NOT override
    # this; customize behavior via the four hooks below instead.
    # ------------------------------------------------------------------

    def run(
        self,
        message: Message,
        provider_name: Optional[str] = None,
        requirement: Optional[ProviderRequirement] = None,
    ) -> str:
        """Run one market-analysis turn: resolve -> pipeline -> render -> provider.

        This is the fixed control flow shared by every market-analysis
        agent:

        0. :meth:`_resolve_provider_for_request` (Stage L7) -- resolve the
           provider for this turn exactly once, either by requirement
           (when ``requirement`` is given) or by name (pre-existing path,
           deferred to step 4 exactly as before when ``requirement`` is
           ``None``).
        1. :meth:`build_context` -- extract the instrument from ``message``
           and build a :class:`~Services.service_context.ServiceContext`,
           seeded with the resolved provider *name* (a plain ``str`` --
           the pipeline/service layer never sees a provider instance).
        2. :meth:`execute_pipeline` -- run the configured service pipeline
           against that context.
        3. :meth:`render_context` -- format the pipeline results into a
           single provider-facing tool message.
        4. Hand conversation history + that tool message to the resolved
           provider via :meth:`~Agents.base_agent.BaseAgent._call_provider`
           (inherited, unchanged from ``BaseAgent``).

        Concrete subclasses customize step 1-3 by overriding
        :meth:`create_pipeline`, :meth:`build_context`,
        :meth:`execute_pipeline`, and/or :meth:`render_context` -- never
        this method itself.

        Args:
            message: The incoming message to run the pipeline for.
            provider_name: Optional explicit provider name -- the
                pre-existing, name-based selection path. Ignored when
                ``requirement`` is also given (Planner's L4 contract).
            requirement: Stage L7 addition (additive, optional). When
                given, the provider for this turn is resolved by
                capability instead of by name -- see
                :meth:`_resolve_provider_for_request`.

        Raises:
            AgentStateError: If called while the agent is in ``ERROR`` state.
        """
        with self._state_lock:
            if self._state is AgentState.ERROR:
                raise AgentStateError(
                    f"Agent '{self.name}' is in ERROR state; call reset() first.",
                    details={"agent_name": self.name},
                )

        provider, resolved_provider_name = self._resolve_provider_for_request(
            provider_name, requirement
        )

        try:
            self._set_state(AgentState.THINKING)
            self._memory.add(message)

            context = self.build_context(message, resolved_provider_name)

            self._set_state(AgentState.CALLING_TOOL)
            results = self.execute_pipeline(context)

            tool_context_text = self.render_context(results)

            self._set_state(AgentState.WAITING_PROVIDER)
            if provider is None:
                provider = self._planner.select_provider(resolved_provider_name)
            reply = self._call_provider(provider, tool_context_text)

            self._set_state(AgentState.RESPONDING)
            self._memory.add(Message(role=MessageRole.ASSISTANT, content=reply.text))

            self._set_state(AgentState.IDLE)
            return reply.text
        except Exception:
            self._set_state(AgentState.ERROR)
            raise

    def _resolve_provider_for_request(
        self,
        provider_name: Optional[str],
        requirement: Optional[ProviderRequirement],
    ) -> Tuple[Optional[BaseProvider], str]:
        """Resolve which provider (or provider *name*) this turn should use.

        Stage L7 addition. This method only *resolves* -- it never
        selects between candidates itself; that judgment is entirely
        ``Planner``'s (``select_by_requirement`` / ``select_provider``).
        It exists so ``run()`` performs provider resolution exactly once,
        before :meth:`build_context` needs a name to seed
        :class:`~Services.service_context.ServiceContext` with.

        Two mutually exclusive outcomes, matching ``Planner.plan()``'s
        own L4 contract exactly (``requirement`` wins, ``provider_name``
        is not consulted at all when it is given -- never merged):

        - ``requirement`` given: delegates to
          ``Planner.select_by_requirement(requirement)`` -- exactly once
          -- and returns the resolved ``BaseProvider`` instance plus its
          ``.name``. The instance is not looked up a second time by name
          anywhere in ``run()``.
        - ``requirement`` is ``None``: returns ``(None, provider_name or
          self._default_provider_name)`` -- the provider *name* only.
          The actual ``BaseProvider`` instance continues to be resolved
          at the exact same point in ``run()`` as before this stage
          (via ``Planner.select_provider``), preserving byte-for-byte
          existing behavior for every pre-existing caller.

        Args:
            provider_name: Optional explicit provider name (name-based path).
            requirement: Optional capability requirement (Stage L7 path).

        Returns:
            A ``(provider, resolved_provider_name)`` tuple. ``provider``
            is ``None`` unless ``requirement`` was given.
        """
        if requirement is not None:
            provider = self._planner.select_by_requirement(requirement)
            return provider, provider.name
        return None, (provider_name or self._default_provider_name)

    # ------------------------------------------------------------------
    # Hooks -- the only methods concrete subclasses should override.
    # Each has a working default, so a subclass with no special needs
    # (e.g. IDXStockAgent) does not need to override any of them.
    # ------------------------------------------------------------------

    def create_pipeline(self) -> Any:
        """Return the service pipeline to run for this request.

        Default: the pipeline injected at construction time
        (``self._service_pipeline``). Override this only if an agent
        needs to select between multiple pipelines at request time (e.g.
        based on message content); do not use this hook to construct a
        new pipeline per call -- pipelines remain dependency-injected.
        """
        return self._service_pipeline

    def build_context(self, message: Message, provider_name: str) -> ServiceContext:
        """Extract the instrument from ``message`` and build a ``ServiceContext``.

        Default: delegates extraction to ``self._instrument_extractor``
        (injected at construction time) and seeds the result under
        :attr:`Services.metadata_keys.MetadataKeys.TICKER`. Individual
        services fall back to their own defaults for any other metadata
        key they read (e.g. ``period``, ``interval``, ``max_news``), so
        this hook does not need to duplicate those defaults.

        Override this only if an agent needs additional or differently
        named seed metadata (e.g. a future ``ForexAgent`` seeding a
        currency pair under a different key).
        """
        instrument = self._instrument_extractor.extract(message.content)
        return ServiceContext(
            agent_name=self.name,
            provider_name=provider_name,
            request_id=str(uuid.uuid4()),
            user_input=message.content,
            conversation_history=[entry.message for entry in self._memory.history()],
            metadata={MetadataKeys.TICKER: instrument},
        )

    def execute_pipeline(self, context: ServiceContext) -> Dict[str, Any]:
        """Run the pipeline returned by :meth:`create_pipeline` against ``context``.

        Default: ``self.create_pipeline().run(context)``. Individual
        service failures are absorbed by the pipeline itself
        (skip-on-fail) and reported as degraded sections later, in
        :meth:`render_context` -- only a pipeline-level exception (e.g. a
        genuinely unimplemented pipeline) propagates out of this method.
        """
        pipeline = self.create_pipeline()
        return pipeline.run(context)

    def render_context(self, results: Dict[str, Any]) -> str:
        """Format pipeline ``results`` into a single provider-facing tool message.

        Default: delegates to ``self._tool_context_builder.build(results)``
        (injected at construction time).
        """
        return self._tool_context_builder.build(results)