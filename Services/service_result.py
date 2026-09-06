"""Normalized result value object returned by every :class:`BaseService`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ServiceResult:
    """Uniform outcome returned by any service's :meth:`BaseService.execute`.

    Every service, regardless of what it does internally, returns this same
    shape -- callers (agents, executors, other services) never need to know
    a service's concrete return type.

    Attributes:
        success: Whether the service execution succeeded.
        message: Human-readable summary of the outcome.
        data: The service's actual payload/result, if any.
        metadata: Optional free-form extra context (e.g. cache hit, source).
        execution_time_ms: How long :meth:`BaseService.execute` took, in
            milliseconds.
        error: The exception that caused failure, when ``success`` is
            ``False``; ``None`` on success.
    """

    success: bool
    message: str = ""
    data: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    error: Optional[Exception] = None

    @classmethod
    def ok(
        cls,
        data: Any = None,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        execution_time_ms: float = 0.0,
    ) -> "ServiceResult":
        """Build a successful :class:`ServiceResult`.

        Args:
            data: The service's result payload.
            message: Optional human-readable summary.
            metadata: Optional extra context.
            execution_time_ms: How long execution took, in milliseconds.
        """
        return cls(
            success=True,
            message=message,
            data=data,
            metadata=metadata or {},
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def fail(
        cls,
        error: Exception,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        execution_time_ms: float = 0.0,
    ) -> "ServiceResult":
        """Build a failed :class:`ServiceResult`.

        Args:
            error: The exception that caused the failure.
            message: Optional human-readable summary. Defaults to
                ``str(error)`` when omitted.
            metadata: Optional extra context.
            execution_time_ms: How long execution took, in milliseconds.
        """
        return cls(
            success=False,
            message=message or str(error),
            data=None,
            metadata=metadata or {},
            execution_time_ms=execution_time_ms,
            error=error,
        )
