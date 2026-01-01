"""
Retry policy - Configurable retry with backoff strategies.

Supports:
- Constant delay
- Exponential backoff
- Jitter
- Retry on specific exceptions
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

from cemaf.core.utils import utc_now


class BackoffStrategy(str, Enum):
    """Backoff strategy for retries."""

    CONSTANT = "constant"  # Same delay each time
    LINEAR = "linear"  # delay * attempt
    EXPONENTIAL = "exponential"  # delay * 2^attempt
    FIBONACCI = "fibonacci"  # Fibonacci sequence


class RetryConfig(BaseModel):
    """Configuration for retry policy."""

    model_config = {"frozen": True}

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    backoff_multiplier: float = 2.0
    jitter: bool = True  # Add randomness to prevent thundering herd
    jitter_factor: float = 0.1  # +/- 10% of delay

    # Retry conditions
    retry_on_exceptions: tuple[type, ...] = (Exception,)
    retry_on_result: Callable[[Any], bool] | None = None  # Retry if returns True


@dataclass(frozen=True)
class RetryResult:
    """Result of a retried operation."""

    success: bool
    result: Any = None
    error: Exception | None = None
    attempts: int = 0
    total_delay_seconds: float = 0.0
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime = field(default_factory=utc_now)
    attempt_errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()


T = TypeVar("T")


class RetryPolicy:
    """
    Configurable retry policy with backoff.

    Usage:
        policy = RetryPolicy(RetryConfig(max_attempts=3))
        result = await policy.execute(my_async_function, arg1, arg2)

        # Or as context manager
        async with policy:
            result = await my_function()
    """

    # Fibonacci sequence for backoff
    _FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]

    def __init__(self, config: RetryConfig | None = None) -> None:
        self._config = config or RetryConfig()

    @property
    def config(self) -> RetryConfig:
        return self._config

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for an attempt (0-indexed)."""
        base = self._config.initial_delay_seconds

        if self._config.backoff_strategy == BackoffStrategy.CONSTANT:
            delay = base
        elif self._config.backoff_strategy == BackoffStrategy.LINEAR:
            delay = base * (attempt + 1)
        elif self._config.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay = base * (self._config.backoff_multiplier**attempt)
        elif self._config.backoff_strategy == BackoffStrategy.FIBONACCI:
            fib_idx = min(attempt, len(self._FIBONACCI) - 1)
            delay = base * self._FIBONACCI[fib_idx]
        else:
            delay = base

        # Apply max delay
        delay = min(delay, self._config.max_delay_seconds)

        # Add jitter (not security-critical, just for retry backoff variance)
        if self._config.jitter:
            jitter_range = delay * self._config.jitter_factor
            delay += random.uniform(-jitter_range, jitter_range)  # nosec B311

        return max(0, delay)

    def _should_retry(self, error: Exception | None, result: Any) -> bool:
        """Check if operation should be retried."""
        if error:
            return isinstance(error, self._config.retry_on_exceptions)

        if self._config.retry_on_result:
            return self._config.retry_on_result(result)

        return False

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> RetryResult:
        """
        Execute function with retry policy.

        Args:
            func: Async function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            RetryResult with success/failure and attempt info
        """
        started_at = utc_now()
        attempt_errors: list[str] = []
        total_delay = 0.0

        for attempt in range(self._config.max_attempts):
            error: Exception | None = None
            result: Any = None

            try:
                result = await func(*args, **kwargs)
            except Exception as e:
                error = e
                attempt_errors.append(str(e))

            # Check if we should retry
            if not self._should_retry(error, result):
                return RetryResult(
                    success=error is None,
                    result=result,
                    error=error,
                    attempts=attempt + 1,
                    total_delay_seconds=total_delay,
                    started_at=started_at,
                    completed_at=utc_now(),
                    attempt_errors=tuple(attempt_errors),
                )

            # Don't delay after last attempt
            if attempt < self._config.max_attempts - 1:
                delay = self._calculate_delay(attempt)
                total_delay += delay
                await asyncio.sleep(delay)

        # All attempts failed
        return RetryResult(
            success=False,
            error=Exception(f"All {self._config.max_attempts} attempts failed"),
            attempts=self._config.max_attempts,
            total_delay_seconds=total_delay,
            started_at=started_at,
            completed_at=utc_now(),
            attempt_errors=tuple(attempt_errors),
        )

    async def __aenter__(self) -> RetryPolicy:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        # Don't suppress exceptions
        return False
