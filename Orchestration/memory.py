"""Memory -- the AIOS structured execution-knowledge layer (Stage L17,
Phase 1: the ``MemoryRecord`` value object).

Scope note (LOCKED baseline, per the L17 implementation prompt): this
milestone implements exactly two things and nothing else:

  1. ``MemoryError`` -- the module's own exception type, following the
     same convention as ``GoalPlannerError``/``ObservationError`` (both
     subclass ``Core.exceptions.AgentError`` directly, no intermediate
     layer).
  2. ``MemoryRecord`` -- an immutable value object wrapping exactly one
     :class:`~Orchestration.observation.Observation`, plus its own
     identity (``record_id``) and its own timestamp (``recorded_at``).

Explicitly NOT part of this milestone: ``MemoryStore``, ``MemoryRecorder``,
any retrieval API, any persistence, any CompositionRoot wiring, any
Runtime/Planner/Observation-producing integration. This module is not
imported by, and does not import from, ``Orchestration.planner``,
``Orchestration.service_skill``, ``Core.runtime``, ``Core.composition_root``,
or any file under ``Agents/``. It is additive-only, standing on its own
until a future L17 milestone builds a store/recorder on top of it.

L17 Memory is AIOS Memory -- structured execution knowledge derived from
``Observation``. It is not, and must never be confused with,
``Agents.memory.ConversationMemory`` (chat/message history) or any other
provider-level prompt memory. This module never reads or writes those.

Dependency direction (LOCKED): Memory depends on Observation. Observation
must never depend on Memory -- ``Orchestration.observation`` is read-only
input here, never modified by this module.

Two distinct timestamps, deliberately not conflated:

  - ``Observation.recorded_at`` -- when the ``Observation`` itself was
    built by ``ObservationRecorder.record(...)`` (L16, unchanged).
  - ``MemoryRecord.recorded_at`` -- when that ``Observation`` was wrapped
    into a ``MemoryRecord`` by Memory (this module). An ``Observation``
    is not necessarily memorized the instant it is created, so these two
    moments in time can differ; both are kept, independently, so a future
    retrieval/history consumer can distinguish "when it happened" from
    "when it was memorized".

Immutability & construction (LOCKED design constraint): ``MemoryRecord``
is a ``@dataclass(frozen=True)`` whose ``record_id`` and ``recorded_at``
are produced by the dataclass's own ``field(default_factory=...)`` --
never assigned in a custom ``__init__`` or computed by an external helper
-- so construction stays a single, plain ``MemoryRecord(observation=...)``
call and the class remains trivially immutable.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Union

from Core.exceptions import AgentError
from Orchestration.observation import Observation


class MemoryError(AgentError):
    """Raised by the Memory layer for its own internal-consistency
    failures.

    Following the same convention as ``GoalPlannerError``/
    ``ObservationError`` (both subclass ``Core.exceptions.AgentError``
    directly). Not raised by this milestone -- ``MemoryRecord`` itself
    has nothing to validate -- but declared now so later Memory
    milestones (``MemoryStore``, ``MemoryRecorder``) share one exception
    type from the start, exactly as ``ObservationError`` was declared
    alongside ``Observation`` before ``ObservationRecorder`` needed it.
    """


@dataclass(frozen=True)
class MemoryRecord(object):
    """Immutable value object wrapping exactly one ``Observation`` as a
    unit of AIOS Memory.

    Every field is either the ``Observation`` itself (already fully
    value-typed and immutable, per its own module's "Immutability &
    serialization safety" guarantee) or a plain value produced by
    ``field(default_factory=...)`` at construction time -- so a
    ``MemoryRecord`` never holds a live reference to a
    ``GoalPlanner``, ``ObservationRecorder``, Runtime object, or any
    other collaborator.

    Attributes:
        observation: The :class:`~Orchestration.observation.Observation`
            this record wraps, unmodified -- Memory never mutates, never
            re-derives, and never copies fields out of it individually;
            the whole object is carried through as-is.
        record_id: A fresh ``uuid4`` string identifying this
            ``MemoryRecord``, generated once at construction via
            ``field(default_factory=...)``. Distinct from anything on
            ``Observation`` itself -- this is Memory's own identity for
            the record, for a future retrieval API to key on.
        recorded_at: Wall-clock ``time.time()`` epoch seconds at the
            moment this ``MemoryRecord`` was constructed -- i.e. when the
            ``observation`` was memorized, not when the ``observation``
            itself was built (see module docstring, "Two distinct
            timestamps").
    """

    observation: Observation
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: float = field(default_factory=time.time)


class MemoryStore:
    """Simple in-memory repository for :class:`MemoryRecord` objects
    (Stage L17, Phase 2).

    Stores and retrieves ``MemoryRecord`` instances -- nothing more. No
    intelligence, no ranking, no filtering, no summarization, no
    embeddings, no persistence, and no interaction with ``GoalPlanner``,
    ``ObservationRecorder``, or Runtime. Accepts and returns only
    ``MemoryRecord``; it never accepts an ``Observation``, ``Goal``, or
    ``ServiceResult`` directly -- that conversion belongs to a future
    ``MemoryRecorder`` milestone, not this class.

    Holds one private, mutable collection internally (a
    ``Dict[str, MemoryRecord]`` keyed by ``MemoryRecord.record_id``) but
    never exposes it, its ``.values()`` view, or any other live
    reference to it -- every accessor returns either a single
    ``MemoryRecord`` (already immutable) or a fresh ``tuple`` snapshot.

    Retention policy (Task 2 addition, additive only, in-memory only --
    no persistence, no external storage backend, no distributed state):
    optionally bounds how long the store grows, via two independent,
    both-optional knobs:

      - ``max_size``: once the store holds more than this many records,
        the oldest (by insertion order, which is also construction
        order for every record this store has actually seen) are
        evicted until the store is back at ``max_size``.
      - ``ttl_seconds``: a record is purged once
        ``time.time() - record.recorded_at`` exceeds this value.

    Both default to ``None`` (disabled) -- a ``MemoryStore()`` built
    with no arguments behaves exactly as it did before this policy
    existed: unbounded, no purge, no eviction. Retention only activates
    when a caller explicitly passes ``max_size`` and/or ``ttl_seconds``.
    Expiry/eviction is checked lazily, at the start of every accessor
    (``add``, ``get``, ``list``, ``__len__``) that would otherwise read
    or report on stale state -- there is no background thread, timer,
    or scheduled task; a record already past its TTL simply is not
    returned once any of those methods next runs.
    """

    def __init__(
        self,
        max_size: Optional[int] = None,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """No required dependencies -- ``MemoryStore`` does not call a
        Service, ``ServiceSkill``, ``GoalPlanner``, Runtime, or
        Provider. Starts empty.

        Args:
            max_size: Optional maximum number of records to retain.
                When set, ``add()`` evicts the oldest record(s) (by
                insertion order) whenever the store would otherwise
                exceed this count. ``None`` (the default) means
                unbounded -- identical to this class's behavior before
                this parameter existed.
            ttl_seconds: Optional maximum age, in seconds, a record may
                reach before it is treated as expired and purged. Age
                is measured against ``MemoryRecord.recorded_at``.
                ``None`` (the default) means no expiry -- identical to
                this class's behavior before this parameter existed.
        """
        self._records: Dict[str, MemoryRecord] = {}
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

    def _purge_expired(self) -> None:
        """Remove every record whose age exceeds ``ttl_seconds``.

        No-op when ``ttl_seconds`` is ``None`` (the default) -- this is
        the one and only place TTL is enforced; every accessor below
        calls this first so a caller never observes an already-expired
        record regardless of which method they call.
        """
        if self._ttl_seconds is None:
            return
        now = time.time()
        expired_ids = [
            record_id
            for record_id, record in self._records.items()
            if (now - record.recorded_at) > self._ttl_seconds
        ]
        for record_id in expired_ids:
            del self._records[record_id]

    def _enforce_max_size(self) -> None:
        """Evict the oldest record(s), by insertion order, until the
        store holds at most ``max_size`` records.

        No-op when ``max_size`` is ``None`` (the default). Insertion
        order is used rather than re-sorting by ``recorded_at`` --
        records are always inserted in non-decreasing ``recorded_at``
        order in practice (each is timestamped at construction, just
        before being handed to :meth:`add`), so the two orderings
        coincide, and relying on the dict's own existing insertion
        order avoids introducing a second, separate ordering concept.
        """
        if self._max_size is None:
            return
        while len(self._records) > self._max_size:
            oldest_id = next(iter(self._records))
            del self._records[oldest_id]

    def add(self, record: MemoryRecord) -> None:
        """Insert ``record`` into the store, keyed by
        ``record.record_id``.

        Args:
            record: The ``MemoryRecord`` to store.

        Raises:
            MemoryError: If a record with the same ``record_id`` is
                already stored. This is the store's one genuine-misuse
                case (an id collision), not a business outcome -- an
                ordinary lookup miss in :meth:`get` is never an error
                (see that method's own docstring). Never raised for
                retention-driven eviction/expiry, which is silent by
                design (see class docstring).
        """
        self._purge_expired()
        if record.record_id in self._records:
            raise MemoryError(
                "MemoryStore.add: a record with this record_id is "
                "already stored -- record_id must be unique.",
                details={"record_id": record.record_id},
            )
        self._records[record.record_id] = record
        self._enforce_max_size()

    def get(self, record_id: str) -> Optional[MemoryRecord]:
        """Return the ``MemoryRecord`` stored under ``record_id``, or
        ``None`` if no such record exists.

        A missing ``record_id`` is a normal, expected outcome of a
        lookup -- never raised as :class:`MemoryError`. This includes a
        ``record_id`` that was once stored but has since expired under
        ``ttl_seconds``: an expired record and a never-stored one are
        indistinguishable to a caller of this method.

        Args:
            record_id: The ``record_id`` to look up.

        Returns:
            The matching ``MemoryRecord``, or ``None`` if not found.
        """
        self._purge_expired()
        return self._records.get(record_id)

    def list(self) -> Tuple[MemoryRecord, ...]:
        """Return every stored ``MemoryRecord`` as a ``tuple``, in
        insertion order.

        Always a fresh ``tuple`` snapshot -- never the internal
        ``dict``, its ``.values()`` view, or any other object that
        shares live state with this store. Mutating (or attempting to
        mutate) the returned tuple never affects the store.

        Returns:
            A ``Tuple[MemoryRecord, ...]`` of every stored record, in
            the order it was added.
        """
        self._purge_expired()
        return tuple(self._records.values())

    def clear(self) -> None:
        """Remove every stored ``MemoryRecord``, leaving the store
        empty."""
        self._records.clear()

    def __len__(self) -> int:
        """Return the number of ``MemoryRecord`` objects currently
        stored."""
        self._purge_expired()
        return len(self._records)


class MemoryRecorder:
    """Wraps a single ``Observation`` into a ``MemoryRecord`` and stores
    it in a :class:`MemoryStore` (Stage L17, Phase 3).

    The sole bridge between Observation and Memory storage. Does not
    inspect, transform, or validate the ``Observation`` it is given --
    it constructs exactly one ``MemoryRecord`` wrapping it, hands that
    record to the store, and returns it. No retrieval, no search, no
    ranking, no persistence, and no logging live here; those remain out
    of scope for this milestone, same as for ``MemoryStore``.

    Holds exactly one collaborator, ``self._store`` -- no other state.
    """

    def __init__(self, store: MemoryStore) -> None:
        """
        Args:
            store: The :class:`MemoryStore` every ``record(...)`` call
                will insert into. Held as-is, never copied or wrapped.
        """
        self._store = store

    def record(self, observation: Observation) -> MemoryRecord:
        """Wrap ``observation`` in a fresh ``MemoryRecord``, store it,
        and return it.

        Args:
            observation: The :class:`~Orchestration.observation.Observation`
                to memorize, unmodified.

        Returns:
            The same ``MemoryRecord`` instance that was inserted into
            the store.

        Raises:
            MemoryError: Propagated unmodified from
                ``MemoryStore.add(...)`` on a ``record_id`` collision --
                never caught here.
        """
        record = MemoryRecord(observation=observation)
        self._store.add(record)
        return record


@dataclass(frozen=True)
class PreferenceRecord(object):
    """Immutable value object representing exactly one non-financial user
    preference (Activation 12, Phase 2).

    ``PreferenceRecord`` is a sibling to :class:`MemoryRecord`, not a
    replacement for it and not a subclass of it. ``MemoryRecord.observation``
    is a required field typed strictly as
    :class:`~Orchestration.observation.Observation` -- a preference has no
    ``Observation`` to wrap, so extending ``MemoryRecord`` additively is not
    possible without breaking that field's contract. Instead this class is
    structurally compatible with :class:`MemoryStore` the same way every
    other Memory collaborator already is in this codebase (``GoalPlanner``
    only ever calls ``memory.list()``, ``LearningLoop`` only ever calls
    ``memory.add(...)``): ``MemoryStore.add``/``get`` key off
    ``record.record_id`` alone and never perform an ``isinstance(record,
    MemoryRecord)`` check, so a ``PreferenceRecord`` -- which carries its
    own fresh ``record_id`` and ``recorded_at`` exactly as ``MemoryRecord``
    does -- stores and retrieves through the existing, unmodified
    ``MemoryStore`` without any change to that class.

    Only fields proven necessary are included: a preference is a ``key``
    (what is being remembered, e.g. ``"analysis_style"``) and a ``value``
    (the user's stated preference for it, e.g. ``"concise"``), plus the
    same identity/timestamp pair ``MemoryRecord`` already has, plus one
    optional ``source`` for where the preference came from (e.g. a chat
    turn or a command). Nothing else.

    ``value`` is restricted to plain primitive types (``str``, ``int``,
    ``float``, ``bool``, or ``None``) at construction time. This is the
    concrete enforcement of "memory must remain non-financial": every
    financial-state object in this codebase (``Account``, ``Position``,
    ``Order``, ``Trade``, and friends) is a structured object, never a bare
    primitive, so none of them can be constructed as a preference's
    ``value`` -- a caller must not, and cannot, hand this class a live
    financial object instead of a plain user-facing setting.

    Attributes:
        key: Non-empty ``str`` identifying which preference this is (e.g.
            ``"notification_style"``). Never a financial identifier such
            as an account or symbol -- this class does not know or care
            about those; it only stores what it is given, restricted to
            the primitive types above.
        value: The preference's value. Restricted to ``str``, ``int``,
            ``float``, ``bool``, or ``None`` -- see class docstring.
        record_id: A fresh ``uuid4`` string identifying this
            ``PreferenceRecord``, generated once at construction via
            ``field(default_factory=...)``, exactly as
            ``MemoryRecord.record_id`` is -- this is what makes the record
            structurally compatible with ``MemoryStore``.
        recorded_at: Wall-clock ``time.time()`` epoch seconds at the
            moment this ``PreferenceRecord`` was constructed.
        source: Optional free-text ``str`` describing where this
            preference came from (e.g. ``"chat"``, ``"cli"``). ``None``
            by default. Never a live reference to any collaborator.
    """

    key: str
    value: Union[str, int, float, bool, None]
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: float = field(default_factory=time.time)
    source: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate ``key`` and ``value`` at construction time.

        Raises:
            MemoryError: If ``key`` is not a non-empty ``str``, or if
                ``value`` is not one of ``str``/``int``/``float``/``bool``/
                ``None``. This is the one and only place either field is
                checked -- ``PreferenceRecord`` has no other behavior.
        """
        if not isinstance(self.key, str) or not self.key:
            raise MemoryError(
                "PreferenceRecord.key must be a non-empty str.",
                details={"key": self.key},
            )
        if self.value is not None and not isinstance(self.value, (str, int, float, bool)):
            raise MemoryError(
                "PreferenceRecord.value must be a primitive (str, int, "
                "float, bool, or None) -- financial or other domain "
                "objects are not valid preference values.",
                details={"key": self.key, "value_type": type(self.value).__name__},
            )


@dataclass(frozen=True)
class StrategyNoteRecord(object):
    """Immutable value object representing exactly one user-authored
    strategy note (Activation 12 Memory -- Strategy Notes).

    ``StrategyNoteRecord`` is a sibling to :class:`MemoryRecord` and
    :class:`PreferenceRecord`, not a subclass of either. Exactly like
    ``PreferenceRecord``'s own reasoning (see that class's docstring):
    ``MemoryRecord.observation`` is a required field typed strictly as
    :class:`~Orchestration.observation.Observation`, and a strategy note
    has no ``Observation`` to wrap, so extending ``MemoryRecord``
    additively is not possible without breaking that field's contract.
    This class is structurally compatible with :class:`MemoryStore` the
    same way every other Memory collaborator already is: ``MemoryStore.
    add``/``get`` key off ``record.record_id`` alone and never perform an
    ``isinstance(record, MemoryRecord)`` check, so a ``StrategyNoteRecord``
    -- which carries its own fresh ``record_id`` and ``recorded_at``
    exactly as ``MemoryRecord``/``PreferenceRecord`` do -- stores and
    retrieves through the existing, unmodified ``MemoryStore`` without
    any change to that class.

    Only fields proven necessary are included: a strategy note is a
    single piece of free text (``text``) the user authored, plus the
    same identity/timestamp pair every other Memory record already has,
    plus one optional ``source`` for where the note came from (e.g. a
    chat turn or a command) -- mirroring ``PreferenceRecord.source``
    exactly. No ``strategy_name``, ``strategy_version``, ``symbol``,
    ``market``, ``account_id``, ``portfolio_id``, ``risk``,
    ``target_price``, ``stop_loss``, ``performance``, or ``trade_id``
    field is included: the roadmap category is "strategy notes" (passive
    user/agent context), not structured financial strategy metadata, and
    none of those fields has a real, already-proven source or consumer
    in this codebase. This class performs no financial parsing, symbol
    parsing, market normalization, strategy classification, sentiment
    analysis, embedding, or LLM processing of any kind -- ``text`` is
    stored, normalized only by stripping surrounding whitespace, exactly
    as given.

    Attributes:
        text: Non-empty (after ``str(text).strip()``) ``str`` holding the
            user-authored strategy note itself, e.g. ``"Use momentum
            strategy on IDX large caps."``. Stored in its normalized
            (stripped) form -- never otherwise parsed, classified, or
            transformed.
        record_id: A fresh ``uuid4`` string identifying this
            ``StrategyNoteRecord``, generated once at construction via
            ``field(default_factory=...)``, exactly as
            ``MemoryRecord.record_id``/``PreferenceRecord.record_id``
            are -- this is what makes the record structurally compatible
            with ``MemoryStore``.
        recorded_at: Wall-clock ``time.time()`` epoch seconds at the
            moment this ``StrategyNoteRecord`` was constructed, exactly
            as ``PreferenceRecord.recorded_at`` is.
        source: Optional free-text ``str`` describing where this note
            came from (e.g. ``"chat"``, ``"cli"``). ``None`` by default.
            Never a live reference to any collaborator.
    """

    text: str
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: float = field(default_factory=time.time)
    source: Optional[str] = None

    def __post_init__(self) -> None:
        """Normalize and validate ``text`` at construction time.

        Raises:
            MemoryError: If ``text`` is not a ``str`` (before
                normalization), or if the stripped result is empty. This
                is the one and only place ``text`` is checked --
                ``StrategyNoteRecord`` has no other behavior. Normalized
                ``text`` is written back via ``object.__setattr__``
                (the same pattern every other frozen-dataclass
                ``__post_init__`` in this codebase must use, since the
                class is frozen) so the stored value is always the
                already-stripped form.
        """
        if not isinstance(self.text, str):
            raise MemoryError(
                "StrategyNoteRecord.text must be a str.",
                details={"text_type": type(self.text).__name__},
            )
        normalized = self.text.strip()
        if normalized == "":
            raise MemoryError(
                "StrategyNoteRecord.text must not be empty (after "
                "stripping whitespace).",
                details={"text": self.text},
            )
        object.__setattr__(self, "text", normalized)


@dataclass(frozen=True)
class PreviousDecisionRecord(object):
    """Immutable value object representing exactly one retrievable
    historical decision/rationale memory record (Activation 12 Memory --
    Previous Decisions).

    ``PreviousDecisionRecord`` is a sibling to :class:`MemoryRecord`,
    :class:`PreferenceRecord`, and :class:`StrategyNoteRecord`, not a
    subclass of any of them. Exactly like those classes' own reasoning
    (see their docstrings): ``MemoryRecord.observation`` is a required
    field typed strictly as
    :class:`~Orchestration.observation.Observation`, and a previous
    decision has no ``Observation`` to wrap, so extending ``MemoryRecord``
    additively is not possible without breaking that field's contract.
    This class is structurally compatible with :class:`MemoryStore` the
    same way every other Memory collaborator already is: ``MemoryStore.
    add``/``get`` key off ``record.record_id`` alone and never perform an
    ``isinstance(record, MemoryRecord)`` check, so a
    ``PreviousDecisionRecord`` -- which carries its own fresh
    ``record_id`` and ``recorded_at`` exactly as ``MemoryRecord``/
    ``PreferenceRecord``/``StrategyNoteRecord`` do -- stores and
    retrieves through the existing, unmodified ``MemoryStore`` without
    any change to that class.

    Only fields proven necessary are included: a previous decision is a
    ``decision`` (what was decided) and a ``rationale`` (why), plus the
    same identity/timestamp pair every other Memory record already has,
    plus one optional ``source`` for where the decision came from (e.g.
    a chat turn, a command, or the planner) -- mirroring
    ``PreferenceRecord.source``/``StrategyNoteRecord.source`` exactly --
    plus one optional ``reference_id``: an opaque string that may refer
    conceptually to an order, trade, or decision key, but performs no
    lookup and holds no live reference to anything. This class performs
    no financial parsing, symbol parsing, account lookup, trade lookup,
    order lookup, decision classification, recommendation parsing, or
    sentiment analysis of any kind -- ``decision`` and ``rationale`` are
    stored, normalized only by stripping surrounding whitespace, exactly
    as given.

    Attributes:
        decision: Non-empty (after ``str(decision).strip()``) ``str``
            holding the decision itself, e.g. ``"Reduced BBCA.JK
            position by half."``. Stored in its normalized (stripped)
            form -- never otherwise parsed, classified, or transformed.
        rationale: Non-empty (after ``str(rationale).strip()``) ``str``
            holding why the decision was made, e.g. ``"Earnings missed
            consensus and momentum turned negative."``. Stored in its
            normalized (stripped) form -- never otherwise parsed,
            classified, or transformed.
        record_id: A fresh ``uuid4`` string identifying this
            ``PreviousDecisionRecord``, generated once at construction
            via ``field(default_factory=...)``, exactly as
            ``MemoryRecord.record_id``/``PreferenceRecord.record_id``/
            ``StrategyNoteRecord.record_id`` are -- this is what makes
            the record structurally compatible with ``MemoryStore``.
        recorded_at: Wall-clock ``time.time()`` epoch seconds at the
            moment this ``PreviousDecisionRecord`` was constructed,
            exactly as ``PreferenceRecord.recorded_at``/
            ``StrategyNoteRecord.recorded_at`` are.
        source: Optional free-text ``str`` describing where this
            decision came from (e.g. ``"cli"``, ``"chat"``,
            ``"planner"``). ``None`` by default. Never a live reference
            to any collaborator.
        reference_id: Optional opaque ``str`` that may refer
            conceptually to an ``order_id``, ``trade_id``, or
            ``decision_key``. ``None`` by default. Never used to
            perform a repository/database lookup, never used to mutate
            financial state, and never a financial source of truth --
            this class holds it as a plain string and nothing more.
    """

    decision: str
    rationale: str
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: float = field(default_factory=time.time)
    source: Optional[str] = None
    reference_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Normalize and validate ``decision`` and ``rationale`` at
        construction time.

        Raises:
            MemoryError: If ``decision`` or ``rationale`` is not a
                ``str`` (before normalization), or if the stripped
                result of either is empty. This is the one and only
                place either field is checked -- ``PreviousDecisionRecord``
                has no other behavior. Normalized values are written
                back via ``object.__setattr__`` (the same pattern every
                other frozen-dataclass ``__post_init__`` in this module
                uses, since the class is frozen) so the stored value is
                always the already-stripped form.
        """
        if not isinstance(self.decision, str):
            raise MemoryError(
                "PreviousDecisionRecord.decision must be a str.",
                details={"decision_type": type(self.decision).__name__},
            )
        normalized_decision = self.decision.strip()
        if normalized_decision == "":
            raise MemoryError(
                "PreviousDecisionRecord.decision must not be empty "
                "(after stripping whitespace).",
                details={"decision": self.decision},
            )

        if not isinstance(self.rationale, str):
            raise MemoryError(
                "PreviousDecisionRecord.rationale must be a str.",
                details={"rationale_type": type(self.rationale).__name__},
            )
        normalized_rationale = self.rationale.strip()
        if normalized_rationale == "":
            raise MemoryError(
                "PreviousDecisionRecord.rationale must not be empty "
                "(after stripping whitespace).",
                details={"rationale": self.rationale},
            )

        object.__setattr__(self, "decision", normalized_decision)
        object.__setattr__(self, "rationale", normalized_rationale)


@dataclass(frozen=True)
class LessonRecord(object):
    """Immutable value object representing exactly one retrievable
    lesson learned from a failed trade (Activation 12 Memory --
    Lessons From Failed Trades).

    ``LessonRecord`` is a sibling to :class:`MemoryRecord`,
    :class:`PreferenceRecord`, :class:`StrategyNoteRecord`, and
    :class:`PreviousDecisionRecord`, not a subclass of any of them.
    Exactly like those classes' own reasoning (see their docstrings):
    ``MemoryRecord.observation`` is a required field typed strictly as
    :class:`~Orchestration.observation.Observation`, and a lesson has
    no ``Observation`` to wrap, so extending ``MemoryRecord``
    additively is not possible without breaking that field's contract.
    This class is structurally compatible with :class:`MemoryStore` the
    same way every other Memory collaborator already is: ``MemoryStore.
    add``/``get`` key off ``record.record_id`` alone and never perform
    an ``isinstance(record, MemoryRecord)`` check, so a
    ``LessonRecord`` -- which carries its own fresh ``record_id`` and
    ``recorded_at`` exactly as ``MemoryRecord``/``PreferenceRecord``/
    ``StrategyNoteRecord``/``PreviousDecisionRecord`` do -- stores and
    retrieves through the existing, unmodified ``MemoryStore`` without
    any change to that class.

    Only fields proven necessary are included: a lesson is a single
    piece of free text (``text``) capturing what was learned from a
    failed trade, plus the same identity/timestamp pair every other
    Memory record already has, plus one optional ``source`` for where
    the lesson came from (e.g. a chat turn or a command) -- mirroring
    ``StrategyNoteRecord.source``/``PreviousDecisionRecord.source``
    exactly -- plus one optional ``reference_id``: an opaque string
    that may refer conceptually to an order, trade, or decision key,
    but performs no lookup and holds no live reference to anything --
    mirroring ``PreviousDecisionRecord.reference_id`` exactly. No
    ``failure_reason``, ``outcome``, ``pnl``, order status, or any
    other structured financial field is included: the roadmap category
    is "lessons from failed trades" (passive user/agent context), not a
    second financial outcome record, and none of those fields has a
    real, already-proven source or consumer in this codebase for this
    milestone. This class performs no financial parsing, order-status
    classification, P/L computation, or outcome resolution of any kind
    -- ``text`` is stored, normalized only by stripping surrounding
    whitespace, exactly as given.

    Attributes:
        text: Non-empty (after ``str(text).strip()``) ``str`` holding
            the lesson itself, e.g. ``"Avoid entering after a gap-up
            without confirmation."``. Stored in its normalized
            (stripped) form -- never otherwise parsed, classified, or
            transformed.
        record_id: A fresh ``uuid4`` string identifying this
            ``LessonRecord``, generated once at construction via
            ``field(default_factory=...)``, exactly as
            ``MemoryRecord.record_id``/``PreferenceRecord.record_id``/
            ``StrategyNoteRecord.record_id``/
            ``PreviousDecisionRecord.record_id`` are -- this is what
            makes the record structurally compatible with
            ``MemoryStore``.
        recorded_at: Wall-clock ``time.time()`` epoch seconds at the
            moment this ``LessonRecord`` was constructed, exactly as
            ``StrategyNoteRecord.recorded_at``/
            ``PreviousDecisionRecord.recorded_at`` are.
        source: Optional free-text ``str`` describing where this
            lesson came from (e.g. ``"chat"``, ``"cli"``). ``None`` by
            default. Never a live reference to any collaborator.
        reference_id: Optional opaque ``str`` that may refer
            conceptually to an ``order_id``, ``trade_id``, or
            ``decision_key``. ``None`` by default. Never used to
            perform a repository/database lookup, never used to mutate
            financial state, and never a financial source of truth --
            this class holds it as a plain string and nothing more.
    """

    text: str
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: float = field(default_factory=time.time)
    source: Optional[str] = None
    reference_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Normalize and validate ``text`` at construction time.

        Raises:
            MemoryError: If ``text`` is not a ``str`` (before
                normalization), or if the stripped result is empty.
                This is the one and only place ``text`` is checked --
                ``LessonRecord`` has no other behavior. Normalized
                ``text`` is written back via ``object.__setattr__``
                (the same pattern every other frozen-dataclass
                ``__post_init__`` in this module uses, since the class
                is frozen) so the stored value is always the
                already-stripped form.
        """
        if not isinstance(self.text, str):
            raise MemoryError(
                "LessonRecord.text must be a str.",
                details={"text_type": type(self.text).__name__},
            )
        normalized = self.text.strip()
        if normalized == "":
            raise MemoryError(
                "LessonRecord.text must not be empty (after "
                "stripping whitespace).",
                details={"text": self.text},
            )
        object.__setattr__(self, "text", normalized)


@dataclass(frozen=True)
class PortfolioContextRecord(object):
    """Immutable value object representing exactly one retrievable
    piece of portfolio context (Activation 12 Memory -- Portfolio
    Context).

    ``PortfolioContextRecord`` is a sibling to :class:`MemoryRecord`,
    :class:`PreferenceRecord`, :class:`StrategyNoteRecord`,
    :class:`PreviousDecisionRecord`, and :class:`LessonRecord`, not a
    subclass of any of them -- exactly the same reasoning as those
    classes' own docstrings: ``MemoryRecord.observation`` is a required
    field typed strictly as
    :class:`~Orchestration.observation.Observation`, and portfolio
    context has no ``Observation`` to wrap, so extending
    ``MemoryRecord`` additively is not possible without breaking that
    field's contract. This class is structurally compatible with
    :class:`MemoryStore` the same way every other Memory collaborator
    already is: ``MemoryStore.add``/``get`` key off ``record.record_id``
    alone and never perform an ``isinstance(record, MemoryRecord)``
    check, so a ``PortfolioContextRecord`` -- which carries its own
    fresh ``record_id`` and ``recorded_at`` exactly as
    ``MemoryRecord``/``PreferenceRecord``/``StrategyNoteRecord``/
    ``PreviousDecisionRecord``/``LessonRecord`` do -- stores and
    retrieves through the existing, unmodified ``MemoryStore`` without
    any change to that class.

    This record is passive, narrative memory only. It is NOT financial
    state and is not, and must never become, a substitute for the
    financial database: authoritative portfolio numbers (cash, market
    value, equity, realized/unrealized P/L, drawdown, exposure) live
    exclusively in ``Database.models.PortfolioSnapshot`` and the
    financial engines/repositories that produce and persist it. This
    class holds no such structured financial field and performs no
    financial computation, aggregation, or lookup of any kind -- it
    only stores whatever narrative ``text`` it is given, e.g.
    ``"Portfolio remains concentrated in a small number of
    positions."``. Any financial figures a caller wants to mention are
    the caller's own authored narrative inside ``text``, never a
    structured field on this class, and this record does not
    synchronize with, refresh from, or otherwise track
    ``PortfolioSnapshot`` automatically -- nothing in this module reads
    ``PortfolioSnapshot``, ``PortfolioSnapshotRepository``, or any other
    financial collaborator.

    Only fields proven necessary are included, mirroring
    ``LessonRecord`` exactly: a single piece of free text (``text``)
    capturing the portfolio context, plus the same identity/timestamp
    pair every other Memory record already has, plus one optional
    ``source`` for where the context came from (e.g. a chat turn or a
    command) -- mirroring ``LessonRecord.source`` exactly -- plus one
    optional ``reference_id``: an opaque string that may refer
    conceptually to a portfolio snapshot, account, or decision key, but
    performs no lookup and holds no live reference to anything --
    mirroring ``LessonRecord.reference_id``/``PreviousDecisionRecord.
    reference_id`` exactly. No ``cash``, ``market_value``, ``equity``,
    ``realized_pnl``, ``unrealized_pnl``, ``drawdown``, ``exposure``,
    ``account_id``, ``position_count``, ``order_count``, or any other
    structured financial field is included: the roadmap category is
    "portfolio context" (passive user/agent context), not a second
    financial state record, and none of those fields has a real,
    already-proven source or consumer in this module for this
    milestone.

    Attributes:
        text: Non-empty (after ``str(text).strip()``) ``str`` holding
            the portfolio context itself, e.g. ``"Portfolio remains
            heavily concentrated in technology positions."``. Stored in
            its normalized (stripped) form -- never otherwise parsed,
            classified, or transformed.
        record_id: A fresh ``uuid4`` string identifying this
            ``PortfolioContextRecord``, generated once at construction
            via ``field(default_factory=...)``, exactly as
            ``MemoryRecord.record_id``/``PreferenceRecord.record_id``/
            ``StrategyNoteRecord.record_id``/
            ``PreviousDecisionRecord.record_id``/
            ``LessonRecord.record_id`` are -- this is what makes the
            record structurally compatible with ``MemoryStore``.
        recorded_at: Wall-clock ``time.time()`` epoch seconds at the
            moment this ``PortfolioContextRecord`` was constructed,
            exactly as ``LessonRecord.recorded_at``/
            ``PreviousDecisionRecord.recorded_at`` are.
        source: Optional free-text ``str`` describing where this
            portfolio context came from (e.g. ``"chat"``, ``"cli"``).
            ``None`` by default. Never a live reference to any
            collaborator.
        reference_id: Optional opaque ``str`` that may refer
            conceptually to a ``snapshot_id``, ``account_id``, or
            ``decision_key``. ``None`` by default. Never used to
            perform a repository/database lookup, never used to
            resolve or fetch a ``PortfolioSnapshot``, never used to
            mutate financial state, and never a financial source of
            truth -- this class holds it as a plain string and nothing
            more.
    """

    text: str
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    recorded_at: float = field(default_factory=time.time)
    source: Optional[str] = None
    reference_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Normalize and validate ``text`` at construction time.

        Raises:
            MemoryError: If ``text`` is not a ``str`` (before
                normalization), or if the stripped result is empty.
                This is the one and only place ``text`` is checked --
                ``PortfolioContextRecord`` has no other behavior.
                Normalized ``text`` is written back via
                ``object.__setattr__`` (the same pattern every other
                frozen-dataclass ``__post_init__`` in this module
                uses, since the class is frozen) so the stored value
                is always the already-stripped form.
        """
        if not isinstance(self.text, str):
            raise MemoryError(
                "PortfolioContextRecord.text must be a str.",
                details={"text_type": type(self.text).__name__},
            )
        normalized = self.text.strip()
        if normalized == "":
            raise MemoryError(
                "PortfolioContextRecord.text must not be empty (after "
                "stripping whitespace).",
                details={"text": self.text},
            )
        object.__setattr__(self, "text", normalized)