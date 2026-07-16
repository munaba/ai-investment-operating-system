"""Executes tools that have been looked up from a :class:`ToolRegistry`."""

from __future__ import annotations

from typing import Any

from Core.exceptions import ToolError
from Core.logger import get_logger
from Agents.tool_registry import ToolRegistry

logger = get_logger(__name__)


class ToolExecutionError(ToolError):
    """Raised when a tool raises an exception while being executed.

    Additive subclass of ``Core.exceptions.ToolError`` (see the
    Architecture Notes in ``Agents.tool_registry``).
    """


class Executor:
    """Runs a registered tool by name.

    The executor never stores tools itself; it delegates lookup to the
    injected :class:`ToolRegistry` and is solely responsible for invoking
    the tool's handler and normalizing failures.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry

    def execute(self, tool_name: str, *args: object, **kwargs: object) -> Any:
        """Look up ``tool_name`` in the registry and run it.

        Args:
            tool_name: Name of the tool to execute.
            *args: Positional arguments forwarded to the tool handler.
            **kwargs: Keyword arguments forwarded to the tool handler.

        Returns:
            Whatever the tool handler returns.

        Raises:
            ToolNotFoundError: If ``tool_name`` is not registered.
            ToolExecutionError: If the tool handler raises an exception.
        """
        tool = self._tool_registry.get(tool_name)
        try:
            logger.debug(f"Executing tool '{tool_name}'")
            return tool.handler(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - normalize any tool failure
            raise ToolExecutionError(
                f"Tool '{tool_name}' raised an exception during execution.",
                details={"tool_name": tool_name, "error": str(exc)},
            ) from exc
