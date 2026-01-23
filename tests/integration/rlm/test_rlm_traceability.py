"""
Integration tests for RLM with full traceability.

Tests RLM + Context patches + RunLogger for complete provenance tracking.
"""

import pytest

from cemaf.context import Context, ContextPatch, PatchSource
from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.llm.mock import MockLLMClient
from cemaf.observability.run_logger import InMemoryRunLogger, ToolCall
from cemaf.rlm import create_rlm_tool


class TestRLMTraceability:
    """Integration tests for RLM traceability."""

    @pytest.fixture
    def estimator(self) -> SimpleTokenEstimator:
        """Create token estimator."""
        return SimpleTokenEstimator(chars_per_token=4.0)

    @pytest.fixture
    def llm_client(self) -> MockLLMClient:
        """Create mock LLM client."""
        return MockLLMClient(responses=["Found 5 mentions", "Summary of key points"])

    @pytest.fixture
    def rlm_tool(self, llm_client: MockLLMClient, estimator: SimpleTokenEstimator) -> object:
        """Create RLM tool."""
        return create_rlm_tool(
            llm_client=llm_client,
            token_estimator=estimator,
            chunk_size=500,
            max_depth=3,
            max_tokens=4000,
        )

    @pytest.fixture
    def run_logger(self) -> InMemoryRunLogger:
        """Create run logger."""
        return InMemoryRunLogger()

    @pytest.mark.asyncio
    async def test_rlm_creates_context_patch(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
        estimator: SimpleTokenEstimator,
    ) -> None:
        """Test that RLM results create proper context patches."""
        # Start run
        initial_ctx = Context(data={"document": "Large document content"})
        run_logger.start_run(
            run_id="run-123",
            dag_name="document_analysis",
            initial_context=initial_ctx,
        )

        # Execute RLM query
        content = "\n\n".join([f"Section {i}: content" for i in range(20)])
        result = await rlm_tool.execute(
            instruction="Find all key points",
            content=content,
        )

        assert result.success is True

        # Create patch for RLM result
        patch = ContextPatch.set(
            path="analysis.summary",
            value=result.data,
            source=PatchSource.TOOL,
            source_id="rlm_query",
            reason="RLM query result for document analysis",
            correlation_id="run-123-agent-1-task-1",
        )

        # Apply patch and record
        new_ctx = initial_ctx.apply(patch)
        run_logger.record_patch(patch)

        # End run
        record = run_logger.end_run(final_context=new_ctx, success=True)

        # Verify patch was recorded
        assert record.total_patches == 1
        assert record.patches[0].path == "analysis.summary"
        assert record.patches[0].source == PatchSource.TOOL
        assert record.patches[0].source_id == "rlm_query"
        assert record.patches[0].correlation_id == "run-123-agent-1-task-1"

    @pytest.mark.asyncio
    async def test_rlm_tool_call_tracking(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
    ) -> None:
        """Test that RLM tool calls are tracked in RunLogger."""
        run_logger.start_run(run_id="run-123")

        # Execute RLM query
        content = "\n\n".join([f"Section {i}" for i in range(10)])
        result = await rlm_tool.execute(
            instruction="Analyze",
            content=content,
        )

        # Record tool call
        tool_call = ToolCall(
            tool_id="rlm_query",
            input={"instruction": "Analyze", "content": content[:50] + "..."},
            output=result.data or "",
            duration_ms=100.0,
            correlation_id="run-123-agent-1-task-1",
            success=result.success,
        )
        run_logger.record_tool_call(tool_call)

        record = run_logger.end_run(success=True)

        # Verify tool call was recorded
        assert record.total_tool_calls == 1
        assert record.tool_calls[0].tool_id == "rlm_query"
        assert record.tool_calls[0].correlation_id == "run-123-agent-1-task-1"
        assert record.tool_calls[0].success is True

    @pytest.mark.asyncio
    async def test_rlm_full_provenance_chain(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
        llm_client: MockLLMClient,
    ) -> None:
        """Test complete provenance chain: RLM → Patch → Context → RunLogger."""
        # Start run
        initial_ctx = Context(data={"document": "Large document"})
        run_logger.start_run(
            run_id="run-123",
            dag_name="analysis",
            initial_context=initial_ctx,
        )

        # Execute RLM
        content = "\n\n".join([f"Section {i}: important content" for i in range(30)])
        result = await rlm_tool.execute(
            instruction="Extract key findings",
            content=content,
        )

        # Create patch with full provenance
        patch = ContextPatch.set(
            path="analysis.key_findings",
            value=result.data,
            source=PatchSource.TOOL,
            source_id="rlm_query",
            reason="RLM analysis of document sections",
            correlation_id="run-123-agent-1-task-1",
        )

        # Apply patch
        new_ctx = initial_ctx.apply(patch)

        # Record everything
        run_logger.record_patch(patch)
        run_logger.record_tool_call(
            ToolCall(
                tool_id="rlm_query",
                input={"instruction": "Extract key findings"},
                output=result.data or "",
                correlation_id="run-123-agent-1-task-1",
            )
        )

        # Record LLM calls (simulated from RLM metadata)
        for _ in range(result.metadata.get("llm_calls_made", 0)):
            from cemaf.observability.run_logger import LLMCall

            run_logger.record_llm_call(
                LLMCall(
                    model="mock",
                    input_messages=[{"role": "user", "content": "..."}],
                    output="Response",
                    input_tokens=100,
                    output_tokens=50,
                    correlation_id="run-123-agent-1-task-1",
                )
            )

        # End run
        record = run_logger.end_run(final_context=new_ctx, success=True)

        # Verify complete provenance
        assert record.total_patches == 1
        assert record.total_tool_calls == 1
        assert record.total_llm_calls == result.metadata.get("llm_calls_made", 0)

        # Verify patch provenance
        patch = record.patches[0]
        assert patch.path == "analysis.key_findings"
        assert patch.source == PatchSource.TOOL
        assert patch.source_id == "rlm_query"
        assert patch.correlation_id == "run-123-agent-1-task-1"
        assert "RLM analysis" in patch.reason

        # Verify correlation IDs link everything
        correlation_id = "run-123-agent-1-task-1"
        assert patch.correlation_id == correlation_id
        assert record.tool_calls[0].correlation_id == correlation_id
        assert all(call.correlation_id == correlation_id for call in record.llm_calls)

    @pytest.mark.asyncio
    async def test_rlm_patch_log_filtering(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
    ) -> None:
        """Test filtering patches by source for RLM operations."""
        run_logger.start_run(run_id="run-123")

        # Multiple operations
        content = "\n\n".join([f"Section {i}" for i in range(10)])

        # RLM query 1
        result1 = await rlm_tool.execute(instruction="Find X", content=content)
        patch1 = ContextPatch.set(
            path="results.query1",
            value=result1.data,
            source=PatchSource.TOOL,
            source_id="rlm_query",
            correlation_id="run-123-agent-1-task-1",
        )
        run_logger.record_patch(patch1)

        # RLM query 2
        result2 = await rlm_tool.execute(instruction="Find Y", content=content)
        patch2 = ContextPatch.set(
            path="results.query2",
            value=result2.data,
            source=PatchSource.TOOL,
            source_id="rlm_query",
            correlation_id="run-123-agent-1-task-2",
        )
        run_logger.record_patch(patch2)

        # Non-RLM patch
        patch3 = ContextPatch.set(
            path="other.data",
            value="value",
            source=PatchSource.AGENT,
            source_id="other_agent",
        )
        run_logger.record_patch(patch3)

        record = run_logger.end_run(success=True)

        # Filter by source
        patch_log = record.get_patch_log()
        rlm_patches = patch_log.filter_by_source(PatchSource.TOOL)
        rlm_patches_by_id = patch_log.filter_by_source_id("rlm_query")

        assert len(rlm_patches) == 2
        assert len(rlm_patches_by_id) == 2
        assert all(p.source_id == "rlm_query" for p in rlm_patches_by_id)

    @pytest.mark.asyncio
    async def test_rlm_correlation_id_tracing(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
    ) -> None:
        """Test tracing RLM operations via correlation IDs."""
        run_logger.start_run(run_id="run-123")

        correlation_id = "run-123-agent-1-task-1"

        # Execute RLM
        content = "\n\n".join([f"Section {i}" for i in range(10)])
        result = await rlm_tool.execute(instruction="Analyze", content=content)

        # Create patch with correlation ID
        patch = ContextPatch.set(
            path="analysis.result",
            value=result.data,
            source=PatchSource.TOOL,
            source_id="rlm_query",
            correlation_id=correlation_id,
        )
        run_logger.record_patch(patch)

        # Record tool call with same correlation ID
        run_logger.record_tool_call(
            ToolCall(
                tool_id="rlm_query",
                input={},
                output=result.data or "",
                correlation_id=correlation_id,
            )
        )

        record = run_logger.end_run(success=True)

        # Filter by correlation ID
        patch_log = record.get_patch_log()
        correlated_patches = patch_log.filter_by_correlation_id(correlation_id)

        assert len(correlated_patches) == 1
        assert correlated_patches[0].correlation_id == correlation_id

        # Verify tool calls match
        correlated_tool_calls = [call for call in record.tool_calls if call.correlation_id == correlation_id]
        assert len(correlated_tool_calls) == 1
