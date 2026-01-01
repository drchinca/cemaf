"""
Factory functions for observability components.

Provides convenient ways to create loggers, tracers, metrics collectors,
and run loggers with sensible defaults while maintaining dependency injection principles.

Extension Point:
    This module is designed for extension. The create_X_from_config()
    functions include clear "EXTEND HERE" sections where you can add
    your own implementations (OpenTelemetry, Datadog, etc.).
"""

import os

from cemaf.config.protocols import Settings
from cemaf.observability.protocols import Logger, MetricsCollector, Tracer
from cemaf.observability.run_logger import (
    InMemoryRunLogger,
    NoOpRunLogger,
    RunLogger,
)
from cemaf.observability.simple import NoOpMetrics, NoOpTracer, SimpleLogger


def create_logger(
    backend: str = "simple",
    level: str = "INFO",
) -> Logger:
    """
    Factory for Logger with sensible defaults.

    Args:
        backend: Logger backend (simple, noop, structured, etc.)
        level: Log level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured Logger instance

    Example:
        # Simple logger
        logger = create_logger()

        # Debug level
        logger = create_logger(level="DEBUG")
    """
    if backend == "simple":
        return SimpleLogger(level=level)
    else:
        raise ValueError(f"Unsupported logger backend: {backend}")


def create_logger_from_config(settings: Settings | None = None) -> Logger:
    """
    Create Logger from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_LOGGER_BACKEND: Backend (default: "simple")
    - CEMAF_OBSERVABILITY_LOG_LEVEL: Log level (default: "INFO")

    Returns:
        Configured Logger instance
    """
    backend = os.getenv("CEMAF_OBSERVABILITY_LOGGER_BACKEND", "simple")
    level = os.getenv("CEMAF_OBSERVABILITY_LOG_LEVEL", "INFO")

    if backend == "simple":
        return create_logger(backend, level)

    # ============================================================================
    # EXTEND HERE: Bring Your Own Logger
    # ============================================================================
    # Example (Structured logging):
    #   elif backend == "structured":
    #       from your_package import StructuredLogger
    #       return StructuredLogger(level=level)
    # ============================================================================

    raise ValueError(f"Unsupported logger backend: {backend}")


def create_tracer(backend: str = "noop") -> Tracer:
    """
    Factory for Tracer with sensible defaults.

    Args:
        backend: Tracer backend (noop, opentelemetry, etc.)

    Returns:
        Configured Tracer instance
    """
    if backend == "noop":
        return NoOpTracer()
    else:
        raise ValueError(f"Unsupported tracer backend: {backend}")


def create_tracer_from_config(settings: Settings | None = None) -> Tracer:
    """
    Create Tracer from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_TRACER_BACKEND: Backend (default: "noop")

    Returns:
        Configured Tracer instance
    """
    backend = os.getenv("CEMAF_OBSERVABILITY_TRACER_BACKEND", "noop")

    if backend == "noop":
        return create_tracer(backend)

    # ============================================================================
    # EXTEND HERE: Bring Your Own Tracer
    # ============================================================================
    # Example (OpenTelemetry):
    #   elif backend == "opentelemetry":
    #       from opentelemetry import trace
    #       from your_package import OpenTelemetryTracer
    #       tracer = trace.get_tracer(__name__)
    #       return OpenTelemetryTracer(tracer=tracer)
    # ============================================================================

    raise ValueError(f"Unsupported tracer backend: {backend}")


def create_metrics_collector(backend: str = "noop") -> MetricsCollector:
    """
    Factory for MetricsCollector with sensible defaults.

    Args:
        backend: Metrics backend (noop, prometheus, etc.)

    Returns:
        Configured MetricsCollector instance
    """
    if backend == "noop":
        return NoOpMetrics()
    else:
        raise ValueError(f"Unsupported metrics backend: {backend}")


def create_metrics_collector_from_config(settings: Settings | None = None) -> MetricsCollector:
    """
    Create MetricsCollector from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_METRICS_BACKEND: Backend (default: "noop")

    Returns:
        Configured MetricsCollector instance
    """
    backend = os.getenv("CEMAF_OBSERVABILITY_METRICS_BACKEND", "noop")

    if backend == "noop":
        return create_metrics_collector(backend)

    # ============================================================================
    # EXTEND HERE: Bring Your Own Metrics Collector
    # ============================================================================
    # Example (Prometheus):
    #   elif backend == "prometheus":
    #       from your_package import PrometheusMetrics
    #       port = int(os.getenv("PROMETHEUS_PORT", "9090"))
    #       return PrometheusMetrics(port=port)
    # ============================================================================

    raise ValueError(f"Unsupported metrics backend: {backend}")


def create_run_logger(
    backend: str = "memory",
    enable_recording: bool = True,
) -> RunLogger:
    """
    Factory for RunLogger with sensible defaults.

    Args:
        backend: Run logger backend (memory, noop, database, etc.)
        enable_recording: Enable recording of runs

    Returns:
        Configured RunLogger instance

    Example:
        # In-memory run logger
        logger = create_run_logger()

        # No-op (disabled)
        logger = create_run_logger(backend="noop")
    """
    if backend == "memory":
        return InMemoryRunLogger() if enable_recording else NoOpRunLogger()
    elif backend == "noop":
        return NoOpRunLogger()
    else:
        raise ValueError(f"Unsupported run logger backend: {backend}")


def create_run_logger_from_config(settings: Settings | None = None) -> RunLogger:
    """
    Create RunLogger from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_RUN_LOGGER_BACKEND: Backend (default: "memory")
    - CEMAF_OBSERVABILITY_ENABLE_RUN_RECORDING: Enable recording (default: True)

    Returns:
        Configured RunLogger instance
    """
    backend = os.getenv("CEMAF_OBSERVABILITY_RUN_LOGGER_BACKEND", "memory")
    enable_recording = os.getenv("CEMAF_OBSERVABILITY_ENABLE_RUN_RECORDING", "true").lower() == "true"

    if backend in ("memory", "noop"):
        return create_run_logger(backend, enable_recording)

    # ============================================================================
    # EXTEND HERE: Bring Your Own Run Logger
    # ============================================================================
    # Example (Database):
    #   elif backend == "database":
    #       from your_package import DatabaseRunLogger
    #       db_url = os.getenv("DATABASE_URL")
    #       return DatabaseRunLogger(connection_string=db_url)
    # ============================================================================

    raise ValueError(f"Unsupported run logger backend: {backend}")
