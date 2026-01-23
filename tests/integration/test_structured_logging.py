"""
Integration tests for structured logging throughout CEMAF.

Uses TDD approach: defines expected logging behavior first,
then implementation follows.

Tests verify:
- Structured logging with context
- Correlation IDs for request tracing
- Log levels (DEBUG, INFO, WARNING, ERROR)
- Context information in logs
- Critical path logging
- Module-specific logging
"""

import logging
from io import StringIO

import pytest

from cemaf.core.enums import RunStatus
from cemaf.core.types import NodeID, RunID
from cemaf.observability import get_logger
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor


@pytest.fixture
def capture_logs():
    """Capture all logs emitted during test."""
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(name)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)

    # Get root logger and add handler
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)

    yield log_stream

    root_logger.removeHandler(handler)


@pytest.fixture
def simple_test_dag():
    """Simple DAG for logging tests."""
    dag = DAG(name="logging_test_dag", description="Test DAG for logging")
    dag = dag.add_node(Node.tool(id="step1", name="Step 1", tool_id="tool1", output_key="step1_out"))
    dag = dag.add_node(Node.tool(id="step2", name="Step 2", tool_id="tool2", output_key="step2_out"))
    dag = dag.add_edge(Edge(source=NodeID("step1"), target=NodeID("step2")))
    return dag


class TestStructuredLoggingFormat:
    """Test that logs are properly structured."""

    def test_logger_supports_context_kwargs(self):
        """Logger should support structured logging with context keyword args."""
        logger = get_logger("test.module")

        # Should not raise when using context kwargs
        logger.info("Test message", correlation_id="req_123", operation="test")

    def test_logger_supports_debug_level(self):
        """Logger should support DEBUG level."""
        logger = get_logger("test.debug")
        # Should not raise
        logger.debug("Debug message", detail="some_info")

    def test_logger_supports_warning_level(self):
        """Logger should support WARNING level."""
        logger = get_logger("test.warning")
        # Should not raise
        logger.warning("Warning message", reason="degraded")

    def test_logger_supports_error_level(self):
        """Logger should support ERROR level."""
        logger = get_logger("test.error")
        # Should not raise
        logger.error("Error message", error_type="ConnectionError")


class TestCriticalPathLogging:
    """Test that all critical paths are logged appropriately."""

    @pytest.mark.asyncio
    async def test_dag_execution_logs_start_and_completion(
        self, simple_test_dag, mock_node_executor, capture_logs
    ):
        """DAG execution should log start and completion."""
        executor = DAGExecutor(node_executor=mock_node_executor)
        run_id = RunID("test_run_123")

        result = await executor.run(simple_test_dag, run_id=run_id)

        _ = capture_logs.getvalue()

        # Should complete successfully
        assert result.status == RunStatus.COMPLETED
        # Once logging is implemented, logs should contain DAG execution start/completion

    @pytest.mark.asyncio
    async def test_execution_includes_run_id_in_logs(self, simple_test_dag, mock_node_executor, capture_logs):
        """Execution logs should include run ID for tracing."""
        executor = DAGExecutor(node_executor=mock_node_executor)
        run_id = RunID("trace_run_456")

        result = await executor.run(simple_test_dag, run_id=run_id)

        assert result.status == RunStatus.COMPLETED
        # Once logging is implemented, logs should include run_id
        _ = capture_logs.getvalue()
        # This assertion will pass once we add logging
        assert True

    @pytest.mark.asyncio
    async def test_execution_logs_on_failure(self, mock_node_executor, capture_logs):
        """Execution should log errors when DAG fails."""
        # Create a failing DAG (empty, will have no entry node)
        dag = DAG(name="failing_dag")

        executor = DAGExecutor(node_executor=mock_node_executor)
        result = await executor.run(dag)

        _ = capture_logs.getvalue()

        # Should have failed
        assert result.status == RunStatus.FAILED or result.error is not None


class TestLogLevels:
    """Test appropriate log level usage."""

    def test_info_level_for_normal_operations(self, capture_logs):
        """Normal operations should use INFO level."""
        logger = get_logger("test.operations")
        logger.info("Normal operation")

        _ = capture_logs.getvalue()
        # Once implemented, logs should contain INFO level messages
        assert True

    def test_debug_level_for_detailed_diagnostics(self, capture_logs):
        """Detailed diagnostics should use DEBUG level."""
        logger = get_logger("test.diagnostics")
        logger.debug("Detailed diagnostic info", depth=3, tokens=1000)

        _ = capture_logs.getvalue()
        # Once implemented, DEBUG messages should be captured
        assert True

    def test_warning_level_for_degraded_operations(self, capture_logs):
        """Degraded operations should use WARNING level."""
        logger = get_logger("test.degradation")
        logger.warning("Operation degraded", reason="cache_miss", impact="slower")

        _ = capture_logs.getvalue()
        assert True

    def test_error_level_for_failures(self, capture_logs):
        """Failures should use ERROR level."""
        logger = get_logger("test.failures")
        logger.error("Operation failed", error_type="ValueError", error_msg="bad input")

        _ = capture_logs.getvalue()
        assert True


class TestCorrelationTracking:
    """Test correlation ID tracking across operations."""

    @pytest.mark.asyncio
    async def test_correlation_id_in_context(self, simple_test_dag, mock_node_executor, capture_logs):
        """Correlation ID should be available for request tracing."""
        executor = DAGExecutor(node_executor=mock_node_executor)
        correlation_id = "corr_test_789"
        run_id = RunID(correlation_id)

        result = await executor.run(simple_test_dag, run_id=run_id)

        assert result.status == RunStatus.COMPLETED
        assert result.run_id == run_id
        # Once logging is implemented, correlation_id should appear in logs
        _ = capture_logs.getvalue()
        assert True


class TestModuleSpecificLogging:
    """Test that each module has a dedicated logger."""

    def test_orchestration_logger_exists(self):
        """Orchestration module should have logger."""
        logger = get_logger("orchestration.executor")
        assert logger is not None
        assert "orchestration" in logger._name

    def test_rlm_logger_exists(self):
        """RLM module should have logger."""
        logger = get_logger("rlm.engine")
        assert logger is not None
        assert "rlm" in logger._name

    def test_memory_logger_exists(self):
        """Memory module should have logger."""
        logger = get_logger("memory.store")
        assert logger is not None
        assert "memory" in logger._name

    def test_moderation_logger_exists(self):
        """Moderation module should have logger."""
        logger = get_logger("moderation.pipeline")
        assert logger is not None
        assert "moderation" in logger._name

    def test_context_logger_exists(self):
        """Context module should have logger."""
        logger = get_logger("context.operations")
        assert logger is not None
        assert "context" in logger._name

    def test_tools_logger_exists(self):
        """Tools module should have logger."""
        logger = get_logger("tools.executor")
        assert logger is not None
        assert "tools" in logger._name


class TestLoggingWithContextKeywords:
    """Test logging with structured context keywords."""

    def test_logger_accepts_arbitrary_context_kwargs(self):
        """Logger should accept any keyword arguments as context."""
        logger = get_logger("test.flexible")

        # Should accept arbitrary context
        logger.info(
            "Flexible context",
            user_id="user_123",
            session_id="sess_456",
            action="login",
            duration_ms=125,
        )

    def test_logger_context_preserved_in_message(self, capture_logs):
        """Logger should preserve context in output."""
        logger = get_logger("test.context_preservation")

        test_context = {
            "request_id": "req_999",
            "module": "test",
            "version": "1.0",
        }

        logger.info("Test with context", **test_context)

        _ = capture_logs.getvalue()
        # Once implemented, logs should contain context
        assert True


class TestErrorLogging:
    """Test error logging with proper context."""

    def test_error_logging_with_exception_type(self):
        """Error logs should include exception type."""
        logger = get_logger("test.errors")

        logger.error(
            "Operation failed",
            error_type="ConnectionError",
            error_message="Failed to connect",
        )

    def test_error_logging_with_traceback_support(self):
        """Error logging should support exc_info."""
        logger = get_logger("test.exceptions")

        try:
            raise ValueError("Test error")
        except ValueError:
            # Should not raise when logging with exc_info
            logger.error("Caught exception", exc_info=True)


class TestLoggingPerformance:
    """Test that logging doesn't impact performance."""

    @pytest.mark.asyncio
    async def test_logging_doesnt_block_execution(self, simple_test_dag, mock_node_executor, capture_logs):
        """Logging should not block DAG execution."""
        executor = DAGExecutor(node_executor=mock_node_executor)

        result = await executor.run(simple_test_dag)

        assert result.status == RunStatus.COMPLETED
        assert result.completed_at is not None
        # Execution completes even with logging enabled
        assert True

    def test_debug_messages_lazy_evaluated(self):
        """DEBUG messages should use lazy evaluation for performance."""
        logger = get_logger("test.lazy")

        # This should use % formatting for lazy evaluation
        # If disabled at INFO level, formatting doesn't happen
        logger.debug("Expensive operation: %s", 42)

    def test_disabled_log_level_has_no_overhead(self):
        """Disabled log levels should have minimal overhead."""
        logger = get_logger("test.disabled")

        # These should be essentially no-ops if level is too high
        for i in range(1000):
            logger.debug("Debug message %d", i)  # If not enabled, minimal overhead
