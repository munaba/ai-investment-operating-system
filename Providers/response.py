from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Usage:
    """Token usage accounting for a single provider request.

    Attributes:
        input_tokens: Number of tokens in the input/prompt.
        output_tokens: Number of tokens generated in the output/completion.
        total_tokens: Total tokens consumed (input + output).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ProviderResponse:
    """A normalized response returned by any LLM provider.

    Attributes:
        text: The generated text content.
        finish_reason: Why generation stopped (e.g. ``"stop"``, ``"length"``,
            ``"MAX_TOKENS"``), as reported by the underlying provider.
        model: Name/identifier of the model that produced this response.
        usage: Token usage information for this request.
        raw_response: The original, unmodified response object returned by
            the underlying SDK, kept for advanced/debugging use cases.
        metadata: Additional provider-specific information that does not
            fit into the other fields.
    """

    text: str
    finish_reason: Optional[str] = None
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    raw_response: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)