"""Concurrency regression tests for RLM query execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.core.types import FinishReason, TokenCount
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message, StreamChunk, ToolDefinition
from cemaf.rlm import create_rlm_tool


class YieldingLLMClient:
    """Mock LLM that yields control so concurrent RLM calls genuinely interleave."""

    def __init__(self) -> None:
        self._call_count = 0
        self._calls: list[list[Message]] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(model="yielding-mock")

    @property
    def call_count(self) -> int:
        return self._call_count

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        await asyncio.sleep(0)
        self._calls.append(list(messages))
        self._call_count += 1
        return CompletionResult.ok(
            message=Message.assistant(f"answer-{self._call_count}"),
            prompt_tokens=10,
            completion_tokens=5,
            model=self.config.model,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(
            content="answer",
            accumulated_content="answer",
            is_final=True,
            finish_reason=FinishReason.TERMINAL_STOP,
        )

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        return self.count_messages_tokens(messages)

    def count_tokens(self, text: str) -> TokenCount:
        return TokenCount(max(1, len(text) // 4))

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        return TokenCount(sum(self.count_tokens(str(message.content)) for message in messages))


@pytest.mark.asyncio
async def test_shared_rlm_tool_handles_concurrent_queries() -> None:
    """A shared RLMQueryTool should not leak per-query state under load."""
    llm_client = YieldingLLMClient()
    tool = create_rlm_tool(
        llm_client=llm_client,
        token_estimator=SimpleTokenEstimator(chars_per_token=4.0),
        chunk_size=100,
        max_depth=3,
        max_tokens=500,
    )
    content = "\n\n".join(f"Section {i}: " + "word " * 100 for i in range(12))

    async def run_query(index: int):
        return await tool.execute(
            instruction=f"Find evidence for query {index}",
            content=content,
        )

    results = await asyncio.gather(*(run_query(index) for index in range(24)))

    assert all(result.success for result in results)
    assert all(
        result.metadata["strategy"] in {"divide_and_conquer", "partial_coverage"} for result in results
    )
    assert all(result.metadata["chunks_examined"] > 0 for result in results)
    assert all(result.metadata["llm_calls_made"] > 1 for result in results)
    assert llm_client.call_count == sum(result.metadata["llm_calls_made"] for result in results)
