"""Integration test for the NodeResolver dispatch chain.

Proves the executor uses the resolver seam — not bespoke if-branches — so a new
node kind is added by registering a resolver, never by growing execute_node.
The auction and council paths already have their own integration tests
(test_agent_auction.py, test_agent_council.py); this one focuses on the seam.
"""

from __future__ import annotations

from time import perf_counter

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.factories import create_agent_directory
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.context.context import Context
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID, TaskID
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices


class _PingGoal(BaseModel):
    pass


class _Ping:
    @property
    def id(self) -> AgentID:
        return AgentID("Ping")

    @property
    def description(self) -> str:
        return "ping"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _PingGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output="pong", state=AgentState())


@pytest.mark.asyncio
async def test_static_ref_dispatch_unchanged() -> None:
    """The canonical Node.agent path still works through the resolver chain."""
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_Ping(), goal_type=_PingGoal)
    executor = create_executor(agent_registry=registry)

    dag = DAG(
        name="d",
        nodes=(Node.agent(id="ping", name="ping", agent_id="Ping", output_key="out"),),
        edges=(),
        entry_node=NodeID("ping"),
    )
    run = await executor.run(dag=dag)

    assert run.status is RunStatus.COMPLETED
    assert run.node_results[0].output == "pong"


@pytest.mark.asyncio
async def test_custom_resolver_wins_over_static() -> None:
    """A custom resolver registered first claims a node before StaticRefResolver.

    Proves the seam is the only seam: a new node 'kind' is a registration, not a
    new branch in execute_node.
    """
    registry = AgentRegistry()
    registry.register_agent(agent_instance=_Ping(), goal_type=_PingGoal)
    executor = create_executor(agent_registry=registry)
    # Reach into the node executor and inject a custom resolver at the head.
    node_executor: ContextNodeExecutor = executor._node_executor  # type: ignore[attr-defined]

    class _SentinelResolver:
        resolver_id = "sentinel"

        def matches(self, *, node: Node) -> bool:
            return bool(node.config and node.config.get("sentinel") is True)

        async def resolve(self, *, node, resolved_inputs, run_id, start):
            from cemaf.orchestration.resolvers import NodeComplete

            return NodeComplete(
                result=NodeResult(
                    node_id=node.id,
                    success=True,
                    output="sentinel-handled",
                    duration_ms=(perf_counter() - start) * 1000,
                    metadata={"sentinel": True},
                )
            )

    # Register the sentinel BEFORE the built-ins.
    node_executor._resolvers = (_SentinelResolver(), *node_executor._resolvers)

    sentinel_node = Node(
        id=NodeID("s"),
        type=Node.agent(id="x", name="x", agent_id="Ping").type,
        name="s",
        ref_id="Ping",  # would normally route to Ping...
        config={"sentinel": True},  # ...but sentinel claims it first
    )
    result = await node_executor.execute_node(sentinel_node, Context())

    assert result.success is True
    assert result.output == "sentinel-handled"
    assert result.metadata["sentinel"] is True


class _RecordingPing:
    """Same as _Ping, but records the AgentContext it was dispatched with."""

    def __init__(self) -> None:
        self.seen_contexts: list[AgentContext] = []

    @property
    def id(self) -> AgentID:
        return AgentID("Ping")

    @property
    def description(self) -> str:
        return "ping"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _PingGoal, context: AgentContext) -> AgentResult[str]:
        self.seen_contexts.append(context)
        return AgentResult.ok(output="pong", state=AgentState())


@pytest.mark.asyncio
async def test_static_ref_dispatch_admits_distinct_identity_per_node() -> None:
    """Two nodes resolving to the same agent_id through the real resolver seam
    (SPEC-18 §2.1) each get a distinct instance_id threaded into the
    AgentContext the agent actually sees — "same definition spawned twice is
    distinguishable" — end to end through create_executor, not just the
    in-memory directory in isolation. The run-scoped directory disposes its
    entries automatically at run end (SPEC-18 §2.1 dispose), so the proof
    lives in what the agent observed, not a post-run directory inspection.
    """
    ping = _RecordingPing()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=ping, goal_type=_PingGoal)
    directory = create_agent_directory()
    executor = create_executor(agent_registry=registry, services=RuntimeServices(agent_directory=directory))

    dag = DAG(
        name="d",
        nodes=(
            Node.agent(id="ping-a", name="ping-a", agent_id="Ping", output_key="out_a"),
            Node.agent(id="ping-b", name="ping-b", agent_id="Ping", output_key="out_b"),
        ),
        edges=(),
        entry_node=NodeID("ping-a"),
    )
    run = await executor.run(dag=dag)

    assert run.status is RunStatus.COMPLETED
    assert len(ping.seen_contexts) == 2
    instance_ids = {ctx.instance_id for ctx in ping.seen_contexts}
    assert len(instance_ids) == 2
    assert all(instance_id is not None for instance_id in instance_ids)

    # dispose() fired automatically at run end — nothing left for this run.
    assert await directory.list(task_id=TaskID(str(run.run_id))) == ()
