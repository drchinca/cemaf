"""
Observability module - Logging, tracing, and metrics.

Provides pluggable interfaces for:
- Logging (structured, leveled)
- Tracing (distributed traces)
- Metrics (counters, gauges, histograms)
"""

from cemaf.observability.protocols import Logger, Tracer, MetricsCollector
from cemaf.observability.simple import SimpleLogger, NoOpTracer, NoOpMetrics

__all__ = [
    # Protocols
    "Logger",
    "Tracer",
    "MetricsCollector",
    # Simple implementations
    "SimpleLogger",
    "NoOpTracer",
    "NoOpMetrics",
]

