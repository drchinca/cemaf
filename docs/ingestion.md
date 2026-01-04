# Context Ingestion

CEMAF doesn't care *how* you fetch data. CEMAF cares *how that data fits into the Context Window*.

This module provides **Context Adapters** - components that transform raw data into token-budgeted, prioritized context sources ready for LLM consumption.

## Philosophy

Traditional "retrieval" frameworks focus on:
- Vector stores and embeddings
- Search APIs and database queries
- Document loaders and parsers

**CEMAF Ingestion focuses on:**
- Token budget management
- Priority-based inclusion/exclusion
- Format optimization for LLM comprehension
- Compression strategies that preserve task-relevant information

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CEMAF Context Ingestion                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   RAW DATA (any source)                                             │
│   ├── Vector DB results                                             │
│   ├── API responses                                                 │
│   ├── File contents                                                 │
│   ├── Database rows                                                 │
│   └── Stream data                                                   │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │   Context Adapter   │ ◄── Compress, Format, Prioritize         │
│   └─────────────────────┘                                          │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │   ContextSource     │ ◄── Token count, priority, metadata      │
│   └─────────────────────┘                                          │
│              │                                                      │
│              ▼                                                      │
│   ┌─────────────────────┐                                          │
│   │   Token Budget      │ ◄── Selection algorithm decides fit      │
│   └─────────────────────┘                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Context Adapter Protocol

```python
from typing import Protocol, runtime_checkable
from cemaf.context.source import ContextSource
from cemaf.context.budget import TokenBudget

@runtime_checkable
class ContextAdapter(Protocol):
    """
    Transforms raw data into token-budgeted context sources.

    CEMAF doesn't fetch data - your code does. The adapter's job is to
    make that data fit efficiently into the context window.
    """

    async def adapt(
        self,
        data: Any,
        budget: TokenBudget,
        priority: int = 0,
    ) -> ContextSource:
        """
        Adapt raw data into a context source.

        Args:
            data: Raw data from any source (you fetched it)
            budget: Available token budget for this source
            priority: Importance for selection algorithm

        Returns:
            ContextSource ready for compilation
        """
        ...

    def estimate_tokens(self, data: Any) -> int:
        """Estimate token count before full adaptation."""
        ...
```

## Built-in Adapters

### TextAdapter

For plain text content:

```python
from cemaf.ingestion import TextAdapter

adapter = TextAdapter(
    max_tokens=2000,
    truncation_strategy="tail",  # head, tail, middle
    preserve_structure=True,     # Keep paragraph breaks
)

source = await adapter.adapt(
    data="Long document content...",
    budget=TokenBudget(max_tokens=4000),
    priority=5,
)
```

### JSONAdapter

For structured data - extracts task-relevant fields:

```python
from cemaf.ingestion import JSONAdapter

adapter = JSONAdapter(
    extract_fields=["id", "title", "description"],  # Only these
    flatten_depth=2,     # Flatten nested objects
    array_limit=10,      # Max items from arrays
)

api_response = {"data": {"items": [...]}}  # You fetched this
source = await adapter.adapt(api_response, budget, priority=3)
```

### TableAdapter

For tabular data (DataFrames, CSV, SQL results):

```python
from cemaf.ingestion import TableAdapter

adapter = TableAdapter(
    max_rows=50,
    priority_columns=["name", "status", "value"],
    format="markdown",  # markdown, csv, json
)

# Your data - doesn't matter where it came from
df = pd.read_sql("SELECT * FROM orders", conn)
source = await adapter.adapt(df, budget, priority=7)
```

### ChunkAdapter

For documents that need splitting:

```python
from cemaf.ingestion import ChunkAdapter

adapter = ChunkAdapter(
    chunk_size=500,
    overlap=50,
    strategy="semantic",  # semantic, fixed, sentence
)

# Returns multiple sources - one per chunk
sources = await adapter.adapt_many(long_document, budget)
```

## Compression Strategies

### Task-Specific Distillation

Not just "summarize" - compress while preserving task-relevant information:

```python
from cemaf.ingestion import TaskDistillationAdapter

adapter = TaskDistillationAdapter(
    llm_client=llm,
    preserve_patterns=[
        r"\d{3}-\d{4}",           # Phone numbers
        r"\d{4}-\d{2}-\d{2}",     # Dates
        r"\$[\d,]+\.?\d*",        # Currency amounts
    ],
    task_context="Extract customer complaints and their resolution status",
)

# 10K document compressed to 500 tokens, dates/phones intact
source = await adapter.adapt(customer_log, budget, priority=8)
```

### Hierarchical Compression

Maintain document structure while reducing tokens:

```python
from cemaf.ingestion import HierarchicalAdapter

adapter = HierarchicalAdapter(
    levels={
        "full": 1.0,      # Include everything at this priority
        "summary": 0.5,   # 50% compression
        "outline": 0.1,   # 10% compression (headers only)
    },
)

# Returns sources at different compression levels
# Selection algorithm picks based on budget
sources = await adapter.adapt_hierarchical(document, budget)
```

## Priority Assignment

Priorities determine which sources survive budget cuts:

```python
from cemaf.ingestion import PriorityAssigner

assigner = PriorityAssigner(
    rules=[
        # Recent items get higher priority
        ("recency", lambda s: 10 if s.age_hours < 1 else 5),

        # User-requested content is critical
        ("user_requested", lambda s: 100 if s.metadata.get("requested") else 0),

        # Type-based defaults
        ("type", {
            "system_prompt": 100,
            "user_input": 90,
            "tool_result": 50,
            "background": 10,
        }),
    ],
)

source = source.with_priority(assigner.calculate(source))
```

## Format Optimization

Different formats have different token efficiency:

```python
from cemaf.ingestion import FormatOptimizer

optimizer = FormatOptimizer()

# Same data, different formats
json_tokens = optimizer.estimate_tokens(data, format="json")      # 1500
yaml_tokens = optimizer.estimate_tokens(data, format="yaml")      # 1200
markdown_tokens = optimizer.estimate_tokens(data, format="markdown")  # 900

# Auto-select most efficient format
source = await optimizer.adapt(data, budget, format="auto")
```

## Integration with Selection Algorithms

Context adapters work with CEMAF's selection algorithms:

```python
from cemaf.context import (
    PriorityContextCompiler,
    KnapsackSelectionAlgorithm,
)
from cemaf.ingestion import TextAdapter, JSONAdapter, TableAdapter

# Adapt your data (from anywhere)
sources = [
    await TextAdapter().adapt(readme_content, budget, priority=5),
    await JSONAdapter().adapt(api_response, budget, priority=8),
    await TableAdapter().adapt(sql_results, budget, priority=3),
]

# Compiler selects what fits
compiler = PriorityContextCompiler(
    algorithm=KnapsackSelectionAlgorithm()
)
compiled = await compiler.compile(sources, budget)

# Only sources that fit within token budget
print(f"Included: {len(compiled.sources)}/{len(sources)}")
```

## Edge Optimization

For resource-constrained environments:

```python
from cemaf.ingestion import EdgeAdapter

adapter = EdgeAdapter(
    # Aggressive compression for limited RAM
    max_memory_mb=50,

    # Streaming adaptation (don't load full doc)
    streaming=True,

    # Disk spillover for large documents
    spillover_path="/tmp/cemaf_context",
)

# Works on Raspberry Pi with 512MB RAM
source = await adapter.adapt(large_document, budget)
```

## Custom Adapters

Implement for your specific data types:

```python
from cemaf.ingestion import ContextAdapter, ContextSource

class SlackMessageAdapter(ContextAdapter):
    """Adapt Slack messages for context."""

    def __init__(self, include_threads: bool = True):
        self.include_threads = include_threads

    async def adapt(
        self,
        data: dict,  # Slack message payload
        budget: TokenBudget,
        priority: int = 0,
    ) -> ContextSource:
        # Extract relevant fields
        content = self._format_message(data)

        # Compress if over budget
        if self.estimate_tokens(content) > budget.available_tokens:
            content = self._compress(content, budget)

        return ContextSource(
            type="slack_message",
            key=data["ts"],
            content=content,
            token_count=self.estimate_tokens(content),
            priority=priority,
            metadata={
                "channel": data["channel"],
                "user": data["user"],
                "timestamp": data["ts"],
            },
        )

    def estimate_tokens(self, data: Any) -> int:
        if isinstance(data, str):
            return len(data) // 4
        return len(str(data)) // 4
```

## Best Practices

1. **Adapt at ingestion time** - Don't store raw data in context; adapt first
2. **Set priorities explicitly** - Don't rely on insertion order
3. **Compress proactively** - Better to have room than overflow
4. **Preserve task-relevant info** - Use pattern-preserving compression
5. **Test with real budgets** - Edge cases matter

## Migration from retrieval.md

If you were using CEMAF's retrieval module:

```python
# OLD: Retrieval-focused
results = await vector_store.search(query)
context = format_results(results)  # How do you know it fits?

# NEW: Ingestion-focused
results = await your_vector_store.search(query)  # Your retrieval
sources = [
    await adapter.adapt(r, budget, priority=r.score * 10)
    for r in results
]
compiled = await compiler.compile(sources, budget)  # Guaranteed to fit
```

The key insight: CEMAF doesn't replace your retrieval system - it makes sure whatever you retrieve **fits the context window efficiently**.
