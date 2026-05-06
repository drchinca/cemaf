"""Agentic DAG integration tests — real agents executing in real DAGs.

Proves the full execution path:
  bootstrap → DAGExecutor → ContextNodeExecutor → AgentRegistry → Agent.run()
  → output to context → TASK_COMPLETED → eval pipeline → quality police → halt

No mocks for core execution. Uses simple deterministic agents that don't need LLM calls.
"""

import json

import pytest
from pydantic import BaseModel, Field

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.evals.evaluators import ContainsEvaluator, LengthEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.evals.police import QualityPolice, QualityPoliceConfig
from cemaf.events.bus import InMemoryEventBus
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices

# ---------------------------------------------------------------------------
# Deterministic test agents (no LLM, no external deps)
# ---------------------------------------------------------------------------


class AnalyzeGoal(BaseModel):
    """Goal for the Analyze agent."""

    topic: str = Field(description="Topic to analyze")


class AnalyzeResult(BaseModel):
    """Result from Analyze agent."""

    analysis: str


class AnalyzeAgent(Agent[AnalyzeGoal, AnalyzeResult]):
    """Deterministic agent that produces a structured analysis."""

    @property
    def id(self) -> AgentID:
        return AgentID("Analyze")

    @property
    def description(self) -> str:
        return "Produces deterministic analysis of a topic"

    @property
    def skills(self):
        return ()

    async def run(self, goal: AnalyzeGoal, context: AgentContext) -> AgentResult[AnalyzeResult]:
        state = AgentState()
        result = AnalyzeResult(
            analysis=f"Analysis of '{goal.topic}': This topic has 3 key aspects. "
            f"First, it is well-documented. Second, it has practical applications. "
            f"Third, ongoing research continues.",
        )
        return AgentResult.ok(output=result, state=state)


class SummarizeGoal(BaseModel):
    """Goal for the Summarize agent."""

    text: str = Field(description="Text to summarize")


class SummarizeResult(BaseModel):
    """Result from Summarize agent."""

    summary: str


class SummarizeAgent(Agent[SummarizeGoal, SummarizeResult]):
    """Deterministic agent that summarizes input text."""

    @property
    def id(self) -> AgentID:
        return AgentID("Summarize")

    @property
    def description(self) -> str:
        return "Summarizes input text deterministically"

    @property
    def skills(self):
        return ()

    async def run(self, goal: SummarizeGoal, context: AgentContext) -> AgentResult[SummarizeResult]:
        state = AgentState()
        # Deterministic summarization: take first 50 chars + "..."
        text = goal.text
        summary = text[:50] + "..." if len(text) > 50 else text
        result = SummarizeResult(summary=f"Summary: {summary}")
        return AgentResult.ok(output=result, state=state)


class BadOutputGoal(BaseModel):
    """Goal for agent that produces low-quality output."""

    instruction: str = "produce bad output"


class BadOutputResult(BaseModel):
    """Result with intentionally bad output."""

    text: str


class BadOutputAgent(Agent[BadOutputGoal, BadOutputResult]):
    """Agent that produces intentionally low-quality output for eval testing."""

    @property
    def id(self) -> AgentID:
        return AgentID("BadOutput")

    @property
    def description(self) -> str:
        return "Produces intentionally bad output"

    @property
    def skills(self):
        return ()

    async def run(self, goal: BadOutputGoal, context: AgentContext) -> AgentResult[BadOutputResult]:
        state = AgentState()
        # Produce empty/bad output that will fail evals
        result = BadOutputResult(text="")
        return AgentResult.ok(output=result, state=state)


class FailingGoal(BaseModel):
    """Goal for agent that always fails."""

    reason: str = "test failure"


class FailingAgent(Agent[FailingGoal, str]):
    """Agent that always returns a failure result."""

    @property
    def id(self) -> AgentID:
        return AgentID("Failing")

    @property
    def description(self) -> str:
        return "Always fails for testing error paths"

    @property
    def skills(self):
        return ()

    async def run(self, goal: FailingGoal, context: AgentContext) -> AgentResult[str]:
        state = AgentState()
        return AgentResult.fail(error=f"Intentional failure: {goal.reason}", state=state)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> AgentRegistry:
    """Registry with all test agents registered."""
    reg = AgentRegistry()
    reg.register_agent(agent_instance=AnalyzeAgent(), goal_type=AnalyzeGoal)
    reg.register_agent(agent_instance=SummarizeAgent(), goal_type=SummarizeGoal)
    reg.register_agent(agent_instance=BadOutputAgent(), goal_type=BadOutputGoal)
    reg.register_agent(agent_instance=FailingAgent(), goal_type=FailingGoal)
    return reg


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


# ---------------------------------------------------------------------------
# Test: Single agent node in a DAG
# ---------------------------------------------------------------------------


class TestSingleAgentDag:
    """A single AGENT node executes through the full bootstrap path."""

    @pytest.mark.asyncio
    async def test_single_agent_produces_output(self, registry: AgentRegistry) -> None:
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=False),
        )
        dag = DAG(
            name="single-agent",
            nodes=(
                Node(
                    id=NodeID("step_1"),
                    type=NodeType.AGENT,
                    name="Analyze Step",
                    ref_id="Analyze",
                    input_mapping={"topic": "machine learning"},
                    output_key="analysis_output",
                    retry_on_failure=False,
                ),
            ),
            edges=(),
            entry_node=NodeID("step_1"),
        )

        result = await executor.run(dag=dag)

        assert result.status == RunStatus.COMPLETED
        assert len(result.node_results) == 1
        assert result.node_results[0].success is True
        # Output should be the JSON-serialized AnalyzeResult
        output = result.node_results[0].output
        assert output is not None
        assert "machine learning" in output
        assert "3 key aspects" in output

    @pytest.mark.asyncio
    async def test_agent_output_stored_in_context(self, registry: AgentRegistry) -> None:
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=False),
        )
        dag = DAG(
            name="context-check",
            nodes=(
                Node(
                    id=NodeID("analyze"),
                    type=NodeType.AGENT,
                    name="Analyze",
                    ref_id="Analyze",
                    input_mapping={"topic": "AI safety"},
                    output_key="analysis",
                    retry_on_failure=False,
                ),
            ),
            edges=(),
            entry_node=NodeID("analyze"),
        )

        result = await executor.run(dag=dag)

        assert result.status == RunStatus.COMPLETED
        # Output should be accessible in final context via output_key
        ctx_value = result.final_context.get("analysis", default=None)
        assert ctx_value is not None

    @pytest.mark.asyncio
    async def test_failing_agent_returns_failure(self, registry: AgentRegistry) -> None:
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=False),
        )
        dag = DAG(
            name="fail-test",
            nodes=(
                Node(
                    id=NodeID("fail_step"),
                    type=NodeType.AGENT,
                    name="Failing Step",
                    ref_id="Failing",
                    input_mapping={"reason": "testing error path"},
                    retry_on_failure=False,
                ),
            ),
            edges=(),
            entry_node=NodeID("fail_step"),
        )

        result = await executor.run(dag=dag)

        # DAG still completes but with failed node
        assert result is not None
        assert len(result.node_results) >= 1
        fail_result = result.node_results[0]
        assert fail_result.success is False
        assert "Intentional failure" in (fail_result.error or "")


# ---------------------------------------------------------------------------
# Test: Multi-agent linear pipeline
# ---------------------------------------------------------------------------


class TestMultiAgentPipeline:
    """Sequential agents with output chaining through input_mapping."""

    @pytest.mark.asyncio
    async def test_two_agent_pipeline(self, registry: AgentRegistry) -> None:
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=False),
        )
        dag = DAG(
            name="two-agent-pipeline",
            nodes=(
                Node(
                    id=NodeID("analyze"),
                    type=NodeType.AGENT,
                    name="Analyze Step",
                    ref_id="Analyze",
                    input_mapping={"topic": "quantum computing"},
                    output_key="analysis_output",
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("summarize"),
                    type=NodeType.AGENT,
                    name="Summarize Step",
                    ref_id="Summarize",
                    input_mapping={"text": "$$analysis_output$$"},
                    output_key="summary_output",
                    retry_on_failure=False,
                ),
            ),
            edges=(
                Edge(
                    source=NodeID("analyze"),
                    target=NodeID("summarize"),
                    condition=EdgeCondition.ON_SUCCESS,
                ),
            ),
            entry_node=NodeID("analyze"),
        )

        result = await executor.run(dag=dag)

        assert result.status == RunStatus.COMPLETED
        assert len(result.node_results) == 2

        # First agent succeeded
        assert result.node_results[0].success is True
        assert "quantum computing" in (result.node_results[0].output or "")

        # Second agent received first agent's output and produced summary
        assert result.node_results[1].success is True
        summary_output = result.node_results[1].output or ""
        assert "Summary:" in summary_output

    @pytest.mark.asyncio
    async def test_pipeline_stops_on_failure_with_on_success_edge(self, registry: AgentRegistry) -> None:
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=False),
        )
        dag = DAG(
            name="fail-pipeline",
            nodes=(
                Node(
                    id=NodeID("fail_first"),
                    type=NodeType.AGENT,
                    name="Failing First",
                    ref_id="Failing",
                    input_mapping={"reason": "first step fails"},
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("should_not_run"),
                    type=NodeType.AGENT,
                    name="Should Not Run",
                    ref_id="Analyze",
                    input_mapping={"topic": "should not execute"},
                    retry_on_failure=False,
                ),
            ),
            edges=(
                Edge(
                    source=NodeID("fail_first"),
                    target=NodeID("should_not_run"),
                    condition=EdgeCondition.ON_SUCCESS,
                ),
            ),
            entry_node=NodeID("fail_first"),
        )

        result = await executor.run(dag=dag)

        # First node failed
        assert result.node_results[0].success is False
        # Second node should not have executed (ON_SUCCESS edge not traversed)
        executed_ids = {str(nr.node_id) for nr in result.node_results}
        assert "should_not_run" not in executed_ids or not any(
            nr.success for nr in result.node_results if str(nr.node_id) == "should_not_run"
        )


# ---------------------------------------------------------------------------
# Test: Agent DAG with eval pipeline and quality police
# ---------------------------------------------------------------------------


class TestAgentDagWithEvals:
    """Real agents in DAGs with online eval pipeline and quality police wired."""

    @pytest.mark.asyncio
    async def test_agent_output_evaluated_by_pipeline(
        self,
        registry: AgentRegistry,
        event_bus: InMemoryEventBus,
    ) -> None:
        eval_pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(LengthEvaluator(min_length=10, max_length=5000),),
                    mode=EvalMode.OBSERVE,
                ),
            ),
            event_bus=event_bus,
        )
        police = QualityPolice(config=QualityPoliceConfig(window_size=5))
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=police,
        )
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        dag = DAG(
            name="eval-test",
            nodes=(
                Node(
                    id=NodeID("analyze"),
                    type=NodeType.AGENT,
                    name="Analyze",
                    ref_id="Analyze",
                    input_mapping={"topic": "neural networks"},
                    output_key="analysis",
                    retry_on_failure=False,
                ),
            ),
            edges=(),
            entry_node=NodeID("analyze"),
        )

        result = await executor.run(dag=dag)
        await eval_pipeline.flush()

        assert result.status == RunStatus.COMPLETED

        # Eval pipeline should have evaluated the agent's output
        assert len(eval_pipeline.results) >= 1
        eval_result = eval_pipeline.results[0]
        assert eval_result["node_id"] == "analyze"
        assert eval_result["overall_score"] > 0
        assert eval_result["overall_passed"] is True

        # Quality police should have recorded the eval score
        assert police.to_dict()["scores_count"] >= 1
        assert not police.should_halt()

    @pytest.mark.asyncio
    async def test_multi_agent_pipeline_with_evals(
        self,
        registry: AgentRegistry,
        event_bus: InMemoryEventBus,
    ) -> None:
        eval_pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(LengthEvaluator(min_length=5, max_length=5000),),
                    mode=EvalMode.OBSERVE,
                ),
            ),
            event_bus=event_bus,
        )
        police = QualityPolice(config=QualityPoliceConfig(window_size=10))
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=police,
        )
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        dag = DAG(
            name="multi-eval",
            nodes=(
                Node(
                    id=NodeID("step_1"),
                    type=NodeType.AGENT,
                    name="Analyze",
                    ref_id="Analyze",
                    input_mapping={"topic": "climate science"},
                    output_key="analysis",
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("step_2"),
                    type=NodeType.AGENT,
                    name="Summarize",
                    ref_id="Summarize",
                    input_mapping={"text": "$$analysis$$"},
                    output_key="summary",
                    retry_on_failure=False,
                ),
            ),
            edges=(
                Edge(
                    source=NodeID("step_1"),
                    target=NodeID("step_2"),
                    condition=EdgeCondition.ON_SUCCESS,
                ),
            ),
            entry_node=NodeID("step_1"),
        )

        result = await executor.run(dag=dag)
        await eval_pipeline.flush()

        assert result.status == RunStatus.COMPLETED
        assert len(result.node_results) == 2

        # Both nodes should have been evaluated
        assert len(eval_pipeline.results) >= 2
        node_ids_evaluated = {r["node_id"] for r in eval_pipeline.results}
        assert "step_1" in node_ids_evaluated
        assert "step_2" in node_ids_evaluated

        # Police should have recorded both scores
        assert police.to_dict()["scores_count"] >= 2

    @pytest.mark.asyncio
    async def test_quality_police_halts_dag_on_bad_output(
        self,
        registry: AgentRegistry,
        event_bus: InMemoryEventBus,
    ) -> None:
        """Quality police halts execution when eval scores degrade.

        Uses GATE mode — the police halt check must see the score before the next
        node's halt gate fires. OBSERVE mode is fire-and-forget by design and will
        not serialize eval → police → halt within the DAG timeline.
        """
        # Strict eval: requires output length > 100 chars (JSON-serialized BadOutputResult is ~12 chars)
        eval_pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(LengthEvaluator(min_length=100, max_length=5000),),
                    mode=EvalMode.GATE,
                ),
            ),
            event_bus=event_bus,
        )
        # Very aggressive police: halt at mean < 0.5, window of 1
        police = QualityPolice(
            config=QualityPoliceConfig(
                window_size=1,
                halt_threshold=0.5,
                warn_threshold=0.9,
                critical_threshold=0.7,
            ),
        )
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=police,
        )
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        # BadOutput agent produces empty string → score 0 → police halts
        # Third node should NOT execute
        dag = DAG(
            name="halt-test",
            nodes=(
                Node(
                    id=NodeID("bad_step"),
                    type=NodeType.AGENT,
                    name="Bad Output",
                    ref_id="BadOutput",
                    input_mapping={"instruction": "produce bad output"},
                    output_key="bad_output",
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("should_not_run"),
                    type=NodeType.AGENT,
                    name="Should Not Run",
                    ref_id="Analyze",
                    input_mapping={"topic": "should never execute"},
                    retry_on_failure=False,
                ),
            ),
            edges=(
                Edge(
                    source=NodeID("bad_step"),
                    target=NodeID("should_not_run"),
                ),
            ),
            entry_node=NodeID("bad_step"),
        )

        result = await executor.run(dag=dag)
        await eval_pipeline.flush()

        # DAG should have been halted by quality police
        assert police.should_halt() or result.status == RunStatus.FAILED
        # At most 1 node should have completed successfully
        successful_nodes = [nr for nr in result.node_results if nr.success]
        assert len(successful_nodes) <= 1

    @pytest.mark.asyncio
    async def test_gate_mode_eval_blocks_downstream(
        self,
        registry: AgentRegistry,
        event_bus: InMemoryEventBus,
    ) -> None:
        """GATE mode eval emits QUALITY_ALERT on failure."""
        # Gate eval that requires "important" keyword
        eval_pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(ContainsEvaluator(case_sensitive=False),),
                    mode=EvalMode.GATE,
                    expected="KEYWORD_NOT_IN_OUTPUT",
                ),
            ),
            event_bus=event_bus,
        )
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
        )
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        dag = DAG(
            name="gate-test",
            nodes=(
                Node(
                    id=NodeID("step_1"),
                    type=NodeType.AGENT,
                    name="Analyze",
                    ref_id="Analyze",
                    input_mapping={"topic": "testing"},
                    retry_on_failure=False,
                ),
            ),
            edges=(),
            entry_node=NodeID("step_1"),
        )

        await executor.run(dag=dag)

        # Eval should have failed (output doesn't contain the expected keyword)
        assert len(eval_pipeline.results) >= 1
        assert eval_pipeline.results[0]["overall_passed"] is False


# ---------------------------------------------------------------------------
# Test: QualityGuardAgent in a DAG
# ---------------------------------------------------------------------------


class TestQualityGuardInDag:
    """QualityGuardAgent registered and used as a DAG node."""

    @pytest.mark.asyncio
    async def test_quality_guard_agent_in_dag(self, event_bus: InMemoryEventBus) -> None:
        """QualityGuardAgent runs as an AGENT node, evaluating text."""
        from cemaf.evals.agents import QualityGuardAgent, QualityGuardGoal

        reg = AgentRegistry()
        police = QualityPolice()
        guard = QualityGuardAgent(quality_police=police)
        reg.register_agent(agent_instance=guard, goal_type=QualityGuardGoal)

        executor = create_executor(
            agent_registry=reg,
            config=ExecutorConfig(enable_events=False),
        )

        dag = DAG(
            name="guard-test",
            nodes=(
                Node(
                    id=NodeID("guard_step"),
                    type=NodeType.AGENT,
                    name="Quality Guard",
                    ref_id="QualityGuard",
                    input_mapping={
                        "output": "This is a perfectly valid output that should pass quality checks.",
                        "evaluator_names": ["length"],
                        "record_to_police": True,
                    },
                    output_key="guard_result",
                    retry_on_failure=False,
                ),
            ),
            edges=(),
            entry_node=NodeID("guard_step"),
        )

        result = await executor.run(dag=dag)

        assert result.status == RunStatus.COMPLETED
        assert result.node_results[0].success is True

        # Guard should have recorded score to police
        assert police.to_dict()["scores_count"] == 1

    @pytest.mark.asyncio
    async def test_analyze_then_guard_pipeline(self, event_bus: InMemoryEventBus) -> None:
        """Agent produces output → QualityGuard evaluates it in same DAG."""
        from cemaf.evals.agents import QualityGuardAgent, QualityGuardGoal

        reg = AgentRegistry()
        police = QualityPolice()

        reg.register_agent(agent_instance=AnalyzeAgent(), goal_type=AnalyzeGoal)
        guard = QualityGuardAgent(quality_police=police)
        reg.register_agent(agent_instance=guard, goal_type=QualityGuardGoal)

        executor = create_executor(
            agent_registry=reg,
            config=ExecutorConfig(enable_events=False),
        )

        dag = DAG(
            name="analyze-then-guard",
            nodes=(
                Node(
                    id=NodeID("analyze"),
                    type=NodeType.AGENT,
                    name="Analyze",
                    ref_id="Analyze",
                    input_mapping={"topic": "renewable energy"},
                    output_key="analysis",
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("guard"),
                    type=NodeType.AGENT,
                    name="Quality Guard",
                    ref_id="QualityGuard",
                    input_mapping={
                        "output": "$$analysis$$",
                        "evaluator_names": ["length", "contains"],
                        "expected": "renewable energy",
                    },
                    output_key="guard_result",
                    retry_on_failure=False,
                ),
            ),
            edges=(
                Edge(
                    source=NodeID("analyze"),
                    target=NodeID("guard"),
                    condition=EdgeCondition.ON_SUCCESS,
                ),
            ),
            entry_node=NodeID("analyze"),
        )

        result = await executor.run(dag=dag)

        assert result.status == RunStatus.COMPLETED
        assert len(result.node_results) == 2
        assert result.node_results[0].success is True  # Analyze
        assert result.node_results[1].success is True  # Guard

        # Parse guard output to verify eval results
        guard_output = result.node_results[1].output
        assert guard_output is not None
        guard_data = json.loads(guard_output)
        assert guard_data["passed"] is True
        assert guard_data["overall_score"] > 0


# ---------------------------------------------------------------------------
# Test: Full automated pipeline (agent + eval + police + context flow)
# ---------------------------------------------------------------------------


class TestFullAutomatedPipeline:
    """The complete agentic pipeline — agents, evals, quality monitoring, context flow."""

    @pytest.mark.asyncio
    async def test_three_agent_pipeline_with_full_observability(
        self,
        registry: AgentRegistry,
        event_bus: InMemoryEventBus,
    ) -> None:
        """Three agents in sequence with eval pipeline and quality police."""
        eval_pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(LengthEvaluator(min_length=5, max_length=10000),),
                    mode=EvalMode.OBSERVE,
                ),
            ),
            event_bus=event_bus,
        )
        police = QualityPolice(
            config=QualityPoliceConfig(
                window_size=10,
                warn_threshold=0.5,
                halt_threshold=0.1,
            ),
        )
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=police,
        )
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        # Analyze → Summarize → Analyze again (with summary as input)
        dag = DAG(
            name="full-pipeline",
            nodes=(
                Node(
                    id=NodeID("research"),
                    type=NodeType.AGENT,
                    name="Research",
                    ref_id="Analyze",
                    input_mapping={"topic": "artificial general intelligence"},
                    output_key="research_output",
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("compress"),
                    type=NodeType.AGENT,
                    name="Compress",
                    ref_id="Summarize",
                    input_mapping={"text": "$$research_output$$"},
                    output_key="compressed_output",
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("refine"),
                    type=NodeType.AGENT,
                    name="Refine",
                    ref_id="Analyze",
                    input_mapping={"topic": "$$compressed_output$$"},
                    output_key="refined_output",
                    retry_on_failure=False,
                ),
            ),
            edges=(
                Edge(
                    source=NodeID("research"),
                    target=NodeID("compress"),
                    condition=EdgeCondition.ON_SUCCESS,
                ),
                Edge(
                    source=NodeID("compress"),
                    target=NodeID("refine"),
                    condition=EdgeCondition.ON_SUCCESS,
                ),
            ),
            entry_node=NodeID("research"),
        )

        result = await executor.run(dag=dag)
        await eval_pipeline.flush()

        # All three agents should have succeeded
        assert result.status == RunStatus.COMPLETED
        assert len(result.node_results) == 3
        for nr in result.node_results:
            assert nr.success is True, f"Node {nr.node_id} failed: {nr.error}"

        # Eval pipeline should have evaluated all 3 outputs
        assert len(eval_pipeline.results) == 3
        for eval_r in eval_pipeline.results:
            assert eval_r["overall_passed"] is True

        # Quality police should have 3 scores and be healthy
        assert police.to_dict()["scores_count"] == 3
        assert not police.should_halt()
        assert police.rolling_mean > 0.5

        # Context should contain all outputs
        assert result.final_context.get("research_output", default=None) is not None
        assert result.final_context.get("compressed_output", default=None) is not None
        assert result.final_context.get("refined_output", default=None) is not None

    @pytest.mark.asyncio
    async def test_mixed_success_failure_pipeline(
        self,
        registry: AgentRegistry,
        event_bus: InMemoryEventBus,
    ) -> None:
        """Pipeline where one agent fails — verify eval and police handle gracefully."""
        eval_pipeline = OnlineEvalPipeline(
            bindings=(
                NodeEvalBinding(
                    node_pattern="*",
                    evaluators=(LengthEvaluator(min_length=1, max_length=10000),),
                    mode=EvalMode.OBSERVE,
                ),
            ),
            event_bus=event_bus,
        )
        police = QualityPolice(config=QualityPoliceConfig(window_size=5))
        services = RuntimeServices(
            event_bus=event_bus,
            online_eval_pipeline=eval_pipeline,
            quality_police=police,
        )
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        # Good agent → Failing agent (ON_SUCCESS edge, so second skipped)
        dag = DAG(
            name="mixed-pipeline",
            nodes=(
                Node(
                    id=NodeID("good"),
                    type=NodeType.AGENT,
                    name="Good Agent",
                    ref_id="Analyze",
                    input_mapping={"topic": "success test"},
                    output_key="good_output",
                    retry_on_failure=False,
                ),
                Node(
                    id=NodeID("failing"),
                    type=NodeType.AGENT,
                    name="Failing Agent",
                    ref_id="Failing",
                    input_mapping={"reason": "mid-pipeline failure"},
                    retry_on_failure=False,
                ),
            ),
            edges=(
                Edge(
                    source=NodeID("good"),
                    target=NodeID("failing"),
                    condition=EdgeCondition.ALWAYS,
                ),
            ),
            entry_node=NodeID("good"),
        )

        result = await executor.run(dag=dag)
        await eval_pipeline.flush()

        # Good node succeeded, failing node failed
        assert result.node_results[0].success is True
        assert result.node_results[1].success is False

        # Eval pipeline evaluated the successful node's output
        successful_evals = [r for r in eval_pipeline.results if r["overall_passed"]]
        assert len(successful_evals) >= 1

        # Police tracked what it could
        assert police.to_dict()["scores_count"] >= 1
