"""Bridge CEMAF Tools to MCP tool format."""

from __future__ import annotations

from typing import Any

from cemaf.mcp.types import MCPToolDefinition, MCPToolResult


class ToolBridge:
    """
    Bridge between CEMAF Tool and MCP tool format.
    """

    @staticmethod
    def to_mcp(tool: Tool) -> MCPToolDefinition:  # noqa: F821
        """
        Convert CEMAF Tool to MCP tool definition.

        Uses the tool's schema for the input schema.
        """
        schema = tool.schema
        return MCPToolDefinition(
            name=schema.name,
            description=schema.description,
            inputSchema={
                "type": "object",
                "properties": schema.parameters.get("properties", {}),
                "required": list(schema.required),
            },
        )

    @staticmethod
    async def call(tool: Tool, arguments: dict[str, Any]) -> MCPToolResult:  # noqa: F821
        """
        Execute CEMAF tool and return MCP result.

        Args:
            tool: CEMAF Tool instance
            arguments: Tool arguments

        Returns:
            MCPToolResult with text content or error
        """
        result = await tool.execute(**arguments)

        if result.is_ok:
            # Convert result to text
            value = result.value
            if isinstance(value, str):
                return MCPToolResult.text(value)
            elif isinstance(value, dict):
                import json

                return MCPToolResult.text(json.dumps(value, indent=2))
            else:
                return MCPToolResult.text(str(value))
        else:
            return MCPToolResult.error(result.error or "Tool execution failed")
