"""Tests for resilience rate limiter."""

import pytest

from cemaf.resilience.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimiterMetrics,
    RateLimitExceeded,
)


class TestRateLimitConfig:
    def test_defaults(self):
        config = RateLimitConfig()
        assert config.rate == 10.0
        assert config.burst == 10
        assert config.wait_on_limit is True
        assert config.max_wait_seconds == 30.0

    def test_frozen(self):
        config = RateLimitConfig()
        with pytest.raises(Exception):
            config.rate = 5.0  # type: ignore[misc]

    def test_custom_values(self):
        config = RateLimitConfig(rate=5.0, burst=20, wait_on_limit=False, max_wait_seconds=10.0)
        assert config.rate == 5.0
        assert config.burst == 20


class TestRateLimiterMetrics:
    def test_defaults(self):
        metrics = RateLimiterMetrics()
        assert metrics.total_requests == 0
        assert metrics.allowed_requests == 0
        assert metrics.throttled_requests == 0
        assert metrics.rejected_requests == 0
        assert metrics.total_wait_time_seconds == 0.0


class TestRateLimiter:
    async def test_acquire_within_burst(self):
        limiter = RateLimiter(config=RateLimitConfig(rate=100.0, burst=10))
        result = await limiter.acquire()
        assert result is True
        assert limiter.metrics.allowed_requests == 1
        assert limiter.metrics.total_requests == 1

    async def test_acquire_multiple_within_burst(self):
        limiter = RateLimiter(config=RateLimitConfig(rate=100.0, burst=5))
        for _ in range(5):
            await limiter.acquire()
        assert limiter.metrics.allowed_requests == 5

    async def test_reject_when_no_wait(self):
        config = RateLimitConfig(rate=1.0, burst=1, wait_on_limit=False)
        limiter = RateLimiter(config=config)
        await limiter.acquire()  # Use the one burst token
        with pytest.raises(RateLimitExceeded):
            await limiter.acquire()
        assert limiter.metrics.rejected_requests == 1

    async def test_rate_limit_exceeded_has_retry_after(self):
        config = RateLimitConfig(rate=1.0, burst=1, wait_on_limit=False)
        limiter = RateLimiter(config=config)
        await limiter.acquire()
        with pytest.raises(RateLimitExceeded) as exc_info:
            await limiter.acquire()
        assert exc_info.value.retry_after > 0

    async def test_execute_wraps_function(self):
        limiter = RateLimiter(config=RateLimitConfig(rate=100.0, burst=10))

        async def my_func(x: int) -> int:
            return x * 2

        result = await limiter.execute(my_func, 5)
        assert result == 10
        assert limiter.metrics.allowed_requests == 1

    def test_reset(self):
        limiter = RateLimiter(config=RateLimitConfig(rate=100.0, burst=10))
        limiter._metrics.total_requests = 50
        limiter._tokens = 0.0
        limiter.reset()
        assert limiter.metrics.total_requests == 0
        assert limiter.available_tokens == 10.0

    def test_available_tokens(self):
        limiter = RateLimiter(config=RateLimitConfig(burst=15))
        assert limiter.available_tokens == 15.0

    def test_config_property(self):
        config = RateLimitConfig(rate=5.0)
        limiter = RateLimiter(config=config)
        assert limiter.config.rate == 5.0
