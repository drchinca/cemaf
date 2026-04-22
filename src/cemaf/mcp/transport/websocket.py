"""WebSocket transport for remote MCP communication."""

from typing import Protocol, runtime_checkable

from cemaf.mcp.transport.base import BaseTransport


@runtime_checkable
class WebSocketConnection(Protocol):
    """Protocol for WebSocket connections (e.g., websockets.WebSocketClientProtocol)."""

    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self) -> None: ...


class WebSocketTransport(BaseTransport):
    """
    Transport over WebSocket.

    Connects to a WebSocket server and exchanges JSON-RPC messages.
    """

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url
        self._ws: WebSocketConnection | None = None

    async def _do_connect(self) -> None:
        try:
            import websockets

            self._ws = await websockets.connect(self._url)
        except ImportError:
            raise ImportError("websockets package required for WebSocketTransport") from None

    async def _do_disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _do_send(self, data: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("Not connected")
        await self._ws.send(data.decode("utf-8"))

    async def _do_receive(self) -> bytes:
        if self._ws is None:
            raise RuntimeError("Not connected")
        message = await self._ws.recv()
        if isinstance(message, str):
            return message.encode("utf-8")
        # websockets.recv() can return str or bytes, ensure we return bytes
        return bytes(message) if not isinstance(message, bytes) else message
