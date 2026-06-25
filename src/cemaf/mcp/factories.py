"""
Factory functions for MCP (Model Context Protocol) components.

Provides convenient ways to create MCP transports and adapters with sensible defaults
while maintaining dependency injection principles.
"""

import os
from typing import Any

from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.protocols import Transport
from cemaf.mcp.transport import SSETransport, StdioTransport, WebSocketTransport

mcp_transport_registry: ProviderRegistry[Transport] = ProviderRegistry(name="mcp_transport")


def _create_stdio_transport(**kwargs: Any) -> Transport:
    return StdioTransport()


def _create_sse_transport(**kwargs: Any) -> Transport:
    base_url = (
        kwargs.get("base_url")
        or kwargs.get("url")
        or os.getenv("CEMAF_MCP_SSE_BASE_URL")
        or os.getenv("CEMAF_MCP_TRANSPORT_URL")
    )
    if not base_url:
        raise ValueError("sse MCP transport requires base_url (or CEMAF_MCP_SSE_BASE_URL env).")
    return SSETransport(base_url=str(base_url))


def _create_websocket_transport(**kwargs: Any) -> Transport:
    url = (
        kwargs.get("url")
        or kwargs.get("websocket_url")
        or os.getenv("CEMAF_MCP_WEBSOCKET_URL")
        or os.getenv("CEMAF_MCP_TRANSPORT_URL")
    )
    if not url:
        raise ValueError("websocket MCP transport requires url (or CEMAF_MCP_WEBSOCKET_URL env).")
    return WebSocketTransport(url=str(url))


mcp_transport_registry.register(backend="stdio", factory=_create_stdio_transport)
mcp_transport_registry.register(backend="sse", factory=_create_sse_transport)
mcp_transport_registry.register(backend="websocket", factory=_create_websocket_transport)


def create_mcp_transport(
    transport_type: str = "stdio",
    server_timeout_seconds: float = 30.0,
    **transport_options: Any,
) -> Transport:
    """Build an MCP transport from a registered transport backend."""
    return mcp_transport_registry.create(
        backend=transport_type,
        server_timeout_seconds=server_timeout_seconds,
        **transport_options,
    )


def create_mcp_adapter(
    transport_type: str = "stdio",
    server_timeout_seconds: float = 30.0,
    **transport_options: Any,
) -> MCPAdapter:
    """
    Factory for MCPAdapter with sensible defaults.

    Args:
        transport_type: Transport type (stdio, sse, websocket, or registered custom backend)
        server_timeout_seconds: Server timeout

    Returns:
        Configured MCPAdapter instance

    Example:
        # With defaults
        adapter = create_mcp_adapter()

        # URL-backed transport
        adapter = create_mcp_adapter(transport_type="websocket", url="ws://localhost:8765")
    """
    transport = create_mcp_transport(
        transport_type=transport_type,
        server_timeout_seconds=server_timeout_seconds,
        **transport_options,
    )

    # MCPAdapter doesn't accept server_timeout_seconds parameter
    # Parameter is kept in factory API for future extension
    return MCPAdapter(transport=transport)


def create_mcp_adapter_from_config(settings: Settings | None = None) -> MCPAdapter:
    """
    Create MCPAdapter from environment configuration.

    Reads from environment variables:
    - CEMAF_MCP_TRANSPORT_TYPE: Transport type (default: stdio)
    - CEMAF_MCP_SERVER_TIMEOUT_SECONDS: Server timeout (default: 30.0)

    Returns:
        Configured MCPAdapter instance

    Example:
        # From environment
        adapter = create_mcp_adapter_from_config()
    """
    transport_type = os.getenv(
        "CEMAF_MCP_TRANSPORT_TYPE",
        settings.mcp.transport_type if settings else "stdio",
    )
    timeout = float(
        os.getenv(
            "CEMAF_MCP_SERVER_TIMEOUT_SECONDS",
            str(settings.mcp.server_timeout_seconds if settings else 30.0),
        )
    )

    return create_mcp_adapter(
        transport_type=transport_type,
        server_timeout_seconds=timeout,
        base_url=os.getenv("CEMAF_MCP_SSE_BASE_URL") or os.getenv("CEMAF_MCP_TRANSPORT_URL"),
        url=os.getenv("CEMAF_MCP_WEBSOCKET_URL") or os.getenv("CEMAF_MCP_TRANSPORT_URL"),
    )
