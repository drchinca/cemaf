"""
Factory functions for resilience components.

Provides convenient ways to create resilience patterns (retry, circuit breaker,
rate limiting) with sensible defaults while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_X_from_config() functions
    include clear "EXTEND HERE" sections where you can add your own implementations.
"""

import os

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter
from cemaf.resilience.retry import RetryConfig, RetryPolicy


def create_retry_policy(
    max_attempts: int = 3,
    initial_delay_seconds: float = 1.0,
    backoff_strategy: str = "exponential",
) -> RetryPolicy:
    """
    Factory for RetryPolicy with sensible defaults.

    Args:
        max_attempts: Maximum retry attempts
        initial_delay_seconds: Initial delay between retries
        backoff_strategy: Backoff strategy (constant, linear, exponential, fibonacci)

    Returns:
        Configured RetryPolicy instance

    Example:
        # With defaults
        policy = create_retry_policy()

        # Custom configuration
        policy = create_retry_policy(max_attempts=5, backoff_strategy="fibonacci")
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        initial_delay_seconds=initial_delay_seconds,
        backoff_strategy=backoff_strategy,
    )
    return RetryPolicy(config)


def create_circuit_breaker(
    failure_threshold: int = 5,
    failure_window_seconds: float = 60.0,
    recovery_timeout_seconds: float = 30.0,
) -> CircuitBreaker:
    """
    Factory for CircuitBreaker with sensible defaults.

    Args:
        failure_threshold: Number of failures before opening circuit
        failure_window_seconds: Time window for counting failures
        recovery_timeout_seconds: Time to wait before trying recovery

    Returns:
        Configured CircuitBreaker instance

    Example:
        # With defaults
        breaker = create_circuit_breaker()

        # Custom thresholds
        breaker = create_circuit_breaker(failure_threshold=10)
    """
    config = CircuitConfig(
        failure_threshold=failure_threshold,
        failure_window_seconds=failure_window_seconds,
        recovery_timeout_seconds=recovery_timeout_seconds,
    )
    return CircuitBreaker(config)


def create_rate_limiter(
    requests_per_second: float = 10.0,
    burst: int = 10,
) -> RateLimiter:
    """
    Factory for RateLimiter with sensible defaults.

    Args:
        requests_per_second: Rate limit (requests per second)
        burst: Burst capacity (max tokens in bucket)

    Returns:
        Configured RateLimiter instance

    Example:
        # With defaults
        limiter = create_rate_limiter()

        # Higher rate
        limiter = create_rate_limiter(requests_per_second=100.0, burst=200)
    """
    config = RateLimitConfig(
        requests_per_second=requests_per_second,
        burst=burst,
    )
    return RateLimiter(config)


def create_retry_policy_from_config(settings: Settings | None = None) -> RetryPolicy:
    """
    Create RetryPolicy from environment configuration.

    Reads from environment variables:
    - CEMAF_RESILIENCE_MAX_RETRIES: Max retry attempts (default: 3)
    - CEMAF_RESILIENCE_INITIAL_RETRY_DELAY_SECONDS: Initial delay (default: 1.0)
    - CEMAF_RESILIENCE_RETRY_BACKOFF_STRATEGY: Backoff strategy (default: exponential)

    Returns:
        Configured RetryPolicy instance

    Example:
        # From environment
        policy = create_retry_policy_from_config()
    """
    cfg = settings or load_settings_from_env_sync()  # noqa: F841

    max_attempts = int(os.getenv("CEMAF_RESILIENCE_MAX_RETRIES", "3"))
    initial_delay = float(os.getenv("CEMAF_RESILIENCE_INITIAL_RETRY_DELAY_SECONDS", "1.0"))
    backoff_strategy = os.getenv("CEMAF_RESILIENCE_RETRY_BACKOFF_STRATEGY", "exponential")

    return create_retry_policy(
        max_attempts=max_attempts,
        initial_delay_seconds=initial_delay,
        backoff_strategy=backoff_strategy,
    )


def create_circuit_breaker_from_config(settings: Settings | None = None) -> CircuitBreaker:
    """
    Create CircuitBreaker from environment configuration.

    Reads from environment variables:
    - CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD: Failure threshold (default: 5)
    - CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS: Window (default: 60.0)
    - CEMAF_RESILIENCE_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS: Timeout (default: 30.0)

    Returns:
        Configured CircuitBreaker instance

    Example:
        # From environment
        breaker = create_circuit_breaker_from_config()
    """
    failure_threshold = int(os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5"))
    failure_window = float(os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS", "60.0"))
    recovery_timeout = float(os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS", "30.0"))

    return create_circuit_breaker(
        failure_threshold=failure_threshold,
        failure_window_seconds=failure_window,
        recovery_timeout_seconds=recovery_timeout,
    )


def create_rate_limiter_from_config(settings: Settings | None = None) -> RateLimiter:
    """
    Create RateLimiter from environment configuration.

    Reads from environment variables:
    - CEMAF_RESILIENCE_RATE_LIMIT_REQUESTS_PER_SECOND: Rate limit (default: 10.0)
    - CEMAF_RESILIENCE_RATE_LIMIT_BURST: Burst capacity (default: 10)

    Returns:
        Configured RateLimiter instance

    Example:
        # From environment
        limiter = create_rate_limiter_from_config()
    """
    requests_per_second = float(os.getenv("CEMAF_RESILIENCE_RATE_LIMIT_REQUESTS_PER_SECOND", "10.0"))
    burst = int(os.getenv("CEMAF_RESILIENCE_RATE_LIMIT_BURST", "10"))

    return create_rate_limiter(
        requests_per_second=requests_per_second,
        burst=burst,
    )
