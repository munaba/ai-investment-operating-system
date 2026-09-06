"""ServiceSkill -- generic per-Service Tool wrapper (Stage L13, "Granular
Skills", Phase 1: Runtime kernel gains the *capability* to call any one of
the 11 Services individually).

Scope note (LOCKED baseline, approved Diff-Level Plan FINAL): L13 is not
about a Planner and not about a "Brain". It only makes each Service
individually callable as a Tool. The production ``StockAgent`` call path
is untouched by this module:

    User -> StockAgent -> RuntimeAnalysisPipeline -> Runtime ->
    AnalysisPipeline -> 11 Services

``AnalysisPipeline`` is not split, no Service is modified, and nothing in
this module is wired into that path. ``ServiceSkill`` instances are only
constructed and registered by ``Core.composition_root`` alongside it, for
a future stage (L14, Planner) to discover and use.

This module implements two LOCKED design decisions ("Option D" = "Option
A", approved):

  1. ``SkillMetadata`` is purely declarative. It is a literal transcription
     of the dependency graph already found by the L13 source audit -- not
     a newly-derived graph, not inferred, not discovered via reflection.
     It has NO behavior: no validation, no parsing, no dependency
     resolution, no scheduling. It is read (never enforced) by this
     module. Only a future Planner (L14) is allowed to actually *read and
     act on* it.
  2. ``ServiceSkill`` is one generic, non-specialized wrapper class used
     11 times (one instance per Service) -- never subclassed per Service.
     Its behavior is limited to exactly: building a ``ServiceContext``,
     calling ``service.execute(context)``, passthrough ``health_check()``,
     and exposing its own metadata/tool_name. It never merges context,
     never resolves a dependency, never transforms a ``ServiceResult``,
     and never applies Service-specific formatting.

Debt deliberately NOT addressed here (LOCKED, see L13 Technical Risk /
handover):

  - R3: ``Agents.sandbox.GenericSandbox``'s JSON-encode fallback
    (``str(result)``) for non-JSON-serializable Tool return values is
    unchanged. A ``ServiceSkill``'s Tool handler returns a
    ``ServiceResult`` (not JSON-serializable: it may carry an
    ``Optional[Exception]`` and arbitrary ``data``) -- if a future caller
    drives it through ``Executor.execute()`` (Runtime), that value will
    be stringified by the existing, unmodified fallback. Not fixed here.
  - R4: Context accumulation (SS5 in ``Core/analysis_pipeline.py`` --
    "flat" + "nested" metadata propagation across the 11-step chain) is
    not moved, copied, or reimplemented here. A single ``ServiceSkill``
    call only ever sees whatever ``metadata`` its own caller passes in --
    it has no notion of "the prior step's output".
  - ``RiskManagementService`` keeps its own precondition
    (``ENTRY_PRICE``/``STOP_LOSS_PERCENT``/``TAKE_PROFIT_PERCENT``/
    ``RISK_PER_TRADE_PERCENT``/``ACCOUNT_BALANCE`` must already be in
    ``metadata``). ``Core.analysis_pipeline.AnalysisPipeline.
    _prepare_risk_management_context`` (PRICE -> ENTRY_PRICE translation
    + simulation defaults) is pipeline-level behavior, out of scope for
    this file, and is NOT reimplemented as a special case here -- calling
    ``ServiceSkill(risk_management_service, ...).execute(...)`` directly,
    without that translation having already happened, fails exactly the
    same way calling ``RiskManagementService.execute()`` directly always
    has.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from Services.base_service import BaseService
from Services.metadata_keys import MetadataKeys
from Services.service_context import ServiceContext
from Services.service_result import ServiceResult


@dataclass(frozen=True)
class SkillMetadata:
    """Purely declarative description of one Service, for a future
    Planner (L14) to read.

    A literal transcription of the L13 source audit's DAG findings --
    every field below is copied from what the wrapped Service's own
    ``execute()`` actually reads from / writes into
    ``ServiceContext.metadata`` (see ``Core/analysis_pipeline.py`` and
    each Service's own module for the source of truth). Nothing here is
    inferred or auto-discovered.

    This class intentionally has NO methods beyond the ones a
    ``@dataclass`` generates for free (``__init__``, ``__eq__``,
    ``__repr__``). No validator, no parser, no dependency resolver, no
    scheduler -- see module docstring, decision #1.

    Attributes:
        service_name: The wrapped Service's own ``BaseService.name``.
        required_inputs: ``ServiceContext.metadata`` keys the Service
            cannot produce a successful result without (per its own
            ``execute()`` -- an explicit ``ServiceResult.fail(...)`` when
            absent). Where a Service accepts "at least one of" several
            keys (``FundamentalService``, ``PatternService``), all of
            those keys are listed here as-is -- this field does not
            encode "at least one" vs. "all of" semantics; that
            distinction lives only in the Service's own ``execute()``,
            unchanged.
        optional_inputs: ``ServiceContext.metadata`` keys the Service
            reads but has its own default for, or otherwise tolerates
            being absent/``None``.
        produced_outputs: Keys present in ``ServiceResult.data`` on a
            successful ``execute()`` call.
    """

    service_name: str
    required_inputs: Tuple[str, ...]
    optional_inputs: Tuple[str, ...]
    produced_outputs: Tuple[str, ...]


class ServiceSkill:
    """Generic, non-specialized Tool wrapper around exactly one
    ``BaseService`` (LOCKED design, decision #2 -- see module docstring).

    One class, instantiated once per Service (11 times in production, via
    ``Core.composition_root._build_service_skills``) -- never subclassed.
    Holds only its two constructor-injected collaborators; carries no
    per-call state.
    """

    def __init__(self, service: BaseService, metadata: SkillMetadata) -> None:
        """Wire up the wrapper via dependency injection only.

        Args:
            service: The already-constructed Service instance to wrap.
                Never constructed here -- ``Core.composition_root`` passes
                in the same instance already held by ``ServiceRegistry``,
                so this never creates a second instance of a Service.
            metadata: The declarative :class:`SkillMetadata` describing
                ``service``. Not validated against ``service`` in any way
                (see module docstring, decision #1) -- keeping them
                accurate is the caller's responsibility.
        """
        self._service = service
        self._metadata = metadata

    @property
    def metadata(self) -> SkillMetadata:
        """Expose this skill's declarative :class:`SkillMetadata`."""
        return self._metadata

    @property
    def tool_name(self) -> str:
        """Stable Tool name this skill should be registered under.

        Derived from ``metadata.service_name`` only (e.g.
        ``"stock_service"`` -> ``"skill.stock_service"``) -- unlike
        ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``'s
        private, UUID-suffixed per-call Tool name, this name is stable
        and standing: it does not change between calls.
        """
        return f"skill.{self._metadata.service_name}"

    def execute(
        self,
        *,
        user_input: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        agent_name: str = "",
        provider_name: str = "",
        request_id: Optional[str] = None,
    ) -> ServiceResult:
        """Build a ``ServiceContext`` from the given arguments and run the
        wrapped Service for it.

        This is the whole of ``ServiceSkill``'s behavior (module
        docstring, decision #2): build context, call
        ``service.execute(context)``, return whatever it returns --
        unmodified. No merging of ``metadata`` with any other context, no
        reading of ``self._metadata`` to validate/resolve/fill anything,
        no transformation of the returned ``ServiceResult``.

        Args:
            user_input: Passed straight through to
                ``ServiceContext.user_input``. Defaults to ``""`` --
                this wrapper has no notion of "the user's message"; a
                future caller (e.g. a Planner) supplies it if relevant.
            metadata: Passed straight through to
                ``ServiceContext.metadata`` (defaults to ``{}`` when
                omitted). This is the only way inputs reach the wrapped
                Service -- exactly the keys the Service's own
                ``execute()`` reads, same as calling it directly.
            agent_name: Passed straight through to
                ``ServiceContext.agent_name``. Defaults to ``""`` --
                this wrapper is not owned by any particular agent.
            provider_name: Passed straight through to
                ``ServiceContext.provider_name``. Defaults to ``""``.
            request_id: Passed straight through to
                ``ServiceContext.request_id``. Defaults to a freshly
                minted ``uuid4`` string when omitted, so every call is
                still traceable even if the caller supplies none.

        Returns:
            The ``ServiceResult`` returned by ``service.execute()``,
            unmodified.
        """
        context = ServiceContext(
            agent_name=agent_name,
            provider_name=provider_name,
            request_id=request_id if request_id is not None else str(uuid.uuid4()),
            user_input=user_input,
            metadata=metadata or {},
        )
        return self._service.execute(context)

    def health_check(self) -> bool:
        """Passthrough to the wrapped Service's own ``health_check()``.

        No aggregation, no interpretation -- returns exactly what
        ``service.health_check()`` returns.
        """
        return self._service.health_check()


#: Literal transcription of the L13 source audit's per-Service dependency
#: graph (LOCKED baseline, decision #1 -- see module docstring). Every key
#: below is copied from the corresponding Service's own ``execute()``
#: body (``Services/<name>.py``) or from ``Core/analysis_pipeline.py``'s
#: fixed 11-step wiring order -- nothing here is inferred, discovered, or
#: derived by this module at import time or otherwise.
#:
#: "required" vs. "optional" reflects each Service's *own*, unchanged
#: ``execute()`` behavior: a key is "required" if its absence is checked
#: for explicitly and produces a failed ``ServiceResult`` (see each
#: Service's own ``if ... is None: return ServiceResult.fail(...)``); a
#: key is "optional" if the Service reads it via
#: ``context.get_metadata(key, <default>)`` and tolerates a missing/None
#: value without failing. Where a Service requires "at least one of"
#: several keys (``fundamental_service``, ``pattern_service``), all of
#: those keys are listed under ``required_inputs`` as-is -- see
#: :class:`SkillMetadata`'s own docstring on why that nuance is not
#: separately encoded here (no behavior beyond declarative storage).
#:
#: Keys with no producer anywhere in the fixed pipeline ("metadata
#: yatim" per the L13 audit -- ``PER_SECTOR_AVG``, ``ROE_SECTOR_AVG``,
#: ``AVG_RETURN``) are listed here exactly as any other input: this
#: mapping only records what each Service itself reads, not who (if
#: anyone) produces it.
#:
#: The first 11 entries below are the fixed ``AnalysisPipeline`` steps
#: (L13 baseline, unchanged). ``notification_service`` (Task 3) is a
#: 12th, independent entry -- a second domain outside that pipeline,
#: added without changing any of the 11 or the shape of this dict.
SKILL_METADATA_BY_SERVICE: Dict[str, SkillMetadata] = {
    "stock_service": SkillMetadata(
        service_name="stock_service",
        required_inputs=(),
        optional_inputs=(
            MetadataKeys.TICKER,
            MetadataKeys.PERIOD,
            MetadataKeys.INTERVAL,
        ),
        produced_outputs=(
            MetadataKeys.TICKER,
            MetadataKeys.HISTORY,
            MetadataKeys.INFO,
            MetadataKeys.PRICE,
            MetadataKeys.PER,
            MetadataKeys.ROE,
            MetadataKeys.DIVIDEND_YIELD,
        ),
    ),
    "technical_indicator_service": SkillMetadata(
        service_name="technical_indicator_service",
        required_inputs=(MetadataKeys.HISTORY,),
        optional_inputs=(),
        produced_outputs=(
            MetadataKeys.RSI,
            MetadataKeys.MACD,
            MetadataKeys.MACD_SIGNAL,
            MetadataKeys.BOLLINGER_UPPER,
            MetadataKeys.BOLLINGER_LOWER,
            MetadataKeys.ATR,
            MetadataKeys.OBV,
        ),
    ),
    "moving_average_service": SkillMetadata(
        service_name="moving_average_service",
        required_inputs=(MetadataKeys.HISTORY,),
        optional_inputs=(),
        produced_outputs=(
            MetadataKeys.MA20,
            MetadataKeys.MA50,
            MetadataKeys.MA200,
        ),
    ),
    "technical_score_service": SkillMetadata(
        service_name="technical_score_service",
        required_inputs=(MetadataKeys.PRICE,),
        optional_inputs=(
            MetadataKeys.RSI,
            MetadataKeys.MA20,
            MetadataKeys.MA50,
            MetadataKeys.MA200,
            MetadataKeys.BOLLINGER_UPPER,
            MetadataKeys.BOLLINGER_LOWER,
        ),
        produced_outputs=(MetadataKeys.TECHNICAL_SCORE,),
    ),
    "fundamental_service": SkillMetadata(
        service_name="fundamental_service",
        # At least one of PER / ROE / DIVIDEND_YIELD is required by
        # FundamentalService.execute() -- see module docstring on why
        # that nuance is not separately encoded here.
        required_inputs=(
            MetadataKeys.PER,
            MetadataKeys.ROE,
            MetadataKeys.DIVIDEND_YIELD,
        ),
        optional_inputs=(
            MetadataKeys.PER_SECTOR_AVG,
            MetadataKeys.ROE_SECTOR_AVG,
        ),
        produced_outputs=(MetadataKeys.FUNDAMENTAL_SCORE,),
    ),
    "backtest_service": SkillMetadata(
        service_name="backtest_service",
        required_inputs=(MetadataKeys.HISTORY,),
        optional_inputs=(
            MetadataKeys.STRATEGY,
            MetadataKeys.INITIAL_CAPITAL,
            MetadataKeys.FAST_PERIOD,
            MetadataKeys.SLOW_PERIOD,
        ),
        produced_outputs=(
            MetadataKeys.STRATEGY,
            MetadataKeys.TOTAL_RETURN,
            MetadataKeys.FINAL_CAPITAL,
            MetadataKeys.TOTAL_TRADE,
            MetadataKeys.WIN_RATE,
            MetadataKeys.TRADE_HISTORY,
        ),
    ),
    "pattern_service": SkillMetadata(
        service_name="pattern_service",
        # At least one of WIN_RATE / AVG_RETURN is required by
        # PatternService.execute() -- same nuance as fundamental_service
        # above. AVG_RETURN ("rata_rata_return") is one of the L13
        # audit's orphan metadata keys: no Service in the fixed pipeline
        # produces it (see module-level docstring above).
        required_inputs=(
            MetadataKeys.WIN_RATE,
            MetadataKeys.AVG_RETURN,
        ),
        optional_inputs=(),
        produced_outputs=(MetadataKeys.PATTERN_SCORE,),
    ),
    "chart_service": SkillMetadata(
        service_name="chart_service",
        required_inputs=(MetadataKeys.HISTORY,),
        optional_inputs=(
            MetadataKeys.TICKER,
            MetadataKeys.INDICATORS,
            MetadataKeys.IMAGE_PATH,
        ),
        produced_outputs=(
            MetadataKeys.FIGURE,
            MetadataKeys.IMAGE_PATH,
            MetadataKeys.CHART_METADATA,
        ),
    ),
    "news_service": SkillMetadata(
        service_name="news_service",
        required_inputs=(),
        optional_inputs=(
            MetadataKeys.TICKER,
            MetadataKeys.MAX_NEWS,
        ),
        produced_outputs=(
            MetadataKeys.TICKER,
            MetadataKeys.NEWS,
            MetadataKeys.TOTAL_NEWS,
        ),
    ),
    "risk_management_service": SkillMetadata(
        service_name="risk_management_service",
        # Identical to AnalysisPipeline's own required_fields list in
        # Core/analysis_pipeline.py -- RiskManagementService.execute()'s
        # own precondition, unchanged and NOT pre-filled here (see module
        # docstring: AnalysisPipeline's PRICE -> ENTRY_PRICE translation
        # + simulation defaults are pipeline-level behavior, out of scope
        # for ServiceSkill).
        required_inputs=(
            MetadataKeys.ENTRY_PRICE,
            MetadataKeys.STOP_LOSS_PERCENT,
            MetadataKeys.TAKE_PROFIT_PERCENT,
            MetadataKeys.RISK_PER_TRADE_PERCENT,
            MetadataKeys.ACCOUNT_BALANCE,
        ),
        optional_inputs=(),
        produced_outputs=(
            MetadataKeys.STOP_LOSS_PRICE,
            MetadataKeys.TAKE_PROFIT_PRICE,
            MetadataKeys.RISK_AMOUNT,
            MetadataKeys.POSITION_SIZE,
            MetadataKeys.RISK_REWARD_RATIO,
        ),
    ),
    "scoring_service": SkillMetadata(
        service_name="scoring_service",
        required_inputs=(
            MetadataKeys.TECHNICAL_SCORE,
            MetadataKeys.FUNDAMENTAL_SCORE,
            MetadataKeys.PATTERN_SCORE,
        ),
        optional_inputs=(),
        produced_outputs=(
            MetadataKeys.TECHNICAL_SCORE,
            MetadataKeys.FUNDAMENTAL_SCORE,
            MetadataKeys.PATTERN_SCORE,
            MetadataKeys.OVERALL_SCORE,
            MetadataKeys.LABEL,
        ),
    ),
    # --- Task 3 ("Second Skill / Cross-Skill Reflection Foundation") ---
    # NotificationService is not one of the 11 fixed AnalysisPipeline steps
    # (it has no place in that chain and is not constructed by
    # _build_analysis_pipeline) -- it is a second, independent domain
    # (outbound notification) that already existed, fully implemented and
    # tested (Tests/integration_test.py), but stayed unregistered/unwired
    # per this module's own L13-era note. Wrapping it as a ServiceSkill,
    # exactly like the 11 pipeline entries above, is the entire scope of
    # Task 3: no new abstraction, no BaseSkill, no subclassing.
    #
    # ``channel`` decides which credential set NotificationService.execute()
    # actually requires (``webhook_url`` for "discord";
    # ``telegram_bot_token``/``telegram_chat_id`` for "telegram") -- the
    # same "required_inputs does not encode conditional/at-least-one-of
    # semantics" nuance already documented on SkillMetadata itself for
    # fundamental_service/pattern_service above. Only CHANNEL and MESSAGE
    # are unconditionally required by every call; the three
    # channel-specific fields are listed as optional here, exactly as
    # that documented nuance prescribes.
    "notification_service": SkillMetadata(
        service_name="notification_service",
        required_inputs=(
            MetadataKeys.CHANNEL,
            MetadataKeys.MESSAGE,
        ),
        optional_inputs=(
            MetadataKeys.TITLE,
            MetadataKeys.IMAGE_PATH,
            MetadataKeys.WEBHOOK_URL,
            MetadataKeys.TELEGRAM_BOT_TOKEN,
            MetadataKeys.TELEGRAM_CHAT_ID,
        ),
        # NotificationService.execute() returns {"channel": ..., "status":
        # ..., "response": ...} -- "status"/"response" have no
        # MetadataKeys constants (they are literal dict keys in the
        # service's own return, not ServiceContext.metadata inputs read
        # by any other service), so they are listed here as the literal
        # strings the service itself uses.
        produced_outputs=(
            MetadataKeys.CHANNEL,
            "status",
            "response",
        ),
    ),
}