"""HTTP SSE transport for MCP communication."""

from typing import Any

from cemaf.mcp.transport.base import BaseTransport


class SSETransport(BaseTransport):
    """
    Transport over HTTP with Server-Sent Events.

    Uses POST for client->server and SSE for server->client.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._session: Any = None  # aiohttp.ClientSession
        self._sse_response: Any = None

    async def _do_connect(self) -> None:
        try:
            import aiohttp

            self._session = aiohttp.ClientSession()
            # Establish SSE connection for receiving
            self._sse_response = await self._session.get(
                f"{self._base_url}/sse",
                headers={"Accept": "text/event-stream"},
            )
        except ImportError:
            raise ImportError("aiohttp package required for SSETransport") from None

    async def _do_disconnect(self) -> None:
        if self._sse_response:
            self._sse_response.close()
            self._sse_response = None
        if self._session:
            await self._session.close()
            self._session = None

    async def _do_send(self, data: bytes) -> None:
        if self._session is None:
            raise RuntimeError("Not connected")
        async with self._session.post(
            f"{self._base_url}/message",
            data=data,
            headers={"Content-Type": "application/json"},
        ) as resp:
            resp.raise_for_status()

    async def _do_receive(self) -> bytes:
        if self._sse_response is None:
            raise RuntimeError("Not connected")
        # Read SSE event
        async for line in self._sse_response.content:
            line = line.decode("utf-8").strip()
            if line.startswith("data:"):
                return line[5:].strip().encode("utf-8")
        raise EOFError("SSE stream ended")
