# CEMAF Protocol-First Architecture Refactoring Plan

## Executive Summary

**Goal**: Refactor CEMAF to fully embrace protocol-first architecture with dependency injection, eliminating direct instantiation patterns and standardizing configuration across all modules.

**Scope**: Comprehensive refactoring (all priorities from ARCHITECTURAL_IMPROVEMENTS.md)
- Priority 1: Remove direct instantiation, convert ABCs to Protocols
- Priority 2: Add factory functions, configuration objects
- Priority 3: Improve encapsulation, add builder patterns

**Breaking Changes**: Acceptable - no backward compatibility required

**Motivation**: Improve pluggability and code clarity

**Duration**: 3-4 weeks with validation checkpoints

---

## Current State Analysis

### Critical Issues Found

**Context Module** (`src/cemaf/context/`):
- ✗ `ContextCompiler` is ABC (should be Protocol)
- ✗ Direct instantiation: `token_estimator or SimpleTokenEstimator()`
- ✗ `AdvancedContextCompiler` inherits from concrete `PriorityContextCompiler`
- ✓ Only one factory exists: `get_estimator()` for TiktokenEstimator

**Orchestration Module** (`src/cemaf/orchestration/`):
- ✓ `Checkpointer` protocol EXISTS (contrary to doc claim)
- ✓ `RunLogger` protocol exists and actively used
- ✗ `DAGExecutor` has 5 parameters (4 optional with None defaults)
- ✗ `EventBus` protocol exists but unused
- ✗ `ModerationPipeline` is concrete class, not protocol

**Retrieval Module** (`src/cemaf/retrieval/`):
- ✗ `InMemoryVectorStore` uses `embedding_provider or MockEmbeddingProvider()`
- ✗ `HybridRetriever` uses `config or RetrievalConfig()`
- ✓ `EmbeddingProvider` is already a Protocol

**Replay Module** (`src/cemaf/replay/`):
- ✗ `Replayer` uses `Callable[..., Any]` (should be ToolExecutor protocol)
- ✗ Has `mock_tools or {}` and `tool_executors or {}` patterns

---

## Implementation Strategy

### Phase 1: Protocol Definitions (Week 1, Days 1-2)
**No breaking changes yet - foundation only**

#### 1.1 Convert ABCs to Protocols

**File**: `src/cemaf/context/compiler.py`

```python
# Convert ContextCompiler from ABC to Protocol
@runtime_checkable
class ContextCompiler(Protocol):
    """Protocol for context compilation strategies."""

    async def compile(
        self,
        artifacts: tuple[tuple[str, str], ...],
        memories: tuple[tuple[str, str], ...],
        budget: TokenBudget,
        priorities: dict[str, int] | None = None,
    ) -> CompiledContext:
        ...
```

**Impact**: Enables duck typing, maximum flexibility for custom implementations

#### 1.2 Create Missing Protocols

**New File**: `src/cemaf/replay/protocols.py`

```python
@runtime_checkable
class ToolExecutor(Protocol):
    """Protocol for executing tools during replay."""

    async def execute(self, tool_id: str, **kwargs: Any) -> Any:
        """Execute a tool with given arguments."""
        ...
```

**Validation Checkpoint**: `python -m py_compile src/cemaf/**/*.py`

---

### Phase 2: Configuration Objects (Week 1, Days 3-4)

#### 2.1 Add Configuration Dataclasses

**File**: `src/cemaf/orchestration/executor.py`

```python
class ExecutorConfig(BaseModel):
    """Configuration for DAGExecutor."""
    model_config = {"frozen": True}

    max_parallel: int = Field(default=10, description="Max parallel nodes")
    enable_logging: bool = Field(default=True)
    enable_events: bool = Field(default=True)
    enable_moderation: bool = Field(default=False)
```

**File**: `src/cemaf/context/compiler.py`

```python
class AdvancedCompilerConfig(BaseModel):
    """Configuration for AdvancedContextCompiler."""
    model_config = {"frozen": True}

    target_summary_tokens: int = Field(default=50)
    max_summarization_retries: int = Field(default=3)
    fallback_on_error: bool = Field(default=True)
```

**Validation Checkpoint**: `pytest tests/unit/test_configs.py -v` (new test file)

---

### Phase 3: Factory Functions (Week 1, Day 5 - Week 2, Day 1)

#### 3.1 Create Factory Modules

**New File**: `src/cemaf/context/factories.py`

```python
def create_priority_compiler(
    token_estimator: TokenEstimator | None = None,
    chars_per_token: float = 4.0,
) -> PriorityContextCompiler:
    """Factory for PriorityContextCompiler with defaults."""
    estimator = token_estimator or SimpleTokenEstimator(chars_per_token)
    return PriorityContextCompiler(estimator)

def create_advanced_compiler(
    llm_client: LLMClient,
    token_estimator: TokenEstimator | None = None,
    base_compiler: ContextCompiler | None = None,
    config: AdvancedCompilerConfig | None = None,
) -> AdvancedContextCompiler:
    """Factory for AdvancedContextCompiler."""
    estimator = token_estimator or SimpleTokenEstimator()
    base = base_compiler or create_priority_compiler(estimator)
    cfg = config or AdvancedCompilerConfig()
    return AdvancedContextCompiler(base, llm_client, estimator, cfg)
```

**New File**: `src/cemaf/retrieval/factories.py`
**New File**: `src/cemaf/orchestration/factories.py`
**New File**: `src/cemaf/replay/factories.py`

**Validation Checkpoint**: `pytest tests/unit/test_factories.py -v` (new test file)

---

### Phase 4: Eliminate Direct Instantiation (Week 2, Days 2-4)
**BREAKING CHANGES BEGIN**

#### 4.1 Context Module

**File**: `src/cemaf/context/compiler.py`

**Before**:
```python
def __init__(self, token_estimator: TokenEstimator | None = None) -> None:
    self._estimator = token_estimator or SimpleTokenEstimator()  # ❌
```

**After**:
```python
def __init__(self, token_estimator: TokenEstimator) -> None:
    self._estimator = token_estimator  # ✅
```

#### 4.2 Retrieval Module

**File**: `src/cemaf/retrieval/memory_store.py`

**Before**:
```python
def __init__(self, embedding_provider: EmbeddingProvider | None = None) -> None:
    self._embedding_provider = embedding_provider or MockEmbeddingProvider()  # ❌
```

**After**:
```python
def __init__(self, embedding_provider: EmbeddingProvider) -> None:
    self._embedding_provider = embedding_provider  # ✅
```

#### 4.3 Fix AdvancedContextCompiler Inheritance

**File**: `src/cemaf/context/advanced_compiler.py`

**Before** (inheritance):
```python
class AdvancedContextCompiler(PriorityContextCompiler):  # ❌ Tight coupling
    def __init__(self, llm_client, token_estimator=None):
        super().__init__(token_estimator)
```

**After** (composition):
```python
class AdvancedContextCompiler:  # ✅ Implements protocol via duck typing
    def __init__(
        self,
        base_compiler: ContextCompiler,
        llm_client: LLMClient,
        token_estimator: TokenEstimator,
        config: AdvancedCompilerConfig,
    ):
        self._base_compiler = base_compiler
        self._llm_client = llm_client
        self._estimator = token_estimator
        self._config = config
```

**Validation Checkpoint**: `pytest tests/unit/test_context_compiler.py -v`

---

### Phase 5: Update Test Infrastructure (Week 2, Day 5)

#### 5.1 Update Central Fixtures

**File**: `tests/conftest.py` (CRITICAL - update FIRST)

**Before**:
```python
@pytest.fixture
def context_compiler() -> PriorityContextCompiler:
    return PriorityContextCompiler()  # Uses default
```

**After**:
```python
@pytest.fixture
def token_estimator() -> SimpleTokenEstimator:
    return SimpleTokenEstimator()

@pytest.fixture
def context_compiler(token_estimator: SimpleTokenEstimator) -> PriorityContextCompiler:
    return create_priority_compiler(token_estimator=token_estimator)
```

**Impact**: Most individual tests won't need changes if fixtures updated correctly

#### 5.2 Add New Test Files

- `tests/unit/test_protocols.py` - Protocol compliance tests
- `tests/unit/test_factories.py` - Factory function tests
- `tests/unit/test_configs.py` - Configuration validation tests

**Validation Checkpoint**: `pytest tests/ -v --cov=src/cemaf`

---

### Phase 6: Update Examples & Documentation (Week 3)

#### 6.1 Update Existing Example

**File**: `examples/retrieval_dag_example.py`

Add factory usage demonstration:
```python
from cemaf.retrieval.factories import create_memory_vector_store
from cemaf.context.factories import create_priority_compiler

# Show factory pattern
vector_store = create_memory_vector_store(dimension=384)
compiler = create_priority_compiler()
```

#### 6.2 Create New Example

**File**: `examples/factory_pattern_example.py`

Demonstrates factory-based initialization for all major components.

#### 6.3 Update Documentation

**Files to Update**:
- `docs/context.md` - Add factory pattern section
- `docs/retrieval.md` - Add configuration section
- `docs/orchestration.md` - Add DAGExecutor config examples
- `docs/architecture.md` - Add DI architecture section
- **NEW**: `docs/migration_guide.md` - Complete before/after migration guide

**Validation Checkpoint**: Run examples, verify output

---

### Phase 7: Module Public APIs (Week 3)

#### 7.1 Update __init__.py Files

**Pattern** (apply to all modules):

```python
# src/cemaf/context/__init__.py
from cemaf.context.compiler import (
    ContextCompiler,  # Protocol
    PriorityContextCompiler,  # Implementation
    # ... other exports
)
from cemaf.context.factories import (
    create_priority_compiler,  # ✅ Recommended way
    create_advanced_compiler,
)

__all__ = [
    # Protocols (for type hints)
    "ContextCompiler",
    "TokenEstimator",
    # Implementations
    "PriorityContextCompiler",
    "AdvancedContextCompiler",
    # Factories (recommended)
    "create_priority_compiler",
    "create_advanced_compiler",
]
```

**Validation Checkpoint**: Import tests pass

---

## Validation Strategy

### Sequential Validation Checkpoints

**Checkpoint 1: Syntax** (after each change)
```bash
python -m py_compile src/cemaf/MODULE_NAME/*.py
```

**Checkpoint 2: Protocol Compliance**
```bash
pytest tests/unit/test_protocols.py -v
```

**Checkpoint 3: Factory Correctness**
```bash
pytest tests/unit/test_factories.py -v
```

**Checkpoint 4: Module Tests**
```bash
pytest tests/unit/MODULE_NAME/ -v
```

**Checkpoint 5: Integration Tests**
```bash
pytest tests/integration/ -v
```

**Checkpoint 6: Full Test Suite**
```bash
pytest tests/ -v --cov=src/cemaf --cov-report=html
# Gate: All 51+ test files pass, coverage >= 90%
```

**Checkpoint 7: Examples Work**
```bash
python examples/retrieval_dag_example.py
python examples/factory_pattern_example.py
```

---

## Migration Order (Minimizes Breakage)

### Week 1: Foundation (No Breaking Changes)
1. Add protocol definitions
2. Add config dataclasses
3. Add factory functions
4. Update test fixtures

### Week 2: Core Refactoring (Breaking Changes)
1. Context module → Update tests
2. Retrieval module → Update tests
3. Orchestration module → Update tests
4. Replay module → Update tests
5. Run integration tests

### Week 3: Polish
1. Update examples
2. Update documentation
3. Write migration guide
4. Final validation

### Week 4: Cleanup
1. Remove old patterns
2. Final test suite run
3. Coverage analysis

---

## Rollback Safety

**Branch Strategy**:
```
main
├── refactor/protocols (Week 1)
├── refactor/core-modules (Week 2, merges protocols)
└── refactor/final (Week 3, merges to main)
```

**Rollback Procedure** (if validation fails):
```bash
# Identify failing module
pytest tests/unit/MODULE/ -v --tb=long > failure.log

# Revert to last working state
git checkout HEAD~1 src/cemaf/MODULE/
git checkout HEAD~1 tests/unit/MODULE/

# Fix in isolation, re-validate
```

---

## Critical Files to Modify

### Highest Priority (Core Architecture)
1. `src/cemaf/context/compiler.py` - ABC → Protocol conversion
2. `src/cemaf/context/advanced_compiler.py` - Inheritance → composition
3. `src/cemaf/retrieval/memory_store.py` - Direct instantiation removal
4. `src/cemaf/orchestration/executor.py` - Config object pattern
5. `tests/conftest.py` - Central fixtures (update FIRST)

### New Files to Create
1. `src/cemaf/context/factories.py` - Context factories
2. `src/cemaf/retrieval/factories.py` - Retrieval factories
3. `src/cemaf/orchestration/factories.py` - Orchestration factories
4. `src/cemaf/replay/factories.py` - Replay factories
5. `src/cemaf/replay/protocols.py` - ToolExecutor protocol
6. `tests/unit/test_protocols.py` - Protocol compliance tests
7. `tests/unit/test_factories.py` - Factory function tests
8. `tests/unit/test_configs.py` - Configuration tests
9. `examples/factory_pattern_example.py` - Factory usage example
10. `docs/migration_guide.md` - Migration documentation

---

## Success Criteria

### Quantitative Metrics
- ✓ All 51+ test files pass
- ✓ Test coverage >= 90% (no degradation)
- ✓ Zero direct instantiation patterns (`or MockX()`)
- ✓ All major components have Protocol definitions
- ✓ All major components have factory functions
- ✓ All examples run without errors

### Qualitative Metrics
- ✓ New developers understand initialization from examples
- ✓ Components can be instantiated with mocks for testing
- ✓ Adding new implementations only requires protocol compliance
- ✓ Configuration is explicit and documented

---

## Expected Benefits

**Pluggability**:
- Swap implementations without code changes
- Add custom providers by implementing protocols
- Test components in isolation with mocks

**Code Clarity**:
- Explicit dependencies via constructors
- Clear configuration objects
- Standardized factory pattern across modules

**Maintainability**:
- Protocol-based contracts
- Composition over inheritance
- Testable by design

---

## Notes

- **Breaking changes are acceptable** per user requirements
- **Checkpointer protocol already exists** (correction to original doc)
- **Focus on fixture-first migration** to minimize test churn
- **Factory functions provide migration path** while maintaining DI benefits
- **Estimate**: 3-4 weeks with proper validation at each step
