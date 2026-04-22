"""Prometheus metrics collector for production observability."""

from __future__ import annotations

from typing import Any

from cemaf.core.types import JSON


class PrometheusMetrics:
    """MetricsCollector backed by prometheus_client."""

    def __init__(self, *, prefix: str = "cemaf") -> None:
        self._prefix = prefix
        self._counters: dict[tuple[str, tuple[str, ...]], Any] = {}
        self._gauges: dict[tuple[str, tuple[str, ...]], Any] = {}
        self._histograms: dict[tuple[str, tuple[str, ...]], Any] = {}
        self._pc = self._import_prometheus()

    @staticmethod
    def _import_prometheus() -> Any:
        """Lazy-import prometheus_client, raising clear error if missing."""
        try:
            import prometheus_client

            return prometheus_client
        except ImportError as exc:
            msg = "prometheus-client is required: install cemaf[prometheus]"
            raise ImportError(msg) from exc

    def _metric_name(self, name: str) -> str:
        """Build full metric name with prefix."""
        return f"{self._prefix}_{name}".replace(".", "_")

    @staticmethod
    def _label_names(tags: JSON | None) -> tuple[str, ...]:
        """Extract sorted label names from tags."""
        if not tags:
            return ()
        return tuple(sorted(tags.keys()))

    @staticmethod
    def _label_values(tags: JSON | None) -> tuple[str, ...]:
        """Extract label values sorted by key."""
        if not tags:
            return ()
        return tuple(str(tags[k]) for k in sorted(tags.keys()))

    def _get_or_create_counter(self, name: str, tags: JSON | None) -> Any:
        """Get existing or register new Counter."""
        full_name = self._metric_name(name=name)
        label_names = self._label_names(tags=tags)
        cache_key = (full_name, label_names)

        if cache_key not in self._counters:
            self._counters[cache_key] = self._pc.Counter(
                full_name,
                f"Counter for {name}",
                labelnames=label_names,
            )
        return self._counters[cache_key]

    def _get_or_create_gauge(self, name: str, tags: JSON | None) -> Any:
        """Get existing or register new Gauge."""
        full_name = self._metric_name(name=name)
        label_names = self._label_names(tags=tags)
        cache_key = (full_name, label_names)

        if cache_key not in self._gauges:
            self._gauges[cache_key] = self._pc.Gauge(
                full_name,
                f"Gauge for {name}",
                labelnames=label_names,
            )
        return self._gauges[cache_key]

    def _get_or_create_histogram(self, name: str, tags: JSON | None) -> Any:
        """Get existing or register new Histogram."""
        full_name = self._metric_name(name=name)
        label_names = self._label_names(tags=tags)
        cache_key = (full_name, label_names)

        if cache_key not in self._histograms:
            self._histograms[cache_key] = self._pc.Histogram(
                full_name,
                f"Histogram for {name}",
                labelnames=label_names,
            )
        return self._histograms[cache_key]

    def counter(self, name: str, value: int = 1, tags: JSON | None = None) -> None:
        """Increment a Prometheus counter."""
        metric = self._get_or_create_counter(name=name, tags=tags)
        label_values = self._label_values(tags=tags)
        if label_values:
            metric.labels(*label_values).inc(amount=value)
        else:
            metric.inc(amount=value)

    def gauge(self, name: str, value: float, tags: JSON | None = None) -> None:
        """Set a Prometheus gauge value."""
        metric = self._get_or_create_gauge(name=name, tags=tags)
        label_values = self._label_values(tags=tags)
        if label_values:
            metric.labels(*label_values).set(value=value)
        else:
            metric.set(value=value)

    def histogram(self, name: str, value: float, tags: JSON | None = None) -> None:
        """Record a Prometheus histogram observation."""
        metric = self._get_or_create_histogram(name=name, tags=tags)
        label_values = self._label_values(tags=tags)
        if label_values:
            metric.labels(*label_values).observe(amount=value)
        else:
            metric.observe(amount=value)

    def timing(self, name: str, value_ms: float, tags: JSON | None = None) -> None:
        """Record timing as histogram observation in seconds."""
        value_seconds = value_ms / 1000.0
        self.histogram(name=name, value=value_seconds, tags=tags)

    def generate_metrics(self) -> str:
        """Return Prometheus text exposition format."""
        result: str = self._pc.generate_latest().decode("utf-8")
        return result
