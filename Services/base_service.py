"""Abstract base class every service must implement.

Architecture Notes:
    ``Providers.BaseProvider.health_check()`` (finished layer) returns a
    plain ``bool``. ``BaseService.health_check()`` mirrors that same
    contract for consistency across the framework, rather than introducing
    a different return shape for services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from Services.service_context import ServiceContext
from Services.service_result import ServiceResult


class BaseService(ABC):
    """Contract shared by every service implementation.

    Agents (and any other caller) must only depend on this interface and
    never on a concrete service implementation.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, human-readable identifier for this service."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Short human-readable description of what this service does."""
        raise NotImplementedError

    @property
    @abstractmethod
    def category(self) -> str:
        """Logical grouping this service belongs to (e.g. ``"finance"``)."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, context: ServiceContext) -> ServiceResult:
        """Run this service for the given ``context``.

        Implementations should never let unexpected exceptions escape;
        failures should be caught and reported via a failed
        :class:`ServiceResult` (see :meth:`ServiceResult.fail`) wherever
        practical.

        Args:
            context: The request context to operate on.

        Returns:
            A :class:`ServiceResult` describing the outcome.
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        """Check whether this service is currently able to serve requests.

        Implementations should never raise -- any failure should be caught
        internally and reflected as a ``False`` return value.

        Returns:
            ``True`` if the service is healthy, ``False`` otherwise.
        """
        raise NotImplementedError
