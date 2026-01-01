"""Mock implementations for MCP testing."""

from collections import deque

from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.protocols import MCPRequest, MCPResponse, Transport


class MockTransport(Transport):
    """
    Mock transport for testing.

    Allows injecting requests and capturing responses.
    """

    def __init__(self) -> None:
        self._connected = False
        self._requests: deque[MCPRequest] = deque()
        self._responses: list[MCPResponse] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, response: MCPResponse) -> None:
        self._responses.append(response)

    async def receive(self) -> MCPRequest:
        if not self._requests:
            raise EOFError("No more requests")
        return self._requests.popleft()

    def inject_request(self, request: MCPRequest) -> None:
        """Inject a request to be received."""
        self._requests.append(request)

    def get_responses(self) -> list[MCPResponse]:
        """Get all sent responses."""
        return self._responses.copy()

    def clear(self) -> None:
        """Clear all requests and responses."""
        self._requests.clear()
        self._responses.clear()


class InMemoryTransport(Transport):
    """
    In-memory transport for testing request/response pairs.

    Directly processes requests without actual I/O.
    """

    def __init__(self, adapter: MCPAdapter) -> None:
        self._adapter = adapter
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, response: MCPResponse) -> None:
        pass  # No-op for in-memory

    async def receive(self) -> MCPRequest:
        raise EOFError("Use send_request instead")

    async def send_request(self, request: MCPRequest) -> MCPResponse:
        """Send request and get response directly."""
        return await self._adapter.handle_request(request)
