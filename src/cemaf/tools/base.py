"""
Tool base classes and protocols.

A Tool is:
- An atomic function with a JSON schema
- Stateless (no memory)
- Returns Result (never raises)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from cemaf.core.types import JSON, ToolID
from cemaf.core.result import Result

F = TypeVar("F", bound=Callable[..., Any])

# Type alias - tools use generic Result
ToolResult = Result[Any]


@dataclass(frozen=True)
class ToolSchema:
    """JSON Schema definition for a tool's parameters."""
    
    name: str
    description: str
    parameters: JSON = field(default_factory=lambda: {"type": "object", "properties": {}})
    required: tuple[str, ...] = ()
    
    def to_openai_format(self) -> JSON:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {**self.parameters, "required": list(self.required)},
            },
        }
    
    def to_anthropic_format(self) -> JSON:
        """Convert to Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {**self.parameters, "required": list(self.required)},
        }


class Tool(ABC):
    """
    Abstract base class for tools.
    
    Example:
        class CalculateTool(Tool):
            @property
            def id(self) -> ToolID:
                return ToolID("calculate")
            
            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(
                    name="calculate",
                    description="Perform arithmetic calculation",
                    parameters={"type": "object", "properties": {"expression": {"type": "string"}}},
                    required=("expression",)
                )
            
            async def execute(self, expression: str) -> ToolResult:
                try:
                    result = eval(expression)
                    return Result.ok(result)
                except Exception as e:
                    return Result.fail(str(e))
    """
    
    @property
    @abstractmethod
    def id(self) -> ToolID:
        """Unique identifier for this tool."""
        ...
    
    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Get the tool's schema."""
        ...
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Returns Result, never raises."""
        ...


def tool(
    name: str,
    description: str,
    parameters: JSON | None = None,
    required: tuple[str, ...] = (),
) -> Callable[[F], Tool]:
    """
    Decorator to create a Tool from a function.
    
    Example:
        @tool(name="add", description="Add two numbers")
        async def add(a: float, b: float) -> ToolResult:
            return Result.ok(a + b)
    """
    def decorator(func: F) -> Tool:
        _schema = ToolSchema(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            required=required,
        )
        
        class FunctionTool(Tool):
            @property
            def id(self) -> ToolID:
                return ToolID(name)
            
            @property
            def schema(self) -> ToolSchema:
                return _schema
            
            async def execute(self, **kwargs: Any) -> ToolResult:
                try:
                    result = await func(**kwargs)
                    if isinstance(result, Result):
                        return result
                    return Result.ok(result)
                except Exception as e:
                    return Result.fail(str(e))
        
        return FunctionTool()
    
    return decorator


# Backwards compatibility alias
tool_decorator = tool
