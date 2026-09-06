"""telegram_inbound_control_plane -- Phase E (Telegram Control Plane,
Task 5, FINAL task).

OWNS Telegram inbound long-polling, allowlist enforcement, audit
logging, and the durable long-poll offset. This is the single module
that ties together the four foundational pieces Tasks 1-4 already
built, none of which are modified here:

* ``Business.telegram_allowlist_policy.TelegramAllowlistPolicy`` --
  authorization decision for one ``chat_id`` (Task 2).
* ``Business.telegram_command_router.parse_command`` -- pure text ->
  ``ParsedCommand`` parsing (Task 3).
* ``Orchestration.telegram_command_executor.TelegramCommandExecutor``
  -- dispatches a ``ParsedCommand`` to the real, already-existing
  ``ApplicationGraph`` services (Task 4).
* ``Repository.persistence.telegram_command_audit_repository.
  TelegramCommandAuditRepository`` -- append-only audit log (Task 1).
* ``Repository.persistence.telegram_inbound_state_repository.
  TelegramInboundStateRepository`` -- durable ``last_update_id``
  (Task 1).

Reply mechanism (LOCKED, unchanged): outbound replies are sent through
the exact same, already-existing ``Services.notification_service.
NotificationService`` instance the rest of this codebase already uses
for Telegram notifications (see ``Business.telegram_notification_channel``
and ``Core.composition_root._build_notification_service`` /
``_notification_service_context_factory``). ``NotificationService``
itself is never modified, subclassed, or monkeypatched here -- this
module only builds its own ``ServiceContext`` per reply (exactly the
same value-object construction ``_notification_service_context_factory``
already performs, just with the *originating* chat id instead of the
single configured default one, since a reply must go back to whichever
chat actually sent the command -- ``TelegramNotificationChannel.send()``
has no seam for that per-call override, so it is not reused directly
here; nothing about it changes either).

Fetching updates (``getUpdates``) is new in this module because no
existing component fetches inbound Telegram updates at all -- Tasks
1-4 are deliberately read-only/parsing/execution-only building blocks
with no network access of their own (see each module's own docstring).
Owning that fetch is this task's entire stated purpose ("Own Telegram
polling"). It talks to the same ``https://api.telegram.org/bot<token>``
base URL ``NotificationService._send_telegram`` already uses, via a
plain ``requests``-compatible HTTP client (injectable for tests, lazily
imported otherwise -- the same seam ``NotificationService`` itself
uses).

Explicitly OUT OF SCOPE for this module (unchanged from every earlier
Phase E task):

* No broker/live execution. No automatic paper order. This module
  never imports anything from an order/broker/execution package, and
  never calls any such thing -- ``TelegramCommandExecutor`` (Task 4)
  already structurally forbids it, and this module adds nothing on
  top of what that executor already dispatches to.
* No LLM. No provider/agent call of any kind.
* No risk-limit changes. No new ``Core.config``/environment behavior
  beyond reading the same ``TELEGRAM_BOT_TOKEN`` environment variable
  ``Core.composition_root`` already reads for the identical purpose.
* Does not modify ``main.py``, ``Core.composition_root``, or
  ``Core.doctor``. Does not modify any of the Task 1-4 modules listed
  above, or ``Services.notification_service`` /
  ``Business.telegram_notification_channel``.
* Not wired into ``Core.composition_root.build_application`` or
  ``main.py`` by this task -- this module is a standalone,
  self-contained orchestrator a future (out-of-scope) entrypoint can
  import and drive. ``build_control_plane_from_graph`` below is the
  one convenience constructor provided for that future caller; calling
  it performs no I/O itself.

Restart safety / duplicate protection (LOCKED DECISION): the durable
``last_update_id`` (``TelegramInboundStateRepository``) is the single
source of truth for "already processed". Within one ``poll_once()``
call, updates are processed in ascending ``update_id`` order; the
in-memory high-water mark is advanced only after an update has been
fully handled (audit recorded, reply attempted), and is persisted to
the repository immediately after -- so a crash between two updates
loses no more than the update currently in flight, which will simply
be re-fetched (and, per the in-memory/durable check below, safely
re-attempted -- never double-executed for anything at or below the
already-persisted offset) on the next call. Any ``update_id`` less
than or equal to the offset in force at the start of this call is
skipped entirely (no re-parse, no re-execute, no duplicate audit row,
no duplicate reply) -- this is what makes a duplicate delivery within
one fetched batch, or a redelivered already-processed update, a no-op.

Audit vocabulary (LOCKED, shared with Task 1/4, imported -- never
redefined): ``EXECUTED`` / ``EXECUTED_REPLY_FAILED`` /
``REJECTED_UNAUTHORIZED`` / ``UNKNOWN_COMMAND`` / ``ERROR``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

from Business.telegram_allowlist_policy import (
    AUTHORIZED,
    TelegramAllowlistPolicy,
    load_telegram_allowlist_policy,
)
from Business.telegram_command_router import ParsedCommand, parse_command
from Core.exceptions import RepositoryError
from Orchestration.telegram_command_executor import ExecutionResult, TelegramCommandExecutor
from Repository.persistence.telegram_command_audit_repository import (
    ERROR,
    EXECUTED,
    EXECUTED_REPLY_FAILED,
    REJECTED_UNAUTHORIZED,
    TelegramCommandAuditRepository,
)
from Repository.persistence.telegram_inbound_state_repository import (
    DEFAULT_STATE_KEY,
    TelegramInboundStateRepository,
)
from Services.metadata_keys import MetadataKeys
from Services.notification_service import NotificationService
from Services.service_context import ServiceContext

#: Environment variable this module reads the Telegram bot token from
#: -- the exact same name ``Core.composition_root`` and ``Core.doctor``
#: already read for the identical credential (see those modules'
#: ``_TELEGRAM_BOT_TOKEN_ENV`` constants). Read only via the injected
#: ``env_get``/``Core.config.config.get_str`` seam -- never hard-coded.
TELEGRAM_BOT_TOKEN_ENV: str = "TELEGRAM_BOT_TOKEN"

#: Fixed ``ServiceContext.agent_name`` this module supplies for every
#: reply it sends -- mirrors ``Core.composition_root.
#: _NOTIFICATION_AGENT_NAME``'s own "no real agent/provider turn is
#: involved" rationale, just labeled for this call site specifically
#: so the two are distinguishable in logs/audit.
_REPLY_AGENT_NAME: str = "telegram_inbound_control_plane"

#: HTTP request timeout, in seconds, for the ``getUpdates`` call --
#: mirrors ``Services.notification_service._REQUEST_TIMEOUT_SECONDS``.
_REQUEST_TIMEOUT_SECONDS: int = 10

#: Telegram long-poll ``timeout`` query parameter default, in seconds.
#: ``0`` means "return immediately with whatever is already queued" --
#: the safe default for a caller-driven ``poll_once()`` loop (a
#: production long-running driver, out of scope here, may inject a
#: larger value).
_DEFAULT_POLL_TIMEOUT_SECONDS: int = 0


class TelegramInboundControlPlaneError(Exception):
    """Raised only for a failed ``getUpdates`` HTTP call.

    Always caught internally by :meth:`TelegramInboundControlPlane.poll_once`
    and turned into a failed :class:`PollOutcome` -- never escapes this
    module's public API.
    """


def _default_clock() -> str:
    """Real UTC-now ISO-8601 timestamp -- this module's sole source of
    non-determinism, isolated here so it can be overridden by
    ``TelegramInboundControlPlane``'s injectable ``clock`` for
    deterministic tests. Mirrors
    ``Orchestration.telegram_command_executor._default_clock``.
    """
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UpdateOutcome:
    """The fully-resolved outcome of handling one inbound Telegram update.

    Attributes:
        update_id: The Telegram ``update_id`` this outcome is for.
        chat_id: The originating chat id, or ``None`` if the update
            carried no message/chat at all.
        command: The parsed command word (e.g. ``"/plan"``), or ``""``
            for an update with no command text to parse.
        status: One of the audit vocabulary constants imported from
            ``Repository.persistence.telegram_command_audit_repository``,
            or ``"SKIPPED_NO_COMMAND"`` / ``"SKIPPED_DUPLICATE"`` for
            the two cases this module handles without writing an audit
            row at all (see class docstring).
        reply_sent: ``True`` iff a reply was attempted and succeeded.
            ``False`` if no reply was attempted, or one was attempted
            and failed.
        detail: Optional free-text detail (mirrors the audit row's own
            ``detail``, when one was written).
    """

    update_id: int
    chat_id: Optional[str]
    command: str
    status: str
    reply_sent: bool
    detail: Optional[str] = None


#: Outcome values used only in-process (never written to the audit
#: table -- the audit vocabulary in
#: ``telegram_command_audit_repository`` has no equivalent for either,
#: because neither case involves a command worth auditing).
SKIPPED_NO_COMMAND: str = "SKIPPED_NO_COMMAND"
SKIPPED_DUPLICATE: str = "SKIPPED_DUPLICATE"


@dataclass
class PollOutcome:
    """The result of one :meth:`TelegramInboundControlPlane.poll_once` call.

    Attributes:
        polling_failed: ``True`` iff the ``getUpdates`` HTTP call
            itself failed (network error, non-200, non-``ok`` body).
            When ``True``, ``updates`` is always empty and
            ``last_update_id`` is unchanged (nothing was fetched, so
            nothing could have been handled).
        polling_error: The failure detail when ``polling_failed`` is
            ``True``, else ``None``.
        updates: One :class:`UpdateOutcome` per update present in the
            fetched batch, in ascending ``update_id`` order -- even
            for updates skipped as duplicates or as having no command.
        last_update_id: The durable ``last_update_id`` now on record
            for this state key (after this call), or ``None`` if
            polling has never advanced.
    """

    polling_failed: bool
    polling_error: Optional[str]
    updates: List[UpdateOutcome] = field(default_factory=list)
    last_update_id: Optional[int] = None


class TelegramInboundControlPlane:
    """Owns Telegram inbound polling + allowlist + audit + durable offset.

    Constructor injection only, mirroring every other
    service/orchestrator in this codebase. Holds no reference to any
    broker/execution component (there is no import of any such thing
    here) and performs no LLM/provider call of any kind.
    """

    def __init__(
        self,
        allowlist_policy: TelegramAllowlistPolicy,
        executor: TelegramCommandExecutor,
        audit_repository: TelegramCommandAuditRepository,
        inbound_state_repository: TelegramInboundStateRepository,
        notification_service: NotificationService,
        *,
        bot_token: str,
        http_client: Optional[Any] = None,
        clock: Callable[[], str] = _default_clock,
        state_key: str = DEFAULT_STATE_KEY,
        poll_timeout_seconds: int = _DEFAULT_POLL_TIMEOUT_SECONDS,
    ) -> None:
        """Store the collaborators this control plane coordinates.

        Args:
            allowlist_policy: The real (or test-double)
                ``TelegramAllowlistPolicy`` -- Task 2. Stored by
                identity, never rebuilt here.
            executor: The real (or test-double)
                ``TelegramCommandExecutor`` -- Task 4.
            audit_repository: The real (or test-double)
                ``TelegramCommandAuditRepository`` -- Task 1.
            inbound_state_repository: The real (or test-double)
                ``TelegramInboundStateRepository`` -- Task 1.
            notification_service: The existing, unmodified
                ``NotificationService`` singleton to send replies
                through -- never a new implementation.
            bot_token: The Telegram bot token, used both for this
                module's own ``getUpdates`` call and as the
                ``telegram_bot_token`` credential handed to
                ``notification_service`` for replies. Read by the
                caller (see ``build_control_plane_from_graph``) from
                the same ``TELEGRAM_BOT_TOKEN`` environment variable
                ``Core.composition_root`` already reads -- never
                hard-coded, never invented here.
            http_client: Optional pre-configured HTTP client (or a
                test double exposing a ``requests``-compatible
                ``.get(url, params=..., timeout=...)`` method).
                Defaults to a lazily-imported ``requests`` module --
                the same injection seam ``NotificationService`` itself
                uses.
            clock: Injectable ISO-8601 UTC-now supplier, used only for
                ``received_at`` audit timestamps. Defaults to a real
                clock read; tests may inject a fixed supplier.
            state_key: Stable identifier for this polling identity.
                Defaults to ``DEFAULT_STATE_KEY`` for a single-bot
                deployment.
            poll_timeout_seconds: Telegram long-poll ``timeout`` query
                parameter. Defaults to ``0`` (return immediately).
        """
        self._allowlist_policy = allowlist_policy
        self._executor = executor
        self._audit_repository = audit_repository
        self._inbound_state_repository = inbound_state_repository
        self._notification_service = notification_service
        self._bot_token = bot_token
        self._http_client = http_client
        self._clock = clock
        self._state_key = state_key
        self._poll_timeout_seconds = poll_timeout_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll_once(self) -> PollOutcome:
        """Fetch one batch of Telegram updates and process each deterministically.

        Never raises: a fetch failure becomes a ``PollOutcome`` with
        ``polling_failed=True``; a per-update processing failure that
        happens after a successful fetch is instead caught by
        ``_process_update`` and turned into an ``ERROR``-status
        ``UpdateOutcome`` for that update alone (processing continues
        with the next update). A durable-offset read failure (e.g. the
        ``telegram_inbound_state``/``telegram_command_audit`` tables
        not yet migrated -- see ``run_telegram_control_migrations.py``)
        is treated the same way as a ``getUpdates`` fetch failure: it
        becomes ``polling_failed=True`` with the underlying detail
        preserved, never an unhandled exception. ``Core.doctor``'s own
        Telegram Inbound Control Plane section already surfaces this
        exact missing-table condition as an actionable BLOCKED check
        before a caller ever reaches this method; this guard is this
        method's own belt-and-braces enforcement of its documented
        "never raises" contract regardless of whether doctor was run
        first.

        Returns:
            A :class:`PollOutcome` describing exactly what happened.
        """
        try:
            last_update_id = self._inbound_state_repository.get_last_update_id(self._state_key)
        except RepositoryError as exc:
            return PollOutcome(
                polling_failed=True,
                polling_error=(
                    f"could not read the durable polling offset: {exc}. Run "
                    "'python run_telegram_control_migrations.py' if the "
                    "telegram_control tables are not yet migrated."
                ),
                updates=[],
                last_update_id=None,
            )

        try:
            raw_updates = self._fetch_updates(last_update_id)
        except TelegramInboundControlPlaneError as exc:
            return PollOutcome(
                polling_failed=True,
                polling_error=str(exc),
                updates=[],
                last_update_id=last_update_id,
            )

        outcomes: List[UpdateOutcome] = []
        high_water_mark = last_update_id

        for raw_update in sorted(raw_updates, key=lambda item: item.get("update_id", 0)):
            update_id = raw_update.get("update_id")
            if update_id is None:
                # No identifiable update_id at all -- nothing durable
                # can be recorded for it, so it is neither audited nor
                # allowed to advance the offset. Telegram never
                # actually omits this field; defended against anyway
                # so a malformed payload cannot raise.
                continue

            if high_water_mark is not None and update_id <= high_water_mark:
                outcomes.append(
                    UpdateOutcome(
                        update_id=update_id,
                        chat_id=self._extract_chat_id(raw_update),
                        command="",
                        status=SKIPPED_DUPLICATE,
                        reply_sent=False,
                        detail="update_id at or below the durable offset; skipped",
                    )
                )
                continue

            outcome = self._process_update(raw_update)
            outcomes.append(outcome)

            # Persist last_update_id only now that this update has been
            # fully handled (audit written and/or reply attempted, per
            # _process_update). A failure inside _process_update itself
            # is already caught there and turned into an ERROR outcome
            # -- this line still runs, since "handled" (including
            # handled-with-an-error, which is itself an explicit,
            # audited terminal outcome) is exactly what happened.
            high_water_mark = update_id
            self._inbound_state_repository.set_last_update_id(
                update_id, updated_at=self._clock(), state_key=self._state_key
            )

        return PollOutcome(
            polling_failed=False,
            polling_error=None,
            updates=outcomes,
            last_update_id=high_water_mark,
        )

    # ------------------------------------------------------------------
    # Per-update processing
    # ------------------------------------------------------------------

    def _process_update(self, raw_update: dict) -> UpdateOutcome:
        """Process exactly one already-fetched, not-yet-handled update.

        Never raises: any unexpected exception from a collaborator
        this module calls directly (allowlist evaluation, parsing,
        audit write, reply send -- ``TelegramCommandExecutor.execute``
        already guarantees it never raises on its own) is caught here
        and turned into an ``ERROR`` audit row, so ``poll_once`` can
        always advance past this update.
        """
        update_id = raw_update["update_id"]
        chat_id = self._extract_chat_id(raw_update)
        text = self._extract_text(raw_update)

        if text is None:
            # Not a text message this control plane understands
            # (e.g. no "message" key at all, or a message with no
            # "text" -- a photo, a sticker, a service message, ...).
            # Nothing to route, execute, or audit; still "handled".
            return UpdateOutcome(
                update_id=update_id,
                chat_id=chat_id,
                command="",
                status=SKIPPED_NO_COMMAND,
                reply_sent=False,
                detail="update carried no message text",
            )

        try:
            parsed = parse_command(text)
            decision = self._allowlist_policy.evaluate(chat_id)

            if not decision.authorized:
                self._audit_repository.record(
                    parsed.command,
                    status=REJECTED_UNAUTHORIZED,
                    received_at=self._clock(),
                    update_id=update_id,
                    chat_id=chat_id,
                    raw_text=text,
                    detail=decision.reason,
                )
                # LOCKED DECISION: an unauthorized chat gets no reply at
                # all -- silently dropping an unauthorized command
                # avoids confirming the bot's presence/behavior to a
                # chat that was never granted access, and the command
                # is never executed either way.
                return UpdateOutcome(
                    update_id=update_id,
                    chat_id=chat_id,
                    command=parsed.command,
                    status=REJECTED_UNAUTHORIZED,
                    reply_sent=False,
                    detail=decision.reason,
                )

            return self._execute_and_reply(parsed, chat_id=chat_id, update_id=update_id, text=text)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # unexpected failure anywhere in this update's handling must
            # become an explicit, audited ERROR outcome, never an
            # exception that escapes poll_once and stalls the offset.
            detail = str(exc)
            try:
                self._audit_repository.record(
                    "",
                    status=ERROR,
                    received_at=self._clock(),
                    update_id=update_id,
                    chat_id=chat_id,
                    raw_text=text,
                    detail=detail,
                )
            except Exception:  # noqa: BLE001 -- audit itself is unavailable;
                # still resolve this update as handled below rather than
                # raise, so the caller does not stall on this update.
                pass
            return UpdateOutcome(
                update_id=update_id,
                chat_id=chat_id,
                command="",
                status=ERROR,
                reply_sent=False,
                detail=detail,
            )

    def _execute_and_reply(
        self, parsed: ParsedCommand, *, chat_id: Optional[str], update_id: int, text: str
    ) -> UpdateOutcome:
        """Execute an authorized, parsed command, send its reply, and
        audit the final outcome exactly once.
        """
        result: ExecutionResult = self._executor.execute(parsed, chat_id=chat_id, update_id=update_id)

        reply_sent = False
        reply_detail: Optional[str] = None
        if chat_id is not None:
            reply_sent, reply_detail = self._send_reply(chat_id, result.reply_text)
        else:
            reply_detail = "no chat id available to reply to"

        final_status = result.outcome
        final_detail = result.detail
        if result.outcome == EXECUTED and not reply_sent:
            # Only a successfully-EXECUTED command's reply failure gets
            # its own audit status (per the LOCKED, closed audit
            # vocabulary) -- a reply failure after UNKNOWN_COMMAND/ERROR
            # does not invent a new status; the reply failure detail is
            # still preserved below either way.
            final_status = EXECUTED_REPLY_FAILED
            final_detail = reply_detail if final_detail is None else f"{final_detail}; {reply_detail}"
        elif not reply_sent and reply_detail is not None:
            final_detail = reply_detail if final_detail is None else f"{final_detail}; {reply_detail}"

        self._audit_repository.record(
            parsed.command,
            status=final_status,
            received_at=self._clock(),
            update_id=update_id,
            chat_id=chat_id,
            raw_text=text,
            detail=final_detail,
        )

        return UpdateOutcome(
            update_id=update_id,
            chat_id=chat_id,
            command=parsed.command,
            status=final_status,
            reply_sent=reply_sent,
            detail=final_detail,
        )

    # ------------------------------------------------------------------
    # Reply mechanism -- delegates to the existing NotificationService
    # ------------------------------------------------------------------

    def _send_reply(self, chat_id: str, text: str) -> "tuple[bool, Optional[str]]":
        """Send ``text`` back to ``chat_id`` via the existing
        ``NotificationService``, never raising.

        Returns:
            ``(True, None)`` on success, or ``(False, detail)`` on any
            failure -- a failed ``ServiceResult`` (the normal,
            already-caught-internally failure path) or an unexpected
            exception (defended against even though
            ``NotificationService.execute`` documents that it never
            raises).
        """
        context = ServiceContext(
            agent_name=_REPLY_AGENT_NAME,
            provider_name="",
            request_id=str(uuid.uuid4()),
            user_input="",
            metadata={
                MetadataKeys.CHANNEL: "telegram",
                MetadataKeys.MESSAGE: text,
                MetadataKeys.TELEGRAM_BOT_TOKEN: self._bot_token,
                MetadataKeys.TELEGRAM_CHAT_ID: chat_id,
            },
        )
        try:
            result = self._notification_service.execute(context)
        except Exception as exc:  # noqa: BLE001 -- defensive; execute() is
            # documented to never raise, but a reply failure must never
            # propagate out of this control plane either way.
            return False, str(exc)

        if result.success:
            return True, None
        return False, result.message or "reply send failed"

    # ------------------------------------------------------------------
    # Fetching updates -- new in this module (see class docstring)
    # ------------------------------------------------------------------

    def _fetch_updates(self, last_update_id: Optional[int]) -> List[dict]:
        """Call Telegram's ``getUpdates`` and return the raw ``result`` list.

        Raises:
            TelegramInboundControlPlaneError: If the HTTP call itself
                fails, or Telegram responds with a non-200 status or a
                non-``ok`` body. Always caught by ``poll_once``.
        """
        http_client = self._get_http_client()
        base_url = f"https://api.telegram.org/bot{self._bot_token}"
        params = {"timeout": self._poll_timeout_seconds}
        if last_update_id is not None:
            params["offset"] = last_update_id + 1

        try:
            response = http_client.get(
                f"{base_url}/getUpdates", params=params, timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 -- normalize any transport-level error
            raise TelegramInboundControlPlaneError(f"getUpdates request failed: {exc}") from exc

        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise TelegramInboundControlPlaneError(
                f"getUpdates returned a non-JSON body: {exc}"
            ) from exc

        status_code = getattr(response, "status_code", None)
        is_ok = bool(body.get("ok")) if isinstance(body, dict) else False
        if status_code != 200 or not is_ok:
            description = body.get("description") if isinstance(body, dict) else None
            raise TelegramInboundControlPlaneError(
                f"getUpdates call failed: {description or status_code}"
            )

        result = body.get("result") if isinstance(body, dict) else None
        return list(result) if isinstance(result, list) else []

    def _get_http_client(self) -> Any:
        """Resolve the HTTP client, injected or lazily imported.

        Mirrors ``Services.notification_service.NotificationService.
        _get_http_client`` exactly (same seam, same failure mode).
        """
        if self._http_client is not None:
            return self._http_client
        try:
            import requests
        except ImportError as exc:
            raise TelegramInboundControlPlaneError(
                "requests is not installed. Install it with 'pip install requests'."
            ) from exc
        return requests

    # ------------------------------------------------------------------
    # Raw update helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_chat_id(raw_update: dict) -> Optional[str]:
        """Return the originating chat id as a string, or ``None``.

        Only ``message.chat.id`` is read (the six supported commands
        are only ever issued as plain text messages) -- an
        ``edited_message``/``channel_post``/other update shape yields
        ``None`` here, which ``_extract_text`` also treats as "nothing
        to process".
        """
        message = raw_update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return None
        chat_id = chat.get("id")
        return str(chat_id) if chat_id is not None else None

    @staticmethod
    def _extract_text(raw_update: dict) -> Optional[str]:
        """Return the message's raw text, or ``None`` if this update
        carries no processable text message.
        """
        message = raw_update.get("message")
        if not isinstance(message, dict):
            return None
        text = message.get("text")
        return text if isinstance(text, str) and text != "" else None


def build_control_plane_from_graph(
    graph: Any,
    *,
    allowlist_policy: Optional[TelegramAllowlistPolicy] = None,
    http_client: Optional[Any] = None,
    clock: Callable[[], str] = _default_clock,
    state_key: str = DEFAULT_STATE_KEY,
    poll_timeout_seconds: int = _DEFAULT_POLL_TIMEOUT_SECONDS,
    env_get: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
) -> TelegramInboundControlPlane:
    """Convenience constructor wiring a ``TelegramInboundControlPlane``
    from an already-built ``Core.composition_root.ApplicationGraph``.

    Performs no I/O itself -- purely object construction, same as every
    ``_build_*`` function in ``Core.composition_root`` (which this
    function deliberately does not modify or add to; a future,
    out-of-scope entrypoint is responsible for actually calling this).

    Args:
        graph: The ``ApplicationGraph`` produced by
            ``Core.composition_root.build_application()``. Read for
            ``graph.database_manager`` (to construct the two Task 1
            repositories over the exact same shared database, never a
            second one), ``graph.manual_scan_service`` /
            ``.decision_brief_service`` / ``.journal_service`` /
            ``.performance_summary_production_service`` (to construct
            the Task 4 executor), and
            ``graph.service_registry.get("notification_service")``
            (the exact same ``NotificationService`` singleton
            ``Core.composition_root._build_notification_service``
            already registered -- never a second instance).
        allowlist_policy: Optional pre-built policy; defaults to
            ``Business.telegram_allowlist_policy.
            load_telegram_allowlist_policy()`` (Task 2's own
            environment-driven factory, unmodified).
        http_client: Passed straight through to
            ``TelegramInboundControlPlane``.
        clock: Passed straight through to
            ``TelegramInboundControlPlane``.
        state_key: Passed straight through to
            ``TelegramInboundControlPlane``.
        poll_timeout_seconds: Passed straight through to
            ``TelegramInboundControlPlane``.
        env_get: Optional injected lookup callable
            (``(key, default) -> Optional[str]``), for testing.
            Defaults to the shared ``Core.config.config.get_str``.

    Returns:
        A fully-wired ``TelegramInboundControlPlane``.

    Raises:
        ValueError: If no ``TELEGRAM_BOT_TOKEN`` is configured -- this
            control plane cannot poll or reply without one, so failing
            fast at construction time is preferable to a confusing
            failure on the first ``poll_once()`` call.
    """
    if env_get is None:
        from Core.config import config as _config

        env_get = _config.get_str

    bot_token = env_get(TELEGRAM_BOT_TOKEN_ENV, None)
    if not bot_token:
        raise ValueError(
            f"{TELEGRAM_BOT_TOKEN_ENV} is not configured; cannot build a "
            "TelegramInboundControlPlane without it."
        )

    resolved_allowlist_policy = allowlist_policy or load_telegram_allowlist_policy(env_get=env_get)

    audit_repository = TelegramCommandAuditRepository(graph.database_manager)
    inbound_state_repository = TelegramInboundStateRepository(graph.database_manager)

    executor = TelegramCommandExecutor(
        graph.manual_scan_service,
        graph.decision_brief_service,
        graph.journal_service,
        graph.performance_summary_production_service,
    )

    notification_service = graph.service_registry.get("notification_service")

    return TelegramInboundControlPlane(
        resolved_allowlist_policy,
        executor,
        audit_repository,
        inbound_state_repository,
        notification_service,
        bot_token=bot_token,
        http_client=http_client,
        clock=clock,
        state_key=state_key,
        poll_timeout_seconds=poll_timeout_seconds,
    )