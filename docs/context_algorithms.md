# Context Algorithms

CEMAF's context management goes beyond simple selection. This module provides:

- **Selection Algorithms**: Which sources fit in the budget
- **KV Cache Management**: Reuse computation for local LLMs
- **Semantic Compression**: Task-aware context reduction
- **Prefix Caching**: Shared context across requests

## Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Context Algorithm Stack                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   Sources (10K tokens)                                              │
│         │                                                           │
│         ▼                                                           │
│   ┌─────────────────┐                                               │
│   │ SELECTION       │ ◄── Greedy, Knapsack, Optimal                │
│   │ (Budget: 4K)    │                                               │
│   └─────────────────┘                                               │
│         │                                                           │
│         ▼                                                           │
│   ┌─────────────────┐                                               │
│   │ COMPRESSION     │ ◄── Task-specific distillation               │
│   │ (3K output)     │                                               │
│   └─────────────────┘                                               │
│         │                                                           │
│         ▼                                                           │
│   ┌─────────────────┐                                               │
│   │ KV CACHE        │ ◄── Prefix caching for local LLMs            │
│   │ (Reuse 2K)      │                                               │
│   └─────────────────┘                                               │
│         │                                                           │
│         ▼                                                           │
│   LLM Inference (1K new tokens computed)                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

The `ContextSelectionAlgorithm` protocol enables pluggable selection strategies:

- **Greedy**: Fast, includes highest priority sources first (default)
- **Knapsack**: Optimal priority maximization using dynamic programming
- **Optimal**: Guaranteed optimal solution for small sets
- **Custom**: Engineer-defined algorithms

## Protocol Interface

```python
@runtime_checkable
class ContextSelectionAlgorithm(Protocol):
    def select_sources(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> SelectionResult:
        """
        Select sources that fit within token budget.

        Args:
            sources: All available context sources (may be pre-sorted)
            budget: Token budget constraints

        Returns:
            SelectionResult with selected sources and metadata
        """
        ...
```

## Built-in Algorithms

### GreedySelectionAlgorithm

**Strategy**: Includes highest priority sources first until budget exhausted.

**Characteristics**:
- Time Complexity: O(n)
- Space Complexity: O(n)
- Optimality: Not guaranteed - may miss better combinations
- Best For: Fast selection when priorities are well-calibrated

**Example**:
```python
from cemaf.context.algorithm import GreedySelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

algorithm = GreedySelectionAlgorithm()
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=algorithm,
)
```

### KnapsackSelectionAlgorithm

**Strategy**: Uses 0/1 knapsack dynamic programming to maximize sum of priorities within budget.

**Characteristics**:
- Time Complexity: O(n × budget)
- Space Complexity: O(n × budget)
- Optimality: Optimal for 0/1 knapsack (maximizes priority sum)
- Best For: When you need optimal priority maximization

**Example**:
```python
from cemaf.context.algorithm import KnapsackSelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

algorithm = KnapsackSelectionAlgorithm()
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=algorithm,
)
```

**Note**: For very large budgets (>100K tokens), automatically falls back to greedy for performance.

### OptimalSelectionAlgorithm

**Strategy**: Uses brute force for small sets to find truly optimal solution, falls back to knapsack for larger sets.

**Characteristics**:
- Time Complexity: O(2^n) for brute force, O(n × budget) for fallback
- Space Complexity: O(2^n) for brute force
- Optimality: Guaranteed optimal for small sets (< 20 sources)
- Best For: Small sets where optimality is critical

**Example**:
```python
from cemaf.context.algorithm import OptimalSelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

algorithm = OptimalSelectionAlgorithm(max_sources=20)
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=algorithm,
)
```

## Implementing Custom Algorithms

To implement a custom algorithm, simply conform to the `ContextSelectionAlgorithm` protocol:

```python
from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
    SelectionResult,
)
from cemaf.context.compiler import ContextSource
from cemaf.context.budget import TokenBudget

class MyCustomAlgorithm:
    """Custom algorithm that prioritizes diversity."""

    def select_sources(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> SelectionResult:
        selected: list[ContextSource] = []
        total_tokens = 0
        available_tokens = budget.available_tokens

        # Custom logic: prioritize diverse sources
        seen_types = set()
        for source in sorted(sources, key=lambda s: s.priority, reverse=True):
            if total_tokens + source.token_count <= available_tokens:
                # Prefer sources of different types
                if source.type not in seen_types or len(selected) < 3:
                    selected.append(source)
                    total_tokens += source.token_count
                    seen_types.add(source.type)

        excluded_keys = [s.key for s in sources if s not in selected]

        return SelectionResult(
            selected_sources=tuple(selected),
            total_tokens=total_tokens,
            metadata={
                "selection_method": "custom_diversity",
                "excluded_count": len(excluded_keys),
                "excluded_keys": excluded_keys,
            },
        )

# Use custom algorithm
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=MyCustomAlgorithm(),
)
```

## SelectionResult

The `SelectionResult` dataclass contains:

- `selected_sources`: Tuple of selected `ContextSource` objects
- `total_tokens`: Total tokens used
- `metadata`: Algorithm-specific information (excluded count, method, etc.)

**Properties**:
- `excluded_count`: Number of excluded sources
- `excluded_keys`: Keys of excluded sources
- `selection_method`: Algorithm method name

## Factory Functions

CEMAF provides factory functions for common setups:

```python
from cemaf.context.factories import (
    create_greedy_compiler,
    create_knapsack_compiler,
    create_optimal_compiler,
)

# Greedy (default)
compiler = create_greedy_compiler()

# Knapsack
compiler = create_knapsack_compiler()

# Optimal
compiler = create_optimal_compiler(max_sources=15)
```

## Algorithm Comparison

| Algorithm | Speed | Optimality | Best For |
|-----------|-------|------------|----------|
| Greedy | Fast (O(n)) | Approximate | General use, well-calibrated priorities |
| Knapsack | Medium (O(n×budget)) | Optimal (priority sum) | Need optimal priority maximization |
| Optimal | Slow (O(2^n)) | Guaranteed optimal | Small sets (< 20 sources) |

## Best Practices

1. **Choose the right algorithm**: Greedy for speed, Knapsack for optimality, Optimal for small sets
2. **Calibrate priorities**: Ensure priorities accurately reflect importance
3. **Monitor metadata**: Check `SelectionResult.metadata` for algorithm insights
4. **Test custom algorithms**: Verify they respect budget constraints
5. **Consider performance**: For large budgets or many sources, prefer greedy

## Advanced Usage

### Using with AdvancedContextCompiler

The `AdvancedContextCompiler` also supports algorithm selection:

```python
from cemaf.context.advanced_compiler import AdvancedContextCompiler
from cemaf.context.algorithm import KnapsackSelectionAlgorithm

compiler = AdvancedContextCompiler(
    llm_client=llm_client,
    token_estimator=estimator,
    algorithm=KnapsackSelectionAlgorithm(),  # Use knapsack before summarization
)
```

### Algorithm Metadata

Algorithms can provide metadata about their selection process:

```python
result = algorithm.select_sources(sources, budget)

# Access metadata
print(f"Method: {result.selection_method}")
print(f"Excluded: {result.excluded_count}")
print(f"Max priority sum: {result.metadata.get('max_priority_sum')}")
print(f"Guaranteed optimal: {result.metadata.get('guaranteed_optimal', False)}")
```

## Examples

See `cemaf/examples/retrieval_dag_example.py` for a complete example demonstrating:
- Using different algorithms
- Comparing results
- Showing algorithm metadata
- Custom algorithm implementation

---

## KV Cache Management

For local LLMs (Llama.cpp, vLLM, Ollama), KV cache reuse is the difference between 50ms and 500ms latency. CEMAF provides prefix-aware context construction.

### The KV Cache Problem

```
Without KV Cache Awareness:
┌─────────────────────────────────────────────────────────────────────┐
│ Request 1: [System Prompt] [History] [Tool Results] [User Query]   │
│            ▲──────────────────────────────────────────────────────▲ │
│            Compute KV for ALL tokens                               │
│                                                                     │
│ Request 2: [System Prompt] [History] [Tool Results'] [User Query'] │
│            ▲──────────────────────────────────────────────────────▲ │
│            Recompute EVERYTHING (even unchanged prefix)            │
└─────────────────────────────────────────────────────────────────────┘

With CEMAF KV Cache Awareness:
┌─────────────────────────────────────────────────────────────────────┐
│ Request 1: [System Prompt] [History] [Tool Results] [User Query]   │
│            ▲─────────────────────────▲                              │
│            Compute KV, CACHE prefix   ▲────────────────────────────▲│
│                                       Compute only new tokens       │
│                                                                     │
│ Request 2: [System Prompt] [History] [Tool Results'] [User Query'] │
│            ▲─────────────────────────▲                              │
│            REUSE cached prefix        ▲────────────────────────────▲│
│                                       Compute only changed suffix   │
└─────────────────────────────────────────────────────────────────────┘
```

### Prefix-Aware Context Construction

```python
from cemaf.context.kv_cache import PrefixAwareCompiler

compiler = PrefixAwareCompiler(
    cache_manager=KVCacheManager(
        max_cache_size_mb=512,
        eviction_policy="lru",
    ),
)

# First request: full computation
compiled1 = await compiler.compile(
    sources=[system_prompt, history, tool_results, user_query],
    budget=budget,
)
# KV cache populated for [system_prompt, history] prefix

# Second request: reuse cached prefix
compiled2 = await compiler.compile(
    sources=[system_prompt, history, new_tool_results, new_query],
    budget=budget,
)
print(f"Prefix reused: {compiled2.prefix_tokens} tokens")
print(f"New computation: {compiled2.new_tokens} tokens")
```

### Stable Ordering for Cache Hits

Context ordering affects cache hit rate:

```python
from cemaf.context.kv_cache import StableOrderingStrategy

strategy = StableOrderingStrategy(
    prefix_order=[
        "system_prompt",   # Always first (high cache value)
        "user_preferences", # Rarely changes
        "conversation_history",  # Append-only
    ],
    suffix_order=[
        "tool_results",    # Changes per request
        "user_query",      # Always last
    ],
)

compiler = PrefixAwareCompiler(
    ordering_strategy=strategy,
)
```

### Cache-Aware Selection

Prefer sources that maximize cache reuse:

```python
from cemaf.context.kv_cache import CacheAwareSelectionAlgorithm

algorithm = CacheAwareSelectionAlgorithm(
    base_algorithm=KnapsackSelectionAlgorithm(),
    cache_bonus=0.2,  # 20% priority boost for cached sources
)

# Sources in cache get priority boost
result = algorithm.select_sources(sources, budget)
print(f"Cache hit ratio: {result.metadata['cache_hit_ratio']:.1%}")
```

### Integration with Local LLMs

```python
from cemaf.llm.local import LlamaCppClient
from cemaf.context.kv_cache import KVCacheManager

# Shared cache across requests
cache = KVCacheManager(max_cache_size_mb=1024)

llm = LlamaCppClient(
    model_path="/models/llama-3-8b.gguf",
    kv_cache_manager=cache,
    context_size=8192,
)

# CEMAF manages cache-aware context construction
compiler = PrefixAwareCompiler(cache_manager=cache)

for query in queries:
    compiled = await compiler.compile(sources + [query], budget)
    response = await llm.complete(compiled.to_messages())
    # Subsequent requests reuse KV cache from prefix
```

---

## Semantic Compression

Not just "summarize" - compress while preserving task-relevant information.

### Task-Specific Distillation

```python
from cemaf.context.compression import TaskDistillationCompressor

compressor = TaskDistillationCompressor(
    llm_client=llm,
    task_description="Extract customer complaints and their resolution status",
    preserve_patterns=[
        r"\d{3}-\d{3}-\d{4}",     # Phone numbers
        r"\d{4}-\d{2}-\d{2}",     # Dates (YYYY-MM-DD)
        r"\$[\d,]+\.?\d*",        # Currency amounts
        r"#[A-Z0-9]+",            # Ticket/order IDs
    ],
    target_ratio=0.3,  # Compress to 30% of original
)

# 10K tokens → 3K tokens, all phone numbers/dates/IDs preserved
compressed = await compressor.compress(source, budget)
```

### Hierarchical Compression

Generate multiple compression levels:

```python
from cemaf.context.compression import HierarchicalCompressor

compressor = HierarchicalCompressor(
    levels={
        "full": 1.0,       # 100% - original
        "detailed": 0.5,   # 50% - key details
        "summary": 0.2,    # 20% - main points
        "headline": 0.05,  # 5% - one-liner
    },
)

# Get all levels
levels = await compressor.compress_all(source)

# Selection algorithm picks appropriate level based on budget
result = algorithm.select_sources(
    sources=[levels["detailed"], other_source, levels["summary"]],
    budget=tight_budget,
)
```

### Entity-Preserving Compression

Maintain named entities while compressing:

```python
from cemaf.context.compression import EntityPreservingCompressor

compressor = EntityPreservingCompressor(
    entity_types=["PERSON", "ORG", "DATE", "MONEY", "PRODUCT"],
    context_window=50,  # Keep 50 chars around each entity
)

# Entities and their context preserved, filler removed
compressed = await compressor.compress(document, budget)
```

### Structural Compression

Preserve document structure:

```python
from cemaf.context.compression import StructuralCompressor

compressor = StructuralCompressor(
    preserve_elements=["headers", "lists", "code_blocks"],
    compress_elements=["paragraphs", "descriptions"],
)

# Headers and code blocks intact, paragraphs compressed
compressed = await compressor.compress(markdown_doc, budget)
```

### Streaming Compression

For very large documents:

```python
from cemaf.context.compression import StreamingCompressor

compressor = StreamingCompressor(
    chunk_size=1000,
    overlap=100,
    aggregation="concatenate",  # or "summarize_chunks"
)

# Process document in chunks without loading entirely into memory
async for chunk in compressor.compress_stream(large_document_path, budget):
    yield chunk
```

### Compression Quality Metrics

```python
from cemaf.context.compression import CompressionAnalyzer

analyzer = CompressionAnalyzer()

metrics = await analyzer.analyze(
    original=source,
    compressed=compressed_source,
)

print(f"Compression ratio: {metrics.ratio:.1%}")
print(f"Entity preservation: {metrics.entity_recall:.1%}")
print(f"Semantic similarity: {metrics.semantic_similarity:.2f}")
print(f"Information density: {metrics.info_density:.2f}")
```

---

## Prefix Caching

Shared context across multiple requests/agents.

### Shared Prefix Pool

```python
from cemaf.context.prefix import PrefixPool

pool = PrefixPool(
    storage_path="/var/cemaf/prefix_cache",
    max_size_mb=2048,
)

# Register common prefixes
await pool.register(
    "system_prompt_v1",
    system_prompt_source,
    ttl_hours=24,
)

await pool.register(
    "company_knowledge_base",
    knowledge_base_source,
    ttl_hours=168,  # 1 week
)

# Use in compilation
compiled = await compiler.compile(
    sources=[
        pool.get_ref("system_prompt_v1"),  # Reference, not content
        pool.get_ref("company_knowledge_base"),
        user_context,
        query,
    ],
    budget=budget,
)
```

### Multi-Agent Prefix Sharing

```python
from cemaf.context.prefix import SharedPrefixManager

manager = SharedPrefixManager(
    redis_url="redis://localhost:6379",
)

# Agent 1 caches prefix
await manager.cache_prefix(
    key="shared_context_v1",
    content=common_context,
    agent_id="agent_001",
)

# Agent 2 reuses cached prefix
prefix = await manager.get_prefix("shared_context_v1")
if prefix:
    # KV cache hit on shared infrastructure
    compiled = await compiler.compile_with_prefix(prefix, new_sources)
```

---

## Algorithm Performance Comparison

| Algorithm | Time | Space | Cache-Aware | Best For |
|-----------|------|-------|-------------|----------|
| Greedy | O(n) | O(n) | No | General use |
| Knapsack | O(n×budget) | O(budget) | No | Optimal priority |
| Cache-Aware Greedy | O(n) | O(n) | Yes | Local LLM |
| Cache-Aware Knapsack | O(n×budget) | O(budget) | Yes | Optimal + cache |
| Hierarchical | O(n×levels) | O(n×levels) | Yes | Variable detail |

## Factory Functions

```python
from cemaf.context.factories import (
    create_kv_cache_compiler,
    create_compression_pipeline,
    create_prefix_pool,
)

# KV cache-aware compiler
compiler = create_kv_cache_compiler(
    cache_size_mb=512,
    model_type="llama",  # Optimized for Llama.cpp KV format
)

# Compression pipeline
pipeline = create_compression_pipeline(
    llm_client=llm,
    strategies=["task_distillation", "entity_preserving"],
    target_ratio=0.3,
)

# Prefix pool
pool = create_prefix_pool(
    storage="redis",  # or "file", "memory"
    config={"url": "redis://localhost:6379"},
)
