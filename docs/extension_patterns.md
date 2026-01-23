# Extension Patterns

This guide shows common patterns for extending CEMAF with your own implementations while maintaining protocol compatibility.

## Overview

CEMAF is designed for extension. You can:
- Replace any default implementation
- Wrap existing implementations
- Create completely custom implementations
- Mix and match modules as needed

## Pattern 1: Custom Tool Implementation

### Standalone Tool

```python
from cemaf.tools.protocols import Tool
from cemaf.core.types import ToolID
from cemaf.tools.base import ToolSchema, ToolResult
from cemaf.core.result import Result

class DatabaseQueryTool:
    """Custom tool that queries a database."""

    def __init__(self, db_connection):
        self._db = db_connection

    @property
    def id(self) -> ToolID:
        return ToolID("database_query")

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="database_query",
            description="Execute SQL query on database",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL query"},
                    "params": {"type": "object", "description": "Query parameters"},
                },
                "required": ["query"],
            },
            required=("query",),
        )

    async def execute(self, query: str, params: dict | None = None) -> ToolResult:
        try:
            results = await self._db.execute(query, params or {})
            return Result.ok(results)
        except Exception as e:
            return Result.fail(f"Query failed: {e}")

# Usage - works anywhere a Tool is expected
tool: Tool = DatabaseQueryTool(my_db)
```

### Tool with Moderation (Optional Integration)

```python
from cemaf.moderation.pipeline import ModerationPipeline

class SafeDatabaseQueryTool(DatabaseQueryTool):
    """Database tool with optional moderation."""

    def __init__(self, db_connection, moderation: ModerationPipeline | None = None):
        super().__init__(db_connection)
        self._moderation = moderation

    async def execute(self, query: str, params: dict | None = None) -> ToolResult:
        # Optional pre-flight check
        if self._moderation:
            mod_result = await self._moderation.check_input(query)
            if not mod_result.allowed:
                return Result.fail("Query blocked by moderation")

        result = await super().execute(query, params)

        # Optional post-flight check
        if self._moderation and result.success:
            mod_result = await self._moderation.check_output(str(result.data))
            if not mod_result.allowed:
                return Result.fail("Results blocked by moderation")

        return result
```

## Pattern 2: Custom Context Compiler

### Simple Compiler

```python
from cemaf.context.protocols import ContextCompiler
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext, ContextSource
from cemaf.core.types import TokenCount

class SimpleConcatenationCompiler:
    """Simple compiler that just concatenates all sources."""

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        sources = []
        total_tokens = 0

        # Add all artifacts
        for key, content in artifacts:
            tokens = len(content) // 4  # Simple estimation
            sources.append(ContextSource(
                type="artifact",
                key=key,
                content=content,
                token_count=TokenCount(tokens),
                priority=priorities.get(key, 0) if priorities else 0,
            ))
            total_tokens += tokens

        # Add all memories
        for key, content in memories:
            tokens = len(content) // 4
            sources.append(ContextSource(
                type="memory",
                key=key,
                content=content,
                token_count=TokenCount(tokens),
                priority=-1,
            ))
            total_tokens += tokens

        return CompiledContext(
            sources=tuple(sources),
            total_tokens=total_tokens,
            budget=budget,
        )

# Usage
compiler: ContextCompiler = SimpleConcatenationCompiler()
```

### Compiler with Custom Algorithm

```python
from cemaf.context.algorithm import ContextSelectionAlgorithm, SelectionResult

class SemanticRelevanceAlgorithm:
    """Custom algorithm that uses embeddings for relevance."""

    def __init__(self, embedding_provider):
        self._embeddings = embedding_provider

    def select_sources(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
        query_embedding: list[float] | None = None,
    ) -> SelectionResult:
        # Your semantic selection logic
        # Score sources by relevance to query
        # Select highest scoring that fit budget
        ...

        return SelectionResult(
            selected_sources=selected,
            total_tokens=total,
            selection_method="semantic_relevance",
        )

class SemanticCompiler:
    """Compiler using semantic relevance."""

    def __init__(self, algorithm: SemanticRelevanceAlgorithm):
        self._algorithm = algorithm

    async def compile(self, ...) -> CompiledContext:
        # Use semantic algorithm for selection
        result = self._algorithm.select_sources(sources, budget, query_embedding)
        return CompiledContext(...)
```

## Pattern 3: Custom Memory Store

```python
from cemaf.memory.protocols import MemoryStore
from cemaf.core.enums import MemoryScope

class RedisMemoryStore:
    """Memory store backed by Redis."""

    def __init__(self, redis_client):
        self._redis = redis_client

    async def store(
        self,
        key: str,
        value: str,
        scope: MemoryScope = MemoryScope.CONVERSATION,
        ttl: int | None = None,
    ) -> None:
        redis_key = f"{scope.value}:{key}"
        await self._redis.set(redis_key, value, ex=ttl)

    async def retrieve(self, key: str, scope: MemoryScope = MemoryScope.CONVERSATION) -> str | None:
        redis_key = f"{scope.value}:{key}"
        return await self._redis.get(redis_key)

    async def retrieve_all(self, scope: MemoryScope) -> tuple[tuple[str, str], ...]:
        pattern = f"{scope.value}:*"
        keys = await self._redis.keys(pattern)
        results = []
        for key in keys:
            value = await self._redis.get(key)
            if value:
                results.append((key, value))
        return tuple(results)

    async def delete(self, key: str, scope: MemoryScope = MemoryScope.CONVERSATION) -> None:
        redis_key = f"{scope.value}:{key}"
        await self._redis.delete(redis_key)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        if scope:
            pattern = f"{scope.value}:*"
        else:
            pattern = "*"
        keys = await self._redis.keys(pattern)
        if keys:
            await self._redis.delete(*keys)

# Usage - works anywhere MemoryStore is expected
memory: MemoryStore = RedisMemoryStore(redis_client)
```

## Pattern 4: Custom LLM Client

```python
from cemaf.llm.protocols import LLMClient, Message, LLMResponse
from cemaf.core.result import Result

class CustomLLMClient:
    """Custom LLM client wrapping your API."""

    def __init__(self, api_key: str, model: str = "custom-model"):
        self._api_key = api_key
        self._model = model

    async def complete(
        self,
        messages: list[Message],
        config: dict | None = None,
    ) -> Result[LLMResponse]:
        try:
            # Call your API
            response = await self._call_api(messages, config)

            return Result.ok(LLMResponse(
                content=response["text"],
                model=self._model,
                total_tokens=response.get("tokens", 0),
            ))
        except Exception as e:
            return Result.fail(str(e))

    async def stream(
        self,
        messages: list[Message],
        config: dict | None = None,
    ):
        # Implement streaming
        ...

# Usage
llm: LLMClient = CustomLLMClient(api_key="...")
```

## Pattern 5: Wrapper Pattern

### Add Caching to Any Compiler

```python
from cemaf.context.protocols import ContextCompiler
from functools import lru_cache

class CachedCompiler:
    """Adds caching to any compiler."""

    def __init__(self, base_compiler: ContextCompiler, cache_size: int = 128):
        self._base = base_compiler
        self._cache = {}
        self._cache_size = cache_size

    async def compile(self, *args, **kwargs):
        # Create cache key
        cache_key = self._make_key(args, kwargs)

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Compile and cache
        result = await self._base.compile(*args, **kwargs)

        # Manage cache size
        if len(self._cache) >= self._cache_size:
            # Remove oldest entry
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[cache_key] = result
        return result

    def _make_key(self, args, kwargs):
        # Create deterministic cache key
        return hash((args, tuple(sorted(kwargs.items()))))

# Usage - wrap any compiler
base = PriorityContextCompiler(estimator)
cached = CachedCompiler(base)
```

## Pattern 6: Adapter Pattern

### Adapt External System to CEMAF Protocol

```python
from cemaf.tools.protocols import Tool

class ExternalServiceAdapter:
    """Adapts external service to CEMAF Tool protocol."""

    def __init__(self, external_service):
        self._service = external_service

    @property
    def id(self) -> ToolID:
        return ToolID("external_service")

    @property
    def schema(self) -> ToolSchema:
        # Map external service API to Tool schema
        return ToolSchema(...)

    async def execute(self, **kwargs) -> ToolResult:
        # Translate CEMAF call to external service call
        external_params = self._translate_params(kwargs)
        result = await self._service.call(external_params)
        return self._translate_result(result)

    def _translate_params(self, kwargs):
        # Convert CEMAF format to external format
        ...

    def _translate_result(self, result):
        # Convert external format to CEMAF Result
        ...

# Usage
tool: Tool = ExternalServiceAdapter(external_service)
```

## Pattern 7: Composition Pattern

### Combine Multiple Components

```python
class CompositeAgent:
    """Agent that combines multiple skills."""

    def __init__(
        self,
        research_skill: Skill,
        analysis_skill: Skill,
        writing_skill: Skill,
    ):
        self._research = research_skill
        self._analysis = analysis_skill
        self._writing = writing_skill

    @property
    def id(self) -> AgentID:
        return AgentID("composite_agent")

    async def run(self, goal: Goal, context: AgentContext) -> AgentResult:
        # Use skills in sequence
        research_result = await self._research.execute(goal.query, context)
        if not research_result.success:
            return AgentResult.fail(research_result.error)

        analysis_result = await self._analysis.execute(research_result.data, context)
        if not analysis_result.success:
            return AgentResult.fail(analysis_result.error)

        writing_result = await self._writing.execute(analysis_result.data, context)
        return AgentResult.ok(writing_result.data)
```

## Pattern 8: Strategy Pattern

### Swap Implementations Based on Context

```python
class AdaptiveCompiler:
    """Compiler that switches strategies based on context size."""

    def __init__(
        self,
        small_compiler: ContextCompiler,
        large_compiler: ContextCompiler,
        threshold: int = 10000,
    ):
        self._small = small_compiler
        self._large = large_compiler
        self._threshold = threshold

    async def compile(self, *args, **kwargs):
        # Estimate context size
        total_size = sum(len(c) for _, c in args[0])

        # Choose compiler based on size
        compiler = self._large if total_size > self._threshold else self._small

        return await compiler.compile(*args, **kwargs)
```

## Testing Your Extensions

### Protocol Compliance Tests

```python
def test_custom_tool_protocol_compliance():
    """Verify custom tool implements Tool protocol."""
    tool = MyCustomTool()

    # Runtime check
    assert isinstance(tool, Tool)

    # Verify required properties
    assert hasattr(tool, 'id')
    assert hasattr(tool, 'schema')
    assert hasattr(tool, 'execute')

    # Verify types
    assert isinstance(tool.id, ToolID)
    assert isinstance(tool.schema, ToolSchema)

def test_custom_tool_functionality():
    """Test custom tool works correctly."""
    tool = MyCustomTool()
    result = await tool.execute(x=1)

    assert result.success
    assert result.data is not None
```

## Integration Examples

### Example: Custom Tool in DAG

```python
from cemaf.orchestration import DAG, Node, Edge
from cemaf.orchestration.executor import DAGExecutor

# Your custom tool
custom_tool = MyCustomTool()

# Use in DAG
dag = DAG(name="my_dag")
dag = dag.add_node(Node.tool(id="custom", tool=custom_tool))

# Executor accepts any Tool (protocol-based)
executor = DAGExecutor(node_executor=my_executor)
result = await executor.run(dag, context)
```

### Example: Custom Compiler in RLM

```python
from cemaf.rlm import DivideAndConquerQueryEngine

# Your custom compiler
custom_compiler = MyCustomCompiler()

# Use in RLM engine (accepts any ContextCompiler)
engine = DivideAndConquerQueryEngine(
    llm_client=llm,
    compiler=custom_compiler,  # Your custom compiler!
    max_depth=3,
)
```

## Best Practices

1. **Implement Protocols, Don't Inherit**: Use structural typing
2. **Document Your Extensions**: Explain what makes yours special
3. **Test Protocol Compliance**: Verify `isinstance()` checks pass
4. **Keep Dependencies Minimal**: Don't force CEMAF dependencies
5. **Follow Result Pattern**: Always return `Result`, never raise
6. **Make It Optional**: Allow users to skip your extension

## Summary

- **Protocols define contracts** - implement them to extend
- **Defaults work** - use them or replace them
- **No registration needed** - structural typing handles it
- **Compose freely** - mix CEMAF and custom components
- **Test compliance** - verify protocol implementation

## Related Documentation

- [Protocol Guide](protocol_guide.md) - Understanding protocols
- [Architecture](architecture.md) - System design
- [Module Reference](module_reference.md) - Protocol definitions
