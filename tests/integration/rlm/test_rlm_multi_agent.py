"""
Integration tests for RLM in multi-agent scenarios.

Tests RLM usage across multiple agents with full traceability.
"""

import pytest

from cemaf.context import Context, ContextPatch, PatchSource
from cemaf.context.compiler import SimpleTokenEstimator
from cemaf.llm.mock import MockLLMClient
from cemaf.observability.run_logger import InMemoryRunLogger, LLMCall, ToolCall
from cemaf.rlm import create_rlm_tool


class TestRLMMultiAgent:
    """Integration tests for RLM in multi-agent scenarios."""

    @pytest.fixture
    def estimator(self) -> SimpleTokenEstimator:
        """Create token estimator."""
        return SimpleTokenEstimator(chars_per_token=4.0)

    @pytest.fixture
    def llm_client(self) -> MockLLMClient:
        """Create mock LLM client."""
        return MockLLMClient(
            responses=[
                "Found research findings",
                "Found methodology details",
                "Found conclusions",
                "Aggregated research summary",
            ]
        )

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
    async def test_multi_agent_rlm_usage(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
    ) -> None:
        """Test RLM usage by multiple agents in a single run."""
        # Start run
        initial_ctx = Context(data={"document": "Large research paper"})
        run_logger.start_run(
            run_id="run-123",
            dag_name="paper_analysis",
            initial_context=initial_ctx,
        )

        ctx = initial_ctx
        content = "\n\n".join([f"Section {i}: content" for i in range(20)])

        # Agent 1: Researcher
        agent1_correlation = "run-123-agent-researcher-task-1"
        result1 = await rlm_tool.execute(
            instruction="Extract research findings",
            content=content,
        )
        patch1 = ContextPatch.set(
            path="research.findings",
            value=result1.data,
            source=PatchSource.AGENT,
            source_id="researcher",
            reason="RLM analysis by researcher agent",
            correlation_id=agent1_correlation,
        )
        ctx = ctx.apply(patch1)
        run_logger.record_patch(patch1)
        run_logger.record_tool_call(
            ToolCall(
                tool_id="rlm_query",
                input={"instruction": "Extract research findings"},
                output=result1.data or "",
                correlation_id=agent1_correlation,
            )
        )

        # Agent 2: Analyst
        agent2_correlation = "run-123-agent-analyst-task-1"
        result2 = await rlm_tool.execute(
            instruction="Analyze methodology",
            content=content,
        )
        patch2 = ContextPatch.set(
            path="analysis.methodology",
            value=result2.data,
            source=PatchSource.AGENT,
            source_id="analyst",
            reason="RLM analysis by analyst agent",
            correlation_id=agent2_correlation,
        )
        ctx = ctx.apply(patch2)
        run_logger.record_patch(patch2)
        run_logger.record_tool_call(
            ToolCall(
                tool_id="rlm_query",
                input={"instruction": "Analyze methodology"},
                output=result2.data or "",
                correlation_id=agent2_correlation,
            )
        )

        # End run
        record = run_logger.end_run(final_context=ctx, success=True)

        # Verify both agents' operations
        assert record.total_patches == 2
        assert record.total_tool_calls == 2

        # Verify agent-specific patches
        researcher_patches = [p for p in record.patches if p.source_id == "researcher"]
        analyst_patches = [p for p in record.patches if p.source_id == "analyst"]

        assert len(researcher_patches) == 1
        assert len(analyst_patches) == 1
        assert researcher_patches[0].path == "research.findings"
        assert analyst_patches[0].path == "analysis.methodology"

    @pytest.mark.asyncio
    async def test_agent_token_usage_tracking(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
        llm_client: MockLLMClient,
    ) -> None:
        """Test tracking token usage per agent."""
        run_logger.start_run(run_id="run-123")

        content = "\n\n".join([f"Section {i}" for i in range(15)])

        # Agent 1 operations
        result1 = await rlm_tool.execute(instruction="Query 1", content=content)
        agent1_correlation = "run-123-agent-1-task-1"
        run_logger.record_tool_call(
            ToolCall(
                tool_id="rlm_query",
                input={},
                output=result1.data or "",
                correlation_id=agent1_correlation,
            )
        )
        # Simulate LLM calls
        for _unused in range(result1.metadata.get("llm_calls_made", 2)):
            run_logger.record_llm_call(
                LLMCall(
                    model="mock",
                    input_messages=[],
                    output="",
                    input_tokens=100,
                    output_tokens=50,
                    correlation_id=agent1_correlation,
                )
            )

        # Agent 2 operations
        result2 = await rlm_tool.execute(instruction="Query 2", content=content)
        agent2_correlation = "run-123-agent-2-task-1"
        run_logger.record_tool_call(
            ToolCall(
                tool_id="rlm_query",
                input={},
                output=result2.data or "",
                correlation_id=agent2_correlation,
            )
        )
        # Simulate LLM calls
        for _unused in range(result2.metadata.get("llm_calls_made", 2)):
            run_logger.record_llm_call(
                LLMCall(
                    model="mock",
                    input_messages=[],
                    output="",
                    input_tokens=150,
                    output_tokens=75,
                    correlation_id=agent2_correlation,
                )
            )

        record = run_logger.end_run(success=True)

        # Calculate token usage per agent
        agent_tokens = {}
        for llm_call in record.llm_calls:
            # Parse correlation_id: "run-123-agent-1-task-1"
            # Format: run-{run_id}-agent-{agent_num}-task-{task_num}
            parts = llm_call.correlation_id.split("-")
            if len(parts) >= 4 and parts[2] == "agent":
                # Extract agent number: "agent-1" -> "1"
                agent_id = f"agent-{parts[3]}"
            else:
                agent_id = "unknown"

            if agent_id not in agent_tokens:
                agent_tokens[agent_id] = {"input": 0, "output": 0}

            agent_tokens[agent_id]["input"] += llm_call.input_tokens
            agent_tokens[agent_id]["output"] += llm_call.output_tokens

        # Verify token tracking
        assert "agent-1" in agent_tokens
        assert "agent-2" in agent_tokens
        assert agent_tokens["agent-1"]["input"] > 0
        assert agent_tokens["agent-2"]["input"] > 0

    @pytest.mark.asyncio
    async def test_multi_agent_context_flow(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
    ) -> None:
        """Test context flow through multiple agents using RLM."""
        # Start run
        initial_ctx = Context(data={"document": "Large document"})
        run_logger.start_run(
            run_id="run-123",
            dag_name="multi_agent_analysis",
            initial_context=initial_ctx,
        )

        ctx = initial_ctx
        content = "\n\n".join([f"Section {i}" for i in range(20)])

        # Agent 1: Initial analysis
        result1 = await rlm_tool.execute(
            instruction="Initial analysis",
            content=content,
        )
        patch1 = ContextPatch.set(
            path="stage1.analysis",
            value=result1.data,
            source=PatchSource.AGENT,
            source_id="agent1",
            correlation_id="run-123-agent-1-task-1",
        )
        ctx = ctx.apply(patch1)
        run_logger.record_patch(patch1)

        # Agent 2: Uses Agent 1's results
        result2 = await rlm_tool.execute(
            instruction="Deep dive analysis",
            content=content,
        )
        patch2 = ContextPatch.set(
            path="stage2.deep_analysis",
            value=result2.data,
            source=PatchSource.AGENT,
            source_id="agent2",
            correlation_id="run-123-agent-2-task-1",
        )
        ctx = ctx.apply(patch2)
        run_logger.record_patch(patch2)

        # Agent 3: Final synthesis
        result3 = await rlm_tool.execute(
            instruction="Synthesize findings",
            content=content,
        )
        patch3 = ContextPatch.set(
            path="stage3.synthesis",
            value=result3.data,
            source=PatchSource.AGENT,
            source_id="agent3",
            correlation_id="run-123-agent-3-task-1",
        )
        ctx = ctx.apply(patch3)
        run_logger.record_patch(patch3)

        record = run_logger.end_run(final_context=ctx, success=True)

        # Verify context evolution
        assert record.total_patches == 3
        assert record.initial_context.get("document") == "Large document"
        assert record.final_context.get("stage1.analysis") is not None
        assert record.final_context.get("stage2.deep_analysis") is not None
        assert record.final_context.get("stage3.synthesis") is not None

        # Verify patch order
        assert record.patches[0].path == "stage1.analysis"
        assert record.patches[1].path == "stage2.deep_analysis"
        assert record.patches[2].path == "stage3.synthesis"

    @pytest.mark.asyncio
    async def test_replay_multi_agent_rlm_run(
        self,
        rlm_tool: object,
        run_logger: InMemoryRunLogger,
    ) -> None:
        """Test replaying a multi-agent run with RLM operations."""
        # Create a run
        initial_ctx = Context(data={"document": "Test document"})
        run_logger.start_run(
            run_id="run-123",
            dag_name="test",
            initial_context=initial_ctx,
        )

        ctx = initial_ctx
        content = "\n\n".join([f"Section {i}" for i in range(10)])

        # Agent operations
        result = await rlm_tool.execute(instruction="Analyze", content=content)
        patch = ContextPatch.set(
            path="result",
            value=result.data,
            source=PatchSource.AGENT,
            source_id="agent1",
            correlation_id="run-123-agent-1-task-1",
        )
        ctx = ctx.apply(patch)
        run_logger.record_patch(patch)

        record = run_logger.end_run(final_context=ctx, success=True)

        # Replay

        patch_log = record.get_patch_log()
        replayed_ctx = patch_log.replay(record.initial_context or Context())

        # Verify determinism
        assert replayed_ctx.get("result") == record.final_context.get("result")
        assert replayed_ctx.to_dict() == record.final_context.to_dict()
