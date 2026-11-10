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
from cemaf.agents.selection import create_default_agent_selector
from cemaf.bootstrap import create_executor
from cemaf.context.patch import SecurityLevel
from cemaf.core.enums import NodeType, RunStatus
from cemaf.core.types import AgentID, NodeID, TaskID
from cemaf.moderation.factories import create_keyword_moderation_pipeline
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.resolvers import NodeComplete, NodeResolver
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
    executor = create_executor(clearance=SecurityLevel.CONFIDENTIAL, agent_registry=registry)

    dag = DAG(
        name="d",
        nodes=(Node.agent(id="ping", name="ping", agent_id="Ping", output_key="out"),),
        edges=(),
        entry_node=NodeID("ping"),
    )
    run = await executor.run(dag=dag)

    assert run.status is RunStatus.COMPLETED
    assert run.node_results[0].output == "pong"


class ApprovalResolver:
    """Custom node kind: nodes marked config["approval"] are approved without running an agent."""

    resolver_id = "approval"

    def __init__(self) -> None:
        self.handled: list[str] = []

    def matches(self, *, node: Node) -> bool:
        return bool(node.config and node.config.get("approval") is True)

    async def resolve(
        self, *, node: Node, resolved_inputs: object, run_id: str, start: float
    ) -> NodeComplete:
        self.handled.append(str(node.id))
        return NodeComplete(
            result=NodeResult(
                node_id=node.id,
                success=True,
                output="approved",
                duration_ms=(perf_counter() - start) * 1000,
                metadata={"approval": True},
            )
        )


class CouncilClaimingResolver(ApprovalResolver):
    """Custom resolver that claims council nodes, to prove custom resolvers run first."""

    resolver_id = "council_claimer"

    def matches(self, *, node: Node) -> bool:
        return bool(node.config and "council" in node.config)


class _CountingPing(_Ping):
    """Ping that counts how often it actually runs."""

    def __init__(self) -> None:
        self.runs = 0

    async def run(self, goal: _PingGoal, context: AgentContext) -> AgentResult[str]:
        self.runs += 1
        return await super().run(goal=goal, context=context)


def _ping_executor(*, ping: _Ping, resolvers: tuple[NodeResolver, ...]) -> DAGExecutor:
    """create_executor with Ping registered and the given custom resolvers."""
    registry = AgentRegistry()
    registry.register_agent(agent_instance=ping, goal_type=_PingGoal)
    return create_executor(
        clearance=SecurityLevel.CONFIDENTIAL,
        agent_registry=registry,
        services=RuntimeServices(node_resolvers=resolvers),
    )


@pytest.mark.asyncio
async def test_custom_resolver_handles_its_node_through_create_executor() -> None:
    """A resolver registered on RuntimeServices claims its node; the ref_id agent never runs."""
    ping = _CountingPing()
    approval = ApprovalResolver()
    executor = _ping_executor(ping=ping, resolvers=(approval,))
    dag = DAG(
        name="approval",
        nodes=(
            Node(
                id=NodeID("approve"),
                type=NodeType.AGENT,
                name="approve",
                ref_id="Ping",
                config={"approval": True},
                output_key="decision",
            ),
        ),
        edges=(),
        entry_node=NodeID("approve"),
    )

    run = await executor.run(dag=dag)

    assert run.status is RunStatus.COMPLETED
    assert run.node_results[0].output == "approved"
    assert approval.handled == ["approve"]
    assert ping.runs == 0


@pytest.mark.asyncio
async def test_custom_resolver_that_does_not_match_falls_through() -> None:
    """An ordinary AGENT node still runs its ref_id agent when a custom resolver is registered."""
    ping = _CountingPing()
    approval = ApprovalResolver()
    executor = _ping_executor(ping=ping, resolvers=(approval,))
    dag = DAG(
        name="ordinary",
        nodes=(Node.agent(id="ping", name="ping", agent_id="Ping", output_key="out"),),
        edges=(),
        entry_node=NodeID("ping"),
    )

    run = await executor.run(dag=dag)

    assert run.node_results[0].output == "pong"
    assert approval.handled == []
    assert ping.runs == 1


@pytest.mark.asyncio
async def test_custom_resolvers_run_before_the_council() -> None:
    """A custom resolver matching council nodes handles them; no deliberation happens."""
    ping = _CountingPing()
    claimer = CouncilClaimingResolver()
    executor = _ping_executor(ping=ping, resolvers=(claimer,))
    dag = DAG(
        name="council",
        nodes=(
            Node(
                id=NodeID("vote"),
                type=NodeType.AGENT,
                name="vote",
                ref_id="Ping",
                config={"council": {"members": ["Ping"], "question": "ship?"}},
                output_key="verdict",
            ),
        ),
        edges=(),
        entry_node=NodeID("vote"),
    )

    run = await executor.run(dag=dag)

    assert run.node_results[0].output == "approved"
    assert claimer.handled == ["vote"]
    assert ping.runs == 0


def test_duplicate_resolver_ids_are_rejected() -> None:
    """Two resolvers sharing an id would make the chain ambiguous, so construction fails."""
    with pytest.raises(ValueError, match="approval"):
        ContextNodeExecutor(
            agent_registry=AgentRegistry(),
            clearance=SecurityLevel.CONFIDENTIAL,
            node_resolvers=(ApprovalResolver(), ApprovalResolver()),
        )


def test_custom_resolver_cannot_reuse_a_built_in_id() -> None:
    """A custom resolver named like a built-in is rejected rather than silently shadowing it."""

    class FakeStatic(ApprovalResolver):
        resolver_id = "static_ref"

    with pytest.raises(ValueError, match="static_ref"):
        ContextNodeExecutor(
            agent_registry=AgentRegistry(),
            clearance=SecurityLevel.CONFIDENTIAL,
            node_resolvers=(FakeStatic(),),
        )


@pytest.mark.parametrize(
    ("with_selector", "expected"),
    [
        (False, ("approval", "council", "static_ref")),
        (True, ("approval", "council", "auction", "static_ref")),
    ],
)
def test_resolver_ids_list_the_chain_in_match_order(with_selector: bool, expected: tuple[str, ...]) -> None:
    """Custom resolvers first, then council, auction only with a selector, and the static fallback last."""
    node_executor = ContextNodeExecutor(
        agent_registry=AgentRegistry(),
        clearance=SecurityLevel.CONFIDENTIAL,
        agent_selector=create_default_agent_selector() if with_selector else None,
        node_resolvers=(ApprovalResolver(),),
    )

    assert node_executor.resolver_ids == expected


@pytest.mark.asyncio
async def test_custom_resolver_output_is_still_moderated() -> None:
    """A custom resolver skips the interceptors like the council does, but moderation still applies."""

    class LeakyResolver(ApprovalResolver):
        resolver_id = "leaky"

        async def resolve(
            self, *, node: Node, resolved_inputs: object, run_id: str, start: float
        ) -> NodeComplete:
            return NodeComplete(result=NodeResult(node_id=node.id, success=True, output="FORBIDDEN draft"))

    registry = AgentRegistry()
    registry.register_agent(agent_instance=_Ping(), goal_type=_PingGoal)
    executor = create_executor(
        clearance=SecurityLevel.CONFIDENTIAL,
        agent_registry=registry,
        config=ExecutorConfig(enable_moderation=True),
        services=RuntimeServices(
            node_resolvers=(LeakyResolver(),),
            moderation_pipeline=create_keyword_moderation_pipeline(blocked_words=("FORBIDDEN",)),
        ),
    )
    dag = DAG(
        name="moderated",
        nodes=(
            Node(
                id=NodeID("leak"),
                type=NodeType.AGENT,
                name="leak",
                ref_id="Ping",
                config={"approval": True},
                output_key="draft",
            ),
        ),
        edges=(),
        entry_node=NodeID("leak"),
    )

    run = await executor.run(dag=dag)

    blocked = run.node_results[0]
    assert blocked.success is False
    assert "moderation" in (blocked.error or "")
    assert run.final_context.get("draft") is None


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
    executor = create_executor(
        clearance=SecurityLevel.CONFIDENTIAL,
        agent_registry=registry,
        services=RuntimeServices(agent_directory=directory),
    )

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
