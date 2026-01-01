"""
Observability protocols - Pluggable logging, tracing, metrics.

Implement these protocols for different backends:
- SimpleLogger (stdout)
- StructuredLogger (JSON)
- OpenTelemetryTracer
- PrometheusMetrics
"""

from typing import Any, Protocol, runtime_checkable

from cemaf.core.types import JSON


@runtime_checkable
class Logger(Protocol):
    """Protocol for structured logging."""

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        ...

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        ...

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        ...

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        ...

    def with_context(self, **kwargs: Any) -> Logger:
        """Return logger with additional context."""
        ...


@runtime_checkable
class Span(Protocol):
    """Protocol for a trace span."""

    def set_attribute(self, key: str, value: Any) -> None:
        """Set span attribute."""
        ...

    def add_event(self, name: str, attributes: JSON | None = None) -> None:
        """Add event to span."""
        ...

    def set_status(self, status: str, description: str | None = None) -> None:
        """Set span status."""
        ...

    def end(self) -> None:
        """End the span."""
        ...


@runtime_checkable
class Tracer(Protocol):
    """Protocol for distributed tracing."""

    def start_span(self, name: str, attributes: JSON | None = None) -> Span:
        """Start a new span."""
        ...

    def get_current_span(self) -> Span | None:
        """Get current active span."""
        ...


@runtime_checkable
class MetricsCollector(Protocol):
    """Protocol for metrics collection."""

    def counter(self, name: str, value: int = 1, tags: JSON | None = None) -> None:
        """Increment a counter."""
        ...

    def gauge(self, name: str, value: float, tags: JSON | None = None) -> None:
        """Set a gauge value."""
        ...

    def histogram(self, name: str, value: float, tags: JSON | None = None) -> None:
        """Record a histogram value."""
        ...

    def timing(self, name: str, value_ms: float, tags: JSON | None = None) -> None:
        """Record a timing value."""
        ...
