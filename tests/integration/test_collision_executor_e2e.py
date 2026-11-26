"""SPEC-12 §2.4 e2e — built-in collision coordination in a REAL DAGExecutor PARALLEL run.

Every other collision test drives the coordinator directly. This is the production path:
create_executor with default RuntimeServices runs a PARALLEL node whose children intend to
write overlapping context keys. The earlier sibling holds right-of-way and runs; the later
one is steered and never dispatched — deterministically, observed through the real
ExecutionResult.
"""

from dataclasses import replace

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.collision import AdvisoryLevel
from cemaf.context.context import Context
from cemaf.context.merge import ReducerMergeStrategy
from cemaf.context.patch import SecurityLevel
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID, RunID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.orchestration.checkpointer import InMemoryCheckpointer
from cemaf.orchestration.context_node_executor import ContextNodeExecutor
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.executor import DAGExecutor
from cemaf.orchestration.node_handlers import COLLISION_METADATA_KEY, SteeredField, is_steered
from cemaf.orchestration.results import ExecutionResult, NodeResult
from cemaf.orchestration.services import RuntimeServices


class _Goal(BaseModel):
    pass


class _Out(BaseModel):
    who: str


class FailsOnceAgent(Agent[_Goal, _Out]):
    """Fails on its first run and succeeds afterwards, so a resumed run gets past it."""

    def __init__(self, *, ran: list[str]) -> None:
        self._ran = ran
        self._attempts = 0

    @property
    def id(self) -> AgentID:
        return AgentID("flaky")

    @property
    def description(self) -> str:
        return "flaky agent"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[_Out]:
        self._attempts += 1
        if self._attempts == 1:
            return AgentResult.fail(error="first attempt fails", state=AgentState())
        self._ran.append("flaky")
        return AgentResult.ok(output=_Out(who="flaky"), state=AgentState())


class RecordingAgent(Agent[_Goal, _Out]):
    """Agent that records each time it actually runs."""

    def __init__(self, *, agent_id: str, ran: list[str]) -> None:
        self._agent_id = agent_id
        self._ran = ran

    @property
    def id(self) -> AgentID:
        return AgentID(self._agent_id)

    @property
    def description(self) -> str:
        return f"{self._agent_id} agent"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[_Out]:
        self._ran.append(self._agent_id)
        return AgentResult.ok(output=_Out(who=self._agent_id), state=AgentState())


def _result_for(run: ExecutionResult, node_id: str) -> NodeResult:
    return next(r for r in run.node_results if r.node_id == NodeID(node_id))


async def _run_parallel(
    *,
    children: list[tuple[str, str]],
    services: RuntimeServices | None = None,
) -> tuple[ExecutionResult, list[str]]:
    """Run a PARALLEL node over (child_id, output_key) children, each backed by its own agent."""
    ran: list[str] = []
    registry = AgentRegistry()
    for child_id, _ in children:
        registry.register_agent(agent_instance=RecordingAgent(agent_id=child_id, ran=ran), goal_type=_Goal)

    dag = DAG(name="collision-parallel", description="children race for context keys")
    dag = dag.add_node(
        node=Node.parallel(
            id="fan",
            name="Fan out",
            parallel_nodes=[child_id for child_id, _ in children],
            output_key="fan_out",
        )
    )
    for child_id, output_key in children:
        dag = dag.add_node(
            node=Node.agent(id=child_id, name=child_id, agent_id=child_id, output_key=output_key)
        )

    executor = create_executor(
        clearance=SecurityLevel.CONFIDENTIAL,
        agent_registry=registry,
        services=services if services is not None else RuntimeServices(),
    )
    return await executor.run(dag=dag), ran


class TestCollisionThroughRealExecutor:
    @pytest.mark.asyncio
    async def test_earlier_sibling_runs_and_later_one_is_steered(self) -> None:
        """Two children write 'decision': the first listed runs, the second never runs."""
        run, ran = await _run_parallel(children=[("first", "decision"), ("second", "decision")])

        assert run.status is RunStatus.COMPLETED
        assert ran == ["first"]
        assert _result_for(run, "first").success is True
        steered = _result_for(run, "second")
        assert is_steered(result=steered)
        assert steered.metadata[COLLISION_METADATA_KEY][SteeredField.HELD_BY] == "first"
        assert "right-of-way" in (steered.error or "")
        assert _result_for(run, "fan").success is True

    @pytest.mark.asyncio
    async def test_swapping_sibling_order_swaps_who_holds(self) -> None:
        """Resolution follows sibling order, not scheduling luck."""
        run, ran = await _run_parallel(children=[("second", "decision"), ("first", "decision")])

        assert ran == ["second"]
        assert is_steered(result=_result_for(run, "first"))

    @pytest.mark.asyncio
    async def test_nested_keys_collide(self) -> None:
        """Writing 'draft' and 'draft.body' overlaps, so only the earlier sibling runs."""
        run, ran = await _run_parallel(children=[("outline", "draft"), ("body", "draft.body")])

        assert ran == ["outline"]
        assert is_steered(result=_result_for(run, "body"))

    @pytest.mark.asyncio
    async def test_disjoint_keys_all_run(self) -> None:
        """Children writing unrelated keys are all dispatched."""
        run, ran = await _run_parallel(children=[("research", "research"), ("outline", "outline")])

        assert run.status is RunStatus.COMPLETED
        assert sorted(ran) == ["outline", "research"]

    @pytest.mark.asyncio
    async def test_sibling_paths_under_one_key_collide(self) -> None:
        """'results.a' and 'results.b' both replace 'results' on merge, so only the earlier one runs."""
        run, ran = await _run_parallel(children=[("left", "results.a"), ("right", "results.b")])

        assert ran == ["left"]
        assert is_steered(result=_result_for(run, "right"))

    @pytest.mark.asyncio
    async def test_first_of_three_holds_the_key(self) -> None:
        """Three children on one key: the first runs and both others are steered by it."""
        run, ran = await _run_parallel(children=[("a", "decision"), ("b", "decision"), ("c", "decision")])

        assert ran == ["a"]
        for steered_id in ("b", "c"):
            steered = _result_for(run, steered_id)
            assert is_steered(result=steered)
            assert steered.metadata[COLLISION_METADATA_KEY][SteeredField.HELD_BY] == "a"

    @pytest.mark.asyncio
    async def test_coordination_off_lets_both_run(self) -> None:
        """collision_policy=None restores last-write-wins: both colliding children run."""
        run, ran = await _run_parallel(
            children=[("first", "decision"), ("second", "decision")],
            services=RuntimeServices(collision_policy=None),
        )

        assert sorted(ran) == ["first", "second"]
        assert _result_for(run, "second").success is True

    @pytest.mark.asyncio
    async def test_fan_in_merge_strategy_keeps_every_sibling(self) -> None:
        """A merge strategy that combines shared writes lets both children write 'findings'."""
        ran: list[str] = []
        registry = AgentRegistry()
        for child_id in ("first", "second"):
            registry.register_agent(
                agent_instance=RecordingAgent(agent_id=child_id, ran=ran), goal_type=_Goal
            )
        dag = DAG(name="fan-in", description="two researchers feed one key")
        dag = dag.add_node(node=Node.parallel(id="fan", name="Fan", parallel_nodes=["first", "second"]))
        for child_id in ("first", "second"):
            dag = dag.add_node(
                node=Node.agent(id=child_id, name=child_id, agent_id=child_id, output_key="findings")
            )
        executor = DAGExecutor(
            node_executor=ContextNodeExecutor(agent_registry=registry, clearance=SecurityLevel.CONFIDENTIAL),
            services=RuntimeServices(),
            merge_strategy=ReducerMergeStrategy(reducers={"findings": list}),
        )

        run = await executor.run(dag=dag)

        assert sorted(ran) == ["first", "second"]
        assert not any(is_steered(result=result) for result in run.node_results)

    @pytest.mark.asyncio
    async def test_key_without_a_reducer_is_still_coordinated(self) -> None:
        """A reducer strategy only exempts the keys it reduces; 'summary' has no reducer."""
        ran: list[str] = []
        registry = AgentRegistry()
        for child_id in ("first", "second"):
            registry.register_agent(
                agent_instance=RecordingAgent(agent_id=child_id, ran=ran), goal_type=_Goal
            )
        dag = DAG(name="uncovered", description="two writers, no reducer")
        dag = dag.add_node(node=Node.parallel(id="fan", name="Fan", parallel_nodes=["first", "second"]))
        for child_id in ("first", "second"):
            dag = dag.add_node(
                node=Node.agent(id=child_id, name=child_id, agent_id=child_id, output_key="summary")
            )
        executor = DAGExecutor(
            node_executor=ContextNodeExecutor(agent_registry=registry, clearance=SecurityLevel.CONFIDENTIAL),
            services=RuntimeServices(),
            merge_strategy=ReducerMergeStrategy(reducers={"findings": list}),
        )

        run = await executor.run(dag=dag)

        assert ran == ["first"]
        assert is_steered(result=_result_for(run, "second"))

    @pytest.mark.asyncio
    async def test_public_run_parallel_nodes_steers_too(self) -> None:
        """DAGExecutor.run_parallel_nodes applies the same coordination as a PARALLEL node."""
        ran: list[str] = []
        registry = AgentRegistry()
        for child_id in ("first", "second"):
            registry.register_agent(
                agent_instance=RecordingAgent(agent_id=child_id, ran=ran), goal_type=_Goal
            )
        executor = create_executor(clearance=SecurityLevel.CONFIDENTIAL, agent_registry=registry)
        children = tuple(
            Node.agent(id=child_id, name=child_id, agent_id=child_id, output_key="decision")
            for child_id in ("first", "second")
        )

        results, _ = await executor.run_parallel_nodes(nodes=children, context=Context())

        assert ran == ["first"]
        assert [is_steered(result=result) for result in results] == [False, True]

    @pytest.mark.asyncio
    async def test_resume_keeps_a_steered_child_unsuccessful(self) -> None:
        """After a later failure, resume must not treat the steered child as a success."""
        ran: list[str] = []
        registry = AgentRegistry()
        for child_id in ("first", "second", "after_second"):
            registry.register_agent(
                agent_instance=RecordingAgent(agent_id=child_id, ran=ran), goal_type=_Goal
            )
        registry.register_agent(agent_instance=FailsOnceAgent(ran=ran), goal_type=_Goal)
        dag = DAG(
            name="resume-steered",
            nodes=(
                Node.parallel(id="fan", name="Fan", parallel_nodes=["first", "second"]),
                Node.agent(id="first", name="first", agent_id="first", output_key="decision"),
                Node.agent(id="second", name="second", agent_id="second", output_key="decision"),
                replace(
                    Node.agent(id="flaky", name="flaky", agent_id="flaky", output_key="flaky_out"),
                    retry_on_failure=False,
                ),
                Node.agent(
                    id="after_second", name="after_second", agent_id="after_second", output_key="later"
                ),
            ),
            edges=(
                Edge(source=NodeID("fan"), target=NodeID("flaky")),
                Edge(
                    source=NodeID("second"), target=NodeID("after_second"), condition=EdgeCondition.ON_SUCCESS
                ),
                Edge(source=NodeID("flaky"), target=NodeID("after_second"), condition=EdgeCondition.ALWAYS),
            ),
            entry_node=NodeID("fan"),
        )
        executor = create_executor(
            clearance=SecurityLevel.CONFIDENTIAL,
            agent_registry=registry,
            services=RuntimeServices(checkpointer=InMemoryCheckpointer()),
        )

        halted = await executor.run(dag=dag, run_id=RunID("run-resume-steered"))
        resumed = await executor.resume(run_id=RunID("run-resume-steered"), dag=dag)

        assert halted.status is RunStatus.FAILED
        assert resumed.status is RunStatus.COMPLETED
        assert "flaky" in ran
        assert "after_second" not in ran

    @pytest.mark.asyncio
    async def test_conflict_is_published_on_the_event_bus(self) -> None:
        """A resolved conflict reaches the bus as CONTEXT_CONFLICT naming holder and steered child."""
        bus = InMemoryEventBus()
        conflicts: list[Event] = []

        async def capture(event: Event) -> None:
            conflicts.append(event)

        bus.subscribe(event_type=EventType.CONTEXT_CONFLICT, handler=capture)

        await _run_parallel(
            children=[("first", "decision"), ("second", "decision")],
            services=RuntimeServices(event_bus=bus),
        )

        assert len(conflicts) == 1
        payload = conflicts[0].payload
        assert payload["agent_id"] == "second"
        assert payload["level"] == AdvisoryLevel.RESOLUTION_ADVISORY
        assert payload["hold"] == "first"
        assert payload["steer"] == "second"
