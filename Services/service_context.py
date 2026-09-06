"""Context value object passed into every service invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from Providers import Message


@dataclass
class ServiceContext:
    """Everything a service may need to fulfil a single request.

    A single, uniform context is built once per request and passed to
    every service that gets invoked for it, so services never need to
    reach back into agent-internal state.

    Attributes:
        agent_name: Name of the agent making this request.
        provider_name: Name of the LLM provider selected for this turn.
        request_id: Unique identifier correlating this request across
            logs/services (e.g. a UUID4 string).
        user_input: The raw end-user input that triggered this request.
        conversation_history: The conversation so far, oldest first.
        metadata: Optional free-form extra context (e.g. session id,
            locale, feature flags) that services may read.
    """

    agent_name: str
    provider_name: str
    request_id: str
    user_input: str
    conversation_history: List[Message] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_metadata(self, key: str, default: Optional[Any] = None) -> Any:
        """Convenience accessor for a single metadata value.

        Args:
            key: Metadata key to look up.
            default: Value returned if ``key`` is not present.
        """
        return self.metadata.get(key, default)
