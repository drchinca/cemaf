"""
Protocol definitions for replay module.

Defines interfaces for tool execution during replay operations.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolExecutor(Protocol):
    """
    Protocol for executing tools during replay.

    Implementations provide custom tool execution logic for
    replaying recorded runs with different tool behaviors.

    Example:
        class MockToolExecutor:
            async def execute(
                self,
                tool_id: str,
                **kwargs: Any,
            ) -> Any:
                # Return mock data for tool
                return {"mocked": True}
    """

    async def execute(
        self,
        tool_id: str,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a tool with given arguments.

        Args:
            tool_id: Identifier of the tool to execute
            **kwargs: Tool arguments

        Returns:
            Tool execution result
        """
        ...
