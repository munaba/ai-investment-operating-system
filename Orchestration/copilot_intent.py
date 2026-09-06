"""CopilotIntent -- Phase F, Task 2: the closed intent vocabulary for the
copilot capability contract defined in Task 1.

Scope note (LOCKED for this task): this module introduces exactly one
thing -- ``CopilotIntent``, a closed ``Enum`` naming the five intents the
copilot contract may classify a user utterance into. Nothing else.

Explicitly NOT part of this task: a classifier, a provider call, a tool,
a skill, a registry, Composition Root wiring, Telegram wiring, database
access, or any side effect. This module is standalone and deterministic
-- it performs no I/O, holds no provider dependency, executes no tool,
and reads/writes no external or persistent state. It mirrors the
existing ``Enum`` convention used by
``Orchestration.task.TaskStatus`` (plain ``Enum`` with ``auto()``
members) rather than ``Orchestration.tool_permission.ToolPermission``'s
``str, Enum`` convention, because -- like ``TaskStatus`` -- intent
membership itself is what matters here, not a serialized wire value.

Dependency direction: this module imports only the stdlib ``enum``
module plus ``Core.exceptions.AgentError`` (for its own exception type,
following the same convention as ``TaskError``/``ToolPermissionError``/
``MemoryError``). It does not import from, and is not imported by, any
``Providers``, ``Orchestration.base_tool``, ``Orchestration.base_skill``,
``Orchestration.memory``, ``Orchestration.tool_permission``,
``Orchestration.permission_context``, ``Core.composition_root``, or
Telegram module. It is additive-only, standing on its own until a
future task builds a classifier on top of it.
"""

from __future__ import annotations

from enum import Enum, auto

from Core.exceptions import AgentError


class CopilotIntentError(AgentError):
    """Raised when an invalid ``CopilotIntent`` value is requested.

    Following the same convention as ``TaskError``/
    ``ToolPermissionError``/``MemoryError`` (all subclass
    ``Core.exceptions.AgentError`` directly). Raised only by
    ``CopilotIntent.from_value`` for an unrecognized name -- this
    module performs no other validation.
    """


class CopilotIntent(Enum):
    """The closed set of intents the copilot capability contract (Phase
    F, Task 1) may classify a user utterance into.

    Exactly five members, matching the four supported capabilities
    (explanation, summary, memory retrieval -- split into
    ``EXPLAIN_DECISION``, ``SUMMARIZE_PORTFOLIO``, and
    ``RECALL_PREFERENCE``) plus one general status query
    (``ASK_STATUS``) and one explicit fallback (``UNSUPPORTED``) for
    anything outside the contract. Intent classification itself is
    not implemented here -- this enum only names the possible
    outcomes.
    """

    EXPLAIN_DECISION = auto()
    SUMMARIZE_PORTFOLIO = auto()
    RECALL_PREFERENCE = auto()
    ASK_STATUS = auto()
    UNSUPPORTED = auto()

    @classmethod
    def from_value(cls, value: "str | CopilotIntent") -> "CopilotIntent":
        """Normalize a member name or existing member to the canonical enum member.

        Mirrors ``Orchestration.tool_permission.ToolPermission.from_value``'s
        shape (idempotent on an existing member, case/whitespace-tolerant
        on a string), adapted for a plain (non-``str``) ``Enum`` by
        matching on member ``name`` rather than ``value``.

        Args:
            value: Either an existing ``CopilotIntent`` member (returned
                unchanged) or a string matching a member's name,
                case-insensitively and with surrounding whitespace
                ignored (e.g. ``"explain_decision"``).

        Returns:
            The canonical ``CopilotIntent`` member.

        Raises:
            CopilotIntentError: If ``value`` is neither a
                ``CopilotIntent`` nor a string matching a known
                member name.
        """
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise CopilotIntentError(
                f"CopilotIntent requires a str value; got {value!r}"
            )
        normalized = value.strip().upper()
        for intent in cls:
            if normalized == intent.name:
                return intent
        raise CopilotIntentError(f"Unknown copilot intent: {value!r}")