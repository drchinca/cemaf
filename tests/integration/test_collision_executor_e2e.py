"""SPEC-12 e2e — collision guard wired into a REAL DAGExecutor PARALLEL run.

Every other collision test drives the coordinator directly. This is the production path: a
CollisionGuardInterceptor (PreInterceptor) consults a run-scoped CollisionCoordinator, wired
via RuntimeServices.interceptor_pipeline, while the executor runs two PARALLEL agent nodes
that intend to write the SAME context output_key. The lower-priority node is steered — its
agent never runs (PRE-REJECT), the higher-priority one holds and runs — deterministically,
observed through the real ExecutionResult.
"""

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.collision import (
    AgentWriteSet,
    CollisionCoordinator,
    WriteItem,
    create_collision_coordinator,
)
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.interceptors.pipeline import InterceptorPipeline
from cemaf.interceptors.types import DecisionKind, PreflightDecision
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.results import ExecutionResult, NodeResult
from cemaf.orchestration.services import RuntimeServices

# A node declares its priority for the collision tiebreak via config["started_at"] —
# lower value = earlier start = holds right-of-way.
_STARTED_AT = "started_at"


class CollisionGuardInterceptor:
    """PreInterceptor that registers each node's write with a CollisionCoordinator and
    REJECTs the node when the resolution advisory steers it away.

    The intended write is the node's output_key; priority is read from node.config so the
    test is deterministic without a wall clock.
    """

    def __init__(self, *, coordinator: CollisionCoordinator, interceptor_id: str = "collision_guard") -> None:
        self._coordinator = coordinator
        self._id = interceptor_id

    @property
    def interceptor_id(self) -> str:
        return self._id

    async def pre(self, *, node: Node, context: AgentContext) -> PreflightDecision:
        if not node.output_key:
            return PreflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self._id)
        started_at = float(node.config.get(_STARTED_AT, 0.0))
        await self._coordinator.register(
            AgentWriteSet(
                agent_id=node.ref_id,
                items=(WriteItem(path=node.output_key),),
                started_at=started_at,
            )
        )
        advisory = await self._coordinator.advise_against_cohort(node.ref_id)
        if advisory.steer == node.ref_id:
            return PreflightDecision(
                kind=DecisionKind.REJECT,
                interceptor_id=self._id,
                reason=(
                    f"collision: {node.ref_id} steered off {node.output_key!r}; "
                    f"{advisory.hold} holds right-of-way (risk={advisory.risk:.2f})"
                ),
            )
        return PreflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self._id)


class _Goal(BaseModel):
    pass


class _Out(BaseModel):
    who: str


class HolderAgent(Agent[_Goal, _Out]):
    @property
    def id(self) -> AgentID:
        return AgentID("holder")

    @property
    def description(self) -> str:
        return "holder agent"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[_Out]:
        return AgentResult.ok(output=_Out(who="holder"), state=AgentState())


class SteerAgent(Agent[_Goal, _Out]):
    @property
    def id(self) -> AgentID:
        return AgentID("steer")

    @property
    def description(self) -> str:
        return "steer agent"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _Goal, context: AgentContext) -> AgentResult[_Out]:
        return AgentResult.ok(output=_Out(who="steer"), state=AgentState())


def _result_for(run: ExecutionResult, node_id: str) -> NodeResult:
    return next(r for r in run.node_results if r.node_id == NodeID(node_id))


def _is_pre_rejected(result: NodeResult) -> bool:
    interceptors = result.metadata.get("interceptors", {})
    return (
        result.success is False
        and interceptors.get("gate_rejected") is True
        and interceptors.get("phase") == "pre"
    )


async def _run_collision_dag(*, holder_started_at: float, steer_started_at: float) -> ExecutionResult:
    """Run a PARALLEL DAG: two agents both write output_key 'decision'; collision steers one."""
    registry = AgentRegistry()
    registry.register_agent(agent_instance=HolderAgent(), goal_type=_Goal)
    registry.register_agent(agent_instance=SteerAgent(), goal_type=_Goal)

    coordinator = create_collision_coordinator(cohort_size=2)
    pipeline = InterceptorPipeline(interceptors=(CollisionGuardInterceptor(coordinator=coordinator),))

    dag = DAG(name="collision-parallel", description="two agents race for one output_key")
    dag = dag.add_node(
        node=Node.parallel(
            id="fan", name="Fan out", parallel_nodes=["holder_node", "steer_node"], output_key="fan_out"
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="holder_node",
            name="Holder",
            agent_id="holder",
            output_key="decision",
            config={_STARTED_AT: holder_started_at},
        )
    )
    dag = dag.add_node(
        node=Node.agent(
            id="steer_node",
            name="Steer",
            agent_id="steer",
            output_key="decision",
            config={_STARTED_AT: steer_started_at},
        )
    )

    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(interceptor_pipeline=pipeline),
    )
    return await executor.run(dag=dag)


class TestCollisionThroughRealExecutor:
    @pytest.mark.asyncio
    async def test_steered_parallel_agent_is_pre_rejected(self) -> None:
        """Holder (earlier start) runs; steer (later start) is PRE-rejected — its agent never runs."""
        run = await _run_collision_dag(holder_started_at=1.0, steer_started_at=2.0)
        assert run.status is RunStatus.COMPLETED  # parallel node tolerates a steered child

        holder = _result_for(run, "holder_node")
        steer = _result_for(run, "steer_node")

        assert holder.success is True
        assert holder.output is not None
        assert _is_pre_rejected(steer)
        assert "right-of-way" in (steer.error or "")

    @pytest.mark.asyncio
    async def test_exactly_one_runs_one_steered(self) -> None:
        """Exactly one of the two colliding agents runs; the other is steered (never both, never neither)."""
        run = await _run_collision_dag(holder_started_at=1.0, steer_started_at=2.0)
        holder = _result_for(run, "holder_node")
        steer = _result_for(run, "steer_node")
        ran = [r for r in (holder, steer) if r.success]
        rejected = [r for r in (holder, steer) if _is_pre_rejected(r)]
        assert len(ran) == 1
        assert len(rejected) == 1

    @pytest.mark.asyncio
    async def test_resolution_is_deterministic_by_priority(self) -> None:
        """Swapping which node started earlier swaps who holds — resolution follows priority, not luck."""
        run_a = await _run_collision_dag(holder_started_at=1.0, steer_started_at=2.0)
        # Now make 'steer' the earlier starter → it should hold, 'holder' gets rejected.
        run_b = await _run_collision_dag(holder_started_at=5.0, steer_started_at=1.0)

        assert _result_for(run_a, "holder_node").success is True
        assert _is_pre_rejected(_result_for(run_a, "steer_node"))

        assert _result_for(run_b, "steer_node").success is True
        assert _is_pre_rejected(_result_for(run_b, "holder_node"))

    @pytest.mark.asyncio
    async def test_no_interceptor_means_both_run(self) -> None:
        """Control: without the collision guard, both colliding agents run (proves the guard is the cause)."""
        registry = AgentRegistry()
        registry.register_agent(agent_instance=HolderAgent(), goal_type=_Goal)
        registry.register_agent(agent_instance=SteerAgent(), goal_type=_Goal)
        dag = DAG(name="no-guard", description="both run")
        dag = dag.add_node(
            node=Node.parallel(
                id="fan", name="Fan", parallel_nodes=["holder_node", "steer_node"], output_key="fan_out"
            )
        )
        dag = dag.add_node(
            node=Node.agent(id="holder_node", name="H", agent_id="holder", output_key="decision")
        )
        dag = dag.add_node(
            node=Node.agent(id="steer_node", name="S", agent_id="steer", output_key="decision")
        )
        executor = create_executor(agent_registry=registry)
        run = await executor.run(dag=dag)
        assert _result_for(run, "holder_node").success is True
        assert _result_for(run, "steer_node").success is True
