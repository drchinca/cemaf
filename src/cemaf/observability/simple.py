"""
Simple implementations of observability interfaces.

For development/testing - swap with real implementations in production.
"""

import logging
import sys
from typing import Any

from cemaf.core.types import JSON
from cemaf.observability.protocols import Span


class SimpleLogger:
    """
    Simple stdout logger with lazy evaluation.

    Uses Python's % formatting for lazy evaluation - arguments only
    formatted if log level is enabled.

    Example:
        logger = SimpleLogger()
        logger.debug("Processing %s items", len(items))  # Lazy evaluation
        logger.info("Started run", run_id=run_id)  # Structured context
    """

    def __init__(
        self,
        name: str = "cemaf",
        level: int = logging.INFO,
        context: JSON | None = None,
    ) -> None:
        self._name = name
        self._level = level
        self._context = context or {}

        # Configure Python logger
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)

        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            # Use standard format with time, level, name, message
            formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    def _add_context(self, message: str, kwargs: dict[str, Any]) -> str:
        """Add structured context to message (lazy evaluation)."""
        if not kwargs and not self._context:
            return message

        all_context = {**self._context, **kwargs}
        context_str = " | ".join("%s=%s" % (k, v) for k, v in all_context.items())
        return "%s | %s" % (message, context_str)

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        Log debug message with lazy evaluation.

        Args:
            message: Message template (use %s, %d, etc. for placeholders)
            *args: Values for message template
            **kwargs: Structured context fields

        Example:
            logger.debug("Found %d items in cache", count, cache_key=key)
        """
        if self._logger.isEnabledFor(logging.DEBUG):
            msg = self._add_context(message, kwargs)
            self._logger.debug(msg, *args)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        Log info message with lazy evaluation.

        Args:
            message: Message template
            *args: Values for message template
            **kwargs: Structured context fields

        Example:
            logger.info("Started execution", run_id=run_id, node_count=len(nodes))
        """
        if self._logger.isEnabledFor(logging.INFO):
            msg = self._add_context(message, kwargs)
            self._logger.info(msg, *args)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        Log warning message with lazy evaluation.

        Args:
            message: Message template
            *args: Values for message template
            **kwargs: Structured context fields

        Example:
            logger.warning("Retry attempt %d failed", attempt, error=str(e))
        """
        if self._logger.isEnabledFor(logging.WARNING):
            msg = self._add_context(message, kwargs)
            self._logger.warning(msg, *args)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        Log error message with lazy evaluation.

        Args:
            message: Message template
            *args: Values for message template
            **kwargs: Structured context fields

        Example:
            logger.error("Operation failed: %s", str(e), exc_info=True)
        """
        if self._logger.isEnabledFor(logging.ERROR):
            msg = self._add_context(message, kwargs)
            # Extract exc_info if provided in kwargs
            exc_info = kwargs.pop("exc_info", False)
            self._logger.error(msg, *args, exc_info=exc_info)

    def with_context(self, **kwargs: Any) -> SimpleLogger:
        """Return logger with additional context."""
        new_context = {**self._context, **kwargs}
        return SimpleLogger(self._name, self._level, new_context)


class NoOpSpan:
    """No-operation span for testing/development."""

    def set_attribute(self, key: str, value: Any) -> None:
        """No-op."""
        pass

    def add_event(self, name: str, attributes: JSON | None = None) -> None:
        """No-op."""
        pass

    def set_status(self, status: str, description: str | None = None) -> None:
        """No-op."""
        pass

    def end(self) -> None:
        """No-op."""
        pass


class NoOpTracer:
    """No-operation tracer for testing/development."""

    def start_span(self, name: str, attributes: JSON | None = None) -> Span:
        """Return no-op span."""
        return NoOpSpan()

    def get_current_span(self) -> Span | None:
        """Return None."""
        return None


class SimpleMetrics:
    """
    Simple metrics collector that logs to stdout for development/testing.

    Records all metrics as log lines for easy inspection during development.
    Useful for verifying metrics collection without external dependencies.

    Example:
        metrics = SimpleMetrics(prefix="cemaf")
        metrics.counter("dag.executions.total", tags={"dag_name": "test"})
        metrics.timing("dag.duration_ms", 123.45, tags={"dag_name": "test"})
    """

    def __init__(self, prefix: str = "cemaf") -> None:
        """
        Initialize SimpleMetrics.

        Args:
            prefix: Metric name prefix (default: "cemaf")
        """
        self._prefix = prefix
        self._logger = logging.getLogger("cemaf.metrics")

    def _format_tags(self, tags: JSON | None) -> str:
        """Format tags as space-separated key=value pairs."""
        if not tags:
            return ""
        return " ".join(f"{k}={v}" for k, v in tags.items())

    def counter(self, name: str, value: int = 1, tags: JSON | None = None) -> None:
        """
        Record counter metric.

        Args:
            name: Metric name (without prefix)
            value: Counter increment (default: 1)
            tags: Metric tags/labels
        """
        tags_str = self._format_tags(tags)
        full_name = f"{self._prefix}.{name}"
        self._logger.info(f"COUNTER {full_name}={value} {tags_str}".rstrip())

    def gauge(self, name: str, value: float, tags: JSON | None = None) -> None:
        """
        Record gauge metric (instantaneous value).

        Args:
            name: Metric name (without prefix)
            value: Gauge value
            tags: Metric tags/labels
        """
        tags_str = self._format_tags(tags)
        full_name = f"{self._prefix}.{name}"
        self._logger.info(f"GAUGE {full_name}={value} {tags_str}".rstrip())

    def histogram(self, name: str, value: float, tags: JSON | None = None) -> None:
        """
        Record histogram metric (distribution).

        Args:
            name: Metric name (without prefix)
            value: Histogram value
            tags: Metric tags/labels
        """
        tags_str = self._format_tags(tags)
        full_name = f"{self._prefix}.{name}"
        self._logger.info(f"HISTOGRAM {full_name}={value} {tags_str}".rstrip())

    def timing(self, name: str, value_ms: float, tags: JSON | None = None) -> None:
        """
        Record timing metric (duration in milliseconds).

        Args:
            name: Metric name (without prefix)
            value_ms: Duration in milliseconds
            tags: Metric tags/labels
        """
        tags_str = self._format_tags(tags)
        full_name = f"{self._prefix}.{name}"
        self._logger.info(f"TIMING {full_name}={value_ms}ms {tags_str}".rstrip())


class NoOpMetrics:
    """No-operation metrics for testing/development."""

    def counter(self, name: str, value: int = 1, tags: JSON | None = None) -> None:
        """No-op."""
        pass

    def gauge(self, name: str, value: float, tags: JSON | None = None) -> None:
        """No-op."""
        pass

    def histogram(self, name: str, value: float, tags: JSON | None = None) -> None:
        """No-op."""
        pass

    def timing(self, name: str, value_ms: float, tags: JSON | None = None) -> None:
        """No-op."""
        pass
