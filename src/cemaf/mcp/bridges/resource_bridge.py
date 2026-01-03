"""Bridge CEMAF resources to MCP format."""

from __future__ import annotations

import json

from cemaf.mcp.types import MCPResource, MCPResourceContents


class ResourceBridge:
    """
    Bridge between CEMAF resources and MCP resource format.
    """

    @staticmethod
    def memory_to_mcp(item: MemoryItem) -> MCPResource:  # noqa: F821
        """
        Convert CEMAF MemoryItem to MCP resource.
        """
        return MCPResource(
            uri=f"memory://{item.scope.value}/{item.key}",
            name=item.key,
            description=f"Memory item in {item.scope.value} scope",
            mimeType="application/json",
        )

    @staticmethod
    def memory_to_contents(item: MemoryItem) -> MCPResourceContents:  # noqa: F821
        """
        Convert MemoryItem value to resource contents.
        """
        value = item.value
        text = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)

        return MCPResourceContents(
            uri=f"memory://{item.scope.value}/{item.key}",
            mimeType="application/json",
            text=text,
        )

    @staticmethod
    def search_result_to_mcp(result: SearchResult) -> MCPResource:  # noqa: F821
        """
        Convert SearchResult to MCP resource.
        """
        doc = result.document
        return MCPResource(
            uri=f"search://{doc.id}",
            name=doc.id,
            description=f"Search result (score: {result.score:.2f})",
            mimeType="text/plain",
        )

    @staticmethod
    def search_result_to_contents(result: SearchResult) -> MCPResourceContents:  # noqa: F821
        """
        Convert SearchResult to resource contents.
        """
        doc = result.document
        content = {
            "content": doc.content,
            "score": result.score,
            "metadata": doc.metadata,
        }
        return MCPResourceContents(
            uri=f"search://{doc.id}",
            mimeType="application/json",
            text=json.dumps(content, indent=2, default=str),
        )
