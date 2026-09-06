from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Type
from Agents.agent_registry import AgentRegistry, agent_registry
from Agents.executor import Executor
from Agents.memory import ConversationMemory
from Agents.planner import Planner
from Agents.stock_agent import StockAgent
from Agents.tool_registry import Tool, ToolRegistry, tool_registry
from Core.analysis_pipeline import AnalysisPipeline
from Core.approval import ToolWhitelistApprovalPort
from Core.approval_config import build_approval_port
from Core.config import Config, config
from Core.exceptions import ConfigurationError
from Core.logger import get_logger
from Core.tool_context_builder import ToolContextBuilder
from Core.bootstrap import DEFAULT_PAPER_ACCOUNT_ID
from Database.account_constants import DEFAULT_RISK_MAX_ORDER_VALUE
from Database.database_config import DatabaseConfig
from Database.database_manager import DatabaseManager
from Database.sqlite_database import SQLiteDatabase
from Orchestration.memory import MemoryRecorder, MemoryStore
from Orchestration.observation import ObservationRecorder
from Orchestration.planner import GoalPlanner
from Orchestration.reflection import Reflector
from Orchestration.decision_engine import DecisionEngine
from Orchestration.decision_policy import DecisionPolicy
from Orchestration.autonomous_agent import AutonomousAgent
from Orchestration.autonomous_scheduler import AutonomousScheduler
from Orchestration.execution_coordinator import ExecutionCoordinator
from Orchestration.execution_intent import ExecutionIntent
from Orchestration.execution_planner import ExecutionPlanner
from Orchestration.learning_loop import LearningLoop
from Orchestration.portfolio_engine import PortfolioEngine
from Orchestration.portfolio_risk import PortfolioRisk
from Orchestration.policy_guard import PolicyGuard
from Orchestration.runtime_analysis_pipeline import RuntimeAnalysisPipeline
from Orchestration.service_skill import SKILL_METADATA_BY_SERVICE, ServiceSkill
from Orchestration.capital_allocation_skill import CapitalAllocationSkill
from Orchestration.market_analysis_agent import MarketAnalysisAgent
from Orchestration.market_analysis_skill import MarketAnalysisSkill
from Orchestration.market_fundamental_tool import MarketFundamentalTool
from Orchestration.market_news_tool import MarketNewsTool
from Orchestration.market_price_tool import MarketPriceTool
from Orchestration.paper_execution_tool import PaperExecutionTool
from Orchestration.copilot_tool import CopilotTool
from Orchestration.order_validation_skill import OrderValidationSkill
from Orchestration.paper_trading_skill import PaperTradingSkill
from Orchestration.portfolio_alert_skill import PortfolioAlertSkill
from Orchestration.portfolio_analysis_skill import PortfolioAnalysisSkill
from Orchestration.portfolio_monitor_skill import PortfolioMonitorSkill
from Orchestration.portfolio_performance_skill import PortfolioPerformanceSkill
from Orchestration.portfolio_report_skill import PortfolioReportSkill
from Orchestration.portfolio_update_skill import PortfolioUpdateSkill
from Orchestration.position_risk_skill import PositionRiskSkill
from Orchestration.position_sizing_skill import PositionSizingSkill
from Orchestration.recommendation_skill import RecommendationSkill
from Orchestration.agents_tool_permission_adapter import AgentsToolPermissionAdapter
from Orchestration.permission_context import PermissionContext
from Orchestration.permissioned_tool import PermissionedTool
from Orchestration.tool_registry import ToolRegistry as OrchestrationToolRegistry
from Orchestration.tool_resolver import ToolResolver
from Orchestration.tool_manager import ToolManager
from Orchestration.trade_history_skill import TradeHistorySkill
from Orchestration.trade_plan_skill import TradePlanSkill
from Orchestration.trading_decision_agent import TradingDecisionAgent
from Orchestration.vision_market_state_pipeline import VisionMarketStatePipeline
from Orchestration.watchlist_analysis_skill import WatchlistAnalysisSkill
from Orchestration.watchlist_scanner import WatchlistScanner
from Orchestration.idx_daily_scheduler import IDXDailyScheduler
from Providers import (
    BaseProvider,
    GeminiProvider,
    NineRouterProvider,
    OllamaProvider,
    ProviderManager,
    ProviderSelector,
    provider_manager,
)
from Providers.gemini_vision_provider import GeminiVisionProvider
from Repository.external.news_repository import NewsRepository
from Repository.external.stock_data_repository import StockDataRepository
from Business.account_balance_service import AccountBalanceService
from Business.daily_report_orchestrator import DailyReportOrchestrator
from Business.execution_policy_config import ExecutionPolicy, load_execution_policy
from Business.execution_service import ExecutionService
from Business.manual_scan_service import ManualScanService
from Business.notification_builder import NotificationBuilder
from Business.notification_dispatcher import NotificationDispatcher
from Business.notification_manager import NotificationManager
from Business.order_lifecycle_service import OrderLifecycleService
from Business.paper_trading_engine import PaperTradingEngine
from Business.position_manager import PositionManager
from Business.ranking_engine import RankingEngine
from Business.recommendation_service import RecommendationService
from Business.report_service import ReportService
from Business.telegram_notification_channel import TelegramNotificationChannel
from Business.unrealized_pnl_engine import UnrealizedPnLEngine
from Business.expectancy_engine import ExpectancyEngine
from Business.maximum_drawdown_engine import MaximumDrawdownEngine
from Business.performance_summary_service import PerformanceSummaryService
from Business.performance_summary_production_service import PerformanceSummaryProductionService
from Business.portfolio_snapshot_service import PortfolioSnapshotService
from Business.reconciliation_engine import ReconciliationEngine
from Business.execution_rate_engine import ExecutionRateEngine
from Business.failure_rate_engine import FailureRateEngine
from Business.position_performance_engine import PositionPerformanceEngine
from Business.profit_factor_engine import ProfitFactorEngine
from Business.trade_statistics_engine import TradeStatisticsEngine
from Business.position_episode_replay_engine import PositionEpisodeReplayEngine
from Business.strategy_performance_engine import StrategyPerformanceEngine
from Business.strategy_performance_service import StrategyPerformanceService
from Business.trade_attribution_engine import TradeAttributionEngine
from Business.trade_attribution_service import TradeAttributionService
from Business.trade_holding_period_engine import TradeHoldingPeriodEngine
from Business.win_rate_engine import WinRateEngine
from Business.market_regime_engine import MarketRegimeEngine
from Business.market_regime_service import MarketRegimeService
from Business.market_regime_performance_engine import MarketRegimePerformanceEngine
from Business.market_regime_attribution_service import MarketRegimeAttributionService
from Repository.persistence.account_repository import AccountRepository
from Repository.persistence.order_approval_repository import OrderApprovalRepository
from Repository.persistence.order_idempotency_repository import OrderIdempotencyRepository
from Repository.persistence.order_repository import OrderRepository
from Repository.persistence.performance_repository import PerformanceRepository
from Business.decision_brief_policy import DecisionBriefPolicy
from Business.risk_ledger_policy import RiskLedgerPolicy
from Business.idx_market_calendar import IDXMarketCalendar, load_idx_market_calendar
from Business.data_freshness_policy import DataFreshnessPolicy, load_data_freshness_policy
from Business.notification_dedup_policy import NotificationDedupPolicy, load_notification_dedup_policy
from Repository.persistence.daily_performance_repository import DailyPerformanceRepository
from Repository.persistence.decision_brief_repository import DecisionBriefRepository
from Repository.persistence.journal_repository import JournalRepository
from Repository.persistence.brief_approval_repository import BriefApprovalRepository
from Repository.persistence.observation_window_repository import ObservationWindowRepository
from Repository.persistence.risk_limits_repository import RiskLimitsRepository
from Repository.persistence.scheduler_state_repository import SchedulerStateRepository
from Repository.persistence.notification_dedup_repository import NotificationDedupRepository
from Repository.persistence.audit_event_repository import AuditEventRepository
from Repository.persistence.portfolio_snapshot_repository import PortfolioSnapshotRepository
from Repository.persistence.position_repository import PositionRepository
from Repository.persistence.snapshot_repository import SnapshotRepository
from Repository.persistence.trade_repository import TradeRepository
from Repository.persistence.watchlist_repository import WatchlistRepository
from Repository.persistence.telegram_command_audit_repository import TelegramCommandAuditRepository
from Repository.persistence.telegram_inbound_state_repository import TelegramInboundStateRepository
from Repository.persistence.final_review_record_repository import FinalReviewRecordRepository
from Repository.persistence.operator_feedback_repository import OperatorFeedbackRepository
from Business.telegram_allowlist_policy import TelegramAllowlistPolicy, load_telegram_allowlist_policy
from Orchestration.telegram_command_executor import TelegramCommandExecutor
from Orchestration.telegram_inbound_control_plane import TelegramInboundControlPlane
from Services.backtest_service import BacktestService
from Services.chart_service import ChartService
from Services.fundamental_service import FundamentalService
from Services.metadata_keys import MetadataKeys
from Services.moving_average_service import MovingAverageService
from Services.news_service import NewsService
from Services.notification_service import NotificationService
from Services.pattern_service import PatternService
from Services.decision_brief_service import DecisionBriefService
from Services.journal_service import JournalService
from Services.observation_window_service import ObservationWindowService
from Services.paper_review_service import PaperReviewService
from Services.sustained_use_final_review_service import SustainedUseFinalReviewService
from Services.sustained_use_report_service import SustainedUseReportService
from Services.sustained_use_review_service import SustainedUseReviewService
from Services.health_audit_service import HealthAuditService
from Services.risk_management_service import RiskManagementService
from Services.scoring_service import ScoringService
from Services.service_context import ServiceContext
from Services.service_registry import ServiceRegistry, service_registry
from Services.stock_service import StockService
from Services.technical_indicator_service import TechnicalIndicatorService
from Services.technical_score_service import TechnicalScoreService

logger = get_logger(__name__)

DEFAULT_PROVIDER_NAME = "gemini"
DEFAULT_AGENT_NAME = "stock_agent"

#: provider_kind -> concrete BaseProvider class. Stage L1 addition
#: (additive only): selects *which class* to construct. Distinct from
#: provider_name, which remains purely the ProviderManager registry key
#: (unchanged meaning -- see _build_provider docstring). Adding a future
#: provider (OpenAI, Anthropic, LM Studio, ...) is a one-line addition
#: here; no change to _build_provider's flow itself (Open/Closed).
_PROVIDER_CLASSES: Dict[str, Type[BaseProvider]] = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "nine_router": NineRouterProvider,
}


@dataclass(frozen=True)
class ApplicationGraph:
    """The fully-wired, production object graph produced by
    :func:`build_application`.

    Every field holds a real, production-configured instance -- never a
    test double. The five registries this module writes to
    (``config``, ``tool_registry``, ``provider_manager``,
    ``agent_registry``, ``service_registry``) are process-wide
    singletons by their own class design (unchanged here) -- this graph
    simply exposes the one shared instance each already resolves to; it
    never constructs a second one.

    ``database_manager`` is different from those five: it is NOT a
    process-wide singleton (``Database.database_manager.DatabaseManager``
    defines no such thing), so a fresh instance is constructed on every
    :func:`build_application` call, same as ``executor``/``planner``/
    ``agent``. It wraps a real, unconnected
    :class:`Database.sqlite_database.SQLiteDatabase` -- see
    :func:`_build_database_manager` for why it is never connected here.

    ``runtime_analysis_pipeline`` (Stage L11 addition, additive only):
    an :class:`~Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline`
    wrapping the same ``executor``/``analysis_pipeline``/
    ``tool_context_builder``/``tool_registry`` this graph already builds.

    Stage L12 (LOCKED decision, additive): this same instance is now also
    passed into ``agent``'s own ``runtime_analysis_pipeline`` constructor
    argument, so ``StockAgent`` routes its analysis calls through it --
    i.e. through ``Core.runtime.Runtime`` as the execution kernel --
    instead of calling ``analysis_pipeline`` directly. ``graph.agent``
    and ``graph.runtime_analysis_pipeline`` are still the same field
    each was before (no field renamed or removed); what changed is that
    ``StockAgent`` now actually uses the latter. ``analysis_pipeline``
    remains reachable unwrapped via ``graph.agent.analysis_pipeline``
    (StockAgent's optional-fallback constructor argument, see
    ``Agents.stock_agent.StockAgent.__init__``) -- only the production
    call path changed, not the object graph's shape.

    ``service_skills`` (Stage L13 addition, additive only, "Granular
    Skills"): a ``Dict[str, ServiceSkill]`` -- one
    :class:`~Orchestration.service_skill.ServiceSkill` per Service already
    held by ``service_registry``, keyed by ``service.name`` (see
    :func:`_build_service_skills`). Each is also registered into this
    same ``tool_registry`` under a stable ``"skill.<service_name>"`` Tool
    name. Purely additive capability: nothing in the production
    ``StockAgent`` -> ``RuntimeAnalysisPipeline`` -> ``Runtime`` ->
    ``AnalysisPipeline`` call path reads or calls anything in this field
    or these Tools -- ``agent`` is constructed exactly as before this
    stage. ``service_skills`` exists on the graph only so a future stage
    (L14, Planner) can discover and use it.

    ``goal_planner`` (Stage L15 Phase 1 Step 7 addition, additive only,
    "Composition Root Integration"): a
    :class:`~Orchestration.planner.GoalPlanner` constructed over this
    same ``service_skills`` mapping (see :func:`_build_goal_planner`) --
    reuses the exact dict already built above; no ``ServiceSkill`` is
    ever constructed a second time. Purely additive capability, same
    shape as ``service_skills`` above: nothing in the production
    ``StockAgent`` -> ``RuntimeAnalysisPipeline`` -> ``Runtime`` ->
    ``AnalysisPipeline`` call path reads or calls ``goal_planner`` --
    ``agent`` (``StockAgent``) is constructed exactly as before this
    stage, and ``GoalPlanner`` is not registered as a Tool. Phase 2,
    Sprint 7 additionally injects this exact singleton into
    ``autonomous_agent`` (see :func:`_build_autonomous_agent`) -- still
    not into ``agent``/``StockAgent``, and still no second
    ``GoalPlanner`` instance.

    ``observation_recorder``, ``memory_store``, ``memory_recorder``,
    ``reflector`` (Task 1A addition, additive only, construction-only
    scope): an :class:`~Orchestration.observation.ObservationRecorder`,
    :class:`~Orchestration.memory.MemoryStore`,
    :class:`~Orchestration.memory.MemoryRecorder` (wrapping that same
    ``memory_store``), and :class:`~Orchestration.reflection.Reflector`
    -- each constructed with no collaborators beyond what is shown here
    (see :func:`_build_memory_recorder` for why ``memory_recorder`` must
    be built after ``memory_store``). None of the four is passed to
    ``agent``, ``runtime_analysis_pipeline``, or ``goal_planner``, and
    none is registered as a Tool -- this stage is graph-visibility only,
    matching the same additive pattern ``goal_planner`` (L15) already
    established. ``MemoryStore``'s lifetime is decided by Task 2:
    constructed fresh on every :func:`build_application` call, same as
    ``database_manager`` -- not a process-wide singleton. Task 2 also
    gives ``MemoryStore`` an optional, configurable in-memory retention
    policy (``max_size``/``ttl_seconds``, both default ``None`` --
    disabled); this graph still constructs it with no arguments
    (:func:`_build_memory_store`), so retention remains inactive on the
    production graph exactly as it was before Task 2, preserving
    current behavior unchanged.

    ``policy_guard`` (Stage L21 addition, additive only, construction-only
    scope): a :class:`~Orchestration.policy_guard.PolicyGuard` -- a
    stateless, deterministic guard-rail component with no collaborators
    (see :func:`_build_policy_guard`). Not passed to ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``, or
    ``decision_policy``, and not registered as a Tool -- this stage is
    graph-visibility only, following the exact same additive pattern
    ``decision_engine`` (L19) and ``decision_policy`` (L20) already
    established.

    ``execution_intent`` (Stage L22 addition, additive only,
    construction-only scope): an
    :class:`~Orchestration.execution_intent.ExecutionIntent` -- a
    stateless, deterministic component with no collaborators (see
    :func:`_build_execution_intent`). Not passed to ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, or ``policy_guard``, and not registered as a
    Tool -- this stage is graph-visibility only, following the exact
    same additive pattern ``decision_engine`` (L19),
    ``decision_policy`` (L20), and ``policy_guard`` (L21) already
    established.

    ``execution_planner`` (Stage L23 addition, additive only,
    construction-only scope): an
    :class:`~Orchestration.execution_planner.ExecutionPlanner` -- a
    stateless, deterministic component with no collaborators (see
    :func:`_build_execution_planner`). Not passed to ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, or ``execution_intent``,
    and not registered as a Tool -- this stage is graph-visibility
    only, following the exact same additive pattern
    ``decision_engine`` (L19), ``decision_policy`` (L20),
    ``policy_guard`` (L21), and ``execution_intent`` (L22) already
    established.

    ``execution_coordinator`` (Stage L24 addition, additive only,
    construction-only scope): an
    :class:`~Orchestration.execution_coordinator.ExecutionCoordinator`
    -- a stateless, deterministic component with no collaborators (see
    :func:`_build_execution_coordinator`). Not passed to ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``, or
    ``execution_planner``, and not registered as a Tool -- this stage
    is graph-visibility only, following the exact same additive
    pattern ``decision_engine`` (L19), ``decision_policy`` (L20),
    ``policy_guard`` (L21), ``execution_intent`` (L22), and
    ``execution_planner`` (L23) already established.

    ``portfolio_engine`` (Stage L25 addition, additive only,
    construction-only scope): a
    :class:`~Orchestration.portfolio_engine.PortfolioEngine` -- a
    stateless, deterministic component with no collaborators (see
    :func:`_build_portfolio_engine`). Not passed to ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``,
    ``execution_planner``, or ``execution_coordinator``, and not
    registered as a Tool -- this stage is graph-visibility only,
    following the exact same additive pattern ``decision_engine``
    (L19), ``decision_policy`` (L20), ``policy_guard`` (L21),
    ``execution_intent`` (L22), ``execution_planner`` (L23), and
    ``execution_coordinator`` (L24) already established.

    ``portfolio_risk`` (Stage L26 addition, additive only,
    construction-only scope): a
    :class:`~Orchestration.portfolio_risk.PortfolioRisk` -- a
    stateless, deterministic component with no collaborators (see
    :func:`_build_portfolio_risk`). Not passed to ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``,
    ``execution_planner``, ``execution_coordinator``, or
    ``portfolio_engine``, and not registered as a Tool -- this stage
    is graph-visibility only, following the exact same additive
    pattern ``decision_engine`` (L19), ``decision_policy`` (L20),
    ``policy_guard`` (L21), ``execution_intent`` (L22),
    ``execution_planner`` (L23), ``execution_coordinator`` (L24), and
    ``portfolio_engine`` (L25) already established.

    ``learning_loop`` (Stage L27 addition, additive only,
    construction-only scope): a
    :class:`~Orchestration.learning_loop.LearningLoop` -- a stateless,
    deterministic component with no collaborators (see
    :func:`_build_learning_loop`). Not passed to ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``,
    ``execution_planner``, ``execution_coordinator``,
    ``portfolio_engine``, or ``portfolio_risk``, and not registered as
    a Tool -- this stage is graph-visibility only, following the exact
    same additive pattern ``decision_engine`` (L19), ``decision_policy``
    (L20), ``policy_guard`` (L21), ``execution_intent`` (L22),
    ``execution_planner`` (L23), ``execution_coordinator`` (L24),
    ``portfolio_engine`` (L25), and ``portfolio_risk`` (L26) already
    established.

    ``autonomous_agent`` (Stage L28A addition; Phase 2 Sprint 3
    updated its wiring): an
    :class:`~Orchestration.autonomous_agent.AutonomousAgent` -- a
    deterministic composition object that aggregates references to the
    ten L18-L27 stage components already built above, plus (as of
    Phase 2 Sprint 3) the same ``runtime_analysis_pipeline`` singleton
    passed into ``agent`` below (see :func:`_build_autonomous_agent`).
    It does not call, invoke, schedule, or otherwise exercise the ten
    L18-L27 components -- reading one of those fields off it is a
    plain attribute access, nothing more. ``step(context)`` is the one
    exception: it delegates to the constructor-injected
    ``RuntimeAnalysisPipeline``, held privately, never to the ten
    aggregated components. Not passed to ``agent``, and not registered
    as a Tool -- this stage remains graph-visibility only, following
    the exact same additive pattern ``decision_engine`` (L19) through
    ``learning_loop`` (L27) already established.
    """

    config: Config
    tool_registry: ToolRegistry
    provider_manager: ProviderManager
    service_registry: ServiceRegistry
    agent_registry: AgentRegistry
    executor: Executor
    planner: Planner
    agent: StockAgent
    database_manager: DatabaseManager
    runtime_analysis_pipeline: RuntimeAnalysisPipeline
    service_skills: Dict[str, ServiceSkill]
    goal_planner: GoalPlanner
    observation_recorder: ObservationRecorder
    memory_store: MemoryStore
    memory_recorder: MemoryRecorder
    reflector: Reflector
    decision_engine: DecisionEngine
    decision_policy: DecisionPolicy
    policy_guard: PolicyGuard
    execution_intent: ExecutionIntent
    execution_planner: ExecutionPlanner
    execution_coordinator: ExecutionCoordinator
    portfolio_engine: PortfolioEngine
    portfolio_risk: PortfolioRisk
    learning_loop: LearningLoop
    autonomous_agent: AutonomousAgent
    agent_name: str
    provider_name: str
    provider_kind: str
    #: Phase 13, Sprint 151 addition (additive only): the constructed,
    #: reachable ``GeminiVisionProvider`` and the
    #: ``VisionMarketStatePipeline`` that wires the existing modern
    #: vision + reasoning Skill chain around it. The exact same
    #: ``vision_market_state_pipeline`` instance is also passed into
    #: ``runtime_analysis_pipeline`` above (see
    #: :func:`_build_runtime_analysis_pipeline`) -- not constructed a
    #: second time. Neither is passed into ``agent`` directly, nor
    #: registered as a Tool; ``RuntimeAnalysisPipeline.run()`` is the
    #: one and only place this graph activates the vision path, and
    #: only when a caller's ``ServiceContext.metadata`` supplies a
    #: chart (see ``RuntimeAnalysisPipeline._maybe_run_vision``).
    gemini_vision_provider: GeminiVisionProvider
    vision_market_state_pipeline: VisionMarketStatePipeline
     
    trading_decision_agent: TradingDecisionAgent

    #: Sprint 4 STEP 1 addition (additive only, "Paper Trading Engine --
    #: Account wiring"): an ``AccountRepository`` constructed over this
    #: exact graph's ``database_manager`` above (see
    #: :func:`_build_account_repository`) -- the same shared instance,
    #: never a second ``DatabaseManager``. Prior to this stage,
    #: ``AccountRepository`` (built in Sprint 3) had zero callers
    #: anywhere in the production graph; this is the first one.
    #: Graph-visibility only, same additive pattern as
    #: ``portfolio_engine``/``portfolio_risk``/etc.: not passed to
    #: ``agent``, ``runtime_analysis_pipeline``, or
    #: ``trading_decision_agent``, and not registered as a Tool --
    #: nothing about the existing ``StockAgent`` ->
    #: ``RuntimeAnalysisPipeline`` -> ``Runtime`` -> ``AnalysisPipeline``
    #: call path, nor the 14-Skill ``TradingDecisionAgent`` chain, is
    #: touched by this addition. Applying
    #: ``Database.migrations_accounts.ACCOUNTS_MIGRATIONS`` to a real
    #: database remains a separate, manual, unchanged operator step
    #: (``run_account_migrations.py``) -- this field being constructible
    #: does not imply the underlying ``accounts`` table already exists
    #: on whatever database file ``database_manager`` points at.
    account_repository: AccountRepository

    #: Sprint 4 STEP 2 addition (additive only, "PositionRepository +
    #: Position Migration"): a ``PositionRepository`` constructed over
    #: this exact graph's ``database_manager`` above (see
    #: :func:`_build_position_repository`) -- the same shared instance
    #: as ``account_repository``, never a second ``DatabaseManager``,
    #: mirroring the identity requirement established in Sprint 4
    #: STEP 1. Graph-visibility only, same additive pattern as
    #: ``account_repository``: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. This STEP is persistence only --
    #: no ``PositionManager``/``PaperTradingEngine`` business logic
    #: exists yet to consume it. Applying
    #: ``Database.migrations_positions.POSITIONS_MIGRATIONS`` to a
    #: real database remains a separate, manual, unchanged operator
    #: step (``run_position_migrations.py``) -- this field being
    #: constructible does not imply the underlying ``positions`` table
    #: already exists on whatever database file ``database_manager``
    #: points at.
    position_repository: PositionRepository

    #: Sprint 4 STEP 3 addition (additive only, "OrderRepository +
    #: Order Migration"): an ``OrderRepository`` constructed over this
    #: exact graph's ``database_manager`` above (see
    #: :func:`_build_order_repository`) -- the same shared instance as
    #: ``account_repository``/``position_repository``, never a second
    #: ``DatabaseManager``, mirroring the identity requirement
    #: established in Sprint 4 STEP 1/STEP 2. Graph-visibility only,
    #: same additive pattern as ``account_repository``/
    #: ``position_repository``: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. This STEP is persistence only --
    #: no ``OrderLifecycleService``/``ExecutionService``/
    #: ``PaperTradingEngine`` business logic exists yet to consume it.
    #: Applying ``Database.migrations_orders.ORDERS_MIGRATIONS`` to a
    #: real database remains a separate, manual, unchanged operator
    #: step (``run_order_migrations.py``) -- this field being
    #: constructible does not imply the underlying ``orders`` table
    #: already exists on whatever database file ``database_manager``
    #: points at.
    order_repository: OrderRepository

    #: Sprint 4 STEP 4 addition (additive only, "TradeRepository +
    #: Trade Migration"): a ``TradeRepository`` constructed over this
    #: exact graph's ``database_manager`` above (see
    #: :func:`_build_trade_repository`) -- the same shared instance as
    #: ``account_repository``/``position_repository``/
    #: ``order_repository``, never a second ``DatabaseManager``,
    #: mirroring the identity requirement established in Sprint 4
    #: STEP 1/STEP 2/STEP 3. Graph-visibility only, same additive
    #: pattern as ``account_repository``/``position_repository``/
    #: ``order_repository``: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. This STEP is persistence only --
    #: no ``ExecutionService``/``OrderLifecycleService``/
    #: ``PositionManager``/``PaperTradingEngine`` business logic exists
    #: yet to consume it. Applying
    #: ``Database.migrations_trades.TRADES_MIGRATIONS`` to a real
    #: database remains a separate, manual, unchanged operator step
    #: (``run_trade_migrations.py``) -- this field being constructible
    #: does not imply the underlying ``trades`` table already exists
    #: on whatever database file ``database_manager`` points at.
    trade_repository: TradeRepository

    #: Sprint 5 STEP 3 addition (additive only, "SnapshotRepository +
    #: Ranking Snapshot Migration"): a ``SnapshotRepository``
    #: constructed over this exact graph's ``database_manager`` above
    #: (see :func:`_build_snapshot_repository`) -- the same shared
    #: instance as ``account_repository``/``position_repository``/
    #: ``order_repository``/``trade_repository``, never a second
    #: ``DatabaseManager``, mirroring the identity requirement
    #: established in Sprint 4 STEP 1/STEP 2/STEP 3/STEP 4.
    #: Graph-visibility only, same additive pattern as
    #: ``trade_repository``: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. This STEP is persistence only for
    #: the ``ranking_snapshots`` table (version=10, LOCKED DECISION --
    #: see ``Database.migrations_snapshots`` for why this is not
    #: version=6) -- it does not run ``Business.ranking_engine.
    #: RankingEngine``, read ``WatchlistScanner``, or wire any consumer
    #: of ``RankingEngine.rank()``'s output into this repository.
    #: Applying ``Database.migrations_snapshots.SNAPSHOTS_MIGRATIONS``
    #: to a real database remains a separate, manual, unchanged
    #: operator step (``run_snapshot_migrations.py``) -- this field
    #: being constructible does not imply the underlying
    #: ``ranking_snapshots`` table already exists on whatever database
    #: file ``database_manager`` points at.
    snapshot_repository: SnapshotRepository

    #: Phase B addition (additive only, "Decision Copilot"): the new
    #: ``DecisionBriefService``, built over this graph's shared
    #: ``snapshot_repository``/``database_manager`` (see
    #: :func:`_build_decision_brief_service`) -- reuses the existing
    #: ``RankingSnapshot``/``RiskManagementService``, never a second
    #: strategy or risk engine. Read-mostly: its only write path is
    #: appending a ``DecisionBrief`` row via ``DecisionBriefRepository``,
    #: never a paper order, ``Trade``, or ``Position``. Not registered
    #: as a Tool; consumed only by ``main.py``'s ``brief`` command.
    #: Applying ``Database.migrations_decision_briefs`` to a real
    #: database remains a separate, manual, unchanged operator step
    #: (``run_decision_brief_migrations.py``).
    decision_brief_service: DecisionBriefService

    #: Phase C addition (additive only, "Personal Risk Ledger +
    #: Decision Journal"): a ``RiskLimitsRepository`` constructed over
    #: this graph's shared ``database_manager`` (see
    #: :func:`_build_risk_limits_repository`) -- the same shared
    #: instance every other repository in this graph uses, never a
    #: second ``DatabaseManager``. Graph-visibility only, same
    #: additive pattern as ``snapshot_repository``: not passed to
    #: ``agent``, ``runtime_analysis_pipeline``, or
    #: ``trading_decision_agent``, and not registered as a Tool.
    #: Applying ``Database.migrations_risk_ledger`` to a real database
    #: remains a separate, manual operator step
    #: (``run_risk_ledger_migrations.py``).
    risk_limits_repository: RiskLimitsRepository

    #: Phase C addition (additive only, "Personal Risk Ledger +
    #: Decision Journal"): the new ``JournalService``, built over this
    #: graph's shared ``risk_limits_repository``/``database_manager``
    #: (see :func:`_build_journal_service`) -- reuses the existing
    #: ``DecisionBrief``/``DecisionBriefRepository``, never a second
    #: strategy or risk engine; enforces personal limits via the one
    #: new ``RiskLedgerPolicy``. Read-mostly: its only write paths are
    #: appending a ``JournalEntry`` row and, later, filling in that
    #: same row's outcome columns -- never a paper order, ``Trade``,
    #: or ``Position``. Not registered as a Tool; consumed only by
    #: ``main.py``'s ``journal``/``risk-limits`` commands. Applying
    #: ``Database.migrations_risk_ledger`` to a real database remains
    #: a separate, manual operator step
    #: (``run_risk_ledger_migrations.py``).
    journal_service: JournalService

    #: Phase D addition (additive only, "Proactive IDX Scheduler
    #: Routine"): the new ``IDXDailyScheduler``, built over this
    #: graph's shared ``database_manager`` (three fresh Phase D
    #: repositories -- ``SchedulerStateRepository``/
    #: ``NotificationDedupRepository``/``AuditEventRepository``, over
    #: that same instance, never a second ``DatabaseManager``) plus
    #: this graph's already-built ``manual_scan_service``/
    #: ``daily_report_orchestrator``/``notification_manager`` (see
    #: :func:`_build_idx_daily_scheduler`) -- reuses the existing scan
    #: and daily-report pipelines, never a second one. Read-mostly
    #: beyond its own three Phase D tables: never touches
    #: ``PaperTradingEngine``/``OrderLifecycleService``/
    #: ``ExecutionService``. Not registered as a Tool; consumed only by
    #: ``main.py``'s ``scheduler idx-tick``/``scheduler simulate-day``
    #: commands. Applying ``Database.migrations_scheduler`` to a real
    #: database remains a separate, manual, unchanged operator step
    #: (``run_scheduler_migrations.py``).
    idx_daily_scheduler: IDXDailyScheduler

    #: Phase D addition (additive only): the new ``HealthAuditService``,
    #: a read-only aggregator over this same graph's Phase D
    #: repositories (see :func:`_build_health_audit_service`). Consumed
    #: only by ``main.py``'s ``scheduler status`` command. Writes
    #: nothing; never touches any non-Phase-D table.
    health_audit_service: HealthAuditService

    #: Sprint 6 STEP 1 addition (additive only, "PerformanceRepository"):
    #: a ``PerformanceRepository`` constructed over this exact graph's
    #: ``database_manager`` above (see
    #: :func:`_build_performance_repository`) -- the same shared
    #: instance as ``account_repository``/``position_repository``/
    #: ``order_repository``/``trade_repository``/``snapshot_repository``,
    #: never a second ``DatabaseManager``, mirroring the identity
    #: requirement established in Sprint 4 STEP 1/STEP 2/STEP 3/STEP 4
    #: and Sprint 5 STEP 3. Graph-visibility only, same additive
    #: pattern as ``snapshot_repository``: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. This STEP is READ-ONLY query
    #: access for performance analysis -- it does not filter, group,
    #: sort for business reasons, aggregate, or compute any statistic
    #: (win rate, expectancy, drawdown, etc.); that is reserved for a
    #: later Sprint 6 STEP that consumes this repository's output.
    performance_repository: PerformanceRepository

    #: Sprint 4 STEP 5 addition (additive only, "OrderLifecycleService
    #: -- Order state machine owner"): the project's first
    #: business-layer component, constructed over this exact graph's
    #: ``order_repository`` above (see
    #: :func:`_build_order_lifecycle_service`) -- the same shared
    #: ``order_repository`` instance, never a second ``OrderRepository``.
    #: This is the consumer ``order_repository``'s own docstring (and
    #: STEP 1-4's ``ApplicationGraph`` field docs) already flagged as
    #: not existing yet. Graph-visibility only, same additive pattern
    #: as every Sprint 4 Repository field: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. This STEP only owns Order status
    #: transitions (NEW -> VALIDATED -> PENDING or NEW -> REJECTED) --
    #: it performs no execution, creates no Trade, and touches no
    #: Position/Account. No ``ExecutionService``/``PositionManager``/
    #: ``AccountBalanceService``/``PaperTradingEngine`` exists yet to
    #: consume it; a later Sprint 4 STEP wires that consumer.
    order_lifecycle_service: OrderLifecycleService

    #: Sprint 4 STEP 6 addition (additive only, "ExecutionService --
    #: paper execution"): constructed over this exact graph's
    #: ``order_repository``/``trade_repository`` above (see
    #: :func:`_build_execution_service`) -- the same shared instances,
    #: never second Repository instances. Graph-visibility only, same
    #: additive pattern as every other Sprint 4 field: not passed to
    #: ``agent``, ``runtime_analysis_pipeline``, or
    #: ``trading_decision_agent``, and not registered as a Tool. This
    #: STEP only owns paper execution of an already-``PENDING`` Order
    #: into a ``Trade`` + ``FILLED`` status -- it does not touch
    #: ``Account``/``Position``/cash/equity/portfolio/P/L, and does not
    #: compute fee or tax (an explicit ``0.0``/``0.0`` placeholder is
    #: used until a future Fee/Tax Policy STEP). No
    #: ``AccountBalanceService``/``PositionManager``/
    #: ``PaperTradingEngine`` exists yet to consume it; a later Sprint
    #: 4 STEP wires that consumer.
    execution_service: ExecutionService

    #: Sprint 4 STEP 7 addition (additive only, "AccountBalanceService --
    #: cash balance"): constructed over this exact graph's
    #: ``account_repository`` above (see
    #: :func:`_build_account_balance_service`) -- the same shared
    #: instance, never a second ``AccountRepository``. Graph-visibility
    #: only, same additive pattern as every other Sprint 4 field: not
    #: passed to ``agent``, ``runtime_analysis_pipeline``, or
    #: ``trading_decision_agent``, and not registered as a Tool. This
    #: STEP only owns applying an already-created ``Trade``'s (Sprint 4
    #: STEP 6) cash impact onto its ``Account`` -- it reads/writes
    #: ``cash`` only, passes ``equity``/``buying_power`` through
    #: unchanged, and does not touch ``Position``/``Portfolio`` or
    #: compute P/L, fee, or tax. No ``PositionManager``/
    #: ``PaperTradingEngine`` exists yet to consume it; a later Sprint
    #: 4 STEP wires that consumer.
    account_balance_service: AccountBalanceService

    #: Sprint 4 STEP 8 addition (additive only, "PositionManager --
    #: position lifecycle"): constructed over this exact graph's
    #: ``position_repository`` above (see
    #: :func:`_build_position_manager`) -- the same shared instance
    #: (from Sprint 4 STEP 2), never a second ``PositionRepository``.
    #: Graph-visibility only, same additive pattern as every other
    #: Sprint 4 field: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. This STEP only owns applying an
    #: already-created ``Trade``'s (Sprint 4 STEP 6) effect onto its
    #: ``Position`` (BUY create/merge, SELL reduce/close) -- it does
    #: not touch ``Account``/``Equity``/``BuyingPower``/``Portfolio``,
    #: and does not compute realized or unrealized P/L. Activation 3.5
    #: STEP 2 wires ``paper_trading_engine`` below as this instance's
    #: first production consumer: after a successful ``Trade`` and
    #: after ``account_balance_service.apply_trade()``, the engine now
    #: also calls this same ``position_manager.apply_trade()`` on it --
    #: the same shared ``PositionManager`` instance, never a second one.
    position_manager: PositionManager

    #: Activation 3.2 addition (additive only, "pre-trade validation --
    #: duplicate request/idempotency"): constructed over this exact
    #: graph's ``database_manager`` (see
    #: :func:`_build_order_idempotency_repository`) -- the same shared
    #: instance as every other Repository field above, never a second
    #: ``DatabaseManager``. Graph-visibility only, same additive
    #: pattern as every other field here: not passed to ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``,
    #: and not registered as a Tool. The only consumer is
    #: ``paper_trading_engine`` below.
    order_idempotency_repository: OrderIdempotencyRepository

    #: Activation 7 Blocker #4 addition (additive only, "persist
    #: user_approval so it is auditable from the database"):
    #: constructed over this exact graph's ``database_manager`` (see
    #: :func:`_build_order_approval_repository`) -- the same shared
    #: instance as every other Repository field above, never a second
    #: ``DatabaseManager``. Graph-visibility only, same additive
    #: pattern as ``order_idempotency_repository`` above: not passed
    #: to ``agent``, ``runtime_analysis_pipeline``, or
    #: ``trading_decision_agent``, and not registered as a Tool. The
    #: only consumer is ``paper_trading_engine`` below, and it does
    #: not change that engine's approval gate, execution logic, or
    #: transaction boundary in any way.
    order_approval_repository: OrderApprovalRepository

    #: Sprint 4 STEP 9 addition, extended by Activation 3.2 ("12
    #: pre-trade validation gates"): constructed over this exact
    #: graph's ``order_lifecycle_service``/``execution_service``/
    #: ``account_repository``/``position_repository``/
    #: ``order_idempotency_repository`` above (see
    #: :func:`_build_paper_trading_engine`) -- the same shared
    #: instances, never second instances. Graph-visibility only, same
    #: additive pattern as every other Sprint 4 field: not passed to
    #: ``agent``, ``runtime_analysis_pipeline``, or
    #: ``trading_decision_agent``, and not registered as a Tool.
    #: Sprint 4 STEP 9 sequence unchanged (``OrderLifecycleService.
    #: create_order()`` then, if ``PENDING``, ``ExecutionService.
    #: execute_order()``); Activation 3.2 adds 12 read-only pre-trade
    #: gates in front of that sequence and one write
    #: (``OrderIdempotencyRepository.create()``) after it. Activation
    #: 3.5 STEP 1 adds one more step to that sequence: after a
    #: successful ``ExecutionService.execute_order()`` and before the
    #: idempotency-key write, this engine now calls this same graph's
    #: ``account_balance_service.apply_trade()`` on the resulting
    #: ``Trade`` -- the same shared ``AccountBalanceService`` instance,
    #: never a second one. Still computes no fee/tax/P&L itself (those
    #: values are read straight off the already-persisted ``Trade``,
    #: computed upstream by ``ExecutionService``/``ExecutionPolicy``).
    #: Activation 3.5 STEP 2 adds one further step to that sequence:
    #: immediately after ``account_balance_service.apply_trade()`` and
    #: still before the idempotency-key write, this engine now also
    #: calls this same graph's ``position_manager.apply_trade()`` on
    #: the resulting ``Trade`` -- the same shared ``PositionManager``
    #: instance, never a second one. This closes the Sprint 4 "Caller
    #: -> PaperTradingEngine -> OrderLifecycleService ->
    #: ExecutionService -> Trade -> AccountBalanceService -> Account
    #: cash / PositionManager -> Position" chain end-to-end.
    #: ``realized_pnl`` remains a pass-through placeholder --
    #: ``PositionManager`` itself does not compute it yet.
    paper_trading_engine: PaperTradingEngine

    #: ``manual_scan_service`` (Sprint 5 STEP 6 addition, additive only,
    #: "ManualScanService"): a pure orchestrator constructed over a
    #: freshly-built ``WatchlistScanner`` (wrapping this exact graph's
    #: ``watchlist_repository``/``market_analysis_agent`` -- see
    #: :func:`_build_manual_scan_service`), a freshly-built
    #: ``RankingEngine``/``RecommendationService``/``ReportService``
    #: (each takes no constructor dependency of its own, per their own
    #: LOCKED DECISIONs, so each is built fresh here -- nothing to
    #: share by identity), and this exact graph's
    #: ``snapshot_repository`` above -- the same shared instance, never
    #: a second ``SnapshotRepository``. Graph-visibility only, same
    #: additive pattern as every other Sprint 4/5 field: not passed to
    #: ``agent``, ``runtime_analysis_pipeline``, or
    #: ``trading_decision_agent``, and not registered as a Tool. This
    #: STEP only sequences the five already-completed Sprint 5 stages
    #: (``WatchlistScanner.scan()`` -> ``RankingEngine.rank()`` ->
    #: ``RecommendationService.build_recommendations()`` ->
    #: ``ReportService.build_report()`` -> one
    #: ``SnapshotRepository.create()`` call per ``Recommendation``) --
    #: it adds no new sorting, ranking, filtering, or scoring logic of
    #: its own (LOCKED DECISION, Sprint 5 STEP 6 Pre-Implementation
    #: Review). No CLI, scheduler, export, Telegram, or Discord
    #: integration exists yet to call it; a future STEP wires that
    #: caller.
    manual_scan_service: ManualScanService

    #: ``notification_builder`` (Sprint 7 STEP 7 addition, additive
    #: only, "Runtime Wiring Notification System"): the Sprint 7
    #: STEP 2 ``NotificationBuilder`` -- see
    #: :func:`_build_notification_builder`. Takes no dependency
    #: (LOCKED, unchanged).
    notification_builder: NotificationBuilder

    #: ``telegram_notification_channel`` (Sprint 7 STEP 7 addition,
    #: additive only): the Sprint 7 STEP 4 ``TelegramNotificationChannel``
    #: -- see :func:`_build_telegram_notification_channel`. Wraps this
    #: exact graph's ``NotificationService`` instance (the same one
    #: :func:`_build_notification_service` registers into
    #: ``service_registry``, never a second one) plus
    #: :func:`_notification_service_context_factory`.
    telegram_notification_channel: TelegramNotificationChannel

    #: ``notification_dispatcher`` (Sprint 7 STEP 7 addition, additive
    #: only): the Sprint 7 STEP 3 ``NotificationDispatcher`` -- see
    #: :func:`_build_notification_dispatcher`. Holds exactly one
    #: channel, this exact graph's ``telegram_notification_channel``
    #: (LOCKED DECISION 5 -- no Discord/email channel added).
    notification_dispatcher: NotificationDispatcher

    #: ``notification_manager`` (Sprint 7 STEP 7 addition, additive
    #: only): the Sprint 7 STEP 5 ``NotificationManager`` -- see
    #: :func:`_build_notification_manager`. Wraps this exact graph's
    #: ``notification_dispatcher``. This STEP is wiring-only: nothing
    #: in ``build_application`` calls ``notification_manager.notify()``
    #: -- a future STEP wires the caller once a real runtime event
    #: exists.
    notification_manager: NotificationManager

    #: ``watchlist_repository`` (Sprint 5 STEP 1 addition, additive
    #: only): a ``WatchlistRepository`` constructed over this same
    #: shared ``database_manager`` -- see :func:`_build_watchlist_repository`.
    #: Mirrors ``account_repository``/``position_repository``/etc.
    #: exactly: never a second ``DatabaseManager``, no migration run
    #: here (``python run_watchlist_migrations.py`` remains the
    #: operator's explicit step). Not yet passed into ``agent`` or any
    #: other collaborator -- consumed only by ``WatchlistScanner``
    #: (built outside this module), which receives this exact instance.
    watchlist_repository: WatchlistRepository

    #: ``market_analysis_agent`` (Sprint 5 STEP 1 addition, additive
    #: only, LOCKED DECISION -- Revisi): the first production instance
    #: of ``Orchestration.market_analysis_agent.MarketAnalysisAgent``
    #: (Phase 11 Sprint 119's three-Skill coordinator -- not to be
    #: confused with ``Agents.market_analysis_agent.MarketAnalysisAgent``,
    #: an unrelated abstract base class). See
    #: :func:`_build_market_analysis_agent`: no prior instance of this
    #: class existed anywhere in production, so this is a first
    #: construction, not a reuse. Its three Skill collaborators
    #: (``MarketAnalysisSkill``, ``PortfolioAnalysisSkill``,
    #: ``WatchlistAnalysisSkill``) are each freshly constructed with no
    #: arguments, deliberately independent of the differently-wired
    #: ``MarketAnalysisSkill`` instance ``_build_trading_decision_agent()``
    #: builds for ``TradingDecisionAgent`` -- that instance and its
    #: ``_resolve_tool``/``ToolResolver`` wiring are untouched, not
    #: read, and not shared; ``TradingDecisionAgent`` remains a black
    #: box, unmodified. Consequence (documented, not remedied here, per
    #: LOCKED DECISION rule 6/10): this fresh ``MarketAnalysisSkill``
    #: has no ``_resolve_tool`` injected, so its per-symbol
    #: ``TextAnalysisSkill`` calls raise a missing-resolver
    #: ``SkillError`` -- caught internally by
    #: ``MarketAnalysisSkill.execute()``'s own per-symbol try/except,
    #: so this never raises out of ``MarketAnalysisAgent.execute()``,
    #: but every ``"market"`` result will carry ``analysis: None`` with
    #: a failure message per symbol until a future STEP wires a
    #: resolver. Not passed into ``agent``, ``runtime_analysis_pipeline``,
    #: or ``trading_decision_agent``, and not registered as a Tool --
    #: consumed only by ``WatchlistScanner`` (built outside this
    #: module), which receives this exact instance.
    market_analysis_agent: MarketAnalysisAgent

    #: ``market_price_tool`` (Activation 4 Session 1 addition, additive
    #: only): a single shared ``Orchestration.market_price_tool.
    #: MarketPriceTool`` instance, graph-visibility only. Construction
    #: is trivial and stateless (no-arg, see that class's own
    #: docstring -- "no ``__init__`` of its own, no instance state, no
    #: cache"), so this is pure wiring, not new business logic: the
    #: exact same ``MarketPriceTool`` class already registered under
    #: ``"market_price"`` in :func:`_build_market_tool_resolver`'s
    #: local ``Orchestration.tool_registry.ToolRegistry`` -- this field
    #: does not replace or duplicate that registration, it only gives
    #: CLI callers (which have no ``ToolResolver``/``ToolContext``
    #: chain of their own) a single shared instance to call
    #: ``.execute(ToolContext(...))`` on directly for a real, current
    #: price lookup. Not passed into ``agent``, ``runtime_analysis_pipeline``,
    #: or ``trading_decision_agent``.
    market_price_tool: MarketPriceTool

    #: ``unrealized_pnl_engine`` (Activation 4 Session 2 addition,
    #: additive only): a single shared
    #: ``Business.unrealized_pnl_engine.UnrealizedPnLEngine`` instance,
    #: graph-visibility only. Per audit STEP 1 section 5, this
    #: component already existed in ``Business/`` (Activation 3.7
    #: STEP 4, LOCKED) but was never a field on this graph -- its
    #: constructor takes exactly one dependency, this graph's own
    #: ``market_price_tool`` (built immediately above), so wiring it
    #: is pure composition, not new business logic: the formula
    #: ``unrealized_pnl = (market_price - average_price) * quantity``
    #: is unchanged and still lives solely inside that engine. Gives
    #: CLI callers (``portfolio``) a single shared instance to call
    #: ``.calculate(position)`` on directly, mirroring how
    #: ``market_price_tool`` itself is exposed for ``paper buy``/
    #: ``paper sell``. Not passed into ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``.
    unrealized_pnl_engine: UnrealizedPnLEngine

    #: Activation 5.5 addition (additive only, "PerformanceSummaryService
    #: production wiring"): a PortfolioSnapshotRepository constructed
    #: over this graph's database_manager (see
    #: _build_portfolio_snapshot_repository) -- the same shared instance
    #: as every other Repository field above. Graph-visibility only, not
    #: passed into agent/runtime_analysis_pipeline/trading_decision_agent,
    #: not registered as a Tool.
    portfolio_snapshot_repository: PortfolioSnapshotRepository

    #: Activation 5.5 addition (additive only): the existing Activation
    #: 5.2/5.4 PortfolioSnapshotService (take_snapshot()/
    #: get_equity_curve()), now reachable via this graph. Built over this
    #: graph's account_repository/position_repository/unrealized_pnl_engine/
    #: portfolio_snapshot_repository plus a locally-built
    #: MaximumDrawdownEngine() -- all pre-existing, LOCKED components, no
    #: new formula. Unchanged class, first production wiring.
    portfolio_snapshot_service: PortfolioSnapshotService

    #: Activation 7 FIX addition (additive only, blocker 3): the
    #: existing Activation 3.9 ReconciliationEngine (read-only
    #: Order/Trade/Cash/Position consistency checker -- 4 invariants,
    #: unchanged formula), now reachable via this graph for the first
    #: time. Built over this graph's order_repository/
    #: trade_repository/account_repository/position_repository --
    #: all pre-existing, LOCKED components. Never opens a transaction,
    #: never writes; the only production caller is the ``paper
    #: buy``/``paper sell`` CLI commands (``main.py``), immediately
    #: after a trade commits, so an INCONSISTENT result is visible to
    #: the operator at the moment it matters most.
    reconciliation_engine: ReconciliationEngine

    #: ACTIVATION 7 -- EXECUTION RATE WIRING ONLY addition (additive
    #: only): the existing, LOCKED Business.execution_rate_engine.
    #: ExecutionRateEngine (read-only order-level ``execution_rate =
    #: filled_orders / resolved_orders`` measurement, unchanged
    #: formula, unchanged tests), now reachable via this graph for the
    #: first time. Built over this graph's order_repository -- the
    #: same shared instance as every other Repository field above,
    #: never a second instance. Graph-visibility only, not passed into
    #: agent/runtime_analysis_pipeline/trading_decision_agent, not
    #: registered as a Tool, no CLI wiring.
    execution_rate_engine: ExecutionRateEngine

    #: ACTIVATION 7 -- FAILURE RATE WIRING ONLY addition (additive
    #: only): the existing, LOCKED Business.failure_rate_engine.
    #: FailureRateEngine (read-only scan/order ``failure_rate``
    #: measurement, unchanged formula, unchanged tests), now reachable
    #: via this graph for the first time. Built over this graph's
    #: snapshot_repository/order_repository -- the same shared
    #: instances as every other Repository field above, never second
    #: instances. Graph-visibility only, not passed into
    #: agent/runtime_analysis_pipeline/trading_decision_agent, not
    #: registered as a Tool, no CLI wiring.
    failure_rate_engine: FailureRateEngine

    #: Activation 5.5 addition (additive only): the existing Sprint 6
    #: STEP 7 PerformanceSummaryService (LOCKED constructor, LOCKED call
    #: order -- see its own module docstring), now reachable via this
    #: graph. Built over six locally-constructed, no-arg Sprint 6 engine
    #: instances -- unchanged class, unchanged formulas, first production
    #: wiring.
    performance_summary_service: PerformanceSummaryService

    #: Activation 5.5 addition (additive only): the new, thin
    #: PerformanceSummaryProductionService -- supplies
    #: performance_summary_service.build() with real, account-scoped
    #: trades/positions/equity_curve read via trade_repository/
    #: position_repository/portfolio_snapshot_service.get_equity_curve().
    #: Read-only; never persists. The one and only production entry
    #: point for a real PerformanceSummary.
    performance_summary_production_service: PerformanceSummaryProductionService

    #: Activation 5.6 addition (additive only): the new, pure,
    #: no-repository ``TradeHoldingPeriodEngine`` -- reconstructs
    #: position-episode holding periods purely from the immutable
    #: ``Trade`` ledger. No new formula supersedes anything
    #: ``PositionManager`` already owns (``quantity``/``average_price``/
    #: ``realized_pnl``/``status`` are never read by this engine).
    trade_holding_period_engine: TradeHoldingPeriodEngine

    #: Activation 5.6 addition (additive only): the new
    #: ``TradeAttributionEngine`` -- assembles the five LOCKED
    #: attribution dimensions (strategy/market/signal/holding_period/
    #: risk_category) per trade from already-resolved inputs. Built
    #: over this graph's existing, LOCKED ``decision_policy`` --
    #: never a second/new risk-mapping component.
    trade_attribution_engine: TradeAttributionEngine

    #: Activation 5.6 addition (additive only): the new, thin
    #: ``TradeAttributionService`` -- supplies
    #: ``trade_attribution_engine``/``trade_holding_period_engine``
    #: with real, account-scoped trades/orders/account/snapshots read
    #: via ``trade_repository``/``order_repository``/
    #: ``account_repository``/``snapshot_repository``. Read-only;
    #: never persists. The one and only production entry point for
    #: real Trade attribution.
    trade_attribution_service: TradeAttributionService

    #: Activation 7 addition (additive only, performance-per-strategy):
    #: the new, pure, single-collaborator ``PositionEpisodeReplayEngine``
    #: -- replays this graph's existing ``trade_holding_period_engine``
    #: to reconstruct closed position episodes (grouping + opening
    #: trade) purely from the immutable ``Trade`` ledger. Never reads
    #: ``Position``, never recomputes the holding-period formula.
    position_episode_replay_engine: PositionEpisodeReplayEngine

    #: Activation 7 addition (additive only): the new, pure,
    #: no-repository ``StrategyPerformanceEngine`` -- aggregates
    #: already-resolved per-episode (strategy, realized_pnl) outcomes
    #: into performance statistics per strategy. Mirrors
    #: ``position_performance_engine``'s own field set, just grouped
    #: by strategy.
    strategy_performance_engine: StrategyPerformanceEngine

    #: Activation 7 addition (additive only): the new, thin
    #: ``StrategyPerformanceService`` -- supplies
    #: ``position_episode_replay_engine``/``strategy_performance_engine``
    #: with real, account-scoped trades/orders/positions read via
    #: ``trade_repository``/``order_repository``/``position_repository``.
    #: Read-only; never persists. The one and only production entry
    #: point for real performance-per-strategy. Uses
    #: ``Position.realized_pnl`` as the already-existing episode P/L --
    #: never recomputed.
    strategy_performance_service: StrategyPerformanceService

    #: ACTIVATION 7 addition (this session, additive only,
    #: performance-per-market-regime -- resolves the roadmap conflict
    #: recorded in ``Docs/ACTIVATION 7/
    #: AIOS_Activation7_Final_Closeout_Report.md``, "Market-condition
    #: evidence -- OPEN GAP"): the new, pure, no-dependency
    #: ``MarketRegimeEngine`` -- deterministically classifies a window
    #: of real closes as trending/ranging/volatile, or
    #: insufficient_data. No ML, no I/O, no persistence.
    market_regime_engine: MarketRegimeEngine

    #: ACTIVATION 7 addition (this session, additive only): the new,
    #: thin ``MarketRegimeService`` -- supplies ``market_regime_engine``
    #: with real OHLCV history read via a dedicated
    #: ``StockDataRepository`` (the same repository/``yfinance`` path
    #: the instruction named). Never persists a regime -- every call
    #: deterministically recomputes from real historical bars, which
    #: is what makes regime attribution restart-safe without a new
    #: database column/table.
    market_regime_service: MarketRegimeService

    #: ACTIVATION 7 addition (this session, additive only): the new,
    #: pure, no-repository ``MarketRegimePerformanceEngine`` --
    #: aggregates already-resolved per-episode (regime, realized_pnl)
    #: outcomes into performance statistics per regime. Mirrors
    #: ``strategy_performance_engine``'s own field set, just grouped
    #: by market regime.
    market_regime_performance_engine: MarketRegimePerformanceEngine

    #: ACTIVATION 7 addition (this session, additive only): the new,
    #: thin ``MarketRegimeAttributionService`` -- supplies
    #: ``position_episode_replay_engine`` (reused, not duplicated)/
    #: ``market_regime_service``/``market_regime_performance_engine``
    #: with real, account-scoped trades/positions, and separately
    #: reports real, currently-observed market-condition variety
    #: across the real watchlist. Read-only; never persists. The one
    #: and only production entry point for real
    #: performance-per-market-regime and market-condition variety.
    market_regime_attribution_service: MarketRegimeAttributionService

    #: Activation 6.4 addition (additive only, "IMPLEMENT"): the new,
    #: thin ``DailyReportOrchestrator`` -- sequences the already-real
    #: ``manual_scan_service`` -> ``performance_summary_production_service``
    #: -> ``notification_builder`` -> ``notification_manager`` chain
    #: into one stable "daily report" call (see
    #: :func:`_build_daily_report_orchestrator`). Reuses this exact
    #: graph's already-built four collaborators -- never second,
    #: independently-constructed instances. No CLI-independent
    #: scheduler or background worker is introduced anywhere in this
    #: graph; the only production caller is the ``report daily`` CLI
    #: command (``main.py``), which calls
    #: ``daily_report_orchestrator.run_daily_report(...)`` directly
    #: and lets any exception -- including a notification failure --
    #: propagate unchanged.
    daily_report_orchestrator: DailyReportOrchestrator

    #: Activation 12.8 addition (additive only, "PAPER_EXECUTION Tool"):
    #: the ONE production ``Orchestration.tool_resolver.ToolResolver``
    #: exposing ``Orchestration.paper_execution_tool.PaperExecutionTool``
    #: under the stable name ``"paper_execution"`` -- see
    #: :func:`_build_paper_execution_tool_resolver`. Built by that
    #: function's own, dedicated ``Orchestration.tool_registry.
    #: ToolRegistry`` (never the same registry instance
    #: :func:`_build_market_tool_resolver` builds for the three
    #: ``Market*Tool`` instances -- two separate, independently-owned
    #: registries, exactly as ``Orchestration.tool_registry.
    #: ToolRegistry``'s own "each instance owns its own independent
    #: dictionary" docstring already permits), constructed AFTER this
    #: graph's ``paper_trading_engine`` above (the one production
    #: instance ``PaperExecutionTool`` wraps and delegates to,
    #: unmodified) and wrapped in
    #: ``Orchestration.permissioned_tool.PermissionedTool`` over the
    #: exact same shared ``PermissionContext`` instance
    #: ``_build_market_tool_resolver``/``_build_service_skills``
    #: already receive (Activation 12.6's single-owner rule) -- never a
    #: second, independently-constructed ``PermissionContext``.
    #: ``PaperExecutionTool`` declares ``ToolPermission.
    #: PAPER_EXECUTION`` (undeclared/READ_ONLY tools -- the three
    #: ``Market*Tool`` instances and the 12 ``ServiceSkill`` instances
    #: -- are unaffected: this field adds a new, separately-resolved
    #: Tool, it does not touch either existing registry/resolver). A
    #: denied ``PermissionContext`` (the LOCKED, fail-closed default
    #: every graph is built with today) means resolving this Tool and
    #: calling ``.execute(context)`` on the result raises
    #: ``Orchestration.tool_permission_enforcer.ToolPermissionDenied``
    #: before ``PaperTradingEngine.submit_order()`` -- and therefore
    #: every one of its 19 pre-trade gates -- is ever reached. Graph-
    #: visibility only: not passed into ``agent``,
    #: ``runtime_analysis_pipeline``, or ``trading_decision_agent``.
    #: The existing CLI ``paper buy``/``paper sell`` path
    #: (``main.py``, unmodified by this Activation) keeps calling
    #: ``paper_trading_engine.submit_order()`` directly and is
    #: entirely unaffected by this field.
    paper_execution_tool_resolver: ToolResolver

    #: Phase F, Task 9 addition (additive only, "Copilot Tool
    #: Registration"): the ONE production ``Orchestration.tool_resolver.
    #: ToolResolver`` exposing ``Orchestration.copilot_tool.CopilotTool``
    #: under the stable name ``"copilot"`` -- see
    #: :func:`_build_copilot_tool_resolver`. Built by that function's
    #: own, dedicated ``Orchestration.tool_registry.ToolRegistry``
    #: (never the same registry instance
    #: :func:`_build_market_tool_resolver`/
    #: :func:`_build_paper_execution_tool_resolver` build for their own
    #: tools -- three separate, independently-owned registries, exactly
    #: as ``Orchestration.tool_registry.ToolRegistry``'s own "each
    #: instance owns its own independent dictionary" docstring already
    #: permits), wrapped in ``Orchestration.permissioned_tool.
    #: PermissionedTool`` over the exact same shared
    #: ``PermissionContext`` instance every other tool resolver in this
    #: graph already receives (Activation 12.6's single-owner rule) --
    #: never a second, independently-constructed ``PermissionContext``.
    #: ``CopilotTool`` declares ``ToolPermission.READ_ONLY`` (see that
    #: class's own docstring) -- resolving ``"copilot"`` and calling
    #: ``.execute(context)`` on the result is authorized unconditionally,
    #: with or without any capability grant on ``permission_context``;
    #: this field never grants PAPER_EXECUTION, LIVE_EXECUTION, or
    #: DESTRUCTIVE_ADMIN to anything. Graph-visibility only: not passed
    #: into ``agent``, ``runtime_analysis_pipeline``,
    #: ``trading_decision_agent``, any planner/agent loop, or any
    #: Telegram module -- none of those exist for the copilot yet.
    copilot_tool_resolver: ToolResolver

    #: Activation 12 (Tool and Capability Registry -- discovery/catalog
    #: only). ``Orchestration.tool_manager.ToolManager`` wrapping the
    #: EXACT SAME ``Orchestration.tool_registry.ToolRegistry`` /
    #: ``Orchestration.tool_resolver.ToolResolver`` pair
    #: :func:`_build_market_tool_resolver` already builds and returns
    #: as ``market_tool_resolver`` above -- never a second,
    #: independently-constructed registry. ``ToolManager`` is a pure
    #: delegation facade (``register``/``resolve``/``has``/``list``/
    #: ``unregister``, each a one-line passthrough -- see that
    #: module's own docstring); wiring it in here adds exactly one new
    #: capability this graph did not previously expose anywhere:
    #: read-only enumeration of the registered tool names
    #: (``market_tool_manager.list()``) for a capability
    #: consumer/agent that wants to know what tools exist, without
    #: resolving or calling any of them. Graph-visibility only, like
    #: ``paper_execution_tool_resolver`` above: not passed into
    #: ``agent``, ``market_analysis_agent``, or ``trading_decision_agent``
    #: -- those already hold ``market_tool_resolver`` directly and are
    #: entirely unaffected by this field's addition. No permission
    #: model, planner, executor, or scheduler wiring is touched by
    #: this field.
    market_tool_manager: ToolManager
    #: ``scheduler`` (Activation 12 Scheduler, atomic step 1 addition,
    #: additive only): the single production
    #: ``Orchestration.autonomous_scheduler.AutonomousScheduler``
    #: instance for this graph, constructed with an empty queue (see
    #: the construction site just above this class's own
    #: ``return ApplicationGraph(...)`` call). Nothing on this graph
    #: schedules a job at construction time -- ``scheduler`` starts
    #: with an empty FIFO queue and unpaused, exactly like
    #: ``AutonomousScheduler()`` always does. Nothing in this
    #: construction function -- and no other production call path --
    #: ever calls ``scheduler.schedule()`` or ``scheduler.tick()``;
    #: that remains exclusively ``main.py``'s manual
    #: ``python main.py scheduler tick`` command's own concern (built
    #: fresh, at CLI-invocation time, from this same singleton
    #: instance -- never a second, independently constructed
    #: ``AutonomousScheduler``). Does not touch ``autonomous_agent``,
    #: ``goal_planner``, ``runtime_analysis_pipeline``, or any
    #: Planner/Memory field on this graph in any way.
    scheduler: AutonomousScheduler

    #: Phase E Task 6 addition (additive only, wiring-only): the Task 1
    #: ``Repository.persistence.telegram_command_audit_repository.
    #: TelegramCommandAuditRepository`` -- append-only audit log for
    #: every inbound Telegram command. Built over this same shared
    #: ``database_manager`` instance (see
    #: :func:`_build_telegram_command_audit_repository`), never a
    #: second ``DatabaseManager``. Graph-visibility only beyond feeding
    #: ``telegram_inbound_control_plane`` below -- unchanged class,
    #: unmodified from Task 1.
    telegram_command_audit_repository: TelegramCommandAuditRepository

    #: Phase E Task 6 addition (additive only, wiring-only): the Task 1
    #: ``Repository.persistence.telegram_inbound_state_repository.
    #: TelegramInboundStateRepository`` -- durable long-poll
    #: ``last_update_id``. Built over this same shared
    #: ``database_manager`` instance (see
    #: :func:`_build_telegram_inbound_state_repository`), never a
    #: second ``DatabaseManager``. Unchanged class, unmodified from
    #: Task 1.
    telegram_inbound_state_repository: TelegramInboundStateRepository

    #: Phase E Task 6 addition (additive only, wiring-only): the Task 2
    #: ``Business.telegram_allowlist_policy.TelegramAllowlistPolicy`` --
    #: pure, fail-closed authorization decision for one candidate
    #: ``chat_id``. Built via that module's own
    #: ``load_telegram_allowlist_policy()`` factory (see
    #: :func:`_build_telegram_allowlist_policy`) -- unchanged class,
    #: unchanged environment resolution order, unmodified from Task 2.
    telegram_allowlist_policy: TelegramAllowlistPolicy

    #: Phase E Task 6 addition (additive only, wiring-only): the Task 4
    #: ``Orchestration.telegram_command_executor.TelegramCommandExecutor``
    #: -- dispatches one already-parsed command to this graph's
    #: existing ``manual_scan_service``/``decision_brief_service``/
    #: ``journal_service``/``performance_summary_production_service``
    #: (see :func:`_build_telegram_command_executor`), never a new or
    #: second instance of any of the four. Unchanged class, unmodified
    #: from Task 4. Holds no broker/execution/order dependency -- none
    #: is imported by that module.
    telegram_command_executor: TelegramCommandExecutor

    #: Phase E Task 6 addition (additive only, wiring-only): the Task 5
    #: ``Orchestration.telegram_inbound_control_plane.
    #: TelegramInboundControlPlane`` -- owns Telegram inbound polling,
    #: allowlist enforcement, audit logging, and the durable offset.
    #: Built over the four fields immediately above plus this graph's
    #: existing ``notification_service`` (the exact same singleton
    #: already registered into ``service_registry`` -- never a second
    #: instance) for replies (see
    #: :func:`_build_telegram_inbound_control_plane`). Unchanged class,
    #: unmodified from Task 5. Nothing in ``build_application`` calls
    #: ``.poll_once()`` on it -- construction only; ``main.py``'s
    #: ``telegram poll``/``telegram status`` commands are the first
    #: real callers.
    telegram_inbound_control_plane: TelegramInboundControlPlane

    #: Phase G Task 5 addition (additive only, wiring-only): the
    #: already-complete, LOCKED ``Services.paper_review_service.
    #: PaperReviewService`` (Phase G Task 4) -- read-only, traces
    #: decision -> brief -> approval -> order -> trade ->
    #: valuation-freshness for one account. Built over fresh
    #: ``JournalRepository``/``DecisionBriefRepository``/
    #: ``BriefApprovalRepository`` instances constructed over this
    #: graph's own shared ``database_manager`` (mirrors
    #: ``_build_journal_service``'s own "a repository over the shared
    #: database_manager holds no independent state" reasoning -- never
    #: a second ``DatabaseManager``), plus this graph's existing
    #: ``account_repository``/``order_repository``/``trade_repository``/
    #: ``strategy_performance_service``/
    #: ``market_regime_attribution_service``/
    #: ``portfolio_snapshot_repository`` -- every one of them the same
    #: shared instance already built above, never a second copy. This
    #: service itself is completely unmodified from Phase G Task 4;
    #: this field only gives it a real, production entry point (``python
    #: main.py report paper-review``) where none existed before.
    paper_review_service: PaperReviewService

    #: Phase H Task 1 addition (additive only, "Observation Window +
    #: Sustained-Use Review Record"): the new
    #: ``Services.observation_window_service.ObservationWindowService``,
    #: built over a fresh ``ObservationWindowRepository`` constructed
    #: over this graph's own shared ``database_manager`` (see
    #: :func:`_build_observation_window_service`) -- never a second
    #: ``DatabaseManager``. Holds no reference to
    #: ``PaperTradingEngine``/``OrderLifecycleService``/
    #: ``ExecutionService``/any risk-policy component and calls none
    #: of them: opening, reading, or closing an observation window
    #: never creates a paper order, a ``Trade``, a ``Position``, or
    #: modifies any risk limit. Not registered as a Tool; consumed
    #: only by ``main.py``'s ``observation-window open/show/close``
    #: commands. Applying ``Database.migrations_observation_window``
    #: to a real database remains a separate, manual operator step
    #: (``run_observation_window_migrations.py``). Does NOT unlock
    #: live execution and makes no automatic period selection -- the
    #: operator must select the window explicitly.
    observation_window_service: ObservationWindowService

    #: Phase H Task 3 addition (additive only, "Sustained-Use Review
    #: Report"): the new
    #: ``Services.sustained_use_review_service.SustainedUseReviewService``
    #: (Phase H Task 2, LOCKED, completely unmodified) getting its
    #: first real production entry point (see
    #: :func:`_build_sustained_use_review_service`), plus the new
    #: ``Services.sustained_use_report_service.SustainedUseReportService``
    #: that turns its ``SustainedUseReviewResult`` into a durable,
    #: human-readable text report. Neither service holds a reference to
    #: ``PaperTradingEngine``/``OrderLifecycleService``/
    #: ``ExecutionService``/any risk-policy component and neither calls
    #: any write method on any collaborator: consumed only by
    #: ``main.py``'s ``report sustained-use`` command. Reuses this
    #: graph's existing shared ``paper_review_service``/
    #: ``reconciliation_engine``/``portfolio_snapshot_repository``
    #: instances (never a second copy); every other repository
    #: collaborator is a fresh, stateless instance built over this
    #: graph's own shared ``database_manager`` (never a second
    #: ``DatabaseManager``), mirroring
    #: ``_build_idx_daily_scheduler``/``_build_health_audit_service``'s
    #: own "a repository over the shared database_manager holds no
    #: independent state" reasoning. Does not create, close, or modify
    #: any ``ObservationWindow``, and makes no CONTINUE/SIMPLIFY/
    #: AUTHORIZE-FUTURE-BROKER-INVESTIGATION decision -- that remains a
    #: separate, future, human decision outside this task's scope.
    sustained_use_review_service: SustainedUseReviewService
    sustained_use_report_service: SustainedUseReportService

    #: Phase H Task 4 addition (additive only, "Operator Feedback +
    #: Final Review Record"): the new
    #: ``Services.sustained_use_final_review_service.
    #: SustainedUseFinalReviewService`` over two brand-new tables
    #: (``operator_feedback``/``final_review_records``) plus this
    #: graph's already-built, LOCKED ``sustained_use_review_service``
    #: (Phase H Task 2, unmodified) and a fresh
    #: ``ObservationWindowRepository`` over the same shared
    #: ``database_manager`` (see :func:`_build_sustained_use_final_review_service`).
    #: Holds no reference to any order/trade/position/risk-limit/
    #: account repository and never calls an LLM/provider -- it can
    #: never infer, score, or otherwise choose CONTINUE/SIMPLIFY/
    #: AUTHORIZE_FUTURE_INVESTIGATION on its own; that value only ever
    #: reaches ``final_review_records.human_decision`` via an explicit
    #: caller-supplied argument to
    #: ``SustainedUseFinalReviewService.record_decision``. Consumed by
    #: ``main.py``'s ``report sustained-use-final`` (read-only) and
    #: ``sustained-use-final feedback``/``sustained-use-final decide``
    #: (the only two write entry points) commands.
    sustained_use_final_review_service: SustainedUseFinalReviewService


def _build_provider(provider_name: str, provider_kind: str) -> BaseProvider:
    """Construct (never connect) the selected provider and register it.

    Stage L1 addition: ``provider_kind`` selects *which* ``BaseProvider``
    subclass to construct (via :data:`_PROVIDER_CLASSES`); ``provider_name``
    keeps its original, unchanged meaning as purely the ``ProviderManager``
    registry key. This is why Stage 9.0's LOCKED test suite -- which calls
    ``build_application(provider_name="gemini-stage9-0-test", ...)`` etc.,
    always expecting ``GeminiProvider`` -- still passes unmodified: those
    calls never pass ``provider_kind``, so it resolves to the default
    (``"gemini"``), regardless of the custom registry key string.

    The constructed provider only reads config values here -- it never
    opens a network connection or imports its underlying SDK/HTTP client
    (deferred to ``connect()``/``generate()``). Required env vars for the
    selected kind may be entirely absent from the environment at this
    point; the resulting provider is simply not usable for a real
    ``generate()`` call until they are -- that gap belongs to Level 2
    (integration smoke), not to this hermetic construction step.

    Guarded by ``exists()`` so calling :func:`build_application` more
    than once in the same process does not raise on re-registration.

    Raises:
        ConfigurationError: If ``provider_kind`` is not a recognized key
            in :data:`_PROVIDER_CLASSES`.
    """
    if not provider_manager.exists(provider_name):
        provider_class = _PROVIDER_CLASSES.get(provider_kind)
        if provider_class is None:
            raise ConfigurationError(
                f"Unknown provider_kind '{provider_kind}'. "
                f"Supported: {sorted(_PROVIDER_CLASSES)}",
                details={"provider_kind": provider_kind, "supported": sorted(_PROVIDER_CLASSES)},
            )
        provider_manager.register(provider_name, provider_class())
    return provider_manager.get(provider_name)


def _register_all_provider_kinds() -> None:
    """Register every known provider kind under its own canonical name
    (Stage L6 addition, additive-only, "Multi-provider Registry").

    Prior to this stage, ``build_application`` only ever constructed and
    registered the one ``provider_kind`` resolved from ``ACTIVE_PROVIDER``
    (or an explicit override) -- ``ProviderManager`` therefore only ever
    had one entry, and ``ProviderSelector``/``Planner.select_by_requirement()``
    (Stages L3/L4) never had more than one real candidate to choose from.

    This closes that gap by registering *every* class in
    :data:`_PROVIDER_CLASSES` under its own key (``"gemini"``,
    ``"ollama"``, ...) -- independent of, and in addition to, whatever
    ``_build_provider`` already registered above under the caller's
    resolved/custom ``provider_name``. ``ACTIVE_PROVIDER`` no longer
    determines *which providers get registered* -- it now determines
    only the *default* provider (``ApplicationGraph.provider_name`` and
    ``Planner``'s ``default_provider_name``, see :func:`build_application`).
    This is a deliberate, explicit re-scoping of ``ACTIVE_PROVIDER``'s
    meaning, not a silent one.

    Uses only ``ProviderManager``'s existing, unchanged public API
    (``exists()``/``register()``, no ``overwrite=True``) -- the same
    idempotency guard ``_build_provider`` already uses, so calling this
    (and therefore ``build_application``) more than once in the same
    process registers nothing twice and raises nothing.

    No provider-name or ``isinstance`` branching is introduced: this
    loop dispatches purely through the existing ``_PROVIDER_CLASSES``
    dict, exactly the same polymorphic construction pattern
    ``_build_provider`` already used (Stage L1, unchanged).

    Note (process-lifetime singleton): ``provider_manager`` is a
    process-wide singleton (unchanged design, see
    ``Providers.provider_manager.ProviderManager``). Once any process
    calls ``build_application()`` a first time, ``"gemini"`` and
    ``"ollama"`` remain registered in that process for its remaining
    lifetime -- this function's ``exists()`` guard makes subsequent
    calls no-ops for those two keys, it does not and cannot "unregister"
    them. Callers/tests that compare registry contents before/after a
    ``build_application()`` call must account for this (e.g. by
    asserting presence/idempotency rather than a before/after set
    difference) -- see Stage L6's proof suite and the revised Stage L5
    scenario for the corrected pattern.
    """
    for kind, provider_class in _PROVIDER_CLASSES.items():
        if not provider_manager.exists(kind):
            provider_manager.register(kind, provider_class())


def _build_database_manager() -> DatabaseManager:
    """Construct (never connect) the ``DatabaseManager`` for this graph.

    ``DatabaseConfig.from_env()`` never raises for missing env vars (every
    field has a documented default), and ``SQLiteDatabase.__init__`` opens
    no connection and touches no filesystem path -- only its own
    ``:memory:``-without-``uri_mode`` guard runs, which is a pure
    in-memory check. No directory is created and no ``.db`` file is
    written by this function. Connecting (``DatabaseManager.connect()``)
    is deliberately left to a future caller (e.g. a Repository, or an
    explicit startup step) -- exactly the same construct-only boundary
    ``_build_provider`` already draws for ``GeminiProvider`` (construct
    here, ``connect()``/real I/O only at actual first use).

    Not a process-wide singleton: unlike ``provider_manager``/
    ``agent_registry``/``service_registry``, ``Database.database_manager.
    DatabaseManager`` defines no such registry, so this simply returns a
    fresh instance on every call, same as ``executor``/``planner``.
    """
    return DatabaseManager(SQLiteDatabase(DatabaseConfig.from_env()))


def _build_account_repository(database_manager: DatabaseManager) -> AccountRepository:
    """Construct (never connect, never migrate) the Sprint 4 STEP 1
    ``AccountRepository`` over this graph's one shared ``database_manager``.

    Purely wiring, same construct-only boundary every other component in
    this module already draws (see :func:`_build_database_manager`,
    :func:`_build_provider`): ``AccountRepository.__init__`` only stores
    ``database_manager`` by reference -- it opens no connection and
    issues no SQL statement. This function's entire job is to make sure
    that reference is the *same* ``DatabaseManager`` instance
    ``build_application`` already built once (never a second one),
    because Sprint 4's later Repositories (``PositionRepository``,
    ``OrderRepository``, ``TradeRepository``, none of which exist yet)
    must share it too -- ``BasePersistenceRepository._session()``'s
    transaction-nesting-via-SAVEPOINT only spans calls that go through
    one common ``DatabaseManager``/connection. Getting this identity
    wrong here would silently break every later Sprint 4 atomicity
    guarantee, so it is proven explicitly by
    ``Tests/test_stage_sprint4_step1_account_repository_wiring.py``
    rather than left implicit.

    Deliberately does NOT run ``ACCOUNTS_MIGRATIONS``: applying the
    ``accounts`` table migration remains the operator's explicit,
    manual step (``python run_account_migrations.py``), same scope
    decision already documented on that script and on
    ``Database.migrations_accounts``. This function only makes
    ``AccountRepository`` reachable from the production graph for the
    first time -- it does not change when or how the schema itself
    gets applied to a real database file.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only,
    the same additive pattern ``portfolio_engine``/``portfolio_risk``/
    etc. already established. No ``PaperTradingEngine`` exists yet to
    consume it; a later Sprint 4 STEP wires that consumer.
    """
    return AccountRepository(database_manager)


def _build_watchlist_repository(database_manager: DatabaseManager) -> WatchlistRepository:
    """Construct (never connect, never migrate) the Sprint 5 STEP 1
    ``WatchlistRepository`` over this graph's one shared ``database_manager``.

    Mirrors :func:`_build_account_repository` exactly: purely wiring --
    ``WatchlistRepository.__init__`` (inherited, unmodified, from
    ``BasePersistenceRepository``) only stores ``database_manager`` by
    reference; it opens no connection and issues no SQL statement.

    Deliberately does NOT run ``Database.migrations_watchlist.
    WATCHLIST_MIGRATIONS``: applying the ``watchlist`` table migration
    remains the operator's explicit, manual step
    (``python run_watchlist_migrations.py``), same scope decision
    already documented on that script. This function only makes
    ``WatchlistRepository`` reachable from the production graph for
    the first time -- it does not change when or how the schema itself
    gets applied to a real database file.

    Not yet passed into ``agent``, ``market_analysis_agent``, or any
    other collaborator -- graph-visibility only, until
    ``WatchlistScanner`` (built outside this module) is wired to
    consume this exact instance.
    """
    return WatchlistRepository(database_manager)


def _build_market_tool_resolver(
    permission_context: PermissionContext,
) -> Tuple[ToolResolver, ToolManager]:
    """Construct the ONE production ``ToolResolver`` over the ONE
    production ``Orchestration.tool_registry.ToolRegistry`` instance
    that wraps the three existing, unmodified ``Market*Tool`` classes
    under their production names -- ``"market_price"``,
    ``"market_news"``, ``"market_fundamental"`` -- and (Activation 12,
    Tool and Capability Registry discovery) the ONE
    ``Orchestration.tool_manager.ToolManager`` facade wrapping that
    EXACT SAME ``tool_registry``/``ToolResolver`` pair, never a
    second, independently-constructed registry. Returns both as a
    ``(ToolResolver, ToolManager)`` tuple -- the ``ToolResolver`` is
    unchanged from every prior Activation's shape and behavior; the
    ``ToolManager`` is new graph-visibility-only surface area (see
    ``ApplicationGraph.market_tool_manager``'s own docstring) adding
    exactly one previously-absent capability: read-only enumeration of
    the registered tool names via ``.list()``.

    Activation 12.6: ``permission_context`` is no longer constructed
    here -- it is injected by the caller (``build_application()``),
    which constructs exactly ONE ``PermissionContext`` per application
    graph and passes that same instance into both this function and
    :func:`_build_service_skills`. See ``build_application()`` for the
    single construction site.

    Activation 2.2 (Production Dependency Resolver): extracted out of
    ``_build_trading_decision_agent()``, which previously built this
    exact registration inline as a private local every time it ran.
    That left ``Orchestration.market_analysis_agent.MarketAnalysisAgent``'s
    own ``MarketAnalysisSkill`` (see :func:`_build_market_analysis_agent`)
    with no resolver at all -- not a second, competing resolver, an
    *absent* one, confirmed by Activation 2.1's audit and by
    ``Tests/test_stage_sprint5_step1_watchlist_scanner_wiring.py``'s own
    (now-updated) regression check. This function is the single place
    that resolver is built; every ``MarketAnalysisSkill`` instance in
    the production graph is wired to the *same* ``ToolResolver``
    returned here -- never a second, independently-constructed one, and
    never a dummy/fallback stand-in.

    No new ``ToolRegistry`` class, no new ``ToolResolver`` class, and no
    new Tool are introduced -- only the existing production
    ``Orchestration.tool_registry.ToolRegistry`` (aliased
    ``OrchestrationToolRegistry`` in this module to avoid colliding with
    the unrelated ``Agents.tool_registry.ToolRegistry``),
    ``Orchestration.tool_resolver.ToolResolver``, and the three existing
    ``MarketPriceTool``/``MarketNewsTool``/``MarketFundamentalTool``
    classes, constructed once instead of built inline per-caller.
    """
    # Activation 12.3: each Market*Tool is wrapped in a PermissionedTool
    # before registration, over one shared PermissionContext for this
    # graph. ToolRegistry.register()/ToolResolver.resolve() are both
    # unchanged -- they already treat a "tool" as an opaque object by
    # design (see both modules' own docstrings), so they transparently
    # store/return the wrapper instead of the raw tool. All three tools
    # are undeclared (no `.permission` attribute), so
    # Orchestration.tool_permission_enforcer.permission_for_tool()
    # defaults them to READ_ONLY -- always authorized regardless of the
    # PermissionContext below -- so this wrapping is a safety boundary
    # addition only, with no behavior change to these three read-only
    # market-data tools today.
    #
    # Activation 12.6: ``permission_context`` is the caller-injected
    # parameter above, not a locally constructed instance -- this is
    # the same object ``_build_service_skills()`` receives, so the
    # canonical and legacy tool paths share one identity, never two
    # independently-constructed contexts.
    tool_registry = OrchestrationToolRegistry()
    tool_registry.register(
        "market_price", PermissionedTool(MarketPriceTool(), permission_context)
    )
    tool_registry.register(
        "market_news", PermissionedTool(MarketNewsTool(), permission_context)
    )
    tool_registry.register(
        "market_fundamental",
        PermissionedTool(MarketFundamentalTool(), permission_context),
    )
    tool_resolver = ToolResolver(tool_registry)
    tool_manager = ToolManager(tool_registry, tool_resolver)
    return tool_resolver, tool_manager


def _build_paper_execution_tool_resolver(
    paper_trading_engine: PaperTradingEngine,
    permission_context: PermissionContext,
) -> ToolResolver:
    """Construct the ONE production ``ToolResolver`` exposing the
    Activation 12.8 ``Orchestration.paper_execution_tool.
    PaperExecutionTool`` under its stable name, ``"paper_execution"``.

    Mirrors :func:`_build_market_tool_resolver`'s own, LOCKED shape
    exactly -- a fresh ``Orchestration.tool_registry.ToolRegistry``,
    one ``PermissionedTool``-wrapped registration, one
    ``Orchestration.tool_resolver.ToolResolver`` returned over it --
    but is a SEPARATE registry/resolver pair, never the same instance
    :func:`_build_market_tool_resolver` builds for the three
    ``Market*Tool`` classes. This is deliberate: this function must run
    strictly AFTER ``paper_trading_engine`` exists (see
    :func:`_build_paper_trading_engine`), while
    :func:`_build_market_tool_resolver` is called before
    ``paper_trading_engine`` is constructed (see ``build_application()``
    for the exact ordering) -- reusing that earlier registry would
    require either constructing ``paper_trading_engine`` before its own
    ten collaborators exist, or reordering roughly 150 lines of already
    LOCKED, narrated production wiring. Both are unnecessary: nothing in
    ``Orchestration.tool_registry.ToolRegistry``'s own contract requires
    a single, global registry (see that module's own "each instance
    owns its own independent dictionary" docstring) -- a second,
    independently-owned registry is exactly the "canonical tool
    resolver/registry" mechanism this Activation's roadmap calls for,
    applied a second time for a second Tool, not a second financial
    execution path.

    ``permission_context`` is never constructed here -- it is the exact
    same shared ``PermissionContext`` instance ``build_application()``
    also passes to :func:`_build_market_tool_resolver` and
    :func:`_build_service_skills` (Activation 12.6's single-owner
    rule). ``paper_trading_engine`` is never constructed here either --
    it is this graph's one, already-fully-wired
    ``Business.paper_trading_engine.PaperTradingEngine`` instance (see
    :func:`_build_paper_trading_engine`), passed straight through to
    ``PaperExecutionTool.__init__`` unchanged.

    ``PaperExecutionTool`` declares ``Orchestration.tool_permission.
    ToolPermission.PAPER_EXECUTION`` on itself (see that class's own
    docstring) -- unlike the three undeclared/READ_ONLY ``Market*Tool``
    instances :func:`_build_market_tool_resolver` wraps, resolving
    ``"paper_execution"`` and calling ``.execute(context)`` on the
    result is denied by ``Orchestration.permissioned_tool.
    PermissionedTool`` (raising ``Orchestration.
    tool_permission_enforcer.ToolPermissionDenied``, strictly before
    ``PaperTradingEngine.submit_order()`` is ever reached) unless
    ``permission_context.paper_execution_allowed`` is ``True`` -- which
    it never is under today's LOCKED, fail-closed
    default, zero-argument ``PermissionContext`` construction.
    """
    tool_registry = OrchestrationToolRegistry()
    tool_registry.register(
        "paper_execution",
        PermissionedTool(
            PaperExecutionTool(paper_trading_engine), permission_context
        ),
    )
    return ToolResolver(tool_registry)


def _build_copilot_tool_resolver(
    permission_context: PermissionContext,
) -> ToolResolver:
    """Construct the ONE production ``ToolResolver`` exposing Phase F,
    Task 8's ``Orchestration.copilot_tool.CopilotTool`` under its
    stable name, ``"copilot"``.

    Mirrors :func:`_build_paper_execution_tool_resolver`'s own, LOCKED
    shape exactly -- a fresh ``Orchestration.tool_registry.
    ToolRegistry``, one ``PermissionedTool``-wrapped registration, one
    ``Orchestration.tool_resolver.ToolResolver`` returned over it --
    but is a SEPARATE registry/resolver pair, never the same instance
    :func:`_build_market_tool_resolver`/
    :func:`_build_paper_execution_tool_resolver` build for their own
    tools. Nothing in ``Orchestration.tool_registry.ToolRegistry``'s
    own contract requires a single, global registry (see that
    module's own "each instance owns its own independent dictionary"
    docstring) -- a third, independently-owned registry is exactly the
    same "canonical tool resolver/registry" mechanism already applied
    twice, applied a third time for a third Tool.

    Unlike :func:`_build_paper_execution_tool_resolver`, this function
    needs no financial collaborator: ``CopilotTool()`` takes no
    constructor arguments (it delegates every ``execute()`` call to a
    freshly-constructed, stateless ``Services.copilot_service.
    CopilotService`` -- see that class's own docstring), so this
    function can run as soon as ``permission_context`` exists, with no
    ordering dependency on ``paper_trading_engine`` or any other
    graph collaborator.

    ``permission_context`` is never constructed here -- it is the
    exact same shared ``PermissionContext`` instance
    ``build_application()`` also passes to
    :func:`_build_market_tool_resolver`,
    :func:`_build_paper_execution_tool_resolver`, and
    :func:`_build_service_skills` (Activation 12.6's single-owner
    rule).

    ``CopilotTool`` declares ``Orchestration.tool_permission.
    ToolPermission.READ_ONLY`` on itself (see that class's own
    docstring) -- exactly like the three undeclared/READ_ONLY
    ``Market*Tool`` instances :func:`_build_market_tool_resolver`
    wraps, resolving ``"copilot"`` and calling ``.execute(context)``
    on the result is authorized unconditionally by
    ``Orchestration.tool_permission_enforcer.authorize_tool``,
    regardless of ``permission_context``'s three (fail-closed, always
    ``False`` by default) capability flags. This function never sets
    any of those flags and never grants PAPER_EXECUTION,
    LIVE_EXECUTION, or DESTRUCTIVE_ADMIN to anything -- ``CopilotTool``
    could not use such a grant even if one existed, since it never
    declares any permission other than READ_ONLY.
    """
    tool_registry = OrchestrationToolRegistry()
    tool_registry.register(
        "copilot",
        PermissionedTool(CopilotTool(), permission_context),
    )
    return ToolResolver(tool_registry)


def _build_market_analysis_agent(tool_resolver: ToolResolver) -> MarketAnalysisAgent:
    """Construct the Sprint 5 STEP 1 ``Orchestration.market_analysis_agent.
    MarketAnalysisAgent`` -- LOCKED DECISION (Revisi): the first
    production instance of this class.

    No instance of ``Orchestration.market_analysis_agent.MarketAnalysisAgent``
    exists anywhere else in production code, so this is a first
    construction, not a reuse -- the "never build a second instance"
    constraint does not apply. Its three Skill collaborators are each
    constructed fresh, with no arguments (confirmed by audit: neither
    ``PortfolioAnalysisSkill`` nor ``WatchlistAnalysisSkill`` defines
    its own ``__init__``, and ``MarketAnalysisSkill`` likewise takes
    none):

        MarketAnalysisSkill(), PortfolioAnalysisSkill(), WatchlistAnalysisSkill()

    Deliberately NOT the same ``MarketAnalysisSkill`` *instance*
    :func:`_build_trading_decision_agent` builds for
    ``TradingDecisionAgent`` -- no refactor merges the two Skill
    objects, per LOCKED DECISION rules 3-4; ``TradingDecisionAgent``
    remains an untouched black box.

    Activation 2.2 fix: this fresh ``MarketAnalysisSkill`` now has
    ``_resolve_tool`` injected from the caller-supplied
    ``tool_resolver`` -- the same production ``ToolResolver``
    :func:`_build_trading_decision_agent` uses for its own
    ``MarketAnalysisSkill`` (see :func:`_build_market_tool_resolver`).
    Before this fix, no ``_resolve_tool`` was injected here at all, so
    every per-symbol ``TextAnalysisSkill`` call this Skill made raised
    a missing-resolver ``SkillError`` internally (caught by
    ``MarketAnalysisSkill.execute()``'s own per-symbol ``try``/
    ``except``, so it never raised out of
    ``MarketAnalysisAgent.execute()`` itself, but every ``"market"``
    result carried ``analysis: None`` with a failure message per
    symbol) -- i.e. the ``scan`` command's market analysis was always
    failing silently. No new ``ToolResolver`` or ``ToolRegistry`` is
    built here; the one built by :func:`_build_market_tool_resolver`
    is reused by reference.

    Not yet passed into ``agent`` or ``runtime_analysis_pipeline`` --
    graph-visibility only, until ``WatchlistScanner`` (built outside
    this module) is wired to consume this exact instance.
    """
    market_analysis_skill = MarketAnalysisSkill()
    market_analysis_skill._resolve_tool = tool_resolver.resolve

    return MarketAnalysisAgent(
        market_analysis_skill,
        PortfolioAnalysisSkill(),
        WatchlistAnalysisSkill(),
    )


def _build_position_repository(database_manager: DatabaseManager) -> PositionRepository:
    """Construct (never connect, never migrate) the Sprint 4 STEP 2
    ``PositionRepository`` over this graph's one shared ``database_manager``.

    Mirrors :func:`_build_account_repository` exactly: purely wiring,
    same construct-only boundary -- ``PositionRepository.__init__``
    only stores ``database_manager`` by reference, opening no
    connection and issuing no SQL statement. This function's entire
    job is to make sure that reference is the *same* ``DatabaseManager``
    instance ``build_application`` already built once (never a second
    one), so that ``account_repository`` and ``position_repository``
    -- and any later Sprint 4 Repository (``OrderRepository``,
    ``TradeRepository``, neither of which exists yet) -- all share one
    connection for ``BasePersistenceRepository._session()``'s
    transaction-nesting-via-SAVEPOINT to actually span them.

    Deliberately does NOT run ``POSITIONS_MIGRATIONS``: applying the
    ``positions`` table migration remains the operator's explicit,
    manual step (``python run_position_migrations.py``), same scope
    decision already documented on that script and on
    ``Database.migrations_positions``.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No ``PositionManager``/``PaperTradingEngine`` exists yet to
    consume it; a later Sprint 4 STEP wires that consumer.
    """
    return PositionRepository(database_manager)


def _build_order_repository(database_manager: DatabaseManager) -> OrderRepository:
    """Construct (never connect, never migrate) the Sprint 4 STEP 3
    ``OrderRepository`` over this graph's one shared ``database_manager``.

    Mirrors :func:`_build_position_repository` exactly: purely wiring,
    same construct-only boundary -- ``OrderRepository.__init__`` only
    stores ``database_manager`` by reference, opening no connection
    and issuing no SQL statement. This function's entire job is to
    make sure that reference is the *same* ``DatabaseManager`` instance
    ``build_application`` already built once (never a second one), so
    that ``account_repository``, ``position_repository``, and
    ``order_repository`` -- and any later Sprint 4 Repository
    (``TradeRepository``, which does not exist yet) -- all share one
    connection for ``BasePersistenceRepository._session()``'s
    transaction-nesting-via-SAVEPOINT to actually span them.

    Deliberately does NOT run ``ORDERS_MIGRATIONS``: applying the
    ``orders`` table migration remains the operator's explicit, manual
    step (``python run_order_migrations.py``), same scope decision
    already documented on that script and on
    ``Database.migrations_orders``.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No ``OrderLifecycleService``/``ExecutionService``/
    ``PaperTradingEngine`` exists yet to consume it; a later Sprint 4
    STEP wires that consumer.
    """
    return OrderRepository(database_manager)


def _build_trade_repository(database_manager: DatabaseManager) -> TradeRepository:
    """Construct (never connect, never migrate) the Sprint 4 STEP 4
    ``TradeRepository`` over this graph's one shared ``database_manager``.

    Mirrors :func:`_build_order_repository` exactly: purely wiring,
    same construct-only boundary -- ``TradeRepository.__init__`` only
    stores ``database_manager`` by reference, opening no connection
    and issuing no SQL statement. This function's entire job is to
    make sure that reference is the *same* ``DatabaseManager`` instance
    ``build_application`` already built once (never a second one), so
    that ``account_repository``, ``position_repository``,
    ``order_repository``, and ``trade_repository`` all share one
    connection for ``BasePersistenceRepository._session()``'s
    transaction-nesting-via-SAVEPOINT to actually span them.

    Deliberately does NOT run ``TRADES_MIGRATIONS``: applying the
    ``trades`` table migration remains the operator's explicit, manual
    step (``python run_trade_migrations.py``), same scope decision
    already documented on that script and on
    ``Database.migrations_trades``.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No ``ExecutionService``/``OrderLifecycleService``/
    ``PositionManager``/``PaperTradingEngine`` exists yet to consume
    it; a later Sprint 4 STEP wires that consumer.
    """
    return TradeRepository(database_manager)


def _build_snapshot_repository(database_manager: DatabaseManager) -> SnapshotRepository:
    """Construct (never connect, never migrate) the Sprint 5 STEP 3
    ``SnapshotRepository`` over this graph's one shared ``database_manager``.

    Mirrors :func:`_build_trade_repository` exactly: purely wiring,
    same construct-only boundary -- ``SnapshotRepository.__init__``
    only stores ``database_manager`` by reference, opening no
    connection and issuing no SQL statement. This function's entire
    job is to make sure that reference is the *same* ``DatabaseManager``
    instance ``build_application`` already built once (never a second
    one), so that ``account_repository``, ``position_repository``,
    ``order_repository``, ``trade_repository``, and
    ``snapshot_repository`` all share one connection for
    ``BasePersistenceRepository._session()``'s transaction-nesting-via-
    SAVEPOINT to actually span them.

    Deliberately does NOT run ``SNAPSHOTS_MIGRATIONS``: applying the
    ``ranking_snapshots`` table migration remains the operator's
    explicit, manual step (``python run_snapshot_migrations.py``), same
    scope decision already documented on that script and on
    ``Database.migrations_snapshots``.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No consumer of ``Business.ranking_engine.RankingEngine.rank()``'s
    output exists yet to write through this repository; this STEP only
    makes the repository constructible and reachable via the graph.
    """
    return SnapshotRepository(database_manager)


def _build_performance_repository(database_manager: DatabaseManager) -> PerformanceRepository:
    """Construct (never connect, never migrate) the Sprint 6 STEP 1
    ``PerformanceRepository`` over this graph's one shared
    ``database_manager``.

    Mirrors :func:`_build_snapshot_repository` exactly: purely wiring,
    same construct-only boundary -- ``PerformanceRepository.__init__``
    (inherited from ``BasePersistenceRepository``) only stores
    ``database_manager`` by reference, opening no connection and
    issuing no SQL statement. This function's entire job is to make
    sure that reference is the *same* ``DatabaseManager`` instance
    ``build_application`` already built once (never a second one), so
    that ``account_repository``, ``position_repository``,
    ``order_repository``, ``trade_repository``, ``snapshot_repository``,
    and ``performance_repository`` all share one connection for
    ``BasePersistenceRepository._session()``'s transaction-nesting-via-
    SAVEPOINT to actually span them.

    Runs no migration: ``PerformanceRepository`` is read-only and
    creates no table of its own -- it queries tables whose migrations
    (``ACCOUNTS_MIGRATIONS``/``POSITIONS_MIGRATIONS``/
    ``ORDERS_MIGRATIONS``/``TRADES_MIGRATIONS``/
    ``SNAPSHOTS_MIGRATIONS``) remain the operator's separate, manual,
    unchanged steps.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No consumer (e.g. a future ``PerformanceAnalysisService``) exists
    yet to read through this repository; this STEP only makes the
    repository constructible and reachable via the graph.
    """
    return PerformanceRepository(database_manager)


def _build_portfolio_snapshot_repository(database_manager: DatabaseManager) -> PortfolioSnapshotRepository:
    """Construct (never connect, never migrate) the Activation 5.2
    ``PortfolioSnapshotRepository`` over this graph's one shared
    ``database_manager``.

    Mirrors :func:`_build_performance_repository` exactly: purely
    wiring, same construct-only boundary -- ``__init__`` (inherited
    from ``BasePersistenceRepository``) only stores ``database_manager``
    by reference. Makes sure it is the *same* shared instance every
    other persistence repository in this graph uses.

    Runs no migration: applying
    ``Database.migrations_portfolio_snapshots`` to a real database
    remains a separate, manual, unchanged operator step.
    """
    return PortfolioSnapshotRepository(database_manager)


def _build_decision_brief_service(
    database_manager: DatabaseManager,
    snapshot_repository: SnapshotRepository,
) -> DecisionBriefService:
    """Construct (never connect, never migrate) Phase B's
    ``DecisionBriefService`` over this graph's shared collaborators.

    Reuses ``snapshot_repository`` -- the same shared instance every
    other repository in this graph uses, never a second
    ``SnapshotRepository`` -- and constructs one
    ``DecisionBriefRepository`` over the same ``database_manager``, one
    stateless ``DecisionBriefPolicy``, and one stateless
    ``RiskManagementService`` (a fresh instance, mirroring
    ``_build_analysis_pipeline``'s own ``RiskManagementService()``
    construction -- that service takes no constructor arguments and
    holds no state, so a second instance here is not a second risk
    engine, just a second handle to the same stateless calculation).

    Runs no migration: applying ``Database.migrations_decision_briefs``
    to a real database remains a separate, manual, unchanged operator
    step (``run_decision_brief_migrations.py``).
    """
    brief_repository = DecisionBriefRepository(database_manager)
    decision_brief_policy = DecisionBriefPolicy()
    risk_service = RiskManagementService()
    return DecisionBriefService(
        snapshot_repository=snapshot_repository,
        decision_brief_policy=decision_brief_policy,
        risk_service=risk_service,
        brief_repository=brief_repository,
    )


def _build_risk_limits_repository(database_manager: DatabaseManager) -> RiskLimitsRepository:
    """Construct (never connect, never migrate) Phase C's
    ``RiskLimitsRepository`` over this graph's shared ``database_manager``.

    Mirrors every other ``_build_*_repository`` function in this
    module: the same shared ``database_manager`` instance, never a
    second ``DatabaseManager``. Applying
    ``Database.migrations_risk_ledger`` to a real database remains a
    separate, manual operator step (``run_risk_ledger_migrations.py``).
    """
    return RiskLimitsRepository(database_manager)


def _build_journal_service(
    database_manager: DatabaseManager,
    risk_limits_repository: RiskLimitsRepository,
) -> JournalService:
    """Construct (never connect, never migrate) Phase C's
    ``JournalService`` -- the personal risk ledger + decision journal.

    Reuses ``risk_limits_repository`` -- the same shared instance this
    graph already built (never a second one) -- and constructs one
    fresh ``DecisionBriefRepository`` over this same
    ``database_manager`` for read-only brief lookups (mirrors
    ``_build_decision_brief_service``'s own ``RiskManagementService()``
    reasoning: a repository over the shared ``database_manager`` holds
    no independent state, so a second instance here observes the same
    ``decision_briefs`` table, not a second one), one new
    ``JournalRepository``, and one stateless ``RiskLedgerPolicy`` --
    the only new risk-policy component this graph adds. It never
    recomputes a stop/target/position size itself, only enforces
    personal limits against the already-priced ``DecisionBrief`` it
    reads.

    Runs no migration: applying ``Database.migrations_risk_ledger`` to
    a real database remains a separate, manual operator step
    (``run_risk_ledger_migrations.py``).
    """
    brief_repository = DecisionBriefRepository(database_manager)
    journal_repository = JournalRepository(database_manager)
    risk_ledger_policy = RiskLedgerPolicy()
    return JournalService(
        brief_repository=brief_repository,
        risk_limits_repository=risk_limits_repository,
        journal_repository=journal_repository,
        risk_ledger_policy=risk_ledger_policy,
    )


def _build_observation_window_service(database_manager: DatabaseManager) -> ObservationWindowService:
    """Construct (never connect, never migrate) Phase H Task 1's
    ``ObservationWindowService`` over this graph's shared
    ``database_manager``.

    Mirrors ``_build_risk_limits_repository``/``_build_journal_service``:
    one fresh ``ObservationWindowRepository`` over the same shared
    ``database_manager`` instance, never a second ``DatabaseManager``.
    This service holds no reference to any trading/execution
    component -- it is purely the operator-selected review-window
    record.

    Runs no migration: applying
    ``Database.migrations_observation_window`` to a real database
    remains a separate, manual operator step
    (``run_observation_window_migrations.py``).
    """
    window_repository = ObservationWindowRepository(database_manager)
    return ObservationWindowService(window_repository=window_repository)


def _build_sustained_use_review_service(
    database_manager: DatabaseManager,
    paper_review_service: PaperReviewService,
    reconciliation_engine: ReconciliationEngine,
    portfolio_snapshot_repository: PortfolioSnapshotRepository,
) -> SustainedUseReviewService:
    """Phase H Task 3 ("Sustained-Use Review Report"): construct (never
    connect, never migrate) Phase H Task 2's already-complete, LOCKED
    ``SustainedUseReviewService``, giving it its first real production
    entry point (``python main.py report sustained-use``).

    Builds fresh, stateless repository instances
    (``ObservationWindowRepository``/``SchedulerStateRepository``/
    ``AuditEventRepository``/``NotificationDedupRepository``/
    ``TelegramCommandAuditRepository``/``DecisionBriefRepository``/
    ``JournalRepository``/``DailyPerformanceRepository``) over this
    graph's own shared ``database_manager`` -- mirrors
    ``_build_idx_daily_scheduler``/``_build_health_audit_service``'s
    own "a repository over the shared database_manager holds no
    independent state" reasoning, never a second ``DatabaseManager``.
    Reuses this graph's already-built ``paper_review_service``/
    ``reconciliation_engine``/``portfolio_snapshot_repository`` -- the
    exact same shared instances, never a second copy.

    Runs no migration: applying any of the underlying migrations to a
    real database remains a separate, manual operator step, same as
    every other ``_build_*`` helper in this module.
    """
    window_repository = ObservationWindowRepository(database_manager)
    scheduler_state_repository = SchedulerStateRepository(database_manager)
    audit_event_repository = AuditEventRepository(database_manager)
    notification_dedup_repository = NotificationDedupRepository(database_manager)
    telegram_command_audit_repository = TelegramCommandAuditRepository(database_manager)
    decision_brief_repository = DecisionBriefRepository(database_manager)
    journal_repository = JournalRepository(database_manager)
    daily_performance_repository = DailyPerformanceRepository(database_manager)

    return SustainedUseReviewService(
        observation_window_repository=window_repository,
        scheduler_state_repository=scheduler_state_repository,
        audit_event_repository=audit_event_repository,
        notification_dedup_repository=notification_dedup_repository,
        telegram_command_audit_repository=telegram_command_audit_repository,
        decision_brief_repository=decision_brief_repository,
        journal_repository=journal_repository,
        paper_review_service=paper_review_service,
        reconciliation_engine=reconciliation_engine,
        daily_performance_repository=daily_performance_repository,
        portfolio_snapshot_repository=portfolio_snapshot_repository,
    )


def _build_sustained_use_final_review_service(
    database_manager: DatabaseManager,
    sustained_use_review_service: SustainedUseReviewService,
) -> SustainedUseFinalReviewService:
    """Phase H Task 4 ("Operator Feedback + Final Review Record"):
    construct (never connect, never migrate) the new
    ``SustainedUseFinalReviewService`` over this graph's shared
    ``database_manager``.

    Builds fresh, stateless repository instances
    (``ObservationWindowRepository``/``OperatorFeedbackRepository``/
    ``FinalReviewRecordRepository``) over this graph's own shared
    ``database_manager`` -- mirrors ``_build_sustained_use_review_service``'s
    own "a repository over the shared database_manager holds no
    independent state" reasoning, never a second ``DatabaseManager``.
    Reuses this graph's already-built, LOCKED
    ``sustained_use_review_service`` (Phase H Task 2, unmodified) --
    the exact same shared instance, never a second copy.

    Runs no migration: applying
    ``Database.migrations_sustained_use_final_review`` to a real
    database remains a separate, manual operator step
    (``run_sustained_use_final_review_migrations.py``).
    """
    window_repository = ObservationWindowRepository(database_manager)
    operator_feedback_repository = OperatorFeedbackRepository(database_manager)
    final_review_record_repository = FinalReviewRecordRepository(database_manager)

    return SustainedUseFinalReviewService(
        observation_window_repository=window_repository,
        sustained_use_review_service=sustained_use_review_service,
        operator_feedback_repository=operator_feedback_repository,
        final_review_record_repository=final_review_record_repository,
    )


def _build_idx_daily_scheduler(
    database_manager: DatabaseManager,
    manual_scan_service: ManualScanService,
    daily_report_orchestrator: DailyReportOrchestrator,
    notification_manager: NotificationManager,
    account_id: str,
) -> IDXDailyScheduler:
    """Construct (never connect, never migrate) Phase D's
    ``IDXDailyScheduler`` -- the proactive IDX scheduler routine.

    Builds three fresh Phase D repositories
    (``SchedulerStateRepository``/``NotificationDedupRepository``/
    ``AuditEventRepository``) over this graph's shared
    ``database_manager`` -- the same shared instance every other
    repository in this graph uses, never a second ``DatabaseManager``
    -- plus one ``IDXMarketCalendar``/``DataFreshnessPolicy``/
    ``NotificationDedupPolicy`` each, loaded from the environment via
    their own ``load_*`` functions (mirrors
    ``_build_journal_service``'s own "one stateless policy, loaded
    once" convention).

    Reuses ``manual_scan_service``/``daily_report_orchestrator``/
    ``notification_manager`` -- the exact same shared instances this
    graph already built (never a second ``ManualScanService`` or a
    second scan/notification pipeline).

    Runs no migration: applying ``Database.migrations_scheduler`` to a
    real database remains a separate, manual operator step
    (``run_scheduler_migrations.py``).
    """
    scheduler_state_repository = SchedulerStateRepository(database_manager)
    notification_dedup_repository = NotificationDedupRepository(database_manager)
    audit_event_repository = AuditEventRepository(database_manager)
    idx_market_calendar = load_idx_market_calendar()
    data_freshness_policy = load_data_freshness_policy()
    notification_dedup_policy = load_notification_dedup_policy()

    return IDXDailyScheduler(
        idx_market_calendar=idx_market_calendar,
        scheduler_state_repository=scheduler_state_repository,
        notification_dedup_repository=notification_dedup_repository,
        notification_dedup_policy=notification_dedup_policy,
        data_freshness_policy=data_freshness_policy,
        audit_event_repository=audit_event_repository,
        manual_scan_service=manual_scan_service,
        daily_report_orchestrator=daily_report_orchestrator,
        notification_manager=notification_manager,
        account_id=account_id,
    )


def _build_health_audit_service(database_manager: DatabaseManager) -> HealthAuditService:
    """Construct (never connect, never migrate) Phase D's read-only
    ``HealthAuditService``.

    Builds its own fresh instances of the same three Phase D
    repositories (over this same shared ``database_manager`` -- so it
    observes the exact same ``scheduler_job_runs``/
    ``notification_dedup_state``/``audit_events`` rows
    ``idx_daily_scheduler`` writes, never a separate copy) plus one
    ``IDXMarketCalendar`` for its own "what trading date is 'today'"
    default. Purely a read-side view; writes nothing.
    """
    scheduler_state_repository = SchedulerStateRepository(database_manager)
    notification_dedup_repository = NotificationDedupRepository(database_manager)
    audit_event_repository = AuditEventRepository(database_manager)
    idx_market_calendar = load_idx_market_calendar()

    return HealthAuditService(
        scheduler_state_repository=scheduler_state_repository,
        notification_dedup_repository=notification_dedup_repository,
        audit_event_repository=audit_event_repository,
        idx_market_calendar=idx_market_calendar,
    )


#: Environment variable this module already reads for the Telegram bot
#: token credential (see ``_TELEGRAM_BOT_TOKEN_ENV`` above, read by
#: ``_notification_service_context_factory``). The Phase E Task 6
#: control-plane wiring below reads the exact same variable, via the
#: exact same ``config.get_str`` seam -- never a second/parallel
#: credential name.
def _build_telegram_command_audit_repository(
    database_manager: DatabaseManager,
) -> TelegramCommandAuditRepository:
    """Construct Phase E Task 1's ``TelegramCommandAuditRepository``.

    Built over this same shared ``database_manager`` instance --
    mirroring every other Repository ``_build_*`` function in this
    module (e.g. :func:`_build_watchlist_repository`) -- never a
    second ``DatabaseManager``. No migration is run here (``python
    run_telegram_control_migrations.py`` remains the operator's
    explicit step, exactly like every other domain migration script).
    """
    return TelegramCommandAuditRepository(database_manager)


def _build_telegram_inbound_state_repository(
    database_manager: DatabaseManager,
) -> TelegramInboundStateRepository:
    """Construct Phase E Task 1's ``TelegramInboundStateRepository``.

    Built over this same shared ``database_manager`` instance, same
    rationale as :func:`_build_telegram_command_audit_repository`
    immediately above.
    """
    return TelegramInboundStateRepository(database_manager)


def _build_telegram_allowlist_policy() -> TelegramAllowlistPolicy:
    """Construct Phase E Task 2's ``TelegramAllowlistPolicy`` via its
    own ``load_telegram_allowlist_policy()`` factory.

    Reads ``TELEGRAM_ALLOWED_CHAT_IDS`` / ``TELEGRAM_CHAT_ID`` from the
    shared ``Core.config.config`` singleton (that factory's own
    default ``env_get``) -- the exact same ``TELEGRAM_CHAT_ID``
    variable ``_notification_service_context_factory`` already reads
    for outbound notifications. Fails closed (empty allowlist) when
    neither is configured, per that module's own LOCKED contract --
    unchanged, unmodified here.
    """
    return load_telegram_allowlist_policy()


def _build_telegram_command_executor(
    manual_scan_service: ManualScanService,
    decision_brief_service: DecisionBriefService,
    journal_service: JournalService,
    performance_summary_production_service: PerformanceSummaryProductionService,
) -> TelegramCommandExecutor:
    """Construct Phase E Task 4's ``TelegramCommandExecutor`` over this
    graph's four already-built, existing services.

    Reuses the exact same ``manual_scan_service``/
    ``decision_brief_service``/``journal_service``/
    ``performance_summary_production_service`` instances
    ``build_application`` already constructed earlier -- never a
    second instance of any of the four, and no broker/execution/order
    dependency is introduced (``TelegramCommandExecutor`` imports none
    itself). ``account_id``/``clock`` are left at that class's own
    defaults (``Core.bootstrap.DEFAULT_PAPER_ACCOUNT_ID`` / a real
    clock read) -- unchanged from Task 4.
    """
    return TelegramCommandExecutor(
        manual_scan_service,
        decision_brief_service,
        journal_service,
        performance_summary_production_service,
    )


def _build_telegram_inbound_control_plane(
    allowlist_policy: TelegramAllowlistPolicy,
    executor: TelegramCommandExecutor,
    audit_repository: TelegramCommandAuditRepository,
    inbound_state_repository: TelegramInboundStateRepository,
    notification_service: NotificationService,
) -> TelegramInboundControlPlane:
    """Construct Phase E Task 5's ``TelegramInboundControlPlane`` over
    this graph's already-built Telegram collaborators plus its
    existing ``notification_service``.

    ``bot_token`` is read once, here, from the same
    ``TELEGRAM_BOT_TOKEN`` environment variable
    ``_notification_service_context_factory`` already reads for
    outbound notifications -- never hard-coded, never a second/parallel
    credential name. When it is not configured, this function still
    returns a fully-constructed ``TelegramInboundControlPlane`` (with
    an empty ``bot_token``) rather than raising or leaving the graph
    partially built: ``poll_once()``/reply-sending will then fail
    per-call exactly as they would for any other missing-credential
    case, and ``Core.doctor``'s Telegram inbound section (Task 6) is
    what surfaces that missing configuration visibly -- construction
    itself must never be the place a graph build fails for a merely
    unconfigured *inbound* feature that a production deployment may
    simply not be using yet.

    Reuses this graph's existing ``notification_service`` singleton
    (the same one already registered into ``service_registry`` by
    :func:`_build_notification_service`) for replies -- never a second
    ``NotificationService`` instance, and that class itself is not
    modified.
    """
    bot_token = config.get_str(_TELEGRAM_BOT_TOKEN_ENV, "") or ""
    return TelegramInboundControlPlane(
        allowlist_policy,
        executor,
        audit_repository,
        inbound_state_repository,
        notification_service,
        bot_token=bot_token,
    )


def _build_order_lifecycle_service(order_repository: OrderRepository) -> OrderLifecycleService:
    """Construct the Sprint 4 STEP 5 ``OrderLifecycleService`` over this
    graph's ``order_repository``.

    Purely wiring, same construct-only boundary every ``_build_*``
    function in this module already draws:
    ``OrderLifecycleService.__init__`` only stores ``order_repository``
    by reference -- it opens no connection and issues no SQL statement
    itself (any I/O it triggers only happens on a later, explicit
    ``create_order()``/``transition_status()`` call, exactly like the
    Repositories above only issue SQL on their own explicit method
    calls). This function's entire job is to make sure that reference
    is the *same* ``OrderRepository`` instance ``build_application``
    already built once (never a second one), so any later call through
    this graph's ``order_lifecycle_service`` observes/persists against
    the same ``orders`` table state as any direct
    ``graph.order_repository`` call would.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No ``ExecutionService``/``PositionManager``/
    ``AccountBalanceService``/``PaperTradingEngine`` exists yet to
    consume it; a later Sprint 4 STEP wires that consumer.
    """
    return OrderLifecycleService(order_repository)


def _build_execution_policy() -> ExecutionPolicy:
    """Read the Activation 3.3 canonical ``ExecutionPolicy`` from
    ``Core.config``, once, at graph-build time.

    Mirrors :func:`_kill_switch_engaged`/:func:`_max_order_value`'s
    "read once, thread the same value through every consumer" wiring
    style: both ``_build_execution_service`` and
    ``_build_paper_trading_engine`` receive the *same*
    ``ExecutionPolicy`` instance this function returns, rather than
    each independently calling ``load_execution_policy()`` a second
    time -- "satu source of truth" (Activation 3.3 Ketentuan 1) means
    one object, not just equal values from two reads of the same env
    vars.
    """
    return load_execution_policy()


def _build_execution_service(
    order_repository: OrderRepository,
    trade_repository: TradeRepository,
    execution_policy: ExecutionPolicy,
) -> ExecutionService:
    """Construct the Sprint 4 STEP 6 ``ExecutionService`` over this
    graph's ``order_repository``/``trade_repository``.

    Purely wiring, same construct-only boundary every ``_build_*``
    function in this module already draws:
    ``ExecutionService.__init__`` only stores both repositories (and,
    since Activation 3.3, ``execution_policy``) by reference -- it
    opens no connection and issues no SQL statement itself (any I/O it
    triggers only happens on a later, explicit ``execute_order()``
    call). This function's entire job is to make sure both repository
    references are the *same* ``OrderRepository``/``TradeRepository``
    instances ``build_application`` already built once (never second
    instances), so any later call through this graph's
    ``execution_service`` observes/persists against the same
    ``orders``/``trades`` table state as a direct
    ``graph.order_repository``/``graph.trade_repository`` call would.

    ``execution_policy`` (Activation 3.3): the same ``ExecutionPolicy``
    instance built once by :func:`_build_execution_policy` and also
    passed to :func:`_build_paper_trading_engine` -- never a second,
    independently-loaded policy.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No ``AccountBalanceService``/``PositionManager``/
    ``PaperTradingEngine`` exists yet to consume it; a later Sprint 4
    STEP wires that consumer.
    """
    return ExecutionService(order_repository, trade_repository, execution_policy)


def _build_account_balance_service(
    account_repository: AccountRepository,
) -> AccountBalanceService:
    """Construct the Sprint 4 STEP 7 ``AccountBalanceService`` over this
    graph's ``account_repository``.

    Purely wiring, same construct-only boundary every ``_build_*``
    function in this module already draws:
    ``AccountBalanceService.__init__`` only stores ``account_repository``
    by reference -- it opens no connection and issues no SQL statement
    itself (any I/O it triggers only happens on a later, explicit
    ``apply_trade()`` call). This function's entire job is to make sure
    that reference is the *same* ``AccountRepository`` instance
    ``build_application`` already built once (never a second one), so
    any later call through this graph's ``account_balance_service``
    observes/persists against the same ``accounts`` table state as a
    direct ``graph.account_repository`` call would.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No ``PositionManager``/``PaperTradingEngine`` exists yet to consume
    it; a later Sprint 4 STEP wires that consumer.
    """
    return AccountBalanceService(account_repository)


def _build_position_manager(
    position_repository: PositionRepository,
) -> PositionManager:
    """Construct the Sprint 4 STEP 8 ``PositionManager`` over this
    graph's ``position_repository``.

    Purely wiring, same construct-only boundary every ``_build_*``
    function in this module already draws:
    ``PositionManager.__init__`` only stores ``position_repository``
    by reference -- it opens no connection and issues no SQL statement
    itself (any I/O it triggers only happens on a later, explicit
    ``apply_trade()`` call). This function's entire job is to make
    sure that reference is the *same* ``PositionRepository`` instance
    ``build_application`` already built once (never a second one), so
    any later call through this graph's ``position_manager``
    observes/persists against the same ``positions`` table state as a
    direct ``graph.position_repository`` call would.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    Activation 3.5 STEP 2 wires ``PaperTradingEngine`` as this
    instance's first production consumer -- see
    :func:`_build_paper_trading_engine`.
    """
    return PositionManager(position_repository)


def _build_order_idempotency_repository(
    database_manager: DatabaseManager,
) -> OrderIdempotencyRepository:
    """Construct (never connect, never migrate) the Activation 3.2
    ``OrderIdempotencyRepository`` over this graph's one shared
    ``database_manager``.

    Purely wiring, mirroring :func:`_build_account_repository` exactly:
    ``OrderIdempotencyRepository.__init__`` only stores
    ``database_manager`` by reference -- it opens no connection and
    issues no SQL statement. This function's entire job is to make
    sure that reference is the *same* ``DatabaseManager`` instance
    every other Repository in this graph shares (never a second one).

    Deliberately does NOT run ``IDEMPOTENCY_MIGRATIONS``: applying the
    ``order_idempotency_keys`` table migration remains the operator's
    explicit, manual step (``python run_idempotency_migrations.py``,
    or ``python main.py init`` which now includes it via
    ``Database.migration_registry``), same scope decision already
    documented on every other ``run_*_migrations.py`` script.
    """
    return OrderIdempotencyRepository(database_manager)


def _build_order_approval_repository(
    database_manager: DatabaseManager,
) -> OrderApprovalRepository:
    """Construct (never connect, never migrate) the Activation 7
    Blocker #4 ``OrderApprovalRepository`` over this graph's one
    shared ``database_manager``.

    Purely wiring, mirroring :func:`_build_order_idempotency_repository`
    exactly: ``OrderApprovalRepository.__init__`` only stores
    ``database_manager`` by reference -- it opens no connection and
    issues no SQL statement. This function's entire job is to make
    sure that reference is the *same* ``DatabaseManager`` instance
    every other Repository in this graph shares (never a second one).

    Deliberately does NOT run ``ORDER_APPROVALS_MIGRATIONS``: applying
    the ``order_approvals`` table migration remains the operator's
    explicit, manual step (``python main.py init``, which includes it
    via ``Database.migration_registry``), same scope decision already
    documented on every other domain in this module.
    """
    return OrderApprovalRepository(database_manager)


def _kill_switch_engaged() -> bool:
    """Read the Activation 3.2 kill-switch flag from ``Core.config``.

    Mirrors ``Core.approval_config.build_approval_port``'s pattern of
    reading env vars via the shared ``Core.config.config`` singleton
    rather than introducing a second config mechanism.

    Env var: ``KILL_SWITCH_ENABLED`` (boolean, default ``False`` --
    trading is enabled by default; an operator must explicitly set
    this to engage the kill switch and block all order submission).
    """
    return config.get_bool("KILL_SWITCH_ENABLED", False)


def _max_order_value() -> float:
    """Read the Activation 3.2 per-order risk-limit ceiling from
    ``Core.config``.

    Mirrors :func:`_kill_switch_engaged`'s pattern. Env var:
    ``RISK_MAX_ORDER_VALUE`` (float, default
    ``Database.account_constants.DEFAULT_RISK_MAX_ORDER_VALUE`` -- see
    that constant's docstring for why that default was chosen).
    """
    return config.get_float("RISK_MAX_ORDER_VALUE", DEFAULT_RISK_MAX_ORDER_VALUE)


def _halted_markets() -> frozenset[str]:
    """Read the Activation 8.4 market kill-switch set from ``Core.config``.

    Mirrors :func:`_kill_switch_engaged`'s pattern one level down: a
    global kill switch blocks every market; this reads which
    individual markets (lower-case, comparable against
    ``Core.market_config.current_market()``) are halted while the
    global switch stays off.

    Env var: ``MARKET_KILL_SWITCH_MARKETS`` (comma-separated market
    identifiers, e.g. ``"idx,us"``; default empty string -- no market
    halted). Each entry is stripped and lower-cased; empty entries
    (e.g. from a trailing comma) are dropped.
    """
    raw = config.get_str("MARKET_KILL_SWITCH_MARKETS", "") or ""
    return frozenset(market.strip().lower() for market in raw.split(",") if market.strip())


def _halted_symbols() -> frozenset[str]:
    """Read the Activation 8.4 symbol kill-switch set from ``Core.config``.

    Mirrors :func:`_halted_markets`'s pattern exactly, one level
    narrower (a single symbol instead of an entire market).

    Env var: ``SYMBOL_KILL_SWITCH_SYMBOLS`` (comma-separated symbols,
    e.g. ``"BBCA,TLKM"``; default empty string -- no symbol halted).
    Each entry is stripped and upper-cased (mirrors
    ``PaperTradingEngine``'s own case-insensitive comparison for this
    gate); empty entries are dropped.
    """
    raw = config.get_str("SYMBOL_KILL_SWITCH_SYMBOLS", "") or ""
    return frozenset(symbol.strip().upper() for symbol in raw.split(",") if symbol.strip())


def _max_daily_loss() -> float | None:
    """Read the Activation 8.4 daily-loss ceiling from ``Core.config``.

    Env var: ``RISK_MAX_DAILY_LOSS`` (float, account-currency units,
    unset/empty by default -- no ceiling configured, the gate never
    rejects). Unlike :func:`_max_order_value`, this has no numeric
    default: a risk ceiling that silently activates at some guessed
    number the operator never chose would be worse than no ceiling at
    all, so this stays ``None`` (gate disabled) until an operator sets
    it explicitly.
    """
    raw = config.get_str("RISK_MAX_DAILY_LOSS", None)
    if raw is None or not raw.strip():
        return None
    return config.get_float("RISK_MAX_DAILY_LOSS", 0.0)


def _max_position_value() -> float | None:
    """Read the Activation 8.4 max-position-value ceiling from
    ``Core.config``.

    Mirrors :func:`_max_daily_loss`'s "no silent numeric default"
    reasoning exactly.

    Env var: ``RISK_MAX_POSITION_VALUE`` (float, account-currency
    units, unset/empty by default -- no ceiling configured, the gate
    never rejects).
    """
    raw = config.get_str("RISK_MAX_POSITION_VALUE", None)
    if raw is None or not raw.strip():
        return None
    return config.get_float("RISK_MAX_POSITION_VALUE", 0.0)


def _build_paper_trading_engine(
    order_lifecycle_service: OrderLifecycleService,
    execution_service: ExecutionService,
    account_repository: AccountRepository,
    position_repository: PositionRepository,
    order_idempotency_repository: OrderIdempotencyRepository,
    execution_policy: ExecutionPolicy,
    account_balance_service: AccountBalanceService,
    position_manager: PositionManager,
    notification_manager: NotificationManager,
    notification_builder: NotificationBuilder,
    order_approval_repository: OrderApprovalRepository,
) -> PaperTradingEngine:
    """Construct the Sprint 4 STEP 9 ``PaperTradingEngine`` (extended by
    Activation 3.2, Activation 3.3 STEP 2, and Activation 3.5 STEP 1)
    over this graph's ``order_lifecycle_service``/``execution_service``/
    ``account_repository``/``position_repository``/
    ``order_idempotency_repository``, plus the two Activation 3.2 config
    values read live from ``Core.config`` at build time.

    ``account_balance_service`` (Activation 3.5 STEP 1): the same
    ``AccountBalanceService`` instance built once by
    :func:`_build_account_balance_service` -- never a second,
    independently-constructed one. Wiring this in is this STEP's whole
    job: previously ``account_balance_service`` was built and exposed
    on ``ApplicationGraph`` but had no production consumer at all; this
    is that first consumer, so a filled ``Trade`` now updates its
    ``Account``'s cash through the same graph-shared repository every
    other ``graph.<service>`` call already reads/writes through.

    ``position_manager`` (Activation 3.5 STEP 2): the same
    ``PositionManager`` instance built once by
    :func:`_build_position_manager` -- never a second,
    independently-constructed one. This is that instance's first
    production consumer, mirroring ``account_balance_service`` above:
    a filled ``Trade`` now also updates its ``Position`` (open/merge on
    BUY, reduce/close/oversell-guard on SELL) through the same
    graph-shared ``position_repository`` every other
    ``graph.<service>`` call already reads/writes through.

    Purely wiring, same construct-only boundary every ``_build_*``
    function in this module already draws:
    ``PaperTradingEngine.__init__`` only stores its collaborators by
    reference -- it opens no connection and issues no SQL statement
    itself (any I/O it triggers only happens on a later, explicit
    ``submit_order()`` call). This function's entire job is to make
    sure every Repository/Service reference is the *same* instance
    ``build_application`` already built once (never a second one), so
    any later call through this graph's ``paper_trading_engine``
    observes/persists against the same ``accounts``/``positions``/
    ``orders``/``trades``/``order_idempotency_keys`` table state as a
    direct ``graph.<repository>``/``graph.<service>`` call would.

    ``kill_switch_engaged``/``max_order_value`` are read once, here, at
    graph-build time (see :func:`_kill_switch_engaged`/
    :func:`_max_order_value`) -- not re-read live on every
    ``submit_order()`` call, matching this codebase's existing
    construct-once wiring style (``Core.approval_config.
    build_approval_port`` is read the same way, once, by
    ``build_application``).

    ``execution_policy`` (Activation 3.3): the same ``ExecutionPolicy``
    instance built once by :func:`_build_execution_policy` and also
    passed to :func:`_build_execution_service` -- never a second,
    independently-loaded policy. Used by this engine's "IDX lot size
    valid" pre-trade gate.

    ``notification_manager``/``notification_builder`` (Activation 6.3):
    the same ``NotificationManager``/``NotificationBuilder`` instances
    built once by :func:`_build_notification_manager`/
    :func:`_build_notification_builder` -- never second,
    independently-constructed ones. Wiring these in is this
    Activation's whole job: previously this function did not accept
    either, so ``PaperTradingEngine`` fell back to its own inert
    defaults (a ``NotificationBuilder()`` and a ``NotificationManager``
    wrapping a channel-less ``NotificationDispatcher``) and no
    ``ORDER_EXECUTED`` notification ever reached the real Telegram
    channel. Passing this graph's already-built instances through
    means ``paper_trading_engine`` now notifies over the same
    notification chain (``notification_builder`` ->
    ``notification_manager`` -> ``notification_dispatcher`` ->
    ``telegram_notification_channel`` -> ``notification_service``)
    every other ``graph.notification_*`` reference already shares --
    never a second chain.

    ``order_approval_repository`` (Activation 7 Blocker #4): the same
    ``OrderApprovalRepository`` instance built once by
    :func:`_build_order_approval_repository` -- never a second,
    independently-constructed one. Wiring this in is this Blocker's
    whole job: ``submit_order()`` now writes one best-effort audit row
    per successful trade so the ``user_approval`` gate 3 already
    required is durably recorded and queryable -- gate 3 itself, the
    required call order above, and the transaction boundary are all
    unchanged.

    ``halted_markets``/``halted_symbols``/``max_daily_loss``/
    ``max_position_value`` (Activation 8.4): read once, here, at
    graph-build time from ``Core.config`` (see
    :func:`_halted_markets`/:func:`_halted_symbols`/
    :func:`_max_daily_loss`/:func:`_max_position_value`), identical
    construct-once pattern to ``kill_switch_engaged``/
    ``max_order_value`` above. All four default to "no restriction"
    (empty set / ``None``) when unset, so this function's behaviour
    for any deployment that has not set the new env vars is unchanged.

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    """
    return PaperTradingEngine(
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_repository=account_repository,
        position_repository=position_repository,
        order_idempotency_repository=order_idempotency_repository,
        kill_switch_engaged=_kill_switch_engaged(),
        max_order_value=_max_order_value(),
        execution_policy=execution_policy,
        account_balance_service=account_balance_service,
        position_manager=position_manager,
        notification_manager=notification_manager,
        notification_builder=notification_builder,
        order_approval_repository=order_approval_repository,
        halted_markets=_halted_markets(),
        halted_symbols=_halted_symbols(),
        max_daily_loss=_max_daily_loss(),
        max_position_value=_max_position_value(),
    )


def _build_manual_scan_service(
    watchlist_repository: WatchlistRepository,
    market_analysis_agent: MarketAnalysisAgent,
    snapshot_repository: SnapshotRepository,
) -> ManualScanService:
    """Construct the Sprint 5 STEP 6 ``ManualScanService`` over this
    graph's ``watchlist_repository``/``market_analysis_agent``/
    ``snapshot_repository``.

    Purely wiring, same construct-only boundary every ``_build_*``
    function in this module already draws: builds a fresh
    ``WatchlistScanner`` over the two shared collaborators passed in
    (never a second ``WatchlistRepository``/``MarketAnalysisAgent``
    instance -- the exact same identity requirement
    :func:`_build_execution_service` etc. already establish for their
    own Repository arguments), plus a fresh ``RankingEngine``/
    ``RecommendationService``/``ReportService`` -- each of those three
    takes no constructor dependency of its own (LOCKED DECISION on
    each of their own modules), so there is no prior singleton to
    share for them, unlike the Repository-backed collaborators.
    ``ManualScanService.__init__`` itself only stores all five
    collaborators by reference -- it opens no connection and issues no
    SQL statement (any I/O it triggers only happens on a later,
    explicit ``run_scan()`` call).

    Not yet passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent`` -- this stage is graph-visibility only.
    No CLI/scheduler/export/Telegram/Discord integration exists yet to
    consume it; a future STEP wires that caller.
    """
    watchlist_scanner = WatchlistScanner(watchlist_repository, market_analysis_agent)
    ranking_engine = RankingEngine()
    recommendation_service = RecommendationService()
    report_service = ReportService()
    return ManualScanService(
        watchlist_scanner,
        ranking_engine,
        recommendation_service,
        report_service,
        snapshot_repository,
    )


def _build_daily_report_orchestrator(
    manual_scan_service: ManualScanService,
    performance_summary_production_service: PerformanceSummaryProductionService,
    notification_builder: NotificationBuilder,
    notification_manager: NotificationManager,
) -> DailyReportOrchestrator:
    """Construct the Activation 6.4 ``DailyReportOrchestrator`` over
    this graph's ``manual_scan_service``/
    ``performance_summary_production_service``/``notification_builder``/
    ``notification_manager``.

    Purely wiring, same construct-only boundary every ``_build_*``
    function in this module already draws:
    ``DailyReportOrchestrator.__init__`` only stores its four
    collaborators by reference -- it opens no connection, sends no
    notification, and issues no SQL statement itself (any I/O it
    triggers only happens on a later, explicit ``run_daily_report()``
    call). This function's entire job is to make sure every reference
    is the *same* instance ``build_application`` already built once
    (never a second one), so a later call through this graph's
    ``daily_report_orchestrator`` observes/persists/sends through the
    exact same collaborators any direct ``graph.manual_scan_service``/
    ``graph.performance_summary_production_service``/
    ``graph.notification_builder``/``graph.notification_manager`` call
    would.

    Must run after all four arguments are already built --
    ``manual_scan_service`` and ``performance_summary_production_service``
    in particular are constructed late in ``build_application()``
    (the latter depends on ``portfolio_snapshot_service``, itself
    built near the very end), so this orchestrator is necessarily
    constructed after them.

    Not passed into ``agent``, ``runtime_analysis_pipeline``, or
    ``trading_decision_agent``, and not registered as a Tool -- the
    only production caller is the ``report daily`` CLI command
    (``main.py``).
    """
    return DailyReportOrchestrator(
        manual_scan_service=manual_scan_service,
        performance_summary_production_service=performance_summary_production_service,
        notification_builder=notification_builder,
        notification_manager=notification_manager,
    )


def _build_runtime_analysis_pipeline(
    executor: Executor,
    analysis_pipeline: AnalysisPipeline,
    tool_context_builder: ToolContextBuilder,
    memory_recorder: MemoryRecorder,
    memory_store: MemoryStore,
    reflector: Reflector,
    decision_engine: DecisionEngine,
    decision_policy: DecisionPolicy,
    policy_guard: PolicyGuard,
    execution_intent: ExecutionIntent,
    execution_planner: ExecutionPlanner,
    execution_coordinator: ExecutionCoordinator,
    portfolio_engine: PortfolioEngine,
    portfolio_risk: PortfolioRisk,
    learning_loop: LearningLoop,
    vision_pipeline: VisionMarketStatePipeline,
    trading_decision_agent: TradingDecisionAgent,
) -> RuntimeAnalysisPipeline:
    """Construct the Stage L11 Runtime-kernel facade over the same
    ``analysis_pipeline``/``tool_context_builder`` this graph already
    builds, sharing the process-wide ``tool_registry`` singleton
    ``executor`` itself was constructed with (required -- see
    :class:`~Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline`
    docstring on ``tool_registry``).

    Integration Sprint 1 addition: also passes through the already-built
    ``memory_recorder``/``memory_store``/``reflector``/``decision_engine``
    (Task 1A / Stage L18 / Stage L19 -- none constructed a second time
    here), so every ``run()`` call now also records an ``Observation``,
    reflects over stored history, and runs ``DecisionEngine`` on the
    result. This is the one and only place in the production graph that
    activates that path -- ``RuntimeAnalysisPipeline`` itself still
    supports running without it (all four arguments optional, defaulting
    to ``None``, which is what every existing test construction of
    ``RuntimeAnalysisPipeline`` across the test suite relies on
    unmodified).

    Integration Sprint 2 addition: also passes through the already-built
    ``decision_policy`` (Stage L20B -- not constructed a second time
    here), so every ``run()`` call now also passes the real ``Decision``
    DecisionEngine produced straight into ``decision_policy.apply()``.

    Integration Sprint 3 addition: also passes through the already-built
    ``policy_guard`` (Stage L21 -- not constructed a second time here),
    so every ``run()`` call now also passes the real
    ``DecisionPolicyResult`` DecisionPolicy produced straight into
    ``policy_guard.evaluate()``.

    Integration Sprint 4 addition: also passes through the already-built
    ``execution_intent`` (Stage L22 -- not constructed a second time
    here), so every ``run()`` call now also passes the real
    ``PolicyGuardResult`` PolicyGuard produced straight into
    ``execution_intent.build()``.

    Integration Sprint 5 addition: also passes through the already-built
    ``execution_planner`` (Stage L23 -- not constructed a second time
    here), so every ``run()`` call now also passes the real
    ``ExecutionIntentResult`` ExecutionIntent produced straight into
    ``execution_planner.plan()``.

    Integration Sprint 6 addition: also passes through the already-built
    ``execution_coordinator`` (Stage L24 -- not constructed a second
    time here), so every ``run()`` call now also passes the real
    ``ExecutionPlan`` ExecutionPlanner produced straight into
    ``execution_coordinator.coordinate()``. Stops at
    ``ExecutionCoordinatorResult`` -- PortfolioEngine and beyond remain
    unwired.

    Integration Sprint 7 addition: also passes through the already-built
    ``portfolio_engine`` (Stage L25 -- not constructed a second time
    here), so every ``run()`` call now also passes the real
    ``ExecutionCoordinatorResult`` ExecutionCoordinator produced straight
    into ``portfolio_engine.evaluate()``. Stops at
    ``PortfolioEngineResult`` -- PortfolioRisk and beyond remain unwired.

    Integration Sprint 8 addition: also passes through the already-built
    ``portfolio_risk`` (Stage L26 -- not constructed a second time
    here), so every ``run()`` call now also passes the real
    ``PortfolioEngineResult`` PortfolioEngine produced straight into
    ``portfolio_risk.assess()``. Stops at ``PortfolioRiskResult`` --
    LearningLoop and beyond remain unwired.

    Integration Sprint 9 addition: also passes through the already-built
    ``learning_loop`` (Stage L27 -- not constructed a second time here),
    so every ``run()`` call now also passes the real
    ``PortfolioRiskResult`` PortfolioRisk produced straight into
    ``learning_loop.learn()``. Stops at ``LearningLoopResult`` --
    AutonomousAgent remains unwired.

    Sprint 152 addition: also passes through the already-built
    ``trading_decision_agent`` (not constructed a second time), so
    every ``run()`` call that produces a real vision ``market_state``
    also bridges it into ``TradingDecisionAgent.execute()``. Stops at
    the six-Skill result dict, attached as ``AnalysisResult
    .trading_decision`` -- nothing past that point is wired.

    Purely additive: constructs a new object, does not modify
    ``executor``, ``analysis_pipeline``, ``tool_context_builder``,
    ``memory_recorder``, ``memory_store``, ``reflector``,
    ``decision_engine``, ``decision_policy``, ``policy_guard``,
    ``execution_intent``, ``execution_planner``,
    ``execution_coordinator``, ``portfolio_engine``, ``portfolio_risk``,
    ``learning_loop``, or ``trading_decision_agent``.
    """
    return RuntimeAnalysisPipeline(
        executor=executor,
        analysis_pipeline=analysis_pipeline,
        tool_context_builder=tool_context_builder,
        tool_registry=tool_registry,
        memory_recorder=memory_recorder,
        memory_store=memory_store,
        reflector=reflector,
        decision_engine=decision_engine,
        decision_policy=decision_policy,
        policy_guard=policy_guard,
        execution_intent=execution_intent,
        execution_planner=execution_planner,
        execution_coordinator=execution_coordinator,
        portfolio_engine=portfolio_engine,
        portfolio_risk=portfolio_risk,
        learning_loop=learning_loop,
        vision_pipeline=vision_pipeline,
        trading_decision_agent=trading_decision_agent,
    )


def _build_vision_market_state_pipeline(
    gemini_vision_provider: GeminiVisionProvider,
) -> VisionMarketStatePipeline:
    """Construct the Sprint 151 ``VisionMarketStatePipeline`` over the
    already-built ``gemini_vision_provider``.

    Purely wiring, same additive pattern as the other ``_build_*``
    helpers in this module: constructs one new object, reusing a
    collaborator already built elsewhere. Introduces no new Skill and
    duplicates no existing Skill's logic -- see
    ``Orchestration.vision_market_state_pipeline`` module docstring.
    """
    return VisionMarketStatePipeline(vision_provider=gemini_vision_provider)


def _build_trading_decision_agent(tool_resolver: ToolResolver) -> TradingDecisionAgent:
    """Construct the Sprint 152 production ``TradingDecisionAgent`` over
    its fourteen already-existing, unmodified constituent Skills
    (Sprint 154 extended the chain from six to fourteen Skills).

    Purely wiring, same additive pattern as
    :func:`_build_vision_market_state_pipeline`: constructs the
    fourteen Skill instances ``TradingDecisionAgent.__init__`` now
    expects (each takes no constructor arguments of its own -- see
    each Skill's own module) and hands them to ``TradingDecisionAgent``
    in its fixed, documented pipeline order. Introduces no new Skill,
    no new Agent, and duplicates no existing Skill's logic -- see
    ``Orchestration.trading_decision_agent`` module docstring.

    Sprint 158 addition (additive only, ToolResolver bridge): before
    ``MarketAnalysisSkill`` is handed to ``TradingDecisionAgent``, this
    function injects ``_resolve_tool`` onto it -- the same
    Executor-shaped attribute assignment already exercised by
    ``Tests/test_stage_l123_trading_decision_agent.py``'s
    ``_real_agent()`` helper.

    Activation 2.2 change: the ``ToolResolver`` is now supplied by the
    caller (``build_application()``, via :func:`_build_market_tool_resolver`)
    rather than built inline here as a private local. This is the same
    single production ``ToolResolver`` -- over the same single
    ``Orchestration.tool_registry.ToolRegistry`` instance, registered
    with the same three unmodified ``Market*Tool`` classes -- that
    :func:`_build_market_analysis_agent` now also uses for its own
    ``MarketAnalysisSkill``. No second ``ToolRegistry``/``ToolResolver``
    is built anywhere in the graph. No new class, wrapper, or adapter
    is introduced -- only existing production objects are constructed
    once and connected.
    """
    market_analysis_skill = MarketAnalysisSkill()
    market_analysis_skill._resolve_tool = tool_resolver.resolve

    return TradingDecisionAgent(
        market_analysis_skill,
        RecommendationSkill(),
        PositionRiskSkill(),
        TradePlanSkill(),
        PositionSizingSkill(),
        CapitalAllocationSkill(),
        OrderValidationSkill(),
        PaperTradingSkill(),
        TradeHistorySkill(),
        PortfolioUpdateSkill(),
        PortfolioMonitorSkill(),
        PortfolioPerformanceSkill(),
        PortfolioAlertSkill(),
        PortfolioReportSkill(),
    )


def _build_analysis_pipeline() -> AnalysisPipeline:
    """Construct the 11-service ``AnalysisPipeline`` in full production
    mode -- every service left at its default (``None``) external-module
    override, exactly the production path each service's own docstring
    describes. No call here imports ``yfinance`` or ``plotly``.

    Each service is additionally registered into the shared
    ``ServiceRegistry`` singleton via its existing public ``register()``
    API, under its own ``BaseService.name``, guarded by ``exists()`` for
    the same re-entrancy reason as ``_build_provider``.
    ``AnalysisPipeline`` itself does not read from ``ServiceRegistry`` --
    it takes services directly, unchanged -- this registration exists
    only so ``ServiceRegistry`` (an existing singleton the framework
    already defines) reflects what the running application actually has.

    Task 1B addition (additive only, Repository DI bypass fix): also
    constructs ``StockDataRepository``/``NewsRepository`` centrally here
    and injects each into its owning Service via the new
    ``stock_repository``/``news_repository`` constructor seams, instead
    of letting ``StockService``/``NewsService`` self-construct their
    repository internally. Neither repository imports ``yfinance`` or
    opens a connection at construction time (same construct-only
    boundary every other repository/provider in this module already
    draws), so this remains a hermetic, no-I/O function.
    """
    stock_repository = StockDataRepository()
    news_repository = NewsRepository()

    services = (
        StockService(stock_repository=stock_repository),
        TechnicalIndicatorService(),
        MovingAverageService(),
        TechnicalScoreService(),
        FundamentalService(),
        PatternService(),
        ChartService(),
        NewsService(news_repository=news_repository),
        BacktestService(),
        RiskManagementService(),
        ScoringService(),
    )
    for service in services:
        if not service_registry.exists(service.name):
            service_registry.register(service)

    (
        stock_service,
        technical_indicator_service,
        moving_average_service,
        technical_score_service,
        fundamental_service,
        pattern_service,
        chart_service,
        news_service,
        backtest_service,
        risk_management_service,
        scoring_service,
    ) = services

    return AnalysisPipeline(
        stock_service=stock_service,
        technical_indicator_service=technical_indicator_service,
        moving_average_service=moving_average_service,
        technical_score_service=technical_score_service,
        fundamental_service=fundamental_service,
        pattern_service=pattern_service,
        chart_service=chart_service,
        news_service=news_service,
        backtest_service=backtest_service,
        risk_management_service=risk_management_service,
        scoring_service=scoring_service,
    )


def _build_notification_service() -> NotificationService:
    """Construct ``NotificationService`` and register it into the shared
    ``ServiceRegistry`` (Task 3, "Second Skill / Cross-Skill Reflection
    Foundation").

    ``NotificationService`` is not one of the 11 fixed
    ``AnalysisPipeline`` steps -- it has no place in that chain and is
    never passed to :func:`_build_analysis_pipeline`'s ``AnalysisPipeline``
    constructor. It is registered here, separately, purely so
    ``ServiceRegistry`` (and therefore :func:`_build_service_skills`,
    unmodified) picks it up as a 12th, independent Service -- the same
    "register under its own name, guard with ``exists()``" pattern
    :func:`_build_analysis_pipeline` already uses for the 11 pipeline
    services, just for one Service outside that pipeline.

    No collaborator is required: ``NotificationService()`` with no
    ``http_client`` override is the same production shape
    ``_build_analysis_pipeline`` uses for every other service that takes
    an optional external-module/client override (e.g. ``StockService``
    is given a real ``StockDataRepository``; here there is nothing to
    inject at construction time -- ``NotificationService`` lazily
    resolves ``requests`` only inside ``execute()``/``health_check()``,
    never here). Constructing it performs no I/O.

    Does not touch ``AnalysisPipeline``, ``StockAgent``, or
    ``RuntimeAnalysisPipeline`` in any way -- this function's only
    effect is one additional entry in ``ServiceRegistry``.
    """
    notification_service = NotificationService()
    if not service_registry.exists(notification_service.name):
        service_registry.register(notification_service)
    return notification_service


#: Fixed ``ServiceContext.agent_name`` the notification wiring below
#: always supplies. Sprint 7 STEP 7 is wiring-only -- no real
#: agent/provider/user turn is associated with a notification send, so
#: this is a stable, self-describing label rather than
#: ``DEFAULT_AGENT_NAME`` (which identifies the production
#: ``StockAgent`` turn, a different concern).
_NOTIFICATION_AGENT_NAME = "notification_system"


#: Environment variable names read for the Telegram credentials this
#: factory injects. These are the exact two names ``Core.doctor.
#: _check_telegram()`` already checks for (see that function's own
#: docstring/comment) -- Activation 6.1 is what turns that
#: previously-unconfirmed naming convention into the one, real
#: production call site that actually reads them via ``Core.config``.
_TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


def _notification_service_context_factory(metadata: Dict[str, object]) -> ServiceContext:
    """The ``service_context_factory`` injected into
    ``TelegramNotificationChannel`` (Sprint 7 STEP 4, LOCKED
    constructor).

    ``TelegramNotificationChannel.send()`` calls this with exactly one
    keyword argument, ``metadata`` (already containing
    ``channel="telegram"`` and ``message=event.message`` -- see that
    module's own ``send()`` docstring). This function fills in the
    remaining ``ServiceContext`` fields that adapter itself has no
    opinion on (``agent_name``/``provider_name``/``request_id``/
    ``user_input``).

    Activation 6.1: this function is also the sole production call
    site that supplies the Telegram credentials
    ``NotificationService.execute()`` requires
    (``MetadataKeys.TELEGRAM_BOT_TOKEN`` / ``.TELEGRAM_CHAT_ID``).
    They are read from the shared ``Core.config.config`` singleton --
    i.e. the ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` environment
    (or ``.env``) variables -- never hard-coded and never accepted as
    a parameter here. A copy of ``metadata`` is built so the caller's
    own dict is never mutated; any key the caller already supplied
    (e.g. a future caller adding ``title``) is left untouched -- this
    function only *adds* the two credential keys, and only when they
    are not already present.

    If a credential is not configured, it is simply left out of
    ``metadata`` rather than defaulted to a placeholder:
    ``NotificationService.execute()``'s own existing
    ``_require_credential`` check then raises a
    ``NotificationServiceError`` (surfaced as a failed
    ``ServiceResult``) -- an explicit failure, never a silent success.
    This function does not duplicate that validation itself.

    Mirrors the same defaulting convention
    ``Orchestration.service_skill.ServiceSkill.execute()`` already uses
    for the four base fields: a fixed ``agent_name`` label, an empty
    ``provider_name`` (no LLM provider is involved in sending a
    notification), a freshly minted ``uuid4`` ``request_id`` per call
    (so every send is still individually traceable), and an empty
    ``user_input`` (no end-user turn triggered this send).

    Does not call ``notification_service.execute()``,
    ``notification_manager.notify()``, ``notification_dispatcher.
    dispatch()``, or ``telegram_notification_channel.send()`` itself --
    purely a value-object constructor, same as every other
    ``_build_*``/factory function in this module. Does not touch
    ``NotificationEvent``, ``TelegramNotificationChannel``,
    ``NotificationDispatcher``, or ``NotificationManager`` -- no
    event/trigger behavior changes.
    """
    resolved_metadata: Dict[str, object] = dict(metadata)

    bot_token = config.get_str(_TELEGRAM_BOT_TOKEN_ENV)
    if bot_token and MetadataKeys.TELEGRAM_BOT_TOKEN not in resolved_metadata:
        resolved_metadata[MetadataKeys.TELEGRAM_BOT_TOKEN] = bot_token

    chat_id = config.get_str(_TELEGRAM_CHAT_ID_ENV)
    if chat_id and MetadataKeys.TELEGRAM_CHAT_ID not in resolved_metadata:
        resolved_metadata[MetadataKeys.TELEGRAM_CHAT_ID] = chat_id

    return ServiceContext(
        agent_name=_NOTIFICATION_AGENT_NAME,
        provider_name="",
        request_id=str(uuid.uuid4()),
        user_input="",
        metadata=resolved_metadata,
    )


def _build_notification_builder() -> NotificationBuilder:
    """Construct the Sprint 7 STEP 2 ``NotificationBuilder``.

    Purely wiring: ``NotificationBuilder()`` takes no dependency
    whatsoever (LOCKED, unchanged) -- this function exists only so
    :func:`build_application` has a single, consistent construction
    point for it, same as every other ``_build_*`` function here.
    Constructing it performs no I/O and sends nothing.
    """
    return NotificationBuilder()


def _build_telegram_notification_channel(
    notification_service: NotificationService,
) -> TelegramNotificationChannel:
    """Construct the Sprint 7 STEP 4 ``TelegramNotificationChannel``
    over this graph's existing ``notification_service``.

    ``notification_service`` must be the exact same instance
    :func:`_build_notification_service` already built and registered
    into ``service_registry`` -- never a second
    ``NotificationService()`` -- so any later send observes/uses the
    same (lazily-resolved) credentials/config that instance already
    carries. The second constructor dependency,
    ``service_context_factory``, is
    :func:`_notification_service_context_factory` above -- a plain
    function reference, not called here. Constructing this adapter
    performs no I/O and sends nothing (``send()`` is never called by
    this function).
    """
    return TelegramNotificationChannel(
        notification_service=notification_service,
        service_context_factory=_notification_service_context_factory,
    )


def _build_notification_dispatcher(
    telegram_notification_channel: TelegramNotificationChannel,
) -> NotificationDispatcher:
    """Construct the Sprint 7 STEP 3 ``NotificationDispatcher`` with
    exactly one channel: this graph's
    ``telegram_notification_channel`` (LOCKED DECISION 5 -- no
    Discord, no email channel added). ``channels=[telegram_notification_
    channel]`` is a fresh list literal wrapping that exact same adapter
    instance, never a copy of the adapter itself. Constructing the
    dispatcher performs no I/O and sends nothing (``dispatch()`` is
    never called by this function).
    """
    return NotificationDispatcher(channels=[telegram_notification_channel])


def _build_notification_manager(
    notification_dispatcher: NotificationDispatcher,
) -> NotificationManager:
    """Construct the Sprint 7 STEP 5 ``NotificationManager`` over this
    graph's ``notification_dispatcher`` (LOCKED DECISION 6 -- the
    dispatcher is its only dependency). Constructing it performs no
    I/O and sends nothing (``notify()`` is never called by this
    function).
    """
    return NotificationManager(notification_dispatcher)


def _build_service_skills(permission_context: PermissionContext) -> Dict[str, ServiceSkill]:
    """Wrap every Service already held by ``ServiceRegistry`` in a Stage
    L13 :class:`~Orchestration.service_skill.ServiceSkill` and register
    each as a standing Tool under a stable name (``"skill.<service_name>"``).

    Purely wiring: this function does not construct a single new Service
    instance, does not declare any ``SkillMetadata`` (that lives entirely
    in :data:`Orchestration.service_skill.SKILL_METADATA_BY_SERVICE`,
    imported here as-is), and does not touch ``AnalysisPipeline``,
    ``StockAgent``, or ``RuntimeAnalysisPipeline`` in any way. Must run
    after :func:`_build_analysis_pipeline`, which is what actually
    populates ``ServiceRegistry`` with the 11 production Service
    instances this function wraps.

    Reviewer note (Diff-Level Plan FINAL, approval note #1 -- ToolRegistry
    guard must not hide a real wiring bug): the ``tool_registry.exists()``
    guard below only ever shields the same re-entrancy case every other
    guard in this module already shields -- calling
    :func:`build_application` more than once in the same process. It
    cannot mask a genuine same-pass collision, because collisions are
    structurally impossible here: ``ServiceRegistry.register`` itself
    already raises ``ServiceAlreadyRegisteredError`` for a duplicate
    ``service.name`` (unchanged, see ``Services/service_registry.py``),
    so ``service_registry.list()`` yields at most one entry per
    ``service.name``, and ``ServiceSkill.tool_name`` is a pure 1:1
    function of ``service.name`` -- so two distinct Tool names can never
    resolve to the same string within a single call of this function. A
    real duplicate-Tool-name bug elsewhere in the graph (e.g. a name
    collision with some other, non-skill Tool) still surfaces immediately
    via ``ToolRegistry.register``'s own, unmodified
    ``ToolAlreadyRegisteredError`` -- nothing here catches or suppresses
    that.

    A Service present in ``ServiceRegistry`` without a matching entry in
    ``SKILL_METADATA_BY_SERVICE`` is skipped rather than wrapped -- at
    the L13 baseline this covered exactly the 11 Services
    ``_build_analysis_pipeline`` registers (``NotificationService`` was
    unregistered/unwired at that point, per ``Services/metadata_keys.py``).
    Task 3 registers ``NotificationService`` too (see
    ``_build_notification_service``) and gives it its own
    ``SKILL_METADATA_BY_SERVICE`` entry, so it is now wrapped here as a
    12th, independent ``ServiceSkill`` -- this function itself is
    unmodified; the branch below is left in place, explicit and
    documented, for any future Service added to the registry ahead of
    its own metadata audit.

    Activation 12.6: ``permission_context`` is no longer constructed
    here -- it is injected by the caller (``build_application()``),
    the exact same instance passed into
    :func:`_build_market_tool_resolver`. See that function and
    ``build_application()`` for the single construction site.

    Activation 12.5: each of the 12 ``skill.<service_name>`` Tools
    registered below now runs through an
    ``Orchestration.agents_tool_permission_adapter.
    AgentsToolPermissionAdapter`` instead of ``skill.execute`` directly,
    closing the real production permission bypass on this legacy
    ``Agents.tool_registry`` path (Core.composition_root._build_service_
    skills() -> Agents.tool_registry singleton -> Agents.Executor ->
    Agents.sandbox.GenericSandbox.execute() -> raw Tool.handler(...),
    see Activation 12.5 audit). Every one of the 12 ``ServiceSkill``
    instances built here is undeclared (no ``.permission`` attribute),
    so ``Orchestration.tool_permission_enforcer.permission_for_tool()``
    defaults each to ``ToolPermission.READ_ONLY`` -- the same
    "undeclared tool defaults to READ_ONLY" semantics
    ``_build_market_tool_resolver()`` already relies on for the three
    ``Market*Tool`` instances it wraps in ``PermissionedTool`` -- so
    this wrapping is a safety-boundary addition only, with no behavior
    change to these 12 read/analysis-only Services today.
    ``Agents.tool_registry.Tool``/``ToolRegistry``,
    ``Agents.executor.Executor``, and ``Agents.sandbox.GenericSandbox``
    are all unmodified: the adapter is a plain
    ``Callable[..., Any]`` plugged in as ``Tool.handler``, the exact
    shape that call site already expects.

    Returns:
        Dict mapping each wrapped Service's ``name`` to its
        :class:`~Orchestration.service_skill.ServiceSkill`.
    """
    skills: Dict[str, ServiceSkill] = {}
    # Activation 12.6: ``permission_context`` is the caller-injected
    # parameter above -- the same single instance
    # ``build_application()`` constructs and also passes into
    # ``_build_market_tool_resolver()``. Never a second, independently
    # constructed instance. Safe (fail-closed) defaults only; no CLI
    # flag or environment-variable toggle is introduced here.
    for service in service_registry.list():
        metadata = SKILL_METADATA_BY_SERVICE.get(service.name)
        if metadata is None:
            continue
        skill = ServiceSkill(service=service, metadata=metadata)
        skills[service.name] = skill
        if not tool_registry.exists(skill.tool_name):
            tool_registry.register(
                Tool(
                    name=skill.tool_name,
                    description=(
                        f"Stage L13 granular skill: runs Service "
                        f"'{service.name}' directly and standalone, "
                        "outside the fixed 11-step AnalysisPipeline "
                        "chain. Not called by the production StockAgent "
                        "path -- reachable only for a future caller "
                        "(e.g. a Planner) that constructs its own "
                        "ServiceContext.metadata for this one Service."
                    ),
                    handler=AgentsToolPermissionAdapter(
                        wrapped_tool=skill,
                        handler=skill.execute,
                        permission_context=permission_context,
                    ),
                )
            )
    return skills


def _build_goal_planner(service_skills: Dict[str, ServiceSkill]) -> GoalPlanner:
    """Construct the Stage L15 Phase 1 :class:`~Orchestration.planner.GoalPlanner`
    over the ``service_skills`` mapping this graph already built.

    Purely wiring, same additive pattern as
    :func:`_build_runtime_analysis_pipeline` (L11) and
    :func:`_build_service_skills` (L13): constructs one new object,
    reusing collaborators already built elsewhere -- does not construct a
    single new ``ServiceSkill`` (``service_skills`` is passed straight
    through to ``GoalPlanner.__init__``, unchanged), and does not touch
    ``AnalysisPipeline``, ``StockAgent``, ``RuntimeAnalysisPipeline``,
    ``Runtime``, ``Executor``, ``Sandbox``, ``ToolRegistry``, or
    ``ServiceRegistry`` in any way. Must run after
    :func:`_build_service_skills`, which is what actually builds the
    mapping this wraps.

    Args:
        service_skills: The already-built ``Dict[str, ServiceSkill]``
            (see :func:`_build_service_skills`) -- the same instance is
            handed to ``GoalPlanner``, never rebuilt or copied here.

    Returns:
        A new :class:`~Orchestration.planner.GoalPlanner` wrapping
        ``service_skills``.
    """
    return GoalPlanner(service_skills=service_skills)


def _build_observation_recorder() -> ObservationRecorder:
    """Construct the Stage L16 :class:`~Orchestration.observation.ObservationRecorder`
    (Task 1A addition, additive only, construction-only scope).

    No collaborators -- ``ObservationRecorder`` takes no constructor
    arguments (see its own docstring). Not called by anything in this
    module beyond this constructor; nothing in ``build_application``
    invokes ``.record(...)`` on the returned instance.
    """
    return ObservationRecorder()


def _build_memory_store() -> MemoryStore:
    """Construct the Stage L17 :class:`~Orchestration.memory.MemoryStore`
    (Task 1A addition, construction-only; lifetime and retention
    resolved by Task 2).

    No required collaborators. Constructed fresh on every
    :func:`build_application` call, same as ``database_manager`` -- this
    is Task 2's final decision, not a placeholder: ``MemoryStore`` is
    not a process-wide singleton. Called with no arguments here, so the
    optional retention policy Task 2 added to ``MemoryStore``
    (``max_size``/``ttl_seconds``) stays disabled on the production
    graph -- identical to this store's behavior before that policy
    existed. A future caller wanting bounded retention on the
    production graph would pass those arguments explicitly here; doing
    so is not part of this stage.
    """
    return MemoryStore()


def _build_memory_recorder(memory_store: MemoryStore) -> MemoryRecorder:
    """Construct the Stage L17 :class:`~Orchestration.memory.MemoryRecorder`
    (Task 1A addition, additive only, construction-only scope), wrapping
    the ``memory_store`` this graph already built.

    Must run after :func:`_build_memory_store`, which is what actually
    constructs the store this wraps -- ``MemoryRecorder.__init__``
    requires a ``MemoryStore`` instance, it is not optional.

    Args:
        memory_store: The already-built :class:`~Orchestration.memory.MemoryStore`
            every future ``.record(...)`` call would insert into. Held
            as-is by the returned ``MemoryRecorder``, never copied.
    """
    return MemoryRecorder(store=memory_store)


def _build_reflector() -> Reflector:
    """Construct the Stage L18 :class:`~Orchestration.reflection.Reflector`
    (Task 1A addition, additive only, construction-only scope).

    No collaborators -- ``Reflector`` is stateless and takes no
    constructor arguments (see its own docstring: it never constructs,
    imports, or references ``MemoryStore``). Nothing in
    ``build_application`` calls ``.reflect(...)`` on the returned
    instance.
    """
    return Reflector()


def _build_decision_engine() -> DecisionEngine:
    """Construct the Stage L19 :class:`~Orchestration.decision_engine.DecisionEngine`
    (additive only, construction-only scope).

    No collaborators -- ``DecisionEngine`` is stateless and takes no
    constructor arguments (see its own docstring: no LLM, Provider,
    Database, Runtime, or ServiceContext dependency). Nothing in
    ``build_application`` calls ``.decide(...)`` on the returned
    instance, and it is not passed into ``agent`` or
    ``runtime_analysis_pipeline``.
    """
    return DecisionEngine()

def _build_decision_policy() -> DecisionPolicy:
   """Construct the Stage L20B DecisionPolicy.
   Additive only.
   No collaborators.
   Not injected anywhere.
   Construction-only scope.
   """
   return DecisionPolicy()


def _build_policy_guard() -> PolicyGuard:
    """Construct the Stage L21 :class:`~Orchestration.policy_guard.PolicyGuard`
    (additive only, construction-only scope).

    No collaborators -- ``PolicyGuard`` is stateless and takes no
    constructor arguments (see its own docstring: no LLM, Provider,
    Database, Runtime, Memory, or Service dependency). Nothing in
    ``build_application`` calls ``.evaluate(...)`` on the returned
    instance, and it is not passed into ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``, or
    ``decision_policy``.
    """
    return PolicyGuard()


def _build_execution_intent() -> ExecutionIntent:
    """Construct the Stage L22 :class:`~Orchestration.execution_intent.ExecutionIntent`
    (additive only, construction-only scope).

    No collaborators -- ``ExecutionIntent`` is stateless and takes no
    constructor arguments (see its own docstring: no LLM, Provider,
    Database, Runtime, Memory, or Service dependency). Nothing in
    ``build_application`` calls ``.build(...)`` on the returned
    instance, and it is not passed into ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, or ``policy_guard``.
    """
    return ExecutionIntent()


def _build_execution_planner() -> ExecutionPlanner:
    """Construct the Stage L23 :class:`~Orchestration.execution_planner.ExecutionPlanner`
    (additive only, construction-only scope).

    No collaborators -- ``ExecutionPlanner`` is stateless and takes
    no constructor arguments (see its own docstring: no LLM,
    Provider, Database, Runtime, Memory, or Service dependency).
    Nothing in ``build_application`` calls ``.plan(...)`` on the
    returned instance, and it is not passed into ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, or ``execution_intent``.
    """
    return ExecutionPlanner()


def _build_execution_coordinator() -> ExecutionCoordinator:
    """Construct the Stage L24 :class:`~Orchestration.execution_coordinator.ExecutionCoordinator`
    (additive only, construction-only scope).

    No collaborators -- ``ExecutionCoordinator`` is stateless and takes
    no constructor arguments (see its own docstring: no LLM, Provider,
    Database, Runtime, Memory, or Service dependency). Nothing in
    ``build_application`` calls ``.coordinate(...)`` on the returned
    instance, and it is not passed into ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``, or
    ``execution_planner``.
    """
    return ExecutionCoordinator()


def _build_portfolio_engine() -> PortfolioEngine:
    """Construct the Stage L25 :class:`~Orchestration.portfolio_engine.PortfolioEngine`
    (additive only, construction-only scope).

    No collaborators -- ``PortfolioEngine`` is stateless and takes no
    constructor arguments (see its own docstring: no LLM, Provider,
    Database, Runtime, Memory, or Service dependency).

    Integration Sprint 7: the returned singleton is now also passed into
    ``runtime_analysis_pipeline`` (see
    :func:`_build_runtime_analysis_pipeline`), which calls
    ``.evaluate(...)`` on it with the real ``ExecutionCoordinatorResult``
    produced by ``execution_coordinator``. It is still not passed into
    ``agent``, ``decision_engine``, ``decision_policy``,
    ``policy_guard``, ``execution_intent``, ``execution_planner``, or
    ``execution_coordinator``, and remains the same single instance used
    everywhere it appears on ``ApplicationGraph`` -- not constructed a
    second time.
    """
    return PortfolioEngine()


def _build_portfolio_risk() -> PortfolioRisk:
    """Construct the Stage L26 :class:`~Orchestration.portfolio_risk.PortfolioRisk`
    (additive only, construction-only scope).

    No collaborators -- ``PortfolioRisk`` is stateless and takes no
    constructor arguments (see its own docstring: no LLM, Provider,
    Database, Runtime, Memory, or Service dependency).

    Integration Sprint 8: the returned singleton is now also passed into
    ``runtime_analysis_pipeline`` (see
    :func:`_build_runtime_analysis_pipeline`), which calls
    ``.assess(...)`` on it with the real ``PortfolioEngineResult``
    produced by ``portfolio_engine``. It is still not passed into
    ``agent``, ``decision_engine``, ``decision_policy``,
    ``policy_guard``, ``execution_intent``, ``execution_planner``,
    ``execution_coordinator``, or ``portfolio_engine``, and remains the
    same single instance used everywhere it appears on
    ``ApplicationGraph`` -- not constructed a second time.
    """
    return PortfolioRisk()


def _build_learning_loop() -> LearningLoop:
    """Construct the Stage L27 :class:`~Orchestration.learning_loop.LearningLoop`
    (additive only, construction-only scope).

    No collaborators -- ``LearningLoop`` is stateless and takes no
    constructor arguments (see its own docstring: no LLM, Provider,
    Database, Runtime, Memory, Service, or Executor dependency).

    Integration Sprint 9: the returned singleton is now also passed into
    ``runtime_analysis_pipeline`` (see
    :func:`_build_runtime_analysis_pipeline`), which calls
    ``.learn(...)`` on it with the real ``PortfolioRiskResult`` produced
    by ``portfolio_risk``. It is still not passed into ``agent``,
    ``decision_engine``, ``decision_policy``, ``policy_guard``,
    ``execution_intent``, ``execution_planner``,
    ``execution_coordinator``, ``portfolio_engine``, or
    ``portfolio_risk``, and remains the same single instance used
    everywhere it appears on ``ApplicationGraph`` -- not constructed a
    second time.
    """
    return LearningLoop()


def _build_autonomous_agent(
    *,
    reflector: Reflector,
    decision_engine: DecisionEngine,
    decision_policy: DecisionPolicy,
    policy_guard: PolicyGuard,
    execution_intent: ExecutionIntent,
    execution_planner: ExecutionPlanner,
    execution_coordinator: ExecutionCoordinator,
    portfolio_engine: PortfolioEngine,
    portfolio_risk: PortfolioRisk,
    learning_loop: LearningLoop,
    runtime_analysis_pipeline: RuntimeAnalysisPipeline,
    goal_planner: GoalPlanner,
) -> AutonomousAgent:
    """Construct the Stage L28A :class:`~Orchestration.autonomous_agent.AutonomousAgent`
    (additive only, construction-only scope).

    Pure composition: ``AutonomousAgent`` takes no dependency of its
    own other than the ten already-built stage components plus the
    already-built ``RuntimeAnalysisPipeline`` and ``GoalPlanner``
    singletons, all passed in here (each built earlier in
    :func:`build_application`, exactly once). It performs no I/O and
    calls none of the ten stage components -- see its own docstring.
    ``runtime_analysis_pipeline`` is the exact same singleton instance
    already passed into ``StockAgent`` (see ``agent`` construction
    below) and exposed on ``ApplicationGraph.runtime_analysis_pipeline``
    -- not a second, separately constructed instance.
    ``goal_planner`` (Phase 2, Sprint 7) is likewise the exact same
    singleton instance built by :func:`_build_goal_planner` and
    exposed on ``ApplicationGraph.goal_planner`` -- not a second,
    separately constructed ``GoalPlanner``. Nothing in
    ``build_application`` calls any method on the returned instance,
    and it is not passed into ``agent``.
    """
    return AutonomousAgent(
        reflection=reflector,
        decision_engine=decision_engine,
        decision_policy=decision_policy,
        policy_guard=policy_guard,
        execution_intent=execution_intent,
        execution_planner=execution_planner,
        execution_coordinator=execution_coordinator,
        portfolio_engine=portfolio_engine,
        portfolio_risk=portfolio_risk,
        learning_loop=learning_loop,
        runtime_analysis_pipeline=runtime_analysis_pipeline,
        goal_planner=goal_planner,
    )


def build_application(
    *,
    provider_name: Optional[str] = None,
    provider_kind: Optional[str] = None,
    agent_name: str = DEFAULT_AGENT_NAME,
) -> ApplicationGraph:
    """Assemble and return the production object graph.

    Stage 9.0 scope (LOCKED decision, Opsi A, additive only): constructs
    ``ProviderManager``-registered ``GeminiProvider``, ``ToolRegistry``,
    ``Executor``, the 11-service ``AnalysisPipeline``, and a ``StockAgent``
    using only each class's existing public constructor/registration API
    -- never a new parameter, never a subclass, never a monkeypatch.
    ``Core.runtime.Runtime``, ``Agents.executor.Executor.__init__``, and
    ``Agents.base_agent.BaseAgent`` are not touched beyond calling their
    existing public surface.

    Stage C5 addition (additive only, approved explicitly): also
    constructs a ``DatabaseManager`` wrapping a construct-only
    ``SQLiteDatabase`` -- see :func:`_build_database_manager`. Nothing
    about the Stage 9.0-9.4 behavior above is changed by this addition.

    Stage L1 addition (additive only, approved explicitly): ``provider_kind``
    now selects which ``BaseProvider`` subclass ``_build_provider``
    constructs (``"gemini"`` -> ``GeminiProvider``, ``"ollama"`` ->
    ``OllamaProvider``), resolved from ``ACTIVE_PROVIDER`` when omitted.
    ``provider_name`` keeps its original, unchanged meaning as purely the
    ``ProviderManager`` registry key -- when omitted it now defaults to
    the resolved ``provider_kind`` instead of the previous literal
    ``"gemini"`` constant, but every existing call site that passes an
    explicit ``provider_name`` (e.g. Stage 9.0's test suite) is completely
    unaffected: it never passed ``provider_kind``, so that still resolves
    to ``"gemini"`` unless ``ACTIVE_PROVIDER`` is set in the environment.

    Stage L5 addition (additive only, "wiring only" -- LOCKED design
    decision, Option A): a :class:`~Providers.provider_selector.ProviderSelector`
    is now constructed over the same ``provider_manager`` singleton and
    passed into ``Planner`` as ``provider_selector=``. This makes
    ``Planner.select_by_requirement()`` (Stage L4) reachable from the
    production graph for the first time. Deliberately NOT changed by this
    stage: what gets registered, or when. ``_build_provider`` still
    registers exactly the one provider ``resolved_provider_kind`` resolves
    to, exactly as before -- so in the default single-call flow the
    selector has exactly one candidate to choose from. Registering every
    known provider kind regardless of ``ACTIVE_PROVIDER`` (so the selector
    has more than one real candidate) is a distinct, larger behavioral
    change intentionally deferred to a future stage ("Multi-provider
    Registry"), not folded in here. ``ApplicationGraph`` gains no new
    field for this -- the selector is a local variable used only to
    construct ``Planner``; nothing outside ``Planner`` can reach it via
    the returned graph.

    Stage L6 addition (additive only, "Multi-provider Registry" -- the
    stage L5 deferred): every provider kind in :data:`_PROVIDER_CLASSES`
    is now registered via :func:`_register_all_provider_kinds`, not just
    ``resolved_provider_kind``. ``ProviderSelector`` (constructed above)
    therefore now sees every registered provider's real ``capabilities``
    as candidates -- not just one. ``ACTIVE_PROVIDER`` is re-scoped by
    this stage to mean *default provider only*: it still determines
    ``resolved_provider_name``/``resolved_provider_kind`` above, and
    therefore ``ApplicationGraph.provider_name``/``.provider_kind`` and
    ``Planner``'s ``default_provider_name`` (see below) -- but it no
    longer determines which providers get registered; that is now
    unconditional. ``ApplicationGraph`` still gains no new field: the
    full registered set is already available via
    ``graph.provider_manager.list()``, so it is not duplicated onto the
    graph itself. ``startup_validation.py`` is deliberately unchanged by
    this stage -- it still validates only the active provider's env
    vars, since every provider's ``connect()`` remains lazy and a
    provider that is registered but never selected is never used.

    Sprint 4 STEP 1 addition (additive only, "Paper Trading Engine --
    Account wiring", approved via Sprint 4 Pre-Implementation Review):
    also constructs an ``AccountRepository`` over this same
    ``database_manager`` -- see :func:`_build_account_repository` and
    ``ApplicationGraph.account_repository``. Graph-visibility only:
    nothing above or below this addition changes, and no existing
    field's construction order, identity, or behavior is affected.

    Sprint 4 STEP 2 addition (additive only, "PositionRepository +
    Position Migration"): also constructs a ``PositionRepository``
    over this same ``database_manager`` -- see
    :func:`_build_position_repository` and
    ``ApplicationGraph.position_repository``. Same graph-visibility-
    only scope as STEP 1: no existing field's construction order,
    identity, or behavior is affected.

    Stage L11 addition (additive only): also constructs a
    :class:`~Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline`
    (see :func:`_build_runtime_analysis_pipeline`) over the same
    ``executor``/``analysis_pipeline``/``tool_context_builder`` this
    function already builds, exposed as
    ``ApplicationGraph.runtime_analysis_pipeline``.

    Stage L12 addition (LOCKED decision, Option A -- additive, minimal
    blast radius, approved explicitly): the same
    ``runtime_analysis_pipeline`` is now also passed into ``StockAgent``'s
    own (optional, Stage L12) constructor argument of the same name, so
    ``agent`` routes its analysis calls through
    ``Core.runtime.Runtime`` as the execution kernel rather than calling
    ``analysis_pipeline`` directly. This is the one and only place in the
    production graph that activates that path -- ``StockAgent`` itself
    still supports running without it (``runtime_analysis_pipeline=None``
    falls back to the pre-L12 direct call, unchanged; see
    ``Agents.stock_agent.StockAgent._run_service_pipeline``), which is
    what every existing test construction of ``StockAgent`` across the
    test suite (none of which passes this argument) continues to rely on
    unmodified.

    Stage L13 addition (additive only, "Granular Skills" -- LOCKED
    decision, approved Diff-Level Plan FINAL): also wraps every Service
    already registered in ``service_registry`` (by
    :func:`_build_analysis_pipeline` above) in a
    :class:`~Orchestration.service_skill.ServiceSkill` and registers each
    as a standing Tool under a stable ``"skill.<service_name>"`` name
    (see :func:`_build_service_skills`), exposed as
    ``ApplicationGraph.service_skills``. This only adds a new capability
    reachable from the graph; it changes nothing about ``agent``,
    ``analysis_pipeline``, or ``runtime_analysis_pipeline`` above --
    ``StockAgent``'s call path is not wired to any of these new Tools.

    Stage L15 Phase 1 Step 7 addition (additive only, "Composition Root
    Integration" -- LOCKED decision): also constructs a
    :class:`~Orchestration.planner.GoalPlanner` (see
    :func:`_build_goal_planner`) over this same ``service_skills``
    mapping, exposed as ``ApplicationGraph.goal_planner``. Not registered
    as a Tool, not wired into ``agent``, and does not change the
    production ``StockAgent`` -> ``RuntimeAnalysisPipeline`` -> ``Runtime``
    -> ``AnalysisPipeline`` call path in any way -- ``goal_planner``
    exists on the graph only as another constructed component, for a
    future stage to wire up.

    Task 3 addition ("Second Skill / Cross-Skill Reflection Foundation",
    additive only): :func:`_build_notification_service` registers
    ``NotificationService`` into ``service_registry`` as a 12th,
    independent Service -- not part of ``AnalysisPipeline``, not passed
    to its constructor, not touching ``StockAgent`` or
    ``RuntimeAnalysisPipeline``. Runs immediately before
    ``_build_service_skills()`` below, which (itself unmodified) then
    wraps it into a ``ServiceSkill`` and registers ``skill.notification_service``
    as a standing Tool exactly the same way it already does for the 11
    pipeline Services -- because ``SKILL_METADATA_BY_SERVICE`` (Stage
    L13's dict) now carries a matching entry for it (see
    ``Orchestration/service_skill.py``). ``ApplicationGraph`` gains no
    new field: the new Service/Skill is reachable via the same
    ``service_registry``/``service_skills`` fields every other Service
    already used.

    Stage L21 addition (additive only, construction-only scope): also
    constructs a :class:`~Orchestration.policy_guard.PolicyGuard` (see
    :func:`_build_policy_guard`), exposed as
    ``ApplicationGraph.policy_guard``. No collaborators, not called by
    anything in this function, and not passed into ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``, or
    ``decision_policy`` -- follows the exact same additive,
    construction-only pattern ``decision_engine`` (L19) and
    ``decision_policy`` (L20) already established.

    Stage L22 addition (additive only, construction-only scope): also
    constructs an :class:`~Orchestration.execution_intent.ExecutionIntent`
    (see :func:`_build_execution_intent`), exposed as
    ``ApplicationGraph.execution_intent``. No collaborators, not
    called by anything in this function, and not passed into
    ``agent``, ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, or ``policy_guard`` -- follows the exact
    same additive, construction-only pattern ``decision_engine``
    (L19), ``decision_policy`` (L20), and ``policy_guard`` (L21)
    already established.

    Stage L23 addition (additive only, construction-only scope): also
    constructs an :class:`~Orchestration.execution_planner.ExecutionPlanner`
    (see :func:`_build_execution_planner`), exposed as
    ``ApplicationGraph.execution_planner``. No collaborators, not
    called by anything in this function, and not passed into
    ``agent``, ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, or ``execution_intent`` --
    follows the exact same additive, construction-only pattern
    ``decision_engine`` (L19), ``decision_policy`` (L20),
    ``policy_guard`` (L21), and ``execution_intent`` (L22) already
    established.

    Stage L24 addition (additive only, construction-only scope): also
    constructs an
    :class:`~Orchestration.execution_coordinator.ExecutionCoordinator`
    (see :func:`_build_execution_coordinator`), exposed as
    ``ApplicationGraph.execution_coordinator``. No collaborators, not
    called by anything in this function, and not passed into
    ``agent``, ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``, or
    ``execution_planner`` -- follows the exact same additive,
    construction-only pattern ``decision_engine`` (L19),
    ``decision_policy`` (L20), ``policy_guard`` (L21),
    ``execution_intent`` (L22), and ``execution_planner`` (L23)
    already established.

    Stage L25 addition (additive only, construction-only scope): also
    constructs a
    :class:`~Orchestration.portfolio_engine.PortfolioEngine`
    (see :func:`_build_portfolio_engine`), exposed as
    ``ApplicationGraph.portfolio_engine``. No collaborators, not
    called by anything in this function, and not passed into
    ``agent``, ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``,
    ``execution_planner``, or ``execution_coordinator`` -- follows
    the exact same additive, construction-only pattern
    ``decision_engine`` (L19), ``decision_policy`` (L20),
    ``policy_guard`` (L21), ``execution_intent`` (L22),
    ``execution_planner`` (L23), and ``execution_coordinator`` (L24)
    already established.

    Stage L26 addition (additive only, construction-only scope): also
    constructs a
    :class:`~Orchestration.portfolio_risk.PortfolioRisk`
    (see :func:`_build_portfolio_risk`), exposed as
    ``ApplicationGraph.portfolio_risk``. No collaborators, not called
    by anything in this function, and not passed into ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``,
    ``execution_planner``, ``execution_coordinator``, or
    ``portfolio_engine`` -- follows the exact same additive,
    construction-only pattern ``decision_engine`` (L19),
    ``decision_policy`` (L20), ``policy_guard`` (L21),
    ``execution_intent`` (L22), ``execution_planner`` (L23),
    ``execution_coordinator`` (L24), and ``portfolio_engine`` (L25)
    already established.

    Stage L27 addition (additive only, construction-only scope): also
    constructs a
    :class:`~Orchestration.learning_loop.LearningLoop`
    (see :func:`_build_learning_loop`), exposed as
    ``ApplicationGraph.learning_loop``. No collaborators, not called
    by anything in this function, and not passed into ``agent``,
    ``runtime_analysis_pipeline``, ``decision_engine``,
    ``decision_policy``, ``policy_guard``, ``execution_intent``,
    ``execution_planner``, ``execution_coordinator``,
    ``portfolio_engine``, or ``portfolio_risk`` -- follows the exact
    same additive, construction-only pattern ``decision_engine``
    (L19), ``decision_policy`` (L20), ``policy_guard`` (L21),
    ``execution_intent`` (L22), ``execution_planner`` (L23),
    ``execution_coordinator`` (L24), ``portfolio_engine`` (L25), and
    ``portfolio_risk`` (L26) already established.

    Stage L28A addition (additive only, construction-only scope): also
    constructs an
    :class:`~Orchestration.autonomous_agent.AutonomousAgent`
    (see :func:`_build_autonomous_agent`), exposed as
    ``ApplicationGraph.autonomous_agent``. A pure composition object
    that aggregates references to the ten L18-L27 components built
    above -- it does not call any of them, is not called by anything
    in this function beyond its own construction, and is not passed
    into ``agent`` or ``runtime_analysis_pipeline``.

    Known Phase-1 limitation (Stage L12, not addressed by this stage by
    deliberate decision): ``Executor`` here is constructed with
    ``approval_port=build_approval_port()``, read from
    ``APPROVAL_POLICY`` (default ``"always_approve"``). This function
    assumes ``APPROVAL_POLICY=always_approve`` (or unset) for
    ``StockAgent``'s new Runtime-routed path to work at all:
    ``RuntimeAnalysisPipeline`` registers a uniquely UUID-named private
    Tool per call (see its own module docstring, decision #4), so an
    exact-match ``tool_whitelist`` policy can never contain that name and
    would deny every single ``StockAgent`` request. This is documented,
    known Phase-1 debt, not solved here -- see the Stage L12 handover.

    Hermetic: performs no network I/O, no filesystem I/O, and requires no
    external package or secret to complete (see module docstring for
    why). Safe to call in any environment, CI included. This still holds
    after Stage C5/L1: ``DatabaseManager``/``SQLiteDatabase`` and the
    selected provider are constructed but never connected here.

    Idempotency: the four registries this function writes to
    (``tool_registry`` is read-only here, ``provider_manager``,
    ``agent_registry``, ``service_registry``) are process-wide
    singletons; every ``register()`` call is guarded by an ``exists()``
    check first, so calling this function more than once in the same
    process is safe and re-registers nothing. It does construct a fresh
    ``Executor``/``Planner``/``AnalysisPipeline``/``StockAgent``/
    ``DatabaseManager`` graph on every call -- only the shared singletons
    are de-duplicated; the *agent instance* and the *database manager
    instance* were never scoped as singletons.

    Args:
        provider_name: Registry key to register the selected provider
            under, and the agent's own default provider name. Defaults
            to the resolved ``provider_kind`` when omitted.
        provider_kind: Which provider class to construct -- a key in
            :data:`_PROVIDER_CLASSES` (``"gemini"`` or ``"ollama"``).
            Defaults to ``config.get("ACTIVE_PROVIDER", "gemini")`` when
            omitted.
        agent_name: Name to register the constructed ``StockAgent``
            under in ``AgentRegistry``. Defaults to ``"stock_agent"``.

    Returns:
        The assembled :class:`ApplicationGraph`.

    Raises:
        ConfigurationError: If the resolved ``provider_kind`` is not a
            recognized key in :data:`_PROVIDER_CLASSES`.
    """
    logger.debug("Composition root: assembling production object graph")

    resolved_provider_kind = provider_kind or config.get("ACTIVE_PROVIDER", DEFAULT_PROVIDER_NAME)
    resolved_provider_name = provider_name if provider_name is not None else resolved_provider_kind

    _build_provider(resolved_provider_name, resolved_provider_kind)

    # Stage L6: registry now holds every known provider kind, not just
    # the one ACTIVE_PROVIDER resolves to. See _register_all_provider_kinds()
    # for why this is additive/idempotent and does not change what
    # resolved_provider_name/resolved_provider_kind mean above.
    _register_all_provider_kinds()

    provider_selector = ProviderSelector(provider_manager)
    planner = Planner(
        provider_manager=provider_manager,
        tool_registry=tool_registry,
        provider_selector=provider_selector,
        # Stage L6: with more than one provider now registered,
        # Planner.select_provider(None)'s old fallback (first-registered,
        # i.e. dict insertion order) would no longer reliably mean
        # "ACTIVE_PROVIDER". Passing the resolved default explicitly
        # keeps "default provider" == ACTIVE_PROVIDER's contract intact
        # without touching Planner's own file/logic.
        default_provider_name=resolved_provider_name,
    )
    memory = ConversationMemory()
    resolved_approval_port = build_approval_port()
    if isinstance(resolved_approval_port, ToolWhitelistApprovalPort):
        raise ConfigurationError(
            "APPROVAL_POLICY=tool_whitelist is incompatible with the "
            "production StockAgent path: RuntimeAnalysisPipeline registers "
            "a uniquely-named Tool per call (runtime_analysis_pipeline::"
            "<uuid>), which a static whitelist can never contain -- every "
            "request would be denied. Use APPROVAL_POLICY=always_approve "
            "or APPROVAL_POLICY=tool_blacklist instead.",
            details={"policy": "tool_whitelist"},
        )
    executor = Executor(
        tool_registry=tool_registry,
        approval_port=resolved_approval_port,
    )

    analysis_pipeline = _build_analysis_pipeline()
    tool_context_builder = ToolContextBuilder()
    database_manager = _build_database_manager()
    # Sprint 4 STEP 1: account_repository must be built immediately
    # after database_manager, over this exact same instance -- never a
    # second DatabaseManager. See _build_account_repository() and
    # ApplicationGraph.account_repository for why the shared-instance
    # requirement matters for later Sprint 4 STEPs (transaction
    # nesting via BasePersistenceRepository._session()). Purely
    # additive: nothing below this line reads account_repository yet.
    account_repository = _build_account_repository(database_manager)
    # Sprint 5 STEP 1: watchlist_repository must be built over this same
    # database_manager instance, mirroring account_repository above --
    # never a second DatabaseManager. See _build_watchlist_repository()
    # and ApplicationGraph.watchlist_repository. Purely additive:
    # nothing below this line reads watchlist_repository yet.
    watchlist_repository = _build_watchlist_repository(database_manager)
    # Activation 2.2 (Production Dependency Resolver): the ONE
    # production ToolResolver (over the ONE production
    # Orchestration.tool_registry.ToolRegistry, registered with the
    # three existing Market*Tool classes) is built exactly once, here,
    # ahead of every MarketAnalysisSkill construction below -- both
    # market_analysis_agent's and trading_decision_agent's. Neither
    # builder constructs its own registry/resolver anymore; both
    # receive this same instance by reference. See
    # _build_market_tool_resolver().
    #
    # Activation 12.6: ONE PermissionContext is constructed here, for
    # the whole application graph -- the single trusted owner. This
    # exact instance (never a copy, never a second construction) is
    # injected into both the canonical market-tool path
    # (_build_market_tool_resolver, immediately below) and the legacy
    # Agents service-tool path (_build_service_skills, further down).
    # All three fields remain at their dataclass defaults (False) --
    # this step introduces no new authorization semantics, no env var,
    # no CLI flag, and no ApplicationGraph field.
    permission_context = PermissionContext()
    # Activation 12 (Tool and Capability Registry discovery):
    # _build_market_tool_resolver() now also returns market_tool_manager,
    # an Orchestration.tool_manager.ToolManager wrapping this EXACT SAME
    # registry/resolver pair -- never a second registry. market_tool_resolver
    # itself is unpacked and used exactly as every prior Activation already
    # does (market_analysis_agent, trading_decision_agent below); only
    # market_tool_manager is new, and it only flows to ApplicationGraph.
    market_tool_resolver, market_tool_manager = _build_market_tool_resolver(
        permission_context
    )
    # Phase F, Task 9: copilot_tool_resolver needs only permission_context
    # (already constructed above) -- no ordering dependency on
    # paper_trading_engine or any other collaborator, so it is built
    # here, alongside market_tool_resolver. See
    # _build_copilot_tool_resolver() and
    # ApplicationGraph.copilot_tool_resolver.
    copilot_tool_resolver = _build_copilot_tool_resolver(permission_context)
    # Phase F, Task 9: also expose the same capability through the
    # legacy Agents.tool_registry path, mirroring Activation 12.8's own
    # AgentsToolPermissionAdapter wiring for paper_execution below --
    # same shared permission_context, same fail-closed default, no
    # direct handler bypass. Guarded by exists() for the same
    # re-entrancy reason every other registration in this module
    # already is (build_application() called more than once in the
    # same process).
    _copilot_tool = CopilotTool()
    if not tool_registry.exists(_copilot_tool.name):
        tool_registry.register(
            Tool(
                name=_copilot_tool.name,
                description=_copilot_tool.description,
                handler=AgentsToolPermissionAdapter(
                    wrapped_tool=_copilot_tool,
                    handler=_copilot_tool.execute,
                    permission_context=permission_context,
                ),
            )
        )
    # Sprint 5 STEP 1: market_analysis_agent is the first production
    # instance of Orchestration.market_analysis_agent.MarketAnalysisAgent
    # (LOCKED DECISION -- Revisi). Takes no collaborators built above
    # other than market_tool_resolver -- see
    # _build_market_analysis_agent() and
    # ApplicationGraph.market_analysis_agent. Purely additive: nothing
    # below this line reads market_analysis_agent yet.
    market_analysis_agent = _build_market_analysis_agent(market_tool_resolver)
    # Sprint 4 STEP 2: position_repository must be built over this same
    # database_manager instance, mirroring account_repository above --
    # never a second DatabaseManager. See _build_position_repository()
    # and ApplicationGraph.position_repository. Purely additive:
    # nothing below this line reads position_repository yet.
    position_repository = _build_position_repository(database_manager)
    # Sprint 4 STEP 3: order_repository must be built over this same
    # database_manager instance, mirroring account_repository/
    # position_repository above -- never a second DatabaseManager. See
    # _build_order_repository() and ApplicationGraph.order_repository.
    # Purely additive: nothing below this line reads order_repository
    # yet.
    order_repository = _build_order_repository(database_manager)
    # Sprint 4 STEP 5: order_lifecycle_service must be built over this
    # same order_repository instance -- never a second OrderRepository.
    # See _build_order_lifecycle_service() and
    # ApplicationGraph.order_lifecycle_service. Purely additive:
    # nothing below this line reads order_lifecycle_service yet.
    order_lifecycle_service = _build_order_lifecycle_service(order_repository)
    # Sprint 4 STEP 4: trade_repository must be built over this same
    # database_manager instance, mirroring account_repository/
    # position_repository/order_repository above -- never a second
    # DatabaseManager. See _build_trade_repository() and
    # ApplicationGraph.trade_repository. Purely additive: nothing
    # below this line reads trade_repository yet.
    trade_repository = _build_trade_repository(database_manager)
    # Sprint 5 STEP 3: snapshot_repository must be built over this same
    # database_manager instance, mirroring account_repository/
    # position_repository/order_repository/trade_repository above --
    # never a second DatabaseManager. See _build_snapshot_repository()
    # and ApplicationGraph.snapshot_repository. Purely additive:
    # nothing below this line reads snapshot_repository yet.
    snapshot_repository = _build_snapshot_repository(database_manager)
    # Phase B ("Decision Copilot"): decision_brief_service must be
    # built over this same snapshot_repository/database_manager --
    # never a second SnapshotRepository, never a second risk engine.
    # See _build_decision_brief_service() and
    # ApplicationGraph.decision_brief_service. Purely additive:
    # nothing below this line reads decision_brief_service yet.
    decision_brief_service = _build_decision_brief_service(database_manager, snapshot_repository)
    # Phase C ("Personal Risk Ledger + Decision Journal"): journal_service
    # must be built over this same database_manager, reusing a fresh
    # risk_limits_repository over that same instance -- never a second
    # DatabaseManager, never a second risk engine. See
    # _build_risk_limits_repository()/_build_journal_service() and
    # ApplicationGraph.risk_limits_repository/journal_service. Purely
    # additive: nothing below this line reads either yet.
    risk_limits_repository = _build_risk_limits_repository(database_manager)
    journal_service = _build_journal_service(database_manager, risk_limits_repository)
    # Phase H Task 1 ("Observation Window + Sustained-Use Review
    # Record"): observation_window_service must be built over this
    # same database_manager -- never a second DatabaseManager. See
    # _build_observation_window_service() and
    # ApplicationGraph.observation_window_service. Purely additive:
    # nothing below this line reads observation_window_service yet.
    observation_window_service = _build_observation_window_service(database_manager)
    # Sprint 6 STEP 1: performance_repository must be built over this same
    # database_manager instance, mirroring account_repository/
    # position_repository/order_repository/trade_repository/
    # snapshot_repository above -- never a second DatabaseManager. See
    # _build_performance_repository() and
    # ApplicationGraph.performance_repository. Purely additive: nothing
    # below this line reads performance_repository yet.
    performance_repository = _build_performance_repository(database_manager)
    # Activation 3.3: execution_policy is read once, here, from
    # Core.config, and threaded through to both execution_service and
    # paper_trading_engine below -- never a second, independently-
    # loaded ExecutionPolicy. See _build_execution_policy().
    execution_policy = _build_execution_policy()
    # Sprint 4 STEP 6: execution_service must be built over these same
    # order_repository/trade_repository instances -- never second
    # Repository instances. See _build_execution_service() and
    # ApplicationGraph.execution_service. Purely additive: nothing
    # below this line reads execution_service yet.
    execution_service = _build_execution_service(order_repository, trade_repository, execution_policy)
    # Sprint 4 STEP 7: account_balance_service must be built over this
    # same account_repository instance (from Sprint 4 STEP 1) -- never
    # a second AccountRepository. See _build_account_balance_service()
    # and ApplicationGraph.account_balance_service. Activation 3.5
    # STEP 1 threads this same instance into paper_trading_engine below
    # -- its first production consumer.
    account_balance_service = _build_account_balance_service(account_repository)
    # Sprint 4 STEP 8: position_manager must be built over this same
    # position_repository instance (from Sprint 4 STEP 2) -- never a
    # second PositionRepository. See _build_position_manager() and
    # ApplicationGraph.position_manager. Activation 3.5 STEP 2 threads
    # this same instance into paper_trading_engine below -- its first
    # production consumer.
    position_manager = _build_position_manager(position_repository)
    # Activation 3.2: order_idempotency_repository must be built over
    # this same database_manager instance, mirroring account_repository/
    # position_repository/order_repository/trade_repository above --
    # never a second DatabaseManager. See
    # _build_order_idempotency_repository() and
    # ApplicationGraph.order_idempotency_repository. Purely additive:
    # nothing below this line reads order_idempotency_repository except
    # paper_trading_engine.
    order_idempotency_repository = _build_order_idempotency_repository(database_manager)
    # Activation 7 Blocker #4: order_approval_repository must be built
    # over this same database_manager instance, mirroring
    # order_idempotency_repository immediately above -- never a second
    # DatabaseManager. See _build_order_approval_repository() and
    # ApplicationGraph.order_approval_repository. Purely additive:
    # nothing below this line reads order_approval_repository except
    # paper_trading_engine.
    order_approval_repository = _build_order_approval_repository(database_manager)
    # Task 3 ("Second Skill / Cross-Skill Reflection Foundation"):
    # registers NotificationService into service_registry as a 12th,
    # independent Service (not part of AnalysisPipeline). Must run
    # before _build_service_skills() below, which wraps every Service
    # already present in service_registry at the time it runs.
    #
    # Activation 6.3 ("Wire ORDER_EXECUTED notification into the
    # trading flow"): this whole notification-chain block (previously
    # built further down, right before _build_service_skills()) is
    # moved up to here -- still before _build_service_skills(), the
    # only real ordering constraint it has ever had -- so that
    # notification_manager/notification_builder exist in time to be
    # passed into _build_paper_trading_engine() below. Construction
    # order within the block is unchanged from Sprint 7 STEP 7 (LOCKED
    # DECISION 3): NotificationBuilder -> TelegramNotificationChannel
    # -> NotificationDispatcher -> NotificationManager.
    notification_service = _build_notification_service()
    notification_builder = _build_notification_builder()
    telegram_notification_channel = _build_telegram_notification_channel(
        notification_service
    )
    notification_dispatcher = _build_notification_dispatcher(
        telegram_notification_channel
    )
    notification_manager = _build_notification_manager(notification_dispatcher)
    # Sprint 4 STEP 9, extended by Activation 3.2, Activation 3.3 STEP 2,
    # Activation 3.5 STEP 1, Activation 3.5 STEP 2, and Activation 6.3:
    # paper_trading_engine must be built over these same
    # order_lifecycle_service/execution_service/account_repository/
    # position_repository/order_idempotency_repository/
    # account_balance_service/position_manager/notification_manager/
    # notification_builder instances -- never second instances. See
    # _build_paper_trading_engine() and ApplicationGraph.
    # paper_trading_engine. account_balance_service (built above, Sprint
    # 4 STEP 7) got its production consumer via Activation 3.5 STEP 1;
    # position_manager (built above, Sprint 4 STEP 8) got its production
    # consumer via Activation 3.5 STEP 2; notification_manager/
    # notification_builder (built immediately above) now finally get a
    # production consumer here -- this is the wiring Activation 6.3 adds.
    # A notification failure inside submit_order() is isolated there
    # (LOCKED, Activation 6.3) and never affects trading state, so
    # wiring a real notification_manager in here carries no new risk to
    # the trading path itself.
    paper_trading_engine = _build_paper_trading_engine(
        order_lifecycle_service,
        execution_service,
        account_repository,
        position_repository,
        order_idempotency_repository,
        execution_policy,
        account_balance_service,
        position_manager,
        notification_manager,
        notification_builder,
        order_approval_repository,
    )
    # Activation 12.8: paper_execution_tool_resolver must be built over
    # this same paper_trading_engine instance (immediately above) and
    # the one shared permission_context constructed earlier in this
    # function (Activation 12.6's single-owner rule, the same instance
    # already passed to _build_market_tool_resolver()/
    # _build_service_skills()) -- never a second PaperTradingEngine and
    # never a second PermissionContext. See
    # _build_paper_execution_tool_resolver() and
    # ApplicationGraph.paper_execution_tool_resolver.
    paper_execution_tool_resolver = _build_paper_execution_tool_resolver(
        paper_trading_engine, permission_context
    )
    # Activation 12.8: also expose the same capability through the
    # legacy Agents.tool_registry path, mirroring _build_service_skills()'s
    # own AgentsToolPermissionAdapter wiring exactly -- no direct handler
    # bypass, same shared permission_context, same fail-closed default.
    # Guarded by exists() for the same re-entrancy reason every other
    # registration in this module already is (build_application() called
    # more than once in the same process).
    _paper_execution_tool = PaperExecutionTool(paper_trading_engine)
    if not tool_registry.exists(_paper_execution_tool.name):
        tool_registry.register(
            Tool(
                name=_paper_execution_tool.name,
                description=_paper_execution_tool.description,
                handler=AgentsToolPermissionAdapter(
                    wrapped_tool=_paper_execution_tool,
                    handler=_paper_execution_tool.execute,
                    permission_context=permission_context,
                ),
            )
        )
    # Sprint 5 STEP 6: manual_scan_service must be built after
    # watchlist_repository, market_analysis_agent, and
    # snapshot_repository above -- it wraps the first two in a fresh
    # WatchlistScanner and reuses the exact same snapshot_repository
    # instance, never a second DatabaseManager-backed Repository. See
    # _build_manual_scan_service() and
    # ApplicationGraph.manual_scan_service. Purely additive: nothing
    # below this line reads manual_scan_service yet.
    manual_scan_service = _build_manual_scan_service(
        watchlist_repository, market_analysis_agent, snapshot_repository
    )
    # Integration Sprint 1: memory_store/memory_recorder/reflector/
    # decision_engine must exist before runtime_analysis_pipeline below,
    # since that facade now takes them as collaborators. Moved up from
    # their prior construction point (immediately after service_skills/
    # goal_planner); each is still built exactly once, by the same
    # _build_* function as before -- only the order changed.
    memory_store = _build_memory_store()
    memory_recorder = _build_memory_recorder(memory_store)
    reflector = _build_reflector()
    decision_engine = _build_decision_engine()
    # Integration Sprint 2: decision_policy must likewise exist before
    # runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after observation_recorder); still
    # built exactly once, by the same _build_decision_policy() as before
    # -- only the order changed.
    decision_policy = _build_decision_policy()
    # Integration Sprint 3: policy_guard must likewise exist before
    # runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after decision_policy); still
    # built exactly once, by the same _build_policy_guard() as before --
    # only the order changed.
    policy_guard = _build_policy_guard()
    # Integration Sprint 4: execution_intent must likewise exist before
    # runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after observation_recorder); still
    # built exactly once, by the same _build_execution_intent() as
    # before -- only the order changed.
    execution_intent = _build_execution_intent()
    # Integration Sprint 5: execution_planner must likewise exist before
    # runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after observation_recorder); still
    # built exactly once, by the same _build_execution_planner() as
    # before -- only the order changed.
    execution_planner = _build_execution_planner()
    # Integration Sprint 6: execution_coordinator must likewise exist
    # before runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after observation_recorder); still
    # built exactly once, by the same _build_execution_coordinator() as
    # before -- only the order changed.
    execution_coordinator = _build_execution_coordinator()
    # Integration Sprint 7: portfolio_engine must likewise exist before
    # runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after observation_recorder); still
    # built exactly once, by the same _build_portfolio_engine() as
    # before -- only the order changed.
    portfolio_engine = _build_portfolio_engine()
    # Integration Sprint 8: portfolio_risk must likewise exist before
    # runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after observation_recorder); still
    # built exactly once, by the same _build_portfolio_risk() as before
    # -- only the order changed. Singleton lifetime is unchanged: still
    # constructed exactly once per build_application() call, same as
    # every other stage component here.
    portfolio_risk = _build_portfolio_risk()
    # Integration Sprint 9: learning_loop must likewise exist before
    # runtime_analysis_pipeline below. Moved up from its prior
    # construction point (immediately after observation_recorder); still
    # built exactly once, by the same _build_learning_loop() as before
    # -- only the order changed. Singleton lifetime is unchanged: still
    # constructed exactly once per build_application() call, same as
    # every other stage component here.
    learning_loop = _build_learning_loop()
    # Phase 13, Sprint 151: gemini_vision_provider/vision_market_state_pipeline
    # must exist before runtime_analysis_pipeline below, since that facade
    # now takes the latter as an optional collaborator. GeminiVisionProvider
    # has no __init__ of its own (see Providers.gemini_vision_provider) --
    # constructing it performs no I/O, exactly the same construct-only
    # boundary every other Provider in this module already draws.
    gemini_vision_provider = GeminiVisionProvider()
    vision_market_state_pipeline = _build_vision_market_state_pipeline(
        gemini_vision_provider
    )
    # Sprint 152: trading_decision_agent must exist before
    # runtime_analysis_pipeline below, since that facade now takes it
    # as an optional collaborator. Each of its six Skills has no
    # __init__ of its own -- constructing them performs no I/O, same
    # construct-only boundary every other component in this module
    # already draws. Activation 2.2: reuses market_tool_resolver (built
    # once, above, near market_analysis_agent) instead of constructing
    # a second, independent ToolRegistry/ToolResolver pair.
    trading_decision_agent = _build_trading_decision_agent(market_tool_resolver)
    runtime_analysis_pipeline = _build_runtime_analysis_pipeline(
        executor=executor,
        analysis_pipeline=analysis_pipeline,
        tool_context_builder=tool_context_builder,
        memory_recorder=memory_recorder,
        memory_store=memory_store,
        reflector=reflector,
        decision_engine=decision_engine,
        decision_policy=decision_policy,
        policy_guard=policy_guard,
        execution_intent=execution_intent,
        execution_planner=execution_planner,
        execution_coordinator=execution_coordinator,
        portfolio_engine=portfolio_engine,
        portfolio_risk=portfolio_risk,
        learning_loop=learning_loop,
        vision_pipeline=vision_market_state_pipeline,
        trading_decision_agent=trading_decision_agent,
    )
    # Stage L13: built after _build_analysis_pipeline() and the Task 3
    # registration above, which together populate service_registry with
    # every production Service this wraps. Additive only -- see
    # _build_service_skills() and ApplicationGraph.service_skills
    # docstrings.
    # Activation 12.6: same single PermissionContext instance
    # constructed above, ahead of _build_market_tool_resolver() -- not
    # a second construction. See that call site for why.
    service_skills = _build_service_skills(permission_context)
    # Stage L15 Phase 1 Step 7: built immediately after service_skills,
    # reusing this exact mapping -- no ServiceSkill is constructed a
    # second time. Additive only -- see _build_goal_planner() and
    # ApplicationGraph.goal_planner docstrings. Phase 2, Sprint 7: now
    # also passed into _build_autonomous_agent() below as the same
    # singleton -- not rebuilt or wrapped.
    goal_planner = _build_goal_planner(service_skills)
    # Task 1A: construction-only. Each is built here purely to be
    # exposed on ApplicationGraph, following the exact same additive
    # pattern as goal_planner (L15) above -- none is passed into
    # agent, runtime_analysis_pipeline, or goal_planner below, and
    # none changes the production StockAgent -> RuntimeAnalysisPipeline
    # -> Runtime -> AnalysisPipeline call path. memory_recorder must be
    # built after memory_store (see _build_memory_recorder).
    observation_recorder = _build_observation_recorder()
    # memory_store, memory_recorder, reflector, decision_engine,
    # decision_policy, policy_guard, execution_intent, execution_planner,
    # execution_coordinator, portfolio_engine, portfolio_risk,
    # learning_loop: built earlier now (see above, Integration Sprint 1 /
    # Integration Sprint 2 / Integration Sprint 3 / Integration Sprint 4 /
    # Integration Sprint 5 / Integration Sprint 6 / Integration
    # Sprint 7 / Integration Sprint 8 / Integration Sprint 9) -- not
    # rebuilt here.
    autonomous_agent = _build_autonomous_agent(
        reflector=reflector,
        decision_engine=decision_engine,
        decision_policy=decision_policy,
        policy_guard=policy_guard,
        execution_intent=execution_intent,
        execution_planner=execution_planner,
        execution_coordinator=execution_coordinator,
        portfolio_engine=portfolio_engine,
        portfolio_risk=portfolio_risk,
        learning_loop=learning_loop,
        runtime_analysis_pipeline=runtime_analysis_pipeline,
        goal_planner=goal_planner,
    )

    agent = StockAgent(
        planner=planner,
        memory=memory,
        executor=executor,
        analysis_pipeline=analysis_pipeline,
        tool_context_builder=tool_context_builder,
        default_provider_name=resolved_provider_name,
        runtime_analysis_pipeline=runtime_analysis_pipeline,
    )

    if not agent_registry.exists(agent_name):
        agent_registry.register(agent_name, agent)

    # Activation 4 Session 1: market_price_tool is a trivial, stateless,
    # no-arg construction (see ApplicationGraph.market_price_tool's own
    # docstring) -- not a new component, the same MarketPriceTool class
    # already used inside _build_market_tool_resolver() above, just also
    # exposed as a graph field so CLI "paper buy"/"paper sell" callers
    # (Core.composition_root has no other production caller with a
    # ToolResolver/ToolContext chain reachable from main.py) can look up
    # a real current price without a second implementation of price
    # fetching being written anywhere.
    market_price_tool = MarketPriceTool()

    # Activation 4 Session 2: unrealized_pnl_engine reuses this exact,
    # already-constructed market_price_tool instance -- the LOCKED,
    # Activation 3.7 STEP 4 UnrealizedPnLEngine's one and only
    # constructor dependency (see ApplicationGraph.unrealized_pnl_engine's
    # own docstring). This is graph-visibility wiring only: no new
    # business logic, no second price-fetch path, no second formula --
    # the engine class itself is untouched.
    unrealized_pnl_engine = UnrealizedPnLEngine(market_price_tool)

    # Activation 5.5: PerformanceSummaryService production wiring.
    # portfolio_snapshot_repository mirrors every other Repository
    # above -- same shared database_manager, never a second one.
    portfolio_snapshot_repository = _build_portfolio_snapshot_repository(database_manager)
    # maximum_drawdown_engine is the existing, LOCKED
    # Business.maximum_drawdown_engine.MaximumDrawdownEngine (no-arg
    # constructor, same trivial/stateless shape as unrealized_pnl_engine
    # above) -- shared between portfolio_snapshot_service (drawdown over
    # the equity curve) and performance_summary_service (drawdown over a
    # caller-supplied curve) below, never two separate instances.
    maximum_drawdown_engine = MaximumDrawdownEngine()
    # portfolio_snapshot_service is the existing, LOCKED Activation
    # 5.2/5.4 PortfolioSnapshotService -- unchanged class, first
    # production wiring. Reuses account_repository/position_repository/
    # unrealized_pnl_engine already built above -- never second
    # instances.
    portfolio_snapshot_service = PortfolioSnapshotService(
        account_repository=account_repository,
        position_repository=position_repository,
        unrealized_pnl_engine=unrealized_pnl_engine,
        maximum_drawdown_engine=maximum_drawdown_engine,
        portfolio_snapshot_repository=portfolio_snapshot_repository,
    )
    # Activation 7 FIX (blocker 3): reconciliation_engine is the
    # existing, LOCKED Activation 3.9 ReconciliationEngine -- unchanged
    # class, unchanged formula, first production wiring (previously
    # constructed only inside its own test file). Reuses
    # order_repository/trade_repository/account_repository/
    # position_repository already built above -- never second
    # instances, never a new Repository.
    reconciliation_engine = ReconciliationEngine(
        order_repository=order_repository,
        trade_repository=trade_repository,
        account_repository=account_repository,
        position_repository=position_repository,
    )
    # ACTIVATION 7 -- EXECUTION RATE WIRING ONLY: execution_rate_engine
    # is the existing, LOCKED ExecutionRateEngine -- unchanged class,
    # unchanged formula, first production wiring (previously
    # constructed only inside its own test file). Reuses
    # order_repository already built above -- never a second instance,
    # never a new Repository.
    execution_rate_engine = ExecutionRateEngine(
        order_repository=order_repository,
    )
    # ACTIVATION 7 -- FAILURE RATE WIRING ONLY: failure_rate_engine is
    # the existing, LOCKED FailureRateEngine -- unchanged class,
    # unchanged formula, first production wiring (previously
    # constructed only inside its own test file). Reuses
    # snapshot_repository/order_repository already built above --
    # never second instances, never a new Repository.
    failure_rate_engine = FailureRateEngine(
        snapshot_repository=snapshot_repository,
        order_repository=order_repository,
    )
    # The six Sprint 6 engines PerformanceSummaryService's LOCKED
    # constructor requires -- every one a no-arg, stateless,
    # already-LOCKED class (see each engine's own module docstring).
    # No formula is touched here; this is pure composition.
    trade_statistics_engine = TradeStatisticsEngine()
    position_performance_engine = PositionPerformanceEngine()
    win_rate_engine = WinRateEngine()
    expectancy_engine = ExpectancyEngine()
    profit_factor_engine = ProfitFactorEngine()
    # performance_summary_service is the existing, LOCKED Sprint 6
    # STEP 7 PerformanceSummaryService -- unchanged class, unchanged
    # LOCKED call order, first production wiring.
    performance_summary_service = PerformanceSummaryService(
        trade_statistics_engine=trade_statistics_engine,
        position_performance_engine=position_performance_engine,
        win_rate_engine=win_rate_engine,
        expectancy_engine=expectancy_engine,
        profit_factor_engine=profit_factor_engine,
        maximum_drawdown_engine=maximum_drawdown_engine,
    )
    # performance_summary_production_service is the new, thin
    # Activation 5.5 orchestrator: supplies performance_summary_service
    # with real, account-scoped trades/positions/equity_curve. The one
    # and only production entry point for a real PerformanceSummary.
    performance_summary_production_service = PerformanceSummaryProductionService(
        account_repository=account_repository,
        trade_repository=trade_repository,
        position_repository=position_repository,
        portfolio_snapshot_service=portfolio_snapshot_service,
        performance_summary_service=performance_summary_service,
    )

    # Activation 6.4: daily_report_orchestrator must be built after
    # manual_scan_service (built earlier above) and
    # performance_summary_production_service (built immediately
    # above), plus this graph's already-built notification_builder/
    # notification_manager -- never second, independently-constructed
    # instances. See _build_daily_report_orchestrator() and
    # ApplicationGraph.daily_report_orchestrator.
    daily_report_orchestrator = _build_daily_report_orchestrator(
        manual_scan_service,
        performance_summary_production_service,
        notification_builder,
        notification_manager,
    )

    # Phase D ("Proactive IDX Scheduler Routine"): idx_daily_scheduler
    # must be built after manual_scan_service and
    # daily_report_orchestrator (both immediately above), reusing both
    # -- never a second scan or daily-report pipeline. See
    # _build_idx_daily_scheduler()/_build_health_audit_service() and
    # ApplicationGraph.idx_daily_scheduler/health_audit_service. Purely
    # additive: nothing below this line reads either yet.
    idx_daily_scheduler = _build_idx_daily_scheduler(
        database_manager,
        manual_scan_service,
        daily_report_orchestrator,
        notification_manager,
        DEFAULT_PAPER_ACCOUNT_ID,
    )
    health_audit_service = _build_health_audit_service(database_manager)

    # Activation 5.6: Strategy Attribution production wiring.
    # trade_holding_period_engine is the new, pure, no-arg, no-repository
    # engine (mirrors trade_statistics_engine/maximum_drawdown_engine
    # above) -- reconstructs holding periods purely from the Trade
    # ledger, never from Position.
    trade_holding_period_engine = TradeHoldingPeriodEngine()
    # trade_attribution_engine reuses this graph's existing, LOCKED
    # decision_policy (built earlier by _build_decision_policy()) --
    # never a second/new risk-mapping component.
    trade_attribution_engine = TradeAttributionEngine(decision_policy)
    # trade_attribution_service is the new, thin Activation 5.6
    # orchestrator: supplies trade_attribution_engine/
    # trade_holding_period_engine with real, account-scoped
    # trades/orders/account/snapshots. Reuses account_repository/
    # trade_repository/order_repository/snapshot_repository already
    # built above -- never second instances. The one and only
    # production entry point for real Trade attribution.
    trade_attribution_service = TradeAttributionService(
        account_repository=account_repository,
        trade_repository=trade_repository,
        order_repository=order_repository,
        snapshot_repository=snapshot_repository,
        trade_attribution_engine=trade_attribution_engine,
        trade_holding_period_engine=trade_holding_period_engine,
    )

    # Activation 7: Performance Per Strategy production wiring.
    # position_episode_replay_engine is the new, pure engine that
    # replays this graph's existing trade_holding_period_engine
    # (built above) -- never a second/new holding-period computation.
    position_episode_replay_engine = PositionEpisodeReplayEngine(
        trade_holding_period_engine
    )
    # strategy_performance_engine is the new, pure, no-arg aggregator
    # (mirrors trade_holding_period_engine/position_performance_engine
    # above) -- aggregates already-resolved (strategy, realized_pnl)
    # outcomes, never reads Position/Trade/Order itself.
    strategy_performance_engine = StrategyPerformanceEngine()
    # strategy_performance_service is the new, thin Activation 7
    # orchestrator: supplies position_episode_replay_engine/
    # strategy_performance_engine with real, account-scoped
    # trades/orders/positions. Reuses account_repository/
    # trade_repository/order_repository/position_repository already
    # built above -- never second instances. The one and only
    # production entry point for real performance-per-strategy.
    strategy_performance_service = StrategyPerformanceService(
        account_repository=account_repository,
        trade_repository=trade_repository,
        order_repository=order_repository,
        position_repository=position_repository,
        position_episode_replay_engine=position_episode_replay_engine,
        strategy_performance_engine=strategy_performance_engine,
    )

    # ACTIVATION 7 (this session): Performance Per Market Regime
    # production wiring -- resolves ONLY the roadmap conflict recorded
    # in the Activation 7 closeout report ("Market-condition evidence
    # -- OPEN GAP"). market_regime_engine is the new, pure, no-arg
    # deterministic classifier (mirrors strategy_performance_engine's
    # own no-dependency style). A dedicated StockDataRepository is
    # constructed here (hermetic -- no yfinance import/connection at
    # construction time, per that class's own docstring) rather than
    # reusing the one already private to _build_analysis_pipeline(),
    # so this addition touches no existing StockService/analysis-
    # pipeline wiring at all.
    market_regime_engine = MarketRegimeEngine()
    market_regime_stock_repository = StockDataRepository()
    market_regime_service = MarketRegimeService(
        stock_data_repository=market_regime_stock_repository,
        market_regime_engine=market_regime_engine,
    )
    market_regime_performance_engine = MarketRegimePerformanceEngine()
    # market_regime_attribution_service reuses this graph's existing
    # position_episode_replay_engine/account_repository/
    # trade_repository/position_repository/watchlist_repository --
    # never second instances. The one and only production entry point
    # for real performance-per-market-regime and market-condition
    # variety.
    market_regime_attribution_service = MarketRegimeAttributionService(
        account_repository=account_repository,
        trade_repository=trade_repository,
        position_repository=position_repository,
        watchlist_repository=watchlist_repository,
        position_episode_replay_engine=position_episode_replay_engine,
        market_regime_service=market_regime_service,
        market_regime_performance_engine=market_regime_performance_engine,
    )

    # Phase G Task 5 ("Paper Review CLI + End-to-End Proof"): give the
    # already-complete, LOCKED PaperReviewService (Phase G Task 4) its
    # first real production entry point. Purely additive wiring -- the
    # service class itself is untouched. Three fresh, stateless
    # repository handles over this graph's own shared database_manager
    # (never a second DatabaseManager, mirrors _build_journal_service's
    # own reasoning for why a second repository instance here is not a
    # second table); every other collaborator below
    # (account_repository/order_repository/trade_repository/
    # strategy_performance_service/market_regime_attribution_service/
    # portfolio_snapshot_repository) reuses this graph's exact existing
    # shared instance, never a second copy.
    paper_review_journal_repository = JournalRepository(database_manager)
    paper_review_decision_brief_repository = DecisionBriefRepository(database_manager)
    paper_review_brief_approval_repository = BriefApprovalRepository(database_manager)
    paper_review_service = PaperReviewService(
        account_repository=account_repository,
        journal_repository=paper_review_journal_repository,
        decision_brief_repository=paper_review_decision_brief_repository,
        brief_approval_repository=paper_review_brief_approval_repository,
        order_repository=order_repository,
        trade_repository=trade_repository,
        strategy_performance_service=strategy_performance_service,
        market_regime_attribution_service=market_regime_attribution_service,
        portfolio_snapshot_repository=portfolio_snapshot_repository,
    )

    # Phase H Task 3 ("Sustained-Use Review Report"): give the
    # already-complete, LOCKED SustainedUseReviewService (Phase H Task
    # 2) its first real production entry point, plus the new,
    # additive-only SustainedUseReportService that turns its result
    # into a durable, human-readable text report. See
    # _build_sustained_use_review_service for the full reasoning.
    sustained_use_review_service = _build_sustained_use_review_service(
        database_manager,
        paper_review_service=paper_review_service,
        reconciliation_engine=reconciliation_engine,
        portfolio_snapshot_repository=portfolio_snapshot_repository,
    )
    sustained_use_report_service = SustainedUseReportService()

    # Phase H Task 4 ("Operator Feedback + Final Review Record"): give
    # operator feedback and the deliberate human CONTINUE/SIMPLIFY/
    # AUTHORIZE_FUTURE_INVESTIGATION decision their first real
    # production entry point, over the already-complete, LOCKED
    # sustained_use_review_service built immediately above. See
    # _build_sustained_use_final_review_service for the full reasoning.
    sustained_use_final_review_service = _build_sustained_use_final_review_service(
        database_manager,
        sustained_use_review_service=sustained_use_review_service,
    )

    # Activation 12 Scheduler, atomic step 1: construct the single
    # production AutonomousScheduler instance for this graph. Purely
    # additive construction -- mirrors every other bare, no-argument-
    # dependency singleton this function already builds (e.g.
    # ``ObservationRecorder()`` above). Starts with an empty FIFO
    # queue, unpaused; nothing here schedules or ticks it. See
    # ApplicationGraph.scheduler's own docstring for the full contract.
    scheduler = AutonomousScheduler()

    # Phase E Task 6 ("Wire the existing Telegram inbound control
    # plane"): built last, after manual_scan_service/
    # decision_brief_service/journal_service/
    # performance_summary_production_service/notification_service
    # (all already built above) -- reuses every one of those five
    # instances, never a second/new copy of any. Reuses
    # database_manager (same shared instance as every other Repository
    # above) for the two Telegram Repositories. See
    # _build_telegram_command_audit_repository() /
    # _build_telegram_inbound_state_repository() /
    # _build_telegram_allowlist_policy() /
    # _build_telegram_command_executor() /
    # _build_telegram_inbound_control_plane() and this class's own
    # telegram_* fields. Purely additive: nothing above this line reads
    # any of these five new instances, and this block calls none of
    # their methods (construction only -- no ``poll_once()`` call,
    # no network I/O).
    telegram_command_audit_repository = _build_telegram_command_audit_repository(database_manager)
    telegram_inbound_state_repository = _build_telegram_inbound_state_repository(database_manager)
    telegram_allowlist_policy = _build_telegram_allowlist_policy()
    telegram_command_executor = _build_telegram_command_executor(
        manual_scan_service,
        decision_brief_service,
        journal_service,
        performance_summary_production_service,
    )
    telegram_inbound_control_plane = _build_telegram_inbound_control_plane(
        telegram_allowlist_policy,
        telegram_command_executor,
        telegram_command_audit_repository,
        telegram_inbound_state_repository,
        notification_service,
    )

    logger.debug(f"Composition root: object graph assembled (agent='{agent_name}')")

    return ApplicationGraph(
        config=config,
        tool_registry=tool_registry,
        provider_manager=provider_manager,
        service_registry=service_registry,
        agent_registry=agent_registry,
        executor=executor,
        planner=planner,
        agent=agent,
        database_manager=database_manager,
        runtime_analysis_pipeline=runtime_analysis_pipeline,
        service_skills=service_skills,
        goal_planner=goal_planner,
        observation_recorder=observation_recorder,
        memory_store=memory_store,
        memory_recorder=memory_recorder,
        reflector=reflector,
        decision_engine=decision_engine,
        decision_policy=decision_policy,
        policy_guard=policy_guard,
        execution_intent=execution_intent,
        execution_planner=execution_planner,
        execution_coordinator=execution_coordinator,
        portfolio_engine=portfolio_engine,
        portfolio_risk=portfolio_risk,
        learning_loop=learning_loop,
        autonomous_agent=autonomous_agent,
        agent_name=agent_name,
        provider_name=resolved_provider_name,
        provider_kind=resolved_provider_kind,
        gemini_vision_provider=gemini_vision_provider,
        vision_market_state_pipeline=vision_market_state_pipeline,
        trading_decision_agent=trading_decision_agent,
        account_repository=account_repository,
        watchlist_repository=watchlist_repository,
        market_analysis_agent=market_analysis_agent,
        position_repository=position_repository,
        order_repository=order_repository,
        trade_repository=trade_repository,
        snapshot_repository=snapshot_repository,
        decision_brief_service=decision_brief_service,
        risk_limits_repository=risk_limits_repository,
        journal_service=journal_service,
        idx_daily_scheduler=idx_daily_scheduler,
        health_audit_service=health_audit_service,
        performance_repository=performance_repository,
        order_lifecycle_service=order_lifecycle_service,
        execution_service=execution_service,
        account_balance_service=account_balance_service,
        position_manager=position_manager,
        order_idempotency_repository=order_idempotency_repository,
        order_approval_repository=order_approval_repository,
        paper_trading_engine=paper_trading_engine,
        manual_scan_service=manual_scan_service,
        notification_builder=notification_builder,
        telegram_notification_channel=telegram_notification_channel,
        notification_dispatcher=notification_dispatcher,
        notification_manager=notification_manager,
        market_price_tool=market_price_tool,
        unrealized_pnl_engine=unrealized_pnl_engine,
        portfolio_snapshot_repository=portfolio_snapshot_repository,
        portfolio_snapshot_service=portfolio_snapshot_service,
        performance_summary_service=performance_summary_service,
        performance_summary_production_service=performance_summary_production_service,
        trade_holding_period_engine=trade_holding_period_engine,
        trade_attribution_engine=trade_attribution_engine,
        trade_attribution_service=trade_attribution_service,
        position_episode_replay_engine=position_episode_replay_engine,
        strategy_performance_engine=strategy_performance_engine,
        strategy_performance_service=strategy_performance_service,
        market_regime_engine=market_regime_engine,
        market_regime_service=market_regime_service,
        market_regime_performance_engine=market_regime_performance_engine,
        market_regime_attribution_service=market_regime_attribution_service,
        daily_report_orchestrator=daily_report_orchestrator,
        reconciliation_engine=reconciliation_engine,
        execution_rate_engine=execution_rate_engine,
        failure_rate_engine=failure_rate_engine,
        paper_execution_tool_resolver=paper_execution_tool_resolver,
        copilot_tool_resolver=copilot_tool_resolver,
        market_tool_manager=market_tool_manager,
        scheduler=scheduler,
        telegram_command_audit_repository=telegram_command_audit_repository,
        telegram_inbound_state_repository=telegram_inbound_state_repository,
        telegram_allowlist_policy=telegram_allowlist_policy,
        telegram_command_executor=telegram_command_executor,
        telegram_inbound_control_plane=telegram_inbound_control_plane,
        paper_review_service=paper_review_service,
        observation_window_service=observation_window_service,
        sustained_use_review_service=sustained_use_review_service,
        sustained_use_report_service=sustained_use_report_service,
        sustained_use_final_review_service=sustained_use_final_review_service,
    )