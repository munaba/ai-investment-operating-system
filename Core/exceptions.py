from __future__ import annotations
 
from typing import Any, Dict, Optional
 
 
class AgentError(Exception):
    """Base exception for every error raised within the AI Agent Framework.
 
    All custom exceptions in this project should inherit from this class so
    that callers can catch a single base type (``AgentError``) when they do
    not need to distinguish between specific failure modes.
 
    Attributes:
        message: Human-readable description of the error.
        details: Optional structured context (e.g. field name, provider
            name, status code) useful for logging and debugging.
    """
 
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the exception.
 
        Args:
            message: Human-readable description of the error.
            details: Optional dictionary with additional structured context.
        """
        super().__init__(message)
        self.message: str = message
        self.details: Dict[str, Any] = details or {}
 
    def __str__(self) -> str:
        """Return a readable string representation including details, if any."""
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message
 
    def __repr__(self) -> str:
        """Return an unambiguous representation useful for debugging/logs."""
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"
 
 
class ProviderError(AgentError):
    """Raised when an AI/LLM provider (e.g. Gemini, Claude, OpenAI) fails.
 
    Typical use cases: API errors, rate limiting (429), service unavailable
    (503), authentication failures, or malformed provider responses.
    """
 
 
class DatabaseError(AgentError):
    """Raised when a database operation fails.
 
    Typical use cases: connection failures, query errors, schema/migration
    issues, or constraint violations (e.g. SQLite, PostgreSQL).
    """
 
 
class ConfigurationError(AgentError):
    """Raised when configuration loading or validation fails.
 
    Typical use cases: missing required environment variables, invalid
    values in the ``.env`` file, or a missing configuration file.
    """
 
 
class ToolError(AgentError):
    """Raised when a tool or function invoked by an agent fails.
 
    Typical use cases: tool execution errors, invalid tool arguments, or
    unexpected tool output.
    """
 
 
class ValidationError(AgentError):
    """Raised when input or output data fails validation.
 
    Typical use cases: invalid user input, malformed API payloads, or data
    that fails schema/type checks before being persisted or sent onward.
    """