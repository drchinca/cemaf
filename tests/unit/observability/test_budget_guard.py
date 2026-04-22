"""Tests for BudgetGuard."""

import pytest

from cemaf.observability.budget_guard import AlertLevel, BudgetAlert, BudgetGuard


class TestBudgetAlert:
    """Tests for BudgetAlert frozen dataclass."""

    def test_create_alert(self) -> None:
        alert = BudgetAlert(
            level=AlertLevel.WARNING,
            utilization=0.75,
            message="test warning",
        )
        assert alert.level == AlertLevel.WARNING
        assert alert.utilization == 0.75
        assert alert.message == "test warning"

    def test_alert_is_frozen(self) -> None:
        alert = BudgetAlert(
            level=AlertLevel.INFO,
            utilization=0.5,
            message="info",
        )
        with pytest.raises(AttributeError):
            alert.level = AlertLevel.HALT  # type: ignore[misc]


class TestBudgetGuard:
    """Tests for BudgetGuard enforcement."""

    def test_initial_state(self) -> None:
        guard = BudgetGuard(max_cost_usd=1.0, max_total_tokens=100_000)
        assert guard.accumulated_cost_usd == 0.0
        assert guard.accumulated_tokens == 0
        assert guard.cost_utilization == 0.0
        assert guard.token_utilization == 0.0
        assert not guard.should_halt()
        assert guard.alerts == ()

    def test_record_usage_below_threshold(self) -> None:
        guard = BudgetGuard(max_cost_usd=1.0, max_total_tokens=100_000)
        alert = guard.record_usage(cost_usd=0.1, tokens=10_000)
        assert alert is None
        assert guard.accumulated_cost_usd == 0.1
        assert guard.accumulated_tokens == 10_000

    def test_warning_threshold(self) -> None:
        guard = BudgetGuard(
            max_cost_usd=1.0,
            max_total_tokens=100_000,
            warning_threshold=0.7,
        )
        alert = guard.record_usage(cost_usd=0.75, tokens=5_000)
        assert alert is not None
        assert alert.level == AlertLevel.WARNING
        assert len(guard.alerts) == 1

    def test_critical_threshold(self) -> None:
        guard = BudgetGuard(
            max_cost_usd=1.0,
            max_total_tokens=100_000,
            critical_threshold=0.9,
        )
        alert = guard.record_usage(cost_usd=0.95, tokens=5_000)
        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL

    def test_halt_at_budget_exhaustion(self) -> None:
        guard = BudgetGuard(max_cost_usd=1.0, max_total_tokens=100_000)
        guard.record_usage(cost_usd=1.0, tokens=50_000)
        assert guard.should_halt()
        assert guard.cost_utilization == 1.0

    def test_halt_on_token_exhaustion(self) -> None:
        guard = BudgetGuard(max_cost_usd=10.0, max_total_tokens=1_000)
        guard.record_usage(cost_usd=0.01, tokens=1_000)
        assert guard.should_halt()
        assert guard.token_utilization == 1.0

    def test_cumulative_usage(self) -> None:
        guard = BudgetGuard(max_cost_usd=1.0, max_total_tokens=100_000)
        guard.record_usage(cost_usd=0.3, tokens=20_000)
        guard.record_usage(cost_usd=0.3, tokens=20_000)
        guard.record_usage(cost_usd=0.3, tokens=20_000)
        assert abs(guard.accumulated_cost_usd - 0.9) < 1e-10
        assert guard.accumulated_tokens == 60_000
        assert not guard.should_halt()

    def test_halt_alert_returned(self) -> None:
        guard = BudgetGuard(max_cost_usd=0.5, max_total_tokens=100_000)
        alert = guard.record_usage(cost_usd=0.6, tokens=100)
        assert alert is not None
        assert alert.level == AlertLevel.HALT
        assert guard.should_halt()

    def test_to_dict(self) -> None:
        guard = BudgetGuard(max_cost_usd=2.0, max_total_tokens=50_000)
        guard.record_usage(cost_usd=0.5, tokens=10_000)
        result = guard.to_dict()
        assert result["max_cost_usd"] == 2.0
        assert result["max_total_tokens"] == 50_000
        assert result["accumulated_cost_usd"] == 0.5
        assert result["accumulated_tokens"] == 10_000
        assert result["cost_utilization"] == 0.25
        assert result["token_utilization"] == 0.2
        assert result["halted"] is False

    def test_zero_budget_halts_immediately(self) -> None:
        guard = BudgetGuard(max_cost_usd=0.0, max_total_tokens=0)
        assert guard.should_halt()
        assert guard.cost_utilization == 1.0
        assert guard.token_utilization == 1.0

    def test_multiple_alerts_accumulated(self) -> None:
        guard = BudgetGuard(
            max_cost_usd=1.0,
            max_total_tokens=100_000,
            warning_threshold=0.5,
            critical_threshold=0.8,
        )
        guard.record_usage(cost_usd=0.6, tokens=1_000)
        guard.record_usage(cost_usd=0.25, tokens=1_000)
        guard.record_usage(cost_usd=0.2, tokens=1_000)
        assert len(guard.alerts) == 3
        assert guard.alerts[0].level == AlertLevel.WARNING
        assert guard.alerts[1].level == AlertLevel.CRITICAL
        assert guard.alerts[2].level == AlertLevel.HALT


class TestAlertLevel:
    """Tests for AlertLevel enum."""

    def test_values(self) -> None:
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.CRITICAL.value == "critical"
        assert AlertLevel.HALT.value == "halt"
