"""Thread-safe singleton registry for services.

Important: this registry only stores services. It never executes them;
running a service remains the responsibility of ``Agents.executor.Executor``
(unchanged), just as ``Agents.tool_registry.ToolRegistry`` only stores tools.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from Core.exceptions import AgentError
from Services.base_service import BaseService


class ServiceError(AgentError):
    """Base class for service-registry related errors.

    Additive subclass of ``Core.exceptions.AgentError`` -- ``Core`` itself
    is left untouched.
    """


class ServiceAlreadyRegisteredError(ServiceError):
    """Raised when registering a service whose name is already taken and
    ``overwrite`` was not requested.
    """


class ServiceNotFoundError(ServiceError):
    """Raised when a requested service does not exist in the registry."""


class ServiceRegistry:
    """Thread-safe singleton storing the set of services available to agents."""

    _instance: Optional["ServiceRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> "ServiceRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._services: Dict[str, BaseService] = {}
        self._data_lock: threading.RLock = threading.RLock()
        self._initialized = True

    def register(self, service: BaseService, overwrite: bool = False) -> None:
        """Register ``service`` under its own :attr:`BaseService.name`.

        Args:
            service: The service instance to register.
            overwrite: If ``True``, silently replace an already-registered
                service with the same name. Defaults to ``False``.

        Raises:
            ServiceAlreadyRegisteredError: If a service with the same name
                already exists and ``overwrite`` is ``False``.
        """
        with self._data_lock:
            if service.name in self._services and not overwrite:
                raise ServiceAlreadyRegisteredError(
                    f"Service '{service.name}' is already registered.",
                    details={"service_name": service.name},
                )
            self._services[service.name] = service

    def unregister(self, name: str) -> None:
        """Remove the service registered under ``name``, if present."""
        with self._data_lock:
            self._services.pop(name, None)

    def exists(self, name: str) -> bool:
        """Return whether a service named ``name`` is registered."""
        with self._data_lock:
            return name in self._services

    def get(self, name: str) -> BaseService:
        """Return the service registered under ``name``.

        Raises:
            ServiceNotFoundError: If no service is registered under ``name``.
        """
        with self._data_lock:
            service = self._services.get(name)
            if service is None:
                raise ServiceNotFoundError(
                    f"Service '{name}' is not registered.", details={"service_name": name}
                )
            return service

    def list(self) -> List[BaseService]:
        """Return all registered services."""
        with self._data_lock:
            return list(self._services.values())

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton. Intended for tests only."""
        with cls._instance_lock:
            cls._instance = None


service_registry = ServiceRegistry()
