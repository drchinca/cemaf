"""
Global logging and observability configuration.

Provides centralized configuration for logging, tracing, and metrics.
Applications using CEMAF can configure observability once at startup.
"""

import logging
import os
from typing import Any

from cemaf.observability.protocols import Logger, MetricsCollector, Tracer
from cemaf.observability.simple import NoOpMetrics, NoOpTracer, SimpleLogger

# Global singleton instances
_logger: Logger | None = None
_tracer: Tracer | None = None
_metrics: MetricsCollector | None = None


def configure_logging(
    logger: Logger | None = None,
    level: str | None = None,
    name: str = "cemaf",
) -> None:
    """
    Configure global logging for CEMAF.

    Args:
        logger: Custom logger implementation (default: SimpleLogger)
        level: Log level (DEBUG, INFO, WARNING, ERROR). Env: CEMAF_LOG_LEVEL
        name: Logger name

    Example:
        # Use default logging
        configure_logging()

        # Use custom level
        configure_logging(level="DEBUG")

        # Use custom logger
        configure_logging(logger=MyStructuredLogger())
    """
    global _logger

    if logger is not None:
        _logger = logger
        return

    # Determine log level from env or parameter
    log_level_str = (level or os.getenv("CEMAF_LOG_LEVEL") or "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    _logger = SimpleLogger(name=name, level=log_level)


def configure_tracing(tracer: Tracer | None = None) -> None:
    """
    Configure global tracing for CEMAF.

    Args:
        tracer: Custom tracer implementation (default: NoOpTracer)

    Example:
        # Disable tracing (default)
        configure_tracing()

        # Use OpenTelemetry
        configure_tracing(tracer=OpenTelemetryTracer())
    """
    global _tracer
    _tracer = tracer or NoOpTracer()


def configure_metrics(metrics: MetricsCollector | None = None) -> None:
    """
    Configure global metrics collection for CEMAF.

    Args:
        metrics: Custom metrics collector (default: NoOpMetrics)

    Example:
        # Disable metrics (default)
        configure_metrics()

        # Use Prometheus
        configure_metrics(metrics=PrometheusMetrics())
    """
    global _metrics
    _metrics = metrics or NoOpMetrics()


def get_logger(name: str | None = None, **context: Any) -> Logger:
    """
    Get logger instance with optional context.

    Args:
        name: Logger name (appended to root name)
        **context: Additional context fields

    Returns:
        Logger instance with context

    Example:
        logger = get_logger("dag.executor", run_id="123")
        logger.info("Starting execution")  # Includes run_id in output
    """
    global _logger

    if _logger is None:
        configure_logging()

    assert _logger is not None  # For type checker

    if name:
        # Create child logger with hierarchical name
        _logger = _logger.with_context(component=name)

    if context:
        _logger = _logger.with_context(**context)

    return _logger


def get_tracer() -> Tracer:
    """
    Get tracer instance.

    Returns:
        Tracer instance

    Example:
        tracer = get_tracer()
        span = tracer.start_span("operation")
        # ... do work
        span.end()
    """
    global _tracer

    if _tracer is None:
        configure_tracing()

    assert _tracer is not None  # For type checker
    return _tracer


def get_metrics() -> MetricsCollector:
    """
    Get metrics collector instance.

    Returns:
        MetricsCollector instance

    Example:
        metrics = get_metrics()
        metrics.counter("requests.total", tags={"method": "POST"})
    """
    global _metrics

    if _metrics is None:
        configure_metrics()

    assert _metrics is not None  # For type checker
    return _metrics


def reset_observability() -> None:
    """
    Reset all observability configuration (for testing).

    Warning: Only use in test teardown.
    """
    global _logger, _tracer, _metrics
    _logger = None
    _tracer = None
    _metrics = None
