"""
Skill data structures and utilities.

This module provides:
- SkillOutput: Dataclass for skill results with tool call traces
- SkillResult: Type alias for skill execution results
- SkillContext: Read-only context provided to skills

For the Skill protocol interface, see cemaf.skills.protocols.Skill

## Best Practices for Skills

### Context Patching for Retrieval

When a skill retrieves data from external stores (vector DB, cache, memory),
emit the results to context so downstream nodes can reuse them:

```python
class RetrievalSkill:  # Implements Skill protocol
    async def execute(self, input: SearchInput, context: SkillContext) -> SkillResult:
        # Retrieve from vector store
        docs = await self.vector_store.search(input.query, top_k=5)

        # Return with metadata for context patching
        return Result.ok(SkillOutput(
            data={"documents": docs, "query": input.query},
            tool_calls=(),  # Track tool calls if applicable
        ))
```

The DAG executor will automatically patch `data` into context if the node
has an `output_key` configured.

### Decorator Stacks for Resilience + Caching

Combine resilience and caching decorators in this order (innermost first):

```python
from cemaf.resilience import retry, circuit_breaker
from cemaf.cache import cache_result

class RobustSkill:  # Implements Skill protocol
    # Order matters: cache → circuit breaker → retry → function
    @cache_result(ttl=600)
    @circuit_breaker(failure_threshold=5)
    @retry(max_attempts=3)
    async def expensive_operation(self, query: str):
        # Expensive LLM or retrieval call
        pass
```

**Why this order?**
1. `cache_result` (outermost): Check cache first, skip everything if hit
2. `circuit_breaker`: Fail fast if service is degraded
3. `retry` (innermost): Retry individual failures

See examples/retrieval_dag_example.py for a complete working example.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from cemaf.core.result import Result
from cemaf.core.types import JSON, SkillID
from cemaf.tools.base import Tool, ToolResult

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class SkillOutput[OutputT]:
    """Skill result with tool call trace."""

    data: OutputT
    tool_calls: tuple[ToolResult, ...] = ()


# Type alias for skill results
SkillResult = Result[SkillOutput[Any]]


class SkillContext(BaseModel):
    """Read-only context provided to skills."""

    model_config = {"frozen": True}

    run_id: str
    agent_id: str
    memory: JSON = Field(default_factory=dict)
    artifacts: JSON = Field(default_factory=dict)


class Skill[InputT: BaseModel, OutputT](ABC):
    """
    Abstract base class for skills.

    A Skill is a composable capability that:
    - Has a unique identifier
    - Has a clear purpose/description
    - Composes one or more tools to accomplish tasks
    - Accepts validated input (typically Pydantic models)
    - Returns structured results with tool call traces

    Example:
        class DataFetchSkill(Skill[FetchInput, FetchOutput]):
            def __init__(self, http_tool: Tool, parser_tool: Tool):
                self._http = http_tool
                self._parser = parser_tool

            @property
            def id(self) -> SkillID:
                return SkillID("data_fetch")

            @property
            def description(self) -> str:
                return "Fetch and parse data from APIs"

            @property
            def tools(self) -> tuple[Tool, ...]:
                return (self._http, self._parser)

            async def execute(self, input: FetchInput, context: SkillContext) -> SkillResult:
                # Fetch data using HTTP tool
                fetch_result = await self._http.execute(url=input.url)
                if not fetch_result.success:
                    return Result.fail(fetch_result.error)

                # Parse data using parser tool
                parse_result = await self._parser.execute(data=fetch_result.data)
                if not parse_result.success:
                    return Result.fail(parse_result.error)

                # Return with tool call trace
                return Result.ok(SkillOutput(
                    data=FetchOutput(data=parse_result.data),
                    tool_calls=(fetch_result, parse_result)
                ))
    """

    @property
    @abstractmethod
    def id(self) -> SkillID:
        """Unique identifier for this skill."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """What this skill does."""
        ...

    @property
    @abstractmethod
    def tools(self) -> tuple[Tool, ...]:
        """Tools used by this skill."""
        ...

    @abstractmethod
    async def execute(self, input: InputT, context: SkillContext) -> SkillResult:
        """Execute the skill with validated input and context."""
        ...
