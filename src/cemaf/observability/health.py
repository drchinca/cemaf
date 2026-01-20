"""
Health check system for CEMAF applications.

Provides health checks for monitoring application status.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from cemaf.core.types import JSON


class HealthStatus(str, Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class HealthCheckResult:
    """Result of a health check."""

    name: str
    status: HealthStatus
    message: str | None = None
    details: JSON = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_healthy(self) -> bool:
        """Check if status is healthy."""
        return self.status == HealthStatus.HEALTHY


@dataclass
class HealthCheck:
    """
    Individual health check.

    Example:
        def check_cache() -> HealthCheckResult:
            try:
                cache.ping()
                return HealthCheckResult("cache", HealthStatus.HEALTHY)
            except Exception as e:
                return HealthCheckResult(
                    "cache",
                    HealthStatus.UNHEALTHY,
                    message=str(e)
                )

        health.register_check("cache", check_cache)
    """

    name: str
    check_fn: Callable[[], HealthCheckResult]
    critical: bool = True  # If False, degraded instead of unhealthy on failure


class HealthMonitor:
    """
    Health monitoring system.

    Aggregates multiple health checks and provides overall status.

    Example:
        health = HealthMonitor()
        health.register_check("llm", check_llm_connection)
        health.register_check("cache", check_cache_connection)

        status = await health.check_all()
        if status.status == HealthStatus.HEALTHY:
            print("All systems operational")
    """

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}

    def register_check(
        self,
        name: str,
        check_fn: Callable[[], HealthCheckResult],
        critical: bool = True,
    ) -> None:
        """
        Register a health check.

        Args:
            name: Check identifier
            check_fn: Function that performs the check
            critical: If True, failure causes UNHEALTHY; if False, DEGRADED
        """
        self._checks[name] = HealthCheck(name, check_fn, critical)

    def unregister_check(self, name: str) -> None:
        """Remove a health check."""
        self._checks.pop(name, None)

    async def check_all(self) -> HealthCheckResult:
        """
        Run all registered health checks.

        Returns:
            Aggregated health check result
        """
        if not self._checks:
            return HealthCheckResult(
                name="system",
                status=HealthStatus.HEALTHY,
                message="No checks registered",
            )

        results: dict[str, HealthCheckResult] = {}
        failed_critical = []
        failed_non_critical = []

        for name, check in self._checks.items():
            try:
                result = check.check_fn()
                results[name] = result

                if result.status != HealthStatus.HEALTHY:
                    if check.critical:
                        failed_critical.append(name)
                    else:
                        failed_non_critical.append(name)
            except Exception as e:
                # Check function itself failed
                error_result = HealthCheckResult(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {str(e)}",
                )
                results[name] = error_result
                if check.critical:
                    failed_critical.append(name)
                else:
                    failed_non_critical.append(name)

        # Determine overall status
        if failed_critical:
            overall_status = HealthStatus.UNHEALTHY
            message = f"Critical checks failed: {', '.join(failed_critical)}"
        elif failed_non_critical:
            overall_status = HealthStatus.DEGRADED
            message = f"Non-critical checks failed: {', '.join(failed_non_critical)}"
        else:
            overall_status = HealthStatus.HEALTHY
            message = f"All {len(results)} checks passed"

        return HealthCheckResult(
            name="system",
            status=overall_status,
            message=message,
            details={name: result.__dict__ for name, result in results.items()},
        )

    async def check_one(self, name: str) -> HealthCheckResult:
        """
        Run a single health check.

        Args:
            name: Check identifier

        Returns:
            Health check result

        Raises:
            KeyError: If check not registered
        """
        if name not in self._checks:
            raise KeyError(f"Health check not found: {name}")

        check = self._checks[name]
        try:
            return check.check_fn()
        except Exception as e:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check failed: {str(e)}",
            )

    def list_checks(self) -> list[str]:
        """List all registered check names."""
        return list(self._checks.keys())


# Global health monitor instance
_health_monitor: HealthMonitor | None = None


def get_health_monitor() -> HealthMonitor:
    """
    Get global health monitor instance.

    Returns:
        HealthMonitor singleton

    Example:
        health = get_health_monitor()
        health.register_check("cache", check_cache)
    """
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


def reset_health_monitor() -> None:
    """Reset health monitor (for testing)."""
    global _health_monitor
    _health_monitor = None
