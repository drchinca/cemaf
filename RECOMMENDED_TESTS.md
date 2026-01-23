# Recommended Test Additions for RLM Integration

## Priority 1: Critical Tests (Add Before Production)

### 1.1 Test LLM Failures in Recursive Context
**File:** `/Users/bado/iccha/iccha_context_multi_agent/cemaf/tests/integration/rlm/test_rlm_large_context.py`

**What:** Test that LLM failures in left/right recursive branches are handled correctly.

**Why:** Lines 168, 171 in engine.py handle failures but are never tested. Production queries could silently fail.

**Code:**
```python
@pytest.mark.asyncio
async def test_rlm_left_recursive_failure(
    self, compiler: PriorityContextCompiler
) -> None:
    """Test handling when left recursive query fails."""

    class PartialFailingLLMClient:
        """LLM client that fails on aggregation step."""

        def __init__(self):
            self.call_count = 0

        @property
        def config(self) -> LLMConfig:
            return LLMConfig(model="mock", temperature=0.7)

        async def complete(self, messages, tools=None, config_override=None):
            self.call_count += 1
            # First call succeeds (single query or left branch)
            # Second call succeeds (right branch)
            # Third call fails (aggregation)
            if self.call_count >= 3:
                return CompletionResult.fail("Aggregation error")
            return CompletionResult.ok(
                message=Message.assistant(f"Result {self.call_count}"),
                prompt_tokens=10,
                completion_tokens=5,
                model="mock",
            )

        def count_tokens(self, text: str) -> TokenCount:
            return TokenCount(len(text) // 4)

        def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
            return TokenCount(10)

    engine = DivideAndConquerQueryEngine(
        PartialFailingLLMClient(), compiler, max_depth=3
    )

    chunks = tuple(
        ContextChunk(
            chunk_id=f"chunk_{i}",
            content="word " * 1000,
            token_count=TokenCount(250),
        )
        for i in range(4)  # 4 chunks force divide-and-conquer
    )

    budget = TokenBudget(max_tokens=100)
    result = await engine.query(
        instruction="Find X",
        chunks=chunks,
        budget=budget,
        max_depth=2,
    )

    # Should return failure, not success with error message
    assert result.success is False
    assert result.error is not None
    assert "Aggregation error" in result.error


@pytest.mark.asyncio
async def test_rlm_aggregation_failure_recovery(
    self, compiler: PriorityContextCompiler
) -> None:
    """Test recovery when aggregation LLM call fails."""

    class AggregationFailingLLM:
        """Fails only on aggregation (3rd LLM call)."""

        def __init__(self):
            self.call_count = 0

        @property
        def config(self) -> LLMConfig:
            return LLMConfig(model="mock", temperature=0.7)

        async def complete(self, messages, tools=None, config_override=None):
            self.call_count += 1
            if "synthesize" in str(messages).lower() or self.call_count >= 3:
                return CompletionResult.fail("Aggregation LLM timeout")
            return CompletionResult.ok(
                message=Message.assistant(f"Branch result {self.call_count}"),
                prompt_tokens=10,
                completion_tokens=5,
                model="mock",
            )

        def count_tokens(self, text: str) -> TokenCount:
            return TokenCount(len(text) // 4)

        def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
            return TokenCount(10)

    engine = DivideAndConquerQueryEngine(
        AggregationFailingLLM(), compiler, max_depth=2
    )

    chunks = tuple(
        ContextChunk(
            chunk_id=f"chunk_{i}",
            content="content",
            token_count=TokenCount(100),
        )
        for i in range(4)
    )

    result = await engine.query(
        instruction="Find important",
        chunks=chunks,
        budget=TokenBudget(max_tokens=100),
    )

    # Aggregation failure should result in failure status
    assert result.success is False
    assert "Aggregation LLM timeout" in result.error
```

---

### 1.2 Test Concurrent RLM Execution
**File:** `/Users/bado/iccha/iccha_context_multi_agent/cemaf/tests/integration/rlm/test_rlm_concurrency.py` (new file)

**What:** Test that multiple RLM queries can run simultaneously without ID collisions.

**Why:** Chunk IDs are generated as `f"chunk_{len(chunks)}"` which is not thread-safe. Concurrent operations could collide.

**Code:**
```python
"""
Concurrency tests for RLM.

Tests RLM behavior when multiple queries execute simultaneously.
"""

import asyncio
import pytest

from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.llm.mock import MockLLMClient
from cemaf.rlm import create_rlm_tool


class TestRLMConcurrency:
    """Test RLM concurrency and race conditions."""

    @pytest.fixture
    def estimator(self) -> SimpleTokenEstimator:
        """Create token estimator."""
        return SimpleTokenEstimator(chars_per_token=4.0)

    @pytest.fixture
    def llm_client(self) -> MockLLMClient:
        """Create mock LLM client."""
        return MockLLMClient(
            responses=[
                "Query 1 result",
                "Query 2 result",
                "Query 3 result",
            ]
        )

    @pytest.fixture
    def rlm_tool(self, llm_client: MockLLMClient, estimator: SimpleTokenEstimator) -> object:
        """Create RLM tool."""
        return create_rlm_tool(
            llm_client=llm_client,
            token_estimator=estimator,
            chunk_size=500,
            max_depth=2,
            max_tokens=4000,
        )

    @pytest.mark.asyncio
    async def test_concurrent_rlm_queries(self, rlm_tool: object) -> None:
        """Test multiple RLM queries running simultaneously."""
        content = "\n\n".join([f"Section {i}: content" for i in range(20)])

        # Run 3 RLM queries concurrently
        tasks = [
            rlm_tool.execute(instruction="Query 1", content=content),
            rlm_tool.execute(instruction="Query 2", content=content),
            rlm_tool.execute(instruction="Query 3", content=content),
        ]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r.success for r in results)

        # All should return different results
        result_strings = [r.data for r in results]
        assert len(set(result_strings)) == 3  # All unique

    @pytest.mark.asyncio
    async def test_concurrent_chunking_no_id_collisions(
        self, rlm_tool: object
    ) -> None:
        """Test that concurrent chunking doesn't create duplicate chunk IDs."""
        # This would require extracting chunk_ids from metadata
        # Implementation depends on how metadata is exposed

        content = "\n\n".join([f"Section {i}: " + "word " * 100 for i in range(50)])

        # Run 5 concurrent queries
        tasks = [
            rlm_tool.execute(instruction=f"Query {i}", content=content)
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)

        # Collect all chunk IDs from metadata
        all_chunk_ids = []
        for result in results:
            if "chunks_examined" in result.metadata:
                # Extract chunk IDs from some representation
                # This depends on implementation detail exposure
                pass

        # Verify no duplicate IDs across concurrent executions
        # This is a placeholder - actual implementation depends on
        # what's exposed in metadata


    @pytest.mark.asyncio
    async def test_concurrent_different_budgets(
        self, llm_client: MockLLMClient, estimator: SimpleTokenEstimator
    ) -> None:
        """Test concurrent queries with different token budgets."""
        # Create multiple tools with different configs
        tool_small = create_rlm_tool(
            llm_client=llm_client,
            token_estimator=estimator,
            max_tokens=1000,
            chunk_size=100,
        )

        tool_large = create_rlm_tool(
            llm_client=llm_client,
            token_estimator=estimator,
            max_tokens=8000,
            chunk_size=1000,
        )

        content = "\n\n".join([f"Content {i}: " + "word " * 50 for i in range(30)])

        # Run concurrent queries with different tools
        results = await asyncio.gather(
            tool_small.execute(instruction="Small budget", content=content),
            tool_large.execute(instruction="Large budget", content=content),
        )

        # Both should succeed despite different budgets
        assert all(r.success for r in results)
```

---

### 1.3 Test Malformed Chunks
**File:** `/Users/bado/iccha/iccha_context_multi_agent/cemaf/tests/integration/rlm/test_rlm_large_context.py`

**Add to existing file:**
```python
@pytest.mark.asyncio
async def test_rlm_with_empty_chunks(self, compiler: PriorityContextCompiler) -> None:
    """Test handling of empty chunks in tuple."""
    chunks = (
        ContextChunk(chunk_id="chunk_0", content="", token_count=TokenCount(0)),
        ContextChunk(chunk_id="chunk_1", content="   ", token_count=TokenCount(0)),
        ContextChunk(
            chunk_id="chunk_2",
            content="Valid content here",
            token_count=TokenCount(50),
        ),
    )

    engine = DivideAndConquerQueryEngine(
        MockLLMClient(responses=["Result"]),
        compiler,
        max_depth=2
    )

    result = await engine.query(
        instruction="Test",
        chunks=chunks,
        budget=TokenBudget(max_tokens=1000),
    )

    # Should handle empty chunks gracefully
    # Either filter them out or process successfully
    assert result.success is True or "empty" in result.error.lower()


@pytest.mark.asyncio
async def test_rlm_zero_token_budget(
    self, llm_client: MockLLMClient, compiler: PriorityContextCompiler
) -> None:
    """Test behavior with zero token budget."""
    chunks = (
        ContextChunk(
            chunk_id="chunk_0",
            content="Some content",
            token_count=TokenCount(100),
        ),
    )

    engine = DivideAndConquerQueryEngine(llm_client, compiler)

    result = await engine.query(
        instruction="Test",
        chunks=chunks,
        budget=TokenBudget(max_tokens=0),
    )

    # Should either fail gracefully or use fallback
    # But not crash or behave unexpectedly
    assert isinstance(result.success, bool)
    assert result.error is None or isinstance(result.error, str)
```

---

## Priority 2: High-Value Tests (Before Release)

### 2.1 Sentence Splitting Edge Cases
**File:** `/Users/bado/iccha/iccha_context_multi_agent/cemaf/tests/unit/rlm/test_chunking.py`

**Add to TestFixedSizeChunkingStrategy class:**
```python
def test_sentence_split_with_ellipsis(self) -> None:
    """Test sentence splitting with ellipsis."""
    strategy = FixedSizeChunkingStrategy(self.estimator, chunk_size=50)
    text = "Dr. Smith arrived... He looked tired."

    sentences = strategy._split_sentences(text)

    # Should properly handle ellipsis and abbreviations
    assert len(sentences) >= 1
    # Each sentence should be non-empty
    assert all(s.strip() for s in sentences)


def test_sentence_split_with_urls(self) -> None:
    """Test sentence splitting with URLs."""
    strategy = FixedSizeChunkingStrategy(self.estimator, chunk_size=100)
    text = "Visit example.com for details. Also see github.com/user/repo. Thanks!"

    sentences = strategy._split_sentences(text)

    # Should not split on dots in URLs
    assert len(sentences) == 3  # "Visit..." "Also..." "Thanks!"
    assert any("example.com" in s for s in sentences)


def test_sentence_split_with_quoted_text(self) -> None:
    """Test sentence splitting with quoted text."""
    strategy = FixedSizeChunkingStrategy(self.estimator, chunk_size=100)
    text = '"He said, "Hello. World."" Then he left.'

    sentences = strategy._split_sentences(text)

    # Should handle quotes with embedded periods
    assert len(sentences) >= 1
    assert all(s.strip() for s in sentences)


def test_sentence_split_with_abbreviations(self) -> None:
    """Test common English abbreviations."""
    strategy = FixedSizeChunkingStrategy(self.estimator, chunk_size=100)
    text = "Mr. Smith and Dr. Jones met. They discussed the U.S. economy."

    sentences = strategy._split_sentences(text)

    # Should not split on Mr., Dr., U.S. abbreviations
    assert len(sentences) == 2  # Two actual sentences
    assert "Mr. Smith" in sentences[0] or "Smith" in sentences[0]
```

---

## Priority 3: Nice-to-Have Tests

### 3.1 Parameter Validation
**File:** `/Users/bado/iccha/iccha_context_multi_agent/cemaf/tests/unit/rlm/test_engine.py`

```python
@pytest.mark.parametrize("invalid_depth", [-1, 0, 11, 100])
def test_invalid_max_depth(
    self,
    llm_client: MockLLMClient,
    compiler: PriorityContextCompiler,
    invalid_depth: int,
) -> None:
    """Test that invalid max_depth values are rejected."""
    with pytest.raises(ValueError):
        DivideAndConquerQueryEngine(llm_client, compiler, max_depth=invalid_depth)


def test_max_depth_boundaries(
    self,
    llm_client: MockLLMClient,
    compiler: PriorityContextCompiler,
) -> None:
    """Test max_depth boundary values."""
    # Should accept valid boundaries
    for valid_depth in [1, 5, 10]:
        engine = DivideAndConquerQueryEngine(
            llm_client, compiler, max_depth=valid_depth
        )
        assert engine._max_depth == valid_depth
```

---

## Test Execution Checklist

- [ ] Copy test code from Priority 1 sections above
- [ ] Add to appropriate test files
- [ ] Run: `uv run pytest tests/integration/rlm/ -v`
- [ ] Verify all 15+ new tests pass
- [ ] Check coverage increases to 98%+
- [ ] Commit with message: `test: add critical RLM failure path tests`

---

## Time Estimate

| Priority | Tests | Hours | Effort |
|----------|-------|-------|--------|
| 1 | 5-6 tests | 2-3 | Small |
| 2 | 6-8 tests | 2-3 | Small |
| 3 | 4-5 tests | 1-2 | Minimal |
| **Total** | **15-19 tests** | **12-18** | **2-3 days** |

---

## Success Criteria

- All 72 existing tests continue to pass ✓
- All new tests pass
- Code coverage reaches 98%+ for engine.py
- No flakiness in new tests (run 10x)
- New tests execute in < 200ms total
- Tests are clearly documented with docstrings
