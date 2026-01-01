"""
Tests for retry policy.

Uses fixtures from conftest.py:
- retry_config: Fast RetryConfig for testing
- retry_policy: RetryPolicy with test config
- async_success: Async function that succeeds
- async_failure: Async function that always fails
- async_flaky: Async function that fails N times then succeeds
"""

import pytest

from cemaf.resilience.retry import (
    BackoffStrategy,
    RetryConfig,
    RetryPolicy,
)


class TestRetryPolicy:
    """Tests for RetryPolicy."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self, retry_policy: RetryPolicy, async_success):
        """Successful call doesn't retry."""
        result = await retry_policy.execute(async_success)

        assert result.success
        assert result.result == "success"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, retry_config: RetryConfig):
        """Retries on failure."""
        policy = RetryPolicy(retry_config)
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = await policy.execute(fail_twice)

        assert result.success
        assert result.attempts == 3
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self):
        """Fails after max attempts."""
        policy = RetryPolicy(
            RetryConfig(
                max_attempts=3,
                initial_delay_seconds=0.01,
            )
        )

        async def always_fail():
            raise ValueError("Always fails")

        result = await policy.execute(always_fail)

        assert not result.success
        assert result.attempts == 3
        assert len(result.attempt_errors) == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Exponential backoff increases delay."""
        policy = RetryPolicy(
            RetryConfig(
                max_attempts=4,
                initial_delay_seconds=0.1,
                backoff_strategy=BackoffStrategy.EXPONENTIAL,
                backoff_multiplier=2.0,
                jitter=False,
            )
        )

        # Test delay calculation
        assert policy._calculate_delay(0) == pytest.approx(0.1)  # 0.1 * 2^0
        assert policy._calculate_delay(1) == pytest.approx(0.2)  # 0.1 * 2^1
        assert policy._calculate_delay(2) == pytest.approx(0.4)  # 0.1 * 2^2

    @pytest.mark.asyncio
    async def test_constant_backoff(self):
        """Constant backoff has same delay."""
        policy = RetryPolicy(
            RetryConfig(
                initial_delay_seconds=0.1,
                backoff_strategy=BackoffStrategy.CONSTANT,
                jitter=False,
            )
        )

        assert policy._calculate_delay(0) == 0.1
        assert policy._calculate_delay(1) == 0.1
        assert policy._calculate_delay(2) == 0.1

    @pytest.mark.asyncio
    async def test_max_delay_cap(self):
        """Delay is capped at max_delay."""
        policy = RetryPolicy(
            RetryConfig(
                initial_delay_seconds=10.0,
                max_delay_seconds=1.0,
                backoff_strategy=BackoffStrategy.EXPONENTIAL,
                jitter=False,
            )
        )

        assert policy._calculate_delay(5) == 1.0  # Capped

    @pytest.mark.asyncio
    async def test_retry_on_specific_exceptions(self):
        """Only retries on configured exceptions, returns failure for others."""
        policy = RetryPolicy(
            RetryConfig(
                max_attempts=3,
                retry_on_exceptions=(ValueError,),
                initial_delay_seconds=0.01,
            )
        )

        async def raise_type_error():
            raise TypeError("Not retryable")

        # RetryPolicy wraps exceptions in result, doesn't raise
        result = await policy.execute(raise_type_error)

        # Should fail immediately (only 1 attempt since TypeError not in retry list)
        assert not result.success
        assert result.attempts == 1  # No retries for TypeError
