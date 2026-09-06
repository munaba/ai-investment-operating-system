"""TelegramAllowlistPolicy -- Phase E (Telegram Control Plane,
foundational task).

Pure decision logic answering: given the ``chat_id`` an inbound
Telegram command was received from, is that chat authorized to issue
commands at all?

Fail closed (LOCKED DECISION): if no allowed chat id can be
determined -- ``TELEGRAM_ALLOWED_CHAT_IDS`` unset/empty AND the
``TELEGRAM_CHAT_ID`` single-user fallback also unset -- then *no*
chat is authorized. An empty/unconfigured allowlist is never
interpreted as "allow everyone"; it is the strictest possible state.

Configuration source (read only by the ``load_*`` factory, never by
the policy itself):

* ``TELEGRAM_ALLOWED_CHAT_IDS`` -- comma-separated list of chat ids
  authorized to issue commands (e.g. ``"111111,222222"``).
* ``TELEGRAM_CHAT_ID`` -- the existing single-user credential already
  read by ``Core.composition_root._notification_service_context_factory``
  for *outbound* notifications. Used here only as a fallback default
  allowlist (a single entry) when ``TELEGRAM_ALLOWED_CHAT_IDS`` is not
  set -- so a single-user deployment that only ever configured the
  existing outbound credential is authorized to command its own bot
  without any additional configuration.

This module never sends anything, never touches persistence, and
never decides *what* a command does -- it is handed a ``chat_id`` and
returns an authorization decision; the caller (a future router,
explicitly out of scope for this task) is responsible for acting on
it, including recording the outcome via
``Repository.persistence.telegram_command_audit_repository``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional

AUTHORIZED: str = "AUTHORIZED"
REJECTED_UNAUTHORIZED: str = "REJECTED_UNAUTHORIZED"


@dataclass(frozen=True)
class AllowlistDecision:
    """The outcome of evaluating one candidate ``chat_id``.

    Attributes:
        action: One of ``AUTHORIZED`` / ``REJECTED_UNAUTHORIZED``.
        authorized: Convenience flag, ``True`` iff
            ``action == AUTHORIZED``.
        reason: One-line human-readable explanation, for audit
            logging.
    """

    action: str
    authorized: bool
    reason: str


@dataclass(frozen=True)
class TelegramAllowlistPolicy:
    """Decides AUTHORIZED vs REJECTED for one candidate ``chat_id``.

    Pure and stateless: holds only the already-resolved set of
    allowed chat ids, performs no I/O, and produces the same decision
    for the same inputs every time.

    Attributes:
        allowed_chat_ids: The closed set of chat ids authorized to
            issue commands. An empty set means "no chat is
            authorized" (fail closed), never "allow everyone".
    """

    allowed_chat_ids: FrozenSet[str]

    def evaluate(self, chat_id: Optional[str]) -> AllowlistDecision:
        """Decide whether ``chat_id`` is authorized to issue commands.

        Args:
            chat_id: The Telegram chat identifier the inbound command
                was received from, or ``None`` if not available.

        Returns:
            An ``AllowlistDecision``. ``AUTHORIZED`` is returned only
            when ``chat_id`` is not ``None`` and is a member of
            ``allowed_chat_ids``. Every other case -- missing
            ``chat_id``, empty allowlist, or a ``chat_id`` not in the
            allowlist -- fails closed to ``REJECTED_UNAUTHORIZED``.
        """
        if not self.allowed_chat_ids:
            return AllowlistDecision(
                action=REJECTED_UNAUTHORIZED,
                authorized=False,
                reason="no allowed chat ids configured (fail closed)",
            )

        if chat_id is None:
            return AllowlistDecision(
                action=REJECTED_UNAUTHORIZED,
                authorized=False,
                reason="no chat id supplied with the inbound command",
            )

        if chat_id not in self.allowed_chat_ids:
            return AllowlistDecision(
                action=REJECTED_UNAUTHORIZED,
                authorized=False,
                reason=f"chat id {chat_id!r} is not in the configured allowlist",
            )

        return AllowlistDecision(
            action=AUTHORIZED,
            authorized=True,
            reason=f"chat id {chat_id!r} is in the configured allowlist",
        )


#: Environment variable names read by ``load_telegram_allowlist_policy``.
_TELEGRAM_ALLOWED_CHAT_IDS_ENV: str = "TELEGRAM_ALLOWED_CHAT_IDS"
_TELEGRAM_CHAT_ID_ENV: str = "TELEGRAM_CHAT_ID"


def _parse_chat_id_list(raw: Optional[str]) -> FrozenSet[str]:
    """Split a comma-separated chat-id string into a normalized set.

    Blank entries (from stray commas/whitespace) are dropped; each
    surviving entry is stripped. Returns an empty ``frozenset`` for
    ``None``/empty/all-blank input.
    """
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def load_telegram_allowlist_policy(env_get=None) -> TelegramAllowlistPolicy:
    """Build a ``TelegramAllowlistPolicy`` from environment
    configuration.

    Resolution order (LOCKED):

    1. ``TELEGRAM_ALLOWED_CHAT_IDS`` -- if set to a non-empty,
       non-blank comma-separated value, this is the allowlist,
       exactly as given (the ``TELEGRAM_CHAT_ID`` fallback is not
       consulted).
    2. ``TELEGRAM_CHAT_ID`` -- single-user default fallback. Used only
       when ``TELEGRAM_ALLOWED_CHAT_IDS`` resolved to an empty set.
    3. Neither set -- the resulting policy's ``allowed_chat_ids`` is
       empty, so every ``evaluate()`` call fails closed.

    Args:
        env_get: Optional injected lookup callable with the signature
            of ``Core.config.Config.get_str`` (``(key, default) ->
            Optional[str]``), for testing. Defaults to the shared
            ``Core.config.config`` singleton's ``get_str``.
    """
    if env_get is None:
        from Core.config import config as _config

        env_get = _config.get_str

    allowed_chat_ids = _parse_chat_id_list(env_get(_TELEGRAM_ALLOWED_CHAT_IDS_ENV, None))
    if not allowed_chat_ids:
        allowed_chat_ids = _parse_chat_id_list(env_get(_TELEGRAM_CHAT_ID_ENV, None))

    return TelegramAllowlistPolicy(allowed_chat_ids=allowed_chat_ids)