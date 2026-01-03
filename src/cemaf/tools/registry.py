"""
Tool Registry - Auto-discovery and dependency injection for tools.

Provides centralized management of tools with features:
- Auto-discovery from packages
- Dependency injection into tool constructors
- Namespace support to prevent ID collisions
- Schema export for LLM function calling (OpenAI, Anthropic formats)

Usage:
    # Basic registration
    registry = ToolRegistry()
    registry.register(MyTool)  # Auto-instantiate
    registry.register_instance(my_tool)  # Pre-constructed

    # With dependency injection
    registry = ToolRegistry(dependencies={"client": llm_client})
    registry.register(ToolRequiringClient)  # Auto-injects client

    # Auto-discovery from package
    registry = ToolRegistry.auto_discover(
        "myapp.tools",
        dependencies={"client": client}
    )

    # Namespace support (prevent ID collisions)
    registry = ToolRegistry(namespace="web")
    registry.register(SearchTool)  # Stored as "web.search"

    # Export schemas for LLM function calling
    openai_schemas = registry.to_openai_schemas()
    anthropic_schemas = registry.to_anthropic_schemas()

    # Retrieve and execute
    tool = registry.get("my_tool")
    result = await tool.execute(param="value")
"""

import inspect
from typing import Any

from cemaf.core.registry import BaseRegistry, RegistryError
from cemaf.core.types import JSON
from cemaf.tools.base import ToolSchema
from cemaf.tools.protocols import Tool

__all__ = ["ToolRegistry", "RegistryError"]


class ToolRegistry(BaseRegistry[Tool]):
    """
    Registry for tool management with auto-discovery and dependency injection.

    Inherits all common registry functionality from BaseRegistry and adds
    tool-specific features like schema export for LLM function calling.

    Example:
        >>> registry = ToolRegistry(dependencies={"client": llm_client})
        >>> registry.register(WebSearchTool)  # Auto-injects client
        >>> tool = registry.get("web_search")
        >>> result = await tool.execute(query="CEMAF context engineering")
    """

    def __init__(
        self,
        *,
        dependencies: dict[str, Any] | None = None,
        namespace: str = "",
    ) -> None:
        """
        Initialize tool registry.

        Args:
            dependencies: Dependencies to inject into tool constructors.
                         Keys are parameter names, values are injected.
            namespace: Optional namespace prefix for tool IDs (e.g., "web.search")
        """
        super().__init__(
            item_type_name="Tool",
            id_attribute="id",
            dependencies=dependencies,
            namespace=namespace,
        )

    def list_tools(self) -> list[Tool]:
        """
        List all registered tools.

        Returns:
            List of all tool instances
        """
        return self.list_items()

    def to_schemas(self) -> list[ToolSchema]:
        """
        Export all tool schemas.

        Returns:
            List of ToolSchema objects for all registered tools
        """
        return [tool.schema for tool in self._items.values()]

    def to_openai_schemas(self) -> list[JSON]:
        """
        Export schemas in OpenAI function calling format.

        Returns:
            List of schema dicts compatible with OpenAI API

        Example:
            >>> schemas = registry.to_openai_schemas()
            >>> response = openai.chat.completions.create(
            ...     model="gpt-4",
            ...     messages=messages,
            ...     tools=schemas
            ... )
        """
        return [schema.to_openai_format() for schema in self.to_schemas()]

    def to_anthropic_schemas(self) -> list[JSON]:
        """
        Export schemas in Anthropic tool format.

        Returns:
            List of schema dicts compatible with Anthropic API

        Example:
            >>> schemas = registry.to_anthropic_schemas()
            >>> response = client.messages.create(
            ...     model="claude-3-5-sonnet-20241022",
            ...     messages=messages,
            ...     tools=schemas
            ... )
        """
        return [schema.to_anthropic_format() for schema in self.to_schemas()]

    def _implements_protocol(self, obj: Any) -> bool:
        """
        Check if object implements Tool protocol.

        Args:
            obj: Object to check (class or instance)

        Returns:
            True if object implements Tool protocol
        """
        # For classes, check if they would implement the protocol when instantiated
        if inspect.isclass(obj):
            # Check for required attributes
            has_id = hasattr(obj, "id")
            has_schema = hasattr(obj, "schema")
            has_execute = hasattr(obj, "execute")
            return has_id and has_schema and has_execute

        # For instances, use isinstance check
        return isinstance(obj, Tool)
