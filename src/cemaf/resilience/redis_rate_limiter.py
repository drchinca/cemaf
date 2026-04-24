"""
Redis-backed rate limiter using atomic Lua token bucket.

Replaces asyncio.Lock with Redis atomic operations for cross-process
coordination. Single Lua script reads, refills, and decrements tokens
atomically (Redis is single-threaded for command execution).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiterMetrics, RateLimitExceeded

T = TypeVar("T")

# Single Lua script: refill from elapsed time then try to consume `requested` tokens.
# Returns 1 if acquired, 0 if not enough tokens.
_TOKEN_BUCKET_SCRIPT = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'last_update')
local tokens = tonumber(data[1]) or tonumber(ARGV[2])
local last   = tonumber(data[2]) or tonumber(ARGV[3])
local elapsed = tonumber(ARGV[3]) - last
tokens = math.min(tonumber(ARGV[2]), tokens + elapsed * tonumber(ARGV[1]))
local requested = tonumber(ARGV[4])
if tokens >= requested then
  tokens = tokens - requested
  redis.call('HMSET', KEYS[1], 'tokens', tostring(tokens), 'last_update', ARGV[3])
  redis.call('EXPIRE', KEYS[1], 3600)
  return 1
else
  redis.call('HMSET', KEYS[1], 'tokens', tostring(tokens), 'last_update', ARGV[3])
  redis.call('EXPIRE', KEYS[1], 3600)
  return 0
end
"""


class RedisRateLimiter:
    """
    Token-bucket rate limiter backed by Redis for multi-process coordination.

    Interface is identical to RateLimiter; metrics are tracked locally
    per-process (cross-process aggregation belongs in a metrics backend).
    """

    def __init__(
        self,
        redis_url: str,
        name: str,
        config: RateLimitConfig | None = None,
    ) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise ImportError(
                "redis package required for RedisRateLimiter. "
                "Install with: uv add redis"
            ) from exc

        self._redis = aioredis.from_url(redis_url)
        self._name = name
        self._config = config or RateLimitConfig()
        self._key = f"cemaf:ratelimit:{name}"
        self._metrics = RateLimiterMetrics()

    @property
    def config(self) -> RateLimitConfig:
        return self._config

    @property
    def metrics(self) -> RateLimiterMetrics:
        return self._metrics

    async def _try_acquire(self, tokens: int = 1) -> bool:
        """Run the Lua script; return True if tokens were consumed."""
        now = time.time()
        result = await self._redis.eval(
            _TOKEN_BUCKET_SCRIPT,
            1,
            self._key,
            self._config.rate,
            self._config.burst,
            now,
            tokens,
        )
        return bool(result)

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens from the Redis bucket.

        Waits up to max_wait_seconds when wait_on_limit is True.
        Returns True on success; raises RateLimitExceeded when the wait
        budget is exhausted or wait_on_limit is False.
        """
        self._metrics.total_requests += 1

        if await self._try_acquire(tokens):
            self._metrics.allowed_requests += 1
            return True

        if not self._config.wait_on_limit:
            self._metrics.rejected_requests += 1
            wait_needed = tokens / self._config.rate
            raise RateLimitExceeded(retry_after=wait_needed)

        total_waited = 0.0
        while True:
            # Time needed to accumulate `tokens` tokens at the configured rate.
            wait_step = min(tokens / self._config.rate, 0.1)

            if total_waited + wait_step > self._config.max_wait_seconds:
                self._metrics.rejected_requests += 1
                raise RateLimitExceeded(retry_after=wait_step)

            await asyncio.sleep(wait_step)
            total_waited += wait_step

            if await self._try_acquire(tokens):
                self._metrics.allowed_requests += 1
                self._metrics.throttled_requests += 1
                self._metrics.total_wait_time_seconds += total_waited
                return True

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Acquire one token then call func."""
        await self.acquire()
        return await func(*args, **kwargs)

    async def reset(self) -> None:
        """Delete the bucket key so the next acquire starts from full burst."""
        await self._redis.delete(self._key)

    async def close(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._redis.aclose()
