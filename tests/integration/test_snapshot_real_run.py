"""SPEC-14 integration — snapshot a REAL DAGExecutor run, not a hand-built fixture.

The unit tests feed snapshot_from_* hand-constructed RunRecord/ExecutionResult objects. Per
"fixtures mirror reality", this drives a genuine 2-node agent DAG through the real executor +
a real InMemoryRunLogger, then snapshots BOTH the returned ExecutionResult and the logged
RunRecord — proving the adapters work on production-shaped objects.
"""

import json

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.operator.snapshot import (
    SCHEMA_VERSION,
    ServicePresence,
    SessionSnapshot,
    SnapshotHealth,
    SnapshotRunState,
    snapshot_from_execution_result,
    snapshot_from_run_record,
)
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.results import ExecutionResult
from cemaf.orchestration.services import RuntimeServices


class AnalyzeGoal(BaseModel):
    topic: str = "machine learning"


class AnalyzeResult(BaseModel):
    analysis: str


class AnalyzeAgent(Agent[AnalyzeGoal, AnalyzeResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Analyze")

    @property
    def description(self) -> str:
        return "Analyzes a topic"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: AnalyzeGoal, context: AgentContext) -> AgentResult[AnalyzeResult]:
        return AgentResult.ok(output=AnalyzeResult(analysis=f"analysis::{goal.topic}"), state=AgentState())


class SummarizeGoal(BaseModel):
    text: str = ""


class SummarizeResult(BaseModel):
    summary: str


class SummarizeAgent(Agent[SummarizeGoal, SummarizeResult]):
    @property
    def id(self) -> AgentID:
        return AgentID("Summarize")

    @property
    def description(self) -> str:
        return "Summarizes text"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: SummarizeGoal, context: AgentContext) -> AgentResult[SummarizeResult]:
        out = SummarizeResult(summary=f"summary::{goal.text[:20]}")
        return AgentResult.ok(output=out, state=AgentState())


def _build_dag() -> DAG:
    dag = DAG(name="analyze-summarize", description="2-node pipeline")
    dag = dag.add_node(
        node=Node.agent(
            id="analyze",
            name="Analyze",
            agent_id="Analyze",
            input_mapping={"topic": "robotics"},
            output_key="analysis",
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="summarize",
            name="Summarize",
            agent_id="Summarize",
            input_mapping={"text": "$$analysis$$"},
            output_key="summary",
        )
    )
    return dag


async def _run() -> tuple[ExecutionResult, InMemoryRunLogger]:
    registry = AgentRegistry()
    registry.register_agent(agent_instance=AnalyzeAgent(), goal_type=AnalyzeGoal)
    registry.register_agent(agent_instance=SummarizeAgent(), goal_type=SummarizeGoal)
    run_logger = InMemoryRunLogger()
    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(run_logger=run_logger),
    )
    result = await executor.run(dag=_build_dag())
    return result, run_logger


class TestSnapshotFromRealRun:
    @pytest.mark.asyncio
    async def test_execution_result_snapshot_from_real_run(self) -> None:
        """A real 2-node run → ExecutionResult → snapshot with one worker per node, all healthy."""
        result, _ = await _run()
        assert result.status is RunStatus.COMPLETED
        assert len(result.node_results) == 2  # the executor actually produced per-node results

        snap = snapshot_from_execution_result(result, services_present=("run_logger",))
        assert isinstance(snap, SessionSnapshot)
        assert snap.schema_version == SCHEMA_VERSION
        assert snap.run.state is SnapshotRunState.COMPLETED
        assert {w.id for w in snap.workers} == {"analyze", "summarize"}
        assert all(w.health is SnapshotHealth.HEALTHY for w in snap.workers)
        # Inv 5 — counts sum to worker_count on a real result.
        assert sum(snap.aggregates.states.values()) == snap.aggregates.worker_count == 2
        assert snap.runtime.services["run_logger"] is ServicePresence.ENABLED

    @pytest.mark.asyncio
    async def test_run_record_snapshot_from_real_logger(self) -> None:
        """The RunLogger captured a real RunRecord → snapshot reflects its run identity + totals."""
        result, run_logger = await _run()
        record = run_logger.get_record(str(result.run_id))
        assert record is not None  # the run was actually logged

        snap = snapshot_from_run_record(record, services_present=("run_logger",))
        assert snap.run.id == str(result.run_id)
        assert snap.run.dag_name == "analyze-summarize"
        assert snap.run.state is SnapshotRunState.COMPLETED
        # Totals come straight off the real record (Inv 7), not invented.
        assert snap.aggregates.total_tokens == record.total_tokens
        assert snap.aggregates.total_cost_usd == record.total_cost_usd

    @pytest.mark.asyncio
    async def test_real_run_snapshot_is_deterministic_and_serializes(self) -> None:
        """The snapshot of a real run round-trips through JSON and is byte-stable per record."""
        result, _ = await _run()
        snap = snapshot_from_execution_result(result)
        reparsed = SessionSnapshot.model_validate(json.loads(snap.to_json()))
        assert reparsed.run.id == snap.run.id
        # Same ExecutionResult ⇒ identical JSON (timestamps come from the result, not generated).
        assert snapshot_from_execution_result(result).to_json() == snap.to_json()
