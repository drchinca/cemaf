"""Resilient LLM client wrapper composing retry, circuit breaker, and rate limiter."""

import logging
from collections.abc import AsyncIterator, Awaitable
from enum import StrEnum
from time import perf_counter
from typing import Any, cast

from cemaf.core.types import FinishReason, TokenCount
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


class QuerySource(StrEnum):
    """Controls retry budget based on call criticality."""

    FOREGROUND = "foreground"
    BACKGROUND = "background"


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
        fallback_model: str | None = None,
        fallback_after_failures: int = 3,
    ) -> None:
        self._client = client
        self._retry = retry
        self._circuit_breaker = circuit_breaker
        self._rate_limiter = rate_limiter
        self._metrics = metrics
        self._fallback_model = fallback_model
        self._fallback_after_failures = fallback_after_failures
        self._consecutive_failures: int = 0

    @property
    def config(self) -> LLMConfig:
        """Delegate to inner client config."""
        return self._client.config

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config_override: LLMConfig | None = None,
        source: QuerySource = QuerySource.FOREGROUND,
        *,
        fidelity: object | None = None,
        token_budget: object | None = None,
        correlation_id: str | None = None,
    ) -> CompletionResult:
        """Complete with rate_limit -> circuit_breaker -> retry -> client.complete."""
        start = perf_counter()

        try:
            if self._rate_limiter is not None:
                await self._rate_limiter.acquire()
        except RateLimitExceeded as exc:
            self._record_error(operation="llm.complete", error=exc)
            return CompletionResult.fail(error=f"Rate limit exceeded: {exc}")

        effective_config = self._resolve_config_override(config_override=config_override)

        async def _inner_complete() -> CompletionResult:
            return await self._client.complete(
                messages=messages,
                tools=tools,
                config_override=effective_config,
                fidelity=fidelity,
                token_budget=token_budget,
                correlation_id=correlation_id,
            )

        async def _with_circuit_breaker() -> CompletionResult:
            if self._circuit_breaker is not None:
                return await self._circuit_breaker.execute(_inner_complete)
            return await _inner_complete()

        try:
            use_retry = self._retry is not None and source == QuerySource.FOREGROUND
            if use_retry:
                retry_result = await self._retry.execute(_with_circuit_breaker)  # type: ignore[union-attr]
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

        self._track_consecutive_failures(success=result.success)

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
        try:
            if self._rate_limiter is not None:
                await self._rate_limiter.acquire()
        except RateLimitExceeded as exc:
            self._record_error(operation="llm.stream", error=exc)
            self._track_consecutive_failures(success=False)
            yield StreamChunk(
                content=f"Rate limit exceeded: {exc}",
                finish_reason=FinishReason.PARTIAL_ERROR,
                is_final=True,
            )
            return

        async def _inner_stream() -> AsyncIterator[StreamChunk]:
            stream_result: Any = self._client.stream(
                messages=messages,
                tools=tools,
                config_override=config_override,
            )
            if hasattr(stream_result, "__aiter__"):
                return cast(AsyncIterator[StreamChunk], stream_result)
            return await cast(Awaitable[AsyncIterator[StreamChunk]], stream_result)

        accumulated = ""
        failed = False
        try:
            if self._circuit_breaker is not None:
                stream = await self._circuit_breaker.execute(_inner_stream)
            else:
                stream = await _inner_stream()

            async for chunk in stream:
                accumulated = chunk.accumulated_content or accumulated + chunk.content
                failed = failed or chunk.finish_reason is FinishReason.PARTIAL_ERROR
                yield chunk
        except CircuitOpenError as exc:
            self._record_error(operation="llm.stream", error=exc)
            self._track_consecutive_failures(success=False)
            yield StreamChunk(
                content=f"Circuit breaker open: {exc}",
                finish_reason=FinishReason.PARTIAL_ERROR,
                is_final=True,
                accumulated_content=accumulated,
            )
            return
        except Exception as exc:
            self._record_error(operation="llm.stream", error=exc)
            self._track_consecutive_failures(success=False)
            yield StreamChunk(
                content=f"LLM stream failed: {exc}",
                finish_reason=FinishReason.PARTIAL_ERROR,
                is_final=True,
                accumulated_content=accumulated,
            )
            return

        self._track_consecutive_failures(success=not failed)

    def count_tokens(self, text: str) -> TokenCount:
        """Delegate token counting to inner client."""
        return self._client.count_tokens(text=text)

    def count_messages_tokens(self, messages: list[Message]) -> TokenCount:
        """Delegate message token counting to inner client."""
        return self._client.count_messages_tokens(messages=messages)

    async def count_tokens_exact(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> TokenCount:
        """Delegate exact token counting to inner client."""
        return await self._client.count_tokens_exact(messages=messages, tools=tools)

    def _resolve_config_override(self, *, config_override: LLMConfig | None) -> LLMConfig | None:
        """Apply fallback model when consecutive failures exceed threshold."""
        if self._fallback_model is not None and self._consecutive_failures >= self._fallback_after_failures:
            base = config_override or self._client.config
            logger.warning(
                "Falling back to %s after %d consecutive failures",
                self._fallback_model,
                self._consecutive_failures,
            )
            return base.model_copy(update={"model": self._fallback_model})
        return config_override

    def _track_consecutive_failures(self, *, success: bool) -> None:
        """Update consecutive failure counter."""
        if success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1

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
    fallback_model: str | None = None,
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
        fallback_model=fallback_model,
    )
