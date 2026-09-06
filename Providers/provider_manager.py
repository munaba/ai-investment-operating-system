from __future__ import annotations
import threading
from typing import Dict, List, Optional
from Core.exceptions import ProviderError
from Core.logger import get_logger

from .base_provider import BaseProvider

logger = get_logger(__name__)


class ProviderManager:
    """Thread-safe singleton registry mapping provider names to instances.

    Example:
        >>> from Providers.provider_manager import provider_manager
        >>> provider_manager.register("gemini", GeminiProvider())
        >>> provider = provider_manager.get("gemini")
    """

    _instance: Optional["ProviderManager"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> "ProviderManager":
        """Create or return the existing singleton instance.

        Returns:
            The single shared ``ProviderManager`` instance.
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the singleton exactly once."""
        if self._initialized:
            return
        self._providers: Dict[str, BaseProvider] = {}
        self._registry_lock: threading.Lock = threading.Lock()
        self._initialized = True

    def register(self, name: str, provider: BaseProvider, overwrite: bool = False) -> None:
        """Register a provider instance under a given name.

        By default, registering under a name that is already taken is
        rejected — this protects against a provider being silently replaced
        by accident. Pass ``overwrite=True`` to explicitly allow replacing
        an existing registration (e.g. when hot-reloading during development).

        Args:
            name: Unique key to register the provider under (e.g. ``"gemini"``).
            provider: A concrete ``BaseProvider`` instance.
            overwrite: If ``True``, allow replacing an already-registered
                provider under the same name. Defaults to ``False``.

        Raises:
            ProviderError: If ``name`` is empty, ``provider`` is not a
                ``BaseProvider`` instance, or ``name`` is already registered
                and ``overwrite`` is ``False``.
        """
        if not name:
            raise ProviderError("Provider name must be a non-empty string")
        if not isinstance(provider, BaseProvider):
            raise ProviderError(
                f"Cannot register '{name}': provider must be an instance of BaseProvider, "
                f"got {type(provider).__name__}"
            )

        with self._registry_lock:
            if name in self._providers and not overwrite:
                raise ProviderError(
                    f"Provider '{name}' is already registered. "
                    "Pass overwrite=True to replace it, or call unregister() first."
                )
            if name in self._providers and overwrite:
                logger.warning(f"Provider '{name}' is already registered; overwriting")
            self._providers[name] = provider

        logger.debug(f"Provider '{name}' registered ({provider.name})")

    def unregister(self, name: str) -> None:
        """Remove a registered provider by name.

        Args:
            name: Key the provider was registered under.

        Raises:
            ProviderError: If no provider is registered under ``name``.
        """
        with self._registry_lock:
            if name not in self._providers:
                raise ProviderError(f"Cannot unregister: provider '{name}' is not registered")
            del self._providers[name]

        logger.debug(f"Provider '{name}' unregistered")

    def get(self, name: str) -> BaseProvider:
        """Retrieve a registered provider by name.

        Args:
            name: Key the provider was registered under.

        Returns:
            The registered ``BaseProvider`` instance.

        Raises:
            ProviderError: If no provider is registered under ``name``.
        """
        with self._registry_lock:
            provider = self._providers.get(name)

        if provider is None:
            raise ProviderError(f"Provider '{name}' is not registered")
        return provider

    def list(self) -> List[str]:
        """List the names of all currently registered providers.

        Returns:
            A list of registered provider names.
        """
        with self._registry_lock:
            return list(self._providers.keys())

    def exists(self, name: str) -> bool:
        """Check whether a provider is registered under a given name.

        Args:
            name: Key to check.

        Returns:
            ``True`` if a provider is registered under ``name``, else ``False``.
        """
        with self._registry_lock:
            return name in self._providers

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton. Intended for tests only."""
        with cls._instance_lock:
            cls._instance = None

provider_manager: ProviderManager = ProviderManager()