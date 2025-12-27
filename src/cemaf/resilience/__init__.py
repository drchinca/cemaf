"""
Resilience module - Fault tolerance patterns.

Provides:
- RetryPolicy: Configurable retry with backoff
- CircuitBreaker: Prevent cascading failures
- RateLimiter: Control request rates
- Timeout: Enforce time limits
- Bulkhead: Isolate failures
"""

from cemaf.resilience.retry import RetryPolicy, RetryConfig, RetryResult
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitConfig
from cemaf.resilience.rate_limiter import RateLimiter, RateLimitConfig
from cemaf.resilience.decorators import with_retry, with_circuit_breaker, with_timeout

__all__ = [
    # Retry
    "RetryPolicy",
    "RetryConfig",
    "RetryResult",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitState",
    "CircuitConfig",
    # Rate limiter
    "RateLimiter",
    "RateLimitConfig",
    # Decorators
    "with_retry",
    "with_circuit_breaker",
    "with_timeout",
]

