from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class MessageRole(str, Enum):
    """The role/author of a chat message.

    Inherits from ``str`` so values compare and serialize naturally
    (e.g. ``MessageRole.USER == "user"`` is ``True``).
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """A single message in a conversation.

    Attributes:
        role: Who authored this message.
        content: The text content of the message.
        metadata: Optional free-form extra context (e.g. tool call id,
            token count, timestamp) that providers or callers may attach.
    """

    role: MessageRole
    content: str
    metadata: Optional[Dict[str, Any]] = field(default=None)