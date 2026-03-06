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

from cemaf.observability.alerting_rules import (
    RECOMMENDED_ALERTS,
    AlertRule,
    Severity,
    export_prometheus_rules,
    get_alert_by_name,
    get_alerts_by_severity,
)
from cemaf.observability.budget_guard import AlertLevel, BudgetAlert, BudgetGuard
from cemaf.observability.config import (
    configure_logging,
    configure_metrics,
    configure_tracing,
    get_logger,
    get_metrics,
    get_tracer,
    reset_observability,
)
from cemaf.observability.cost_tracking import ModelPricing, ModelPricingRegistry
from cemaf.observability.glass_box import GlassBoxReport, GlassBoxReporter
from cemaf.observability.health import (
    HealthCheck,
    HealthCheckResult,
    HealthMonitor,
    HealthStatus,
    get_health_monitor,
)
from cemaf.observability.metrics_helper import MetricsHelper, record_timing
from cemaf.observability.protocols import Logger, MetricsCollector, Tracer
from cemaf.observability.run_logger import (
    InMemoryRunLogger,
    LLMCall,
    NoOpRunLogger,
    RunLogger,
    RunRecord,
    ToolCall,
)
from cemaf.observability.simple import NoOpMetrics, NoOpTracer, SimpleLogger, SimpleMetrics
from cemaf.observability.token_telemetry import (
    count_tokens,
    extract_token_metadata,
    merge_token_metadata,
)

__all__ = [
    # Configuration
    "configure_logging",
    "configure_tracing",
    "configure_metrics",
    "get_logger",
    "get_tracer",
    "get_metrics",
    "reset_observability",
    # Protocols
    "Logger",
    "Tracer",
    "MetricsCollector",
    # Simple implementations
    "SimpleLogger",
    "SimpleMetrics",
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
    # Cost tracking
    "ModelPricing",
    "ModelPricingRegistry",
    # Token telemetry
    "extract_token_metadata",
    "count_tokens",
    "merge_token_metadata",
    # Metrics helpers
    "MetricsHelper",
    "record_timing",
    # Budget guard
    "BudgetGuard",
    "BudgetAlert",
    "AlertLevel",
    # Glass box
    "GlassBoxReport",
    "GlassBoxReporter",
    # Alerting rules
    "AlertRule",
    "Severity",
    "RECOMMENDED_ALERTS",
    "export_prometheus_rules",
    "get_alert_by_name",
    "get_alerts_by_severity",
]
