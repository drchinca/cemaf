"""Tests for run logger."""

import pytest

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch
from cemaf.observability.run_logger import (
    InMemoryRunLogger,
    LLMCall,
    NoOpRunLogger,
    RunRecord,
    ToolCall,
)


class TestToolCall:
    """Tests for ToolCall."""

    def test_create_tool_call(self) -> None:
        """Test creating a tool call record."""
        call = ToolCall(
            tool_id="web_search",
            input={"query": "test"},
            output={"results": []},
            duration_ms=150.5,
            correlation_id="corr-123",
        )

        assert call.tool_id == "web_search"
        assert call.input == {"query": "test"}
        assert call.output == {"results": []}
        assert call.duration_ms == 150.5
        assert call.success is True
        assert call.id.startswith("call_")

    def test_failed_tool_call(self) -> None:
        """Test creating a failed tool call."""
        call = ToolCall(
            tool_id="failing_tool",
            input={},
            output={},
            success=False,
            error="Tool execution failed",
        )

        assert call.success is False
        assert call.error == "Tool execution failed"

    def test_serialization(self) -> None:
        """Test tool call serialization."""
        call = ToolCall(
            tool_id="test_tool",
            input={"a": 1},
            output={"b": 2},
        )

        data = call.to_dict()
        restored = ToolCall.from_dict(data)

        assert restored.tool_id == call.tool_id
        assert restored.input == call.input
        assert restored.output == call.output


class TestLLMCall:
    """Tests for LLMCall."""

    def test_create_llm_call(self) -> None:
        """Test creating an LLM call record."""
        call = LLMCall(
            model="gpt-4",
            input_messages=[{"role": "user", "content": "Hello"}],
            output="Hello! How can I help?",
            input_tokens=10,
            output_tokens=20,
            duration_ms=500.0,
        )

        assert call.model == "gpt-4"
        assert len(call.input_messages) == 1
        assert call.input_tokens == 10
        assert call.output_tokens == 20
        assert call.id.startswith("llm_")

    def test_serialization(self) -> None:
        """Test LLM call serialization."""
        call = LLMCall(
            model="claude-3",
            input_messages=[{"role": "user", "content": "Test"}],
            output="Response",
        )

        data = call.to_dict()
        restored = LLMCall.from_dict(data)

        assert restored.model == call.model
        assert restored.output == call.output


class TestRunRecord:
    """Tests for RunRecord."""

    def test_create_run_record(self) -> None:
        """Test creating a run record."""
        record = RunRecord(
            run_id="run-123",
            dag_name="test_dag",
        )

        assert record.run_id == "run-123"
        assert record.dag_name == "test_dag"
        assert record.success is True
        assert record.total_tool_calls == 0

    def test_record_with_calls(self) -> None:
        """Test record with tool and LLM calls."""
        record = RunRecord(run_id="run-123")
        record.tool_calls.append(ToolCall(tool_id="tool1", input={}, output={}))
        record.tool_calls.append(ToolCall(tool_id="tool2", input={}, output={}))
        record.llm_calls.append(
            LLMCall(
                model="gpt-4",
                input_messages=[],
                output="",
                input_tokens=100,
                output_tokens=50,
            )
        )

        assert record.total_tool_calls == 2
        assert record.total_llm_calls == 1
        assert record.total_tokens == 150

    def test_get_patch_log(self) -> None:
        """Test getting patches as PatchLog."""
        record = RunRecord(run_id="run-123")
        record.patches.append(ContextPatch.set("a", 1))
        record.patches.append(ContextPatch.set("b", 2))

        log = record.get_patch_log()

        assert len(log) == 2

    def test_serialization(self) -> None:
        """Test run record serialization."""
        ctx = Context(data={"initial": True})
        record = RunRecord(
            run_id="run-123",
            dag_name="test_dag",
            initial_context=ctx,
        )
        record.tool_calls.append(ToolCall(tool_id="tool1", input={}, output={}))

        data = record.to_dict()
        restored = RunRecord.from_dict(data)

        assert restored.run_id == record.run_id
        assert restored.dag_name == record.dag_name
        assert len(restored.tool_calls) == 1


class TestInMemoryRunLogger:
    """Tests for InMemoryRunLogger."""

    def test_basic_logging(self) -> None:
        """Test basic logging workflow."""
        logger = InMemoryRunLogger()

        # Start run
        initial_ctx = Context(data={"start": True})
        logger.start_run(
            run_id="run-123",
            dag_name="test_dag",
            initial_context=initial_ctx,
        )

        # Record tool call
        logger.record_tool_call(ToolCall(tool_id="tool1", input={"x": 1}, output={"y": 2}))

        # Record patch
        logger.record_patch(ContextPatch.set("result", 42))

        # End run
        final_ctx = Context(data={"result": 42})
        record = logger.end_run(final_context=final_ctx, success=True)

        assert record.run_id == "run-123"
        assert record.dag_name == "test_dag"
        assert record.total_tool_calls == 1
        assert record.total_patches == 1
        assert record.success is True
        assert record.completed_at is not None

    def test_get_current_record(self) -> None:
        """Test getting current record during run."""
        logger = InMemoryRunLogger()

        # No current record
        assert logger.get_current_record() is None

        # Start run
        logger.start_run(run_id="run-123")
        current = logger.get_current_record()
        assert current is not None
        assert current.run_id == "run-123"

        # End run
        logger.end_run()
        assert logger.get_current_record() is None

    def test_history(self) -> None:
        """Test run history."""
        logger = InMemoryRunLogger()

        # Run 1
        logger.start_run(run_id="run-1")
        logger.end_run()

        # Run 2
        logger.start_run(run_id="run-2")
        logger.end_run()

        history = logger.get_history()
        assert len(history) == 2
        assert history[0].run_id == "run-1"
        assert history[1].run_id == "run-2"

    def test_get_record_by_id(self) -> None:
        """Test getting specific record by ID."""
        logger = InMemoryRunLogger()

        logger.start_run(run_id="run-1")
        logger.end_run()

        logger.start_run(run_id="run-2")
        logger.end_run()

        record = logger.get_record("run-1")
        assert record is not None
        assert record.run_id == "run-1"

        not_found = logger.get_record("run-999")
        assert not_found is None

    def test_clear_history(self) -> None:
        """Test clearing history."""
        logger = InMemoryRunLogger()

        logger.start_run(run_id="run-1")
        logger.end_run()

        assert len(logger.get_history()) == 1

        logger.clear_history()
        assert len(logger.get_history()) == 0

    def test_failed_run(self) -> None:
        """Test recording a failed run."""
        logger = InMemoryRunLogger()

        logger.start_run(run_id="run-123")
        record = logger.end_run(success=False, error="Something went wrong")

        assert record.success is False
        assert record.error == "Something went wrong"

    def test_end_run_without_start_raises(self) -> None:
        """Test that ending run without start raises error."""
        logger = InMemoryRunLogger()

        with pytest.raises(RuntimeError):
            logger.end_run()


class TestNoOpRunLogger:
    """Tests for NoOpRunLogger."""

    def test_no_op_operations(self) -> None:
        """Test that no-op logger does nothing."""
        logger = NoOpRunLogger()

        # All operations should work without error
        logger.start_run(run_id="run-123")
        logger.record_tool_call(ToolCall(tool_id="tool1", input={}, output={}))
        logger.record_patch(ContextPatch.set("a", 1))
        record = logger.end_run()

        assert record.run_id == "noop"
        assert logger.get_current_record() is None
