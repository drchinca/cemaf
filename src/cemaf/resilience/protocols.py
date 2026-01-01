"""
Resilience protocols - Abstract interfaces for fault tolerance patterns.

Supports:
- Retry strategies with backoff
- Circuit breakers for cascading failure prevention
- Rate limiting for request throttling

## Protocol-First Design

This module provides structural typing via @runtime_checkable protocols.
Any class that implements the required methods is automatically compatible.

Extension Point:
    Custom resilience implementations should implement these protocols rather
    than creating new classes from scratch. This allows maximum flexibility
    and follows CEMAF's dependency injection principles.

Example:
    >>> from cemaf.resilience.protocols import RetryStrategy
    >>>
    >>> class MyCustomRetryStrategy:
    ...     async def execute(self, func, *args, **kwargs):
    ...         # Your custom retry logic
    ...         ...
    >>>
    >>> # No inheritance needed - structural compatibility!
    >>> assert isinstance(MyCustomRetryStrategy(), RetryStrategy)
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "RetryStrategy",
    "CircuitBreakerProtocol",
    "RateLimiterProtocol",
]


@runtime_checkable
class RetryStrategy(Protocol):
    """
    Protocol for retry strategy implementations.

    A RetryStrategy handles automatic retries of failed operations with:
    - Configurable retry attempts
    - Backoff strategies (constant, exponential, fibonacci)
    - Jitter for thundering herd prevention
    - Selective retry based on exception types
    - Result-based retry conditions

    Extension Point:
        Implement this protocol for custom retry strategies:
        - Custom backoff algorithms
        - Adaptive retry (based on system load)
        - Context-aware retry (different strategies per service)
        - Distributed retry coordination

    Example:
        >>> class ExponentialRetryStrategy:
        ...     def __init__(self, max_attempts: int = 3, base_delay: float = 1.0):
        ...         self.max_attempts = max_attempts
        ...         self.base_delay = base_delay
        ...
        ...     async def execute(self, func, *args, **kwargs):
        ...         for attempt in range(self.max_attempts):
        ...             try:
        ...                 return await func(*args, **kwargs)
        ...             except Exception as e:
        ...                 if attempt == self.max_attempts - 1:
        ...                     raise
        ...                 delay = self.base_delay * (2 ** attempt)
        ...                 await asyncio.sleep(delay)
        >>>
        >>> # Automatically compatible!
        >>> strategy = ExponentialRetryStrategy()
        >>> assert isinstance(strategy, RetryStrategy)

    See Also:
        - cemaf.resilience.retry.RetryPolicy (built-in implementation)
        - cemaf.resilience.decorators.with_retry (decorator)
    """

    async def execute[T](
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute a function with retry logic.

        Args:
            func: Async function to execute
            *args: Positional arguments to pass to func
            **kwargs: Keyword arguments to pass to func

        Returns:
            Result of the function

        Raises:
            Exception: If all retry attempts fail

        Example:
            >>> async def flaky_api_call(url: str) -> dict:
            ...     response = await http.get(url)
            ...     return response.json()
            >>>
            >>> strategy = ExponentialRetryStrategy(max_attempts=3)
            >>> result = await strategy.execute(flaky_api_call, "https://api.example.com")
        """
        ...


@runtime_checkable
class CircuitBreakerProtocol(Protocol):
    """
    Protocol for circuit breaker implementations.

    A Circuit Breaker prevents cascading failures by:
    - Tracking failure rates
    - Opening circuit after threshold exceeded
    - Allowing recovery attempts after timeout
    - Closing circuit when service recovers

    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Service is failing, requests fail immediately
        - HALF_OPEN: Testing if service has recovered

    Extension Point:
        Implement this protocol for custom circuit breakers:
        - Distributed circuit breakers (shared state)
        - Adaptive thresholds (based on load)
        - Multiple failure metrics (latency, errors, timeouts)
        - Integration with service discovery

    Example:
        >>> class SimpleCircuitBreaker:
        ...     def __init__(self, failure_threshold: int = 5):
        ...         self.failure_threshold = failure_threshold
        ...         self.failures = 0
        ...         self.is_open = False
        ...
        ...     async def call(self, func, *args, **kwargs):
        ...         if self.is_open:
        ...             raise Exception("Circuit is open")
        ...         try:
        ...             result = await func(*args, **kwargs)
        ...             self.failures = 0  # Reset on success
        ...             return result
        ...         except Exception:
        ...             self.failures += 1
        ...             if self.failures >= self.failure_threshold:
        ...                 self.is_open = True
        ...             raise
        >>>
        >>> # Automatically compatible!
        >>> breaker = SimpleCircuitBreaker()
        >>> assert isinstance(breaker, CircuitBreakerProtocol)

    See Also:
        - cemaf.resilience.circuit_breaker.CircuitBreaker (built-in implementation)
        - cemaf.resilience.decorators.with_circuit_breaker (decorator)
    """

    async def call[T](
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute a function through the circuit breaker.

        Args:
            func: Async function to execute
            *args: Positional arguments to pass to func
            **kwargs: Keyword arguments to pass to func

        Returns:
            Result of the function

        Raises:
            Exception: If circuit is open or function fails

        Example:
            >>> breaker = SimpleCircuitBreaker(failure_threshold=5)
            >>>
            >>> async def call_api(endpoint: str) -> dict:
            ...     response = await http.get(endpoint)
            ...     return response.json()
            >>>
            >>> # Wrapped calls are protected
            >>> result = await breaker.call(call_api, "/users")
        """
        ...


@runtime_checkable
class RateLimiterProtocol(Protocol):
    """
    Protocol for rate limiter implementations.

    A Rate Limiter controls the rate of requests to prevent overload:
    - Token bucket algorithm
    - Sliding window
    - Fixed window
    - Adaptive rate limiting

    Extension Point:
        Implement this protocol for custom rate limiters:
        - Distributed rate limiting (Redis, DynamoDB)
        - Per-user rate limits
        - Adaptive rate limiting (based on system load)
        - Priority-based rate limiting

    Example:
        >>> class TokenBucketRateLimiter:
        ...     def __init__(self, rate: float, burst: int):
        ...         self.rate = rate  # Requests per second
        ...         self.burst = burst  # Burst capacity
        ...         self.tokens = burst
        ...         self.last_update = time.time()
        ...
        ...     async def acquire(self, tokens: int = 1) -> bool:
        ...         # Refill tokens based on elapsed time
        ...         now = time.time()
        ...         elapsed = now - self.last_update
        ...         self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        ...         self.last_update = now
        ...
        ...         # Check if we have enough tokens
        ...         if self.tokens >= tokens:
        ...             self.tokens -= tokens
        ...             return True
        ...         return False
        >>>
        >>> # Automatically compatible!
        >>> limiter = TokenBucketRateLimiter(rate=10.0, burst=100)
        >>> assert isinstance(limiter, RateLimiterProtocol)

    See Also:
        - cemaf.resilience.rate_limiter.RateLimiter (built-in implementation)
    """

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens from the rate limiter.

        Args:
            tokens: Number of tokens to acquire (default: 1)

        Returns:
            True if tokens were acquired, False if rate limit exceeded

        Example:
            >>> limiter = TokenBucketRateLimiter(rate=10.0, burst=100)
            >>>
            >>> # Check if we can proceed
            >>> if await limiter.acquire():
            ...     # Make request
            ...     await api.call()
            >>> else:
            ...     # Rate limited, wait or fail
            ...     await asyncio.sleep(1)
        """
        ...
