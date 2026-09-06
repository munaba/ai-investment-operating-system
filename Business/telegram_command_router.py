"""telegram_command_router -- Phase E (Telegram Control Plane,
foundational task).

PARSING ONLY. Deterministically turns one inbound Telegram message's
raw text into a structured, typed result describing which supported
command (if any) it names and what its arguments are. This module
does not execute anything, does not decide authorization, does not
touch the database, does not make a network call, does not change any
risk limit, and does not place a paper or live order -- it is pure,
side-effect-free string parsing, exactly one function
(``parse_command``) plus the value objects it returns.

A future router/executor (explicitly out of scope for this task) is
responsible for taking a ``ParsedCommand`` and actually dispatching
it, checking ``Business.telegram_allowlist_policy`` for authorization,
and recording the outcome via
``Repository.persistence.telegram_command_audit_repository`` using
its own outcome constants (``EXECUTED`` / ``EXECUTED_REPLY_FAILED`` /
``REJECTED_UNAUTHORIZED`` / ``UNKNOWN_COMMAND`` / ``ERROR``). This
module supplies exactly one of the inputs that future router needs
(the parsed command) -- it never calls that repository or policy
itself.

Supported commands (LOCKED set for this task):

* ``/scan`` -- no arguments.
* ``/plan SYMBOL`` -- exactly one argument, the ticker symbol.
* ``/journal`` -- no arguments.
* ``/review`` -- no arguments.
* ``/health`` -- no arguments.
* ``/help`` -- no arguments.

Anything else is either ``UNKNOWN_COMMAND`` (the command word itself
is not one of the six above) or ``INVALID_COMMAND`` (the command word
*is* one of the six, but its arguments don't match what that command
accepts -- e.g. ``/plan`` with zero or more than one argument, or any
zero-argument command given extra arguments). Both cases return an
explicit, typed result -- never raise -- so a caller always has a
normalized command/argument record to persist for audit, whatever the
outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional, Tuple

#: The three possible outcomes of ``parse_command``.
PARSED: str = "PARSED"
UNKNOWN_COMMAND: str = "UNKNOWN_COMMAND"
INVALID_COMMAND: str = "INVALID_COMMAND"

#: The closed set of recognized command words (already normalized:
#: lowercase, leading ``/``, no ``@BotName`` suffix). Any command word
#: outside this set is ``UNKNOWN_COMMAND`` regardless of its
#: arguments.
SUPPORTED_COMMANDS: FrozenSet[str] = frozenset(
    {"/scan", "/plan", "/journal", "/review", "/health", "/help"}
)

#: Command words that take no arguments -- any argument supplied to
#: one of these is ``INVALID_COMMAND``. ``/plan`` is deliberately
#: excluded (it requires exactly one argument, validated separately).
_ZERO_ARG_COMMANDS: FrozenSet[str] = frozenset(
    {"/scan", "/journal", "/review", "/health", "/help"}
)


@dataclass(frozen=True)
class ParsedCommand:
    """The outcome of parsing one inbound Telegram message's raw text.

    Always constructed by ``parse_command`` -- never raised as an
    exception, so a caller always has a value to persist for audit
    (``Repository.persistence.telegram_command_audit_repository``
    expects exactly this normalized command/arguments shape),
    regardless of whether parsing actually succeeded.

    Attributes:
        action: One of ``PARSED`` / ``UNKNOWN_COMMAND`` /
            ``INVALID_COMMAND``.
        is_valid: Convenience flag, ``True`` iff ``action == PARSED``.
        command: The normalized command word (lowercase, leading
            ``/``, any ``@BotName`` suffix stripped) -- e.g.
            ``"/plan"``. Empty string only when ``raw_text`` had no
            command word at all (blank input).
        args: The whitespace-split argument tokens following the
            command word, exactly as given (not normalized), for
            audit fidelity. Empty tuple when there were none.
        symbol: For a successfully parsed ``/plan SYMBOL``, the
            argument uppercased and stripped (tickers are
            case-insensitive by convention). ``None`` for every other
            command, and ``None`` when ``/plan`` itself was
            malformed (the raw argument is still visible in ``args``).
        raw_text: The original, unmodified input text, preserved
            verbatim for audit.
        reason: One-line human-readable explanation of the outcome,
            for audit logging. ``None`` only when ``action == PARSED``.
    """

    action: str
    is_valid: bool
    command: str
    args: Tuple[str, ...]
    symbol: Optional[str]
    raw_text: str
    reason: Optional[str]


def _strip_bot_suffix(command_word: str) -> str:
    """Strip an optional ``@BotName`` suffix from a command word.

    Telegram appends ``@BotName`` to commands in group chats (e.g.
    ``/plan@MyTradingBot``) -- this is a fixed, deterministic string
    transform, not a lookup of any actual bot name, so it stays pure.
    """
    at_index = command_word.find("@")
    return command_word[:at_index] if at_index != -1 else command_word


def parse_command(raw_text: str) -> ParsedCommand:
    """Deterministically parse one inbound Telegram message's raw text.

    Pure function: no randomness, no clock, no I/O of any kind. The
    same ``raw_text`` always produces an equal ``ParsedCommand``.

    Args:
        raw_text: The raw message text as received from Telegram
            (e.g. ``"/plan AAPL"``). May be ``None``/empty/whitespace
            -- treated as blank input, not an error.

    Returns:
        A ``ParsedCommand`` describing the outcome. Never raises.
    """
    original = raw_text if raw_text is not None else ""
    text = original.strip()

    if not text:
        return ParsedCommand(
            action=INVALID_COMMAND,
            is_valid=False,
            command="",
            args=(),
            symbol=None,
            raw_text=original,
            reason="empty command text",
        )

    tokens = text.split()
    command = _strip_bot_suffix(tokens[0]).lower()
    args: Tuple[str, ...] = tuple(tokens[1:])

    if command not in SUPPORTED_COMMANDS:
        return ParsedCommand(
            action=UNKNOWN_COMMAND,
            is_valid=False,
            command=command,
            args=args,
            symbol=None,
            raw_text=original,
            reason=f"{command!r} is not a supported command",
        )

    if command == "/plan":
        if len(args) != 1 or not args[0].strip():
            return ParsedCommand(
                action=INVALID_COMMAND,
                is_valid=False,
                command=command,
                args=args,
                symbol=None,
                raw_text=original,
                reason="/plan requires exactly one SYMBOL argument",
            )
        return ParsedCommand(
            action=PARSED,
            is_valid=True,
            command=command,
            args=args,
            symbol=args[0].strip().upper(),
            raw_text=original,
            reason=None,
        )

    if command in _ZERO_ARG_COMMANDS and args:
        return ParsedCommand(
            action=INVALID_COMMAND,
            is_valid=False,
            command=command,
            args=args,
            symbol=None,
            raw_text=original,
            reason=f"{command!r} does not take any arguments",
        )

    return ParsedCommand(
        action=PARSED,
        is_valid=True,
        command=command,
        args=args,
        symbol=None,
        raw_text=original,
        reason=None,
    )