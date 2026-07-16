from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _new_uuid() -> str:
    """Generate a new random UUID4 string.

    Returns:
        A UUID4 value formatted as a string.
    """
    return str(uuid.uuid4())


def _utc_now_iso() -> str:
    """Get the current UTC timestamp formatted as an ISO-8601 string.

    Returns:
        The current UTC time, e.g. ``"2026-07-16T06:19:22.123456+00:00"``.
    """
    return datetime.now(timezone.utc).isoformat()


@dataclass(kw_only=True)
class BaseModel:
    """Base class for all database record models.

    Provides a unique identifier and creation/update timestamps shared by
    every model, plus generic ``to_dict`` / ``from_dict`` serialization.

    Attributes:
        id: Unique identifier for the record (UUID4 string by default).
        created_at: ISO-8601 UTC timestamp of when the record was created.
        updated_at: ISO-8601 UTC timestamp of when the record was last updated.
    """

    id: str = field(default_factory=_new_uuid)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this model instance into a plain dictionary.

        Returns:
            A dictionary representation of all dataclass fields, suitable
            for JSON serialization or persistence.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseModel":
        """Build a model instance from a plain dictionary.

        Args:
            data: Dictionary containing keys matching the dataclass fields.
                Unknown keys are ignored; missing keys fall back to the
                field's default (if any).

        Returns:
            A new instance of the calling class populated from ``data``.
        """
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {key: value for key, value in data.items() if key in valid_fields}
        return cls(**filtered)

    def touch(self) -> None:
        """Update ``updated_at`` to the current UTC time in place."""
        self.updated_at = _utc_now_iso()


@dataclass(kw_only=True)
class ChatHistory(BaseModel):
    """A single message exchanged in a chat/conversation session.

    Attributes:
        session_id: Identifier grouping messages belonging to one conversation.
        role: Message author role, e.g. ``"user"``, ``"assistant"``, ``"system"``.
        message: The message text content.
        metadata: Optional free-form extra context (e.g. token usage, model name).
    """

    session_id: str = ""
    role: str = ""
    message: str = ""
    metadata: Optional[Dict[str, Any]] = None


@dataclass(kw_only=True)
class MemoryRecord(BaseModel):
    """A piece of long-term memory content, typically backed by a vector store.

    Attributes:
        collection: Name of the logical memory collection this record belongs to.
        content: The raw text content that was (or will be) embedded.
        embedding_id: Identifier of the corresponding vector in the vector store.
        metadata: Optional free-form extra context (e.g. source, tags).
    """

    collection: str = ""
    content: str = ""
    embedding_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass(kw_only=True)
class ToolExecution(BaseModel):
    """A record of a single tool/function invocation made by an agent.

    Attributes:
        tool_name: Name of the tool that was executed.
        input_data: Arguments passed to the tool.
        output_data: Result returned by the tool, if execution succeeded.
        status: Execution status, e.g. ``"pending"``, ``"success"``, ``"failed"``.
        error_message: Error description if the tool execution failed.
    """

    tool_name: str = ""
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Optional[Any] = None
    status: str = "pending"
    error_message: Optional[str] = None


@dataclass(kw_only=True)
class AuditLog(BaseModel):
    """A record of a security- or compliance-relevant action taken in the system.

    Attributes:
        actor: Identifier of who or what performed the action (user, agent, service).
        action: Short verb/phrase describing the action performed.
        resource: Identifier of the resource that was acted upon.
        details: Optional free-form extra context about the action.
    """

    actor: str = ""
    action: str = ""
    resource: str = ""
    details: Optional[Dict[str, Any]] = None