from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Tuple

from Core.exceptions import AgentError
from Orchestration.event_bus import Event, EventBus
from Orchestration.memory import MemoryRecord


class ReflectionError(AgentError):
    """Raised when Reflector.reflect() encounters an unexpected failure.

    Mirrors the existing exception hierarchy (AgentError) used
    elsewhere in the codebase, rather than deriving from the bare
    Exception class.
    """
    pass


@dataclass(frozen=True)
class ReflectionRecord:
    """Immutable result of reflecting over a batch of MemoryRecord.

    Deliberately holds only reflection metadata — it does NOT retain
    the input MemoryRecord tuple (or any other storage-shaped copy of
    it). This keeps ReflectionRecord from silently becoming a second
    copy of whatever Memory already holds. Phase 1 is intentionally
    minimal: it establishes the reflect() contract and a
    source_record_count/reflected_at pair; real analysis (success/fail
    ratios, ranking, etc.) is left to a future phase.
    """
    source_record_count: int
    reflected_at: datetime


class Reflector:
    """Pure, stateless component that reflects over MemoryRecord history.

    Reflector never constructs, imports, or references MemoryStore. It
    receives a Tuple[MemoryRecord, ...] from the caller and returns a
    ReflectionRecord. This keeps Reflection decoupled from however
    Memory happens to be stored today (in-memory list) or in the
    future (SQLite, Redis, ChromaDB, etc.) — that decoupling is the
    explicit point of this stage.

    The input tuple is read only to determine its length; it is never
    copied into, or retained by, the returned ReflectionRecord.

    Sprint 39 -- ``attach(event_bus)`` makes ``Reflector`` an
    ``EventBus`` subscriber: it listens for ``"runtime.completed"``
    and ``"runtime.failed"`` (published by ``WorkflowRuntime`` as of
    Sprint 38) and, on either, invokes the exact same ``reflect()``
    already defined above -- there is no second reflection path and
    no new value object. ``Reflector`` still never imports,
    constructs, or references ``WorkflowRuntime``, ``WorkflowEngine``,
    ``Executor``, ``Scheduler``, ``Memory``, or ``LearningLoop``; the
    only new dependency this class takes on is
    ``Orchestration.event_bus`` (``Event``/``EventBus``), which it
    only ever *subscribes to* -- ``attach()`` never mutates
    ``EventBus`` itself beyond the one ``subscribe()`` call per event
    name it documents.

    ``attach()`` keeps ``Reflector`` genuinely stateless: no
    ``event_bus`` reference (or anything else) is stored on ``self``
    -- the subscribed handler is simply a bound method, exactly as
    reusable and inspectable as ``reflect()`` itself.

    Sprint 40 -- ``attach()`` grows one optional keyword argument,
    ``learning_loop``, so ``Reflector`` keeps exactly the same two
    public members (``attach``, ``reflect``) Stage L18/Sprint 39
    already locked -- no third public method is added. Passing
    ``learning_loop=<something>`` gives this ``Reflector`` instance an
    optional collaborator to forward completed reflection output to.
    ``Reflector`` still never imports, constructs, or references
    ``LearningLoop`` -- the accepted object is validated purely by
    duck typing (it must expose a callable ``learn`` attribute) and
    stored as an opaque ``self._learning_loop`` reference. Omitting
    ``learning_loop`` (the default) stores nothing on ``self`` at all
    (``getattr(self, "_learning_loop", None)`` is used to read it), so
    a ``Reflector`` attached without one remains exactly as stateless
    as before Sprint 40. When a learning loop *is* attached,
    ``reflect()`` calls ``learning_loop.learn(...)`` with the
    ``ReflectionRecord`` it just produced, exactly once, after that
    ``ReflectionRecord`` is fully built -- ``reflect()`` performs no
    learning itself; it only forwards its own, unchanged output.
    """

    def attach(self, event_bus: EventBus, learning_loop=None) -> None:
        """Subscribe this ``Reflector`` to ``event_bus``'s
        ``"runtime.completed"`` and ``"runtime.failed"`` events, and
        optionally give it a learning-loop collaborator to forward
        completed ``ReflectionRecord`` output to.

        Every other event name is left entirely alone -- this method
        never calls ``event_bus.subscribe()`` for anything but those
        two, so unrelated events (e.g. ``"runtime.started"``) are
        never delivered to this ``Reflector`` at all.

        Args:
            event_bus: the ``EventBus`` to subscribe to. Must be an
                ``EventBus`` instance.
            learning_loop: optional. Any object exposing a callable
                ``learn`` attribute (e.g. an
                ``Orchestration.learning_loop.LearningLoop`` instance)
                -- accepted purely by duck typing, so this method (and
                ``Reflector`` generally) never imports, constructs, or
                references ``LearningLoop`` itself. When given,
                ``reflect()`` forwards every ``ReflectionRecord`` it
                produces to ``learning_loop.learn(...)``. When omitted
                (the default), ``Reflector`` behaves exactly as before
                Sprint 40 -- no attribute is even stored on ``self``.

        Returns:
            ``None``.

        Raises:
            ReflectionError: if ``event_bus`` is not an ``EventBus``
                instance, or if ``learning_loop`` is given but does
                not expose a callable ``learn`` attribute.
            EventBusError: if this exact ``Reflector`` instance is
                already subscribed to ``"runtime.completed"`` or
                ``"runtime.failed"`` on ``event_bus`` (``EventBus``'s
                own duplicate-subscription guard -- ``attach()``
                introduces no separate mechanism of its own).
        """
        if not isinstance(event_bus, EventBus):
            raise ReflectionError(
                f"Reflector.attach() requires an EventBus instance; got "
                f"{event_bus!r}"
            )

        if learning_loop is not None:
            if not callable(getattr(learning_loop, "learn", None)):
                raise ReflectionError(
                    f"Reflector.attach()'s learning_loop argument must "
                    f"expose a callable 'learn' method; got "
                    f"{learning_loop!r}"
                )
            self._learning_loop = learning_loop

        event_bus.subscribe("runtime.completed", self._on_runtime_event)
        event_bus.subscribe("runtime.failed", self._on_runtime_event)

    def _on_runtime_event(self, event: Event) -> None:
        """Handle one ``"runtime.completed"``/``"runtime.failed"``
        ``Event`` delivered by a subscribed ``EventBus``.

        ``event.payload`` (``workflow_id``/``session_id``/
        ``execution_id``, plus ``exception_type`` on failure) is
        extracted here per the Sprint 39 handler contract, but none of
        those runtime identifiers is a ``MemoryRecord`` -- the
        ``EventBus`` carries no ``MemoryRecord`` history of its own,
        so this sprint does not invent a payload-to-``MemoryRecord``
        mapping (that would be a second reflection path, which Sprint
        39 explicitly forbids). The already-implemented ``reflect()``
        is invoked exactly as-is, over an empty batch.
        """
        payload = event.payload  # noqa: F841 -- extracted per handler contract
        self.reflect(())

    def reflect(self, records: Tuple[MemoryRecord, ...]) -> ReflectionRecord:
        if not isinstance(records, tuple):
            raise ReflectionError(
                f"Reflector.reflect() expects Tuple[MemoryRecord, ...], "
                f"got {type(records).__name__}"
            )

        try:
            # record_count is computed inside the try (not the except)
            # and reused for the error message below, so a records
            # object whose own __len__ raises is (a) caught by this
            # try, and (b) never has len() called on it a second time
            # while building the ReflectionError message -- which
            # would otherwise let that second failure escape raw
            # instead of the documented ReflectionError.
            record_count = len(records)
            reflection_record = ReflectionRecord(
                source_record_count=record_count,
                reflected_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise ReflectionError(
                f"Unexpected failure while reflecting over the given "
                f"record batch: {exc}"
            ) from exc

        # Sprint 40 -- forward the just-built, unchanged
        # ReflectionRecord to the attached learning loop (if any).
        # This is the only place reflection output ever reaches
        # LearningLoop, and it happens exactly once per reflect()
        # call -- reflection performs no learning of its own here,
        # it only hands its finished output onward.
        learning_loop = getattr(self, "_learning_loop", None)
        if learning_loop is not None:
            learning_loop.learn(reflection_record)

        return reflection_record