"""
Unit tests for MCP (Model Context Protocol) module.

Tests:
- MCPRequest: creation, serialization, deserialization
- MCPResponse: success, failure, serialization
- MCPError: factory methods and error codes
- MCPToolDefinition, MCPResource, MCPPrompt: serialization
- MockTransport: inject_request, get_responses
- MCPAdapter: handle_request for tools/list, prompts/list
- Transport: base protocol
"""

from typing import Any

import pytest

from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.mock import InMemoryTransport, MockTransport
from cemaf.mcp.protocols import (
    MCPError,
    MCPErrorCode,
    MCPRequest,
    MCPResponse,
)
from cemaf.mcp.types import (
    MCPPrompt,
    MCPPromptArgument,
    MCPResource,
    MCPResourceContents,
    MCPToolDefinition,
    MCPToolResult,
)
from cemaf.tools.base import Tool, ToolSchema

# --- Mock Tool for Testing ---


class EchoTool(Tool):
    """Simple tool that echoes input for testing."""

    @property
    def id(self) -> ToolID:
        return ToolID("echo")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="echo",
            description="Echoes input back",
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to echo"},
                },
            },
            required=("message",),
        )

    async def execute(self, **kwargs: Any) -> Result[str]:
        message = kwargs.get("message", "")
        return Result.ok(f"Echo: {message}")


class CalculatorTool(Tool):
    """Simple calculator tool for testing."""

    @property
    def id(self) -> ToolID:
        return ToolID("calculator")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="calculator",
            description="Performs basic arithmetic",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                    "operation": {"type": "string", "enum": ["add", "subtract"]},
                },
            },
            required=("a", "b", "operation"),
        )

    async def execute(self, **kwargs: Any) -> Result[float]:
        a = kwargs.get("a", 0)
        b = kwargs.get("b", 0)
        op = kwargs.get("operation", "add")

        if op == "add":
            return Result.ok(a + b)
        elif op == "subtract":
            return Result.ok(a - b)
        else:
            return Result.fail(f"Unknown operation: {op}")


# --- MCPRequest Tests ---


class TestMCPRequest:
    """Tests for MCPRequest."""

    def test_creation_basic(self):
        """MCPRequest can be created with basic parameters."""
        request = MCPRequest(method="tools/list", id=1)

        assert request.method == "tools/list"
        assert request.id == 1
        assert request.jsonrpc == "2.0"
        assert request.params == {}

    def test_creation_with_params(self):
        """MCPRequest can be created with parameters."""
        request = MCPRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {"message": "hello"}},
            id="req-123",
        )

        assert request.method == "tools/call"
        assert request.params["name"] == "echo"
        assert request.id == "req-123"

    def test_to_dict(self):
        """MCPRequest converts to dictionary correctly."""
        request = MCPRequest(
            method="tools/list",
            params={"cursor": None},
            id=42,
        )

        d = request.to_dict()

        assert d["jsonrpc"] == "2.0"
        assert d["method"] == "tools/list"
        assert d["params"] == {"cursor": None}
        assert d["id"] == 42

    def test_to_dict_no_params(self):
        """MCPRequest.to_dict omits empty params."""
        request = MCPRequest(method="ping", id=1)

        d = request.to_dict()

        assert "params" not in d

    def test_to_dict_notification(self):
        """MCPRequest.to_dict omits id for notifications."""
        request = MCPRequest(method="initialized", id=None)

        d = request.to_dict()

        assert "id" not in d

    def test_from_dict(self):
        """MCPRequest can be created from dictionary."""
        data = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "test"},
            "id": 99,
        }

        request = MCPRequest.from_dict(data)

        assert request.method == "tools/call"
        assert request.params == {"name": "test"}
        assert request.id == 99
        assert request.jsonrpc == "2.0"

    def test_from_dict_minimal(self):
        """MCPRequest.from_dict handles minimal data."""
        data = {"method": "ping"}

        request = MCPRequest.from_dict(data)

        assert request.method == "ping"
        assert request.params == {}
        assert request.id is None

    def test_is_notification(self):
        """MCPRequest.is_notification returns True when id is None."""
        notification = MCPRequest(method="initialized", id=None)
        regular = MCPRequest(method="ping", id=1)

        assert notification.is_notification is True
        assert regular.is_notification is False

    def test_create_factory_method(self):
        """MCPRequest.create factory method works correctly."""
        request = MCPRequest.create(
            method="tools/list",
            params={"cursor": None},
            id=1,
        )

        assert request.method == "tools/list"
        assert request.id == 1

    def test_notification_factory_method(self):
        """MCPRequest.notification factory method creates notification."""
        request = MCPRequest.notification(
            method="initialized",
            params={"status": "ready"},
        )

        assert request.is_notification is True
        assert request.params["status"] == "ready"

    def test_immutability(self):
        """MCPRequest is frozen/immutable."""
        request = MCPRequest(method="ping", id=1)

        with pytest.raises((TypeError, AttributeError)):
            request.method = "pong"  # type: ignore


# --- MCPResponse Tests ---


class TestMCPResponse:
    """Tests for MCPResponse."""

    def test_success_response(self):
        """MCPResponse.success creates successful response."""
        response = MCPResponse.success(id=1, result={"tools": []})

        assert response.id == 1
        assert response.result == {"tools": []}
        assert response.error is None
        assert response.is_success is True
        assert response.is_error is False

    def test_failure_response(self):
        """MCPResponse.failure creates error response."""
        error = MCPError.method_not_found("unknown/method")
        response = MCPResponse.failure(id=2, error=error)

        assert response.id == 2
        assert response.result is None
        assert response.error == error
        assert response.is_success is False
        assert response.is_error is True

    def test_to_dict_success(self):
        """MCPResponse.to_dict for success response."""
        response = MCPResponse.success(id=1, result={"data": "test"})

        d = response.to_dict()

        assert d["jsonrpc"] == "2.0"
        assert d["id"] == 1
        assert d["result"] == {"data": "test"}
        assert "error" not in d

    def test_to_dict_failure(self):
        """MCPResponse.to_dict for error response."""
        error = MCPError(code=-32600, message="Invalid request")
        response = MCPResponse.failure(id=1, error=error)

        d = response.to_dict()

        assert d["jsonrpc"] == "2.0"
        assert d["id"] == 1
        assert d["error"]["code"] == -32600
        assert d["error"]["message"] == "Invalid request"

    def test_from_dict_success(self):
        """MCPResponse.from_dict parses success response."""
        data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "echo"}]},
        }

        response = MCPResponse.from_dict(data)

        assert response.id == 1
        assert response.result == {"tools": [{"name": "echo"}]}
        assert response.error is None

    def test_from_dict_failure(self):
        """MCPResponse.from_dict parses error response."""
        data = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32601,
                "message": "Method not found",
                "data": {"method": "unknown"},
            },
        }

        response = MCPResponse.from_dict(data)

        assert response.id == 1
        assert response.error is not None
        assert response.error.code == -32601
        assert response.error.message == "Method not found"
        assert response.error.data == {"method": "unknown"}

    def test_immutability(self):
        """MCPResponse is frozen/immutable."""
        response = MCPResponse.success(id=1, result={})

        with pytest.raises((TypeError, AttributeError)):
            response.id = 2  # type: ignore


# --- MCPError Tests ---


class TestMCPError:
    """Tests for MCPError."""

    def test_parse_error(self):
        """MCPError.parse_error creates correct error."""
        error = MCPError.parse_error("JSON parse failed")

        assert error.code == MCPErrorCode.PARSE_ERROR
        assert error.code == -32700
        assert error.message == "JSON parse failed"

    def test_invalid_request(self):
        """MCPError.invalid_request creates correct error."""
        error = MCPError.invalid_request("Missing method field")

        assert error.code == MCPErrorCode.INVALID_REQUEST
        assert error.code == -32600
        assert error.message == "Missing method field"

    def test_method_not_found(self):
        """MCPError.method_not_found creates correct error."""
        error = MCPError.method_not_found("unknown/method")

        assert error.code == MCPErrorCode.METHOD_NOT_FOUND
        assert error.code == -32601
        assert "unknown/method" in error.message

    def test_invalid_params(self):
        """MCPError.invalid_params creates correct error."""
        error = MCPError.invalid_params("Missing required parameter: name")

        assert error.code == MCPErrorCode.INVALID_PARAMS
        assert error.code == -32602
        assert "name" in error.message

    def test_internal_error(self):
        """MCPError.internal_error creates correct error."""
        error = MCPError.internal_error("Unexpected exception")

        assert error.code == MCPErrorCode.INTERNAL_ERROR
        assert error.code == -32603
        assert error.message == "Unexpected exception"

    def test_server_error(self):
        """MCPError.server_error creates error with custom code."""
        error = MCPError.server_error(-32050, "Custom server error", {"detail": "info"})

        assert error.code == -32050
        assert error.message == "Custom server error"
        assert error.data == {"detail": "info"}

    def test_server_error_invalid_code(self):
        """MCPError.server_error raises for invalid code."""
        with pytest.raises(ValueError):
            MCPError.server_error(-32100, "Invalid")  # Outside range

        with pytest.raises(ValueError):
            MCPError.server_error(-31999, "Invalid")  # Outside range

    def test_to_dict(self):
        """MCPError.to_dict converts correctly."""
        error = MCPError(code=-32600, message="Bad request", data={"field": "missing"})

        d = error.to_dict()

        assert d["code"] == -32600
        assert d["message"] == "Bad request"
        assert d["data"] == {"field": "missing"}

    def test_to_dict_no_data(self):
        """MCPError.to_dict omits data when None."""
        error = MCPError(code=-32600, message="Bad request")

        d = error.to_dict()

        assert "data" not in d

    def test_immutability(self):
        """MCPError is frozen/immutable."""
        error = MCPError.parse_error()

        with pytest.raises((TypeError, AttributeError)):
            error.code = 0  # type: ignore


# --- MCP Type Tests ---


class TestMCPToolDefinition:
    """Tests for MCPToolDefinition."""

    def test_creation(self):
        """MCPToolDefinition can be created."""
        tool_def = MCPToolDefinition(
            name="test_tool",
            description="A test tool",
            inputSchema={
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            },
        )

        assert tool_def.name == "test_tool"
        assert tool_def.description == "A test tool"

    def test_to_dict(self):
        """MCPToolDefinition.to_dict converts correctly."""
        tool_def = MCPToolDefinition(
            name="echo",
            description="Echoes input",
            inputSchema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
            },
        )

        d = tool_def.to_dict()

        assert d["name"] == "echo"
        assert d["description"] == "Echoes input"
        assert d["inputSchema"]["type"] == "object"


class TestMCPResource:
    """Tests for MCPResource."""

    def test_creation(self):
        """MCPResource can be created."""
        resource = MCPResource(
            uri="memory://session/user_name",
            name="session:user_name",
            description="User's name from session",
            mimeType="application/json",
        )

        assert resource.uri == "memory://session/user_name"
        assert resource.name == "session:user_name"

    def test_to_dict(self):
        """MCPResource.to_dict converts correctly."""
        resource = MCPResource(
            uri="file:///path/to/file.txt",
            name="file.txt",
            description="A text file",
            mimeType="text/plain",
        )

        d = resource.to_dict()

        assert d["uri"] == "file:///path/to/file.txt"
        assert d["name"] == "file.txt"
        assert d["mimeType"] == "text/plain"


class TestMCPResourceContents:
    """Tests for MCPResourceContents."""

    def test_text_contents(self):
        """MCPResourceContents with text."""
        contents = MCPResourceContents(
            uri="file:///test.txt",
            mimeType="text/plain",
            text="Hello, world!",
        )

        d = contents.to_dict()

        assert d["uri"] == "file:///test.txt"
        assert d["text"] == "Hello, world!"
        assert "blob" not in d

    def test_blob_contents(self):
        """MCPResourceContents with blob."""
        contents = MCPResourceContents(
            uri="file:///image.png",
            mimeType="image/png",
            blob="iVBORw0KGgoAAAANSUhEUgAAAAUA...",
        )

        d = contents.to_dict()

        assert d["blob"] == "iVBORw0KGgoAAAANSUhEUgAAAAUA..."
        assert "text" not in d


class TestMCPPrompt:
    """Tests for MCPPrompt."""

    def test_creation(self):
        """MCPPrompt can be created."""
        prompt = MCPPrompt(
            name="greeting",
            description="Generates a greeting",
            arguments=(MCPPromptArgument(name="name", description="Person's name", required=True),),
        )

        assert prompt.name == "greeting"
        assert len(prompt.arguments) == 1

    def test_to_dict(self):
        """MCPPrompt.to_dict converts correctly."""
        prompt = MCPPrompt(
            name="summary",
            description="Summarizes text",
            arguments=(
                MCPPromptArgument(name="text", required=True),
                MCPPromptArgument(name="max_words", required=False),
            ),
        )

        d = prompt.to_dict()

        assert d["name"] == "summary"
        assert d["description"] == "Summarizes text"
        assert len(d["arguments"]) == 2
        assert d["arguments"][0]["name"] == "text"
        assert d["arguments"][0]["required"] is True


class TestMCPToolResult:
    """Tests for MCPToolResult."""

    def test_text_result(self):
        """MCPToolResult.text creates text result."""
        result = MCPToolResult.text("Hello, world!")

        assert result.isError is False
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert result.content[0]["text"] == "Hello, world!"

    def test_error_result(self):
        """MCPToolResult.error creates error result."""
        result = MCPToolResult.error("Something went wrong")

        assert result.isError is True
        assert result.content[0]["text"] == "Something went wrong"

    def test_to_dict(self):
        """MCPToolResult.to_dict converts correctly."""
        result = MCPToolResult.text("Test output")

        d = result.to_dict()

        assert d["isError"] is False
        assert d["content"] == [{"type": "text", "text": "Test output"}]


# --- MockTransport Tests ---


class TestMockTransport:
    """Tests for MockTransport."""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """MockTransport can connect and disconnect."""
        transport = MockTransport()

        assert transport.is_connected is False

        await transport.connect()
        assert transport.is_connected is True

        await transport.disconnect()
        assert transport.is_connected is False

    @pytest.mark.asyncio
    async def test_inject_request(self):
        """MockTransport.inject_request adds request to queue."""
        transport = MockTransport()
        await transport.connect()

        request = MCPRequest(method="ping", id=1)
        transport.inject_request(request)

        received = await transport.receive()
        assert received.method == "ping"
        assert received.id == 1

    @pytest.mark.asyncio
    async def test_inject_multiple_requests(self):
        """MockTransport handles multiple injected requests in order."""
        transport = MockTransport()
        await transport.connect()

        transport.inject_request(MCPRequest(method="first", id=1))
        transport.inject_request(MCPRequest(method="second", id=2))
        transport.inject_request(MCPRequest(method="third", id=3))

        r1 = await transport.receive()
        r2 = await transport.receive()
        r3 = await transport.receive()

        assert r1.method == "first"
        assert r2.method == "second"
        assert r3.method == "third"

    @pytest.mark.asyncio
    async def test_receive_empty_queue(self):
        """MockTransport.receive raises EOFError when queue is empty."""
        transport = MockTransport()
        await transport.connect()

        with pytest.raises(EOFError):
            await transport.receive()

    @pytest.mark.asyncio
    async def test_send_captures_response(self):
        """MockTransport.send captures responses."""
        transport = MockTransport()
        await transport.connect()

        response1 = MCPResponse.success(id=1, result={"data": "first"})
        response2 = MCPResponse.success(id=2, result={"data": "second"})

        await transport.send(response1)
        await transport.send(response2)

        responses = transport.get_responses()
        assert len(responses) == 2
        assert responses[0].result == {"data": "first"}
        assert responses[1].result == {"data": "second"}

    def test_get_responses_returns_copy(self):
        """MockTransport.get_responses returns a copy."""
        transport = MockTransport()

        responses1 = transport.get_responses()
        responses2 = transport.get_responses()

        assert responses1 is not responses2

    @pytest.mark.asyncio
    async def test_clear(self):
        """MockTransport.clear clears all requests and responses."""
        transport = MockTransport()
        await transport.connect()

        transport.inject_request(MCPRequest(method="ping", id=1))
        await transport.send(MCPResponse.success(id=1, result={}))

        transport.clear()

        assert len(transport.get_responses()) == 0
        with pytest.raises(EOFError):
            await transport.receive()


# --- InMemoryTransport Tests ---


class TestInMemoryTransport:
    """Tests for InMemoryTransport."""

    @pytest.mark.asyncio
    async def test_send_request(self):
        """InMemoryTransport.send_request works with adapter."""
        mock_transport = MockTransport()
        adapter = MCPAdapter(transport=mock_transport)

        # Register a tool
        adapter.register_tool(EchoTool())

        # Create in-memory transport with adapter
        in_memory = InMemoryTransport(adapter)
        await in_memory.connect()

        # Send request directly
        request = MCPRequest(method="tools/list", id=1)
        response = await in_memory.send_request(request)

        assert response.is_success
        assert "tools" in response.result

    @pytest.mark.asyncio
    async def test_receive_raises(self):
        """InMemoryTransport.receive raises EOFError."""
        mock_transport = MockTransport()
        adapter = MCPAdapter(transport=mock_transport)
        in_memory = InMemoryTransport(adapter)

        with pytest.raises(EOFError, match="Use send_request instead"):
            await in_memory.receive()


# --- MCPAdapter Tests ---


class TestMCPAdapter:
    """Tests for MCPAdapter."""

    @pytest.mark.asyncio
    async def test_handle_tools_list(self):
        """MCPAdapter handles tools/list request."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        adapter.register_tool(EchoTool())
        adapter.register_tool(CalculatorTool())

        request = MCPRequest(method="tools/list", id=1)
        response = await adapter.handle_request(request)

        assert response.is_success
        assert "tools" in response.result
        assert len(response.result["tools"]) == 2

        tool_names = {t["name"] for t in response.result["tools"]}
        assert "echo" in tool_names
        assert "calculator" in tool_names

    @pytest.mark.asyncio
    async def test_handle_tools_list_empty(self):
        """MCPAdapter handles tools/list with no tools."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        request = MCPRequest(method="tools/list", id=1)
        response = await adapter.handle_request(request)

        assert response.is_success
        assert response.result["tools"] == []

    @pytest.mark.asyncio
    async def test_handle_prompts_list_empty(self):
        """MCPAdapter handles prompts/list with no prompts."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        request = MCPRequest(method="prompts/list", id=1)
        response = await adapter.handle_request(request)

        assert response.is_success
        assert response.result["prompts"] == []

    @pytest.mark.asyncio
    async def test_handle_method_not_found(self):
        """MCPAdapter returns error for unknown method."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        request = MCPRequest(method="unknown/method", id=1)
        response = await adapter.handle_request(request)

        assert response.is_error
        assert response.error is not None
        assert response.error.code == MCPErrorCode.METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_handle_ping(self):
        """MCPAdapter handles ping request."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        request = MCPRequest(method="ping", id=1)
        response = await adapter.handle_request(request)

        assert response.is_success
        assert response.result == {}

    @pytest.mark.asyncio
    async def test_handle_initialize(self):
        """MCPAdapter handles initialize request."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        request = MCPRequest(
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
            id=1,
        )
        response = await adapter.handle_request(request)

        assert response.is_success
        assert "protocolVersion" in response.result
        assert "serverInfo" in response.result
        assert "capabilities" in response.result

    @pytest.mark.asyncio
    async def test_register_unregister_tool(self):
        """MCPAdapter can register and unregister tools."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        tool = EchoTool()
        adapter.register_tool(tool)

        assert adapter.tool_count == 1
        assert "echo" in adapter.list_tool_names()

        removed = adapter.unregister_tool("echo")
        assert removed is True
        assert adapter.tool_count == 0

        # Unregistering again returns False
        removed = adapter.unregister_tool("echo")
        assert removed is False

    @pytest.mark.asyncio
    async def test_register_multiple_tools(self):
        """MCPAdapter can register multiple tools at once."""
        transport = MockTransport()
        adapter = MCPAdapter(transport=transport)

        adapter.register_tools([EchoTool(), CalculatorTool()])

        assert adapter.tool_count == 2


# --- Transport Protocol Tests ---


class TestTransportProtocol:
    """Tests for Transport protocol compliance."""

    def test_mock_transport_is_transport(self):
        """MockTransport implements Transport protocol."""
        transport = MockTransport()

        # Check it has required methods/properties
        assert hasattr(transport, "is_connected")
        assert hasattr(transport, "connect")
        assert hasattr(transport, "disconnect")
        assert hasattr(transport, "send")
        assert hasattr(transport, "receive")

    def test_in_memory_transport_is_transport(self):
        """InMemoryTransport implements Transport protocol."""
        mock_transport = MockTransport()
        adapter = MCPAdapter(transport=mock_transport)
        transport = InMemoryTransport(adapter)

        # Check it has required methods/properties
        assert hasattr(transport, "is_connected")
        assert hasattr(transport, "connect")
        assert hasattr(transport, "disconnect")
        assert hasattr(transport, "send")
        assert hasattr(transport, "receive")
