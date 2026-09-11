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
 
 
class RepositoryError(AgentError):
    """Raised when a repository fails to fetch or normalize external data.

    Typical use cases: an external data provider (e.g. yfinance) is not
    installed, a network/SDK call fails, or a provider returns no usable
    data for the requested resource. Repositories translate
    provider-specific exceptions into this single error type so that
    Services never need to know which external SDK is involved.
    """


class ValidationError(AgentError):
    """Raised when input or output data fails validation.

    Typical use cases: invalid user input, malformed API payloads, or data
    that fails schema/type checks before being persisted or sent onward.
    """


class BootstrapError(AgentError):
    """Raised when an Activation 1.4 application-bootstrap step (default
    paper account, watchlist verification, or safe config template)
    fails inside ``Core.bootstrap.run_bootstrap``.

    Distinct from ``DatabaseError``/``RepositoryError``/``OSError`` --
    those are the *causes*; this wraps whichever one actually occurred
    together with the name of the bootstrap step that raised it, so
    ``Core.init_command.run_init`` can report precisely which step
    failed (Section 12: never a silent/ambiguous "INIT FAILED") without
    needing to inspect the original exception's type.
    """

    def __init__(self, step: str, original: Exception) -> None:
        super().__init__(f"bootstrap step '{step}' failed: {original}", details={"step": step})
        self.step: str = step
        self.original: Exception = original


class RuntimeInvariantError(AgentError):
    """Raised when an invariant guaranteed by ``Core.runtime.Runtime`` is
    violated in a way that indicates a genuine bug, not a normal tool
    failure.

    Typical use cases (Stage 8.2): the Event trailing a drained ``step()``
    loop is not ``EFFECT_COMPLETED`` as expected, or a Sandbox error-as-data
    payload reports an ``error_type`` the caller does not recognize. Never
    raised for ordinary tool failures (unregistered tool, handler
    exception) -- those map to ``ToolNotFoundError``/``ToolExecutionError``
    instead.

    Stage 8.5: also never raised anymore for a legitimate
    ``ApprovalOutcome.DENIED``/``PENDING`` outcome -- those are
    ``ApprovalDenied``/``ApprovalPending`` (below), not invariant
    violations. See ``Docs/runtime_lifecycle.md`` §4.
    """


class ApprovalDenied(AgentError):
    """Raised when ``ApprovalPort.check()`` returned
    ``ApprovalOutcome.DENIED`` for a tool-call INTENT.

    This is a legitimate policy outcome, not a bug: the Actor is
    untouched (no ``EFFECT_COMPLETED`` was ever produced, no
    ``Sandbox.execute()`` call happened) and remains fully usable for
    further ``execute()`` calls. Distinct from ``RuntimeInvariantError``
    by design (Stage 8.5, ``Docs/runtime_lifecycle.md`` §4) -- a denial is
    an expected, first-class result of the approval policy, not a "this
    should never happen" signal.
    """


class ApprovalPending(AgentError):
    """Raised when ``ApprovalPort.check()`` returned
    ``ApprovalOutcome.PENDING`` for a tool-call INTENT.

    Legitimate "not yet decided" outcome (e.g. awaiting human-in-the-loop
    approval) -- not a failure, and not a ``RuntimeInvariantError``
    (Stage 8.5, ``Docs/runtime_lifecycle.md`` §4). The Actor is untouched
    and remains fully usable; Runtime does not retry the INTENT itself
    (ND-3), so the caller decides what "pending" means for its own
    workflow (e.g. surfacing this to a human, or trying again later with
    a fresh call).
    """