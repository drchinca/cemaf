"""Resilient LLM client wrapper composing retry, circuit breaker, and rate limiter."""

import logging
from collections.abc import AsyncIterator
from time import perf_counter

from cemaf.core.types import TokenCount
from cemaf.llm.protocols import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    Message,
    StreamChunk,
    ToolDefinition,
)
from cemaf.observability.metrics_helper import MetricsHelper
from cemaf.observability.protocols import MetricsCollector
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig, CircuitOpenError
from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter, RateLimitExceeded
from cemaf.resilience.retry import BackoffStrategy, RetryConfig, RetryPolicy

logger = logging.getLogger(__name__)


class ResilientLLMClient:
    """LLM client wrapper with retry, circuit breaker, and rate limiting."""

    def __init__(
        self,
        *,
        client: LLMClient,
        retry: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        rate_limiter: RateLimiter | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._client = client
        self._retry = retry
        self._circuit_breaker = circuit_breaker
        self._rate_limiter = rate_limiter
        self._metrics = metrics

    @property
    def config(self) -> LLMConfig:
        """Delegate to inner client config."""
        return self._client.config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> CompletionResult:
        """Complete with rate_limit -> circuit_breaker -> retry -> client.complete."""
        start = perf_counter()

        try:
            if self._rate_limiter is not None:
                await self._rate_limiter.acquire()
        except RateLimitExceeded as exc:
            self._record_error(operation="llm.complete", error=exc)
            return CompletionResult.fail(error=f"Rate limit exceeded: {exc}")

        async def _inner_complete() -> CompletionResult:
            return await self._client.complete(
                messages=messages,
                tools=tools,
                config_override=config_override,
            )

        async def _with_circuit_breaker() -> CompletionResult:
            if self._circuit_breaker is not None:
                return await self._circuit_breaker.execute(_inner_complete)
            return await _inner_complete()

        try:
            if self._retry is not None:
                retry_result = await self._retry.execute(_with_circuit_breaker)
                if retry_result.success:
                    result = retry_result.result
                else:
                    error_msg = str(retry_result.error) if retry_result.error else "All retry attempts failed"
                    result = CompletionResult.fail(error=error_msg)
            else:
                result = await _with_circuit_breaker()
        except CircuitOpenError as exc:
            self._record_error(operation="llm.complete", error=exc)
            return CompletionResult.fail(error=f"Circuit breaker open: {exc}")
        except Exception as exc:
            self._record_error(operation="llm.complete", error=exc)
            return CompletionResult.fail(error=f"LLM call failed: {exc}")

        duration_ms = (perf_counter() - start) * 1000
        completion_result: CompletionResult = result
        self._record_llm_metrics(result=completion_result, duration_ms=duration_ms)
        return completion_result

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream with rate_limit -> circuit_breaker -> client.stream (no retry)."""
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()

        async def _inner_stream() -> AsyncIterator[StreamChunk]:
            return await self._client.stream(
                messages=messages,
                tools=tools,
                config_override=config_override,
            )

        if self._circuit_breaker is not None:
            return await self._circuit_breaker.execute(_inner_stream)
        return await _inner_stream()

    def count_tokens(self, text: str) -> TokenCount:
        """Delegate token counting to inner client."""
        return self._client.count_tokens(text=text)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Delegate message token counting to inner client."""
        return self._client.count_messages_tokens(messages=messages)

    def _record_llm_metrics(self, *, result: CompletionResult, duration_ms: float) -> None:
        """Record LLM call metrics if collector available."""
        if self._metrics is None:
            return
        MetricsHelper.record_llm_call(
            metrics=self._metrics,
            model=result.model or self._client.config.model,
            prompt_tokens=int(result.prompt_tokens),
            completion_tokens=int(result.completion_tokens),
            duration_ms=duration_ms,
            success=result.success,
            finish_reason=result.finish_reason or None,
        )

    def _record_error(self, *, operation: str, error: Exception) -> None:
        """Record error metrics if collector available."""
        if self._metrics is None:
            return
        MetricsHelper.record_error(
            metrics=self._metrics,
            operation=f"cemaf.{operation}",
            error_type=type(error).__name__,
        )


def create_resilient_client(
    *,
    client: LLMClient,
    metrics: MetricsCollector | None = None,
) -> ResilientLLMClient:
    """Create ResilientLLMClient with sensible defaults."""
    return ResilientLLMClient(
        client=client,
        retry=RetryPolicy(
            config=RetryConfig(
                max_attempts=3,
                initial_delay_seconds=1.0,
                backoff_strategy=BackoffStrategy.EXPONENTIAL,
            ),
        ),
        circuit_breaker=CircuitBreaker(
            config=CircuitConfig(failure_threshold=5),
        ),
        rate_limiter=RateLimiter(
            config=RateLimitConfig(rate=10.0, burst=20),
        ),
        metrics=metrics,
    )
