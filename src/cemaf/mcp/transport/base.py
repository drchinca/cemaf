import json
from abc import ABC, abstractmethod

from cemaf.mcp.protocols import MCPRequest, MCPResponse


class BaseTransport(ABC):
    """
    Base class for MCP transports with common functionality.

    Subclasses implement the actual I/O operations.
    """

    def __init__(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Establish connection."""
        await self._do_connect()
        self._connected = True

    async def disconnect(self) -> None:
        """Close connection."""
        await self._do_disconnect()
        self._connected = False

    async def send(self, response: MCPResponse) -> None:
        """Send response, serialized to JSON."""
        data = json.dumps(response.to_dict()).encode("utf-8")
        await self._do_send(data)

    async def receive(self) -> MCPRequest:
        """Receive request, parsed from JSON."""
        data = await self._do_receive()
        parsed = json.loads(data.decode("utf-8"))
        return MCPRequest.from_dict(parsed)

    @abstractmethod
    async def _do_connect(self) -> None:
        """Implementation-specific connect."""
        ...

    @abstractmethod
    async def _do_disconnect(self) -> None:
        """Implementation-specific disconnect."""
        ...

    @abstractmethod
    async def _do_send(self, data: bytes) -> None:
        """Implementation-specific send."""
        ...

    @abstractmethod
    async def _do_receive(self) -> bytes:
        """Implementation-specific receive."""
        ...
