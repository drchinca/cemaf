"""Unit tests for BatchLLMClient protocol fallbacks."""

import inspect

import pytest

from cemaf.core.types import FinishReason, LLMProvider, TokenCount
from cemaf.llm.batch_client import BatchLLMClient
from cemaf.llm.factories import create_batch_client
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message, ToolCall, ToolDefinition


class _ImmediateBatchClient(BatchLLMClient):
    def __init__(self, result: CompletionResult) -> None:
        self._result = result
        self._config = LLMConfig(model="batch-test")

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
        return self._result


def test_create_batch_client_requires_explicit_provider_model() -> None:
    signature = inspect.signature(create_batch_client)

    assert signature.parameters["model"].default is inspect.Signature.empty


@pytest.mark.asyncio
async def test_stream_falls_back_to_completed_result() -> None:
    tool_call = ToolCall(id="call_1", name="search", arguments={"q": "cemaf"})
    result = CompletionResult.ok(
        message=Message.assistant("batch response", tool_calls=(tool_call,)),
        prompt_tokens=7,
        completion_tokens=3,
        model="claude-sonnet-4-6",
        finish_reason=FinishReason.TERMINAL_TOOL,
        provider=LLMProvider.ANTHROPIC,
    )
    client = _ImmediateBatchClient(result)

    chunks = [chunk async for chunk in client.stream([Message.user("hello")])]

    assert len(chunks) == 2
    assert chunks[0].content == "batch response"
    assert chunks[0].accumulated_content == "batch response"
    assert chunks[1].is_final is True
    assert chunks[1].accumulated_content == "batch response"
    assert chunks[1].tool_calls == (tool_call,)
    assert chunks[1].prompt_tokens == TokenCount(7)
    assert chunks[1].completion_tokens == TokenCount(3)


@pytest.mark.asyncio
async def test_stream_failure_yields_final_error_chunk() -> None:
    client = _ImmediateBatchClient(CompletionResult.fail("batch failed"))

    chunks = [chunk async for chunk in client.stream([Message.user("hello")])]

    assert len(chunks) == 1
    assert chunks[0].is_final is True
    assert chunks[0].finish_reason is FinishReason.PARTIAL_ERROR


@pytest.mark.asyncio
async def test_count_tokens_exact_uses_local_estimate_with_tools() -> None:
    client = _ImmediateBatchClient(CompletionResult.fail("unused"))
    messages = [Message.system("system prompt"), Message.user("hello")]
    tools = [
        ToolDefinition(
            name="search",
            description="Search docs",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            required=("query",),
        )
    ]

    result = await client.count_tokens_exact(messages=messages, tools=tools)

    assert result > client.count_messages_tokens(messages)
