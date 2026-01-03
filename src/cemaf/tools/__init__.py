"""
Tools module - Atomic, stateless functions.

Tools are the LOWEST level of the hierarchy:
- ATOMIC: Do ONE thing only
- STATELESS: No memory, no side effects beyond their purpose
- SCHEMA-DRIVEN: Have JSON Schema for LLM function calling
- DETERMINISTIC: Same input → same output (when possible)

Tools are used BY Skills, never directly by Agents.

## Configuration

Settings for this module are defined in ToolsSettings.

Environment Variables:
    CEMAF_TOOLS_ENABLE_CALL_RECORDING: Record all tool calls (default: True)
    CEMAF_TOOLS_MAX_TOOL_TIMEOUT_SECONDS: Max timeout for tools (default: 60.0)
    CEMAF_TOOLS_ENABLE_MODERATION: Enable content moderation (default: False)
    CEMAF_TOOLS_ENABLE_CACHING: Enable result caching (default: True)

## Usage

Protocol-based:
    >>> from cemaf.tools import Tool, ToolSchema, ToolResult
    >>> from cemaf.core.types import ToolID
    >>> from cemaf.core.result import Result
    >>>
    >>> class MyTool:
    ...     @property
    ...     def id(self) -> ToolID:
    ...         return ToolID("my_tool")
    ...
    ...     @property
    ...     def schema(self) -> ToolSchema:
    ...         return ToolSchema(name="my_tool", description="My custom tool")
    ...
    ...     async def execute(self, **kwargs) -> ToolResult:
    ...         return Result.ok("result")

Function Decorator (Quick):
    >>> from cemaf.tools.base import tool
    >>>
    >>> @tool(name="add", description="Add two numbers")
    >>> async def add(a: float, b: float) -> float:
    ...     return a + b

## Extension

Tool implementations are discovered via protocols. No registration needed.
Simply implement the Tool protocol and your tool is compatible with all
CEMAF orchestration systems and LLM function calling.

See cemaf.tools.protocols.Tool for the protocol definition.
"""

# Decorator (quick tool creation)
from cemaf.tools.base import tool, tool_decorator
from cemaf.tools.protocols import Tool, ToolResult, ToolSchema
from cemaf.tools.registry import RegistryError, ToolRegistry

__all__ = [
    "Tool",
    "ToolSchema",
    "ToolResult",
    "tool",
    "tool_decorator",
    # Registry (new in Phase 1 Week 2)
    "ToolRegistry",
    "RegistryError",
]
