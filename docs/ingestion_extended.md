# Ingestion Module - Extended Documentation

## Overview

The ingestion module transforms raw data into token-budgeted context, applying compression strategies, assigning priorities, and optimizing formats for LLM consumption.

**What it does**: Provides ContextAdapter protocol for converting different data types (JSON, tables, text, chunks) into ContextSource objects. Supports token budget constraints, compression strategies (summarization, sampling, deduplication), format optimization (markdown, lists, structured), and priority assignment for context selection.

**Key use cases**:
- Convert CSV/database rows into narrative context
- Reduce token count while preserving information
- Format documents for LLM reading (markdown, structured)
- Assign relevance scores for context selection
- Handle different data types uniformly through adapters
- Optimize which sources fit in context window

**When to use vs. alternatives**: Use ingestion when you need to transform raw data into LLM-friendly context. Use it for token budget management and compression. Don't use for data validation (use validation module) or retrieval (use retrieval module).

## Core Concepts

### Context Adaptation

Raw data → ContextAdapter → ContextSource (formatted, token-counted, prioritized)

**ContextSource**: Structured context ready for LLM. Contains:
- Content (formatted text)
- Token count (for budgeting)
- Priority (relevance score 0-1)
- Source metadata (where it came from)
- Format (markdown, JSON, list, etc.)

### Compression Strategies

When data doesn't fit in context window:

**Summarization**: Replace long text with shorter summary. Loses details but saves tokens.
**Sampling**: Keep only important rows/items. Loses some data but maintains structure.
**Deduplication**: Remove repeated information. Lossless.
**Excerpt**: Keep only relevant sections. Requires understanding content.

Each strategy trades off information for token count.

### Token Budgeting

Track token usage across all sources. Allocate budget:
- Fixed: Total tokens available in context window
- Per-source: Max tokens per data source
- Dynamic: Adjust allocation based on importance

Fill context up to budget while respecting priorities.

## Usage Examples

### Basic Data Transformation

```python
from cemaf.ingestion import TextAdapter, JSONAdapter, TableAdapter
from cemaf.ingestion.protocols import CompressionStrategy
from cemaf.core.types import Tokens

# Transform different data types
text_adapter = TextAdapter()
json_adapter = JSONAdapter()
table_adapter = TableAdapter()

# Plain text → context source
source = await text_adapter.adapt(
    data="Long article text...",
    metadata={"source": "article.md", "date": "2024-01-15"}
)
print(f"Text: {source.token_count} tokens")

# JSON → context source
source = await json_adapter.adapt(
    data={"key": "value", "items": [...]},
    metadata={"source": "api_response"}
)
print(f"JSON: {source.token_count} tokens")

# Table → context source
source = await table_adapter.adapt(
    data=[
        {"name": "Alice", "score": 95},
        {"name": "Bob", "score": 87},
    ],
    metadata={"source": "database", "table": "results"}
)
print(f"Table: {source.token_count} tokens")
```

### Token Budget Management

```python
from cemaf.ingestion import ContextBudget

# Create token budget
budget = ContextBudget(
    total_tokens=2000,
    reserved_tokens=200,  # For instructions
    per_source_max=500
)

sources = [
    # Get sources from retrieval/ingestion
    source1,  # 800 tokens
    source2,  # 600 tokens
    source3,  # 400 tokens
    source4,  # 300 tokens
]

# Fit sources within budget
selected = await budget.select_sources(
    sources=sources,
    sort_by="priority"  # Use priority to select best sources
)

# Result: selected sources that fit in 2000 total tokens
# Might exclude some sources if they don't fit
```

### Compression Strategies

```python
from cemaf.ingestion.compression import SummarizationStrategy, SamplingStrategy

# Strategy 1: Summarization for long text
summarizer = SummarizationStrategy(
    target_tokens=200,
    preserve_key_points=True
)

source = await text_adapter.adapt(
    data=long_article,
    compression=summarizer
)
# Original 1000 tokens → ~200 tokens summary

# Strategy 2: Sampling for large tables
sampler = SamplingStrategy(
    sample_size=10,  # Keep 10 rows
    stratified=True  # Maintain distribution
)

source = await table_adapter.adapt(
    data=large_table,
    compression=sampler
)
# 1000 rows → 10 representative rows

# Strategy 3: Deduplication for repeated content
deduplicator = DeduplicationStrategy()

source = await text_adapter.adapt(
    data=repeated_text,
    compression=deduplicator
)
# Remove redundant sentences
```

### Format Optimization

```python
from cemaf.ingestion.formatters import MarkdownFormatter, StructuredFormatter

# Format for readability
formatter = MarkdownFormatter()
source = await text_adapter.adapt(
    data=raw_text,
    formatter=formatter
)

# Result:
# # Title
# ## Section 1
# Content...

# Format for structure
formatter = StructuredFormatter()
source = await json_adapter.adapt(
    data={"users": [...]},
    formatter=formatter
)

# Result:
# **Users:**
# - User 1: email1@example.com
# - User 2: email2@example.com
```

### Priority Assignment

```python
from cemaf.ingestion.priority import RelevanceScorer

# Assign priorities based on relevance
scorer = RelevanceScorer()

sources = [
    source1,  # Recent, high relevance
    source2,  # Old, low relevance
    source3,  # Relevant but large
]

# Score sources
for source in sources:
    source.priority = await scorer.score(
        source=source,
        query="What happened today?",
        context=current_context
    )

# Sort by priority for selection
sources.sort(key=lambda s: s.priority, reverse=True)
```

### Custom Adapters

```python
from cemaf.ingestion.protocols import ContextAdapter
from cemaf.core.types import JSON

class CSVAdapter(ContextAdapter):
    """Adapter for CSV data."""

    async def adapt(
        self,
        data: str,  # CSV text
        metadata: dict | None = None
    ) -> ContextSource:
        """Convert CSV to context source."""
        import csv
        import io

        reader = csv.DictReader(io.StringIO(data))
        rows = list(reader)

        # Format as markdown table
        content = "| " + " | ".join(rows[0].keys()) + " |\n"
        content += "| " + " | ".join(["---"] * len(rows[0])) + " |\n"
        for row in rows[:10]:  # First 10 rows
            content += "| " + " | ".join(row.values()) + " |\n"

        token_count = await self.count_tokens(content)

        return ContextSource(
            content=content,
            token_count=token_count,
            priority=0.7,
            source=metadata or {},
            format="markdown"
        )
```

### Common Mistake: Ignoring Token Counts

```python
# ❌ WRONG - Assume small data fits
source = await adapter.adapt(data)
context.add_source(source)
context.add_source(another_source)
# No tracking - context might exceed limit!

# ✅ CORRECT - Respect token budget
sources = [await adapter.adapt(d) for d in all_data]
selected = await budget.select_sources(sources)
context.add_sources(selected)
# Guaranteed to fit in token limit
```

## Integration

### With Context Module

```python
from cemaf.ingestion import create_adapter_from_config
from cemaf.context.context import Context

# Load raw data and convert to context
async def build_context_from_raw(raw_data):
    adapter = create_adapter_from_config(
        format=raw_data['format']  # auto-detect adapter
    )

    source = await adapter.adapt(
        data=raw_data['content'],
        metadata=raw_data['metadata']
    )

    context = Context(sources=[source])
    return context
```

### With Retrieval Module

```python
from cemaf.retrieval import HybridRetriever
from cemaf.ingestion import ContextBudget

# Retrieve sources, then ingest with budget
class BudgetedRetrieval:
    def __init__(self, retriever, budget, adapter_config):
        self.retriever = retriever
        self.budget = budget
        self.adapter_config = adapter_config

    async def retrieve_and_ingest(self, query: str):
        # Retrieve
        sources = await self.retriever.retrieve(query, limit=20)

        # Convert to context sources
        ingested = []
        for source in sources:
            adapter = create_adapter_from_config(self.adapter_config)
            context_source = await adapter.adapt(
                data=source.text,
                metadata={"url": source.id}
            )
            ingested.append(context_source)

        # Select within budget
        selected = await self.budget.select_sources(ingested)
        return selected
```

### With Generation Module

```python
# Use ingested context in generation
async def generate_with_ingested_context(prompt: str):
    # Retrieve sources
    sources = await retriever.retrieve(prompt, limit=10)

    # Ingest with budget
    ingested = [await adapter.adapt(s) for s in sources]
    selected = await budget.select_sources(ingested)

    # Format context for LLM
    context_text = "\n\n".join([
        f"# {s.source['title']}\n{s.content}"
        for s in selected
    ])

    # Generate with context
    full_prompt = f"Context:\n{context_text}\n\nTask: {prompt}"
    response = await llm.generate(full_prompt)

    return response
```

## API Reference

### ContextSource Dataclass

```python
@dataclass
class ContextSource:
    content: str                        # Formatted content
    token_count: int                    # Token count
    priority: float = 0.5               # Relevance (0-1)
    source: dict = Field(default_factory=dict)  # Metadata
    format: str = "text"                # markdown, json, list, etc.
```

### ContextAdapter Protocol

```python
@runtime_checkable
class ContextAdapter(Protocol):
    async def adapt(
        self,
        data: Any,
        metadata: dict | None = None,
        compression: CompressionStrategy | None = None,
        formatter: FormatOptimizer | None = None
    ) -> ContextSource: ...
```

### CompressionStrategy Protocol

```python
@runtime_checkable
class CompressionStrategy(Protocol):
    async def compress(
        self,
        content: str,
        target_tokens: int
    ) -> str: ...
```

### FormatOptimizer Protocol

```python
@runtime_checkable
class FormatOptimizer(Protocol):
    async def optimize(
        self,
        content: str,
        target_format: str
    ) -> str: ...
```

### Built-in Adapters

```python
class TextAdapter(ContextAdapter):
    """Plain text → context source."""

class JSONAdapter(ContextAdapter):
    """JSON data → context source."""

class TableAdapter(ContextAdapter):
    """Tabular data → context source."""

class ChunkAdapter(ContextAdapter):
    """Pre-chunked data → context source."""
```

### ContextBudget

```python
class ContextBudget:
    def __init__(
        self,
        total_tokens: int,
        reserved_tokens: int = 0,
        per_source_max: int | None = None
    ): ...

    async def select_sources(
        self,
        sources: list[ContextSource],
        sort_by: str = "priority"
    ) -> list[ContextSource]: ...

    @property
    def available_tokens(self) -> int: ...

    @property
    def used_tokens(self) -> int: ...
```

## Best Practices

### Token Counting Accuracy

```python
# Always use consistent token counter
from cemaf.llm import token_counter

# Count with same model being used
tokens = await token_counter.count(text, model="claude-3-5-sonnet")

# Verify on actual LLM
response = await llm.generate(prompt)
actual_tokens = response.usage.input_tokens
```

### Compression Strategy Selection

```python
# Different strategies for different data:
COMPRESSION_STRATEGIES = {
    "long_article": SummarizationStrategy(target_tokens=300),
    "large_table": SamplingStrategy(sample_size=20),
    "code": ExcerptStrategy(lines_per_section=10),
    "emails": DeduplicationStrategy(),
}
```

### Performance Tips

- **Cache adapted sources**: Don't re-adapt same data
- **Lazy compression**: Only compress sources that don't fit
- **Batch processing**: Adapt many sources in parallel
- **Streaming for large data**: Stream compression to avoid memory issues

### Common Pitfalls

**Lossy compression without warning**: Tell users when data is compressed. They need to know.

**Over-compression**: If you compress too aggressively, information loss might hurt generation.

**Wrong format**: Text data forced to JSON format won't work well. Match format to data.

**Token budget exceeded**: Always respect budget. Over-fitting token count breaks system.

### When NOT to Use

- **Raw database queries**: Use SQL directly, not ingestion
- **Streaming data**: Ingestion is batch-oriented
- **Real-time transformation**: Ingestion is pre-computation focused
- **Unstructured blobs**: Need some structure for adaptation
