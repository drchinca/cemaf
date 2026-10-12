"""Real-DAG proof of SPEC-18 phase 1b — identity admission wired into actual
dispatch (§2.1), through `create_executor`/`DAGExecutor.run()`, no mocks.

`test_agent_identity_substrate.py` (phase 1a) proves the directory's own
contracts under concurrent load. `test_resolver_chain.py` and
`test_agent_auction.py` prove admission on the static/auction paths. This
file is the phase-1b companion covering the two surfaces those don't:
parallel pre-dispatch registration and the recovery-loop's per-attempt
identity transitions — plus the automatic run-scoped dispose.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.factories import create_agent_directory
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID, TaskID
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.interceptors import GateEvalInterceptor, GateFailureMode, create_interceptor_pipeline
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.services import RuntimeServices


class _WorkerGoal(BaseModel):
    pass


class _Worker:
    """Records, from inside its own run(), how many peers the directory
    already shows for this task — proving pre-dispatch registration ran
    before any sibling started, not just that each node admits itself.
    """

    def __init__(self, *, directory, observed: list[int], seen_instance_ids: list[UUID | None]) -> None:
        self._directory = directory
        self._observed = observed
        self._seen_instance_ids = seen_instance_ids

    @property
    def id(self) -> AgentID:
        return AgentID("Worker")

    @property
    def description(self) -> str:
        return "worker"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _WorkerGoal, context: AgentContext) -> AgentResult[str]:
        task_id = TaskID(str(context.run_id))
        peers = await self._directory.list(task_id=task_id)
        self._observed.append(len(peers))
        self._seen_instance_ids.append(context.instance_id)
        return AgentResult.ok(output="done", state=AgentState())


@pytest.mark.asyncio
async def test_parallel_peers_are_preadmitted_with_distinct_identity_before_dispatch() -> None:
    """Three PARALLEL sub-nodes resolving to the same registered agent
    definition each see all three peers already admitted the instant they
    start running — proof `_preadmit_parallel_peers` ran before
    `asyncio.gather`, not that each node merely admits itself lazily.
    """
    observed: list[int] = []
    seen_instance_ids: list[UUID | None] = []
    directory = create_agent_directory()
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=_Worker(directory=directory, observed=observed, seen_instance_ids=seen_instance_ids),
        goal_type=_WorkerGoal,
    )
    executor = create_executor(agent_registry=registry, services=RuntimeServices(agent_directory=directory))

    sub_nodes = tuple(Node.agent(id=f"w{i}", name=f"w{i}", agent_id="Worker") for i in range(3))
    dag = DAG(
        name="parallel-identity",
        nodes=(*sub_nodes, Node.parallel("fanout", "fanout", [n.id for n in sub_nodes])),
        # Edges from the PARALLEL node into its own sub-nodes put "fanout"
        # first in topological order, so its fan-out is what actually runs
        # each sub-node (and marks it completed) — without these, the
        # sub-nodes have in_degree 0 and the main loop would ALSO schedule
        # them standalone, double-executing each one.
        edges=tuple(Edge(source=NodeID("fanout"), target=n.id) for n in sub_nodes),
        entry_node=NodeID("fanout"),
    )
    run = await executor.run(dag=dag)

    assert run.status is RunStatus.COMPLETED
    assert len(observed) == 3
    assert observed == [3, 3, 3]  # every worker saw all 3 peers already admitted
    assert len(seen_instance_ids) == 3
    assert all(instance_id is not None for instance_id in seen_instance_ids)
    assert len(set(seen_instance_ids)) == 3  # each spawn distinguishable

    # dispose() fired automatically at run end.
    assert await directory.list(task_id=TaskID(str(run.run_id))) == ()


class _RecoveringWorker:
    """Emits a short draft on the first attempt (triggers RECOVER via the
    length gate), then a passing one — recording, from real directory state
    inspected mid-run, the (instance_id, attempt_id) pair the directory
    shows on each attempt.
    """

    def __init__(self, *, directory) -> None:
        self._directory = directory
        self.attempts: list[tuple[UUID | None, str | None]] = []

    @property
    def id(self) -> AgentID:
        return AgentID("Recoverer")

    @property
    def description(self) -> str:
        return "recoverer"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _WorkerGoal, context: AgentContext) -> AgentResult[str]:
        task_id = TaskID(str(context.run_id))
        instance = (
            await self._directory.get(context.instance_id, task_id=task_id)
            if context.instance_id is not None
            else None
        )
        self.attempts.append((context.instance_id, instance.attempt_id if instance is not None else None))
        if len(self.attempts) == 1:
            return AgentResult.ok(output="short", state=AgentState())
        return AgentResult.ok(output="x" * 200, state=AgentState())


@pytest.mark.asyncio
async def test_recover_retry_keeps_identity_but_gets_new_attempt_id() -> None:
    """A POST RECOVER retry (SPEC-01a) is the same logical AgentInstance
    (SPEC-18 §2.1) across both attempts, with a distinct attempt_id per
    attempt — proving retries retain identity rather than re-admitting.
    """
    directory = create_agent_directory()
    worker = _RecoveringWorker(directory=directory)
    registry = AgentRegistry()
    registry.register_agent(agent_instance=worker, goal_type=_WorkerGoal)
    pipeline = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=100),),
                node_pattern="recover",
                threshold=0.5,
                on_failure=GateFailureMode.RECOVER,
            ),
        )
    )
    executor = create_executor(
        agent_registry=registry,
        services=RuntimeServices(
            agent_directory=directory, interceptor_pipeline=pipeline, max_recovery_attempts=2
        ),
    )
    dag = DAG(
        name="recover-identity",
        nodes=(Node.agent(id="recover", name="recover", agent_id="Recoverer"),),
        edges=(),
        entry_node=NodeID("recover"),
    )
    run = await executor.run(dag=dag)

    assert run.status is RunStatus.COMPLETED
    assert len(worker.attempts) == 2
    (first_id, first_attempt), (second_id, second_attempt) = worker.attempts
    assert first_id is not None and second_id is not None
    assert first_id == second_id  # same logical instance across the retry
    assert first_attempt is not None and second_attempt is not None
    assert first_attempt != second_attempt  # distinct attempt per try

    # dispose() fired automatically at run end.
    assert await directory.list(task_id=TaskID(str(run.run_id))) == ()
