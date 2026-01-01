"""WebSocket transport for remote MCP communication."""

from typing import Any

from cemaf.mcp.transport.base import BaseTransport


class WebSocketTransport(BaseTransport):
    """
    Transport over WebSocket.

    Connects to a WebSocket server and exchanges JSON-RPC messages.
    """

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url
        self._ws: Any = None  # websockets.WebSocketClientProtocol

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
        return message
