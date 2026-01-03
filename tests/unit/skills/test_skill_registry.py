"""
Tests for SkillRegistry - Auto-discovery and dependency injection for skills.

This module tests the registry pattern for skill management, including:
- Skill registration (classes and instances)
- Dependency injection (tools + other dependencies)
- Auto-discovery from packages
- Namespace support for ID collision prevention
"""

import pytest

from cemaf.core.result import Result
from cemaf.core.types import SkillID, ToolID
from cemaf.skills.base import SkillContext, SkillOutput, SkillResult
from cemaf.skills.registry import RegistryError, SkillRegistry
from cemaf.tools.base import ToolResult, ToolSchema
from cemaf.tools.protocols import Tool


# Test tool implementations (skills compose tools)
class MockTool:
    """Mock tool for testing skill dependencies."""

    @property
    def id(self) -> ToolID:
        return ToolID("mock_tool")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="mock_tool", description="Mock")

    async def execute(self, **kwargs) -> ToolResult:
        return Result.ok("mock_result")


class AnotherMockTool:
    """Another mock tool."""

    @property
    def id(self) -> ToolID:
        return ToolID("another_tool")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(name="another_tool", description="Another")

    async def execute(self, **kwargs) -> ToolResult:
        return Result.ok("another_result")


# Test skill implementations
class SimpleSkill:
    """Simple skill with no dependencies."""

    @property
    def id(self) -> SkillID:
        return SkillID("simple_skill")

    @property
    def description(self) -> str:
        return "A simple test skill"

    @property
    def tools(self) -> tuple:
        return ()

    async def execute(self, input: str, context: SkillContext) -> SkillResult:
        return Result.ok(SkillOutput(data=f"Simple: {input}"))


class SkillWithToolDependency:
    """Skill that requires a tool."""

    def __init__(self, mock_tool: Tool) -> None:
        self.mock_tool = mock_tool

    @property
    def id(self) -> SkillID:
        return SkillID("tool_dependent_skill")

    @property
    def description(self) -> str:
        return "Skill with tool dependency"

    @property
    def tools(self) -> tuple:
        return (self.mock_tool,)

    async def execute(self, input: str, context: SkillContext) -> SkillResult:
        result = await self.mock_tool.execute()
        return Result.ok(SkillOutput(data=f"Used tool: {result.data}"))


class SkillWithMultipleDeps:
    """Skill with multiple dependencies (tools + other)."""

    def __init__(self, mock_tool: Tool, client: str) -> None:
        self.mock_tool = mock_tool
        self.client = client

    @property
    def id(self) -> SkillID:
        return SkillID("multi_dep_skill")

    @property
    def description(self) -> str:
        return "Skill with multiple dependencies"

    @property
    def tools(self) -> tuple:
        return (self.mock_tool,)

    async def execute(self, input: str, context: SkillContext) -> SkillResult:
        return Result.ok(SkillOutput(data=f"Client: {self.client}"))


# === Basic Registration Tests ===


def test_create_empty_registry():
    """Create an empty registry."""
    registry = SkillRegistry()
    assert registry.list_skills() == []
    assert registry.count() == 0


def test_register_skill_class():
    """Register a skill class without dependencies."""
    registry = SkillRegistry()
    registry.register(SimpleSkill)

    skill = registry.get("simple_skill")
    assert skill is not None
    assert isinstance(skill, SimpleSkill)
    assert skill.id == SkillID("simple_skill")


def test_register_skill_instance():
    """Register a skill instance directly."""
    registry = SkillRegistry()
    skill_instance = SimpleSkill()
    registry.register_instance(skill_instance)

    retrieved = registry.get("simple_skill")
    assert retrieved is skill_instance


def test_list_skills():
    """List all registered skills."""
    registry = SkillRegistry()
    registry.register(SimpleSkill)

    skills = registry.list_skills()
    assert len(skills) == 1
    assert skills[0].id == SkillID("simple_skill")


def test_count_skills():
    """Count registered skills."""
    registry = SkillRegistry()
    assert registry.count() == 0

    registry.register(SimpleSkill)
    assert registry.count() == 1


def test_has_skill():
    """Check if skill exists in registry."""
    registry = SkillRegistry()
    assert not registry.has("simple_skill")

    registry.register(SimpleSkill)
    assert registry.has("simple_skill")


def test_get_missing_skill_returns_none():
    """Get non-existent skill returns None."""
    registry = SkillRegistry()
    skill = registry.get("nonexistent")
    assert skill is None


def test_get_or_raise_missing_skill():
    """Get non-existent skill with get_or_raise raises error."""
    registry = SkillRegistry()

    with pytest.raises(RegistryError, match="Skill not found: nonexistent"):
        registry.get_or_raise("nonexistent")


def test_get_or_raise_existing_skill():
    """Get existing skill with get_or_raise returns skill."""
    registry = SkillRegistry()
    registry.register(SimpleSkill)

    skill = registry.get_or_raise("simple_skill")
    assert skill.id == SkillID("simple_skill")


# === Duplicate Registration Tests ===


def test_register_duplicate_skill_raises_error():
    """Registering duplicate skill ID raises error."""
    registry = SkillRegistry()
    registry.register(SimpleSkill)

    with pytest.raises(RegistryError, match="Skill already registered: simple_skill"):
        registry.register(SimpleSkill)


def test_register_duplicate_instance_raises_error():
    """Registering duplicate instance raises error."""
    registry = SkillRegistry()
    skill = SimpleSkill()
    registry.register_instance(skill)

    with pytest.raises(RegistryError, match="Skill already registered: simple_skill"):
        registry.register_instance(skill)


# === Dependency Injection Tests ===


def test_dependency_injection_tool():
    """Inject tool dependency into skill constructor."""
    tool = MockTool()
    registry = SkillRegistry(dependencies={"mock_tool": tool})
    registry.register(SkillWithToolDependency)

    skill = registry.get("tool_dependent_skill")
    assert skill is not None
    assert skill.mock_tool is tool


def test_dependency_injection_multiple_deps():
    """Inject multiple dependencies (tool + other)."""
    tool = MockTool()
    registry = SkillRegistry(
        dependencies={
            "mock_tool": tool,
            "client": "test_client",
        }
    )
    registry.register(SkillWithMultipleDeps)

    skill = registry.get("multi_dep_skill")
    assert skill is not None
    assert skill.mock_tool is tool
    assert skill.client == "test_client"


def test_register_class_without_required_dependency():
    """Registering skill class without required dependency raises error."""
    registry = SkillRegistry()  # No dependencies

    with pytest.raises(
        RegistryError,
        match="Failed to instantiate skill 'SkillWithToolDependency': Missing required dependency",
    ):
        registry.register(SkillWithToolDependency)


def test_register_instance_ignores_dependencies():
    """Registering instance ignores registry dependencies (already constructed)."""
    registry = SkillRegistry(dependencies={"mock_tool": MockTool()})
    tool = AnotherMockTool()
    skill = SkillWithToolDependency(mock_tool=tool)
    registry.register_instance(skill)

    retrieved = registry.get("tool_dependent_skill")
    assert retrieved.mock_tool is tool  # Uses instance value, not registry


# === Namespace Tests ===


def test_namespace_prefixes_skill_ids():
    """Namespace prefixes skill IDs to prevent collisions."""
    registry = SkillRegistry(namespace="analytics")
    registry.register(SimpleSkill)

    # Tool stored with namespace prefix
    assert registry.has("analytics.simple_skill")
    assert not registry.has("simple_skill")

    skill = registry.get("analytics.simple_skill")
    assert skill is not None
    # Original skill ID unchanged
    assert skill.id == SkillID("simple_skill")


def test_multiple_namespaces_no_collision():
    """Multiple registries with different namespaces don't collide."""
    analytics_registry = SkillRegistry(namespace="analytics")
    social_registry = SkillRegistry(namespace="social")

    analytics_registry.register(SimpleSkill)
    social_registry.register(SimpleSkill)

    assert analytics_registry.has("analytics.simple_skill")
    assert social_registry.has("social.simple_skill")
    assert not analytics_registry.has("social.simple_skill")
    assert not social_registry.has("analytics.simple_skill")


# === Auto-Discovery Tests ===


@pytest.mark.asyncio
async def test_auto_discover_from_module():
    """Auto-discover skills from a module path.

    Note: This test would require creating a test module structure.
    For now, we'll test the interface and error handling.
    """
    # Test that auto_discover is a class method
    assert hasattr(SkillRegistry, "auto_discover")

    # Test error case: invalid module path
    with pytest.raises(RegistryError, match="Failed to discover skills from"):
        SkillRegistry.auto_discover("nonexistent.module.path")


def test_auto_discover_with_dependencies():
    """Auto-discover can receive dependencies for skill instantiation.

    Note: This would require a test module. Testing the interface.
    """
    # Verify the method signature accepts dependencies
    import inspect

    sig = inspect.signature(SkillRegistry.auto_discover)
    assert "dependencies" in sig.parameters


# === Skill Execution Tests ===


@pytest.mark.asyncio
async def test_execute_registered_skill():
    """Execute a skill retrieved from registry."""
    registry = SkillRegistry()
    registry.register(SimpleSkill)

    skill = registry.get("simple_skill")
    context = SkillContext(run_id="test", agent_id="test_agent", memory={})
    result = await skill.execute(input="test", context=context)

    assert result.success is True
    assert result.data.data == "Simple: test"


@pytest.mark.asyncio
async def test_execute_skill_with_injected_tool():
    """Execute skill with injected tool dependency."""
    tool = MockTool()
    registry = SkillRegistry(dependencies={"mock_tool": tool})
    registry.register(SkillWithToolDependency)

    skill = registry.get("tool_dependent_skill")
    context = SkillContext(run_id="test", agent_id="test_agent", memory={})
    result = await skill.execute(input="test", context=context)

    assert result.success is True
    assert "mock_result" in result.data.data


# === Edge Cases ===


def test_empty_namespace():
    """Empty namespace behaves like no namespace."""
    registry = SkillRegistry(namespace="")
    registry.register(SimpleSkill)

    # Should work without namespace prefix
    assert registry.has("simple_skill")
    skill = registry.get("simple_skill")
    assert skill is not None


def test_register_invalid_skill_class():
    """Registering class without Skill protocol raises error."""

    class NotASkill:
        pass

    registry = SkillRegistry()

    with pytest.raises(RegistryError, match="does not implement Skill protocol"):
        registry.register(NotASkill)  # type: ignore


def test_register_instance_not_implementing_protocol():
    """Registering instance not implementing Skill protocol raises error."""

    class NotASkill:
        pass

    registry = SkillRegistry()

    with pytest.raises(RegistryError, match="does not implement Skill protocol"):
        registry.register_instance(NotASkill())  # type: ignore


def test_clear_registry():
    """Clear all skills from registry."""
    registry = SkillRegistry()
    registry.register(SimpleSkill)
    assert registry.count() == 1

    registry.clear()
    assert registry.count() == 0
    assert registry.list_skills() == []


def test_registry_repr():
    """Registry has useful string representation."""
    registry = SkillRegistry(namespace="test")
    registry.register(SimpleSkill)

    repr_str = repr(registry)
    assert "SkillRegistry" in repr_str
    assert "namespace=test" in repr_str or "1 skill" in repr_str
