"""Regression tests — DAGExecutor must be safe under concurrent run() calls.

Before the fix, `self._route_choices` and `self._correlation_id` were
instance fields rewritten at the start of every run(). Two concurrent runs
on the same executor clobbered each other's routing state mid-flight.

The fix uses contextvars.ContextVar so each async task gets its own view.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID, RunID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _TagGoal(BaseModel):
    tag: str


class _TagResult(BaseModel):
    tag: str


class _TagAgent(Agent[_TagGoal, _TagResult]):
    """Agent that echoes its input tag after a small async hop."""

    @property
    def id(self) -> AgentID:
        return AgentID("Tag")

    @property
    def description(self) -> str:
        return "Echoes the input tag"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _TagGoal, context: AgentContext) -> AgentResult[_TagResult]:
        # Yield to the event loop to force interleaving between concurrent runs.
        await asyncio.sleep(0)
        return AgentResult.ok(output=_TagResult(tag=goal.tag), state=AgentState())


def _dag_tagged(run_tag: str) -> DAG:
    node = Node(
        id=NodeID("n1"),
        type=NodeType.AGENT,
        name="tag",
        ref_id="Tag",
        input_mapping={"tag": run_tag},
        output_key="tag_out",
        retry_on_failure=False,
    )
    return DAG(name=f"concurrent-{run_tag}", nodes=(node,), edges=(), entry_node=node.id)


def _registry() -> AgentRegistry:
    r = AgentRegistry()
    r.register_agent(agent_instance=_TagAgent(), goal_type=_TagGoal)
    return r


@pytest.mark.asyncio
async def test_concurrent_runs_on_shared_executor_do_not_clobber_state() -> None:
    """10 concurrent run() calls each see their own correlation_id in emitted events."""
    bus = InMemoryEventBus()
    received_events: list[Event] = []

    async def capture(event: Event) -> None:
        received_events.append(event)

    bus.subscribe(event_type=EventType.DAG_COMPLETED, handler=capture)

    executor = create_executor(
        agent_registry=_registry(),
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(event_bus=bus),
    )

    tasks = []
    expected_correlation_ids: set[str] = set()
    for i in range(10):
        run_id = RunID(f"run-{i}")
        expected_correlation_ids.add(str(run_id))
        tasks.append(executor.run(dag=_dag_tagged(run_tag=f"t{i}"), run_id=run_id))

    results = await asyncio.gather(*tasks)

    # All 10 runs succeed independently
    assert all(r.status == RunStatus.COMPLETED for r in results)

    # Each run's DAG_COMPLETED event carried that run's own correlation_id —
    # before the ContextVar fix, all events would share the last-set value.
    observed = {ev.correlation_id for ev in received_events}
    assert expected_correlation_ids.issubset(observed), (
        f"correlation ids bled between runs. expected {expected_correlation_ids}, got {observed}"
    )


@pytest.mark.asyncio
async def test_shared_executor_handles_interleaved_runs() -> None:
    """Concurrent runs produce the right output for each input tag."""
    executor = create_executor(
        agent_registry=_registry(),
        config=ExecutorConfig(enable_events=False),
        services=RuntimeServices(),
    )

    tasks = [executor.run(dag=_dag_tagged(run_tag=f"t{i}")) for i in range(20)]
    results = await asyncio.gather(*tasks)

    assert all(r.status == RunStatus.COMPLETED for r in results)
    # Each run's final_context.get("tag_out") should be that run's tag,
    # not someone else's.
    for i, result in enumerate(results):
        output = result.final_context.get("tag_out", default=None)
        assert output is not None
        assert f"t{i}" in str(output), f"run {i} saw someone else's tag: {output}"
