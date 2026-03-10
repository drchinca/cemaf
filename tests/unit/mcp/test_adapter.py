"""Tests for MCPAdapter tool, resource, and prompt handling.

Covers the key public methods: tools/list, tools/call,
resources/list, resources/read, and error cases for missing
tools and resources.
"""

from typing import Any

import pytest

from cemaf.core.enums import MemoryScope
from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.mock import MockTransport
from cemaf.mcp.protocols import MCPRequest
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.tools.base import ToolSchema


class StubTool:
    """Minimal tool for adapter tests."""

    def __init__(self, name: str = "stub", output: str = "result") -> None:
        self._name = name
        self._output = output

    @property
    def id(self) -> ToolID:
        return ToolID(self._name)

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description=f"Stub tool: {self._name}",
            parameters={
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input value"},
                },
            },
            required=("input",),
        )

    async def execute(self, **kwargs: Any) -> Result[str]:
        return Result.ok(f"{self._output}: {kwargs.get('input', '')}")


def _make_adapter(
    tools: list[StubTool] | None = None,
    memory_store: InMemoryStore | None = None,
) -> MCPAdapter:
    """Build an MCPAdapter with mock transport and optional tools/store."""
    transport = MockTransport()
    adapter = MCPAdapter(transport=transport)
    for tool in tools or []:
        adapter.register_tool(tool)
    if memory_store:
        adapter.set_memory_store(memory_store)
    return adapter


class TestListTools:
    """Tests for tools/list handler."""

    @pytest.mark.asyncio
    async def test_list_tools(self) -> None:
        """Listing tools returns all registered tool definitions."""
        adapter = _make_adapter(
            tools=[
                StubTool(name="alpha"),
                StubTool(name="beta"),
            ]
        )

        request = MCPRequest(method="tools/list", id=1)
        response = await adapter.handle_request(request)

        assert response.is_success
        tool_names = {t["name"] for t in response.result["tools"]}
        assert tool_names == {"alpha", "beta"}

    @pytest.mark.asyncio
    async def test_list_tools_empty(self) -> None:
        """Listing tools with none registered returns empty list."""
        adapter = _make_adapter()

        request = MCPRequest(method="tools/list", id=1)
        response = await adapter.handle_request(request)

        assert response.is_success
        assert response.result["tools"] == []


class TestCallTool:
    """Tests for tools/call handler."""

    @pytest.mark.asyncio
    async def test_call_tool(self) -> None:
        """Calling a registered tool dispatches and returns result."""
        adapter = _make_adapter(tools=[StubTool(name="echo", output="echoed")])

        request = MCPRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {"input": "hello"}},
            id=2,
        )
        response = await adapter.handle_request(request)

        assert response.is_success
        content = response.result["content"]
        assert any("echoed: hello" in item["text"] for item in content)
        assert response.result["isError"] is False

    @pytest.mark.asyncio
    async def test_call_tool_not_found(self) -> None:
        """Calling a non-existent tool returns an error response."""
        adapter = _make_adapter()

        request = MCPRequest(
            method="tools/call",
            params={"name": "nonexistent", "arguments": {}},
            id=3,
        )
        response = await adapter.handle_request(request)

        assert response.is_error
        assert (
            "nonexistent" in response.error.message.lower() or "not found" in response.error.message.lower()
        )


class TestListResources:
    """Tests for resources/list handler."""

    @pytest.mark.asyncio
    async def test_list_resources(self) -> None:
        """Listing resources returns memory items as MCP resources."""
        store = InMemoryStore()
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="user_name",
                value="Alice",
            )
        )

        adapter = _make_adapter(memory_store=store)

        request = MCPRequest(method="resources/list", id=4)
        response = await adapter.handle_request(request)

        assert response.is_success
        resources = response.result["resources"]
        assert len(resources) >= 1
        uris = {r["uri"] for r in resources}
        assert "memory://session/user_name" in uris

    @pytest.mark.asyncio
    async def test_list_resources_empty(self) -> None:
        """Listing resources with empty store returns empty list."""
        adapter = _make_adapter(memory_store=InMemoryStore())

        request = MCPRequest(method="resources/list", id=5)
        response = await adapter.handle_request(request)

        assert response.is_success
        assert response.result["resources"] == []


class TestReadResource:
    """Tests for resources/read handler."""

    @pytest.mark.asyncio
    async def test_read_resource(self) -> None:
        """Reading a resource returns its contents."""
        store = InMemoryStore()
        await store.set(
            MemoryItem(
                scope=MemoryScope.SESSION,
                key="config",
                value={"theme": "dark"},
            )
        )

        adapter = _make_adapter(memory_store=store)

        request = MCPRequest(
            method="resources/read",
            params={"uri": "memory://session/config"},
            id=6,
        )
        response = await adapter.handle_request(request)

        assert response.is_success
        contents = response.result["contents"]
        assert len(contents) == 1
        assert "dark" in contents[0]["text"]

    @pytest.mark.asyncio
    async def test_read_resource_not_found(self) -> None:
        """Reading a non-existent resource returns an error."""
        adapter = _make_adapter(memory_store=InMemoryStore())

        request = MCPRequest(
            method="resources/read",
            params={"uri": "memory://session/nonexistent"},
            id=7,
        )
        response = await adapter.handle_request(request)

        assert response.is_error
        assert (
            "not found" in response.error.message.lower() or "nonexistent" in response.error.message.lower()
        )

    @pytest.mark.asyncio
    async def test_read_resource_no_store(self) -> None:
        """Reading a resource without a configured store returns an error."""
        adapter = _make_adapter()

        request = MCPRequest(
            method="resources/read",
            params={"uri": "memory://session/anything"},
            id=8,
        )
        response = await adapter.handle_request(request)

        assert response.is_error
