"""
Factory functions for MCP (Model Context Protocol) components.

Provides convenient ways to create MCP transports and adapters with sensible defaults
while maintaining dependency injection principles.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.transport.stdio import StdioTransport


def create_mcp_adapter(
    transport_type: str = "stdio",
    server_timeout_seconds: float = 30.0,
) -> MCPAdapter:
    """
    Factory for MCPAdapter with sensible defaults.

    Args:
        transport_type: Transport type (stdio, sse, websocket)
        server_timeout_seconds: Server timeout

    Returns:
        Configured MCPAdapter instance

    Example:
        # With defaults
        adapter = create_mcp_adapter()

        # Custom transport
        adapter = create_mcp_adapter(transport_type="websocket")
    """
    if transport_type == "stdio":
        transport = StdioTransport()
    else:
        raise ValueError(f"Unsupported MCP transport: {transport_type}")

    return MCPAdapter(
        transport=transport,
        server_timeout_seconds=server_timeout_seconds,
    )


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
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    transport_type = os.getenv("CEMAF_MCP_TRANSPORT_TYPE", "stdio")
    timeout = float(os.getenv("CEMAF_MCP_SERVER_TIMEOUT_SECONDS", "30.0"))

    return create_mcp_adapter(
        transport_type=transport_type,
        server_timeout_seconds=timeout,
    )
