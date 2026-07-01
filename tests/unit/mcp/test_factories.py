"""Tests for MCP factory composition roots."""

import pytest

from cemaf.mcp import (
    MCPAdapter,
    MockTransport,
    SSETransport,
    StdioTransport,
    WebSocketTransport,
    create_mcp_adapter,
    create_mcp_adapter_from_config,
    create_mcp_transport,
    mcp_transport_registry,
)


class TestCreateMCPTransport:
    def test_default_backend_returns_stdio_transport(self) -> None:
        transport = create_mcp_transport()

        assert isinstance(transport, StdioTransport)

    def test_sse_backend_accepts_base_url(self) -> None:
        transport = create_mcp_transport(transport_type="sse", base_url="http://localhost:3000/")

        assert isinstance(transport, SSETransport)
        assert transport._base_url == "http://localhost:3000"  # noqa: SLF001

    def test_websocket_backend_accepts_url(self) -> None:
        transport = create_mcp_transport(transport_type="websocket", url="ws://localhost:8765")

        assert isinstance(transport, WebSocketTransport)
        assert transport._url == "ws://localhost:8765"  # noqa: SLF001

    def test_url_backed_backend_requires_url(self) -> None:
        with pytest.raises(ValueError, match="websocket MCP transport requires url"):
            create_mcp_transport(transport_type="websocket")

    def test_unsupported_backend_mentions_registry_extension_point(self) -> None:
        with pytest.raises(ValueError, match="mcp_transport_registry.register"):
            create_mcp_transport(transport_type="named-pipe")

    def test_supports_custom_registered_transport(self) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return MockTransport()

        mcp_transport_registry.register(backend="custom-mcp-transport", factory=_factory)

        transport = create_mcp_transport(
            transport_type="custom-mcp-transport",
            server_timeout_seconds=4.5,
            endpoint="pipe://agent",
        )

        assert isinstance(transport, MockTransport)
        assert created["args"]["server_timeout_seconds"] == 4.5
        assert created["args"]["endpoint"] == "pipe://agent"


class TestCreateMCPAdapter:
    def test_adapter_uses_registered_transport(self) -> None:
        mcp_transport_registry.register(
            backend="adapter-custom-mcp-transport",
            factory=lambda **_: MockTransport(),
        )

        adapter = create_mcp_adapter(transport_type="adapter-custom-mcp-transport")

        assert isinstance(adapter, MCPAdapter)
        assert isinstance(adapter._transport, MockTransport)  # noqa: SLF001

    def test_adapter_from_config_uses_env_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        created: dict[str, object] = {}

        def _factory(**kwargs):
            created["args"] = kwargs
            return MockTransport()

        mcp_transport_registry.register(backend="env-custom-mcp-transport", factory=_factory)
        monkeypatch.setenv("CEMAF_MCP_TRANSPORT_TYPE", "env-custom-mcp-transport")
        monkeypatch.setenv("CEMAF_MCP_SERVER_TIMEOUT_SECONDS", "7.25")

        adapter = create_mcp_adapter_from_config()

        assert isinstance(adapter._transport, MockTransport)  # noqa: SLF001
        assert created["args"]["server_timeout_seconds"] == 7.25

    def test_adapter_from_config_uses_url_env_for_url_backed_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CEMAF_MCP_TRANSPORT_TYPE", "websocket")
        monkeypatch.setenv("CEMAF_MCP_TRANSPORT_URL", "ws://localhost:9000")

        adapter = create_mcp_adapter_from_config()

        transport = adapter._transport  # noqa: SLF001
        assert isinstance(transport, WebSocketTransport)
        assert transport._url == "ws://localhost:9000"  # noqa: SLF001
