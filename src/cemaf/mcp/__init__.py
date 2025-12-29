"""MCP (Model Context Protocol) module - JSON-RPC 2.0 protocols and transport abstractions."""

from cemaf.mcp.protocols import (
    MCPErrorCode,
    MCPError,
    MCPRequest,
    MCPResponse,
    Transport,
    MessageHandler,
    MethodRegistry,
)
from cemaf.mcp.types import (
    MCPPrompt,
    MCPPromptArgument,
    MCPResource,
    MCPResourceContents,
    MCPToolDefinition,
    MCPToolResult,
)
from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.bridges import ToolBridge, ResourceBridge, PromptBridge
from cemaf.mcp.transport import BaseTransport, StdioTransport, WebSocketTransport, SSETransport
from cemaf.mcp.mock import MockTransport, InMemoryTransport

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
