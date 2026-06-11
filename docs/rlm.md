# RLM - Recursive Language Models

**Infinite context that works** through divide-and-conquer querying.

## Overview

RLM (Recursive Language Models) enables querying of arbitrarily large context by treating context as external state and using recursive self-query with divide-and-conquer strategies. Instead of trying to fit everything into the LLM's context window, RLM breaks content into chunks, queries them recursively, and aggregates results.

### Key Concepts

- **Context as External State**: Content lives outside the LLM, queried on-demand
- **Divide-and-Conquer**: Large context split into chunks, queried recursively, results aggregated
- **Token Budget Enforcement**: Respects token limits at every recursion level
- **Protocol-Based**: Extensible design allowing custom chunking and query strategies

## Architecture

```mermaid
flowchart TB
    subgraph Input
        INST[Instruction]
        CONTENT[Large Content<br/>100K+ tokens]
    end

    subgraph Chunking
        STRATEGY[ChunkingStrategy]
        CHUNKS[ContextChunk[]]
    end

    subgraph Query Engine
        ENGINE[RecursiveQueryEngine]
        COMPILER[ContextCompiler]
        BUDGET[TokenBudget]
    end

    subgraph Recursion
        BASE{Fits in budget?}
        SINGLE[Single LLM Call]
        SPLIT[Split Chunks]
        LEFT[Query Left]
        RIGHT[Query Right]
        AGG[Aggregate Results]
    end

    subgraph Output
        RESULT[RecursiveQueryResult]
        ANSWER[Answer]
        META[Metadata]
    end

    CONTENT --> STRATEGY
    STRATEGY --> CHUNKS
    CHUNKS --> ENGINE
    INST --> ENGINE
    ENGINE --> COMPILER
    ENGINE --> BUDGET
    ENGINE --> BASE

    BASE -->|Yes| SINGLE
    BASE -->|No| SPLIT
    SPLIT --> LEFT
    SPLIT --> RIGHT
    LEFT --> AGG
    RIGHT --> AGG

    SINGLE --> RESULT
    AGG --> RESULT
    RESULT --> ANSWER
    RESULT --> META
```

## v0.2 Improvements

### Parallel Chunk Processing

Left and right branches of divide-and-conquer are now processed in parallel via `asyncio.gather`, significantly reducing latency for large contexts:

```
Sequential (v0.1):  Left(2s) → Right(2s) → Aggregate(1s) = 5s
Parallel   (v0.2):  Left(2s) ‖ Right(2s) → Aggregate(1s) = 3s
```

### Partial Coverage Fallback

When max depth is reached or a single chunk exceeds the budget, the engine now processes budget-sized batches and aggregates results instead of only querying the first chunk:

```python
# v0.1: Only first chunk processed → low coverage
# v0.2: All chunks processed in batches → full coverage
result = await engine.query(instruction="...", chunks=large_chunks, budget=small_budget)
print(result.metadata["strategy"])       # "partial_coverage"
print(result.metadata["coverage_ratio"]) # 1.0 (all chunks examined)
```

### Coverage Ratio Tracking

`RecursiveQueryResult` now includes `coverage_ratio` (0.0-1.0) indicating what fraction of chunks were examined.

## Quick Start

### Basic Usage

```python
from cemaf.rlm import create_rlm_tool
from cemaf.llm.anthropic import AnthropicLLMClient

# Create LLM client
llm = AnthropicLLMClient(api_key="...")

# Create RLM tool with defaults
rlm_tool = create_rlm_tool(llm)

# Query large content
result = await rlm_tool.execute(
    instruction="Summarize the main points about CEMAF",
    content=large_document,  # Can be 100K+ tokens
)

if result.success:
    print(f"Answer: {result.data}")
    print(f"Depth: {result.metadata['depth_reached']}")
    print(f"LLM Calls: {result.metadata['llm_calls_made']}")
    print(f"Tokens: {result.metadata['total_tokens_used']}")
else:
    print(f"Error: {result.error}")
```

### Custom Configuration

```python
# Custom chunk size, depth, and token budget
rlm_tool = create_rlm_tool(
    llm_client=llm,
    chunk_size=1000,    # Larger chunks
    max_depth=5,        # Deeper recursion
    max_tokens=8000,    # Larger budget
)

result = await rlm_tool.execute(
    instruction="Find all mentions of 'context engineering'",
    content=massive_codebase,
    max_depth=4,        # Override default for this query
)
```

## Integration with Skills

RLM is a standard CEMAF Tool, so it integrates cleanly with Skills:

```python
from cemaf.skills.base import Skill, SkillContext, SkillOutput
from cemaf.core.result import Result

class DocumentAnalysisSkill:
    """Skill for analyzing large documents using RLM."""

    def __init__(self, rlm_tool):
        self._rlm = rlm_tool

    @property
    def id(self) -> SkillID:
        return SkillID("document_analysis")

    @property
    def tools(self) -> tuple:
        """Expose RLM tool to framework."""
        return (self._rlm,)

    async def execute(
        self,
        input: str,
        context: SkillContext,
    ) -> Result[SkillOutput]:
        # Get document from context
        document = context.memory.get("document", "project")

        # Use RLM to analyze
        result = await self._rlm.execute(
            instruction=input,
            content=document,
        )

        if not result.success:
            return Result.fail(result.error)

        # Return as SkillOutput with tool trace
        return Result.ok(
            SkillOutput(
                data=result.data,
                tool_calls=[
                    {
                        "tool": "rlm_query",
                        "input": {"instruction": input},
                        "output": result.data,
                        "metadata": result.metadata,
                    }
                ],
            )
        )
```

## Integration with Agents

Skills using RLM work seamlessly with Agents:

```python
from cemaf.agents.base import Agent, AgentContext, AgentGoal, AgentResult

class AnalystAgent:
    """Agent that analyzes large datasets using RLM."""

    def __init__(self, analysis_skill):
        self._skill = analysis_skill

    @property
    def id(self) -> AgentID:
        return AgentID("analyst")

    @property
    def skills(self) -> tuple:
        return (self._skill,)

    async def run(
        self,
        goal: AgentGoal,
        context: AgentContext,
    ) -> AgentResult:
        # Execute analysis skill with RLM
        result = await self._skill.execute(
            goal.instruction,
            context,
        )

        if not result.success:
            return AgentResult.fail(result.error)

        # Return with state trace
        return AgentResult.ok(
            result.data,
            state=AgentState(
                status=AgentStatus.COMPLETED,
                skill_calls=[result],
            ),
        )
```

## Integration with ToolRegistry

For LLM function calling, register RLM with ToolRegistry:

```python
from cemaf.tools.registry import ToolRegistry

# Create registry with dependencies
registry = ToolRegistry(
    dependencies={"llm_client": llm},
    namespace="analysis",
)

# Register RLM tool
registry.register_instance(rlm_tool)

# Export for Claude/GPT function calling
anthropic_schemas = registry.to_anthropic_schemas()
# → [{"name": "analysis.rlm_query", "description": "...", "input_schema": {...}}]

# LLM can now call RLM as a function
messages = [
    Message.user("Analyze this large document: [content]")
]

result = await llm.complete(
    messages=messages,
    tools=anthropic_schemas,  # RLM available as tool
)
```

## How It Works

### 1. Chunking

Content is broken into chunks based on token count:

```python
from cemaf.rlm.chunking import FixedSizeChunkingStrategy
from cemaf.context.compiler import SimpleTokenEstimator

estimator = SimpleTokenEstimator()
chunking = FixedSizeChunkingStrategy(estimator, chunk_size=500)

chunks = chunking.chunk(large_content, max_chunk_tokens=500)
# → tuple[ContextChunk, ...]
```

Each chunk contains:
- `chunk_id`: Unique identifier
- `content`: Chunk text
- `token_count`: Estimated tokens
- `parent_id`: For hierarchical organization (future)
- `depth`: Nesting level
- `metadata`: Additional info

### 2. Recursive Querying

The engine uses divide-and-conquer:

```python
from cemaf.rlm.engine import DivideAndConquerQueryEngine
from cemaf.context.compiler import PriorityContextCompiler
from cemaf.context.budget import TokenBudget

compiler = PriorityContextCompiler(estimator)
engine = DivideAndConquerQueryEngine(llm, compiler, max_depth=3)

budget = TokenBudget(max_tokens=4000, reserved_for_output=1000)

result = await engine.query(
    instruction="Find all mentions of X",
    chunks=chunks,
    budget=budget,
    max_depth=3,
)
```

**Algorithm**:
1. **Base case**: If chunks fit in budget → single LLM call
2. **Recursive case**: Split chunks in half, query each, aggregate results
3. **Fallback**: At max depth or single large chunk → query first chunk only

### 3. Result Aggregation

Results from recursive queries are aggregated:

```python
# Left half result
left_answer = "Found 3 mentions in section A"

# Right half result
right_answer = "Found 2 mentions in section B"

# Aggregation prompt
aggregated = await llm.complete([
    Message.user(f"""
    Original question: Find all mentions of X

    Part 1: {left_answer}
    Part 2: {right_answer}

    Synthesize these into a single coherent response.
    """)
])
# → "Found 5 mentions total: 3 in section A, 2 in section B"
```

## Execution Metadata

Every RLM query returns rich metadata:

```python
result = await rlm_tool.execute(
    instruction="Analyze sentiment",
    content=large_corpus,
)

print(result.metadata)
# {
#     "depth_reached": 2,              # Recursion depth used
#     "chunks_examined": 8,             # Total chunks processed
#     "llm_calls_made": 15,             # Total LLM calls
#     "total_tokens_used": 45000,       # Total tokens consumed
#     "relevant_chunks_count": 8,       # Chunks with relevant info
#     "total_chunks_created": 20,       # Total chunks from content
#     "strategy": "divide_and_conquer", # Execution strategy
#     "left_chunks": 10,                # Chunks in left half
#     "right_chunks": 10,               # Chunks in right half
# }
```

## Advanced Usage

### Custom Token Estimator

```python
from cemaf.context.compiler import TokenEstimator

class CustomTokenEstimator:
    """Custom token estimator using tiktoken."""

    def __init__(self, model: str = "gpt-4"):
        import tiktoken
        self.encoding = tiktoken.encoding_for_model(model)

    def estimate(self, text: str) -> int:
        return len(self.encoding.encode(text))

# Use custom estimator
rlm_tool = create_rlm_tool(
    llm_client=llm,
    token_estimator=CustomTokenEstimator(),
)
```

### Custom Chunking Strategy

```python
from cemaf.rlm.protocols import ContextChunk, ChunkingStrategy

class SemanticChunkingStrategy:
    """Chunk by semantic boundaries (paragraphs, sections, etc.)."""

    def chunk(
        self,
        content: str,
        max_chunk_tokens: int,
    ) -> tuple[ContextChunk, ...]:
        # Custom chunking logic
        sections = split_by_sections(content)
        chunks = []

        for i, section in enumerate(sections):
            chunks.append(
                ContextChunk(
                    chunk_id=f"section_{i}",
                    content=section,
                    token_count=TokenCount(estimate_tokens(section)),
                    metadata={"type": "section"},
                )
            )

        return tuple(chunks)

    def create_hierarchy(
        self,
        chunks: tuple[ContextChunk, ...],
    ) -> tuple[ContextChunk, ...]:
        # Create parent-child relationships
        return chunks

# Use custom strategy
chunking = SemanticChunkingStrategy()
engine = DivideAndConquerQueryEngine(llm, compiler, max_depth=3)
rlm_tool = RLMQueryTool(engine, chunking)
```

### Custom Query Engine

```python
from cemaf.rlm.protocols import RecursiveQueryEngine, RecursiveQueryResult

class CachedQueryEngine:
    """Query engine with caching for repeated queries."""

    def __init__(self, base_engine, cache):
        self._engine = base_engine
        self._cache = cache

    async def query(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        budget: TokenBudget,
        max_depth: int = 3,
    ) -> RecursiveQueryResult:
        # Create cache key from instruction + chunk IDs
        chunk_ids = tuple(c.chunk_id for c in chunks)
        cache_key = f"{instruction}:{hash(chunk_ids)}"

        # Check cache
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        # Query and cache
        result = await self._engine.query(
            instruction, chunks, budget, max_depth
        )

        if result.success:
            self._cache.set(cache_key, result)

        return result
```

## Performance Considerations

### Token Budget

- **Default**: 4000 tokens total, 1000 reserved for output
- **Recommendation**: Larger budgets reduce recursion depth, fewer LLM calls
- **Trade-off**: Smaller budgets = more calls but lower cost per call

```python
# Small budget: more recursive calls
rlm_tool = create_rlm_tool(llm, max_tokens=2000)  # → deeper recursion

# Large budget: fewer recursive calls
rlm_tool = create_rlm_tool(llm, max_tokens=16000)  # → shallower recursion
```

### Chunk Size

- **Default**: 500 tokens per chunk
- **Recommendation**: Larger chunks fit more context but may exceed budget
- **Trade-off**: Smaller chunks = more granular but more overhead

```python
# Small chunks: more granular, more calls
rlm_tool = create_rlm_tool(llm, chunk_size=250)

# Large chunks: less granular, fewer calls
rlm_tool = create_rlm_tool(llm, chunk_size=2000)
```

### Max Depth

- **Default**: 3 levels of recursion
- **Recommendation**: Deeper allows larger content but more LLM calls
- **Trade-off**: Shallower = faster but may truncate content

```python
# Shallow: faster but limited content
rlm_tool = create_rlm_tool(llm, max_depth=2)

# Deep: slower but handles massive content
rlm_tool = create_rlm_tool(llm, max_depth=10)
```

### Cost Estimation

```python
# Estimate LLM calls for content
content_tokens = 100000
chunk_size = 500
num_chunks = content_tokens / chunk_size  # 200 chunks

# Binary tree recursion
max_depth = 3
calls_per_level = [
    num_chunks,              # Level 0: 200 chunks → 200 calls (impossible)
    num_chunks / 2,          # Level 1: 100 pairs → 100 aggregations
    num_chunks / 4,          # Level 2: 50 pairs → 50 aggregations
    num_chunks / 8,          # Level 3: 25 pairs → 25 aggregations
]

# Total calls ≈ sum of calls at each level until budget is met
# Actual depends on budget, but worst case is O(n log n)
```

## Best Practices

### 1. Start with Defaults

The factory provides sensible defaults for most use cases:

```python
rlm_tool = create_rlm_tool(llm_client)  # Use defaults first
```

### 2. Profile Before Optimizing

Use metadata to understand execution:

```python
result = await rlm_tool.execute(instruction, content)

print(f"Depth: {result.metadata['depth_reached']}")
print(f"LLM calls: {result.metadata['llm_calls_made']}")
print(f"Tokens: {result.metadata['total_tokens_used']}")

# If depth_reached == max_depth frequently:
# → Increase max_depth or max_tokens
# If llm_calls_made is too high:
# → Increase chunk_size or max_tokens
```

### 3. Match Chunk Size to Content Type

```python
# Code: smaller chunks (respect function boundaries)
code_rlm = create_rlm_tool(llm, chunk_size=300)

# Prose: larger chunks (respect paragraph boundaries)
prose_rlm = create_rlm_tool(llm, chunk_size=800)

# Mixed: medium chunks
mixed_rlm = create_rlm_tool(llm, chunk_size=500)  # default
```

### 4. Use Clear Instructions

```python
# ✅ Good: specific, actionable
result = await rlm_tool.execute(
    instruction="Find all function definitions and their signatures",
    content=codebase,
)

# ❌ Bad: vague, open-ended
result = await rlm_tool.execute(
    instruction="Analyze the code",
    content=codebase,
)
```

### 5. Handle Failures Gracefully

```python
result = await rlm_tool.execute(instruction, content)

if not result.success:
    if "max_depth" in result.error:
        # Retry with larger max_depth
        result = await rlm_tool.execute(
            instruction, content, max_depth=5
        )
    elif "budget" in result.error:
        # Retry with larger budget
        result = await rlm_tool.execute(
            instruction, content, max_tokens=8000
        )
    else:
        # Log and fail gracefully
        logger.error(f"RLM failed: {result.error}")
        return default_response
```

## Limitations

### Current Limitations (v1)

1. **Chunking Strategy**: Only fixed-size chunking (no semantic/hierarchical)
2. **No Parallelization**: Recursive queries are sequential (left then right)
3. **No Caching**: No deduplication of similar queries
4. **No Streaming**: Results returned at the end, no partial results
5. **Token Estimation**: Uses simple char/token ratio (not precise)

### Future Enhancements

See implementation plan for v2, v3, v4 features:
- Semantic chunking (sentence/section aware)
- Parallel execution (asyncio.gather for map phase)
- Query caching and deduplication
- Hierarchical summarization (parent chunks)
- Streaming results
- Binary search optimization (O(log N) instead of O(N))

## Testing

RLM has comprehensive unit tests:

```bash
# Run all RLM tests
uv run pytest tests/unit/rlm/ -v

# Run specific test file
uv run pytest tests/unit/rlm/test_tool.py -v

# Run with coverage
uv run pytest tests/unit/rlm/ --cov=src/cemaf/rlm --cov-report=term-missing
```

## Examples

### Example 1: Codebase Analysis

```python
# Analyze large codebase for patterns
codebase = read_directory_recursive("src/")

result = await rlm_tool.execute(
    instruction="Find all occurrences of deprecated API usage",
    content=codebase,
)

print(result.data)
# → "Found 15 occurrences:
#    - src/foo.py:42 - uses old_api()
#    - src/bar.py:100 - uses deprecated_method()
#    ..."
```

### Example 2: Document Summarization

```python
# Summarize long research paper
paper = read_file("research_paper.txt")  # 50K tokens

result = await rlm_tool.execute(
    instruction="Summarize the key findings and methodology",
    content=paper,
)

print(result.data)
# → "The paper presents three key findings:
#    1. [Finding 1]
#    2. [Finding 2]
#    3. [Finding 3]
#
#    Methodology: [Summary]"
```

### Example 3: Knowledge Base Search

```python
# Search knowledge base for specific information
kb = load_knowledge_base()  # 200K tokens

result = await rlm_tool.execute(
    instruction="What are the company's policies on remote work?",
    content=kb,
)

print(result.data)
# → "The company's remote work policies include:
#    - Flexible hours between 9am-5pm
#    - Required to attend weekly team meetings
#    - Equipment provided: laptop, monitor, keyboard
#    ..."
```

### Example 4: Batch Processing

```python
# Process multiple large documents
documents = [read_file(f) for f in document_paths]

results = []
for doc in documents:
    result = await rlm_tool.execute(
        instruction="Extract action items and deadlines",
        content=doc,
    )
    results.append(result.data)

# Aggregate results
all_action_items = "\n".join(results)
```

## Comparison with Other Approaches

| Approach | Pros | Cons |
|----------|------|------|
| **RLM** | Handles unlimited content, cost-effective, preserves detail | Multiple LLM calls, sequential processing |
| **Summarization** | Single LLM call, fast | Lossy, may miss details, limited by summary quality |
| **RAG** | Good for search, pre-indexed | Requires embedding, may miss context, setup overhead |
| **Long-context LLMs** | Simple, single call | Expensive, still has limits (200K max), quality degrades |

**When to use RLM**:
- Content exceeds LLM context window
- Need to preserve detail (not just summaries)
- Cost is a concern (vs long-context LLMs)
- Don't need real-time responses

**When NOT to use RLM**:
- Content fits in context window (use regular LLM call)
- Need real-time streaming (use long-context LLM)
- Need precise search (use RAG with embeddings)
- Okay with lossy compression (use summarization)

## See Also

- [Module Reference - RLM](./module_reference.md#rlm---recursive-language-models-cemafrlm)
- [Tools Documentation](./tools.md)
- [Context Engineering](./context.md)
- [Token Budget](./context.md#token-budget)
