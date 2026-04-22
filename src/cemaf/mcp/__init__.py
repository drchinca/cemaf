"""Model Context Protocol — adapter, bridges, transports.

Lets CEMAF act as an MCP server (exposing its tools, memory, and blueprints
to any MCP client — Claude Desktop, IDE plugins, another agent framework)
AND wrap external MCP-compatible tools as CEMAF integration seams. The
`bridges/` sub-package holds concrete adapters; `bridges/openspec/` is the
canonical example that lets the self-hosting meta layer drive the OpenSpec
CLI to spec-and-validate CEMAF's own evolution.

Key types:
- `MCPAdapter` — server-side adapter that exposes CEMAF to MCP clients
- `ToolBridge` / `ResourceBridge` / `PromptBridge` — type converters
- `Transport` protocol + `StdioTransport` / `SSETransport` / `WebSocketTransport`
- `MCPRequest` / `MCPResponse` / `MCPError` — JSON-RPC 2.0 wrappers

Usage (CEMAF as MCP server):
    from cemaf.mcp.adapter import MCPAdapter
    from cemaf.mcp.transport import StdioTransport

    adapter = MCPAdapter(transport=StdioTransport())
    adapter.register_tools(tool_registry.to_list())
    adapter.set_memory_store(memory_store)
    await adapter.serve()
"""

from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.bridges import PromptBridge, ResourceBridge, ToolBridge
from cemaf.mcp.mock import InMemoryTransport, MockTransport
from cemaf.mcp.protocols import (
    MCPError,
    MCPErrorCode,
    MCPRequest,
    MCPResponse,
    MessageHandler,
    MethodRegistry,
    Transport,
)
from cemaf.mcp.transport import BaseTransport, SSETransport, StdioTransport, WebSocketTransport
from cemaf.mcp.types import (
    MCPPrompt,
    MCPPromptArgument,
    MCPResource,
    MCPResourceContents,
    MCPToolDefinition,
    MCPToolResult,
)

__all__ = [
    # Protocols
    "MCPErrorCode",
    "MCPError",
    "MCPRequest",
    "MCPResponse",
    "Transport",
    "MessageHandler",
    "MethodRegistry",
    # Types
    "MCPToolDefinition",
    "MCPPromptArgument",
    "MCPPrompt",
    "MCPResource",
    "MCPResourceContents",
    "MCPToolResult",
    # Adapter and bridges
    "MCPAdapter",
    "ToolBridge",
    "ResourceBridge",
    "PromptBridge",
    # Transports
    "BaseTransport",
    "StdioTransport",
    "WebSocketTransport",
    "SSETransport",
    # Mocks for testing
    "MockTransport",
    "InMemoryTransport",
]
