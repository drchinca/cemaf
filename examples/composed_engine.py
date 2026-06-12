"""CEMAF as ONE engine — not a feature menu.

This is the canonical "whole engine" demo. A single DAG run threads the maximum
set of real subsystems through one composition root:

    council (agents deliberate + vote a plan)
        │  verdict steers the DAG via a conditional edge
        ▼
    auction (capability-based agent selection)  →  agent executes
        │  every node emits events
        ▼
    online-eval pipeline  →  blueprint harvester (distils a reusable blueprint)

All wired through `create_executor(services=RuntimeServices(...))`. No mocks.

Run:
    uv run python examples/composed_engine.py

The point: these are not 22 features. They are stations one engine loop passes
through. Where a station does NOT yet thread automatically (compiled-context to
the prompt; a guardian POST stage), see tests/integration/test_composed_engine.py
`TestSeamGaps` — those are the interceptor-pipeline spine (SPEC-01) still to come.
"""

import asyncio

from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.blueprint import (
    BlueprintLibrary,
    InMemoryWritableBlueprintSource,
    create_blueprint_harvester,
)
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.types import AgentID, NodeID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.types import Opinion
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.events.bus import InMemoryEventBus
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.dag import (
    DAG,
    Condition,
    ConditionOperator,
    Edge,
    EdgeCondition,
    Node,
)
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices


class _PlanGoal(BaseModel):
    objective: str = "decide a plan"


class Planner:
    """A council member (full agent + can deliberate)."""

    def __init__(self, member_id: str, vote: str) -> None:
        self._id, self._vote = AgentID(member_id), vote

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "votes on the plan"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _PlanGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._vote, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
        return Opinion(member_id=self._id, choice=self._vote)


class _WriteGoal(BaseModel):
    objective: str = "write"


class Writer:
    """A WRITE-capable agent chosen by auction."""

    def __init__(self, agent_id: str, load: float) -> None:
        self._id, self._load = AgentID(agent_id), load

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "writes the announcement"

    @property
    def skills(self) -> tuple[()]:
        return ()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.WRITE})

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: _WriteGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(
            output="A thorough launch announcement. " * 5,
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.07, "tokens_total": 700, "overall_score": 0.95},
        )


async def main() -> None:
    event_bus = InMemoryEventBus()

    registry = AgentRegistry()
    for name, vote in (("p1", "ship"), ("p2", "ship"), ("p3", "hold")):
        registry.register_instance(item=Planner(name, vote))
    registry.register_agent(
        agent_instance=Writer("WriterBusy", load=0.9), goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    registry.register_agent(
        agent_instance=Writer("WriterIdle", load=0.1), goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )

    online = OnlineEvalPipeline(
        bindings=(
            NodeEvalBinding(
                node_pattern="write",
                evaluators=(LengthEvaluator(min_length=100),),
                mode=EvalMode.OBSERVE,
            ),
        ),
        event_bus=event_bus,
    )
    harvest_source = InMemoryWritableBlueprintSource()
    create_blueprint_harvester(
        writable_source=harvest_source,
        event_bus=event_bus,
        library=BlueprintLibrary(),
        threshold=0.8,
    )

    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            event_bus=event_bus,
            budget_guard=BudgetGuard(max_cost_usd=5.0),
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=50_000, reserved_for_output=4_000),
            agent_selector=DefaultAgentSelector(),
            council_aggregator=DefaultVoteAggregator(),
            online_eval_pipeline=online,
        ),
    )

    dag = DAG(
        name="composed-engine",
        nodes=(
            Node.council(
                id="plan", name="plan", members=("p1", "p2", "p3"),
                options=("ship", "hold"), output_key="plan_verdict",
            ),
            Node.auction(
                id="write", name="write",
                capability=Capability.WRITE.value, output_key="article",
            ),
        ),
        edges=(
            Edge(
                source=NodeID("plan"), target=NodeID("write"),
                condition=EdgeCondition.JSON_RULE,
                condition_rule=Condition(
                    field="plan_verdict", operator=ConditionOperator.EQUALS, value="ship"
                ),
            ),
        ),
        entry_node=NodeID("plan"),
    )

    run = await executor.run(dag=dag)
    await online.flush()

    results = {str(r.node_id): r for r in run.node_results}
    print(f"run status        : {run.status.value}")
    print(f"council verdict   : {results['plan'].output}  (tally {results['plan'].metadata['council']['tally']})")
    print(f"auction winner    : {results['write'].metadata['selection']['agent_id']}")
    print(f"online evals run  : {len(online._results)}")
    print(f"blueprints harvested: {len(list(harvest_source.load()))}")
    print(f"accumulated cost  : ${run.node_results and sum(float(r.metadata.get('cost_estimate_usd', 0)) for r in run.node_results):.2f}")


if __name__ == "__main__":
    asyncio.run(main())
