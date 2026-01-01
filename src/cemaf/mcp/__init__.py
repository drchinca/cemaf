"""MCP (Model Context Protocol) module - JSON-RPC 2.0 protocols and transport abstractions."""

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
