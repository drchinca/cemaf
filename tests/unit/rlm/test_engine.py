"""
Unit tests for RLM query engine.

Tests recursive query execution with divide-and-conquer strategy.
"""

from collections.abc import Callable

import pytest

from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.types import TokenCount
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message, ToolDefinition
from cemaf.rlm.engine import DivideAndConquerQueryEngine
from cemaf.rlm.protocols import ContextChunk


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        """Initialize mock client with predefined responses."""
        self.responses = responses or ["Mock answer"]
        self.call_count = 0
        self.calls: list[list[Message]] = []

    @property
    def config(self) -> LLMConfig:
        """Get mock config."""
        return LLMConfig(model="mock", temperature=0.7)

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        """Mock completion."""
        del tools, config_override, fidelity, token_budget, correlation_id
        self.calls.append(messages)
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1

        return CompletionResult.ok(
            message=Message.assistant(response),
            prompt_tokens=10,
            completion_tokens=5,
            model="mock",
        )

    def count_tokens(self, text: str) -> TokenCount:
        """Mock token counting."""
        return TokenCount(len(text) // 4)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Mock message token counting."""
        total = sum(len(str(m.content)) for m in messages)
        return TokenCount(total // 4)


class PromptFailingLLMClient(MockLLMClient):
    """Mock LLM that fails when a prompt matches the configured predicate."""

    def __init__(
        self,
        should_fail: Callable[[str], bool],
        *,
        failure: str = "Injected LLM failure",
    ) -> None:
        super().__init__(responses=["Branch answer", "Aggregated answer"])
        self._should_fail = should_fail
        self._failure = failure

    async def complete(
        self,
        messages: list[Message],
        tools: list | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        prompt = "\n".join(str(message.content) for message in messages)
        self.calls.append(messages)
        self.call_count += 1
        if self._should_fail(prompt):
            return CompletionResult.fail(self._failure)
        return CompletionResult.ok(
            message=Message.assistant(f"Answer {self.call_count}"),
            prompt_tokens=10,
            completion_tokens=5,
            model="mock",
        )


class TestDivideAndConquerQueryEngine:
    """Tests for DivideAndConquerQueryEngine."""

    @pytest.fixture
    def estimator(self) -> SimpleTokenEstimator:
        """Create token estimator."""
        return SimpleTokenEstimator(chars_per_token=4.0)

    @pytest.fixture
    def compiler(self, estimator: SimpleTokenEstimator) -> PriorityContextCompiler:
        """Create context compiler."""
        return PriorityContextCompiler(estimator)

    @pytest.fixture
    def llm_client(self) -> MockLLMClient:
        """Create mock LLM client."""
        return MockLLMClient(responses=["Found result", "Aggregated answer"])

    @pytest.fixture
    def engine(
        self, llm_client: MockLLMClient, compiler: PriorityContextCompiler
    ) -> DivideAndConquerQueryEngine:
        """Create query engine."""
        return DivideAndConquerQueryEngine(llm_client, compiler, max_depth=3)

    def test_engine_initialization(
        self, llm_client: MockLLMClient, compiler: PriorityContextCompiler
    ) -> None:
        """Test engine initialization."""
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=5)
        assert engine._max_depth == 5

    @pytest.mark.asyncio
    async def test_empty_chunks(self, engine: DivideAndConquerQueryEngine) -> None:
        """Test querying with no chunks."""
        budget = TokenBudget(max_tokens=1000)
        result = await engine.query(
            instruction="Find X",
            chunks=(),
            budget=budget,
        )

        assert result.success is False
        assert "No chunks" in result.error

    @pytest.mark.asyncio
    async def test_single_chunk_within_budget(
        self, engine: DivideAndConquerQueryEngine, llm_client: MockLLMClient
    ) -> None:
        """Test single chunk that fits within budget."""
        chunk = ContextChunk(
            chunk_id="chunk_0",
            content="Small content",
            token_count=TokenCount(10),
        )

        budget = TokenBudget(max_tokens=10000)
        result = await engine.query(
            instruction="Summarize",
            chunks=(chunk,),
            budget=budget,
        )

        assert result.success is True
        assert result.answer is not None
        assert result.depth_reached == 0
        assert result.chunks_examined == 1
        assert result.llm_calls_made == 1
        assert llm_client.call_count == 1

    @pytest.mark.asyncio
    async def test_multiple_chunks_within_budget(
        self, engine: DivideAndConquerQueryEngine, llm_client: MockLLMClient
    ) -> None:
        """Test multiple chunks that fit within budget."""
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content=f"Content {i}",
                token_count=TokenCount(10),
            )
            for i in range(3)
        )

        budget = TokenBudget(max_tokens=10000)
        result = await engine.query(
            instruction="Find mentions",
            chunks=chunks,
            budget=budget,
        )

        assert result.success is True
        assert result.depth_reached == 0
        assert result.chunks_examined == 3
        assert result.llm_calls_made == 1

    @pytest.mark.asyncio
    async def test_recursive_query_exceeds_budget(
        self,
        engine: DivideAndConquerQueryEngine,
        llm_client: MockLLMClient,
        estimator: SimpleTokenEstimator,
    ) -> None:
        """Test recursive querying when chunks exceed budget."""
        large_content = "word " * 1000
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content=large_content,
                token_count=TokenCount(estimator.estimate(large_content)),
            )
            for i in range(4)
        )

        budget = TokenBudget(max_tokens=100)
        result = await engine.query(
            instruction="Analyze",
            chunks=chunks,
            budget=budget,
            max_depth=2,
        )

        assert result.success is True
        assert result.depth_reached > 0
        assert result.llm_calls_made > 1
        assert llm_client.call_count > 1

    @pytest.mark.asyncio
    async def test_recurses_when_subset_fits_budget(
        self,
        engine: DivideAndConquerQueryEngine,
        llm_client: MockLLMClient,
        estimator: SimpleTokenEstimator,
    ) -> None:
        """Regression: a budget where SOME but not all chunks fit must recurse.

        The compiler silently drops over-budget chunks, so `within_budget()`
        reports True on the surviving subset. Gating single-query on that alone
        would answer from a partial subset while claiming full coverage. The
        engine must instead recurse to preserve every chunk.
        """
        # Each chunk ~same size; budget admits roughly half of them.
        content = "word " * 50
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content=content,
                token_count=TokenCount(estimator.estimate(content)),
            )
            for i in range(4)
        )
        per_chunk = estimator.estimate(content)
        # available = max_tokens - reserved_for_output (4000). Size available so
        # the compiler keeps ~2 of 4 chunks: within_budget() is True on that
        # subset, but excluded_count > 0 — the exact condition where the old
        # gate single-queried a partial subset while claiming full coverage.
        budget = TokenBudget(max_tokens=4000 + per_chunk * 2 + 10)

        result = await engine.query(instruction="Analyze", chunks=chunks, budget=budget, max_depth=3)

        assert result.success is True
        # Recursion happened: not a single-shot answer over a dropped subset.
        assert result.metadata.get("strategy") != "single_query"
        assert result.depth_reached > 0
        # Every chunk was examined despite only a subset fitting at the top level.
        assert result.chunks_examined == 4

    @pytest.mark.asyncio
    async def test_max_depth_enforcement(
        self,
        engine: DivideAndConquerQueryEngine,
        estimator: SimpleTokenEstimator,
    ) -> None:
        """Test that max depth is enforced."""
        large_content = "word " * 1000
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content=large_content,
                token_count=TokenCount(estimator.estimate(large_content)),
            )
            for i in range(8)
        )

        budget = TokenBudget(max_tokens=50)
        result = await engine.query(
            instruction="Search",
            chunks=chunks,
            budget=budget,
            max_depth=1,
        )

        assert result.success is True
        assert result.depth_reached <= 1

    @pytest.mark.asyncio
    async def test_result_metadata(self, engine: DivideAndConquerQueryEngine) -> None:
        """Test that result includes proper metadata."""
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content="Content",
                token_count=TokenCount(5),
            )
            for i in range(2)
        )

        budget = TokenBudget(max_tokens=10000)
        result = await engine.query(
            instruction="Test",
            chunks=chunks,
            budget=budget,
        )

        assert "strategy" in result.metadata
        assert result.total_tokens_used > TokenCount(0)

    @pytest.mark.asyncio
    async def test_llm_failure_handling(self, compiler: PriorityContextCompiler) -> None:
        """Test handling of LLM failures."""

        class FailingLLMClient:
            @property
            def config(self) -> LLMConfig:
                return LLMConfig(model="mock")

            async def complete(
                self,
                messages: list[Message],
                tools: list[ToolDefinition] | None = None,
                config_override: LLMConfig | None = None,
                *,
                fidelity: object | None = None,
                token_budget: object | None = None,
                correlation_id: str | None = None,
            ) -> CompletionResult:
                del messages, tools, config_override, fidelity, token_budget, correlation_id
                return CompletionResult.fail("LLM error")

            def count_tokens(self, text: str) -> TokenCount:
                return TokenCount(len(text) // 4)

            def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
                return TokenCount(10)

        engine = DivideAndConquerQueryEngine(FailingLLMClient(), compiler)  # type: ignore[arg-type]
        chunks = (ContextChunk(chunk_id="chunk_0", content="Test", token_count=TokenCount(5)),)

        budget = TokenBudget(max_tokens=10000)
        result = await engine.query(
            instruction="Test",
            chunks=chunks,
            budget=budget,
        )

        # LLM failures should now return failure, not success with error message
        assert result.success is False
        assert result.error is not None
        assert "LLM error" in result.error

    @pytest.mark.asyncio
    async def test_recursive_left_branch_failure_propagates(self, compiler: PriorityContextCompiler) -> None:
        """Failure below the left recursive branch returns a failed query result."""
        llm_client = PromptFailingLLMClient(
            lambda prompt: "[Chunk left_fail]" in prompt,
            failure="left branch unavailable",
        )
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=2)
        chunks = (
            ContextChunk(chunk_id="left_fail", content="left failure content", token_count=TokenCount(500)),
            ContextChunk(chunk_id="left_ok", content="left ok content", token_count=TokenCount(500)),
            ContextChunk(chunk_id="right_ok_1", content="right ok content", token_count=TokenCount(500)),
            ContextChunk(chunk_id="right_ok_2", content="right ok content", token_count=TokenCount(500)),
        )

        result = await engine.query(
            instruction="Analyze branches",
            chunks=chunks,
            budget=TokenBudget(max_tokens=100),
            max_depth=2,
        )

        assert result.success is False
        assert result.error is not None
        assert "left branch unavailable" in result.error
        assert result.metadata.get("strategy") == "partial_coverage"

    @pytest.mark.asyncio
    async def test_recursive_right_branch_failure_propagates(self, compiler: PriorityContextCompiler) -> None:
        """Failure below the right recursive branch returns a failed query result."""
        llm_client = PromptFailingLLMClient(
            lambda prompt: "[Chunk right_fail]" in prompt,
            failure="right branch unavailable",
        )
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=2)
        chunks = (
            ContextChunk(chunk_id="left_ok_1", content="left ok content", token_count=TokenCount(500)),
            ContextChunk(chunk_id="left_ok_2", content="left ok content", token_count=TokenCount(500)),
            ContextChunk(chunk_id="right_fail", content="right failure content", token_count=TokenCount(500)),
            ContextChunk(chunk_id="right_ok", content="right ok content", token_count=TokenCount(500)),
        )

        result = await engine.query(
            instruction="Analyze branches",
            chunks=chunks,
            budget=TokenBudget(max_tokens=100),
            max_depth=2,
        )

        assert result.success is False
        assert result.error is not None
        assert "right branch unavailable" in result.error
        assert result.metadata.get("strategy") == "partial_coverage"

    @pytest.mark.asyncio
    async def test_recursive_aggregation_failure_returns_partial_success_metadata(
        self, compiler: PriorityContextCompiler
    ) -> None:
        """Aggregation failure keeps partial answers but records fallback metadata."""
        llm_client = PromptFailingLLMClient(
            lambda prompt: "two parts of the context" in prompt,
            failure="aggregator unavailable",
        )
        engine = DivideAndConquerQueryEngine(llm_client, compiler, max_depth=2)
        chunks = (
            ContextChunk(chunk_id="left_ok", content="left ok content", token_count=TokenCount(500)),
            ContextChunk(chunk_id="right_ok", content="right ok content", token_count=TokenCount(500)),
        )

        result = await engine.query(
            instruction="Synthesize branches",
            chunks=chunks,
            budget=TokenBudget(max_tokens=100),
            max_depth=2,
        )

        assert result.success is True
        assert result.answer is not None
        assert "Aggregation failed: aggregator unavailable" in result.answer
        assert result.metadata["strategy"] == "divide_and_conquer"
        assert result.metadata["aggregation_success"] is False
        assert result.metadata["aggregation_error"] == "aggregator unavailable"

    @pytest.mark.asyncio
    async def test_token_usage_tracking(self, engine: DivideAndConquerQueryEngine) -> None:
        """Test that token usage is tracked accurately."""
        chunks = tuple(
            ContextChunk(
                chunk_id=f"chunk_{i}",
                content="Content",
                token_count=TokenCount(5),
            )
            for i in range(2)
        )

        budget = TokenBudget(max_tokens=10000)
        result = await engine.query(
            instruction="Analyze",
            chunks=chunks,
            budget=budget,
        )

        assert result.total_tokens_used > TokenCount(0)
        assert isinstance(result.total_tokens_used, int)
