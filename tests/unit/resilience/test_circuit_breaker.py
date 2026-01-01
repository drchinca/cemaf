"""
Tests for circuit breaker.

Uses fixtures from conftest.py:
- circuit_config: Fast CircuitConfig for testing
- circuit_breaker: CircuitBreaker with test config
- async_success: Async function that succeeds
- async_failure: Async function that always fails
"""

import contextlib

import pytest

from cemaf.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitConfig,
    CircuitOpenError,
    CircuitState,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    @pytest.mark.asyncio
    async def test_starts_closed(self, circuit_breaker: CircuitBreaker):
        """Circuit starts in closed state."""
        assert circuit_breaker.state == CircuitState.CLOSED
        assert not circuit_breaker.is_open

    @pytest.mark.asyncio
    async def test_success_stays_closed(self, circuit_breaker: CircuitBreaker, async_success):
        """Successful calls keep circuit closed."""
        await circuit_breaker.execute(async_success)
        await circuit_breaker.execute(async_success)

        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.metrics.successful_calls == 2

    @pytest.mark.asyncio
    async def test_opens_on_failures(self, circuit_config: CircuitConfig, async_failure):
        """Circuit opens after failure threshold."""
        breaker = CircuitBreaker(CircuitConfig(failure_threshold=3))

        # First 3 failures should open circuit
        for _ in range(3):
            with contextlib.suppress(ValueError):
                await breaker.execute(async_failure)

        assert breaker.state == CircuitState.OPEN
        assert breaker.metrics.times_opened == 1

    @pytest.mark.asyncio
    async def test_rejects_when_open(self):
        """Open circuit rejects calls."""
        breaker = CircuitBreaker(
            CircuitConfig(
                failure_threshold=1,
                recovery_timeout_seconds=100,  # Long timeout
            )
        )

        async def fail():
            raise ValueError()

        async def succeed():
            return "ok"

        # Open the circuit
        with contextlib.suppress(ValueError):
            await breaker.execute(fail)

        # Should be rejected
        with pytest.raises(CircuitOpenError):
            await breaker.execute(succeed)

        assert breaker.metrics.rejected_calls == 1

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        """Circuit goes half-open after recovery timeout."""
        breaker = CircuitBreaker(
            CircuitConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0.01,  # Very short
            )
        )

        async def fail():
            raise ValueError()

        async def succeed():
            return "ok"

        # Open the circuit
        with contextlib.suppress(ValueError):
            await breaker.execute(fail)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        import asyncio

        await asyncio.sleep(0.02)

        # Next call should attempt (half-open)
        result = await breaker.execute(succeed)

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_closes_after_successes(self):
        """Circuit closes after success threshold in half-open."""
        breaker = CircuitBreaker(
            CircuitConfig(
                failure_threshold=1,
                recovery_timeout_seconds=0.01,
                success_threshold=2,
            )
        )

        async def fail():
            raise ValueError()

        async def succeed():
            return "ok"

        # Open the circuit
        with contextlib.suppress(ValueError):
            await breaker.execute(fail)

        import asyncio

        await asyncio.sleep(0.02)

        # Two successes should close
        await breaker.execute(succeed)
        await breaker.execute(succeed)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics.times_closed == 1

    @pytest.mark.asyncio
    async def test_reset(self):
        """Reset returns to initial state."""
        breaker = CircuitBreaker(CircuitConfig(failure_threshold=1))

        async def fail():
            raise ValueError()

        # Open the circuit
        with contextlib.suppress(ValueError):
            await breaker.execute(fail)

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.metrics.total_calls == 0
