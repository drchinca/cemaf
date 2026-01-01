"""
Unit tests for the AdvancedContextCompiler.
"""

from collections.abc import AsyncIterator  # New import
from typing import Any

import pytest

from cemaf.context.advanced_compiler import AdvancedContextCompiler
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import TokenEstimator
from cemaf.llm.protocols import CompletionResult, LLMClient, LLMConfig, Message


class MockTokenEstimator(TokenEstimator):
    def estimate(self, text: str) -> int:
        return len(text.split())  # Simple word count for testing


class MockLLMClient(LLMClient):
    def __init__(self, summaries: dict[str, str] | None = None, config: LLMConfig | None = None):
        self._summaries = summaries or {}
        self._config = config or LLMConfig(model="mock-llm")
        self.completion_calls = []

    @property
    def config(self) -> LLMConfig:
        return self._config

    async def complete(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        self.completion_calls.append((messages, tools, config_override))
        prompt_content = messages[0].content
        for key, summary_text in self._summaries.items():
            if key in prompt_content:  # Simple check to match summary to content
                return CompletionResult.ok(Message.system(summary_text), model=self.config.model)
        return CompletionResult.ok(Message.system("Default summary"), model=self.config.model)  # Fallback

    async def stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[Any]:
        # Not used for this compiler, but required by protocol
        if False:
            yield

    def count_tokens(self, text: str) -> int:
        return MockTokenEstimator().estimate(text)

    def count_messages_tokens(self, messages: list[Message]) -> int:
        return sum(self.count_tokens(m.content) for m in messages) + len(messages) * 4  # Basic overhead


@pytest.fixture
def mock_token_estimator() -> MockTokenEstimator:
    return MockTokenEstimator()


@pytest.fixture
def mock_llm_client(mock_token_estimator: MockTokenEstimator) -> MockLLMClient:
    return MockLLMClient(
        summaries={
            "very long content": "short summary",
            "another lengthy text": "brief",
            "important but lengthy": "concise",
        },
        config=LLMConfig(max_tokens=2000),  # Max tokens for LLM is larger than our test budget
    )


class TestAdvancedContextCompiler:
    @pytest.mark.asyncio
    async def test_no_summarization_if_within_budget(
        self, mock_llm_client: MockLLMClient, mock_token_estimator: MockTokenEstimator
    ):
        """Context should be compiled normally if it fits the budget."""
        compiler = AdvancedContextCompiler(llm_client=mock_llm_client, token_estimator=mock_token_estimator)

        artifacts = (
            ("brief", "short and sweet brief"),  # 4 tokens
        )
        memories = (
            ("mem1", "relevant memory snippet"),  # 3 tokens
        )
        budget = TokenBudget(max_tokens=10, reserved_for_output=0)  # Ensure a positive available_tokens

        compiled_context = await compiler.compile(artifacts, memories, budget)

        assert compiled_context.within_budget()
        assert len(compiled_context.sources) == 2
        assert mock_llm_client.completion_calls == []  # No LLM calls made

    @pytest.mark.asyncio
    async def test_summarization_when_budget_exceeded(
        self, mock_llm_client: MockLLMClient, mock_token_estimator: MockTokenEstimator
    ):
        """Compiler should attempt to summarize sources when budget is exceeded."""
        compiler = AdvancedContextCompiler(llm_client=mock_llm_client, token_estimator=mock_token_estimator)

        artifacts = (
            ("brief", "important brief content"),  # 3 tokens
        )
        memories = (
            ("long_mem", "this is a very long content that needs summarization"),  # 8 tokens
        )
        budget = TokenBudget(max_tokens=10, reserved_for_output=0)

        compiled_context = await compiler.compile(
            artifacts, memories, budget, priorities={"brief": 10, "long_mem": 0}
        )
        assert compiled_context.total_tokens <= budget.available_tokens
        assert len(compiled_context.sources) == 2  # brief + summarized long_mem

        # Check that summarization happened for 'long_mem'
        summarized_source = next(s for s in compiled_context.sources if "summarized_long_mem" in s.key)
        assert summarized_source.content == "short summary"  # From mock
        assert mock_llm_client.completion_calls  # LLM call should have been made

    @pytest.mark.asyncio
    async def test_prioritization_for_summarization(
        self, mock_llm_client: MockLLMClient, mock_token_estimator: MockTokenEstimator
    ):
        """Lower priority items should be summarized first."""
        compiler = AdvancedContextCompiler(llm_client=mock_llm_client, token_estimator=mock_token_estimator)

        # Budget just enough for high_prio_art + summaries of others
        budget = TokenBudget(max_tokens=8, reserved_for_output=0)

        compiled_context = await compiler.compile(
            artifacts=(
                ("high_prio_art", "critical data for the LLM"),
                ("low_prio_art", "another lengthy text that can be summarized"),
            ),
            memories=(("very_low_prio_mem", "important but lengthy memory, summarize this first"),),
            budget=budget,
            priorities={"high_prio_art": 100, "low_prio_art": 0, "very_low_prio_mem": -10},
        )
        assert compiled_context.total_tokens <= budget.available_tokens

        # high_prio_art should be untouched
        assert any(s.key == "high_prio_art" for s in compiled_context.sources)
        assert not any("summarized_high_prio_art" in s.key for s in compiled_context.sources)

        # very_low_prio_mem should be summarized first (due to lower priority)
        assert any("summarized_very_low_prio_mem" in s.key for s in compiled_context.sources)
        assert (
            next(s for s in compiled_context.sources if "summarized_very_low_prio_mem" in s.key).content
            == "concise"
        )

        # low_prio_art should also be summarized
        assert any("summarized_low_prio_art" in s.key for s in compiled_context.sources)
        assert (
            next(s for s in compiled_context.sources if "summarized_low_prio_art" in s.key).content == "brief"
        )

        assert mock_llm_client.completion_calls  # LLM calls should have been made

    @pytest.mark.asyncio
    async def test_llm_summarization_failure_skips_source(
        self, mock_llm_client: MockLLMClient, mock_token_estimator: MockTokenEstimator
    ):
        """If LLM summarization fails for a source, it should be skipped."""
        # Configure mock_llm_client to fail for a specific content
        failing_llm_client = MockLLMClient(
            summaries={"another lengthy text": "brief summary"},  # For other_mem
            config=LLMConfig(model="mock-llm"),
        )

        # Simulate LLM returning a failure result for a specific prompt
        original_complete = failing_llm_client.complete

        async def failing_complete(messages: list[Message], **kwargs):
            if any("this is a failing content that needs summarization" in m.content for m in messages):
                return CompletionResult.fail("LLM error")
            return await original_complete(messages, **kwargs)

        failing_llm_client.complete = failing_complete

        compiler = AdvancedContextCompiler(
            llm_client=failing_llm_client, token_estimator=mock_token_estimator
        )

        artifacts = (
            ("brief", "important brief content"),  # 3 tokens
        )
        memories = (
            ("long_mem", "this is a failing content that needs summarization"),  # 7 tokens
            ("other_mem", "another lengthy text"),  # 3 tokens
        )
        # Total: 3 + 7 + 3 = 13 tokens, but budget is only 5, so summarization needed
        budget = TokenBudget(max_tokens=5, reserved_for_output=0)

        compiled_context = await compiler.compile(artifacts, memories, budget)

        assert compiled_context.total_tokens <= budget.available_tokens
        # 'brief' should be there, 'other_mem' summarized, 'long_mem' skipped
        assert len(compiled_context.sources) == 2
        assert any(s.key == "brief" for s in compiled_context.sources)
        assert any(s.key == "summarized_other_mem" for s in compiled_context.sources)
        assert not any(
            "failing content" in s.content for s in compiled_context.sources
        )  # Ensure failed content is not present
        assert not any(
            "summarized_long_mem" in s.key for s in compiled_context.sources
        )  # Ensure failed content is not present

        assert failing_llm_client.completion_calls  # LLM calls should have been made
