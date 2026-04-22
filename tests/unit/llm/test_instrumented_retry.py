"""Tests for error handling and retry in InstrumentedLLMClient."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from cemaf.core.types import TokenCount
from cemaf.llm.instrumented import InstrumentedLLMClient
from cemaf.llm.protocols import (
    CompletionResult,
    LLMConfig,
    Message,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.run_logger import InMemoryRunLogger, LLMCall
from cemaf.resilience.retry import BackoffStrategy, RetryConfig, RetryPolicy


def _make_mock_client(
    complete_side_effect: list | None = None,
    complete_return: CompletionResult | None = None,
) -> MagicMock:
    """Build a mock LLM client with configurable behavior."""
    client = MagicMock()
    type(client).config = PropertyMock(return_value=LLMConfig(model="test-model", temperature=0.0))

    if complete_side_effect is not None:
        client.complete = AsyncMock(side_effect=complete_side_effect)
    elif complete_return is not None:
        client.complete = AsyncMock(return_value=complete_return)
    else:
        client.complete = AsyncMock(return_value=CompletionResult(success=True))

    client.count_tokens = MagicMock(return_value=TokenCount(10))
    client.count_messages_tokens = MagicMock(return_value=TokenCount(20))
    return client


def _success_result() -> CompletionResult:
    return CompletionResult(success=True, model="test-model")


class TestCompleteRecordsOnError:
    """Verify telemetry is recorded even when the inner client raises."""

    @pytest.mark.asyncio
    async def test_complete_records_on_error(self) -> None:
        """LLMCall with error info is recorded when complete() raises."""
        mock_client = _make_mock_client(complete_side_effect=[ConnectionError("LLM unavailable")])
        run_logger = InMemoryRunLogger()
        run_logger.start_run(run_id="test-run")

        instrumented = InstrumentedLLMClient(
            client=mock_client,
            run_logger=run_logger,
        )

        messages = [Message.user("Hello")]
        with pytest.raises(ConnectionError, match="LLM unavailable"):
            await instrumented.complete(messages=messages)

        # Verify telemetry was recorded despite the error
        assert len(run_logger._current.llm_calls) == 1
        recorded: LLMCall = run_logger._current.llm_calls[0]
        assert recorded.error == "LLM unavailable"
        assert recorded.output == ""
        assert recorded.model == "test-model"


class TestCompleteRetriesWithPolicy:
    """Verify retry_policy retries the inner call on transient failure."""

    @pytest.mark.asyncio
    async def test_complete_retries_with_policy(self) -> None:
        """LLM fails once then succeeds; retry policy handles it."""
        success = _success_result()
        mock_client = _make_mock_client(complete_side_effect=[ConnectionError("transient"), success])
        run_logger = InMemoryRunLogger()
        run_logger.start_run(run_id="test-run")

        retry_policy = RetryPolicy(
            RetryConfig(
                max_attempts=3,
                initial_delay_seconds=0.001,
                jitter=False,
                backoff_strategy=BackoffStrategy.CONSTANT,
            )
        )

        instrumented = InstrumentedLLMClient(
            client=mock_client,
            run_logger=run_logger,
            retry_policy=retry_policy,
        )

        messages = [Message.user("Hello")]
        result = await instrumented.complete(messages=messages)

        assert result.success
        assert mock_client.complete.call_count == 2
        # Success path records one LLMCall (no error)
        assert len(run_logger._current.llm_calls) == 1
        assert run_logger._current.llm_calls[0].error is None


class TestStreamRecordsOnError:
    """Verify partial telemetry is recorded when stream() fails mid-stream."""

    @pytest.mark.asyncio
    async def test_stream_records_on_error(self) -> None:
        """LLMCall is recorded with error when stream iteration raises."""
        mock_client = MagicMock()
        type(mock_client).config = PropertyMock(return_value=LLMConfig(model="test-model", temperature=0.0))

        async def _failing_stream(
            messages: list[Message],
            tools: list[ToolDefinition] | None = None,
            config_override: LLMConfig | None = None,
        ) -> AsyncIterator[StreamChunk]:
            yield StreamChunk(content="partial ", accumulated_content="partial ")
            raise RuntimeError("stream interrupted")

        mock_client.stream = _failing_stream
        mock_client.count_tokens = MagicMock(return_value=TokenCount(10))
        mock_client.count_messages_tokens = MagicMock(return_value=TokenCount(20))

        run_logger = InMemoryRunLogger()
        run_logger.start_run(run_id="test-run")

        instrumented = InstrumentedLLMClient(
            client=mock_client,
            run_logger=run_logger,
        )

        messages = [Message.user("Hello")]
        chunks: list[StreamChunk] = []

        with pytest.raises(RuntimeError, match="stream interrupted"):
            async for chunk in instrumented.stream(messages=messages):
                chunks.append(chunk)

        # Partial chunk was yielded before error
        assert len(chunks) == 1
        assert chunks[0].content == "partial "

        # Telemetry recorded with error
        assert len(run_logger._current.llm_calls) == 1
        recorded: LLMCall = run_logger._current.llm_calls[0]
        assert recorded.error == "stream interrupted"
        assert recorded.output == "partial "
