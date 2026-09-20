"""Integration test: DeepAgentOrchestrator identity admission (SPEC-18 §2.1).

Fills a real gap — no integration-level test (real orchestrator, not just
guardrail unit tests) exercised deep-agent spawning before this. A real
3-level recursive spawn chain — root -> child -> grandchild — through the
real `DeepAgentOrchestrator`: agents genuinely call
`orchestrator.spawn_child()` from inside their own `run()`, recursively, the
same pattern `tests/unit/test_deep_agent.py`'s `MockAgent` already
establishes. `MockNodeExecutor` stands in only for the `DAGExecutor`
dependency `DeepAgentOrchestrator` requires but never exercises here —
identity admission is entirely `DeepAgentOrchestrator`'s own machinery, not
DAG execution.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.factories import create_agent_directory
from cemaf.core.enums import InstanceStatus
from cemaf.core.types import AgentID, RunID, TaskID
from cemaf.orchestration.deep_agent import DeepAgentOrchestrator
from cemaf.orchestration.executor import DAGExecutor
from tests.conftest import MockNodeExecutor


class _Goal(BaseModel):
    task: str


class _Result(BaseModel):
    output: str


class _RecursiveAgent(Agent[_Goal, _Result]):
    """Spawns its configured children via a REAL orchestrator.spawn_child()
    call from inside its own run() — genuinely recursive, not simulated.
    """

    def __init__(self, agent_id: str, spawn_children: list[str] | None = None) -> None:
        self._id = AgentID(agent_id)
        self._spawn_children = spawn_children or []
        self._orchestrator: DeepAgentOrchestrator | None = None

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"recursive agent {self._id}"

    @property
    def skills(self) -> tuple[()]:
        return ()

    def set_orchestrator(self, orchestrator: DeepAgentOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[_Result]:
        assert self._orchestrator is not None
        for child_id in self._spawn_children:
            await self._orchestrator.spawn_child(
                parent_id=self._id,
                child_agent_id=AgentID(child_id),
                goal=goal,
                parent_context=context,
            )
        return AgentResult.ok(_Result(output=f"done:{self._id}"), AgentState())


@pytest.mark.asyncio
async def test_three_level_recursive_spawn_chain_gets_correct_parent_instance_chain() -> None:
    """root -> child -> grandchild: 3 distinct instances, each parent_instance_id
    pointing at its *immediate* parent's own spawn identity (not the root's),
    every one COMPLETED once the whole chain finishes.
    """
    directory = create_agent_directory()
    root = _RecursiveAgent("root", spawn_children=["child"])
    child = _RecursiveAgent("child", spawn_children=["grandchild"])
    grandchild = _RecursiveAgent("grandchild")

    dag_executor = DAGExecutor(node_executor=MockNodeExecutor())
    orchestrator = DeepAgentOrchestrator(
        agents={root.id: root, child.id: child, grandchild.id: grandchild},
        dag_executor=dag_executor,
        agent_directory=directory,
    )
    for agent in (root, child, grandchild):
        agent.set_orchestrator(orchestrator)

    run_id = RunID("deep-chain-run")
    result = await orchestrator.run(root_agent_id=root.id, goal=_Goal(task="go"), run_id=run_id)

    assert result.success
    assert result.total_agents_spawned == 2  # child + grandchild (root isn't a "spawn")

    task_id = TaskID(str(run_id))
    instances = await directory.list(task_id=task_id)
    assert len(instances) == 3

    root_instance = next(i for i in instances if i.agent_id == "root")
    child_instance = next(i for i in instances if i.agent_id == "child")
    grandchild_instance = next(i for i in instances if i.agent_id == "grandchild")

    assert root_instance.parent_instance_id is None
    assert child_instance.parent_instance_id == root_instance.instance_id
    assert grandchild_instance.parent_instance_id == child_instance.instance_id
    # The immediate-parent chain, not "everyone points at root":
    assert grandchild_instance.parent_instance_id != root_instance.instance_id

    all_ids = {root_instance.instance_id, child_instance.instance_id, grandchild_instance.instance_id}
    assert len(all_ids) == 3

    assert all(
        i.status is InstanceStatus.COMPLETED for i in (root_instance, child_instance, grandchild_instance)
    )


@pytest.mark.asyncio
async def test_two_spawns_of_same_child_agent_from_one_parent_get_distinct_instances() -> None:
    """Two children spawned with the SAME child_agent_id from one parent —
    the current_children counter in the spawn key must disambiguate them.
    """
    directory = create_agent_directory()
    root = _RecursiveAgent("root", spawn_children=["worker", "worker"])
    worker = _RecursiveAgent("worker")

    dag_executor = DAGExecutor(node_executor=MockNodeExecutor())
    orchestrator = DeepAgentOrchestrator(
        agents={root.id: root, worker.id: worker},
        dag_executor=dag_executor,
        agent_directory=directory,
    )
    root.set_orchestrator(orchestrator)
    worker.set_orchestrator(orchestrator)

    run_id = RunID("deep-duplicate-run")
    result = await orchestrator.run(root_agent_id=root.id, goal=_Goal(task="go"), run_id=run_id)

    assert result.success
    assert result.total_agents_spawned == 2

    task_id = TaskID(str(run_id))
    instances = await directory.list(task_id=task_id)
    workers = [i for i in instances if i.agent_id == "worker"]
    root_instance = next(i for i in instances if i.agent_id == "root")

    assert len(workers) == 2
    assert workers[0].instance_id != workers[1].instance_id
    assert {w.parent_instance_id for w in workers} == {root_instance.instance_id}
    assert all(w.status is InstanceStatus.COMPLETED for w in workers)
