from __future__ import annotations

from dataclasses import dataclass

from Core.exceptions import AgentError


class LearningLoopError(AgentError):
    """Raised when LearningLoop.learn() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used elsewhere
    in the codebase (ReflectionError, DecisionEngineError,
    DecisionPolicyError, PolicyGuardError, ExecutionIntentError,
    ExecutionPlannerError, ExecutionCoordinatorError,
    PortfolioEngineError, PortfolioRiskError), rather than deriving
    from the bare Exception class.
    """
    pass


@dataclass(frozen=True)
class LearningLoopResult:
    """Immutable result of LearningLoop.learn().

    Stage L27 is intentionally minimal: a deterministic pass-through of
    an already-assessed portfolio risk result into a structured
    learning-signal record. No model update, no weight adjustment, no
    background/autonomous behaviour, no persistence, no reference back
    to whatever produced the portfolio risk result it was given --
    LearningLoopResult only describes a single recorded learning signal
    for a future stage to act on.
    """
    recorded: bool
    signal: str
    violation_count: int
    notes: str


class LearningLoop:
    """Pure component that turns a PortfolioRiskResult-shaped object
    into a LearningLoopResult.

    Design constraints (Stage L27, following the exact L18/L19/L20/L21/
    L22/L23/L24/L25/L26 additive pattern):
        - Deterministic: same portfolio risk result always produces the
          same LearningLoopResult.
        - No LLM calls.
        - No Provider dependency.
        - No Database dependency.
        - No Service dependency.
        - No Executor dependency.
        - No Runtime, Scheduler, or EventBus dependency.

    LearningLoop never constructs, imports, or references any of the
    above, and does not import composition_root, Executor, Runtime,
    Database, StockAgent, or any other Orchestration module (its only
    project import is ``Core.exceptions.AgentError``). It receives a
    plain ``portfolio_risk_result`` object (with ``approved``,
    ``exposure_level``, ``diversification_level``, and ``violations``
    attributes -- the same shape as
    ``Orchestration.portfolio_risk.PortfolioRiskResult``, accessed
    purely by duck typing, never imported) and returns a single
    ``LearningLoopResult`` per call. It is not wired into StockAgent,
    RuntimeAnalysisPipeline, DecisionEngine, DecisionPolicy, PolicyGuard,
    ExecutionIntent, ExecutionPlanner, ExecutionCoordinator,
    PortfolioEngine, PortfolioRisk, or ApplicationGraph's production
    call path -- it exists only as a standalone component, for a future
    stage to wire up. There is no autonomous or background loop of any
    kind: ``learn()`` processes exactly one input and returns exactly
    one result, synchronously, with no scheduling, polling, retry, or
    state carried between calls.

    Behavior:
        - When ``approved`` is True: ``recorded=True``,
          ``signal="POSITIVE"``, ``violation_count=0``, and ``notes``
          summarizes the approved outcome, including the input's
          ``exposure_level``/``diversification_level``.
        - When ``approved`` is False: ``recorded=True``,
          ``signal="NEGATIVE"``, ``violation_count`` is the length of
          the input's ``violations`` sequence, and ``notes`` summarizes
          the rejected outcome and the violation count.

    LearningLoop does not update any model, adjust any weight, place an
    order, call Runtime, call Executor, call Database, call Providers,
    call Services, or touch any execution surface -- it only produces a
    structured, immutable, single-shot learning-signal record.

    Sprint 41 -- ``__init__(memory=None)`` gives a ``LearningLoop``
    instance an optional collaborator to forward completed learning
    output to; this is the *only* new surface Sprint 41 adds, and it
    extends the existing constructor rather than introducing a new
    public method. ``LearningLoop`` still never imports, constructs,
    or references ``MemoryStore``, ``MemoryRecorder``, or any other
    ``Orchestration.memory`` symbol -- the accepted object is
    validated purely by duck typing (it must expose a callable
    ``add`` attribute, the same primitive
    ``Orchestration.memory.MemoryStore`` already exposes) and stored
    as an opaque ``self._memory`` reference. Omitting ``memory`` (the
    default) stores nothing on ``self`` at all
    (``getattr(self, "_memory", None)`` is used to read it), so a
    ``LearningLoop()`` built with no arguments remains exactly as
    attribute-free as before Sprint 41 (``vars(LearningLoop()) == {}``
    still holds -- see Stage L27's own I10). When a memory collaborator
    *is* attached, ``learn()`` calls ``memory.add(...)`` with the
    ``LearningLoopResult`` it just produced, exactly once, after that
    result is fully built -- ``learn()`` performs no storage itself;
    it only forwards its own, unchanged output. ``LearningLoop``
    remains the only caller of ``Memory``; it never becomes a database
    and never duplicates ``MemoryStore``'s own storage logic.
    """

    def __init__(self, memory=None) -> None:
        """
        Args:
            memory: optional. Any object exposing a callable ``add``
                attribute (e.g. an ``Orchestration.memory.MemoryStore``
                instance) -- accepted purely by duck typing, so this
                constructor (and ``LearningLoop`` generally) never
                imports, constructs, or references ``MemoryStore`` or
                ``MemoryRecorder`` itself. When given, ``learn()``
                forwards every ``LearningLoopResult`` it produces to
                ``memory.add(...)``. When omitted (the default),
                ``LearningLoop`` behaves exactly as before Sprint 41
                -- no attribute is even stored on ``self``.

        Raises:
            LearningLoopError: if ``memory`` is given but does not
                expose a callable ``add`` attribute.
        """
        if memory is not None:
            if not callable(getattr(memory, "add", None)):
                raise LearningLoopError(
                    f"LearningLoop()'s memory argument must expose a "
                    f"callable 'add' method; got {memory!r}"
                )
            self._memory = memory

    def learn(self, portfolio_risk_result) -> LearningLoopResult:
        try:
            approved = portfolio_risk_result.approved
            exposure_level = portfolio_risk_result.exposure_level
            diversification_level = portfolio_risk_result.diversification_level
            violations = portfolio_risk_result.violations
        except AttributeError as exc:
            raise LearningLoopError(
                "LearningLoop.learn() expects a portfolio risk result "
                "object with 'approved', 'exposure_level', "
                "'diversification_level', and 'violations' attributes"
            ) from exc

        try:
            if approved:
                signal = "POSITIVE"
                violation_count = 0
                notes = (
                    f"learning signal recorded: approved outcome "
                    f"(exposure_level={exposure_level}, "
                    f"diversification_level={diversification_level})"
                )
            else:
                signal = "NEGATIVE"
                violation_count = len(violations)
                notes = (
                    f"learning signal recorded: rejected outcome "
                    f"({violation_count} violation(s))"
                )

            result = LearningLoopResult(
                recorded=True,
                signal=signal,
                violation_count=violation_count,
                notes=notes,
            )
        except LearningLoopError:
            raise
        except Exception as exc:
            raise LearningLoopError(
                f"Unexpected failure while building learning loop result: {exc}"
            ) from exc

        # Sprint 41 -- forward the just-built, unchanged
        # LearningLoopResult to the attached memory collaborator (if
        # any). This is the only place learning output ever reaches
        # Memory, and it happens exactly once per learn() call --
        # LearningLoop performs no storage of its own here, it only
        # hands its finished output onward via Memory's own existing
        # add() primitive.
        memory = getattr(self, "_memory", None)
        if memory is not None:
            memory.add(result)

        return result