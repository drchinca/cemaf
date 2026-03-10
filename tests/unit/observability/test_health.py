"""Tests for health check system."""

import pytest

from cemaf.observability.health import (
    HealthCheck,
    HealthCheckResult,
    HealthMonitor,
    HealthStatus,
    get_health_monitor,
    reset_health_monitor,
)


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_healthy_status(self):
        """Test HEALTHY status value."""
        assert HealthStatus.HEALTHY == "healthy"

    def test_degraded_status(self):
        """Test DEGRADED status value."""
        assert HealthStatus.DEGRADED == "degraded"

    def test_unhealthy_status(self):
        """Test UNHEALTHY status value."""
        assert HealthStatus.UNHEALTHY == "unhealthy"


class TestHealthCheckResult:
    """Test HealthCheckResult dataclass."""

    def test_create_healthy_result(self):
        """Test creating a healthy check result."""
        result = HealthCheckResult(
            name="test_check",
            status=HealthStatus.HEALTHY,
        )
        assert result.name == "test_check"
        assert result.status == HealthStatus.HEALTHY
        assert result.message is None
        assert result.details == {}
        assert result.checked_at is not None

    def test_create_unhealthy_result(self):
        """Test creating an unhealthy check result."""
        result = HealthCheckResult(
            name="test_check",
            status=HealthStatus.UNHEALTHY,
            message="Service unavailable",
            details={"error": "Connection refused"},
        )
        assert result.name == "test_check"
        assert result.status == HealthStatus.UNHEALTHY
        assert result.message == "Service unavailable"
        assert result.details == {"error": "Connection refused"}

    def test_is_healthy_true(self):
        """Test is_healthy returns True for HEALTHY status."""
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.HEALTHY,
        )
        assert result.is_healthy() is True

    def test_is_healthy_false_for_degraded(self):
        """Test is_healthy returns False for DEGRADED status."""
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.DEGRADED,
        )
        assert result.is_healthy() is False

    def test_is_healthy_false_for_unhealthy(self):
        """Test is_healthy returns False for UNHEALTHY status."""
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.UNHEALTHY,
        )
        assert result.is_healthy() is False

    def test_frozen_dataclass(self):
        """Test that HealthCheckResult is frozen."""
        result = HealthCheckResult(
            name="test",
            status=HealthStatus.HEALTHY,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.status = HealthStatus.UNHEALTHY


class TestHealthCheck:
    """Test HealthCheck dataclass."""

    def test_create_health_check(self):
        """Test creating a health check."""

        def check_fn():
            return HealthCheckResult("test", HealthStatus.HEALTHY)

        check = HealthCheck(
            name="test_check",
            check_fn=check_fn,
            critical=True,
        )
        assert check.name == "test_check"
        assert check.check_fn == check_fn
        assert check.critical is True

    def test_default_critical_true(self):
        """Test that critical defaults to True."""

        def check_fn():
            return HealthCheckResult("test", HealthStatus.HEALTHY)

        check = HealthCheck(name="test", check_fn=check_fn)
        assert check.critical is True


class TestHealthMonitor:
    """Test HealthMonitor class."""

    def test_create_monitor(self):
        """Test creating a health monitor."""
        monitor = HealthMonitor()
        assert monitor.list_checks() == []
        assert len(monitor.list_checks()) == 0

    def test_register_check(self):
        """Test registering a health check."""
        monitor = HealthMonitor()

        def check_fn():
            return HealthCheckResult("cache", HealthStatus.HEALTHY)

        monitor.register_check("cache", check_fn)
        assert "cache" in monitor.list_checks()
        assert len(monitor.list_checks()) == 1

    def test_register_non_critical_check(self):
        """Test registering a non-critical check."""
        monitor = HealthMonitor()

        def check_fn():
            return HealthCheckResult("metrics", HealthStatus.HEALTHY)

        monitor.register_check("metrics", check_fn, critical=False)
        assert "metrics" in monitor.list_checks()

    def test_unregister_check(self):
        """Test unregistering a check."""
        monitor = HealthMonitor()

        def check_fn():
            return HealthCheckResult("cache", HealthStatus.HEALTHY)

        monitor.register_check("cache", check_fn)
        assert len(monitor.list_checks()) == 1

        monitor.unregister_check("cache")
        assert len(monitor.list_checks()) == 0
        assert "cache" not in monitor.list_checks()

    def test_unregister_nonexistent_check(self):
        """Test unregistering a check that doesn't exist."""
        monitor = HealthMonitor()
        monitor.unregister_check("nonexistent")  # Should not raise
        assert len(monitor.list_checks()) == 0
        assert "nonexistent" not in monitor.list_checks()

    @pytest.mark.asyncio
    async def test_check_all_empty(self):
        """Test check_all with no registered checks."""
        monitor = HealthMonitor()
        result = await monitor.check_all()

        assert result.name == "system"
        assert result.status == HealthStatus.HEALTHY
        assert result.message == "No checks registered"

    @pytest.mark.asyncio
    async def test_check_all_single_healthy(self):
        """Test check_all with single healthy check."""
        monitor = HealthMonitor()

        def check_cache():
            return HealthCheckResult("cache", HealthStatus.HEALTHY)

        monitor.register_check("cache", check_cache)
        result = await monitor.check_all()

        assert result.status == HealthStatus.HEALTHY
        assert "1 checks passed" in result.message
        assert "cache" in result.details

    @pytest.mark.asyncio
    async def test_check_all_multiple_healthy(self):
        """Test check_all with multiple healthy checks."""
        monitor = HealthMonitor()

        def check_cache():
            return HealthCheckResult("cache", HealthStatus.HEALTHY)

        def check_db():
            return HealthCheckResult("database", HealthStatus.HEALTHY)

        monitor.register_check("cache", check_cache)
        monitor.register_check("database", check_db)
        result = await monitor.check_all()

        assert result.status == HealthStatus.HEALTHY
        assert "2 checks passed" in result.message
        assert len(result.details) == 2

    @pytest.mark.asyncio
    async def test_check_all_critical_failure(self):
        """Test check_all with critical check failing."""
        monitor = HealthMonitor()

        def check_cache():
            return HealthCheckResult("cache", HealthStatus.HEALTHY)

        def check_db():
            return HealthCheckResult(
                "database",
                HealthStatus.UNHEALTHY,
                message="Connection failed",
            )

        monitor.register_check("cache", check_cache)
        monitor.register_check("database", check_db, critical=True)
        result = await monitor.check_all()

        assert result.status == HealthStatus.UNHEALTHY
        assert "Critical checks failed" in result.message
        assert "database" in result.message

    @pytest.mark.asyncio
    async def test_check_all_non_critical_failure(self):
        """Test check_all with non-critical check failing."""
        monitor = HealthMonitor()

        def check_cache():
            return HealthCheckResult("cache", HealthStatus.HEALTHY)

        def check_metrics():
            return HealthCheckResult(
                "metrics",
                HealthStatus.UNHEALTHY,
                message="Metrics service down",
            )

        monitor.register_check("cache", check_cache, critical=True)
        monitor.register_check("metrics", check_metrics, critical=False)
        result = await monitor.check_all()

        assert result.status == HealthStatus.DEGRADED
        assert "Non-critical checks failed" in result.message
        assert "metrics" in result.message

    @pytest.mark.asyncio
    async def test_check_all_mixed_failures(self):
        """Test check_all with both critical and non-critical failures."""
        monitor = HealthMonitor()

        def check_db():
            return HealthCheckResult(
                "database",
                HealthStatus.UNHEALTHY,
                message="DB down",
            )

        def check_metrics():
            return HealthCheckResult(
                "metrics",
                HealthStatus.DEGRADED,
                message="Metrics slow",
            )

        monitor.register_check("database", check_db, critical=True)
        monitor.register_check("metrics", check_metrics, critical=False)
        result = await monitor.check_all()

        # Critical failures take precedence
        assert result.status == HealthStatus.UNHEALTHY
        assert "Critical checks failed" in result.message

    @pytest.mark.asyncio
    async def test_check_all_exception_in_check(self):
        """Test check_all when check function raises exception."""
        monitor = HealthMonitor()

        def failing_check():
            raise RuntimeError("Check crashed")

        monitor.register_check("crash", failing_check)
        result = await monitor.check_all()

        assert result.status == HealthStatus.UNHEALTHY
        assert "Critical checks failed" in result.message
        assert "crash" in result.message
        assert "crash" in result.details

    @pytest.mark.asyncio
    async def test_check_one_success(self):
        """Test checking a single health check."""
        monitor = HealthMonitor()

        def check_cache():
            return HealthCheckResult("cache", HealthStatus.HEALTHY)

        monitor.register_check("cache", check_cache)
        result = await monitor.check_one("cache")

        assert result.name == "cache"
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_one_not_found(self):
        """Test checking a non-existent health check."""
        monitor = HealthMonitor()

        with pytest.raises(KeyError, match="Health check not found: nonexistent"):
            await monitor.check_one("nonexistent")

    @pytest.mark.asyncio
    async def test_check_one_exception(self):
        """Test check_one when check function raises exception."""
        monitor = HealthMonitor()

        def failing_check():
            raise ValueError("Test error")

        monitor.register_check("fail", failing_check)
        result = await monitor.check_one("fail")

        assert result.status == HealthStatus.UNHEALTHY
        assert "Check failed" in result.message

    def test_list_checks(self):
        """Test listing all registered checks."""
        monitor = HealthMonitor()

        def check1():
            return HealthCheckResult("check1", HealthStatus.HEALTHY)

        def check2():
            return HealthCheckResult("check2", HealthStatus.HEALTHY)

        monitor.register_check("check1", check1)
        monitor.register_check("check2", check2)

        checks = monitor.list_checks()
        assert len(checks) == 2
        assert "check1" in checks
        assert "check2" in checks


class TestGlobalHealthMonitor:
    """Test global health monitor singleton."""

    def setup_method(self):
        """Reset health monitor before each test."""
        reset_health_monitor()

    def teardown_method(self):
        """Reset health monitor after each test."""
        reset_health_monitor()

    def test_get_health_monitor_singleton(self):
        """Test that get_health_monitor returns singleton."""
        monitor1 = get_health_monitor()
        monitor2 = get_health_monitor()
        assert monitor1 is monitor2

    def test_get_health_monitor_returns_monitor(self):
        """Test that get_health_monitor returns HealthMonitor instance."""
        monitor = get_health_monitor()
        assert isinstance(monitor, HealthMonitor)

    @pytest.mark.asyncio
    async def test_global_monitor_usage(self):
        """Test using global monitor."""
        monitor = get_health_monitor()

        def check_fn():
            return HealthCheckResult("test", HealthStatus.HEALTHY)

        monitor.register_check("test", check_fn)
        result = await monitor.check_all()

        assert result.status == HealthStatus.HEALTHY

    def test_reset_health_monitor(self):
        """Test resetting health monitor."""
        monitor1 = get_health_monitor()

        def check_fn():
            return HealthCheckResult("test", HealthStatus.HEALTHY)

        monitor1.register_check("test", check_fn)

        reset_health_monitor()
        monitor2 = get_health_monitor()

        assert monitor1 is not monitor2
        assert len(monitor2.list_checks()) == 0
