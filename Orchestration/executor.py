from __future__ import annotations

from Core.exceptions import AgentError
from Orchestration.autonomous_host import AutonomousHost
from Orchestration.execution_session import ExecutionSession, ExecutionSessionError
from Orchestration.skill_context import SkillContext
from Orchestration.skill_execution_plan import SkillExecutionPlan
from Orchestration.skill_resolver import SkillResolver
from Orchestration.task_manager import TaskManager
from Orchestration.tool_context import ToolContext
from Orchestration.tool_invocation import ToolInvocation
from Orchestration.tool_resolver import ToolResolver


class ExecutorError(AgentError):
    """Raised when ``Executor`` is given invalid inputs, either at
    construction time or when ``execute()`` is called.

    Mirrors the existing exception hierarchy (``AgentError``) used
    elsewhere in the codebase (``WorkflowEngineError``,
    ``WorkflowManagerError``, ``TaskError``, ``TaskQueueError``,
    ``TaskManagerError``, ``AutonomousSchedulerError``,
    ``AutonomousHostError``, ``AutonomousAgentError``,
    ``EventBusError``, and others), rather than deriving from the
    bare ``Exception`` class.
    """

    pass


class Executor:
    """Sprint 30 -- the component responsible for consuming prepared
    ``Task`` instances from a ``TaskManager`` and delegating their
    execution to an ``AutonomousHost``.

    Sprint 32 temporarily added an ``execute_workflow()`` convenience
    method that imported ``WorkflowEngine``/``ExecutionContext``
    directly, coupling this generic execution component to the
    Workflow stack's preparation concerns. Sprint 33 (Executor
    Decoupling) removes that method and those imports again:
    workflow preparation-then-execution is now driven from outside
    ``Executor`` by ``Orchestration.workflow_execution_coordinator.
    WorkflowExecutionCoordinator``, which calls
    ``WorkflowEngine.prepare()`` and this class's unmodified
    ``execute()`` in turn. ``Executor`` itself no longer knows that
    ``WorkflowEngine`` or ``Workflow`` exist.

    ``Executor`` owns exactly two collaborator references -- the
    single ``TaskManager`` and the single ``AutonomousHost`` it was
    constructed with -- and nothing else. It holds no ``Task`` state
    of its own, never reads or writes ``Task.status`` or
    ``Workflow.status``, and never imports, references, or calls
    ``Orchestration.workflow_manager.WorkflowManager``,
    ``Orchestration.workflow.Workflow``,
    ``Orchestration.workflow_engine.WorkflowEngine``,
    ``Orchestration.execution_context.ExecutionContext``,
    ``Orchestration.task_queue.TaskQueue`` (it only ever reaches the
    queue indirectly, through ``TaskManager``'s own public API),
    ``Orchestration.autonomous_scheduler.AutonomousScheduler``,
    ``Orchestration.autonomous_agent.AutonomousAgent``,
    ``Orchestration.runtime_analysis_pipeline.RuntimeAnalysisPipeline``,
    ``Orchestration.event_bus.EventBus``, or the Composition Root.

    ``execute()`` is deliberately the simplest possible synchronous
    consume-and-delegate loop: obtain the next ``Task`` from the
    bound ``TaskManager`` (preserving whatever FIFO order the
    ``TaskManager`` itself already guarantees); if a ``SkillResolver``
    was injected at construction time, resolve the ``Task`` via it
    first (Sprint 45 -- exactly one ``resolve()`` call per ``Task``,
    before the delegated ``start()`` call; the resolved object is
    never inspected, called, or executed by this class); then hand
    the ``Task`` to the bound ``AutonomousHost`` via exactly one
    ``start()`` call, and repeat -- stopping the moment the queue is
    empty or the requested number of iterations has been reached. If
    no ``SkillResolver`` was injected, resolution is skipped entirely
    (Sprint 45A -- ``Executor`` never constructs a ``SkillResolver``
    or ``SkillRegistry`` itself; that is the Composition Root's job).
    There is no retry, no dependency graph, no branching, no
    persistence, no threading, and no asyncio anywhere in this
    module -- this is a pure, synchronous execution layer. ``context``
    is accepted and passed through as a plain, opaque ``object`` --
    ``Executor`` does not require it to be an ``ExecutionContext`` or
    any other specific type.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        host: AutonomousHost,
        skill_resolver: SkillResolver | None = None,
        tool_resolver: ToolResolver | None = None,
    ) -> None:
        """Construct an ``Executor`` bound to a single ``TaskManager``,
        a single ``AutonomousHost``, and an optional ``SkillResolver``.

        Args:
            task_manager: the ``TaskManager`` this executor will pull
                ``Task`` instances from. Must not be ``None`` and must
                be a ``TaskManager`` instance.
            host: the ``AutonomousHost`` this executor will delegate
                execution to. Must not be ``None`` and must be an
                ``AutonomousHost`` instance.
            skill_resolver: the ``SkillResolver`` this executor will
                use to resolve each dequeued ``Task`` before
                delegating to ``host``. Optional -- defaults to
                ``None``. When ``None``, ``Executor`` performs no
                resolution at all: it behaves exactly as it did before
                Sprint 45 (``Task`` goes straight to
                ``AutonomousHost.start()``). ``Executor`` never
                constructs a ``SkillResolver`` or ``SkillRegistry``
                itself under any circumstances -- building those
                collaborators is the Composition Root's responsibility,
                not this class's. If a non-``None`` value is provided,
                it must be a ``SkillResolver`` instance.
            tool_resolver: an optional ``ToolResolver`` this executor
                merely hands to the currently selected Skill (Phase 8
                Sprint 84 -- Skill Tool Resolution Boundary). Never
                constructed here, never called by ``Executor`` itself
                (``Executor`` still never resolves or executes a
                Tool) -- it is stored purely so it can be injected
                into the Skill as a callable in
                ``invoke_current_skill()``. Optional -- defaults to
                ``None``. If a non-``None`` value is provided, it
                must be a ``ToolResolver`` instance.

        Raises:
            ExecutorError: if ``task_manager`` is ``None`` or is not a
                ``TaskManager`` instance, if ``host`` is ``None`` or
                is not an ``AutonomousHost`` instance, if
                ``skill_resolver`` is provided (non-``None``) but is
                not a ``SkillResolver`` instance, or if
                ``tool_resolver`` is provided (non-``None``) but is
                not a ``ToolResolver`` instance.
        """
        if task_manager is None:
            raise ExecutorError(
                "Executor requires a non-None 'task_manager'"
            )

        if not isinstance(task_manager, TaskManager):
            raise ExecutorError(
                f"Executor requires 'task_manager' to be a TaskManager "
                f"instance; got {task_manager!r}"
            )

        if host is None:
            raise ExecutorError("Executor requires a non-None 'host'")

        if not isinstance(host, AutonomousHost):
            raise ExecutorError(
                f"Executor requires 'host' to be an AutonomousHost "
                f"instance; got {host!r}"
            )

        if skill_resolver is not None and not isinstance(
            skill_resolver, SkillResolver
        ):
            raise ExecutorError(
                f"Executor requires 'skill_resolver' to be a "
                f"SkillResolver instance or None; got {skill_resolver!r}"
            )

        if tool_resolver is not None and not isinstance(
            tool_resolver, ToolResolver
        ):
            raise ExecutorError(
                f"Executor requires 'tool_resolver' to be a "
                f"ToolResolver instance or None; got {tool_resolver!r}"
            )

        self._task_manager: TaskManager = task_manager
        self._host: AutonomousHost = host
        self._skill_resolver: SkillResolver | None = skill_resolver
        self._tool_resolver: ToolResolver | None = tool_resolver

    def execute(self, context: object, iterations: int = 1) -> int:
        """Consume and execute up to ``iterations`` ``Task`` instances
        from the bound ``TaskManager``, in FIFO order.

        Repeatedly calls ``TaskManager.next_task()`` to obtain the
        next ``Task`` (preserving whatever order the ``TaskManager``
        itself returns tasks in). If a ``SkillResolver`` was injected
        at construction time, makes exactly one call to
        ``SkillResolver.resolve(task)`` before the delegated call --
        with the resolved object discarded, never inspected, called,
        or executed. If no ``SkillResolver`` was injected, this step
        is skipped entirely. Either way, follows with exactly one
        delegated call to ``AutonomousHost.start(task, context, 1)``.
        Stops as soon as either the bound ``TaskManager`` reports no
        pending tasks (``has_tasks()`` is ``False``), or ``iterations``
        ``Task`` instances have been executed -- whichever happens
        first.

        Args:
            context: the value passed unchanged as the second
                positional argument to every delegated
                ``AutonomousHost.start()`` call this method makes.
                Must not be ``None``.
            iterations: the maximum number of ``Task`` instances to
                execute in this call. Must be an ``int`` >= 1
                (``bool`` is rejected even though it is technically an
                ``int`` subclass). Defaults to ``1``.

        Returns:
            The number of ``Task`` instances actually executed --
            this may be fewer than ``iterations`` if the bound
            ``TaskManager`` ran out of pending tasks first.

        Raises:
            ExecutorError: if ``context`` is ``None``, or if
                ``iterations`` is not an ``int`` >= 1 (including when
                it is a ``bool``). No ``Task`` is dequeued and no
                ``AutonomousHost.start()`` call is made when this
                validation fails.
        """
        if context is None:
            raise ExecutorError(
                "Executor.execute() requires a non-None 'context'"
            )

        if (
            not isinstance(iterations, int)
            or isinstance(iterations, bool)
            or iterations < 1
        ):
            raise ExecutorError(
                "Executor.execute() requires 'iterations' to be an "
                f"int >= 1; got {iterations!r}"
            )

        executed = 0
        while executed < iterations:
            if not self._task_manager.has_tasks():
                break

            task = self._task_manager.next_task()
            if self._skill_resolver is not None:
                self._skill_resolver.resolve(task)
            self._host.start(task, context, 1)
            executed += 1

        return executed

    def has_pending_tasks(self) -> bool:
        """Return whether the bound ``TaskManager`` currently has at
        least one ``Task`` waiting to be executed.

        Delegates directly to ``TaskManager.has_tasks()``.

        Returns:
            ``True`` if at least one ``Task`` is waiting, ``False``
            otherwise.
        """
        return self._task_manager.has_tasks()

    def execute_plan(self, plan: SkillExecutionPlan) -> None:
        """Accept a ``SkillExecutionPlan``, validate its type, wrap it
        in a pending ``ExecutionSession``, and store that session by
        identity (Phase 6 Sprint 73, Executor stores an
        ExecutionSession, not a raw SkillExecutionPlan -- still no
        execution).

        This is deliberately the simplest possible accept-validate-
        wrap-store operation (LOCKED scope for this sprint): it only
        ever checks ``isinstance(plan, SkillExecutionPlan)`` and then
        assigns ``self._current_plan = ExecutionSession(plan=plan,
        state="pending", metadata={})`` -- the given ``plan`` is
        wrapped by identity (never copied or cloned) inside a freshly
        constructed ``ExecutionSession``. It never iterates
        ``plan.skills`` or ``plan.tools``, never reads or inspects
        ``plan.metadata``, never inspects the ``ExecutionSession`` it
        just built, never executes a skill or a tool, never calls
        ``AutonomousHost``, ``TaskManager``, ``SkillResolver``,
        ``ToolResolver``, ``Runtime``, ``Workflow``, or ``EventBus``,
        and never mutates ``plan`` in any way. ``execute()``,
        ``has_pending_tasks()``, and this class's constructor are all
        completely untouched by this addition.

        Args:
            plan: The ``SkillExecutionPlan`` to accept and wrap. Must
                be a ``SkillExecutionPlan`` instance.

        Returns:
            ``None``, always.

        Raises:
            ExecutorError: if ``plan`` is not a ``SkillExecutionPlan``
                instance. ``self._current_plan`` is left completely
                unchanged when validation fails -- a rejected call
                never overwrites a previously stored session.
        """
        if not isinstance(plan, SkillExecutionPlan):
            raise ExecutorError(
                f"Executor.execute_plan() requires 'plan' to be a "
                f"SkillExecutionPlan instance; got {plan!r}"
            )

        self._current_plan = ExecutionSession(
            plan=plan, state="pending", metadata={}
        )
        return None

    def prepare_session(self) -> None:
        """Advance the currently stored ``ExecutionSession`` from
        ``pending`` to ``ready`` (Phase 6 Sprint 74 -- controlled
        session state transitions; execution remains disabled).

        This is deliberately the simplest possible read-transition-
        store operation (LOCKED scope for this sprint): it requires
        that ``self._current_plan`` already exists (set by a prior
        ``execute_plan()`` call), then replaces it with
        ``self._current_plan = self._current_plan.with_state
        ("ready")`` -- the one sanctioned ``ExecutionSession``
        transition method, which itself returns a brand-new instance
        rather than mutating the existing one. It never iterates
        ``plan.skills`` or ``plan.tools``, never reads or inspects
        ``plan.metadata``, never executes a skill or a tool, never
        calls ``AutonomousHost``, ``TaskManager``, ``SkillResolver``,
        ``ToolResolver``, ``Runtime``, ``Workflow``, or ``EventBus``,
        and never mutates the existing ``ExecutionSession`` (or its
        wrapped ``plan``) in any way. ``execute()``,
        ``has_pending_tasks()``, ``execute_plan()``, and this class's
        constructor are all completely untouched by this addition.

        Returns:
            ``None``, always.

        Raises:
            ExecutorError: if ``self._current_plan`` does not exist
                yet (no prior successful ``execute_plan()`` call).
        """
        if not hasattr(self, "_current_plan"):
            raise ExecutorError(
                "Executor.prepare_session() requires an existing "
                "'_current_plan'; call execute_plan() first"
            )

        self._current_plan = self._current_plan.with_state("ready")
        return None

    def start_session(self) -> None:
        """Advance the currently stored ``ExecutionSession`` from
        ``ready`` to ``running`` (Phase 7 Sprint 75 -- execution
        lifecycle: ``pending`` -> ``ready`` -> ``running``; execution
        of a Skill or Tool remains completely disabled).

        This is deliberately the simplest possible read-transition-
        store operation (LOCKED scope for this sprint): it requires
        that ``self._current_plan`` already exists (set by a prior
        ``execute_plan()`` call), then replaces it with
        ``self._current_plan = self._current_plan.start()`` -- the
        one sanctioned ``ExecutionSession.start()`` transition method,
        which itself returns a brand-new instance rather than
        mutating the existing one. It never iterates ``plan.skills``
        or ``plan.tools``, never reads or inspects ``plan.metadata``,
        never executes a skill or a tool, never calls
        ``AutonomousHost``, ``TaskManager``, ``SkillResolver``,
        ``ToolResolver``, ``Runtime``, ``Workflow``, or ``EventBus``,
        and never mutates the existing ``ExecutionSession`` (or its
        wrapped ``plan``) in any way. ``execute()``,
        ``has_pending_tasks()``, ``execute_plan()``,
        ``prepare_session()``, and this class's constructor are all
        completely untouched by this addition.

        Returns:
            ``None``, always.

        Raises:
            ExecutorError: if ``self._current_plan`` does not exist
                yet (no prior successful ``execute_plan()`` call).
                Note: if a session exists but is not in state
                ``"ready"``, the underlying
                ``ExecutionSession.start()`` call raises
                ``ExecutionSessionError`` instead, which propagates
                unchanged.
        """
        if not hasattr(self, "_current_plan"):
            raise ExecutorError(
                "Executor.start_session() requires an existing "
                "'_current_plan'; call execute_plan() first"
            )

        self._current_plan = self._current_plan.start()
        return None

    def advance_skill(self) -> None:
        """Advance the currently stored ``ExecutionSession``'s
        execution cursor by one position (Phase 7 Sprint 76 -- the
        current-skill cursor; still no Skill is executed and
        ``plan.skills`` is never read).

        This is deliberately the simplest possible read-transition-
        store operation (LOCKED scope for this sprint): it requires
        that ``self._current_plan`` already exists (set by a prior
        ``execute_plan()`` call), then replaces it with
        ``self._current_plan = self._current_plan.advance()`` -- the
        one sanctioned ``ExecutionSession.advance()`` transition
        method, which itself returns a brand-new instance rather than
        mutating the existing one. It never iterates ``plan.skills``
        or ``plan.tools``, never reads or inspects ``plan.metadata``,
        never performs bounds checking against the number of skills in
        the wrapped plan, never executes a skill or a tool, never
        calls ``AutonomousHost``, ``TaskManager``, ``SkillResolver``,
        ``ToolResolver``, ``Runtime``, ``Workflow``, or ``EventBus``,
        introduces no loop of any kind, and never mutates the existing
        ``ExecutionSession`` (or its wrapped ``plan``) in any way.
        ``execute()``, ``has_pending_tasks()``, ``execute_plan()``,
        ``prepare_session()``, ``start_session()``, and this class's
        constructor are all completely untouched by this addition.

        Returns:
            ``None``, always.

        Raises:
            ExecutorError: if ``self._current_plan`` does not exist
                yet (no prior successful ``execute_plan()`` call).
                Note: if a session exists but is not in state
                ``"running"``, the underlying
                ``ExecutionSession.advance()`` call raises
                ``ExecutionSessionError`` instead, which propagates
                unchanged.
        """
        if not hasattr(self, "_current_plan"):
            raise ExecutorError(
                "Executor.advance_skill() requires an existing "
                "'_current_plan'; call execute_plan() first"
            )

        self._current_plan = self._current_plan.advance()
        return None

    def current_skill(self):
        """Return the currently selected Skill from the currently
        stored ``ExecutionSession`` (Phase 7 Sprint 77 -- Current
        Skill Selection; still no Skill is executed, no Tool is
        executed, and no metadata is inspected).

        This is deliberately the simplest possible read-only
        accessor (LOCKED scope for this sprint): it requires that
        ``self._current_plan`` already exists (set by a prior
        ``execute_plan()`` call) and that its ``state`` is already
        ``"running"``, then reads exactly
        ``self._current_plan.plan.skills`` and
        ``self._current_plan.current_skill_index`` and returns
        ``plan.skills[current_skill_index]`` exactly -- the selected
        Skill object itself, never copied, cloned, or wrapped. It
        never iterates ``plan.skills`` or ``plan.tools``, never reads
        or inspects ``plan.metadata``, never performs a bounds check
        against the number of skills in the wrapped plan, never
        calls ``Skill.execute()`` or any other method on the returned
        object, never inspects tools or metadata, never calls
        ``AutonomousHost``, ``TaskManager``, ``SkillResolver``,
        ``ToolResolver``, ``Runtime``, ``Workflow``, ``EventBus``, or
        ``Planner``, and never mutates the existing
        ``ExecutionSession`` (or its wrapped ``plan``) in any way.
        ``execute()``, ``has_pending_tasks()``, ``execute_plan()``,
        ``prepare_session()``, ``start_session()``,
        ``advance_skill()``, and this class's constructor are all
        completely untouched by this addition.

        Returns:
            The Skill object at ``plan.skills[current_skill_index]``,
            returned exactly -- no copy, no wrapper.

        Raises:
            ExecutorError: if ``self._current_plan`` does not exist
                yet (no prior successful ``execute_plan()`` call).
            ExecutionSessionError: if a session exists but its
                ``state`` is not ``"running"`` -- raised directly by
                this method (there is no underlying
                ``ExecutionSession`` method to propagate it from),
                mirroring the same exception type already used by
                ``ExecutionSession.start()``/``ExecutionSession.
                advance()`` for the same kind of invalid-state
                condition.
        """
        if not hasattr(self, "_current_plan"):
            raise ExecutorError(
                "Executor.current_skill() requires an existing "
                "'_current_plan'; call execute_plan() first"
            )

        if self._current_plan.state != "running":
            raise ExecutionSessionError(
                f"Executor.current_skill() requires the current "
                f"session to be 'running'; got "
                f"{self._current_plan.state!r}"
            )

        return self._current_plan.plan.skills[
            self._current_plan.current_skill_index
        ]

    def invoke_current_skill(self):
        """Construct exactly one ``SkillContext``, invoke the
        currently selected Skill with it, and propagate whatever it
        returns completely unchanged (Phase 7 Sprint 79 -- SkillContext
        Invocation; Phase 7 Sprint 80 -- SkillResult Propagation, which
        binds ``skill.execute(context)``'s return value to a local
        before returning it, but performs no inspection, isinstance
        check, attribute access, wrapping, copying, or caching of that
        value -- it is treated as completely opaque, whether it is a
        ``SkillResult``, ``None``, an ``int``, a ``str``, a ``dict``,
        or any other arbitrary object).

        This is deliberately the simplest possible select-construct-
        invoke operation (LOCKED scope for this sprint): it obtains
        the currently selected Skill via exactly one
        ``self.current_skill()`` call (reusing that method's own
        existing-session/running-state checks rather than duplicating
        them), reads ``self._current_plan.plan.tools`` exactly once
        into a local ``tool_names`` (Phase 8 Sprint 83 -- Skill Tool
        Discovery; the exact tuple object is read, never iterated,
        indexed, copied, or normalized here), defines exactly one
        local, zero-argument ``tool_context_factory`` function that,
        when called, constructs and returns exactly one
        ``Orchestration.tool_context.ToolContext`` instance --
        ``ToolContext(task=None, parameters={}, metadata={})`` --
        (Phase 8 Sprint 82 -- ToolContext Factory Construction; this
        construction still performs no ``Tool`` lookup, execution, or
        wiring through ``ToolRegistry``/``ToolResolver``/
        ``ToolManager`` -- it is a pure value-object build, never
        invoked by this method itself), constructs exactly one
        ``Orchestration.skill_context.SkillContext`` instance --
        ``SkillContext(task=None, parameters={}, metadata={},
        tool_context_factory=tool_context_factory)`` -- (the tool
        list is deliberately not threaded through ``SkillContext``
        itself; its constructor is unchanged) sets exactly one
        attribute, ``skill._tool_names = tool_names``, via a single
        ``setattr()`` call immediately before invoking the Skill, and
        invokes the Skill exactly once via ``skill.execute(context)``,
        returning its result unchanged. It never constructs a
        ``Task`` or a ``Workflow`` itself, never inspects
        ``plan.metadata``, never iterates or indexes ``plan.tools``
        or ``tool_names``, never deduplicates or normalizes them,
        never iterates ``plan.skills``, never calls
        ``advance_skill()``, never mutates ``self._current_plan`` or
        any of its fields, and never calls ``AutonomousHost``,
        ``TaskManager``, ``SkillResolver``, ``ToolResolver``,
        ``ToolManager``, ``ToolRegistry``, ``Runtime``, ``Workflow``,
        or ``Planner``. There is no try/except, no wrapper, no
        normalization, and no caching anywhere in this method.

        Phase 8 Sprint 84 -- Skill Tool Resolution Boundary: if a
        ``ToolResolver`` was injected at construction time, defines
        exactly one additional local, single-argument function
        ``resolve_tool(name)`` that does nothing but return
        ``self._tool_resolver.resolve(name)``, and sets exactly one
        additional attribute, ``skill._resolve_tool = resolve_tool``,
        via a single ``setattr()`` call, immediately after
        ``_tool_names`` is set and strictly before
        ``skill.execute(context)`` is invoked. ``Executor`` never
        calls ``resolve_tool(...)`` or ``self._tool_resolver.resolve(
        ...)`` itself -- only the Skill may call the injected
        callable, and only once it has been handed ``context`` via
        ``execute()``. If no ``ToolResolver`` was injected, this step
        is skipped entirely and behavior is identical to Sprint 83.
        This still resolves nothing and executes no Tool -- it merely
        hands the Skill a way to ask for one later.
        ``execute()``, ``has_pending_tasks()``, ``execute_plan()``,
        ``prepare_session()``, ``start_session()``, ``advance_skill()``,
        ``current_skill()``, and this class's constructor are all
        completely untouched by this addition.

        Returns:
            Whatever ``skill.execute(context)`` returns, propagated
            unchanged and unexamined -- the exact same object by
            identity, never a copy or a wrapper, regardless of its
            type.

        Raises:
            ExecutorError: if ``self._current_plan`` does not exist
                yet (no prior successful ``execute_plan()`` call) --
                raised by the delegated ``self.current_skill()`` call.
            ExecutionSessionError: if a session exists but its
                ``state`` is not ``"running"`` -- raised by the
                delegated ``self.current_skill()`` call.
            Exception: any exception raised while constructing the
                ``SkillContext`` (for example ``SkillContextError``)
                or by ``skill.execute(context)`` itself propagates
                unchanged.
        """
        skill = self.current_skill()
        tool_names = self._current_plan.plan.tools

        def tool_context_factory():
            return ToolContext(
                task=None,
                parameters={},
                metadata={},
            )

        context = SkillContext(
            task=None,
            parameters={},
            metadata={},
            tool_context_factory=tool_context_factory,
        )
        setattr(skill, "_tool_names", tool_names)
        if self._tool_resolver is not None:
            def resolve_tool(name):
                return self._tool_resolver.resolve(name)
            setattr(skill, "_resolve_tool", resolve_tool)
        result = skill.execute(context)
        return result

    def current_tool_invocation(self):
        """Return the ``ToolInvocation`` corresponding to the first
        tool name declared for the currently selected Skill (Phase 8
        Sprint 95 REVISED -- Current ToolInvocation Exposure; still no
        Tool is resolved, no Tool is executed, and nothing is cached).

        This is deliberately the simplest possible boundary-only
        accessor (LOCKED scope for this sprint): it obtains the
        currently selected Skill via exactly one
        ``self.current_skill()`` call -- reusing that method's own
        existing-session/running-state checks exactly the way
        ``invoke_current_skill()`` already does, rather than
        duplicating them -- then reads ``skill._tool_names`` exactly
        once into a local ``tool_names``. If the current skill has no
        ``_tool_names`` attribute at all, or if ``tool_names`` is
        empty, this method raises ``ExecutorError`` -- there is no
        Tool to build a valid ``ToolInvocation`` for. Otherwise it
        constructs and returns exactly one
        ``Orchestration.tool_invocation.ToolInvocation`` instance:
        ``ToolInvocation(tool_name=tool_names[0], context=None,
        metadata={})`` -- the first declared tool name, preserved by
        identity, never normalized, deduplicated, or otherwise
        transformed.

        It never calls ``ToolResolver`` or ``self._tool_resolver``,
        never performs a Tool lookup, never calls ``Tool.execute()``,
        never constructs a ``ToolContext``, and never calls
        ``Runtime``, ``Workflow``, ``Planner``, ``Registry``,
        ``Manager``, or ``Service``. It never caches or stores the
        constructed ``ToolInvocation`` anywhere, never mutates
        ``self._current_plan`` or the current ``ExecutionSession``,
        and never modifies the current skill cursor. There is no
        try/except and no exception wrapping anywhere in this method.
        ``execute()``, ``has_pending_tasks()``, ``execute_plan()``,
        ``prepare_session()``, ``start_session()``,
        ``advance_skill()``, ``current_skill()``,
        ``invoke_current_skill()``, and this class's constructor are
        all completely untouched by this addition.

        Returns:
            A freshly constructed ``ToolInvocation`` instance --
            ``ToolInvocation(tool_name=tool_names[0], context=None,
            metadata={})`` -- returned by identity, never copied or
            wrapped.

        Raises:
            ExecutorError: if ``self._current_plan`` does not exist
                yet (no prior successful ``execute_plan()`` call), or
                if a session exists but its ``state`` is not
                ``"running"`` -- both raised by the delegated
                ``self.current_skill()`` call. Also raised directly
                by this method if the current skill has no
                ``_tool_names`` attribute, or if ``_tool_names`` is
                empty.
        """
        skill = self.current_skill()
        if not hasattr(skill, "_tool_names"):
            raise ExecutorError(
                "Executor.current_tool_invocation() requires the "
                "current skill to have '_tool_names' set"
            )

        tool_names = skill._tool_names
        if len(tool_names) == 0:
            raise ExecutorError(
                "Executor.current_tool_invocation() requires the "
                "current skill's '_tool_names' to be non-empty"
            )

        invocation = ToolInvocation(
            tool_name=tool_names[0],
            context=None,
            metadata={},
        )
        return invocation

    def resolve_current_tool(self):
        """Resolve the ``ToolInvocation`` for the currently selected
        Skill to a concrete Tool object (Phase 8 Sprint 96 -- Executor
        <-> ToolResolver Integration; still no Tool is executed, no
        ``ToolContext``/``SkillContext`` is constructed, and nothing
        is cached).

        This is deliberately the simplest possible resolve-only
        accessor (LOCKED scope for this sprint): it obtains the
        current ``ToolInvocation`` via exactly one
        ``self.current_tool_invocation()`` call -- reusing that
        method's own existing-session/running-state/``_tool_names``
        checks rather than duplicating them (which in turn makes
        exactly one ``self.current_skill()`` call internally, so this
        method itself never calls ``current_skill()`` a second time)
        -- then, if ``self._tool_resolver`` was not injected at
        construction time, raises ``ExecutorError`` immediately.
        Otherwise it makes exactly one delegated call,
        ``self._tool_resolver.resolve(invocation.tool_name)``, and
        returns whatever it returns completely unchanged.

        It never calls ``Tool.execute()``, never constructs a
        ``ToolContext`` or ``SkillContext``, and never calls
        ``Runtime``, ``Workflow``, ``Planner``, ``Registry``,
        ``Manager``, ``Repository``, or ``Service``. It never caches
        or stores the resolved Tool anywhere, never retries the
        resolution, never wraps or inspects the resolved Tool or any
        exception ``self._tool_resolver.resolve(...)`` raises, and
        never logs anything. It never mutates ``self._current_plan``,
        the current ``ExecutionSession``, the skill cursor, or
        session state. ``execute()``, ``has_pending_tasks()``,
        ``execute_plan()``, ``prepare_session()``, ``start_session()``,
        ``advance_skill()``, ``current_skill()``,
        ``invoke_current_skill()``, ``current_tool_invocation()``, and
        this class's constructor are all completely untouched by this
        addition.

        Returns:
            The exact Tool object returned by
            ``self._tool_resolver.resolve(invocation.tool_name)`` --
            returned by identity, never copied or wrapped.

        Raises:
            ExecutorError: if ``self._current_plan`` does not exist
                yet, if a session exists but its ``state`` is not
                ``"running"``, or if the current skill has no
                (non-empty) ``_tool_names`` -- all raised by the
                delegated ``self.current_tool_invocation()`` call.
                Also raised directly by this method if no
                ``ToolResolver`` was injected at construction time
                (``self._tool_resolver`` is ``None``).
            Exception: any exception raised by
                ``self._tool_resolver.resolve(...)`` itself propagates
                unchanged.
        """
        invocation = self.current_tool_invocation()
        if self._tool_resolver is None:
            raise ExecutorError(
                "Executor.resolve_current_tool() requires a "
                "ToolResolver to have been injected at construction "
                "time"
            )

        tool = self._tool_resolver.resolve(invocation.tool_name)
        return tool

    def execute_current_tool(self):
        """Resolve, construct a ``ToolContext`` for, and execute the
        Tool bound to the currently selected Skill -- exactly once
        (Phase 8 Sprint 97 -- Tool Invocation Pipeline Completion;
        still no Runtime, no Workflow, no Planner, no Composition
        Root, and no inspection of the returned ``ToolResult``).

        This is deliberately the simplest possible resolve-then-
        execute accessor (LOCKED scope for this sprint): it obtains
        the concrete Tool via exactly one
        ``self.resolve_current_tool()`` call -- reusing that method's
        own existing-session/running-state/``_tool_names``/resolver
        checks rather than duplicating any of them -- then constructs
        exactly one ``Orchestration.tool_context.ToolContext``
        instance with the fixed arguments ``task=None``,
        ``parameters={}``, ``metadata={}``, then makes exactly one
        delegated call, ``tool.execute(context)``, and returns
        whatever it returns completely unchanged.

        It never calls ``Runtime``, ``Workflow``, ``Planner``,
        ``Registry``, ``Manager``, ``Repository``, or ``Service``. It
        never inspects, wraps, copies, caches, or logs the returned
        ``ToolResult``, never retries the call, and never checks the
        result's ``success``, ``output``, ``error``, or ``metadata``
        fields. It never mutates ``self._current_plan``, the current
        ``ExecutionSession``, the skill cursor, or session state.
        ``execute()``, ``has_pending_tasks()``, ``execute_plan()``,
        ``prepare_session()``, ``start_session()``,
        ``advance_skill()``, ``current_skill()``,
        ``invoke_current_skill()``, ``current_tool_invocation()``,
        ``resolve_current_tool()``, and this class's constructor are
        all completely untouched by this addition.

        Returns:
            The exact ``ToolResult`` (or whatever else) returned by
            ``tool.execute(context)`` -- returned by identity, never
            copied or wrapped.

        Raises:
            ExecutorError: propagated unchanged from
                ``self.resolve_current_tool()`` (missing session,
                non-running session, missing/empty ``_tool_names``,
                or no ``ToolResolver`` injected).
            Exception: any exception raised while constructing the
                ``ToolContext`` (for example, ``ToolContextError``),
                or any exception raised by
                ``self._tool_resolver.resolve(...)`` (propagated via
                ``resolve_current_tool()``), or any exception raised
                by ``tool.execute(context)`` itself, all propagate
                unchanged.
        """
        tool = self.resolve_current_tool()
        context = ToolContext(
            task=None,
            parameters={},
            metadata={},
        )
        result = tool.execute(context)
        return result

    def execute_current_skill(self):
        """Execute the currently selected Skill directly and return
        whatever it returns, completely unchanged (Phase 9 Sprint 101
        -- Executor / Skill Integration; the first end-to-end
        execution path. Still no Runtime, no Workflow, no Planner,
        and no Composition Root).

        This is deliberately the simplest possible select-and-execute
        operation (LOCKED scope for this sprint): it obtains the
        currently selected Skill via exactly one ``self.current_skill()``
        call (reusing that method's own existing-session/running-state
        checks rather than duplicating them), makes exactly one
        delegated call, ``skill.execute(None)``, and returns whatever
        it returns completely unchanged.

        It never constructs a ``SkillContext`` or ``ToolContext``,
        never calls ``invoke_current_skill()``, never calls
        ``AutonomousHost``, ``TaskManager``, ``SkillResolver``,
        ``ToolResolver``, ``ToolManager``, ``ToolRegistry``,
        ``Runtime``, ``Workflow``, ``Planner``, or the Composition
        Root. It never inspects, wraps, copies, caches, or logs the
        returned ``SkillResult``, never retries the call, and never
        checks the result's ``success``, ``output``, ``error``, or
        ``metadata`` fields. It never mutates ``self._current_plan``,
        the current ``ExecutionSession``, the skill cursor, or
        session state. ``execute()``, ``has_pending_tasks()``,
        ``execute_plan()``, ``prepare_session()``, ``start_session()``,
        ``advance_skill()``, ``current_skill()``,
        ``invoke_current_skill()``, ``current_tool_invocation()``,
        ``resolve_current_tool()``, ``execute_current_tool()``, and
        this class's constructor are all completely untouched by this
        addition.

        Returns:
            The exact ``SkillResult`` (or whatever else) returned by
            ``skill.execute(None)`` -- returned by identity, never
            copied or wrapped.

        Raises:
            ExecutorError: propagated unchanged from
                ``self.current_skill()`` (missing session).
            ExecutionSessionError: propagated unchanged from
                ``self.current_skill()`` (session not ``"running"``).
            Exception: any exception raised by ``skill.execute(None)``
                itself propagates unchanged.
        """
        skill = self.current_skill()
        result = skill.execute(
            None
        )
        return result

    def __repr__(self) -> str:
        """Return an unambiguous, informative representation useful
        for debugging/logs -- the class name plus whether tasks are
        currently pending, mirroring the terse, no-content-dump style
        already used by ``repr()`` elsewhere in this codebase for
        orchestration objects (e.g. ``TaskManager.__repr__``,
        ``WorkflowEngine.__repr__``)."""
        return (
            f"Executor(has_pending_tasks={self._task_manager.has_tasks()})"
        )