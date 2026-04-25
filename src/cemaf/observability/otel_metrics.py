"""OpenTelemetry MetricsCollector implementation."""

from typing import Any

from cemaf.core.types import JSON


def _require_otel_metrics() -> None:
    try:
        import opentelemetry.metrics  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "opentelemetry-sdk is required for OTelMetricsCollector. "
            "Install with: uv add opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
        ) from exc


class OTelMetricsCollector:
    """
    MetricsCollector backed by an OpenTelemetry Meter.

    Instruments are created lazily on first use and cached — the OTel SDK
    prohibits creating two instruments with the same name on the same meter.
    """

    def __init__(self, meter: Any) -> None:
        _require_otel_metrics()
        self._meter = meter
        self._counters: dict[str, Any] = {}
        self._up_down_counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

    def _get_or_create_counter(self, name: str) -> Any:
        if name not in self._counters:
            self._counters[name] = self._meter.create_counter(name)
        return self._counters[name]

    def _get_or_create_up_down_counter(self, name: str) -> Any:
        if name not in self._up_down_counters:
            self._up_down_counters[name] = self._meter.create_up_down_counter(name)
        return self._up_down_counters[name]

    def _get_or_create_histogram(self, name: str) -> Any:
        if name not in self._histograms:
            self._histograms[name] = self._meter.create_histogram(name)
        return self._histograms[name]

    def counter(self, name: str, value: int = 1, tags: JSON | None = None) -> None:
        self._get_or_create_counter(name).add(value, attributes=tags or {})

    def gauge(self, name: str, value: float, tags: JSON | None = None) -> None:
        # OTel has no mutable gauge; UpDownCounter is the conventional replacement.
        self._get_or_create_up_down_counter(name).add(value, attributes=tags or {})

    def histogram(self, name: str, value: float, tags: JSON | None = None) -> None:
        self._get_or_create_histogram(name).record(value, attributes=tags or {})

    def timing(self, name: str, value_ms: float, tags: JSON | None = None) -> None:
        self.histogram(name, value_ms, tags)
