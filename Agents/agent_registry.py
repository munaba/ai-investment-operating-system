from __future__ import annotations
import threading
from typing import Any, Dict, List, Optional
from Core.logger import get_logger
logger = get_logger(__name__)


class AgentRegistry:
    """Thread-safe singleton storing the set of agents available to the framework.

    Mirrors the registration/lookup contract already used by
    ``Agents.tool_registry.ToolRegistry``,
    ``Services.service_registry.ServiceRegistry``, and
    ``Providers.provider_manager.ProviderManager``: a single, process-wide
    registry that only stores instances by name and never executes them.

    Example:
        >>> from Agents.agent_registry import agent_registry
        >>> agent_registry.register("stock_agent", stock_agent_instance)
        >>> agent = agent_registry.get("stock_agent")
    """

    _instance: Optional["AgentRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> "AgentRegistry":
        """Create or return the existing singleton instance.

        Returns:
            The single shared ``AgentRegistry`` instance.
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
        self._agents: Dict[str, Any] = {}
        self._data_lock: threading.RLock = threading.RLock()
        self._initialized = True

    def register(self, name: str, agent: Any) -> None:
        """Register ``agent`` under ``name``.

        Args:
            name: Unique key to register the agent under (e.g. ``"stock_agent"``).
            agent: The agent instance to register. Never type-checked
                against a specific base class -- only required to be
                non-``None`` -- so this registry can store any concrete
                agent implementation.

        Raises:
            ValueError: If ``name`` is empty, or ``agent`` is ``None``.
            KeyError: If ``name`` is already registered.
        """
        if not name:
            raise ValueError("Agent name must be a non-empty string")
        if agent is None:
            raise ValueError(f"Cannot register '{name}': agent must not be None")

        with self._data_lock:
            if name in self._agents:
                raise KeyError(f"Agent '{name}' is already registered.")
            self._agents[name] = agent

        logger.debug(f"Agent '{name}' registered ({type(agent).__name__})")

    def get(self, name: str) -> Any:
        """Retrieve a registered agent by name.

        Args:
            name: Key the agent was registered under.

        Returns:
            The registered agent instance.

        Raises:
            KeyError: If no agent is registered under ``name``.
        """
        with self._data_lock:
            agent = self._agents.get(name)

        if agent is None:
            raise KeyError(f"Agent '{name}' is not registered.")
        return agent

    def exists(self, name: str) -> bool:
        """Check whether an agent is registered under a given name.

        Args:
            name: Key to check.

        Returns:
            ``True`` if an agent is registered under ``name``, else ``False``.
        """
        with self._data_lock:
            return name in self._agents

    def list(self) -> List[str]:
        """List the names of all currently registered agents.

        Returns:
            A list of registered agent names.
        """
        with self._data_lock:
            return list(self._agents.keys())

    def unregister(self, name: str) -> None:
        """Remove the agent registered under ``name``.

        Args:
            name: Key the agent was registered under.

        Raises:
            KeyError: If no agent is registered under ``name``.
        """
        with self._data_lock:
            if name not in self._agents:
                raise KeyError(f"Cannot unregister: agent '{name}' is not registered.")
            del self._agents[name]

        logger.debug(f"Agent '{name}' unregistered")

    def clear(self) -> None:
        """Remove all registered agents."""
        with self._data_lock:
            count = len(self._agents)
            self._agents.clear()

        logger.debug(f"Cleared {count} agent(s) from AgentRegistry")

    def health_check(self) -> bool:
        """Report whether this registry is currently usable.

        Never raises: any failure while probing internal state is caught,
        logged, and reflected as a ``False`` return value, mirroring the
        ``bool``-returning contract shared by every ``health_check()`` in
        the framework (``BaseProvider``, ``BaseAgent``, ``BaseService``).
        This only checks that the registry itself (its internal lock and
        storage) is reachable and functioning -- it does not check the
        health of any individual *registered* agent (callers should use
        each agent's own ``health_check()`` for that).

        Returns:
            ``True`` if the registry can be read from safely, ``False``
            otherwise.
        """
        try:
            with self._data_lock:
                _ = len(self._agents)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"AgentRegistry health_check failed: {exc}")
            return False

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton. Intended for tests only."""
        with cls._instance_lock:
            cls._instance = None


agent_registry: AgentRegistry = AgentRegistry()