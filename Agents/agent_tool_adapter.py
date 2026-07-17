"""
Adapter module bridging Agent instances to the Tool interface.

This module defines `AgentToolAdapter`, a thin adapter class whose sole
purpose is to let an `Agent` be treated as a `Tool`. It exists so that a
future `Executor` can invoke an agent through `ToolRegistry` without any
agent needing to import another agent (or the registry) directly.

This file is foundation-only: it performs no wiring to `ToolRegistry` or
`AgentRegistry`, and it does not modify any existing class, constructor,
or behavior in the project.
"""


class AgentToolAdapter:
    """
    Adapter between an Agent and the Tool interface.

    `AgentToolAdapter` wraps an existing `Agent` instance and exposes it
    through the minimal surface expected of a `Tool` (`name`, `description`,
    `execute`, `health_check`), without introducing any dependency on
    `ToolRegistry`, `AgentRegistry`, or `Executor`.

    The adapter is intentionally "thin": it stores its constructor
    parameters and delegates execution directly to the wrapped agent's
    `chat` method, without adding logic, validation, logging, exception
    handling, or transformation of the agent's result.

    Attributes:
        _name: Private name identifying this adapter as a tool.
        _description: Private human-readable description of this tool.
        _agent: Private reference to the wrapped `Agent` instance.
    """

    def __init__(
        self,
        name: str,
        description: str,
        agent,
    ):
        """
        Initialize the adapter with a name, description, and wrapped agent.

        Args:
            name: The name this adapter will expose as a tool.
            description: A human-readable description of this tool.
            agent: The `Agent` instance being wrapped.
        """
        self._name = name
        self._description = description
        self._agent = agent

    @property
    def name(self) -> str:
        """
        Return the name of this tool.

        Returns:
            The tool name provided at construction time.
        """
        return self._name

    @property
    def description(self) -> str:
        """
        Return the description of this tool.

        Returns:
            The tool description provided at construction time.
        """
        return self._description

    def execute(self, user_input: str, provider_name: str | None = None):
        """
        Delegate execution directly to the wrapped agent's `chat` method.

        This method contains no logic beyond the delegation itself: no
        exception handling, no logging, no validation, and no
        transformation of the agent's result.

        Args:
            user_input: The input text to pass to the wrapped agent.
            provider_name: Optional provider name to pass to the wrapped
                agent.

        Returns:
            Whatever the wrapped agent's `chat` method returns.
        """
        return self._agent.chat(
            user_input=user_input,
            provider_name=provider_name,
        )

    def health_check(self):
        """
        Report whether the wrapped agent is healthy.

        If the wrapped agent exposes a `health_check()` method, this
        returns True only if calling it returns True. If the wrapped
        agent does not expose a `health_check()` method, this returns
        True (nothing to report as unhealthy). If calling the wrapped
        agent's `health_check()` raises an exception, this returns
        False; no exception is propagated out of this method.

        Returns:
            True if the agent is healthy or exposes no health check;
            False if the agent's health check raised an exception or
            reported failure.
        """
        if not hasattr(self._agent, "health_check"):
            return True
        try:
            return self._agent.health_check() is True
        except Exception:
            return False