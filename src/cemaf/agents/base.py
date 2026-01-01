"""
Agent base classes.

An Agent is:
- Autonomous entity with a goal
- Uses skills to accomplish tasks
- Maintains state/memory
- Can make decisions

## Best Practices

### Using VectorStore and Memory Stores

When skills or agents retrieve from vector stores or memory stores, they should:

1. **Emit context patches** for retrieval results so downstream nodes can reuse them:

    ```python
    # In a skill or agent:
    retrieved_docs = await vector_store.search(query, top_k=5)

    # Patch retrieval results into context
    context = context.set("retrieved_docs", retrieved_docs)
    # Or use ContextPatch explicitly for better provenance tracking
    ```

2. **Store retrieval metadata** (query, timestamp, scores) for debugging:

    ```python
    metadata = {
        "query": query,
        "num_results": len(results),
        "top_score": results[0].score if results else None,
    }
    ```

3. **Use caching** for expensive retrieval operations (see below)

### Resilience Patterns

Use resilience decorators around expensive or flaky operations:

```python
from cemaf.resilience import retry, circuit_breaker

class RetrievalSkill(Skill):
    @retry(max_attempts=3, backoff_factor=1.5)
    @circuit_breaker(failure_threshold=5, recovery_timeout=60)
    async def search_vector_store(self, query: str) -> list[Document]:
        # Expensive retrieval operation
        return await self.vector_store.search(query)
```

### Caching Patterns

Use caching decorators for expensive calls (LLM, retrieval):

```python
from cemaf.cache import cache_result

class AnalysisAgent(Agent):
    @cache_result(ttl=3600)  # Cache for 1 hour
    async def analyze_with_llm(self, text: str) -> AnalysisResult:
        # Expensive LLM call
        return await self.llm.complete(...)

    @cache_result(ttl=600, key_prefix="retrieval")
    async def retrieve_context(self, query: str) -> list[Document]:
        # Expensive retrieval
        return await self.vector_store.search(query)
```

See examples/retrieval_dag_example.py for a complete working example.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from cemaf.core.enums import AgentStatus
from cemaf.core.types import JSON, AgentID
from cemaf.skills.base import Skill, SkillResult

GoalT = TypeVar("GoalT", bound=BaseModel)
ResultT = TypeVar("ResultT")


class AgentState(BaseModel):
    """Mutable state during agent execution."""

    model_config = {"frozen": True}

    status: AgentStatus = AgentStatus.IDLE
    iteration: int = 0
    skill_calls: int = 0
    messages: tuple[JSON, ...] = ()
    working_memory: JSON = Field(default_factory=dict)

    def next(self, **updates: Any) -> AgentState:
        """Create new state with updates."""
        data = self.model_dump()
        data.update(updates)
        return AgentState(**data)


@dataclass(frozen=True)
class AgentResult[ResultT]:
    """Result of agent execution with state trace."""

    success: bool
    output: ResultT | None = None
    error: str | None = None
    final_state: AgentState | None = None
    skill_results: tuple[SkillResult, ...] = ()
    metadata: JSON = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Ensure trace collections remain immutable and replay-safe."""
        object.__setattr__(self, "skill_results", tuple(self.skill_results))

    @classmethod
    def ok(cls, output: ResultT, state: AgentState) -> AgentResult[ResultT]:
        return cls(success=True, output=output, final_state=state)

    @classmethod
    def fail(cls, error: str, state: AgentState | None = None) -> AgentResult[ResultT]:
        return cls(success=False, error=error, final_state=state)


class AgentContext(BaseModel):
    """Isolated context for agent execution."""

    model_config = {"frozen": True}

    run_id: str
    agent_id: str
    parent_agent_id: str | None = None
    depth: int = 0
    global_memory: JSON = Field(default_factory=dict)
    artifacts: JSON = Field(default_factory=dict)


class Agent[GoalT: BaseModel, ResultT](ABC):
    """
    Abstract base class for agents.

    Example:
        class AnalystAgent(Agent[AnalysisGoal, AnalysisResult]):
            def __init__(self, sql_skill: Skill):
                self._sql = sql_skill

            @property
            def id(self) -> AgentID:
                return AgentID("analyst")

            @property
            def skills(self) -> tuple[Skill, ...]:
                return (self._sql,)

            async def run(self, goal: AnalysisGoal, ctx: AgentContext) -> AgentResult:
                state = AgentState()
                result = await self._sql.execute(...)
                if not result.success:
                    return AgentResult.fail(result.error, state)
                return AgentResult.ok(AnalysisResult(data=result.data), state)
    """

    @property
    @abstractmethod
    def id(self) -> AgentID:
        """Unique identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """What this agent does."""
        ...

    @property
    @abstractmethod
    def skills(self) -> tuple[Skill[Any, Any], ...]:
        """Skills available to this agent."""
        ...

    @abstractmethod
    async def run(self, goal: GoalT, context: AgentContext) -> AgentResult[ResultT]:
        """Execute the agent to accomplish a goal."""
        ...
