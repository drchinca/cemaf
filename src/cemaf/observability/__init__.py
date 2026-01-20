"""
Observability module - Logging, tracing, metrics, and health checks.

Provides pluggable interfaces for:
- Logging (structured, leveled, lazy evaluation)
- Tracing (distributed traces)
- Metrics (counters, gauges, histograms)
- Health checks (system monitoring)
- Run logging (recording and replay)

Configuration:
    # Configure at application startup
    from cemaf.observability import configure_logging, configure_metrics

    configure_logging(level="DEBUG")  # Set log level
    configure_metrics(metrics=PrometheusMetrics())  # Use custom metrics

    # Get logger in your code
    from cemaf.observability import get_logger

    logger = get_logger(__name__)
    logger.info("Started processing", item_count=len(items))
"""

from cemaf.observability.config import (
    configure_logging,
    configure_metrics,
    configure_tracing,
    get_logger,
    get_metrics,
    get_tracer,
)
from cemaf.observability.health import (
    HealthCheck,
    HealthCheckResult,
    HealthMonitor,
    HealthStatus,
    get_health_monitor,
)
from cemaf.observability.protocols import Logger, MetricsCollector, Tracer
from cemaf.observability.run_logger import (
    InMemoryRunLogger,
    LLMCall,
    NoOpRunLogger,
    RunLogger,
    RunRecord,
    ToolCall,
)
from cemaf.observability.simple import NoOpMetrics, NoOpTracer, SimpleLogger

__all__ = [
    # Configuration
    "configure_logging",
    "configure_tracing",
    "configure_metrics",
    "get_logger",
    "get_tracer",
    "get_metrics",
    # Protocols
    "Logger",
    "Tracer",
    "MetricsCollector",
    # Simple implementations
    "SimpleLogger",
    "NoOpTracer",
    "NoOpMetrics",
    # Health checks
    "HealthStatus",
    "HealthCheckResult",
    "HealthCheck",
    "HealthMonitor",
    "get_health_monitor",
    # Run logging
    "ToolCall",
    "LLMCall",
    "RunRecord",
    "RunLogger",
    "InMemoryRunLogger",
    "NoOpRunLogger",
]
