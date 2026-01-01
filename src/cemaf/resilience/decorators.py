"""
Resilience decorators - Easy-to-use decorators for resilience patterns.

Usage:
    @with_retry(max_attempts=3)
    async def my_function():
        ...

    @with_circuit_breaker(failure_threshold=5)
    async def my_function():
        ...

    @with_timeout(seconds=30)
    async def my_function():
        ...
"""

import asyncio
import builtins
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
from cemaf.resilience.retry import RetryConfig, RetryPolicy

T = TypeVar("T")


def with_retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential: bool = True,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator to add retry behavior to an async function.

    Usage:
        @with_retry(max_attempts=3, initial_delay=1.0)
        async def flaky_function():
            ...
    """
    from cemaf.resilience.retry import BackoffStrategy

    config = RetryConfig(
        max_attempts=max_attempts,
        initial_delay_seconds=initial_delay,
        max_delay_seconds=max_delay,
        backoff_strategy=BackoffStrategy.EXPONENTIAL if exponential else BackoffStrategy.CONSTANT,
    )
    policy = RetryPolicy(config)

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            result = await policy.execute(func, *args, **kwargs)
            if result.success:
                return result.result
            raise result.error or Exception("Retry failed")

        return wrapper

    return decorator


# Global circuit breakers by name
_circuit_breakers: dict[str, CircuitBreaker] = {}


def with_circuit_breaker(
    name: str | None = None,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator to add circuit breaker to an async function.

    Functions with the same name share a circuit breaker.

    Usage:
        @with_circuit_breaker(name="external_api", failure_threshold=5)
        async def call_external_api():
            ...
    """
    config = CircuitConfig(
        failure_threshold=failure_threshold,
        recovery_timeout_seconds=recovery_timeout,
    )

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        breaker_name = name or func.__name__

        # Get or create circuit breaker
        if breaker_name not in _circuit_breakers:
            _circuit_breakers[breaker_name] = CircuitBreaker(config)
        breaker = _circuit_breakers[breaker_name]

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await breaker.execute(func, *args, **kwargs)

        return wrapper

    return decorator


class TimeoutError(Exception):
    """Raised when operation times out."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(f"Operation timed out after {seconds}s")


def with_timeout(
    seconds: float,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator to add timeout to an async function.

    Usage:
        @with_timeout(seconds=30)
        async def slow_function():
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except builtins.TimeoutError:
                raise TimeoutError(seconds) from None

        return wrapper

    return decorator


def with_fallback[T](
    fallback_value: T,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator to return fallback value on any exception.

    Usage:
        @with_fallback(fallback_value=[])
        async def get_items():
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await func(*args, **kwargs)
            except Exception:
                return fallback_value

        return wrapper

    return decorator
