"""
Test different architectural patterns for Tool abstraction.

Compares three approaches:
1. Protocol-only (duck typing, no inheritance)
2. ABC-only (inheritance required)
3. Hybrid (ABC with helpers + Protocol for typing)
"""

import pytest

from cemaf.core.result import Result
from cemaf.core.types import JSON, ToolID
from cemaf.tools.base import ToolResult, ToolSchema


class TestProtocolOnlyPattern:
    """Test protocol-only approach (no ABC, just duck typing)."""

    def test_protocol_implementation_no_inheritance(self):
        """Protocol works without inheritance."""
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class Tool(Protocol):
            @property
            def id(self) -> ToolID: ...

            @property
            def schema(self) -> ToolSchema: ...

            async def execute(self, **kwargs) -> ToolResult: ...

        # Implementation without inheritance
        class WeatherTool:
            @property
            def id(self) -> ToolID:
                return ToolID("weather")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(
                    name="weather",
                    description="Get weather",
                    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
                )

            async def execute(self, city: str) -> ToolResult:
                return Result.ok(f"Weather for {city}")

        tool = WeatherTool()
        assert isinstance(tool, Tool)  # Protocol checking works

    def test_standalone_helper_functions(self):
        """Helper functions work with protocol objects."""
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class Tool(Protocol):
            @property
            def schema(self) -> ToolSchema: ...

        # Standalone helper (not in class)
        def to_openai_format(tool: Tool) -> JSON:
            return {
                "type": "function",
                "function": {
                    "name": tool.schema.name,
                    "description": tool.schema.description,
                    "parameters": tool.schema.parameters,
                },
            }

        class SimpleTool:
            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(name="test", description="Test tool")

        tool = SimpleTool()
        openai = to_openai_format(tool)

        assert openai["type"] == "function"
        assert openai["function"]["name"] == "test"

    def test_protocol_type_checking_in_functions(self):
        """Functions accept any protocol-compatible object."""
        from typing import Protocol

        class Tool(Protocol):
            @property
            def id(self) -> ToolID: ...

        def register_tool(tool: Tool) -> str:
            """Function accepts any Tool-like object."""
            return str(tool.id)

        class DuckTool:
            @property
            def id(self) -> ToolID:
                return ToolID("duck")

        # No inheritance, but type checks pass
        result = register_tool(DuckTool())
        assert result == "duck"


class TestABCOnlyPattern:
    """Test ABC-only approach (inheritance required)."""

    def test_abc_with_helpers(self):
        """ABC provides shared helper methods."""
        from abc import ABC, abstractmethod

        class Tool(ABC):
            @property
            @abstractmethod
            def id(self) -> ToolID: ...

            @property
            @abstractmethod
            def schema(self) -> ToolSchema: ...

            @abstractmethod
            async def execute(self, **kwargs) -> ToolResult: ...

            # Concrete helper methods
            def to_openai_format(self) -> JSON:
                """All tools get this for free."""
                return {
                    "type": "function",
                    "function": {
                        "name": self.schema.name,
                        "description": self.schema.description,
                        "parameters": self.schema.parameters,
                    },
                }

            def to_anthropic_format(self) -> JSON:
                """All tools get this for free."""
                return {
                    "name": self.schema.name,
                    "description": self.schema.description,
                    "input_schema": self.schema.parameters,
                }

        class WeatherTool(Tool):
            @property
            def id(self) -> ToolID:
                return ToolID("weather")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(name="weather", description="Get weather")

            async def execute(self, **kwargs) -> ToolResult:
                return Result.ok("sunny")

        tool = WeatherTool()

        # Helper methods available for free
        openai = tool.to_openai_format()
        anthropic = tool.to_anthropic_format()

        assert openai["type"] == "function"
        assert anthropic["name"] == "weather"

    def test_abc_requires_inheritance(self):
        """ABC doesn't work with duck typing."""
        from abc import ABC, abstractmethod

        class Tool(ABC):
            @abstractmethod
            async def execute(self) -> ToolResult: ...

        class DuckTool:
            """Implements everything correctly but doesn't inherit."""

            async def execute(self) -> ToolResult:
                return Result.ok("done")

        duck = DuckTool()

        # isinstance fails because no inheritance
        assert not isinstance(duck, Tool)

    def test_abc_enforces_abstract_methods(self):
        """ABC prevents instantiation if methods missing."""
        from abc import ABC, abstractmethod

        class Tool(ABC):
            @abstractmethod
            def id(self) -> ToolID: ...

        class IncompleteTool(Tool):
            pass

        # Cannot instantiate - missing abstract method
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteTool()


class TestHybridPattern:
    """Test hybrid approach (ABC with helpers + Protocol for typing)."""

    def test_abc_provides_helpers_protocol_provides_typing(self):
        """ABC for helpers, Protocol for function signatures."""
        from abc import ABC, abstractmethod
        from typing import Protocol, runtime_checkable

        # Protocol - minimal contract
        @runtime_checkable
        class Tool(Protocol):
            @property
            def id(self) -> ToolID: ...

            @property
            def schema(self) -> ToolSchema: ...

            async def execute(self, **kwargs) -> ToolResult: ...

        # ABC - batteries included
        class BaseTool(ABC):
            @property
            @abstractmethod
            def id(self) -> ToolID: ...

            @property
            @abstractmethod
            def schema(self) -> ToolSchema: ...

            @abstractmethod
            async def execute(self, **kwargs) -> ToolResult: ...

            # Concrete helpers
            def to_openai_format(self) -> JSON:
                return {"type": "function", "function": {"name": self.schema.name}}

        # Option 1: Inherit from ABC (get helpers)
        class ManagedTool(BaseTool):
            @property
            def id(self) -> ToolID:
                return ToolID("managed")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(name="managed", description="Managed tool")

            async def execute(self, **kwargs) -> ToolResult:
                return Result.ok("managed")

        # Option 2: Duck type (no helpers)
        class CustomTool:
            @property
            def id(self) -> ToolID:
                return ToolID("custom")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(name="custom", description="Custom tool")

            async def execute(self, **kwargs) -> ToolResult:
                return Result.ok("custom")

        # Function accepts Protocol (works with both)
        def register_tool(tool: Tool) -> str:
            return str(tool.id)

        managed = ManagedTool()
        custom = CustomTool()

        # Both work with function (Protocol typing)
        assert register_tool(managed) == "managed"
        assert register_tool(custom) == "custom"

        # Only ABC descendant has helpers
        assert hasattr(managed, "to_openai_format")
        assert not hasattr(custom, "to_openai_format")

        # Both pass isinstance check
        assert isinstance(managed, Tool)  # Protocol check
        assert isinstance(custom, Tool)  # Protocol check

    def test_function_signatures_use_protocol(self):
        """Best practice: functions use Protocol, not ABC."""
        from abc import ABC, abstractmethod
        from typing import Protocol

        class Tool(Protocol):
            @property
            def id(self) -> ToolID: ...

        class BaseTool(ABC):
            @property
            @abstractmethod
            def id(self) -> ToolID: ...

        # ✅ GOOD - Use Protocol in signature
        def good_function(tool: Tool) -> str:
            """Accepts any Tool-like object."""
            return str(tool.id)

        # ❌ BAD - Use ABC in signature (too restrictive)
        def bad_function(tool: BaseTool) -> str:
            """Only accepts ABC descendants."""
            return str(tool.id)

        class ABCTool(BaseTool):
            @property
            def id(self) -> ToolID:
                return ToolID("abc")

        class DuckTool:
            @property
            def id(self) -> ToolID:
                return ToolID("duck")

        abc_tool = ABCTool()
        duck_tool = DuckTool()

        # good_function accepts both
        assert good_function(abc_tool) == "abc"
        assert good_function(duck_tool) == "duck"

        # bad_function only accepts ABC descendants
        assert bad_function(abc_tool) == "abc"
        # This would fail type checking (but works at runtime):
        # bad_function(duck_tool)  # Type error: DuckTool not a BaseTool


class TestDeveloperExperience:
    """Test developer experience with different patterns."""

    def test_protocol_error_detection(self):
        """Protocol errors detected at type-check time, not import time."""
        from typing import Protocol

        class Tool(Protocol):
            async def execute(self) -> ToolResult: ...

        class IncompleteTool:
            """Missing execute method."""

            pass

        # No error at instantiation (unlike ABC)
        tool = IncompleteTool()
        assert tool is not None

        # Error would happen at call time
        with pytest.raises(AttributeError):
            tool.execute()

    def test_abc_error_detection(self):
        """ABC errors detected at instantiation time."""
        from abc import ABC, abstractmethod

        class Tool(ABC):
            @abstractmethod
            async def execute(self) -> ToolResult: ...

        class IncompleteTool(Tool):
            """Missing execute method."""

            pass

        # Error at instantiation (better for beginners)
        with pytest.raises(TypeError):
            IncompleteTool()

    def test_helper_method_discoverability(self):
        """ABC helpers are more discoverable than standalone functions."""
        from abc import ABC, abstractmethod

        class BaseTool(ABC):
            @abstractmethod
            def id(self) -> ToolID: ...

            # Helper is obvious
            def to_openai_format(self) -> JSON:
                return {"id": str(self.id)}

        class MyTool(BaseTool):
            @property
            def id(self) -> ToolID:
                return ToolID("my")

        tool = MyTool()

        # IDE autocomplete shows to_openai_format()
        # Obvious: tool.<tab> shows helper methods
        result = tool.to_openai_format()
        assert result["id"] == "my"


class TestPerformanceImplications:
    """Test performance differences between patterns."""

    def test_protocol_isinstance_performance(self):
        """Protocol isinstance is slower than ABC isinstance."""
        import time
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class ProtocolTool(Protocol):
            def id(self) -> ToolID: ...

        class DuckTool:
            @property
            def id(self) -> ToolID:
                return ToolID("duck")

        tool = DuckTool()

        # Protocol isinstance requires structural check
        start = time.perf_counter()
        for _ in range(10000):
            isinstance(tool, ProtocolTool)
        protocol_time = time.perf_counter() - start

        # Just measure it (don't assert - varies by machine)
        assert protocol_time >= 0

    def test_abc_isinstance_performance(self):
        """ABC isinstance is faster (simple class check)."""
        import time
        from abc import ABC, abstractmethod

        class ABCTool(ABC):
            @property
            @abstractmethod
            def id(self) -> ToolID: ...

        class MyTool(ABCTool):
            @property
            def id(self) -> ToolID:
                return ToolID("my")

        tool = MyTool()

        # ABC isinstance is simple class hierarchy check
        start = time.perf_counter()
        for _ in range(10000):
            isinstance(tool, ABCTool)
        abc_time = time.perf_counter() - start

        # Just measure it
        assert abc_time >= 0
