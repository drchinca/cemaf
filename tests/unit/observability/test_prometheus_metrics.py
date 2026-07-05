"""Tests for PrometheusMetrics collector."""

import prometheus_client as pc
import pytest

from cemaf.observability.prometheus_metrics import PrometheusMetrics
from cemaf.observability.protocols import MetricsCollector


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Clear default registry between tests to avoid duplicate metric errors."""
    collectors = list(pc.REGISTRY._names_to_collectors.values())
    for collector in collectors:
        try:
            pc.REGISTRY.unregister(collector)
        except Exception:
            pass


class TestPrometheusMetricsProtocol:
    def test_satisfies_protocol(self) -> None:
        metrics = PrometheusMetrics()
        assert isinstance(metrics, MetricsCollector)


class TestPrometheusMetricsCounter:
    def test_counter_increments(self) -> None:
        metrics = PrometheusMetrics(prefix="test")
        metrics.counter(name="requests", value=1)
        metrics.counter(name="requests", value=3)

        output = metrics.generate_metrics()
        assert "test_requests_total" in output

    def test_counter_with_tags(self) -> None:
        metrics = PrometheusMetrics(prefix="test")
        metrics.counter(name="http_calls", value=1, tags={"method": "GET"})

        output = metrics.generate_metrics()
        assert "test_http_calls_total" in output
        assert 'method="GET"' in output


class TestPrometheusMetricsHistogram:
    def test_histogram_records(self) -> None:
        metrics = PrometheusMetrics(prefix="test")
        metrics.histogram(name="response_size", value=1024.0)

        output = metrics.generate_metrics()
        assert "test_response_size_bucket" in output

    def test_timing_records_in_seconds(self) -> None:
        metrics = PrometheusMetrics(prefix="test")
        metrics.timing(name="latency", value_ms=500.0)

        output = metrics.generate_metrics()
        assert "test_latency_bucket" in output


class TestPrometheusMetricsGauge:
    def test_gauge_sets_value(self) -> None:
        metrics = PrometheusMetrics(prefix="test")
        metrics.gauge(name="active_connections", value=42.0)

        output = metrics.generate_metrics()
        assert "test_active_connections" in output


class TestGenerateMetrics:
    def test_generate_metrics_returns_text(self) -> None:
        metrics = PrometheusMetrics(prefix="test")
        metrics.counter(name="events", value=1)

        output = metrics.generate_metrics()
        assert isinstance(output, str)
        assert len(output) > 0
        assert "test_events_total" in output
