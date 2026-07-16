"""Thread-safe singleton registry for agent tools.

Important: this registry only stores tools. It never executes them; running
a tool is the responsibility of :class:`Agents.executor.Executor`.

Architecture Notes:
    ``Core.exceptions`` only defines a generic ``ToolError``. To let callers
    distinguish *why* a tool operation failed without touching the
    (finished) ``Core`` layer, this module adds two specific subclasses of
    ``ToolError`` -- ``ToolAlreadyRegisteredError`` and
    ``ToolNotFoundError``. This is purely additive: both are still instances
    of ``Core.exceptions.ToolError``, so any existing ``except ToolError``
    handler keeps working unchanged.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from Core.exceptions import ToolError


class ToolAlreadyRegisteredError(ToolError):
    """Raised when registering a tool whose name is already taken."""


class ToolNotFoundError(ToolError):
    """Raised when a requested tool does not exist in the registry."""


@dataclass(frozen=True)
class Tool:
    """A tool that can be looked up by name and later executed.

    Attributes:
        name: Unique tool identifier.
        description: Human-readable description, useful for planning.
        handler: The callable that implements the tool's behaviour.
    """

    name: str
    description: str
    handler: Callable[..., Any]


class ToolRegistry:
    """Thread-safe singleton storing the set of tools available to agents."""

    _instance: Optional["ToolRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._tools: Dict[str, Tool] = {}
        self._data_lock: threading.RLock = threading.RLock()
        self._initialized = True

    def register(self, tool: Tool) -> None:
        """Register ``tool``.

        Raises:
            ToolAlreadyRegisteredError: If a tool with the same name exists.
        """
        with self._data_lock:
            if tool.name in self._tools:
                raise ToolAlreadyRegisteredError(
                    f"Tool '{tool.name}' is already registered.",
                    details={"tool_name": tool.name},
                )
            self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Remove the tool registered under ``name``, if present."""
        with self._data_lock:
            self._tools.pop(name, None)

    def exists(self, name: str) -> bool:
        """Return whether a tool named ``name`` is registered."""
        with self._data_lock:
            return name in self._tools

    def get(self, name: str) -> Tool:
        """Return the tool registered under ``name``.

        Raises:
            ToolNotFoundError: If no tool is registered under ``name``.
        """
        with self._data_lock:
            tool = self._tools.get(name)
            if tool is None:
                raise ToolNotFoundError(
                    f"Tool '{name}' is not registered.", details={"tool_name": name}
                )
            return tool

    def list(self) -> List[Tool]:
        """Return all registered tools."""
        with self._data_lock:
            return list(self._tools.values())

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton. Intended for tests only."""
        with cls._instance_lock:
            cls._instance = None


tool_registry = ToolRegistry()
