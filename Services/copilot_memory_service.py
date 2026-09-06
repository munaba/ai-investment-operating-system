"""CopilotMemoryService -- Phase F, Task 5: read-only retrieval from the
existing ``Orchestration.memory.MemoryStore``.

Scope note (LOCKED for this task): this module introduces exactly two
things.

  1. ``CopilotMemoryLookupResult`` -- an immutable value object carrying
     the outcome of a single retrieval call.
  2. ``CopilotMemoryService`` -- a pure, stateless component with one
     read-only method per existing Activation 12 record type
     (``PreferenceRecord``, ``StrategyNoteRecord``,
     ``PreviousDecisionRecord``, ``LessonRecord``,
     ``PortfolioContextRecord``), each answering one of the five
     questions this task lists.

This is the narrowest possible "memory retrieval" slice of the Phase F,
Task 1 copilot contract. It reads an existing, already-populated
``MemoryStore``; it never constructs one, never writes to one, and
never wraps/replaces/extends ``MemoryStore`` or ``MemoryRecorder``.

Explicitly NOT part of this task: any database access (``MemoryStore``
is already in-memory-only -- see its own module docstring -- and this
service never introduces persistence of any kind), a new memory
backend, a write path of any kind (this module has no ``add``/
``record``/``store``/``save`` method anywhere), a provider/LLM call, a
Telegram side effect, a tool/skill invocation, or a paper/live order.
``MemoryStore``/``MemoryRecorder`` and all five record dataclasses in
``Orchestration.memory`` are imported for type-checking and
``isinstance`` discrimination only -- none of their code is modified.

Every field on every returned record is the original object, unchanged
-- this service never copies, reconstructs, or partially extracts a
record's fields; ``CopilotMemoryLookupResult.matches``/``latest`` hold
the exact ``PreferenceRecord``/``StrategyNoteRecord``/etc. instances
already sitting in the ``MemoryStore``, verbatim, including their
original ``record_id``/``recorded_at``/``source``/``reference_id``.
Retrieval never invents a record: a query that matches nothing returns
an explicit ``NOT_FOUND`` result (record type exists in the store but
no record matches the query) or ``EMPTY`` result (no record of that
type exists in the store at all) -- never a synthesized placeholder.

Determinism: for a given, unchanged ``MemoryStore`` and the same query
arguments, every method here always returns bit-for-bit the same
``CopilotMemoryLookupResult`` (same ``matches`` tuple, in the store's
own insertion order, same ``latest``) -- there is no randomness, no
ranking heuristic, and no time-of-call-dependent behavior beyond
``MemoryStore.list()``'s own existing lazy TTL purge (already
deterministic given a fixed ``store``).

Dependency direction: this module imports only the stdlib
``dataclasses``/``typing`` modules plus ``Orchestration.memory``
(``MemoryStore``, ``PreferenceRecord``, ``StrategyNoteRecord``,
``PreviousDecisionRecord``, ``LessonRecord``,
``PortfolioContextRecord``). It does not import from, and is not
imported by, ``Core.composition_root``, any Telegram module,
``Providers``, any tool/skill module, or
``Orchestration.tool_permission``/``permission_context``. It is
additive-only, standing on its own until a future task wires it
behind a copilot-facing entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Type

from Orchestration.memory import (
    LessonRecord,
    MemoryStore,
    PortfolioContextRecord,
    PreferenceRecord,
    PreviousDecisionRecord,
    StrategyNoteRecord,
)

#: The three explicit outcomes a lookup may report. Not an ``Enum`` --
#: kept as plain string literals to mirror the existing Phase-B status
#: convention (``Services.decision_brief_service.STATUS_*``, plain
#: module-level string constants, not an ``Enum``) rather than the
#: separate ``Enum`` convention this codebase also uses elsewhere
#: (``Orchestration.task.TaskStatus``) -- either is an established
#: project convention; strings are chosen here since
#: ``CopilotMemoryLookupResult.status`` is meant to travel unchanged
#: into a future copilot-facing response payload.
STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_EMPTY = "EMPTY"
STATUS_ERROR = "ERROR"


@dataclass(frozen=True)
class CopilotMemoryLookupResult:
    """Immutable outcome of a single ``CopilotMemoryService`` retrieval
    call.

    Attributes:
        success: Whether the lookup itself could be performed at all.
            ``False`` only for invalid input (e.g. ``store`` was not a
            ``MemoryStore``) -- never ``False`` merely because nothing
            matched; ``EMPTY``/``NOT_FOUND`` are both successful,
            fully-answered outcomes.
        status: One of ``STATUS_FOUND``, ``STATUS_NOT_FOUND``,
            ``STATUS_EMPTY``, or ``STATUS_ERROR``.
        record_type: The record class name this lookup targeted (e.g.
            ``"PreferenceRecord"``), carried through regardless of
            outcome.
        query: The optional filter value the caller supplied (a
            preference ``key`` or a free-text keyword), ``None`` if no
            filter was given. Echoed back unchanged for traceability.
        matches: Every matching record, verbatim, in the ``MemoryStore``'s
            own insertion order. Always a tuple -- empty when
            ``status`` is not ``STATUS_FOUND``.
        latest: The single most-recently-recorded record among
            ``matches`` (by ``recorded_at``), verbatim -- a convenience
            for a future copilot layer that wants one answer rather
            than a list. ``None`` unless ``status`` is
            ``STATUS_FOUND``.
        match_count: ``len(matches)``. Always ``0`` unless ``status``
            is ``STATUS_FOUND``.
        error: Human-readable explanation of why ``success`` is
            ``False``. ``None`` whenever ``success`` is ``True``.
    """

    success: bool
    status: str
    record_type: str
    query: Optional[str] = None
    matches: Tuple[Any, ...] = ()
    latest: Optional[Any] = None
    match_count: int = 0
    error: Optional[str] = None


class CopilotMemoryService:
    """Pure, stateless, read-only retrieval layer over an existing
    ``MemoryStore``.

    Holds no state and no collaborators of its own -- construction
    takes no arguments, and every method takes the caller's
    already-constructed ``MemoryStore`` as an explicit argument rather
    than owning or caching one. This service never constructs a
    ``MemoryStore``/``MemoryRecorder``, never calls ``MemoryStore.add``,
    and never mutates anything it is handed. Every method here is a
    thin, deterministic filter over ``MemoryStore.list()``.
    """

    def get_preference(
        self, store: MemoryStore, key: Optional[str] = None
    ) -> CopilotMemoryLookupResult:
        """Answer "what preference did I state?".

        Args:
            store: The ``MemoryStore`` to read from.
            key: Optional ``PreferenceRecord.key`` to filter by,
                matched case-insensitively after stripping whitespace.
                ``None`` (the default) returns every stored preference.

        Returns:
            A ``CopilotMemoryLookupResult`` over every matching
            ``PreferenceRecord``, verbatim.
        """
        return self._lookup(
            store,
            record_cls=PreferenceRecord,
            record_type_name="PreferenceRecord",
            query=key,
            matcher=self._preference_matches,
        )

    def get_strategy_note(
        self, store: MemoryStore, keyword: Optional[str] = None
    ) -> CopilotMemoryLookupResult:
        """Answer "what strategy note did we record?".

        Args:
            store: The ``MemoryStore`` to read from.
            keyword: Optional free-text substring to filter
                ``StrategyNoteRecord.text`` by, matched
                case-insensitively. ``None`` (the default) returns
                every stored strategy note.

        Returns:
            A ``CopilotMemoryLookupResult`` over every matching
            ``StrategyNoteRecord``, verbatim.
        """
        return self._lookup(
            store,
            record_cls=StrategyNoteRecord,
            record_type_name="StrategyNoteRecord",
            query=keyword,
            matcher=self._text_matches,
        )

    def get_previous_decision(
        self, store: MemoryStore, keyword: Optional[str] = None
    ) -> CopilotMemoryLookupResult:
        """Answer "what previous decision is relevant?".

        Args:
            store: The ``MemoryStore`` to read from.
            keyword: Optional free-text substring to filter by, matched
                case-insensitively against either
                ``PreviousDecisionRecord.decision`` or ``.rationale``.
                ``None`` (the default) returns every stored previous
                decision.

        Returns:
            A ``CopilotMemoryLookupResult`` over every matching
            ``PreviousDecisionRecord``, verbatim.
        """
        return self._lookup(
            store,
            record_cls=PreviousDecisionRecord,
            record_type_name="PreviousDecisionRecord",
            query=keyword,
            matcher=self._decision_matches,
        )

    def get_lesson(
        self, store: MemoryStore, keyword: Optional[str] = None
    ) -> CopilotMemoryLookupResult:
        """Answer "what lesson did we record?".

        Args:
            store: The ``MemoryStore`` to read from.
            keyword: Optional free-text substring to filter
                ``LessonRecord.text`` by, matched case-insensitively.
                ``None`` (the default) returns every stored lesson.

        Returns:
            A ``CopilotMemoryLookupResult`` over every matching
            ``LessonRecord``, verbatim.
        """
        return self._lookup(
            store,
            record_cls=LessonRecord,
            record_type_name="LessonRecord",
            query=keyword,
            matcher=self._text_matches,
        )

    def get_portfolio_context(
        self, store: MemoryStore, keyword: Optional[str] = None
    ) -> CopilotMemoryLookupResult:
        """Answer "what portfolio context was stored?".

        Args:
            store: The ``MemoryStore`` to read from.
            keyword: Optional free-text substring to filter
                ``PortfolioContextRecord.text`` by, matched
                case-insensitively. ``None`` (the default) returns
                every stored portfolio context record.

        Returns:
            A ``CopilotMemoryLookupResult`` over every matching
            ``PortfolioContextRecord``, verbatim.
        """
        return self._lookup(
            store,
            record_cls=PortfolioContextRecord,
            record_type_name="PortfolioContextRecord",
            query=keyword,
            matcher=self._text_matches,
        )

    def _lookup(
        self,
        store: MemoryStore,
        *,
        record_cls: Type[Any],
        record_type_name: str,
        query: Optional[str],
        matcher: Callable[[Any, str], bool],
    ) -> CopilotMemoryLookupResult:
        """Shared, deterministic filter-and-classify routine used by
        every public ``get_*`` method.

        Args:
            store: The ``MemoryStore`` to read from.
            record_cls: The concrete record dataclass to filter for
                (e.g. ``PreferenceRecord``), via ``isinstance``.
            record_type_name: ``record_cls.__name__``, passed
                explicitly rather than computed, so the returned
                ``record_type`` is stable even if a caller passes a
                subclass.
            query: The caller's optional filter value, or ``None`` to
                match every record of ``record_cls``.
            matcher: A ``(record, query) -> bool`` predicate applied
                only when ``query`` is not ``None``.

        Returns:
            A ``CopilotMemoryLookupResult`` with ``status`` set to
            ``STATUS_ERROR`` (invalid ``store``), ``STATUS_EMPTY`` (no
            record of ``record_cls`` exists at all),
            ``STATUS_NOT_FOUND`` (records of that type exist but none
            match ``query``), or ``STATUS_FOUND``.
        """
        if not isinstance(store, MemoryStore):
            return CopilotMemoryLookupResult(
                success=False,
                status=STATUS_ERROR,
                record_type=record_type_name,
                query=query,
                error=f"store must be a MemoryStore instance; got {type(store).__name__!r}.",
            )

        all_records = store.list()
        of_type = tuple(
            record for record in all_records if isinstance(record, record_cls)
        )

        if not of_type:
            return CopilotMemoryLookupResult(
                success=True,
                status=STATUS_EMPTY,
                record_type=record_type_name,
                query=query,
            )

        if query is None:
            matched = of_type
        else:
            matched = tuple(record for record in of_type if matcher(record, query))

        if not matched:
            return CopilotMemoryLookupResult(
                success=True,
                status=STATUS_NOT_FOUND,
                record_type=record_type_name,
                query=query,
            )

        latest = max(matched, key=lambda record: record.recorded_at)
        return CopilotMemoryLookupResult(
            success=True,
            status=STATUS_FOUND,
            record_type=record_type_name,
            query=query,
            matches=matched,
            latest=latest,
            match_count=len(matched),
        )

    @staticmethod
    def _preference_matches(record: PreferenceRecord, key: str) -> bool:
        """Match a ``PreferenceRecord`` by ``key``, case-insensitively
        after stripping whitespace from both sides.

        Args:
            record: The ``PreferenceRecord`` to test.
            key: The caller's filter value.

        Returns:
            ``True`` if ``record.key`` matches ``key``.
        """
        if not isinstance(key, str):
            return False
        return record.key.strip().lower() == key.strip().lower()

    @staticmethod
    def _text_matches(record: Any, keyword: str) -> bool:
        """Match any single-``text``-field record (``StrategyNoteRecord``/
        ``LessonRecord``/``PortfolioContextRecord``) by substring,
        case-insensitively.

        Args:
            record: The record to test. Must expose a ``text``
                attribute.
            keyword: The caller's filter value.

        Returns:
            ``True`` if ``keyword`` is a case-insensitive substring of
            ``record.text``.
        """
        if not isinstance(keyword, str) or keyword.strip() == "":
            return False
        return keyword.strip().lower() in record.text.lower()

    @staticmethod
    def _decision_matches(record: PreviousDecisionRecord, keyword: str) -> bool:
        """Match a ``PreviousDecisionRecord`` by substring, case-
        insensitively, against either ``decision`` or ``rationale``.

        Args:
            record: The ``PreviousDecisionRecord`` to test.
            keyword: The caller's filter value.

        Returns:
            ``True`` if ``keyword`` is a case-insensitive substring of
            ``record.decision`` or ``record.rationale``.
        """
        if not isinstance(keyword, str) or keyword.strip() == "":
            return False
        normalized = keyword.strip().lower()
        return (
            normalized in record.decision.lower()
            or normalized in record.rationale.lower()
        )