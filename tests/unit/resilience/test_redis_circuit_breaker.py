"""Tests for RedisCircuitBreaker using mocked Redis calls."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from cemaf.resilience.circuit_breaker import CircuitConfig, CircuitOpenError, CircuitState
from cemaf.resilience.redis_circuit_breaker import RedisCircuitBreaker


@pytest.fixture
def fast_config() -> CircuitConfig:
    return CircuitConfig(
        failure_threshold=3,
        failure_window_seconds=60.0,
        recovery_timeout_seconds=0.05,
        success_threshold=2,
        failure_exceptions=(Exception,),
    )


def _make_breaker(config: CircuitConfig) -> RedisCircuitBreaker:
    """Build a RedisCircuitBreaker with a fully mocked Redis client."""
    cb = RedisCircuitBreaker.__new__(RedisCircuitBreaker)
    cb._name = "test"
    cb._config = config
    cb._state_key = "cemaf:circuit:test"
    cb._failures_key = "cemaf:circuit:test:failures"

    mock_redis = MagicMock()
    # eval returns 0 by default (no state change) — individual tests override
    mock_redis.eval = AsyncMock(return_value=0)
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock()
    mock_redis.delete = AsyncMock()
    cb._redis = mock_redis
    return cb


async def _fail() -> None:
    raise Exception("boom")


async def _succeed() -> str:
    return "ok"


class TestRedisCircuitBreaker:
    @pytest.mark.asyncio
    async def test_starts_closed(self, fast_config):
        """Initial state (no Redis key) resolves to CLOSED."""
        cb = _make_breaker(fast_config)
        # hget returns None → no stored state → CLOSED
        state = await cb.get_state()
        assert state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, fast_config):
        """After threshold failures the Lua script opens the circuit."""
        cb = _make_breaker(fast_config)

        # Make eval return 1 (threshold crossed) on the last failure call
        call_count = [0]

        async def _eval_side_effect(script, nkeys, *args):
            call_count[0] += 1
            if call_count[0] >= fast_config.failure_threshold:
                # Simulate Lua writing 'open' to the hash
                cb._redis.hget = AsyncMock(return_value=b"open")
                return 1
            return 0

        cb._redis.eval = _eval_side_effect

        for _ in range(fast_config.failure_threshold):
            with pytest.raises(Exception):
                await cb.execute(_fail)

        state = await cb.get_state()
        assert state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_raises_circuit_open_when_open(self, fast_config):
        """execute() raises CircuitOpenError when state is OPEN and timeout hasn't elapsed."""
        cb = _make_breaker(fast_config)
        # Seed Redis as open with opened_at = now (timeout not yet elapsed)
        opened_at = str(time.time())
        cb._redis.hget = AsyncMock(
            side_effect=lambda key, field: (
                AsyncMock(return_value=b"open")()
                if field == "state"
                else AsyncMock(return_value=opened_at.encode())()
            )
        )

        # Use a simpler approach: patch get_state and _should_attempt_reset
        async def _open_state():
            return CircuitState.OPEN

        async def _no_reset():
            return False

        cb.get_state = _open_state
        cb._should_attempt_reset = _no_reset

        with pytest.raises(CircuitOpenError):
            await cb.execute(_succeed)

    @pytest.mark.asyncio
    async def test_half_open_after_recovery_timeout(self, fast_config):
        """After recovery_timeout, execute transitions to HALF_OPEN and attempts the call."""
        cb = _make_breaker(fast_config)

        # Circuit is OPEN but recovery timeout has passed
        async def _open_state():
            return CircuitState.OPEN

        async def _should_reset():
            return True

        transition_called = [False]

        async def _transition():
            transition_called[0] = True
            # After transition, pretend we are half_open
            cb.get_state = AsyncMock(return_value=CircuitState.HALF_OPEN)

        cb.get_state = _open_state
        cb._should_attempt_reset = _should_reset
        cb._transition_to_half_open = _transition
        cb._record_success_and_check = AsyncMock()

        result = await cb.execute(_succeed)
        assert result == "ok"
        assert transition_called[0]
        cb._record_success_and_check.assert_called_once()
