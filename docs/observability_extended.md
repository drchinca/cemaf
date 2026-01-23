# Observability Module - Extended Documentation

## Overview

The observability module provides comprehensive logging, health monitoring, metrics collection, and execution tracing for CEMAF applications.

**What it does**: Captures detailed logs of agent execution (tool calls, context updates, decisions), performs health checks on dependencies, collects performance metrics (latency, tokens, cost), and enables distributed tracing. Supports multiple exporters (file, cloud, metrics systems) and structured logging with context propagation.

**Key use cases**:
- Debug agent behavior through detailed execution logs
- Monitor system health with liveness/readiness probes
- Track costs and token usage per run
- Identify performance bottlenecks with latency metrics
- Comply with logging requirements (audit trails, retention)
- Correlate events across distributed systems with trace IDs

**When to use vs. alternatives**: Use observability for production execution visibility, debugging, and compliance. Use it for all long-running processes. Don't use for functional validation (use validation module) or content safety (use moderation module).

## Core Concepts

### Execution Logging

RunRecord captures complete execution timeline:

**ToolCall**: When a tool executes, record the tool name, inputs, outputs, latency, cost. This enables understanding exactly what the agent did at each step.

**ContextUpdate**: When context changes (sources added, decisions made, summaries updated), record what changed. This enables understanding the reasoning flow.

**Event**: Discrete events (error, warning, retry, milestone). Useful for tracking control flow and detecting issues.

All logs include:
- Timestamp (for ordering)
- Run ID (for correlation)
- Component/tool name (for filtering)
- Structured data (for querying)

### Health Monitoring

Health checks verify system readiness:

**Liveness**: Is the service running? (process alive, not deadlocked)
**Readiness**: Can it handle requests? (dependencies available, warmed up)
**Startup**: Is initialization complete? (caches loaded, connections open)

Each health check returns status (HEALTHY, DEGRADED, UNHEALTHY) and details (what's wrong).

### Metrics Collection

Metrics track quantitative data:

**Counters**: How many tool calls, errors, retries
**Gauges**: Current queue depth, active runs, memory usage
**Histograms**: Latencies, token counts, content lengths
**Summaries**: Percentile latencies, cost distribution

Metrics enable performance analysis and alerting.

### Trace Context

Trace IDs and span IDs enable correlating logs across components and requests. When a request flows through multiple services, all use the same trace ID.

## Usage Examples

### Basic Execution Logging

```python
from cemaf.observability.run_logger import RunLogger, ToolCall, ContextUpdate

logger = RunLogger()

# Start logging a run
run_id = "run_123"
await logger.start_run(run_id, run_inputs={"query": "..."})

# Log tool execution
tool_call = ToolCall(
    tool_name="web_search",
    input={"query": "climate change", "limit": 10},
    output={"results": [...]},
    duration_ms=245.3,
    tokens_used=150,
    cost_usd=0.005
)
await logger.log_tool_call(run_id, tool_call)

# Log context changes
update = ContextUpdate(
    sources_added=["https://example.com/article1"],
    decisions_added=[("search_strategy", "use_google")],
    summaries_updated={"key_findings": "..."}
)
await logger.log_context_update(run_id, update)

# Complete run
await logger.end_run(
    run_id,
    final_outputs={"response": "..."},
    status="completed",
    total_cost=0.025
)

# Retrieve full record
record = await logger.get_record(run_id)
print(f"Run {run_id}:")
print(f"  Tool calls: {len(record.tool_calls)}")
print(f"  Duration: {record.duration_ms}ms")
print(f"  Total cost: ${record.total_cost}")
```

### Health Checks

```python
from cemaf.observability.health import HealthChecker, HealthStatus

checker = HealthChecker()

# Register health checks
async def check_database():
    try:
        await db.execute("SELECT 1")
        return HealthStatus.HEALTHY, "Database responding"
    except Exception as e:
        return HealthStatus.UNHEALTHY, f"Database error: {e}"

async def check_llm_api():
    try:
        await llm.health_check()
        return HealthStatus.HEALTHY, "LLM API available"
    except Exception as e:
        return HealthStatus.DEGRADED, f"LLM API slow: {e}"

checker.register("database", check_database)
checker.register("llm_api", check_llm_api)

# Perform health check
health = await checker.check_all()

if health.status == HealthStatus.HEALTHY:
    print("✓ All systems healthy")
elif health.status == HealthStatus.DEGRADED:
    print("⚠️  System degraded:")
    for check, result in health.checks.items():
        if result.status == HealthStatus.DEGRADED:
            print(f"  {check}: {result.message}")
else:
    print("❌ System unhealthy")
    for check, result in health.checks.items():
        if result.status == HealthStatus.UNHEALTHY:
            print(f"  {check}: {result.message}")
```

### Metrics Collection

```python
from cemaf.observability.metrics import MetricsCollector

metrics = MetricsCollector()

# Track tool execution
metrics.record_tool_execution(
    tool_name="web_search",
    duration_ms=245,
    tokens=150,
    success=True
)

# Track generation
metrics.record_generation(
    model="claude-3-5-sonnet",
    tokens_in=500,
    tokens_out=1200,
    latency_ms=2500,
    cost=0.025
)

# Track errors
metrics.record_error(
    error_type="ToolTimeoutError",
    tool_name="web_search"
)

# Query metrics
stats = metrics.get_tool_stats("web_search")
print(f"Web search - p50: {stats.p50_latency}ms, p99: {stats.p99_latency}ms")
print(f"  Success rate: {stats.success_rate:.1%}")
print(f"  Total cost: ${stats.total_cost}")
```

### Structured Logging with Context

```python
from cemaf.observability.logger import StructuredLogger

logger = StructuredLogger()

# Log with structured data
await logger.info(
    "Generation started",
    run_id=run_id,
    model="claude-3-5-sonnet",
    max_tokens=1000,
    extra={"user_id": "user_123", "project": "campaign_q1"}
)

# Log errors with context
try:
    result = await llm.generate(prompt)
except Exception as e:
    await logger.error(
        "Generation failed",
        run_id=run_id,
        error=str(e),
        error_type=type(e).__name__,
        extra={"prompt_length": len(prompt)}
    )

# Log with different levels
await logger.debug("Detailed execution trace", ...)
await logger.warning("Unexpected behavior but continuing", ...)
await logger.critical("System failure, immediate action needed", ...)
```

### Distributed Tracing

```python
from cemaf.observability.tracing import Tracer, SpanContext

tracer = Tracer()

# Create root span for request
with tracer.start_span("user_request", span_context=SpanContext()) as span:
    span.set_attribute("user_id", "user_123")

    # Child spans for components
    with tracer.start_child_span("context_retrieval") as child:
        child.set_attribute("query", "...")
        sources = await retrieval.retrieve()

    with tracer.start_child_span("generation") as child:
        child.set_attribute("model", "claude-3-5-sonnet")
        response = await llm.generate(prompt)

    with tracer.start_child_span("moderation") as child:
        child.set_attribute("content_length", len(response))
        result = await moderator.moderate(response)

# All spans share same trace ID for correlation
```

### Cost Tracking

```python
from cemaf.observability.metrics import CostTracker

tracker = CostTracker()

# Track LLM costs
await tracker.record_llm_call(
    model="claude-3-5-sonnet",
    input_tokens=500,
    output_tokens=1200,
    cost_per_input=0.003,
    cost_per_output=0.015
)

# Track API costs
await tracker.record_api_call(
    api_name="web_search",
    cost=0.005
)

# Get cost breakdown
costs = await tracker.get_run_costs(run_id)
print(f"Run {run_id} cost breakdown:")
print(f"  LLM: ${costs['llm']:.4f}")
print(f"  APIs: ${costs['api']:.4f}")
print(f"  Total: ${costs['total']:.4f}")

# Project cost forecast
monthly_forecast = await tracker.forecast_monthly_cost()
print(f"Projected monthly cost: ${monthly_forecast:.2f}")
```

### Error Tracking and Alerting

```python
from cemaf.observability.logger import StructuredLogger
from cemaf.observability.metrics import ErrorMetrics

logger = StructuredLogger()
errors = ErrorMetrics()

# Track error
try:
    result = await risky_operation()
except Exception as e:
    # Log error with full context
    await logger.error(
        "Operation failed",
        error=str(e),
        error_type=type(e).__name__,
        stack_trace=traceback.format_exc(),
        context={
            "operation": "risky_operation",
            "run_id": run_id,
            "retry_count": retry_count
        }
    )

    # Track metrics
    errors.record_error(
        error_type=type(e).__name__,
        severity="high"
    )

    # Alert if error rate exceeds threshold
    if errors.get_error_rate() > 0.05:  # 5% error rate
        await alerter.alert(
            level="critical",
            message=f"Error rate {errors.get_error_rate():.1%} exceeds threshold"
        )
```

### Common Mistake: Lost Log Context

```python
# ❌ WRONG - Logs without trace ID or run ID
await logger.info("Tool executed")
# Later, can't correlate with which run

# ✅ CORRECT - Include trace/run context
await logger.info(
    "Tool executed",
    run_id=run_id,
    trace_id=trace_id,
    tool_name="web_search"
)
# Can correlate and filter
```

## Integration

### With Persistence Module

```python
from cemaf.observability.run_logger import RunLogger
from cemaf.persistence.entities import Run, RunStatus

logger = RunLogger()
run_record = await logger.get_record(run_id)

# Convert to persistence entity
run = Run(
    id=run_id,
    project_id=project_id,
    pipeline="content_generation",
    inputs=run_record.inputs,
    outputs=run_record.outputs,
    total_tokens_used=run_record.total_tokens_used,
    total_cost_usd=run_record.total_cost,
    status=RunStatus.COMPLETED if run_record.success else RunStatus.FAILED,
    error=run_record.error
)
await run_store.create(run)
```

### With Resilience Module

```python
from cemaf.resilience import RetryPolicy
from cemaf.observability.logger import StructuredLogger

logger = StructuredLogger()
retry_policy = RetryPolicy(max_retries=3)

# Retry tracks to observability
result = await retry_policy.execute(
    async_fn,
    on_retry=lambda attempt, error: logger.warning(
        "Retry attempt",
        attempt=attempt,
        error=str(error),
        run_id=run_id
    )
)
```

### With Events Module

```python
from cemaf.events import EventBus
from cemaf.observability.metrics import MetricsCollector

metrics = MetricsCollector()
event_bus = EventBus()

# Publish metrics as events
async def publish_metrics_events():
    stats = metrics.get_stats()
    await event_bus.publish({
        "type": "metrics.updated",
        "timestamp": utc_now(),
        "metrics": {
            "tool_calls": stats.tool_call_count,
            "avg_latency": stats.avg_latency,
            "total_cost": stats.total_cost
        }
    })
```

## API Reference

### RunLogger

```python
class RunLogger:
    async def start_run(
        self,
        run_id: str,
        run_inputs: JSON = None,
        trace_id: str | None = None
    ) -> None: ...

    async def log_tool_call(
        self,
        run_id: str,
        tool_call: ToolCall
    ) -> None: ...

    async def log_context_update(
        self,
        run_id: str,
        update: ContextUpdate
    ) -> None: ...

    async def log_error(
        self,
        run_id: str,
        error: Exception,
        context: dict = None
    ) -> None: ...

    async def end_run(
        self,
        run_id: str,
        final_outputs: JSON = None,
        status: str = "completed",
        error: str | None = None
    ) -> None: ...

    async def get_record(self, run_id: str) -> RunRecord: ...

    async def list_records(
        self,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None
    ) -> list[RunRecord]: ...
```

### HealthChecker

```python
class HealthChecker:
    def register(
        self,
        name: str,
        check: Callable[[], Awaitable[tuple[HealthStatus, str]]]
    ) -> None: ...

    async def check_all(self) -> HealthResult: ...
    async def check(self, name: str) -> tuple[HealthStatus, str]: ...

class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
```

### MetricsCollector

```python
class MetricsCollector:
    def record_tool_execution(
        self,
        tool_name: str,
        duration_ms: float,
        tokens: int = 0,
        success: bool = True,
        error: str | None = None
    ) -> None: ...

    def record_generation(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
        cost: float
    ) -> None: ...

    def record_error(
        self,
        error_type: str,
        tool_name: str | None = None,
        context: dict | None = None
    ) -> None: ...

    def get_tool_stats(self, tool_name: str) -> ToolStats: ...
    def get_stats(self) -> SystemStats: ...
```

## Best Practices

### Performance Tips

- **Async logging**: Always use async logging, don't block main execution
- **Batch exports**: Don't export every log immediately. Batch and export periodically
- **Sampling**: For high-volume systems, sample logs (log 1 in N events) to reduce volume
- **Local buffering**: Keep logs in memory initially, flush to persistent storage asynchronously

### Common Pitfalls

**Missing context**: Always include run ID, trace ID, and component name. Logs without context are useless.

**Over-logging**: Log strategically. Don't log every variable state. Log state transitions, errors, and interesting events.

**Lost errors**: Always log full error with stack trace, not just the message. You need the context to debug.

**Ignoring metrics**: Metrics are only useful if you look at them. Set up dashboards and alerts.

**Not rotating logs**: Logs grow unbounded. Implement rotation (daily, size-based) or you'll run out of disk.

### Logging Best Practices

```python
# ✅ GOOD - Structured logging
await logger.info(
    "Tool executed successfully",
    run_id=run_id,
    tool_name="web_search",
    duration_ms=245,
    results_count=10
)

# ❌ BAD - String formatting
await logger.info(f"Tool web_search ran for 245ms and returned 10 results")

# ✅ GOOD - Include error details
await logger.error(
    "Tool failed",
    error_type=type(e).__name__,
    error_message=str(e),
    stack_trace=traceback.format_exc(),
    retry_attempt=attempt
)

# ❌ BAD - Vague error logging
await logger.error("Tool failed")
```

### Health Check Strategy

Register health checks for all external dependencies:

```python
checker.register("database", check_db)          # Data storage
checker.register("llm_api", check_llm)          # Core dependency
checker.register("vector_store", check_vectors) # RAG dependency
checker.register("cache", check_cache)          # Performance optimization
checker.register("event_bus", check_events)     # Async processing
```

### Metrics to Track

Core metrics for all CEMAF systems:

```python
# Functional metrics
- Tool calls (count, success rate)
- Generation (latency, tokens, cost)
- Errors (count, type distribution)

# Performance metrics
- Request latency (p50, p95, p99)
- Queue depths (if async processing)
- Cache hit rates

# Business metrics
- Total cost (daily, monthly)
- Content generated (count, tokens)
- User satisfaction (if available)
```

### When NOT to Use

- **Runtime validation**: Use validation module, not logging
- **Business logic**: Don't put business decisions in observability
- **Sensitive data**: Don't log passwords, API keys, or PII
- **High-frequency events**: Don't log every millisecond. Sample instead.
