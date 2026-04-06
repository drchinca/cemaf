"""Tests for MetricsHelper and record_timing utilities."""

from unittest.mock import MagicMock, call

import pytest

from cemaf.observability.metrics_helper import MetricsHelper, record_timing


@pytest.fixture()
def metrics() -> MagicMock:
    """Create a mock MetricsCollector."""
    return MagicMock()


class TestRecordTiming:
    """Tests for the record_timing context manager."""

    def test_records_timing_on_normal_exit(self, metrics: MagicMock) -> None:
        with record_timing(metrics, "test.operation", tags={"env": "test"}):
            pass

        metrics.timing.assert_called_once()
        name, duration_ms = metrics.timing.call_args.args
        assert name == "test.operation"
        assert duration_ms >= 0
        assert metrics.timing.call_args.kwargs == {"tags": {"env": "test"}}

    def test_records_timing_on_exception(self, metrics: MagicMock) -> None:
        with pytest.raises(ValueError, match="boom"), record_timing(metrics, "failing.op"):
            raise ValueError("boom")

        metrics.timing.assert_called_once()
        name, _ = metrics.timing.call_args.args
        assert name == "failing.op"

    def test_records_timing_with_no_tags(self, metrics: MagicMock) -> None:
        with record_timing(metrics, "bare.metric"):
            pass

        metrics.timing.assert_called_once()
        assert metrics.timing.call_args.kwargs == {"tags": None}


class TestRecordExecution:
    """Tests for MetricsHelper.record_execution."""

    def test_success_records_counter_and_histogram(self, metrics: MagicMock) -> None:
        MetricsHelper.record_execution(
            metrics=metrics,
            name="cemaf.node",
            duration_ms=150.5,
            success=True,
            tags={"node_id": "n1"},
        )

        expected_tags = {"node_id": "n1", "status": "success"}
        metrics.counter.assert_any_call("cemaf.node.total", tags=expected_tags)
        metrics.counter.assert_any_call("cemaf.node.success", tags=expected_tags)
        metrics.histogram.assert_called_once_with("cemaf.node.duration_ms", 150.5, tags=expected_tags)

    def test_failure_records_failed_counter(self, metrics: MagicMock) -> None:
        MetricsHelper.record_execution(
            metrics=metrics,
            name="cemaf.node",
            duration_ms=50.0,
            success=False,
        )

        expected_tags = {"status": "failed"}
        metrics.counter.assert_any_call("cemaf.node.total", tags=expected_tags)
        metrics.counter.assert_any_call("cemaf.node.failed", tags=expected_tags)
        # Should not record success counter
        success_calls = [
            c for c in metrics.counter.call_args_list if c == call("cemaf.node.success", tags=expected_tags)
        ]
        assert len(success_calls) == 0

    def test_no_tags_defaults_to_empty_dict_with_status(self, metrics: MagicMock) -> None:
        MetricsHelper.record_execution(
            metrics=metrics,
            name="op",
            duration_ms=10.0,
            success=True,
        )

        metrics.counter.assert_any_call("op.total", tags={"status": "success"})


class TestRecordLLMCall:
    """Tests for MetricsHelper.record_llm_call."""

    def test_successful_call_records_all_metrics(self, metrics: MagicMock) -> None:
        MetricsHelper.record_llm_call(
            metrics=metrics,
            model="claude-opus-4-5",
            prompt_tokens=1000,
            completion_tokens=500,
            duration_ms=2345.67,
            success=True,
        )

        tags = {"model": "claude-opus-4-5"}
        metrics.counter.assert_any_call("cemaf.llm.calls.total", tags=tags)
        metrics.counter.assert_any_call("cemaf.llm.calls.success", tags=tags)
        metrics.counter.assert_any_call("cemaf.llm.tokens.prompt", value=1000, tags=tags)
        metrics.counter.assert_any_call("cemaf.llm.tokens.completion", value=500, tags=tags)
        metrics.counter.assert_any_call("cemaf.llm.tokens.total", value=1500, tags=tags)
        metrics.histogram.assert_any_call("cemaf.llm.latency_ms", 2345.67, tags=tags)

    def test_failed_call_records_failed_counter(self, metrics: MagicMock) -> None:
        MetricsHelper.record_llm_call(
            metrics=metrics,
            model="claude-sonnet",
            prompt_tokens=100,
            completion_tokens=0,
            duration_ms=500.0,
            success=False,
        )

        tags = {"model": "claude-sonnet"}
        metrics.counter.assert_any_call("cemaf.llm.calls.failed", tags=tags)
        # Should not record success
        success_calls = [
            c for c in metrics.counter.call_args_list if c == call("cemaf.llm.calls.success", tags=tags)
        ]
        assert len(success_calls) == 0

    def test_cost_records_histogram_and_counter_in_cents(self, metrics: MagicMock) -> None:
        MetricsHelper.record_llm_call(
            metrics=metrics,
            model="claude-opus-4-5",
            prompt_tokens=500,
            completion_tokens=200,
            duration_ms=1000.0,
            success=True,
            cost=0.0225,
        )

        tags = {"model": "claude-opus-4-5"}
        metrics.histogram.assert_any_call("cemaf.llm.cost.cents", 2.25, tags=tags)
        metrics.counter.assert_any_call("cemaf.llm.cost.total_cents", value=2, tags=tags)

    def test_no_cost_skips_cost_metrics(self, metrics: MagicMock) -> None:
        MetricsHelper.record_llm_call(
            metrics=metrics,
            model="m",
            prompt_tokens=10,
            completion_tokens=5,
            duration_ms=100.0,
            success=True,
        )

        cost_calls = [c for c in metrics.histogram.call_args_list if "cost" in str(c)]
        assert len(cost_calls) == 0

    def test_finish_reason_records_counter(self, metrics: MagicMock) -> None:
        MetricsHelper.record_llm_call(
            metrics=metrics,
            model="m",
            prompt_tokens=10,
            completion_tokens=5,
            duration_ms=100.0,
            success=True,
            finish_reason="stop",
        )

        tags = {"model": "m"}
        metrics.counter.assert_any_call("cemaf.llm.finish_reason.stop", tags=tags)

    def test_no_finish_reason_skips_reason_counter(self, metrics: MagicMock) -> None:
        MetricsHelper.record_llm_call(
            metrics=metrics,
            model="m",
            prompt_tokens=10,
            completion_tokens=5,
            duration_ms=100.0,
            success=True,
        )

        reason_calls = [c for c in metrics.counter.call_args_list if "finish_reason" in str(c)]
        assert len(reason_calls) == 0


class TestRecordError:
    """Tests for MetricsHelper.record_error."""

    def test_records_failed_and_typed_error_counters(self, metrics: MagicMock) -> None:
        MetricsHelper.record_error(
            metrics=metrics,
            operation="cemaf.dag.execution",
            error_type="TimeoutError",
            tags={"dag_name": "my_dag"},
        )

        expected_tags = {"dag_name": "my_dag", "error_type": "TimeoutError"}
        metrics.counter.assert_any_call("cemaf.dag.execution.failed", tags=expected_tags)
        metrics.counter.assert_any_call("cemaf.dag.execution.errors.TimeoutError", tags=expected_tags)

    def test_no_tags_still_includes_error_type(self, metrics: MagicMock) -> None:
        MetricsHelper.record_error(
            metrics=metrics,
            operation="op",
            error_type="ValueError",
        )

        expected_tags = {"error_type": "ValueError"}
        metrics.counter.assert_any_call("op.failed", tags=expected_tags)
        metrics.counter.assert_any_call("op.errors.ValueError", tags=expected_tags)

    def test_records_exactly_two_counters(self, metrics: MagicMock) -> None:
        MetricsHelper.record_error(
            metrics=metrics,
            operation="op",
            error_type="RuntimeError",
        )

        assert metrics.counter.call_count == 2


class TestRecordContextCompilation:
    """Tests for MetricsHelper.record_context_compilation."""

    def test_records_all_compilation_metrics(self, metrics: MagicMock) -> None:
        MetricsHelper.record_context_compilation(
            metrics=metrics,
            sources_considered=20,
            sources_included=8,
            total_tokens=3500,
            budget_available=10000,
            selection_method="priority",
            tags={"dag": "test"},
        )

        expected_tags = {"dag": "test", "selection_method": "priority"}
        metrics.counter.assert_called_once_with("cemaf.context.compilation.total", tags=expected_tags)
        metrics.gauge.assert_any_call("cemaf.context.sources.considered", 20, tags=expected_tags)
        metrics.gauge.assert_any_call("cemaf.context.sources.included", 8, tags=expected_tags)
        metrics.gauge.assert_any_call("cemaf.context.tokens.used", 3500, tags=expected_tags)
        metrics.histogram.assert_called_once_with(
            "cemaf.context.budget.utilization", 0.35, tags=expected_tags
        )

    def test_zero_budget_skips_utilization_histogram(self, metrics: MagicMock) -> None:
        MetricsHelper.record_context_compilation(
            metrics=metrics,
            sources_considered=5,
            sources_included=3,
            total_tokens=1000,
            budget_available=0,
            selection_method="greedy",
        )

        metrics.histogram.assert_not_called()


class TestRecordBudgetUtilization:
    """Tests for MetricsHelper.record_budget_utilization."""

    def test_records_cost_and_token_utilization(self, metrics: MagicMock) -> None:
        MetricsHelper.record_budget_utilization(
            metrics=metrics,
            cost_usd=5.0,
            tokens_used=50000,
            max_cost_usd=10.0,
            max_tokens=100000,
        )

        expected_tags = {"halted": "False"}
        metrics.histogram.assert_any_call("cemaf.budget.cost_usd", 5.0, tags=expected_tags)
        metrics.histogram.assert_any_call("cemaf.budget.cost_utilization", 0.5, tags=expected_tags)
        metrics.histogram.assert_any_call("cemaf.budget.token_utilization", 0.5, tags=expected_tags)
        metrics.gauge.assert_called_once_with("cemaf.budget.tokens_used", 50000, tags=expected_tags)

    def test_halted_records_halt_counter(self, metrics: MagicMock) -> None:
        MetricsHelper.record_budget_utilization(
            metrics=metrics,
            cost_usd=10.0,
            tokens_used=100000,
            max_cost_usd=10.0,
            max_tokens=100000,
            halted=True,
        )

        expected_tags = {"halted": "True"}
        metrics.counter.assert_called_once_with("cemaf.budget.halt", tags=expected_tags)

    def test_zero_max_cost_skips_cost_utilization(self, metrics: MagicMock) -> None:
        MetricsHelper.record_budget_utilization(
            metrics=metrics,
            cost_usd=0.0,
            tokens_used=1000,
            max_cost_usd=0.0,
            max_tokens=5000,
        )

        cost_util_calls = [c for c in metrics.histogram.call_args_list if "cost_utilization" in str(c)]
        assert len(cost_util_calls) == 0

    def test_zero_max_tokens_skips_token_utilization(self, metrics: MagicMock) -> None:
        MetricsHelper.record_budget_utilization(
            metrics=metrics,
            cost_usd=1.0,
            tokens_used=0,
            max_cost_usd=5.0,
            max_tokens=0,
        )

        token_util_calls = [c for c in metrics.histogram.call_args_list if "token_utilization" in str(c)]
        assert len(token_util_calls) == 0


class TestRecordCitationEvent:
    """Tests for MetricsHelper.record_citation_event."""

    def test_records_citation_counter(self, metrics: MagicMock) -> None:
        MetricsHelper.record_citation_event(
            metrics=metrics,
            event_type="verified",
            citation_count=3,
            tags={"source": "web"},
        )

        expected_tags = {"source": "web", "event_type": "verified"}
        metrics.counter.assert_called_once_with("cemaf.citation.events", value=3, tags=expected_tags)

    def test_default_citation_count_is_one(self, metrics: MagicMock) -> None:
        MetricsHelper.record_citation_event(
            metrics=metrics,
            event_type="added",
        )

        metrics.counter.assert_called_once_with(
            "cemaf.citation.events", value=1, tags={"event_type": "added"}
        )


class TestRecordCacheOperation:
    """Tests for MetricsHelper.record_cache_operation."""

    def test_records_cache_counter(self, metrics: MagicMock) -> None:
        MetricsHelper.record_cache_operation(
            metrics=metrics,
            cache_name="result_cache",
            operation="hit",
        )

        metrics.counter.assert_called_once_with("cemaf.cache.hit", tags={"cache_name": "result_cache"})

    def test_records_duration_when_provided(self, metrics: MagicMock) -> None:
        MetricsHelper.record_cache_operation(
            metrics=metrics,
            cache_name="embeddings",
            operation="miss",
            duration_us=42.5,
        )

        metrics.histogram.assert_called_once_with(
            "cemaf.cache.miss.duration_us", 42.5, tags={"cache_name": "embeddings"}
        )

    def test_no_duration_skips_histogram(self, metrics: MagicMock) -> None:
        MetricsHelper.record_cache_operation(
            metrics=metrics,
            cache_name="c",
            operation="set",
        )

        metrics.histogram.assert_not_called()

    def test_evict_operation(self, metrics: MagicMock) -> None:
        MetricsHelper.record_cache_operation(
            metrics=metrics,
            cache_name="c",
            operation="evict",
            duration_us=10.0,
        )

        metrics.counter.assert_called_once_with("cemaf.cache.evict", tags={"cache_name": "c"})
        metrics.histogram.assert_called_once_with(
            "cemaf.cache.evict.duration_us", 10.0, tags={"cache_name": "c"}
        )
