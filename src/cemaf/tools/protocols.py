"""
Tool protocols - Abstract interfaces for atomic functions.

Supports:
- JSON schema definitions for LLM function calling
- Stateless execution
- OpenAI/Anthropic function calling formats
- Result pattern (never raises exceptions)

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Custom tool implementations should implement these protocols rather than
    inheriting from ABC classes. This allows maximum flexibility and follows
    CEMAF's dependency injection principles.

Example:
    >>> from cemaf.tools.protocols import Tool
    >>> from cemaf.core.types import ToolID
    >>> from cemaf.core.result import Result
    >>>
    >>> class MyCustomTool:
    ...     @property
    ...     def id(self) -> ToolID:
    ...         return ToolID("my_tool")
    ...
    ...     @property
    ...     def schema(self) -> ToolSchema:
    ...         return ToolSchema(name="my_tool", description="My custom tool")
    ...
    ...     async def execute(self, **kwargs) -> ToolResult:
    ...         return Result.ok("result")
    >>>
    >>> # No inheritance needed - structural compatibility!
    >>> assert isinstance(MyCustomTool(), Tool)
"""

from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import ToolID

# Re-export data classes from base (these are not changed)
from cemaf.tools.base import ToolResult, ToolSchema

__all__ = [
    "Tool",
    "ToolResult",
    "ToolSchema",
]


@runtime_checkable
class Tool(Protocol):
    """
    Protocol for tool implementations.

    A Tool is an atomic, stateless function that:
    - Has a unique identifier
    - Has a JSON schema for parameter validation
    - Executes a single, focused task
    - Returns Result (never raises exceptions)
    - Can be called by LLMs via function calling

    This is a protocol, not an ABC. Any class with these methods is compatible.

    Extension Point:
        Implement this protocol for custom tools:
        - API integration tools (HTTP requests, database queries)
        - Data processing tools (parsing, transformation)
        - Calculation tools (math, statistics)
        - File operation tools (read, write, search)
        - External service tools (cloud APIs, webhooks)

    Example:
        >>> from pydantic import BaseModel
        >>>
        >>> class CalculateTool:
        ...     @property
        ...     def id(self) -> ToolID:
        ...         return ToolID("calculate")
        ...
        ...     @property
        ...     def schema(self) -> ToolSchema:
        ...         return ToolSchema(
        ...             name="calculate",
        ...             description="Perform arithmetic calculation",
        ...             parameters={
        ...                 "type": "object",
        ...                 "properties": {
        ...                     "expression": {"type": "string", "description": "Math expression"}
        ...                 }
        ...             },
        ...             required=("expression",)
        ...         )
        ...
        ...     async def execute(self, expression: str) -> ToolResult:
        ...         try:
        ...             result = eval(expression)
        ...             return Result.ok(result)
        ...         except Exception as e:
        ...             return Result.fail(str(e))
        >>>
        >>> # Automatically compatible - no inheritance!
        >>> tool = CalculateTool()
        >>> assert isinstance(tool, Tool)
        >>>
        >>> # Can be used in LLM function calling
        >>> openai_schema = tool.schema.to_openai_format()
        >>> anthropic_schema = tool.schema.to_anthropic_format()

    Best Practices:
        1. **Single Responsibility**: Each tool does ONE thing well
        2. **Stateless**: No instance variables, no memory
        3. **Result Pattern**: Always return Result, never raise exceptions
        4. **Schema-Driven**: Define clear, detailed JSON schemas
        5. **Deterministic**: Same inputs → same outputs (when possible)
        6. **Idempotent**: Safe to retry (when possible)

        Example:
            >>> # Good: Stateless, single-purpose, returns Result
            >>> class GetWeatherTool:
            ...     async def execute(self, city: str) -> ToolResult:
            ...         data = await fetch_weather(city)
            ...         return Result.ok(data)
            >>>
            >>> # Bad: Stateful, raises exceptions
            >>> class BadTool:
            ...     def __init__(self):
            ...         self.cache = {}  # ❌ Stateful
            ...
            ...     async def execute(self, city: str) -> dict:
            ...         return fetch_weather(city)  # ❌ Raises exceptions

    Schema Best Practices:
        1. **Clear Descriptions**: Help LLMs understand when to use the tool
        2. **Type Hints**: Use JSON Schema types (string, number, boolean, etc.)
        3. **Validation**: Mark required parameters
        4. **Examples**: Include examples in descriptions when helpful

        Example:
            >>> schema = ToolSchema(
            ...     name="search_database",
            ...     description="Search database for records matching criteria. "
            ...                 "Returns up to 100 results. Use filters to narrow results.",
            ...     parameters={
            ...         "type": "object",
            ...         "properties": {
            ...             "query": {
            ...                 "type": "string",
            ...                 "description": "Search query (supports wildcards)"
            ...             },
            ...             "table": {
            ...                 "type": "string",
            ...                 "enum": ["users", "posts", "comments"],
            ...                 "description": "Table to search"
            ...             },
            ...             "limit": {
            ...                 "type": "integer",
            ...                 "minimum": 1,
            ...                 "maximum": 100,
            ...                 "default": 10,
            ...                 "description": "Max results to return"
            ...             }
            ...         }
            ...     },
            ...     required=("query", "table")
            ... )

    See Also:
        - cemaf.tools.base.Tool (deprecated ABC, use this protocol instead)
        - cemaf.tools.base.tool (decorator for creating tools from functions)
        - cemaf.skills.protocols.Skill (skill protocol that uses tools)
    """

    @property
    def id(self) -> ToolID:
        """
        Unique identifier for this tool.

        Returns:
            ToolID instance (typically ToolID("name"))

        Example:
            >>> @property
            >>> def id(self) -> ToolID:
            ...     return ToolID("my_tool")
        """
        ...

    @property
    def schema(self) -> ToolSchema:
        """
        JSON Schema definition for this tool's parameters.

        The schema is used for:
        - LLM function calling (OpenAI, Anthropic formats)
        - Parameter validation
        - Documentation generation

        Returns:
            ToolSchema with name, description, parameters, and required fields

        Example:
            >>> @property
            >>> def schema(self) -> ToolSchema:
            ...     return ToolSchema(
            ...         name="get_weather",
            ...         description="Get current weather for a city",
            ...         parameters={
            ...             "type": "object",
            ...             "properties": {
            ...                 "city": {
            ...                     "type": "string",
            ...                     "description": "City name (e.g., 'New York')"
            ...                 },
            ...                 "units": {
            ...                     "type": "string",
            ...                     "enum": ["celsius", "fahrenheit"],
            ...                     "default": "celsius"
            ...                 }
            ...             }
            ...         },
            ...         required=("city",)
            ...     )
        """
        ...

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool with keyword arguments.

        This is the main entry point for tool execution. The tool should:
        1. Validate inputs (schema already defines structure)
        2. Execute the atomic operation
        3. Return Result (never raise exceptions)

        Args:
            **kwargs: Keyword arguments matching the tool's schema

        Returns:
            Result[Any] containing:
            - success: Whether execution succeeded
            - data: The result data (if successful)
            - error: Error message (if failed)
            - metadata: Additional execution metadata

        Example:
            >>> async def execute(self, city: str, units: str = "celsius") -> ToolResult:
            ...     try:
            ...         # Fetch weather data
            ...         response = await http_client.get(f"/weather?city={city}&units={units}")
            ...         data = await response.json()
            ...
            ...         # Return success result
            ...         return Result.ok(data, metadata={"source": "weather_api"})
            ...
            ...     except Exception as e:
            ...         # Return failure result (never raise)
            ...         return Result.fail(
            ...             f"Failed to fetch weather: {str(e)}",
            ...             metadata={"city": city}
            ...         )

        Best Practices:
            - Always return Result, never raise exceptions
            - Catch all exceptions and convert to Result.fail
            - Include helpful error messages
            - Add metadata for debugging/observability
            - Keep execution focused and atomic
            - Avoid side effects beyond the tool's purpose
        """
        ...
