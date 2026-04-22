"""Bridge CEMAF resources to MCP format."""

import json
from typing import Any

from cemaf.mcp.types import MCPResource, MCPResourceContents
from cemaf.memory.base import MemoryItem
from cemaf.memory.protocols import MemoryStore
from cemaf.observability import get_logger
from cemaf.retrieval.protocols import SearchResult

logger = get_logger("mcp.bridges.resource")


class ResourceBridge:
    """Bridge between CEMAF resources and MCP resource format."""

    @staticmethod
    def memory_item_to_resource(
        scope: str,
        key: str,
        description: str = "",
    ) -> MCPResource:
        """Convert memory item metadata to MCP resource."""
        uri = f"memory://{scope}/{key}"
        return MCPResource(
            uri=uri,
            name=f"{scope}:{key}",
            description=description,
            mimeType="application/json",
        )

    @staticmethod
    def memory_to_mcp(item: MemoryItem) -> MCPResource:
        """Convert CEMAF MemoryItem to MCP resource."""
        return MCPResource(
            uri=f"memory://{item.scope.value}/{item.key}",
            name=item.key,
            description=f"Memory item in {item.scope.value} scope",
            mimeType="application/json",
        )

    @staticmethod
    def memory_to_contents(item: MemoryItem) -> MCPResourceContents:
        """Convert MemoryItem value to resource contents."""
        value = item.value
        text = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)
        return MCPResourceContents(
            uri=f"memory://{item.scope.value}/{item.key}",
            mimeType="application/json",
            text=text,
        )

    @staticmethod
    async def list_resources(store: MemoryStore) -> list[MCPResource]:
        """List all memory items as MCP resources."""
        from cemaf.core.enums import MemoryScope

        resources: list[MCPResource] = []

        for scope in MemoryScope:
            try:
                items = await store.list_by_scope(scope)
                for item in items:
                    resource = ResourceBridge.memory_item_to_resource(
                        scope=scope.value,
                        key=item.key,
                        description=f"Memory item in {scope.value} scope",
                    )
                    resources.append(resource)
            except Exception as e:
                logger.warning(
                    "Failed to list resources for memory scope %s: %s",
                    scope.value,
                    str(e),
                    exc_info=True,
                )
                continue

        return resources

    @staticmethod
    async def read_resource(
        store: MemoryStore,
        uri: str,
    ) -> MCPResourceContents | None:
        """Read a memory item by URI (memory://scope/key)."""
        from cemaf.core.enums import MemoryScope

        if not uri.startswith("memory://"):
            return None

        path = uri[len("memory://") :]
        parts = path.split("/", 1)
        if len(parts) != 2:
            return None

        scope_str, key = parts

        try:
            scope = MemoryScope(scope_str)
        except ValueError:
            return None

        item = await store.get(scope, key)
        if item is None:
            return None

        text = json.dumps(item.value, indent=2)
        return MCPResourceContents(
            uri=uri,
            mimeType="application/json",
            text=text,
        )

    @staticmethod
    def search_result_to_mcp(result: SearchResult) -> MCPResource:
        """Convert SearchResult to MCP resource."""
        doc = result.document
        return MCPResource(
            uri=f"search://{doc.id}",
            name=doc.id,
            description=f"Search result (score: {result.score:.2f})",
            mimeType="text/plain",
        )

    @staticmethod
    def search_result_to_contents(result: SearchResult) -> MCPResourceContents:
        """Convert SearchResult to resource contents."""
        doc = result.document
        content: dict[str, Any] = {
            "content": doc.content,
            "score": result.score,
            "metadata": doc.metadata,
        }
        return MCPResourceContents(
            uri=f"search://{doc.id}",
            mimeType="application/json",
            text=json.dumps(content, indent=2, default=str),
        )
