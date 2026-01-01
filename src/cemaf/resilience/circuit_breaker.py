"""
Circuit breaker - Prevent cascading failures.

States:
- CLOSED: Normal operation, failures counted
- OPEN: Failing fast, no calls allowed
- HALF_OPEN: Testing if service recovered
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

from cemaf.core.utils import utc_now


class CircuitState(str, Enum):
    """State of the circuit breaker."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitConfig(BaseModel):
    """Configuration for circuit breaker."""

    model_config = {"frozen": True}

    # Failure threshold to open circuit
    failure_threshold: int = 5

    # Time window for counting failures
    failure_window_seconds: float = 60.0

    # Time to wait before testing recovery
    recovery_timeout_seconds: float = 30.0

    # Successes needed in half-open to close
    success_threshold: int = 2

    # Exceptions that count as failures
    failure_exceptions: tuple[type, ...] = (Exception,)


@dataclass
class CircuitMetrics:
    """Metrics for circuit breaker."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0

    # Recent failures (within window)
    recent_failures: list[datetime] = field(default_factory=list)

    # State transitions
    times_opened: int = 0
    times_closed: int = 0

    last_failure: datetime | None = None
    last_success: datetime | None = None
    last_state_change: datetime | None = None


class CircuitOpenError(Exception):
    """Raised when circuit is open."""

    def __init__(self, message: str = "Circuit breaker is open"):
        super().__init__(message)


T = TypeVar("T")


class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.

    Prevents cascading failures by failing fast when service is unhealthy.

    Usage:
        breaker = CircuitBreaker(CircuitConfig(failure_threshold=5))

        try:
            result = await breaker.execute(my_function)
        except CircuitOpenError:
            # Circuit is open, use fallback
            result = fallback_value
    """

    def __init__(self, config: CircuitConfig | None = None) -> None:
        self._config = config or CircuitConfig()
        self._state = CircuitState.CLOSED
        self._metrics = CircuitMetrics()
        self._half_open_successes = 0
        self._opened_at: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def metrics(self) -> CircuitMetrics:
        """Circuit metrics."""
        return self._metrics

    @property
    def is_open(self) -> bool:
        """Whether circuit is open (failing fast)."""
        return self._state == CircuitState.OPEN

    def _clean_old_failures(self) -> None:
        """Remove failures outside the window."""
        cutoff = utc_now() - timedelta(seconds=self._config.failure_window_seconds)
        self._metrics.recent_failures = [f for f in self._metrics.recent_failures if f > cutoff]

    def _should_open(self) -> bool:
        """Check if circuit should open."""
        self._clean_old_failures()
        return len(self._metrics.recent_failures) >= self._config.failure_threshold

    def _should_attempt_reset(self) -> bool:
        """Check if we should try half-open state."""
        if self._opened_at is None:
            return True

        elapsed = (utc_now() - self._opened_at).total_seconds()
        return elapsed >= self._config.recovery_timeout_seconds

    def _record_success(self) -> None:
        """Record a successful call."""
        self._metrics.total_calls += 1
        self._metrics.successful_calls += 1
        self._metrics.last_success = utc_now()

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self._config.success_threshold:
                self._close()

    def _record_failure(self) -> None:
        """Record a failed call."""
        now = utc_now()
        self._metrics.total_calls += 1
        self._metrics.failed_calls += 1
        self._metrics.last_failure = now
        self._metrics.recent_failures.append(now)

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open opens circuit
            self._open()
        elif self._state == CircuitState.CLOSED and self._should_open():
            self._open()

    def _open(self) -> None:
        """Open the circuit."""
        self._state = CircuitState.OPEN
        self._opened_at = utc_now()
        self._metrics.times_opened += 1
        self._metrics.last_state_change = self._opened_at
        self._half_open_successes = 0

    def _close(self) -> None:
        """Close the circuit."""
        self._state = CircuitState.CLOSED
        self._metrics.times_closed += 1
        self._metrics.last_state_change = utc_now()
        self._half_open_successes = 0
        self._metrics.recent_failures.clear()

    def _half_open(self) -> None:
        """Enter half-open state."""
        self._state = CircuitState.HALF_OPEN
        self._metrics.last_state_change = utc_now()
        self._half_open_successes = 0

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute function through circuit breaker.

        Raises CircuitOpenError if circuit is open.
        """
        async with self._lock:
            # Check state
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._half_open()
                else:
                    self._metrics.rejected_calls += 1
                    raise CircuitOpenError()

        # Execute the function
        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._record_success()
            return result
        except Exception as e:
            if isinstance(e, self._config.failure_exceptions):
                async with self._lock:
                    self._record_failure()
            raise

    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        self._close()
        self._metrics = CircuitMetrics()

    async def __aenter__(self) -> CircuitBreaker:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False
