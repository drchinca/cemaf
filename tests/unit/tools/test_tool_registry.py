"""
Tests for ToolRegistry - Auto-discovery and dependency injection for tools.

This module tests the registry pattern for tool management, including:
- Tool registration (classes and instances)
- Dependency injection into tool constructors
- Auto-discovery from packages
- Namespace support for ID collision prevention
- Schema export for LLM function calling
"""

import pytest

from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.tools.base import ToolResult, ToolSchema
from cemaf.tools.registry import RegistryError, ToolRegistry


# Test tool implementations
class SimpleTool:
    """Simple tool with no dependencies."""

    @property
    def id(self) -> ToolID:
        return ToolID("simple_tool")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="simple_tool",
            description="A simple test tool",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
            required=("value",),
        )

    async def execute(self, value: str) -> ToolResult:
        return Result.ok(f"Simple: {value}")


class ToolWithDependency:
    """Tool that requires a dependency."""

    def __init__(self, client: str) -> None:
        self.client = client

    @property
    def id(self) -> ToolID:
        return ToolID("dependent_tool")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="dependent_tool",
            description="Tool with dependency",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            required=("query",),
        )

    async def execute(self, query: str) -> ToolResult:
        return Result.ok(f"Client: {self.client}, Query: {query}")


class ToolWithMultipleDeps:
    """Tool that requires multiple dependencies."""

    def __init__(self, client: str, database: str) -> None:
        self.client = client
        self.database = database

    @property
    def id(self) -> ToolID:
        return ToolID("multi_dep_tool")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="multi_dep_tool",
            description="Tool with multiple dependencies",
            parameters={
                "type": "object",
                "properties": {"action": {"type": "string"}},
            },
        )

    async def execute(self, action: str) -> ToolResult:
        return Result.ok(f"{action} via {self.client} and {self.database}")


# === Basic Registration Tests ===


def test_create_empty_registry():
    """Create an empty registry."""
    registry = ToolRegistry()
    assert registry.list_tools() == []
    assert registry.count() == 0


def test_register_tool_class():
    """Register a tool class without dependencies."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    tool = registry.get("simple_tool")
    assert tool is not None
    assert isinstance(tool, SimpleTool)
    assert tool.id == ToolID("simple_tool")


def test_register_tool_instance():
    """Register a tool instance directly."""
    registry = ToolRegistry()
    tool_instance = SimpleTool()
    registry.register_instance(tool_instance)

    retrieved = registry.get("simple_tool")
    assert retrieved is tool_instance


def test_list_tools():
    """List all registered tools."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0].id == ToolID("simple_tool")


def test_count_tools():
    """Count registered tools."""
    registry = ToolRegistry()
    assert registry.count() == 0

    registry.register(SimpleTool)
    assert registry.count() == 1


def test_has_tool():
    """Check if tool exists in registry."""
    registry = ToolRegistry()
    assert not registry.has("simple_tool")

    registry.register(SimpleTool)
    assert registry.has("simple_tool")


def test_get_missing_tool_returns_none():
    """Get non-existent tool returns None."""
    registry = ToolRegistry()
    tool = registry.get("nonexistent")
    assert tool is None


def test_get_or_raise_missing_tool():
    """Get non-existent tool with get_or_raise raises error."""
    registry = ToolRegistry()

    with pytest.raises(RegistryError, match="Tool not found: nonexistent"):
        registry.get_or_raise("nonexistent")


def test_get_or_raise_existing_tool():
    """Get existing tool with get_or_raise returns tool."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    tool = registry.get_or_raise("simple_tool")
    assert tool.id == ToolID("simple_tool")


# === Duplicate Registration Tests ===


def test_register_duplicate_tool_raises_error():
    """Registering duplicate tool ID raises error."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    with pytest.raises(RegistryError, match="Tool already registered: simple_tool"):
        registry.register(SimpleTool)


def test_register_duplicate_instance_raises_error():
    """Registering duplicate instance raises error."""
    registry = ToolRegistry()
    tool = SimpleTool()
    registry.register_instance(tool)

    with pytest.raises(RegistryError, match="Tool already registered: simple_tool"):
        registry.register_instance(tool)


# === Dependency Injection Tests ===


def test_dependency_injection_single_dep():
    """Inject single dependency into tool constructor."""
    registry = ToolRegistry(dependencies={"client": "test_client"})
    registry.register(ToolWithDependency)

    tool = registry.get("dependent_tool")
    assert tool is not None
    assert tool.client == "test_client"


def test_dependency_injection_multiple_deps():
    """Inject multiple dependencies into tool constructor."""
    registry = ToolRegistry(
        dependencies={
            "client": "test_client",
            "database": "test_db",
        }
    )
    registry.register(ToolWithMultipleDeps)

    tool = registry.get("multi_dep_tool")
    assert tool is not None
    assert tool.client == "test_client"
    assert tool.database == "test_db"


def test_register_class_without_required_dependency():
    """Registering tool class without required dependency raises error."""
    registry = ToolRegistry()  # No dependencies

    with pytest.raises(
        RegistryError,
        match="Failed to instantiate tool 'ToolWithDependency': Missing required dependency",
    ):
        registry.register(ToolWithDependency)


def test_register_instance_ignores_dependencies():
    """Registering instance ignores registry dependencies (already constructed)."""
    registry = ToolRegistry(dependencies={"client": "registry_client"})
    tool = ToolWithDependency(client="instance_client")
    registry.register_instance(tool)

    retrieved = registry.get("dependent_tool")
    assert retrieved.client == "instance_client"  # Uses instance value, not registry


# === Namespace Tests ===


def test_namespace_prefixes_tool_ids():
    """Namespace prefixes tool IDs to prevent collisions."""
    registry = ToolRegistry(namespace="web")
    registry.register(SimpleTool)

    # Tool stored with namespace prefix
    assert registry.has("web.simple_tool")
    assert not registry.has("simple_tool")

    tool = registry.get("web.simple_tool")
    assert tool is not None
    # Original tool ID unchanged
    assert tool.id == ToolID("simple_tool")


def test_multiple_namespaces_no_collision():
    """Multiple registries with different namespaces don't collide."""
    web_registry = ToolRegistry(namespace="web")
    api_registry = ToolRegistry(namespace="api")

    web_registry.register(SimpleTool)
    api_registry.register(SimpleTool)

    assert web_registry.has("web.simple_tool")
    assert api_registry.has("api.simple_tool")
    assert not web_registry.has("api.simple_tool")
    assert not api_registry.has("web.simple_tool")


def test_namespace_in_list_tools():
    """List tools includes namespace prefix."""
    registry = ToolRegistry(namespace="custom")
    registry.register(SimpleTool)

    ids = [t.id for t in registry.list_tools()]
    # Note: Actual tool instances keep original IDs
    # Namespace only affects registry lookup keys
    assert ToolID("simple_tool") in ids


# === Schema Export Tests ===


def test_to_schemas_basic():
    """Export all tool schemas."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    schemas = registry.to_schemas()
    assert len(schemas) == 1
    assert schemas[0].name == "simple_tool"
    assert schemas[0].description == "A simple test tool"


def test_to_openai_schemas():
    """Export schemas in OpenAI function calling format."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    schemas = registry.to_openai_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "simple_tool"
    assert "parameters" in schemas[0]["function"]


def test_to_anthropic_schemas():
    """Export schemas in Anthropic tool format."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    schemas = registry.to_anthropic_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "simple_tool"
    assert "input_schema" in schemas[0]


def test_to_schemas_multiple_tools():
    """Export schemas for multiple tools."""
    registry = ToolRegistry(dependencies={"client": "test"})
    registry.register(SimpleTool)
    registry.register(ToolWithDependency)

    schemas = registry.to_schemas()
    assert len(schemas) == 2
    names = {s.name for s in schemas}
    assert names == {"simple_tool", "dependent_tool"}


# === Auto-Discovery Tests ===


@pytest.mark.asyncio
async def test_auto_discover_from_module():
    """Auto-discover tools from a module path.

    Note: This test would require creating a test module structure.
    For now, we'll test the interface and error handling.
    """
    # Test that auto_discover is a class method
    assert hasattr(ToolRegistry, "auto_discover")

    # Test error case: invalid module path
    with pytest.raises(RegistryError, match="Failed to discover tools from"):
        ToolRegistry.auto_discover("nonexistent.module.path")


def test_auto_discover_with_dependencies():
    """Auto-discover can receive dependencies for tool instantiation.

    Note: This would require a test module. Testing the interface.
    """
    # Verify the method signature accepts dependencies
    import inspect

    sig = inspect.signature(ToolRegistry.auto_discover)
    assert "dependencies" in sig.parameters


# === Tool Execution Tests ===


@pytest.mark.asyncio
async def test_execute_registered_tool():
    """Execute a tool retrieved from registry."""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    tool = registry.get("simple_tool")
    result = await tool.execute(value="test")

    assert result.success is True
    assert result.data == "Simple: test"


@pytest.mark.asyncio
async def test_execute_tool_with_injected_dependency():
    """Execute tool with dependency injection."""
    registry = ToolRegistry(dependencies={"client": "injected_client"})
    registry.register(ToolWithDependency)

    tool = registry.get("dependent_tool")
    result = await tool.execute(query="test_query")

    assert result.success is True
    assert "Client: injected_client" in result.data
    assert "Query: test_query" in result.data


# === Edge Cases ===


def test_empty_namespace():
    """Empty namespace behaves like no namespace."""
    registry = ToolRegistry(namespace="")
    registry.register(SimpleTool)

    # Should work without namespace prefix
    assert registry.has("simple_tool")
    tool = registry.get("simple_tool")
    assert tool is not None


def test_register_invalid_tool_class():
    """Registering class without Tool protocol raises error."""

    class NotATool:
        pass

    registry = ToolRegistry()

    with pytest.raises(RegistryError, match="does not implement Tool protocol"):
        registry.register(NotATool)  # type: ignore


def test_register_instance_not_implementing_protocol():
    """Registering instance not implementing Tool protocol raises error."""

    class NotATool:
        pass

    registry = ToolRegistry()

    with pytest.raises(RegistryError, match="does not implement Tool protocol"):
        registry.register_instance(NotATool())  # type: ignore


def test_clear_registry():
    """Clear all tools from registry."""
    registry = ToolRegistry()
    registry.register(SimpleTool)
    assert registry.count() == 1

    registry.clear()
    assert registry.count() == 0
    assert registry.list_tools() == []


def test_registry_repr():
    """Registry has useful string representation."""
    registry = ToolRegistry(namespace="test")
    registry.register(SimpleTool)

    repr_str = repr(registry)
    assert "ToolRegistry" in repr_str
    assert "namespace=test" in repr_str or "1 tool" in repr_str
