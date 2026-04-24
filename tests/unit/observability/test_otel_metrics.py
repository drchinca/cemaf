"""Tests for OTelMetricsCollector using mocks (no OTel SDK required)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cemaf.observability.otel_metrics import OTelMetricsCollector


def _meter() -> tuple[OTelMetricsCollector, MagicMock]:
    """Return a collector backed by a fully-mocked OTel Meter."""
    mock_meter = MagicMock()
    mock_counter = MagicMock()
    mock_updown = MagicMock()
    mock_histogram = MagicMock()

    mock_meter.create_counter.return_value = mock_counter
    mock_meter.create_up_down_counter.return_value = mock_updown
    mock_meter.create_histogram.return_value = mock_histogram

    # Patch the guard so it does not raise ImportError without OTel installed
    import cemaf.observability.otel_metrics as _mod
    orig = _mod._require_otel_metrics

    def _noop() -> None:
        pass

    _mod._require_otel_metrics = _noop
    collector = OTelMetricsCollector(mock_meter)
    _mod._require_otel_metrics = orig

    return collector, mock_meter


class TestOTelMetricsCollector:
    def test_counter_increments(self):
        collector, mock_meter = _meter()
        collector.counter("test.requests", value=3, tags={"env": "test"})

        mock_meter.create_counter.assert_called_once_with("test.requests")
        counter_inst = mock_meter.create_counter.return_value
        counter_inst.add.assert_called_once_with(3, attributes={"env": "test"})

    def test_counter_cached_on_second_call(self):
        """Calling counter() twice with the same name reuses the instrument."""
        collector, mock_meter = _meter()
        collector.counter("same.name")
        collector.counter("same.name")
        assert mock_meter.create_counter.call_count == 1

    def test_histogram_records(self):
        collector, mock_meter = _meter()
        collector.histogram("test.latency", 42.5, tags={"op": "read"})

        mock_meter.create_histogram.assert_called_once_with("test.latency")
        hist_inst = mock_meter.create_histogram.return_value
        hist_inst.record.assert_called_once_with(42.5, attributes={"op": "read"})

    def test_timing_calls_histogram(self):
        collector, mock_meter = _meter()
        collector.timing("test.duration_ms", 100.0)

        mock_meter.create_histogram.assert_called_once_with("test.duration_ms")

    def test_gauge_uses_up_down_counter(self):
        collector, mock_meter = _meter()
        collector.gauge("test.queue_depth", 7.0, tags={"q": "main"})

        mock_meter.create_up_down_counter.assert_called_once_with("test.queue_depth")
        udc = mock_meter.create_up_down_counter.return_value
        udc.add.assert_called_once_with(7.0, attributes={"q": "main"})
