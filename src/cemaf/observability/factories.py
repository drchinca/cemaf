"""Registry-backed factory functions for observability components.

Provides convenient ways to create loggers, tracers, metrics collectors,
and run loggers with sensible defaults while maintaining dependency injection principles.

Extension Point:
    Register custom observability backends with the relevant registry.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import cemaf.observability.run_logger as run_logger_module
from cemaf.config.factories import load_settings_from_env_sync
from cemaf.config.protocols import Settings
from cemaf.core.provider_registry import ProviderRegistry
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.observability.protocols import Logger, MetricsCollector, Tracer
from cemaf.observability.run_logger import (
    InMemoryRunLogger,
    NoOpRunLogger,
    RunLogger,
)
from cemaf.observability.simple import NoOpMetrics, NoOpTracer, SimpleLogger, SimpleMetrics
from cemaf.observability.structured import StructuredLogger

logger_registry: ProviderRegistry[Logger] = ProviderRegistry(name="logger")
tracer_registry: ProviderRegistry[Tracer] = ProviderRegistry(name="tracer")
metrics_collector_registry: ProviderRegistry[MetricsCollector] = ProviderRegistry(name="metrics_collector")
run_logger_registry: ProviderRegistry[RunLogger] = ProviderRegistry(name="run_logger")


def _log_level_int(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, level.upper(), logging.INFO)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() == "true"


def _create_simple_logger(**kwargs: Any) -> Logger:
    return SimpleLogger(
        name=str(kwargs.get("name", "cemaf")),
        level=_log_level_int(kwargs.get("level", "INFO")),
    )


def _create_structured_logger(**kwargs: Any) -> Logger:
    return StructuredLogger(
        name=str(kwargs.get("name", "cemaf")),
        level=_log_level_int(kwargs.get("level", "INFO")),
    )


def _create_noop_tracer(**kwargs: Any) -> Tracer:
    return NoOpTracer()


def _create_otel_tracer(**kwargs: Any) -> Tracer:
    from cemaf.observability.otel_tracer import OTelTracer

    tracer = kwargs.get("tracer")
    if tracer is None:
        try:
            from opentelemetry import trace
        except ImportError as exc:
            raise ImportError(
                "OpenTelemetry tracing requires the 'otel' extra. "
                "Install with: pip install 'cemaf[otel]' (or 'cemaf[all]')."
            ) from exc
        tracer = trace.get_tracer(str(kwargs.get("name", "cemaf")))
    return OTelTracer(tracer)


def _create_noop_metrics(**kwargs: Any) -> MetricsCollector:
    return NoOpMetrics()


def _create_simple_metrics(**kwargs: Any) -> MetricsCollector:
    return SimpleMetrics(prefix=str(kwargs.get("prefix", "cemaf")))


def _create_prometheus_metrics(**kwargs: Any) -> MetricsCollector:
    from cemaf.observability.prometheus_metrics import PrometheusMetrics

    return PrometheusMetrics(prefix=str(kwargs.get("prefix", "cemaf")))


def _create_otel_metrics(**kwargs: Any) -> MetricsCollector:
    from cemaf.observability.otel_metrics import OTelMetricsCollector

    meter = kwargs.get("meter")
    if meter is None:
        try:
            from opentelemetry import metrics
        except ImportError as exc:
            raise ImportError(
                "OpenTelemetry metrics require the 'otel' extra. "
                "Install with: pip install 'cemaf[otel]' (or 'cemaf[all]')."
            ) from exc
        meter = metrics.get_meter(str(kwargs.get("name", kwargs.get("prefix", "cemaf"))))
    return OTelMetricsCollector(meter)


def _create_memory_run_logger(**kwargs: Any) -> RunLogger:
    return InMemoryRunLogger() if bool(kwargs.get("enable_recording", True)) else NoOpRunLogger()


def _create_file_run_logger(**kwargs: Any) -> RunLogger:
    if not bool(kwargs.get("enable_recording", True)):
        return NoOpRunLogger()
    root = kwargs.get("root")
    if root is None:
        raise ValueError("root is required for file run logger backend")
    file_run_logger = getattr(run_logger_module, "FileRunLogger")  # noqa: B009
    return cast(RunLogger, file_run_logger(root=root, dir_namer=kwargs.get("dir_namer")))


def _create_noop_run_logger(**kwargs: Any) -> RunLogger:
    return NoOpRunLogger()


logger_registry.register(backend="simple", factory=_create_simple_logger)
logger_registry.register(backend="structured", factory=_create_structured_logger)
tracer_registry.register(backend="noop", factory=_create_noop_tracer)
tracer_registry.register(backend="otel", factory=_create_otel_tracer)
tracer_registry.register(backend="opentelemetry", factory=_create_otel_tracer)
metrics_collector_registry.register(backend="noop", factory=_create_noop_metrics)
metrics_collector_registry.register(backend="simple", factory=_create_simple_metrics)
metrics_collector_registry.register(backend="prometheus", factory=_create_prometheus_metrics)
metrics_collector_registry.register(backend="otel", factory=_create_otel_metrics)
metrics_collector_registry.register(backend="opentelemetry", factory=_create_otel_metrics)
run_logger_registry.register(backend="memory", factory=_create_memory_run_logger)
run_logger_registry.register(backend="file", factory=_create_file_run_logger)
run_logger_registry.register(backend="noop", factory=_create_noop_run_logger)


def create_logger(
    backend: str = "simple",
    level: str = "INFO",
    **backend_options: Any,
) -> Logger:
    """
    Factory for Logger with sensible defaults.

    Args:
        backend: Logger backend (simple, structured, or registered custom backend)
        level: Log level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured Logger instance

    Example:
        # Simple logger
        logger = create_logger()

        # Debug level
        logger = create_logger(level="DEBUG")
    """
    return logger_registry.create(backend=backend, level=level, **backend_options)


def create_logger_from_config(settings: Settings | None = None) -> Logger:
    """
    Create Logger from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_LOGGER_BACKEND: Backend (default: "simple")
    - CEMAF_OBSERVABILITY_LOG_LEVEL: Log level (default: "INFO")

    Returns:
        Configured Logger instance
    """
    cfg = settings or load_settings_from_env_sync()
    backend = os.getenv("CEMAF_OBSERVABILITY_LOGGER_BACKEND", "simple")
    level = os.getenv("CEMAF_OBSERVABILITY_LOG_LEVEL", cfg.observability.log_level)
    return create_logger(backend=backend, level=level)


def create_tracer(backend: str = "noop", **backend_options: Any) -> Tracer:
    """
    Factory for Tracer with sensible defaults.

    Args:
        backend: Tracer backend (noop, otel, opentelemetry, or registered custom backend)

    Returns:
        Configured Tracer instance
    """
    return tracer_registry.create(backend=backend, **backend_options)


def create_tracer_from_config(settings: Settings | None = None) -> Tracer:
    """
    Create Tracer from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_TRACER_BACKEND: Backend (default: "noop")

    Returns:
        Configured Tracer instance
    """
    cfg = settings or load_settings_from_env_sync()
    default_backend = "otel" if cfg.observability.enable_tracing else "noop"
    backend = os.getenv("CEMAF_OBSERVABILITY_TRACER_BACKEND", default_backend)
    return create_tracer(backend=backend)


def create_metrics_collector(
    backend: str = "noop",
    prefix: str = "cemaf",
    **backend_options: Any,
) -> MetricsCollector:
    """
    Factory for MetricsCollector with sensible defaults.

    Args:
        backend: Metrics backend (noop, simple, prometheus, otel, opentelemetry, or registered custom backend)

    Returns:
        Configured MetricsCollector instance

    Example:
        # No-op (default)
        metrics = create_metrics_collector()

        # Simple metrics (logs to stdout)
        metrics = create_metrics_collector("simple")
    """
    return metrics_collector_registry.create(
        backend=backend,
        prefix=prefix,
        **backend_options,
    )


def create_metrics_collector_from_config(settings: Settings | None = None) -> MetricsCollector:
    """
    Create MetricsCollector from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_METRICS_BACKEND: Backend (default: "noop")
    - CEMAF_OBSERVABILITY_METRICS_PREFIX: Metric prefix (default: "cemaf")

    Returns:
        Configured MetricsCollector instance

    Supported backends:
        - noop: No-op metrics (default)
        - simple: Simple metrics that log to stdout
        - prometheus: Prometheus metrics collector
        - otel/opentelemetry: OpenTelemetry metrics collector
        - registered custom backends

    Environment examples:
        # Use simple metrics
        export CEMAF_OBSERVABILITY_METRICS_BACKEND=simple

        # Use an optional built-in backend
        export CEMAF_OBSERVABILITY_METRICS_BACKEND=prometheus
    """
    cfg = settings or load_settings_from_env_sync()
    default_backend = "simple" if cfg.observability.enable_metrics else "noop"
    backend = os.getenv("CEMAF_OBSERVABILITY_METRICS_BACKEND", default_backend).lower()
    prefix = os.getenv("CEMAF_OBSERVABILITY_METRICS_PREFIX", cfg.app_name)
    return create_metrics_collector(backend=backend, prefix=prefix)


def create_budget_guard(
    *,
    max_cost_usd: float = 1.0,
    max_total_tokens: int = 500_000,
    warning_threshold: float = 0.7,
    critical_threshold: float = 0.9,
) -> BudgetGuard:
    """Create a BudgetGuard with explicit token/cost thresholds."""
    return BudgetGuard(
        max_cost_usd=max_cost_usd,
        max_total_tokens=max_total_tokens,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    )


def create_run_logger(
    backend: str = "memory",
    enable_recording: bool = True,
    *,
    root: str | Path | None = None,
    dir_namer: Callable[[str, str], str] | None = None,
    **backend_options: Any,
) -> RunLogger:
    """
    Factory for RunLogger with sensible defaults.

    Args:
        backend: Run logger backend (memory, file, noop, or registered custom backend)
        enable_recording: Enable recording of runs
        root: Filesystem root for file-backed run logging
        dir_namer: Optional directory namer for file-backed run logging

    Returns:
        Configured RunLogger instance

    Example:
        # In-memory run logger
        logger = create_run_logger()

        # No-op (disabled)
        logger = create_run_logger(backend="noop")
    """
    return run_logger_registry.create(
        backend=backend,
        enable_recording=enable_recording,
        root=root,
        dir_namer=dir_namer,
        **backend_options,
    )


def create_run_logger_from_config(settings: Settings | None = None) -> RunLogger:
    """
    Create RunLogger from environment configuration.

    Reads from environment variables:
    - CEMAF_OBSERVABILITY_RUN_LOGGER_BACKEND: Backend (default: "memory")
    - CEMAF_OBSERVABILITY_ENABLE_RUN_RECORDING: Enable recording (default: True)
    - CEMAF_OBSERVABILITY_RUN_LOGGER_ROOT: Root directory for file backend

    Returns:
        Configured RunLogger instance
    """
    cfg = settings or load_settings_from_env_sync()
    backend = os.getenv("CEMAF_OBSERVABILITY_RUN_LOGGER_BACKEND", "memory")
    enable_recording = _env_bool(
        "CEMAF_OBSERVABILITY_ENABLE_RUN_RECORDING",
        cfg.observability.enable_run_recording,
    )
    root = os.getenv("CEMAF_OBSERVABILITY_RUN_LOGGER_ROOT")
    return create_run_logger(backend=backend, enable_recording=enable_recording, root=root)
