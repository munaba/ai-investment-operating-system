from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, List, Optional
from .message import Message
from .response import ProviderResponse


@dataclass
class HealthCheckResult:
    """Diagnostic detail produced by a provider's most recent health check.

    This is additive, non-abstract state — it does not change the required
    ``health_check() -> bool`` signature. Providers may populate it (via
    :meth:`BaseProvider._record_health_check`) to give callers richer
    diagnostics than a bare boolean, without breaking the shared interface.

    Attributes:
        healthy: Whether the provider was reachable and functional.
        latency_ms: How long the check took, in milliseconds, if measured.
        error: Error message if the check failed, else ``None``.
        checked_at: ISO-8601 UTC timestamp of when the check ran.
    """

    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: str = ""


class BaseProvider(ABC):
    """Abstract interface that every LLM provider implementation must satisfy."""

    def __init__(self) -> None:
        """Initialize shared, non-abstract provider state."""
        self._last_health_check: Optional[HealthCheckResult] = None

    @property
    def last_health_check(self) -> Optional[HealthCheckResult]:
        """Diagnostic detail from the most recent :meth:`health_check` call.

        Returns:
            The last :class:`HealthCheckResult` recorded, or ``None`` if
            ``health_check()`` has not been called yet.
        """
        return self._last_health_check

    def _record_health_check(
        self, healthy: bool, latency_ms: Optional[float] = None, error: Optional[str] = None
    ) -> None:
        """Record diagnostic detail for the current health check.

        Concrete providers should call this from within their
        ``health_check()`` implementation before returning the boolean
        result, so callers can inspect richer detail via
        :attr:`last_health_check` when needed.

        Args:
            healthy: Whether the check succeeded.
            latency_ms: How long the check took, in milliseconds.
            error: Error message if the check failed.
        """
        self._last_health_check = HealthCheckResult(
            healthy=healthy,
            latency_ms=latency_ms,
            error=error,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    @property
    def name(self) -> str:
        """Human-readable identifier for this provider.

        Defaults to the concrete class name (e.g. ``"GeminiProvider"``).
        Not an abstract method — subclasses may override it, but are not
        required to, so this does not add a new mandatory method to the
        interface.

        Returns:
            A short string identifying this provider.
        """
        return self.__class__.__name__

    @abstractmethod
    def connect(self) -> None:
        """Establish any connection/client/session needed to use this provider.

        Implementations should be idempotent: calling ``connect()`` on an
        already-connected provider should be a no-op.

        Raises:
            ProviderError: If the connection could not be established
                (e.g. missing API key, invalid configuration, network error).
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Release any connection/client/session held by this provider.

        Raises:
            ProviderError: If disconnecting fails unexpectedly.
        """
        raise NotImplementedError

    @abstractmethod
    def generate(self, messages: List[Message], **kwargs: Any) -> ProviderResponse:
        """Generate a single, complete response for the given conversation.

        Args:
            messages: The conversation history to generate a reply for,
                ordered from oldest to newest.
            **kwargs: Provider-specific generation options (e.g.
                ``temperature``, ``max_output_tokens``).

        Returns:
            A normalized :class:`ProviderResponse`.

        Raises:
            ProviderError: If generation fails.
        """
        raise NotImplementedError

    @abstractmethod
    def stream(self, messages: List[Message], **kwargs: Any) -> Iterator[str]:
        """Generate a response incrementally, yielding text chunks as they arrive.

        Args:
            messages: The conversation history to generate a reply for,
                ordered from oldest to newest.
            **kwargs: Provider-specific generation options.

        Yields:
            Successive text chunks of the generated response.

        Raises:
            ProviderError: If streaming fails.
            NotImplementedError: If the concrete provider/SDK does not yet
                support streaming.
        """
        raise NotImplementedError

    @abstractmethod
    def count_tokens(self, messages: List[Message]) -> int:
        """Count how many tokens the given messages would consume.

        Args:
            messages: The messages to count tokens for.

        Returns:
            The total token count as reported by the provider.

        Raises:
            ProviderError: If the token count could not be determined.
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        """Check whether this provider is currently reachable and functional.

        Implementations should never raise — any failure should be caught
        internally, logged, and reflected as a ``False`` return value.
        Implementations are encouraged (but not required) to call
        :meth:`_record_health_check` before returning, so callers can
        inspect richer diagnostics via :attr:`last_health_check`.

        Returns:
            ``True`` if the provider is healthy and ready to serve
            requests, ``False`` otherwise.
        """
        raise NotImplementedError