"""Tests for tool safety flags: is_concurrent_safe, is_read_only, is_destructive."""

import pytest

from cemaf.core.enums import ToolRiskLevel
from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.tools.base import Tool, ToolResult, ToolSchema, tool
from cemaf.tools.protocols import Tool as ToolProtocol

# --- ToolSchema safety flags ---


class TestToolSchemaSafetyFlags:
    """Safety flags on ToolSchema dataclass."""

    def test_defaults_are_all_false(self) -> None:
        schema = ToolSchema(name="test", description="test tool")
        assert schema.is_concurrent_safe is False
        assert schema.is_read_only is False
        assert schema.is_destructive is False

    def test_flags_set_explicitly(self) -> None:
        schema = ToolSchema(
            name="safe_reader",
            description="reads stuff",
            is_concurrent_safe=True,
            is_read_only=True,
            is_destructive=False,
        )
        assert schema.is_concurrent_safe is True
        assert schema.is_read_only is True
        assert schema.is_destructive is False

    def test_destructive_flag(self) -> None:
        schema = ToolSchema(
            name="deleter",
            description="deletes stuff",
            is_destructive=True,
        )
        assert schema.is_destructive is True
        assert schema.is_read_only is False

    def test_frozen_immutability(self) -> None:
        schema = ToolSchema(name="test", description="test", is_read_only=True)
        with pytest.raises(AttributeError):
            schema.is_read_only = False  # type: ignore[misc]


# --- Tool ABC safety flags ---


class ReadOnlyTool(Tool):
    """A read-only tool for testing."""

    @property
    def id(self) -> ToolID:
        return ToolID("reader")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="reader",
            description="reads data",
            is_read_only=True,
            is_concurrent_safe=True,
        )

    @property
    def is_concurrent_safe(self) -> bool:
        return True

    @property
    def is_read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: object) -> ToolResult:
        return Result.ok(data="read result")


class DestructiveTool(Tool):
    """A destructive tool for testing."""

    @property
    def id(self) -> ToolID:
        return ToolID("destroyer")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="destroyer",
            description="destroys things",
            is_destructive=True,
        )

    @property
    def is_destructive(self) -> bool:
        return True

    async def execute(self, **kwargs: object) -> ToolResult:
        return Result.ok(data="destroyed")


class TestToolABCSafetyFlags:
    """Safety flags on Tool ABC subclasses."""

    def test_default_flags_are_false(self) -> None:
        """Tool ABC defaults all safety flags to False."""

        class MinimalTool(Tool):
            @property
            def id(self) -> ToolID:
                return ToolID("minimal")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(name="minimal", description="minimal")

            async def execute(self, **kwargs: object) -> ToolResult:
                return Result.ok(data=None)

        t = MinimalTool()
        assert t.is_concurrent_safe is False
        assert t.is_read_only is False
        assert t.is_destructive is False

    def test_read_only_tool(self) -> None:
        t = ReadOnlyTool()
        assert t.is_read_only is True
        assert t.is_concurrent_safe is True
        assert t.is_destructive is False

    def test_destructive_tool(self) -> None:
        t = DestructiveTool()
        assert t.is_destructive is True
        assert t.is_read_only is False
        assert t.is_concurrent_safe is False


# --- tool() decorator safety flags ---


class TestToolDecoratorSafetyFlags:
    """Safety flags propagated through the @tool decorator."""

    def test_decorator_defaults(self) -> None:
        @tool(name="simple", description="simple tool")
        async def simple_tool() -> ToolResult:
            return Result.ok(data="done")

        assert simple_tool.is_concurrent_safe is False
        assert simple_tool.is_read_only is False
        assert simple_tool.is_destructive is False

    def test_decorator_with_concurrent_safe_schema(self) -> None:
        """Decorator picks up flags from the ToolSchema it creates."""

        # The @tool decorator doesn't expose safety flags directly,
        # but the FunctionTool reads from the schema
        @tool(name="reader", description="reads things")
        async def reader_tool() -> ToolResult:
            return Result.ok(data="read")

        # Default schema has False flags
        assert reader_tool.schema.is_concurrent_safe is False

    def test_function_tool_protocol_compliance(self) -> None:
        """FunctionTool from @tool decorator satisfies Tool protocol."""

        @tool(name="proto", description="protocol test")
        async def proto_tool() -> ToolResult:
            return Result.ok(data="ok")

        assert isinstance(proto_tool, ToolProtocol)


# --- Protocol structural typing with safety flags ---


class TestToolProtocolSafetyFlags:
    """Structural compatibility: any object with safety flag properties satisfies Tool protocol."""

    def test_structural_tool_with_safety_flags(self) -> None:
        """A plain class with safety flag properties satisfies Tool protocol."""

        class CustomTool:
            @property
            def id(self) -> ToolID:
                return ToolID("custom")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(name="custom", description="custom tool")

            @property
            def is_concurrent_safe(self) -> bool:
                return True

            @property
            def is_read_only(self) -> bool:
                return True

            @property
            def is_destructive(self) -> bool:
                return False

            @property
            def risk_level(self) -> ToolRiskLevel:
                return ToolRiskLevel.LOW

            async def execute(self, **kwargs: object) -> ToolResult:
                return Result.ok(data="custom")

        assert isinstance(CustomTool(), ToolProtocol)

    def test_abc_subclass_satisfies_protocol(self) -> None:
        assert isinstance(ReadOnlyTool(), ToolProtocol)
        assert isinstance(DestructiveTool(), ToolProtocol)
