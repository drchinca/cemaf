"""MCP server wrapping the CEMAF docs index.

Exposes `cemaf_docs_search` and `cemaf_docs_get` as MCP tools so any
MCP-speaking client (Claude Desktop, IDE plugins, other agent frameworks)
can query CEMAF's own documentation without Python knowledge.

Usage (programmatic):
    from cemaf.docs_api import build_default_index
    from cemaf.docs_api.mcp_server import create_docs_mcp_server
    from cemaf.mcp.transport.stdio import StdioTransport

    server = create_docs_mcp_server(
        index=build_default_index(),
        transport=StdioTransport(),
    )
    await server.serve()

Usage (CLI):
    cemaf docs serve

Drop into Claude Desktop's `claude_desktop_config.json`:
    {
      "mcpServers": {
        "cemaf-docs": {
          "command": "uv",
          "args": ["run", "cemaf", "docs", "serve"]
        }
      }
    }
"""

from __future__ import annotations

from cemaf.docs_api.index import DocIndex
from cemaf.docs_api.tools import CemafDocsSearchTool, DocsRetrievalTool
from cemaf.mcp.adapter import MCPAdapter
from cemaf.mcp.protocols import Transport


def create_docs_mcp_server(
    *,
    index: DocIndex,
    transport: Transport,
) -> MCPAdapter:
    """Build an MCPAdapter preloaded with CEMAF docs tools.

    The adapter exposes two tools to MCP clients:
    - `cemaf_docs_search` — top-k search with excerpts and kind filter
    - `cemaf_docs_get` — fetch the full body of one entry by id

    Both are read-only and concurrent-safe. The server does not mutate
    the docs index; each tool call is a pure read against the in-memory
    corpus built at construction time.
    """
    adapter = MCPAdapter(transport=transport)
    adapter.register_tool(tool=CemafDocsSearchTool(index=index))
    adapter.register_tool(tool=DocsRetrievalTool(index=index))
    return adapter


__all__ = ["create_docs_mcp_server"]
