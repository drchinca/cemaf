"""
Tool base classes and protocols.

A Tool is:
- An atomic function with a JSON schema
- Stateless (no memory)
- Returns Result (never raises)
- Can record calls for replay/debugging

Note: Uses PEP 563 (from __future__ import annotations) to defer annotation evaluation
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
from cemaf.core.utils import utc_now

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

    async def execute_with_recording(
        self,
        run_logger: RunLogger,  # noqa: F821
        correlation_id: str = "",
        moderation_pipeline: ModerationPipeline | None = None,  # noqa: F821
        **kwargs: Any,
    ) -> ToolResult:
        """
        Execute the tool and record the call to the run logger.

        Args:
            run_logger: Logger to record the call
            correlation_id: Optional correlation ID for tracing
            moderation_pipeline: Optional moderation pipeline for pre/post-flight checks
            **kwargs: Arguments to pass to execute()

        Returns:
            ToolResult from execution
        """
        from cemaf.observability.run_logger import ToolCall

        start_time = utc_now()

        # Pre-flight moderation check
        if moderation_pipeline is not None:
            pre_result = await moderation_pipeline.check_input(kwargs)
            if not pre_result.allowed:
                # Return blocked result
                violation_msg = (
                    pre_result.violations[0].message if pre_result.violations else "Content blocked"
                )
                return Result.fail(f"Pre-flight moderation blocked: {violation_msg}")

        # Execute the tool
        result = await self.execute(**kwargs)

        # Post-flight moderation check (only if execution succeeded)
        if moderation_pipeline is not None and result.success:
            post_result = await moderation_pipeline.check_output(result.data)
            if not post_result.allowed:
                # Return blocked result
                violation_msg = (
                    post_result.violations[0].message if post_result.violations else "Output blocked"
                )
                return Result.fail(f"Post-flight moderation blocked: {violation_msg}")
            # Use redacted content if available
            if post_result.redacted_content is not None:
                result = Result.ok(post_result.redacted_content)

        end_time = utc_now()
        duration_ms = (end_time - start_time).total_seconds() * 1000

        # Create and record the call
        call = ToolCall(
            tool_id=str(self.id),
            input=kwargs,
            output=result.data if result.success else None,
            duration_ms=duration_ms,
            timestamp=start_time,
            correlation_id=correlation_id,
            success=result.success,
            error=result.error if not result.success else None,
        )
        run_logger.record_tool_call(call)

        return result


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
