from __future__ import annotations

import json
from typing import Any, Optional

from Core.approval import AlwaysApproveApprovalPort
from Core.event import EventType
from Core.event_store import EventStore, InMemoryEventStore
from Core.exceptions import ApprovalDenied, ApprovalPending, RuntimeInvariantError, ToolError
from Core.gateaway import DefaultGateway, Gateway
from Core.logger import get_logger
from Core.reducer_shell import ReducerShell, State
from Core.runtime import ActorID, ApprovalPort, NoEventToProcessError, Runtime, StepResult
from Agents.sandbox import GenericSandbox
from Agents.tool_registry import ToolNotFoundError, ToolRegistry

logger = get_logger(__name__)


class ToolExecutionError(ToolError):
    """Raised when a tool raises an exception while being executed.

    Additive subclass of ``Core.exceptions.ToolError``. Stage 8.2: the
    original exception no longer crosses the Runtime boundary as a live
    object (it was reduced to an error-as-data payload inside
    ``GenericSandbox``, then serialized through Event Store bytes), so
    ``__cause__`` is intentionally NOT preserved here (LOCKED). What
    survives instead is metadata in ``details``:
      - ``original_exception_class``: ``type(original_exc).__name__``
      - ``original_message``: ``str(original_exc)``
    """


class _NoOpReducerLogic:
    """Minimal ``ReducerPort`` bound to Executor's private ``Runtime``.

    Executor never reads Actor ``State`` -- it only cares about the Event
    trajectory (read back via ``replay()``). ``Runtime.__init__`` requires
    a valid ``ReducerPort`` regardless (runtime.py CLOSED), so this logic
    exists purely to satisfy that constructor contract; ``reduce()`` is a
    deliberate no-op.
    """

    version = "executor-noop-reducer-v1"

    def reduce(self, state: State, event) -> Any:  # noqa: ARG002 - Executor discards State
        return None


class Executor:
    """Runs a registered tool by name, via Runtime (ingest -> step -> replay).

    The executor never stores tools itself; lookup and invocation happen
    inside ``GenericSandbox``, reached only through the private ``Runtime``
    instance constructed here. Executor is solely responsible for driving
    that Runtime for one tool-call and normalizing the outcome.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        approval_port: Optional[ApprovalPort] = None,
        gateway: Optional[Gateway] = None,
        event_store: Optional[EventStore] = None,
    ) -> None:
        """Construct the Executor and its private ``Runtime``.

        Stage 9.1 (additive, backward-compatible): ``approval_port``,
        ``gateway``, and ``event_store`` open dependency injection for
        exactly the three ``Runtime`` collaborators this stage was scoped
        to -- nothing else. Each defaults to ``None``, in which case the
        exact same concrete class Stage 8.2 always hardcoded here is
        constructed instead, so a caller that supplies none of them
        (every caller today, including ``Core.composition_root``) gets
        byte-for-byte identical behavior to before this stage: the
        default path is not merely "similar", it constructs the same
        classes with the same zero-argument calls as before.

        ``sandbox`` (``GenericSandbox(tool_registry)``) and ``reducer``
        (``ReducerShell(_NoOpReducerLogic())``) are deliberately NOT
        opened here -- out of Stage 9.1's scope by design decision, kept
        hardcoded exactly as Stage 8.2 left them.
        """
        self._tool_registry = tool_registry
        sandbox = GenericSandbox(tool_registry)
        self._runtime = Runtime(
            event_store=event_store if event_store is not None else InMemoryEventStore(),
            gateway=gateway if gateway is not None else DefaultGateway(),
            reducer=ReducerShell(_NoOpReducerLogic()),
            sandbox=sandbox,
            approval=approval_port if approval_port is not None else AlwaysApproveApprovalPort(),
        )

    def create_actor(self, task: bytes) -> ActorID:
        """Create and return a new Actor via the private Runtime.

        Stage 8.3 (additive -- BaseAgent owns Actor lifecycle): exposes
        ``Runtime.create_actor()`` so a caller (e.g. ``BaseAgent``) can
        mint an Actor it intends to reuse across multiple ``execute()``
        calls, by holding on to the returned ``actor_id`` and passing it
        back into :meth:`execute`. This is a thin passthrough only --
        Executor still owns the sole ``Runtime`` instance/reference;
        nothing about the Runtime itself is exposed to the caller.

        Purely additive: does not change ``execute()``'s own default
        behavior (fresh Actor per call when ``actor_id`` is omitted --
        LOCKED Stage 8.2, unchanged, see :meth:`execute`).
        """
        return self._runtime.create_actor(task=task)

    def execute(
        self,
        tool_name: str,
        *args: object,
        actor_id: Optional[ActorID] = None,
        **kwargs: object,
    ) -> Any:
        """Look up ``tool_name`` and run it through the Runtime.

        Args:
            tool_name: Name of the tool to execute.
            *args: Positional arguments forwarded to the tool handler.
                Must be JSON-serializable -- they cross the Runtime as a
                JSON tool-call envelope inside an INTENT payload.
            actor_id: Stage 8.3 (additive). When omitted (``None``, the
                default), behavior is byte-for-byte identical to Stage
                8.2 LOCKED: a fresh Actor is minted for this call via
                ``self._runtime.create_actor()``, exactly as before this
                parameter existed. When supplied, that Actor (already
                alive -- typically obtained from :meth:`create_actor`)
                is reused instead: the INTENT for this call is ingested
                into its existing stream rather than a brand-new one.
                This lets a caller (e.g. ``BaseAgent``) own one Actor
                across many ``execute()`` calls without Executor's
                default one-Actor-per-call path ever changing.
            **kwargs: Keyword arguments forwarded to the tool handler.
                Same JSON-serializability requirement as ``*args``.

        Returns:
            Whatever the tool handler returns.

        Raises:
            ToolNotFoundError: If ``tool_name`` is not registered.
            ToolExecutionError: If the tool handler raises an exception.
            ApprovalDenied: Stage 8.5. If ``ApprovalPort.check()`` denied
                the INTENT. Never raised today via this constructor's
                default ``AlwaysApproveApprovalPort`` -- reachable only
                once a non-always-approve ``ApprovalPort`` exists.
            ApprovalPending: Stage 8.5. If ``ApprovalPort.check()``
                returned PENDING. Same reachability note as above.
        """
        if actor_id is None:
            # Default path -- LOCKED Stage 8.2, unchanged: fresh Actor
            # minted per execute() call.
            genesis_task = json.dumps({"executor_genesis": tool_name}).encode("utf-8")
            actor_id = self._runtime.create_actor(task=genesis_task)
            owns_actor = True
        else:
            # Caller supplied an Actor it already owns (Stage 8.3,
            # additive) -- ingest into that existing stream below instead
            # of minting a new one. Never reached unless a caller opts in.
            owns_actor = False

        try:
            envelope = json.dumps(
                {"tool_name": tool_name, "args": list(args), "kwargs": kwargs}
            ).encode("utf-8")
            self._runtime.ingest(
                envelope, source="Executor.execute", actor_id=actor_id, event_type=EventType.INTENT
            )

            self._drain(actor_id)

            events, _state = self._runtime.replay(actor_id)
            last_event = events[-1]  # Event terakhir diambil melalui replay() -- LOCKED.

            return self._translate_last_event(last_event, tool_name, actor_id)
        finally:
            # Additive cleanup for the one-shot path only (owns_actor is
            # only True when this call minted its own Actor above): the
            # Actor is terminated then archived so long-lived processes
            # don't grow Runtime._states/_cursors and EventStore streams
            # without bound. Never runs for the caller-supplied-actor
            # path (BaseAgent), which owns its Actor's lifecycle itself.
            # Wrapped so cleanup can never mask the real result/exception.
            if owns_actor:
                try:
                    if self._runtime.is_alive(actor_id):
                        self._runtime.terminate(actor_id, reason=b"executor_one_shot_complete")
                    self._runtime.archive_actor(actor_id)
                except Exception:  # noqa: BLE001 -- cleanup must never mask the real outcome
                    logger.warning(
                        f"Executor: cleanup failed for one-shot Actor {actor_id!r}", exc_info=True
                    )

    def _drain(self, actor_id: str) -> None:
        """Panggil ``step()`` berulang sampai tidak ada Event lagi diproses.

        Untuk satu tool-call, satu INTENT biasanya selesai dalam satu
        panggilan ``step()`` (Approved -> Decision + Effect sinkron), tapi
        loop ini tetap generik: berhenti begitu ``NoEventToProcessError``
        (tidak ada trigger Event berikutnya) atau ``StepResult.TERMINATED``.
        """
        while True:
            try:
                result = self._runtime.step(actor_id)
            except NoEventToProcessError:
                return
            if result == StepResult.TERMINATED:
                return

    @staticmethod
    def _translate_last_event(last_event: Any, tool_name: str, actor_id: ActorID) -> Any:
        """Stage 8.5: single dispatch point translating the last Event of a
        drained INTENT cycle into Executor's public outcome.

        This is the only place ``execute()`` interprets ``last_event`` --
        centralized here instead of a growing if/elif chain inline in
        ``execute()``, per Stage 8.5 design decision. Every branch below
        maps to exactly one outcome:

          EFFECT_COMPLETED         -> plain return value, or
                                      ToolNotFoundError/ToolExecutionError
                                      (still decoded by ``_decode_effect``,
                                      unchanged from Stage 8.2)
          DECISION(DENIED)         -> ApprovalDenied  (Stage 8.5, new)
          DECISION(PENDING)        -> ApprovalPending (Stage 8.5, new)
          DECISION(APPROVED)       -> unreachable per Core.runtime.step()
                                      (LOCKED): an APPROVED Decision is
                                      always followed by EFFECT_COMPLETED
                                      in the same step(). Guarded
                                      explicitly rather than silently
                                      falling through.
          anything else            -> RuntimeInvariantError (unchanged
                                      meaning: a genuine contract
                                      violation, never a legitimate
                                      tool-domain or approval outcome)
        """
        if last_event.type == "EFFECT_COMPLETED":
            return Executor._decode_effect(last_event.payload, tool_name)

        if last_event.type == EventType.DECISION:
            decision = json.loads(last_event.payload.decode("utf-8"))
            outcome = decision.get("outcome")
            policy_version = decision.get("policy_version")

            if outcome == "DENIED":
                raise ApprovalDenied(
                    f"Tool '{tool_name}' was not approved for execution.",
                    details={
                        "tool_name": tool_name,
                        "actor_id": actor_id,
                        "policy_version": policy_version,
                    },
                )

            if outcome == "PENDING":
                raise ApprovalPending(
                    f"Approval for tool '{tool_name}' is still pending.",
                    details={
                        "tool_name": tool_name,
                        "actor_id": actor_id,
                        "policy_version": policy_version,
                    },
                )

            # outcome == "APPROVED" (or anything unrecognized) landing here
            # as the LAST event would mean Runtime advanced past a
            # DECISION without ever producing EFFECT_COMPLETED --
            # structurally unreachable per Core.runtime.step() (LOCKED),
            # not a legitimate approval/tool outcome. Genuine invariant
            # violation.
            raise RuntimeInvariantError(
                f"Executor mengharapkan EFFECT_COMPLETED atau DECISION dengan "
                f"outcome DENIED/PENDING sebagai Event terakhir untuk tool "
                f"'{tool_name}', dapat DECISION(outcome={outcome!r}).",
                details={"tool_name": tool_name, "actor_id": actor_id},
            )

        raise RuntimeInvariantError(
            f"Executor mengharapkan EFFECT_COMPLETED sebagai Event terakhir "
            f"untuk tool '{tool_name}', dapat {last_event.type!r}.",
            details={"tool_name": tool_name, "actor_id": actor_id},
        )

    @staticmethod
    def _decode_effect(payload: bytes, tool_name: str) -> Any:
        """Buka payload EFFECT_COMPLETED (dikodekan GenericSandbox) dan
        petakan ke API publik Executor lama: sukses -> return value mentah,
        gagal -> ToolNotFoundError / ToolExecutionError.
        """
        body = json.loads(payload.decode("utf-8"))
        status = body.get("status")

        if status == "ok":
            return body.get("result")

        if status == "error":
            error_type = body.get("error_type")
            message = body.get("message", "")

            if error_type == "tool_not_found":
                raise ToolNotFoundError(message, details={"tool_name": tool_name})

            if error_type == "execution_error":
                raise ToolExecutionError(
                    f"Tool '{tool_name}' raised an exception during execution.",
                    details={
                        "tool_name": tool_name,
                        "original_exception_class": body.get("error_class"),
                        "original_message": message,
                    },
                ) from None

            # "decode_error" atau error_type lain yang tak dikenal: envelope
            # dibangun Executor sendiri di atas -- kalau Sandbox menolaknya,
            # itu bug Executor/Sandbox, bukan kegagalan tool normal.
            raise RuntimeInvariantError(
                f"GenericSandbox melaporkan error_type={error_type!r} yang tidak "
                f"terduga untuk tool '{tool_name}': {message}",
                details={"tool_name": tool_name},
            )

        raise RuntimeInvariantError(
            f"EFFECT_COMPLETED payload untuk tool '{tool_name}' berisi "
            f"status={status!r} yang tidak dikenal.",
            details={"tool_name": tool_name},
        )