# Protocol-Based Architecture Guide

CEMAF is built on **protocol-based design** - a pattern that enables loose coupling, standalone module usage, and easy extensibility. This guide explains how to understand, use, and extend CEMAF's protocol-based architecture.

## Core Principle

**CEMAF provides protocols (interfaces) and default implementations. You can use the defaults OR replace them with your own implementations.**

## What Are Protocols?

Protocols in CEMAF are Python `Protocol` types (structural typing) that define **what** a component must do, not **how** it does it.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    """Protocol defining what a Tool must provide."""

    @property
    def id(self) -> ToolID:
        """Unique identifier."""
        ...

    @property
    def schema(self) -> ToolSchema:
        """JSON schema for parameters."""
        ...

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool."""
        ...
```

**Key Point**: Any class that implements these methods is automatically compatible - no inheritance required!

## Protocol vs Implementation

### Protocol (Interface)
- Defines **what** must be provided
- Located in `cemaf.{module}.protocols`
- Example: `Tool`, `Skill`, `Agent`, `ContextCompiler`

### Default Implementation
- Provides **how** it works
- Located in `cemaf.{module}.base` or `cemaf.{module}`
- Example: `Tool` (ABC), `PriorityContextCompiler`, `InMemoryRunLogger`

### Your Implementation
- You can create your own
- Just needs to match the protocol
- No registration needed - structural typing!

## Using Modules Standalone

Every CEMAF module can be used independently:

### Example 1: Use Only Context Management

```python
from cemaf.context import Context, ContextPatch, PatchSource

# Use context without any other modules
ctx = Context(data={"user": "Alice"})
patch = ContextPatch.set(
    path="user.preferences",
    value={"theme": "dark"},
    source=PatchSource.USER,
)
new_ctx = ctx.apply(patch)
```

### Example 2: Use Only Tools

```python
from cemaf.tools.protocols import Tool
from cemaf.core.result import Result

class MyTool:
    @property
    def id(self):
        return ToolID("my_tool")

    @property
    def schema(self):
        return ToolSchema(name="my_tool", ...)

    async def execute(self, **kwargs):
        return Result.ok("done")

# Works standalone - no other CEMAF modules needed
tool = MyTool()
result = await tool.execute(x=1)
```

### Example 3: Use Only RLM

```python
from cemaf.rlm import create_rlm_tool
from cemaf.llm.mock import MockLLMClient

# RLM works with any LLM client (protocol-based)
llm = MockLLMClient()
rlm = create_rlm_tool(llm)

# Use RLM independently
result = await rlm.execute(
    instruction="Find key points",
    content=large_document,
)
```

## Extending CEMAF

### Pattern 1: Replace Default Implementation

```python
from cemaf.context.protocols import ContextCompiler
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import CompiledContext

class MyCustomCompiler:
    """Custom compiler that implements the protocol."""

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        # Your custom logic here
        return CompiledContext(...)

# Use your compiler anywhere a ContextCompiler is expected
compiler: ContextCompiler = MyCustomCompiler()
```

### Pattern 2: Wrap Existing Implementation

```python
from cemaf.context.compiler import PriorityContextCompiler

class CachedCompiler:
    """Wrapper that adds caching to existing compiler."""

    def __init__(self, base_compiler: ContextCompiler):
        self._base = base_compiler
        self._cache = {}

    async def compile(self, *args, **kwargs):
        cache_key = hash((args, tuple(kwargs.items())))
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await self._base.compile(*args, **kwargs)
        self._cache[cache_key] = result
        return result

# Wrap default implementation
base = PriorityContextCompiler(estimator)
cached = CachedCompiler(base)
```

### Pattern 3: Implement Protocol from Scratch

```python
from cemaf.tools.protocols import Tool

class ExternalAPITool:
    """Tool that wraps external API - no CEMAF dependencies."""

    def __init__(self, api_client):
        self._api = api_client

    @property
    def id(self):
        return ToolID("external_api")

    @property
    def schema(self):
        return ToolSchema(...)

    async def execute(self, **kwargs):
        # Call external API
        response = await self._api.call(**kwargs)
        return Result.ok(response)

# Automatically compatible with CEMAF
tool: Tool = ExternalAPITool(my_api_client)
```

## Protocol Discovery

### Finding Protocols

1. **Check `protocols.py`**: Each module has `cemaf.{module}.protocols`
2. **Look for `@runtime_checkable`**: Marks protocols
3. **Check module `__init__.py`**: Protocols are exported

### Protocol Documentation

Each protocol includes:
- **Purpose**: What it's for
- **Extension Point**: How to extend it
- **Example**: Usage example
- **Best Practices**: Implementation guidelines

## Integration Patterns (Not Code!)

CEMAF documents **patterns** for integration, not hard-coded integrations:

### Pattern: Context + Observability

**Pattern**: Context changes create patches, patches can be logged

**Implementation Options**:
1. Use default: `DAGExecutor` automatically logs patches
2. Custom: Create your own logger that implements `RunLogger` protocol
3. None: Don't use logging at all

### Pattern: Tools + Moderation

**Pattern**: Tools can check inputs/outputs with moderation

**Implementation Options**:
1. Wrap tool execution with moderation pipeline
2. Create moderation-aware tool wrapper
3. Skip moderation entirely

### Pattern: RLM + Compiler

**Pattern**: RLM uses compiler for budget enforcement

**Implementation Options**:
1. Use default: `PriorityContextCompiler`
2. Use advanced: `AdvancedContextCompiler` (if you have LLM)
3. Custom: Your own compiler implementing `ContextCompiler` protocol

## Default Implementations

CEMAF provides working defaults for everything:

| Module | Default Implementation | Location |
|--------|----------------------|----------|
| Tools | `Tool` (ABC) | `cemaf.tools.base` |
| Skills | `Skill` (ABC) | `cemaf.skills.base` |
| Agents | `Agent` (ABC) | `cemaf.agents.base` |
| Context Compiler | `PriorityContextCompiler` | `cemaf.context.compiler` |
| LLM Client | `MockLLMClient` (for testing) | `cemaf.llm.mock` |
| Memory Store | `InMemoryMemoryStore` | `cemaf.memory.base` |
| Run Logger | `InMemoryRunLogger` | `cemaf.observability.simple` |
| Vector Store | `InMemoryVectorStore` | `cemaf.retrieval.memory_store` |

**All defaults work out of the box!**

## Factory Functions

Factory functions provide convenient ways to create components with sensible defaults:

```python
# Factory with defaults
from cemaf.rlm import create_rlm_tool
rlm = create_rlm_tool(llm_client)

# Or create manually with your own components
from cemaf.rlm import DivideAndConquerQueryEngine, FixedSizeChunkingStrategy
from cemaf.context.compiler import MyCustomCompiler

engine = DivideAndConquerQueryEngine(
    llm=llm_client,
    compiler=MyCustomCompiler(),  # Your custom compiler!
    max_depth=3,
)
```

## Best Practices

### 1. Use Protocols in Function Signatures

```python
# ✅ Good: Accepts any Tool implementation
def use_tool(tool: Tool) -> Result:
    return await tool.execute(...)

# ❌ Bad: Tied to specific implementation
def use_tool(tool: PriorityContextCompiler) -> Result:
    ...
```

### 2. Dependency Injection

```python
# ✅ Good: Accept protocol, inject implementation
class MyAgent:
    def __init__(self, memory_store: MemoryStore):
        self._memory = memory_store

# ❌ Bad: Hard-coded dependency
class MyAgent:
    def __init__(self):
        self._memory = InMemoryMemoryStore()  # Can't replace!
```

### 3. Check Protocol Compatibility

```python
from cemaf.tools.protocols import Tool

tool = MyCustomTool()
assert isinstance(tool, Tool)  # Runtime check
```

### 4. Document Your Extensions

```python
class MyCustomCompiler:
    """
    Custom compiler that implements ContextCompiler protocol.

    Extends PriorityContextCompiler with semantic relevance scoring.
    """
    ...
```

## Common Patterns

### Pattern: Adapter

Wrap external systems to match CEMAF protocols:

```python
class ExternalSystemAdapter:
    """Adapts external system to CEMAF Tool protocol."""
    ...
```

### Pattern: Decorator

Add functionality to existing implementations:

```python
class CachedTool:
    """Adds caching to any Tool."""
    ...
```

### Pattern: Strategy

Swap implementations based on context:

```python
compiler = AdvancedContextCompiler(...) if use_llm else PriorityContextCompiler(...)
```

## Testing Your Extensions

```python
def test_my_custom_tool():
    tool = MyCustomTool()

    # Verify protocol compliance
    assert isinstance(tool, Tool)

    # Test functionality
    result = await tool.execute(x=1)
    assert result.success
```

## Summary

1. **Protocols define interfaces** - located in `protocols.py`
2. **Defaults provide implementations** - use them or replace them
3. **Modules work standalone** - no forced dependencies
4. **Structural typing** - no inheritance required
5. **Patterns, not code** - integration is documented, not hard-coded
6. **Extensible by design** - implement protocols to extend

## Related Documentation

- [Architecture](architecture.md) - System design overview
- [Module Interconnections](module_interconnections.md) - Integration patterns
- [Integration Guide](integration.md) - External framework integration
- [Module Reference](module_reference.md) - API reference
