"""
Redis-backed circuit breaker for cross-process coordination.

State stored in Redis hash; Lua scripts replace asyncio.Lock for
atomicity across multiple Python workers. ZADD + ZRANGEBYSCORE for
time-windowed failure counting.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from cemaf.resilience.circuit_breaker import CircuitConfig, CircuitOpenError, CircuitState

T = TypeVar("T")

# Atomically record a failure and open the circuit if threshold is met.
# Returns 1 if circuit was opened, 0 otherwise.
_RECORD_FAILURE_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local threshold = tonumber(ARGV[3])
redis.call('ZADD', KEYS[2], now, tostring(now) .. tostring(math.random()))
redis.call('ZREMRANGEBYSCORE', KEYS[2], 0, now - window)
local count = redis.call('ZCARD', KEYS[2])
if count >= threshold then
  redis.call('HSET', KEYS[1], 'state', 'open', 'opened_at', tostring(now), 'half_open_successes', '0')
  return 1
end
return 0
"""

# Atomically record a half-open success and close if success_threshold is met.
# Returns 1 if circuit was closed, 0 otherwise.
_RECORD_SUCCESS_SCRIPT = """
local threshold = tonumber(ARGV[1])
local current = tonumber(redis.call('HGET', KEYS[1], 'half_open_successes') or '0')
local next_val = current + 1
if next_val >= threshold then
  redis.call('HSET', KEYS[1], 'state', 'closed', 'half_open_successes', '0', 'opened_at', '')
  redis.call('DEL', KEYS[2])
  return 1
end
redis.call('HSET', KEYS[1], 'half_open_successes', tostring(next_val))
return 0
"""

# Atomically transition from open to half-open.
_SET_HALF_OPEN_SCRIPT = """
local current_state = redis.call('HGET', KEYS[1], 'state')
if current_state == 'open' then
  redis.call('HSET', KEYS[1], 'state', 'half_open', 'half_open_successes', '0')
  return 1
end
return 0
"""


class RedisCircuitBreaker:
    """
    Circuit breaker that synchronises state in Redis for multi-process deployments.

    Semantics are identical to CircuitBreaker; Redis replaces the asyncio.Lock
    so separate OS processes share a single logical circuit state.
    """

    def __init__(
        self,
        redis_url: str,
        name: str,
        config: CircuitConfig | None = None,
    ) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError as exc:
            raise ImportError(
                "redis package required for RedisCircuitBreaker. "
                "Install with: uv add redis"
            ) from exc

        self._redis = aioredis.from_url(redis_url)
        self._name = name
        self._config = config or CircuitConfig()
        self._state_key = f"cemaf:circuit:{name}"
        self._failures_key = f"cemaf:circuit:{name}:failures"

    async def get_state(self) -> CircuitState:
        """Read current state from Redis."""
        raw = await self._redis.hget(self._state_key, "state")
        if raw is None:
            return CircuitState.CLOSED
        value = raw.decode() if isinstance(raw, bytes) else raw
        try:
            return CircuitState(value)
        except ValueError:
            return CircuitState.CLOSED

    async def _should_attempt_reset(self) -> bool:
        """Check whether enough time has elapsed since the circuit opened."""
        raw = await self._redis.hget(self._state_key, "opened_at")
        if raw is None:
            return True
        val = raw.decode() if isinstance(raw, bytes) else raw
        if not val:
            return True
        try:
            opened_at = float(val)
        except ValueError:
            return True
        return (time.time() - opened_at) >= self._config.recovery_timeout_seconds

    async def _record_failure_and_check(self) -> None:
        """Record failure in sorted set and open circuit if threshold exceeded."""
        now = time.time()
        await self._redis.eval(
            _RECORD_FAILURE_SCRIPT,
            2,
            self._state_key,
            self._failures_key,
            now,
            self._config.failure_window_seconds,
            self._config.failure_threshold,
        )

    async def _record_success_and_check(self) -> None:
        """Record half-open success and close circuit if threshold met."""
        await self._redis.eval(
            _RECORD_SUCCESS_SCRIPT,
            2,
            self._state_key,
            self._failures_key,
            self._config.success_threshold,
        )

    async def _transition_to_half_open(self) -> None:
        """Atomically set state to half-open if currently open."""
        await self._redis.eval(
            _SET_HALF_OPEN_SCRIPT,
            1,
            self._state_key,
        )

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute function through the Redis-backed circuit breaker."""
        state = await self.get_state()

        if state == CircuitState.OPEN:
            if await self._should_attempt_reset():
                await self._transition_to_half_open()
                state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError(f"Circuit '{self._name}' is open")

        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            if isinstance(exc, self._config.failure_exceptions):
                await self._record_failure_and_check()
            raise

        # On success in half-open, check if we should close.
        if state == CircuitState.HALF_OPEN:
            await self._record_success_and_check()

        return result

    async def reset(self) -> None:
        """Delete all Redis keys, restoring the circuit to a clean closed state."""
        await self._redis.delete(self._state_key, self._failures_key)

    async def close(self) -> None:
        """Close the underlying Redis connection pool."""
        await self._redis.aclose()
