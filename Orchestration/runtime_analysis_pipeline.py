"""RuntimeAnalysisPipeline -- Runtime-kernel facade for the 11-step
``AnalysisPipeline`` (Stage L11, Phase 1: "Runtime sebagai Execution
Kernel").

Design decisions this module implements (LOCKED baseline, Stage L11):

  1. Phase 1 uses Runtime as the execution kernel via ONE big Tool --
     ``AnalysisPipeline`` is not split into many Tools.
  2. ``RuntimeAnalysisPipeline`` is a new facade class, not an evolution
     of ``Orchestration.analysis_pipeline_adapter.AnalysisPipelineAdapter``.
  3. ``AnalysisPipelineAdapter`` stays pure delegation, untouched --
     it already has its own regression lock and is out of scope here.
  4. The Tool handler is a private implementation detail of
     ``RuntimeAnalysisPipeline`` (see :meth:`RuntimeAnalysisPipeline.run`)
     -- it is never registered as a standing, reusable Tool and is never
     exposed on the public API.
  5. ``ToolContextBuilder.build()`` is called *inside* the Tool handler,
     not by the caller of :meth:`RuntimeAnalysisPipeline.run` -- so the
     only thing that ever crosses the Runtime/Executor boundary is the
     final formatted ``str``. This is also what keeps the call
     JSON-safe: ``ServiceContext`` and ``dict[str, ServiceResult]`` are
     not JSON-serializable and never need to be, because they never
     leave this class -- only the closure captures them, and only a
     ``str`` return value round-trips through
     ``Agents.executor.Executor.execute`` /
     ``Agents.sandbox.GenericSandbox.execute``.
  6. ``RuntimeAnalysisPipeline`` is stateless beyond its standard
     constructor-injected collaborators -- no per-call state is kept on
     ``self`` between calls to :meth:`run`.
  7. Approval stays ``AlwaysApprove`` for Phase 1 (unchanged here --
     this class does not construct or configure an ``ApprovalPort``
     itself; that remains ``Executor``'s / ``Core.approval_config``'s
     concern).
  8. ``EventStore`` stays ``InMemory`` for Phase 1 (same reasoning as
     #7 -- this class never constructs a ``Runtime``/``EventStore``
     directly, only an already-built ``Executor``).
  9. One user turn == one Actor, using ``Executor``'s default path (no
     explicit ``actor_id`` is ever passed to ``Executor.execute``).
  10. Additive-only, minimal blast radius: no existing file is modified
      by this module; ``AnalysisPipeline``, ``ToolContextBuilder``,
      ``Executor``, and ``ToolRegistry`` are all used strictly through
      their existing public APIs.

Integration Sprint 2 extends the live chain by exactly one stage:
DecisionEngine -> DecisionPolicy (see :meth:`RuntimeAnalysisPipeline
._maybe_reflect_and_decide`). The real ``Decision`` object DecisionEngine
already produces is passed directly into ``DecisionPolicy.apply()`` --
not recreated, transformed, or duplicated. Stops at
``DecisionPolicyResult``; PolicyGuard and everything past it remain
unwired.

Integration Sprint 3 extends the live chain by exactly one further
stage: DecisionPolicy -> PolicyGuard (see :meth:`RuntimeAnalysisPipeline
._maybe_reflect_and_decide`). The real ``DecisionPolicyResult`` object
DecisionPolicy already produces is passed directly into
``PolicyGuard.evaluate()`` -- not recreated, transformed, or duplicated.
Stops at ``PolicyGuardResult``; ExecutionIntent and everything past it
remain unwired.

Integration Sprint 4 extends the live chain by exactly one further
stage: PolicyGuard -> ExecutionIntent (see :meth:`RuntimeAnalysisPipeline
._maybe_reflect_and_decide`). The real ``PolicyGuardResult`` object
PolicyGuard already produces is passed directly into
``ExecutionIntent.build()`` -- not recreated, transformed, or
duplicated. Stops at ``ExecutionIntentResult``; ExecutionPlanner and
everything past it remain unwired.

Integration Sprint 5 extends the live chain by exactly one further
stage: ExecutionIntent -> ExecutionPlanner (see
:meth:`RuntimeAnalysisPipeline._maybe_reflect_and_decide`). The real
``ExecutionIntentResult`` object ExecutionIntent already produces is
passed directly into ``ExecutionPlanner.plan()`` -- not recreated,
transformed, or duplicated. Stops at ``ExecutionPlan``;
ExecutionCoordinator and everything past it remain unwired.

Integration Sprint 6 extends the live chain by exactly one further
stage: ExecutionPlanner -> ExecutionCoordinator (see
:meth:`RuntimeAnalysisPipeline._maybe_reflect_and_decide`). The real
``ExecutionPlan`` object ExecutionPlanner already produces is passed
directly into ``ExecutionCoordinator.coordinate()`` -- not recreated,
transformed, or duplicated. Stops at ``ExecutionCoordinatorResult``;
PortfolioEngine and everything past it remain unwired.

Integration Sprint 7 extends the live chain by exactly one further
stage: ExecutionCoordinator -> PortfolioEngine (see
:meth:`RuntimeAnalysisPipeline._maybe_reflect_and_decide`). The real
``ExecutionCoordinatorResult`` object ExecutionCoordinator already
produces is passed directly into ``PortfolioEngine.evaluate()`` -- not
recreated, transformed, or duplicated. Stops at
``PortfolioEngineResult``, which is only ever logged via
``logger.debug()``; PortfolioRisk and everything past it remain
unwired.

Integration Sprint 8 extends the live chain by exactly one further
stage: PortfolioEngine -> PortfolioRisk (see
:meth:`RuntimeAnalysisPipeline._maybe_reflect_and_decide`). The real
``PortfolioEngineResult`` object PortfolioEngine already produces is
passed directly into ``PortfolioRisk.assess()`` -- not recreated,
transformed, or duplicated. Stops at ``PortfolioRiskResult``, which is
only ever logged via ``logger.debug()``; LearningLoop and everything
past it remain unwired.

Integration Sprint 9 extends the live chain by exactly one further
stage: PortfolioRisk -> LearningLoop (see
:meth:`RuntimeAnalysisPipeline._maybe_reflect_and_decide`). The real
``PortfolioRiskResult`` object PortfolioRisk already produces is passed
directly into ``LearningLoop.learn()`` -- not recreated, transformed,
or duplicated. Stops at ``LearningLoopResult``, which is only ever
logged via ``logger.debug()``; AutonomousAgent remains unwired.

Sprint 152 extends the live chain by exactly one further, independent
stage: the Sprint 151 vision-produced ``market_state`` mapping ->
``Orchestration.trading_decision_agent.TradingDecisionAgent`` (see
:meth:`RuntimeAnalysisPipeline._maybe_run_trading_decision`). This is
purely a bridge: no existing Skill's logic is touched, and
``TradingDecisionAgent`` itself is not modified in any way. When a
chart was supplied and vision produced a ``market_state`` mapping,
that mapping's own ``"symbol"`` field seeds a freshly built
``Orchestration.task.Task`` (``metadata={"symbols": [...],
"capital": 0}``), which is handed to
``trading_decision_agent.execute(task)`` exactly once. The resulting
six-Skill dict is attached to the returned :class:`AnalysisResult` as
``.trading_decision`` -- it never affects ``classic_analysis``. No
chart, no ``market_state``, or no ``trading_decision_agent`` injected
at construction time all result in ``.trading_decision`` staying
``None``, byte-for-byte the same classic-only behavior as before this
integration.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from Agents.executor import Executor
from Agents.tool_registry import Tool, ToolRegistry
from Core.analysis_pipeline import AnalysisPipeline
from Core.logger import get_logger
from Core.tool_context_builder import ToolContextBuilder
from Orchestration.decision_engine import DecisionEngine
from Orchestration.decision_policy import DecisionPolicy
from Orchestration.execution_coordinator import ExecutionCoordinator
from Orchestration.execution_intent import ExecutionIntent
from Orchestration.execution_planner import ExecutionPlanner
from Orchestration.learning_loop import LearningLoop
from Orchestration.memory import MemoryRecorder, MemoryStore
from Orchestration.observation import Observation, StepObservation
from Orchestration.policy_guard import PolicyGuard
from Orchestration.portfolio_engine import PortfolioEngine
from Orchestration.portfolio_risk import PortfolioRisk
from Orchestration.reflection import Reflector
from Orchestration.task import Task
from Orchestration.trading_decision_agent import TradingDecisionAgent
from Orchestration.vision_market_state_pipeline import VisionMarketStatePipeline
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult

logger = get_logger(__name__)

#: Prefix for the private, single-use Tool name minted per run() call.
#: Namespaced so a collision with any other Tool's name is not a realistic
#: concern, and so the name is recognizable in logs/registry dumps as
#: belonging to this facade.
_TOOL_NAME_PREFIX = "runtime_analysis_pipeline"

#: Sprint 151 addition: the ``ServiceContext.metadata`` key a caller uses
#: to opt a request into the modern vision pipeline. Reuses the existing
#: ``ServiceContext.metadata`` transport already used for every other
#: seeded value (see ``Services.metadata_keys.MetadataKeys``) -- no
#: second chart-input representation is introduced. Absent or empty ->
#: no chart input supplied -> vision pipeline is never invoked (see
#: ``RuntimeAnalysisPipeline._maybe_run_vision``).
VISION_CHART_PATH_METADATA_KEY = "chart_path"


class AnalysisResult(str):
    """The ``str`` classic-analysis tool message, additionally carrying
    an optional ``market_state`` mapping (Sprint 151 addition), an
    optional ``trading_decision`` mapping (Sprint 152 addition), and a
    derived ``portfolio_report`` (this sprint's addition).

    Backward-compatible by construction: this *is* a ``str`` (a
    subclass), so every existing caller of
    ``RuntimeAnalysisPipeline.run()`` that treats the return value as
    plain text (equality checks, string formatting, passing straight
    into a provider call, ``isinstance(x, str)``) keeps working
    unchanged and unaware anything was added. ``market_state``,
    ``trading_decision``, and ``portfolio_report`` are additional,
    opt-in surface for a caller that wants them -- reading any of
    them never mutates or replaces the classic text.
    """

    market_state: Optional[Any]
    trading_decision: Optional[Any]

    def __new__(
        cls,
        classic_analysis: str,
        market_state: Optional[Any] = None,
        trading_decision: Optional[Any] = None,
    ) -> "AnalysisResult":
        instance = super().__new__(cls, classic_analysis)
        instance.market_state = market_state
        instance.trading_decision = trading_decision
        return instance

    @property
    def classic_analysis(self) -> str:
        """The exact classic-analysis text this instance wraps.

        Returns:
            ``str(self)`` -- identical to what every pre-Sprint-151
            caller already received as the whole return value.
        """
        return str(self)

    @property
    def portfolio_report(self) -> Optional[Any]:
        """The final ``PortfolioReportSkill`` result out of
        ``trading_decision``, forwarded by identity.

        This is a pure, read-only derivation from ``self.trading_decision``
        -- no new state is stored on the instance, so it can never drift
        out of sync with it. If ``trading_decision`` is a ``Mapping``
        carrying a ``"portfolio_report"`` entry (the real
        ``TradingDecisionAgent.execute()`` return shape), that exact
        object is returned unchanged -- not copied, transformed,
        summarized, merged, or formatted. If ``trading_decision`` is
        ``None``, or is a ``Mapping`` without that key, or is not a
        ``Mapping`` at all, this returns ``None``.

        Returns:
            The identity-forwarded ``"portfolio_report"`` entry of
            ``trading_decision``, or ``None``.
        """
        if isinstance(self.trading_decision, Mapping):
            return self.trading_decision.get("portfolio_report")
        return None


def _observation_from_analysis_results(
    results: Dict[str, ServiceResult]
) -> Observation:
    """Integration-layer adapter: builds a real ``Observation`` directly
    from the ``Dict[str, ServiceResult]`` this facade already produces.

    This function exists only because the two real, existing contracts
    do not currently meet: ``Orchestration.observation.ObservationRecorder
    .record()`` requires a ``Goal`` and an ``ExecutionPlan`` (both
    ``GoalPlanner``-only concepts, Stage L15), but
    ``RuntimeAnalysisPipeline`` never runs ``GoalPlanner`` -- it runs the
    fixed ``AnalysisPipeline`` directly, which has no ``Goal`` or
    ``ExecutionPlan`` at all. No ``Goal`` or ``ExecutionPlan`` is
    fabricated here, or anywhere else in this module.

    Every field below is either:
      - real data already present in ``results`` (service name, success,
        message, data, metadata, execution_time_ms, error, and the
        dict's own iteration order -- which is real execution order,
        since ``AnalysisPipeline._build_result_dict`` builds it from an
        ordered list of (name, result) pairs), or
      - an empty default that ``Observation``/``StepObservation``
        explicitly type as allowing (``goal_metadata: Dict[str, Any]``,
        ``required_inputs: Tuple[str, ...]``) -- used here only because
        no ``Goal``/``PlanStep`` exists on this call path to source them
        from, never to imply such data was semantically empty.

    The aggregation rule below (later steps' dict-shaped data overwrites
    same-named earlier keys; a failed or non-dict result contributes
    nothing) is the same rule ``ObservationRecorder.record()`` already
    implements -- reproduced here rather than invoked there, since that
    method's signature does not accept this call path's real inputs.
    """
    step_observations: List[StepObservation] = []
    aggregated_outputs: Dict[str, object] = {}

    for order, (service_name, result) in enumerate(results.items()):
        data = dict(result.data) if isinstance(result.data, dict) else result.data
        result_metadata = dict(result.metadata)
        error_message = str(result.error) if result.error is not None else None

        step_observations.append(
            StepObservation(
                order=order,
                service_name=service_name,
                required_inputs=(),
                success=result.success,
                message=result.message,
                data=data,
                error_message=error_message,
                execution_time_ms=result.execution_time_ms,
                result_metadata=result_metadata,
            )
        )

        if result.success and isinstance(result.data, dict):
            aggregated_outputs = {**aggregated_outputs, **result.data}

    return Observation(
        goal_metadata={},
        plan_step_names=tuple(results.keys()),
        steps=tuple(step_observations),
        aggregated_outputs=aggregated_outputs,
    )


class RuntimeAnalysisPipeline:
    """Runs the fixed 11-step ``AnalysisPipeline`` through the Runtime
    execution kernel, as a single Tool invocation per call.

    Distinct from ``AnalysisPipelineAdapter`` (pure delegation, untouched,
    LOCKED): this facade instead routes each :meth:`run` call through
    ``Executor`` -- i.e. through ``Core.runtime.Runtime`` -- so a single
    analysis request becomes one Runtime Actor's
    ``INTENT -> Decision -> EFFECT_COMPLETED`` trajectory, rather than a
    direct Python call into ``AnalysisPipeline``.

    Stateless beyond its constructor-injected collaborators: every call
    to :meth:`run` registers and unregisters its own private Tool, so no
    per-call state ever lives on ``self``.
    """

    def __init__(
        self,
        executor: Executor,
        analysis_pipeline: AnalysisPipeline,
        tool_context_builder: ToolContextBuilder,
        tool_registry: ToolRegistry,
        memory_recorder: Optional[MemoryRecorder] = None,
        memory_store: Optional[MemoryStore] = None,
        reflector: Optional[Reflector] = None,
        decision_engine: Optional[DecisionEngine] = None,
        decision_policy: Optional[DecisionPolicy] = None,
        policy_guard: Optional[PolicyGuard] = None,
        execution_intent: Optional[ExecutionIntent] = None,
        execution_planner: Optional[ExecutionPlanner] = None,
        execution_coordinator: Optional[ExecutionCoordinator] = None,
        portfolio_engine: Optional[PortfolioEngine] = None,
        portfolio_risk: Optional[PortfolioRisk] = None,
        learning_loop: Optional[LearningLoop] = None,
        vision_pipeline: Optional[VisionMarketStatePipeline] = None,
        trading_decision_agent: Optional[TradingDecisionAgent] = None,
    ) -> None:
        """Wire up the facade via dependency injection only.

        Args:
            executor: Drives the private Tool call through Runtime
                (ingest -> step -> replay), exactly like any other
                ``Executor.execute`` caller. Never constructed here.
            analysis_pipeline: The existing, unmodified 11-step pipeline
                to run inside the Tool handler.
            tool_context_builder: Formats the pipeline's
                ``dict[str, ServiceResult]`` into the single tool-message
                string returned by :meth:`run`.
            tool_registry: Registry the private, single-use Tool is
                registered into (and unregistered from) for the duration
                of one :meth:`run` call. Must be the same ``ToolRegistry``
                instance ``executor`` was constructed with, or the Tool
                handler will not be reachable from the Runtime call
                ``executor`` drives.
            memory_recorder: Optional. When provided together with
                ``memory_store``, ``reflector``, and ``decision_engine``,
                each :meth:`run` call also records an ``Observation``
                (built from that call's own results -- see
                :func:`_observation_from_analysis_results`), reflects
                over the full stored history, and runs ``DecisionEngine``
                on the result. Defaults to ``None`` -- every existing
                caller that does not pass these four arguments gets
                byte-for-byte the same behavior as before this
                integration.
            memory_store: Optional. See ``memory_recorder`` above; must
                be the same ``MemoryStore`` instance ``memory_recorder``
                itself wraps, so ``.list()`` reflects what was just
                recorded.
            reflector: Optional. See ``memory_recorder`` above.
            decision_engine: Optional. See ``memory_recorder`` above.
            decision_policy: Optional. Integration Sprint 2 addition. When
                provided (together with the four ``memory_recorder``/
                ``memory_store``/``reflector``/``decision_engine``
                arguments above), each :meth:`run` call also passes the
                real ``Decision`` produced by ``decision_engine`` straight
                into ``decision_policy.apply()`` -- no reconstruction, no
                transformation, no duplication of that ``Decision``.
                Defaults to ``None`` -- every existing caller that does
                not pass it gets byte-for-byte the same behavior as
                before this integration.
            policy_guard: Optional. Integration Sprint 3 addition. When
                provided (together with the five arguments above), each
                :meth:`run` call also passes the real
                ``DecisionPolicyResult`` produced by ``decision_policy``
                straight into ``policy_guard.evaluate()`` -- no
                reconstruction, no transformation, no duplication of
                that ``DecisionPolicyResult``. Defaults to ``None`` --
                every existing caller that does not pass it gets
                byte-for-byte the same behavior as before this
                integration.
            execution_intent: Optional. Integration Sprint 4 addition.
                When provided (together with the six arguments above),
                each :meth:`run` call also passes the real
                ``PolicyGuardResult`` produced by ``policy_guard``
                straight into ``execution_intent.build()`` -- no
                reconstruction, no transformation, no duplication of
                that ``PolicyGuardResult``. Defaults to ``None`` --
                every existing caller that does not pass it gets
                byte-for-byte the same behavior as before this
                integration.
            execution_planner: Optional. Integration Sprint 5 addition.
                When provided (together with the seven arguments
                above), each :meth:`run` call also passes the real
                ``ExecutionIntentResult`` produced by
                ``execution_intent`` straight into
                ``execution_planner.plan()`` -- no reconstruction, no
                transformation, no duplication of that
                ``ExecutionIntentResult``. Defaults to ``None`` -- every
                existing caller that does not pass it gets byte-for-byte
                the same behavior as before this integration.
            execution_coordinator: Optional. Integration Sprint 6
                addition. When provided (together with the eight
                arguments above), each :meth:`run` call also passes the
                real ``ExecutionPlan`` produced by ``execution_planner``
                straight into ``execution_coordinator.coordinate()`` --
                no reconstruction, no transformation, no duplication of
                that ``ExecutionPlan``. Defaults to ``None`` -- every
                existing caller that does not pass it gets byte-for-byte
                the same behavior as before this integration.
            portfolio_engine: Optional. Integration Sprint 7 addition.
                When provided (together with the nine arguments above),
                each :meth:`run` call also passes the real
                ``ExecutionCoordinatorResult`` produced by
                ``execution_coordinator`` straight into
                ``portfolio_engine.evaluate()`` -- no reconstruction, no
                transformation, no duplication of that
                ``ExecutionCoordinatorResult``. Defaults to ``None`` --
                every existing caller that does not pass it gets
                byte-for-byte the same behavior as before this
                integration.
            portfolio_risk: Optional. Integration Sprint 8 addition.
                When provided (together with the ten arguments above),
                each :meth:`run` call also passes the real
                ``PortfolioEngineResult`` produced by ``portfolio_engine``
                straight into ``portfolio_risk.assess()`` -- no
                reconstruction, no transformation, no duplication of
                that ``PortfolioEngineResult``. Defaults to ``None`` --
                every existing caller that does not pass it gets
                byte-for-byte the same behavior as before this
                integration.
            learning_loop: Optional. Integration Sprint 9 addition. When
                provided (together with the eleven arguments above),
                each :meth:`run` call also passes the real
                ``PortfolioRiskResult`` produced by ``portfolio_risk``
                straight into ``learning_loop.learn()`` -- no
                reconstruction, no transformation, no duplication of
                that ``PortfolioRiskResult``. Defaults to ``None`` --
                every existing caller that does not pass it gets
                byte-for-byte the same behavior as before this
                integration.
            vision_pipeline: Sprint 151 addition, optional. When
                provided and ``context.metadata`` (see :meth:`run`)
                carries a non-empty ``"chart_path"`` string, each
                :meth:`run` call also runs the modern vision +
                reasoning Skill chain via
                ``Orchestration.vision_market_state_pipeline.VisionMarketStatePipeline``
                and attaches its ``market_state`` output to the
                returned :class:`AnalysisResult`. Defaults to
                ``None`` -- every existing caller that does not pass
                it gets byte-for-byte the same classic-only behavior
                as before this integration (this includes every call
                where ``context.metadata`` has no ``"chart_path"``,
                regardless of whether ``vision_pipeline`` was
                supplied).
            trading_decision_agent: Sprint 152 addition, optional.
                When provided and :meth:`_maybe_run_vision` produced
                a real ``market_state`` mapping, each :meth:`run`
                call also builds a
                :class:`~Orchestration.task.Task` from that mapping's
                ``"symbol"`` field and calls
                ``trading_decision_agent.execute(task)`` exactly
                once, attaching its result to the returned
                :class:`AnalysisResult` as ``.trading_decision``.
                Defaults to ``None`` -- every existing caller that
                does not pass it gets byte-for-byte the same
                behavior as before this integration (this includes
                every call where no ``market_state`` was produced,
                regardless of whether ``trading_decision_agent`` was
                supplied).
        """
        self._executor = executor
        self._analysis_pipeline = analysis_pipeline
        self._tool_context_builder = tool_context_builder
        self._tool_registry = tool_registry
        self._memory_recorder = memory_recorder
        self._memory_store = memory_store
        self._reflector = reflector
        self._decision_engine = decision_engine
        self._decision_policy = decision_policy
        self._policy_guard = policy_guard
        self._execution_intent = execution_intent
        self._execution_planner = execution_planner
        self._execution_coordinator = execution_coordinator
        self._portfolio_engine = portfolio_engine
        self._portfolio_risk = portfolio_risk
        self._learning_loop = learning_loop
        self._vision_pipeline = vision_pipeline
        self._trading_decision_agent = trading_decision_agent

    def run(self, context: ServiceContext) -> str:
        """Run the 11-step ``AnalysisPipeline`` for ``context`` through
        Runtime, returning the final formatted tool-message string.

        A private, single-use Tool handler is registered under a unique
        name for the duration of this call (implementation detail, see
        module docstring decision #4/#5), then unregistered in a
        ``finally`` block regardless of outcome -- including when the
        handler raises, which ``Executor.execute`` surfaces as
        ``Core.exceptions.ToolExecutionError`` (error-as-data through
        ``GenericSandbox``, unchanged Runtime behavior), not a silent
        failure.

        Args:
            context: The already-built ``ServiceContext`` to run the
                pipeline for -- built by the caller exactly as it is
                today for ``AnalysisPipeline.run`` directly (unchanged
                contract).

        Returns:
            An :class:`AnalysisResult` -- a ``str`` subclass equal to
            the formatted tool-message text
            ``ToolContextBuilder.build()`` already produces for the
            existing (non-Runtime) call path (identical in shape and
            content to the pre-Sprint-151 plain ``str`` return value),
            additionally carrying ``.market_state`` (Sprint 151): the
            modern vision pipeline's output when ``context.metadata``
            supplied a chart, ``None`` otherwise. A vision-specific
            failure never affects the classic text above -- see
            :meth:`_maybe_run_vision`.

        Raises:
            Core.exceptions.ToolExecutionError: If ``analysis_pipeline``
                or ``tool_context_builder`` raises while the Tool handler
                runs.
            Core.exceptions.ApprovalDenied: If the configured
                ``ApprovalPort`` denies the INTENT (unreachable under the
                Phase 1 ``AlwaysApprove`` default).
            Core.exceptions.ApprovalPending: Same reachability note as
                above, for a ``PENDING`` outcome.
        """
        tool_name = self._register_tool_handler(context)
        try:
            classic_analysis = self._executor.execute(tool_name)
        finally:
            self._tool_registry.unregister(tool_name)

        market_state = self._maybe_run_vision(context)
        trading_decision = self._maybe_run_trading_decision(market_state)
        return AnalysisResult(classic_analysis, market_state, trading_decision)

    def _maybe_run_vision(self, context: ServiceContext) -> Optional[Any]:
        """Run the modern vision pipeline for ``context`` iff valid
        chart input is present -- otherwise a no-op (Sprint 151).

        No chart input supplied (``self._vision_pipeline`` is ``None``,
        or ``context.metadata[VISION_CHART_PATH_METADATA_KEY]`` is
        missing/empty/non-``str``): returns ``None`` immediately,
        calling neither the vision Skill chain nor any Vision Provider
        -- the classic path above is completely unaffected.

        Valid chart input supplied: delegates to
        ``VisionMarketStatePipeline.run()``. Any exception it raises
        is caught here (logged, not swallowed silently) and converted
        into a deterministic ``"UNAVAILABLE"`` market-state mapping,
        so a vision-specific failure can never crash or replace the
        classic analysis result already computed in :meth:`run`.

        Args:
            context: The same ``ServiceContext`` passed to :meth:`run`.

        Returns:
            The ``market_state`` mapping, a deterministic
            ``{"market_state": "UNAVAILABLE", ...}`` mapping on
            failure, or ``None`` when no chart input was supplied.
        """
        if self._vision_pipeline is None:
            return None

        chart_path = context.metadata.get(VISION_CHART_PATH_METADATA_KEY)
        if not isinstance(chart_path, str) or chart_path == "":
            return None

        symbol = context.metadata.get(MetadataKeys.TICKER)
        timeframe = context.metadata.get(MetadataKeys.INTERVAL)

        try:
            return self._vision_pipeline.run(
                symbol=symbol, timeframe=timeframe, chart_path=chart_path
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Vision pipeline failed for chart_path={chart_path!r}: {exc}"
            )
            return {
                "market_state": "UNAVAILABLE",
                "state_reason": "Vision pipeline raised an unexpected exception",
                "error": str(exc),
            }

    def _maybe_run_trading_decision(self, market_state: Optional[Any]) -> Optional[Any]:
        """Bridge a real ``market_state`` mapping into
        ``TradingDecisionAgent`` -- otherwise a no-op (Sprint 152).

        No bridging is attempted (returns ``None`` immediately,
        calling neither ``Task`` construction nor
        ``TradingDecisionAgent.execute()``) when
        ``self._trading_decision_agent`` is ``None``, or when
        ``market_state`` is ``None``/not a ``Mapping`` (this also
        covers :meth:`_maybe_run_vision`'s no-chart ``None`` return
        and its ``\"UNAVAILABLE\"`` failure mapping -- both leave the
        production trading-decision path untouched, exactly as before
        this integration).

        A real ``market_state`` mapping seeds a freshly built
        ``Orchestration.task.Task`` using only its own ``\"symbol\"``
        field (``metadata={\"symbols\": [symbol] if symbol else [],
        \"capital\": 0}``) -- no new reasoning or trading logic is
        introduced here; ``capital`` is left at ``TradingDecisionAgent``'s
        own documented safe default of ``0``, exactly as it already
        behaves for any caller that omits it.

        Any exception raised while building the ``Task`` or while
        ``trading_decision_agent.execute()`` runs is caught here
        (logged, not swallowed silently) so a trading-decision-specific
        failure can never crash or replace the classic analysis result
        already computed in :meth:`run` -- mirroring
        :meth:`_maybe_run_vision`'s own safety boundary.

        Args:
            market_state: The same value :meth:`_maybe_run_vision`
                already returned for this call.

        Returns:
            The ``dict`` ``TradingDecisionAgent.execute()`` produces,
            or ``None`` when no bridging was attempted or it failed.
        """
        if self._trading_decision_agent is None:
            return None

        if not isinstance(market_state, Mapping):
            return None

        symbol = market_state.get("symbol")
        symbols = [symbol] if isinstance(symbol, str) and symbol else []

        try:
            task = Task(
                name="trading-decision",
                description=(
                    "Trading decision derived from the vision-produced "
                    "MarketState for this run."
                ),
                metadata={"symbols": symbols, "capital": 0},
            )
            return self._trading_decision_agent.execute(task)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"TradingDecisionAgent failed for market_state={market_state!r}: {exc}"
            )
            return None

    def _register_tool_handler(self, context: ServiceContext) -> str:
        """Register a private, single-use Tool wrapping ``context`` and
        return its name.

        The handler closes over ``context`` (and ``self``) directly --
        it takes no parameters and is never called with ``args``/
        ``kwargs`` from ``Executor.execute``. This is what keeps
        ``ServiceContext``/``dict[str, ServiceResult]`` off the
        Runtime/Executor JSON tool-call boundary entirely (see module
        docstring decision #5): only the ``str`` this handler returns
        ever crosses it.
        """
        tool_name = f"{_TOOL_NAME_PREFIX}::{uuid.uuid4()}"

        def _handler() -> str:
            results = self._analysis_pipeline.run(context)
            self._maybe_reflect_and_decide(results)
            return self._tool_context_builder.build(results)

        self._tool_registry.register(
            Tool(
                name=tool_name,
                description=(
                    "Private, single-use Tool: runs the 11-step AnalysisPipeline "
                    "for one ServiceContext and formats the result into one "
                    "tool-message string. Registered and unregistered per "
                    "RuntimeAnalysisPipeline.run() call -- not a standing Tool."
                ),
                handler=_handler,
            )
        )
        return tool_name

    def _maybe_reflect_and_decide(self, results: Dict[str, ServiceResult]) -> None:
        """Integration Sprint 1: Reflection -> DecisionEngine.
        Integration Sprint 2: DecisionEngine -> DecisionPolicy.
        Integration Sprint 3: DecisionPolicy -> PolicyGuard.
        Integration Sprint 4: PolicyGuard -> ExecutionIntent.
        Integration Sprint 5: ExecutionIntent -> ExecutionPlanner.
        Integration Sprint 6: extends this by one further stage,
        ExecutionPlanner -> ExecutionCoordinator.
        Integration Sprint 7: extends this by one further stage,
        ExecutionCoordinator -> PortfolioEngine.
        Integration Sprint 8: extends this by one further stage,
        PortfolioEngine -> PortfolioRisk.
        Integration Sprint 9: extends this by one further stage,
        PortfolioRisk -> LearningLoop, and stops there. No-op unless
        every one of ``memory_recorder``, ``memory_store``,
        ``reflector``, and ``decision_engine`` was provided at
        construction -- so this call site has zero effect on any
        existing caller.

        When ``decision_policy`` was also provided at construction, the
        real ``Decision`` object returned by ``decision_engine.decide()``
        is passed directly into ``decision_policy.apply()`` -- not
        recreated, not transformed, not duplicated. When
        ``policy_guard`` was also provided, the real
        ``DecisionPolicyResult`` returned by ``decision_policy.apply()``
        is likewise passed directly into ``policy_guard.evaluate()`` --
        not recreated, not transformed, not duplicated. When
        ``execution_intent`` was also provided, the real
        ``PolicyGuardResult`` returned by ``policy_guard.evaluate()`` is
        likewise passed directly into ``execution_intent.build()`` --
        not recreated, not transformed, not duplicated. When
        ``execution_planner`` was also provided, the real
        ``ExecutionIntentResult`` returned by ``execution_intent.build()``
        is likewise passed directly into ``execution_planner.plan()`` --
        not recreated, not transformed, not duplicated. When
        ``execution_coordinator`` was also provided, the real
        ``ExecutionPlan`` returned by ``execution_planner.plan()`` is
        likewise passed directly into
        ``execution_coordinator.coordinate()`` -- not recreated, not
        transformed, not duplicated. When ``portfolio_engine`` was also
        provided, the real ``ExecutionCoordinatorResult`` returned by
        ``execution_coordinator.coordinate()`` is likewise passed
        directly into ``portfolio_engine.evaluate()`` -- not recreated,
        not transformed, not duplicated. When ``portfolio_risk`` was
        also provided, the real ``PortfolioEngineResult`` returned by
        ``portfolio_engine.evaluate()`` is likewise passed directly into
        ``portfolio_risk.assess()`` -- not recreated, not transformed,
        not duplicated. When ``learning_loop`` was also provided, the
        real ``PortfolioRiskResult`` returned by ``portfolio_risk
        .assess()`` is likewise passed directly into
        ``learning_loop.learn()`` -- not recreated, not transformed, not
        duplicated. The resulting ``PortfolioEngineResult``,
        ``PortfolioRiskResult``, and ``LearningLoopResult`` are only
        ever logged via ``logger.debug()`` -- none is returned, stored,
        or exposed through any public API, and none changes
        ``RuntimeAnalysisPipeline.run()``'s return value. When any of
        ``decision_policy``/``policy_guard``/``execution_intent``/
        ``execution_planner``/``execution_coordinator``/
        ``portfolio_engine``/``portfolio_risk``/``learning_loop`` was
        not provided, behavior stops at the corresponding earlier
        sprint's stage.

        Does not call, or wire in, AutonomousAgent -- out of scope for
        this integration step.
        """
        if (
            self._memory_recorder is None
            or self._memory_store is None
            or self._reflector is None
            or self._decision_engine is None
        ):
            return

        observation = _observation_from_analysis_results(results)
        self._memory_recorder.record(observation)
        records = self._memory_store.list()
        reflection_record = self._reflector.reflect(records)

        # Score adapter: ReflectionRecord (Phase 1) carries exactly one
        # numeric signal -- source_record_count. This is a direct,
        # literal type conversion (int -> float), not a synthesized
        # trading score; Reflection does not yet produce one.
        score = float(reflection_record.source_record_count)
        decision = self._decision_engine.decide(score)

        logger.debug(
            "RuntimeAnalysisPipeline reflection->decision: "
            f"source_record_count={reflection_record.source_record_count} "
            f"score={score} action={decision.action} "
            f"confidence={decision.confidence}"
        )

        if self._decision_policy is None:
            return

        # The real Decision object above, passed as-is -- no new Decision
        # is constructed, no field is copied or transformed.
        policy_result = self._decision_policy.apply(decision)

        logger.debug(
            "RuntimeAnalysisPipeline decision->policy: "
            f"action={policy_result.action} "
            f"confidence={policy_result.confidence} "
            f"position_size={policy_result.position_size} "
            f"allow_entry={policy_result.allow_entry} "
            f"allow_exit={policy_result.allow_exit} "
            f"risk_level={policy_result.risk_level}"
        )

        if self._policy_guard is None:
            return

        # The real DecisionPolicyResult above, passed as-is -- no new
        # DecisionPolicyResult is constructed, no field is copied or
        # transformed.
        guard_result = self._policy_guard.evaluate(policy_result)

        logger.debug(
            "RuntimeAnalysisPipeline policy->guard: "
            f"approved={guard_result.approved} "
            f"action={guard_result.action} "
            f"risk_level={guard_result.risk_level} "
            f"position_size={guard_result.position_size} "
            f"violations={guard_result.violations}"
        )

        if self._execution_intent is None:
            return

        # The real PolicyGuardResult above, passed as-is -- no new
        # PolicyGuardResult is constructed, no field is copied or
        # transformed.
        intent_result = self._execution_intent.build(guard_result)

        logger.debug(
            "RuntimeAnalysisPipeline guard->intent: "
            f"ready={intent_result.ready} "
            f"action={intent_result.action} "
            f"risk_level={intent_result.risk_level} "
            f"position_size={intent_result.position_size} "
            f"denial_reason={intent_result.denial_reason!r}"
        )

        if self._execution_planner is None:
            return

        # The real ExecutionIntentResult above, passed as-is -- no new
        # ExecutionIntentResult is constructed, no field is copied or
        # transformed.
        execution_plan = self._execution_planner.plan(intent_result)

        logger.debug(
            "RuntimeAnalysisPipeline intent->plan: "
            f"planned={execution_plan.planned} "
            f"action={execution_plan.action} "
            f"risk_level={execution_plan.risk_level} "
            f"position_size={execution_plan.position_size} "
            f"skip_reason={execution_plan.skip_reason!r}"
        )

        if self._execution_coordinator is None:
            return

        # The real ExecutionPlan above, passed as-is -- no new
        # ExecutionPlan is constructed, no field is copied or
        # transformed.
        coordinator_result = self._execution_coordinator.coordinate(execution_plan)

        logger.debug(
            "RuntimeAnalysisPipeline plan->coordinator: "
            f"coordinated={coordinator_result.coordinated} "
            f"action={coordinator_result.action} "
            f"risk_level={coordinator_result.risk_level} "
            f"position_size={coordinator_result.position_size} "
            f"sequence_position={coordinator_result.sequence_position} "
            f"hold_reason={coordinator_result.hold_reason!r}"
        )

        if self._portfolio_engine is None:
            return

        # The real ExecutionCoordinatorResult above, passed as-is -- no
        # new ExecutionCoordinatorResult is constructed, no field is
        # copied or transformed.
        portfolio_result = self._portfolio_engine.evaluate(coordinator_result)

        logger.debug(
            "RuntimeAnalysisPipeline coordinator->portfolio: "
            f"approved={portfolio_result.approved} "
            f"allocation_weight={portfolio_result.allocation_weight} "
            f"exposure={portfolio_result.exposure}"
        )

        if self._portfolio_risk is None:
            return

        # The real PortfolioEngineResult above, passed as-is -- no new
        # PortfolioEngineResult is constructed, no field is copied or
        # transformed.
        risk_result = self._portfolio_risk.assess(portfolio_result)

        logger.debug(
            "RuntimeAnalysisPipeline portfolio->risk: "
            f"approved={risk_result.approved} "
            f"exposure_level={risk_result.exposure_level} "
            f"diversification_level={risk_result.diversification_level} "
            f"violations={risk_result.violations}"
        )

        if self._learning_loop is None:
            return

        # The real PortfolioRiskResult above, passed as-is -- no new
        # PortfolioRiskResult is constructed, no field is copied or
        # transformed.
        learning_result = self._learning_loop.learn(risk_result)

        logger.debug(
            "RuntimeAnalysisPipeline risk->learning: "
            f"recorded={learning_result.recorded} "
            f"signal={learning_result.signal} "
            f"violation_count={learning_result.violation_count}"
        )

    def health_check(self) -> bool:
        """Delegate to the wrapped ``AnalysisPipeline``'s own health_check().

        Mirrors ``AnalysisPipelineAdapter.health_check`` in spirit (pure
        passthrough), kept as a plain method here rather than routed
        through Runtime -- health_check is a liveness probe, not an
        analysis Tool call, and decision #1 scopes "one big Tool" to the
        analysis pipeline itself.
        """
        return self._analysis_pipeline.health_check()