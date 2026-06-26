"""Registry-backed factory functions for resilience components.

Provides convenient ways to create resilience patterns (retry, circuit breaker,
rate limiting) with sensible defaults while maintaining dependency injection principles.

Extension Point:
    Register custom retry, circuit breaker, and rate limiter backends with the
    relevant registry.
"""

import os
from typing import Any, cast

from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
from cemaf.resilience.protocols import CircuitBreakerProtocol, RateLimiterProtocol, RetryStrategy
from cemaf.resilience.rate_limiter import RateLimitConfig, RateLimiter
from cemaf.resilience.retry import BackoffStrategy, RetryConfig, RetryPolicy

retry_policy_registry: ProviderRegistry[RetryStrategy] = ProviderRegistry(name="retry_policy")
circuit_breaker_registry: ProviderRegistry[CircuitBreakerProtocol] = ProviderRegistry(name="circuit_breaker")
rate_limiter_registry: ProviderRegistry[RateLimiterProtocol] = ProviderRegistry(name="rate_limiter")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() == "true"


def _create_default_retry_policy(**kwargs: Any) -> RetryStrategy:
    backoff_strategy = kwargs.get("backoff_strategy", BackoffStrategy.EXPONENTIAL)
    strategy_enum = (
        BackoffStrategy(backoff_strategy) if isinstance(backoff_strategy, str) else backoff_strategy
    )
    config = RetryConfig(
        max_attempts=int(kwargs.get("max_attempts", 3)),
        initial_delay_seconds=float(kwargs.get("initial_delay_seconds", 1.0)),
        max_delay_seconds=float(kwargs.get("max_delay_seconds", 60.0)),
        backoff_strategy=strategy_enum,
        backoff_multiplier=float(kwargs.get("backoff_multiplier", 2.0)),
        jitter=bool(kwargs.get("jitter", True)),
        jitter_factor=float(kwargs.get("jitter_factor", 0.1)),
    )
    return cast(RetryStrategy, RetryPolicy(config))


def _create_default_circuit_breaker(**kwargs: Any) -> CircuitBreakerProtocol:
    config = CircuitConfig(
        failure_threshold=int(kwargs.get("failure_threshold", 5)),
        failure_window_seconds=float(kwargs.get("failure_window_seconds", 60.0)),
        recovery_timeout_seconds=float(kwargs.get("recovery_timeout_seconds", 30.0)),
        success_threshold=int(kwargs.get("success_threshold", 2)),
    )
    return CircuitBreaker(config)


def _create_token_bucket_rate_limiter(**kwargs: Any) -> RateLimiterProtocol:
    config = RateLimitConfig(
        rate=float(kwargs.get("requests_per_second", kwargs.get("rate", 10.0))),
        burst=int(kwargs.get("burst", 10)),
        wait_on_limit=bool(kwargs.get("wait_on_limit", True)),
        max_wait_seconds=float(kwargs.get("max_wait_seconds", 30.0)),
    )
    return RateLimiter(config)


retry_policy_registry.register(backend="default", factory=_create_default_retry_policy)
circuit_breaker_registry.register(backend="default", factory=_create_default_circuit_breaker)
rate_limiter_registry.register(backend="token_bucket", factory=_create_token_bucket_rate_limiter)


def create_retry_policy(
    max_attempts: int = 3,
    initial_delay_seconds: float = 1.0,
    max_delay_seconds: float = 60.0,
    backoff_strategy: str = "exponential",
    backoff_multiplier: float = 2.0,
    jitter: bool = True,
    jitter_factor: float = 0.1,
    backend: str = "default",
    **backend_options: Any,
) -> RetryStrategy:
    """
    Factory for RetryPolicy with sensible defaults.

    Args:
        max_attempts: Maximum retry attempts
        initial_delay_seconds: Initial delay between retries
        max_delay_seconds: Maximum delay between retries
        backoff_strategy: Backoff strategy (constant, linear, exponential, fibonacci)
        backoff_multiplier: Multiplier for exponential backoff
        jitter: Add randomized delay variance
        jitter_factor: Percent of delay used for jitter range
        backend: Registered retry backend name

    Returns:
        Configured RetryPolicy instance

    Example:
        # With defaults
        policy = create_retry_policy()

        # Custom configuration
        policy = create_retry_policy(max_attempts=5, backoff_strategy="fibonacci")
    """
    return retry_policy_registry.create(
        backend=backend,
        max_attempts=max_attempts,
        initial_delay_seconds=initial_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        backoff_strategy=backoff_strategy,
        backoff_multiplier=backoff_multiplier,
        jitter=jitter,
        jitter_factor=jitter_factor,
        **backend_options,
    )


def create_circuit_breaker(
    failure_threshold: int = 5,
    failure_window_seconds: float = 60.0,
    recovery_timeout_seconds: float = 30.0,
    success_threshold: int = 2,
    backend: str = "default",
    **backend_options: Any,
) -> CircuitBreakerProtocol:
    """
    Factory for CircuitBreaker with sensible defaults.

    Args:
        failure_threshold: Number of failures before opening circuit
        failure_window_seconds: Time window for counting failures
        recovery_timeout_seconds: Time to wait before trying recovery
        success_threshold: Successes needed in half-open to close
        backend: Registered circuit breaker backend name

    Returns:
        Configured CircuitBreaker instance

    Example:
        # With defaults
        breaker = create_circuit_breaker()

        # Custom thresholds
        breaker = create_circuit_breaker(failure_threshold=10)
    """
    return circuit_breaker_registry.create(
        backend=backend,
        failure_threshold=failure_threshold,
        failure_window_seconds=failure_window_seconds,
        recovery_timeout_seconds=recovery_timeout_seconds,
        success_threshold=success_threshold,
        **backend_options,
    )


def create_rate_limiter(
    requests_per_second: float = 10.0,
    burst: int = 10,
    wait_on_limit: bool = True,
    max_wait_seconds: float = 30.0,
    backend: str = "token_bucket",
    **backend_options: Any,
) -> RateLimiterProtocol:
    """
    Factory for RateLimiter with sensible defaults.

    Args:
        requests_per_second: Rate limit (requests per second)
        burst: Burst capacity (max tokens in bucket)
        wait_on_limit: Wait for tokens instead of rejecting immediately
        max_wait_seconds: Maximum wait before rejecting
        backend: Registered rate limiter backend name

    Returns:
        Configured RateLimiter instance

    Example:
        # With defaults
        limiter = create_rate_limiter()

        # Higher rate
        limiter = create_rate_limiter(requests_per_second=100.0, burst=200)
    """
    return rate_limiter_registry.create(
        backend=backend,
        requests_per_second=requests_per_second,
        burst=burst,
        wait_on_limit=wait_on_limit,
        max_wait_seconds=max_wait_seconds,
        **backend_options,
    )


def create_retry_policy_from_config(settings: Settings | None = None) -> RetryStrategy:
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

    backend = os.getenv("CEMAF_RESILIENCE_RETRY_BACKEND", "default")
    max_attempts = int(os.getenv("CEMAF_RESILIENCE_MAX_RETRIES", "3"))
    initial_delay = float(os.getenv("CEMAF_RESILIENCE_INITIAL_RETRY_DELAY_SECONDS", "1.0"))
    max_delay = float(os.getenv("CEMAF_RESILIENCE_MAX_RETRY_DELAY_SECONDS", "60.0"))
    backoff_strategy = os.getenv("CEMAF_RESILIENCE_RETRY_BACKOFF_STRATEGY", "exponential")
    backoff_multiplier = float(os.getenv("CEMAF_RESILIENCE_RETRY_BACKOFF_MULTIPLIER", "2.0"))
    jitter = _env_bool("CEMAF_RESILIENCE_RETRY_JITTER", True)

    return create_retry_policy(
        backend=backend,
        max_attempts=max_attempts,
        initial_delay_seconds=initial_delay,
        max_delay_seconds=max_delay,
        backoff_strategy=backoff_strategy,
        backoff_multiplier=backoff_multiplier,
        jitter=jitter,
    )


def create_circuit_breaker_from_config(settings: Settings | None = None) -> CircuitBreakerProtocol:
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
    _ = settings
    backend = os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_BACKEND", "default")
    failure_threshold = int(os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5"))
    failure_window = float(os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS", "60.0"))
    recovery_timeout = float(os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS", "30.0"))
    success_threshold = int(os.getenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_SUCCESS_THRESHOLD", "2"))

    return create_circuit_breaker(
        backend=backend,
        failure_threshold=failure_threshold,
        failure_window_seconds=failure_window,
        recovery_timeout_seconds=recovery_timeout,
        success_threshold=success_threshold,
    )


def create_rate_limiter_from_config(settings: Settings | None = None) -> RateLimiterProtocol:
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
    _ = settings
    backend = os.getenv("CEMAF_RESILIENCE_RATE_LIMITER_BACKEND", "token_bucket")
    requests_per_second = float(os.getenv("CEMAF_RESILIENCE_RATE_LIMIT_REQUESTS_PER_SECOND", "10.0"))
    burst = int(os.getenv("CEMAF_RESILIENCE_RATE_LIMIT_BURST", "10"))
    wait_on_limit = _env_bool("CEMAF_RESILIENCE_RATE_LIMIT_WAIT_ON_LIMIT", True)
    max_wait_seconds = float(os.getenv("CEMAF_RESILIENCE_RATE_LIMIT_MAX_WAIT_SECONDS", "30.0"))

    return create_rate_limiter(
        backend=backend,
        requests_per_second=requests_per_second,
        burst=burst,
        wait_on_limit=wait_on_limit,
        max_wait_seconds=max_wait_seconds,
    )
