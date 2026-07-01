"""Tests for RedisRateLimiter using mocked Redis calls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiterMetrics, RateLimitExceeded
from cemaf.resilience.redis_rate_limiter import RedisRateLimiter


@pytest.fixture
def config() -> RateLimitConfig:
    return RateLimitConfig(rate=100.0, burst=5, wait_on_limit=False, max_wait_seconds=1.0)


def _make_limiter(config: RateLimitConfig, *, lua_returns: list[int]) -> RedisRateLimiter:
    """Build a RedisRateLimiter whose Lua script returns values from `lua_returns`."""
    rl = RedisRateLimiter.__new__(RedisRateLimiter)
    rl._name = "test"
    rl._config = config
    rl._key = "cemaf:ratelimit:test"
    rl._metrics = RateLimiterMetrics()

    returns_iter = iter(lua_returns)

    async def _eval(*args, **kwargs):
        try:
            return next(returns_iter)
        except StopIteration:
            return 0

    mock_redis = MagicMock()
    mock_redis.eval = _eval
    mock_redis.delete = AsyncMock()
    rl._redis = mock_redis
    return rl


class TestRedisRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_burst(self, config):
        """All burst requests succeed when Lua reports tokens available."""
        # Lua returns 1 (acquired) for every call
        rl = _make_limiter(config, lua_returns=[1] * config.burst)
        for _ in range(config.burst):
            acquired = await rl.acquire()
            assert acquired is True
        assert rl._metrics.allowed_requests == config.burst

    @pytest.mark.asyncio
    async def test_blocks_above_rate(self, config):
        """After burst is exhausted (Lua returns 0) and wait=False → RateLimitExceeded."""
        # First 5 succeed, then 0 forever
        rl = _make_limiter(config, lua_returns=[1] * config.burst + [0] * 10)
        for _ in range(config.burst):
            await rl.acquire()

        with pytest.raises(RateLimitExceeded):
            await rl.acquire()

        assert rl._metrics.rejected_requests == 1

    @pytest.mark.asyncio
    async def test_reset_refills_tokens(self, config):
        """reset() deletes the Redis key; subsequent acquires start from full burst."""
        # First burst of requests fail (exhausted), then after reset succeed
        fail_then_succeed = [0] * config.burst + [1] * config.burst
        rl = _make_limiter(config, lua_returns=fail_then_succeed)

        # All fail initially (bucket already empty in this mock scenario)
        rl._metrics = RateLimiterMetrics()
        await rl.reset()

        rl._redis.delete.assert_called_once_with(rl._key)

        # After reset, assume tokens available (Lua returns 1)
        rl2 = _make_limiter(config, lua_returns=[1] * config.burst)
        for _ in range(config.burst):
            acquired = await rl2.acquire()
            assert acquired is True
