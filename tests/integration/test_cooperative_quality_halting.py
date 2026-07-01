"""
Integration Test: Cooperative Quality Halting inside DAG Loops.

Validates the complex "flesh" of CEMAF's runtime quality safety:
1. Running a DAG containing a LOOP node.
2. Generating outputs with progressively degrading quality.
3. An interceptor evaluating quality and publishing EVAL_COMPLETED events.
4. QualityPolice performing live linear trend regression analysis.
5. QualityPolice triggering a Predictive Halt BEFORE hard thresholds are crossed.
6. LOOP node cooperatively polling the halt signal and gracefully aborting execution mid-flight.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from cemaf.agents.base import Agent, AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID
from cemaf.evals.police import AlertLevel, QualityPolice, QualityPoliceConfig
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event, EventType
from cemaf.interceptors import (
    DecisionKind,
    PostflightDecision,
    PostInterceptor,
    create_interceptor_pipeline,
)
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices

# ============================================================================
# Simulated Components
# ============================================================================


class DegradingGoal(BaseModel):
    objective: str = "Generate compliant text"


class DegradingWriterAgent(Agent[DegradingGoal, str]):
    """An agent whose output quality progressively degrades on every iteration.

    1st run: 100 characters (score 1.0)
    2nd run: 80 characters (score 0.8)
    3rd run: 60 characters (score 0.6)
    4th run: 40 characters (score 0.4)
    5th run: 20 characters (score 0.2)
    """

    def __init__(self) -> None:
        self.iterations = 0

    @property
    def id(self) -> AgentID:
        return AgentID("degrading_writer")

    @property
    def description(self) -> str:
        return "Writer that gets progressively worse"

    @property
    def skills(self) -> tuple:
        return ()

    async def run(self, goal: DegradingGoal, context: AgentContext) -> AgentResult[str]:
        self.iterations += 1
        state = AgentState()

        # Output lengths: 100, 80, 60, 40, 20
        length = max(10, 120 - (self.iterations * 20))
        output = "x" * length

        return AgentResult.ok(output=output, state=state)


class OnlineEvalInterceptor(PostInterceptor):
    """Postflight interceptor that evaluates node output and publishes EVAL_COMPLETED.

    This ensures that even sub-nodes executing inside a LOOP node (which bypasses the
    top-level executor's _execute_nodes complete event) have their quality scores
    synchronously published and tracked by the QualityPolice.
    """

    def __init__(self, event_bus: InMemoryEventBus) -> None:
        self._bus = event_bus

    @property
    def interceptor_id(self) -> str:
        return "online_eval"

    async def post(self, *, node: Node, context: AgentContext, result: NodeResult) -> PostflightDecision:
        # Simple length-based quality evaluation
        length = len(str(result.output))
        score = min(1.0, length / 100.0)

        # Publish EVAL_COMPLETED directly to the bus synchronously
        await self._bus.publish(
            Event.create(
                type=EventType.EVAL_COMPLETED,
                payload={
                    "node_id": str(node.id),
                    "overall_score": score,
                    "overall_passed": score >= 0.6,
                },
                source="online_eval_interceptor",
            )
        )
        return PostflightDecision(kind=DecisionKind.ACCEPT, interceptor_id=self.interceptor_id)


# ============================================================================
# Integration Test Case
# ============================================================================


@pytest.mark.asyncio
async def test_quality_police_predictive_halt_gracefully_stops_loop() -> None:
    """End-to-end integration:

    - Run a loop with max_iterations=10.
    - Quality degrades linearly on every iteration.
    - OnlineEvalInterceptor publishes EVAL_COMPLETED synchronously on each completed task.
    - QualityPolice performs trend-regression analysis on those scores.
    - On iteration 4, linear trend projects crossing the halt_threshold (0.3) within 5 steps.
    - QualityPolice raises predictive AlertLevel.HALT.
    - LOOP handler cooperatively polls `should_halt()` and aborts mid-flight.
    - Entire DAG halts with 'FAILED' status, preserving budget and preventing wasted runs.
    """
    event_bus = InMemoryEventBus()

    # 1. Setup QualityPolice (with tight limits for deterministic halting)
    police_config = QualityPoliceConfig(
        window_size=10,
        warn_threshold=0.8,
        critical_threshold=0.6,
        halt_threshold=0.3,
        predictive_halt_enabled=True,
        predictive_halt_horizon=5,
        min_samples_for_trend=4,  # Need at least 4 samples to calculate regression
    )
    police = QualityPolice(config=police_config)
    police.subscribe(event_bus=event_bus)

    # 2. Setup Agent Registry & Interceptor pipeline
    agent_instance = DegradingWriterAgent()
    registry = AgentRegistry()
    registry.register_agent(agent_instance=agent_instance, goal_type=DegradingGoal)

    pipeline = create_interceptor_pipeline(interceptors=(OnlineEvalInterceptor(event_bus=event_bus),))

    # 3. Setup RuntimeServices
    services = RuntimeServices(event_bus=event_bus, quality_police=police, interceptor_pipeline=pipeline)

    executor = create_executor(
        agent_registry=registry, services=services, config=ExecutorConfig(enable_events=True)
    )

    # 4. Construct DAG with a LOOP node
    # loop_node -> executes writer_node in each iteration
    loop_node = Node.loop(
        id="loop_node",
        name="writer_loop",
        body_node_ids=("writer_node",),
        max_iterations=10,
    )

    writer_node = Node.agent(
        id="writer_node", name="writer", agent_id="degrading_writer", output_key="draft_output"
    )

    dag = DAG(name="predictive_halt_dag")
    # Add nodes (loop added first makes it entry node)
    dag = dag.add_node(loop_node).add_node(writer_node)

    events_received = []
    event_bus.subscribe_all(lambda e: events_received.append(e))

    # 5. Execute DAG!
    result = await executor.run(dag)

    # 6. Verify Cooperative Halting & Emergent Behavior Invariants
    print("\n--- EVENTS RECEIVED ---")
    for e in events_received:
        print(f"EVENT: {e.type} | PAYLOAD: {e.payload}")
    print("-----------------------\n")

    # Invariant 1: The DAG execution halted with a failure status due to quality degradation
    assert result.success is False
    assert result.status is RunStatus.FAILED
    assert "Quality degradation" in str(result.error)

    # Invariant 2: The LOOP stopped cooperatively before completing max_iterations
    # It should have halted after the 3rd sample (iteration 3) because of a combination of
    # steep linear trend regression and anomaly detection (dropping 0.3 below rolling mean).
    assert agent_instance.iterations == 3
    assert police.should_halt() is True

    # Invariant 3: The alert level contains a predictive halt
    alerts = police.alerts
    assert len(alerts) >= 1
    halt_alerts = [a for a in alerts if a.level == AlertLevel.HALT]
    assert len(halt_alerts) == 1
    assert "predictive" in halt_alerts[0].message.lower()

    # Invariant 4: No further iterations were run, saving budget
    # The draft output is preserved up to the last successful completed run
    assert "draft_output" in result.final_context.data
