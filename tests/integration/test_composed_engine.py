"""Composed-engine evidence: how many subsystems actually thread through ONE run.

CEMAF has ~22 optional subsystems. The thesis under test is that they form a
single engine, not a feature menu. This test wires the MAXIMUM real set through
one multi-station DAG and splits its assertions in two:

  TestEngineConnects  — seams that genuinely thread end-to-end today.
  TestBoundaryHonesty — proves protocol-boundary delivery and names the limits
                        that remain outside the base executor.

No mocks — real EventBus, BudgetGuard, compiler, memory, council, auction,
online-eval pipeline, and blueprint harvester.

The DAG (one run, three stations):

    plan (council: members vote a plan)  →  write (auction: capability=WRITE)

so a single run exercises: council deliberation → DAG steering via verdict →
auction selection → agent execution → events → online eval → harvest.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.blueprint import (
    BlueprintLibrary,
    InMemoryWritableBlueprintSource,
    create_blueprint_harvester,
)
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.enums import RunStatus
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

# --- Real agents (LLM-less, deterministic) --------------------------------


class _PlanGoal(BaseModel):
    objective: str = "decide a plan"


class _Planner:
    """A council member that votes a plan AND is a full Agent."""

    def __init__(self, member_id: str, vote: str) -> None:
        self._id = AgentID(member_id)
        self._vote = vote

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "plans"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _PlanGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._vote, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
        return Opinion(member_id=self._id, choice=self._vote)


class _WriteGoal(BaseModel):
    objective: str = "write"


class _Writer:
    """A WRITE-capable agent selected by auction; emits a long article (passes eval)."""

    def __init__(self, agent_id: str, load: float) -> None:
        self._id = AgentID(agent_id)
        self._load = load
        self.seen_contexts: list[AgentContext] = []

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "writes"

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
        self.seen_contexts.append(context)
        article = "A thorough launch announcement. " * 5  # > 100 chars → passes LengthEvaluator
        return AgentResult.ok(
            output=article,
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.07, "tokens_total": 700, "overall_score": 0.95},
        )


def _build_engine() -> tuple[RuntimeServices, AgentRegistry, InMemoryEventBus, dict[str, object]]:
    """Wire the maximum real subsystem set through the base composition root."""
    event_bus = InMemoryEventBus()

    registry = AgentRegistry()
    # council members
    registry.register_instance(item=_Planner("p1", "ship"))
    registry.register_instance(item=_Planner("p2", "ship"))
    registry.register_instance(item=_Planner("p3", "hold"))
    # auction candidates (both WRITE; idle should win)
    writer_busy = _Writer("WriterBusy", load=0.9)
    writer_idle = _Writer("WriterIdle", load=0.1)
    registry.register_agent(
        agent_instance=writer_busy,
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    registry.register_agent(
        agent_instance=writer_idle,
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )

    # online eval pipeline (subscribes TASK_COMPLETED → emits EVAL_COMPLETED)
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

    # blueprint harvester (subscribes EVAL_COMPLETED → distills blueprint)
    harvest_source = InMemoryWritableBlueprintSource()
    harvest_library = BlueprintLibrary()
    harvester = create_blueprint_harvester(
        writable_source=harvest_source,
        event_bus=event_bus,
        library=harvest_library,
        threshold=0.8,
    )

    services = RuntimeServices(
        event_bus=event_bus,
        budget_guard=BudgetGuard(max_cost_usd=5.0),
        context_compiler=PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=3.5)),
        token_budget=TokenBudget(max_tokens=50_000, reserved_for_output=4_000),
        agent_selector=DefaultAgentSelector(),
        council_aggregator=DefaultVoteAggregator(),
        online_eval_pipeline=online,
    )
    artifacts = {
        "online": online,
        "harvest_source": harvest_source,
        "harvest_library": harvest_library,
        "harvester": harvester,
        "writer_busy": writer_busy,
        "writer_idle": writer_idle,
    }
    return services, registry, event_bus, artifacts


def _engine_dag() -> DAG:
    plan = Node.council(
        id="plan",
        name="plan",
        members=("p1", "p2", "p3"),
        options=("ship", "hold"),
        output_key="plan_verdict",
    )
    write = Node.auction(
        id="write",
        name="write",
        capability=Capability.WRITE.value,
        output_key="article",
    )
    return DAG(
        name="composed-engine",
        nodes=(plan, write),
        edges=(
            Edge(
                source=NodeID("plan"),
                target=NodeID("write"),
                condition=EdgeCondition.JSON_RULE,
                condition_rule=Condition(
                    field="plan_verdict", operator=ConditionOperator.EQUALS, value="ship"
                ),
            ),
        ),
        entry_node=NodeID("plan"),
    )


class TestEngineConnects:
    """Seams that genuinely thread end-to-end through one run today."""

    @pytest.mark.asyncio
    async def test_council_to_auction_to_agent_one_run(self) -> None:
        from cemaf.bootstrap import create_executor

        services, registry, _bus, artifacts = _build_engine()
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        run = await executor.run(dag=_engine_dag())
        await artifacts["online"].flush()  # type: ignore[attr-defined]

        # 1. The run completed across both stations.
        assert run.status == RunStatus.COMPLETED
        results = {str(r.node_id): r for r in run.node_results}

        # 2. STATION 1 — council deliberated and decided "ship" (2-1 majority).
        assert results["plan"].output == "ship"
        assert results["plan"].metadata["council"]["tally"] == {"ship": 2.0, "hold": 1.0}

        # 3. Council verdict STEERED the DAG: the gated write node ran because
        #    plan_verdict == "ship" opened the JSON_RULE edge.
        assert "write" in results
        assert results["write"].success

        # 4. STATION 2 — auction selected the low-load writer.
        assert results["write"].metadata["selection"]["agent_id"] == "WriterIdle"

        # 5. BudgetGuard accumulated real cost across the run.
        assert services.budget_guard.accumulated_cost_usd > 0  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_event_chain_executor_to_online_eval_to_harvest(self) -> None:
        """Executor TASK_COMPLETED → OnlineEval EVAL_COMPLETED → harvester distills a blueprint."""
        from cemaf.bootstrap import create_executor

        services, registry, _bus, artifacts = _build_engine()
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )

        await executor.run(dag=_engine_dag())
        await artifacts["online"].flush()  # type: ignore[attr-defined]

        # The online eval pipeline ran (it recorded results from TASK_COMPLETED).
        online = artifacts["online"]
        assert online._results, "online eval pipeline should have evaluated the write node"  # type: ignore[attr-defined]

        # And the harvester, three subsystems downstream, distilled a blueprint from
        # the high-scoring run — proving executor → online-eval → harvest threads
        # through a single run via the EventBus, with zero direct coupling.
        harvested = list(artifacts["harvest_source"].load())  # type: ignore[attr-defined]
        assert harvested, "harvester should have distilled a blueprint from the passing run"


class TestBoundaryHonesty:
    """Positive seams and remaining limits stated at their actual boundary."""

    @pytest.mark.asyncio
    async def test_compiled_context_reaches_selected_agent(self) -> None:
        """The compiler projection is delivered through AgentContext artifacts.

        CEMAF cannot force a custom agent to use that projection in its private
        LLM prompt, but the execution root does make the bounded context available
        at the protocol boundary.
        """
        from cemaf.bootstrap import create_executor

        services, registry, _bus, artifacts = _build_engine()
        executor = create_executor(
            agent_registry=registry,
            config=ExecutorConfig(enable_events=True),
            services=services,
        )
        run = await executor.run(dag=_engine_dag())

        write = {str(r.node_id): r for r in run.node_results}["write"]
        assert write.output.startswith("A thorough launch announcement.")
        selected_writer = artifacts["writer_idle"]
        assert selected_writer.seen_contexts  # type: ignore[attr-defined]
        assert "compiled_context" in selected_writer.seen_contexts[0].artifacts  # type: ignore[attr-defined]
        # Honest remaining seam: custom agents own their actual LLM invocation,
        # so prompt consumption/token telemetry cannot be enforced structurally.
        assert "compiled_context_tokens" not in write.metadata

    @pytest.mark.asyncio
    async def test_gap_harvest_wired_outside_runtime_services(self) -> None:
        """GAP: the harvest flywheel is wired by subscribing to the EventBus directly,
        NOT through RuntimeServices like every other subsystem. The composition root
        holds no `blueprint_harvester` field — it is a separate wiring path."""
        fields = RuntimeServices().__dataclass_fields__
        assert "blueprint_harvester" not in fields  # not a first-class engine seam yet
        # (it works — but the caller must wire it out-of-band, unlike council/auction/evals)

    @pytest.mark.asyncio
    async def test_interceptor_spine_now_exists_guardian_mesh_still_pending(self) -> None:
        """PROGRESS: the interceptor spine (SPEC-01a) now exists — every AGENT node
        passes through a PRE→execute→POST chain, and a POST gate genuinely blocks
        (see tests/integration/test_interceptor_gate.py). The guardian MESH (SPEC-05 —
        the composed set of cite-or-fail / moderation / calibration guardians as POST
        interceptors) is the remaining gap."""
        import importlib.util

        # Spine: closed.
        assert importlib.util.find_spec("cemaf.interceptors") is not None
        assert "interceptor_pipeline" in RuntimeServices().__dataclass_fields__
        # Guardian mesh: still pending (SPEC-05).
        assert importlib.util.find_spec("cemaf.guardian") is None
