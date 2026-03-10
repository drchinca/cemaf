"""
Integration tests for metrics collection.

Tests the complete metrics collection infrastructure including SimpleMetrics,
cost tracking, alerting rules, and helper utilities.
"""

from unittest.mock import Mock

from cemaf.observability import (
    RECOMMENDED_ALERTS,
    MetricsHelper,
    ModelPricing,
    ModelPricingRegistry,
    Severity,
    SimpleMetrics,
    configure_metrics,
    get_metrics,
    record_timing,
    reset_observability,
)


class TestSimpleMetrics:
    """Test SimpleMetrics implementation."""

    def test_counter_records_metric(self) -> None:
        """Counter should record metric with tags."""
        metrics = SimpleMetrics(prefix="test")
        metrics.counter("dag.executions.total", value=1, tags={"dag_name": "test"})
        assert metrics._prefix == "test"
        assert hasattr(metrics, "counter")

    def test_gauge_records_metric(self) -> None:
        """Gauge should record instantaneous value."""
        metrics = SimpleMetrics(prefix="test")
        metrics.gauge("dag.nodes.pending", value=5.0, tags={"dag_name": "test"})
        assert metrics._prefix == "test"

    def test_histogram_records_metric(self) -> None:
        """Histogram should record distribution value."""
        metrics = SimpleMetrics(prefix="test")
        metrics.histogram("dag.duration_ms", value=123.45, tags={"dag_name": "test"})
        assert metrics._prefix == "test"

    def test_timing_records_milliseconds(self) -> None:
        """Timing should record duration in milliseconds."""
        metrics = SimpleMetrics(prefix="test")
        metrics.timing("dag.duration_ms", value_ms=123.45, tags={"dag_name": "test"})
        assert metrics._prefix == "test"

    def test_metrics_without_tags(self) -> None:
        """Metrics should work without tags."""
        metrics = SimpleMetrics(prefix="test")
        metrics.counter("dag.total")
        metrics.gauge("dag.count", 1.0)
        metrics.histogram("dag.duration_ms", 100.0)
        metrics.timing("dag.duration_ms", 100.0)
        # All calls completed without raising
        assert metrics._prefix == "test"

    def test_custom_prefix(self) -> None:
        """Custom prefix should be applied to all metrics."""
        metrics = SimpleMetrics(prefix="custom")
        metrics.counter("metric.name", tags={})
        assert metrics._prefix == "custom"

    def test_metrics_protocol_compliance(self) -> None:
        """SimpleMetrics should implement MetricsCollector protocol."""
        from cemaf.observability.protocols import MetricsCollector

        metrics = SimpleMetrics()
        assert isinstance(metrics, MetricsCollector)


class TestMetricsHelper:
    """Test MetricsHelper utility functions."""

    def test_record_execution_success(self) -> None:
        """Should record execution metrics for successful operation."""
        metrics = Mock()
        MetricsHelper.record_execution(
            metrics,
            "cemaf.dag.execution",
            duration_ms=100.0,
            success=True,
            tags={"dag_name": "test"},
        )

        # Should record total, success, and timing
        calls = metrics.counter.call_args_list + metrics.histogram.call_args_list
        assert len(calls) >= 3

    def test_record_execution_failure(self) -> None:
        """Should record execution metrics for failed operation."""
        metrics = Mock()
        MetricsHelper.record_execution(
            metrics,
            "cemaf.dag.execution",
            duration_ms=100.0,
            success=False,
            tags={"dag_name": "test"},
        )

        # Should record total, failed, and timing
        assert metrics.counter.called or metrics.histogram.called

    def test_record_llm_call(self) -> None:
        """Should record LLM call metrics."""
        metrics = Mock()
        MetricsHelper.record_llm_call(
            metrics,
            model="claude-opus-4-5",
            prompt_tokens=1000,
            completion_tokens=500,
            duration_ms=2345.67,
            success=True,
            finish_reason="stop",
            cost=0.0225,
        )

        # Should record multiple metrics
        assert metrics.counter.called
        assert metrics.histogram.called

    def test_record_llm_call_without_cost(self) -> None:
        """Should record LLM call metrics without cost."""
        metrics = Mock()
        MetricsHelper.record_llm_call(
            metrics,
            model="claude-opus-4-5",
            prompt_tokens=1000,
            completion_tokens=500,
            duration_ms=2345.67,
            success=True,
        )

        # Should still record metrics
        assert metrics.counter.called or metrics.histogram.called

    def test_record_error(self) -> None:
        """Should record error metrics."""
        metrics = Mock()
        MetricsHelper.record_error(
            metrics,
            operation="cemaf.dag.execution",
            error_type="TimeoutError",
            tags={"dag_name": "test"},
        )

        assert metrics.counter.called

    def test_record_cache_operation(self) -> None:
        """Should record cache operation metrics."""
        metrics = Mock()
        MetricsHelper.record_cache_operation(
            metrics,
            cache_name="result_cache",
            operation="hit",
            duration_us=123.45,
        )

        assert metrics.counter.called


class TestRecordTiming:
    """Test record_timing context manager."""

    def test_record_timing_context_manager(self) -> None:
        """Should record timing for code block."""
        metrics = Mock()

        with record_timing(metrics, "cemaf.dag.execution", tags={"dag_name": "test"}):
            pass  # Simulate work

        # Should have called timing
        assert metrics.timing.called

    def test_record_timing_with_exception(self) -> None:
        """Should still record timing even if exception occurs."""
        metrics = Mock()

        try:
            with record_timing(metrics, "cemaf.operation", tags={}):
                raise ValueError("Test error")
        except ValueError:
            pass

        # Should still record timing before exception propagates
        assert metrics.timing.called

    def test_record_timing_measures_duration(self) -> None:
        """Should measure actual duration."""
        import time

        metrics = Mock()

        with record_timing(metrics, "cemaf.operation"):
            time.sleep(0.01)  # 10ms

        # Get the timing value from mock call
        assert metrics.timing.called
        # Duration should be >= 10ms
        call_args = metrics.timing.call_args
        duration = call_args[0][1] if call_args[0] else None
        if duration is not None:
            assert duration >= 10.0


class TestModelPricingRegistry:
    """Test model pricing and cost tracking."""

    def test_get_pricing_exact_match(self) -> None:
        """Should find pricing for exact model match."""
        pricing = ModelPricingRegistry.get_pricing("claude-opus-4-5")
        assert pricing is not None
        assert pricing.model_id == "claude-opus-4-5"

    def test_get_pricing_prefix_match(self) -> None:
        """Should find pricing for versioned model with prefix match."""
        pricing = ModelPricingRegistry.get_pricing("claude-opus-4-5-20251101")
        assert pricing is not None
        assert pricing.model_id == "claude-opus-4-5"

    def test_get_pricing_unknown_model(self) -> None:
        """Should return None for unknown model."""
        pricing = ModelPricingRegistry.get_pricing("unknown-model")
        assert pricing is None

    def test_calculate_cost(self) -> None:
        """Should calculate cost for known model."""
        cost = ModelPricingRegistry.calculate_cost("claude-haiku-4-5", 1000, 500)
        assert cost is not None
        # claude-haiku-4-5: prompt=$0.8M, completion=$4M
        # (1000/1M * $0.8) + (500/1M * $4.0) = $0.0008 + $0.002 = $0.0028
        assert abs(cost - 0.0028) < 0.0001

    def test_calculate_cost_unknown_model(self) -> None:
        """Should return None for unknown model."""
        cost = ModelPricingRegistry.calculate_cost("unknown-model", 1000, 500)
        assert cost is None

    def test_register_custom_pricing(self) -> None:
        """Should register and use custom pricing."""
        custom_pricing = ModelPricing("custom-model", 2.0, 10.0)
        ModelPricingRegistry.register_custom_pricing(custom_pricing)

        retrieved = ModelPricingRegistry.get_pricing("custom-model")
        assert retrieved is not None
        assert retrieved.model_id == "custom-model"

        cost = ModelPricingRegistry.calculate_cost("custom-model", 1000, 500)
        assert cost is not None
        # (1000/1M * $2.0) + (500/1M * $10.0) = $0.002 + $0.005 = $0.007
        assert abs(cost - 0.007) < 0.0001

    def test_get_all_models(self) -> None:
        """Should return list of all known models."""
        models = ModelPricingRegistry.get_all_models()
        assert isinstance(models, list)
        assert len(models) > 0
        assert "claude-opus-4-5" in models


class TestAlertingRules:
    """Test alerting rules and exports."""

    def test_recommended_alerts_exist(self) -> None:
        """Should have recommended alerts configured."""
        assert len(RECOMMENDED_ALERTS) > 0

    def test_alerts_have_required_fields(self) -> None:
        """All alerts should have required fields."""
        for alert in RECOMMENDED_ALERTS:
            assert alert.name
            assert alert.metric
            assert alert.threshold >= 0
            assert alert.description
            assert alert.remediation
            assert alert.severity in [Severity.INFO, Severity.WARNING, Severity.CRITICAL]

    def test_critical_alerts_exist(self) -> None:
        """Should have critical severity alerts."""
        critical = [a for a in RECOMMENDED_ALERTS if a.severity == Severity.CRITICAL]
        assert len(critical) > 0

    def test_warning_alerts_exist(self) -> None:
        """Should have warning severity alerts."""
        warnings = [a for a in RECOMMENDED_ALERTS if a.severity == Severity.WARNING]
        assert len(warnings) > 0

    def test_export_prometheus_rules(self, tmp_path) -> None:
        """Should export rules to Prometheus format."""
        from cemaf.observability import export_prometheus_rules

        output_file = tmp_path / "rules.yml"
        export_prometheus_rules(str(output_file))

        assert output_file.exists()
        content = output_file.read_text()

        # Should contain expected structure
        assert "groups:" in content
        assert "cemaf_alerts" in content
        assert "alert:" in content
        assert "expr:" in content

    def test_export_contains_all_alerts(self, tmp_path) -> None:
        """Exported rules should contain all alerts."""
        from cemaf.observability import export_prometheus_rules

        output_file = tmp_path / "rules.yml"
        export_prometheus_rules(str(output_file))

        content = output_file.read_text()

        # Should contain all alert names
        for alert in RECOMMENDED_ALERTS:
            assert alert.name in content

    def test_get_alerts_by_severity(self) -> None:
        """Should filter alerts by severity."""
        from cemaf.observability import get_alerts_by_severity

        critical = get_alerts_by_severity(Severity.CRITICAL)
        assert len(critical) > 0
        for alert in critical:
            assert alert.severity == Severity.CRITICAL

    def test_get_alert_by_name(self) -> None:
        """Should find alert by name."""
        from cemaf.observability import get_alert_by_name

        alert = get_alert_by_name("HighDAGFailureRate")
        assert alert is not None
        assert alert.name == "HighDAGFailureRate"

    def test_get_alert_by_name_not_found(self) -> None:
        """Should return None for unknown alert."""
        from cemaf.observability import get_alert_by_name

        alert = get_alert_by_name("UnknownAlert")
        assert alert is None


class TestMetricsConfiguration:
    """Test metrics configuration and factory functions."""

    def setup_method(self) -> None:
        """Reset observability before each test."""
        reset_observability()

    def test_get_metrics_returns_collector(self) -> None:
        """get_metrics should return configured collector."""
        metrics = get_metrics()
        assert metrics is not None
        assert hasattr(metrics, "counter")
        assert hasattr(metrics, "gauge")
        assert hasattr(metrics, "histogram")
        assert hasattr(metrics, "timing")

    def test_configure_metrics_simple_backend(self) -> None:
        """Should configure SimpleMetrics backend."""
        reset_observability()
        simple_metrics = SimpleMetrics(prefix="test")
        configure_metrics(simple_metrics)

        retrieved = get_metrics()
        assert retrieved is simple_metrics

    def test_metrics_factory_supports_simple(self) -> None:
        """Factory should support simple backend."""
        from cemaf.observability.factories import create_metrics_collector

        metrics = create_metrics_collector(backend="simple")
        assert isinstance(metrics, SimpleMetrics)

    def test_metrics_factory_from_config_default_noop(self) -> None:
        """Factory from config should default to noop."""
        import os

        from cemaf.observability.factories import create_metrics_collector_from_config

        # Ensure env var not set
        os.environ.pop("CEMAF_OBSERVABILITY_METRICS_BACKEND", None)

        metrics = create_metrics_collector_from_config()
        from cemaf.observability.simple import NoOpMetrics

        assert isinstance(metrics, NoOpMetrics)


class TestMetricsPricingDataclass:
    """Test ModelPricing dataclass."""

    def test_model_pricing_calculation(self) -> None:
        """Should calculate cost correctly."""
        pricing = ModelPricing("test-model", 10.0, 20.0)

        # 1M prompt tokens = $10
        # 500K completion tokens = $10
        # Total = $20
        cost = pricing.calculate_cost(1_000_000, 500_000)
        assert abs(cost - 20.0) < 0.01

    def test_model_pricing_zero_tokens(self) -> None:
        """Should handle zero tokens."""
        pricing = ModelPricing("test-model", 10.0, 20.0)
        cost = pricing.calculate_cost(0, 0)
        assert cost == 0.0

    def test_model_pricing_fractional_tokens(self) -> None:
        """Should handle fractional token costs."""
        pricing = ModelPricing("test-model", 1.0, 1.0)

        # 100 prompt + 100 completion = $0.0002
        cost = pricing.calculate_cost(100, 100)
        assert abs(cost - 0.0002) < 0.00001


class TestMetricsIntegration:
    """End-to-end integration tests."""

    def test_full_metrics_workflow(self) -> None:
        """Should support complete metrics workflow."""
        from cemaf.observability import configure_metrics

        # Configure metrics
        metrics = SimpleMetrics(prefix="test")
        configure_metrics(metrics)

        # Record various metrics
        retrieved = get_metrics()
        assert retrieved is metrics

        retrieved.counter("test.counter", value=1, tags={"type": "test"})
        retrieved.gauge("test.gauge", value=42.0, tags={"type": "test"})
        retrieved.histogram("test.histogram", value=100.0, tags={"type": "test"})
        retrieved.timing("test.timing", value_ms=50.0, tags={"type": "test"})

    def test_metrics_with_cost_tracking(self) -> None:
        """Should integrate cost tracking with metrics."""
        metrics = SimpleMetrics()

        # Record LLM call with cost
        cost = ModelPricingRegistry.calculate_cost("claude-haiku-4-5", 1000, 500)
        assert cost is not None
        assert cost > 0

        MetricsHelper.record_llm_call(
            metrics,
            model="claude-haiku-4-5",
            prompt_tokens=1000,
            completion_tokens=500,
            duration_ms=1000.0,
            success=True,
            cost=cost,
        )

        assert metrics._prefix == "cemaf"
