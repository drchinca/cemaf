"""
Tool data structures and utilities.

This module provides:
- ToolSchema: JSON Schema definition for tool parameters
- ToolResult: Type alias for tool execution results
- tool decorator: Convert functions to Tool protocol implementations

For the Tool protocol interface, see cemaf.tools.protocols.Tool

Note: Uses PEP 563 () to defer annotation evaluation
and avoid circular imports with cemaf.moderation and cemaf.observability.
Type imports happen at runtime within methods that need them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from cemaf.core.result import Result
from cemaf.core.types import JSON, ToolID
from cemaf.llm.protocols import ToolDefinition

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

    def __post_init__(self) -> None:
        """Validate that schema parameters are JSON-serializable."""
        import json

        try:
            json.dumps(self.parameters)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Tool schema parameters must be JSON-serializable: {e}") from e

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

    def to_definition(self) -> ToolDefinition:
        """Convert to LLM ToolDefinition."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            required=self.required,
        )


class Tool(ABC):
    """
    Abstract base class for tools.

    A Tool is an atomic, stateless function that:
    - Has a unique identifier
    - Has a JSON schema for parameter validation
    - Executes a single, focused task
    - Returns Result (never raises exceptions)

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
                    parameters={
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "Math expression"}
                        }
                    },
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
        """JSON Schema definition for this tool's parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with keyword arguments."""
        ...

    async def _check_moderation_input(
        self,
        text: str,
    ) -> tuple[bool, str | None, list[str]]:
        """Check input text with moderation pipeline if configured.

        Returns tuple of (allowed, error_message, violations_list).
        If no moderation pipeline is configured, always returns (True, None, []).
        """
        # Check if this tool has a moderation_pipeline property
        if not hasattr(self, "moderation_pipeline"):
            return (True, None, [])

        moderation_pipeline = getattr(self, "moderation_pipeline", None)
        if moderation_pipeline is None:
            return (True, None, [])

        # Check input with pre-flight gate
        result = await moderation_pipeline.check_input(text)

        if result.allowed:
            return (True, None, [])

        # Extract violation messages
        violations = [v.message for v in result.violations]
        error_message = violations[0] if violations else "Input blocked by moderation"

        return (False, error_message, violations)

    async def _check_moderation_output(
        self,
        text: str,
    ) -> tuple[bool, str | None, list[str]]:
        """Check output text with moderation pipeline if configured.

        Returns tuple of (allowed, error_message, violations_list).
        If no moderation pipeline is configured, always returns (True, None, []).
        """
        # Check if this tool has a moderation_pipeline property
        if not hasattr(self, "moderation_pipeline"):
            return (True, None, [])

        moderation_pipeline = getattr(self, "moderation_pipeline", None)
        if moderation_pipeline is None:
            return (True, None, [])

        # Check output with post-flight gate
        result = await moderation_pipeline.check_output(text)

        if result.allowed:
            return (True, None, [])

        # Extract violation messages
        violations = [v.message for v in result.violations]
        error_message = violations[0] if violations else "Output blocked by moderation"

        return (False, error_message, violations)


def tool(
    name: str,
    description: str,
    parameters: JSON | None = None,
    required: tuple[str, ...] = (),
) -> Callable[[F], Any]:
    """
    Decorator to create a Tool protocol implementation from a function.

    The returned object implements the Tool protocol (cemaf.tools.protocols.Tool).

    Example:
        @tool(name="add", description="Add two numbers")
        async def add(a: float, b: float) -> ToolResult:
            return Result.ok(a + b)
    """

    def decorator(func: F) -> Any:
        _schema = ToolSchema(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            required=required,
        )

        class FunctionTool:
            """Tool protocol implementation wrapping a function."""

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
