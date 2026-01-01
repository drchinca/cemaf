"""
Rate limiter - Control request rates.

Implements token bucket algorithm for smooth rate limiting.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from cemaf.core.utils import utc_now


class RateLimitConfig(BaseModel):
    """Configuration for rate limiter."""

    model_config = {"frozen": True}

    # Requests per second
    rate: float = 10.0

    # Burst capacity (max tokens)
    burst: int = 10

    # Whether to wait or reject when limited
    wait_on_limit: bool = True

    # Max wait time before rejecting
    max_wait_seconds: float = 30.0


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: float = 0.0):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after:.2f}s")


@dataclass
class RateLimiterMetrics:
    """Metrics for rate limiter."""

    total_requests: int = 0
    allowed_requests: int = 0
    throttled_requests: int = 0
    rejected_requests: int = 0
    total_wait_time_seconds: float = 0.0


T = TypeVar("T")


class RateLimiter:
    """
    Token bucket rate limiter.

    Provides smooth rate limiting with burst support.

    Usage:
        limiter = RateLimiter(RateLimitConfig(rate=10, burst=20))

        # Will wait if rate limited
        await limiter.acquire()
        result = await my_function()

        # Or wrap function
        result = await limiter.execute(my_function, arg1, arg2)
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        self._tokens = float(self._config.burst)
        self._last_update = utc_now()
        self._metrics = RateLimiterMetrics()
        self._lock = asyncio.Lock()

    @property
    def config(self) -> RateLimitConfig:
        return self._config

    @property
    def metrics(self) -> RateLimiterMetrics:
        return self._metrics

    @property
    def available_tokens(self) -> float:
        """Current available tokens."""
        return self._tokens

    def _add_tokens(self) -> None:
        """Add tokens based on elapsed time."""
        now = utc_now()
        elapsed = (now - self._last_update).total_seconds()
        self._last_update = now

        # Add tokens at configured rate
        self._tokens = min(self._config.burst, self._tokens + elapsed * self._config.rate)

    def _time_until_token(self) -> float:
        """Calculate time until next token is available."""
        if self._tokens >= 1.0:
            return 0.0
        tokens_needed = 1.0 - self._tokens
        return tokens_needed / self._config.rate

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens from the bucket.

        If wait_on_limit is True, waits until tokens available.
        Otherwise raises RateLimitExceeded.

        Returns True if acquired, raises if not.
        """
        async with self._lock:
            self._metrics.total_requests += 1
            self._add_tokens()

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._metrics.allowed_requests += 1
                return True

            if not self._config.wait_on_limit:
                retry_after = self._time_until_token()
                self._metrics.rejected_requests += 1
                raise RateLimitExceeded(retry_after)

        # Wait for tokens
        total_wait = 0.0
        while True:
            async with self._lock:
                self._add_tokens()

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self._metrics.allowed_requests += 1
                    self._metrics.throttled_requests += 1
                    self._metrics.total_wait_time_seconds += total_wait
                    return True

                wait_time = self._time_until_token()

            if total_wait + wait_time > self._config.max_wait_seconds:
                self._metrics.rejected_requests += 1
                raise RateLimitExceeded(wait_time)

            await asyncio.sleep(min(wait_time, 0.1))  # Check every 100ms max
            total_wait += min(wait_time, 0.1)

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute function with rate limiting.

        Acquires a token before executing.
        """
        await self.acquire()
        return await func(*args, **kwargs)

    def reset(self) -> None:
        """Reset the limiter."""
        self._tokens = float(self._config.burst)
        self._last_update = utc_now()
        self._metrics = RateLimiterMetrics()
