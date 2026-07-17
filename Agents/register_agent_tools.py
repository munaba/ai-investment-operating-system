 
from Agents.tool_registry import Tool
 
 
def register_agent_tool(
    tool_registry,
    agent_name: str,
    description: str,
    agent,
):
    """
    Register an agent's `chat` method as a Tool into tool_registry.
 
    Builds a `Tool` whose handler is `agent.chat` and registers it into
    the given `tool_registry` using the registry's existing `register`
    API. This function does not create a new registry, does not catch
    any exception raised by `tool_registry` during registration (for
    example, on a duplicate tool name), and does not perform any other
    wiring.
 
    Args:
        tool_registry: The existing `ToolRegistry` instance to register
            the tool into.
        agent_name: The name under which the agent will be exposed as a
            tool.
        description: A human-readable description of the agent, used as
            the tool's description.
        agent: The `Agent` instance whose `chat` method will be used as
            the tool's handler.
 
    Returns:
        The `Tool` instance that was registered.
 
    Raises:
        Whatever exception `tool_registry.register` raises, for example
        `ToolAlreadyRegisteredError` on a duplicate tool name. Such
        exceptions are not caught here and propagate to the caller
        unchanged.
    """
    tool = Tool(
        name=agent_name,
        description=description,
        handler=agent.chat,
    )
 
    tool_registry.register(tool)
 
    return tool