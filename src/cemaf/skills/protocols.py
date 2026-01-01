"""
Skill protocols - Abstract interfaces for composable capabilities.

Supports:
- Tool composition
- Context-aware execution
- Result tracking with tool call traces
- Input/output validation

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Custom skill implementations should implement these protocols rather than
    inheriting from ABC classes. This allows maximum flexibility and follows
    CEMAF's dependency injection principles.

Example:
    >>> from cemaf.skills.protocols import Skill
    >>> from cemaf.core.types import SkillID
    >>>
    >>> class MyCustomSkill:
    ...     @property
    ...     def id(self) -> SkillID:
    ...         return SkillID("my_skill")
    ...
    ...     @property
    ...     def description(self) -> str:
    ...         return "My custom skill"
    ...
    ...     @property
    ...     def tools(self) -> tuple:
    ...         return ()
    ...
    ...     async def execute(self, input, context) -> SkillResult:
    ...         return Result.ok(SkillOutput(data="result"))
    >>>
    >>> # No inheritance needed - structural compatibility!
    >>> assert isinstance(MyCustomSkill(), Skill)
"""

from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import SkillID

# Re-export data classes from base (these are not changed)
from cemaf.skills.base import SkillContext, SkillOutput, SkillResult

__all__ = [
    "Skill",
    "SkillContext",
    "SkillOutput",
    "SkillResult",
]


@runtime_checkable
class Skill[InputT, OutputT](Protocol):
    """
    Protocol for skill implementations.

    A Skill is a composable capability that:
    - Has a unique identifier
    - Has a clear purpose/description
    - Composes one or more tools to accomplish tasks
    - Accepts validated input (typically Pydantic models)
    - Returns structured results with tool call traces

    This is a protocol, not an ABC. Any class with these methods is compatible.

    Type Parameters:
        InputT: Type of input this skill accepts (typically a Pydantic model)
        OutputT: Type of output this skill produces

    Extension Point:
        Implement this protocol for custom skills:
        - Data retrieval skills (API calls, database queries)
        - Processing skills (transformation, analysis)
        - Generation skills (content creation, code generation)
        - Integration skills (third-party service wrappers)

    Example:
        >>> from pydantic import BaseModel
        >>>
        >>> class FetchInput(BaseModel):
        ...     url: str
        ...
        >>> class FetchOutput(BaseModel):
        ...     data: dict
        ...
        >>> class DataFetchSkill:
        ...     def __init__(self, http_tool, parser_tool):
        ...         self._http = http_tool
        ...         self._parser = parser_tool
        ...
        ...     @property
        ...     def id(self) -> SkillID:
        ...         return SkillID("data_fetch")
        ...
        ...     @property
        ...     def description(self) -> str:
        ...         return "Fetches and parses data from URLs"
        ...
        ...     @property
        ...     def tools(self) -> tuple:
        ...         return (self._http, self._parser)
        ...
        ...     async def execute(self, input: FetchInput, ctx: SkillContext) -> SkillResult:
        ...         http_result = await self._http.execute(url=input.url)
        ...         if not http_result.success:
        ...             return Result.fail(http_result.error or "HTTP failed")
        ...
        ...         parse_result = await self._parser.execute(data=http_result.data)
        ...         if not parse_result.success:
        ...             return Result.fail(parse_result.error or "Parse failed")
        ...
        ...         return Result.ok(SkillOutput(
        ...             data=FetchOutput(data=parse_result.data),
        ...             tool_calls=(http_result, parse_result)
        ...         ))
        >>>
        >>> # Automatically compatible - no inheritance!
        >>> skill = DataFetchSkill(http_tool, parser_tool)
        >>> assert isinstance(skill, Skill)

    Best Practices:
        1. **Dependency Injection**: Accept all tools in __init__
        2. **Result Pattern**: Always return Result[SkillOutput[T]], never raise
        3. **Tool Tracing**: Include all tool calls in SkillOutput.tool_calls
        4. **Context Patching**: Return data that can be patched into context
        5. **Resilience**: Combine retry/circuit breaker decorators for robustness

        Decorator Stack Example:
            >>> from cemaf.resilience import retry, circuit_breaker
            >>> from cemaf.cache import cache_result
            >>>
            >>> class RobustSkill:
            ...     @cache_result(ttl=600)
            ...     @circuit_breaker(failure_threshold=5)
            ...     @retry(max_attempts=3)
            ...     async def expensive_operation(self, query: str):
            ...         # Expensive LLM or retrieval call
            ...         pass

    See Also:
        - cemaf.skills.base.Skill (deprecated ABC, use this protocol instead)
        - cemaf.tools.protocols.Tool (tool protocol)
        - cemaf.agents.protocols.Agent (agent protocol)
    """

    @property
    def id(self) -> SkillID:
        """
        Unique identifier for this skill.

        Returns:
            SkillID instance (typically SkillID("name"))

        Example:
            >>> @property
            >>> def id(self) -> SkillID:
            ...     return SkillID("my_skill")
        """
        ...

    @property
    def description(self) -> str:
        """
        Human-readable description of what this skill does.

        Returns:
            Clear, concise description of skill's purpose

        Example:
            >>> @property
            >>> def description(self) -> str:
            ...     return "Fetches data from APIs and parses responses"
        """
        ...

    @property
    def tools(self) -> tuple[Any, ...]:
        """
        Tools used by this skill.

        Tools are atomic functions that skills compose to accomplish tasks.
        This tuple defines which tools this skill has access to.

        Returns:
            Tuple of Tool instances (empty tuple if no tools)

        Example:
            >>> @property
            >>> def tools(self) -> tuple:
            ...     return (self._http_tool, self._parser_tool)
        """
        ...

    async def execute(self, input: InputT, context: SkillContext) -> SkillResult:
        """
        Execute the skill with validated input.

        This is the main entry point for skill execution. The skill should:
        1. Validate input (typically handled by Pydantic)
        2. Execute tools in appropriate sequence
        3. Handle tool failures gracefully
        4. Aggregate results
        5. Return structured output with tool traces

        Args:
            input: Validated input data (typically a Pydantic model)
            context: Read-only execution context with run metadata, memory

        Returns:
            Result[SkillOutput[OutputT]] containing:
            - success: Whether skill execution succeeded
            - data: SkillOutput with result data and tool call traces
            - error: Error message (if failed)
            - metadata: Additional execution metadata

        Example:
            >>> async def execute(self, input: FetchInput, context: SkillContext) -> SkillResult:
            ...     # Execute first tool
            ...     http_result = await self._http.execute(url=input.url)
            ...     if not http_result.success:
            ...         return Result.fail(http_result.error or "HTTP failed")
            ...
            ...     # Execute second tool
            ...     parse_result = await self._parser.execute(data=http_result.data)
            ...     if not parse_result.success:
            ...         return Result.fail(parse_result.error or "Parse failed")
            ...
            ...     # Return aggregated result with tool traces
            ...     return Result.ok(SkillOutput(
            ...         data=FetchOutput(data=parse_result.data),
            ...         tool_calls=(http_result, parse_result)
            ...     ))

        Best Practices:
            - Always return Result, never raise exceptions
            - Include all tool calls in SkillOutput.tool_calls for observability
            - Use context.memory for read-only state access
            - Return data that can be patched into context for downstream nodes
            - Apply resilience decorators for flaky operations
        """
        ...
