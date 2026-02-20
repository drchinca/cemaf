"""
Metrics collection helper utilities.

Provides common patterns for recording metrics, including context managers
for automatic timing and standardized metric recording functions.

Example:
    from cemaf.observability import get_metrics
    from cemaf.observability.metrics_helper import MetricsHelper, record_timing

    metrics = get_metrics()

    # Record execution metrics
    MetricsHelper.record_execution(
        metrics,
        "cemaf.node.execution",
        duration_ms=123.45,
        success=True,
        tags={"node_id": "step1"}
    )

    # Use context manager for automatic timing
    with record_timing(metrics, "cemaf.dag.execution", tags={"dag_name": "my_dag"}):
        # do work
        pass
"""

from contextlib import contextmanager
from time import perf_counter
from typing import Any

from cemaf.core.types import JSON
from cemaf.observability.protocols import MetricsCollector


@contextmanager
def record_timing(
    metrics: MetricsCollector,
    name: str,
    tags: JSON | None = None,
) -> Any:
    """
    Context manager for automatic timing metrics.

    Measures elapsed time and records as a timing metric.
    Useful for wrapping blocks of code to automatically record duration.

    Args:
        metrics: MetricsCollector instance
        name: Metric name (without prefix)
        tags: Metric tags/labels

    Example:
        metrics = get_metrics()
        with record_timing(metrics, "dag.execution", tags={"dag_name": "test"}):
            # do work - timing automatically recorded
            result = await executor.run(dag)
    """
    start = perf_counter()
    try:
        yield
    finally:
        duration_ms = (perf_counter() - start) * 1000
        metrics.timing(name, duration_ms, tags=tags)


class MetricsHelper:
    """Helper utilities for common metrics patterns."""

    @staticmethod
    def record_execution(
        metrics: MetricsCollector,
        name: str,
        duration_ms: float,
        success: bool,
        tags: JSON | None = None,
    ) -> None:
        """
        Record execution metrics with standard pattern.

        Records counter for total executions, counter for success/failed,
        and histogram for duration.

        Args:
            metrics: MetricsCollector instance
            name: Base metric name (without ".total" or ".duration_ms" suffix)
            duration_ms: Execution duration in milliseconds
            success: Whether execution succeeded
            tags: Metric tags/labels (will include status=success/failed)

        Example:
            MetricsHelper.record_execution(
                metrics,
                "cemaf.node.execution",
                duration_ms=123.45,
                success=True,
                tags={"node_id": "step1", "node_type": "TOOL"}
            )

            # Records:
            # - cemaf.node.execution.total (counter)
            # - cemaf.node.execution.success or .failed (counter)
            # - cemaf.node.execution.duration_ms (histogram)
        """
        all_tags = {**(tags or {}), "status": "success" if success else "failed"}

        # Record total executions
        metrics.counter(f"{name}.total", tags=all_tags)

        # Record success/failed
        if success:
            metrics.counter(f"{name}.success", tags=all_tags)
        else:
            metrics.counter(f"{name}.failed", tags=all_tags)

        # Record duration
        metrics.histogram(f"{name}.duration_ms", duration_ms, tags=all_tags)

    @staticmethod
    def record_llm_call(
        metrics: MetricsCollector,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_ms: float,
        success: bool,
        finish_reason: str | None = None,
        cost: float | None = None,
    ) -> None:
        """
        Record LLM call metrics with standard pattern.

        Records counters for tokens, timing, success/failure, and cost.

        Args:
            metrics: MetricsCollector instance
            model: Model ID (e.g., "claude-opus-4-5")
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            duration_ms: LLM call duration in milliseconds
            success: Whether LLM call succeeded
            finish_reason: LLM finish reason (stop, length, tool_calls, etc.)
            cost: Cost in USD (if calculated)

        Example:
            MetricsHelper.record_llm_call(
                metrics,
                model="claude-opus-4-5",
                prompt_tokens=1000,
                completion_tokens=500,
                duration_ms=2345.67,
                success=True,
                finish_reason="stop",
                cost=0.0225
            )

            # Records:
            # - cemaf.llm.calls.total (counter)
            # - cemaf.llm.calls.success or .failed (counter)
            # - cemaf.llm.tokens.prompt (counter)
            # - cemaf.llm.tokens.completion (counter)
            # - cemaf.llm.tokens.total (counter)
            # - cemaf.llm.latency_ms (histogram)
            # - cemaf.llm.cost.cents (histogram, if cost provided)
            # - cemaf.llm.finish_reason.* (counter, if reason provided)
        """
        tags = {"model": model}

        # Record call counts
        metrics.counter("cemaf.llm.calls.total", tags=tags)
        if success:
            metrics.counter("cemaf.llm.calls.success", tags=tags)
        else:
            metrics.counter("cemaf.llm.calls.failed", tags=tags)

        # Record token counts
        metrics.counter("cemaf.llm.tokens.prompt", value=prompt_tokens, tags=tags)
        metrics.counter("cemaf.llm.tokens.completion", value=completion_tokens, tags=tags)
        metrics.counter("cemaf.llm.tokens.total", value=prompt_tokens + completion_tokens, tags=tags)

        # Record latency
        metrics.histogram("cemaf.llm.latency_ms", duration_ms, tags=tags)

        # Record cost if provided (in cents for better histogram resolution)
        if cost is not None:
            cost_cents = cost * 100
            metrics.histogram("cemaf.llm.cost.cents", cost_cents, tags=tags)
            metrics.counter("cemaf.llm.cost.total_cents", value=int(cost_cents), tags=tags)

        # Record finish reason if provided
        if finish_reason:
            metrics.counter(f"cemaf.llm.finish_reason.{finish_reason}", tags=tags)

    @staticmethod
    def record_error(
        metrics: MetricsCollector,
        operation: str,
        error_type: str,
        tags: JSON | None = None,
    ) -> None:
        """
        Record error metrics.

        Args:
            metrics: MetricsCollector instance
            operation: Operation name (e.g., "dag.execution")
            error_type: Exception class name (e.g., "ValueError", "TimeoutError")
            tags: Metric tags/labels

        Example:
            try:
                await executor.run(dag)
            except Exception as e:
                MetricsHelper.record_error(
                    metrics,
                    "cemaf.dag.execution",
                    error_type=type(e).__name__,
                    tags={"dag_name": dag.name}
                )
        """
        error_tags = {**(tags or {}), "error_type": error_type}
        metrics.counter(f"{operation}.failed", tags=error_tags)
        metrics.counter(f"{operation}.errors.{error_type}", tags=error_tags)

    @staticmethod
    def record_context_compilation(
        metrics: MetricsCollector,
        sources_considered: int,
        sources_included: int,
        total_tokens: int,
        budget_available: int,
        selection_method: str,
        tags: JSON | None = None,
    ) -> None:
        """Record context compilation metrics."""
        all_tags = {
            **(tags or {}),
            "selection_method": selection_method,
        }
        metrics.counter("cemaf.context.compilation.total", tags=all_tags)
        metrics.gauge(
            "cemaf.context.sources.considered",
            sources_considered,
            tags=all_tags,
        )
        metrics.gauge(
            "cemaf.context.sources.included",
            sources_included,
            tags=all_tags,
        )
        metrics.gauge("cemaf.context.tokens.used", total_tokens, tags=all_tags)
        if budget_available > 0:
            utilization = total_tokens / budget_available
            metrics.histogram(
                "cemaf.context.budget.utilization",
                utilization,
                tags=all_tags,
            )

    @staticmethod
    def record_budget_utilization(
        metrics: MetricsCollector,
        cost_usd: float,
        tokens_used: int,
        max_cost_usd: float,
        max_tokens: int,
        halted: bool = False,
        tags: JSON | None = None,
    ) -> None:
        """Record budget guard utilization metrics."""
        all_tags = {**(tags or {}), "halted": str(halted)}
        metrics.histogram("cemaf.budget.cost_usd", cost_usd, tags=all_tags)
        metrics.gauge("cemaf.budget.tokens_used", tokens_used, tags=all_tags)
        if max_cost_usd > 0:
            metrics.histogram(
                "cemaf.budget.cost_utilization",
                cost_usd / max_cost_usd,
                tags=all_tags,
            )
        if max_tokens > 0:
            metrics.histogram(
                "cemaf.budget.token_utilization",
                tokens_used / max_tokens,
                tags=all_tags,
            )
        if halted:
            metrics.counter("cemaf.budget.halt", tags=all_tags)

    @staticmethod
    def record_citation_event(
        metrics: MetricsCollector,
        event_type: str,
        citation_count: int = 1,
        tags: JSON | None = None,
    ) -> None:
        """Record citation tracking event."""
        all_tags = {**(tags or {}), "event_type": event_type}
        metrics.counter(
            "cemaf.citation.events",
            value=citation_count,
            tags=all_tags,
        )

    @staticmethod
    def record_cache_operation(
        metrics: MetricsCollector,
        cache_name: str,
        operation: str,  # "hit", "miss", "set", "evict"
        duration_us: float | None = None,
    ) -> None:
        """
        Record cache operation metrics.

        Args:
            metrics: MetricsCollector instance
            cache_name: Cache identifier
            operation: Operation type (hit, miss, set, evict)
            duration_us: Operation duration in microseconds (optional)

        Example:
            MetricsHelper.record_cache_operation(
                metrics,
                cache_name="result_cache",
                operation="hit",
                duration_us=123.45
            )
        """
        tags = {"cache_name": cache_name}
        metrics.counter(f"cemaf.cache.{operation}", tags=tags)

        if duration_us is not None:
            metrics.histogram(f"cemaf.cache.{operation}.duration_us", duration_us, tags=tags)
