"""Tests for resilience factory helpers."""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from cemaf.config.protocols import ResilienceSettings, Settings
from cemaf.resilience import (
    CircuitBreaker,
    RateLimiter,
    RetryPolicy,
    circuit_breaker_registry,
    create_circuit_breaker,
    create_circuit_breaker_from_config,
    create_rate_limiter,
    create_rate_limiter_from_config,
    create_retry_policy,
    create_retry_policy_from_config,
    rate_limiter_registry,
    retry_policy_registry,
)
from cemaf.resilience.retry import BackoffStrategy


def test_create_retry_policy_uses_full_config() -> None:
    policy = create_retry_policy(
        max_attempts=5,
        initial_delay_seconds=0.2,
        max_delay_seconds=3.0,
        backoff_strategy="fibonacci",
        backoff_multiplier=1.5,
        jitter=False,
    )

    assert isinstance(policy, RetryPolicy)
    assert policy.config.max_attempts == 5
    assert policy.config.initial_delay_seconds == 0.2
    assert policy.config.max_delay_seconds == 3.0
    assert policy.config.backoff_strategy == BackoffStrategy.FIBONACCI
    assert policy.config.backoff_multiplier == 1.5
    assert policy.config.jitter is False


def test_create_circuit_breaker_uses_success_threshold() -> None:
    breaker = create_circuit_breaker(
        failure_threshold=7,
        failure_window_seconds=12.0,
        recovery_timeout_seconds=4.0,
        success_threshold=3,
    )

    assert isinstance(breaker, CircuitBreaker)
    assert breaker.config.failure_threshold == 7
    assert breaker.config.failure_window_seconds == 12.0
    assert breaker.config.recovery_timeout_seconds == 4.0
    assert breaker.config.success_threshold == 3


def test_create_rate_limiter_uses_full_config() -> None:
    limiter = create_rate_limiter(
        requests_per_second=22.0,
        burst=44,
        wait_on_limit=False,
        max_wait_seconds=2.5,
    )

    assert isinstance(limiter, RateLimiter)
    assert limiter.config.rate == 22.0
    assert limiter.config.burst == 44
    assert limiter.config.wait_on_limit is False
    assert limiter.config.max_wait_seconds == 2.5


def test_register_custom_retry_policy_backend() -> None:
    captured: dict[str, object] = {}

    class CustomRetryPolicy:
        async def execute[T](
            self,
            func: Callable[..., Awaitable[T]],
            *args: Any,
            **kwargs: Any,
        ) -> T:
            return await func(*args, **kwargs)

    def factory(**kwargs: object) -> CustomRetryPolicy:
        captured.update(kwargs)
        return CustomRetryPolicy()

    retry_policy_registry.register(backend="unit-custom-retry", factory=factory)

    policy = create_retry_policy(backend="unit-custom-retry", max_attempts=9, service="search")

    assert isinstance(policy, CustomRetryPolicy)
    assert captured["max_attempts"] == 9
    assert captured["service"] == "search"


def test_create_registered_retry_policy_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class EnvRetryPolicy:
        async def execute[T](
            self,
            func: Callable[..., Awaitable[T]],
            *args: Any,
            **kwargs: Any,
        ) -> T:
            return await func(*args, **kwargs)

    def factory(**kwargs: object) -> EnvRetryPolicy:
        captured.update(kwargs)
        return EnvRetryPolicy()

    retry_policy_registry.register(backend="env-custom-retry", factory=factory)
    monkeypatch.setenv("CEMAF_RESILIENCE_RETRY_BACKEND", "env-custom-retry")
    monkeypatch.setenv("CEMAF_RESILIENCE_MAX_RETRIES", "8")
    monkeypatch.setenv("CEMAF_RESILIENCE_INITIAL_RETRY_DELAY_SECONDS", "0.4")
    monkeypatch.setenv("CEMAF_RESILIENCE_MAX_RETRY_DELAY_SECONDS", "5.0")
    monkeypatch.setenv("CEMAF_RESILIENCE_RETRY_BACKOFF_STRATEGY", "linear")
    monkeypatch.setenv("CEMAF_RESILIENCE_RETRY_BACKOFF_MULTIPLIER", "1.25")
    monkeypatch.setenv("CEMAF_RESILIENCE_RETRY_JITTER", "false")

    policy = create_retry_policy_from_config()

    assert isinstance(policy, EnvRetryPolicy)
    assert captured["max_attempts"] == 8
    assert captured["initial_delay_seconds"] == 0.4
    assert captured["max_delay_seconds"] == 5.0
    assert captured["backoff_strategy"] == "linear"
    assert captured["backoff_multiplier"] == 1.25
    assert captured["jitter"] is False


def test_resilience_from_config_uses_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CEMAF_RESILIENCE_RETRY_BACKEND",
        "CEMAF_RESILIENCE_MAX_RETRIES",
        "CEMAF_RESILIENCE_INITIAL_RETRY_DELAY_SECONDS",
        "CEMAF_RESILIENCE_MAX_RETRY_DELAY_SECONDS",
        "CEMAF_RESILIENCE_RETRY_BACKOFF_STRATEGY",
        "CEMAF_RESILIENCE_RETRY_BACKOFF_MULTIPLIER",
        "CEMAF_RESILIENCE_RETRY_JITTER",
        "CEMAF_RESILIENCE_CIRCUIT_BREAKER_BACKEND",
        "CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        "CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS",
        "CEMAF_RESILIENCE_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS",
        "CEMAF_RESILIENCE_CIRCUIT_BREAKER_SUCCESS_THRESHOLD",
        "CEMAF_RESILIENCE_RATE_LIMITER_BACKEND",
        "CEMAF_RESILIENCE_RATE_LIMIT_REQUESTS_PER_SECOND",
        "CEMAF_RESILIENCE_RATE_LIMIT_BURST",
        "CEMAF_RESILIENCE_RATE_LIMIT_WAIT_ON_LIMIT",
        "CEMAF_RESILIENCE_RATE_LIMIT_MAX_WAIT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(
        resilience=ResilienceSettings(
            max_retries=6,
            initial_retry_delay_seconds=0.15,
            max_retry_delay_seconds=9.0,
            retry_backoff_strategy="linear",
            retry_backoff_multiplier=1.4,
            retry_jitter=False,
            circuit_breaker_failure_threshold=4,
            circuit_breaker_failure_window_seconds=11.0,
            circuit_breaker_recovery_timeout_seconds=12.0,
            circuit_breaker_success_threshold=3,
            rate_limit_requests_per_second=33.0,
            rate_limit_burst=34,
            rate_limit_wait_on_limit=False,
            rate_limit_max_wait_seconds=2.25,
        )
    )

    policy = create_retry_policy_from_config(settings=settings)
    breaker = create_circuit_breaker_from_config(settings=settings)
    limiter = create_rate_limiter_from_config(settings=settings)

    assert isinstance(policy, RetryPolicy)
    assert policy.config.max_attempts == 6
    assert policy.config.initial_delay_seconds == 0.15
    assert policy.config.max_delay_seconds == 9.0
    assert policy.config.backoff_strategy == BackoffStrategy.LINEAR
    assert policy.config.backoff_multiplier == 1.4
    assert policy.config.jitter is False

    assert isinstance(breaker, CircuitBreaker)
    assert breaker.config.failure_threshold == 4
    assert breaker.config.failure_window_seconds == 11.0
    assert breaker.config.recovery_timeout_seconds == 12.0
    assert breaker.config.success_threshold == 3

    assert isinstance(limiter, RateLimiter)
    assert limiter.config.rate == 33.0
    assert limiter.config.burst == 34
    assert limiter.config.wait_on_limit is False
    assert limiter.config.max_wait_seconds == 2.25


def test_register_custom_circuit_breaker_backend() -> None:
    captured: dict[str, object] = {}

    class CustomCircuitBreaker:
        async def call[T](
            self,
            func: Callable[..., Awaitable[T]],
            *args: Any,
            **kwargs: Any,
        ) -> T:
            return await func(*args, **kwargs)

    def factory(**kwargs: object) -> CustomCircuitBreaker:
        captured.update(kwargs)
        return CustomCircuitBreaker()

    circuit_breaker_registry.register(backend="unit-custom-circuit", factory=factory)

    breaker = create_circuit_breaker(
        backend="unit-custom-circuit",
        failure_threshold=11,
        success_threshold=4,
    )

    assert isinstance(breaker, CustomCircuitBreaker)
    assert captured["failure_threshold"] == 11
    assert captured["success_threshold"] == 4


def test_create_registered_circuit_breaker_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class EnvCircuitBreaker:
        async def call[T](
            self,
            func: Callable[..., Awaitable[T]],
            *args: Any,
            **kwargs: Any,
        ) -> T:
            return await func(*args, **kwargs)

    def factory(**kwargs: object) -> EnvCircuitBreaker:
        captured.update(kwargs)
        return EnvCircuitBreaker()

    circuit_breaker_registry.register(backend="env-custom-circuit", factory=factory)
    monkeypatch.setenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_BACKEND", "env-custom-circuit")
    monkeypatch.setenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "12")
    monkeypatch.setenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS", "13.0")
    monkeypatch.setenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS", "14.0")
    monkeypatch.setenv("CEMAF_RESILIENCE_CIRCUIT_BREAKER_SUCCESS_THRESHOLD", "5")

    breaker = create_circuit_breaker_from_config()

    assert isinstance(breaker, EnvCircuitBreaker)
    assert captured["failure_threshold"] == 12
    assert captured["failure_window_seconds"] == 13.0
    assert captured["recovery_timeout_seconds"] == 14.0
    assert captured["success_threshold"] == 5


def test_register_custom_rate_limiter_backend() -> None:
    captured: dict[str, object] = {}

    class CustomRateLimiter:
        async def acquire(self, tokens: int = 1) -> bool:
            return True

    def factory(**kwargs: object) -> CustomRateLimiter:
        captured.update(kwargs)
        return CustomRateLimiter()

    rate_limiter_registry.register(backend="unit-custom-rate", factory=factory)

    limiter = create_rate_limiter(
        backend="unit-custom-rate",
        requests_per_second=15.0,
        burst=16,
        wait_on_limit=False,
        max_wait_seconds=1.5,
    )

    assert isinstance(limiter, CustomRateLimiter)
    assert captured["requests_per_second"] == 15.0
    assert captured["burst"] == 16
    assert captured["wait_on_limit"] is False
    assert captured["max_wait_seconds"] == 1.5


def test_create_registered_rate_limiter_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class EnvRateLimiter:
        async def acquire(self, tokens: int = 1) -> bool:
            return True

    def factory(**kwargs: object) -> EnvRateLimiter:
        captured.update(kwargs)
        return EnvRateLimiter()

    rate_limiter_registry.register(backend="env-custom-rate", factory=factory)
    monkeypatch.setenv("CEMAF_RESILIENCE_RATE_LIMITER_BACKEND", "env-custom-rate")
    monkeypatch.setenv("CEMAF_RESILIENCE_RATE_LIMIT_REQUESTS_PER_SECOND", "17.0")
    monkeypatch.setenv("CEMAF_RESILIENCE_RATE_LIMIT_BURST", "18")
    monkeypatch.setenv("CEMAF_RESILIENCE_RATE_LIMIT_WAIT_ON_LIMIT", "false")
    monkeypatch.setenv("CEMAF_RESILIENCE_RATE_LIMIT_MAX_WAIT_SECONDS", "1.75")

    limiter = create_rate_limiter_from_config()

    assert isinstance(limiter, EnvRateLimiter)
    assert captured["requests_per_second"] == 17.0
    assert captured["burst"] == 18
    assert captured["wait_on_limit"] is False
    assert captured["max_wait_seconds"] == 1.75


def test_unknown_resilience_backends_name_registries() -> None:
    with pytest.raises(ValueError, match="retry_policy_registry.register"):
        create_retry_policy(backend="missing-retry")
    with pytest.raises(ValueError, match="circuit_breaker_registry.register"):
        create_circuit_breaker(backend="missing-circuit")
    with pytest.raises(ValueError, match="rate_limiter_registry.register"):
        create_rate_limiter(backend="missing-rate")
