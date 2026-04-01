"""Tests for ResilientLLMClient wrapper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import CompletionResult, LLMConfig, Message, MessageRole, StreamChunk
from cemaf.llm.resilient import QuerySource, ResilientLLMClient
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter
from cemaf.resilience.retry import RetryConfig, RetryPolicy


def _make_message(content: str = "hello") -> Message:
    return Message(role=MessageRole.ASSISTANT, content=content)


def _make_result(*, success: bool = True, content: str = "hello") -> CompletionResult:
    if success:
        return CompletionResult.ok(
            message=_make_message(content=content),
            model="test-model",
            prompt_tokens=10,
            completion_tokens=5,
        )
    return CompletionResult.fail(error="boom")


def _mock_client(*, result: CompletionResult | None = None) -> AsyncMock:
    client = AsyncMock()
    client.config = LLMConfig(model="test-model")
    client.complete = AsyncMock(return_value=result or _make_result())
    client.stream = AsyncMock(return_value=AsyncMock())
    client.count_tokens = MagicMock(return_value=TokenCount(10))
    client.count_messages_tokens = MagicMock(return_value=TokenCount(20))
    return client


@pytest.mark.asyncio
async def test_successful_call_delegates() -> None:
    """Normal call passes through to inner client."""
    inner = _mock_client()
    resilient = ResilientLLMClient(client=inner)
    messages = [Message.user(content="hi")]

    result = await resilient.complete(messages=messages)

    assert result.success is True
    assert result.content == "hello"
    inner.complete.assert_awaited_once_with(
        messages=messages,
        tools=None,
        config_override=None,
    )


@pytest.mark.asyncio
async def test_retry_on_failure() -> None:
    """Client fails twice then succeeds on third attempt."""
    inner = _mock_client()
    call_count = 0

    async def _failing_complete(**kwargs: object) -> CompletionResult:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient")
        return _make_result()

    inner.complete = AsyncMock(side_effect=_failing_complete)
    retry = RetryPolicy(
        config=RetryConfig(
            max_attempts=3,
            initial_delay_seconds=0.01,
            jitter=False,
        ),
    )
    resilient = ResilientLLMClient(client=inner, retry=retry)

    result = await resilient.complete(messages=[Message.user(content="hi")])

    assert result.success is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_circuit_breaker_opens() -> None:
    """After threshold failures, circuit opens and returns fail result."""
    inner = _mock_client()
    inner.complete = AsyncMock(side_effect=ConnectionError("down"))
    cb = CircuitBreaker(config=CircuitConfig(failure_threshold=5))
    resilient = ResilientLLMClient(client=inner, circuit_breaker=cb)

    # Trip the circuit with 5 failures
    for _ in range(5):
        result = await resilient.complete(messages=[Message.user(content="hi")])
        assert result.success is False

    # Next call should get CircuitOpenError -> CompletionResult.fail
    result = await resilient.complete(messages=[Message.user(content="hi")])
    assert result.success is False
    assert "Circuit breaker open" in (result.error or "")


@pytest.mark.asyncio
async def test_rate_limiter_applied() -> None:
    """Rate limiter acquire is called before client.complete."""
    inner = _mock_client()
    rl = RateLimiter(config=RateLimitConfig(rate=100.0, burst=100))
    resilient = ResilientLLMClient(client=inner, rate_limiter=rl)

    with patch.object(rl, "acquire", new_callable=AsyncMock, return_value=True) as mock_acquire:
        result = await resilient.complete(messages=[Message.user(content="hi")])

    mock_acquire.assert_awaited_once()
    assert result.success is True


@pytest.mark.asyncio
async def test_metrics_recorded() -> None:
    """MetricsHelper.record_llm_call is invoked on success."""
    inner = _mock_client()
    metrics = MagicMock()
    resilient = ResilientLLMClient(client=inner, metrics=metrics)

    with patch("cemaf.llm.resilient.MetricsHelper.record_llm_call") as mock_record:
        await resilient.complete(messages=[Message.user(content="hi")])

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args
    assert call_kwargs.kwargs["success"] is True
    assert call_kwargs.kwargs["model"] == "test-model"


@pytest.mark.asyncio
async def test_stream_no_retry() -> None:
    """Stream delegates directly without retry wrapper."""
    inner = _mock_client()

    async def _fake_stream(**kwargs: object) -> list[StreamChunk]:
        return [StreamChunk(content="chunk")]

    inner.stream = AsyncMock(side_effect=_fake_stream)
    retry = RetryPolicy(config=RetryConfig(max_attempts=3))
    resilient = ResilientLLMClient(client=inner, retry=retry)

    with patch.object(retry, "execute", new_callable=AsyncMock) as mock_retry_exec:
        await resilient.stream(messages=[Message.user(content="hi")])

    # Retry.execute should NOT be called for stream
    mock_retry_exec.assert_not_awaited()
    inner.stream.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_tokens_delegates() -> None:
    """Token counting delegates directly."""
    inner = _mock_client()
    resilient = ResilientLLMClient(client=inner)

    assert resilient.count_tokens(text="hello") == TokenCount(10)
    assert resilient.count_messages_tokens(messages=[]) == TokenCount(20)


@pytest.mark.asyncio
async def test_config_delegates() -> None:
    """Config property delegates to inner client."""
    inner = _mock_client()
    resilient = ResilientLLMClient(client=inner)

    assert resilient.config.model == "test-model"


# --- Model fallback tests ---


@pytest.mark.asyncio
async def test_fallback_model_activates_after_consecutive_failures() -> None:
    """After N failures, subsequent calls use the fallback model config."""
    inner = _mock_client(result=_make_result(success=False))
    resilient = ResilientLLMClient(
        client=inner,
        fallback_model="gpt-3.5-turbo",
        fallback_after_failures=2,
    )

    # Two failures to cross the threshold
    await resilient.complete(messages=[Message.user(content="hi")])
    await resilient.complete(messages=[Message.user(content="hi")])

    assert resilient._consecutive_failures == 2

    # Third call should use fallback model in config_override
    await resilient.complete(messages=[Message.user(content="hi")])

    last_call = inner.complete.call_args
    override: LLMConfig = last_call.kwargs["config_override"]
    assert override.model == "gpt-3.5-turbo"


@pytest.mark.asyncio
async def test_fallback_resets_on_success() -> None:
    """A successful call resets the failure counter, stopping fallback."""
    call_count = 0

    async def _alternate(**kwargs: object) -> CompletionResult:
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            return _make_result(success=False)
        return _make_result(success=True)

    inner = _mock_client()
    inner.complete = AsyncMock(side_effect=_alternate)
    resilient = ResilientLLMClient(
        client=inner,
        fallback_model="gpt-3.5-turbo",
        fallback_after_failures=3,
    )

    # 3 failures
    for _ in range(3):
        await resilient.complete(messages=[Message.user(content="hi")])
    assert resilient._consecutive_failures == 3

    # 4th call succeeds (using fallback), resets counter
    await resilient.complete(messages=[Message.user(content="hi")])
    assert resilient._consecutive_failures == 0


@pytest.mark.asyncio
async def test_no_fallback_when_not_configured() -> None:
    """Without fallback_model, config_override stays None."""
    inner = _mock_client(result=_make_result(success=False))
    resilient = ResilientLLMClient(client=inner)

    for _ in range(5):
        await resilient.complete(messages=[Message.user(content="hi")])

    last_call = inner.complete.call_args
    assert last_call.kwargs["config_override"] is None


# --- Source-aware retry gating tests ---


@pytest.mark.asyncio
async def test_background_source_skips_retry() -> None:
    """BACKGROUND queries bypass retry entirely."""
    inner = _mock_client()
    inner.complete = AsyncMock(side_effect=ConnectionError("down"))
    retry = RetryPolicy(
        config=RetryConfig(max_attempts=3, initial_delay_seconds=0.01, jitter=False),
    )
    resilient = ResilientLLMClient(client=inner, retry=retry)

    with patch.object(retry, "execute", new_callable=AsyncMock) as mock_retry_exec:
        result = await resilient.complete(
            messages=[Message.user(content="hi")],
            source=QuerySource.BACKGROUND,
        )

    # Retry.execute should NOT be called for background
    mock_retry_exec.assert_not_awaited()
    assert result.success is False


@pytest.mark.asyncio
async def test_foreground_source_uses_retry() -> None:
    """FOREGROUND queries use retry as normal."""
    inner = _mock_client()
    retry = RetryPolicy(
        config=RetryConfig(max_attempts=3, initial_delay_seconds=0.01, jitter=False),
    )
    resilient = ResilientLLMClient(client=inner, retry=retry)

    result = await resilient.complete(
        messages=[Message.user(content="hi")],
        source=QuerySource.FOREGROUND,
    )

    assert result.success is True
