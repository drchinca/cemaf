"""Stdio transport for local MCP communication."""

import asyncio
import sys

from cemaf.mcp.transport.base import BaseTransport


class StdioTransport(BaseTransport):
    """
    Transport over stdin/stdout.

    Reads JSON-RPC messages from stdin, writes to stdout.
    Messages are newline-delimited.
    """

    def __init__(self) -> None:
        super().__init__()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def _do_connect(self) -> None:
        # Get async streams for stdin/stdout
        loop = asyncio.get_running_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        # For stdout
        transport, _ = await loop.connect_write_pipe(asyncio.Protocol, sys.stdout)
        self._writer = asyncio.StreamWriter(transport, protocol, self._reader, loop)

    async def _do_disconnect(self) -> None:
        if self._writer:
            self._writer.close()
            # await self._writer.wait_closed()  # May not be available
        self._reader = None
        self._writer = None

    async def _do_send(self, data: bytes) -> None:
        if self._writer is None:
            raise RuntimeError("Not connected")
        self._writer.write(data + b"\n")
        await self._writer.drain()

    async def _do_receive(self) -> bytes:
        if self._reader is None:
            raise RuntimeError("Not connected")
        line = await self._reader.readline()
        if not line:
            raise EOFError("End of input")
        return line.strip()
