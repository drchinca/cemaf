# CEMAF Architectural Improvements

**Analysis Date**: 2024-12-27
**Framework**: Context Engineering Multi-Agent Framework (Protocol-First)

## Executive Summary

CEMAF is designed as a **protocol-first framework** for context engineering management. While the architecture is generally well-designed, several modules need standardization to fully embrace the protocol-based dependency injection pattern. This document identifies modules requiring improvement for better encapsulation, standardization, and dependency injection.

---

## Core Principles (From Documentation)

1. **Protocol-Based**: All components use Python `Protocol`s for maximum flexibility
2. **Dependency Injection**: Components receive dependencies via constructor, not direct instantiation
3. **Pluggability**: Swap implementations without changing code
4. **Immutability**: State managed through immutable objects
5. **Testability**: Mock-friendly design

---

## Critical Issues

### 🔴 Priority 1: Direct Instantiation of Dependencies

#### Issue: Context Compiler Module

**Location**: `cemaf/src/cemaf/context/compiler.py`

**Problem**:

```python
class ContextCompiler(ABC):
    def __init__(
        self,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        self._estimator = token_estimator or SimpleTokenEstimator()  # ❌ Direct instantiation
```

**Impact**:

- Violates dependency injection principle
- Makes testing harder (can't easily mock)
- Creates hidden dependencies

**Fix**:

```python
class ContextCompiler(ABC):
    def __init__(
        self,
        token_estimator: TokenEstimator,  # ✅ Required, no default
    ) -> None:
        self._estimator = token_estimator
```

**Recommendation**: Remove all default instantiations. Require dependencies via constructor.

---

#### Issue: Advanced Context Compiler

**Location**: `cemaf/src/cemaf/context/advanced_compiler.py`

**Problem**:

```python
class AdvancedContextCompiler(PriorityContextCompiler):  # ❌ Inherits from concrete class
    def __init__(
        self,
        llm_client: LLMClient,
        token_estimator: TokenEstimator | None = None,  # ❌ Optional with default
    ) -> None:
        super().__init__(token_estimator)  # ❌ Passes None to parent
```

**Impact**:

- Tight coupling to concrete implementation
- Violates Liskov Substitution Principle
- Hard to test in isolation

**Fix**:

```python
class AdvancedContextCompiler(ContextCompiler):  # ✅ Inherit from protocol/ABC
    def __init__(
        self,
        llm_client: LLMClient,
        token_estimator: TokenEstimator,  # ✅ Required
    ) -> None:
        super().__init__(token_estimator)
        self._llm_client = llm_client
```

**Recommendation**:

1. Make `ContextCompiler` a Protocol instead of ABC
2. Require all dependencies explicitly
3. Use composition over inheritance where possible

---

#### Issue: InMemoryVectorStore

**Location**: `cemaf/src/cemaf/retrieval/memory_store.py`

**Problem**:

```python
class InMemoryVectorStore:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider or MockEmbeddingProvider()  # ❌ Direct instantiation
```

**Impact**:

- Production code shouldn't depend on mock implementations
- Violates dependency injection
- Makes it impossible to use without embedding provider

**Fix**:

```python
class InMemoryVectorStore:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,  # ✅ Required
    ) -> None:
        self._embedding_provider = embedding_provider
```

**Recommendation**:

- Remove all `or MockX()` patterns
- Require dependencies explicitly
- Provide factory functions for common setups if needed

---

### 🔴 Priority 1: Missing Protocol Abstractions

#### Issue: ContextCompiler Should Be Protocol

**Location**: `cemaf/src/cemaf/context/compiler.py`

**Current**:

```python
class ContextCompiler(ABC):  # ❌ Abstract base class
    @abstractmethod
    async def compile(...) -> CompiledContext:
        ...
```

**Problem**: ABC requires inheritance, Protocol allows structural typing

**Fix**:

```python
@runtime_checkable
class ContextCompiler(Protocol):  # ✅ Protocol for structural typing
    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        ...
```

**Recommendation**:

- Convert all ABCs to Protocols where possible
- Use `@runtime_checkable` for runtime checks
- Allows duck typing and better testability

---

#### Issue: Missing Checkpointer Protocol

**Location**: `cemaf/src/cemaf/orchestration/checkpointer.py`

**Problem**: `DAGExecutor` uses checkpointer but no protocol exists

**Current**:

```python
# No protocol defined, concrete implementation only
class InMemoryCheckpointer:
    ...
```

**Fix**:

```python
@runtime_checkable
class Checkpointer(Protocol):
    async def save_checkpoint(
        self,
        run_id: RunID,
        context: Context,
        node_results: tuple[NodeResult, ...],
    ) -> None:
        ...

    async def load_checkpoint(
        self,
        run_id: RunID,
    ) -> Checkpoint | None:
        ...
```

**Recommendation**:

- Define protocol before implementation
- Allows swapping implementations (Redis, Postgres, etc.)

---

### 🟡 Priority 2: Inconsistent Dependency Patterns

#### Issue: DAGExecutor Optional Dependencies

**Location**: `cemaf/src/cemaf/orchestration/executor.py`

**Current**:

```python
class DAGExecutor:
    def __init__(
        self,
        node_executor: NodeExecutor,
        max_parallel: int = MAX_PARALLEL_NODES,
        run_logger: RunLogger | None = None,  # ❌ Optional
        event_bus: EventBus | None = None,     # ❌ Optional
        moderation_pipeline: ModerationPipeline | None = None,  # ❌ Optional
    ) -> None:
```

**Problem**:

- Optional dependencies create "maybe" behavior
- Hard to know what's actually being used
- Makes testing harder

**Recommendation**:

```python
@dataclass
class DAGExecutorConfig:
    """Configuration for DAG executor."""
    max_parallel: int = MAX_PARALLEL_NODES
    run_logger: RunLogger | None = None
    event_bus: EventBus | None = None
    moderation_pipeline: ModerationPipeline | None = None

class DAGExecutor:
    def __init__(
        self,
        node_executor: NodeExecutor,
        config: DAGExecutorConfig | None = None,
    ) -> None:
        self._node_executor = node_executor
        self._config = config or DAGExecutorConfig()
```

**Benefits**:

- Clear configuration object
- Easier to extend
- Better documentation

---

#### Issue: Replayer Takes Concrete Types

**Location**: `cemaf/src/cemaf/replay/replayer.py`

**Current**:

```python
class Replayer:
    def __init__(
        self,
        record: RunRecord,  # ✅ Good - immutable data
        mock_tools: dict[str, JSON] | None = None,  # ❌ Should be protocol
        tool_executors: dict[str, Callable[..., Any]] | None = None,  # ❌ Should be protocol
    ) -> None:
```

**Problem**:

- `Callable` is too generic
- No protocol for tool execution
- Hard to test

**Fix**:

```python
@runtime_checkable
class ToolExecutor(Protocol):
    """Protocol for executing tools during replay."""
    async def execute(
        self,
        tool_id: str,
        arguments: JSON,
    ) -> JSON:
        ...

class Replayer:
    def __init__(
        self,
        record: RunRecord,
        tool_executor: ToolExecutor | None = None,  # ✅ Protocol
    ) -> None:
```

---

### 🟡 Priority 2: Missing Factory Functions

#### Issue: No Standardized Factories

**Problem**: Users must know which concrete classes to instantiate

**Recommendation**: Add factory functions for common setups

```python
# cemaf/src/cemaf/context/factories.py
def create_context_compiler(
    token_estimator: TokenEstimator | None = None,
) -> ContextCompiler:
    """Create a standard context compiler."""
    estimator = token_estimator or SimpleTokenEstimator()
    return PriorityContextCompiler(token_estimator=estimator)

def create_advanced_compiler(
    llm_client: LLMClient,
    token_estimator: TokenEstimator | None = None,
) -> ContextCompiler:
    """Create an advanced compiler with summarization."""
    estimator = token_estimator or SimpleTokenEstimator()
    return AdvancedContextCompiler(
        llm_client=llm_client,
        token_estimator=estimator,
    )
```

**Benefits**:

- Hides implementation details
- Provides sensible defaults
- Easy migration path

---

### 🟢 Priority 3: Encapsulation Improvements

#### Issue: Public Attributes in Executors

**Location**: `cemaf/src/cemaf/orchestration/executor.py`

**Current**: Internal state exposed via `self._route_choices`, `self._correlation_id`

**Recommendation**:

- Use private attributes consistently
- Provide read-only properties if needed
- Document public API clearly

---

#### Issue: Missing Builder Pattern for Complex Objects

**Problem**: Some objects have many optional parameters

**Example**: `DAGExecutor` has 5+ optional parameters

**Recommendation**: Use builder pattern for complex configuration

```python
@dataclass
class DAGExecutorBuilder:
    """Builder for DAGExecutor configuration."""
    node_executor: NodeExecutor
    max_parallel: int = MAX_PARALLEL_NODES
    run_logger: RunLogger | None = None
    event_bus: EventBus | None = None
    moderation_pipeline: ModerationPipeline | None = None

    def with_run_logger(self, logger: RunLogger) -> DAGExecutorBuilder:
        self.run_logger = logger
        return self

    def with_event_bus(self, bus: EventBus) -> DAGExecutorBuilder:
        self.event_bus = bus
        return self

    def build(self) -> DAGExecutor:
        return DAGExecutor(
            node_executor=self.node_executor,
            max_parallel=self.max_parallel,
            run_logger=self.run_logger,
            event_bus=self.event_bus,
            moderation_pipeline=self.moderation_pipeline,
        )
```

---

## Module-by-Module Recommendations

### ✅ Well-Designed Modules (Examples to Follow)

1. **`cemaf/llm/protocols.py`**: Excellent protocol-based design

   - `LLMClient` is a Protocol
   - All implementations are separate
   - No direct instantiation

2. **`cemaf/tools/base.py`**: Good abstraction

   - `Tool` is ABC (could be Protocol)
   - Clear separation of concerns

3. **`cemaf/memory/base.py`**: Good protocol usage
   - `MemoryStore` is ABC with hooks
   - Clear interface

---

### 🔧 Modules Needing Improvement

#### 1. Context Module (`cemaf/context/`)

**Issues**:

- `ContextCompiler` should be Protocol, not ABC
- `SimpleTokenEstimator` instantiated directly
- `AdvancedContextCompiler` inherits from concrete class

**Actions**:

1. Convert `ContextCompiler` to Protocol
2. Require `TokenEstimator` in constructor (no defaults)
3. Make `AdvancedContextCompiler` implement protocol directly
4. Add factory functions for common setups

---

#### 2. Orchestration Module (`cemaf/orchestration/`)

**Issues**:

- Missing `Checkpointer` protocol
- `DAGExecutor` has too many optional parameters
- Internal state management could be cleaner

**Actions**:

1. Define `Checkpointer` protocol
2. Create `DAGExecutorConfig` dataclass
3. Use builder pattern for complex setup
4. Document public API clearly

---

#### 3. Retrieval Module (`cemaf/retrieval/`)

**Issues**:

- `InMemoryVectorStore` creates `MockEmbeddingProvider` directly
- No factory for common setups

**Actions**:

1. Require `EmbeddingProvider` in constructor
2. Add factory function: `create_in_memory_store(embedding_provider)`
3. Document that `MockEmbeddingProvider` is for testing only

---

#### 4. Replay Module (`cemaf/replay/`)

**Issues**:

- `Replayer` uses `Callable` instead of protocol
- No clear interface for tool execution

**Actions**:

1. Define `ToolExecutor` protocol
2. Update `Replayer` to use protocol
3. Provide default implementations

---

#### 5. Observability Module (`cemaf/observability/`)

**Issues**:

- `SimpleLogger` doesn't implement `Logger` protocol
- Mix of ABC and concrete classes

**Actions**:

1. Ensure all implementations implement protocols
2. Convert ABCs to Protocols where possible
3. Add factory functions

---

## Standardization Checklist

### Protocol Design

- [ ] All major components have Protocol definitions
- [ ] Protocols use `@runtime_checkable` for runtime checks
- [ ] No ABCs where Protocols would work better
- [ ] Protocols are in separate `protocols.py` files

### Dependency Injection

- [ ] No direct instantiation of dependencies (`or MockX()`)
- [ ] All dependencies passed via constructor
- [ ] No optional dependencies with defaults (use factory functions)
- [ ] Clear separation between protocol and implementation

### Factory Functions

- [ ] Common setups have factory functions
- [ ] Factories provide sensible defaults
- [ ] Factories are in `factories.py` or `__init__.py`
- [ ] Factories documented with examples

### Configuration

- [ ] Complex objects use config dataclasses
- [ ] Builder pattern for very complex objects
- [ ] Configuration is immutable (frozen dataclass)
- [ ] Clear defaults documented

### Testing

- [ ] All protocols have mock implementations
- [ ] Mocks are in `mock.py` files
- [ ] Mocks are clearly marked as testing-only
- [ ] Integration tests use real implementations

---

## Migration Strategy

### Phase 1: Critical Fixes (Week 1)

1. Fix `ContextCompiler` direct instantiation
2. Fix `InMemoryVectorStore` direct instantiation
3. Convert `ContextCompiler` ABC to Protocol

### Phase 2: Protocol Standardization (Week 2)

1. Define `Checkpointer` protocol
2. Define `ToolExecutor` protocol
3. Convert remaining ABCs to Protocols

### Phase 3: Factory Functions (Week 3)

1. Add factory functions for common setups
2. Update documentation with factory examples
3. Deprecate direct instantiation patterns

### Phase 4: Configuration Objects (Week 4)

1. Create config dataclasses for complex objects
2. Add builder patterns where needed
3. Update all examples

---

## Examples of Improved Code

### Before (Current)

```python
# ❌ Direct instantiation
compiler = PriorityContextCompiler()  # Creates SimpleTokenEstimator internally

# ❌ Optional with default
store = InMemoryVectorStore()  # Creates MockEmbeddingProvider internally

# ❌ Too many optional parameters
executor = DAGExecutor(
    node_executor=my_executor,
    run_logger=logger,  # Optional
    event_bus=bus,      # Optional
    moderation_pipeline=pipeline,  # Optional
)
```

### After (Improved)

```python
# ✅ Explicit dependencies
estimator = SimpleTokenEstimator()
compiler = PriorityContextCompiler(token_estimator=estimator)

# ✅ Or use factory
compiler = create_context_compiler()  # Factory provides default

# ✅ Explicit dependencies
embedding_provider = OpenAIEmbeddingProvider()
store = InMemoryVectorStore(embedding_provider=embedding_provider)

# ✅ Configuration object
config = DAGExecutorConfig(
    run_logger=logger,
    event_bus=bus,
    moderation_pipeline=pipeline,
)
executor = DAGExecutor(
    node_executor=my_executor,
    config=config,
)
```

---

## Conclusion

CEMAF is well-architected but needs standardization to fully embrace the protocol-first philosophy. The main improvements needed are:

1. **Remove all direct instantiation** of dependencies
2. **Convert ABCs to Protocols** where possible
3. **Require explicit dependencies** via constructor
4. **Add factory functions** for common setups
5. **Use configuration objects** for complex initialization

These changes will make CEMAF more:

- **Testable**: Easy to mock dependencies
- **Pluggable**: Swap implementations without code changes
- **Maintainable**: Clear dependencies and interfaces
- **Documented**: Factory functions show common patterns

---

## References

- [CEMAF Architecture Docs](docs/architecture.md)
- [CEMAF Integration Guide](docs/integration.md)
- [Python Protocols Documentation](https://docs.python.org/3/library/typing.html#typing.Protocol)
