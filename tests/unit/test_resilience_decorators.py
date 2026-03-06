"""Tests for resilience decorators."""

import pytest

from cemaf.resilience.decorators import (
    TimeoutError,
    _circuit_breakers,
    with_circuit_breaker,
    with_fallback,
    with_retry,
    with_timeout,
)


class TestWithRetry:
    async def test_succeeds_first_try(self):
        call_count = 0

        @with_retry(max_attempts=3)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_failure(self):
        call_count = 0

        @with_retry(max_attempts=3, initial_delay=0.01)
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    async def test_exhausts_retries(self):
        @with_retry(max_attempts=2, initial_delay=0.01)
        async def always_fail():
            raise ValueError("always fails")

        with pytest.raises((ValueError, Exception)):
            await always_fail()


class TestWithCircuitBreaker:
    async def test_succeeds_normally(self):
        # Use unique name to avoid cross-test interference
        @with_circuit_breaker(name="test_cb_success", failure_threshold=5)
        async def succeed():
            return "ok"

        result = await succeed()
        assert result == "ok"

        # Cleanup
        _circuit_breakers.pop("test_cb_success", None)

    async def test_shared_breaker_by_name(self):
        name = "test_shared_breaker"

        @with_circuit_breaker(name=name, failure_threshold=3)
        async def func_a():
            return "a"

        @with_circuit_breaker(name=name, failure_threshold=3)
        async def func_b():
            return "b"

        await func_a()
        await func_b()
        assert name in _circuit_breakers

        # Cleanup
        _circuit_breakers.pop(name, None)


class TestWithTimeout:
    async def test_completes_within_timeout(self):
        @with_timeout(seconds=5.0)
        async def fast():
            return "done"

        result = await fast()
        assert result == "done"

    async def test_raises_on_timeout(self):
        import asyncio

        @with_timeout(seconds=0.01)
        async def slow():
            await asyncio.sleep(10)
            return "never"

        with pytest.raises(TimeoutError) as exc_info:
            await slow()
        assert exc_info.value.seconds == 0.01


class TestWithFallback:
    async def test_returns_value_on_success(self):
        @with_fallback(fallback_value="default")
        async def succeed():
            return "actual"

        result = await succeed()
        assert result == "actual"

    async def test_returns_fallback_on_failure(self):
        @with_fallback(fallback_value="default")
        async def fail():
            raise ValueError("boom")

        result = await fail()
        assert result == "default"

    async def test_fallback_with_list(self):
        @with_fallback(fallback_value=[])
        async def fail():
            raise RuntimeError("oops")

        result = await fail()
        assert result == []


class TestTimeoutError:
    def test_message(self):
        err = TimeoutError(seconds=30.0)
        assert "30" in str(err)
        assert err.seconds == 30.0
