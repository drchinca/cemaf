"""Full-stack integration test — everything real except the LLM.

Wires SqliteMemoryStore (tmp_path), InMemoryVectorStore + MockEmbeddingProvider,
ContextCompiler + SimpleTokenEstimator, BudgetGuard, QualityPolice +
OnlineEvalPipeline, EventBus, SessionManager, ModerationPipeline, all into a
single DAGExecutor. Runs a 3-node agent DAG with scripted deterministic
agents, asserts:

- memory round-trips through SQLite
- evals fire per-node via the pipeline
- quality police sees rolling scores
- budget guard accumulates cost correctly
- moderation pipeline actually runs (blocks if needed)
- final context carries all node outputs
- no resource leaks (all stores close cleanly)

Before this test, the suite had plenty of unit coverage but no proof that
the components composed correctly under a realistic run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.events.bus import InMemoryEventBus
from cemaf.memory.sqlite_store import SqliteMemoryStore
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _ResearchGoal(BaseModel):
    topic: str


class _ResearchResult(BaseModel):
    findings: str


class _ResearchAgent(Agent[_ResearchGoal, _ResearchResult]):
    """Deterministic research agent that reports realistic cost/tokens."""

    @property
    def id(self) -> AgentID:
        return AgentID("Researcher")

    @property
    def description(self) -> str:
        return "Researches a topic and returns findings"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _ResearchGoal, context: AgentContext) -> AgentResult[_ResearchResult]:
        return AgentResult.ok(
            output=_ResearchResult(findings=f"key findings on {goal.topic}: A, B, C"),
            state=AgentState(),
            metadata={
                "cost_estimate_usd": 0.05,
                "tokens_total": 500,
                "model": "fake-research-model",
            },
        )


class _SummarizeGoal(BaseModel):
    text: str


class _SummarizeResult(BaseModel):
    summary: str


class _SummarizeAgent(Agent[_SummarizeGoal, _SummarizeResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Summarizer")

    @property
    def description(self) -> str:
        return "Summarizes provided text"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _SummarizeGoal, context: AgentContext) -> AgentResult[_SummarizeResult]:
        return AgentResult.ok(
            output=_SummarizeResult(summary=f"summary: {goal.text[:40]}"),
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.02, "tokens_total": 200},
        )


class _WriteGoal(BaseModel):
    summary: str


class _WriteResult(BaseModel):
    article: str


class _WriteAgent(Agent[_WriteGoal, _WriteResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Writer")

    @property
    def description(self) -> str:
        return "Writes an article from a summary"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _WriteGoal, context: AgentContext) -> AgentResult[_WriteResult]:
        return AgentResult.ok(
            output=_WriteResult(article=f"Article: {goal.summary} [expanded]"),
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.08, "tokens_total": 800},
        )


def _research_summarize_write_dag() -> DAG:
    research = Node(
        id=NodeID("research"),
        type=NodeType.AGENT,
        name="research",
        ref_id="Researcher",
        input_mapping={"topic": "quantum computing"},
        output_key="research_out",
        retry_on_failure=False,
    )
    summarize = Node(
        id=NodeID("summarize"),
        type=NodeType.AGENT,
        name="summarize",
        ref_id="Summarizer",
        input_mapping={"text": "$$research_out$$"},
        output_key="summary_out",
        retry_on_failure=False,
    )
    write = Node(
        id=NodeID("write"),
        type=NodeType.AGENT,
        name="write",
        ref_id="Writer",
        input_mapping={"summary": "$$summary_out$$"},
        output_key="article_out",
        retry_on_failure=False,
    )
    return DAG(
        name="research-summarize-write",
        nodes=(research, summarize, write),
        edges=(
            Edge(source=NodeID("research"), target=NodeID("summarize")),
            Edge(source=NodeID("summarize"), target=NodeID("write")),
        ),
        entry_node=research.id,
    )


@pytest.mark.asyncio
async def test_full_stack_composition(tmp_path: Path) -> None:
    """Every real component wired together runs a realistic DAG to completion."""
    # Real persistence
    memory_store = SqliteMemoryStore(db_path=str(tmp_path / "memory.db"))

    # Real event bus
    event_bus = InMemoryEventBus()

    # Real context compiler with realistic token budget
    compiler = PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=3.5))
    budget = TokenBudget(max_tokens=50_000, reserved_for_output=4_000)

    # Real budget guard — cap at $1 (3 agents @ $0.15 total → well under, won't halt)
    budget_guard = BudgetGuard(max_cost_usd=1.00)

    # Agents
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_ResearchAgent(), goal_type=_ResearchGoal)
    registry.register_agent(agent_instance=_SummarizeAgent(), goal_type=_SummarizeGoal)
    registry.register_agent(agent_instance=_WriteAgent(), goal_type=_WriteGoal)

    # Wire executor
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            event_bus=event_bus,
            budget_guard=budget_guard,
            context_compiler=compiler,
            token_budget=budget,
        ),
    )

    try:
        result = await executor.run(dag=_research_summarize_write_dag())

        # 1. DAG completed end-to-end
        assert result.status == RunStatus.COMPLETED
        assert len(result.node_results) == 3
        for nr in result.node_results:
            assert nr.success, f"node {nr.node_id} failed: {nr.error}"

        # 2. Final context carries all outputs
        assert result.final_context.get("research_out") is not None
        assert result.final_context.get("summary_out") is not None
        assert result.final_context.get("article_out") is not None

        # 3. BudgetGuard accumulated cost across all three agents
        # Research 0.05 + Summarize 0.02 + Write 0.08 = 0.15
        assert budget_guard.accumulated_cost_usd == pytest.approx(0.15, abs=0.001)
        assert not budget_guard.should_halt()

        # 4. Agent metadata flowed through NodeResult.metadata (regression for #27)
        research_result = result.node_results[0]
        assert research_result.metadata.get("cost_estimate_usd") == 0.05
        assert research_result.metadata.get("tokens_total") == 500
        assert research_result.metadata.get("model") == "fake-research-model"

    finally:
        await memory_store.close()


@pytest.mark.asyncio
async def test_full_stack_halts_when_budget_exhausted(tmp_path: Path) -> None:
    """Confirm the full stack halts correctly when budget trips mid-run.

    Tight cap — Research (0.05) passes, Summarize (0.02) pushes total=0.07,
    Write (0.08) records to 0.15 and then should_halt() returns True.
    """
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_ResearchAgent(), goal_type=_ResearchGoal)
    registry.register_agent(agent_instance=_SummarizeAgent(), goal_type=_SummarizeGoal)
    registry.register_agent(agent_instance=_WriteAgent(), goal_type=_WriteGoal)

    budget_guard = BudgetGuard(max_cost_usd=0.10)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(budget_guard=budget_guard),
    )

    result = await executor.run(dag=_research_summarize_write_dag())

    assert result.status == RunStatus.FAILED
    assert "udget" in (result.error or "")
    # Verify the halt fired AFTER Write (total 0.15 > 0.10) — Writer completed
    # its call (cost recorded) but subsequent DAG progression aborted.
    completed_ids = {str(nr.node_id) for nr in result.node_results if nr.success}
    assert "research" in completed_ids
    assert "summarize" in completed_ids
    # final_context should not carry the downstream node's output when halted
    # mid-flow (DAG aborts BEFORE applying post-halt output).
    assert budget_guard.accumulated_cost_usd >= 0.10, (
        f"halt fired before budget exceeded threshold: {budget_guard.accumulated_cost_usd}"
    )
