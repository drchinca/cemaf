"""
Observability module - Logging, tracing, and metrics.

Provides pluggable interfaces for:
- Logging (structured, leveled)
- Tracing (distributed traces)
- Metrics (counters, gauges, histograms)
- Run logging (recording and replay)
"""

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
    # Protocols
    "Logger",
    "Tracer",
    "MetricsCollector",
    # Simple implementations
    "SimpleLogger",
    "NoOpTracer",
    "NoOpMetrics",
    # Run logging
    "ToolCall",
    "LLMCall",
    "RunRecord",
    "RunLogger",
    "InMemoryRunLogger",
    "NoOpRunLogger",
]
