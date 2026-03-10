"""Bridge CEMAF Tools to MCP tool format."""

import json
from typing import Any

from cemaf.mcp.types import MCPToolDefinition, MCPToolResult
from cemaf.observability.run_logger import RunLogger
from cemaf.tools.protocols import Tool


class ToolBridge:
    """Bridge between CEMAF Tool and MCP tool format."""

    @staticmethod
    def to_mcp(tool: Tool) -> MCPToolDefinition:
        """Convert CEMAF Tool to MCP tool definition."""
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
    async def call(
        tool: Tool,
        arguments: dict[str, Any],
        run_logger: RunLogger | None = None,
        correlation_id: str = "",
    ) -> MCPToolResult:
        """Execute CEMAF tool and return MCP-formatted result."""
        try:
            if run_logger:
                result = await tool.execute_with_recording(  # type: ignore[attr-defined]
                    run_logger=run_logger,
                    correlation_id=correlation_id,
                    **arguments,
                )
            else:
                result = await tool.execute(**arguments)

            if result.success:
                value = result.data
                if isinstance(value, str):
                    text = value
                elif isinstance(value, (dict, list)):
                    text = json.dumps(value, indent=2)
                else:
                    text = str(value)
                return MCPToolResult.text(text, is_error=False)
            else:
                return MCPToolResult.error(result.error or "Tool execution failed")

        except Exception as e:
            return MCPToolResult.error(str(e))
