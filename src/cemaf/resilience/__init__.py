"""
Resilience module - Fault tolerance patterns.

Provides:
- RetryPolicy: Configurable retry with backoff
- CircuitBreaker: Prevent cascading failures
- RateLimiter: Control request rates
- Timeout: Enforce time limits
- Bulkhead: Isolate failures

## Configuration

Settings for this module are defined in ResilienceSettings.

Environment Variables:
    CEMAF_RESILIENCE_MAX_RETRIES: Max retry attempts (default: 3)
    CEMAF_RESILIENCE_INITIAL_RETRY_DELAY_SECONDS: Initial delay (default: 1.0)
    CEMAF_RESILIENCE_MAX_RETRY_DELAY_SECONDS: Max delay (default: 60.0)
    CEMAF_RESILIENCE_RETRY_BACKOFF_STRATEGY: Backoff strategy (default: exponential)
    CEMAF_RESILIENCE_RETRY_BACKOFF_MULTIPLIER: Backoff multiplier (default: 2.0)
    CEMAF_RESILIENCE_RETRY_JITTER: Enable jitter (default: True)
    CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD: Failure threshold (default: 5)
    CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS: Failure window (default: 60.0)
    CEMAF_RESILIENCE_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS: Recovery timeout (default: 30.0)
    CEMAF_RESILIENCE_CIRCUIT_BREAKER_SUCCESS_THRESHOLD: Success threshold (default: 2)
    CEMAF_RESILIENCE_RATE_LIMIT_REQUESTS_PER_SECOND: Rate limit (default: 10.0)
    CEMAF_RESILIENCE_RATE_LIMIT_BURST: Burst capacity (default: 10)
    CEMAF_RESILIENCE_RATE_LIMIT_WAIT_ON_LIMIT: Wait on limit (default: True)
    CEMAF_RESILIENCE_RATE_LIMIT_MAX_WAIT_SECONDS: Max wait time (default: 30.0)

## Usage

Protocols (Extension Point):
    >>> from cemaf.resilience.protocols import RetryStrategy, CircuitBreakerProtocol
    >>> # Implement these protocols for custom resilience patterns

Built-in Implementations:
    >>> from cemaf.resilience import RetryPolicy, CircuitBreaker, RateLimiter
    >>> from cemaf.resilience import RetryConfig, CircuitConfig, RateLimitConfig
    >>>
    >>> # Retry example
    >>> config = RetryConfig(max_attempts=3, backoff_strategy="exponential")
    >>> policy = RetryPolicy(config)
    >>> result = await policy.execute(my_function, arg1, arg2)
    >>>
    >>> # Circuit breaker example
    >>> circuit = CircuitBreaker(CircuitConfig(failure_threshold=5))
    >>> result = await circuit.call(api_call, endpoint)

Decorators (Quick):
    >>> from cemaf.resilience import with_retry, with_circuit_breaker, with_timeout
    >>>
    >>> @with_retry(max_attempts=3)
    >>> @with_circuit_breaker(failure_threshold=5)
    >>> async def call_api(endpoint: str):
    ...     return await http.get(endpoint)

## Extension

Resilience implementations are discovered via protocols. No registration needed.
Simply implement the resilience protocols and your patterns are compatible with
all CEMAF orchestration systems.

See cemaf.resilience.protocols for protocol definitions.
"""

# Protocols (extension point)
# Built-in implementations
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig, CircuitState
from cemaf.resilience.decorators import with_circuit_breaker, with_retry, with_timeout
from cemaf.resilience.protocols import (
    CircuitBreakerProtocol,
    RateLimiterProtocol,
    RetryStrategy,
)
from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter
from cemaf.resilience.retry import RetryConfig, RetryPolicy, RetryResult

__all__ = [
    # Protocols (recommended for extension)
    "RetryStrategy",
    "CircuitBreakerProtocol",
    "RateLimiterProtocol",
    # Built-in implementations
    "RetryPolicy",
    "RetryConfig",
    "RetryResult",
    "CircuitBreaker",
    "CircuitState",
    "CircuitConfig",
    "RateLimiter",
    "RateLimitConfig",
    # Decorators (quick usage)
    "with_retry",
    "with_circuit_breaker",
    "with_timeout",
]
