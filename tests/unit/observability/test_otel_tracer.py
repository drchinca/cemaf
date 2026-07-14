"""Tests for OTelSpan and OTelTracer using unittest.mock when OTel SDK is absent."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cemaf.observability.otel_tracer import OTelSpan, OTelTracer, _flatten_value


class TestFlattenValue:
    def test_scalar_passthrough(self):
        assert _flatten_value("hello") == "hello"
        assert _flatten_value(42) == 42
        assert _flatten_value(3.14) == 3.14
        assert _flatten_value(True) is True

    def test_dict_serialised_to_json_string(self):
        result = _flatten_value({"key": "value"})
        assert isinstance(result, str)
        assert "key" in result

    def test_list_serialised_to_json_string(self):
        result = _flatten_value([1, 2, 3])
        assert isinstance(result, str)
        assert "1" in result


class TestOTelSpan:
    def _span(self) -> tuple[OTelSpan, MagicMock]:
        mock_span = MagicMock()
        return OTelSpan(mock_span), mock_span

    def test_set_attribute_flattens_dict(self):
        span, mock = self._span()
        span.set_attribute("cemaf.metadata", {"a": 1})
        mock.set_attribute.assert_called_once()
        key, value = mock.set_attribute.call_args[0]
        assert key == "cemaf.metadata"
        assert isinstance(value, str)

    def test_set_attribute_passes_scalar(self):
        span, mock = self._span()
        span.set_attribute("cemaf.count", 7)
        mock.set_attribute.assert_called_once_with("cemaf.count", 7)

    def test_add_event_passes_name_and_attributes(self):
        span, mock = self._span()
        span.add_event("node.start", {"node": "n1"})
        mock.add_event.assert_called_once()
        args, kwargs = mock.add_event.call_args
        assert args[0] == "node.start"

    def test_end_delegates(self):
        span, mock = self._span()
        span.end()
        mock.end.assert_called_once()

    def test_set_status_ok(self):
        """set_status('OK') maps to StatusCode.OK."""
        from opentelemetry.trace import StatusCode

        mock_span = MagicMock()
        span = OTelSpan(mock_span)
        span.set_status("OK")
        mock_span.set_status.assert_called_once()
        call_args = mock_span.set_status.call_args[0]
        assert call_args[0] == StatusCode.OK

    def test_set_status_error(self):
        """set_status('ERROR') maps to StatusCode.ERROR."""
        from opentelemetry.trace import StatusCode

        mock_span = MagicMock()
        span = OTelSpan(mock_span)
        span.set_status("ERROR", "something went wrong")
        call_args = mock_span.set_status.call_args[0]
        assert call_args[0] == StatusCode.ERROR


class TestOTelTracer:
    def test_start_span_delegates_to_inner(self):
        mock_tracer = MagicMock()
        mock_inner_span = MagicMock()
        mock_scope = MagicMock()
        mock_scope.__enter__.return_value = mock_inner_span
        mock_tracer.start_as_current_span.return_value = mock_scope

        tracer = OTelTracer(mock_tracer)
        span = tracer.start_span("test.span", {"key": "value"})

        mock_tracer.start_as_current_span.assert_called_once()
        assert isinstance(span, OTelSpan)

    def test_start_span_creates_exportable_span(self):
        """Integration: OTelTracer wraps an OTel SDK Tracer and span is recording."""
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        except ImportError:
            pytest.skip("opentelemetry-sdk not installed")

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        raw_tracer = provider.get_tracer("test")

        tracer = OTelTracer(raw_tracer)
        span = tracer.start_span("cemaf.test.op", {"cemaf.run.id": "r1"})
        span.set_status("OK")
        span.end()

        finished = exporter.get_finished_spans()
        assert len(finished) == 1
        assert finished[0].name == "cemaf.test.op"
